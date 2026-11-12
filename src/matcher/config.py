"""Settings from environment variables, validated all at once at startup."""

import os
from dataclasses import dataclass

LOG_LEVELS = ("debug", "info", "warning", "error")
MIN_TOKEN_LEN = 16


@dataclass(frozen=True)
class Settings:
    token: str
    host: str = "0.0.0.0"
    port: int = 8000
    log_level: str = "info"

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
        )
