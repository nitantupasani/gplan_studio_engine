"""Wire-schema constants and a dependency-free shape check for structural_model.

The wire shape is produced by StructuralModel.to_dict(): snake_case keys, plan
geometry in FEET (y-down, origin top-left), section dimensions in millimetres,
engineering quantities in SI. Every numeric key carries a unit suffix.
"""

from __future__ import annotations

from typing import Any, Dict, List

STRUCTURAL_SCHEMA_VERSION = "structural-1.0"

# api-backend validates the major prefix only; minor bumps are additive.
STRUCTURAL_SCHEMA_MAJOR = "structural-1"

UNITS = {
    "geometry": "ft",
    "sections": "mm",
    "forces": "kN",
    "moments": "kNm",
    "loads": "kPa",
    "stresses": "MPa",
}

REQUIRED_TOP_LEVEL_KEYS = (
    "schema_version",
    "id",
    "source",
    "system",
    "fingerprint",
    "units",
    "meta",
    "storeys",
    "axes",
    "walls",
    "rooms",
    "cores",
    "columns",
    "beams",
    "slabs",
    "bands",
    "lintels",
    "footings",
    "loads",
    "seismic",
    "analysis",
    "design",
    "quantities",
    "warnings",
)

LIST_TOP_LEVEL_KEYS = (
    "storeys",
    "walls",
    "rooms",
    "cores",
    "columns",
    "beams",
    "slabs",
    "bands",
    "lintels",
    "footings",
    "design",
    "warnings",
)

# Unit suffixes allowed on numeric wire keys (the audit in tests uses this set).
UNIT_SUFFIXES = (
    "_ft",
    "_mm",
    "_m2",
    "_sqft",
    "_kn",
    "_knm",
    "_kpa",
    "_mpa",
    "_kg",
    "_m3",
    "_pct",
    "_s",
    "_deg",
)

# Numeric keys that are counts, indices or codes, so carry no unit.
NON_DIMENSIONAL_KEYS = frozenset(
    [
        "index",
        "count",
        "level",
        "storey",
        "storeys",
        "rot",
        "score",
        "layer",
        "legs",
        "ratio",
        "utilization",
        "zone",
    ]
)


def validate_wire(d: Any) -> List[str]:
    """Light structural check of a wire dict; returns a list of problem strings."""
    problems = []  # type: List[str]
    if not isinstance(d, dict):
        return ["structural_model must be an object, got " + type(d).__name__]

    version = d.get("schema_version")
    if not isinstance(version, str):
        problems.append("schema_version missing or not a string")
    elif not version.startswith(STRUCTURAL_SCHEMA_MAJOR):
        problems.append(
            "schema_version major mismatch: expected "
            + STRUCTURAL_SCHEMA_MAJOR
            + ".x, got "
            + version
        )

    for key in REQUIRED_TOP_LEVEL_KEYS:
        if key not in d:
            problems.append("missing required key: " + key)

    for key in LIST_TOP_LEVEL_KEYS:
        if key in d and not isinstance(d[key], list):
            problems.append(key + " must be a list")

    units = d.get("units")
    if not isinstance(units, dict):
        problems.append("units block missing or not an object")
    else:
        for key in sorted(UNITS):
            if units.get(key) != UNITS[key]:
                problems.append(
                    "units." + key + " must be " + UNITS[key] + ", got " + repr(units.get(key))
                )

    axes = d.get("axes")
    if not isinstance(axes, dict):
        problems.append("axes must be an object with x and y lists")
    else:
        for key in ("x", "y"):
            if not isinstance(axes.get(key), list):
                problems.append("axes." + key + " must be a list")

    return problems


def units_block() -> Dict[str, str]:
    """A fresh copy of the units block, safe to embed in a response."""
    return dict(UNITS)
