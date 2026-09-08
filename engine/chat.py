"""AI chat engine â€” tools + plumbing for a PC assistant.

This module owns the *capabilities* of the assistant and a demo backend.
Every answer is grounded in the real system through the tool registry below:

    get_specs          -> the detected hardware profile (this machine)
    get_applied        -> tweaks this app has applied (with timestamps)
    get_tweak_info     -> full explanation of one tweak by id
    list_tweaks        -> all tweaks in a category
    check_tweak        -> live state of one tweak (active/inactive/unknown)
    recent_activity    -> the in-app activity feed

The tool definitions are written in the OpenAI function-calling schema so the
same registry can be handed to a real LLM: the model calls ``name(args)`` and
we execute ``call_tool``. When a Groq API key is configured, the assistant
answers through Groq's OpenAI-compatible endpoint (function calling loop).
Without a key, ``ChatAssistant.respond`` uses a small keyword router that
calls the same tools, so the plumbing is proven end to end.
"""
from __future__ import annotations

import html
import json
import re
import time

import httpx

from config.app_config import (
    BOT_NAME,
    GEMINI_API_KEY,
    GEMINI_BASE_URL,
    GEMINI_MODEL,
    GROQ_API_KEY,
    GROQ_BASE_URL,
    GROQ_MODEL,
)
from database import BY_ID, TWEAKS
from engine import activity, state as state_mgr
from engine import state_checker
from rexlog import logger


# ---------------------------------------------------------------------------
# Tool registry (OpenAI function-calling schema + python implementations)
# ---------------------------------------------------------------------------

def _fmt_specs(profile: dict) -> str:
    if not profile:
        return "No system scan has run yet \u2014 open the Detect page or restart the app."
    lines = [
        f"CPU: {profile.get('cpu_name')} ({profile.get('cpu_vendor')}, "
        f"{profile.get('cpu_cores')}c/{profile.get('cpu_threads')}t @ ~{profile.get('cpu_ghz')} GHz)",
        f"GPU: {', '.join(profile.get('gpu_names') or ['Unknown'])}",
        f"RAM: {profile.get('ram_gb')} GB ({profile.get('ram_channels')} channel, "
        f"{profile.get('ram_mtps')} MT/s)",
        f"Storage: {('NVMe SSD' if profile.get('nvme') else 'SSD' if profile.get('ssd') else '')}"
        f"{', HDD' if profile.get('hdd') else ''}",
        f"Windows: {profile.get('win_version')} (build {profile.get('win_build')})",
        f"Laptop: {'yes' if profile.get('laptop') else 'no'}",
        f"Monitor: {profile.get('monitor_refresh') or '?'} Hz",
        f"Network adapter: {profile.get('adapter', {}).get('name')} "
        f"({profile.get('adapter', {}).get('type')}, {profile.get('adapter', {}).get('speed')})",
    ]
    return "\n".join(lines)


def _tweak_summary(t: dict) -> str:
    return (f"[{t['id']}] {t['name']} \u2014 {t.get('desc', '')} "
            f"(risk: {t.get('risk')}, recommended: {t.get('recommended')})")


def tool_get_specs(profile: dict) -> str:
    return _fmt_specs(profile)


def tool_get_applied() -> str:
    ids = sorted(state_mgr.applied_ids())
    if not ids:
        return "No tweaks have been applied yet."
    lines = []
    for tid in ids:
        t = BY_ID.get(tid)
        name = t["name"] if t else tid
        at = state_mgr.applied_at(tid) or "?"
        lines.append(f"[{tid}] {name} (applied {at})")
    return f"{len(lines)} tweak(s) applied:\n" + "\n".join(lines)


