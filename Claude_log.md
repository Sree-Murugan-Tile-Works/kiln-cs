# Claude Log

## 2026-06-16 — Bootstrap Claude Code support for kiln-cs
- Added `CLAUDE.md` documenting the actual fan-ctrl daemon and dashboard architecture, data flow, SQLite schema, key conventions, and known technical debt (stubbed PLC I/O in `plc.py`, `pid.py` never setting `ki`/`kd`, debug `print()`s in `dashboard/web.py`).
- Copied `CLAUDE-COMMON.md` and `PROJ_STARTER.md` verbatim from the `kl-mithunvel/claude` template repo; their content is also reproduced inside `CLAUDE.md`'s `## User Rules` section per the documented process.
- Added `.claude/skills/pdf/SKILL.md`, `.claude/skills/grill-me/SKILL.md`, and `.claude/skills/update-docs/SKILL.md`, copied from the template repo's `.CLAUDE/skill/` (moved to the lowercase `.claude/skills/` path so Claude Code actually discovers them in this project).
- Created this log file and `TODO.md` as the companion files `CLAUDE-COMMON.md` requires, seeded with the technical debt items already visible in the codebase.
- Nothing left incomplete from this task. Future sessions should keep `TODO.md` and this log updated per `CLAUDE-COMMON.md`'s rules.
