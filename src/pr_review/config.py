"""Validated runtime review settings, without provider requests."""
from decimal import Decimal, InvalidOperation
import os
import re

from pr_review.core import DEFAULT_MODEL, ReviewError


def _setting(name, default):
    raw = os.environ.get(name)
    return default if raw is None or not raw.strip() else raw


def _model_id(model):
    if not isinstance(model, str) or not re.fullmatch(r"claude-[a-z0-9-]+", model):
        raise ReviewError(
            "configuration: CLAUDE_MODEL must be a Claude model identifier "
            "matching claude-[a-z0-9-]+",
            stage="configuration", code="configuration.invalid_model")
    return model


def selected_model():
    """Read the requested provider model at runtime; blank uses the default."""
    return _model_id(_setting("CLAUDE_MODEL", DEFAULT_MODEL))


def _enum(name, default, choices):
    value = _setting(name, default)
    if value not in choices:
        raise ReviewError(
            f"configuration: {name} must be one of {', '.join(choices)}",
            stage="configuration", code="config.invalid_controls")
    return value


def _integer(name, default, minimum, maximum):
    raw = _setting(name, str(default))
    # ASCII digits only: reject floats, signs and accidental surrounding spaces.
    # Cap the representation before int() to avoid Python's oversized-int error.
    if not re.fullmatch(r"[0-9]+", raw) or len(raw) > 9:
        value = None
    else:
        value = int(raw)
    if value is None or not minimum <= value <= maximum:
        raise ReviewError(
            f"configuration: {name} must be an integer from {minimum} to {maximum}",
            stage="configuration", code="config.invalid_controls")
    return value


def review_controls():
    """Resolve mutable operational controls within fixed resource guardrails.

    Every call reads the environment. The JSON-compatible result is suitable
    for the offline configuration preview and review/cache provenance.
    """
    return {
        "mode": _enum("CLAUDE_REVIEW_MODE", "context", ("context", "diff")),
        "fail_severity": _enum("CLAUDE_FAIL_SEVERITY", "high",
                               ("low", "medium", "high", "critical", "none")),
        "research_calls": _integer("CLAUDE_MAX_EXPLORATION_CALLS", 4, 0, 8),
        "tool_operations": _integer("CLAUDE_MAX_TOOL_OPERATIONS", 12, 1, 100),
        "input_tokens": _integer("CLAUDE_MAX_INPUT_TOKENS", 24000, 4096, 128000),
        "research_output": _integer("CLAUDE_EXPLORATION_MAX_OUTPUT_TOKENS", 2000, 1, 16000),
        "final_output": _integer("CLAUDE_FINAL_MAX_OUTPUT_TOKENS", 4000, 1, 16000),
    }


def cache_only_mode():
    """Execution-only switch; must not invalidate the cache it is meant to reuse."""
    return _enum("CLAUDE_CACHE_ONLY", "false", ("true", "false")) == "true"


def effective_config(model=None):
    """Return safe effective settings without reading credentials or calling APIs."""
    model = selected_model() if model is None else _model_id(model)
    return {"model": model, "budget": review_budget(model), "controls": review_controls()}


def _positive_decimal(name, default=None):
    raw = os.environ.get(name)
    if raw is None or not raw.strip():
        raw = default
    if raw is None:
        return None
    try:
        value = Decimal(raw)
    except (InvalidOperation, ValueError):
        raise ReviewError(
            f"configuration: {name} must be a finite positive decimal",
            stage="configuration", code="configuration.invalid_budget") from None
    if not value.is_finite() or value <= 0:
        raise ReviewError(
            f"configuration: {name} must be a finite positive decimal",
            stage="configuration", code="configuration.invalid_budget")
    # Avoid float conversion and Decimal.normalize()'s context-dependent rounding.
    text = format(value, "f")
    return text.rstrip("0").rstrip(".") if "." in text else text


def review_budget(model):
    """Resolve prices per million tokens and an optional review cost ceiling.

    The tested default has historical 1/5 USD rates. Other model identifiers
    require explicit prices so choosing a model never silently reuses Haiku's
    budget estimate. None for max_cost preserves the caller's mode ceiling.
    Blank Actions variables count as unset. Read on every call; canonical
    decimal strings also serve cache identity.
    """
    input_rate = _positive_decimal(
        "CLAUDE_INPUT_USD_PER_MILLION", "1" if model == DEFAULT_MODEL else None)
    output_rate = _positive_decimal(
        "CLAUDE_OUTPUT_USD_PER_MILLION", "5" if model == DEFAULT_MODEL else None)
    if input_rate is None or output_rate is None:
        raise ReviewError(
            "configuration: non-default CLAUDE_MODEL requires both "
            "CLAUDE_INPUT_USD_PER_MILLION and CLAUDE_OUTPUT_USD_PER_MILLION",
            stage="configuration", code="configuration.missing_prices")
    return {"input_rate": input_rate, "output_rate": output_rate,
            "max_cost": _positive_decimal("CLAUDE_MAX_REVIEW_USD")}
