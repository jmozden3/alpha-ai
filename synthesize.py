import os
import anthropic

MODEL = "claude-sonnet-4-6"

SYSTEM_PROMPT = """You are the editor of Alpha AI, a weekly newsletter for non-technical people who want to use AI in their everyday lives and work.

Your readers are curious, busy professionals — not developers. They want to know what AI can do FOR them right now, not how it works under the hood.

Rules you must follow:
- Write like a smart friend explaining things over coffee, not a press release
- Every single item must be immediately usable by someone with no technical background
- No jargon without plain-English explanation
- No market commentary, funding rounds, valuations, or stock prices — readers don't care
- No developer-only tools, APIs, or anything requiring code
- Cite the source (publication name) at the end of each section
- Be specific and concrete. "Use ChatGPT to do X by doing Y and Z" beats "AI can help with productivity"
"""

NEWSLETTER_FORMAT = """
## ⚡ The Alpha
The single best actionable insight this week. One thing someone can use today. Must be specific — not "AI can help you write better" but HOW to do it step by step. Cite the source.

## 🛠 Tool of the Week
One specific AI tool. What it does in one sentence, exactly how to use it right now (specific steps), and who it's most useful for. No hype words like "revolutionary" or "game-changing". Cite the source.

## 💡 Prompt of the Week
One prompting technique with the EXACT prompt someone can copy-paste into ChatGPT, Claude, or any AI assistant. Explain what it does and when to use it. The prompt itself should be in a code block. Cite the source.

## 🔓 Workflow Unlock
One concrete way to use AI differently in real work. Give specific steps, not vague advice. Example of good: "Open [tool], paste your meeting notes, type [specific instruction], and you get [specific output]." Cite the source.

## 📡 Signal vs Noise
SIGNAL: One thing happening in AI right now that non-technical people should actually pay attention to, and exactly why it matters to them personally.
NOISE: One thing that sounds important but isn't actionable yet for regular people — tell them to ignore it for now and why.
Cite sources for both.
""".strip()


def _format_sources(sources_dict: dict) -> str:
    lines = []
    for source_name, items in sources_dict.items():
        if not items:
            continue
        lines.append(f"\n### {source_name}")
        for item in items:
            lines.append(f"**{item['title']}**")
            if item.get("text"):
                lines.append(item["text"])
            if item.get("url"):
                lines.append(f"Source URL: {item['url']}")
            lines.append("")
    return "\n".join(lines)


def synthesize(sources_dict: dict) -> str:
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

    print("\n")
    return newsletter
