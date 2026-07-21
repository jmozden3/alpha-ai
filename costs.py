# costs.py — centralized cost tracking for all APIs used in the pipeline.
# Add a new entry to PRICING when a new API/model is introduced.

from dataclasses import dataclass, field
from datetime import date

PRICING = {
    # Anthropic — per million tokens
    "anthropic": {
        "claude-sonnet-5":   {"input_per_m": 3.00, "output_per_m": 15.00},  # intro $2/$10 through 2026-08-31; using sticker rate
        "claude-sonnet-4-6": {"input_per_m": 3.00, "output_per_m": 15.00},
        "claude-opus-4-6":   {"input_per_m": 5.00, "output_per_m": 25.00},
        "claude-opus-4-8":   {"input_per_m": 5.00, "output_per_m": 25.00},
    },
    # OpenAI Whisper — per minute of audio
    "openai": {
        "whisper-1": {"per_minute": 0.006},
    },
}


@dataclass
class CostEntry:
    api: str
    model: str
    detail: str          # human-readable label, e.g. source name for whisper
    input_tokens: int = 0
    output_tokens: int = 0
    audio_minutes: float = 0.0

    @property
    def cost(self) -> float:
        p = PRICING.get(self.api, {}).get(self.model, {})
        if "input_per_m" in p:
            return (self.input_tokens / 1_000_000 * p["input_per_m"] +
                    self.output_tokens / 1_000_000 * p["output_per_m"])
        if "per_minute" in p:
            return self.audio_minutes * p["per_minute"]
        return 0.0


@dataclass
class CostLog:
    run_date: str = field(default_factory=lambda: date.today().strftime("%Y-%m-%d"))
    entries: list = field(default_factory=list)

    def add(self, entry: CostEntry):
        self.entries.append(entry)

    @property
    def total(self) -> float:
        return sum(e.cost for e in self.entries)

    def print_summary(self):
        print("\n" + "=" * 40)
        print(f"  Cost Summary — {self.run_date}")
        print("=" * 40)
        for e in self.entries:
            if e.input_tokens or e.output_tokens:
                # Missing price rows must never kill the run — the pipeline has
                # already generated the newsletter by the time this prints.
                p = PRICING.get(e.api, {}).get(e.model, {})
                print(f"\n  {e.api.title()} / {e.model} ({e.detail})")
                if "input_per_m" in p:
                    print(f"    Input tokens:  {e.input_tokens:>8,}  (${e.input_tokens / 1_000_000 * p['input_per_m']:.4f})")
                    print(f"    Output tokens: {e.output_tokens:>8,}  (${e.output_tokens / 1_000_000 * p['output_per_m']:.4f})")
                else:
                    print(f"    Input tokens:  {e.input_tokens:>8,}  (unknown pricing — add {e.api}/{e.model} to PRICING)")
                    print(f"    Output tokens: {e.output_tokens:>8,}")
            elif e.audio_minutes:
                print(f"\n  {e.api.title()} / {e.model} ({e.detail})")
                print(f"    Audio:         {e.audio_minutes:>7.1f} min  (${e.cost:.4f})")
        print(f"\n  {'Total run cost:':30s} ${self.total:.4f}")
        print("=" * 40 + "\n")

    def to_html(self) -> str:
        rows = ""
        for e in self.entries:
            if e.input_tokens or e.output_tokens:
                rows += f"<tr><td>{e.api.title()} / {e.model}</td><td>{e.input_tokens:,}</td><td>{e.output_tokens:,}</td><td>${e.cost:.4f}</td></tr>"
            elif e.audio_minutes:
                rows += f"<tr><td>{e.api.title()} / {e.model} ({e.detail})</td><td colspan='2'>{e.audio_minutes:.1f} min</td><td>${e.cost:.4f}</td></tr>"
        return f"""
        <table border='1' cellpadding='6' cellspacing='0' style='border-collapse:collapse;font-family:monospace;'>
          <tr style='background:#f0f0f0;'><th>Service</th><th>Input tokens</th><th>Output tokens</th><th>Cost</th></tr>
          {rows}
          <tr style='font-weight:bold;background:#fff3cd;'><td colspan='3'>Total run cost</td><td>${self.total:.4f}</td></tr>
        </table>"""

    def append_to_file(self, path: str = "costs.log"):
        with open(path, "a", encoding="utf-8") as f:
            f.write(f"{self.run_date}")
            for e in self.entries:
                if e.input_tokens or e.output_tokens:
                    f.write(f" | {e.api}/{e.model} in={e.input_tokens} out={e.output_tokens} ${e.cost:.4f}")
                elif e.audio_minutes:
                    f.write(f" | {e.api}/{e.model} {e.audio_minutes:.1f}min ${e.cost:.4f}")
            f.write(f" | TOTAL ${self.total:.4f}\n")
