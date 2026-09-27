"""Deepgram Flux streaming speech-to-text.

The browser streams raw 16-bit PCM microphone audio to OUR backend, and the
backend forwards it to Deepgram. The Deepgram API key therefore never leaves
the server (no temporary browser tokens needed).

Flux (`/v2/listen`) has built-in end-of-turn detection: it tells us when the
caller has finished speaking with an `EndOfTurn` event, which is exactly the
turn-taking signal the voice agent needs.

Docs: https://developers.deepgram.com/docs/flux/quickstart
"""

import asyncio
import json
from collections.abc import Awaitable, Callable
from urllib.parse import urlencode

from websockets.asyncio.client import ClientConnection, connect
from websockets.exceptions import ConnectionClosed

from config import get_settings

FLUX_URL = "wss://api.deepgram.com/v2/listen"


class FluxTranscriber:
    """One Deepgram Flux connection for one voice session."""

    def __init__(
        self,
        sample_rate: int,
        on_interim: Callable[[str], Awaitable[None]],
        on_end_of_turn: Callable[[str], Awaitable[None]],
        on_error: Callable[[str], Awaitable[None]],
    ):
        self.sample_rate = sample_rate
        self.on_interim = on_interim
        self.on_end_of_turn = on_end_of_turn
        self.on_error = on_error
        self._ws: ClientConnection | None = None
        self._receiver: asyncio.Task | None = None
        self._closing = False

    async def connect(self) -> None:
        settings = get_settings()
        if not settings.deepgram_api_key:
            raise RuntimeError("DEEPGRAM_API_KEY is not set")
        params = [
            ("model", settings.deepgram_stt_model),
            ("encoding", "linear16"),
            ("sample_rate", self.sample_rate),
        ]
        # Keyterm prompting: one repeated `keyterm` parameter per term.
        params += [("keyterm", t.strip()) for t in settings.deepgram_keyterms.split(",") if t.strip()]
        query = urlencode(params)
        self._ws = await connect(
            f"{FLUX_URL}?{query}",
            additional_headers={"Authorization": f"Token {settings.deepgram_api_key}"},
        )
        self._receiver = asyncio.create_task(self._receive_loop())

    async def send_audio(self, chunk: bytes) -> None:
        if self._ws is not None and not self._closing:
            try:
                await self._ws.send(chunk)
            except ConnectionClosed:
                pass  # reported by the receive loop

    async def close(self) -> None:
        self._closing = True
        if self._ws is not None:
            try:
                await self._ws.send(json.dumps({"type": "CloseStream"}))
            except ConnectionClosed:
                pass
            await self._ws.close()
        if self._receiver is not None:
            self._receiver.cancel()

    async def _receive_loop(self) -> None:
        assert self._ws is not None
        try:
            async for raw in self._ws:
                message = json.loads(raw)
                msg_type = message.get("type")
                if msg_type == "TurnInfo":
                    transcript = (message.get("transcript") or "").strip()
                    if message.get("event") == "EndOfTurn":
                        if transcript:
                            await self.on_end_of_turn(transcript)
                    elif transcript:
                        await self.on_interim(transcript)
                elif msg_type == "Error":
                    await self.on_error(
                        f"Deepgram error {message.get('code')}: {message.get('description')}"
                    )
        except ConnectionClosed as exc:
            if not self._closing:
                await self.on_error(f"Deepgram connection closed: {exc}")
        except asyncio.CancelledError:
            pass
