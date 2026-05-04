"""Unit tests for pipeline-internal helpers in ``bitpart.tts.pipeline``.

Kept narrow: only the small pure helpers that benefit from direct unit coverage.
End-to-end pipeline behavior is exercised by the CLI subprocess tests in
``tests/test_cli.py`` and the higher-level fixtures elsewhere.
"""
from bitpart.tts.config import DEFAULT_RETRY_COUNT
from bitpart.tts.pipeline import _load_retry_count

ENV_VAR = "BITPART_TTS_RETRY_COUNT"


def test_load_retry_count_default_when_env_unset(monkeypatch):
    monkeypatch.delenv(ENV_VAR, raising=False)
    assert _load_retry_count() == DEFAULT_RETRY_COUNT


def test_load_retry_count_reads_valid_env_value(monkeypatch):
    monkeypatch.setenv(ENV_VAR, "5")
    assert _load_retry_count() == 5


def test_load_retry_count_clamps_negative_to_zero(monkeypatch):
    monkeypatch.setenv(ENV_VAR, "-3")
    assert _load_retry_count() == 0


def test_load_retry_count_falls_back_on_unparseable(monkeypatch):
    monkeypatch.setenv(ENV_VAR, "not-a-number")
    assert _load_retry_count() == DEFAULT_RETRY_COUNT
