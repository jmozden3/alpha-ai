import json
import os
import re
from datetime import date, datetime, timedelta

import anthropic

from costs import CostEntry, CostLog

MODEL = "claude-sonnet-5"
# Sonnet 5 turns adaptive thinking ON when `thinking` is omitted; for this
# straightforward generation job we keep it OFF to preserve cost/latency and
# avoid empty-thinking-block streaming pauses. The variety self-check (below)
# does the enforcement that thinking might otherwise help with.
NO_THINKING = {"type": "disabled"}
FEEDBACK_PATH = "FEEDBACK.md"
COVERAGE_PATH = "coverage.json"
COVERAGE_LOOKBACK_DAYS = 90  # how far back to remember covered use cases (~3 months)
MAX_VARIETY_RETRIES = 1  # one re-roll if the draft repeats a source or a story

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
- Every section must be grounded in a specific source item from the material below. Each item is labeled with an ID like [S12]. At the end of each section, output the ID of the item you actually drew from — do NOT write a source name or URL yourself. The system fills in the correct name and link from that ID, so a section's citation is only ever right if the ID genuinely matches the content you wrote. Never attach an ID whose story is about something other than what your section says

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
- No single news event may anchor more than one section — and this includes the editor intro. If one event dominated the week (a launch, a ban, an outage), you may touch it in at most ONE place. Do not let it appear in the intro AND a section, or in two sections under different source names. Pull the other sections from genuinely different stories
- No single named tool or app (for example Perplexity, ChatGPT, Claude, Notion, Gemini) may be the recommended action OR the primary subject of more than one section. This holds even when the angle differs — "use Perplexity to stress-test an idea" and "Perplexity, the research tool" both count as Perplexity and may not both appear. In particular, the Tip of the Week and the Tool of the Week must center on DIFFERENT tools
- No more than one section should have the same company or product as its primary subject. If one company had a big week, pick their single most useful story for your audience and use it once; find the best content from other sources for the rest
- The content sections together should feel like different windows into the AI world this week — different tools, different use cases, different sources, different kinds of readers served

Before you finish, re-read your full draft and verify four things: (1) no tool or app is recommended or featured in more than one section, (2) no source item ID is used in more than one section, (3) each section is a genuinely different story, and (4) no single event appears in both the intro and a section (or in two sections). If any check fails, replace the weaker section with different content drawn from the source material.

Length and focus rules — the newsletter must be short enough that a busy reader actually finishes it and acts:
- This is an actionable newsletter. One thing a reader will actually do beats five things they never will. Do not pad.
- Keep the whole newsletter tight — aim for roughly a 3-minute read. Be ruthless about cutting anything that isn't directly useful.
- The Tip of the Week is the hero. Give it room. Keep every other section lean.
"""

_PROMPT_SECTION = """## 💡 Prompt of the Week
One prompting technique with the EXACT prompt someone can copy-paste into ChatGPT, Claude, or any AI assistant. Explain what it does and when to use it in a sentence or two — keep the prose lean, let the prompt do the work. The prompt itself should be in a code block. End with a line containing ONLY the item ID you drew from, exactly like this: SOURCE_ID: S12 (use the real ID). Do not write a source name or URL yourself."""

_WORKFLOW_SECTION = """## 🔓 Workflow Unlock
One concrete way to use AI differently in real work. Give specific steps, not vague advice. Example of good: "Open [tool], paste your meeting notes, type [specific instruction], and you get [specific output]." Keep it tight — the steps, not a lecture. End with a line containing ONLY the item ID you drew from, exactly like this: SOURCE_ID: S12 (use the real ID). Do not write a source name or URL yourself."""

ROTATING_SECTIONS = {"prompt": _PROMPT_SECTION, "workflow": _WORKFLOW_SECTION}


def build_newsletter_format(rotating: str = "prompt") -> str:
    rotating_section = ROTATING_SECTIONS.get(rotating, _PROMPT_SECTION)
    return f"""
## From the Editor

*[Write your intro here — 2-4 sentences. A reaction, something you noticed, or anything on your mind this week related to AI. Not a tip — just your voice.]*

*— [Your name]*

---

## ⚡ The Alpha — Tip of the Week
The single best actionable insight this week, and the hero of the issue — give it room. One thing someone can use today. Must be specific — not "AI can help you write better" but HOW to do it step by step. End with a line containing ONLY the item ID you drew from, exactly like this: SOURCE_ID: S12 (use the real ID). Do not write a source name or URL yourself.

## 🛠 Tool of the Week
One specific AI tool. What it does in one sentence, exactly how to use it right now (specific steps), and who it's most useful for. Keep it lean. No hype words like "revolutionary" or "game-changing". End with a line containing ONLY the item ID you drew from, exactly like this: SOURCE_ID: S12 (use the real ID). Do not write a source name or URL yourself.

{rotating_section}

