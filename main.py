import argparse
import glob
import html
import io
import json
import os
import sys
from datetime import date, datetime, timedelta

from dotenv import load_dotenv

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

from config import (
    BRIEFING_MAX_CANDIDATES,
    ROUNDUP_MAX_LOOKBACK_DAYS,
    ROUNDUP_NEWS,
    ROUNDUP_RUNNERS_UP,
    ROUNDUP_TIPS,
)
from costs import CostLog
from sources import fetch_rss_feeds, fetch_reddit_posts, fetch_hackernews
from synthesize import distill_candidates, extract_coverage, synthesize_roundup, COVERAGE_PATH

load_dotenv()

SEEN_URLS_PATH = "seen_urls.json"
SEEN_URL_TTL_DAYS = 60  # forget URLs older than this so the ledger can't grow forever

BRIEFINGS_DIR = "briefings"
ROUNDUPS_DIR = "roundups"
ROUNDUP_STATE_PATH = "roundup_state.json"  # {"consumed_through": "YYYY-MM-DD"}

REPO_URL = "https://github.com/jmozden3/alpha-ai"

# Standing transparency line at the top of every roundup draft. Kept as static
# text (not part of the AI-generated body) so the wording and the link are
# always exact — the model never gets a chance to reword it or invent the URL.
ROUNDUP_PREAMBLE = (
    '*The intro and "my take" notes are me. The tips and news below are '
    f"AI-distilled from sources I curate — [how it's made]({REPO_URL}).*"
)
INTRO_PLACEHOLDER = "*[Your intro — 2-4 sentences. What stood out this period, or why you picked these.]*"


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


def _split_lanes(candidates: list[dict]) -> tuple[list[dict], list[dict]]:
    practical = [c for c in candidates if c.get("type") != "news"]
    news = [c for c in candidates if c.get("type") == "news"]
    return practical, news


def _render_briefing_md(candidates: list[dict], today: str) -> str:
    """Human-readable weekly briefing for the repo (the email mirrors it)."""
    practical, news = _split_lanes(candidates)
    lines = [
        f"# Alpha AI Briefing — Week of {today}",
        "",
        f"*Private research briefing: {len(practical)} practical candidate(s) and "
        f"{len(news)} news candidate(s), best first. Machine-generated for a future "
        "roundup — not for publication.*",
        "",
    ]

    def _section(title: str, items: list[dict]):
        if not items:
            return
        lines.append(f"## {title}")
        lines.append("")
        for i, c in enumerate(items, 1):
            lines.append(f"### {i}. {c['title']}")
            lines.append("")
            lines.append(f"`{c['type']}` · score {c['score']}/10")
            lines.append("")
            if c.get("summary"):
                lines.append(c["summary"])
                lines.append("")
            if c.get("why"):
                lines.append(f"**Why it matters:** {c['why']}")
                lines.append("")
            src = f"[{c['source']}]({c['url']})" if c.get("url") else c["source"]
            lines.append(f"**Source:** {src}")
            lines.append("")

    _section("Tips & tricks", practical)
    _section("News worth knowing", news)
    return "\n".join(lines)


def _render_briefing_email_html(candidates: list[dict], today: str,
                                cost_log: CostLog, health_html: str) -> str:
    """Full briefing content in the email body, so the week's reading needs zero
    clicks. Rendered from the candidate dicts directly — no markdown parsing."""
    practical, news = _split_lanes(candidates)

    def _items_html(items: list[dict]) -> str:
        blocks = ""
        for c in items:
            title = html.escape(c["title"])
            summary = html.escape(c.get("summary", ""))
            why = html.escape(c.get("why", ""))
            source = html.escape(c["source"])
            link = f"<a href='{html.escape(c['url'])}'>{source}</a>" if c.get("url") else source
            blocks += f"""
<div style='margin:0 0 18px 0;padding:12px 14px;border:1px solid #e0e0e0;border-radius:6px;'>
  <p style='margin:0 0 6px 0;font-size:15px;'><strong>{title}</strong>
     <span style='color:#888;font-size:12px;'>&nbsp;{html.escape(c.get("type", "tip"))} · {c.get("score", "?")}/10</span></p>
  <p style='margin:0 0 6px 0;'>{summary}</p>
  <p style='margin:0 0 6px 0;color:#555;'><em>Why it matters: {why}</em></p>
  <p style='margin:0;font-size:13px;'>Source: {link}</p>
</div>"""
        return blocks

    sections = ""
    if practical:
        sections += f"<h3>Tips &amp; tricks ({len(practical)})</h3>{_items_html(practical)}"
    if news:
        sections += f"<h3>News worth knowing ({len(news)})</h3>{_items_html(news)}"

    return f"""
<div style='font-family:sans-serif;font-size:14px;max-width:640px;'>
<h2>Alpha AI Briefing — Week of {today}</h2>
<p style='color:#666;'>This week's candidates for a future roundup. Nothing to do —
read, and star anything you want to write about.</p>

{sections}

<p><a href="{REPO_URL}/blob/main/{BRIEFINGS_DIR}/{today}.md">View this briefing on GitHub &rarr;</a></p>

{cost_log.to_html()}
{health_html}
<hr>
<p style="color:#888;font-size:12px;">Sent automatically by your Alpha AI pipeline.</p>
</div>"""


