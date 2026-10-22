"""AgentReel G04 - one-command multi-agent reel pipeline.

    python run.py --brief briefs/C05.yaml --seed 42

Brief -> Planner -> Researcher (RAG) -> Scriptwriter <-> Critic(script gate)
      -> Storyboarder -> Asset Generator -> Editor -> Critic(video gate)
      -> [fail: route back, max 3 loops | pass: human checkpoint -> export]
      -> frontend data, agent graph, process report.
"""
from __future__ import annotations

import argparse
import json
import random
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

import numpy as np

from agents import asset_generator, critic, editor, planner, researcher, scriptwriter, storyboarder
from agents.common import (DIRS, INTERVENTIONS, ROOT, RUN_LOG, RunContext, load_brief, load_env, log_call,
                           next_run_id, say, write_json)
from agents.graph import draw_agent_graph
from agents.llm import LLM

MAX_LOOPS = 3


def checkpoint(ctx: RunContext, meta: dict, auto: bool) -> bool:
    """Mandatory pre-export human review for Category A/C briefs (does not count
    toward the 5-intervention limit). Recorded in logs/interventions.md."""
    if ctx.brief.id[0] not in "AC":
        return True
    if auto or not sys.stdin.isatty():
        decision, who = "approved", "auto-approved (--auto-approve / non-interactive run)"
    else:
        print(f"\n  >>> Human checkpoint: review {meta['final']} (and {meta['srt']}).")
        try:
            ans = input("  >>> Approve export? [Y/n] ").strip().lower()
            decision, who = ("rejected", "reviewer") if ans.startswith("n") else ("approved", "reviewer")
        except EOFError:  # stdin claims to be a TTY but is closed (IDE / CI shells)
            decision, who = "approved", "auto-approved (no interactive stdin)"
    with open(INTERVENTIONS, "a", encoding="utf-8") as fh:
        fh.write(f"| {datetime.now():%H:%M} | {ctx.run_id} | Critic -> export | Pre-export review checkpoint: "
                 f"{decision} | Mandatory Category {ctx.brief.id[0]} review ({who}); not counted as an "
                 f"intervention |\n")
    log_call(ctx, agent="human", tool="checkpoint", status=decision, note=who)
    return decision == "approved"


def ensure_interventions_header():
    if not INTERVENTIONS.exists() or not INTERVENTIONS.read_text(encoding="utf-8").strip():
        INTERVENTIONS.write_text(
            "# Human interventions log\n\n"
            "Every human change during a run is one row (limit: 5 per Live Run). Mandatory review\n"
            "checkpoints are recorded too but marked as not counted.\n\n"
            "| Time | Run | Stage / agent | What the human changed | Reason |\n"
            "|---|---|---|---|---|\n", encoding="utf-8")


