import json
import os
import re
from datetime import date, datetime, timedelta

import anthropic

from costs import CostEntry, CostLog

MODEL = "claude-opus-4-8"
# We keep thinking OFF for these straightforward jobs to preserve cost/latency.
# On Opus 4.8 omitting `thinking` already means no thinking, but we disable it
# explicitly for clarity.
NO_THINKING = {"type": "disabled"}
FEEDBACK_PATH = "FEEDBACK.md"
COVERAGE_PATH = "coverage.json"
COVERAGE_LOOKBACK_DAYS = 90  # how far back to remember covered use cases (~3 months)
MAX_VARIETY_RETRIES = 1  # one re-roll if the roundup draft repeats a source or a story

# Shared description of who we serve. Both the weekly briefing (research
# assistant) and the roundup draft (editor's drafting assistant) select
# against it.
_AUDIENCE = """The reader is someone whose job runs on thinking, communicating, and organizing: the SMB owner prepping for a board meeting, the teacher planning next week's lessons, the mid-career manager trying to do more with less, the early-career professional trying to stand out. They are not developers. They are not AI researchers. They know AI is a thing and they want to actually use it — not just read about it.

The common thread across all readers: their work is 80% communication, judgment, and organization. That's exactly where AI is most useful right now. A practical item must pass this test: could a busy professional use it before tomorrow morning, with no setup and no technical background? A news item must pass a different test: will this plausibly touch a regular person's work, money, or daily tools — not just excite people who follow the AI industry?"""

BRIEFING_SYSTEM_PROMPT = f"""You are the research assistant for Alpha AI Roundup, a digest of practical AI tips and relevant AI news for knowledge workers who want to use AI to level up — without becoming technical.

{_AUDIENCE}

Your job is NOT to write the newsletter. A human editor writes each issue by hand, working from your weekly briefings. Your job is to scan this week's raw material and pull out the strongest CANDIDATES for the editor to pick from later, in two lanes:

1. Practical items (type "tip", "tool", "prompt", or "workflow") — something the reader can do
2. News items (type "news") — a real development a regular person should know about (a policy change, a platform shift, a new capability arriving in tools they already use). Not benchmark drama, not funding rounds, not model-release hype

Selection rules:
- Every practical item must be immediately usable by someone with no technical background
- No market commentary, funding rounds, valuations, or stock prices
- No developer-only tools, APIs, or anything requiring code
- Specific beats general: "use ChatGPT to do X by doing Y and Z" beats "AI can help with productivity"
- Frame through real work: emails, meetings, decisions, planning, communication, learning
- Reddit and Hacker News posts are community discussion, not journalism. A practical candidate drawn from them must be an idea worth trying, never a factual claim; a news candidate must never rest on a Reddit/HN post alone
- Some items include an "(Engagement: ...)" line — a Reddit top-of-week rank, or Hacker News points and comments. High engagement is a signal of what's resonating, but audience fit always overrides raw popularity
- Aim for roughly two thirds practical items and one third news when the week supports it; fewer candidates is fine on a thin week. Quality over quantity

Accuracy rules — non-negotiable:
- The summary must capture the item's core so the editor never has to re-read the full source: for practical items, the concrete steps and any copy-pastable prompt verbatim; for news items, what actually happened and who it affects
- Never include a statistic, percentage, or numerical claim unless it appears verbatim in the source material
- A candidate must be grounded in exactly one source item; its "id" is that item's ID

Output ONLY a JSON array — no prose, no code fences. Each element:
{{"id": "S12", "type": "tip" | "tool" | "prompt" | "workflow" | "news", "title": "<short concrete headline>", "summary": "<3-6 sentences; steps/prompt verbatim for practical items, what-happened for news>", "why": "<one line: why a busy non-technical professional would care>", "score": <1-10 value for this reader>}}"""


