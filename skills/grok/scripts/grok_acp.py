#!/usr/bin/env python3
"""Drive the locally-installed Grok Build agent over ACP (Agent Client Protocol).

Speaks JSON-RPC 2.0 to `grok agent --always-approve stdio`, which exposes Grok's
backend-hosted `x_search` (X/Twitter) and `web_search` tools. Standard library
only; works from any agent harness that can run a shell command.

Docs: https://docs.x.ai/build/overview  ·  https://agentclientprotocol.com
"""

from __future__ import annotations

import argparse
import json
import os
import queue
import re
import shutil
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Any, Callable, Iterable

# --------------------------------------------------------------------------- #
# Binary discovery
# --------------------------------------------------------------------------- #

DEFAULT_TIMEOUT = 300


def find_grok() -> str:
    """Resolve the grok binary: $GROK_BIN, then PATH, then the default install."""
    explicit = os.environ.get("GROK_BIN")
    if explicit:
        if os.path.isfile(explicit) and os.access(explicit, os.X_OK):
            return explicit
        die(f"GROK_BIN={explicit!r} is not an executable file")
    found = shutil.which("grok")
    if found:
        return found
    fallback = Path.home() / ".grok" / "bin" / "grok"
    if fallback.is_file() and os.access(fallback, os.X_OK):
        return str(fallback)
    die(
        "grok CLI not found.\n"
        "  Install:  curl -fsSL https://x.ai/cli/install.sh | bash\n"
        "  Then:     grok login\n"
        "  Or set GROK_BIN=/path/to/grok"
    )


def die(msg: str, code: int = 2) -> None:
    print(f"error: {msg}", file=sys.stderr)
    raise SystemExit(code)


def scratch_dir() -> str:
    """An empty workspace so search runs cannot see or touch the caller's repo."""
    d = Path(os.environ.get("GROK_SKILL_SCRATCH") or (Path.home() / ".cache" / "grok-skill" / "workspace"))
    d.mkdir(parents=True, exist_ok=True)
    return str(d)


# --------------------------------------------------------------------------- #
# ACP client
# --------------------------------------------------------------------------- #


class AcpError(RuntimeError):
    pass


