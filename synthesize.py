import os
import re

import anthropic

from costs import CostEntry, CostLog

MODEL = "claude-sonnet-4-6"
FEEDBACK_PATH = "FEEDBACK.md"

SYSTEM_PROMPT = """You are the editor of Alpha AI, a weekly newsletter for knowledge workers who want to use AI to level up — without becoming technical.

Your reader is someone whose job runs on thinking, communicating, and organizing: the SMB owner prepping for a board meeting, the teacher planning next week's lessons, the mid-career manager trying to do more with less, the early-career professional trying to stand out. They are not developers. They are not AI researchers. They know AI is a thing and they want to actually use it — not just read about it.

The common thread across all your readers: their work is 80% communication, judgment, and organization. That's exactly where AI is most useful right now. Every item you write should pass this test: could a busy professional use this before tomorrow morning, with no setup and no technical background?

Rules you must follow:
- Write like a smart friend explaining things over coffee, not a press release
- Every single item must be immediately usable by someone with no technical background
- No jargon without plain-English explanation
- No market commentary, funding rounds, valuations, or stock prices — readers don't care
- No developer-only tools, APIs, or anything requiring code
- Be specific and concrete. "Use ChatGPT to do X by doing Y and Z" beats "AI can help with productivity"
- Frame everything through real work: emails, meetings, decisions, planning, communication, learning — not abstract productivity

Accuracy rules — these are non-negotiable:
- Never cite specific statistics, percentages, or numerical claims unless they appear verbatim in the source material. If a claim is vague, anecdotal, or from a Reddit post, use hedged language like "some reports suggest", "anecdotally", or "according to community discussion" instead of presenting it as established fact
- Reddit and Hacker News posts are community discussion, not journalism. Treat them as signals of what people are talking about, never as sources for specific facts or data
- If you are uncertain whether a claim is accurate, omit the specific detail rather than risk publishing a false statistic
- At the end of each section, cite the source name AND include the source URL in parentheses so readers can verify for themselves

Engagement signals:
- Some items include an "(Engagement: ...)" line — a Reddit top-of-week rank, or Hacker News points and comment counts. This tells you how much a story is resonating right now; prefer high-engagement stories when choosing what to feature
- Engagement is NOT a measure of accuracy or fit for your reader. A story can be #1 on Hacker News and still be too technical, too niche, or wrong for a non-technical knowledge worker. Judgment about your audience always overrides raw popularity

Freshness rules:
- Each item in the source material includes a publication date in brackets, e.g. [2026-05-20]
- Strongly prefer items published within the last 7 days over older content
- If two items cover similar topics, pick the more recent one
- Avoid repeating topics or tools that feel like they could have appeared in last week's newsletter — favor what is genuinely new this week

Source variety rules:
- Each of the four content sections must draw from a DIFFERENT source. Never cite the same source — or the same source URL — in two sections. You have many feeds available this week, so there is no excuse for repeating a source
- Across the full newsletter, draw from at least four different sources — each section should bring something the others don't
- Reddit communities count as a source; treat each subreddit as its own source (r/ChatGPT and r/LocalLLaMA are distinct)

Story and topic diversity rules — these are the most important variety rules:
- Each section must be based on a genuinely different story, announcement, or piece of content. Never take one story and reframe it across two sections — readers will notice
- No single named tool or app (for example Perplexity, ChatGPT, Claude, Notion, Gemini) may be the recommended action OR the primary subject of more than one section. This holds even when the angle differs — "use Perplexity to stress-test an idea" and "Perplexity, the research tool" both count as Perplexity and may not both appear. In particular, the Tip of the Week and the Tool of the Week must center on DIFFERENT tools
- No more than one section should have the same company or product as its primary subject. If one company had a big week, pick their single most useful story for your audience and use it once; find the best content from other sources for the rest
- The content sections together should feel like different windows into the AI world this week — different tools, different use cases, different sources, different kinds of readers served

Before you finish, re-read your full draft and verify three things: (1) no tool or app is recommended or featured in more than one section, (2) no source name or URL is cited in more than one section, (3) each section is a genuinely different story. If any check fails, replace the weaker section with different content drawn from the source material.

Length and focus rules — the newsletter must be short enough that a busy reader actually finishes it and acts:
- This is an actionable newsletter. One thing a reader will actually do beats five things they never will. Do not pad.
- Keep the whole newsletter tight — aim for roughly a 3-minute read. Be ruthless about cutting anything that isn't directly useful.
- The Tip of the Week is the hero. Give it room. Keep every other section lean.
"""

_PROMPT_SECTION = """## 💡 Prompt of the Week
One prompting technique with the EXACT prompt someone can copy-paste into ChatGPT, Claude, or any AI assistant. Explain what it does and when to use it in a sentence or two — keep the prose lean, let the prompt do the work. The prompt itself should be in a code block. End with: *Source: [Publication Name] — [URL]*"""

