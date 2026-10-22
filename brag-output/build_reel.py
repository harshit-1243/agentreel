"""Builds the HyperFrames composition for the submission reel from a finished
pipeline run, so every scene lands on its spoken line and every number on
screen comes from the run's own artefacts.

    python brag-output/build_reel.py            # writes brag-output/composition/
    npx hyperframes check  brag-output/composition
    npx hyperframes render brag-output/composition -o brag-output/brag.mp4

Inputs: outputs/{edit_meta,script,storyboard,facts,qa_report}.json, logs/run_log.jsonl,
outputs/G19_C05_final.mp4 (audio mix), outputs/frames/*.jpg, docs/screenshots/frontend_hero.png
"""
from __future__ import annotations

import html
import json
import re
import shutil
import subprocess
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "outputs"
COMP = Path(__file__).resolve().parent / "composition"
SFX_SRC = Path.home() / ".claude/plugins/cache/brag/brag/0.4.0/skills/brag/assets/sfx"
W, H = 1080, 1920

E = html.escape
load = lambda p: json.loads((OUT / p).read_text(encoding="utf-8"))

# --------------------------------------------------------------------- shared
BASE_CSS = """
@font-face { font-family: 'Archivo'; src: url('assets/fonts/Archivo.ttf'); font-weight: 100 900; font-stretch: 62% 125%; }
#root { position: absolute; inset: 0; color: #263a8c; font-family: 'Archivo', sans-serif; font-weight: 500; }
.serif { font-family: 'Archivo', sans-serif; font-weight: 900; font-stretch: 112%; letter-spacing: -0.02em; }
.mono { font-family: 'JetBrains Mono', monospace; }
.red { color: #e8412c; } .amber { color: #263a8c; } .mute { color: #263a8c; }
.card { position: absolute; background: #ede9e0; border: 5px solid #263a8c; }
.kick { font-family: 'Archivo', sans-serif; font-size: 32px; font-weight: 800; font-stretch: 100%; color: #263a8c;
        border-bottom: 3px solid #263a8c; padding-bottom: 6px; }
.plate { text-shadow: 6px 4px 0 rgba(232,65,44,.92); }
"""


def word_time(meta, shot, target, scene_start, fallback):
    """Local time (s) at which `target` is spoken inside `shot`."""
    t = target.lower()
    for c in meta["captions"]:
        if c["shot"] != shot:
            continue
        for w in c["words"]:
            if re.sub(r"[^a-z0-9-]", "", w["w"].lower()).startswith(t):
                return round(w["t0"] - scene_start, 3)
    return fallback


def scene_file(sid, body, css, js):
    return f"""<template>
  <style>{BASE_CSS}{css}</style>
  <div id="root" data-composition-id="{sid}" data-width="{W}" data-height="{H}">
{body}
  </div>
  <script>
    const tl = gsap.timeline({{ paused: true }});
{js}
    window.__timelines["{sid}"] = tl;
  </script>
</template>
"""


# --------------------------------------------------------------------- scenes
def sc_hook(sid, seg, ctx):
    t_build = word_time(ctx["meta"], seg["shot"], "build", seg["start"], 1.5)
    d = seg["end"] - seg["start"]
    body = f"""
    <div id="{sid}-k" class="kick" style="position:absolute;top:300px;left:96px;">BRIEF {E(ctx['brief']['id'])} · ASPIRANTS &amp; RECRUITERS</div>
    <div id="{sid}-q" class="serif plate" style="position:absolute;top:380px;left:80px;right:50px;font-size:126px;line-height:.94;font-stretch:104%;">
      What does an <span class="red">AI&#8209;ready</span> graduate <span id="{sid}-w" style="display:inline-block;">build?</span>
    </div>
    <div id="{sid}-line" style="position:absolute;top:1090px;left:96px;width:0;height:4px;background:#e8412c;"></div>"""
    js = f"""
    tl.fromTo("#{sid}-w", {{ opacity: 0, filter: "blur(10px)", y: 30 }}, {{ opacity: 1, filter: "blur(0px)", y: 0, duration: 0.22, ease: "power4.out" }}, {t_build - 0.05:.2f});
    tl.fromTo("#{sid}-line", {{ width: 0 }}, {{ width: 520, duration: 0.6, ease: "expo.out" }}, {t_build:.2f});
    tl.to("#{sid}-q", {{ scale: 1.6, opacity: 0, filter: "blur(14px)", transformOrigin: "50% 40%", duration: 0.3, ease: "power3.in" }}, {d - 0.3:.2f});
    tl.to(["#{sid}-k", "#{sid}-line"], {{ opacity: 0, duration: 0.2 }}, {d - 0.3:.2f});"""
    return body, "", js


