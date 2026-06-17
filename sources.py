import os
import re
import time
from datetime import datetime, timezone, timedelta

import feedparser
import requests

from config import (
    RSS_FEEDS,
    SUBREDDITS,
    MAX_ITEMS_PER_SOURCE,
    MAX_CHARS_PER_ITEM,
    DAYS_LOOKBACK,
    HN_QUERY,
    HN_MIN_POINTS,
)


def _strip_html(text: str) -> str:
    text = re.sub(r"<[^>]+>", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def _entry_date(entry) -> datetime | None:
    for field in ("published_parsed", "updated_parsed"):
        t = getattr(entry, field, None)
        if t:
            return datetime(*t[:6], tzinfo=timezone.utc)
    return None


def fetch_rss_feeds() -> dict[str, list[dict]]:
    results = {}
    for source_name, url in RSS_FEEDS.items():
        print(f"  Fetching RSS: {source_name}...")
        try:
            feed = feedparser.parse(url)
            # Newest first, so the freshest items win the limited slots even when
            # a feed isn't strictly chronological. We deliberately do NOT hard-drop
            # older items: infrequent feeds (Import AI, The Gradient) would vanish
            # on quiet weeks, and seen_urls.json already prevents week-over-week repeats.
            entries = sorted(
                feed.entries,
                key=lambda e: _entry_date(e) or datetime.min.replace(tzinfo=timezone.utc),
                reverse=True,
            )
            items = []
            for entry in entries[:MAX_ITEMS_PER_SOURCE]:
                summary = getattr(entry, "summary", "") or ""
                if not summary and hasattr(entry, "content"):
                    summary = entry.content[0].get("value", "")
                text = _strip_html(summary)[:MAX_CHARS_PER_ITEM]
                pub = _entry_date(entry)
                items.append({
                    "title": entry.get("title", "").strip(),
                    "text": text,
                    "url": entry.get("link", ""),
                    "date": pub.strftime("%Y-%m-%d") if pub else "unknown",
                })
            results[source_name] = items
            print(f"    -> {len(items)} items")
        except Exception as e:
            print(f"    -> failed: {e}")
            results[source_name] = []
    return results


DEFAULT_REDDIT_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "alpha-ai-newsletter/1.0"
)


def _reddit_user_agent() -> str:
    # A real browser-style User-Agent gets blocked far less than the default
    # python-requests/feedparser one. Override REDDIT_USER_AGENT in .env to tweak.
    return os.environ.get("REDDIT_USER_AGENT", DEFAULT_REDDIT_UA)


def _reddit_int_env(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name, default))
    except (TypeError, ValueError):
        return default


def _fetch_reddit_rss(subreddit: str, headers: dict, max_retries: int) -> bytes:
    # Reddit serves public subreddit feeds at /top.rss. Empirically this endpoint
    # still answers 200 to a cold request (unlike /top.json, which 403s outright),
    # but it rate-limits rapid repeats with 429. So: retry 429 with exponential
    # backoff (honoring Retry-After when present), but treat 403/4xx/5xx as a hard
    # failure worth surfacing — no point retrying a block.
    url = f"https://www.reddit.com/r/{subreddit}/top.rss"
    params = {"t": "week", "limit": MAX_ITEMS_PER_SOURCE}
    backoff = _reddit_int_env("REDDIT_BACKOFF_SECONDS", 10)
    for attempt in range(1, max_retries + 1):
        resp = requests.get(url, params=params, headers=headers, timeout=20)
        if resp.status_code == 200:
            return resp.content
        if resp.status_code == 429 and attempt < max_retries:
            wait = _reddit_int_env_from_header(resp) or backoff
            print(f"    429 rate-limited; waiting {wait}s (attempt {attempt}/{max_retries})")
            time.sleep(wait)
            backoff *= 2
            continue
        resp.raise_for_status()
        raise RuntimeError(f"unexpected HTTP {resp.status_code}")
    raise RuntimeError(f"still rate-limited (429) after {max_retries} attempts")


def _reddit_int_env_from_header(resp) -> int:
    try:
        return int(float(resp.headers.get("Retry-After", 0)))
    except (TypeError, ValueError):
        return 0


