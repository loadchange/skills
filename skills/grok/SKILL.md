---
name: grok
description: Delegate live X (Twitter) and web research to the locally-installed Grok Build agent over ACP. Use whenever a task needs X/Twitter data — searching posts, finding accounts, reading a thread or its replies, tracking what people are saying about a topic, sentiment or reaction on X, an account's posting history — or needs current real-world facts that your own tools cannot reach or that you should not answer from memory. Triggers on "search X", "search Twitter", "推特/X 上搜", "what are people saying about", "find the X account for", "read this thread", "posts from @someone", any x.com / twitter.com URL, and on "ask grok" / "让 grok ...". Returns a cited markdown report, optional JSON.
---

# Grok

Grok Build ships an X-native search tool no other agent has: `x_search`, executed
server-side by xAI with direct access to the X firehose. This skill drives the
local `grok` binary over ACP (JSON-RPC) and hands you back a cited report.

**Use it for what Grok is uniquely good at — live X data and current facts. Do
your own coding.**

## Setup check

Run once per machine; it verifies the binary, auth, model, and ACP handshake:

```bash
python3 <skill-path>/scripts/grok_acp.py check
```

If it reports a missing binary or no auth: `curl -fsSL https://x.ai/cli/install.sh | bash` then `grok login`.
Everything below assumes `<skill-path>` is this skill's directory. Python 3.9+, no
third-party packages.

## Commands

| Command | Use for |
|---|---|
| `x "<request>"` | **The main one.** Any X/Twitter question: posts, topics, sentiment, an account's history, who said what |
| `user "<who>"` | Find an X account and profile it (handle, bio, followers, recent activity) |
| `thread <url\|post_id>` | One post's full text plus its thread, replies, and quote-posts |
| `web "<request>"` | Live web search with URL citations |
| `research "<topic>"` | Multi-round research: decomposed sub-questions, double-checked claims, explicit unknowns (slow — raise `--timeout`) |
| `ask "<prompt>"` | Free-form — Grok picks its own tools |
| `check` | Verify install, auth, models, handshake |

```bash
python3 <skill-path>/scripts/grok_acp.py x "what are developers actually saying about the new Gemini release"
python3 <skill-path>/scripts/grok_acp.py x "from:sama posts about compute" --since 2026-06-01 --sort top
python3 <skill-path>/scripts/grok_acp.py user "the creator of the Zed editor"
python3 <skill-path>/scripts/grok_acp.py thread https://x.com/karpathy/status/2081195664479068350
python3 <skill-path>/scripts/grok_acp.py web "current status of the EU AI Act GPAI obligations"
```

The answer goes to **stdout**; progress, timing, session id, and the exact search
queries Grok ran go to **stderr**. A typical `x` run takes 20–60s.

## Flags

| Flag | Effect |
|---|---|
| `--since` / `--until` `YYYY-MM-DD` | Date window (also aliased `--from-date` / `--to-date`) |
| `--sort latest\|top` | Rank by recency or by engagement |
| `--lang XX` | Only posts in that language (`en`, `zh`, `ja`, …) |
| `--limit N` | Roughly how many results to report |
| `--reply-lang LANG` | Language to write the **report** in — e.g. `--reply-lang Chinese` |
| `--rules "TEXT"` | Extra instructions appended to the search rules |
| `--json` | One JSON object on stdout: `answer`, `queries`, `tool_calls`, `usage`, `session_id` |
| `--schema FILE\|'{...}'` | JSON Schema; Grok's answer is constrained to it (parsed into `.structured` under `--json`) |
| `--session ID` | Continue a previous run — follow-ups keep the retrieved posts in context |
| `--effort low\|medium\|high` | Reasoning effort |
| `--timeout SEC` | Per-turn timeout (default 300; 900 for `research`) |
| `--quiet` | No stderr trace |

## How to use it well

**Ask in plain language, not in operators.** Grok translates the request into X
advanced-search syntax itself and runs several query variants. `x "how are people
reacting to the Figma IPO"` beats hand-writing a query string. Save the operators
for when you need exact control — then just put them in the request:
`x "from:elonmusk min_faves:5000 -filter:replies since:2026-07-01"`.

**Say what you want back.** The request text steers the report shape: "list the
top 10 with follower counts", "quote the exact wording", "group by stance",
"just the permalinks". For machine-readable output use `--schema`.

**Follow up instead of re-searching.** `--session <id>` (printed on stderr after
every run) keeps the retrieved posts in context, so "who replied to the first
one?" costs one cheap turn rather than a whole new search.

**Trust but verify the trace.** The stderr "queries run" list shows the exact
search strings. If they look too narrow, re-run with a wider request or add
`--rules "also search Chinese-language posts"`.

**Don't ask Grok for opinions dressed as facts.** It reports what X returned. If
a search comes back empty it says so — treat that as a real signal, not a
prompting failure.

## Reporting back

Preserve permalinks and quoted text verbatim when you relay results — the
permalink is what makes the claim checkable. Attribute clearly: say the posts came
from an X search, and keep engagement numbers attached to the post they describe.
Don't merge Grok's findings into your own voice as if you'd verified them.

## Safety

Search commands run in an isolated empty workspace (`~/.cache/grok-skill/workspace`)
with Grok's toolset restricted to `web_search`, `web_fetch`, and `x_search` — it
has no file, shell, or subagent access and never sees the caller's repo. This
also cuts the prompt from ~62k to ~13k input tokens.

`ask --workspace --cwd DIR` is the deliberate exception: it gives Grok its full
toolset inside `DIR`, with tool approvals auto-accepted. Only pass a directory the
user has explicitly agreed to hand over.

## More

- `references/x-search.md` — the four `x_search` sub-tools, full X operator
  reference, recipes, and known limits. **Read this when a search underperforms**
  or when you need precise operator control.
- `references/acp.md` — the ACP wire protocol, `_meta` options, and how to drive
  `grok agent stdio` directly for anything this script does not cover.