def sc_lab(sid, seg, ctx):
    b = ctx["brief"]
    d = seg["end"] - seg["start"]
    t_study = word_time(ctx["meta"], seg["shot"], "study", seg["start"], d * 0.55)
    t_ship = word_time(ctx["meta"], seg["shot"], "ship", seg["start"], d * 0.85)
    rows = [("ID", b["id"]), ("CATEGORY", b["category"]), ("AUDIENCE", b["audience"]),
            ("FORMAT", "9:16 · %d s" % b["duration_s"])]
    rows_html = "".join(f"""<div class="{sid}-r"><span class="mono mute">{k}</span><span>{E(str(v))}</span></div>""" for k, v in rows)
    body = f"""
    <div id="{sid}-k" class="kick" style="position:absolute;top:250px;left:96px;">FINAL-YEAR · AGENTIC AI LAB · K J SOMAIYA</div>
    <div id="{sid}-card" class="card" style="left:90px;top:320px;width:900px;padding:50px 60px 40px;">
      <div class="mono amber" style="font-size:28px;letter-spacing:.2em;">SEALED BRIEF CARD</div>
      <div class="serif" style="font-size:50px;line-height:1.02;margin:18px 0 22px;">{E(b['topic'].split(':')[0])}:<br><span class="mute" style="">{E(b['topic'].split(':',1)[1].strip())}</span></div>
      {rows_html}
    </div>
    <div id="{sid}-a" class="serif" style="position:absolute;top:1015px;left:80px;font-size:104px;line-height:1;">
      <span id="{sid}-study" style="position:relative;display:inline-block;">study AI<span id="{sid}-strike" style="position:absolute;left:-6px;top:56%;height:8px;width:0;background:#e8412c;"></span></span>
      <span id="{sid}-ship" class="red" style="display:inline-block;">&nbsp;ship it.</span>
    </div>"""
    css = f""".{sid}-r {{ display:flex; justify-content:space-between; gap:30px; padding:13px 0; border-top:1px solid #263a8c; font-size:30px; }}
    .{sid}-r span:last-child {{ text-align:right; }}"""
    js = f"""
    tl.fromTo("#{sid}-card", {{ y: 160, rotation: -4, opacity: 0 }}, {{ y: 0, rotation: 0, opacity: 1, duration: 0.7, ease: "expo.out" }}, 0.05);
    tl.fromTo("#{sid}-k", {{ opacity: 0 }}, {{ opacity: 1, duration: 0.3 }}, 0.2);
    tl.fromTo(".{sid}-r", {{ opacity: 0, x: -20 }}, {{ opacity: 1, x: 0, duration: 0.3, stagger: 0.07, ease: "power3.out" }}, 0.45);
    tl.fromTo("#{sid}-study", {{ opacity: 0, filter: "blur(8px)" }}, {{ opacity: 1, filter: "blur(0px)", duration: 0.2 }}, {t_study - 0.1:.2f});
    tl.fromTo("#{sid}-strike", {{ width: 0 }}, {{ width: 400, duration: 0.35, ease: "power2.inOut" }}, {t_study + 0.6:.2f});
    tl.fromTo("#{sid}-ship", {{ opacity: 0, scale: 1.6, rotation: -6 }}, {{ opacity: 1, scale: 1, rotation: -3, duration: 0.28, ease: "back.out(1.6)" }}, {t_ship - 0.05:.2f});
    tl.to(["#{sid}-card", "#{sid}-a", "#{sid}-k"], {{ opacity: 0, filter: "blur(8px)", duration: 0.2, ease: "power2.in" }}, {d - 0.22:.2f});"""
    ctx["sfx"].append(("interface/drop_002.ogg", seg["start"] + t_ship - 0.02, 0.55))
    return body, css, js


def sc_agents(sid, seg, ctx):
    d = seg["end"] - seg["start"]
    t_critic = word_time(ctx["meta"], seg["shot"], "critic", seg["start"], d * 0.75)
    agg = ctx["agg"]
    names = [("planner", "Planner", "plan.json"), ("researcher", "Researcher", "facts.json"),
             ("scriptwriter", "Scriptwriter", "script.md"), ("storyboarder", "Storyboarder", "storyboard.json"),
             ("asset_generator", "Asset Gen", "manifest.csv"), ("editor", "Editor", "final.mp4"),
             ("critic", "Critic", "qa_report.json")]
    rows = ""
    for i, (k, n, o) in enumerate(names):
        a = agg.get(k, {"n": 0, "t": 0.0})
        rows += f"""<div class="{sid}-row" id="{sid}-row{i}" style="top:{i * 104}px;{'border-color:#e8412c;' if k == 'critic' else ''}">
          <span class="mono amber" style="font-size:28px;width:60px;">0{i + 1}</span>
          <span style="flex:1;font-weight:700;font-size:38px;white-space:nowrap;">{n}</span>
          <span class="mono mute" style="font-size:28px;margin-right:22px;white-space:nowrap;">{a['t']:.1f}s</span>
          <span class="mono" style="font-size:28px;color:#263a8c;">{o}</span></div>"""
    body = f"""
    <div id="{sid}-k" class="kick" style="position:absolute;top:220px;left:96px;">SEVEN AGENTS · ONE COMMAND</div>
    <div id="{sid}-lane" style="position:absolute;left:90px;top:290px;width:830px;height:740px;">{rows}</div>
    <svg id="{sid}-loop" style="position:absolute;left:900px;top:290px;" width="140" height="740" viewBox="0 0 140 740">
      <path id="{sid}-path" d="M 20 668 C 120 668, 120 252, 20 252" fill="none" stroke="#e8412c" stroke-width="7" stroke-linecap="round" stroke-dasharray="560" stroke-dashoffset="560"/>
      <path id="{sid}-head" d="M 20 252 l 26 -16 M 20 252 l 26 16" stroke="#e8412c" stroke-width="7" stroke-linecap="round" opacity="0"/>
    </svg>
    <div id="{sid}-lbl" class="mono red" style="position:absolute;top:1046px;left:96px;font-size:30px;letter-spacing:.1em;">CRITIC → SCRIPTWRITER · MAX 3 LOOPS</div>"""
    css = f""".{sid}-row {{ position:absolute; left:0; width:830px; height:88px; display:flex; align-items:center; padding:0 30px;
      background:#ede9e0; border:2px solid #263a8c;  }}"""
    step = min(0.32, max(0.12, (t_critic - 0.3) / 7))
    js = f"""
    tl.fromTo("#{sid}-k", {{ opacity: 0 }}, {{ opacity: 1, duration: 0.25 }}, 0);
    tl.fromTo(".{sid}-row", {{ opacity: 0.0, x: 60, filter: "blur(6px)" }}, {{ opacity: 1, x: 0, filter: "blur(0px)", duration: 0.35, stagger: {step:.3f}, ease: "expo.out" }}, 0.1);
    tl.fromTo("#{sid}-path", {{ strokeDashoffset: 560 }}, {{ strokeDashoffset: 0, duration: 0.5, ease: "power2.inOut" }}, {t_critic:.2f});
    tl.fromTo("#{sid}-head", {{ opacity: 0 }}, {{ opacity: 1, duration: 0.1 }}, {t_critic + 0.45:.2f});
    tl.fromTo("#{sid}-lbl", {{ opacity: 0, y: 14 }}, {{ opacity: 1, y: 0, duration: 0.3, ease: "power3.out" }}, {t_critic + 0.2:.2f});
    tl.to("#{sid}-lane", {{ x: -1100, filter: "blur(10px)", duration: 0.28, ease: "power3.in" }}, {d - 0.28:.2f});
    tl.to(["#{sid}-loop", "#{sid}-lbl", "#{sid}-k"], {{ opacity: 0, duration: 0.18 }}, {d - 0.25:.2f});"""
    return body, css, js