class GrokAgent:
    """One `grok agent stdio` subprocess, one ACP conversation."""

    def __init__(
        self,
        cwd: str,
        model: str | None = None,
        effort: str | None = None,
        always_approve: bool = True,
        raw_log: str | None = None,
        on_progress: Callable[[str], None] | None = None,
    ) -> None:
        self.bin = find_grok()
        self.cwd = cwd
        self.model = model
        self.effort = effort
        self.always_approve = always_approve
        self.on_progress = on_progress or (lambda _m: None)
        self.raw_log = open(raw_log, "w", encoding="utf-8") if raw_log else None

        self.proc: subprocess.Popen[str] | None = None
        self._q: queue.Queue[dict[str, Any] | None] = queue.Queue()
        self._stderr: list[str] = []
        self._next_id = 0
        self.init_result: dict[str, Any] = {}
        self.session_id: str | None = None

    # -- lifecycle ---------------------------------------------------------- #

    def __enter__(self) -> "GrokAgent":
        cmd = [self.bin, "agent"]
        if self.model:
            cmd += ["--model", self.model]
        if self.effort:
            cmd += ["--reasoning-effort", self.effort]
        if self.always_approve:
            cmd += ["--always-approve"]
        cmd += ["stdio"]

        self.proc = subprocess.Popen(
            cmd,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
            bufsize=1,
            cwd=self.cwd,
        )
        threading.Thread(target=self._pump_stdout, daemon=True).start()
        threading.Thread(target=self._pump_stderr, daemon=True).start()
        return self

    def __exit__(self, *_exc: object) -> None:
        self.close()

    def close(self) -> None:
        if self.proc and self.proc.poll() is None:
            try:
                self.proc.stdin.close()  # type: ignore[union-attr]
            except Exception:
                pass
            try:
                self.proc.terminate()
                self.proc.wait(timeout=5)
            except Exception:
                try:
                    self.proc.kill()
                except Exception:
                    pass
        if self.raw_log:
            self.raw_log.close()
            self.raw_log = None

    # -- plumbing ----------------------------------------------------------- #

    def _pump_stdout(self) -> None:
        assert self.proc and self.proc.stdout
        for line in self.proc.stdout:
            line = line.strip()
            if not line:
                continue
            self._log("<< " + line)
            try:
                self._q.put(json.loads(line))
            except json.JSONDecodeError:
                pass  # non-JSON chatter on stdout is not part of the protocol
        self._q.put(None)  # EOF sentinel

    def _pump_stderr(self) -> None:
        assert self.proc and self.proc.stderr
        for line in self.proc.stderr:
            self._stderr.append(line)
            self._log("!! " + line.rstrip())
            del self._stderr[:-200]

    def _log(self, s: str) -> None:
        if self.raw_log:
            self.raw_log.write(s + "\n")
            self.raw_log.flush()

    def _send(self, obj: dict[str, Any]) -> None:
        assert self.proc and self.proc.stdin
        s = json.dumps(obj, ensure_ascii=False)
        self._log(">> " + s)
        try:
            self.proc.stdin.write(s + "\n")
            self.proc.stdin.flush()
        except (BrokenPipeError, ValueError):
            raise AcpError(self._exit_reason())

    def _exit_reason(self) -> str:
        tail = "".join(self._stderr[-15:]).strip()
        rc = self.proc.poll() if self.proc else None
        base = f"grok agent exited (code {rc})" if rc is not None else "grok agent closed its stdin"
        return f"{base}\n{tail}" if tail else base

    def request(
        self,
        method: str,
        params: dict[str, Any],
        timeout: float = DEFAULT_TIMEOUT,
        on_update: Callable[[dict[str, Any]], None] | None = None,
    ) -> dict[str, Any]:
        """Send a request and pump the message loop until its response arrives."""
        self._next_id += 1
        rid = self._next_id
        self._send({"jsonrpc": "2.0", "id": rid, "method": method, "params": params})

        deadline = time.monotonic() + timeout
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise AcpError(f"timed out after {timeout:.0f}s waiting for {method}")
            try:
                msg = self._q.get(timeout=min(remaining, 1.0))
            except queue.Empty:
                continue
            if msg is None:
                raise AcpError(self._exit_reason())

            if msg.get("id") == rid and ("result" in msg or "error" in msg):
                if "error" in msg:
                    err = msg["error"]
                    raise AcpError(f"{method}: {err.get('message')} {err.get('data') or ''}".strip())
                return msg.get("result") or {}

            if "method" in msg and msg.get("id") is not None:
                self._answer_agent_request(msg)
            elif msg.get("method") == "session/update" and on_update:
                on_update(msg.get("params", {}).get("update") or {})

    def _answer_agent_request(self, msg: dict[str, Any]) -> None:
        """Agent -> client calls. Approve permissions; decline what we never opted into."""
        method = msg.get("method")
        rid = msg.get("id")
        if method == "session/request_permission":
            options = (msg.get("params") or {}).get("options") or []
            pick = next((o for o in options if o.get("kind") == "allow_always"), None) or next(
                (o for o in options if o.get("kind") == "allow_once"), None
            )
            if pick:
                self.on_progress(f"permission auto-approved: {(msg.get('params') or {}).get('toolCall', {}).get('title', '')}")
                self._send({"jsonrpc": "2.0", "id": rid, "result": {"outcome": {"outcome": "selected", "optionId": pick["optionId"]}}})
                return
            self._send({"jsonrpc": "2.0", "id": rid, "result": {"outcome": {"outcome": "cancelled"}}})
            return
        self._send({"jsonrpc": "2.0", "id": rid, "error": {"code": -32601, "message": f"client does not implement {method}"}})

    # -- protocol ----------------------------------------------------------- #

    def initialize(self, timeout: float = 60) -> dict[str, Any]:
        self.init_result = self.request(
            "initialize",
            {
                "protocolVersion": 1,
                # No fs/terminal capability: Grok uses its own workspace tools and
                # never asks this process to read or write files on its behalf.
                "clientCapabilities": {"fs": {"readTextFile": False, "writeTextFile": False}, "terminal": False},
                "_meta": {"clientIdentifier": "grok-skill"},
            },
            timeout=timeout,
        )
        return self.init_result

    def new_session(self, meta: dict[str, Any] | None = None, timeout: float = 120) -> str:
        res = self.request(
            "session/new",
            {"cwd": self.cwd, "mcpServers": [], "_meta": {"yoloMode": self.always_approve, **(meta or {})}},
            timeout=timeout,
        )
        self.session_id = res.get("sessionId")
        if not self.session_id:
            raise AcpError("session/new returned no sessionId")
        return self.session_id

    def load_session(self, session_id: str, meta: dict[str, Any] | None = None, timeout: float = 180) -> str:
        self.request(
            "session/load",
            {"sessionId": session_id, "cwd": self.cwd, "mcpServers": [], "_meta": {"yoloMode": self.always_approve, **(meta or {})}},
            timeout=timeout,
        )
        self.session_id = session_id
        return session_id

    def prompt(self, text: str, meta: dict[str, Any] | None = None, timeout: float = DEFAULT_TIMEOUT) -> dict[str, Any]:
        """Send one prompt turn; return the assembled answer, tool calls and usage."""
        if not self.session_id:
            raise AcpError("no session; call new_session() or load_session() first")

        segments: list[str] = []
        pending: list[str] = []
        tool_calls: dict[str, dict[str, Any]] = {}
        order: list[str] = []
        broke = [False]  # a tool call since the last text chunk => paragraph break

        def flush() -> None:
            if pending:
                segments.append("".join(pending).strip())
                pending.clear()

        def on_update(u: dict[str, Any]) -> None:
            kind = u.get("sessionUpdate")
            if kind == "agent_message_chunk":
                if broke[0]:
                    flush()
                    broke[0] = False
                pending.append((u.get("content") or {}).get("text") or "")
            elif kind == "agent_thought_chunk":
                pass
            elif kind in ("tool_call", "tool_call_update"):
                broke[0] = True
                tid = u.get("toolCallId") or ""
                entry = tool_calls.setdefault(tid, {"name": None, "title": u.get("title"), "input": None, "status": None})
                if tid not in order:
                    order.append(tid)
                entry["status"] = u.get("status") or entry["status"]
                raw_out = u.get("rawOutput") if isinstance(u.get("rawOutput"), dict) else {}
                if raw_out.get("name"):
                    # x_search: the sub-tool name plus a re-encoded JSON input string.
                    entry["name"] = raw_out["name"]
                    entry["input"] = _parse_maybe_json(raw_out.get("input"))
                    self.on_progress(f"{entry['name']} {_compact(entry['input'])}")
                elif isinstance(raw_out.get("action"), dict):
                    # web_search: search / open_page / find, keyed by action.type.
                    action = raw_out["action"]
                    entry["name"] = f"web_{action.get('type') or 'search'}"
                    entry["input"] = action
                    self.on_progress(f"{entry['name']} {_compact(action.get('query') or action.get('url') or action.get('pattern') or '')}")
                elif kind == "tool_call":
                    raw_in = u.get("rawInput") or {}
                    label = raw_in.get("variant") or u.get("title") or "tool"
                    entry["name"] = entry["name"] or (u.get("title") or "").rstrip(":") or label
                    self.on_progress(f"{label} …")

        res = self.request("session/prompt", {"sessionId": self.session_id, "prompt": [{"type": "text", "text": text}], "_meta": meta or {}}, timeout=timeout, on_update=on_update)
        flush()

        calls = [dict(tool_calls[t], id=t) for t in order]
        segments = [s for s in segments if s]
        return {
            "answer": "\n\n".join(segments),
            # One entry per assistant message. Under an outputSchema every message
            # (including the "still searching…" preambles) is schema-shaped, so the
            # real payload is the last one that parses.
            "segments": segments,
            "tool_calls": calls,
            "queries": _extract_queries(calls),
            "stop_reason": res.get("stopReason"),
            "meta": res.get("_meta") or {},
        }


