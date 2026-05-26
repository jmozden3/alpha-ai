import os
import anthropic

from costs import CostEntry, CostLog

MODEL = "claude-sonnet-4-6"

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
- Reddit posts (r/anything) are community discussion, not journalism. Treat them as signals of what people are talking about, never as sources for specific facts or data
- If you are uncertain whether a claim is accurate, omit the specific detail rather than risk publishing a false statistic
- At the end of each section, cite the source name AND include the source URL in parentheses so readers can verify for themselves

Freshness rules:
- Each item in the source material includes a publication date in brackets, e.g. [2026-05-20]
- Strongly prefer items published within the last 7 days over older content
- If two items cover similar topics, pick the more recent one
- Avoid repeating topics or tools that feel like they could have appeared in last week's newsletter — favor what is genuinely new this week

Source variety rules:
- No single source should appear in more than two of the five sections
- Across the full newsletter, aim to draw from at least four different sources
- If the best available content for a section comes from an already-used source, use it — quality beats variety — but actively look across all sources before defaulting to a familiar one
- Reddit communities count as a source; treat each subreddit as its own source (r/ChatGPT and r/LocalLLaMA are distinct)
"""

NEWSLETTER_FORMAT = """
## From the Editor

*[Write your intro here — 2-4 sentences. A reaction, something you noticed, or anything on your mind this week related to AI. Not a tip — just your voice.]*

*— [Your name]*

---

## ⚡ The Alpha — Tip of the Week
The single best actionable insight this week. One thing someone can use today. Must be specific — not "AI can help you write better" but HOW to do it step by step. End with: *Source: [Publication Name] — [URL]*

## 🛠 Tool of the Week
One specific AI tool. What it does in one sentence, exactly how to use it right now (specific steps), and who it's most useful for. No hype words like "revolutionary" or "game-changing". End with: *Source: [Publication Name] — [URL]*

## 💡 Prompt of the Week
One prompting technique with the EXACT prompt someone can copy-paste into ChatGPT, Claude, or any AI assistant. Explain what it does and when to use it. The prompt itself should be in a code block. End with: *Source: [Publication Name] — [URL]*

## 🔓 Workflow Unlock
One concrete way to use AI differently in real work. Give specific steps, not vague advice. Example of good: "Open [tool], paste your meeting notes, type [specific instruction], and you get [specific output]." End with: *Source: [Publication Name] — [URL]*

## 📡 Signal vs Noise
SIGNAL: One thing happening in AI right now that non-technical people should actually pay attention to, and exactly why it matters to them personally. End with: *Source: [Publication Name] — [URL]*
NOISE: One thing that sounds important but isn't actionable yet for regular people — tell them to ignore it for now and why. If sourced from Reddit, explicitly note it is community discussion, not a verified report. End with: *Source: [Publication Name] — [URL]*
""".strip()


def _format_sources(sources_dict: dict) -> str:
    lines = []
    for source_name, items in sources_dict.items():
        if not items:
            continue
        lines.append(f"\n### {source_name}")
        for item in items:
            date_str = f" [{item['date']}]" if item.get("date") and item["date"] != "unknown" else ""
            lines.append(f"**{item['title']}**{date_str}")
            if item.get("text"):
                lines.append(item["text"])
            if item.get("url"):
                lines.append(f"Source URL: {item['url']}")
            lines.append("")
    return "\n".join(lines)


def synthesize(sources_dict: dict, cost_log: CostLog | None = None) -> str:
    client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])

    formatted_content = _format_sources(sources_dict)
    total_sources = sum(len(v) for v in sources_dict.values() if v)
    print(f"Sending {total_sources} items to Claude for synthesis...")

    user_prompt = f"""Here is this week's raw content pulled from AI newsletters and communities:

{formatted_content}

---

Now write this week's Alpha AI newsletter. Use only the content above as your source material. Follow exactly this format:

{NEWSLETTER_FORMAT}

Write the full newsletter now."""

    with client.messages.stream(
        model=MODEL,
        max_tokens=4096,
        system=SYSTEM_PROMPT,
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