def sc_constraint(sid, seg, ctx):
    d = seg["end"] - seg["start"]
    m = ctx["meta"]
    t1 = word_time(m, seg["shot"], "sealed", seg["start"], 0.2)
    t2 = word_time(m, seg["shot"], "three-hour", seg["start"], None) or word_time(m, seg["shot"], "three", seg["start"], d * 0.35)
    t3 = word_time(m, seg["shot"], "five-hundred", seg["start"], None) or word_time(m, seg["shot"], "five", seg["start"], d * 0.68)
    spend = ctx["spent"]
    body = f"""
    <div id="{sid}-k" class="kick" style="position:absolute;top:220px;left:96px;">THE LIVE-RUN RULES</div>
    <div id="{sid}-b1" class="card" style="left:90px;top:300px;width:900px;height:200px;padding:0 54px;display:flex;align-items:center;justify-content:space-between;">
      <span class="serif" style="font-size:84px;">A sealed brief</span>
      <span id="{sid}-seal" class="mono" style="font-size:30px;letter-spacing:.2em;color:#220f18;background:#e8412c;padding:14px 22px;transform:rotate(-6deg);">SEALED</span></div>
    <div id="{sid}-b2" class="card" style="left:90px;top:530px;width:900px;height:250px;padding:0 54px;display:flex;align-items:center;justify-content:space-between;">
      <span class="serif" style="font-size:84px;line-height:.95;">Hard<br>stop</span>
      <span id="{sid}-clock" class="mono amber" style="font-size:118px;font-weight:700;">3:00:00</span></div>
    <div id="{sid}-b3" class="card" style="left:90px;top:810px;width:900px;height:260px;padding:44px 54px;">
      <div style="display:flex;justify-content:space-between;align-items:baseline;">
        <span class="serif" style="font-size:72px;">Budget</span>
        <span style="font-size:40px;font-weight:800;white-space:nowrap;"><span style="color:#263a8c;">₹{spend:.2f}</span><span class="mute"> / ₹500</span></span></div>
      <div style="margin-top:36px;height:22px;background:#263a8c;overflow:hidden;">
        <div id="{sid}-bar" style="height:100%;width:100%;background:linear-gradient(90deg,#e8412c,#263a8c);transform-origin:0 50%;"></div></div>
      <div class="mono mute" style="font-size:28px;margin-top:14px;">every call costed in cost_report.csv</div></div>"""
    js = f"""
    tl.fromTo("#{sid}-k", {{ opacity: 0 }}, {{ opacity: 1, duration: 0.25 }}, 0);
    tl.fromTo("#{sid}-b1", {{ opacity: 0, y: 80 }}, {{ opacity: 1, y: 0, duration: 0.5, ease: "expo.out" }}, {max(0.0, t1 - 0.5):.2f});
    tl.fromTo("#{sid}-seal", {{ opacity: 0, scale: 2.2 }}, {{ opacity: 1, scale: 1, duration: 0.22, ease: "power4.out" }}, {t1:.2f});
    tl.fromTo("#{sid}-b2", {{ opacity: 0, y: 80 }}, {{ opacity: 1, y: 0, duration: 0.5, ease: "expo.out" }}, {t2 - 0.25:.2f});
    tl.fromTo("#{sid}-b3", {{ opacity: 0, y: 80 }}, {{ opacity: 1, y: 0, duration: 0.5, ease: "expo.out" }}, {t3 - 0.25:.2f});
    tl.fromTo("#{sid}-bar", {{ scaleX: 0 }}, {{ scaleX: {max(0.004, spend / 500):.4f}, duration: 0.8, ease: "power2.out" }}, {t3 + 0.2:.2f});
    tl.to(["#{sid}-b1", "#{sid}-b2", "#{sid}-k"], {{ opacity: 0, y: -60, duration: 0.25, ease: "power3.in" }}, {d - 0.3:.2f});
    tl.to("#{sid}-b3", {{ scale: 1.25, opacity: 0, filter: "blur(10px)", duration: 0.3, ease: "power3.in" }}, {d - 0.3:.2f});"""
    # countdown ticks: deterministic, a function of timeline time
    js += f"""
    const {sid}Clock = {{ s: 10800 }};
    tl.to({sid}Clock, {{ s: 10800 - {max(1.0, d - t2):.2f} * 37, duration: {max(0.5, d - t2 - 0.3):.2f}, ease: "none",
      onUpdate: () => {{ const s = Math.round({sid}Clock.s); const el = document.querySelector("#{sid}-clock");
        if (el) el.textContent = Math.floor(s / 3600) + ":" + String(Math.floor(s / 60) % 60).padStart(2, "0") + ":" + String(s % 60).padStart(2, "0"); }} }}, {t2:.2f});"""
    ctx["sfx"].append(("impact/impactSoft_medium_001.ogg", seg["start"] + t1, 0.6))
    return body, "", js


