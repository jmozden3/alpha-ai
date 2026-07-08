import io
import json
import os
import sys
from datetime import date, datetime, timedelta
from dotenv import load_dotenv

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

from config import PUBLISH_EVERY_N_WEEKS, CADENCE_EPOCH
from costs import CostLog
from sources import fetch_rss_feeds, fetch_reddit_posts, fetch_hackernews
from synthesize import synthesize, extract_coverage, COVERAGE_PATH

load_dotenv()

SEEN_URLS_PATH = "seen_urls.json"
SEEN_URL_TTL_DAYS = 60  # forget URLs older than this so the ledger can't grow forever

# Standing transparency footer appended to every issue. Kept as static text
# (not part of the AI-generated body) so the wording and the link are always
# exact — the model never gets a chance to reword it or invent the URL.
NEWSLETTER_FOOTER = (
    "\n\n---\n\n"
    "*P.S. — reminder: these tips are distilled with AI from the best sources I "
    "curate. [How it's made.](https://github.com/jmozden3/alpha-ai)*\n"
)


def _load_seen_urls() -> dict:
    """Return {url: 'YYYY-MM-DD'}. Transparently upgrades the old list format
    (bare URLs with no dates) by stamping those entries with today's date."""
    if not os.path.exists(SEEN_URLS_PATH):
        return {}
    with open(SEEN_URLS_PATH, "r", encoding="utf-8") as f:
        data = json.load(f)
    if isinstance(data, dict):
        return data
    today = date.today().strftime("%Y-%m-%d")
    return {url: today for url in data}  # migrate legacy list format


def _prune_seen(seen: dict) -> dict:
    """Drop entries older than SEEN_URL_TTL_DAYS. Undated/malformed entries are
    kept (we can't tell their age, so err toward not re-surfacing them)."""
    cutoff = date.today() - timedelta(days=SEEN_URL_TTL_DAYS)
    kept = {}
    for url, seen_date in seen.items():
        try:
            if datetime.strptime(seen_date, "%Y-%m-%d").date() >= cutoff:
                kept[url] = seen_date
        except (TypeError, ValueError):
            kept[url] = seen_date
    return kept


def _save_seen_urls(seen: dict):
    with open(SEEN_URLS_PATH, "w", encoding="utf-8") as f:
        json.dump(dict(sorted(seen.items())), f, indent=2)


def _filter_seen(sources: dict, seen_urls: set) -> tuple[dict, int]:
    filtered = {}
    skipped = 0
    for source, items in sources.items():
        if not isinstance(items, list):
            filtered[source] = []
            continue
        kept = [item for item in items if item.get("url") not in seen_urls]
        skipped += len(items) - len(kept)
        filtered[source] = kept
    return filtered, skipped


