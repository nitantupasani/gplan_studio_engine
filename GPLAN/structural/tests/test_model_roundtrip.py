"""Pins for the canonical model: wire round-trip, unit suffixes, ids, invariants."""

from __future__ import annotations

import pytest

# Relative: the engine repo root carries its own __init__.py, so pytest imports this
# package as GPLAN.GPLAN.structural.tests, and an absolute GPLAN.structural import
# would resolve against the outer directory instead.
from .. import model as M
from ..schema import STRUCTURAL_SCHEMA_VERSION, validate_wire

FT = M.FT

# The wire contract: every numeric key ends in one of these ...
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

# ... or is one of these explicitly non-dimensional keys.
NON_DIMENSIONAL_KEYS = frozenset(["index", "count", "level", "storey", "storeys", "rot", "score"])

# Opaque slots carrying another submodule's serialized output verbatim.
OPAQUE_SLOTS = frozenset(["meta", "loads", "seismic", "analysis", "design", "quantities"])


def _wall(storey, wid, a, b, thickness_m, role, room_ids, openings=()):
    return M.WallLine(
        id=wid,
        storey=storey,
        a=a,
        b=b,
        thickness_m=thickness_m,
        role=role,
        material=M.Material.BRICK_MASONRY,
        bearing=None,
        openings=list(openings),
        room_ids=room_ids,
    )