def sc_logging(sid, seg, ctx):
    d = seg["end"] - seg["start"]
    recs = [r for r in ctx["logs"] if r["agent"] not in ("orchestrator",)][:11]
    lines = ""
    for i, r in enumerate(recs):
        lines += f"""<div class="{sid}-ln" style="top:{i * 52}px;"><span class="amber">{E(r['agent'][:14]):<14}</span><span>{E(r['tool'][:16])}</span><span class="mute">{r['latency_s']:.2f}s</span><span style="color:#263a8c;">₹{r['cost_inr']:.2f}</span><span class="mute">{E(r['status'][:4])}</span></div>"""
    cmd = f"python run.py --brief briefs/{ctx['brief']['id']}.yaml --seed 42"
    t_cmd = word_time(ctx["meta"], seg["shot"], "one", seg["start"], d * 0.6)
    body = f"""
    <div id="{sid}-k" class="kick" style="position:absolute;top:220px;left:96px;">LOGS/RUN_LOG.JSONL · RUN {E(ctx['run_id'])}</div>
    <div id="{sid}-term" class="card" style="left:60px;top:290px;width:960px;height:800px;">
      <div style="display:flex;gap:12px;padding:26px 30px;border-bottom:1px solid #263a8c;">
        <i style="width:18px;height:18px;background:#e8412c;"></i><i style="width:18px;height:18px;background:#263a8c;"></i><i style="width:18px;height:18px;background:#263a8c;"></i></div>
      <div style="position:absolute;left:34px;top:96px;width:900px;height:580px;">{lines}</div>
      <div id="{sid}-cmd" class="mono" style="position:absolute;left:34px;bottom:44px;font-size:28px;color:#263a8c;white-space:nowrap;overflow:hidden;width:0;">
        <span class="mute">$ </span>{E(cmd)}</div></div>"""
    css = f""".{sid}-ln {{ position:absolute; left:0; width:900px; display:grid; grid-template-columns: 250px 290px 120px 110px 80px;
      font-family:'JetBrains Mono',monospace; font-size:28px; color:#263a8c; }}"""
    n = max(1, len(recs))
    step = min(0.22, max(0.08, (t_cmd - 0.4) / n))
    js = f"""
    tl.fromTo("#{sid}-term", {{ opacity: 0, scale: 0.92 }}, {{ opacity: 1, scale: 1, duration: 0.45, ease: "expo.out" }}, 0);
    tl.fromTo("#{sid}-k", {{ opacity: 0 }}, {{ opacity: 1, duration: 0.25 }}, 0.1);
    tl.fromTo(".{sid}-ln", {{ opacity: 0 }}, {{ opacity: 1, duration: 0.05, stagger: {step:.3f} }}, 0.35);
    tl.fromTo("#{sid}-cmd", {{ width: 0 }}, {{ width: 900, duration: 1.0, ease: "steps(52)" }}, {t_cmd:.2f});
    tl.to("#{sid}-term", {{ scaleY: 0.82, scaleX: 0.96, opacity: 0, filter: "blur(8px)", duration: 0.28, ease: "power3.in" }}, {d - 0.3:.2f});
    tl.to("#{sid}-k", {{ opacity: 0, duration: 0.2 }}, {d - 0.3:.2f});"""
    for i in range(0, n, 3):
        ctx["sfx"].append((f"keyboard/keypress-0{(i % 9) + 10}.wav", seg["start"] + 0.35 + i * step, 0.35))
    return body, css, js


