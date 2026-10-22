"""Configurable LLM wrapper used by the text agents.

Provider is chosen with LLM_PROVIDER (offline | anthropic | openai | ollama).
`offline` runs a deterministic, seeded template model locally (Rs 0) so the
whole pipeline reproduces bit-for-bit without keys. Any hosted call that fails
falls back to the offline model and the fallback is logged, never hidden.
Every call - hosted or offline - goes through common.log_call."""
from __future__ import annotations

import json
import os
import re
import time
import urllib.request
from pathlib import Path
from typing import Callable, Optional

from .common import DIRS, RunContext, est_tokens, log_call, price

DEFAULT_MODELS = {
    "offline": "offline-template",
    "anthropic": "claude-haiku-5-5",
    "openai": "gpt-4o-mini",
    "ollama": "qwen2.5:7b-instruct",
}


def load_prompt(prompt_id: str) -> tuple[str, str]:
    """prompts/<id>.md holds a SYSTEM block and a USER block separated by '---'."""
    text = (DIRS["prompts"] / f"{prompt_id}.md").read_text(encoding="utf-8")
    body = re.sub(r"^<!--.*?-->\s*", "", text, flags=re.S)
    system, _, user = body.partition("\n---\n")
    return system.replace("SYSTEM:", "", 1).strip(), user.replace("USER:", "", 1).strip()


class LLM:
    def __init__(self, seed: int):
        self.provider = os.getenv("LLM_PROVIDER", "offline").lower()
        self.model = os.getenv("LLM_MODEL") or DEFAULT_MODELS.get(self.provider, "offline-template")
        self.seed = seed

    # ------------------------------------------------------------------ public
    def complete(self, ctx: RunContext, *, agent: str, prompt_id: str, variables: dict,
                 offline: Callable[[], str], output_path: Optional[Path] = None) -> str:
        system, user_t = load_prompt(prompt_id)
        user = user_t
        for k, v in variables.items():  # plain substitution: prompts contain literal JSON braces
            user = user.replace("{" + k + "}", str(v))
        t0 = time.perf_counter()
        provider, model, status = self.provider, self.model, "ok"
        in_tok = est_tokens(system + user)
        out_text = None
        if provider != "offline":
            try:
                out_text, in_tok, out_tok = self._hosted(system, user)
            except Exception as exc:  # network / key / quota -> deterministic fallback
                status = f"fallback-offline ({type(exc).__name__})"
                provider, model = "offline", DEFAULT_MODELS["offline"]
        if out_text is None:
            provider, model = "offline", DEFAULT_MODELS["offline"]
            out_text = offline()
            out_tok = est_tokens(out_text)
        if output_path is not None:
            output_path.parent.mkdir(parents=True, exist_ok=True)
            output_path.write_text(out_text, encoding="utf-8")
        log_call(ctx, agent=agent, tool="llm", provider=provider, model=model, prompt_id=prompt_id,
                 input_tokens=in_tok, output_tokens=out_tok, cost_inr=price(model, in_tok, out_tok),
                 latency_s=time.perf_counter() - t0, status=status, output_path=output_path)
        return out_text

    # ----------------------------------------------------------------- hosted
    def _hosted(self, system: str, user: str):
        if self.provider == "anthropic":
            body = {"model": self.model, "max_tokens": 1500, "temperature": 0.4,
                    "system": system, "messages": [{"role": "user", "content": user}]}
            req = urllib.request.Request(
                "https://api.anthropic.com/v1/messages", data=json.dumps(body).encode(),
                headers={"x-api-key": os.environ["ANTHROPIC_API_KEY"], "content-type": "application/json",
                         "anthropic-version": "2023-06-01"})
            data = json.loads(urllib.request.urlopen(req, timeout=60).read())
            return (data["content"][0]["text"], data["usage"]["input_tokens"],
                    data["usage"]["output_tokens"])
        base = (os.getenv("OLLAMA_BASE_URL", "http://localhost:11434") + "/v1"
                if self.provider == "ollama" else "https://api.openai.com/v1")
        body = {"model": self.model, "temperature": 0.4, "seed": self.seed,
                "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}]}
        req = urllib.request.Request(
            base + "/chat/completions", data=json.dumps(body).encode(),
            headers={"Authorization": f"Bearer {os.getenv('OPENAI_API_KEY', 'ollama')}",
                     "content-type": "application/json"})
        data = json.loads(urllib.request.urlopen(req, timeout=120).read())
        usage = data.get("usage", {})
        text = data["choices"][0]["message"]["content"]
        return text, usage.get("prompt_tokens", est_tokens(system + user)), \
            usage.get("completion_tokens", est_tokens(text))


def extract_json(text: str):
    """Hosted models sometimes wrap JSON in prose or fences; pull the first object/array."""
    m = re.search(r"(\{.*\}|\[.*\])", text, flags=re.S)
    return json.loads(m.group(1) if m else text)
