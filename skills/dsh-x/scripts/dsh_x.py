#!/usr/bin/env python3
"""Search X (Twitter) through your own dsh-x-search endpoint.

Talks HTTP to a dsh-x-search instance (https://github.com/loadchange/dsh-x-search): a dsh
plugin that searches X with your own account and writes cited reports with the host's model.
Standard library only; works from any agent harness that can run a shell command.

Config lives in a file, never in environment variables:

    ~/.config/dsh-x/config.json
    {"url": "https://x-search.example.com", "token": "<bearer token>", "timeoutSec": 300}

    python3 dsh_x.py config --url https://x-search.example.com --token <token>   # writes it (0600)
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

CONFIG_PATH = Path(os.environ.get("DSH_X_CONFIG") or (Path.home() / ".config" / "dsh-x" / "config.json"))
DEFAULT_TIMEOUT = 300
USER_AGENT = "dsh-x-skill/1.0 (+https://github.com/loadchange/skills)"

# Stable error codes the endpoint returns, and what the caller can do about each.
HINTS = {
    "UNAUTHORIZED": "the token in the config file is wrong or missing — run `dsh_x.py config --token <token>`",
    "SESSION_EXPIRED": "the X login cookies on the server expired — re-import them (dsh-x-search deploy/README.md) and restart x-search.service",
    "RATE_LIMITED": "the endpoint's own quota is used up; wait and retry",
    "UPSTREAM_CHANGED": "X changed its web response shape; capture a response with dsh-x-search scripts/capture.ts and fix the parser",
    "UPSTREAM_TIMEOUT": "the page loaded but the data call never came back; retry, and check the server's last-failure.png if it persists",
    "BROWSER_UNAVAILABLE": "Chromium could not start on the server — check `journalctl -u x-search`",
    "MODEL_UNAVAILABLE": "the server has no model route; searches still work with --raw, follow-ups do not",
}


def die(msg: str, code: int = 2) -> None:
    print(f"error: {msg}", file=sys.stderr)
    raise SystemExit(code)


# --------------------------------------------------------------------------- #
# Config
# --------------------------------------------------------------------------- #


def load_config() -> dict[str, Any]:
    if not CONFIG_PATH.is_file():
        die(f"no config at {CONFIG_PATH}\n  create it:  dsh_x.py config --url https://x-search.example.com --token <token>")
    try:
        raw = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        die(f"{CONFIG_PATH} is not valid JSON: {e}")
    if not isinstance(raw, dict) or not str(raw.get("url", "")).strip():
        die(f"{CONFIG_PATH} needs at least {{\"url\": ...}}")
    return {
        "url": str(raw["url"]).rstrip("/"),
        "token": str(raw.get("token") or "").strip(),
        "timeout": float(raw.get("timeoutSec") or DEFAULT_TIMEOUT),
    }


def cmd_config(args: argparse.Namespace) -> int:
    current: dict[str, Any] = {}
    if CONFIG_PATH.is_file():
        try:
            current = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            current = {}
    if args.show or (not args.url and not args.token and args.timeout is None):
        if not current:
            print(f"{CONFIG_PATH}: not configured")
            return 1
        token = str(current.get("token") or "")
        print(json.dumps({**current, "token": (token[:4] + "…" + token[-4:]) if len(token) > 12 else ("set" if token else "")}, ensure_ascii=False, indent=2))
        print(f"({CONFIG_PATH})")
        return 0
    if args.url:
        current["url"] = args.url.rstrip("/")
    if args.token:
        current["token"] = args.token
    if args.timeout is not None:
        current["timeoutSec"] = args.timeout
    if not current.get("url"):
        die("--url is required the first time")
    CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    os.chmod(CONFIG_PATH.parent, 0o700)
    fd = os.open(CONFIG_PATH, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        json.dump(current, f, ensure_ascii=False, indent=2)
        f.write("\n")
    os.chmod(CONFIG_PATH, 0o600)
    print(f"written {CONFIG_PATH} (0600)")
    return 0


# --------------------------------------------------------------------------- #
# HTTP
# --------------------------------------------------------------------------- #


def call(cfg: dict[str, Any], path: str, payload: dict[str, Any] | None, timeout: float) -> tuple[int, dict[str, Any]]:
    """POST `payload` (or GET when None). Returns (http status, parsed body)."""
    body = None if payload is None else json.dumps(payload, ensure_ascii=False).encode("utf-8")
    headers = {"user-agent": USER_AGENT, "accept": "application/json"}
    if cfg["token"]:
        headers["authorization"] = f"Bearer {cfg['token']}"
    if body is not None:
        headers["content-type"] = "application/json"
    req = urllib.request.Request(cfg["url"] + path, data=body, method="GET" if body is None else "POST", headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.status, json.loads(resp.read().decode("utf-8") or "{}")
    except urllib.error.HTTPError as e:
        raw = e.read().decode("utf-8", errors="replace")
        try:
            return e.code, json.loads(raw or "{}")
        except json.JSONDecodeError:
            # Cloudflare error pages are HTML; keep the status, drop the page.
            return e.code, {"ok": False, "code": "UNAUTHORIZED" if e.code in (401, 403) else "INTERNAL", "message": f"HTTP {e.code} from the edge"}
    except (urllib.error.URLError, TimeoutError, OSError) as e:
        raise RuntimeError(f"cannot reach {cfg['url']}: {getattr(e, 'reason', e)}") from None


# --------------------------------------------------------------------------- #
# Commands
# --------------------------------------------------------------------------- #


def cmd_check(_args: argparse.Namespace) -> int:
    cfg = load_config()
    print(f"endpoint  {cfg['url']}")
    print(f"token     {'set' if cfg['token'] else 'NOT SET (the endpoint will answer 401)'}")
    print(f"config    {CONFIG_PATH}")
    try:
        status, data = call(cfg, "/api/status", None, 30)
    except RuntimeError as e:
        print(f"status    unreachable: {e}")
        return 1
    if status == 401:
        print("status    401 unauthorized — wrong or missing token")
        return 1
    if not data.get("ok", True) and data.get("code"):
        print(f"status    {data.get('code')}: {data.get('message')}")
        return 1
    browser = data.get("browser") or {}
    lim = data.get("limiter") or {}
    print(f"status    http {status} · session {browser.get('session')} · browser {'open' if browser.get('open') else 'closed'}"
          f" · model {'available' if (data.get('llm') or {}).get('available') else 'unavailable'}")
    print(f"quota     {lim.get('usedInWindow')}/{lim.get('perWindow')} per window · {lim.get('usedToday')}/{lim.get('perDay')} today")
    if browser.get("lastError"):
        print(f"last err  {browser['lastError']}")
    print("ready.")
    return 0


def build_payload(args: argparse.Namespace, subject: str) -> tuple[str, dict[str, Any]]:
    common: dict[str, Any] = {}
    if args.reply_lang:
        common["replyLang"] = args.reply_lang
    if args.raw:
        common["raw"] = True
    if args.ask:
        common["question"] = args.ask
    if args.command == "x" and args.session:
        return "/api/followup", {"sessionId": args.session, "request": subject, **{k: v for k, v in common.items() if k == "replyLang"}}
    if args.command == "ask":
        # `ask <url-or-id> <question…>`: answer a question about one post, images included, server-side.
        parts = subject.split(None, 1)
        if len(parts) < 2:
            die("ask needs a post URL/id followed by the question")
        return "/api/thread", {"post": parts[0], "question": parts[1], **{k: v for k, v in common.items() if k != "question"}}
    if args.command == "x":
        extra = {
            "since": args.since, "until": args.until, "sort": args.sort, "lang": args.lang, "limit": args.limit, "rules": args.rules,
            "allowedHandles": args.handle or None, "excludedHandles": args.exclude_handle or None,
            "excludeReplies": True if args.no_replies else None,
        }
        return "/api/search", {"request": subject, **{k: v for k, v in extra.items() if v is not None}, **common}
    if args.command == "user":
        return "/api/user", {"request": subject, **common}
    return "/api/thread", {"post": subject, **common}


def cmd_run(args: argparse.Namespace) -> int:
    cfg = load_config()
    subject = " ".join(args.query).strip()
    if not subject:
        die("empty query")
    quiet = args.json or args.quiet
    timeout = args.timeout if args.timeout is not None else cfg["timeout"]
    path, payload = build_payload(args, subject)
    started = time.monotonic()
    if not quiet:
        print(f"[dsh-x] {args.command}{' (follow-up)' if path.endswith('/followup') else ''} · {cfg['url']}", file=sys.stderr, flush=True)
    try:
        status, data = call(cfg, path, payload, timeout)
    except RuntimeError as e:
        if args.json:
            print(json.dumps({"ok": False, "command": args.command, "query": subject, "error": str(e)}, ensure_ascii=False, indent=2))
        else:
            print(f"error: {e}", file=sys.stderr)
        return 1
    elapsed = time.monotonic() - started

    if not data.get("ok"):
        code, msg = data.get("code", "INTERNAL"), data.get("message", f"HTTP {status}")
        hint = HINTS.get(code, "")
        if code == "RATE_LIMITED" and data.get("retryAfterMs"):
            hint = f"retry after ~{int(data['retryAfterMs'] / 1000)}s"
        if args.json:
            print(json.dumps({"ok": False, "command": args.command, "query": subject, "code": code, "error": msg, "http": status, "hint": hint}, ensure_ascii=False, indent=2))
        else:
            print(f"error: {code} — {msg}" + (f"\n  {hint}" if hint else ""), file=sys.stderr)
        return 1

    # search/followup return `posts`; user returns `recentPosts`; thread returns `thread` + `replies`.
    posts = data.get("posts") or data.get("recentPosts") or ((data.get("thread") or []) + (data.get("replies") or []))
    if args.json:
        print(json.dumps({
            "ok": True,
            "command": args.command,
            "query": subject,
            "answer": data.get("answer", ""),
            "posts": posts,
            "profile": data.get("profile"),
            "candidates": data.get("candidates"),
            "focal": data.get("focal"),
            "original": data.get("original"),
            "queries": data.get("queries", []),
            "warnings": data.get("warnings", []),
            "planner": data.get("planner"),
            "report": data.get("report"),
            "session_id": data.get("sessionId"),
            "elapsed_sec": round(elapsed, 1),
            "server_elapsed_sec": round((data.get("elapsedMs") or 0) / 1000, 1),
        }, ensure_ascii=False, indent=2))
        return 0

    print(data.get("answer", ""))
    if data.get("original") and (args.ask or args.command == "ask") and not quiet:
        print("\n--- 原文（服务端已读图） ---")
        print(data["original"])
    if not quiet:
        lim = data.get("limiter") or {}
        print(f"\n[dsh-x] {elapsed:.0f}s · {len(posts)} posts · planner={data.get('planner')} report={data.get('report')}"
              + (f" · quota {lim.get('usedInWindow')}/{lim.get('perWindow')} per window, {lim.get('usedToday')}/{lim.get('perDay')} today" if lim else ""),
              file=sys.stderr)
        if data.get("sessionId"):
            print(f"[dsh-x] follow up with: --session {data['sessionId']}", file=sys.stderr)
        for w in data.get("warnings") or []:
            print(f"[dsh-x] warning: {w}", file=sys.stderr)
        if data.get("queries"):
            print("[dsh-x] queries run:", file=sys.stderr)
            for q in data["queries"]:
                print(f"         {q}", file=sys.stderr)
    return 0


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #

EPILOG = """\
examples:
  dsh_x.py config --url https://x-search.example.com --token <token>
  dsh_x.py check
  dsh_x.py ask https://x.com/someone/status/123 这个帖子什么意思？        # server reads the images, answers directly
  dsh_x.py x "what are developers saying about the Zed editor this week" --since 2026-09-15 --reply-lang Chinese
  dsh_x.py x "from:sama posts about compute" --since 2026-06-01 --sort top
  dsh_x.py x "reactions to the Figma IPO" --handle bloomberg --handle reuters --raw
  dsh_x.py x "which of these has the most engagement?" --session <id>
  dsh_x.py user karpathy
  dsh_x.py thread https://x.com/karpathy/status/2081195664479068350 --json
