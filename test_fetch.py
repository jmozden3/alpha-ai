import sys, io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

from sources import fetch_rss_feeds, fetch_reddit_posts


def print_results(label: str, results: dict):
    print(f"\n{'='*50}")
    print(f"{label}")
    print(f"{'='*50}")
    for source, items in results.items():
        count = len(items)
        first_title = items[0]["title"] if items else "(no items)"
        print(f"\n  {source} — {count} item(s)")
        print(f"    First: {first_title}")


if __name__ == "__main__":
    print("Fetching RSS feeds...")
    rss = fetch_rss_feeds()
    print_results("RSS RESULTS", rss)

    print("\nFetching Reddit posts...")
    reddit = fetch_reddit_posts()
    print_results("REDDIT RESULTS", reddit)
