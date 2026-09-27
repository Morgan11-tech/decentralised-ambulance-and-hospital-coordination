"""End-to-end WebSocket protocol test in text mode (no audio, fake providers)."""

import asyncio
from functools import partial

from fastapi.testclient import TestClient

import main
from intake_agent import IntakeAgent
from prompts.emergency_agent import CLOSING_MESSAGE, GREETING
from tests.test_intake_agent import COMPLETE, SETTINGS, Fakes, classification, turn


def receive_until(ws, event_type, **match):
    """Collect events until one of `event_type` (matching `match`) arrives."""
    seen = []
    while True:
        event = ws.receive_json()
        seen.append(event)
        if event["type"] == event_type and all(event.get(k) == v for k, v in match.items()):
            return seen


def test_text_mode_conversation(monkeypatch):
    fakes = Fakes(
        turns=[turn("What is your location?", incident_description="Cyclist fell."), turn("Thanks.", ready=True, **COMPLETE)],
        results=[classification(0.9)],
    )
    monkeypatch.setattr(
        main, "IntakeAgent",
        partial(IntakeAgent, llm=fakes.llm, classifier=fakes.classifier, store=fakes.store, settings=SETTINGS),
    )
    client = TestClient(main.app)
    session_id = client.post("/api/session").json()["session_id"]

    with client.websocket_connect(f"/ws/voice/{session_id}") as ws:
        ws.send_json({"type": "start", "mode": "text"})
        events = receive_until(ws, "state", state="listening")
        assert {"type": "agent_response", "text": GREETING} in events

        ws.send_json({"type": "user_text", "text": "My friend fell off his bike."})
        events = receive_until(ws, "state", state="listening")
        assert {"type": "transcript", "speaker": "user", "text": "My friend fell off his bike.", "final": True} in events
        assert {"type": "agent_response", "text": "What is your location?"} in events
        assert any(e["type"] == "incident_state" for e in events)

        ws.send_json({"type": "user_text", "text": "University of Twente."})
        events = receive_until(ws, "state", state="completed")
        types = [e["type"] for e in events]
        assert "classification" in types
        complete = next(e for e in events if e["type"] == "incident_complete")
        assert complete["persisted"] is True
        assert {"type": "agent_response", "text": CLOSING_MESSAGE} in events

    incident_id = complete["incident"]["incident_id"]
    monkeypatch.setattr(main.mongodb_service, "get_incident_document", _raise)
    response = client.get(f"/api/incidents/{incident_id}")  # falls back to memory
    assert response.status_code == 200
    assert response.json()["incident"]["incident_type"] == "trauma"


def test_end_while_agent_is_thinking(monkeypatch):
    """Ending mid-turn lets the turn finish silently, then saves what is known."""
    fakes = Fakes(turns=[turn("What is your location?", incident_description="Dad collapsed.")], results=[classification(0.9)])
    real_llm = fakes.llm

    async def slow_llm(prompt):
        await asyncio.sleep(0.2)
        return await real_llm(prompt)

    monkeypatch.setattr(
        main, "IntakeAgent",
        partial(IntakeAgent, llm=slow_llm, classifier=fakes.classifier, store=fakes.store, settings=SETTINGS),
    )
    client = TestClient(main.app)
    session_id = client.post("/api/session").json()["session_id"]

    with client.websocket_connect(f"/ws/voice/{session_id}") as ws:
        ws.send_json({"type": "start", "mode": "text"})
        receive_until(ws, "state", state="listening")
        ws.send_json({"type": "user_text", "text": "My dad collapsed."})
        receive_until(ws, "state", state="thinking")
        ws.send_json({"type": "end"})
        events = receive_until(ws, "session_ended")

    assert events[-1] == {"type": "session_ended", "incident_saved": True}
    assert {"type": "agent_response", "text": "What is your location?"} not in events
    assert len(fakes.stored) == 1


def test_unknown_session_is_rejected():
    client = TestClient(main.app)
    try:
        with client.websocket_connect("/ws/voice/not-a-session") as ws:
            ws.receive_json()
        raise AssertionError("expected the connection to be closed")
    except Exception as exc:  # starlette raises WebSocketDisconnect
        assert getattr(exc, "code", None) == 4404


def test_health_reports_configuration():
    body = TestClient(main.app).get("/health").json()
    assert body["status"] == "ok"
    assert set(body["configured"]) == {"deepgram", "gemini", "jev", "mongodb"}


async def _raise(*_args, **_kwargs):
    raise RuntimeError("MONGODB_URI is not set")