def main(argv=None):
    ap = argparse.ArgumentParser(description="AgentReel multi-agent video pipeline")
    ap.add_argument("--brief", required=True, help="path to briefs/<id>.yaml")
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--team", default=None, help="team id (default from .env TEAM_ID or G04)")
    ap.add_argument("--auto-approve", action="store_true", help="skip the interactive export checkpoint")
    ap.add_argument("--no-report", action="store_true", help="skip generate_report.py")
    args = ap.parse_args(argv)

    load_env()
    import os
    random.seed(args.seed)
    np.random.seed(args.seed)
    brief = load_brief(args.brief)
    team = args.team or os.getenv("TEAM_ID", "G04")
    ctx = RunContext(brief=brief, seed=args.seed, team_id=team, run_id=next_run_id(team, brief.id),
                     work=DIRS["outputs"])
    for d in DIRS.values():
        d.mkdir(exist_ok=True)
    ensure_interventions_header()
    llm = LLM(args.seed)
    t_start = time.time()
    print(f"\n== AgentReel | run {ctx.run_id} | brief {brief.id}: {brief.topic}")
    print(f"   LLM provider: {llm.provider} ({llm.model}) | seed {args.seed}\n")
    log_call(ctx, agent="orchestrator", tool="start", note=f"brief={args.brief} seed={args.seed} "
                                                           f"provider={llm.provider}")

    history = []
    plan = planner.run(ctx, llm)
    facts = researcher.run(ctx, llm)

    # ---- script gate: Scriptwriter <-> Critic (max 3 loops)
    feedback, version = None, 1
    for loop in range(1, MAX_LOOPS + 1):
        lines = scriptwriter.run(ctx, llm, plan, facts, feedback=feedback, version=version)
        rep = critic.review_script(ctx, plan, lines, facts)
        history.append({"loop": loop, **rep})
        if rep["status"] == "pass":
            break
        if "researcher" in rep["route_to"]:
            facts = researcher.run(ctx, llm)
        feedback = {"over_words": rep["over_words"],
                    "failed": [c["id"] for c in rep["checks"] if not c["passed"]]}
        version += 1
    else:
        raise SystemExit("script gate failed after 3 loops - see outputs/qa_report.json")

    shots = storyboarder.run(ctx, llm, plan, lines)

    # ---- video gate: assets -> edit -> Critic (max 3 loops)
    rate = int(plan.get("tts_rate", "+0%").strip("%"))
    for loop in range(1, MAX_LOOPS + 1):
        assets = asset_generator.run(ctx, shots, rate=f"{rate:+d}%")
        meta = editor.run(ctx, shots, assets)
        rep = critic.review_video(ctx, plan, meta)
        history.append({"loop": loop, **rep})
        if rep["status"] == "pass":
            break
        dur = rep["probe"]["duration"]
        if dur > min(60, brief.duration_s * 1.2):
            rate += 8   # self-repair: speak faster rather than cut grounded lines
        elif dur < max(30, brief.duration_s * 0.8):
            rate -= 8
        say("orchestrator", f"video gate failed -> retry with TTS rate {rate:+d}%")
    else:
        write_json(DIRS["outputs"] / "qa_report.json", {"run_id": ctx.run_id, "status": "fail", "history": history})
        raise SystemExit("video gate failed after 3 loops - see outputs/qa_report.json")

    approved = checkpoint(ctx, meta, args.auto_approve)
    elapsed = time.time() - t_start
    qa = {"run_id": ctx.run_id, "brief": brief.id, "status": "pass" if approved else "rejected",
          "final": meta["final"], "srt": meta["srt"], "duration_s": rep["probe"]["duration"],
          "lufs": rep["lufs"], "probe": rep["probe"], "loops": {
              "script": sum(1 for h in history if h["gate"] == "script"),
              "video": sum(1 for h in history if h["gate"] == "video")},
          "history": history, "elapsed_s": round(elapsed, 1), "spent_inr": round(ctx.spent_inr, 4),
          "llm_provider": llm.provider, "seed": args.seed}
    write_json(DIRS["outputs"] / "qa_report.json", qa)
    log_call(ctx, agent="critic", tool="qa_report", output_path=DIRS["outputs"] / "qa_report.json",
             status=qa["status"])

    draw_agent_graph(DIRS["docs"] / "agent_graph.png")
    export_frontend(ctx)
    log_call(ctx, agent="orchestrator", tool="finish", latency_s=time.time() - t_start,
             note=f"status={qa['status']}")
    export_frontend(ctx)  # once more so the finish record is in the dashboard too

    if not args.no_report:
        subprocess.run([sys.executable, str(ROOT / "generate_report.py"), "--run-id", ctx.run_id], check=True)
    print(f"\n== done in {elapsed:.0f}s | {meta['final']} | QA {qa['status'].upper()} | "
          f"spent Rs {ctx.spent_inr:.2f} of 500 | open frontend/index.html\n")


def export_frontend(ctx: RunContext):
    """Bundle this run's artefacts into frontend/data.js (works from file://)."""
    out = DIRS["outputs"]
    load = lambda p: json.loads((out / p).read_text(encoding="utf-8")) if (out / p).exists() else None
    logs = [json.loads(l) for l in RUN_LOG.read_text(encoding="utf-8").splitlines()
            if l.strip() and json.loads(l)["run_id"] == ctx.run_id]
    data = {"run_id": ctx.run_id, "brief": ctx.brief.model_dump(), "plan": load("plan.json"),
            "facts": load("facts.json"), "script": load("script.json"), "storyboard": load("storyboard.json"),
            "edit": load("edit_meta.json"), "qa": load("qa_report.json"),
            "retrieval": load("retrieval_test.json"), "logs": logs,
            "interventions": INTERVENTIONS.read_text(encoding="utf-8"),
            "generated": datetime.now().isoformat(timespec="seconds")}
    (DIRS["frontend"] / "data.js").write_text("window.AGENTREEL = " + json.dumps(data, ensure_ascii=False)
                                              + ";\n", encoding="utf-8")


if __name__ == "__main__":
    main()
