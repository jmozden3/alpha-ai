RSS_FEEDS = {
    # --- Audience-appropriate feeds (verified live 2026-07-07) ---
    # Kept: written for non-technical knowledge workers or accessible practitioners.
    "One Useful Thing":      "https://www.oneusefulthing.org/feed",
    "The Rundown AI":        "https://rss.beehiiv.com/feeds/2R3C6Bt5wj.xml",
    "Ben's Bites":           "https://www.bensbites.com/feed",
    "The Neuron":            "https://rss.beehiiv.com/feeds/N4eCstxvgX.xml",
    "Every.to":              "https://every.to/chain-of-thought/feed.xml",
    "Simon Willison":        "https://simonwillison.net/atom/everything/",
    "All-In Pod":            "https://allinchamathjason.libsyn.com/rss",
    # Added 2026-07-07 — verified live, aimed at our actual reader:
    "OpenAI":                "https://openai.com/news/rss.xml",              # primary source for real feature launches (Tool of the Week)
    "TLDR AI":               "https://tldr.tech/api/rss/ai",                  # daily plain-English AI digest
    "Lenny's Newsletter":    "https://www.lennysnewsletter.com/feed",        # product/work practices for managers & professionals
    "MIT Sloan Mgmt Review": "https://sloanreview.mit.edu/feed/",            # AI-at-work from a management lens
    "Platformer":            "https://www.platformer.news/rss/",             # consumer/policy AI news for Signal vs Noise
    # Pruned 2026-07-07 — too technical/researcher-focused for a non-technical
    # reader; they rarely yielded usable items and inflated the source blob:
    #   Latent Space, Import AI (jack-clark.net), Ahead of AI, The Gradient
}

SUBREDDITS = [
    # Swapped 2026-07-07 toward communities of the people we write FOR
    # (professionals using AI at work) instead of hobbyist/dev-heavy subs.
    "ChatGPT",
    "ClaudeAI",
    "OpenAI",
    "AI_Agents",
    "productivity",      # replaced hobbyist r/LocalLLaMA
    "Entrepreneur",      # replaced futurist r/singularity
    "smallbusiness",     # replaced dev-focused r/VibeCoding
]

# General-interest subs (above) are NOT AI-native: their top posts are mostly
# off-topic for us. Alpha AI is specifically about using AI for tangible impact
# in everyday work, so we only let posts through from these subs when they
# actually mention AI. The AI-native subs are exempt from this gate.
GENERAL_SUBREDDITS = {"productivity", "Entrepreneur", "smallbusiness"}

# Case-insensitive substrings that mark a post as AI-relevant. Kept broad enough
# to catch the tools/terms our reader would recognize without demanding an exact
# match. Add to this as new mainstream tools appear.
AI_KEYWORDS = [
    "ai", "a.i.", "artificial intelligence", "chatgpt", "gpt", "claude",
    "gemini", "copilot", "llm", "openai", "anthropic", "perplexity",
    "notebooklm", "midjourney", "prompt", "automation", "agent", "machine learning",
]

MAX_ITEMS_PER_SOURCE = 5
MAX_CHARS_PER_ITEM = 2000
DAYS_LOOKBACK = 7

# --- Cadence & volumes ---
# The GitHub Action fires every Tuesday and always collects a weekly BRIEFING —
# candidate tips + news, emailed to the editor and saved to briefings/. Roundup
# drafts are generated ON DEMAND (python main.py --mode roundup locally, or the
# "Run workflow" button on GitHub Actions with mode=roundup) whenever the editor
# feels like writing an issue. There is no publishing schedule.
BRIEFING_MAX_CANDIDATES = 8     # max candidates kept per weekly briefing
ROUNDUP_TIPS = 3                # full tip write-ups per roundup draft
ROUNDUP_NEWS = 2                # max "Worth knowing" news items per draft
ROUNDUP_RUNNERS_UP = 5          # shortlist bullets appended under the tips
ROUNDUP_MAX_LOOKBACK_DAYS = 60  # safety cap on how far back a roundup reaches

# --- Hacker News (Algolia API, unauthenticated, not IP-blocked on Actions) ---
HN_QUERY = "AI"        # full-text query against story titles/text
HN_MIN_POINTS = 30     # ignore low-engagement stories below this many points
