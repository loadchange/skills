---
name: agy-tools
description: >
  Use Antigravity CLI (agy) for web search, image recognition, and terminal task automation.
  Trigger on: search/look up/find online, 搜索/搜一下/查一下, image analysis/recognition/识图/看图/分析图片,
  error troubleshooting, URLs/base64 images, or any task requiring web research or agy CLI automation.
---

# Antigravity CLI (agy) Tools

The Antigravity CLI (`agy`) leverages full agentic capabilities to perform web search, image recognition, and code analysis directly from the terminal.

> [!WARNING]
> **Deadlock Risk in Sub-processes**
> Do not execute `agy --print` or `agy models` from within an active agent session (e.g. using `run_command` in a tool execution). This will cause a deadlock because `agy` attempts to communicate with the active Antigravity Language Server, which is currently blocked waiting for your tool execution to finish.
> This skill is primarily intended to guide the **user** on how to run `agy` commands in their terminal, or for execution in standalone scripts where no parent agent session is active.

## 1. Web Search & Question Answering

Run a single query non-interactively using the `--print` (or `-p`) flag. By default, it will auto-approve any tool execution permissions if `--dangerously-skip-permissions` is passed.

```bash
# Query the model using the default settings
agy --dangerously-skip-permissions --print "search for the latest Next.js 15 routing features"

# Override the model (e.g., use an alternative model)
agy --model alternative-model --dangerously-skip-permissions --print "explain react compiler current status"
```

## 2. Image Recognition & File Analysis

`agy` runs a full agent session. To analyze an image or file, simply include the file path in your prompt. The agent will automatically call its file viewing tools to inspect the file.

```bash
# Analyze a local screenshot or image
agy --dangerously-skip-permissions --print "describe this image and extract text: /absolute/path/to/screenshot.png"
```

### Remote/Base64 Files
For URLs or base64 data, download or decode the file to `/tmp/` first, then run `agy`:

```bash
# Download from URL
curl -sL "https://example.com/image.png" -o /tmp/target_img.png
agy --dangerously-skip-permissions --print "analyze this image: /tmp/target_img.png"

# Convert from base64 data
echo "<base64_data>" | base64 -d > /tmp/target_img.png
agy --dangerously-skip-permissions --print "analyze this image: /tmp/target_img.png"
```
