import pytest

from matcher.config import Settings


def test_defaults(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MATCHER_TOKEN", "t" * 16)
    for name in ("MATCHER_PORT", "MATCHER_HOST", "LOG_LEVEL"):
        monkeypatch.delenv(name, raising=False)
    s = Settings.from_env()
    assert (s.host, s.port, s.log_level) == ("0.0.0.0", 8000, "info")


def test_reports_every_error_at_once(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MATCHER_TOKEN", "short")
    monkeypatch.setenv("MATCHER_PORT", "70000")
    monkeypatch.setenv("LOG_LEVEL", "loud")
    with pytest.raises(ValueError, match="MATCHER_TOKEN") as e:
        Settings.from_env()
    assert "MATCHER_PORT" in str(e.value)
    assert "LOG_LEVEL" in str(e.value)
