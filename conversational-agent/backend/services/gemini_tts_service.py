"""Gemini TTS: turns the agent's reply text into speech.

Unary (non-streaming) Gemini 3.8 TTS requests return a complete WAV file
(24 kHz, mono, 16-bit PCM), which the browser can decode and play directly.
"""

import base64

from config import get_settings
from services.gemini_service import _get_client

SPEAKING_STYLE = "calm, clear and reassuring emergency call-taker, steady pace"


async def synthesize(text: str) -> bytes:
    """Returns WAV bytes for `text`."""
    settings = get_settings()
    interaction = await _get_client().aio.interactions.create(
        model=settings.gemini_tts_model,
        input=[
            {
                "type": "user_input",
                "content": [
                    {
                        "type": "text",
                        "text": text,
                        "annotations": [{"type": "speech_metadata", "style": SPEAKING_STYLE}],
                    }
                ],
            }
        ],
        response_format={"type": "audio", "mime_type": "audio/wav"},
        generation_config={"speech_config": [{"voice": settings.gemini_tts_voice}]},
        store=False,
    )
    if interaction.output_audio is None or not interaction.output_audio.data:
        raise RuntimeError("Gemini TTS returned no audio")
    return base64.b64decode(interaction.output_audio.data)
