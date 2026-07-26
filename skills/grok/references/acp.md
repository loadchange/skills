# Driving Grok over ACP directly

`scripts/grok_acp.py` covers the common cases. This is the wire protocol
underneath, for when you need something it does not expose.

Reference: <https://docs.x.ai/build/overview> · <https://agentclientprotocol.com>

## Transport

```bash
grok agent --always-approve stdio          # JSON-RPC 2.0, newline-delimited, on stdin/stdout
grok agent --always-approve serve --bind 127.0.0.1:2419 --secret <token>   # WebSocket
```

Agent-level flags go **after** `agent` and **before** the mode:
`-m/--model`, `--reasoning-effort`, `--always-approve` (alias `--yolo`),
`--agent-profile <PATH>`, `--leader` / `--no-leader`, `--reauth`, `--plugin-dir`.

Without `--always-approve`, the agent sends `session/request_permission` requests
that a client must answer or the turn hangs.

## Handshake

```json
{"jsonrpc":"2.0","id":1,"method":"initialize","params":{
  "protocolVersion":1,
  "clientCapabilities":{"fs":{"readTextFile":false,"writeTextFile":false},"terminal":false},
  "_meta":{"clientIdentifier":"my-client"}}}
```

Declaring `fs`/`terminal` as `false` means the agent never asks your process to
read or write files on its behalf — it uses its own workspace tools.

The response carries, under `_meta`: `agentVersion`, `defaultAuthMethodId`
(absent ⇒ not signed in, run `grok login`), `modelState.currentModelId` and
`availableModels`, `availableCommands` (the slash commands), and
`currentWorkingDirectory`. Under `agentCapabilities._meta["x.ai/capabilities"]`:

```json
{"toolOverrides":{"x_keyword_search":true,"x_semantic_search":true,
                  "x_user_search":false,"x_thread_fetch":false}}
```

— which `x_search` sub-tools honour the `dateBound` override.

## Session

```json
{"jsonrpc":"2.0","id":2,"method":"session/new","params":{
  "cwd":"/abs/path","mcpServers":[],
  "_meta":{"yoloMode":true,"rules":"…","agentProfile":{…}}}}
```
→ `{"sessionId":"019f9c…"}`

Resume with `session/load` using the same `sessionId`, `cwd`, and `mcpServers`.
Sessions are stored per workspace — loading with a different `cwd` fails with
`FS_NOT_FOUND`.

### `session/new` `_meta`

| Field | Effect |
|---|---|
| `yoloMode` | Always-approve for this session |
| `autoMode` | Auto permission mode (superseded by `yoloMode`) |
| `rules` | Extra text folded into the system prompt inside `<human_rules>`. **Creation only** — not re-applied on resume |
| `systemPromptOverride` | Replaces the system prompt outright; *is* re-synced on resume |
| `agentProfile` | Agent name (string) or a full definition (object) |

### `agentProfile`

A JSON `AgentDefinition`, camelCase on the wire. `name` and `description` are
required; everything else defaults. What this skill sends for search runs:

```json
{"name":"grok-research",
 "description":"Live X and web research. No filesystem, shell, or subagent access.",
 "tools":["web_search","web_fetch","x_search"],
 "discoverSkills":false,
 "agentsMd":false}
```

`tools` is an allowlist (empty ⇒ inherit all); `disallowedTools` is a denylist and
wins over `tools`. Built-in tool ids include `read_file`, `grep`, `list_dir`,
`search_replace`, `run_terminal_cmd`, `web_search`, `web_fetch`, plus the hosted
`x_search`; `Agent` / `Agent(explore)` entries control subagent spawning.
Restricting the toolset also shrinks the system prompt — measured ~62k → ~13k
input tokens on a search turn.

Other useful fields: `promptMode`, `effort`, `maxTurns`, `permissionMode`,
`model`, `mcpServers`, `memory`, `toolOverrides`, `initialPrompt`.

## Prompting

```json
{"jsonrpc":"2.0","id":3,"method":"session/prompt","params":{
  "sessionId":"019f9c…",
  "prompt":[{"type":"text","text":"…"}],
  "_meta":{
    "toolOverrides":{"xSearch":{"dateBound":{"fromDate":"2026-07-01","toDate":"2026-07-26"}}},
    "outputSchema":{"type":"object","properties":{…}}}}}
```

