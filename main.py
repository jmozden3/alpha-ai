import io
import json
import os
import sys
from datetime import date
from dotenv import load_dotenv

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

from costs import CostLog
from sources import fetch_rss_feeds, fetch_reddit_posts
from synthesize import synthesize

load_dotenv()

SEEN_URLS_PATH = "seen_urls.json"


def _load_seen_urls() -> set:
    if os.path.exists(SEEN_URLS_PATH):
        with open(SEEN_URLS_PATH, "r", encoding="utf-8") as f:
            return set(json.load(f))
    return set()


def _save_seen_urls(seen: set):
    with open(SEEN_URLS_PATH, "w", encoding="utf-8") as f:
        json.dump(sorted(seen), f, indent=2)


def _filter_seen(sources: dict, seen_urls: set) -> tuple[dict, int]:
    filtered = {}
    skipped = 0
    for source, items in sources.items():
        kept = [item for item in items if item.get("url") not in seen_urls]
        skipped += len(items) - len(kept)
        filtered[source] = kept
    return filtered, skipped


def _source_health_html(rss: dict, reddit: dict) -> str:
    rows = ""

    for name, items in rss.items():
        count = len(items)
        if count > 0:
            status = f"<span style='color:green;'>&#10003; {count} items</span>"
        else:
            status = "<span style='color:red;'>&#10007; No content — check feed</span>"
        rows += f"<tr><td>{name}</td><td>RSS</td><td>{status}</td></tr>"

    for name, items in reddit.items():
        count = len(items)
        if count > 0:
            status = f"<span style='color:green;'>&#10003; {count} items</span>"
        else:
            status = "<span style='color:orange;'>&#9888; No posts this week</span>"
        rows += f"<tr><td>{name}</td><td>Reddit</td><td>{status}</td></tr>"

    alive = sum(1 for v in {**rss, **reddit}.values() if v)
    total = len(rss) + len(reddit)

    return f"""
<h3>Source Health ({alive}/{total} active)</h3>
<table border='1' cellpadding='6' cellspacing='0'
       style='border-collapse:collapse;font-family:sans-serif;font-size:13px;'>
  <tr style='background:#f0f0f0;'>
    <th>Source</th><th>Type</th><th>Status</th>
  </tr>
  {rows}
</table>"""


def main():
    print("=== Alpha AI Newsletter Pipeline ===\n")
    cost_log = CostLog()

    print("Fetching RSS feeds...")
    rss = fetch_rss_feeds()

    print("\nFetching Reddit posts...")
    reddit = fetch_reddit_posts()

    sources = {**rss, **reddit}

    # Deduplicate against previously seen URLs
    seen_urls = _load_seen_urls()
    all_urls = {item["url"] for items in sources.values() for item in items if item.get("url")}
    sources_filtered, skipped = _filter_seen(sources, seen_urls)
    total_new = sum(len(v) for v in sources_filtered.values() if v)
    total_all = sum(len(v) for v in sources.values() if v)

    # Safety valve: if filtering removed more than 80% of content, ignore it.
    # This prevents an empty run when the pipeline is triggered twice in one week
    # (e.g. a local test followed by the scheduled Action).
    if total_new < total_all * 0.2:
        print(f"\nWarning: deduplication would leave only {total_new}/{total_all} items — skipping filter this run")
        sources_filtered = sources
        skipped = 0
        total_new = total_all
    elif skipped:
        print(f"\nSkipped {skipped} previously seen item(s) (seen_urls.json)")

    print(f"Sending {total_new} new items to synthesis\n")

    print("Synthesizing newsletter...\n")
    newsletter = synthesize(sources_filtered, cost_log=cost_log)

    # Persist all fetched URLs so future runs skip them
    seen_urls.update(all_urls)
    _save_seen_urls(seen_urls)

    today = date.today().strftime("%Y-%m-%d")
    output_path = os.path.join("newsletters", f"{today}.md")

    with open(output_path, "w", encoding="utf-8") as f:
        f.write(f"# Alpha AI — Week of {today}\n\n")
        f.write(newsletter)

    print(f"Newsletter saved to {output_path}")

    cost_log.print_summary()
    cost_log.append_to_file("costs.log")
    print("Costs logged to costs.log")

    total_items = sum(len(v) for v in sources.values() if v)
    with open("run_summary.html", "w", encoding="utf-8") as f:
        f.write(f"""
<h2>Your Alpha AI newsletter is ready.</h2>
<p><strong>Week of {today}</strong></p>

<h3>This week's run</h3>
<p>Sources fetched: <strong>{total_items} items</strong></p>
{cost_log.to_html()}

{_source_health_html(rss, reddit)}

<br>
<p>
  <a href="https://github.com/jmozden3/alpha-ai/blob/main/newsletters/{today}.md"
     style="background:#0066cc;color:white;padding:10px 20px;text-decoration:none;border-radius:4px;">
    View Newsletter in GitHub &rarr;
  </a>
</p>
<hr>
<p style="color:#888;font-size:12px;">Sent automatically by your Alpha AI pipeline.</p>
""")


if __name__ == "__main__":
    main()
