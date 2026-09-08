"""AI chat engine — tools + plumbing for a PC assistant.

This module owns the *capabilities* of the assistant and a demo backend.
Every answer is grounded in the real system through the tool registry below:

    get_specs          -> the detected hardware profile (this machine)
    get_applied        -> tweaks this app has applied (with timestamps)
    get_tweak_info     -> full explanation of one tweak by id
    list_tweaks        -> all tweaks in a category
    check_tweak        -> live state of one tweak (active/inactive/unknown)
    recent_activity    -> the in-app activity feed

The tool definitions are written in the OpenAI function-calling schema so the
exact same registry can be handed to a real LLM (Ollama / OpenAI / Anthropic)
later: the model calls ``name(args)`` and we execute ``call_tool``.  Until a
model is connected, ``ChatAssistant.respond`` uses a small keyword router that
calls the same tools, so the plumbing is proven end to end.
"""
from __future__ import annotations

import re

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
    applied_txt = "recorded as applied by Rex Tweaks" if applied else "not recorded as applied"
    return f"[{t['id']}] {t['name']}: {state_txt}. {applied_txt}."


def tool_recent_activity() -> str:
    rows = activity.history(10)
    if not rows:
        return "No activity yet this session."
    return "\n".join(f"{r['time']}  {r['kind'].upper()}  {r['text']}" for r in rows)


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
]

_HANDLERS = {
    "get_specs": tool_get_specs,
    "get_applied": tool_get_applied,
    "get_tweak_info": tool_get_tweak_info,
    "list_tweaks": tool_list_tweaks,
    "check_tweak": tool_check_tweak,
    "recent_activity": tool_recent_activity,
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
        "You are the Rex Tweaks assistant, an expert on Windows PC performance "
        "and troubleshooting. Answer concisely and practically. You may use the "
        "provided tools to read the actual system.\n\n"
        "Detected system:\n" + _fmt_specs(profile)
    )


# ---------------------------------------------------------------------------
# Demo backend: keyword router that drives the same tools.
# ---------------------------------------------------------------------------

_ID_RE = re.compile(r"\b([a-z]{2,6}-\d{3})\b")

_INTROS = {
    "get_specs": "Here is the detected hardware of this PC:",
    "get_applied": "Here is what has been applied to this system so far:",
    "recent_activity": "Recent activity:",
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
            "mount/paste, and set a power plan that caps turbo. Rex Tweaks can "
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


class ChatAssistant:
    """Stateless assistant: routes a question through the tool registry."""

    def respond(self, question: str, profile: dict | None = None) -> dict:
        """Return {"text": str, "tools": [names used]} for one user message."""
        q = (question or "").strip()
        if not q:
            return {"text": "Ask me anything about your PC.", "tools": []}
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
            text = ("I'm the demo assistant \u2014 connect a real model "
                    "(Ollama/OpenAI) in engine/chat.py for full answers. I can "
                    "already read this system: try 'show my specs', 'what tweaks "
                    "are applied?', or 'explain net-005'.")
        return {"text": text, "tools": tools}
