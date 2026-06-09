import re
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


def fetch_reddit_posts() -> dict[str, list[dict]]:
    # Reddit's JSON API blocks data center IPs (GitHub Actions gets HTTP 403).
    # Their RSS feeds go through feedparser and are not blocked.
    results = {}
    for subreddit in SUBREDDITS:
        print(f"  Fetching Reddit: r/{subreddit}...")
        try:
            rss_url = f"https://www.reddit.com/r/{subreddit}/top.rss?t=week&limit={MAX_ITEMS_PER_SOURCE}"
            feed = feedparser.parse(rss_url)
            if feed.bozo and not feed.entries:
                raise ValueError(f"feed parse error: {feed.bozo_exception}")
            # top.rss?t=week is already ordered best-first, so feed position IS
            # the top-of-week rank — pass it through as an engagement signal.
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
    url = (
        "https://hn.algolia.com/api/v1/search"
        f"?tags=story&query={HN_QUERY}"
        f"&numericFilters=created_at_i>{cutoff_ts},points>{HN_MIN_POINTS}"
        "&hitsPerPage=50"
    )
    try:
        resp = requests.get(url, timeout=20, headers={"User-Agent": "alpha-ai-newsletter"})
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
