# dsh-x-search HTTP API

The script is a thin client over this. Everything is JSON; every request except
`/healthz` needs `Authorization: Bearer <token>`.

| Route | Body |
|---|---|
| `GET /healthz` | — (`{ok, session, updatedAt}`; no auth) |
| `GET /api/status` | — (browser, limiter, model availability, session count) |
| `POST /api/search` | `{request, since?, until?, sort?, lang?, limit?, allowedHandles?, excludedHandles?, excludeReplies?, replyLang?, rules?, raw?, queries?}` |
| `POST /api/user` | `{request, replyLang?, raw?}` |
| `POST /api/thread` | `{post, replyLang?, raw?}` |
| `POST /api/followup` | `{sessionId, request, replyLang?}` |

Success: `{ok: true, sessionId, answer, posts | recentPosts | thread+replies, queries, planner, report, warnings, elapsedMs, limiter}`.
`planner` is `llm` / `passthrough` / `explicit`; `report` is `llm` / `raw`.

Failure: `{ok: false, code, message, retryAfterMs?}` with the status mapped from `code`:

| code | status | meaning |
|---|---|---|
| `BAD_REQUEST` | 400 | parameter problem (dates, handle lists, empty request) |
| `UNAUTHORIZED` | 401 | missing/wrong bearer token |
| `NOT_FOUND` | 404 | account or post not visible; unknown/expired session |
| `RATE_LIMITED` | 429 | server quota or X 429; `Retry-After` header |
| `SESSION_EXPIRED` | 503 | X login cookies on the server no longer work |
| `BROWSER_UNAVAILABLE` | 503 | Chromium did not start |
| `MODEL_UNAVAILABLE` | 503 | no model route (follow-ups need one; search falls back to raw) |
| `UPSTREAM_TIMEOUT` | 504 | page loaded, data call never came |
| `UPSTREAM_CHANGED` | 502 | response parsed to nothing — X changed its shape |

A post:

```json
{"id":"…","url":"https://x.com/<handle>/status/<id>","text":"…","createdAt":"2026-09-22T04:57:00.000Z",
 "author":{"id":"…","handle":"…","name":"…","followers":123,"verified":true},
 "metrics":{"likes":1,"reposts":2,"replies":3,"quotes":4,"bookmarks":5,"views":6},
 "conversationId":"…","inReplyToId":"…","inReplyToHandle":"…","quoted":{…},"repostedBy":{…},"media":["photo"],"links":["https://…"],"lang":"en"}
```

Raw `curl`:

```bash
curl -H "authorization: Bearer $TOKEN" -H content-type:application/json \
     -d '{"request":"what are people saying about zed this week","limit":20,"replyLang":"Chinese"}' \
     https://x-search.example.com/api/search
```
