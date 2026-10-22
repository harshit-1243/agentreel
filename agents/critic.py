"""Critic / QA: explicit, checkable rules. Two gates:

  review_script  - before any asset is generated (cheap): word budget, hook
                   length, fact grounding, numbers, must-include / must-avoid.
  review_video   - after the edit: duration, resolution, fps, codecs, file size,
                   loudness, captions, safe zones, CTA + AI disclosure.

Each failed check names the agent it routes back to. The orchestrator loops
at most 3 times; qa_report.json records every iteration."""
from __future__ import annotations

import re
import subprocess
from pathlib import Path

from .common import RUN_LOG, Fact, RunContext, ScriptLine, log_call, say
from .planner import HOOK_WPS

NUM_WORDS = {"one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7, "eight": 8,
             "nine": 9, "ten": 10, "twelve": 12, "fifteen": 15, "twenty": 20, "thirty": 30, "forty": 40,
             "fifty": 50, "sixty": 60, "hundred": 100}
HYPE = re.compile(r"\b(\d+\s*%|lpa|crore|lakh|highest package|100\s*percent|placement record|"
                  r"top[- ]\d+|ranked|#1|number one|guaranteed)\b", re.I)


def _numbers(text: str) -> set[int]:
    nums = {int(n) for n in re.findall(r"\d+", text.replace(",", ""))}
    t = text.lower()
    for m in re.finditer(r"\b(five|four|three|two|one|six|seven|eight|nine|ten)[- ]hundred\b", t):
        nums.add(NUM_WORDS[m.group(1)] * 100)
        t = t.replace(m.group(0), " ")
    for w, v in NUM_WORDS.items():
        if re.search(rf"\b{w}\b", t):
            nums.add(v)
    nums.discard(1)  # "one command", "one brief" are not statistics
    return nums


def _check(cid, name, ok, detail, route):
    return {"id": cid, "name": name, "passed": bool(ok), "detail": detail, "route_to": None if ok else route}


def review_script(ctx: RunContext, plan: dict, lines: list[ScriptLine], facts: list[Fact]) -> dict:
    fmap = {f.id: f for f in facts}
    words = sum(len(l.text.split()) for l in lines)
    cap = plan["word_budget"]["max"]
    hook = lines[0]
    hook_s = len(hook.text.split()) / HOOK_WPS
    fact_text = " ".join(f.claim for f in facts if f.verified)
    allowed = _numbers(fact_text) | {3}
    body = [l for l in lines if l.role == "body"]

    ungrounded = [l.id for l in body if not l.fact_ids or any(
        (fid not in fmap or not fmap[fid].verified) and not (fid == "SELF:run_log" and RUN_LOG.exists())
        for fid in l.fact_ids)]
    stray = sorted({n for l in lines for n in _numbers(l.text)} - allowed)
    hype = [l.id for l in lines if HYPE.search(l.text)]
    all_text = " ".join(l.text for l in lines).lower()
    checks = [
        _check("S1", "word budget", words <= cap, f"{words} words vs max {cap}"
               + ("" if words <= cap else f" (over by {words - cap})"), "scriptwriter"),
        _check("S2", "hook <= 3 s", hook_s <= 3.0, f"\"{hook.text}\" ~{hook_s:.2f}s", "scriptwriter"),
        _check("S3", "every body line cites a verified fact", not ungrounded,
               "all grounded" if not ungrounded else f"ungrounded: {ungrounded}", "researcher"),
        _check("S4", "no numbers absent from facts.json", not stray,
               "numbers ok" if not stray else f"unsupported numbers {stray}", "scriptwriter"),
        _check("S5", "must avoid: exaggerated placement figures / stats", not hype,
               "clean" if not hype else f"hype terms in {hype}", "scriptwriter"),
        _check("S6", "must include: real lab infrastructure", "lab" in all_text,
               "mentions the Agentic AI Lab", "scriptwriter"),
        _check("S7", "must include: real-world deployment skills", "deploy" in all_text,
               "mentions deployment targets", "scriptwriter"),
        _check("S8", "CTA present", lines[-1].text.strip() == ctx.brief.cta.strip(),
               f"\"{lines[-1].text}\"", "scriptwriter"),
    ]
    rep = _finish(ctx, "script", checks)
    rep["over_words"] = max(0, words - cap)
    return rep


