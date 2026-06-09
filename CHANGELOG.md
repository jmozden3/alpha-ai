# Changelog

A running, plain-language log of changes to the Alpha AI pipeline and *why* we made them. Newest first.

## 2026-06-09

- Shortened the newsletter to four content blocks plus the editor's note, with a rotating action slot (Prompt of the Week one week, Workflow Unlock the next), because we got reader feedback that the issues were too long. The point of the newsletter is actionable AI — one thing people actually do beats five they never get to.
- Trimmed the Signal vs Noise section to about two sentences per half, for the same length reason.
- Looked at a popular, similar open-source project (`last30days-skill`, which pulls from many sources and ranks them by real engagement) and borrowed two ideas from it:
  - Added **Hacker News** as a source.
  - Started passing **engagement signals** through to the AI — Reddit top-of-week rank, and Hacker News points and comments — so it can weight what's actually resonating instead of guessing.
- Fixed a quiet bug: the 7-day recency window was never enforced in code, only asked for in the prompt. Replaced it with newest-first sorting of each feed, so fresh items win the limited slots — without dropping feeds that only publish every couple of weeks.
- Hardened the diversity rules after a test run featured the same tool (Perplexity) in two different sections. Now no single tool or source can anchor more than one section, and the AI re-checks its own draft before finishing.
- Started this changelog and a `FEEDBACK.md` file. Feedback written in `FEEDBACK.md` is read by the pipeline on every run, so notes about what we like and don't like steer future newsletters over time.