def sample_model():
    """Two storeys, four rooms, a dressed door and an assumed door, one core, framing."""
    ext_t = 0.75 * FT
    int_t = 0.4 * FT

    storeys = [
        M.Storey(index=0, name="Ground", bottom_z_m=0.0, height_m=3.048, kind=M.StoreyKind.UNITS),
        M.Storey(index=1, name="First", bottom_z_m=3.048, height_m=3.048, kind=M.StoreyKind.ROOF),
    ]
    axes = [
        M.GridAxis(id=M.axis_id(M.AxisDir.X, "1"), dir=M.AxisDir.X, pos_m=0.0, label="1", source=M.AxisSource.OUTLINE, storeys=[0, 1]),
        M.GridAxis(id=M.axis_id(M.AxisDir.X, "2"), dir=M.AxisDir.X, pos_m=7.0, label="2", source=M.AxisSource.PARTY, storeys=[0, 1]),
        M.GridAxis(id=M.axis_id(M.AxisDir.Y, "A"), dir=M.AxisDir.Y, pos_m=0.0, label="A", source=M.AxisSource.OUTLINE, storeys=[0, 1]),
    ]

    rooms = [
        M.RoomPoly(
            id=M.room_id(0, "liv1"),
            storey=0,
            name="Living Room",
            occupancy=M.Occupancy.HABITABLE,
            polygon=[(0.0, 0.0), (7.0, 0.0), (7.0, 8.0), (0.0, 8.0)],
            area_m2=56.0,
        ),
        M.RoomPoly(
            id=M.room_id(0, "cor1"),
            storey=0,
            name="Corridor",
            occupancy=M.Occupancy.CORRIDOR,
            polygon=[(7.0, 0.0), (12.0, 0.0), (12.0, 8.0), (7.0, 8.0)],
            area_m2=40.0,
        ),
        M.RoomPoly(
            id=M.room_id(1, "bed1"),
            storey=1,
            name="Bedroom 1",
            occupancy=M.Occupancy.HABITABLE,
            polygon=[(0.0, 0.0), (7.0, 0.0), (7.0, 8.0), (0.0, 8.0)],
            area_m2=56.0,
        ),
        M.RoomPoly(
            id=M.room_id(1, "bal1"),
            storey=1,
            name="Balcony",
            occupancy=M.Occupancy.BALCONY,
            polygon=[(7.0, 0.0), (12.0, 0.0), (12.0, 8.0), (7.0, 8.0)],
            area_m2=40.0,
        ),
    ]

    walls = []
    for storey in (0, 1):
        ext_id = M.wall_id(storey, "h", 0.0, 0.0)
        int_id = M.wall_id(storey, "v", 7.0, 0.0)
        left = rooms[0].id if storey == 0 else rooms[2].id
        right = rooms[1].id if storey == 0 else rooms[3].id
        if storey == 0:
            door = M.Opening(
                id=M.opening_id(int_id, 0),
                kind=M.OpeningKind.DOOR,
                offset_m=3.5,
                width_m=0.9,
                sill_m=0.0,
                head_m=2.1,
                provenance=M.Provenance.DRESSED,
            )
        else:
            door = M.Opening(
                id=M.opening_id(int_id, 0),
                kind=M.OpeningKind.DOOR,
                offset_m=4.0,
                width_m=0.9,
                provenance=M.Provenance.ASSUMED_MID_WALL,
            )
        walls.append(_wall(storey, ext_id, (0.0, 0.0), (12.0, 0.0), ext_t, M.WallRole.EXTERIOR, (None, left)))
        walls.append(_wall(storey, int_id, (7.0, 0.0), (7.0, 8.0), int_t, M.WallRole.INTERIOR, (left, right), [door]))

    cores = [
        M.Core(
            id=M.core_id("stair-1"),
            kind=M.CoreKind.STAIRS,
            x_m=8.0,
            y_m=1.0,
            w_m=2.5,
            h_m=4.5,
            storeys=[0, 1],
            stair_landing_hint="north",
        )
    ]

    columns = [
        M.Column(
            id=M.column_id(0, "1", "A"),
            stack_id=M.stack_id("1", "A"),
            storey=0,
            x_m=0.0,
            y_m=0.0,
            width_m=0.23,
            depth_m=0.3,
            rot=0,
            on_grid=("1", "A"),
            placed_by="frame.corner_column",
            code_refs=["IS 456 Cl 26.5.3.1"],
        ),
        M.Column(
            id=M.column_id(0, "2", "A"),
            stack_id=M.stack_id("2", "A"),
            storey=0,
            x_m=7.0,
            y_m=0.0,
            width_m=0.23,
            depth_m=0.3,
            rot=90,
            on_grid=("2", "A"),
            placed_by="frame.wall_intersection",
        ),
    ]

    beams = [
        M.Beam(
            id=M.beam_id(0, M.AxisDir.Y, "A", 0),
            storey=0,
            a=(0.0, 0.0),
            b=(7.0, 0.0),
            width_m=0.23,
            depth_m=0.45,
            kind=M.BeamKind.PRIMARY,
            supports_wall_id=walls[0].id,
            placed_by="frame.beam_on_wall",
        ),
        M.Beam(
            id=M.beam_id(0, M.AxisDir.X, "2", 0),
            storey=0,
            a=(7.0, 0.0),
            b=(7.0, 8.0),
            width_m=0.23,
            depth_m=0.45,
            kind=M.BeamKind.SECONDARY,
            supports_wall_id=walls[1].id,
            placed_by="frame.beam_on_wall",
        ),
    ]

    slabs = [
        M.SlabPanel(
            id=M.slab_id(0, 0),
            storey=0,
            polygon=[(0.0, 0.0), (12.0, 0.0), (12.0, 8.0), (0.0, 8.0)],
            thickness_m=0.150,
            two_way=True,
            lx_m=7.0,
            ly_m=8.0,
            edge_continuity={"n": "discontinuous", "e": "discontinuous", "s": "continuous", "w": "discontinuous"},
            kind=M.SlabKind.FLOOR,
            support_ids=[beams[0].id, beams[1].id],
            placed_by="frame.slab_panel",
        )
    ]

    model = M.StructuralModel(
        id="model-test-1",
        source=M.ModelSource.BUILDING,
        system=M.System.RC_FRAME,
        fingerprint="0" * 64,
        meta={"north": "-y", "plinth_height_ft": 0.5, "storey_height_ft": 10.0},
        storeys=storeys,
        axes=axes,
        walls=walls,
        rooms=rooms,
        cores=cores,
        columns=columns,
        beams=beams,
        slabs=slabs,
        bands=[
            M.Band(
                id=M.band_id(M.BandKind.PLINTH, 0),
                kind=M.BandKind.PLINTH,
                storey=0,
                wall_ids=[walls[0].id],
                level_m=0.15,
                placed_by="masonry.band",
            )
        ],
        lintels=[
            M.Lintel(
                id=M.lintel_id(walls[1].id, 0),
                wall_id=walls[1].id,
                opening_id=walls[1].openings[0].id,
                span_m=1.2,
                placed_by="masonry.lintel",
            )
        ],
        footings=[
            M.Footing(
                id=M.footing_id(columns[0].stack_id),
                kind=M.FootingKind.ISOLATED,
                supports=[columns[0].id],
                x_m=0.0,
                y_m=0.0,
                w_m=1.2,
                h_m=1.2,
                depth_m=0.45,
                placed_by="foundations.isolated",
            )
        ],
        loads={"cases": ["DL", "LL"], "area_loads": [{"element_id": slabs[0].id, "case": "DL", "value_kpa": 3.75}]},
        seismic={"zone": "III", "z": 0.16, "base_shear_kn": 210.5},
        analysis={"envelopes": [{"element_id": beams[0].id, "m_knm": 42.1, "v_kn": 31.0}]},
        design=[{"element_id": beams[0].id, "status": "pass", "utilization_max": 0.83}],
        quantities={"totals": {"concrete_m3": 41.2, "steel_kg": 3620.0}},
    )

    model.add_warning("E_TRANSFER_REQUIRED", "a floating column would be required", [columns[1].id], stage="placement")
    model.add_warning("W_DOOR_ASSUMED", "1 door assumed mid-wall", [walls[3].openings[0].id], stage="adapter")
    model.add_warning("N_WASTAGE_3PCT", "3 percent steel wastage included", [], stage="quantities")
    return model