def collect(force: bool):
    """Weekly research-assistant run: fetch everything, distill the week's
    candidates, save the briefing to the repo, and email it to the editor."""
    today = date.today().strftime("%Y-%m-%d")
    os.makedirs(BRIEFINGS_DIR, exist_ok=True)
    md_path = os.path.join(BRIEFINGS_DIR, f"{today}.md")
    if os.path.exists(md_path) and not force:
        print(f"Briefing for {today} already exists at {md_path}.")
        print("Set ALPHA_FORCE=1 to regenerate. Exiting without changes.")
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

    print(f"Sending {total_new} new items to distillation\n")
    candidates = distill_candidates(sources_filtered, cost_log=cost_log,
                                    max_candidates=BRIEFING_MAX_CANDIDATES)

    # Persist all fetched URLs (stamped today) so future runs skip them, then
    # prune anything past the TTL so the ledger doesn't grow without bound.
    for url in all_urls:
        seen_urls[url] = today
    seen_urls = _prune_seen(seen_urls)
    _save_seen_urls(seen_urls)

    with open(md_path, "w", encoding="utf-8") as f:
        f.write(_render_briefing_md(candidates, today))
    json_path = os.path.join(BRIEFINGS_DIR, f"{today}.json")
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump({"week": today, "candidates": candidates}, f, indent=2, ensure_ascii=False)
    print(f"Briefing saved to {md_path} (+ {json_path})")

    cost_log.print_summary()
    cost_log.append_to_file("costs.log")
    print("Costs logged to costs.log")

    with open("run_summary.html", "w", encoding="utf-8") as f:
        f.write(_render_briefing_email_html(candidates, today, cost_log,
                                            _source_health_html(rss, reddit, hn)))


def _load_briefings_since(consumed_through: str) -> tuple[list[dict], str]:
    """Gather candidates from every briefing JSON newer than `consumed_through`
    (bounded by ROUNDUP_MAX_LOOKBACK_DAYS as a safety cap), deduped by URL with
    the higher score winning. Returns (candidates, newest_briefing_date)."""
    floor = (date.today() - timedelta(days=ROUNDUP_MAX_LOOKBACK_DAYS)).strftime("%Y-%m-%d")
    start = max(consumed_through, floor)

    by_url: dict[str, dict] = {}
    no_url: list[dict] = []
    newest = consumed_through
    used_files = []
    for path in sorted(glob.glob(os.path.join(BRIEFINGS_DIR, "*.json"))):
        stem = os.path.splitext(os.path.basename(path))[0]  # YYYY-MM-DD
        if stem <= start:
            continue
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
        except (json.JSONDecodeError, OSError) as e:
            print(f"  Skipping unreadable briefing {path}: {e}")
            continue
        used_files.append(path)
        newest = max(newest, stem)
        for c in data.get("candidates", []):
            c = dict(c)
            c["week"] = data.get("week", stem)
            url = c.get("url")
            if not url:
                no_url.append(c)
            elif url not in by_url or (c.get("score") or 0) > (by_url[url].get("score") or 0):
                by_url[url] = c

    candidates = list(by_url.values()) + no_url
    candidates.sort(key=lambda c: c.get("score") or 0, reverse=True)
    print(f"Loaded {len(candidates)} candidate(s) from {len(used_files)} briefing(s) since {start}")
    return candidates, newest


