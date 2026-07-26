# Skills Marketplace

[![skills.sh](https://skills.sh/b/loadchange/skills)](https://skills.sh/loadchange/skills)

This is my personal Claude Skills marketplace, forked from [Anthropic's official skills repository](https://github.com/anthropics/skills), serving as a template and repository for custom skills.

## Current Skills

### grok
Delegate live X (Twitter) and web research to the locally-installed [Grok Build](https://docs.x.ai/build/overview) agent over ACP — search posts, find accounts, read threads and replies, track sentiment, or get current facts, returned as a cited report. Works from any agent tool that can run a shell command.

### polymarket-wallet
Polymarket wallet trading analysis and report generation — look up a trader by wallet address or display name to get positions, P&L, and win rate.

### hyperliquid-analytics
Query and analyze Hyperliquid account/address data (positions, fills, PnL, funding, HyperEVM on-chain reads) via pre-built Python scripts.

### drawio-diagram
Create or edit draw.io / diagrams.net diagrams — flowcharts, architecture diagrams, sequence diagrams, mind maps — written as `.drawio` files.

### guodegang
基于郭德纲长篇单口语料提炼的原创京味说书式幽默写作与改写技能 — 把话术、文案、对白改写成带相声/评书节奏、市井观察和反转包袱的中文，或只给背景直接创作一段。

## Installation

### Any coding agent (skills.sh)

Install with the open agent-skills CLI — works with Claude Code, Cursor, Codex, Gemini CLI, and 70+ other agents:

```bash
npx skills@latest add loadchange/skills
```

Then pick the skills and agents you want. Directory page: <https://skills.sh/loadchange/skills>.

### Claude Code
Register this marketplace in Claude Code:

```bash
/plugin marketplace add loadchange/skills
```

Then install the plugin:

```bash
/plugin install loadchange@loadchange-skills
```

### Claude.ai
In Claude.ai:
1. Go to project settings
2. Select "Skills"
3. Click "Add custom skill"
4. Upload the desired folder under `skills/` (e.g. `skills/drawio-diagram`)

## Creating New Skills

1. Create a new folder under `skills/`
2. Add a `SKILL.md` file with the following format:

```markdown
---
name: your-skill-name
description: Clear description of the skill
---

# Skill Name

[Add instructions that Claude will follow here]

## Use Cases
- Use case 1
- Use case 2
```

3. Update `.claude-plugin/marketplace.json` to include the new skill

## References

- [Agent Skills Specification](https://agentskills.io)
- [Claude Skills Documentation](https://support.claude.com/en/articles/12512176-what-are-skills)
- [Creating Custom Skills](https://support.claude.com/en/articles/12512198-creating-custom-skills)

## License

This project is forked from [Anthropic/skills](https://github.com/anthropics/skills) and follows the original repository's license.
