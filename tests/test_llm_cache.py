import pytest

from llm_cache import LLMCacheMiss, cached_call, hash_key, load, save

PROVIDER = "ollama"
MODEL = "llama3.1:8b"


def test_hash_key_deterministic_regardless_of_dict_order():
    a = hash_key(PROVIDER, MODEL, "extract requirements", {"scheme": "x", "page": 1})
    b = hash_key(PROVIDER, MODEL, "extract requirements", {"page": 1, "scheme": "x"})
    assert a == b


def test_hash_key_differs_for_different_prompts():
    a = hash_key(PROVIDER, MODEL, "prompt a", {"x": 1})
    b = hash_key(PROVIDER, MODEL, "prompt b", {"x": 1})
    assert a != b


def test_hash_key_differs_for_different_provider_or_model():
    base = hash_key(PROVIDER, MODEL, "p", {"x": 1})
    other_provider = hash_key("anthropic", MODEL, "p", {"x": 1})
    other_model = hash_key(PROVIDER, "llama3.1:70b", "p", {"x": 1})
    assert base != other_provider
    assert base != other_model


def test_replay_mode_never_calls_the_model(tmp_path):
    calls = []

    def call_fn():
        calls.append(1)
        return {"answer": "should not happen"}

    key = hash_key(PROVIDER, MODEL, "p", {"x": 1})
    save(key, PROVIDER, MODEL, "p", {"x": 1}, {"answer": 42}, cache_dir=tmp_path)

    result = cached_call(
        PROVIDER, MODEL, "p", {"x": 1}, call_fn, mode="replay", cache_dir=tmp_path
    )

    assert result == {"answer": 42}
    assert calls == []  # call_fn was never invoked


def test_replay_mode_raises_on_cache_miss_without_calling_model(tmp_path):
    calls = []

    def call_fn():
        calls.append(1)
        return "network response"

    with pytest.raises(LLMCacheMiss) as exc_info:
        cached_call(
            PROVIDER, MODEL, "never recorded", {}, call_fn, mode="replay", cache_dir=tmp_path
        )

    assert calls == []
    # the miss error must name the exact missing key so it can be hand-authored
    missing_key = hash_key(PROVIDER, MODEL, "never recorded", {})
    assert missing_key in str(exc_info.value)


def test_record_mode_calls_model_and_persists(tmp_path):
    calls = []

    def call_fn():
        calls.append(1)
        return {"answer": "fresh"}

    result = cached_call(
        PROVIDER, MODEL, "extract requirements", {"scheme": "y"}, call_fn,
        mode="record", cache_dir=tmp_path,
    )

    assert result == {"answer": "fresh"}
    assert calls == [1]

    key = hash_key(PROVIDER, MODEL, "extract requirements", {"scheme": "y"})
    assert load(key, cache_dir=tmp_path) == {"answer": "fresh"}


def test_record_mode_refreshes_existing_entry(tmp_path):
    key = hash_key(PROVIDER, MODEL, "p", {})
    save(key, PROVIDER, MODEL, "p", {}, "stale", cache_dir=tmp_path)

    result = cached_call(
        PROVIDER, MODEL, "p", {}, lambda: "fresh", mode="record", cache_dir=tmp_path
    )

    assert result == "fresh"
    assert load(key, cache_dir=tmp_path) == "fresh"


def test_live_mode_always_calls_and_never_persists(tmp_path):
    calls = []

    def call_fn():
        calls.append(1)
        return "live response"

    result = cached_call(PROVIDER, MODEL, "p", {}, call_fn, mode="live", cache_dir=tmp_path)

    assert result == "live response"
    assert calls == [1]
    assert load(hash_key(PROVIDER, MODEL, "p", {}), cache_dir=tmp_path) is None


def test_unknown_mode_raises():
    with pytest.raises(ValueError):
        cached_call(PROVIDER, MODEL, "p", {}, lambda: None, mode="bogus")


def test_mode_from_env_defaults_to_replay(tmp_path, monkeypatch):
    monkeypatch.delenv("KAGAZ_LLM_MODE", raising=False)
    with pytest.raises(LLMCacheMiss):
        cached_call(PROVIDER, MODEL, "p", {}, lambda: "x", cache_dir=tmp_path)


def test_mode_from_env_var(tmp_path, monkeypatch):
    monkeypatch.setenv("KAGAZ_LLM_MODE", "record")
    result = cached_call(PROVIDER, MODEL, "p", {}, lambda: "from-env-record", cache_dir=tmp_path)
    assert result == "from-env-record"
