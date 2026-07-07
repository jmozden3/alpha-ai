"""Fast, offline tests for the synthesis guardrails — no network, no API key.

Run directly:  python test_synthesis.py

Covers the two pieces of logic most likely to regress silently:
  1. Citation resolution — the model cites an item ID, we substitute the real
     source + URL, and duplicate/unknown citations are flagged.
  2. The Reddit AI-relevance gate — general subs only pass AI posts through,
     without false-matching everyday words like "email" or "again".
"""

from sources import _is_ai_relevant
from synthesize import resolve_citations, _format_sources_with_ids


def test_format_assigns_ids():
    sources = {
        "OpenAI": [{"title": "New feature", "text": "x", "url": "https://openai.com/a", "date": "2026-07-01"}],
        "r/ChatGPT": [{"title": "Cool trick", "text": "y", "url": "https://reddit.com/b", "date": "2026-07-02", "signal": "#1 top post"}],
    }
    text, reg = _format_sources_with_ids(sources)
    assert "[S1]" in text and "[S2]" in text
    assert reg["S1"]["source"] == "OpenAI"
    assert reg["S2"]["url"] == "https://reddit.com/b"


def _registry():
    return {
        "S1": {"source": "OpenAI", "url": "https://openai.com/a", "title": "t1"},
        "S2": {"source": "r/ChatGPT", "url": "https://reddit.com/b", "title": "t2"},
    }


def test_resolve_happy_path():
    draft = "## Tip\nDo it.\nSOURCE_ID: S1\n\n## Tool\nUse it.\nSOURCE_ID: S2\n"
    resolved, used, viol = resolve_citations(draft, _registry())
    assert "*Source: OpenAI — https://openai.com/a*" in resolved
    assert "*Source: r/ChatGPT — https://reddit.com/b*" in resolved
    assert "SOURCE_ID" not in resolved
    assert used == ["OpenAI", "r/ChatGPT"]
    assert viol == []


def test_resolve_flags_duplicate_source():
    _, _, viol = resolve_citations("A\nSOURCE_ID: S1\n\nB\nSOURCE_ID: S1\n", _registry())
    assert any("more than one section" in v for v in viol)


def test_resolve_flags_unknown_id():
    resolved, _, viol = resolve_citations("A\nSOURCE_ID: S99\n", _registry())
    assert "(unverified)" in resolved
    assert any("unknown item ID" in v for v in viol)


def test_resolve_tolerates_token_variants():
    for tok in ("SOURCE_ID: [S1]", "*SOURCE_ID: S1*", "source_id: s1"):
        resolved, _, _ = resolve_citations("X\n" + tok + "\n", _registry())
        assert "OpenAI" in resolved, tok


def test_ai_gate_matches_ai_posts():
    assert _is_ai_relevant("How I use ChatGPT to plan my week")
    assert _is_ai_relevant("Best AI tools for small business")
    assert _is_ai_relevant("An AI-powered workflow", "")
    assert _is_ai_relevant("automation saved me hours")
    assert _is_ai_relevant("trying GPT-5 for emails")


def test_ai_gate_ignores_everyday_words():
    assert not _is_ai_relevant("I sent an email again about the chair")
    assert not _is_ai_relevant("My retail store had a great quarter")
    assert not _is_ai_relevant("detailing my morning routine")


if __name__ == "__main__":
    passed = 0
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            print(f"  ok  {name}")
            passed += 1
    print(f"\n{passed} tests passed")
