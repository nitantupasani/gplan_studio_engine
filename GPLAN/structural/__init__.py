"""GPLAN structural: preliminary structural scheme, analysis, design and quantities.

The package is organised around one canonical data structure, `StructuralModel`
(model.py), which adapters write and every other submodule reads and extends.
Internal units are SI metres and kN; the wire shape emitted by `to_dict()` uses
feet for plan geometry and millimetres for section dimensions.

Nothing here computes a construction-ready design: every fallback and assumption
is disclosed on the model's ladder using the codes registered in `model.REGISTRY`.
"""

from __future__ import annotations

from .model import (
    FT,
    REGISTRY,
    AxisDir,
    AxisSource,
    BandKind,
    Beam,
    BeamKind,
    Band,
    Column,
    Core,
    CoreKind,
    Disclosure,
    DisclosureLog,
    Footing,
    FootingKind,
    GridAxis,
    Lintel,
    Material,
    ModelSource,
    Occupancy,
    Opening,
    OpeningKind,
    Provenance,
    RoomPoly,
    Severity,
    SlabKind,
    SlabPanel,
    Storey,
    StoreyKind,
    StructuralModel,
    System,
    WallLine,
    WallRole,
    add_disclosure,
    ft_to_m,
    m_to_ft,
    make_disclosure,
)
from .schema import STRUCTURAL_SCHEMA_MAJOR, STRUCTURAL_SCHEMA_VERSION, UNITS, validate_wire

__version__ = "structural-1.0"

__all__ = [
    "__version__",
    "FT",
    "REGISTRY",
    "STRUCTURAL_SCHEMA_MAJOR",
    "STRUCTURAL_SCHEMA_VERSION",
    "UNITS",
    "AxisDir",
    "AxisSource",
    "Band",
    "BandKind",
    "Beam",
    "BeamKind",
    "Column",
    "Core",
    "CoreKind",
    "Disclosure",
    "DisclosureLog",
    "Footing",
    "FootingKind",
    "GridAxis",
    "Lintel",
    "Material",
    "ModelSource",
    "Occupancy",
    "Opening",
    "OpeningKind",
    "Provenance",
    "RoomPoly",
    "Severity",
    "SlabKind",
    "SlabPanel",
    "Storey",
    "StoreyKind",
    "StructuralModel",
    "System",
    "WallLine",
    "WallRole",
    "add_disclosure",
    "ft_to_m",
    "m_to_ft",
    "make_disclosure",
    "validate_wire",
]