def sc_deploy(sid, seg, ctx):
    d = seg["end"] - seg["start"]
    m = ctx["meta"]
    tg = [word_time(m, seg["shot"], "github", seg["start"], d * 0.45),
          word_time(m, seg["shot"], "hugging", seg["start"], d * 0.62),
          word_time(m, seg["shot"], "streamlit", seg["start"], d * 0.8)]
    pills = "".join(f"""<span id="{sid}-p{i}" class="{sid}-pill">{n}</span>""" for i, n in
                    enumerate(["GitHub Pages", "Hugging Face Spaces", "Streamlit Cloud"]))
    body = f"""
    <div id="{sid}-k" class="kick" style="position:absolute;top:220px;left:96px;">DEPLOY TARGETS · FROM THE LAB HANDOUT</div>
    <div id="{sid}-win" class="card" style="left:60px;top:290px;width:960px;height:640px;overflow:hidden;">
      <div style="height:74px;display:flex;align-items:center;gap:12px;padding:0 28px;border-bottom:1px solid #263a8c;background:#ede9e0;">
        <i style="width:16px;height:16px;background:#e8412c;"></i><i style="width:16px;height:16px;background:#263a8c;"></i><i style="width:16px;height:16px;background:#263a8c;"></i>
        <span class="mono mute" style="margin-left:24px;font-size:28px;background:#ede9e0;padding:8px 18px;">AgentReel · run dashboard</span></div>
      <img src="assets/img/dashboard.png" style="position:absolute;left:0;top:74px;width:960px;height:auto;" alt="">
    </div>
    <div id="{sid}-pills" style="position:absolute;left:60px;top:970px;width:960px;display:flex;flex-wrap:wrap;gap:16px;">{pills}</div>"""
    css = f""".{sid}-pill {{ font-family:'JetBrains Mono',monospace; font-size:30px; padding:16px 26px; 
      border:2px solid #263a8c; color:#263a8c; background:#ede9e0; }}"""
    js = f"""
    tl.fromTo("#{sid}-win", {{ opacity: 0, y: 120 }}, {{ opacity: 1, y: 0, duration: 0.6, ease: "expo.out" }}, 0);
    tl.fromTo("#{sid}-win img", {{ y: 0 }}, {{ y: -170, duration: {max(1.0, d - 0.6):.2f}, ease: "power1.inOut" }}, 0.3);
    tl.fromTo("#{sid}-k", {{ opacity: 0 }}, {{ opacity: 1, duration: 0.25 }}, 0.1);"""
    for i, t in enumerate(tg):
        js += f"""
    tl.fromTo("#{sid}-p{i}", {{ color: "#263a8c", borderColor: "#263a8c", y: 16, opacity: 0.3 }}, {{ color: "#263a8c", borderColor: "#263a8c", y: 0, opacity: 1, duration: 0.25, ease: "power3.out" }}, {t - 0.05:.2f});"""
        ctx["sfx"].append((f"interface/drop_00{i + 1}.ogg", seg["start"] + t - 0.03, 0.4))
    js += f"""
    tl.to(["#{sid}-win", "#{sid}-pills", "#{sid}-k"], {{ opacity: 0, duration: 0.25, ease: "power2.in" }}, {d - 0.27:.2f});"""
    return body, css, js


def sc_responsible(sid, seg, ctx):
    d = seg["end"] - seg["start"]
    m = ctx["meta"]
    items = [("grounding", f"{ctx['n_facts']} facts · every one with source + page"),
             ("consent", "no faces, no cloned voices"),
             ("disclosure", "“Created with AI agents” end card"),
             ("licensing", "manifest.csv · OFL fonts · CC0 music")]
    rows = ""
    for i, (w, ev) in enumerate(items):
        rows += f"""<div class="{sid}-row" id="{sid}-r{i}" style="top:{i * 170}px;">
          <span id="{sid}-c{i}" class="{sid}-chk">✓</span>
          <div><div class="serif" style="font-size:76px;line-height:1;text-transform:capitalize;">{w}</div>
          <div class="mono mute" style="font-size:28px;margin-top:8px;">{E(ev)}</div></div></div>"""
    body = f"""
    <div id="{sid}-k" class="kick" style="position:absolute;top:220px;left:96px;">RESPONSIBLE AI · CHECKED BY THE CRITIC</div>
    <div style="position:absolute;left:96px;top:310px;width:900px;height:700px;">{rows}</div>"""
    css = f""".{sid}-row {{ position:absolute; left:0; width:890px; display:flex; gap:40px; align-items:center; }}
    .{sid}-chk {{ width:96px; height:96px; flex:0 0 96px; border-radius:50%; display:grid; place-items:center; font-size:52px; font-weight:800;
      background:#ede9e0; border:3px solid #263a8c; color:#263a8c; }}"""
    js = f"""
    tl.fromTo("#{sid}-k", {{ opacity: 0 }}, {{ opacity: 1, duration: 0.25 }}, 0);"""
    for i, (w, _) in enumerate(items):
        t = word_time(m, seg["shot"], w, seg["start"], 0.6 + i * 0.7)
        js += f"""
    tl.fromTo("#{sid}-r{i}", {{ opacity: 0.25, x: -20 }}, {{ opacity: 1, x: 0, duration: 0.25, ease: "power3.out" }}, {t - 0.05:.2f});
    tl.fromTo("#{sid}-c{i}", {{ backgroundColor: "#ede9e0", color: "#ede9e0", borderColor: "#263a8c", scale: 0.7 }}, {{ backgroundColor: "#e8412c", color: "#220f18", borderColor: "#e8412c", scale: 1, duration: 0.25, ease: "back.out(2)" }}, {t:.2f});"""
        ctx["sfx"].append((f"interface/drop_00{(i % 3) + 1}.ogg", seg["start"] + t - 0.02, 0.4))
    js += f"""
    tl.to([".{sid}-row", "#{sid}-k"], {{ opacity: 0, x: 80, duration: 0.25, stagger: 0.03, ease: "power3.in" }}, {d - 0.35:.2f});"""
    return body, css, js


