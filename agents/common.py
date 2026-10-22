"""Shared plumbing for every agent: paths, run context, schemas and the
logging wrapper that writes one record per model/tool call to
logs/run_log.jsonl and a cost roll-up row to logs/cost_report.csv."""
from __future__ import annotations

import csv
import hashlib
import json
import os
import time
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import List, Optional

import yaml
from pydantic import BaseModel, Field

ROOT = Path(__file__).resolve().parent.parent
DIRS = {name: ROOT / name for name in
        ("briefs", "agents", "prompts", "data", "assets", "outputs", "logs", "docs", "frontend")}
RUN_LOG = DIRS["logs"] / "run_log.jsonl"
COST_CSV = DIRS["logs"] / "cost_report.csv"
INTERVENTIONS = DIRS["logs"] / "interventions.md"
FONTS = DIRS["assets"] / "fonts"

COST_HEADER = ["ts", "run_id", "stage", "provider", "model", "tool", "units",
               "input_tokens", "output_tokens", "cost_inr", "latency_s", "status"]

# INR per 1M tokens (input, output). Local / offline models are free but still logged.
PRICE_INR_PER_MTOK = {
    "offline-template": (0.0, 0.0),
    "claude-haiku-5-5": (85.0, 425.0),
    "claude-sonnet-5-5": (255.0, 1275.0),
    "gpt-4o-mini": (13.0, 51.0),
    "ollama": (0.0, 0.0),
}
TOTAL_BUDGET_INR = 500.0


# --------------------------------------------------------------------- schemas
class Brief(BaseModel):
    id: str
    category: str
    topic: str
    audience: str
    format: str = "video_9x16"
    duration_s: int = 45
    tone: str = "professional"
    language: str = "English"
    must_include: List[str] = Field(default_factory=list)
    must_avoid: List[str] = Field(default_factory=list)
    cta: str


class Fact(BaseModel):
    id: str
    claim: str
    source: str
    page: int
    score: float
    query: str
    tags: List[str] = Field(default_factory=list)
    verified: bool = True


class ScriptLine(BaseModel):
    id: str
    key: str = ""                # bank key (hook, lab, rag, ... cta)
    role: str                    # hook | body | cta
    text: str
    fact_ids: List[str] = Field(default_factory=list)
    priority: int = 5            # lower = more important, dropped last
    est_start: float = 0.0
    est_end: float = 0.0


class Shot(BaseModel):
    shot_id: str
    role: str
    vo: str
    on_screen_text: str
    visual: str
    style: str
    duration_est: float
    asset_source: str = "generated"
    fact_ids: List[str] = Field(default_factory=list)


# ------------------------------------------------------------------- run state
@dataclass
class RunContext:
    brief: Brief
    seed: int
    team_id: str
    run_id: str
    work: Path
    started: float = field(default_factory=time.time)
    spent_inr: float = 0.0
    calls: int = 0

    @property
    def final_stem(self) -> str:
        return f"{self.team_id}_{self.brief.id}_final"


def load_brief(path: str | Path) -> Brief:
    with open(path, "r", encoding="utf-8") as fh:
        return Brief(**yaml.safe_load(fh))


def next_run_id(team_id: str, brief_id: str) -> str:
    prefix = f"{team_id}-{brief_id}-"
    n = 0
    if RUN_LOG.exists():
        for line in RUN_LOG.read_text(encoding="utf-8").splitlines():
            try:
                rid = json.loads(line).get("run_id", "")
            except json.JSONDecodeError:
                continue
            if rid.startswith(prefix):
                n = max(n, int(rid[len(prefix):] or 0))
    return f"{prefix}{n + 1:02d}"


def write_json(path: Path, obj) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    if isinstance(obj, BaseModel):
        obj = obj.model_dump()
    path.write_text(json.dumps(obj, indent=2, ensure_ascii=False, default=_jsonable), encoding="utf-8")
    return path


def _jsonable(o):
    if isinstance(o, BaseModel):
        return o.model_dump()
    if isinstance(o, Path):
        return str(o.relative_to(ROOT)) if o.is_absolute() and ROOT in o.parents else str(o)
    raise TypeError(type(o))


def sha256(path: Optional[Path]) -> Optional[str]:
    if not path or not Path(path).exists() or Path(path).is_dir():
        return None
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def rel(path: Optional[Path]) -> Optional[str]:
    if path is None:
        return None
    p = Path(path).resolve()
    try:
        return p.relative_to(ROOT).as_posix()
    except ValueError:
        return str(p)


def est_tokens(text: str) -> int:
    return max(1, round(len(text) / 4))


def price(model: str, in_tok: int, out_tok: int) -> float:
    pin, pout = PRICE_INR_PER_MTOK.get(model, (0.0, 0.0))
    return round(in_tok * pin / 1e6 + out_tok * pout / 1e6, 4)


# --------------------------------------------------------------------- logging
def log_call(ctx: RunContext, *, agent: str, tool: str, model: str = "-", provider: str = "local",
             prompt_id: str = "-", input_tokens: int = 0, output_tokens: int = 0, units: str = "",
             cost_inr: float = 0.0, latency_s: float = 0.0, status: str = "ok",
             output_path: Optional[Path] = None, human_intervention: bool = False, note: str = "") -> dict:
    rec = {
        "ts": datetime.now().isoformat(timespec="seconds"),
        "run_id": ctx.run_id,
        "agent": agent,
        "tool": tool,
        "model": model,
        "prompt_id": prompt_id,
        "input_tokens": int(input_tokens),
        "output_tokens": int(output_tokens),
        "cost_inr": round(float(cost_inr), 4),
        "latency_s": round(float(latency_s), 3),
        "status": status,
        "output_path": rel(output_path),
        "output_sha256": sha256(output_path),
        "human_intervention": human_intervention,
    }
    if note:
        rec["note"] = note
    RUN_LOG.parent.mkdir(parents=True, exist_ok=True)
    with open(RUN_LOG, "a", encoding="utf-8") as fh:
        fh.write(json.dumps(rec, ensure_ascii=False) + "\n")

    new_file = not COST_CSV.exists() or COST_CSV.stat().st_size == 0
    with open(COST_CSV, "a", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        if new_file:
            w.writerow(COST_HEADER)
        w.writerow([rec["ts"], ctx.run_id, agent, provider, model, tool,
                    units or f"{input_tokens + output_tokens} tok", input_tokens, output_tokens,
                    rec["cost_inr"], rec["latency_s"], status])
    ctx.spent_inr += rec["cost_inr"]
    ctx.calls += 1
    return rec


@contextmanager
def traced(ctx: RunContext, agent: str, tool: str, **kw):
    """Time a tool call and log it. The body may update the yielded dict
    (output_path, units, status, tokens...) before it is written."""
    info = dict(kw)
    t0 = time.perf_counter()
    try:
        yield info
    except Exception as exc:  # log the failure, then re-raise for the orchestrator
        info["status"] = f"error: {type(exc).__name__}: {exc}"[:200]
        log_call(ctx, agent=agent, tool=tool, latency_s=time.perf_counter() - t0, **info)
        raise
    log_call(ctx, agent=agent, tool=tool, latency_s=time.perf_counter() - t0, **info)


def say(agent: str, msg: str) -> None:
    print(f"  [{agent:<13}] {msg}", flush=True)


def load_env() -> None:
    env = ROOT / ".env"
    if env.exists():
        for line in env.read_text(encoding="utf-8").splitlines():
            if "=" in line and not line.strip().startswith("#"):
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip())
