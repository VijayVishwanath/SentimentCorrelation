"""AI API: experience text analysis, Diagnosis Assist, ML second opinion, predictive risk, DEX Copilot, knowledge base."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.concurrency import run_in_threadpool
from pydantic import BaseModel, Field

from .. import db
from ..copilot import agent
from ..copilot.retriever import get_kb
from ..copilot.tools import effective_config
from ..data.store import DataStore
from ..engines import experience as exp
from ..engines import forecast, ml
from ..engines.diagnosis import diagnose
from .deps import CleanRoute, store_dep

router = APIRouter(route_class=CleanRoute)


class TextIn(BaseModel):
    text: str = Field(..., min_length=1, max_length=5000)
    repeat_contacts: int = Field(0, ge=0, le=50)
    escalations: int = Field(0, ge=0, le=20)


class DiagnosisIn(BaseModel):
    ticket_text: str = Field(..., min_length=1, max_length=5000)
    device_id: str = Field(..., pattern=r"^[A-Za-z0-9_-]{1,32}$")
    week: int | None = Field(None, ge=1, le=520)
    repeat_contacts: int = Field(0, ge=0, le=50)
    escalations: int = Field(0, ge=0, le=20)
    include_ml: bool = True


class ChatTurn(BaseModel):
    role: str = Field(..., pattern="^(user|assistant)$")
    content: str = Field(..., max_length=20000)


class CopilotIn(BaseModel):
    question: str = Field(..., min_length=1, max_length=4000)
    device_id: str | None = Field(None, pattern=r"^[A-Za-z0-9_-]{1,32}$")
    ticket_text: str | None = Field(None, max_length=5000)
    week: int | None = Field(None, ge=1, le=520)
    history: list[ChatTurn] = Field(default_factory=list, max_length=20)


@router.post("/experience/analyze", summary="Module 1 — score free text (sentiment, frustration, emotion, severity)")
def analyze(body: TextIn):
    return exp.analyze_text(body.text, body.repeat_contacts, body.escalations).as_dict()


@router.post("/experience/explain", summary="Module 1 — step-by-step derivation of the frustration score for free text")
def explain_text(body: TextIn):
    return exp.explain(body.text, body.repeat_contacts, body.escalations)


@router.post("/diagnosis", summary="Module 4 — Diagnosis Assist: ranked root causes, evidence, fix")
def run_diagnosis(body: DiagnosisIn, store: DataStore = Depends(store_dep)):
    if store.device(body.device_id) is None:
        raise HTTPException(404, f"device {body.device_id} not found")
    if store.telemetry_at(body.device_id, body.week) is None:
        raise HTTPException(422, f"device {body.device_id} has no telemetry")
    result = diagnose(body.ticket_text, body.device_id, store, week=body.week,
                      repeat_contacts=body.repeat_contacts, escalations=body.escalations)
    if body.include_ml:
        row = store.telemetry_at(body.device_id, body.week)
        m = ml.get_model(store)
        pred = m.predict(body.ticket_text, row)
        pred["agrees_with_rules"] = pred.get("prediction") == result["primary"]["category"]
        pred["model_metrics"] = m.metrics
        result["ml_second_opinion"] = pred
    db.log_diagnosis(body.device_id, body.ticket_text, result)
    return result


@router.get("/diagnosis/recent", summary="Recent diagnoses (audit log)")
def recent_diagnoses(limit: int = Query(20, ge=1, le=200)):
    return {"items": db.recent_diagnoses(limit)}


@router.get("/models/metrics", summary="AI model evaluation: rule engine vs ML variants")
def model_metrics(store: DataStore = Depends(store_dep)):
    m = ml.get_model(store)
    return {"root_cause": m.metrics, "classes": m.classes_, "forecast": forecast.get_forecaster(store).metrics,
            "sentiment_lexicon": {"validated_agreement_pct": 93.3,
                                  "note": "Agreement with the dataset's hidden ground-truth tier, measured during "
                                          "dataset construction (judge briefing). Ground truth is not shipped."},
            "disclosure": "Categories in the simulated dataset were seeded from telemetry and templated text, so "
                          "near-perfect accuracy here reflects separable synthetic data, not expected real-world accuracy."}


@router.get("/forecast/watchlist", summary="Predictive DEX — devices most likely to raise a frustrated ticket next week")
async def forecast_watchlist(top: int = Query(50, ge=1, le=500), department: str | None = None,
                             store: DataStore = Depends(store_dep)):
    fc = await run_in_threadpool(forecast.get_forecaster, store)  # first call trains (seconds on large fleets)
    return fc.watchlist(effective_config(), top=top, department=department)


@router.get("/forecast/metrics", summary="Predictive DEX — out-of-time backtest vs the rule baseline, drivers")
async def forecast_metrics(store: DataStore = Depends(store_dep)):
    return (await run_in_threadpool(forecast.get_forecaster, store)).metrics


@router.get("/forecast/devices/{device_id}", summary="Predictive DEX — one device's risk history and explanation")
async def forecast_device(device_id: str, store: DataStore = Depends(store_dep)):
    if store.device(device_id) is None:
        raise HTTPException(404, f"device {device_id} not found")
    return (await run_in_threadpool(forecast.get_forecaster, store)).device(device_id)


@router.post("/copilot/ask", summary="Module 5 — DEX Copilot (agentic, tool-grounded, RAG)")
async def copilot_ask(body: CopilotIn):
    history = [t.model_dump() for t in body.history]
    return await run_in_threadpool(agent.ask, body.question, body.device_id, body.ticket_text, body.week, history)


@router.get("/copilot/status", summary="Which Copilot provider is active")
def copilot_status():
    name = agent.resolve_provider_name()
    from ..config import get_settings
    s = get_settings()
    model = {"anthropic": s.anthropic_model, "azure_openai": s.azure_openai_deployment}.get(name, "grounded-template-v1")
    return {"provider": name, "model": model, "llm_enabled": name != "template",
            "kb_articles": len(get_kb().articles)}


@router.get("/kb", summary="List knowledge-base runbooks")
def kb_list():
    return {"items": [a.as_dict() for a in get_kb().articles.values()]}


@router.get("/kb/search", summary="Search runbooks (BM25)")
def kb_search(q: str = Query(..., min_length=1, max_length=500), category: str | None = None, top_k: int = Query(5, ge=1, le=20)):
    return {"query": q, "results": get_kb().search(q, top_k=top_k, category=category)}


@router.get("/kb/{article_id}", summary="Get a runbook")
def kb_get(article_id: str):
    a = get_kb().get(article_id)
    if a is None:
        raise HTTPException(404, f"article {article_id} not found")
    return a.as_dict(full=True)