def sc_proof(sid, seg, ctx):
    d = seg["end"] - seg["start"]
    frames = ctx["frames"]
    tiles = "".join(f"""<img class="{sid}-f" src="assets/frames/{f}" style="left:{(i % 3) * 300}px;top:{(i // 3) * 520}px;" alt="">"""
                    for i, f in enumerate(frames))
    qa = ctx["qa"]
    passed = sum(c["passed"] for h in qa["history"] if h["status"] == "pass" for c in h["checks"])
    total = sum(len(h["checks"]) for h in qa["history"] if h["status"] == "pass")
    t_ag = word_time(ctx["meta"], seg["shot"], "agents", seg["start"], d * 0.75)
    body = f"""
    <div id="{sid}-k" class="kick" style="position:absolute;top:220px;left:96px;">FRAMES RENDERED BY THE EDITOR AGENT</div>
    <div id="{sid}-mask" style="position:absolute;left:90px;top:290px;width:900px;height:800px;overflow:hidden;" data-layout-allow-overflow>
      <div id="{sid}-grid" style="position:absolute;left:0;top:0;width:900px;height:{((len(frames) + 2) // 3) * 520}px;">{tiles}</div></div>
    <div id="{sid}-badge" style="position:absolute;left:150px;top:560px;width:780px;padding:40px 44px;background:#ede9e0;border:3px solid #e8412c;">
      <div class="mono amber" style="font-size:28px;letter-spacing:.14em;">RUN {E(ctx['run_id'])}</div>
      <div class="serif" style="font-size:96px;line-height:1;margin-top:12px;">QA <span class="red" style="">passed</span></div>
      <div class="mono mute" style="font-size:28px;margin-top:14px;">{passed}/{total} rules · {qa['duration_s']:.1f} s · {qa['lufs']:.1f} LUFS · ₹{ctx['spent']:.2f}</div></div>"""
    css = f""".{sid}-f {{ position:absolute; width:290px; height:515px; object-fit:cover;  border:2px solid #263a8c; }}"""
    rows = (len(frames) + 2) // 3
    js = f"""
    tl.fromTo("#{sid}-k", {{ opacity: 0 }}, {{ opacity: 1, duration: 0.25 }}, 0);
    tl.fromTo("#{sid}-mask", {{ opacity: 0, scale: 0.9 }}, {{ opacity: 1, scale: 1, duration: 0.5, ease: "expo.out" }}, 0);
    tl.fromTo("#{sid}-grid", {{ y: 0 }}, {{ y: {-(rows * 520 - 800)}, duration: {max(1.0, d - 0.4):.2f}, ease: "power1.inOut" }}, 0.2);
    tl.fromTo("#{sid}-badge", {{ opacity: 0, y: 40, scale: 0.94 }}, {{ opacity: 1, y: 0, scale: 1, duration: 0.4, ease: "expo.out" }}, {t_ag:.2f});
    tl.to(["#{sid}-mask", "#{sid}-badge", "#{sid}-k"], {{ opacity: 0, duration: 0.15 }}, {d - 0.17:.2f});"""
    ctx["sfx"].append(("impact/impactSoft_medium_002.ogg", seg["start"] + t_ag, 0.45))
    return body, css, js


def sc_cta(sid, seg, ctx):
    d = seg["end"] - seg["start"]
    words = ctx["brief"]["cta"].split()
    spans = ""
    for i, w in enumerate(words):
        cls = "red" if i == len(words) - 1 else ""
        spans += f"""<span id="{sid}-w{i}" class="{cls}" style="display:inline-block;margin-right:28px;">{E(w).replace('-', '&#8209;')}</span>"""
    js = f"""
    tl.fromTo("#{sid}-k", {{ opacity: 0 }}, {{ opacity: 1, duration: 0.25 }}, 0);"""
    for i, w in enumerate(words):
        t = word_time(ctx["meta"], seg["shot"], re.sub(r"[^a-z0-9-]", "", w.lower()), seg["start"], 0.15 + i * 0.3)
        js += f"""
    tl.fromTo("#{sid}-w{i}", {{ opacity: 0, filter: "blur(8px)" }}, {{ opacity: 1, filter: "blur(0px)", duration: 0.16, ease: "power4.out" }}, {max(0.0, t - 0.04):.2f});"""
    body = f"""
    <div id="{sid}-k" class="kick" style="position:absolute;top:330px;left:96px;">FOR RECRUITERS</div>
    <div class="serif plate" style="position:absolute;left:80px;right:60px;top:400px;font-size:150px;line-height:.92;">{spans}</div>"""
    js += f""""""
    return body, "", js


def sc_fact(sid, seg, ctx):
    """Generic grounded scene for any other line: headline + the fact card it cites."""
    d = seg["end"] - seg["start"]
    shot = next(s for s in ctx["story"] if s["shot_id"] == seg["shot"])
    fact = next((f for f in ctx["facts"] if f["id"] in shot.get("fact_ids", [])), None)
    card = ""
    if fact:
        card = f"""<div id="{sid}-c" class="card" style="left:90px;top:640px;width:900px;padding:50px 56px;">
          <div class="serif" style="font-size:56px;line-height:1.1;">“{E(fact['claim'][:150])}”</div>
          <div class="mono mute" style="font-size:28px;margin-top:20px;">{E(fact['id'])} · {E(fact['source'])} · p.{fact['page']}</div></div>"""
    body = f"""
    <div id="{sid}-h" class="serif" style="position:absolute;left:90px;right:70px;top:330px;font-size:130px;line-height:.98;">{E(shot['on_screen_text'])}</div>
    {card}"""
    js = f"""
    tl.fromTo("#{sid}-h", {{ opacity: 0, filter: "blur(8px)" }}, {{ opacity: 1, filter: "blur(0px)", duration: 0.2 }}, 0.05);
    {'tl.fromTo("#' + sid + '-c", { opacity: 0, y: 60 }, { opacity: 1, y: 0, duration: 0.5, ease: "expo.out" }, 0.3);' if fact else ''}
    tl.to("#{sid}-h", {{ opacity: 0, duration: 0.2 }}, {d - 0.22:.2f});"""
    return body, "", js