def tool_get_tweak_info(tweak_id: str) -> str:
    t = BY_ID.get(tweak_id.strip().lower())
    if t is None:
        return f"Unknown tweak id '{tweak_id}'. Try list_tweaks to see what exists."
    return (
        f"[{t['id']}] {t['name']}\n"
        f"Category: {t['category']}\n"
        f"What it does: {t.get('changes')}\n"
        f"Why: {t.get('why')}\n"
        f"Risk: {t.get('risk')}  Impact: {t.get('impact')}  "
        f"Recommended: {t.get('recommended')}"
    )


def tool_list_tweaks(category: str) -> str:
    cat = category.strip().lower()
    if not cat or cat in ("all", "everything"):
        items = TWEAKS
        head = f"There are {len(items)} tweaks across all categories."
    else:
        items = [t for t in TWEAKS if cat in t["category"].lower()
                 or cat in (t.get("module") or "").lower()]
        head = f"{len(items)} tweak(s) in '{category}':"
    if not items:
        return f"No tweaks found for '{category}'. Categories include: " \
               + ", ".join(sorted({t["category"] for t in TWEAKS}))
    return head + "\n" + "\n".join(_tweak_summary(t) for t in items[:25])


def tool_check_tweak(tweak_id: str) -> str:
    t = BY_ID.get(tweak_id.strip().lower())
    if t is None:
        return f"Unknown tweak id '{tweak_id}'."
    live = state_checker.check_id(t["id"])
    applied = t["id"] in state_mgr.applied_ids()
    state_txt = {True: "ACTIVE (already matches the optimized state)",
                 False: "inactive (not applied)",
                 None: "not measurable (guidance/one-shot)"}.get(live, "unknown")
    applied_txt = "recorded as applied by Maximum Tweaks" if applied else "not recorded as applied"
    return f"[{t['id']}] {t['name']}: {state_txt}. {applied_txt}."


def tool_recent_activity() -> str:
    rows = activity.history(10)
    if not rows:
        return "No activity yet this session."
    return "\n".join(f"{r['time']}  {r['kind'].upper()}  {r['text']}" for r in rows)


_SEARCH_UA = "MaximumTweaks/2.0 (Windows; PC assistant)"


def tool_web_search(query: str, max_results: int = 4) -> str:
    """Keyless web lookup (works worldwide): Wikipedia search with a short
    extract per hit, plus DuckDuckGo instant answers when they respond."""
    q = (query or "").strip()
    if not q:
        return "Empty query."
    results: list[str] = []

    # 1) DuckDuckGo instant answers (best-effort; often empty/202)
    try:
        resp = httpx.get(
            "https://api.duckduckgo.com/",
            params={"q": q, "format": "json", "no_html": 1,
                    "no_redirect": 1},
            headers={"User-Agent": _SEARCH_UA},
            timeout=10.0,
        )
        if resp.status_code == 200:
            data = resp.json()
            abstract = (data.get("Abstract") or "").strip()
            if abstract and data.get("AbstractURL"):
                results.append(f"- {abstract}\n  {data['AbstractURL']}")
            for topic in data.get("RelatedTopics") or []:
                if isinstance(topic, dict):
                    txt = (topic.get("Text") or "").strip()
                    url = (topic.get("FirstURL") or "").strip()
                    if txt and url:
                        results.append(f"- {txt}\n  {url}")
                elif isinstance(topic, list):
                    for sub in topic:
                        if not isinstance(sub, dict):
                            continue
                        txt = (sub.get("Text") or "").strip()
                        url = (sub.get("FirstURL") or "").strip()
                        if txt and url:
                            results.append(f"- {txt}\n  {url}")
                if len(results) >= max_results:
                    break
    except Exception as exc:  # noqa: BLE001
        logger.warn(f"chat tool web_search (ddg): {type(exc).__name__}: {exc}")

    # 2) Wikipedia: search + intro extract in one call (reliable)
    if len(results) < max_results:
        try:
            resp = httpx.get(
                "https://en.wikipedia.org/w/api.php",
                params={
                    "action": "query",
                    "generator": "search",
                    "gsrsearch": q,
                    "gsrlimit": max_results,
                    "prop": "extracts",
                    "exintro": 1,
                    "explaintext": 1,
                    "format": "json",
                    "utf8": 1,
                },
                headers={"User-Agent": _SEARCH_UA},
                timeout=12.0,
            )
            if resp.status_code == 200:
                pages = (resp.json().get("query", {}).get("pages")
                         or {}).values()
                pages = sorted(pages, key=lambda p: p.get("index", 0))
                for page in pages:
                    title = str(page.get("title") or "")
                    extract = html.unescape(str(page.get("extract")
                                                or "")).strip()
                    if not extract:
                        extract = re.sub(r"\s+", " ", str(
                            page.get("snippet") or "")).strip()
                    if not extract:
                        continue
                    snippet = (extract[:220] + "\u2026"
                               if len(extract) > 220 else extract)
                    results.append(
                        f"- {title}: {snippet}\n"
                        f"  https://en.wikipedia.org/wiki/{title.replace(' ', '_')}")
                    if len(results) >= max_results:
                        break
        except Exception as exc:  # noqa: BLE001
            logger.warn(f"chat tool web_search (wiki): {type(exc).__name__}: {exc}")

    if not results:
        return f"No web results found for {query!r}. Try rephrasing."
    return "\n".join(results[:max_results])


TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "get_specs",
            "description": "Return the detected hardware specs of this PC (CPU, GPU, RAM, storage, Windows, network).",
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_applied",
            "description": "Return the list of tweaks that have been applied to this system.",
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_tweak_info",
            "description": "Explain a single tweak by its id (e.g. 'net-005').",
            "parameters": {
                "type": "object",
                "properties": {"tweak_id": {"type": "string",
                                            "description": "Tweak id like 'net-005'."}},
                "required": ["tweak_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_tweaks",
            "description": "List tweaks in a category (e.g. 'network', 'system', 'gpu', 'mouse').",
            "parameters": {
                "type": "object",
                "properties": {"category": {"type": "string",
                                            "description": "Category name."}},
                "required": ["category"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "check_tweak",
            "description": "Check whether a tweak is currently active on the live system.",
            "parameters": {
                "type": "object",
                "properties": {"tweak_id": {"type": "string"}},
                "required": ["tweak_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "recent_activity",
            "description": "Return the recent in-app activity feed (applies, reverts, scans, errors).",
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "web_search",
            "description": "Search the web for current info, people, places, news, prices, tutorials, sports, etc. Returns a short list of results with real links. Use this whenever a link or live/current information would help.",
            "parameters": {
                "type": "object",
                "properties": {"query": {"type": "string",
                                         "description": "What to search for."}},
                "required": ["query"],
            },
        },
    },
]

_HANDLERS = {
    "get_specs": tool_get_specs,
    "get_applied": tool_get_applied,
    "get_tweak_info": tool_get_tweak_info,
    "list_tweaks": tool_list_tweaks,
    "check_tweak": tool_check_tweak,
    "recent_activity": tool_recent_activity,
    "web_search": tool_web_search,
}


def call_tool(name: str, profile: dict | None = None, **kwargs) -> str:
    """Execute a tool by name; returns its text result. Safe for any backend."""
    fn = _HANDLERS.get(name)
    if fn is None:
        return f"Unknown tool '{name}'."
    try:
        if name == "get_specs":
            return fn(profile or {})
        return fn(**kwargs)
    except Exception as exc:  # noqa: BLE001
        logger.warn(f"chat tool {name}: {type(exc).__name__}: {exc}")
        return f"Tool {name} failed: {exc}"


def build_system_prompt(profile: dict) -> str:
    """System context injected ahead of every request (demo and LLM paths)."""
    return (
        f"You are {BOT_NAME}, the assistant inside Maximum Tweaks. You are "
        "like ChatGPT \u2014 a general-purpose assistant that knows the world "
        "\u2014 and you're also an expert on this PC and how to tune it.\n\n"
        "Talk exactly like a real person texting you: casual, warm, and "
        "direct. Use short sentences and contractions (\u201cI'm\u201d, "
        "\u201cyou're\u201d, \u201ccan't\u201d). NEVER sound like a help "
        "desk or a bot: no \u201cI'd be happy to help\u201d, no corporate "
        "phrasing.\n\n"
        "Rules:\n"
        "- Answer general questions about anything \u2014 people, places, "
        "events, how-to, tech, news, math, code. Be accurate; if you're "
        "unsure, say so instead of guessing.\n"
        "- Share real links (URLs) whenever they help. Call web_search to "
        "get current info or real links, and only cite URLs that came from "
        "the search results \u2014 never invent a URL.\n"
        "- Small talk ('hi', 'how are you', 'what's up') gets a short, "
        "friendly reply that matches the user's energy. Do NOT pivot into "
        "features or offers.\n"
        "- Read this machine with the tools when the question is about "
        "specs, tweaks, ping, fps, or hardware \u2014 weave the facts into "
        "natural sentences, never dump raw lists.\n"
        "- Keep answers short. One or two lines is often enough. Add detail "
        "only if the user asks.\n"
        "- Be yourself: laid-back, sharp, a little witty. Never robotic.\n\n"
        "Detected system (use only when relevant):\n" + _fmt_specs(profile)
    )


def llm_configured() -> bool:
    """True when at least one AI provider (Gemini or Groq) has a key set."""
    return bool((GROQ_API_KEY or "").strip()
                or (GEMINI_API_KEY or "").strip())


_SERVICE_ERROR = ("I couldn't reach the AI service right now \u2014 "
                  "give it a second and try again.")


_FN_TAG_RE = re.compile(r"<function\b(.*?)</function>", re.S)


def _parse_content_calls(text: str) -> list[dict]:
    """llama-3.3 sometimes writes tool calls into content instead of the
    ``tool_calls`` field, in wildly varying shapes:
    ``<function=web_search>{"q":1}</function>``,
    ``<function\\web_search {"q":1} </function>``,
    ``<function(web_search {"q":1})</function>``.
    Parse any of them into call dicts."""
    out = []
    for match in _FN_TAG_RE.finditer(text or ""):
        body = match.group(1).strip()
        name_m = re.search(r"\b([A-Za-z_][A-Za-z0-9_]*)\b", body)
        if not name_m:
            continue
        name = name_m.group(1)
        args: dict = {}
        obj = re.search(r"\{.*\}", body, re.S)
        if obj:
            try:
                parsed = json.loads(obj.group(0))
                if isinstance(parsed, dict):
                    args = parsed
            except json.JSONDecodeError:
                args = {}
        out.append({"function": {"name": name,
                                 "arguments": json.dumps(args)}})
    return out


def _chat(base_url: str, api_key: str, model: str,
          question: str, history: list[dict],
          profile: dict | None = None,
          max_tool_rounds: int = 6) -> dict:
    """Run one turn through any OpenAI-compatible chat completions endpoint
    (Groq, Google Gemini's OpenAI bridge, etc.) with function calling.

    ``history`` is a list of {"role": "user"|"assistant", "text": str} for the
    earlier turns of the conversation. Returns {"text": str, "tools": [...]}.
    """
    messages = [{"role": "system", "content": build_system_prompt(profile or {})}]
    for turn in history:
        messages.append({"role": turn["role"], "content": turn["text"]})
    messages.append({"role": "user", "content": question})

    url = base_url.rstrip("/") + "/chat/completions"
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    tools_used: list[str] = []
    round_num = 0
    while round_num < max_tool_rounds:
        payload = {
            "model": model,
            "messages": messages,
            "tools": TOOLS,
            "tool_choice": "auto",
            "temperature": 0.85,
        }
        retries = 0
        while True:
            try:
                resp = httpx.post(url, headers=headers, json=payload,
                                  timeout=60.0)
            except httpx.HTTPError as exc:
                logger.warn(f"ai: request failed: {type(exc).__name__}: {exc}")
                if retries < 2:
                    retries += 1
                    time.sleep(2.0 * retries)
                    continue
                return {"text": _SERVICE_ERROR, "tools": tools_used}
            # Rate limit: back off briefly and retry.
            if resp.status_code == 429 and retries < 3:
                retries += 1
                logger.warn(f"ai: rate limited; backing off ({retries}/3)")
                time.sleep(2.0 * retries)
                continue
            # Groq occasionally rejects a tool call with malformed arguments
            # ("tool_use_failed"); that is usually transient, so retry with
            # tools before giving up on them.
            if (resp.status_code == 400
                    and "tool_use_failed" in resp.text
                    and retries < 2):
                retries += 1
                logger.warn("ai: tool call rejected; retrying with tools")
                continue
            break
        if resp.status_code != 200:
            # Still failing? Drop tools so the user gets an answer anyway.
            if resp.status_code == 400 and "tool_use_failed" in resp.text:
                logger.warn("ai: tool call rejected; retrying without tools")
                fallback = {
                    "model": model,
                    "messages": messages,
                    "temperature": 0.85,
                }
                try:
                    resp2 = httpx.post(url, headers=headers, json=fallback,
                                       timeout=60.0)
                except httpx.HTTPError as exc:
                    logger.warn(f"ai: fallback request failed: "
                                f"{type(exc).__name__}: {exc}")
                    return {"text": _SERVICE_ERROR, "tools": tools_used}
                if resp2.status_code == 200:
                    choice = (resp2.json().get("choices") or [{}])[0]
                    return {"text": choice.get("message", {}).get("content", ""),
                            "tools": tools_used}
            detail = resp.text[:200]
            logger.warn(f"ai: HTTP {resp.status_code}: {detail}")
            return {"text": _SERVICE_ERROR, "tools": tools_used}
        data = resp.json()
        choice = (data.get("choices") or [{}])[0]
        message = choice.get("message") or {}
        text = message.get("content") or ""
        calls = message.get("tool_calls") or []
        if not calls:
            parsed = _parse_content_calls(text)
            if parsed:
                built = []
                for i, call in enumerate(parsed):
                    cid = f"call_{round_num}_{i}"
                    call["id"] = cid
                    built.append({
                        "id": cid,
                        "type": "function",
                        "function": call["function"],
                    })
                calls = built
                message = {"role": "assistant", "content": None,
                           "tool_calls": calls}
        if not calls:
            return {"text": text, "tools": tools_used}
        messages.append(message)
        for call in calls:
            fn = call.get("function") or {}
            name = fn.get("name") or ""
            try:
                args = json.loads(fn.get("arguments") or "{}")
                if not isinstance(args, dict):
                    args = {}
            except json.JSONDecodeError:
                args = {}
            result = call_tool(name, profile=profile, **args)
            tools_used.append(name)
            messages.append({
                "role": "tool",
                "tool_call_id": call.get("id"),
                "content": result,
            })
        round_num += 1
    return {"text": "Maximum hit the tool-call limit \u2014 try a simpler question.",
            "tools": tools_used}


def respond_with_gemini(question: str, history: list[dict],
                        profile: dict | None = None,
                        max_tool_rounds: int = 6) -> dict:
    """Run one turn through Google Gemini (OpenAI-compatible bridge)."""
    return _chat(
        GEMINI_BASE_URL
        or "https://generativelanguage.googleapis.com/v1beta/openai",
        GEMINI_API_KEY, GEMINI_MODEL, question, history, profile,
        max_tool_rounds)


def respond_with_groq(question: str, history: list[dict],
                      profile: dict | None = None,
                      max_tool_rounds: int = 6) -> dict:
    """Run one turn through Groq (OpenAI-compatible endpoint)."""
    return _chat(
        GROQ_BASE_URL or "https://api.groq.com/openai/v1",
        GROQ_API_KEY, GROQ_MODEL, question, history, profile,
        max_tool_rounds)


# ---------------------------------------------------------------------------
# Demo backend: keyword router that drives the same tools.
# ---------------------------------------------------------------------------

_ID_RE = re.compile(r"\b([a-z]{2,6}-\d{3})\b")

_INTROS = {
    "get_specs": "Here is the detected hardware of this PC:",
    "get_applied": "Here is what has been applied to this system so far:",
    "recent_activity": "Recent activity:",
    "web_search": "Here's what I found online:",
}


def _route(question: str) -> list[str]:
    q = question.lower()
    tools = []
    ids = _ID_RE.findall(question)
    if ids:
        tid = ids[0]
        if any(k in q for k in ("check", "state", "active", "applied",
                                "working", "is it", "status")):
            tools.append("check_tweak")
        else:
            tools.append("get_tweak_info")
    elif any(k in q for k in ("specs", "specifications", "hardware", "what pc",
                              "system info", "computer", "my pc", "what cpu",
                              "what gpu", "ram")):
        tools.append("get_specs")
    elif any(k in q for k in ("applied", "what tweaks", "applied tweaks",
                              "what have", "installed", "changed")):
        tools.append("get_applied")
    elif any(k in q for k in ("recent", "activity", "what happened",
                              "did it", "log")):
        tools.append("recent_activity")
    elif any(k in q for k in ("tweaks in", "list tweaks", "list ", "tweaks for",
                              "tweaks category", "category")):
        for cat in sorted({t["category"] for t in TWEAKS}):
            if cat.lower() in q:
                tools.append("list_tweaks")
                break
        if not tools:
            tools.append("list_tweaks")
    elif any(k in q for k in ("search", "google", "who is", "who was",
                              "what is ", "what are ", "when was", "where is",
                              "web", "online", "news", "latest", "price",
                              "how to", "find me", "look up")):
        tools.append("web_search")
    return tools


def _advice(question: str, tool_results: dict) -> str:
    q = question.lower()
    if any(k in q for k in ("ping", "latency", "lag", "network")):
        if "get_specs" in tool_results:
            return (
                "For high ping/latency on this machine, start with: "
                "1) run the Network optimizer (Optimize Network on the Tweaks "
                "page) \u2014 it applies the TCP tuning that fits this adapter; "
                "2) close background downloads/upload; 3) use Ethernet over Wi-Fi "
                "if you can; 4) check the router for QoS/gaming mode. "
                "Use a wired speed test to confirm the base line.")
    if any(k in q for k in ("fps", "stutter", "slow", "performance",
                            "optimize", "make faster", "boost")):
        return (
            "The fastest wins for gaming FPS on this PC, in order: "
            "1) GPU driver \u2014 latest Game Ready/Adrenalin build; "
            "2) run the GPU + CPU + RAM optimizers from the Tweaks page; "
            "3) cap FPS just below your monitor refresh to keep frame times flat; "
            "4) close background apps (use the Startup tweaks). "
            "Try the category optimizers \u2014 they only apply what matches "
            "your hardware.")
    if any(k in q for k in ("overheat", "hot", "temp", "thermal")):
        return (
            "Check CPU/GPU temps with Task Manager > Performance or HWiNFO. "
            "If they hit 85-95\u00b0C under load: clean dust, check the cooler "
            "mount/paste, and set a power plan that caps turbo. Maximum Tweaks can "
            "set the High Performance plan under the Power category.")
    if any(k in q for k in ("crash", "bsod", "blue screen", "random restart")):
        return (
            "For crashes/BSODs: 1) read the minidumps \u2014 open Event Viewer > "
            "Windows Logs > System, or use the 'View Reliability History' tool on "
            "the Tools page; 2) check for bad RAM (Windows Memory Diagnostic); "
            "3) update chipset/GPU drivers. Revert any tweak you applied right "
            "before the crashes \u2014 every tweak here is revertable.")
    if any(k in q for k in ("what can you do", "help", "how do you work",
                            "what do you know")):
        return (
            "I can read this PC's real state and explain tweaks. Try asking:\n"
            "\u2022 'show my specs'\n"
            "\u2022 'what tweaks are applied?'\n"
            "\u2022 'explain net-005'\n"
            "\u2022 'is my PC good for gaming?'\n"
            "\u2022 'why is my ping high?'")
    if any(k in q for k in ("good", "worth", "capable", "gaming pc",
                            "can it run", "upgrade")):
        return (
            "I can see the detected specs above. A solid rule of thumb: for 1080p "
            "esports (Fortnite/Valorant/CS2) an 8-core CPU with a mid GPU is "
            "plenty. Run the GPU optimizer and check your FPS with the "
            "performance monitor on the Dashboard for a real answer.")
    return None


def _demo_respond(q: str, profile: dict | None = None) -> str:
    """Offline keyword-router answer used when no AI key is set or the AI
    service is down. Returns a plain-text reply."""
    tools = _route(q)
    results = {}
    for name in tools:
        kwargs = {}
        ids = _ID_RE.findall(q)
        if name in ("get_tweak_info", "check_tweak") and ids:
            kwargs["tweak_id"] = ids[0]
        if name == "list_tweaks":
            cat = next((c for c in sorted({t["category"] for t in TWEAKS})
                        if c.lower() in q.lower()), "all")
            kwargs["category"] = cat
        results[name] = call_tool(name, profile=profile, **kwargs)
    body = "\n\n".join(
        _INTROS.get(n, f"Tool '{n}':") + "\n" + results[n]
        for n in tools)
    advice = _advice(q, results)
    text = "\n\n".join(part for part in (body, advice) if part)
    if not text:
        text = (f"I'm {BOT_NAME}. I can already read this system \u2014 "
                "try 'show my specs', 'what tweaks are applied?', or "
                "'explain net-005'.")
    return text


class ChatAssistant:
    """Stateless assistant: routes a question through the tool registry.

    When a Groq API key is configured every turn goes to the real model via
    ``respond_with_groq`` (which needs the conversation history); otherwise it
    falls back to the offline keyword router so the page still answers. If the
    AI service is down or rate-limited, the same offline router answers so the
    user is never stuck with an error.
    """

    def respond(self, question: str, profile: dict | None = None,
                history: list[dict] | None = None) -> dict:
        """Return {"text": str, "tools": [names used]} for one user message."""
        q = (question or "").strip()
        if not q:
            return {"text": "Ask me anything about your PC.", "tools": []}
        if llm_configured():
            providers = []
            if (GEMINI_API_KEY or "").strip():
                providers.append(("gemini", respond_with_gemini))
            if (GROQ_API_KEY or "").strip():
                providers.append(("groq", respond_with_groq))
            last_tools: list[str] = []
            for name, fn in providers:
                try:
                    result = fn(q, list(history or []), profile)
                except Exception as exc:  # noqa: BLE001
                    logger.warn(f"ai: {name} raised "
                                f"{type(exc).__name__}: {exc}")
                    result = {"text": _SERVICE_ERROR, "tools": []}
                last_tools = result.get("tools") or []
                if not (result.get("text") or "").startswith(_SERVICE_ERROR[:24]):
                    return result
                logger.warn(f"ai: {name} unavailable; trying next provider")
            logger.warn("ai: all providers down; using offline router")
            return {"text": _demo_respond(q, profile) +
                           "\n\n(AI service was busy \u2014 showing quick "
                           "results. Try again in a moment for the full "
                           "answer.)",
                    "tools": last_tools}
        return {"text": _demo_respond(q, profile), "tools": _route(q)}