def probe(path: Path) -> dict:
    from .editor import ffmpeg_exe
    r = subprocess.run([ffmpeg_exe(), "-hide_banner", "-i", str(path)], capture_output=True, text=True)
    s = r.stderr
    dur = re.search(r"Duration: (\d+):(\d+):([\d.]+)", s)
    v = re.search(r"Video: (\w+) \(([^)]+)\).*?, (\w+)\(?.*?, (\d+)x(\d+).*?, ([\d.]+) fps", s)
    a = re.search(r"Audio: (\w+).*?, (\d+) Hz, (\w+).*?, (\d+) kb/s", s)
    return {
        "duration": int(dur[1]) * 3600 + int(dur[2]) * 60 + float(dur[3]) if dur else 0.0,
        "vcodec": v[1] if v else None, "profile": v[2] if v else None, "pix_fmt": v[3] if v else None,
        "width": int(v[4]) if v else 0, "height": int(v[5]) if v else 0, "fps": float(v[6]) if v else 0,
        "acodec": a[1] if a else None, "sr": int(a[2]) if a else 0, "channels": a[3] if a else None,
        "abitrate": int(a[4]) if a else 0, "size_mb": round(path.stat().st_size / 1e6, 2),
    }


def review_video(ctx: RunContext, plan: dict, meta: dict) -> dict:
    from .common import ROOT
    from .editor import loudnorm_measure
    path = ROOT / meta["final"]
    p = probe(path)
    lufs = float(loudnorm_measure(path)["input_i"])
    lay = meta["layout"]
    target = ctx.brief.duration_s
    checks = [
        _check("V1", "duration 30-60 s", 30 <= p["duration"] <= 60, f"{p['duration']:.2f}s", "scriptwriter"),
        _check("V2", f"duration near brief ({target}s ±20%)", abs(p["duration"] - target) <= 0.2 * target,
               f"{p['duration']:.2f}s vs {target}s", "scriptwriter"),
        _check("V3", "1080x1920 (9:16)", (p["width"], p["height"]) == (1080, 1920),
               f"{p['width']}x{p['height']}", "editor"),
        _check("V4", "constant 30 fps", abs(p["fps"] - 30) < 0.01, f"{p['fps']} fps", "editor"),
        _check("V5", "H.264 High, yuv420p", p["vcodec"] == "h264" and p["profile"] == "High"
               and p["pix_fmt"] == "yuv420p", f"{p['vcodec']} {p['profile']} {p['pix_fmt']}", "editor"),
        _check("V6", "AAC 48 kHz stereo 128-192 kbps", p["acodec"] == "aac" and p["sr"] == 48000
               and p["channels"] == "stereo" and 120 <= p["abitrate"] <= 200,
               f"{p['acodec']} {p['sr']} Hz {p['channels']} {p['abitrate']} kb/s", "editor"),
        _check("V7", "file size <= 100 MB", p["size_mb"] <= 100, f"{p['size_mb']} MB", "editor"),
        _check("V8", "loudness ≈ -14 LUFS (±1.5)", abs(lufs + 14) <= 1.5, f"{lufs:.1f} LUFS", "editor"),
        _check("V9", "burned captions + .srt", len(meta["captions"]) > 0 and (ROOT / meta["srt"]).exists(),
               f"{len(meta['captions'])} cues, {meta['srt']}", "editor"),
        _check("V10", "text inside safe zones (top 250 / bottom 350 px)",
               lay["topbar"][0] >= lay["safe_top"] and lay["headline"][0] >= lay["safe_top"]
               and lay["caption"][1] <= lay["safe_bottom"],
               f"topbar {lay['topbar']}, headline {lay['headline']}, captions {lay['caption']}", "editor"),
        _check("V11", "hook spoken inside first 3 s", meta["captions"][0]["start"] < 0.5
               and meta["timeline"][0]["end"] <= 3.6, f"first cue at {meta['captions'][0]['start']}s, "
               f"hook shot ends {meta['timeline'][0]['end']}s", "scriptwriter"),
        _check("V12", "end card 3-5 s with CTA + AI disclosure",
               3 <= meta["timeline"][-1]["end"] - meta["timeline"][-1]["start"] <= 5
               and meta["disclosure"] == "Created with AI agents — LY Agentic AI Lab"
               and meta["cta"] == ctx.brief.cta, f"\"{meta['disclosure']}\"", "editor"),
    ]
    rep = _finish(ctx, "video", checks)
    rep["probe"] = p
    rep["lufs"] = lufs
    return rep


def _finish(ctx, gate, checks):
    ok = all(c["passed"] for c in checks)
    routes = sorted({c["route_to"] for c in checks if c["route_to"]})
    log_call(ctx, agent="critic", tool=f"rules:{gate}", provider="local", model="rule-engine",
             units=f"{sum(c['passed'] for c in checks)}/{len(checks)} pass", status="ok" if ok else "fail")
    for c in checks:
        if not c["passed"]:
            say("critic", f"FAIL {c['id']} {c['name']}: {c['detail']} -> {c['route_to']}")
    say("critic", f"{gate} gate: {'PASS' if ok else 'FAIL'} ({sum(c['passed'] for c in checks)}/{len(checks)})")
    return {"gate": gate, "status": "pass" if ok else "fail", "checks": checks, "route_to": routes}
