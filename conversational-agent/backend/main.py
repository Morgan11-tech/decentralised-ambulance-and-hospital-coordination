"""FastAPI backend for the emergency voice intake prototype.

Endpoints
    GET  /health                    configuration check
    POST /api/session               create a conversation session
    WS   /ws/voice/{session_id}     audio + events (protocol below)
    GET  /api/incidents/{id}        fetch a finalized incident

WebSocket protocol (see README "WebSocket protocol")
    browser -> server
        binary frames                       16-bit PCM mono microphone audio
        {"type": "start", "mode": "voice"|"text", "sample_rate": 16000}
        {"type": "user_text", "text": "..."} typed caller message
        {"type": "playback_done"}           agent audio finished playing
        {"type": "retry"}                   retry after a recoverable error
        {"type": "end"}                     caller ends the conversation
    server -> browser
        {"type": "state", "state": "listening"|"thinking"|"speaking"|"completed"|"error"}
        {"type": "transcript", "speaker": "user", "text": "...", "final": bool}
        {"type": "agent_response", "text": "..."}
        {"type": "audio", "format": "wav", "data": "<base64>"}
        {"type": "incident_state", "state": {...}}
        {"type": "classification", "data": {...}}
        {"type": "incident_complete", "incident": {...}, "persisted": bool, "persistence_error": str|null}
        {"type": "error", "source": "deepgram"|"gemini"|"tts"|"jev", "message": "...", "recoverable": bool}
        {"type": "session_ended", "incident_saved": bool}
"""

import asyncio
import base64
import contextlib
import json
import logging
from contextlib import asynccontextmanager
from uuid import uuid4

from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware

from config import get_settings
from intake_agent import AgentError, AgentReply, IntakeAgent
from services import gemini_tts_service, mongodb_service
from services.deepgram_service import FluxTranscriber

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("conversational-agent")

# In-memory stores: fine for a single-process demo.
sessions: set[str] = set()
completed_incidents: dict[str, dict] = {}


@asynccontextmanager
async def lifespan(_app: FastAPI):
    yield
    await mongodb_service.close()


