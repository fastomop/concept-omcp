# .agents

Source-of-truth for shared, team-level AI-agent assets (prompts, skills, notes),
following the [agents.md](https://agents.md/) convention. Tool-specific directories
alias in here via tracked symlinks so every contributor sees the same content
regardless of which agent they use.

- Project-wide instructions live in the repo-root [AGENTS.md](../AGENTS.md).
- `CLAUDE.md` (repo root) and `.claude/` symlink to `AGENTS.md` / `.agents/`.

To add a shared asset, put the file here and symlink it from `.claude/`:

```sh
ln -s ../.agents/<name> .claude/<name>
```