def _audit_units(node, key, path, problems):
    if isinstance(node, dict):
        for child_key in node:
            _audit_units(node[child_key], child_key, path + "." + str(child_key), problems)
    elif isinstance(node, list):
        for i, item in enumerate(node):
            _audit_units(item, key, path + "[" + str(i) + "]", problems)
    elif isinstance(node, bool):
        return
    elif isinstance(node, (int, float)):
        if key in NON_DIMENSIONAL_KEYS:
            return
        if any(str(key).endswith(suffix) for suffix in UNIT_SUFFIXES):
            return
        problems.append(path)


def test_wire_round_trip_is_stable():
    model = sample_model()
    first = model.to_dict()
    second = M.StructuralModel.from_dict(first).to_dict()
    assert first == second


def test_wire_shape_passes_schema_check():
    wire = sample_model().to_dict()
    assert validate_wire(wire) == []
    assert wire["schema_version"] == STRUCTURAL_SCHEMA_VERSION
    assert wire["units"]["geometry"] == "ft"
    assert wire["units"]["sections"] == "mm"


def test_geometry_crosses_the_wire_in_feet_and_sections_in_mm():
    wire = sample_model().to_dict()
    wall = wire["walls"][0]
    assert wall["a_ft"] == [0.0, 0.0]
    assert wall["b_ft"] == [pytest.approx(39.3701, abs=1e-4), 0.0]
    assert wall["thickness_ft"] == pytest.approx(0.75, abs=1e-4)
    column = wire["columns"][0]
    assert column["b_mm"] == 230
    assert column["d_mm"] == 300
    assert wire["slabs"][0]["thickness_mm"] == 150
    assert wire["rooms"][0]["area_sqft"] == pytest.approx(602.78, abs=0.01)


def test_every_numeric_wire_key_carries_a_unit_or_is_whitelisted():
    wire = sample_model().to_dict()
    audited = {k: v for k, v in wire.items() if k not in OPAQUE_SLOTS}
    problems = []
    _audit_units(audited, "", "structural_model", problems)
    assert problems == []

    # the audit bites: an unsuffixed numeric geometry key is a spec violation
    audited["walls"][0]["thickness"] = 0.75
    bad = []
    _audit_units(audited, "", "structural_model", bad)
    assert bad == ["structural_model.walls[0].thickness"]


def test_opaque_slots_pass_through_verbatim():
    model = sample_model()
    wire = model.to_dict()
    assert wire["loads"] == model.loads
    assert wire["seismic"] == model.seismic
    assert wire["analysis"] == model.analysis
    assert wire["design"] == model.design
    assert wire["quantities"] == model.quantities
    restored = M.StructuralModel.from_dict(wire)
    assert restored.loads == model.loads
    assert restored.design == model.design


def test_unknown_wire_keys_land_in_meta_extra():
    wire = sample_model().to_dict()
    wire["future_block"] = {"value_kn": 1.0}
    restored = M.StructuralModel.from_dict(wire)
    assert restored.meta["extra"] == {"future_block": {"value_kn": 1.0}}