def _parse_maybe_json(v: Any) -> Any:
    if isinstance(v, str):
        try:
            return json.loads(v)
        except json.JSONDecodeError:
            return v
    return v


def _compact(v: Any, width: int = 110) -> str:
    if v is None:
        return ""
    s = json.dumps(v, ensure_ascii=False) if not isinstance(v, str) else v
    return s if len(s) <= width else s[: width - 1] + "…"


def _extract_queries(calls: Iterable[dict[str, Any]]) -> list[str]:
    """The exact search strings Grok ran — the most re-usable part of the trace."""
    out: list[str] = []
    for c in calls:
        inp, name = c.get("input"), c.get("name") or ""
        if not isinstance(inp, dict):
            continue
        q = inp.get("query") or inp.get("post_id") or inp.get("url") or inp.get("pattern")
        if not q:
            continue
        extras = [f"{k}={inp[k]}" for k in ("mode", "limit", "count", "usernames") if inp.get(k)]
        if isinstance(inp.get("sources"), list):
            extras.append(f"{len(inp['sources'])} sources")
        line = f"{name}: {q}" + (f"  [{', '.join(map(str, extras))}]" if extras else "")
        if line not in out:
            out.append(line)
    return out


# --------------------------------------------------------------------------- #
# Prompt policy — what makes Grok good at each job
# --------------------------------------------------------------------------- #

