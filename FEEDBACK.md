# Newsletter Feedback

Your running notebook for steering the newsletter AI. It has two parts:

1. **Style guidance** — distilled do / don't rules. **The pipeline reads everything under the `## Style guidance` heading on every run and feeds it to the AI**, so edits here actually change future newsletters. Keep it short and concrete.
2. **Feedback log** — dated, freeform notes on specific issues (what landed, what didn't). Dump thoughts here freely; this part is *not* sent to the AI. Every so often, distill the recurring patterns up into Style guidance.

The flow: react to an issue → jot it in the log → when a pattern repeats, promote it to a Style guidance bullet → the AI picks it up on the next run.

---

## Style guidance

<!-- The newsletter AI reads everything under this heading on every run.
     Write short, concrete do/don't bullets. HTML comments like this are ignored. -->

### Do

- Keep the whole issue to about a 3-minute read. Longer issues didn't get acted on.

### Don't

- Don't reuse a use case or piece of advice we've already run, even with a different tool. The repeating *action* is the problem, not the tool: "use [tool] to pressure-test your idea" must not come back as the same idea wearing a different tool's name. Each issue's actions should be genuinely new angles, not old advice re-skinned.

<!-- Add things you don't want to see, e.g.:
- Don't recommend a tool unless it has a free tier a non-technical reader can start with today. -->

---

## Feedback log

<!-- Add a dated entry whenever you react to an issue. Copy the template below. -->

### 2026-06-17 — recurring use cases

- **Issue:** general pattern across recent issues
- **Didn't like:** the same underlying advice/use case keeps showing up over time, just pointed at a different tool (e.g. "use X to pressure-test your idea").
- **Change to make:** give the synthesizer a memory of what past issues already covered so it stops repeating use cases. Promoted to a Style guidance "Don't" bullet above. Implementing a "recently covered" feed from past newsletters (see below).

### YYYY-MM-DD — (template, copy me)

- **Issue:** week of YYYY-MM-DD
- **Liked:**
- **Didn't like:**
- **Change to make:**
