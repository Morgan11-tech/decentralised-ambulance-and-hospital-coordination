from urllib.parse import parse_qs, urlsplit

from config import Settings
from services import deepgram_service


class FakeSocket:
    def __aiter__(self):
        return self

    async def __anext__(self):
        raise StopAsyncIteration


async def test_flux_url_includes_model_audio_format_and_keyterms(monkeypatch):
    captured = {}

    async def fake_connect(url, additional_headers):
        captured["url"], captured["headers"] = url, additional_headers
        return FakeSocket()

    settings = Settings(_env_file=None, deepgram_api_key="k", deepgram_keyterms="University of Twente, Enschede,")
    monkeypatch.setattr(deepgram_service, "connect", fake_connect)
    monkeypatch.setattr(deepgram_service, "get_settings", lambda: settings)

    async def noop(_):
        pass

    await deepgram_service.FluxTranscriber(16000, noop, noop, noop).connect()

    url = urlsplit(captured["url"])
    query = parse_qs(url.query)
    assert url.path == "/v2/listen"
    assert query["model"] == ["flux-general-en"]
    assert query["encoding"] == ["linear16"] and query["sample_rate"] == ["16000"]
    assert query["keyterm"] == ["University of Twente", "Enschede"]
    assert captured["headers"] == {"Authorization": "Token k"}
