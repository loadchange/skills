---
name: dsh-x
description: Search X (Twitter) through your own dsh-x-search endpoint — posts, topics, sentiment, an account and its recent posts, or one post's full thread — returned as a cited report with structured posts. Use for anything on X; also on "查一下 X", "推特上", "ask dsh-x". No Grok subscription involved.
---

# dsh-x

Your own X search service: a [dsh-x-search](https://github.com/loadchange/dsh-x-search)
instance reads X with your account and writes cited reports with its host's model. This
skill is the client. It covers X only — for web search, page fetching or images use
another skill.

## Setup

Config is a file, not environment variables:

```bash
python3 <skill-path>/scripts/dsh_x.py config --url https://x-search.example.com --token <token>   # writes ~/.config/dsh-x/config.json (0600)
python3 <skill-path>/scripts/dsh_x.py check                                                       # endpoint, session, quota
```

`~/.config/dsh-x/config.json` is `{"url": "...", "token": "...", "timeoutSec": 300}`;
`DSH_X_CONFIG=<path>` points elsewhere. Python 3.9+, stdlib only.

## Commands

| Command | Use for |
|---|---|
| `x "<request>"` | **The main one.** Any X question: posts, topics, sentiment, who said what |
| `user "<handle or who>"` | Profile + recent posts; a description is resolved through People search |
| `thread <url\|post_id>` | One post's full text, the author's thread, and the replies |
| `ask <url\|id> <question…>` | **"What does this post mean?"** — the server reads the post, its thread *and its images*, then answers directly and returns the original text with image descriptions |
| `x "<question>" --session <id>` | Follow-up over the previous search's posts — no new search, seconds |
| `check` · `config` | Endpoint status · write/show the config file |

```bash
S=<skill-path>/scripts/dsh_x.py
python3 $S x "what are developers saying about the Zed editor this week" --since 2026-09-15 --reply-lang Chinese
python3 $S x "from:sama posts about compute" --since 2026-06-01 --sort top
python3 $S x "reactions to the Figma IPO" --handle bloomberg --handle reuters --raw
python3 $S user karpathy
python3 $S thread https://x.com/karpathy/status/2081195664479068350 --json
python3 $S ask https://x.com/someone/status/1234567890123456789 这个帖子什么意思？
python3 $S x "zed editor reactions" --ask "what are the main complaints?"
```

The report goes to stdout; timing, session id, warnings and the exact queries run go
to stderr. `--json` gives one object: `answer`, `posts[]` (structured: id, url, text,
author, metrics, createdAt…), `queries`, `warnings`, `session_id`.

## Flags

| Flag | Effect |
|---|---|
| `--since` / `--until` `YYYY-MM-DD` | Date window (compiled into `since:` / `until:` by the server) |
| `--sort latest\|top` | Recency or engagement |
| `--lang XX` | Only posts in that language |
| `--limit N` | Roughly how many posts (default 30, hard cap 80) |
| `--handle H` (repeat) | Only these accounts, max 20 — mirrors xAI `allowed_x_handles` |
| `--exclude-handle H` (repeat) | Exclude these accounts, max 20; not together with `--handle` |
| `--no-replies` | Drop replies |
| `--reply-lang LANG` | Language of the report |
| `--rules "TEXT"` | Extra instructions for the report writer |
| `--ask "QUESTION"` | Answer this question directly instead of writing a report; the server reads the posts' images first. On `thread`/`user`/`x` |
| `--raw` | Cited post list only, no written report (cheaper; good when you synthesize yourself) |
| `--session ID` | Follow-up on cached posts |
| `--json` · `--quiet` · `--timeout SEC` | Output and timing controls |

## Notes

**Understanding happens on the server — do not fetch media yourself.** When the user
asks what a post means, run `ask <url> <question>` (or `thread <url> --ask "…"`) and
relay the answer. The server has the login session, the network path to X's image
CDN and a vision model: it transcribes text inside images and answers with the
original quoted. Do not try syndication endpoints, image proxies or local downloads;
the client usually cannot reach X at all.

**Ask in plain language.** The server plans several X queries from the request. A
request that already contains X operators (`from:`, `min_faves:`, `"exact phrase"`,
`OR`) is passed through untouched — use that for exact control.

**Dates, handles and language go in flags, not in the request text.** The server
compiles them into operators itself; writing them into the text as well double-filters.

**Follow up, don't re-search.** `--session <id>` (printed on stderr) answers over the
posts already retrieved. Sessions live about two hours.

**Empty results are real.** `posts: []` with no warnings means X has nothing for that
query. Read the stderr "queries run" list before widening.

**`--raw` is the escape hatch.** When the server has no model, or you want the
posts and will write the analysis yourself, `--raw` returns the cited list only.

## Limits

- Requests share the server's quota (default 40 per 15 min, 600 per day); a
  natural-language search uses up to 3. `RATE_LIMITED` comes with a retry hint.
- The public endpoint sits behind Cloudflare, which waits about 100 s for the
  origin; a search normally takes 5–50 s.
- Only what a logged-in user sees: protected, deleted and blocked posts are invisible;
  engagement counts are a snapshot.
- X changes its web responses occasionally; `UPSTREAM_CHANGED` means the server's
  parser needs updating, not that the query was wrong.

## Reporting back

Relay permalinks and quoted text verbatim — the permalink is what makes a claim
checkable. Keep engagement numbers with the post they describe, and say the results
came from an X search.

## Safety

The token in the config file grants use of the owner's X account and its quota:
keep the file 0600 and never paste the token into a repo or a chat. The endpoint's
errors carry a stable `code`; the script prints a hint for each.
