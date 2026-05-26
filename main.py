import io
import os
import sys
from datetime import date
from dotenv import load_dotenv

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

from costs import CostLog
from sources import fetch_rss_feeds, fetch_reddit_posts
from synthesize import synthesize

load_dotenv()


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

    print("\nSynthesizing newsletter...\n")
    newsletter = synthesize(sources, cost_log=cost_log)

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