"""


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="dsh_x.py", description="Search X (Twitter) through your own dsh-x-search endpoint.",
                                epilog=EPILOG, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="command", required=True)

    def add_common(sp: argparse.ArgumentParser, search_flags: bool) -> None:
        sp.add_argument("query", nargs="+", help="what to search for, in plain language (or X operators)")
        if search_flags:
            sp.add_argument("--since", metavar="YYYY-MM-DD", help="only posts on/after this date")
            sp.add_argument("--until", metavar="YYYY-MM-DD", help="only posts before this date")
            sp.add_argument("--sort", choices=["latest", "top"], help="rank by recency or by engagement")
            sp.add_argument("--lang", metavar="XX", help="only posts in this language (en, zh, ja, …)")
            sp.add_argument("--limit", type=int, metavar="N", help="roughly how many posts to return (default 30)")
            sp.add_argument("--handle", action="append", metavar="HANDLE", help="only these accounts (repeat; max 20)")
            sp.add_argument("--exclude-handle", action="append", metavar="HANDLE", help="exclude these accounts (repeat; max 20; not with --handle)")
            sp.add_argument("--no-replies", action="store_true", help="drop replies")
            sp.add_argument("--rules", metavar="TEXT", help="extra instructions for the report writer")
            sp.add_argument("--session", metavar="ID", help="ask a follow-up over a previous search's posts (no new search)")
        sp.add_argument("--ask", metavar="QUESTION", help="answer this question directly (server reads the posts' images first) instead of writing a report")
        sp.add_argument("--reply-lang", metavar="LANG", help="language to write the report in (e.g. Chinese)")
        sp.add_argument("--raw", action="store_true", help="cited post list only, no written report")
        sp.add_argument("--json", action="store_true", help="one JSON object on stdout (answer, posts, queries, session_id, …)")
        sp.add_argument("--timeout", type=float, metavar="SEC", help=f"request timeout (default from config or {DEFAULT_TIMEOUT})")
        sp.add_argument("--quiet", action="store_true", help="no stderr trace")
        sp.set_defaults(func=cmd_run)

    add_common(sub.add_parser("x", help="search X: posts, topics, sentiment, an account's history"), search_flags=True)
    add_common(sub.add_parser("user", help="find an X account (handle or description) and read its recent posts"), search_flags=False)
    add_common(sub.add_parser("thread", help="one post's full text plus its thread and replies"), search_flags=False)
    add_common(sub.add_parser("ask", help="answer a question about one post: `ask <url|id> <question…>` (images read server-side)"), search_flags=False)

    chk = sub.add_parser("check", help="verify config and the endpoint's status")
    chk.set_defaults(func=cmd_check)

    cfgp = sub.add_parser("config", help="write or show ~/.config/dsh-x/config.json")
    cfgp.add_argument("--url", metavar="URL", help="endpoint, e.g. https://x-search.example.com")
    cfgp.add_argument("--token", metavar="TOKEN", help="bearer token")
    cfgp.add_argument("--timeout", type=float, metavar="SEC", help="default request timeout")
    cfgp.add_argument("--show", action="store_true", help="print the current config (token masked)")
    cfgp.set_defaults(func=cmd_config)
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    for name in ("since", "until", "sort", "lang", "limit", "handle", "exclude_handle", "no_replies", "rules", "session", "reply_lang", "raw", "json", "timeout", "quiet", "ask"):
        if not hasattr(args, name):
            setattr(args, name, None)
    try:
        return args.func(args)
    except KeyboardInterrupt:
        print("\ninterrupted", file=sys.stderr)
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
