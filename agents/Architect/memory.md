# Architect Memory

Structured log of mistakes the Architect has made, kept so future invocations can skim and avoid repetition.

**Entry format (append new entries at the bottom):**

```
## <YYYY-MM-DD> — <one-line title>
**What I did:** ...
**Why it was wrong:** ...
**How to avoid:** ...
**Source:** <who caught it — Reviewer / scope_check / verify_claims / user>
```

Scripts auto-append entries for Builder on `scope_check` and `verify_claims` failures. Reviewer appends entries for Designer or Builder whenever it issues REJECTED.

---

## Findings

A cumulative log of concise observations from exploring `runs/`. The Architect appends here whenever it digs into a specific idea or design, so future invocations can skim past investigations without re-reading the same files.

**Entry format (append at the bottom):**

```
- <YYYY-MM-DD> runs/<idea_id>/<design_id>: <1–3 sentence factual observation>
```

Keep entries short and factual — observations only, not speculation.

---

## Literature

A cumulative log of web/arxiv searches the Architect has run. Skim before searching — if a recent entry covers the topic, reuse it instead of re-searching. Log even null results so the next Architect doesn't repeat empty searches.

**Entry format (append at the bottom):**

```
- <YYYY-MM-DD> <topic>: <1-line takeaway> [link]
```

Budget per Architect invocation: 1–3 searches, at most 2 abstracts fetched. The point is to expand the hypothesis space, not write a survey.
