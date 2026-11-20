"""Logging for the whole backend: one setup, and helpers that keep secrets and bulk out of it.

    LOG_LEVEL=debug uvicorn app.main:app      # DEBUG, INFO (the default), WARNING, ERROR
    LOG_FILE=/data/watchtower.log             # also write to this file (optional)
    LOG_FORMAT=json                           # JSON lines on stdout with portal_id and run_id (CONVENTIONS rule 12);
                                              # the default is readable text on stderr. The Dockerfile sets json.

Every module logs to a child of the `watchtower` logger (`watchtower.fetch`, `watchtower.loop`,
`watchtower.reader`, ...), so `LOG_LEVEL` can be set per area with `LOG_LEVEL_FETCH=debug`.

What is never logged (CLAUDE.md: "never write a key to a log"):
  * an API key: every line is scrubbed of `OPENAI_API_KEY`'s value and of anything shaped like
    `sk-...` before it is written, whatever called the logger;
  * a page, a prompt or a model answer in full: modules log sizes and short clips (`clip`);
  * the password, token, key and session parts of an address (`safe_url`).

At DEBUG a line says what was decided and why (the inputs and the result), so that a portal that
reads `failed` can be followed from the request to the state.
"""
from __future__ import annotations

import functools
import json
import logging
import os
import re
import sys
import time
from collections.abc import Callable, Mapping
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

ROOT = "watchtower"
FORMAT = "%(asctime)s.%(msecs)03d %(levelname)-7s %(name)s: %(message)s"
DATE_FORMAT = "%H:%M:%S"
_SECRET_SHAPE = re.compile(r"\bsk-[A-Za-z0-9_\-]{8,}")
_SECRET_NAMES = re.compile(r"(token|key|secret|passw|pwd|session|sid|auth|signature|jwt|credential)", re.I)
_MARK = "_watchtower_handler"
_PORTAL_ID = re.compile(r"\bportal ([0-9a-f]{12})\b")
_RUN_ID = re.compile(r"\brun ([0-9a-f]{32})\b")


class JsonFormatter(logging.Formatter):
    """One JSON object per line: time, level, area, message, and the portal and run it is about when the line says."""

    def format(self, record: logging.LogRecord) -> str:
        message = record.getMessage()
        out: dict[str, Any] = {"ts": self.formatTime(record, "%Y-%m-%dT%H:%M:%S") + f".{int(record.msecs):03d}",
                               "level": record.levelname, "logger": record.name}
        if message.startswith("{"):  # a line that is already an event (the agent runner's)
            try:
                event = json.loads(message)
                if isinstance(event, dict):
                    out.update(event)
                    message = ""
            except ValueError:
                pass
        if message:
            out["message"] = message
            for key, pattern in (("portal_id", _PORTAL_ID), ("run_id", _RUN_ID)):
                found = pattern.search(message)
                if found:
                    out[key] = found.group(1)
        if record.exc_info:
            out["exception"] = self.formatException(record.exc_info)
        return json.dumps(out, ensure_ascii=False, default=str)


class Scrub(logging.Filter):
    """Replaces a secret in a finished log line by `***`. A filter on the handler, so no caller can skip it."""

    def __init__(self, environ: Mapping[str, str] | None = None) -> None:
        super().__init__()
        self._environ = os.environ if environ is None else environ

    def filter(self, record: logging.LogRecord) -> bool:
        text = record.getMessage()
        key = self._environ.get("OPENAI_API_KEY", "").strip()
        if len(key) >= 8:
            text = text.replace(key, "***")
        scrubbed = _SECRET_SHAPE.sub("***", text)
        if scrubbed != record.getMessage():
            record.msg, record.args = scrubbed, None
        return True