# Restricting the toolset also trims Grok's system prompt (~62k -> ~13k input
# tokens observed), so search runs are both safer and cheaper.
SEARCH_PROFILE = {
    "name": "grok-research",
    "description": "Live X (Twitter) and web research. No filesystem, shell, or subagent access.",
    "tools": ["web_search", "web_fetch", "x_search"],
    "discoverSkills": False,
    "agentsMd": False,
}

X_RULES = """\
You are an X (Twitter) research engine. The caller is another AI agent that will
act on your answer verbatim, so precision beats prose.

Hosted x_search sub-tools available to you:
- x_keyword_search {query, limit, mode:"Latest"|"Top"} - full X advanced-search
  operator syntax: from: to: @ since: until: min_faves: min_retweets: min_replies:
  filter:links filter:media filter:images filter:videos filter:replies
  -filter:replies filter:verified filter:quote lang: url: list: conversation_id:
  "exact phrase", OR, -exclusion.
- x_semantic_search {query, limit, usernames?} - meaning-based retrieval; use it
  when the request is topical rather than lexical, or to catch posts that phrase
  the idea differently.
- x_user_search {query, count} - find accounts by name, handle, or description.
- x_thread_fetch {post_id} - full text of a post plus its thread/reply context.

Method:
1. Translate the request into explicit operators. Reach for x_keyword_search when
   accounts, dates, or exact phrases are named; x_semantic_search when the request
   is about a topic or an idea. Run both when coverage matters.
2. Run SEVERAL queries with different operator combinations, not one. Vary mode
   between "Latest" (recency) and "Top" (reach). Widen or narrow after seeing
   results.
3. Call x_thread_fetch on any post that is truncated, is part of a thread, or is a
   reply/quote whose context changes the meaning. Never summarize a post you have
   not read in full.
4. Stop when new queries stop returning new posts.

Report:
- Only what the tools returned. If a query came back empty, say so. Never invent a
  post, ID, handle, date, or metric, and never reconstruct one from memory.
- Cite every post as: @handle - YYYY-MM-DD - https://x.com/<handle>/status/<id>
- Quote the post's own words for anything load-bearing. If you translate, keep the
  original text alongside.
- Include engagement counts (likes / reposts / replies / views) when the tool
  returned them; omit the field rather than guessing.
- Flag replies, quote-posts, and reposts as such.
- Close with a "Queries run" list of the exact search strings you used, so the
  caller can widen or re-run them.
"""