_WORKFLOW_SECTION = """## 🔓 Workflow Unlock
One concrete way to use AI differently in real work. Give specific steps, not vague advice. Example of good: "Open [tool], paste your meeting notes, type [specific instruction], and you get [specific output]." Keep it tight — the steps, not a lecture. End with: *Source: [Publication Name] — [URL]*"""

ROTATING_SECTIONS = {"prompt": _PROMPT_SECTION, "workflow": _WORKFLOW_SECTION}


def build_newsletter_format(rotating: str = "prompt") -> str:
    rotating_section = ROTATING_SECTIONS.get(rotating, _PROMPT_SECTION)
    return f"""
## From the Editor

*[Write your intro here — 2-4 sentences. A reaction, something you noticed, or anything on your mind this week related to AI. Not a tip — just your voice.]*

*— [Your name]*

---

## ⚡ The Alpha — Tip of the Week
The single best actionable insight this week, and the hero of the issue — give it room. One thing someone can use today. Must be specific — not "AI can help you write better" but HOW to do it step by step. End with: *Source: [Publication Name] — [URL]*

## 🛠 Tool of the Week
One specific AI tool. What it does in one sentence, exactly how to use it right now (specific steps), and who it's most useful for. Keep it lean. No hype words like "revolutionary" or "game-changing". End with: *Source: [Publication Name] — [URL]*

{rotating_section}

## 📡 Signal vs Noise
Keep this section short — about two sentences for each half.
SIGNAL: One thing happening in AI right now that non-technical people should actually pay attention to, and in one sentence why it matters to them personally. End with: *Source: [Publication Name] — [URL]*
NOISE: One thing that sounds important but isn't actionable yet for regular people — tell them to ignore it for now and why, briefly. If sourced from Reddit, explicitly note it is community discussion, not a verified report. End with: *Source: [Publication Name] — [URL]*
""".strip()


def _format_sources(sources_dict: dict) -> str:
    lines = []
    for source_name, items in sources_dict.items():
        if not isinstance(items, list) or not items:
            continue
        lines.append(f"\n### {source_name}")
        for item in items:
            date_str = f" [{item['date']}]" if item.get("date") and item["date"] != "unknown" else ""
            lines.append(f"**{item['title']}**{date_str}")
            if item.get("signal"):
                lines.append(f"(Engagement: {item['signal']})")
            if item.get("text"):
                lines.append(item["text"])
            if item.get("url"):
                lines.append(f"Source URL: {item['url']}")
            lines.append("")
    return "\n".join(lines)


def _load_style_guidance(path: str = FEEDBACK_PATH) -> str:
    """Return the text under the '## Style guidance' heading of FEEDBACK.md so the
    editor's accumulated preferences steer each run. Empty string if the file or
    section is missing. HTML comments are stripped so placeholders never leak in."""
    if not os.path.exists(path):
        return ""
    with open(path, "r", encoding="utf-8") as f:
        lines = f.read().splitlines()

    captured, capturing = [], False
    for line in lines:
        if line.strip().lower().startswith("## style guidance"):
            capturing = True
            continue
        if capturing and (line.startswith("## ") or line.strip() == "---"):
            break  # next top-level section or horizontal-rule separator ends it
        if capturing:
            captured.append(line)

    text = re.sub(r"<!--.*?-->", "", "\n".join(captured), flags=re.DOTALL)
    return text.strip()


def synthesize(sources_dict: dict, cost_log: CostLog | None = None, rotating: str = "prompt") -> str:
    client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])

    formatted_content = _format_sources(sources_dict)
    total_sources = sum(len(v) for v in sources_dict.values() if v)
    print(f"Sending {total_sources} items to Claude for synthesis...")
    print(f"Rotating action slot this week: {rotating}")

    system_prompt = SYSTEM_PROMPT
    guidance = _load_style_guidance()
    if guidance:
        system_prompt += (
            "\n\nEditor feedback — accumulated preferences from past issues. "
            "Treat these as high-priority style rules, second only to the accuracy rules above:\n"
            + guidance
        )
        print("Applied editor style guidance from FEEDBACK.md")

    newsletter_format = build_newsletter_format(rotating)

    user_prompt = f"""Here is this week's raw content pulled from AI newsletters and communities:

{formatted_content}

---

Now write this week's Alpha AI newsletter. Use only the content above as your source material. Follow exactly this format:

{newsletter_format}

Write the full newsletter now."""

    with client.messages.stream(
        model=MODEL,
        max_tokens=4096,
        system=system_prompt,
        messages=[{"role": "user", "content": user_prompt}],
    ) as stream:
        newsletter = ""
        for text in stream.text_stream:
            print(text, end="", flush=True)
            newsletter += text
        final = stream.get_final_message()

    if cost_log is not None:
        cost_log.add(CostEntry(
            api="anthropic",
            model=MODEL,
            detail="newsletter synthesis",
            input_tokens=final.usage.input_tokens,
            output_tokens=final.usage.output_tokens,
        ))

    print("\n")
    return newsletter
