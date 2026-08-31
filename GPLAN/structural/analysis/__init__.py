"""Analysis package: the shared force contract every designer consumes.

Critic resolution 20 makes this module the ONE place the design wave reads
member forces from: `ForceEnvelope` carries per-station signed envelope values
(m_pos_max_knm / m_neg_min_knm / v_max_kn / n_max_kn / n_min_kn), the "slab"
element type carries the combined pressures {w_u_kpa, w_service_kpa}, and the
three converters `to_beam_forces` / `to_column_forces` / `to_slab_load` return
the plain dataclasses (`BeamForces`, `ColumnForces`, `SlabLoad`) the designers
take as input.  `analysis/takedown.py` builds envelopes for the gravity path;
`analysis/diaphragm.py` and `analysis/frame_fe.py` (parallel work) plug their
results into the same shapes.

Sign conventions (spec section 1): gravity positive downward, sagging moment
positive, axial compression positive.  Envelope stations are parametric 0..1
along the element from its own `a` end; the takedown emits three stations
(ends + mid), the FE phase eleven.  The mid station's `m_pos_max_knm` carries
the largest sagging moment anywhere in the span, not just the value at 0.5,
so a designer reading three stations never under-reads a span maximum.

`governing` maps a quantity name ("m_pos", "m_neg", "v", "n") to the id of the
combination that produced the enveloped value.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, Optional, Tuple

__all__ = [
    "StationForces",
    "ForceEnvelope",
    "BeamForces",
    "ColumnForces",
    "SlabLoad",
    "to_beam_forces",
    "to_column_forces",
    "to_slab_load",
]

_DP = 6


def _r(value: float) -> float:
    return round(float(value), _DP) + 0.0


def _r_opt(value: Optional[float]) -> Optional[float]:
    return None if value is None else _r(value)


@dataclass(frozen=True)
class StationForces:
    """Signed envelope values at one parametric station along an element."""

    station: float
    m_pos_max_knm: float = 0.0
    m_neg_min_knm: float = 0.0
    v_max_kn: float = 0.0  # largest absolute shear at the station
    n_max_kn: float = 0.0  # axial, compression positive
    n_min_kn: float = 0.0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "station": _r(self.station),
            "m_pos_max_knm": _r(self.m_pos_max_knm),
            "m_neg_min_knm": _r(self.m_neg_min_knm),
            "v_max_kn": _r(self.v_max_kn),
            "n_max_kn": _r(self.n_max_kn),
            "n_min_kn": _r(self.n_min_kn),
        }

    @staticmethod
    def from_dict(d: Dict[str, Any]) -> "StationForces":
        return StationForces(
            station=float(d["station"]),
            m_pos_max_knm=float(d.get("m_pos_max_knm", 0.0)),
            m_neg_min_knm=float(d.get("m_neg_min_knm", 0.0)),
            v_max_kn=float(d.get("v_max_kn", 0.0)),
            n_max_kn=float(d.get("n_max_kn", 0.0)),
            n_min_kn=float(d.get("n_min_kn", 0.0)),
        )


@dataclass
class ForceEnvelope:
    """Combination-enveloped forces for one element; THE designer contract.

    element_type is "beam" | "column" | "wall" | "footing" | "slab".  A slab
    envelope carries no stations and instead the combined pressures
    `w_u_kpa` (limit state) and `w_service_kpa`.  A wall envelope's axial
    values are per metre of wall (kN/m), noted in `units_note`.  `storey` and
    `length_m` ride along for the column converter (unsupported length in v1
    is the floor-to-floor height; the design side applies effective-length
    factors).  `method` is "coeff" | "exact" | "takedown" | "fe:<backend>".
    """

    element_id: str
    element_type: str
    stations: Tuple[StationForces, ...] = ()
    method: str = "takedown"
    governing: Dict[str, str] = field(default_factory=dict)
    w_u_kpa: Optional[float] = None
    w_service_kpa: Optional[float] = None
    storey: Optional[int] = None
    length_m: Optional[float] = None
    units_note: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "element_id": self.element_id,
            "element_type": self.element_type,
            "stations": [s.to_dict() for s in self.stations],
            "method": self.method,
            "governing": {k: self.governing[k] for k in sorted(self.governing)},
            "w_u_kpa": _r_opt(self.w_u_kpa),
            "w_service_kpa": _r_opt(self.w_service_kpa),
            "storey": None if self.storey is None else int(self.storey),
            "length_m": _r_opt(self.length_m),
            "units_note": self.units_note,
        }

    @staticmethod
    def from_dict(d: Dict[str, Any]) -> "ForceEnvelope":
        return ForceEnvelope(
            element_id=d["element_id"],
            element_type=d["element_type"],
            stations=tuple(StationForces.from_dict(s) for s in d.get("stations", [])),
            method=d.get("method", "takedown"),
            governing=dict(d.get("governing", {})),
            w_u_kpa=d.get("w_u_kpa"),
            w_service_kpa=d.get("w_service_kpa"),
            storey=d.get("storey"),
            length_m=d.get("length_m"),
            units_note=d.get("units_note", ""),
        )


# ---------------------------------------------------------------------------
# designer-facing shapes (the ONLY designer inputs, critic finding 20)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class BeamForces:
    """Design magnitudes for one beam span run element, kN and kNm positive."""

    mu_hog_end_a_knm: float
    mu_hog_end_b_knm: float
    mu_sag_mid_knm: float
    vu_a_kn: float
    vu_b_kn: float
    tu_knm: Optional[float] = None
    combo_tags: Tuple[Tuple[str, str], ...] = ()
    # Additive B17 contract: every shear station the analysis supplied,
    # expressed as (parametric station 0..1, absolute shear kN).  The empty
    # tuple preserves the legacy five-force constructor and tells the beam
    # designer that it must use its explicitly disclosed end-only fallback.
    shear_stations: Tuple[Tuple[float, float], ...] = ()

    def combo_map(self) -> Dict[str, str]:
        return dict(self.combo_tags)


@dataclass(frozen=True)
class ColumnForces:
    """Design actions for one column lift; moments are zero in the v1 gravity
    path (the design side applies the IS 456 Cl 25.4 minimum eccentricity)."""

    pu_kn: float
    mux_knm: float
    muy_knm: float
    lex_m: float
    ley_m: float
    storey: int


@dataclass(frozen=True)
class SlabLoad:
    """Combined slab pressures: factored and service, kPa."""

    w_u_kpa: float
    w_service_kpa: float


def _station_at(envelope: ForceEnvelope, where: float) -> StationForces:
    """The station nearest the parametric position, lowest station on a tie."""
    if not envelope.stations:
        return StationForces(station=where)
    best = envelope.stations[0]
    for station in envelope.stations:
        if abs(station.station - where) < abs(best.station - where) - 1e-12:
            best = station
    return best


def to_beam_forces(envelope: ForceEnvelope) -> BeamForces:
    """The design magnitudes a beam designer needs from one envelope.

    Hogging moments come back as positive magnitudes (the envelope stores them
    signed as m_neg_min); the sagging value is the largest m_pos_max across the
    stations, which the takedown parks on the mid station.
    """
    if envelope.element_type != "beam":
        raise ValueError("to_beam_forces expects a beam envelope, got " + envelope.element_type)
    end_a = _station_at(envelope, 0.0)
    end_b = _station_at(envelope, 1.0)
    sag = max([s.m_pos_max_knm for s in envelope.stations] or [0.0])
    return BeamForces(
        mu_hog_end_a_knm=max(0.0, -end_a.m_neg_min_knm),
        mu_hog_end_b_knm=max(0.0, -end_b.m_neg_min_knm),
        mu_sag_mid_knm=max(0.0, sag),
        vu_a_kn=abs(end_a.v_max_kn),
        vu_b_kn=abs(end_b.v_max_kn),
        tu_knm=None,
        combo_tags=tuple(sorted(envelope.governing.items())),
        shear_stations=tuple(
            (float(station.station), abs(float(station.v_max_kn)))
            for station in sorted(envelope.stations, key=lambda item: float(item.station))
        ),
    )


def to_column_forces(envelope: ForceEnvelope) -> ColumnForces:
    """The design actions a column designer needs from one envelope."""
    if envelope.element_type != "column":
        raise ValueError("to_column_forces expects a column envelope, got " + envelope.element_type)
    pu = max([s.n_max_kn for s in envelope.stations] or [0.0])
    length = envelope.length_m if envelope.length_m is not None else 0.0
    return ColumnForces(
        pu_kn=pu,
        mux_knm=0.0,
        muy_knm=0.0,
        lex_m=length,
        ley_m=length,
        storey=envelope.storey if envelope.storey is not None else 0,
    )


def to_slab_load(envelope: ForceEnvelope) -> SlabLoad:
    """The combined pressures a slab designer needs from one envelope."""
    if envelope.element_type != "slab":
        raise ValueError("to_slab_load expects a slab envelope, got " + envelope.element_type)
    return SlabLoad(
        w_u_kpa=envelope.w_u_kpa if envelope.w_u_kpa is not None else 0.0,
        w_service_kpa=envelope.w_service_kpa if envelope.w_service_kpa is not None else 0.0,
    )