WEB_RULES = """\
You are a live web research engine. The caller is another AI agent that will act on
your answer verbatim.

- Search the live web; do not answer from memory. If your search returns nothing
  usable, say so instead of filling the gap.
- Run several differently-phrased queries before concluding. Fetch the primary
  source rather than trusting a summary of it.
- Cite every claim with a full URL, and give the publication date when the page
  shows one.
- Separate what the sources state from what you infer. Mark disagreement between
  sources rather than averaging it away.
- Close with a "Sources" list of the URLs you actually opened.
"""

RESEARCH_RULES = (
    WEB_RULES
    + """
This is a deep-research turn, so go wider than a single search pass:

1. Decompose the topic into the distinct sub-questions that must each be answered
   before the whole can be. State them before you search.
2. Work each sub-question separately, with several differently-phrased queries.
   Use X search alongside web search when practitioner reaction, first-hand
   accounts, or very recent developments are relevant.
3. Cross-check every load-bearing claim against a second independent source. Say
   which claims you could confirm twice and which rest on one source.
4. Actively look for evidence that contradicts your emerging answer before you
   settle on it.
5. Structure the report as: answer up front, then per sub-question findings, then
   an explicit "Uncertain / unresolved" section, then Sources.

Do not run a background workflow or hand the work to a subagent — research and
report within this turn.
"""
)

ASK_RULES = """\
The caller is another AI agent, not a human at a terminal. Answer with the finished
result, not a plan or a progress narration. Use live search whenever the answer
depends on current facts, and cite URLs for anything you retrieved. State plainly
when something could not be verified.
"""

MODE_HINT = {
    "latest": 'Order by recency: prefer mode "Latest" and sort the report newest-first.',
    "top": 'Order by reach: prefer mode "Top" and sort the report by engagement.',
}


def build_prompt(cmd: str, subject: str, args: argparse.Namespace) -> tuple[str, str]:
    """Return (rules, prompt_text) for a command."""
    directives: list[str] = []
    if args.since or args.until:
        window = []
        if args.since:
            window.append(f"since:{args.since}")
        if args.until:
            window.append(f"until:{args.until}")
        directives.append(f"Restrict results to {' '.join(window)} and put these operators in the query itself.")
    if getattr(args, "sort", None):
        directives.append(MODE_HINT[args.sort])
    if getattr(args, "limit", None):
        directives.append(f"Return about {args.limit} results.")
    if getattr(args, "lang", None):
        directives.append(f"Restrict to lang:{args.lang} posts.")
    if getattr(args, "reply_lang", None):
        directives.append(f"Write the report in {args.reply_lang}.")
    tail = ("\n\nConstraints:\n" + "\n".join(f"- {d}" for d in directives)) if directives else ""

    if cmd == "x":
        return X_RULES, f"Search X (Twitter) and answer this request:\n\n<request>\n{subject}\n</request>{tail}"
    if cmd == "user":
        return X_RULES, (
            f"Identify the X account(s) matching: <request>\n{subject}\n</request>\n\n"
            "Use x_user_search first. For each account report handle, display name, bio, "
            "follower count, verified status, join date, location and website when the tool "
            "returns them, plus the profile URL. Then use x_keyword_search with `from:<handle>` "
            "to show that account's recent activity. If several accounts could match, list the "
            "candidates and say which one fits and why — do not silently pick one." + tail
        )
    if cmd == "thread":
        pid = extract_post_id(subject)
        target = f"post_id {pid}" if pid else f"the post at {subject}"
        return X_RULES, (
            f"Use x_thread_fetch on {target} and report the full thread.\n\n"
            "Give the root post's author, date, permalink and complete text; then every post in "
            "the thread in order; then the notable replies and quote-posts with their authors and "
            "permalinks. If the post quotes or replies to another post, fetch that one too so the "
            "context is complete. Reproduce the text — do not paraphrase it away." + tail
        )
    if cmd == "web":
        return WEB_RULES, f"Research this on the live web and answer:\n\n<request>\n{subject}\n</request>{tail}"
    if cmd == "research":
        return RESEARCH_RULES, f"Research this thoroughly and report:\n\n<topic>\n{subject}\n</topic>{tail}"
    return ASK_RULES, subject + tail