def roundup(force: bool):
    """On-demand editor run: gather every briefing since the last roundup, draft
    'Alpha AI Roundup — Issue N' with the editor's placeholders, and stop. The
    human writes the intro and takes, then publishes to the blog by hand."""
    today = date.today().strftime("%Y-%m-%d")
    os.makedirs(ROUNDUPS_DIR, exist_ok=True)
    draft_path = os.path.join(ROUNDUPS_DIR, f"{today}-draft.md")
    if os.path.exists(draft_path) and not force:
        print(f"A roundup draft for {today} already exists at {draft_path}.")
        print("Set ALPHA_FORCE=1 to regenerate. Exiting without changes.")
        return

    state = {}
    if os.path.exists(ROUNDUP_STATE_PATH):
        try:
            with open(ROUNDUP_STATE_PATH, "r", encoding="utf-8") as f:
                state = json.load(f)
        except (json.JSONDecodeError, OSError):
            state = {}
    consumed_through = state.get("consumed_through", "0000-00-00")

    candidates, newest = _load_briefings_since(consumed_through)
    if len(candidates) < ROUNDUP_TIPS:
        print(f"Only {len(candidates)} unused candidate(s) since the last roundup — "
              f"need at least {ROUNDUP_TIPS}. Let a few more weekly briefings land first.")
        return

    issue_number = len(glob.glob(os.path.join(ROUNDUPS_DIR, "*.md"))) + 1

    cost_log = CostLog()
    print(f"Drafting Alpha AI Roundup — Issue {issue_number}...\n")
    body = synthesize_roundup(candidates, cost_log=cost_log, tips=ROUNDUP_TIPS,
                              news=ROUNDUP_NEWS, runners_up=ROUNDUP_RUNNERS_UP)

    draft = (
        f"# Alpha AI Roundup — Issue {issue_number}\n\n"
        f"{ROUNDUP_PREAMBLE}\n\n"
        f"{INTRO_PLACEHOLDER}\n\n"
        "---\n\n"
        f"{body.strip()}\n"
    )
    with open(draft_path, "w", encoding="utf-8") as f:
        f.write(draft)
    print(f"Draft saved to {draft_path}")

    # Mark the consumed briefings so the next roundup starts where this one
    # stopped — regardless of how long the editor waits between issues.
    with open(ROUNDUP_STATE_PATH, "w", encoding="utf-8") as f:
        json.dump({"consumed_through": newest, "last_issue": issue_number,
                   "last_draft": draft_path}, f, indent=2)

    # Append this issue's use cases to the coverage ledger so future issues avoid
    # repeating them. Best-effort: a failed extraction never blocks the run.
    covered = extract_coverage(draft, cost_log=cost_log)
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

    with open("run_summary.html", "w", encoding="utf-8") as f:
        f.write(f"""
<div style='font-family:sans-serif;font-size:14px;max-width:640px;'>
<h2>Your roundup draft is ready — Issue {issue_number}</h2>
<p><strong>{today}</strong> · drafted from candidates gathered since your last issue.</p>
<p>Next step is yours: write the intro, add your takes (especially under
<em>Worth knowing</em>), swap anything from the runners-up, then paste it into the blog.</p>
<p>
  <a href="{REPO_URL}/blob/main/{ROUNDUPS_DIR}/{today}-draft.md"
     style="background:#0066cc;color:white;padding:10px 20px;text-decoration:none;border-radius:4px;">
    Open the draft &rarr;
  </a>
</p>
{cost_log.to_html()}
<hr>
<p style="color:#888;font-size:12px;">Sent automatically by your Alpha AI pipeline.</p>
</div>""")


def main():
    parser = argparse.ArgumentParser(description="Alpha AI pipeline")
    parser.add_argument("--mode", choices=["collect", "roundup"], default="collect",
                        help="collect = weekly briefing (default); roundup = draft an issue on demand")
    args = parser.parse_args()

    force = bool(os.environ.get("ALPHA_FORCE"))
    print(f"=== Alpha AI Pipeline — {args.mode} ===\n")
    if args.mode == "roundup":
        roundup(force)
    else:
        collect(force)


if __name__ == "__main__":
    main()