`_meta.toolOverrides` is a **per-turn** patch: an object sets, `null` clears,
absent leaves. Only `xSearch` (`dateBound.fromDate` / `.toDate`, zero-padded
`YYYY-MM-DD`, `from ≤ to`) and `webSearch` (`allowedDomains`) are accepted;
unknown keys are rejected. The applied value is echoed in the response
`_meta.toolOverrides`.

`_meta.outputSchema` constrains output to a JSON Schema. Caveat: it constrains
**every** assistant message in the turn, including the "still searching…"
preambles — so parse the **last** schema-shaped message, not the concatenation.

The response is `{"stopReason":"end_turn", "_meta":{…}}` where `_meta` carries
`sessionId`, `modelId`, `usage` (`inputTokens`, `outputTokens`,
`cachedReadTokens`, `reasoningTokens`, `modelCalls`, `apiDurationMs`,
`costUsdTicks`, `numTurns`) and the tool-override echo.

Prompt text starting with `/` runs a slash command; the full list arrives in
`initialize` under `_meta.availableCommands`. Note that `/deep-research` and
`/workflow` **start a background workflow and return within seconds** — the turn
ends with "started in the background", and the report arrives later via
`x.ai/session_notification` updates that a short-lived client will never see. This
is why the skill's `research` command does the work inside a normal turn instead.

## Streaming

`session/update` notifications, keyed by `update.sessionUpdate`:

| Value | Payload |
|---|---|
| `agent_message_chunk` | `content.text` — response text. Consecutive chunks form one message; a tool call between them starts a new one |
| `agent_thought_chunk` | Reasoning trace |
| `tool_call` | New call: `toolCallId`, `title`, `kind`, `status`, `rawInput` |
| `tool_call_update` | `status` and `rawOutput` for an in-flight call |
| `plan` | The agent's execution plan |

X search calls arrive as `kind:"search"` with `rawInput:{"variant":"XSearch","backend":true}`.
The interesting part lands on the **update**, in `rawOutput`:

```json
{"name":"x_keyword_search",
 "input":"{\"query\":\"from:elonmusk since:2026-07-19\",\"limit\":\"10\",\"mode\":\"Latest\"}",
 "call_id":"xs_…","id":"ctc_…"}
```

`rawOutput.input` is a **JSON string** that must be parsed again. `rawOutput`
carries the call, not the retrieved posts — those are consumed server-side and
surface only through the model's answer. This is why the answer's citations are
the source of truth, and why the skill prints the query trace separately.

Web search calls use `variant:"WebSearch"` with `rawOutput.action.type` of
`search` (`.query`, `.sources[].url`), `open_page` (`.url`), or `find`.

## Agent → client requests

With `--always-approve` and `fs`/`terminal` capabilities off, none should arrive.
If they do, answer them — an unanswered request stalls the turn.

`session/request_permission` expects:

```json
{"jsonrpc":"2.0","id":<id>,"result":{"outcome":{"outcome":"selected","optionId":"<from params.options>"}}}
```

Option `kind`s are `allow_once`, `allow_always`, `reject_once`, `reject_always`.
Reply `{"outcome":{"outcome":"cancelled"}}` to abort. Anything else you do not
implement: respond with JSON-RPC error `-32601`.

## x.ai extension methods

Beyond base ACP, prefixed `x.ai/`: `fs/*` (`list`, `exists`, `read_file`,
`write_file`), `git/*` and `git/worktree/*`, `search/*` (`fuzzy/open`,
`fuzzy/change`, `content`), `terminal/*`, `session/fork`, `rewind/*`,
`compact_conversation`, `prompt_history`, `auth/*`, `telemetry/*`. Non-exhaustive
and version-dependent — discover them from the `initialize` response rather than
hardcoding.

## Official SDKs

TypeScript `@agentclientprotocol/sdk` · Rust `agent-client-protocol` ·
Python `agent-client-protocol-python` · Go `acp-go-sdk` · Kotlin `acp`