def _build_roundup_system_prompt(tips: int, news: int) -> str:
    return f"""You are the drafting assistant for Alpha AI Roundup, a digest of practical AI tips and relevant AI news written for knowledge workers who want to use AI to level up — without becoming technical.

{_AUDIENCE}

You are given several weeks of pre-screened candidates in two lanes: practical items (tips, tools, prompts, workflows) and news items. Write the body sections of this issue — and ONLY those sections. The human editor writes the title, the intro, and the personal "my take" notes. Never write an intro, a sign-off, or address the reader as "we".

Output structure — follow it exactly:
1. Exactly {tips} practical sections. Each starts with a `## ` heading — a short, concrete headline (no emoji, no "Tip of the Week" labels)
2. Then one section headed exactly `## Worth knowing`, containing up to {news} news items, each under a `### ` heading with 2-4 sentences on what happened and who it touches

Selection rules:
- Pick the STRONGEST candidates for this reader. A theme that kept resurfacing across several weeks is a good signal, but pick one best expression of it
- Practical sections come only from practical candidates; Worth knowing items only from news candidates
- All chosen sections must be genuinely different: different tools, different underlying stories, different use cases, different sources. No single named tool or app may be the recommended action or primary subject of more than one section

Writing rules:
- Write like a smart friend explaining things over coffee, not a press release
- Practical sections give specific steps someone can follow today; if the candidate includes a copy-paste prompt, present it in a code block
- News items report what happened plainly and stop — the editor adds the judgment, so do not editorialize about what it means
- No hype words like "revolutionary" or "game-changing"; no jargon without a plain-English explanation
- Keep the whole body to roughly a 3-minute read. One thing a reader will actually do beats five things they never will

Accuracy rules — non-negotiable:
- Use only what is in the candidate material below. Never add statistics, features, or claims that are not there
- End each practical section and each news item with a line containing ONLY the candidate ID you drew from, exactly like this: SOURCE_ID: S12 (use the real ID). Do not write source names or URLs yourself — the system fills in the correct link from the ID, so a citation is only ever right if the ID genuinely matches the content you wrote"""


def _format_sources_with_ids(sources_dict: dict) -> tuple[str, dict]:
    """Format the raw source material for the model AND build a registry mapping
    each item to a stable ID (S1, S2, ...). The model cites the ID it used; we
    substitute the real source name + URL afterward (see resolve_citations), so a
    citation is always correct and can't be confabulated. Returns (text, registry)
    where registry maps "S<n>" -> {"source", "url", "title", "date", "text"}."""
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
                "date": item.get("date", ""),
                "text": item.get("text", ""),
            }
            date_str = f" [{item['date']}]" if item.get("date") and item["date"] != "unknown" else ""
            lines.append(f"[{item_id}] **{item['title']}**{date_str}")
            if item.get("signal"):
                lines.append(f"(Engagement: {item['signal']})")
            if item.get("text"):
                lines.append(item["text"])
            lines.append(f"(this item's ID is {item_id})")
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


