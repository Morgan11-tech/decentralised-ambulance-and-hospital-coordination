"""Gemini: the conversational brain.

Each call is stateless: we send the system prompt, the current incident state
and the transcript, and get back a `GeminiTurn` via structured output (JSON
Schema), so we never parse free-form LLM text.
"""

from google import genai

from config import get_settings
from models.conversation import GeminiTurn
from prompts.emergency_agent import SYSTEM_PROMPT

_client: genai.Client | None = None


def _get_client() -> genai.Client:
    global _client
    if _client is None:
        api_key = get_settings().gemini_api_key
        if not api_key:
            raise RuntimeError("GEMINI_API_KEY is not set")
        _client = genai.Client(api_key=api_key)
    return _client


async def generate_turn(prompt: str) -> GeminiTurn:
    settings = get_settings()
    interaction = await _get_client().aio.interactions.create(
        model=settings.gemini_llm_model,
        system_instruction=SYSTEM_PROMPT,
        input=prompt,
        response_format={
            "type": "text",
            "mime_type": "application/json",
            "schema": GeminiTurn.model_json_schema(),
        },
        generation_config={"thinking_level": settings.gemini_thinking_level},
        store=False,  # we keep our own conversation state
    )
    return GeminiTurn.model_validate_json(interaction.output_text)