## 📡 Signal vs Noise
Keep this section short — about two sentences for each half.
SIGNAL: One thing happening in AI right now that non-technical people should actually pay attention to, and in one sentence why it matters to them personally. End with a line containing ONLY the item ID you drew from, exactly like this: SOURCE_ID: S12 (use the real ID). Do not write a source name or URL yourself.
NOISE: One thing that sounds important but isn't actionable yet for regular people — tell them to ignore it for now and why, briefly. If sourced from Reddit, explicitly note it is community discussion, not a verified report. End with a line containing ONLY the item ID you drew from, exactly like this: SOURCE_ID: S12 (use the real ID). Do not write a source name or URL yourself.
""".strip()


def _format_sources_with_ids(sources_dict: dict) -> tuple[str, dict]:
    """Format the raw source material for the model AND build a registry mapping
    each item to a stable ID (S1, S2, ...). The model cites the ID it used; we
    substitute the real source name + URL afterward (see resolve_citations), so a
    citation is always correct and can't be confabulated. Returns (text, registry)
    where registry maps "S<n>" -> {"source", "url", "title"}."""
    lines = []
    registry: dict[str, dict] = {}
    counter = 0
    for source_name, items in sources_dict.items():
        if not isinstance(items, list) or not items:
            continue
        lines.append(f"\n### {source_name}")
        for item in items:
            counter += 1
            item_id = f"S{counter}"
            registry[item_id] = {
                "source": source_name,
                "url": item.get("url", ""),
                "title": item.get("title", ""),
            }
            date_str = f" [{item['date']}]" if item.get("date") and item["date"] != "unknown" else ""
            lines.append(f"[{item_id}] **{item['title']}**{date_str}")
            if item.get("signal"):
                lines.append(f"(Engagement: {item['signal']})")
            if item.get("text"):
                lines.append(item["text"])
            lines.append(f"(cite this item as SOURCE_ID: {item_id})")
            lines.append("")
    return "\n".join(lines), registry


_SOURCE_ID_TOKEN = re.compile(r"\*{0,2}\s*SOURCE_ID:\s*\[?\s*S?(\d+)\s*\]?\s*\*{0,2}", re.IGNORECASE)


def resolve_citations(newsletter: str, registry: dict) -> tuple[str, list[str], list[str]]:
    """Replace each `SOURCE_ID: S<n>` token the model emitted with the real
    `*Source: <name> — <url>*` line looked up from the registry. Returns
    (resolved_text, source_names_used_in_order, violations). Violations flag an
    unknown ID or the same source cited in more than one section — the caller can
    use them to trigger a re-roll."""
    used: list[str] = []
    violations: list[str] = []

    def _sub(match: re.Match) -> str:
        item_id = f"S{match.group(1)}"
        entry = registry.get(item_id)
        if not entry:
            violations.append(f"cited an unknown item ID ({item_id})")
            return "*Source: (unverified)*"
        used.append(entry["source"])
        url = entry["url"]
        return f"*Source: {entry['source']} — {url}*" if url else f"*Source: {entry['source']}*"

    resolved = _SOURCE_ID_TOKEN.sub(_sub, newsletter)

    seen = set()
    for name in used:
        if name in seen:
            violations.append(f"source '{name}' is cited in more than one section")
        seen.add(name)

    return resolved, used, violations


def detect_story_overlap(newsletter: str, cost_log: CostLog | None = None) -> list[str]:
    """Ask the model whether any two sections (including the editor intro) lean on
    the same underlying story/event or feature the same tool. Different source
    names can still be the same story on a big-news week, which the mechanical
    source-dedup can't catch. Returns a list of short violation strings ([] if
    clean or on any failure — a bad check never blocks the pipeline)."""
    client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
    instruction = (
        "You are a strict editor checking a finished newsletter for repetition. "
        "Read it and report ONLY genuine problems where two different sections "
        "(count the 'From the Editor' intro as a section) are built on the SAME "
        "underlying news event/story, OR feature the SAME named tool as their "
        "primary subject. Reframing one story two ways counts. Return a JSON array "
        "of short strings, each naming the two sections and the shared story/tool. "
        "If there is no real overlap, return []. Return ONLY the JSON array.\n\n"
        f"Newsletter:\n{newsletter}"
    )
    try:
        resp = client.messages.create(
            model=MODEL,
            max_tokens=400,
            thinking=NO_THINKING,
            messages=[{"role": "user", "content": instruction}],
        )
        if cost_log is not None:
            cost_log.add(CostEntry(
                api="anthropic",
                model=MODEL,
                detail="variety check",
                input_tokens=resp.usage.input_tokens,
                output_tokens=resp.usage.output_tokens,
            ))
        text = resp.content[0].text.strip()
        text = re.sub(r"^```(?:json)?|```$", "", text, flags=re.MULTILINE).strip()
        parsed = json.loads(text)
        return [str(x) for x in parsed if str(x).strip()]
    except Exception as e:
        print(f"  Variety check failed (non-fatal): {e}")
        return []


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


def _load_recent_coverage(path: str = COVERAGE_PATH, days: int = COVERAGE_LOOKBACK_DAYS) -> str:
    """Return a dated bullet list of use cases covered in the last `days` so the
    editor can steer away from them. Empty string if the ledger is missing/empty.
    Entries are {"date": "YYYY-MM-DD", "covered": ["...", ...]}."""
    if not os.path.exists(path):
        return ""
    try:
        with open(path, "r", encoding="utf-8") as f:
            ledger = json.load(f)
    except (json.JSONDecodeError, OSError):
        return ""

    cutoff = date.today() - timedelta(days=days)
    lines = []
    for entry in ledger:
        try:
            entry_date = datetime.strptime(entry.get("date", ""), "%Y-%m-%d").date()
        except ValueError:
            continue
        if entry_date < cutoff:
            continue
        for item in entry.get("covered", []):
            lines.append(f"- ({entry['date']}) {item}")
    return "\n".join(lines)


def extract_coverage(newsletter: str, cost_log: CostLog | None = None) -> list[str]:
    """Distill a finished issue into a few short 'use case' lines for the ledger.
    Returns [] on any failure so a bad extraction never blocks the pipeline."""
    client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
    instruction = (
        "Distill this published newsletter issue into a compact coverage record so "
        "future issues can avoid repeating the same use cases. For each main section "
        "(Tip of the Week, Tool of the Week, the Prompt/Workflow slot, and each half of "
        "Signal vs Noise), output ONE short line capturing the SPECIFIC use case or "
        "advice — the action a reader takes, not just the tool name. Format each line as "
        "\"<section>: <use case in 12 words or fewer> (tool: <tool or n/a>)\". "
        "Return ONLY a JSON array of strings, nothing else.\n\n"
        f"Newsletter:\n{newsletter}"
    )
    try:
        resp = client.messages.create(
            model=MODEL,
            max_tokens=500,
            thinking=NO_THINKING,
            messages=[{"role": "user", "content": instruction}],
        )
        if cost_log is not None:
            cost_log.add(CostEntry(
                api="anthropic",
                model=MODEL,
                detail="coverage extraction",
                input_tokens=resp.usage.input_tokens,
                output_tokens=resp.usage.output_tokens,
            ))
        text = resp.content[0].text.strip()
        text = re.sub(r"^```(?:json)?|```$", "", text, flags=re.MULTILINE).strip()
        covered = json.loads(text)
        return [str(x) for x in covered if str(x).strip()]
    except Exception as e:
        print(f"  Coverage extraction failed (non-fatal): {e}")
        return []


def _stream_once(client, system_prompt: str, user_prompt: str, cost_log: CostLog | None) -> str:
    """Stream one synthesis pass and return the raw text (with SOURCE_ID tokens)."""
    with client.messages.stream(
        model=MODEL,
        max_tokens=4096,
        thinking=NO_THINKING,
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


def synthesize(sources_dict: dict, cost_log: CostLog | None = None, rotating: str = "prompt") -> str:
    client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])

    formatted_content, registry = _format_sources_with_ids(sources_dict)
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

    recent_coverage = _load_recent_coverage()
    if recent_coverage:
        system_prompt += (
            "\n\nAlready covered in the last 3 months — do NOT repeat these use cases, "
            "prompts, or hero tools, even pointed at a different tool. The repeating "
            "ACTION is what to avoid: bring genuinely new angles this week.\n"
            + recent_coverage
        )
        print(f"Applied {recent_coverage.count(chr(10)) + 1} recent coverage line(s) from coverage.json")

    newsletter_format = build_newsletter_format(rotating)

    user_prompt = f"""Here is this week's raw content pulled from AI newsletters and communities. Each item is labeled with an ID like [S12]:

