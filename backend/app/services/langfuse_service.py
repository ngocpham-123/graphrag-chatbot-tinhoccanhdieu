"""Langfuse observability — optional, fail-open.

Tracing must never break the chatbot: if the `langfuse` package is missing, the
keys are unset, or the Langfuse server is down, every helper here degrades to a
no-op and the request is served normally.

What gets traced (see backend/app/routers/chat.py and services/orchestrator.py):
  chat-request                trace root — user message in, final reply out
  ├─ condense-question        the "internal thinking": follow-up rewriting
  ├─ describe-image           vision description of an attached image
  ├─ sparql-retrieval         generated SPARQL + rows retrieved
  ├─ vector-retrieval         semantically similar passages
  └─ generate-answer          the final answer LLM call

The LangChain callback handler is attached to every LLM `.invoke()` so the raw
prompts, completions, model names and token usage land inside those spans.

Written against the Langfuse Python SDK v4 API (start_as_current_observation /
propagate_attributes / set_current_trace_io).
"""

import logging
from contextlib import contextmanager

from backend.app.config import (
    LANGFUSE_HOST,
    LANGFUSE_PUBLIC_KEY,
    LANGFUSE_SECRET_KEY,
)

logger = logging.getLogger(__name__)

_client = None
_callback_handler = None
_propagate_attributes = None
_enabled = False


def _init() -> None:
    """Create the Langfuse client once, at import time."""
    global _client, _callback_handler, _propagate_attributes, _enabled

    if not (LANGFUSE_PUBLIC_KEY and LANGFUSE_SECRET_KEY):
        logger.info("Langfuse disabled (LANGFUSE_PUBLIC_KEY/SECRET_KEY not set)")
        return

    try:
        from langfuse import Langfuse, propagate_attributes
        from langfuse.langchain import CallbackHandler
    except ImportError:
        logger.warning("Langfuse keys are set but the `langfuse` package is not installed")
        return

    try:
        _client = Langfuse(
            public_key=LANGFUSE_PUBLIC_KEY,
            secret_key=LANGFUSE_SECRET_KEY,
            host=LANGFUSE_HOST,
        )
        # CallbackHandler resolves the client from the SDK's global registry, so
        # it must be constructed after Langfuse().
        _callback_handler = CallbackHandler()
        _propagate_attributes = propagate_attributes
        _enabled = True
        logger.info("Langfuse tracing enabled (host=%s)", LANGFUSE_HOST)
    except Exception:
        logger.exception("Langfuse initialization failed; tracing disabled")
        _client = None
        _callback_handler = None
        _propagate_attributes = None
        _enabled = False


_init()


def is_enabled() -> bool:
    return _enabled


def langchain_config(**kwargs) -> dict:
    """A LangChain `config=` dict carrying the Langfuse callback handler.

    Returns a dict without callbacks when tracing is off, so call sites can pass
    it unconditionally: `llm.invoke(msg, config=langchain_config())`.
    """
    config = dict(kwargs)
    if _callback_handler is not None:
        config["callbacks"] = [_callback_handler]
    return config


class _NoopSpan:
    """Stands in for a Langfuse span when tracing is off or errored."""

    def update(self, **kwargs):
        return self


@contextmanager
def trace(
    name: str,
    input=None,
    session_id: str | None = None,
    user_id: str | None = None,
    tags: list[str] | None = None,
    metadata: dict | None = None,
):
    """Open a root observation and set the trace-level attributes on it.

    `session_id`/`user_id`/`tags` are propagated to every nested span, which is
    how a multi-turn conversation groups into one Langfuse session.
    """
    if not _enabled or _client is None:
        yield _NoopSpan()
        return

    try:
        attrs = _propagate_attributes(
            session_id=session_id, user_id=user_id, tags=tags, trace_name=name
        )
    except Exception:
        logger.exception("Langfuse trace start failed: %s", name)
        yield _NoopSpan()
        return

    with attrs:
        with _client.start_as_current_observation(
            name=name, input=input, metadata=metadata
        ) as root:
            set_trace_io(input=input)
            yield root


@contextmanager
def span(name: str, input=None, metadata=None, as_type: str = "span"):
    """Open a nested Langfuse span; yields a span object (or a no-op stand-in).

    The yielded object always accepts `.update(output=..., metadata=...)`, so
    callers need no `if enabled` branches.
    """
    if not _enabled or _client is None:
        yield _NoopSpan()
        return

    try:
        ctx = _client.start_as_current_observation(
            name=name, as_type=as_type, input=input, metadata=metadata
        )
    except Exception:
        logger.exception("Langfuse span start failed: %s", name)
        yield _NoopSpan()
        return

    with ctx as active:
        yield active


def set_trace_io(input=None, output=None) -> None:
    """Set the trace's top-level input/output (what the UI shows in the list)."""
    if not _enabled or _client is None:
        return
    try:
        _client.set_current_trace_io(input=input, output=output)
    except Exception:
        logger.exception("Langfuse set_current_trace_io failed")


def flush() -> None:
    """Push buffered events (Langfuse batches in a background thread)."""
    if not _enabled or _client is None:
        return
    try:
        _client.flush()
    except Exception:
        logger.exception("Langfuse flush failed")