def fetch_reddit_posts() -> dict[str, list[dict] | dict]:
    # Unauthenticated RSS feeds. Reddit shut down self-serve API-key creation
    # behind its "Responsible Builder Policy", and the /top.json endpoint is
    # 403-blocked, so RSS + a browser User-Agent is the working path. Requests are
    # spaced out (REDDIT_REQUEST_DELAY) to stay under the per-IP rate limit; bump
    # the delay if running on a throttled (e.g. data-center) IP.
    results = {}
    headers = {"User-Agent": _reddit_user_agent()}
    max_retries = _reddit_int_env("REDDIT_MAX_RETRIES", 4)
    delay = _reddit_int_env("REDDIT_REQUEST_DELAY", 5)

    for i, subreddit in enumerate(SUBREDDITS):
        print(f"  Fetching Reddit: r/{subreddit}...")
        if i > 0 and delay > 0:
            time.sleep(delay)  # space requests so we don't trip the rate limit
        try:
            content = _fetch_reddit_rss(subreddit, headers, max_retries)
            feed = feedparser.parse(content)
            if feed.bozo and not feed.entries:
                raise ValueError(f"feed parse error: {feed.bozo_exception}")
            # top.rss?t=week is ordered best-first, so feed position IS the
            # top-of-week rank — pass it through as an engagement signal.
            items = []
            for rank, entry in enumerate(feed.entries[:MAX_ITEMS_PER_SOURCE], start=1):
                summary = getattr(entry, "summary", "") or ""
                text = _strip_html(summary)[:MAX_CHARS_PER_ITEM]
                if not text:
                    text = entry.get("title", "")[:MAX_CHARS_PER_ITEM]
                pub = _entry_date(entry)
                items.append({
                    "title": entry.get("title", "").strip(),
                    "text": text,
                    "url": entry.get("link", ""),
                    "date": pub.strftime("%Y-%m-%d") if pub else "unknown",
                    "signal": f"#{rank} top post in r/{subreddit} this week",
                })
            results[f"r/{subreddit}"] = items
            print(f"    -> {len(items)} items")
        except Exception as e:
            error_msg = str(e)
            print(f"    -> failed: {error_msg}")
            results[f"r/{subreddit}"] = {"error": error_msg}
    return results


def fetch_hackernews() -> dict[str, list[dict] | dict]:
    # Hacker News via the Algolia API: unauthenticated and NOT IP-blocked on
    # GitHub Actions (unlike Reddit's JSON API). Every story carries points and
    # comment counts, giving Claude a real engagement signal for what's resonating.
    print("  Fetching Hacker News...")
    cutoff_ts = int((datetime.now(timezone.utc) - timedelta(days=DAYS_LOOKBACK)).timestamp())
    # numericFilters must be a list of separate conditions. Comma-joining them
    # into one value makes Algolia reject the request ("invalid numeric
    # attribute(points)") — passing a list serializes to repeated params, which
    # it accepts and applies as AND.
    params = {
        "tags": "story",
        "query": HN_QUERY,
        "numericFilters": [f"created_at_i>{cutoff_ts}", f"points>{HN_MIN_POINTS}"],
        "hitsPerPage": 50,
    }
    try:
        resp = requests.get(
            "https://hn.algolia.com/api/v1/search",
            params=params,
            timeout=20,
            headers={"User-Agent": "alpha-ai-newsletter"},
        )
        resp.raise_for_status()
        hits = resp.json().get("hits", [])
        hits.sort(key=lambda h: h.get("points", 0) or 0, reverse=True)
        items = []
        for hit in hits[:MAX_ITEMS_PER_SOURCE]:
            points = hit.get("points", 0) or 0
            comments = hit.get("num_comments", 0) or 0
            permalink = f"https://news.ycombinator.com/item?id={hit.get('objectID')}"
            text = _strip_html(hit.get("story_text") or hit.get("title", ""))[:MAX_CHARS_PER_ITEM]
            pub = (
                datetime.fromtimestamp(hit["created_at_i"], tz=timezone.utc)
                if hit.get("created_at_i")
                else None
            )
            items.append({
                "title": (hit.get("title") or "").strip(),
                "text": text,
                "url": hit.get("url") or permalink,  # link posts -> article; Ask/Show HN -> permalink
                "date": pub.strftime("%Y-%m-%d") if pub else "unknown",
                "signal": f"{points} points, {comments} comments on Hacker News",
            })
        print(f"    -> {len(items)} items")
        return {"Hacker News": items}
    except Exception as e:
        error_msg = str(e)
        print(f"    -> failed: {error_msg}")
        return {"Hacker News": {"error": error_msg}}
