# `.agent/` — Agent Governance

This directory defines **who may change this repository, in what format, and under which
rules**.

| File | Purpose |
|---|---|
| [`agent.md`](agent.md) | The standard agent definition format, lifecycle, boundaries, and the binding rules every agent obeys |
| [`skills/skill-dictionary.md`](skills/skill-dictionary.md) | The project skill dictionary. **Currently awaiting population** — skill definitions arrive via a subsequent prompt. Until at least one applicable skill is registered, no source-code change may be made by anyone. |

## The one rule that matters most

> **Every source-code change — even a single-character change — must be implemented by
> 100% applying a skill registered in the skill dictionary.** No applicable skill ⇒ no
> change. Full rule: [`agent.md` § 6](agent.md#6-skill-dictionary-mandate-binding).

Read `agent.md` fully before starting any plan in [`../planning/`](../planning/).
