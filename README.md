# Skills Marketplace

This is my personal Claude Skills marketplace, forked from [Anthropic's official skills repository](https://github.com/anthropics/skills), serving as a template and repository for custom skills.

## Current Skills

### gemini-tools
Use Gemini CLI for web search and image recognition to reduce API costs.

- **Web Search**: Fast web retrieval using Gemini 3 Flash Preview
- **Image Recognition**: Supports local images, URLs, and base64 format image analysis
- **Cost Optimization**: Significantly reduces search and image recognition costs compared to direct Claude API usage

## Installation

### Claude Code
Register this marketplace in Claude Code:

```bash
/plugin marketplace add LoadChange/skills
```

Then install the skill:

```bash
/plugin install gemini-tools@loadchange-skills
```

### Claude.ai
In Claude.ai:
1. Go to project settings
2. Select "Skills"
3. Click "Add custom skill"
4. Upload the `skills/gemini-tools` folder

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
