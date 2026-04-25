---
name: coze-router
description: >
  Call the Coze-based workflow router at d3q1e0dyfg5ace.cloudfront.net for web search
  (google_search), URL-to-plaintext fetching (url_fetch), and Reddit browsing / search /
  inbox (reddit). Use this skill whenever the user wants to: search the web through Coze,
  read a specific web page's plaintext, list hot posts site-wide or inside a subreddit,
  run a Reddit search (site-wide or scoped), or check their Reddit inbox / unread
  messages. Also triggers on explicit mentions of "coze router", "workflow/list",
  "workflow/run", the bearer token prefix `bvr_`, or phrases like "list Coze workflows",
  "run the reddit workflow", "use the coze api". Prefer this skill over ad-hoc curl when
  the user asks about any of the workflows the router exposes — the bundled script
  already handles auth, envelope parsing, and per-workflow formatting.
---

# Coze Router

A thin CLI wrapper around a Coze-hosted workflow router. Two HTTP endpoints are exposed:

- `GET  /v1/workflow/list` — returns the catalog of workflows with their JSONSchema
- `POST /v1/workflow/run`  — runs `{"name": <workflow>, "parameters": <params>}`

The `/run` response always wraps its useful payload as a **JSON-encoded string** inside
the top-level `data` field. The script (`scripts/coze_run.py`) parses that for you and
formats per workflow, so you almost never need to touch the raw response.

## Quick Start

```bash
# List all workflows (and their sub-methods for router-style workflows like `reddit`)
python3 <skill-path>/scripts/coze_run.py list

# Web search
python3 <skill-path>/scripts/coze_run.py search "claude opus 4.7" --num 5

# Fetch a page as plaintext
python3 <skill-path>/scripts/coze_run.py fetch "https://example.com/article"

# Reddit: site-wide hot / search
python3 <skill-path>/scripts/coze_run.py reddit-hot --limit 10
python3 <skill-path>/scripts/coze_run.py reddit-search "anthropic" --limit 10

# Reddit: subreddit hot / search
python3 <skill-path>/scripts/coze_run.py sub-hot ClaudeAI --limit 10
python3 <skill-path>/scripts/coze_run.py sub-search ClaudeAI "MCP" --limit 5

# Reddit inbox (requires the router's Reddit auth to be configured upstream)
python3 <skill-path>/scripts/coze_run.py inbox --limit 10
python3 <skill-path>/scripts/coze_run.py unread --limit 10

# Escape hatch: run any workflow with a raw JSON params blob, returns parsed JSON
python3 <skill-path>/scripts/coze_run.py raw google_search '{"googleWebSearch":{"query":"x","num":3}}'
```

Add `--json` to any subcommand to print the parsed payload as JSON instead of the
pretty-printed text (useful for piping into `jq`).

## Workflow Reference

### 1. `google_search`

Ranked organic Google results.

```json
{"name":"google_search","parameters":{"googleWebSearch":{"query":"...","num":5,"start":0}}}
```

- `num` — 1..10, default 5
- `start` — pagination offset, default 0

Returns `output.organic_results[]` with `title`, `link`, `snippet`. The script prints a
numbered list; snippets longer than ~320 chars are truncated so the output stays scannable.

### 2. `url_fetch`

Plaintext extraction of an HTTPS page.

```json
{"name":"url_fetch","parameters":{"url":"https://example.com"}}
```

Returns `{title, content}`. Long pages may be truncated upstream — if the user needs the
full article, warn them and prefer structured scraping.

### 3. `reddit` (router with 6 sub-methods)

Pass **exactly one** of these method namespaces as the `parameters` object:

| Method            | Params                                | What it does                             |
|-------------------|---------------------------------------|------------------------------------------|
| `redditHot`       | `limit` (string)                      | Site-wide hot feed                       |
| `redditSearch`    | `q`, `limit`                          | Site-wide search                         |
| `subRedditHot`    | `subreddit`, `limit`                  | Hot posts in a subreddit                 |
| `subRedditSearch` | `subreddit`, `q`, `limit`             | Search inside a subreddit                |
| `messageInbox`    | `limit`, optional `sr_detail`         | Authenticated user's inbox               |
| `messageUnread`   | `limit`, optional `sr_detail`         | Authenticated user's unread messages     |

**All values are strings** — including numeric limits (`"10"`, not `10`). The CLI
handles the stringification for you.

The response envelope always contains all six slot keys; only the invoked one is
populated (`data` is non-null there, null elsewhere). For `redditHot`/`Search` slots the
listing lives at `<slot>.data.postData.data.children[]`; for message slots at
`<slot>.data.messageData.data.children[]`. The script unwraps this automatically.

Per-post fields surfaced: `title`, `subreddit_name_prefixed`, `author`, `score`,
`num_comments`, `link_flair_text`, `permalink`, `url_overridden_by_dest`, `selftext`.

## Response Envelope (for `raw` / debugging)

Every `/v1/workflow/run` success looks like:

```json
{
  "code": 0,
  "data": "<stringified JSON>",
  "msg": "Success",
  "execute_id": "...",
  "debug_url": "https://www.coze.com/work_flow?execute_id=...",
  "usage": {"input_count": 0, "output_count": 0, "token_count": 0}
}
```

Errors return a non-zero `code` and no `data` — e.g. an unknown workflow name yields
`{"code":404,"msg":"workflow \"bogus_workflow\" not found"}`. The script surfaces these
to stderr and exits 1.

## Auth & Configuration

Credentials live in `~/.config/coze-router/config.json` (override the path with
`COZE_ROUTER_CONFIG`). Expected shape:

```json
{
  "base_url": "https://d3q1e0dyfg5ace.cloudfront.net",
  "token":    "bvr_xxxxxxxxxxxxxxxxxxxxxxxx"
}
```

First-run bootstrap: if the file is missing, the script creates a stub with
placeholder values, chmods it to `0600`, prints a message telling the user which
fields to fill in, and exits with code 2. Same behaviour (exit 2 + clear message) if
fields are empty or still contain the `<...>` placeholders. Rerun once filled.

Env var overrides (mostly for ad-hoc testing):

- `COZE_ROUTER_CONFIG` — path to the config file
- `COZE_ROUTER_TOKEN` — override the token from config
- `COZE_ROUTER_BASE_URL` — override the base URL from config
- `COZE_ROUTER_UA` — user-agent string. **The API is behind Cloudflare with browser
  fingerprinting** — the default `python-urllib` UA is blocked (HTTP 403, error 1010),
  so the script sends a normal Chrome UA. Don't strip this.

## When to Use vs. Alternatives

- For general web search, `gemini-tools` (Gemini CLI) is the default cost-saver. Prefer
  this skill when the user explicitly wants the Coze router, when they need Reddit
  data (Gemini can't do that), or when they want the raw plaintext of a specific URL
  through the router's `url_fetch`.
- For reading arbitrary web pages when you just need the content in-context, the
  built-in `WebFetch` tool is usually simpler. Reach for `url_fetch` here only when the
  user is specifically exercising the router.
