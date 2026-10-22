"""Builds docs/process_report.pdf (3 pages) from the run's logs and outputs:
logs/cost_report.csv, logs/interventions.md, outputs/*.json, docs/agent_graph.png,
a storyboard contact sheet and a headless-browser screenshot of the frontend.

    python generate_report.py [--run-id G04-C05-03]
"""
from __future__ import annotations

import argparse
import csv
import json
import shutil
import subprocess
import time
from collections import defaultdict
from datetime import datetime
from pathlib import Path

from fpdf import FPDF
from PIL import Image

ROOT = Path(__file__).resolve().parent
OUT, DOCS, LOGS, FONTS = ROOT / "outputs", ROOT / "docs", ROOT / "logs", ROOT / "assets" / "fonts"
# two-ink riso print: everything is blue except one scarlet accent per block
INK = MUTE = LINE = (38, 58, 140)
RED = AMBER = (232, 65, 44)
PAPER = (240, 236, 228)
ARCH = str(FONTS / "Archivo[wdth,wght].ttf")
TEAM = [("Harshit Modi", "16014223039"), ("Mohammed Zamee Sheikh", "16014223054"), ("Eashan Salian", "16014223035")]
BROWSERS = [r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
            r"C:\Program Files\Google\Chrome\Application\chrome.exe",
            "/usr/bin/chromium", "/usr/bin/google-chrome",
            "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"]


def load(name):
    p = OUT / name
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else None


