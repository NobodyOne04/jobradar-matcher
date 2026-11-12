"""JSON logs on stdout (jobradar ADR 0009). Never log request bodies or profile content."""

import logging

import structlog


def configure(level: str) -> None:
    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,  # request_id bound per request
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso", key="ts"),
            structlog.processors.dict_tracebacks,
            structlog.processors.JSONRenderer(),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(
            logging.getLevelNamesMapping()[level.upper()]
        ),
        cache_logger_on_first_use=True,
    )


log = structlog.get_logger(service="matcher")
