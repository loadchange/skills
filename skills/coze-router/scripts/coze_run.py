#!/usr/bin/env python3
"""Coze Router CLI — call workflows on the Coze-based router API.

Wraps two endpoints:
    GET  /v1/workflow/list       -> available workflows + their schemas
    POST /v1/workflow/run        -> run a named workflow with parameters

The /run response always wraps the useful payload as a *stringified* JSON
under `data`. This script parses that string, then formats per workflow
so the caller gets readable output rather than a wall of JSON.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import textwrap
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

CONFIG_PATH = Path(
    os.environ.get("COZE_ROUTER_CONFIG", "~/.config/coze-router/config.json")
).expanduser()

CONFIG_TEMPLATE = {
    "base_url": "https://<router-host>",
    "token": "<paste your bvr_... token here>",
}


def _bootstrap_config() -> None:
    """Create a stub config and tell the user how to fill it in, then exit."""
    CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    CONFIG_PATH.write_text(json.dumps(CONFIG_TEMPLATE, indent=2) + "\n", encoding="utf-8")
    try:
        os.chmod(CONFIG_PATH, 0o600)
    except OSError:
        pass
    print(
        f"Created a stub config at {CONFIG_PATH}.\n"
        "Open it and fill in:\n"
        '  - "base_url": the router base URL (e.g. https://d3q1e0dyfg5ace.cloudfront.net)\n'
        '  - "token":    your bearer token (the string that starts with `bvr_`)\n'
        "Then rerun the command.",
        file=sys.stderr,
    )
    sys.exit(2)


def _load_config() -> dict:
    if not CONFIG_PATH.exists():
        _bootstrap_config()  # exits
    try:
        cfg = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        print(f"Config file {CONFIG_PATH} is not valid JSON: {e}", file=sys.stderr)
        sys.exit(2)
    missing = [k for k in ("base_url", "token") if not cfg.get(k)]
    placeholder = [
        k for k in ("base_url", "token")
        if str(cfg.get(k, "")).startswith("<") and str(cfg.get(k, "")).endswith(">")
    ]
    if missing or placeholder:
        bad = missing + placeholder
        print(
            f"Config at {CONFIG_PATH} is incomplete. Please fill in: {', '.join(bad)}.\n"
            'Expected shape: {"base_url": "https://...", "token": "bvr_..."}',
            file=sys.stderr,
        )
        sys.exit(2)
    return cfg


_CFG = _load_config()

BASE_URL = os.environ.get("COZE_ROUTER_BASE_URL", _CFG["base_url"]).rstrip("/")
TOKEN = os.environ.get("COZE_ROUTER_TOKEN", _CFG["token"])

USER_AGENT = os.environ.get(
    "COZE_ROUTER_UA",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0.0.0 Safari/537.36",
)


def _request(method: str, path: str, body: dict | None = None) -> dict:
    url = f"{BASE_URL}{path}"
    headers = {
        "accept": "application/json",
        "Authorization": f"Bearer {TOKEN}",
        "User-Agent": USER_AGENT,
    }
    data = None
    if body is not None:
        headers["Content-Type"] = "application/json"
        data = json.dumps(body).encode("utf-8")
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        detail = e.read().decode("utf-8", errors="replace")
        try:
            detail = json.loads(detail)
        except Exception:
            pass
        print(f"HTTP {e.code} error calling {path}: {detail}", file=sys.stderr)
        sys.exit(1)
    except urllib.error.URLError as e:
        print(f"Network error calling {path}: {e}", file=sys.stderr)
        sys.exit(1)


def _parse_envelope(env: dict) -> Any:
    """Unwrap the `data` field which is almost always a JSON-encoded string."""
    if env.get("code") != 0:
        msg = env.get("msg") or env.get("message") or "unknown error"
        print(f"Workflow error (code={env.get('code')}): {msg}", file=sys.stderr)
        sys.exit(1)
    data = env.get("data")
    if isinstance(data, str):
        try:
            return json.loads(data)
        except json.JSONDecodeError:
            return data
    return data


def _run(name: str, parameters: dict) -> Any:
    env = _request("POST", "/v1/workflow/run", {"name": name, "parameters": parameters})
    return _parse_envelope(env)


# --- Formatters ---------------------------------------------------------------

def _wrap(text: str, width: int = 100, indent: str = "    ") -> str:
    if not text:
        return ""
    lines = []
    for para in text.splitlines():
        lines.extend(textwrap.wrap(para, width=width) or [""])
    return "\n".join(indent + l for l in lines)


def _fmt_search(payload: dict) -> str:
    results = (payload.get("output") or {}).get("organic_results") or []
    if not results:
        return "(no results)"
    out = []
    for i, r in enumerate(results, 1):
        title = (r.get("title") or "(untitled)").strip()
        link = r.get("link") or ""
        snippet = (r.get("snippet") or "").strip()
        if len(snippet) > 320:
            snippet = snippet[:320].rstrip() + "…"
        out.append(f"{i}. {title}")
        if link:
            out.append(f"   {link}")
        if snippet:
            out.append(_wrap(snippet, indent="   "))
        out.append("")
    return "\n".join(out).rstrip()


def _fmt_fetch(payload: dict) -> str:
    # payload is itself already { code, content, title, ... }
    title = payload.get("title") or ""
    content = payload.get("content") or ""
    if not (title or content):
        return "(empty page)"
    header = f"# {title}\n" if title else ""
    return f"{header}{content}".strip()


def _fmt_reddit_posts(posts: list[dict]) -> str:
    if not posts:
        return "(no posts)"
    out = []
    for i, p in enumerate(posts, 1):
        d = p.get("data") or {}
        title = d.get("title") or "(untitled)"
        subreddit = d.get("subreddit_name_prefixed") or d.get("subreddit") or ""
        author = d.get("author") or "?"
        score = d.get("score")
        comments = d.get("num_comments")
        flair = d.get("link_flair_text") or ""
        permalink = d.get("permalink") or ""
        url = d.get("url_overridden_by_dest") or d.get("url") or ""
        selftext = (d.get("selftext") or "").strip()

        head = f"{i}. [{subreddit}] {title}"
        if flair:
            head += f"  ({flair})"
        out.append(head)
        meta_bits = [f"u/{author}"]
        if score is not None:
            meta_bits.append(f"↑{score}")
        if comments is not None:
            meta_bits.append(f"💬{comments}")
        out.append("   " + " · ".join(meta_bits))
        if permalink:
            out.append(f"   https://www.reddit.com{permalink}")
        if url and url not in (f"https://www.reddit.com{permalink}", ""):
            out.append(f"   link: {url}")
        if selftext:
            excerpt = selftext if len(selftext) < 400 else selftext[:400].rstrip() + "…"
            out.append(_wrap(excerpt, indent="   "))
        out.append("")
    return "\n".join(out).rstrip()


def _fmt_reddit_messages(msgs: list[dict]) -> str:
    if not msgs:
        return "(no messages)"
    out = []
    for i, m in enumerate(msgs, 1):
        d = m.get("data") or {}
        subject = d.get("subject") or "(no subject)"
        author = d.get("author") or "?"
        body = (d.get("body") or "").strip()
        out.append(f"{i}. {subject}   —   u/{author}")
        if body:
            excerpt = body if len(body) < 400 else body[:400].rstrip() + "…"
            out.append(_wrap(excerpt, indent="   "))
        out.append("")
    return "\n".join(out).rstrip()


def _fmt_geocode(payload: dict) -> str:
    results = (payload.get("geocoding") or {}).get("result") or []
    if not results:
        return "(no results)"
    out = []
    for i, r in enumerate(results, 1):
        name = r.get("name") or "?"
        country = r.get("country") or "?"
        lat = r.get("lat")
        lon = r.get("lon")
        coord = f"({lat:.4f}, {lon:.4f})" if isinstance(lat, (int, float)) and isinstance(lon, (int, float)) else ""
        out.append(f"{i}. {name} / {country} {coord}".rstrip())
    return "\n".join(out)


def _fmt_current(payload: dict, units: str) -> str:
    cw = payload.get("get_current_weather") or {}
    if not cw.get("name") and not cw.get("main"):
        return "(no data)"
    name = cw.get("name") or "?"
    country = (cw.get("sys") or {}).get("country") or ""
    weather = (cw.get("weather") or [{}])[0]
    main = cw.get("main") or {}
    wind = cw.get("wind") or {}
    clouds = cw.get("clouds") or {}
    unit_sym = {"metric": "°C", "imperial": "°F", "standard": "K"}.get(units, "°")
    speed_unit = "mph" if units == "imperial" else "m/s"
    head = f"# {name}{', ' + country if country else ''} — {weather.get('description') or '?'}"
    lines = [
        head,
        f"  Temp: {main.get('temp')}{unit_sym} (feels like {main.get('feels_like')}{unit_sym}, {main.get('temp_min')}–{main.get('temp_max')}{unit_sym})",
        f"  Humidity {main.get('humidity')}%, pressure {main.get('pressure')} hPa, clouds {clouds.get('all')}%",
        f"  Wind {wind.get('speed')} {speed_unit} @ {wind.get('deg')}° (gust {wind.get('gust')})",
    ]
    vis = cw.get("visibility")
    if vis is not None:
        lines.append(f"  Visibility {vis} m")
    return "\n".join(lines)


def _fmt_forecast(payload: dict, units: str) -> str:
    fc = payload.get("forecast") or {}
    city = fc.get("city") or {}
    items = fc.get("list") or []
    if not items:
        return "(no forecast)"
    unit_sym = {"metric": "°C", "imperial": "°F", "standard": "K"}.get(units, "°")
    out = [f"# {city.get('name') or '?'}, {city.get('country') or '?'} — {len(items)} × 3-hour slices"]
    for it in items:
        dt = it.get("dt_txt") or "?"
        m = it.get("main") or {}
        w = (it.get("weather") or [{}])[0]
        pop = it.get("pop")
        pop_str = f", pop {int(pop * 100)}%" if isinstance(pop, (int, float)) else ""
        wind = it.get("wind") or {}
        out.append(
            f"  {dt} | {m.get('temp')}{unit_sym} (feels {m.get('feels_like')}{unit_sym}) | "
            f"{w.get('description') or '?'} | humidity {m.get('humidity')}%, wind {wind.get('speed')}{pop_str}"
        )
    return "\n".join(out)


def _extract_reddit_slot(payload: dict, slot: str, kind: str) -> list[dict]:
    """Pull the active slot's listing children out of the multi-slot envelope.

    `kind` is "posts" or "messages" — determines which inner key holds the Listing.
    """
    slot_data = (payload.get(slot) or {}).get("data")
    if slot_data is None:
        status = (payload.get(slot) or {}).get("message") or "no data"
        return []  # empty; caller prints "(no posts)"
    inner_key = "postData" if kind == "posts" else "messageData"
    listing = (slot_data.get(inner_key) or {}).get("data") or {}
    return listing.get("children") or []


# --- Subcommands --------------------------------------------------------------

def cmd_list(args):
    env = _request("GET", "/v1/workflow/list")
    if env.get("code") != 0:
        print(f"Error: {env.get('msg')}", file=sys.stderr)
        sys.exit(1)
    workflows = env.get("data") or []
    if args.json:
        print(json.dumps(workflows, indent=2, ensure_ascii=False))
        return
    for w in workflows:
        print(f"• {w.get('name')}")
        desc = (w.get("description") or "").strip()
        if desc:
            print(_wrap(desc, indent="    "))
        # show oneOf method names for router-style workflows
        one_of = (w.get("parameters") or {}).get("oneOf") or []
        methods = [
            (req or {}).get("required", [None])[0]
            for req in one_of
        ]
        methods = [m for m in methods if m]
        if methods:
            print(f"    methods: {', '.join(methods)}")
        print()


def cmd_search(args):
    params = {"googleWebSearch": {"query": args.query, "num": args.num}}
    if args.start:
        params["googleWebSearch"]["start"] = args.start
    payload = _run("google_search", params)
    if args.json:
        print(json.dumps(payload, indent=2, ensure_ascii=False))
        return
    print(_fmt_search(payload))


def cmd_fetch(args):
    payload = _run("url_fetch", {"url": args.url})
    if args.json:
        print(json.dumps(payload, indent=2, ensure_ascii=False))
        return
    print(_fmt_fetch(payload))


def cmd_reddit_hot(args):
    payload = _run("reddit", {"redditHot": {"limit": str(args.limit)}})
    if args.json:
        print(json.dumps(payload, indent=2, ensure_ascii=False))
        return
    posts = _extract_reddit_slot(payload, "redditHot", "posts")
    print(_fmt_reddit_posts(posts))


def cmd_reddit_search(args):
    payload = _run("reddit", {"redditSearch": {"q": args.query, "limit": str(args.limit)}})
    if args.json:
        print(json.dumps(payload, indent=2, ensure_ascii=False))
        return
    posts = _extract_reddit_slot(payload, "redditSearch", "posts")
    print(_fmt_reddit_posts(posts))


def cmd_sub_hot(args):
    payload = _run(
        "reddit",
        {"subRedditHot": {"subreddit": args.subreddit, "limit": str(args.limit)}},
    )
    if args.json:
        print(json.dumps(payload, indent=2, ensure_ascii=False))
        return
    posts = _extract_reddit_slot(payload, "subRedditHot", "posts")
    print(_fmt_reddit_posts(posts))


def cmd_sub_search(args):
    payload = _run(
        "reddit",
        {
            "subRedditSearch": {
                "subreddit": args.subreddit,
                "q": args.query,
                "limit": str(args.limit),
            }
        },
    )
    if args.json:
        print(json.dumps(payload, indent=2, ensure_ascii=False))
        return
    posts = _extract_reddit_slot(payload, "subRedditSearch", "posts")
    print(_fmt_reddit_posts(posts))


def cmd_inbox(args):
    params = {"messageInbox": {"limit": str(args.limit), "sr_detail": "true" if args.sr_detail else "false"}}
    payload = _run("reddit", params)
    if args.json:
        print(json.dumps(payload, indent=2, ensure_ascii=False))
        return
    msgs = _extract_reddit_slot(payload, "messageInbox", "messages")
    print(_fmt_reddit_messages(msgs))


def cmd_unread(args):
    params = {"messageUnread": {"limit": str(args.limit), "sr_detail": "true" if args.sr_detail else "false"}}
    payload = _run("reddit", params)
    if args.json:
        print(json.dumps(payload, indent=2, ensure_ascii=False))
        return
    msgs = _extract_reddit_slot(payload, "messageUnread", "messages")
    print(_fmt_reddit_messages(msgs))


def cmd_geocode(args):
    # Note: upstream parameter name is misspelled "lmit", not "limit". Kept faithful.
    params = {"geocoding": {"q": args.query, "lmit": str(args.limit)}}
    payload = _run("weather", params)
    if args.json:
        print(json.dumps(payload, indent=2, ensure_ascii=False))
        return
    print(_fmt_geocode(payload))


def cmd_current(args):
    params = {
        "get_current_weather": {
            "lat": str(args.lat),
            "lon": str(args.lon),
            "lang": args.lang,
            "mode": args.mode,
            "units": args.units,
        }
    }
    payload = _run("weather", params)
    # Pretty formatter only understands JSON; if the user picks xml/html, dump raw.
    if args.json or args.mode != "json":
        print(json.dumps(payload, indent=2, ensure_ascii=False) if isinstance(payload, (dict, list)) else payload)
        return
    print(_fmt_current(payload, args.units))


def cmd_forecast(args):
    params = {
        "forecast": {
            "lat": str(args.lat),
            "lon": str(args.lon),
            "cnt": str(args.cnt),
            "lang": args.lang,
            "mode": args.mode,
            "units": args.units,
        }
    }
    payload = _run("weather", params)
    if args.json or args.mode != "json":
        print(json.dumps(payload, indent=2, ensure_ascii=False) if isinstance(payload, (dict, list)) else payload)
        return
    print(_fmt_forecast(payload, args.units))


def cmd_raw(args):
    try:
        params = json.loads(args.parameters)
    except json.JSONDecodeError as e:
        print(f"--parameters must be valid JSON: {e}", file=sys.stderr)
        sys.exit(2)
    payload = _run(args.workflow, params)
    print(json.dumps(payload, indent=2, ensure_ascii=False))


# --- argparse -----------------------------------------------------------------

def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="coze_run",
        description="Call workflows on the Coze-based router API.",
    )
    sub = p.add_subparsers(dest="cmd", required=True)

    sp = sub.add_parser("list", help="List available workflows with their methods.")
    sp.add_argument("--json", action="store_true")
    sp.set_defaults(func=cmd_list)

    sp = sub.add_parser("search", help="Google web search (google_search workflow).")
    sp.add_argument("query")
    sp.add_argument("--num", type=int, default=5, help="Results count 1-10 (default 5).")
    sp.add_argument("--start", type=int, help="Pagination offset.")
    sp.add_argument("--json", action="store_true")
    sp.set_defaults(func=cmd_search)

    sp = sub.add_parser("fetch", help="Fetch an https URL as plaintext (url_fetch).")
    sp.add_argument("url")
    sp.add_argument("--json", action="store_true")
    sp.set_defaults(func=cmd_fetch)

    sp = sub.add_parser("reddit-hot", help="Site-wide hot posts.")
    sp.add_argument("--limit", type=int, default=10)
    sp.add_argument("--json", action="store_true")
    sp.set_defaults(func=cmd_reddit_hot)

    sp = sub.add_parser("reddit-search", help="Site-wide Reddit search.")
    sp.add_argument("query")
    sp.add_argument("--limit", type=int, default=10)
    sp.add_argument("--json", action="store_true")
    sp.set_defaults(func=cmd_reddit_search)

    sp = sub.add_parser("sub-hot", help="Hot posts in a subreddit.")
    sp.add_argument("subreddit", help="Subreddit name without the leading 'r/'.")
    sp.add_argument("--limit", type=int, default=10)
    sp.add_argument("--json", action="store_true")
    sp.set_defaults(func=cmd_sub_hot)

    sp = sub.add_parser("sub-search", help="Search within a subreddit.")
    sp.add_argument("subreddit")
    sp.add_argument("query")
    sp.add_argument("--limit", type=int, default=10)
    sp.add_argument("--json", action="store_true")
    sp.set_defaults(func=cmd_sub_search)

    sp = sub.add_parser("inbox", help="Authenticated user's inbox messages.")
    sp.add_argument("--limit", type=int, default=10)
    sp.add_argument("--sr-detail", action="store_true", help="Expand subreddit details on each message (upstream sr_detail=true).")
    sp.add_argument("--json", action="store_true")
    sp.set_defaults(func=cmd_inbox)

    sp = sub.add_parser("unread", help="Authenticated user's unread messages.")
    sp.add_argument("--limit", type=int, default=10)
    sp.add_argument("--sr-detail", action="store_true", help="Expand subreddit details on each message (upstream sr_detail=true).")
    sp.add_argument("--json", action="store_true")
    sp.set_defaults(func=cmd_unread)

    sp = sub.add_parser("geocode", help="Resolve a place name to coordinates (weather.geocoding).")
    sp.add_argument("query", help='Place name, e.g. "shanghai", "beijing", "London". Add ISO 3166 country code or US state code to disambiguate, e.g. "London,GB" or "Boston,MA,US".')
    sp.add_argument("--limit", type=int, default=5, help="Number of locations to return (1..5; upstream caps at 5). Mapped to upstream `lmit`.")
    sp.add_argument("--json", action="store_true")
    sp.set_defaults(func=cmd_geocode)

    sp = sub.add_parser("current", help="Current weather at a coordinate (weather.get_current_weather).")
    sp.add_argument("lat", type=float)
    sp.add_argument("lon", type=float)
    sp.add_argument("--units", default="metric", choices=["metric", "imperial", "standard"], help="metric=°C (default), imperial=°F, standard=K.")
    sp.add_argument("--lang", default="en", help='Output language, e.g. "en", "zh_cn".')
    sp.add_argument("--mode", default="json", choices=["json", "xml"], help="Upstream response format (json default; xml supported). Non-json forces raw output (the pretty formatter only parses json).")
    sp.add_argument("--json", action="store_true")
    sp.set_defaults(func=cmd_current)

    sp = sub.add_parser("forecast", help="5-day / 3-hour forecast at a coordinate (weather.forecast).")
    sp.add_argument("lat", type=float)
    sp.add_argument("lon", type=float)
    sp.add_argument("--cnt", type=int, default=8, help="Number of timestamps (3-hour slices) to return; default 8 = next 24h. Upstream cap depends on the OpenWeatherMap plan (5-day endpoint allows up to 40).")
    sp.add_argument("--units", default="metric", choices=["metric", "imperial", "standard"])
    sp.add_argument("--lang", default="en")
    sp.add_argument("--mode", default="json", choices=["json", "xml"], help="Upstream response format (json default; xml supported). Non-json forces raw output.")
    sp.add_argument("--json", action="store_true")
    sp.set_defaults(func=cmd_forecast)

    sp = sub.add_parser(
        "raw",
        help="Run any workflow with a raw JSON parameters blob; prints parsed JSON.",
    )
    sp.add_argument("workflow", help="Workflow name, e.g. google_search, url_fetch, reddit.")
    sp.add_argument("parameters", help="JSON object string for the workflow parameters.")
    sp.set_defaults(func=cmd_raw)

    return p


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