def test_id_helpers_are_deterministic():
    assert M.fmt(12.5) == "12.5"
    assert M.fmt(12.0) == "12"
    assert M.fmt(-0.0) == "0"
    assert M.column_id(0, "1", "A") == M.column_id(0, "1", "A")
    assert M.column_id(0, "1", "A") == "col-1-A-s0"
    assert M.column_id(0, "1", "A") != M.column_id(1, "1", "A")
    assert M.column_id(2, x_m=ft_of(12.5), y_m=0.0) == "col-@12.5x0-s2"
    assert M.stack_id("1", "A") == "stk-1-A"
    assert M.stack_id(x_m=ft_of(3.0), y_m=ft_of(4.25)) == "stk-@3x4.25"
    assert M.wall_id(0, "h", 0.0, 0.0) == "wall-s0-h-0-0"
    assert M.wall_id(1, "v", ft_of(7.5), ft_of(2.0)) == "wall-s1-v-7.5-2"
    assert M.beam_id(0, M.AxisDir.Y, "A", 0) == "beam-s0-yA-0"
    assert M.beam_id(0, M.AxisDir.X, "2", 1, plinth=True) == "pbeam-s0-x2-1"
    assert M.opening_id("wall-s0-v-7-0", 2) == "wall-s0-v-7-0-op2"
    assert M.lintel_id("wall-s0-v-7-0", 2) == "lin-wall-s0-v-7-0-op2"
    assert M.slab_id(1, 3) == "slab-s1-3"
    assert M.band_id(M.BandKind.LINTEL, 2) == "band-lintel-s2"
    assert M.footing_id("stk-1-A") == "ftg-stk-1-A"
    assert M.strip_footing_id("wall-s0-h-0-0") == "ftg-strip-wall-s0-h-0-0"
    assert M.core_id("stair 1") == "core-stair_1"
    assert M.room_id(0, "liv1") != M.room_id(0, "liv2")


def ft_of(value_ft):
    """Metres for a feet literal, so id tokens can be asserted in feet."""
    return M.ft_to_m(value_ft)


def test_derived_helpers():
    model = sample_model()
    assert model.corridor_rects(0) == [(7.0, 0.0, 5.0, 8.0)]
    assert model.corridor_rects(1) == []
    assert model.balcony_rects(1) == [(7.0, 0.0, 5.0, 8.0)]
    assert model.doors_known(0) is True
    assert model.doors_known(1) is False
    wall = model.walls[1]
    opening = wall.openings[0]
    assert model.opening_span(wall, opening) == (pytest.approx(3.05), pytest.approx(3.95))
    assert model.opening_assumed(opening) is False
    assert model.opening_assumed(model.walls[3].openings[0]) is True
    assert model.by_id(opening.id) is opening
    assert model.by_id("nope") is None
    assert [w.id for w in model.walls_on(1)] == [model.walls[2].id, model.walls[3].id]
    assert [c.id for c in model.columns_on(0)] == [c.id for c in model.columns]
    assert model.cores_on(1) == model.cores


def test_wall_stacks_group_aligned_walls():
    model = sample_model()
    stacks = model.build_wall_stacks()
    assert len(stacks) == 2
    for stack in stacks:
        assert sorted(stack["walls"]) == [0, 1]
        assert stack["grounded"] is True
        assert stack["max_offset_m"] == pytest.approx(0.0)
    assert [s["stack_id"] for s in stacks] == sorted(s["stack_id"] for s in stacks)


def test_wall_stacks_split_when_centrelines_drift_beyond_half_thickness():
    def two_storey(offset_m):
        lower = _wall(0, M.wall_id(0, "v", 7.0, 0.0), (7.0, 0.0), (7.0, 8.0), 0.12, M.WallRole.INTERIOR, (None, None))
        upper = _wall(1, M.wall_id(1, "v", 7.0 + offset_m, 0.0), (7.0 + offset_m, 0.0), (7.0 + offset_m, 8.0), 0.12, M.WallRole.INTERIOR, (None, None))
        return M.StructuralModel(walls=[lower, upper])

    near = two_storey(0.02).build_wall_stacks()
    assert len(near) == 1
    assert near[0]["walls"] == {0: "wall-s0-v-22.97-0", 1: "wall-s1-v-23.03-0"}
    assert near[0]["max_offset_m"] == pytest.approx(0.02)

    far = two_storey(0.5).build_wall_stacks()
    assert len(far) == 2
    assert far[0]["grounded"] is True
    assert far[1]["grounded"] is False


def test_unregistered_disclosure_code_raises():
    model = sample_model()
    with pytest.raises(ValueError) as excinfo:
        M.add_disclosure(model, "W_MADE_UP", "not in the registry")
    assert "unregistered disclosure code" in str(excinfo.value)
    with pytest.raises(ValueError):
        model.add_warning("W_MADE_UP", "not in the registry")


