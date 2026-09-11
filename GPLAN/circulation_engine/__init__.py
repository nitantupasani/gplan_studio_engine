"""Headless circulation on an immutable existing floorplan.

This package deliberately does not import the legacy GUI circulation module.
"""

from .models import CirculationError
from .registry import get_capabilities
from .service import generate_circulation, validate_circulation

__all__ = ["CirculationError", "get_capabilities", "generate_circulation", "validate_circulation"]
