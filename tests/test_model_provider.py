import os
from pathlib import Path

import pytest

from model_provider import get_model


def test_ollama_provider_constructs_without_network(monkeypatch):
    monkeypatch.delenv("KAGAZ_MODEL_PROVIDER", raising=False)
    # Constructing an OllamaModel just stores config; it does not contact
    # the Ollama server. This must succeed even if no server is running.
    model = get_model("ollama")
    assert model is not None


def test_ollama_still_selectable_via_env(monkeypatch):
    monkeypatch.setenv("KAGAZ_MODEL_PROVIDER", "ollama")
    model = get_model()
    assert model is not None


def test_provider_defaults_to_vertex_when_env_unset(monkeypatch):
    monkeypatch.delenv("KAGAZ_MODEL_PROVIDER", raising=False)
    monkeypatch.delenv("GOOGLE_CLOUD_PROJECT", raising=False)
    # Constructing a GeminiModel just stores config; it does not contact
    # Vertex AI or require credentials until an Agent actually invokes it.
    model = get_model()
    assert model is not None


def test_anthropic_not_implemented_yet():
    with pytest.raises(NotImplementedError):
        get_model("anthropic")


def test_bedrock_raises_not_implemented_points_at_vertex():
    with pytest.raises(NotImplementedError, match="Vertex"):
        get_model("bedrock")


@pytest.mark.skipif(
    "GOOGLE_CLOUD_PROJECT" not in os.environ,
    reason="no GOOGLE_CLOUD_PROJECT configured for this environment yet",
)
def test_vertex_provider_constructs_without_network(monkeypatch):
    # Only runs once a project is configured. Constructing a GeminiModel
    # just stores config (model_id, client_args) — it does not call
    # Vertex AI or require Application Default Credentials to exist yet.
    monkeypatch.setenv("KAGAZ_VERTEX_MODEL_ID", "gemini-2.5-flash")
    monkeypatch.setenv("GOOGLE_CLOUD_LOCATION", "us-central1")
    model = get_model("vertex")
    assert model is not None


def test_vertex_import_is_lazy_not_at_module_scope():
    # GeminiModel (and therefore google-genai) must only be imported
    # inside the vertex branch of get_model(), not at module scope — so
    # importing model_provider, or using any other provider, never
    # requires google-genai to be installed.
    import model_provider

    source = Path(model_provider.__file__).read_text(encoding="utf-8")
    module_header = source.split("def get_model(", 1)[0]
    assert "GeminiModel" not in module_header


def test_unknown_provider_raises_value_error():
    with pytest.raises(ValueError):
        get_model("openai")


def test_ollama_model_id_and_host_are_configurable():
    model = get_model("ollama", model_id="qwen2.5:7b", host="http://localhost:11434")
    assert model is not None
