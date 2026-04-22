# Reviewer Memory

Structured log of mistakes the Reviewer has made, kept so future invocations can skim and avoid repetition.

**Entry format (append new entries at the bottom):**

```
## <YYYY-MM-DD> — <one-line title>
**What I did:** ...
**Why it was wrong:** ...
**How to avoid:** ...
**Source:** <who caught it — Reviewer / scope_check / verify_claims / user>
```

Scripts auto-append entries for Builder on `scope_check` and `verify_claims` failures. Reviewer appends entries for Designer or Builder whenever it issues REJECTED.
