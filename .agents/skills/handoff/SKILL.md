---
name: handoff
description: Write a concise handoff so a fresh Codex session can continue the current task. Use when the user asks to hand off work or resume it in a new session.
---

Summarize the current task, decisions, completed work, verification, blockers, and next action. If the user gives a focus, tailor the handoff to it. Save the Markdown file with a unique name in the OS temporary directory.

Include a “Suggested skills” section with relevant Codex skill names in `$skill-name` form. Point to existing specs, plans, commits, or issues by path or URL.

Redact credentials and personal information. Give the user the absolute path and a short prompt they can paste into a new Codex session to resume the work.
