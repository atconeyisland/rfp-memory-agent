from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel

from rfp_agent import ToolBox, build_trace, verify
from rfp_agent.seed import seeded_store


app = FastAPI(title="RFP Memory Agent")
INDEX = Path(__file__).with_name("index.html")
box = ToolBox(seeded_store())


class RecallRequest(BaseModel):
    client: str
    question: str
    rfp_text: str = ""


class CorrectionRequest(BaseModel):
    client: str
    text: str
    item_id: str | None = None
    category: str = "other"


def _draft(recall: dict, question: str) -> str:
    if recall["empty"]:
        if "sla" in question.lower():
            return "We will confirm the required availability target and service-credit terms with your team."
        return "We propose a phased delivery plan with measurable milestones."
    if "lead" in question.lower():
        return "We will confirm the named technical contact with your team."
    if "price" in question.lower() or "tier" in question.lower():
        fact = next((f for f in recall["world_facts"] if f["category"] == "pricing" and not f["stale"]), None)
        return "Pricing is presented on the Enterprise tier." if fact else "We will confirm the commercial tier with your team."
    return "Executive summary: a measurable ROI model with a payback timeline leads this response."


def _scan_rfp(rfp_text: str) -> dict:
    markers = ("ignore previous", "ignore all prior", "reveal your prompt", "system message", "call retain")
    lowered = rfp_text.lower()
    matches = [marker for marker in markers if marker in lowered]
    return {"scanned": bool(rfp_text.strip()), "injection_detected": bool(matches), "matches": matches}


def _state(client: str, question: str, rfp_text: str = "") -> dict:
    if client not in box.store.entities:
        raise HTTPException(status_code=404, detail="unknown client")
    recall = box.recall(client, question)
    draft = _draft(recall, question)
    trace = build_trace(recall)
    violations = verify(draft + "\n" + trace, box.recall_log, [
        alias for entity, aliases in box.store.entities.items() if entity != client for alias in aliases[:1]
    ])
    return {"client": client, "question": question, "draft": draft, "trace": trace,
            "recall": recall, "violations": violations,
            "security": _scan_rfp(rfp_text)}


@app.get("/")
def index():
    return FileResponse(INDEX)


@app.get("/api/clients")
def clients():
    return {"clients": [{"id": entity, "name": aliases[1] if len(aliases) > 1 else entity}
                         for entity, aliases in box.store.entities.items()]}


@app.post("/api/state")
def state(request: RecallRequest):
    return _state(request.client, request.question, request.rfp_text)


@app.post("/api/correction")
def correction(request: CorrectionRequest):
    if request.client not in box.store.entities:
        raise HTTPException(status_code=404, detail="unknown client")
    result = box.correction_ingest(request.client, request.text, request.item_id, request.category)
    return {"result": result}