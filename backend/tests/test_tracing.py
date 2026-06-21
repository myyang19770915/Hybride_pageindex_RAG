import pytest
from app.core import tracing
from app.core.config import get_settings


@pytest.fixture
def reset_tracing():
    tracing._initialized = False
    tracing._tracer = None
    yield
    tracing._initialized = False
    tracing._tracer = None
    get_settings.cache_clear()


def test_tracing_is_noop_without_endpoint(reset_tracing, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PHOENIX_ENDPOINT", "")
    get_settings.cache_clear()

    assert tracing.configure_tracing() is False
    with tracing.span("retrieval.pipeline", {"k": "v"}) as current:
        assert current is None
    tracing.add_event("noop")  # must not raise


def test_tracing_configures_exporter_with_endpoint(
    reset_tracing, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("PHOENIX_ENDPOINT", "http://127.0.0.1:6006/v1/traces")
    get_settings.cache_clear()

    # Validates that the provider + OTLP exporter are constructed. We avoid
    # emitting a span here so the background exporter does not try to reach a
    # live collector during the test run.
    assert tracing.configure_tracing() is True
    assert tracing._tracer is not None
