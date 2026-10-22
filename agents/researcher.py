"""Researcher (RAG): ingest the official PDFs in data/ into ChromaDB with
sentence-transformers embeddings, retrieve evidence for each information need
and emit facts.json - every claim carries its source file and page number.

If data/ holds no PDFs, a clearly-labelled mock fact sheet is used instead and
every mock fact is marked verified=false so the Critic blocks it from the video."""
from __future__ import annotations

import hashlib
import json
import os
import re
import time
from pathlib import Path

from .common import DIRS, ROOT, Fact, RunContext, log_call, say, traced, write_json
from .llm import LLM, extract_json

EMBED_MODEL = "sentence-transformers/all-MiniLM-L6-v2"

# Information needs for the Scriptwriter. Each tag maps to a retrieval query.
NEEDS = {
    "lab":           "LY Agentic AI Laboratory final year lab evaluation lab hours",
    "multi_agent":   "Design a multi-agent workflow with clearly defined roles, hand-offs and a critic feedback loop",
    "rag":           "Ground LLM generation in verified source documents using retrieval RAG to avoid hallucinated claims",
    "orchestration": "Orchestrate text, image, video, speech and audio generation tools under time and budget constraints",
    "logging":       "Instrument an agent system with structured logs, cost tracking and one-command reproducibility",
    "responsible":   "Apply responsible-AI practices: factual grounding, consent, disclosure, safe messaging and licensing",
    "budget":        "API budget maximum per Live Run across all paid APIs",
    "timebox":       "Live Run 3 hours hard stop from brief draw to submission",
    "deploy":        "Deployment public URL GitHub Pages Hugging Face Spaces Streamlit Cloud",
    "portfolio":     "Students graduate with a real-client portfolio piece and a reproducible agentic system on GitHub",
    "local_models":  "local open models via Ollama vLLM Llama Qwen Mistral",
    "frameworks":    "Agent framework LangGraph CrewAI AutoGen OpenAI Agents SDK Claude Agent SDK",
}

SAMPLE_QUESTIONS = [
    "What is the maximum API budget for a Live Run?",
    "How long is the Live Run?",
    "Which agent checks duration and factual claims?",
    "What must the end card contain?",
    "What are the learning outcomes of the lab?",
    "Which vector stores are suggested for RAG?",
    "How many human interventions are allowed?",
    "What frame rate and codec must the video use?",
    "Where can a digital experience be deployed?",
    "What happens if a fact is fabricated?",
]

MOCK_FACTS = [  # used ONLY when data/ is empty - never verified, never shown in the video
    ("Lab workstations: NVIDIA RTX-class GPUs (24 GB VRAM) for local model inference.", "lab"),
    ("Shared GPU server with 4 x A100 80 GB for fine-tuning workloads.", "lab"),
    ("Students deploy agent apps to cloud endpoints as part of coursework.", "deploy"),
]


# ------------------------------------------------------------------ ingestion
def _load_pages():
    import pymupdf as fitz
    pages = []
    for pdf in sorted(DIRS["data"].glob("*.pdf")):
        with fitz.open(pdf) as doc:
            for i, page in enumerate(doc, start=1):
                text = re.sub(r"\s+", " ", page.get_text()).strip()
                if text:
                    pages.append({"source": pdf.name, "page": i, "text": text})
    return pages


def _chunks(pages):
    from langchain_text_splitters import RecursiveCharacterTextSplitter
    splitter = RecursiveCharacterTextSplitter(chunk_size=520, chunk_overlap=90,
                                              separators=[". ", "; ", ", ", " "])
    out = []
    for p in pages:
        for j, c in enumerate(splitter.split_text(p["text"])):
            out.append({"id": f"{p['source']}#p{p['page']}c{j}", "text": c,
                        "source": p["source"], "page": p["page"]})
    return out


class Index:
    """ChromaDB + sentence-transformers; lexical fallback if the model is unavailable."""

    def __init__(self, chunks):
        self.chunks = chunks
        self.backend = "chromadb+minilm"
        key = hashlib.sha1("".join(c["id"] + c["text"] for c in chunks).encode()).hexdigest()[:10]
        cached = Path.home() / ".cache/huggingface/hub/models--sentence-transformers--all-MiniLM-L6-v2"
        if cached.exists():  # model already downloaded: don't let a flaky network stall the run
            os.environ.setdefault("HF_HUB_OFFLINE", "1")
        os.environ.setdefault("HF_HUB_DISABLE_SYMLINKS_WARNING", "1")
        try:
            import chromadb
            from sentence_transformers import SentenceTransformer
            self.model = SentenceTransformer(EMBED_MODEL, device="cpu")
            client = chromadb.PersistentClient(path=str(ROOT / ".cache" / "chroma"))
            self.col = client.get_or_create_collection(f"facts_{key}", metadata={"hnsw:space": "cosine"})
            if self.col.count() != len(chunks):
                emb = self.model.encode([c["text"] for c in chunks], normalize_embeddings=True).tolist()
                self.col.upsert(ids=[c["id"] for c in chunks], embeddings=emb,
                                documents=[c["text"] for c in chunks],
                                metadatas=[{"source": c["source"], "page": c["page"]} for c in chunks])
        except Exception as exc:  # offline machine: keep going, but say so in the log
            self.backend = f"lexical-fallback ({type(exc).__name__})"
            self.col = None

    def query(self, q, k=4):
        if self.col is not None:
            emb = self.model.encode([q], normalize_embeddings=True).tolist()
            r = self.col.query(query_embeddings=emb, n_results=k)
            return [{"text": d, "source": m["source"], "page": m["page"], "score": round(1 - dist, 4)}
                    for d, m, dist in zip(r["documents"][0], r["metadatas"][0], r["distances"][0])]
        qt = _toks(q)
        scored = sorted(self.chunks, key=lambda c: -len(qt & _toks(c["text"])))
        return [{**c, "score": round(len(qt & _toks(c["text"])) / max(1, len(qt)), 4)} for c in scored[:k]]