POST_ID_RE = re.compile(r"(?:status(?:es)?/)(\d{5,25})")


def extract_post_id(s: str) -> str | None:
    m = POST_ID_RE.search(s)
    if m:
        return m.group(1)
    s = s.strip()
    return s if s.isdigit() and 5 <= len(s) <= 25 else None


def load_schema(spec: str) -> dict[str, Any]:
    if spec == "-":
        raw = sys.stdin.read()
    elif spec.lstrip().startswith("{"):
        raw = spec
    else:
        try:
            raw = Path(spec).read_text(encoding="utf-8")
        except OSError as e:
            die(f"--schema: cannot read {spec!r}: {e}")
            return {}
    try:
        schema = json.loads(raw)
    except json.JSONDecodeError as e:
        die(f"--schema is not valid JSON: {e}")
    if not isinstance(schema, dict):
        die("--schema must be a JSON object describing a JSON Schema")
    return schema


DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def date_bound(args: argparse.Namespace) -> dict[str, Any] | None:
    """xSearch.dateBound is a best-effort server-side window (see references/x-search.md)."""
    bound = {}
    if args.since:
        bound["fromDate"] = args.since
    if args.until:
        bound["toDate"] = args.until
    for k, v in bound.items():
        if not DATE_RE.match(v):
            die(f"{k} must be YYYY-MM-DD (got {v!r})")
    return {"xSearch": {"dateBound": bound}} if bound else None


# --------------------------------------------------------------------------- #
# Commands
# --------------------------------------------------------------------------- #


def cmd_check(args: argparse.Namespace) -> int:
    binary = find_grok()
    print(f"binary   {binary}")
    for label, flags in (("version ", ["--version"]), ("models  ", ["models"])):
        try:
            out = subprocess.run([binary, *flags], capture_output=True, text=True, timeout=60)
            print(f"{label} {(out.stdout or out.stderr).strip().splitlines()[0] if (out.stdout or out.stderr).strip() else '(no output)'}")
            if flags == ["models"]:
                for line in (out.stdout or "").splitlines()[1:]:
                    if line.strip():
                        print(f"         {line.strip()}")
        except Exception as e:  # noqa: BLE001
            print(f"{label} FAILED: {e}")

    print("\nACP handshake…")
    with GrokAgent(cwd=scratch_dir(), on_progress=lambda m: None) as agent:
        res = agent.initialize()
        meta = res.get("_meta") or {}
        caps = ((res.get("agentCapabilities") or {}).get("_meta") or {}).get("x.ai/capabilities") or {}
        print(f"  agent          {meta.get('agentVersion')}")
        print(f"  auth           {meta.get('defaultAuthMethodId') or 'NOT AUTHENTICATED — run: grok login'}")
        print(f"  model          {((meta.get('modelState') or {}).get('currentModelId'))}")
        print(f"  loadSession    {(res.get('agentCapabilities') or {}).get('loadSession')}")
        print(f"  x_search subtools honouring dateBound: {json.dumps(caps.get('toolOverrides') or {})}")
        agent.new_session(meta={"agentProfile": SEARCH_PROFILE})
        print(f"  session/new    ok ({agent.session_id})")
    print(f"\nworkspace  {scratch_dir()}  (isolated; search runs never see your repo)")
    print("ready.")
    return 0