def sc_endcard(sid, seg, ctx):
    d = seg["end"] - seg["start"]
    b = ctx["brief"]
    body = f"""
    <div id="{sid}-name" style="position:absolute;left:80px;top:250px;font-size:40px;font-weight:800;">K J Somaiya School of Engineering</div>
    <div id="{sid}-uni" style="position:absolute;left:80px;top:302px;font-size:30px;">Somaiya Vidyavihar University</div>
    <div id="{sid}-flood" style="position:absolute;left:0;right:0;top:400px;height:640px;background:#e8412c;"></div>
    <div id="{sid}-cta" class="serif" style="position:absolute;left:80px;right:60px;top:450px;font-size:120px;line-height:.95;color:#220f18;">{E(b['cta']).replace('-', '&#8209;')}</div>
    <div id="{sid}-mark" class="serif" style="position:absolute;left:80px;top:1090px;font-size:56px;">AI-ready. Industry-ready.</div>
    <div id="{sid}-rule" style="position:absolute;left:80px;right:80px;top:1196px;height:4px;background:#263a8c;"></div>
    <div id="{sid}-disc" style="position:absolute;left:80px;top:1220px;font-size:34px;font-weight:800;">Created with AI agents — LY Agentic AI Lab</div>
    <div id="{sid}-src" style="position:absolute;left:80px;top:1272px;font-size:28px;">Facts: LY Agentic AI Lab handout · Brief {E(b['id'])} · Team G19</div>"""
    js = f"""
    tl.fromTo("#{sid}-flood", {{ scaleY: 0, transformOrigin: "50% 0%" }}, {{ scaleY: 1, duration: 0.45, ease: "expo.out" }}, 0);
    tl.fromTo(["#{sid}-name", "#{sid}-uni"], {{ opacity: 0 }}, {{ opacity: 1, duration: 0.3 }}, 0.05);
    tl.fromTo("#{sid}-mark", {{ opacity: 0, y: 30, filter: "blur(6px)" }}, {{ opacity: 1, y: 0, filter: "blur(0px)", duration: 0.6, ease: "expo.out" }}, 0.15);
    tl.fromTo("#{sid}-rule", {{ scaleX: 0, transformOrigin: "0% 50%" }}, {{ scaleX: 1, duration: 0.4, ease: "expo.out" }}, 0.45);
    tl.fromTo("#{sid}-cta", {{ opacity: 0, filter: "blur(8px)" }}, {{ opacity: 1, filter: "blur(0px)", duration: 0.25, ease: "power4.out" }}, 0.6);
    tl.fromTo(["#{sid}-disc", "#{sid}-src"], {{ opacity: 0 }}, {{ opacity: 1, duration: 0.3, stagger: 0.1 }}, 0.9);"""
    ctx["sfx"].append(("impact/impactBell_heavy_000.ogg", seg["start"] + 0.15, 0.35))
    return body, "", js


BUILDERS = {"hook": sc_hook, "lab": sc_lab, "graph": sc_agents, "clock": sc_constraint, "terminal": sc_logging,
            "deploy": sc_deploy, "shield": sc_responsible, "reel": sc_proof, "cta": sc_cta, "endcard": sc_endcard}


# ------------------------------------------------------------------- captions
def captions_file(meta, total):
    groups, js = "", ""
    for i, c in enumerate(meta["captions"]):
        words = "".join(f"""<span id="cw{i}-{j}" class="cw">{E(w['w'])}</span> """ for j, w in enumerate(c["words"]))
        groups += f"""<div id="cg{i}" class="cg"><span class="pill">{words.strip()}</span></div>\n"""
        s, e = c["start"], c["end"]
        js += f"""    tl.set("#cg{i}", {{ opacity: 1, visibility: "visible" }}, {max(0.1, s):.3f});
    tl.set("#cg{i}", {{ opacity: 0, visibility: "hidden" }}, {e:.3f});\n"""
        for j, w in enumerate(c["words"]):
            js += f"""    tl.set("#cw{i}-{j}", {{ backgroundColor: "#e8412c", color: "#220f18" }}, {w['t0']:.3f});\n"""
            nxt = c["words"][j + 1]["t0"] if j + 1 < len(c["words"]) else e
            js += f"""    tl.set("#cw{i}-{j}", {{ backgroundColor: "rgba(232,65,44,0)", color: "#263a8c" }}, {nxt:.3f});\n"""
    css = """
    @font-face { font-family: 'Archivo'; src: url('assets/fonts/Archivo.ttf'); font-weight: 100 900; font-stretch: 62% 125%; }
    .cg { position:absolute; left:80px; right:60px; top:1160px; text-align:left; opacity:0; visibility:hidden; }
    .pill { display:inline-block; font-family:'Archivo',sans-serif; font-weight:800; font-size:64px; letter-spacing:-0.01em; color:#263a8c; }
    .cw { padding:0 8px; margin:0 -4px; }
    """
    return f"""<template>
  <style>#root {{ position:absolute; inset:0; }} {css}</style>
  <div id="root" data-composition-id="captions" data-width="{W}" data-height="{H}">
{groups}  </div>
  <script>
    const tl = gsap.timeline({{ paused: true }});
{js}    window.__timelines["captions"] = tl;
  </script>
</template>
"""


# ----------------------------------------------------------------------- main
def media_len(path):
    r = subprocess.run([ffmpeg(), "-hide_banner", "-i", str(path)], capture_output=True, text=True)
    m = re.search(r"Duration: (\d+):(\d+):([\d.]+)", r.stderr)
    return int(m[1]) * 3600 + int(m[2]) * 60 + float(m[3]) if m else 0.5


def ffmpeg():
    import imageio_ffmpeg
    return imageio_ffmpeg.get_ffmpeg_exe()


