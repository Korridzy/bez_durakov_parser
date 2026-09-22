"""Shared structlog and standard-library logging configuration."""

import datetime
import decimal
import enum
import logging
import os
import pathlib
import sys
import uuid
from collections.abc import Mapping
from typing import TextIO, cast

import structlog

from bd_shared.log_redaction import redact_sensitive

ENV_LEVEL = "BD_LOG_LEVEL"
ENV_FORMAT = "BD_LOG_FORMAT"
ENV_ENVIRONMENT = "BD_ENVIRONMENT"
ENV_VERSION = "BD_APP_VERSION"

DEFAULT_LEVEL = "INFO"
DEFAULT_FORMAT = "console"
DEFAULT_ENVIRONMENT = "development"
DEFAULT_VERSION = "unknown"

LOG_FORMATS = ("json", "console")

THIRD_PARTY_LEVELS: Mapping[str, str] = {
    "LiteLLM": "WARNING",
    "LiteLLM Proxy": "WARNING",
    "LiteLLM Router": "WARNING",
    "httpx": "WARNING",
    "httpcore": "WARNING",
    "sqlalchemy.engine": "WARNING",
    "uvicorn.access": "WARNING",
    "apscheduler": "INFO",
}

_configured: str | None = None


def _level_number(level: str) -> int:
    normalized = level.upper()
    levels = logging.getLevelNamesMapping()
    if normalized not in levels:
        raise ValueError(f"Unknown log level: {level!r}")
    return levels[normalized]


def _json_default(value: object) -> object:
    if isinstance(value, datetime.datetime):
        return value.isoformat()
    if isinstance(value, pathlib.PurePath):
        return str(value)
    if isinstance(value, (uuid.UUID, decimal.Decimal)):
        return str(value)
    if isinstance(value, enum.Enum):
        return cast(object, value.value)
    return f"<{type(value).__name__}>"


def configure_logging(
    service_name: str,
    *,
    level: str | None = None,
    log_format: str | None = None,
    environment: str | None = None,
    version: str | None = None,
    logger_levels: Mapping[str, str] | None = None,
    stream: TextIO | None = None,
) -> None:
    """Configure the process-wide stdlib and structlog logging pipeline once."""
    global _configured

    if _configured is not None:
        if _configured == service_name:
            return
        raise RuntimeError(
            f"Logging is already configured for service {_configured!r}; cannot configure it for {service_name!r}"
        )

    resolved_level = level if level is not None else os.getenv(ENV_LEVEL, DEFAULT_LEVEL)
    resolved_format = (
        log_format
        if log_format is not None
        else os.getenv(ENV_FORMAT, DEFAULT_FORMAT)
    )
    resolved_environment = (
        environment
        if environment is not None
        else os.getenv(ENV_ENVIRONMENT, DEFAULT_ENVIRONMENT)
    )
    resolved_version = (
        version if version is not None else os.getenv(ENV_VERSION, DEFAULT_VERSION)
    )

    root_level = _level_number(resolved_level)
    if resolved_format not in LOG_FORMATS:
        raise ValueError(
            f"Unknown log format: {resolved_format!r}; expected one of {LOG_FORMATS!r}"
        )

    numeric_third_party_levels = {
        name: _level_number(logger_level)
        for name, logger_level in THIRD_PARTY_LEVELS.items()
    }
    numeric_logger_levels = {
        name: _level_number(logger_level)
        for name, logger_level in (logger_levels or {}).items()
    }

    def _add_static_fields(
        logger: object,
        method_name: str,
        event_dict: structlog.typing.EventDict,
    ) -> structlog.typing.EventDict:
        del logger, method_name
        event_dict["service"] = service_name
        event_dict["environment"] = resolved_environment
        event_dict["version"] = resolved_version
        return event_dict

    shared_processors: list[structlog.typing.Processor] = [
        structlog.contextvars.merge_contextvars,
        structlog.stdlib.add_logger_name,
        structlog.stdlib.add_log_level,
        structlog.stdlib.PositionalArgumentsFormatter(),
        structlog.processors.TimeStamper(fmt="iso", utc=True, key="timestamp"),
        structlog.processors.StackInfoRenderer(),
        structlog.processors.CallsiteParameterAdder(
            parameters=[
                structlog.processors.CallsiteParameter.MODULE,
                structlog.processors.CallsiteParameter.LINENO,
                structlog.processors.CallsiteParameter.FUNC_NAME,
            ]
        ),
        _add_static_fields,
        structlog.processors.UnicodeDecoder(),
    ]

    output_stream = stream or sys.stderr
    stream_is_a_tty = bool(getattr(output_stream, "isatty", lambda: False)())
    if resolved_format == "json":
        exception_step = structlog.processors.ExceptionRenderer(
            structlog.processors.ExceptionDictTransformer(
                show_locals=False, max_frames=50
            )
        )
        renderer = structlog.processors.JSONRenderer(
            ensure_ascii=False, default=_json_default
        )
    else:
        exception_step = structlog.processors.format_exc_info
        renderer = structlog.dev.ConsoleRenderer(colors=stream_is_a_tty)

    formatter = structlog.stdlib.ProcessorFormatter(
        foreign_pre_chain=[structlog.stdlib.ExtraAdder(), *shared_processors],
        processors=[
            structlog.stdlib.ProcessorFormatter.remove_processors_meta,
            exception_step,
            cast(structlog.typing.Processor, redact_sensitive),
            renderer,
        ],
    )
    handler = logging.StreamHandler(output_stream)
    handler.setFormatter(formatter)

    root_logger = logging.getLogger()
    for existing_handler in root_logger.handlers[:]:
        root_logger.removeHandler(existing_handler)
    root_logger.addHandler(handler)
    root_logger.setLevel(root_level)

    for logger_name, logger_level in numeric_third_party_levels.items():
        logging.getLogger(logger_name).setLevel(logger_level)
    for logger_name, logger_level in numeric_logger_levels.items():
        logging.getLogger(logger_name).setLevel(logger_level)

    structlog.configure(
        processors=[
            *shared_processors,
            structlog.stdlib.ProcessorFormatter.wrap_for_formatter,
        ],
        wrapper_class=structlog.stdlib.BoundLogger,
        logger_factory=structlog.stdlib.LoggerFactory(),
        cache_logger_on_first_use=False,
    )

    _configured = service_name


def adopt_third_party_loggers(*names: str) -> None:
    """Remove vendor-installed handlers so named loggers use the root pipeline."""
    for name in names:
        logger = logging.getLogger(name)
        for handler in logger.handlers[:]:
            logger.removeHandler(handler)
        logger.propagate = True


def get_logger(name: str | None = None) -> structlog.stdlib.BoundLogger:
    """Return a structlog logger backed by the standard-library logger factory."""
    return cast(structlog.stdlib.BoundLogger, structlog.get_logger(name))


def _reset_for_tests() -> None:
    """Reset global logging state used by this module's isolated unit tests."""
    global _configured

    _configured = None
    root_logger = logging.getLogger()
    for handler in root_logger.handlers[:]:
        root_logger.removeHandler(handler)
    structlog.reset_defaults()
    structlog.contextvars.clear_contextvars()
