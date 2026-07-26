---
name: grok
description: Search X (Twitter) and the live web, or generate and edit images, via the locally-installed Grok Build agent. Use for X posts, accounts, threads and sentiment; for current facts your own tools can't reach; or to make or edit an image. Also on "ask grok" / "让 grok ...".
---

# Grok

Grok Build carries two things no other agent has: `x_search`, run server-side by
xAI against the X firehose, and the xAI Imagine image models. This skill drives the
local `grok` binary over ACP and hands back a cited report or a saved file. Use it
for live X data, current facts, and images — not for coding.

## Setup

```bash
python3 <skill-path>/scripts/grok_acp.py check    # binary, auth, model, handshake
```

Missing binary or auth: `curl -fsSL https://x.ai/cli/install.sh | bash`, then
`grok login`. Python 3.9+, stdlib only.

## Commands

**Search & research**

| Command | Use for |
|---|---|
| `x "<request>"` | **The main one.** Any X question: posts, topics, sentiment, an account's history, who said what |
| `user "<who>"` | Find an X account and profile it |
| `thread <url\|post_id>` | One post's full text plus its thread, replies, and quote-posts |
| `web "<request>"` | Live web search with URL citations |
| `research "<topic>"` | Sub-questions, cross-checked claims, explicit unknowns (slow — raise `--timeout`) |

**Media** (xAI Imagine — needs SuperGrok tier; fails loudly if not)

| Command | Use for |
|---|---|
| `image "<brief>"` | Text to image. `--aspect 1:1\|16:9\|9:16\|3:2\|2:3\|…` |
| `edit "<brief>" --image PATH` | Edit / restyle / remix. Repeat `--image` for multi-image edits |
| `video "<brief>" --image PATH` | Animate an image (`--duration`, `--resolution`). Repeat `--image` (2–7) to blend references |

**Other**: `ask "<prompt>"` (free-form, Grok picks its tools) · `check`

```bash
S=<skill-path>/scripts/grok_acp.py
python3 $S x "what are developers actually saying about the new Gemini release"
python3 $S x "from:sama posts about compute" --since 2026-06-01 --sort top
python3 $S user "the creator of the Zed editor"
python3 $S thread https://x.com/karpathy/status/2081195664479068350
python3 $S web "current status of the EU AI Act GPAI obligations"
python3 $S image "minimalist origami crane logo, flat vector, dark background" --aspect 1:1 --out ./assets
python3 $S edit "make the crane warm gold, keep composition" --image ./assets/grok-image.jpg
```

The answer **streams to stdout as it arrives**. Progress, timing, session id, and
the exact queries Grok ran go to **stderr**. Generated media is copied out of
Grok's session folder into `--out` and its final path printed to stdout.

## Flags

| Flag | Effect |
|---|---|
| `--since` / `--until` `YYYY-MM-DD` | Date window (aliases: `--from-date` / `--to-date`) |
| `--sort latest\|top` | Rank by recency or engagement |
| `--lang XX` | Only posts in that language (`en`, `zh`, `ja`, …) |
| `--limit N` | Roughly how many results to report |
| `--reply-lang LANG` | Language to write the **report** in |
| `--rules "TEXT"` | Extra instructions appended to the rules |
| `--json` | One JSON object: `answer`, `media`, `queries`, `tool_calls`, `usage`, `session_id` |
| `--schema FILE\|'{...}'` | JSON Schema constraining the answer (parsed into `.structured`) |
| `--session ID` | Continue a previous run |
| `--out DIR\|FILE` | Where to save generated media (default: current directory) |
| `--thinking` | Show the reasoning stream on stderr |
| `--no-stream` | Wait for the complete answer instead of streaming |
| `--timeout SEC` | Per-turn (default 300; 600 media, 900 research) |
| `--effort low\|medium\|high` | Reasoning effort — see Speed first |
| `--quiet` | No stderr trace |

## Notes

**Ask in plain language.** Grok writes the X operator syntax itself and runs
several query variants, so `x "how are people reacting to the Figma IPO"` beats a
hand-built query string. Put operators in the request only for exact control:
`x "from:elonmusk min_faves:5000 -filter:replies"`.

**Steer the report shape in the request** — "top 10 with follower counts", "quote
the exact wording", "group by stance". Use `--schema` for machine-readable output.

**Follow up, don't re-search.** `--session <id>` (printed on stderr) keeps the
retrieved posts in context, so "who replied to the first one?" is one cheap turn.

**Empty results are real.** Grok says when a search found nothing — that's a fact
about X, not a prompting failure. Read the stderr query trace before widening.

**For images, give a brief, not a prompt.** Grok loads xAI's `imagine` guidance
and expands it. Hard constraints are honoured — aspect, exact colours, "keep the
composition". Exact text, numbers, and data-driven charts belong in code, not an
image model.

## Speed

| | |
|---|---|
| Fixed overhead (spawn + handshake + session) | ~1.9s |
| First sign of life | ~9–10s |
| Typical `x` / `web` turn | 10–25s |
| `image` / `edit` | ~20s |
| `research` | minutes |

The cost is model-side, which is why the answer streams by default. Two
non-optimizations, measured: `--effort low` does not speed searches up (17.2s
high / 25.5s medium / 21.0s low — the time is in the search calls), and
`--leader` lands within noise while leaving a resident daemon (`grok leader kill`
to clear it).

## Reporting back

Relay permalinks and quoted text verbatim — the permalink is what makes a claim
checkable. Say the results came from an X search, and keep engagement numbers with
the post they describe. For media, report the printed path; the script exits
non-zero and prints the tool's error when generation fails.

## Safety

Search runs in an isolated empty workspace (`~/.cache/grok-skill/workspace`) with
the toolset restricted to `web_search`, `web_fetch`, and `x_search` — no file,
shell, or subagent access, and it never sees the caller's repo (this also cuts the
prompt from ~62k to ~13k input tokens). Media runs in the same workspace with the
full toolset so Grok can load its `imagine` guide; the script then copies results
to `--out`.

`ask --workspace --cwd DIR` is the exception: full toolset inside `DIR` with tool
approvals auto-accepted. Only pass a directory the user agreed to hand over.

## More

- `references/x-search.md` — the four `x_search` sub-tools, X operator reference,
  recipes, limits. **Read when a search underperforms.**
- `references/media.md` — image/video tools, aspect ratios, where files land, ZDR
  video config (nested S3 tables), and remote `uploaded_url` download.
- `references/acp.md` — ACP wire protocol and `_meta` options, for driving
  `grok agent stdio` directly.
