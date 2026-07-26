from __future__ import annotations
import os
import time
import uuid
from fastapi import FastAPI, HTTPException, Header
from fastapi.middleware.cors import CORSMiddleware
from app import cache
from app.models import (
    GenerateRequest,
    GenerateResponse,
    JobStatus,
    JobStatusResponse,
    CollageResponse,
    LedgerRecord,
    LedgerRecentResponse,
    LedgerFatePatch,
)
from app.tasks import task_orchestrate

# Shared secret guarding the private ledger. Unset => the ledger endpoints are disabled
# (503) rather than world-readable, so an unconfigured deploy never leaks post data.
LEDGER_SECRET = os.getenv("LEDGER_SECRET", "").strip()

app = FastAPI(title="ephemera")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.post("/generate", response_model=GenerateResponse)
def generate(req: GenerateRequest):
    topic = req.topic.strip()
    density = req.density if req.density in ("sparse", "dense") else None
    layout_seed = req.layout_seed
    if not topic:
        raise HTTPException(status_code=400, detail="topic is required")

    # Return cached result immediately if available
    cached_id = cache.get_cached_collage_id(topic, density, layout_seed)
    if cached_id and cache.get_collage(cached_id):
        return GenerateResponse(job_id=cached_id)

    job_id = str(uuid.uuid4())
    cache.set_job(job_id, {
        "id": job_id,
        "status": JobStatus.pending.value,
        "progress": 0,
    })
    task_orchestrate.delay(job_id, topic, density, layout_seed)
    return GenerateResponse(job_id=job_id)


@app.get("/job/{job_id}", response_model=JobStatusResponse)
def job_status(job_id: str):
    data = cache.get_job(job_id)
    if not data:
        raise HTTPException(status_code=404, detail="job not found")
    return JobStatusResponse(
        status=data["status"],
        progress=data.get("progress", 0),
        error=data.get("error"),
    )


@app.get("/collage/{job_id}", response_model=CollageResponse)
def get_collage(job_id: str):
    data = cache.get_collage(job_id)
    if not data:
        job = cache.get_job(job_id)
        if job and job["status"] == JobStatus.done.value:
            raise HTTPException(status_code=500, detail="collage missing despite done status")
        raise HTTPException(status_code=404, detail="collage not ready")
    return CollageResponse(**data)


def _ledger_auth(secret: str | None) -> None:
    if not LEDGER_SECRET:
        raise HTTPException(status_code=503, detail="ledger not configured")
    if secret != LEDGER_SECRET:
        raise HTTPException(status_code=403, detail="forbidden")


@app.post("/ledger", response_model=LedgerRecord)
def ledger_append(record: LedgerRecord, x_ledger_secret: str | None = Header(default=None)):
    _ledger_auth(x_ledger_secret)
    data = record.model_dump()
    if data.get("ts") is None:
        data["ts"] = time.time()
    return LedgerRecord(**cache.ledger_append(data))


@app.get("/ledger/recent", response_model=LedgerRecentResponse)
def ledger_recent(n: int = 50, x_ledger_secret: str | None = Header(default=None)):
    _ledger_auth(x_ledger_secret)
    n = max(1, min(n, 500))
    return LedgerRecentResponse(records=[LedgerRecord(**r) for r in cache.ledger_recent(n)])


@app.post("/ledger/fate")
def ledger_fate(patch: LedgerFatePatch, x_ledger_secret: str | None = Header(default=None)):
    _ledger_auth(x_ledger_secret)
    updated = cache.ledger_update_fate(patch.post_id, {"state": patch.state, "notes": patch.notes})
    return {"updated": updated}


@app.get("/health")
def health():
    return {"ok": True}