def main():
    meta, qa = load("edit_meta.json"), load("qa_report.json")
    script, story, facts = load("script.json"), load("storyboard.json"), load("facts.json")
    run_id = qa["run_id"]
    brief = yaml.safe_load(open(ROOT / "briefs" / f"{qa['brief']}.yaml", encoding="utf-8"))
    logs = [json.loads(l) for l in (ROOT / "logs/run_log.jsonl").read_text(encoding="utf-8").splitlines()
            if l.strip() and f'"{run_id}"' in l]
    agg = {}
    for r in logs:
        a = agg.setdefault(r["agent"], {"n": 0, "t": 0.0})
        a["n"] += 1
        a["t"] += r["latency_s"]

    # assets
    for sub in ("fonts", "img", "frames", "audio", "sfx"):
        (COMP / "assets" / sub).mkdir(parents=True, exist_ok=True)
    shutil.copy(ROOT / "assets/fonts/Archivo[wdth,wght].ttf", COMP / "assets/fonts/Archivo.ttf")
    for old in (COMP / "assets/fonts").glob("InstrumentSerif*"):
        old.unlink()
    shutil.copy(ROOT / "docs/screenshots/frontend_hero.png", COMP / "assets/img/dashboard.png")
    frames = []
    for s, p in meta["frames"].items():
        if s != story[-1]["shot_id"]:
            shutil.copy(ROOT / p, COMP / "assets/frames" / Path(p).name)
            frames.append(Path(p).name)
    subprocess.run([ffmpeg(), "-y", "-v", "error", "-i", str(ROOT / meta["final"]), "-vn", "-ac", "2", "-ar", "48000",
                    str(COMP / "assets/audio/mix.wav")], check=True)

    ctx = {"meta": meta, "qa": qa, "brief": brief, "logs": logs, "agg": agg, "run_id": run_id, "facts": facts,
           "story": story, "frames": frames, "n_facts": sum(f["verified"] for f in facts),
           "spent": sum(r["cost_inr"] for r in logs), "sfx": []}
    hosts = ""
    style_of = {s["shot_id"]: s["style"] for s in story}
    for i, seg in enumerate(meta["timeline"]):
        sid = f"s{i + 1:02d}"
        style = style_of.get(seg["shot"], "endcard")
        body, css, js = BUILDERS.get(style, sc_fact)(sid, seg, ctx)
        (COMP / "compositions" / f"{sid}.html").write_text(scene_file(sid, body, css, js), encoding="utf-8")
        dur = seg["end"] - seg["start"]
        hosts += f"""      <div id="{sid}" data-composition-id="{sid}" data-composition-src="compositions/{sid}.html" data-start="{seg['start']:.3f}" data-duration="{dur:.3f}" data-track-index="1" data-track-kind="graphics" data-width="{W}" data-height="{H}" style="z-index:{2 + i};"></div>\n"""

    total = meta["duration_s"]
    cap_end = meta["timeline"][-1]["start"]
    (COMP / "compositions/captions.html").write_text(captions_file(meta, total), encoding="utf-8")
    hosts += f"""      <div id="captions" data-composition-id="captions" data-composition-src="compositions/captions.html" data-start="0" data-duration="{cap_end:.3f}" data-track-index="2" data-track-kind="captions" data-width="{W}" data-height="{H}" style="z-index:50;"></div>\n"""

    audio = f"""      <audio id="mix" class="clip" data-start="0" data-duration="{total:.3f}" data-track-index="10" data-volume="1" src="assets/audio/mix.wav"></audio>\n"""
    for k, (rel, t, vol) in enumerate(sorted(ctx["sfx"], key=lambda x: x[1])):
        src = SFX_SRC / rel
        if not src.exists():
            continue
        dst = COMP / "assets/sfx" / rel.replace("/", "_")
        shutil.copy(src, dst)
        audio += f"""      <audio id="sfx{k:02d}" class="clip" data-start="{max(0, t):.3f}" data-duration="{media_len(dst):.2f}" data-track-index="{11 + k}" data-volume="{vol}" src="assets/sfx/{dst.name}"></audio>\n"""

    index = f"""<!doctype html>
<html lang="en" data-resolution="portrait">
  <head>
    <meta charset="UTF-8" />
    <meta name="viewport" content="width={W}, height={H}" />
    <script src="assets/vendor/gsap.min.js"></script>
    <style>
      * {{ margin: 0; padding: 0; box-sizing: border-box; }}
      html, body {{ width: {W}px; height: {H}px; overflow: hidden; background: #ede9e0; }}
      #ground {{ position: absolute; inset: 0; background:
          url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='240' height='240'%3E%3Cfilter id='n'%3E%3CfeTurbulence type='fractalNoise' baseFrequency='.8' numOctaves='3' stitchTiles='stitch'/%3E%3CfeColorMatrix values='0 0 0 0 .55  0 0 0 0 .52  0 0 0 0 .47  0 0 0 .16 0'/%3E%3C/filter%3E%3Crect width='100%25' height='100%25' filter='url(%23n)'/%3E%3C/svg%3E"), #ede9e0; }}
    </style>
  </head>
  <body>
    <div id="root" data-composition-id="main" data-start="0" data-duration="{total:.3f}" data-width="{W}" data-height="{H}">
      <div id="ground" class="clip" data-start="0" data-duration="{total:.3f}" data-track-index="0" style="z-index:0;"></div>
{hosts}{audio}    </div>
    <script>
      const tl = gsap.timeline({{ paused: true }});
      window.__timelines["main"] = tl;
    </script>
  </body>
</html>
"""
    (COMP / "index.html").write_text(index, encoding="utf-8")
    print(f"composition written: {len(meta['timeline'])} scenes, {len(meta['captions'])} caption groups, "
          f"{len(ctx['sfx'])} sfx, {total:.2f}s")


if __name__ == "__main__":
    main()
