# X (Twitter) search through Grok

Grok's `x_search` is a **backend-hosted tool**: xAI runs it server-side during
inference against X's own index. You never call it directly — you describe what
you want and Grok picks the sub-tool, writes the query, and reads the results.
That is why the request text matters more than any flag.

## The four sub-tools

Grok chooses among these. Knowing them lets you write a request that steers the
choice.

| Sub-tool | Input | What it does |
|---|---|---|
| `x_keyword_search` | `{query, limit, mode: "Latest"\|"Top"}` | Lexical search over X's index using full advanced-search operator syntax |
| `x_semantic_search` | `{query, limit, usernames?, from_date?, to_date?}` | Meaning-based retrieval; finds posts that express an idea in different words. `usernames` scopes it to specific accounts |
| `x_user_search` | `{query, count}` | Finds accounts by name, handle, or profile description |
| `x_thread_fetch` | `{post_id}` | Full text of one post plus its thread and reply context |

**Steering by phrasing:**

- Name an account, a date, or an exact phrase → keyword search.
  *"posts from @sama since June about compute"*
- Describe a topic or an attitude → semantic search.
  *"posts complaining that agent frameworks are over-engineered"*
- Ask "who is / find the account" → user search.
  *"find the X account of the person who maintains ripgrep"*
- Give a post URL or ask "what did people reply" → thread fetch.
- Ask for both coverage and precision → say **"run both keyword and semantic
  searches"**; Grok will.

## X advanced-search operators

Put these directly in the request when you need exact control.

**Accounts**
`from:handle` · `to:handle` · `@handle` (mentions) · `list:LIST_ID`

**Content**
`"exact phrase"` · `a OR b` · `-excluded` · `#hashtag` · `$TICKER` · `url:domain.com`

**Time**
`since:YYYY-MM-DD` · `until:YYYY-MM-DD` · `within_time:2d` · `since_time:UNIX` · `until_time:UNIX`

**Engagement thresholds** — the best noise filter there is
`min_faves:100` · `min_retweets:50` · `min_replies:10`

**Type filters**
`filter:links` · `filter:media` · `filter:images` · `filter:videos` · `filter:native_video`
`filter:replies` / `-filter:replies` · `filter:quote` · `filter:verified` · `filter:follows`
`filter:nativeretweets` / `-filter:retweets` · `filter:spaces`

**Language / place**
`lang:en` (`zh`, `ja`, `es`, …) · `near:"San Francisco" within:15mi` · `geocode:lat,lon,10km`

**Conversation graph**
`conversation_id:ID` · `in_reply_to_tweet_id:ID` · `quoted_tweet_id:ID`

**Ranking:** `mode: "Latest"` = reverse-chronological, `mode: "Top"` = engagement-ranked.
`--sort latest|top` sets the preference.

Operators confirmed in use by this integration: `from:`, `since:`, `lang:`, `OR`,
`-`, `"phrase"`, `min_faves:`, `-filter:replies`, `conversation_id:`,
`in_reply_to_tweet_id:`. The rest are standard X syntax.

## Recipes

```bash
S=<skill-path>/scripts/grok_acp.py

# Signal only — engagement floor kills the noise
python3 $S x 'reactions to the new Anthropic release, min_faves:500, exclude replies' --sort top

# One account's history in a window
python3 $S x 'from:karpathy since:2026-01-01 until:2026-07-01, no replies' --limit 30

# Sentiment split, both search modes
python3 $S x 'run keyword AND semantic searches on Rust async runtimes this month; group posts into positive / negative / mixed with counts'

# Who is talking about us
python3 $S x '"our-product-name" OR @ourhandle, last 14 days, exclude our own account' --sort latest

# Non-English coverage
python3 $S x 'discussion of Sora 3 in Japanese' --lang ja --reply-lang English

# Find the account, then read it
python3 $S user 'the person who wrote the Zig compiler'
python3 $S x 'from:<handle-from-above> most-discussed posts' --sort top

# A thread and everything hanging off it
python3 $S thread https://x.com/user/status/1234567890123456789

# Structured, for a pipeline
python3 $S x 'top 10 posts about $TSLA earnings today' --sort top \
  --schema '{"type":"object","properties":{"posts":{"type":"array","items":{"type":"object",
    "properties":{"handle":{"type":"string"},"date":{"type":"string"},"url":{"type":"string"},
    "likes":{"type":"integer"},"stance":{"enum":["bullish","bearish","neutral"]},
    "text":{"type":"string"}},"required":["handle","url","text","stance"]}}},"required":["posts"]}' \
  --json
```

## Limits worth knowing

- **`--since` / `--until` are enforced two ways.** The script sets the wire-level
  `xSearch.dateBound` **and** tells Grok to put `since:` / `until:` into the query
  itself. The wire-level bound is honoured only by `x_keyword_search` and
  `x_semantic_search` — `x_user_search` and `x_thread_fetch` ignore it (the agent
  declares this in its `initialize` response), and in testing it did not reliably
  filter on its own. The in-query operators are what actually bite. If a date
  window matters, also state it in the request text.
- **`--limit` is a hint, not a cap.** It reaches the model as instruction text.
  Grok often runs several queries with its own limits and reports the union.
- **Deleted, protected, and blocked-account posts are invisible.** An empty result
  can mean "does not exist", "is protected", or "the operators were too narrow" —
  read the "queries run" trace on stderr before concluding.
- **Engagement counts are a snapshot** from when the tool ran, not live.
- **Views are often missing** on older or low-reach posts; Grok omits the field
  rather than guessing.
- **One turn ≈ 20–60s.** Deep multi-query work runs longer; raise `--timeout`.

## When results disappoint

1. Read the stderr **"queries run"** list. It shows exactly what was searched.
2. Too few results → drop `min_faves:`/`filter:` constraints, widen the date
   window, or add `--rules "also try semantic search and alternate spellings"`.
3. Too much noise → add an engagement floor and `-filter:replies`.
4. Wrong account → run `user` first to pin the handle, then search `from:` it.
5. Truncated post text → ask for `thread` on that post; `x_thread_fetch` returns
   the full text.
6. Still stuck → `--session <id>` and ask Grok directly: *"which queries did you
   run, and what else would you try?"*
