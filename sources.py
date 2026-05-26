import re
from datetime import datetime, timezone, timedelta

import feedparser
import requests

from config import RSS_FEEDS, SUBREDDITS, MAX_ITEMS_PER_SOURCE, MAX_CHARS_PER_ITEM, DAYS_LOOKBACK

CUTOFF = datetime.now(timezone.utc) - timedelta(days=DAYS_LOOKBACK)


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
            items = []
            for entry in feed.entries[:MAX_ITEMS_PER_SOURCE]:
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
    results = {}
    headers = {"User-Agent": "alpha-ai-newsletter/1.0"}
    for subreddit in SUBREDDITS:
        print(f"  Fetching Reddit: r/{subreddit}...")
        try:
            url = f"https://www.reddit.com/r/{subreddit}/top.json"
            params = {"t": "week", "limit": MAX_ITEMS_PER_SOURCE}
            resp = requests.get(url, headers=headers, params=params, timeout=10)
            resp.raise_for_status()
            posts = resp.json()["data"]["children"]
            items = []
            for post in posts:
                d = post["data"]
                text = _strip_html(d.get("selftext", "").strip() or d["title"])[:MAX_CHARS_PER_ITEM]
                pub = datetime.fromtimestamp(d["created_utc"], tz=timezone.utc)
                items.append({
                    "title": d["title"],
                    "text": text,
                    "url": f"https://reddit.com{d['permalink']}",
                    "date": pub.strftime("%Y-%m-%d"),
                })
            results[f"r/{subreddit}"] = items
            print(f"    -> {len(items)} items")
        except Exception as e:
            print(f"    -> failed: {e}")
            results[f"r/{subreddit}"] = []
    return results