def _source_health_html(rss: dict, reddit: dict, hn: dict) -> str:
    rows = ""

    for name, items in rss.items():
        count = len(items)
        if count > 0:
            status = f"<span style='color:green;'>&#10003; {count} items</span>"
        else:
            status = "<span style='color:red;'>&#10007; No content — check feed</span>"
        rows += f"<tr><td>{name}</td><td>RSS</td><td>{status}</td></tr>"

    # Reddit and Hacker News share the same shape (list of items, or {"error": ...})
    for label, group in (("Reddit", reddit), ("Hacker News", hn)):
        for name, items in group.items():
            if isinstance(items, dict) and "error" in items:
                status = f"<span style='color:red;'>&#10007; Error: {items['error']}</span>"
            elif len(items) > 0:
                status = f"<span style='color:green;'>&#10003; {len(items)} items</span>"
            else:
                status = "<span style='color:orange;'>&#9888; No posts this week</span>"
            rows += f"<tr><td>{name}</td><td>{label}</td><td>{status}</td></tr>"

    alive = sum(1 for v in {**rss, **reddit, **hn}.values() if v and not (isinstance(v, dict) and "error" in v))
    total = len(rss) + len(reddit) + len(hn)

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

    # Don't clobber an existing issue for today. A manual test run followed by the
    # scheduled Action (or two runs in one day) would otherwise overwrite the file
    # and produce duplicate commits. Set ALPHA_FORCE=1 to regenerate deliberately.
    force = bool(os.environ.get("ALPHA_FORCE"))
    today = date.today().strftime("%Y-%m-%d")
    output_path = os.path.join("newsletters", f"{today}.md")
    if os.path.exists(output_path) and not force:
        print(f"Newsletter for {today} already exists at {output_path}.")
        print("Set ALPHA_FORCE=1 to regenerate. Exiting without changes.")
        return

    # Biweekly cadence: the Action runs weekly, but we only publish every Nth
    # week (counted from CADENCE_EPOCH so it never drifts). On off weeks we exit
    # before doing any work — nothing fetched, written, committed, or emailed.
    weeks_since = (date.today() - CADENCE_EPOCH).days // 7
    if PUBLISH_EVERY_N_WEEKS > 1 and weeks_since % PUBLISH_EVERY_N_WEEKS != 0 and not force:
        print(f"Off week for the {PUBLISH_EVERY_N_WEEKS}-week schedule — nothing to publish today.")
        print("Set ALPHA_FORCE=1 to generate anyway, or PUBLISH_EVERY_N_WEEKS=1 in config.py for weekly.")
        return

    cost_log = CostLog()

    print("Fetching RSS feeds...")
    rss = fetch_rss_feeds()

    print("\nFetching Reddit posts...")
    reddit = fetch_reddit_posts()

    print("\nFetching Hacker News...")
    hn = fetch_hackernews()

    sources = {**rss, **reddit, **hn}

    # Deduplicate against previously seen URLs
    seen_urls = _load_seen_urls()
    all_urls = {item["url"] for items in sources.values() if isinstance(items, list) for item in items if item.get("url")}
    sources_filtered, skipped = _filter_seen(sources, seen_urls)
    total_new = sum(len(v) for v in sources_filtered.values() if isinstance(v, list))
    total_all = sum(len(v) for v in sources.values() if isinstance(v, list))

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

    # Alternate the action slot from issue to issue so each stays short without
    # losing variety over a month. Keyed to the count of PUBLISHED issues (not the
    # calendar week), so alternation survives skipped/off weeks: even issues get
    # the Prompt, odd issues get the Workflow Unlock.
    issue_index = weeks_since // PUBLISH_EVERY_N_WEEKS
    rotating = "prompt" if issue_index % 2 == 0 else "workflow"

    print("Synthesizing newsletter...\n")
    newsletter = synthesize(sources_filtered, cost_log=cost_log, rotating=rotating)

    # Persist all fetched URLs (stamped today) so future runs skip them, then
    # prune anything past the TTL so the ledger doesn't grow without bound.
    for url in all_urls:
        seen_urls[url] = today
    seen_urls = _prune_seen(seen_urls)
    _save_seen_urls(seen_urls)

    with open(output_path, "w", encoding="utf-8") as f:
        f.write(f"# Alpha AI — Week of {today}\n\n")
        f.write(newsletter)
        f.write(NEWSLETTER_FOOTER)

    print(f"Newsletter saved to {output_path}")

    # Append this issue's use cases to the coverage ledger so future runs avoid
    # repeating them. Best-effort: a failed extraction never blocks the run.
    covered = extract_coverage(newsletter, cost_log=cost_log)
    if covered:
        ledger = []
        if os.path.exists(COVERAGE_PATH):
            try:
                with open(COVERAGE_PATH, "r", encoding="utf-8") as f:
                    ledger = json.load(f)
            except (json.JSONDecodeError, OSError):
                ledger = []
        ledger.append({"date": today, "covered": covered})
        with open(COVERAGE_PATH, "w", encoding="utf-8") as f:
            json.dump(ledger, f, indent=2, ensure_ascii=False)
        print(f"Coverage ledger updated ({len(covered)} use case(s) logged)")

    cost_log.print_summary()
    cost_log.append_to_file("costs.log")
    print("Costs logged to costs.log")

    total_items = sum(len(v) for v in sources.values() if isinstance(v, list))
    with open("run_summary.html", "w", encoding="utf-8") as f:
        f.write(f"""
<h2>Your Alpha AI newsletter is ready.</h2>
<p><strong>Week of {today}</strong></p>

<h3>This week's run</h3>
<p>Sources fetched: <strong>{total_items} items</strong></p>
{cost_log.to_html()}

{_source_health_html(rss, reddit, hn)}

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
