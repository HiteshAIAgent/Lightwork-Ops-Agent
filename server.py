from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import Optional
import os
import db
from agent import run

db.init_db()

app = FastAPI()
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])


class ChatRequest(BaseModel):
    message: str
    history: list = []


class CommitmentRequest(BaseModel):
    team: str
    description: str
    deadline: str
    owner: str = ""
    priority: str = "medium"
    depends_on: Optional[int] = None
    notes: str = ""


class CommitmentPatch(BaseModel):
    description: Optional[str] = None
    deadline: Optional[str] = None
    owner: Optional[str] = None
    priority: Optional[str] = None
    status: Optional[str] = None
    notes: Optional[str] = None


@app.patch("/commitments/{commitment_id}")
def patch_commitment(commitment_id: int, req: CommitmentPatch):
    result = {}
    if any([req.description, req.deadline, req.owner is not None, req.priority]):
        result['commitment'] = db.update_commitment(
            commitment_id,
            description=req.description,
            deadline=req.deadline,
            owner=req.owner,
            priority=req.priority,
        )
    if req.status:
        result['update'] = db.log_update(commitment_id, req.status, req.notes or None)
    elif req.notes:
        latest = db.get_commitments()
        c = next((x for x in latest if x['id'] == commitment_id), None)
        if c:
            result['update'] = db.log_update(commitment_id, c['latest_status'] if c['latest_status'] != 'no_update' else 'on_track', req.notes)
    return result


class AlertRequest(BaseModel):
    from_role: str
    to_team: str
    message: str


class AlertResponseRequest(BaseModel):
    response: str


@app.post("/chat")
def chat(req: ChatRequest):
    response = run(req.message, req.history)
    return {"response": response}


@app.get("/commitments")
def get_commitments(team: str = "", status: str = ""):
    return db.get_commitments(team or None, status or None)


@app.post("/commitments")
def add_commitment(req: CommitmentRequest):
    result = db.add_commitment(
        req.team, req.description, req.deadline,
        req.owner or None, req.priority, req.depends_on
    )
    if req.notes:
        db.log_update(result["id"], "on_track", req.notes)
    return result


@app.get("/alerts")
def get_alerts(team: str = ""):
    return db.get_alerts(team or None, include_resolved=False)


@app.post("/alerts")
def create_alert(req: AlertRequest):
    return db.create_alert(req.from_role, req.to_team, req.message)


@app.post("/alerts/{alert_id}/respond")
def respond_alert(alert_id: int, req: AlertResponseRequest):
    return db.respond_to_alert(alert_id, req.response)


if not os.environ.get("VERCEL"):
    app.mount("/", StaticFiles(directory="public", html=True), name="static")
