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
<br>
<p>
  <a href="https://github.com/jmozden3/alpha-ai/blob/main/newsletters/{today}.md"
     style="background:#0066cc;color:white;padding:10px 20px;text-decoration:none;border-radius:4px;">
    View Newsletter in GitHub →
  </a>
</p>
<hr>
<p style="color:#888;font-size:12px;">Sent automatically by your Alpha AI pipeline.</p>
""")


if __name__ == "__main__":
    main()