def detect_story_overlap(draft: str, cost_log: CostLog | None = None) -> list[str]:
    """Ask the model whether any two sections lean on the same underlying
    story/event or feature the same tool. Different source names can still be the
    same story, which the mechanical source-dedup can't catch. Returns a list of
    short violation strings ([] if clean or on any failure — a bad check never
    blocks the pipeline)."""
    client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
    instruction = (
        "You are a strict editor checking a draft for repetition. Read it and "
        "report ONLY genuine problems where two different sections (a `##` tip "
        "section or a `###` news item both count as sections) are built on the "
        "SAME underlying news event/story, OR feature the SAME named tool as "
        "their primary subject. Reframing one story two ways counts. Return a "
        "JSON array of short strings, each naming the two sections and the "
        "shared story/tool. If there is no real overlap, return []. Return ONLY "
        "the JSON array.\n\n"
        f"Draft:\n{draft}"
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


def extract_coverage(issue_text: str, cost_log: CostLog | None = None) -> list[str]:
    """Distill a finished roundup draft into a few short 'use case' lines for the
    ledger. Returns [] on any failure so a bad extraction never blocks the run."""
    client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
    instruction = (
        "Distill this issue into a compact coverage record so future issues can "
        "avoid repeating the same use cases. For EACH tip section and EACH item "
        "under 'Worth knowing', output ONE short line capturing the SPECIFIC use "
        "case, advice, or news story — the action a reader takes or the event "
        "reported, not just the tool name. Ignore intro placeholders, 'my take' "
        "placeholders, and any runners-up list. Format each line as "
        "\"<section>: <use case in 12 words or fewer> (tool: <tool or n/a>)\". "
        "Return ONLY a JSON array of strings, nothing else.\n\n"
        f"Issue:\n{issue_text}"
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


def _parse_candidates(text: str, registry: dict, max_candidates: int) -> list[dict]:
    """Parse the briefing model's JSON array and join each candidate with its
    registry entry (verified source name/URL, plus the raw excerpt the roundup
    step will need). Unknown IDs are dropped, scores clamped to 1-10. Raises
    ValueError if the text isn't a JSON array at all — the caller retries."""
    cleaned = re.sub(r"^```(?:json)?|```$", "", text.strip(), flags=re.MULTILINE).strip()
    parsed = json.loads(cleaned)  # JSONDecodeError is a ValueError
    if not isinstance(parsed, list):
        raise ValueError("model output was JSON but not an array")

    candidates = []
    for c in parsed:
        if not isinstance(c, dict):
            continue
        entry = registry.get(str(c.get("id", "")).strip())
        if not entry:
            print(f"  Dropping candidate with unknown item ID: {c.get('id')!r}")
            continue
        try:
            score = max(1, min(10, int(c.get("score", 5))))
        except (TypeError, ValueError):
            score = 5
        candidates.append({
            "type": str(c.get("type", "tip")).strip().lower() or "tip",
            "title": str(c.get("title", "")).strip() or entry["title"],
            "summary": str(c.get("summary", "")).strip(),
            "why": str(c.get("why", "")).strip(),
            "score": score,
            "source": entry["source"],
            "url": entry["url"],
            "date": entry.get("date", ""),
            "text": entry.get("text", ""),
        })
    candidates.sort(key=lambda c: c["score"], reverse=True)
    return candidates[:max_candidates]


def distill_candidates(sources_dict: dict, cost_log: CostLog | None = None,
                       max_candidates: int = 8) -> list[dict]:
    """Weekly research-assistant pass: scan the week's raw material and return the
    top candidates (practical items + news) as structured dicts. One retry if the
    model doesn't return valid JSON; raises after that so the failure is visible
    in the Actions log instead of an empty briefing shipping silently."""
    client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])

    formatted_content, registry = _format_sources_with_ids(sources_dict)
    total_sources = sum(len(v) for v in sources_dict.values() if v)
    print(f"Sending {total_sources} items to Claude for briefing distillation...")

    system_prompt = BRIEFING_SYSTEM_PROMPT + f"\n\nReturn at most {max_candidates} candidates."
    user_prompt = (
        "Here is this week's raw content pulled from AI newsletters and communities. "
        f"Each item is labeled with an ID like [S12]:\n\n{formatted_content}\n\n---\n\n"
        "Select this week's candidates now. Return ONLY the JSON array."
    )

    for attempt in range(2):
        resp = client.messages.create(
            model=MODEL,
            max_tokens=4000,
            thinking=NO_THINKING,
            system=system_prompt,
            messages=[{"role": "user", "content": user_prompt}],
        )
        if cost_log is not None:
            cost_log.add(CostEntry(
                api="anthropic",
                model=MODEL,
                detail="briefing distillation",
                input_tokens=resp.usage.input_tokens,
                output_tokens=resp.usage.output_tokens,
            ))
        try:
            candidates = _parse_candidates(resp.content[0].text, registry, max_candidates)
            practical = sum(1 for c in candidates if c["type"] != "news")
            print(f"Kept {len(candidates)} candidate(s): {practical} practical, {len(candidates) - practical} news")
            return candidates
        except ValueError as e:
            print(f"  Briefing output was not a valid JSON array ({e}); retrying once")
            user_prompt += "\n\nYour previous reply was not a valid JSON array. Return ONLY the JSON array."

    raise RuntimeError("briefing distillation failed: model did not return a valid JSON array")


def _stream_once(client, system_prompt: str, user_prompt: str, cost_log: CostLog | None) -> str:
    """Stream one drafting pass and return the raw text (with SOURCE_ID tokens)."""
    with client.messages.stream(
        model=MODEL,
        max_tokens=4096,
        thinking=NO_THINKING,
        system=system_prompt,
        messages=[{"role": "user", "content": user_prompt}],
    ) as stream:
        draft = ""
        for text in stream.text_stream:
            print(text, end="", flush=True)
            draft += text
        final = stream.get_final_message()

    if cost_log is not None:
        cost_log.add(CostEntry(
            api="anthropic",
            model=MODEL,
            detail="roundup draft",
            input_tokens=final.usage.input_tokens,
            output_tokens=final.usage.output_tokens,
        ))
    print("\n")
    return draft


# Editor slots inserted mechanically after each verified source line, so the
# wording is always identical and the model never gets to write "your" voice.
TIP_TAKE_PLACEHOLDER = "> **My take:** *[Tried it? One or two lines — or delete this line.]*"
NEWS_TAKE_PLACEHOLDER = "**My take:** *[Your judgment call — what should a regular person make of this? This is the section where your commentary carries the issue.]*"
WORTH_KNOWING_HEADING = "## Worth knowing"