def _toks(s):
    return {w for w in re.findall(r"[a-z0-9]+", s.lower()) if len(w) > 2}


def _best_sentence(query, hits):
    """Pick the single sentence across the top hits that best answers the need."""
    qt = _toks(query)
    best = None
    for h in hits:
        for sent in re.split(r"(?<=[.!?])\s+|\s\|\s", h["text"]):
            sent = sent.strip(" |")
            if not 25 <= len(sent) <= 240:
                continue
            overlap = len(qt & _toks(sent)) / max(1, len(qt))
            score = 0.6 * overlap + 0.4 * h["score"]
            if best is None or score > best[0]:
                best = (score, sent, h)
    return best


# ----------------------------------------------------------------------- agent
def run(ctx: RunContext, llm: LLM) -> list[Fact]:
    with traced(ctx, "researcher", "pymupdf+splitter", model="PyMuPDF", provider="local") as t:
        pages = _load_pages()
        chunks = _chunks(pages) if pages else []
        t["units"] = f"{len(pages)} pages / {len(chunks)} chunks"

    facts: list[Fact] = []
    if not chunks:
        say("researcher", "data/ is empty -> MOCK fact sheet (unverified, blocked by Critic)")
        for i, (claim, tag) in enumerate(MOCK_FACTS, 1):
            facts.append(Fact(id=f"M{i:02d}", claim=claim, source="MOCK - replace with official fact sheet",
                              page=0, score=0.0, query=tag, tags=[tag], verified=False))
        log_call(ctx, agent="researcher", tool="mock-facts", status="mock", units=f"{len(facts)} facts")
    else:
        t0 = time.perf_counter()
        index = Index(chunks)
        evidence = {}
        for tag, q in NEEDS.items():
            evidence[tag] = index.query(q, k=4)
        for q in ctx.brief.must_include:
            evidence[f"must:{q}"] = index.query(q, k=4)
        log_call(ctx, agent="researcher", tool="vector-search", provider="local", model=index.backend,
                 units=f"{len(evidence)} queries x k=4", latency_s=time.perf_counter() - t0)

        def offline() -> str:
            out, seen = [], set()
            for tag, hits in evidence.items():
                pick = _best_sentence(NEEDS.get(tag, tag.split(":", 1)[-1]), hits)
                if not pick:
                    continue
                score, sent, h = pick
                if sent in seen:
                    for f in out:  # same sentence answers two needs: merge tags
                        if f["claim"] == sent:
                            f["tags"].append(tag)
                    continue
                seen.add(sent)
                out.append({"id": f"F{len(out) + 1:02d}", "claim": sent, "source": h["source"],
                            "page": h["page"], "score": round(score, 3), "query": tag, "tags": [tag],
                            "verified": True})
            return json.dumps(out, indent=2, ensure_ascii=False)

        ev_text = "\n".join(f"[{t}] ({h['source']} p{h['page']}) {h['text']}"
                            for t, hs in evidence.items() for h in hs[:2])
        raw = llm.complete(ctx, agent="researcher", prompt_id="researcher_v1",
                           variables={"topic": ctx.brief.topic, "evidence": ev_text}, offline=offline)
        facts = [Fact(**f) for f in extract_json(raw)]

        # retrieval smoke-test (handout step 3.2.2): 10 sample questions
        test = [{"q": q, "top": [{"source": h["source"], "page": h["page"], "score": h["score"],
                                  "snippet": h["text"][:160]} for h in index.query(q, k=2)]}
                for q in SAMPLE_QUESTIONS]
        write_json(ctx.work / "retrieval_test.json", {"backend": index.backend, "results": test})

    path = write_json(ctx.work / "facts.json", [f.model_dump() for f in facts])
    log_call(ctx, agent="researcher", tool="write", units=f"{len(facts)} facts", output_path=path)
    say("researcher", f"{len(facts)} facts ({sum(f.verified for f in facts)} verified)")
    return facts