{formatted_content}

---

Now write this week's Alpha AI newsletter. Use only the content above as your source material. Follow exactly this format:

{newsletter_format}

Write the full newsletter now."""

    # First pass, then up to MAX_VARIETY_RETRIES re-rolls if the draft repeats a
    # source or a story. Resolving citations from item IDs (rather than trusting
    # the model to write URLs) also guarantees every source line is correct.
    prompt = user_prompt
    resolved = ""
    for attempt in range(MAX_VARIETY_RETRIES + 1):
        raw = _stream_once(client, system_prompt, prompt, cost_log)
        resolved, _used, dup_violations = resolve_citations(raw, registry)
        story_violations = detect_story_overlap(resolved, cost_log)
        violations = dup_violations + story_violations
        if not violations or attempt == MAX_VARIETY_RETRIES:
            if violations:
                print(f"\nVariety issues remain after retry (surfacing, not blocking): {violations}")
            return resolved
        print(f"\nVariety issues detected, re-rolling once: {violations}")
        prompt = user_prompt + (
            "\n\nYour previous draft had these problems:\n- "
            + "\n- ".join(violations)
            + "\n\nRewrite the full newsletter fixing them. Each section must use a "
            "DIFFERENT source item ID and a genuinely different underlying story, "
            "and no single event may appear in both the intro and a section."
        )

    return resolved