def synthesize_roundup(candidates: list[dict], cost_log: CostLog | None = None,
                       tips: int = 3, news: int = 2, runners_up: int = 5) -> str:
    """Turn the accumulated candidates into the body of a roundup draft: the
    strongest practical tips, a 'Worth knowing' news section, editor placeholders
    under every item, and a mechanical runners-up shortlist. The title, intro
    slot, and transparency line are added by the caller."""
    client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])

    registry = {}
    lines = []
    for i, c in enumerate(candidates, 1):
        cid = f"S{i}"
        registry[cid] = {"source": c["source"], "url": c.get("url", ""), "title": c.get("title", "")}
        lane = "NEWS" if c.get("type") == "news" else "PRACTICAL"
        header = f"[{cid}] ({lane}) **{c.get('title', '(untitled)')}** (type: {c.get('type', 'tip')}, score {c.get('score', '?')}, from {c['source']}"
        if c.get("date") and c["date"] != "unknown":
            header += f", {c['date']}"
        lines.append(header + ")")
        if c.get("why"):
            lines.append(f"Why it matters: {c['why']}")
        if c.get("summary"):
            lines.append(f"Summary: {c['summary']}")
        excerpt = (c.get("text") or "").strip()
        if excerpt:
            lines.append("Source excerpt:")
            lines.append(excerpt[:1200])
        lines.append(f"(cite this candidate as SOURCE_ID: {cid})")
        lines.append("")
    candidate_blob = "\n".join(lines)

    system_prompt = _build_roundup_system_prompt(tips, news)
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
            "\n\nAlready covered in recent issues — do NOT repeat these use cases, "
            "prompts, stories, or hero tools, even pointed at a different tool. The "
            "repeating ACTION is what to avoid: bring genuinely new angles this issue:\n"
            + recent_coverage
        )
        print(f"Applied {recent_coverage.count(chr(10)) + 1} recent coverage line(s) from coverage.json")

    user_prompt = (
        "Here are the candidates accumulated since the last issue, each labeled "
        f"with an ID like [S3]:\n\n{candidate_blob}\n\n---\n\n"
        "Write the issue body now — the practical sections, then Worth knowing. Nothing else."
    )

    prompt = user_prompt
    resolved, used_ids = "", []
    for attempt in range(MAX_VARIETY_RETRIES + 1):
        raw = _stream_once(client, system_prompt, prompt, cost_log)
        used_ids = [f"S{m.group(1)}" for m in _SOURCE_ID_TOKEN.finditer(raw)]
        resolved, _used, dup_violations = resolve_citations(raw, registry)
        story_violations = detect_story_overlap(resolved, cost_log)
        violations = dup_violations + story_violations
        if not violations or attempt == MAX_VARIETY_RETRIES:
            if violations:
                print(f"\nVariety issues remain after retry (surfacing, not blocking): {violations}")
            break
        print(f"\nVariety issues detected, re-rolling once: {violations}")
        prompt = user_prompt + (
            "\n\nYour previous draft had these problems:\n- "
            + "\n- ".join(violations)
            + "\n\nRewrite the issue body fixing them. Each section must use a "
            "DIFFERENT candidate ID and a genuinely different underlying story and tool."
        )

    # Insert the editor's slot after every verified source line — the short one
    # under tips, the judgment-sized one under Worth knowing items.
    parts = resolved.split("\n" + WORTH_KNOWING_HEADING, 1)
    parts[0] = re.sub(r"(\*Source:[^\n]*\*)", lambda m: m.group(1) + "\n\n" + TIP_TAKE_PLACEHOLDER, parts[0])
    if len(parts) == 2:
        parts[1] = re.sub(r"(\*Source:[^\n]*\*)", lambda m: m.group(1) + "\n\n" + NEWS_TAKE_PLACEHOLDER, parts[1])
        resolved = parts[0] + "\n" + WORTH_KNOWING_HEADING + parts[1]
    else:
        resolved = parts[0]

    # Runners-up: best unused candidates, rendered mechanically (no model call)
    # so the titles and links are exactly what the briefings recorded.
    used = set(used_ids)
    leftovers = [c for i, c in enumerate(candidates, 1) if f"S{i}" not in used]
    leftovers.sort(key=lambda c: c.get("score") or 0, reverse=True)
    bullets = []
    for c in leftovers[:runners_up]:
        src = f"[{c['source']}]({c['url']})" if c.get("url") else c["source"]
        hook = c.get("why") or c.get("summary", "")
        bullets.append(f"- **{c.get('title', '(untitled)')}** — {hook} *({src})*")
    if bullets:
        resolved = resolved.rstrip() + (
            "\n\n---\n\n## Also worth a look\n\n"
            "*[Runners-up from the same period — keep any that grab you, or delete this section.]*\n\n"
            + "\n".join(bullets) + "\n"
        )

    return resolved
