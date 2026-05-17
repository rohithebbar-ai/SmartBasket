# ShopSense skills (Claude / Agent Skills)

Skills for building and shipping **ShopSense** — see [`../ShopSense_Platform_Plan_v3.md`](../ShopSense_Platform_Plan_v3.md).

Install by pointing Claude Code / Claude desktop at this directory, or symlink each skill folder into your [Agent Skills](https://agentskills.io/specification) path (for example `~/.claude/skills/`). Each skill is a folder containing `SKILL.md` with YAML frontmatter (`name`, `description`).

## Skills

| Folder | `name` | Role |
|--------|--------|------|
| [code-reviewer](code-reviewer/SKILL.md) | `shopsense-code-reviewer` | Security and quality review for Python/TS aligned with ShopSense (NL-to-SQL, agent, Kafka, infra). |
| [coder](coder/SKILL.md) | `shopsense-coder` | Implement features inside module boundaries and conventions from the platform plan. |
| [deployment-agent](deployment-agent/SKILL.md) | `shopsense-deployment-agent` | Safe releases: Terraform/EC2, Docker, Nginx, checklists, rollback mindset. |

## Suggested workflow

1. **shopsense-coder** — implement or refactor against the plan.
2. **shopsense-code-reviewer** — run checklist + `./code-reviewer/scripts/review.py` on touched paths.
3. **shopsense-deployment-agent** — pre-flight and deploy following `infra/terraform` and the deployment checklist.

## Code reviewer scripts

From `skills/code-reviewer/`:

```bash
chmod +x scripts/*.py
pip install ruff bandit mypy semgrep   # optional but recommended

./scripts/review.py ../../../path/to/shopsense/app
./scripts/review.py ../../../path/to/file.py --security-only
./scripts/security-check.py ../../../path/to/file.py
```

Paths are relative to `skills/code-reviewer/`; adjust to your checkout layout.
