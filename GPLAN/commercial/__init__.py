"""Metric commercial office programming and bounded whole-building generation."""

from .models import BriefError, SCHEMA_VERSION, normalize_brief
from .service import (
    estimate_commercial_fit, generate_commercial_options,
    validate_commercial_option, options, preview, generate, validate,
)

__all__ = [
    "BriefError", "SCHEMA_VERSION", "normalize_brief", "estimate_commercial_fit",
    "generate_commercial_options", "validate_commercial_option", "options",
    "preview", "generate", "validate",
]