def configure_logging(environ: Mapping[str, str] | None = None) -> None:
    """Set the `watchtower` logger up once: level from LOG_LEVEL, stderr, and LOG_FILE when set. Safe to call again."""
    env = os.environ if environ is None else environ
    root = logging.getLogger(ROOT)
    root.setLevel(_level(env.get("LOG_LEVEL"), logging.INFO))
    for name, value in env.items():  # LOG_LEVEL_FETCH=debug -> watchtower.fetch
        if name.startswith("LOG_LEVEL_") and value.strip():
            logging.getLogger(f"{ROOT}.{name[len('LOG_LEVEL_'):].lower()}").setLevel(_level(value, logging.INFO))
    if any(getattr(h, _MARK, False) for h in root.handlers):
        return
    as_json = env.get("LOG_FORMAT", "").strip().lower() == "json"
    formatter: logging.Formatter = JsonFormatter() if as_json else logging.Formatter(FORMAT, DATE_FORMAT)
    handlers: list[logging.Handler] = [logging.StreamHandler(sys.stdout if as_json else sys.stderr)]
    if env.get("LOG_FILE", "").strip():
        handlers.append(logging.FileHandler(env["LOG_FILE"].strip(), encoding="utf-8"))
    for handler in handlers:
        handler.setFormatter(formatter)
        handler.addFilter(Scrub(env))
        setattr(handler, _MARK, True)
        root.addHandler(handler)


def _level(raw: str | None, default: int) -> int:
    if not raw or not raw.strip():
        return default
    level = logging.getLevelName(raw.strip().upper())
    return level if isinstance(level, int) else default


def get(area: str) -> logging.Logger:
    """The logger of one area of the backend: `get("fetch")` is `watchtower.fetch`."""
    return logging.getLogger(f"{ROOT}.{area}")


# == Helpers for what goes into a line ==

def clip(value: Any, limit: int = 160) -> str:
    """A short, single-line form of anything, for a line that must not hold a whole page or answer."""
    text = value if isinstance(value, str) else repr(value)
    text = " ".join(text.split())
    return text if len(text) <= limit else f"{text[:limit]}... (+{len(text) - limit} chars)"


def safe_url(url: str) -> str:
    """An address without its user, password and fragment, and with the values of secret-looking parameters hidden."""
    try:
        parts = urlsplit(url)
        host = parts.hostname or ""
        if parts.port:
            host = f"{host}:{parts.port}"
        query = urlencode([(k, "***" if _SECRET_NAMES.search(k) else v) for k, v in parse_qsl(parts.query, keep_blank_values=True)])
        return urlunsplit((parts.scheme, host, parts.path, query, ""))
    except ValueError:
        return clip(url, 120)


def safe_mapping(values: Mapping[str, Any] | None) -> dict[str, Any]:
    """A copy of headers, parameters or a body with the secret-looking entries hidden and the values clipped."""
    return {k: "***" if _SECRET_NAMES.search(str(k)) else clip(v, 80) for k, v in (values or {}).items()}


def timed(logger: logging.Logger, name: str, describe: Callable[..., str] | None = None,
          summarize: Callable[[Any], str] | None = None) -> Callable:
    """Decorator: a DEBUG line when the function starts (what `describe` says of its arguments) and when it ends
    (how long it took and what `summarize` says of its result), or when it raises. Costs nothing above DEBUG."""
    def decorate(function: Callable) -> Callable:
        @functools.wraps(function)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            if not logger.isEnabledFor(logging.DEBUG):
                return function(*args, **kwargs)
            about = ""
            try:
                about = f" {describe(*args, **kwargs)}" if describe else ""
            except Exception:  # a log line must never break the call
                pass
            logger.debug("%s starts%s", name, about)
            began = time.monotonic()
            try:
                result = function(*args, **kwargs)
            except BaseException as error:
                logger.debug("%s raised %s after %.2fs: %s", name, type(error).__name__, time.monotonic() - began, clip(error))
                raise
            try:
                summary = f": {summarize(result)}" if summarize else ""
            except Exception:
                summary = ""
            logger.debug("%s took %.2fs%s", name, time.monotonic() - began, summary)
            return result
        return wrapper
    return decorate