app = FastAPI(title="Emergency Voice Intake (research prototype)", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=[get_settings().frontend_origin],
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health")
async def health():
    s = get_settings()
    return {
        "status": "ok",
        "configured": {
            "deepgram": bool(s.deepgram_api_key),
            "gemini": bool(s.gemini_api_key),
            "jev": bool(s.jev_api_key),
            "mongodb": bool(s.mongodb_uri),
        },
    }


@app.post("/api/session")
async def create_session():
    session_id = str(uuid4())
    sessions.add(session_id)
    return {"session_id": session_id}


@app.get("/api/incidents/{incident_id}")
async def get_incident(incident_id: str):
    try:
        document = await mongodb_service.get_incident_document(incident_id)
        if document is not None:
            return {"incident": document["incident"], "metadata": document["metadata"], "persisted": True}
    except Exception as exc:
        log.warning("MongoDB lookup failed: %s", exc)
    if incident_id in completed_incidents:
        return completed_incidents[incident_id]
    raise HTTPException(status_code=404, detail="Incident not found")


@app.websocket("/ws/voice/{session_id}")
async def voice_websocket(ws: WebSocket, session_id: str):
    if session_id not in sessions:
        await ws.close(code=4404)
        return
    await ws.accept()
    session = VoiceSession(ws, session_id)
    try:
        await session.run()
    except WebSocketDisconnect:
        pass
    finally:
        await session.cleanup()
        sessions.discard(session_id)


class VoiceSession:
    """Connects one browser WebSocket to STT, the intake agent and TTS.

    Turn-taking is simple half-duplex: caller audio is only transcribed while
    the UI state is "listening". While the agent thinks or speaks we forward
    silence to Deepgram instead, so the agent never hears itself.
    """

    def __init__(self, ws: WebSocket, session_id: str):
        self.ws = ws
        self.agent = IntakeAgent(session_id, emit=self.send)
        self.ui_state = "idle"
        self.speech_enabled = False
        self.stt: FluxTranscriber | None = None
        self.turn_task: asyncio.Task | None = None
        self.ending = False
        self._send_lock = asyncio.Lock()

    # --- outgoing ---------------------------------------------------------------

    async def send(self, event: dict) -> None:
        async with self._send_lock:
            await self.ws.send_json(event)

    async def set_state(self, state: str) -> None:
        self.ui_state = state
        await self.send({"type": "state", "state": state})

    async def send_error(self, source: str, message: str, recoverable: bool) -> None:
        log.error("%s error: %s", source, message)
        await self.send({"type": "error", "source": source, "message": message, "recoverable": recoverable})

    # --- incoming ---------------------------------------------------------------

    async def run(self) -> None:
        while True:
            message = await self.ws.receive()
            if message["type"] == "websocket.disconnect":
                return
            if message.get("bytes") is not None:
                await self.on_audio(message["bytes"])
            elif message.get("text"):
                await self.on_command(json.loads(message["text"]))

    async def on_audio(self, chunk: bytes) -> None:
        if self.stt is None:
            return
        await self.stt.send_audio(chunk if self.ui_state == "listening" else bytes(len(chunk)))

    async def on_command(self, command: dict) -> None:
        kind = command.get("type")
        if kind == "start" and self.ui_state == "idle":
            await self.start(command.get("mode", "voice"), int(command.get("sample_rate", 16000)))
        elif kind == "user_text" and self.ui_state == "listening" and command.get("text", "").strip():
            self.begin_turn(command["text"].strip())
        elif kind == "playback_done" and self.ui_state == "speaking":
            await self.finish_turn()
        elif kind == "retry" and self.ui_state == "error" and self.agent.awaiting_reply:
            self.begin_turn(None)
        elif kind == "end" and not self.ending:
            await self.end()

    # --- conversation -----------------------------------------------------------

    async def start(self, mode: str, sample_rate: int) -> None:
        if mode == "voice":
            self.speech_enabled = True
            self.stt = FluxTranscriber(
                sample_rate,
                on_interim=self.on_interim_transcript,
                on_end_of_turn=self.on_end_of_turn,
                on_error=self.on_stt_error,
            )
            try:
                await self.stt.connect()
            except Exception as exc:
                self.stt = None
                await self.send_error("deepgram", f"Could not connect to Deepgram: {exc}", False)
                await self.set_state("error")
                return
        self.ui_state = "thinking"
        self.turn_task = asyncio.create_task(self._greet())

    async def _greet(self) -> None:
        await self.set_state("thinking")
        await self.respond(await self.agent.start())

    async def on_interim_transcript(self, text: str) -> None:
        if self.ui_state == "listening":
            await self.send({"type": "transcript", "speaker": "user", "text": text, "final": False})

    async def on_end_of_turn(self, text: str) -> None:
        if self.ui_state == "listening":
            self.begin_turn(text)

    async def on_stt_error(self, message: str) -> None:
        await self.send_error("deepgram", message, False)
        await self.set_state("error")

    def begin_turn(self, text: str | None) -> None:
        """Start processing a caller turn (text=None means retry the last one)."""
        self.ui_state = "thinking"  # immediately, so no second turn can start
        self.turn_task = asyncio.create_task(self._run_turn(text))

    async def _run_turn(self, text: str | None) -> None:
        await self.set_state("thinking")
        if text is not None:
            await self.send({"type": "transcript", "speaker": "user", "text": text, "final": True})
        try:
            reply = await (self.agent.handle_caller_text(text) if text else self.agent.retry())
        except AgentError as exc:
            await self.send_error(exc.source, str(exc), True)
            await self.set_state("error")
            return
        if reply is not None:
            await self.respond(reply)

    async def respond(self, reply: AgentReply) -> None:
        self._remember_incident()
        if self.ending:
            return  # the caller hung up: nothing more to say
        await self.send({"type": "agent_response", "text": reply.text})
        audio = None
        if self.speech_enabled:
            try:
                audio = await gemini_tts_service.synthesize(reply.text)
            except Exception as exc:
                await self.send_error("tts", f"Speech synthesis failed: {exc}", True)
        if audio:
            await self.set_state("speaking")
            await self.send({"type": "audio", "format": "wav", "data": base64.b64encode(audio).decode()})
            # The browser sends "playback_done" when it finishes playing.
        else:
            await self.finish_turn()

    async def finish_turn(self) -> None:
        """Agent finished talking: listen again, or wrap up if the incident is complete."""
        if self.agent.done:
            await self.close_stt()
            await self.set_state("completed")
        else:
            await self.set_state("listening")

    async def end(self) -> None:
        self.ending = True
        if self.turn_task and not self.turn_task.done():
            # Let the current step finish (e.g. a MongoDB write) instead of cutting it off.
            with contextlib.suppress(Exception):
                await self.turn_task
        saved = await self.agent.force_finalize()
        self._remember_incident()
        await self.close_stt()
        await self.send({"type": "session_ended", "incident_saved": saved})
        await self.set_state("completed" if saved else "idle")

    def _remember_incident(self) -> None:
        incident = self.agent.incident
        if incident is not None:
            completed_incidents[incident.incident_id] = {
                "incident": incident.model_dump(mode="json"),
                "persisted": self.agent.persisted,
                "persistence_error": self.agent.persistence_error,
            }

    async def close_stt(self) -> None:
        if self.stt is not None:
            await self.stt.close()
            self.stt = None

    async def cleanup(self) -> None:
        if self.turn_task and not self.turn_task.done():
            self.turn_task.cancel()
        await self.close_stt()