def cmd_run(args: argparse.Namespace) -> int:
    subject = " ".join(args.query).strip()
    if not subject:
        die("empty query")

    if getattr(args, "workspace", False) and not args.cwd:
        die("ask --workspace needs --cwd DIR — the directory you are handing Grok")
    quiet = args.json or args.quiet
    timeout = args.timeout if args.timeout is not None else (900 if args.command == "research" else DEFAULT_TIMEOUT)
    started = time.monotonic()

    def progress(msg: str) -> None:
        if not quiet:
            print(f"  · {msg}", file=sys.stderr, flush=True)

    workspace = args.cwd or scratch_dir()
    # The search-only profile also blocks subagent spawning (a non-empty `tools`
    # allowlist with no Agent directive), which keeps `research` synchronous.
    restricted = args.command in ("x", "user", "thread", "web", "research") or (args.command == "ask" and not args.workspace)
    rules, text = build_prompt(args.command, subject, args)
    if args.rules:
        rules = f"{rules}\n\nAdditional caller instructions:\n{args.rules}"

    session_meta: dict[str, Any] = {"rules": rules}
    if restricted and not args.no_restrict:
        session_meta["agentProfile"] = SEARCH_PROFILE

    prompt_meta: dict[str, Any] = {}
    if args.command in ("x", "user", "thread"):
        bound = date_bound(args)
        if bound:
            prompt_meta["toolOverrides"] = bound
    schema = load_schema(args.schema) if args.schema else None
    if schema:
        prompt_meta["outputSchema"] = schema

    if not quiet:
        print(f"[grok] {args.command} · workspace {workspace}", file=sys.stderr, flush=True)

    try:
        with GrokAgent(
            cwd=workspace,
            model=args.model,
            effort=args.effort,
            raw_log=args.raw_log,
            on_progress=progress,
        ) as agent:
            agent.initialize()
            if args.session:
                try:
                    agent.load_session(args.session, meta=session_meta)
                except AcpError as e:
                    raise AcpError(
                        f"could not resume session {args.session}: {e}\n"
                        "Sessions are per-workspace — pass the same --cwd you used originally, "
                        "or drop --session to start a fresh one."
                    ) from None
            else:
                agent.new_session(meta=session_meta)
            result = agent.prompt(text, meta=prompt_meta, timeout=timeout)
            session_id = agent.session_id
    except AcpError as e:
        msg = str(e)
        if "auth" in msg.lower():
            msg += "\nSign in first:  grok login"
        if args.json:
            print(json.dumps({"ok": False, "command": args.command, "query": subject, "error": msg}, ensure_ascii=False, indent=2))
        else:
            print(f"error: {msg}", file=sys.stderr)
        return 1

    elapsed = time.monotonic() - started
    answer = result["answer"]
    structured = None
    if schema:
        for seg in reversed(result["segments"]):
            try:
                structured = json.loads(_strip_fence(seg))
            except json.JSONDecodeError:
                continue
            answer = _strip_fence(seg)  # drop the schema-shaped progress preambles
            break

    if args.json:
        print(
            json.dumps(
                {
                    "ok": True,
                    "command": args.command,
                    "query": subject,
                    "answer": answer,
                    "structured": structured,
                    "queries": result["queries"],
                    "tool_calls": result["tool_calls"],
                    "session_id": session_id,
                    "stop_reason": result["stop_reason"],
                    "usage": (result["meta"] or {}).get("usage"),
                    "tool_overrides": (result["meta"] or {}).get("toolOverrides"),
                    "elapsed_sec": round(elapsed, 1),
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        return 0

    print(answer)
    if not quiet:
        usage = (result["meta"] or {}).get("usage") or {}
        print(
            f"\n[grok] {elapsed:.0f}s · {len(result['tool_calls'])} tool calls · "
            f"{usage.get('inputTokens', '?')}in/{usage.get('outputTokens', '?')}out tokens · "
            f"stop={result['stop_reason']}",
            file=sys.stderr,
        )
        print(f"[grok] resume with: --session {session_id}", file=sys.stderr)
        if result["queries"]:
            print("[grok] queries run:", file=sys.stderr)
            for q in result["queries"]:
                print(f"         {q}", file=sys.stderr)
    if result["stop_reason"] not in (None, "end_turn"):
        return 1
    return 0


def _strip_fence(s: str) -> str:
    s = s.strip()
    if s.startswith("```"):
        s = re.sub(r"^```[a-zA-Z]*\n", "", s)
        s = re.sub(r"\n```$", "", s)
    return s.strip()


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #

EPILOG = """\
examples:
  grok_acp.py check
  grok_acp.py x "what are people saying about the new Claude model this week"
  grok_acp.py x "from:sama posts about AGI" --since 2026-01-01 --sort top
  grok_acp.py user "the person who created Rust"
  grok_acp.py thread https://x.com/elonmusk/status/2080706813662482472
  grok_acp.py web "current status of the EU AI Act implementation timeline"
  grok_acp.py x "sentiment on $NVDA earnings" --json
"""


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="grok_acp.py",
        description="Ask the local Grok Build agent (over ACP) to run live X/Twitter and web research.",
        epilog=EPILOG,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    sub = p.add_subparsers(dest="command", required=True)

    def add_common(sp: argparse.ArgumentParser, x_flags: bool) -> None:
        sp.add_argument("query", nargs="+", help="what to search for, in plain language")
        if x_flags:
            sp.add_argument("--since", "--from-date", dest="since", metavar="YYYY-MM-DD", help="only posts on/after this date")
            sp.add_argument("--until", "--to-date", dest="until", metavar="YYYY-MM-DD", help="only posts before this date")
            sp.add_argument("--sort", choices=["latest", "top"], help="rank by recency or by engagement")
            sp.add_argument("--lang", metavar="XX", help="restrict to posts in this language (e.g. en, zh, ja)")
        sp.add_argument("--limit", type=int, metavar="N", help="roughly how many results to report")
        sp.add_argument("--reply-lang", metavar="LANG", help="language to write the report in (e.g. Chinese)")
        sp.add_argument("--rules", metavar="TEXT", help="extra instructions appended to the search rules")
        sp.add_argument("--schema", metavar="FILE|JSON", help="JSON Schema; forces a JSON-only answer matching it")
        sp.add_argument("--json", action="store_true", help="emit one JSON object (answer + trace + usage) on stdout")
        sp.add_argument("--session", metavar="ID", help="continue a previous session instead of starting fresh")
        sp.add_argument("--cwd", metavar="DIR", help="workspace dir (default: an empty scratch dir)")
        sp.add_argument("--model", metavar="ID", help="model id (default: Grok's configured default)")
        sp.add_argument("--effort", choices=["low", "medium", "high"], help="reasoning effort")
        sp.add_argument("--timeout", type=float, default=None, metavar="SEC", help=f"per-turn timeout (default {DEFAULT_TIMEOUT}, 900 for research)")
        sp.add_argument("--quiet", action="store_true", help="suppress the stderr progress trace")
        sp.add_argument("--raw-log", metavar="FILE", help="dump the full JSON-RPC transcript here")
        sp.add_argument("--no-restrict", action="store_true", help="give Grok its full toolset instead of search-only")
        sp.set_defaults(func=cmd_run, workspace=False)

    add_common(sub.add_parser("x", help="search X/Twitter: posts, users, threads, history"), x_flags=True)
    add_common(sub.add_parser("user", help="find an X account and profile it"), x_flags=True)
    add_common(sub.add_parser("thread", help="fetch a post + its full thread and replies"), x_flags=True)
    add_common(sub.add_parser("web", help="live web search with citations"), x_flags=False)
    add_common(sub.add_parser("research", help="deep research: parallel agents, cross-checked, cited report"), x_flags=False)
    ask = sub.add_parser("ask", help="free-form prompt; Grok picks its own tools")
    add_common(ask, x_flags=True)
    ask.add_argument("--workspace", action="store_true", help="run in --cwd with Grok's full toolset (it can then read/write files there)")

    chk = sub.add_parser("check", help="verify install, auth, models and the ACP handshake")
    chk.set_defaults(func=cmd_check)
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    for name in ("since", "until", "sort", "lang", "limit", "reply_lang"):
        if not hasattr(args, name):
            setattr(args, name, None)
    try:
        return args.func(args)
    except KeyboardInterrupt:
        print("\ninterrupted", file=sys.stderr)
        return 130
    except AcpError as e:
        die(str(e), 1)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
