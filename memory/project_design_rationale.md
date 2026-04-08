---
name: Multi-agent design rationale
description: Why the project uses multiple specialized agents instead of one
type: project
---

The multi-agent architecture is specifically designed to overcome the **limited context window of a single agent**. Each agent (Architect, Designer, Reviewer, Builder, Debugger) handles only its scoped subtask, keeping context usage low and focused. A single agent running the full research loop would exhaust its context across a long experiment campaign.

**Why:** Context limits make a single-agent loop impractical for long-running, multi-experiment ML research.

A second design pillar is the **script layer**: every meaningful action (registering ideas, syncing status, submitting jobs, building the dashboard) is persisted to disk via CLI scripts rather than kept in agent memory. This makes the system resilient — if an agent crashes or a session ends, no work is lost. The next agent reads files and continues exactly where the last left off.

**How to apply:** When suggesting improvements, keep each agent's context footprint small and scoped. Prefer persisting state to disk via scripts over relying on agent memory. Avoid designs that require one agent to hold full research history in context.
