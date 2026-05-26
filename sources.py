import re
from datetime import datetime, timezone, timedelta

import feedparser

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
            items = []
            for entry in feed.entries[:MAX_ITEMS_PER_SOURCE]:
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
                })
            results[f"r/{subreddit}"] = items
            print(f"    -> {len(items)} items")
        except Exception as e:
            error_msg = str(e)
            print(f"    -> failed: {error_msg}")
            results[f"r/{subreddit}"] = {"error": error_msg}
    return results