def test_registry_severities_match_the_code_prefix():
    for code in sorted(M.REGISTRY):
        severity, meaning = M.REGISTRY[code]
        assert meaning
        expected = {"E": M.Severity.ERROR, "W": M.Severity.WARNING, "N": M.Severity.NOTE}[code[0]]
        assert severity == expected


def test_disclosure_log_dedupes_by_code_and_message_and_counts():
    log = M.DisclosureLog()
    # same code AND same message: one condition seen on two walls, ids merge
    log.add("W_DOOR_ASSUMED", "doors assumed", ["wall-a"])
    log.add("W_DOOR_ASSUMED", "doors assumed", ["wall-b", "wall-a"])
    log.add("N_WASTAGE_3PCT", "wastage")
    log.add("E_ROOM_OVERLAP", "rooms overlap", ["room-x"])
    assert len(log.entries) == 3
    assert log.entries[0].element_ids == ["wall-a", "wall-b"]
    assert log.counts() == {"error": 1, "warning": 1, "note": 1}
    assert log.codes() == ["E_ROOM_OVERLAP", "N_WASTAGE_3PCT", "W_DOOR_ASSUMED"]
    assert [e["code"] for e in log.to_dict()["disclosures"]] == [
        "E_ROOM_OVERLAP",
        "W_DOOR_ASSUMED",
        "N_WASTAGE_3PCT",
    ]
    assert log.to_dict()["counts"]["error"] == 1


def test_disclosure_severity_comes_from_the_registry():
    model = sample_model()
    assert model.warnings[0].severity == M.Severity.ERROR
    assert model.warnings[1].severity == M.Severity.WARNING
    assert model.warnings[2].severity == M.Severity.NOTE
    with pytest.raises(ValueError):
        model.add_warning("W_NO_STAIR", "stair missing", severity=M.Severity.ERROR)


def test_validate_is_clean_on_the_sample_model():
    assert sample_model().validate() == []


def test_validate_rejects_an_rc_slab_below_the_project_minimum():
    model = sample_model()
    model.slabs[0].thickness_m = 0.149
    problems = model.validate()
    assert [problem.code for problem in problems] == ["E_SLAB_THICKNESS_MIN"]
    assert problems[0].element_ids == [model.slabs[0].id]


def test_validate_catches_core_footprint_mismatch():
    model = sample_model()
    model.cores = [
        M.Core(id="core-stair-1-s0", kind=M.CoreKind.STAIRS, x_m=8.0, y_m=1.0, w_m=2.5, h_m=4.5, storeys=[0]),
        M.Core(id="core-stair-1-s1", kind=M.CoreKind.STAIRS, x_m=8.0, y_m=1.0, w_m=3.1, h_m=4.5, storeys=[1]),
    ]
    problems = model.validate()
    assert [p.code for p in problems] == ["E_CORE_MISMATCH"]
    assert problems[0].severity == M.Severity.ERROR
    assert problems[0].element_ids == ["core-stair-1-s0", "core-stair-1-s1"]


def test_validate_catches_skew_walls_and_dangling_references():
    model = sample_model()
    model.walls[0].b = (12.0, 0.4)
    model.beams[0].supports_wall_id = "wall-that-never-was"
    codes = [p.code for p in model.validate()]
    assert "E_NOT_RECTANGULAR" in codes
    assert "E_BAD_ENVELOPE" in codes


def test_validate_catches_storey_gaps_and_duplicate_ids():
    model = sample_model()
    model.storeys[1].index = 2
    model.columns[1].id = model.columns[0].id
    codes = [p.code for p in model.validate()]
    assert "E_STACK_DISCONTINUOUS" in codes
    assert "E_BAD_ENVELOPE" in codes


def test_enums_compare_as_strings():
    model = sample_model()
    assert model.system == "rc_frame"
    assert M.System.LOAD_BEARING_MASONRY == "load_bearing_masonry"
    assert sorted(k.value for k in M.BeamKind) == [
        "cantilever",
        "landing",
        "lintel",
        "plinth",
        "primary",
        "secondary",
        "spandrel",
        "tie",
        "trimmer",
    ]
    assert sorted(s.value for s in M.AxisSource) == [
        "core",
        "corridor",
        "inserted",
        "outline",
        "party",
        "wall",
    ]