# ------------------------------------------------------------------ figures
def contact_sheet(edit, path: Path):
    frames = [ROOT / f for f in edit["frames"].values()]
    tw, th = 216, 384
    cols = min(len(frames), 6)
    rows = (len(frames) + cols - 1) // cols
    sheet = Image.new("RGB", (cols * tw + (cols + 1) * 12, rows * th + (rows + 1) * 12), (38, 58, 140))
    for i, f in enumerate(frames):
        im = Image.open(f).convert("RGB").resize((tw, th))
        sheet.paste(im, (12 + (i % cols) * (tw + 12), 12 + (i // cols) * (th + 12)))
    sheet.save(path, quality=88)
    return path


def screenshot_frontend(path: Path, height=3400):
    exe = next((b for b in BROWSERS if Path(b).exists()), None) or shutil.which("chromium")
    if not exe:
        return None
    url = (ROOT / "frontend" / "index.html").resolve().as_uri()
    subprocess.run([exe, "--headless=new", "--disable-gpu", "--hide-scrollbars", "--allow-file-access-from-files",
                    f"--screenshot={path}", f"--window-size=1440,{height}", "--virtual-time-budget=6000",
                    "--force-device-scale-factor=1", url], capture_output=True, timeout=120)
    for _ in range(40):  # the browser can return before the PNG is flushed
        if path.exists() and path.stat().st_size > 0:
            time.sleep(0.5)
            return path
        time.sleep(0.25)
    return None


# --------------------------------------------------------------------- PDF
class Report(FPDF):
    def __init__(self, meta):
        super().__init__(format="A4")
        self.meta = meta
        self.set_margins(14, 14, 14)
        self.set_auto_page_break(True, 14)
        self.add_font("plex", "", ARCH, variations={"wght": 420, "wdth": 100})
        self.add_font("plex", "B", ARCH, variations={"wght": 800, "wdth": 100})
        self.add_font("plex", "I", ARCH, variations={"wght": 420, "wdth": 92})
        self.add_font("plexsb", "", ARCH, variations={"wght": 700, "wdth": 100})
        self.add_font("mono", "", str(FONTS / "IBMPlexMono-Regular.ttf"))
        self.add_font("serif", "", ARCH, variations={"wght": 900, "wdth": 118})   # display: black, expanded
        self.add_font("serif", "I", ARCH, variations={"wght": 600, "wdth": 100})

    def header(self):
        self.set_fill_color(*PAPER)
        self.rect(0, 0, 210, 297, "F")
        if self.page_no() > 1:
            self.set_font("plexsb", "", 7)
            self.set_text_color(*MUTE)
            self.set_draw_color(*INK)
            self.set_line_width(0.3)
            self.line(14, 12, 196, 12)
            self.set_line_width(0.2)
            self.set_xy(14, 7)
            self.cell(0, 4, f"AGENTREEL · {self.meta['team']} · BRIEF {self.meta['brief']} · RUN {self.meta['run_id']}")
            self.set_xy(14, 7)
            self.cell(0, 4, f"PROCESS REPORT · p.{self.page_no()}", align="R")
            self.set_y(14)

    def footer(self):
        self.set_y(-10)
        self.set_font("plexsb", "", 6.5)
        self.set_text_color(*MUTE)
        self.cell(0, 4, "Created with AI agents — LY Agentic AI Lab · K J Somaiya School of Engineering", align="C")

    def h2(self, num, title):
        self.ln(2)
        self.set_font("plexsb", "", 7.5)
        self.set_text_color(*RED)
        self.cell(0, 4, num, new_x="LMARGIN", new_y="NEXT")
        self.set_font("serif", "", 15)
        self.set_text_color(*INK)
        self.cell(0, 8, title, new_x="LMARGIN", new_y="NEXT")
        self.set_draw_color(*LINE)
        self.set_line_width(0.7)
        self.line(14, self.get_y() + 0.5, 196, self.get_y() + 0.5)
        self.set_line_width(0.2)
        self.ln(2.5)

    def para(self, text, size=8.8, color=INK, h=4.3, style=""):
        self.set_font("plex", style, size)
        self.set_text_color(*color)
        self.multi_cell(0, h, text, new_x="LMARGIN", new_y="NEXT", markdown=True)

    def bullet(self, text, size=8.6):
        self.set_font("plex", "", size)
        self.set_text_color(*RED)
        x = self.get_x()
        self.set_fill_color(*RED)
        self.rect(self.get_x() + 0.3, self.get_y() + 1.4, 1.6, 1.6, "F")
        self.cell(4, 4.2, "")
        self.set_text_color(*INK)
        self.multi_cell(0, 4.2, text, new_x="LMARGIN", new_y="NEXT", markdown=True)
        self.set_x(x)


def build(run_id=None):
    qa, plan, edit, script = load("qa_report.json"), load("plan.json"), load("edit_meta.json"), load("script.json")
    facts, story = load("facts.json") or [], load("storyboard.json") or []
    run_id = run_id or qa["run_id"]
    brief_id = qa["brief"]
    rows = [r for r in csv.DictReader(open(LOGS / "cost_report.csv", encoding="utf-8")) if r["run_id"] == run_id]
    iv_text = (LOGS / "interventions.md").read_text(encoding="utf-8")
    iv_rows = [l for l in iv_text.splitlines() if l.startswith("| ") and not l.startswith("| Time")
               and run_id in l]
    counted = [l for l in iv_rows if "not counted" not in l]
    import yaml
    brief = yaml.safe_load(open(ROOT / "briefs" / f"{brief_id}.yaml", encoding="utf-8"))

    shots_dir = DOCS / "screenshots"
    shots_dir.mkdir(parents=True, exist_ok=True)
    sheet = contact_sheet(edit, shots_dir / "storyboard_sheet.jpg")
    (shots_dir / "frontend_dashboard.png").unlink(missing_ok=True)
    dash = screenshot_frontend(shots_dir / "frontend_dashboard.png")
    if dash:
        im = Image.open(dash)
        im.crop((0, 0, im.width, min(im.height, 1000))).save(shots_dir / "frontend_hero.png")
        im.crop((0, 1450, im.width, min(im.height, 2420))).save(shots_dir / "frontend_qa.png")

    stage = defaultdict(lambda: {"calls": 0, "tin": 0, "tout": 0, "cost": 0.0, "t": 0.0, "models": set()})
    for r in rows:
        s = stage[r["stage"]]
        s["calls"] += 1
        s["tin"] += int(r["input_tokens"])
        s["tout"] += int(r["output_tokens"])
        s["cost"] += float(r["cost_inr"])
        if r["stage"] != "orchestrator":  # its 'finish' record is the whole run's wall-clock
            s["t"] += float(r["latency_s"])
        if r["model"] not in ("-", ""):
            s["models"].add(r["model"])
    total_cost = sum(s["cost"] for s in stage.values())

    meta = {"team": run_id.split("-")[0], "brief": brief_id, "run_id": run_id}
    pdf = Report(meta)
    pdf.set_draw_color(*INK)

    # ================================================================ page 1
    pdf.add_page()
    pdf.set_xy(14, 9)
    pdf.set_font("plexsb", "", 7.5)
    pdf.set_text_color(*INK)
    pdf.cell(0, 4, "K J Somaiya School of Engineering · LY Agentic AI Laboratory · Somaiya AgentReel Challenge")
    pdf.set_font("serif", "", 50)
    pdf.set_text_color(*RED)               # scarlet plate, off register
    pdf.set_xy(14.9, 15.6)
    pdf.cell(0, 20, "AGENTREEL")
    pdf.set_text_color(*INK)
    pdf.set_xy(14, 15)
    pdf.cell(0, 20, "AGENTREEL")
    pdf.set_fill_color(*INK)
    pdf.rect(14, 37, 182, 1.6, "F")
    pdf.set_xy(14, 40)
    pdf.set_font("serif", "", 13)
    pdf.cell(0, 7, "Process report")
    pdf.set_xy(14, 47)
    pdf.set_font("plexsb", "", 9)
    pdf.cell(0, 5, f"Brief {brief_id}: {brief['topic']}")
    pdf.set_xy(14, 52.3)
    pdf.set_font("plexsb", "", 8)
    pdf.cell(0, 4, f"Team {meta['team']} (Group 4): " + " · ".join(f"{n} ({r})" for n, r in TEAM))
    pdf.set_xy(14, 56.6)
    pdf.set_font("plex", "", 7.2)
    pdf.cell(0, 4, f"Run {run_id} · seed {qa['seed']} · LLM {qa['llm_provider']} · "
                   f"{datetime.now():%d %b %Y} · L3 · python run.py --brief briefs/{brief_id}.yaml --seed {qa['seed']}")
    pdf.set_line_width(0.3)
    pdf.line(14, 61.5, 196, 61.5)
    pdf.set_line_width(0.2)

    kp = [(f"{qa['duration_s']:.1f}s", "duration (30–60)"), (f"{qa['lufs']:.1f}", "LUFS (target −14)"),
          (f"₹{total_cost:.2f}", "spend of ₹500"), (f"{qa['elapsed_s'] / 60:.1f} min", "wall-clock of 180"),
          (str(len(counted)), "interventions of 5"),
          (f"{sum(c['passed'] for h in qa['history'] if h['status'] == 'pass' for c in h['checks'])}/"
           f"{sum(len(h['checks']) for h in qa['history'] if h['status'] == 'pass')}", "QA rules passed")]
    pdf.set_y(65)
    w = 182 / len(kp)
    for i, (v, l) in enumerate(kp):
        x = 14 + i * w
        pdf.set_xy(x, 65)
        pdf.set_font("serif", "", 17)
        pdf.set_text_color(*(RED if i == 2 else INK))
        pdf.cell(w, 9, v)
        pdf.set_xy(x, 74)
        pdf.set_font("plexsb", "", 6.5)
        pdf.set_text_color(*MUTE)
        pdf.cell(w, 4, l)
    pdf.set_y(81)

    pdf.h2("01 — BRIEF INTERPRETATION & CREATIVE STRATEGY", "Show, don't claim")
    pdf.para(f"**Audience insight.** {plan['creative']['audience_insight']} The brief forbids exaggerated "
             f"placement figures and hallucinated statistics, so the reel sells capability with evidence "
             f"instead of outcomes: every sentence is traceable to the official LY Agentic AI Lab handout.")
    hooks = sorted(script.get("hooks", []), key=lambda h: -h["score"])
    others = "; ".join(f"\"{h['text']}\" {h['score']}" for h in hooks[1:])
    pdf.para(f"**Hook (0–3 s).** \"{script['lines'][0]['text']}\" — best of {len(hooks)} scored variants "
             f"(score {hooks[0]['score'] if hooks else '-'}; others: {others}). **Angle.** {plan['creative']['angle']} "
             f"**CTA.** \"{brief['cta']}\" on a 4 s end card with the AI-disclosure line.")
    pdf.para(f"**Must include** real lab infrastructure (the final-year Agentic AI Lab, local open models, "
             f"logged and costed runs) and real-world deployment skills (GitHub Pages / Hugging Face Spaces / "
             f"Streamlit Cloud) — both verified by Critic rules S6/S7.")

    pdf.h2("02 — AGENT GRAPH, FRAMEWORK & MODELS", "Seven agents, two critic gates")
    pdf.image(str(DOCS / "agent_graph.png"), x=14, w=182)
    pdf.ln(1.5)
    why = [
        f"**Planner** – turns the brief into plan.json: 9:16 spec, {plan['timing']['vo_s']} s of speech + {plan['timing']['end_card_s']:.0f} s end card, "
        f"{plan['word_budget']['max']}-word cap, ₹ and minute budgets per stage.",
        "**Researcher (RAG)** – PyMuPDF → LangChain splitter → ChromaDB with all-MiniLM-L6-v2; returns verbatim claims with source + page.",
        "**Scriptwriter** – A/B/C hooks scored for the 3-second rule; each body line is bound to fact ids and dropped by priority when over budget.",
        "**Storyboarder** – 6–12 face-free shots + end card with on-screen text and asset source. **Asset Generator** – Edge-TTS with word timings, procedural visuals, procedural music, manifest.csv.",
        "**Editor** – MoviePy: Ken Burns, cross-dissolves, karaoke captions in safe zones, ducked music, 2-pass loudnorm. **Critic** – 20 deterministic rules in two gates that route failures back (max 3 loops).",
    ]
    for t in why:
        pdf.bullet(t, 8.2)
    pdf.para("Framework: custom Python orchestrator (run.py) with pydantic schemas on every hand-off. Text agents "
             "use a provider-agnostic LLM wrapper (offline seeded template model by default — ₹0 and bit-for-bit "
             "reproducible; Claude / OpenAI / Ollama via LLM_PROVIDER). The Critic is intentionally not an LLM.",
             7.8, MUTE, 3.8)

    # ================================================================ page 2
    pdf.add_page()
    pdf.h2("03 — TIME & COST PER STAGE", f"₹{total_cost:.2f} spent of the ₹500 cap")
    cols = [("Stage", 30), ("Models / tools", 70), ("Calls", 14), ("Tokens in/out", 26), ("Time (s)", 20), ("Cost ₹", 22)]
    pdf.set_font("mono", "", 7)
    pdf.set_text_color(*MUTE)
    for name, cw in cols:
        pdf.cell(cw, 6, name.upper(), border="B", align="R" if name not in ("Stage", "Models / tools") else "L")
    pdf.ln()
    order = ["orchestrator", "planner", "researcher", "scriptwriter", "storyboarder", "asset_generator", "editor",
             "critic", "human"]
    tot_t = 0.0
    for st in sorted(stage, key=lambda s: order.index(s) if s in order else 99):
        s = stage[st]
        tot_t += s["t"]
        vals = [st, ", ".join(sorted(s["models"]))[:44], str(s["calls"]), f"{s['tin']}/{s['tout']}",
                "wall" if st == "orchestrator" else f"{s['t']:.1f}", f"{s['cost']:.2f}"]
        for (name, cw), v in zip(cols, vals):
            pdf.set_font("plex" if name in ("Stage",) else "mono", "", 7.6 if name != "Models / tools" else 6.8)
            pdf.set_text_color(*INK)
            pdf.cell(cw, 5.4, v, border="B", align="R" if name not in ("Stage", "Models / tools") else "L")
        pdf.ln()
    pdf.set_font("plexsb", "", 8)
    pdf.cell(100, 6, "Total")
    pdf.cell(14, 6, str(sum(s["calls"] for s in stage.values())), align="R")
    pdf.cell(26, 6, "", align="R")
    pdf.cell(20, 6, f"{tot_t:.1f}", align="R")  # sum of stage times; wall-clock is in the KPI row
    pdf.cell(22, 6, f"{total_cost:.2f}", align="R")
    pdf.ln(7)
    slow = max(((k, v) for k, v in stage.items() if k != "orchestrator"), key=lambda kv: kv[1]["t"])
    pdf.para(f"The most expensive stage in time is **{slow[0]}** ({slow[1]['t']:.0f} s — frame-by-frame PIL "
             f"compositing at 1080×1920×30 fps). It could be cut by rendering overlays with ffmpeg filters or "
             f"caching static layers per shot. Paid-API spend is ₹0 because text agents ran on the offline "
             f"model and TTS/embeddings are free; switching the Scriptwriter to Claude Haiku would cost roughly "
             f"₹1–2 per run at the logged token counts.", 8.4)

    pdf.h2("04 — CRITIC LOOP: WHAT FAILED, WHAT WAS FIXED", "Self-repair without a human")
    for h in qa["history"]:
        fails = [c for c in h["checks"] if not c["passed"]]
        label = f"{h['gate'].title()} gate · iteration {h['loop']} · {h['status'].upper()}"
        if fails:
            detail = "; ".join(f"{c['id']} {c['name']} ({c['detail']}) → {c['route_to']}" for c in fails)
        else:
            detail = f"all {len(h['checks'])} rules passed"
        pdf.bullet(f"**{label}** — {detail}", 8.4)
    if qa["loops"]["script"] > 1:
        pdf.para("The first draft wrote every grounded line it could (greedy coverage). The Critic measured it "
                 "against the planner's word budget and routed it back; the Scriptwriter dropped the "
                 "lowest-priority lines (priority 3–5: retrieval, orchestration, portfolio) while keeping must-include and hook/CTA lines, and v2 "
                 "passed all eight script rules — no human edit was needed.", 8.4)
    pdf.ln(1)
    pdf.set_font("mono", "", 7)
    pdf.set_text_color(*MUTE)
    pdf.cell(0, 5, "STORYBOARD → RENDERED FRAMES (EDITOR OUTPUT, ONE PER SHOT + END CARD)", new_x="LMARGIN",
             new_y="NEXT")
    pdf.image(str(sheet), x=14, w=182)

    # ================================================================ page 3
    pdf.add_page()
    pdf.h2("05 — FRONTEND & VERIFICATION", "The run, auditable at a glance")
    if dash:
        y0 = pdf.get_y()
        pdf.image(str(shots_dir / "frontend_hero.png"), x=14, y=y0, w=89)
        pdf.image(str(shots_dir / "frontend_qa.png"), x=107, y=y0, w=89)
        pdf.set_y(y0 + 89 * 1000 / 1440 + 2)
        pdf.para("frontend/index.html renders this run from frontend/data.js: brief card, live agent graph with "
                 "per-agent calls/time/₹, RAG facts with page citations, scored hooks, storyboard frames, both QA "
                 "gates, cost table and the raw run log.", 7.8, MUTE, 3.8)
    pdf.ln(1)
    p = qa["probe"]
    pdf.para(f"**Spec check (ffmpeg probe).** {p['width']}×{p['height']} · {p['fps']:.0f} fps · "
             f"{p['vcodec']} {p['profile']} {p['pix_fmt']} · {p['acodec']} {p['sr']} Hz {p['channels']} "
             f"{p['abitrate']} kb/s · {p['size_mb']} MB · {qa['lufs']:.1f} LUFS · {len(edit['captions'])} caption cues "
             f"(Archivo ExtraBold 60 px) · captions y={edit['layout']['caption']} inside the 250/350 px safe zones.", 8.4)
    pdf.para(f"**Grounding.** {len(facts)} facts retrieved ({sum(f['verified'] for f in facts)} verified); every "
             f"body line cites ≥1 fact id; numbers in the VO (3 hours, ₹500) are matched against facts.json by rule S4.", 8.4)

    if (ROOT / "brag-output" / "build_reel.py").exists():
        pdf.para("**Submission cut.** brag-output/build_reel.py turns this run's timeline, captions, logs and QA "
                 "report into a HyperFrames (HTML-to-video) composition that shows the real artefacts on screen; it "
                 "reuses the pipeline's VO + music mix, so the same .srt and the same QA numbers apply.", 8.4)
    final_checks = [c for g in ("script", "video")
                    for c in next(h for h in reversed(qa["history"]) if h["gate"] == g)["checks"]]
    pdf.ln(1)
    col_w, x0, y0 = 89, 14, pdf.get_y()
    half = (len(final_checks) + 1) // 2
    for i, c in enumerate(final_checks):
        x = x0 + (0 if i < half else col_w + 4)
        y = y0 + (i % half) * 4.6
        pdf.set_xy(x, y)
        pdf.set_font("mono", "", 6.8)
        pdf.set_text_color(*(INK if c["passed"] else RED))
        pdf.cell(9, 4.6, ("✓ " if c["passed"] else "✗ ") + c["id"])
        pdf.set_text_color(*INK)
        pdf.set_font("plex", "", 6.9)
        pdf.cell(col_w - 9, 4.6, f"{c['name']} — {c['detail']}"[:72])
    pdf.set_y(y0 + half * 4.6 + 1)

    pdf.h2("06 — HUMAN INTERVENTIONS", f"{len(counted)} counted · {len(iv_rows) - len(counted)} checkpoint")
    if iv_rows:
        for l in iv_rows:
            cells = [c.strip() for c in l.strip("|").split("|")]
            reason = cells[4].replace("--", "‑‑")
            pdf.bullet(f"**{cells[0]} · {cells[2].replace('->', '→')}** — {cells[3]} ({reason})", 8.2)
    else:
        pdf.para("None recorded for this run.", 8.4)
    pdf.para("To remove the checkpoint next time (L4), a second, independent critic (e.g. an LLM safety reviewer "
             "voting with the rule engine) would have to sign off Category A/C exports — the handout keeps this "
             "review mandatory, so we kept it.", 8.2, MUTE, 4.0)

    pdf.h2("07 — LIMITATIONS, ETHICS & NEXT STEPS", "What we would do with another week")
    for t in [
        "**Fact sheet.** No separate admissions fact sheet was supplied, so the only source is the official lab "
        "handout; this deliberately limits claims (no hardware specs, no placement data). The mock-fact fallback "
        "is marked unverified and is blocked by rule S3.",
        "**Visuals.** Official media-kit stills were unavailable; procedural, face-free visuals stand in "
        "(drop files into assets/official/ to replace them). No real person's face or voice is generated; the TTS "
        "voice is a stock synthetic voice.",
        "**Licensing & disclosure.** Fonts are SIL OFL, music is generated by the pipeline (CC0), every asset is in "
        "assets/manifest.csv; the end card carries \"Created with AI agents — LY Agentic AI Lab\".",
        "**Brand.** The end card uses a text wordmark until the official logo is provided (assets/official/logo.png "
        "is placed undistorted automatically).",
        "**Next.** Whisper-aligned captions, Hindi/Marathi auto-dub, multi-critic voting, and a hosted LLM "
        "scriptwriter with the same fact-id contract.",
    ]:
        pdf.bullet(t, 8.2)

    out = DOCS / "process_report.pdf"
    pdf.output(str(out))
    print(f"  [report       ] {out.relative_to(ROOT)} ({pdf.page} pages)")
    return out


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--run-id", default=None)
    build(ap.parse_args().run_id)
