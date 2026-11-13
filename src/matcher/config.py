"""Settings from environment variables, validated all at once at startup."""

import os
from dataclasses import dataclass
from pathlib import Path

LOG_LEVELS = ("debug", "info", "warning", "error")
MIN_TOKEN_LEN = 16


@dataclass(frozen=True)
class Settings:
    token: str
    host: str = "0.0.0.0"
    port: int = 8000
    log_level: str = "info"
    mlflow_uri: str | None = None  # MLFLOW_TRACKING_URI: where model versions come from
    cache_dir: Path = Path(".cache/models")  # MATCHER_CACHE_DIR: downloaded model versions
    embedding_dir: Path | None = None  # MATCHER_EMBEDDING_DIR: required for readiness if set

    @classmethod
    def from_env(cls) -> Settings:
        """Read MATCHER_* and LOG_LEVEL; raise ValueError listing every problem."""
        errors: list[str] = []
        token = os.environ.get("MATCHER_TOKEN", "")
        if len(token) < MIN_TOKEN_LEN:
            errors.append(f"MATCHER_TOKEN must be set, at least {MIN_TOKEN_LEN} characters")
        port_raw = os.environ.get("MATCHER_PORT", "8000")
        port = int(port_raw) if port_raw.isdigit() else -1
        if not 0 < port < 65536:
            errors.append(f"MATCHER_PORT must be 1-65535, got {port_raw!r}")
        log_level = os.environ.get("LOG_LEVEL", "info").lower()
        if log_level not in LOG_LEVELS:
            errors.append(f"LOG_LEVEL must be one of {', '.join(LOG_LEVELS)}, got {log_level!r}")
        if errors:
            raise ValueError("; ".join(errors))
        return cls(
            token=token,
            host=os.environ.get("MATCHER_HOST", "0.0.0.0"),
            port=port,
            log_level=log_level,
            mlflow_uri=os.environ.get("MLFLOW_TRACKING_URI") or None,
            cache_dir=Path(os.environ.get("MATCHER_CACHE_DIR", ".cache/models")),
            embedding_dir=Path(e) if (e := os.environ.get("MATCHER_EMBEDDING_DIR")) else None,
        )
