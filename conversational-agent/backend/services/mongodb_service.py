"""MongoDB persistence for finalized incidents.

Document shape (canonical payload kept separate from debugging data):

    {
      "_id": "<incident_id>",
      "incident": { ...canonical Incident... },
      "metadata": { "session_id", "transcript", "jev_raw", "jev_error", ... },
      "created_at": <datetime>
    }
"""

from datetime import datetime, timezone

from pymongo import AsyncMongoClient

from config import get_settings
from models.incident import Incident

_client: AsyncMongoClient | None = None


def _collection():
    global _client
    settings = get_settings()
    if not settings.mongodb_uri:
        raise RuntimeError("MONGODB_URI is not set")
    if _client is None:
        _client = AsyncMongoClient(settings.mongodb_uri, serverSelectionTimeoutMS=5000, tz_aware=True)
    return _client[settings.mongodb_database][settings.mongodb_incident_collection]


async def save_incident(incident: Incident, metadata: dict) -> None:
    """Raises on failure; the caller decides how to report it."""
    document = {
        "_id": incident.incident_id,
        "incident": incident.model_dump(mode="json"),
        "metadata": metadata,
        "created_at": datetime.now(timezone.utc),
    }
    await _collection().insert_one(document)


async def get_incident_document(incident_id: str) -> dict | None:
    return await _collection().find_one({"_id": incident_id})


async def close() -> None:
    global _client
    if _client is not None:
        await _client.close()
        _client = None
