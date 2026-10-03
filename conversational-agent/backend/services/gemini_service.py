"""Gemini: the conversational brain.

Each call is stateless: we send the system prompt, the current incident state
and the transcript, and get back structured output (JSON Schema), so we never
parse free-form LLM text.
"""

from typing import TypeVar

from google import genai
from pydantic import BaseModel

from config import get_settings
from models.conversation import ClarificationQuestion, GeminiTurn
from prompts.emergency_agent import SYSTEM_PROMPT

_client: genai.Client | None = None
T = TypeVar("T", bound=BaseModel)


def _get_client() -> genai.Client:
    global _client
    if _client is None:
        api_key = get_settings().gemini_api_key
        if not api_key:
            raise RuntimeError("GEMINI_API_KEY is not set")
        _client = genai.Client(api_key=api_key)
    return _client


async def _generate(prompt: str, schema: type[T]) -> T:
    settings = get_settings()
    interaction = await _get_client().aio.interactions.create(
        model=settings.gemini_llm_model,
        system_instruction=SYSTEM_PROMPT,
        input=prompt,
        response_format={
            "type": "text",
            "mime_type": "application/json",
            "schema": schema.model_json_schema(),
        },
        generation_config={"thinking_level": settings.gemini_thinking_level},
        store=False,  # we keep our own conversation state
    )
    return schema.model_validate_json(interaction.output_text)


async def extract_turn(prompt: str) -> GeminiTurn:
    """Extract facts from the caller's latest message and phrase the needed questions."""
    return await _generate(prompt, GeminiTurn)


async def generate_clarification(prompt: str) -> str:
    """Phrase one clarification question when Jev is not confident."""
    return (await _generate(prompt, ClarificationQuestion)).question
