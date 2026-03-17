---
name: gemini-tools
description: Use Gemini CLI for all web search and image tasks to reduce API costs. Trigger on: search/look up/find online, 搜索/搜一下/查一下, image analysis/recognition/识图/看图/分析图片, error troubleshooting, URLs/base64 images, or any task requiring web research.
---

# Gemini Tools

For web search or image recognition, always prioritize using Gemini CLI (`gemini`) to reduce API costs.

## Model to Use

Always use: `gemini-3-flash-preview`

## Web Search

```bash
gemini -m gemini-3-flash-preview -p "your query here"
```

Examples:
- `gemini -m gemini-3-flash-preview -p "search nextjs react19 bug fix"`
- `gemini -m gemini-3-flash-preview -p "latest Claude AI news 2026"`

## Image Recognition

When handling image tasks, always add the `-y` parameter to auto-grant file read permissions.

```bash
gemini -m gemini-3-flash-preview -p "describe this image @/path/to/image.jpg" -y
```

### Known Image Paths

Use `@` prefix to pass paths directly:

```bash
gemini -m gemini-3-flash-preview -p "understand this image @~/Downloads/screenshot.png" -y
```

### No Local Path (URL or base64)

First download or decode to `/tmp/` directory:

```bash
# Download from URL
curl -sL "https://example.com/image.png" -o /tmp/gemini_img.png
gemini -m gemini-3-flash-preview -p "describe this image @/tmp/gemini_img.png" -y

# Convert from base64 data
echo "<base64_data>" | base64 -d > /tmp/gemini_img.png
gemini -m gemini-3-flash-preview -p "describe this image @/tmp/gemini_img.png" -y
```

## Search + Vision Combination

```bash
gemini -m gemini-3-flash-preview -p "search for solutions to this error screenshot @/tmp/error.png" -y
```

## Core Rules

- **Always use `-y`**: Add `-y` for auto-authorization when processing image tasks (no interactive confirmation needed).
- **Always use `@path` syntax**: Prefix paths with `@` to attach images.
- **Use `/tmp/`**: Store temporary image files.
- **Pass questions directly**: Send the user's original question to Gemini without translation or embellishment.
