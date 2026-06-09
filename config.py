RSS_FEEDS = {
    # --- Verified working as of 2026-05-25 ---
    "One Useful Thing":      "https://www.oneusefulthing.org/feed",
    "The Rundown AI":        "https://rss.beehiiv.com/feeds/2R3C6Bt5wj.xml",
    "Ben's Bites":           "https://www.bensbites.com/feed",
    "The Neuron":            "https://rss.beehiiv.com/feeds/N4eCstxvgX.xml",
    "Every.to":              "https://every.to/chain-of-thought/feed.xml",
    "Simon Willison":        "https://simonwillison.net/atom/everything/",
    "Latent Space":          "https://www.latent.space/feed",
    "All-In Pod":            "https://allinchamathjason.libsyn.com/rss",
    "Import AI":             "https://jack-clark.net/feed/",
    "Ahead of AI":           "https://magazine.sebastianraschka.com/feed",
    "The Gradient":          "https://thegradient.pub/rss/",
}

SUBREDDITS = [
    "LocalLLaMA",
    "ChatGPT",
    "ClaudeAI",
    "singularity",       # replaced dead r/AIPromptEngineering (last post Apr 27, score 3)
    "VibeCoding",
    "OpenAI",            # replaced dead r/AI_Automations (last post Apr 24, score 1)
    "AI_Agents",
]

MAX_ITEMS_PER_SOURCE = 5
MAX_CHARS_PER_ITEM = 2000
DAYS_LOOKBACK = 7

# --- Hacker News (Algolia API, unauthenticated, not IP-blocked on Actions) ---
HN_QUERY = "AI"        # full-text query against story titles/text
HN_MIN_POINTS = 30     # ignore low-engagement stories below this many points
