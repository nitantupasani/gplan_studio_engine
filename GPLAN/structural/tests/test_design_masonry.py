"""The masonry design battery: SP 20 vectors end to end, the gates, the inverse.

Three things are pinned here and each one is pinned for a different reason.

The SP 20 style vectors in `vectors/sp20/wall_examples.yaml` are driven through
`design_masonry_walls` itself, model and all, not through the code callables:
`test_codes_masonry.py` already pins the callables, so what this file proves is
that the design layer wires them together without dropping or double counting a
factor. fb, ks, fc and the verdict are asserted to two significant figures, the
tolerance the handbook is written to.

The gates are pinned because they are the answers a user acts on: a wall that
busts the slenderness cap must say `slenderness` and not something downstream
of it, and a wall beaten by in-plane shear must say `shear`.

The prescription inverse is pinned because it is the useful output. A wall that
fails on the assumed brick must come back with the cheapest pair that works,
and a wall that no pair can carry must climb the whole ladder and end at a
referral, never at an exception.
"""

from __future__ import annotations

import json
import os

import pytest
import yaml

# Relative: see the note in test_model_roundtrip.py.
from .. import model as M
from ..analysis import takedown as TD
from ..codes import is4326
from ..design import common as CM
from ..design import masonry as MD

VECTORS = os.path.join(os.path.dirname(os.path.abspath(__file__)), "vectors", "sp20", "wall_examples.yaml")


def _two_sf(value):
    """A number at the two significant figures the worked examples are read to."""
    return float("%.2g" % float(value))


def _wire(value):
    """A NamedTuple's dict as it lands on the wire: tuples become JSON lists."""
    return {key: (list(item) if isinstance(item, tuple) else item) for key, item in value.items()}


def _load_vectors():
    with open(VECTORS, "r", encoding="utf-8") as handle:
        return yaml.safe_load(handle)


# ---------------------------------------------------------------------------
# model builders
# ---------------------------------------------------------------------------


def _wall(wall_id, storey, a, b, thickness_m=0.230, role=M.WallRole.INTERIOR, openings=None):
    return M.WallLine(
        id=wall_id,
        storey=storey,
        a=a,
        b=b,
        thickness_m=thickness_m,
        role=role,
        material=M.Material.BRICK_MASONRY,
        bearing=True,
        openings=list(openings or []),
    )


def _storeys(count, height_m=3.0):
    return [
        M.Storey(index=index, name="S%d" % index, bottom_z_m=index * height_m, height_m=height_m)
        for index in range(count)
    ]


def _stress(wall_id, storey, n_kn_m, e_over_t=0.0, thickness_m=0.230):
    return {
        "wall_id": wall_id,
        "storey": storey,
        "n_kn_m": float(n_kn_m),
        "e_m": float(e_over_t) * float(thickness_m),
        "e_over_t": float(e_over_t),
    }


def _vector_model(example):
    """A one wall model that reproduces one SP 20 vector's geometry exactly.

    The cross walls and the continuing wall are real wall lines, so the Table 5
    end conditions the design layer derives are derived, not declared.
    """
    geometry = example["geometry"]
    length = float(geometry["length_m"])
    thickness = float(geometry["thickness_m"])
    model = M.StructuralModel(id=example["id"])
    model.storeys = _storeys(int(example["materials"]["storeys"]), height_m=float(geometry["clear_height_m"]))
    model.walls.append(_wall("w-main", 0, (0.0, 0.0), (length, 0.0), thickness_m=thickness))

    ends = geometry["end_conditions"]
    if ends is not None:
        for index, end in enumerate(ends):
            station = 0.0 if index == 0 else length
            if end == "cross_wall":
                model.walls.append(
                    _wall("w-cross%d" % index, 0, (station, 0.0), (station, 3.0), thickness_m=thickness)
                )
            elif end == "continuous":
                far = station - 2.0 if index == 0 else station + 2.0
                model.walls.append(
                    _wall("w-run%d" % index, 0, (min(station, far), 0.0), (max(station, far), 0.0), thickness_m=thickness)
                )
    return model


def _vector_options(example, **overrides):
    fields = {
        "assumed_unit_strength_mpa": float(example["materials"]["unit_strength_mpa"]),
        "assumed_mortar_grade": example["materials"]["mortar_grade"],
        "unit_h_over_w": float(example["geometry"]["unit_h_over_w"]),
        "storeys": int(example["materials"]["storeys"]),
    }
    fields.update(overrides)
    return MD.MasonryOptions(**fields)


def _run_vector(example):
    """One vector all the way through the public entry point."""
    model = _vector_model(example)
    loads = example["loads"]
    key = "w-main@s0"
    dead = {} if loads["dead_axial_kn_per_m"] is None else {key: float(loads["dead_axial_kn_per_m"])}
    lateral = None if loads["shear_kn"] is None else {key: float(loads["shear_kn"])}
    options = _vector_options(example, dead_axial_kn_m=dead)
    stresses = [
        _stress(
            "w-main",
            0,
            loads["axial_kn_per_m"],
            e_over_t=loads["e_over_t"],
            thickness_m=example["geometry"]["thickness_m"],
        )
    ]
    results = MD.design_masonry_walls(model, stresses, lateral, options)
    return (model, results)


# ---------------------------------------------------------------------------
# the SP 20 vectors, end to end through design_masonry_walls
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("index", [0, 1, 2])
def test_sp20_vectors_through_the_design_layer(index):
    example = _load_vectors()["examples"][index]
    expected = example["expected"]
    _model, results = _run_vector(example)

    wall = results[0].to_dict()
    assert wall["element_id"] == "w-main@s0"
    assert wall["element_type"] == MD.ELEMENT_TYPE_WALL
    check = wall["masonry"]["check"]

    assert _two_sf(check["fb_mpa"]) == _two_sf(expected["fb_mpa"]), example["id"] + " fb"
    assert _two_sf(check["ks"]) == _two_sf(expected["ks"]), example["id"] + " ks"
    assert _two_sf(check["fc_mpa"]) == _two_sf(expected["fc_mpa"]), example["id"] + " fc"
    assert check["verdict"] == expected["verdict"]
    assert wall["status"] == CM.STATUS_PASS

    # the same numbers to full precision, since nothing here is a re-derivation
    assert check["ks"] == pytest.approx(expected["ks"], rel=1e-5)
    assert check["fc_mpa"] == pytest.approx(expected["fc_mpa"], rel=1e-5)
    assert check["fa_mpa"] == pytest.approx(expected["fa_mpa"], rel=1e-5)
    assert check["utilization_compression"] == pytest.approx(expected["utilization_compression"], rel=1e-5)


@pytest.mark.parametrize("index", [0, 1, 2])
def test_sp20_vectors_derive_their_own_slenderness_chain(index):
    example = _load_vectors()["examples"][index]
    expected = example["expected"]
    _model, results = _run_vector(example)
    block = results[0].to_dict()["masonry"]

    assert block["check"]["heff_m"] == pytest.approx(expected["heff_m"], rel=1e-6)
    assert block["check"]["teff_m"] == pytest.approx(expected["teff_m"], rel=1e-6)
    assert block["check"]["slenderness_ratio"] == pytest.approx(expected["slenderness_ratio"], rel=1e-5)
    assert block["check"]["slenderness_ok"] is expected["slenderness_ok"]
    if expected["leff_m"] is None:
        assert block["check"]["leff_m"] is None
        assert block["segment"]["end_conditions"] is None
    else:
        assert block["check"]["leff_m"] == pytest.approx(expected["leff_m"], rel=1e-6)
        assert block["segment"]["end_conditions"] == list(example["geometry"]["end_conditions"])


def test_the_shear_vector_carries_its_dead_only_stress_and_its_share():
    example = {e["id"]: e for e in _load_vectors()["examples"]}["sp20-w3"]
    expected = example["expected"]
    _model, results = _run_vector(example)
    check = results[0].to_dict()["masonry"]["check"]
    segment = results[0].to_dict()["masonry"]["segment"]

    assert segment["dead_kn_per_m"] == pytest.approx(90.0)
    assert "supplied by the caller" in segment["dead_source"]
    assert segment["shear_kn"] == pytest.approx(12.0)
    assert _two_sf(check["fs_mpa"]) == _two_sf(expected["fs_mpa"])
    assert check["fs_mpa"] == pytest.approx(expected["fs_mpa"], rel=1e-5)
    assert check["tau_mpa"] == pytest.approx(expected["tau_mpa"], rel=1e-5)
    assert check["utilization_shear"] == pytest.approx(expected["utilization_shear"], rel=1e-5)


def test_the_small_pier_vector_loses_its_area_factor_through_the_design_layer():
    examples = {e["id"]: e for e in _load_vectors()["examples"]}
    for wall_id, want in (("sp20-w1", 1.0), ("sp20-w2", 1.0), ("sp20-w3", 0.907)):
        _model, results = _run_vector(examples[wall_id])
        assert results[0].to_dict()["masonry"]["check"]["ka"] == pytest.approx(want, rel=1e-6)


def test_every_vector_publishes_four_checks_and_a_traced_waterfall():
    example = _load_vectors()["examples"][0]
    _model, results = _run_vector(example)
    wall = results[0]
    assert [row.name for row in wall.checks] == [
        MD.CHECK_SLENDERNESS,
        MD.CHECK_COMPRESSION,
        MD.CHECK_SHEAR,
        MD.CHECK_TENSION,
    ]
    refs = [entry.code + " " + entry.ref for entry in wall.trace]
    for wanted in ("IS1905:1987 Table 4", "IS1905:1987 Table 8", "IS1905:1987 Table 9", "IS1905:1987 Cl 5.4.1"):
        assert wanted in refs, wanted + " is missing from the wall trace"


# ---------------------------------------------------------------------------
# the slenderness gate
# ---------------------------------------------------------------------------


def _slender_model():
    """A 150 mm wall on a timber floor: no rotational restraint, 4.5 m clear."""
    model = M.StructuralModel(id="slender")
    model.storeys = _storeys(1, height_m=4.5)
    model.walls.append(_wall("w-tall", 0, (0.0, 0.0), (6.0, 0.0), thickness_m=0.150))
    model.walls.append(_wall("w-cross0", 0, (0.0, 0.0), (0.0, 3.0), thickness_m=0.150))
    model.walls.append(_wall("w-cross1", 0, (6.0, 0.0), (6.0, 3.0), thickness_m=0.150))
    return model


def test_a_slender_150_wall_fails_the_slenderness_gate_and_says_so():
    model = _slender_model()
    # The ladder is pinned to the placed thickness so the gate is what is on
    # trial here and not the rescue; the rescue has its own test below.
    options = MD.MasonryOptions(
        top_restraint="lateral",
        bottom_restraint="lateral",
        storeys=1,
        thickness_ladder_mm=(150.0,),
    )
    results = MD.design_masonry_walls(model, [_stress("w-tall", 0, 20.0, thickness_m=0.150)], None, options)

    wall = results[0].to_dict()
    check = wall["masonry"]["check"]
    # heff = 1.00 x 4.5 = 4.5 m, teff = 0.150 m, so SR = 30 against the cap of 27.
    assert check["slenderness_ratio"] == pytest.approx(30.0, rel=1e-6)
    assert check["slenderness_limit"] == pytest.approx(27.0)
    assert check["slenderness_ok"] is False
    assert wall["status"] == CM.STATUS_FAIL
    assert wall["governing_check"] == MD.CHECK_SLENDERNESS

    rows = {row["name"]: row for row in wall["checks"]}
    assert rows[MD.CHECK_SLENDERNESS]["status"] == CM.CHECK_FAIL
    # Off the bottom of Table 9 there is no permissible stress at all, and the
    # result says that in words rather than inventing one.
    assert check["ks"] is None
    assert check["fc_mpa"] is None
    assert any("Table 9" in text for text in wall["warnings"])
    assert len(wall["checks"]) == 4
    # No brick fixes slenderness, so the ladder runs out with nothing to build.
    assert [step["step"] for step in wall["prescription"]["steps"]] == [
        MD.STEP_ASSUMED,
        MD.STEP_GRID,
        MD.STEP_CONFINED,
        MD.STEP_RC_FRAME,
    ]


def test_the_slenderness_gate_is_rescued_by_the_thickness_ladder():
    model = _slender_model()
    options = MD.MasonryOptions(top_restraint="lateral", bottom_restraint="lateral", storeys=1)
    results = MD.design_masonry_walls(model, [_stress("w-tall", 0, 20.0, thickness_m=0.150)], None, options)
    wall = results[0].to_dict()

    # 150 is not a standard thickness: the ladder starts at 190, where the
    # slenderness ratio falls to 4.5 / 0.19 = 23.68 and the wall is inside the cap.
    bumped = [step for step in wall["prescription"]["steps"] if step["step"] == MD.STEP_THICKNESS]
    assert [step["thickness_mm"] for step in bumped] == [190.0]
    assert bumped[0]["outcome"] == "passed"
    assert wall["prescription"]["thickness_mm"] == 190.0
    assert wall["masonry"]["check"]["slenderness_ratio"] == pytest.approx(4.5 / 0.19, rel=1e-6)
    assert wall["masonry"]["check"]["slenderness_ok"] is True
    assert wall["status"] == CM.STATUS_RESIZED
    assert wall["resize_history"][-1] == {
        "from": 150.0,
        "to": 190.0,
        "reason": "no pair in the grid passes at the placed thickness; the wall is prescribed one standard thicker",
    }
    assert "W_RELEASED_CAP" in [entry.code for entry in model.warnings]


# ---------------------------------------------------------------------------
# the shear gate
# ---------------------------------------------------------------------------


def test_a_shear_governed_wall_names_shear_as_its_governing_check():
    model = M.StructuralModel(id="shear")
    model.storeys = _storeys(1, height_m=3.0)
    model.walls.append(_wall("w-shear", 0, (0.0, 0.0), (2.0, 0.0)))
    model.walls.append(_wall("w-cross0", 0, (0.0, 0.0), (0.0, 3.0)))
    model.walls.append(_wall("w-cross1", 0, (2.0, 0.0), (2.0, 3.0)))

    # 230 is the top of the ladder here, so the published check is the check on
    # the wall as placed and the hand arithmetic below is readable.
    options = MD.MasonryOptions(
        storeys=1,
        dead_axial_kn_m={"w-shear@s0": 30.0},
        thickness_ladder_mm=(190.0, 230.0),
    )
    results = MD.design_masonry_walls(
        model,
        [_stress("w-shear", 0, 40.0)],
        {("w-shear", 0): 90.0},
        options,
    )
    wall = results[0].to_dict()
    check = wall["masonry"]["check"]

    # fd = 30 / 230 = 0.13043 MPa, so fs = 0.1 + fd/6 = 0.121739 MPa,
    # and tau = 90 kN over 230 x 2000 mm = 0.195652 MPa.
    assert check["fd_mpa"] == pytest.approx(30.0 / 230.0, rel=1e-5)
    assert check["fs_mpa"] == pytest.approx(0.1 + (30.0 / 230.0) / 6.0, rel=1e-5)
    assert check["tau_mpa"] == pytest.approx(90.0 * 1000.0 / (230.0 * 2000.0), rel=1e-5)
    assert check["utilization_shear"] > 1.0
    assert check["utilization_compression"] < 1.0
    assert check["governing_check"] == MD.CHECK_SHEAR
    assert wall["governing_check"] == MD.CHECK_SHEAR
    assert wall["status"] == CM.STATUS_FAIL
    rows = {row["name"]: row for row in wall["checks"]}
    assert rows[MD.CHECK_SHEAR]["clause"] == "IS1905:1987 Cl 5.4.3"

    # Shear capacity does not move with the brick, so the ladder ends in a refusal.
    assert wall["prescription"]["passes"] is False
    assert wall["prescription"]["steps"][-1]["step"] == MD.STEP_RC_FRAME


def test_m2_stays_in_the_grid_but_cannot_win_with_in_plane_shear():
    segment = MD.WallSegment(
        wall_id="w-shear-mortar",
        storey=0,
        storeys_total=1,
        thickness_mm=230.0,
        length_mm=3000.0,
        net_length_mm=3000.0,
        height_mm=3000.0,
        n_kn_per_m=20.0,
        e_over_t=0.0,
        dead_kn_per_m=15.0,
        shear_kn=10.0,
        end_conditions=("cross_wall", "cross_wall"),
    )
    options = MD.MasonryOptions(unit_strengths_mpa=(3.5,))
    m2 = CM.MasonryMaterial(unit_strength_mpa=3.5, mortar_grade="M2")

    m2_check = MD.evaluate_segment(segment, m2, options)
    assert m2_check.fs_mpa == 0.0
    assert m2_check.utilization_shear == 999.0
    assert m2_check.governing_check == MD.CHECK_SHEAR

    adopted = MD.cheapest_passing(segment, options)
    assert adopted is not None
    assert adopted[0].mortar_grade == "M1"


def test_a_lean_adopted_mortar_reaches_the_registry_disclosure():
    model = M.StructuralModel(id="lean-mortar")
    model.storeys = _storeys(1, height_m=3.0)
    model.walls.append(_wall("w-lean", 0, (0.0, 0.0), (3.0, 0.0)))
    options = MD.MasonryOptions(
        assumed_unit_strength_mpa=3.5,
        assumed_mortar_grade="M2",
        unit_strengths_mpa=(3.5,),
        mortar_grades=("M2",),
        thickness_ladder_mm=(230.0,),
        storeys=1,
    )

    results = MD.design_masonry_walls(
        model,
        [_stress("w-lean", 0, 20.0)],
        {("w-lean", 0): 10.0},
        options,
    )
    check = results[0].to_dict()["masonry"]["check"]
    warning = next(entry for entry in model.warnings if entry.code == "W_MASONRY_SHEAR_MORTAR")

    assert check["fs_mpa"] == 0.0
    assert check["governing_check"] == MD.CHECK_SHEAR
    assert warning.clause == "IS1905:1987 Cl 5.4.3"
    assert warning.element_ids == ["w-lean"]
    assert "require zero in-plane shear demand" in warning.message


def test_no_lateral_input_means_zero_shear_disclosed_not_guessed():
    model = M.StructuralModel(id="noshear")
    model.storeys = _storeys(1, height_m=3.0)
    model.walls.append(_wall("w-a", 0, (0.0, 0.0), (3.0, 0.0)))
    results = MD.design_masonry_walls(model, [_stress("w-a", 0, 40.0)], None, MD.MasonryOptions(storeys=1))
    wall = results[0].to_dict()
    assert wall["masonry"]["segment"]["shear_kn"] == 0.0
    assert any("in-plane shear taken as zero" in note for note in wall["notes"])
    assert any("of the service axial" in note for note in wall["notes"])


# ---------------------------------------------------------------------------
# the prescription inverse
# ---------------------------------------------------------------------------


def _heavy_segment(n_kn_per_m, thickness_mm=230.0):
    return MD.WallSegment(
        wall_id="w-heavy",
        storey=0,
        storeys_total=2,
        thickness_mm=thickness_mm,
        length_mm=3000.0,
        net_length_mm=3000.0,
        height_mm=3000.0,
        n_kn_per_m=n_kn_per_m,
        e_over_t=1.0 / 6.0,
        dead_kn_per_m=0.75 * n_kn_per_m,
        shear_kn=0.0,
        end_conditions=("cross_wall", "cross_wall"),
    )


def test_the_inverse_returns_the_cheapest_pair_that_passes():
    options = MD.MasonryOptions()
    segment = _heavy_segment(160.0)

    assumed = MD.evaluate_segment(segment, options.assumed_material(), options)
    assert assumed.ok is False, "this vector is only interesting if the assumed pair fails"

    material, check = MD.cheapest_passing(segment, options)
    assert check.ok is True
    # 10.0 N/mm2 in M1 is the cheapest passing pair against the IS 1905:1987
    # Table 8 as printed: the printed M1 row reads 0.96 MPa at a 10 N/mm2
    # unit, where this file used to carry 0.81 and the sweep had to climb to
    # H2. Table 8 was corrected against the print on 2026-08-30 (task J4).
    assert (material.unit_strength_mpa, material.mortar_grade) == (10.0, "M1")

    # Cheapest means cheapest: every pair below it in the cost order fails.
    for candidate in options.candidate_pairs():
        if options.cost_rank(candidate) >= options.cost_rank(material):
            break
        assert MD.evaluate_segment(segment, candidate, options).ok is False, candidate


def test_a_wall_upgraded_by_the_inverse_reports_resized_not_pass():
    model = M.StructuralModel(id="upgrade")
    model.storeys = _storeys(2, height_m=3.0)
    for storey in (0, 1):
        model.walls.append(_wall("w-main-s%d" % storey, storey, (0.0, 0.0), (3.0, 0.0)))
        model.walls.append(_wall("w-c0-s%d" % storey, storey, (0.0, 0.0), (0.0, 3.0)))
        model.walls.append(_wall("w-c1-s%d" % storey, storey, (3.0, 0.0), (3.0, 3.0)))
    stresses = [_stress("w-main-s0", 0, 160.0, e_over_t=1.0 / 6.0)]

    results = MD.design_masonry_walls(model, stresses, None, MD.MasonryOptions(storeys=2))
    wall = results[0].to_dict()

    assert wall["status"] == CM.STATUS_RESIZED
    assert wall["prescription"]["unit_strength_mpa"] == 10.0
    # 10.0 N/mm2 in M1 is the cheapest passing pair against the IS 1905:1987
    # Table 8 as printed: the printed M1 row reads 0.96 MPa at a 10 N/mm2
    # unit, where this file used to carry 0.81 and the sweep had to climb to
    # H2. Table 8 was corrected against the print on 2026-08-30 (task J4).
    assert wall["prescription"]["mortar_grade"] == "M1"
    assert wall["prescription"]["thickness_mm"] == 230.0
    assert wall["prescription"]["passes"] is True
    assert [step["step"] for step in wall["prescription"]["steps"]] == [MD.STEP_ASSUMED, MD.STEP_GRID]
    assert wall["resize_history"][0]["from"] == {"unit_strength_mpa": 7.5, "mortar_grade": "M1"}
    assert wall["resize_history"][0]["to"] == {"unit_strength_mpa": 10.0, "mortar_grade": "M1"}
    # Every published check is the check on the adopted pair, so none of them fails.
    assert all(row["status"] == CM.CHECK_PASS for row in wall["checks"])


def test_the_ladder_bumps_the_thickness_before_it_refers_the_wall():
    options = MD.MasonryOptions()
    adopted = MD._prescribe(_heavy_segment(300.0), options)
    steps = [(step["step"], step["outcome"]) for step in adopted.steps]

    assert steps == [
        (MD.STEP_ASSUMED, "insufficient"),
        (MD.STEP_GRID, "insufficient"),
        (MD.STEP_THICKNESS, "passed"),
    ]
    assert adopted.passed is True
    assert adopted.thickness_mm == 345.0
    assert adopted.thickness_changed is True


def test_a_compression_governed_ladder_refuses_the_confined_referral():
    model = M.StructuralModel(id="confine")
    model.storeys = _storeys(1, height_m=3.0)
    model.walls.append(_wall("w-heavy", 0, (0.0, 0.0), (3.0, 0.0)))
    model.walls.append(_wall("w-c0", 0, (0.0, 0.0), (0.0, 3.0)))
    model.walls.append(_wall("w-c1", 0, (3.0, 0.0), (3.0, 3.0)))
    stresses = [_stress("w-heavy", 0, 450.0, e_over_t=1.0 / 6.0)]

    results = MD.design_masonry_walls(model, stresses, None, MD.MasonryOptions(storeys=1))
    wall = results[0].to_dict()
    steps = [(step["step"], step["outcome"]) for step in wall["prescription"]["steps"]]

    assert steps == [
        (MD.STEP_ASSUMED, "insufficient"),
        (MD.STEP_GRID, "insufficient"),
        (MD.STEP_THICKNESS, "insufficient"),
        (MD.STEP_CONFINED, "refused"),
        (MD.STEP_RC_FRAME, "refused"),
    ]
    assert wall["status"] == CM.STATUS_FAIL
    assert wall["governing_check"] == MD.CHECK_COMPRESSION
    assert wall["referrals"] == []
    assert "permissible stress" in wall["prescription"]["steps"][-2]["detail"]
    assert MD.REFERRAL_CONFINED in CM.REFERRAL_ACTIONS
    # The strongest pair tried is still published: a failing wall is not an empty one.
    assert wall["prescription"]["unit_strength_mpa"] == 12.5
    assert wall["prescription"]["mortar_grade"] == "H1"
    assert wall["prescription"]["thickness_mm"] == 345.0
    assert len(wall["checks"]) == 4


def test_a_slenderness_governed_ladder_reaches_the_confined_referral():
    # At 230 mm this wall is more than twice the Table 7 limit. At the final
    # 345 mm rung its slenderness shortfall is inside the configured relief cap,
    # so that final rung, not the stale placed-wall check, controls referral.
    segment = MD.WallSegment(
        wall_id="w-slender",
        storey=0,
        storeys_total=1,
        thickness_mm=230.0,
        length_mm=3000.0,
        net_length_mm=3000.0,
        height_mm=18000.0,
        n_kn_per_m=10.0,
        e_over_t=0.0,
        dead_kn_per_m=7.5,
        shear_kn=0.0,
        end_conditions=None,
    )

    adopted = MD._prescribe(segment, MD.MasonryOptions(storeys=1))
    steps = [(step["step"], step["outcome"]) for step in adopted.steps]

    assert steps == [
        (MD.STEP_ASSUMED, "insufficient"),
        (MD.STEP_GRID, "insufficient"),
        (MD.STEP_THICKNESS, "insufficient"),
        (MD.STEP_CONFINED, "referred"),
        (MD.STEP_RC_FRAME, "refused"),
    ]
    assert adopted.referral is True
    assert adopted.check.governing_check == MD.CHECK_SLENDERNESS
    assert adopted.check.thickness_mm == 345.0
    assert adopted.check.slenderness_ratio / adopted.check.slenderness_limit <= 2.0


def test_a_hopeless_wall_is_refused_outright_rather_than_referred():
    options = MD.MasonryOptions()
    adopted = MD._prescribe(_heavy_segment(2000.0), options)
    outcomes = {step["step"]: step["outcome"] for step in adopted.steps}

    assert outcomes[MD.STEP_CONFINED] == "refused"
    assert outcomes[MD.STEP_RC_FRAME] == "refused"
    assert adopted.referral is False
    assert adopted.passed is False


def test_the_building_rollup_prices_one_specification():
    model = M.StructuralModel(id="rollup")
    model.storeys = _storeys(1, height_m=3.0)
    model.walls.append(_wall("w-light", 0, (0.0, 0.0), (3.0, 0.0)))
    model.walls.append(_wall("w-heavy", 0, (0.0, 3.0), (3.0, 3.0)))
    model.walls.append(_wall("w-c0", 0, (0.0, 0.0), (0.0, 3.0)))
    model.walls.append(_wall("w-c1", 0, (3.0, 0.0), (3.0, 3.0)))
    stresses = [
        _stress("w-light", 0, 40.0),
        _stress("w-heavy", 0, 160.0, e_over_t=1.0 / 6.0),
    ]

    results = MD.design_masonry_walls(model, stresses, None, MD.MasonryOptions(storeys=1))
    assert [row.element_type for row in results] == [
        MD.ELEMENT_TYPE_WALL,
        MD.ELEMENT_TYPE_WALL,
        MD.ELEMENT_TYPE_BUILDING,
    ]

    building = results[-1].to_dict()
    spec = building["prescription"]
    assert building["element_id"] == MD.BUILDING_ELEMENT_ID
    assert spec["governing_wall"] == "w-heavy@s0"
    # 10.0 N/mm2 in M1 is the cheapest passing pair against the IS 1905:1987
    # Table 8 as printed: the printed M1 row reads 0.96 MPa at a 10 N/mm2
    # unit, where this file used to carry 0.81 and the sweep had to climb to
    # H2. Table 8 was corrected against the print on 2026-08-30 (task J4).
    assert (spec["unit_strength_mpa"], spec["mortar_grade"]) == (10.0, "M1")
    assert spec["thickness_mm"] == 230.0
    # The light wall would have been happy with the assumed pair; the rollup is
    # the max over the walls, so the BOQ prices one brick and one mortar.
    per_wall = {row["element_id"]: row for row in spec["walls"]}
    assert per_wall["w-light@s0"]["unit_strength_mpa"] == 7.5
    assert per_wall["w-heavy@s0"]["unit_strength_mpa"] == 10.0
    assert building["status"] == CM.STATUS_RESIZED

    rows = {row["name"]: row for row in building["checks"]}
    assert set(rows) == {
        "wall_slenderness",
        "wall_compression",
        "wall_shear",
        "wall_tension",
    }
    assert rows["wall_slenderness"]["clause"] == "IS1905:1987 Table 7"
    assert rows["wall_compression"]["clause"] == "IS1905:1987 Cl 5.4.1"
    assert rows["wall_shear"]["clause"] == "IS1905:1987 Cl 5.4.3"
    assert rows["wall_tension"]["clause"] == "IS1905:1987 Cl 5.4.2"
    checks = [row.to_dict()["masonry"]["check"] for row in results[:-1]]
    assert rows["wall_slenderness"]["demand"] == pytest.approx(
        max(row["slenderness_ratio"] / row["slenderness_limit"] for row in checks)
    )
    assert rows["wall_compression"]["demand"] == pytest.approx(
        max(row["utilization_compression"] for row in checks)
    )
    assert rows["wall_shear"]["demand"] == pytest.approx(
        max(row["utilization_shear"] for row in checks)
    )
    assert rows["wall_tension"]["demand"] == pytest.approx(
        max(row["utilization_tension"] for row in checks)
    )


# ---------------------------------------------------------------------------
# IS 4326 band and vertical bar specifications
# ---------------------------------------------------------------------------


def _two_storey_house(zone="IV"):
    """A 4.0 x 3.0 m two storey box in a category D zone, walls all round."""
    model = M.StructuralModel(id="house")
    model.storeys = _storeys(2, height_m=3.0)
    for storey in (0, 1):
        model.walls.append(_wall("w-s%d-south" % storey, storey, (0.0, 0.0), (4.0, 0.0), role=M.WallRole.EXTERIOR))
        model.walls.append(_wall("w-s%d-north" % storey, storey, (0.0, 3.0), (4.0, 3.0), role=M.WallRole.EXTERIOR))
        model.walls.append(_wall("w-s%d-west" % storey, storey, (0.0, 0.0), (0.0, 3.0), role=M.WallRole.EXTERIOR))
        model.walls.append(_wall("w-s%d-east" % storey, storey, (4.0, 0.0), (4.0, 3.0), role=M.WallRole.EXTERIOR))
    stresses = []
    for storey in (0, 1):
        for side in ("south", "north", "west", "east"):
            stresses.append(_stress("w-s%d-%s" % (storey, side), storey, 60.0 if storey == 0 else 30.0, e_over_t=1.0 / 6.0))
    return (model, stresses, MD.MasonryOptions(zone=zone, storeys=2))


def test_a_two_storey_category_d_house_gets_its_table_6_bands():
    model, stresses, options = _two_storey_house()
    results = MD.design_masonry_walls(model, stresses, None, options)
    bands = results[-1].to_dict()["prescription"]["bands"]

    assert bands["category"] == "D"
    assert bands["category"] == is4326.seismic_category("IV", 1.0)
    assert bands["storeys"] == 2

    by_key = {(entry["kind"], entry["storey"]): entry for entry in bands["bands"]}
    assert sorted(by_key) == [("gable", 1), ("lintel", 0), ("lintel", 1), ("plinth", 0), ("roof", 1)]

    # Table 6, 5 m span row, category D: two 8 mm bars, 75 mm deep, 6 mm links at 150.
    lintel = by_key[("lintel", 0)]
    assert lintel["required"] is True
    assert lintel["span_m"] == 4.0
    assert lintel["spec"]["bars_n"] == 2
    assert lintel["spec"]["bar_dia_mm"] == 8
    assert lintel["spec"]["depth_mm"] == 75
    assert lintel["spec"]["link_dia_mm"] == 6
    assert lintel["spec"]["link_spacing_mm"] == 150
    assert lintel["spec"] == dict(is4326.lintel_band(4.0, "D")._asdict())

    # Cl 8.4.7 makes the plinth band mandatory for category D on any soil.
    assert by_key[("plinth", 0)]["required"] is True
    assert by_key[("plinth", 0)]["spec"] == dict(is4326.plinth_band("D", False, 4.0)._asdict())

    # Cl 8.4.6: the cast-in-situ flat roof slab IS the roof band, said out loud.
    roof = by_key[("roof", 1)]
    assert roof["required"] is False
    assert is4326.roof_band(4.0, "D", "flat", True) is None
    assert "Cl 8.4.6" in roof["reason"]

    # A flat roof has no raking end wall, so no gable band, also said out loud.
    assert by_key[("gable", 1)]["required"] is False
    assert "raking end wall" in by_key[("gable", 1)]["reason"]
    assert bands["bands_required"] == 3


def test_a_two_storey_category_d_house_gets_its_table_7_vertical_steel():
    model, stresses, options = _two_storey_house()
    results = MD.design_masonry_walls(model, stresses, None, options)
    bars = results[-1].to_dict()["prescription"]["vertical_bars"]

    assert bars["category"] == "D"
    assert bars["storeys"] == 2
    detail = {entry["storey"]: entry for entry in bars["storeys_detail"]}
    assert sorted(detail) == [0, 1]

    # Printed IS 4326:1993 Table 7, two storey stack, category D: 12 mm at the
    # bottom storey and 10 mm at the top. This file used to say 10 at both,
    # corrected against the print on 2026-08-30 (task J4).
    for index, position, dia in ((0, "bottom", 12), (1, "top", 10)):
        assert detail[index]["required"] is True
        assert detail[index]["spec"]["dia_mm"] == dia
        assert detail[index]["spec"]["position"] == position
        assert detail[index]["spec"]["bars_per_location"] == 1
        assert detail[index]["spec"]["steel_grade"] == "Fe415"
        assert detail[index]["spec"] == _wire(is4326.vertical_bars(2, index, "D")._asdict())
    # Cl 8.4.9: category D takes bars at corners, junctions and the jambs.
    assert detail[0]["spec"]["locations"] == ["corner", "junction", "jamb"]
    assert bars["storeys_required"] == 2


def test_category_b_says_not_required_rather_than_saying_nothing():
    model, stresses, _options = _two_storey_house()
    options = MD.MasonryOptions(zone="II", storeys=2)
    results = MD.design_masonry_walls(model, stresses, None, options)
    spec = results[-1].to_dict()["prescription"]

    assert spec["category"] == "B"
    bars = spec["vertical_bars"]
    assert bars["storeys_required"] == 0
    for entry in bars["storeys_detail"]:
        assert entry["required"] is False
        assert "not required, category B" in entry["reason"]
        assert entry["spec"] is None

    # Category B still takes bands, and its plinth band is the optional one.
    by_key = {(entry["kind"], entry["storey"]): entry for entry in spec["bands"]["bands"]}
    assert by_key[("lintel", 0)]["required"] is True
    assert by_key[("plinth", 0)]["required"] is False
    assert "Cl 8.4.7" in by_key[("plinth", 0)]["reason"]
    assert any("no vertical steel is required at category B" in note for note in results[-1].notes)


def test_the_band_and_bar_lookups_are_traced_on_the_building_result():
    model, stresses, options = _two_storey_house()
    results = MD.design_masonry_walls(model, stresses, None, options)
    refs = [entry.code + " " + entry.ref for entry in results[-1].trace]

    assert "IS4326:1993 Table 1" in refs
    assert "IS4326:1993 Table 6 lintel" in refs
    assert "IS4326:1993 Table 6 roof" in refs
    assert "IS4326:1993 Table 7" in refs
    # The exempted roof band is an explicit None in the trace, not a silence.
    roof = [entry for entry in results[-1].trace if entry.ref == "Table 6 roof"][0]
    assert roof.output is None


def test_a_gable_roof_puts_the_gable_band_back():
    model, stresses, _options = _two_storey_house()
    options = MD.MasonryOptions(zone="IV", storeys=2, roof_type="gable")
    results = MD.design_masonry_walls(model, stresses, None, options)
    by_key = {(e["kind"], e["storey"]): e for e in results[-1].to_dict()["prescription"]["bands"]["bands"]}

    assert by_key[("gable", 1)]["required"] is True
    assert by_key[("roof", 1)]["required"] is True
    assert by_key[("roof", 1)]["spec"]["bars_n"] == 2


def test_the_placed_band_schedule_is_what_gets_specified_when_there_is_one():
    model, stresses, options = _two_storey_house()
    model.meta["masonry_placement"] = {
        "band_schedule": [
            {"band_id": "band-lintel-s0", "kind": "lintel", "storey": 0, "span_m": 7.0, "wall_ids": ["w-s0-south"]},
            {"band_id": "band-plinth-s0", "kind": "plinth", "storey": 0, "span_m": 7.0, "wall_ids": ["w-s0-south"]},
        ],
        "vertical_bars": [
            {"id": "vb-1", "x_m": 0.0, "y_m": 0.0, "dia_mm": 10, "from_storey": 0, "to_storey": 1, "position": "corner", "clause": "Cl 8.4.9"},
        ],
    }
    results = MD.design_masonry_walls(model, stresses, None, options)
    spec = results[-1].to_dict()["prescription"]

    assert "placed by placement/masonry.py" in spec["bands"]["source"]
    entries = {entry["band_id"]: entry for entry in spec["bands"]["bands"]}
    assert sorted(entries) == ["band-lintel-s0", "band-plinth-s0"]
    # The 7 m row of Table 6 for category D is two 12 mm bars, still 75 mm deep.
    assert entries["band-lintel-s0"]["span_m"] == 7.0
    assert entries["band-lintel-s0"]["spec"]["bar_dia_mm"] == 12
    assert entries["band-lintel-s0"]["spec"]["bars_n"] == 2
    assert entries["band-lintel-s0"]["wall_ids"] == ["w-s0-south"]
    assert spec["vertical_bars"]["placed_bars_total"] == 2
    assert spec["vertical_bars"]["storeys_detail"][0]["placed_bars"] == 1


def test_a_band_span_past_table_6_is_disclosed_not_extrapolated():
    model, stresses, options = _two_storey_house()
    model.meta["masonry_placement"] = {
        "band_schedule": [{"band_id": "band-long", "kind": "lintel", "storey": 0, "span_m": 12.0, "wall_ids": []}]
    }
    results = MD.design_masonry_walls(model, stresses, None, options)
    entry = results[-1].to_dict()["prescription"]["bands"]["bands"][0]

    assert entry["required"] is True
    assert entry["spec"] is None
    assert "cannot size it" in entry["reason"]


def test_a_stack_taller_than_the_transcribed_tables_is_disclosed():
    model = M.StructuralModel(id="tall")
    model.storeys = _storeys(4, height_m=3.0)
    for storey in range(4):
        model.walls.append(_wall("w-s%d" % storey, storey, (0.0, 0.0), (3.0, 0.0)))
    stresses = [_stress("w-s%d" % storey, storey, 40.0) for storey in range(4)]

    results = MD.design_masonry_walls(model, stresses, None, MD.MasonryOptions())
    assert "E_MASONRY_LIMIT" in [entry.code for entry in model.warnings]
    bars = results[-1].to_dict()["prescription"]["vertical_bars"]
    assert bars["storeys_required"] == 0
    assert all("cannot answer for this stack" in entry["reason"] for entry in bars["storeys_detail"])


# ---------------------------------------------------------------------------
# segment resolution
# ---------------------------------------------------------------------------


def test_openings_come_off_the_bearing_length_loaded_area_and_compressive_section():
    door = M.Opening(
        id="o-1",
        kind=M.OpeningKind.DOOR,
        offset_m=1.5,
        width_m=0.9,
        sill_m=0.0,
        head_m=2.1,
        provenance=M.Provenance.DRESSED,
    )
    model = M.StructuralModel(id="opening")
    model.storeys = _storeys(1, height_m=3.0)
    model.walls.append(_wall("w-door", 0, (0.0, 0.0), (3.0, 0.0), openings=[door]))

    segments = MD.resolve_segments(model, [_stress("w-door", 0, 40.0)], None, MD.MasonryOptions(storeys=1))
    assert len(segments) == 1
    assert segments[0].length_mm == pytest.approx(3000.0)
    assert segments[0].net_length_mm == pytest.approx(2100.0)
    assert segments[0].openings_known is True
    assert segments[0].loaded_area_m2() == pytest.approx(0.230 * 2.1, rel=1e-9)
    check = MD.evaluate_segment(segments[0], MD.MasonryOptions().assumed_material(), MD.MasonryOptions())
    # The takedown's 40 kN/m is on the gross 3.0 m line. The whole 120 kN
    # stands on the 2.1 m net bed joint, so the stress carries 3.0 / 2.1.
    assert check.fa_mpa == pytest.approx(40.0 * (3000.0 / 2100.0) / 230.0, rel=1e-9)
    assert "W_ASSUMED_OPENINGS" not in [entry.code for entry in model.warnings]


def test_serialized_takedown_at_the_kern_matches_the_live_result():
    def one_wall(model_id):
        model = M.StructuralModel(id=model_id)
        model.storeys = _storeys(1, height_m=3.0)
        model.walls.append(_wall("w-kern", 0, (0.0, 0.0), (3.0, 0.0)))
        return model

    takedown = TD.TakedownResult(
        wall_stresses=[
            TD.WallStress(
                wall_id="w-kern",
                storey=0,
                n_kn_m=40.0,
                e_m=0.230 / 6.0,
                e_over_t=1.0 / 6.0,
            )
        ]
    )
    wire = takedown.to_dict()
    assert wire["wall_stresses"][0]["e_over_t"] == 0.166667

    options = MD.MasonryOptions(storeys=1)
    live_wall = MD.design_masonry_walls(one_wall("kern-live"), takedown, None, options)[0].to_dict()
    wire_wall = MD.design_masonry_walls(one_wall("kern-wire"), wire, None, options)[0].to_dict()

    for wall in (live_wall, wire_wall):
        check = wall["masonry"]["check"]
        assert check["tension_demand_mpa"] == 0.0
        assert check["utilization_tension"] == 0.0
        assert wall["status"] == CM.STATUS_PASS


def test_undressed_openings_are_disclosed_on_the_ladder_and_on_the_wall():
    model = M.StructuralModel(id="assumed")
    model.storeys = _storeys(1, height_m=3.0)
    model.walls.append(_wall("w-a", 0, (0.0, 0.0), (3.0, 0.0)))
    results = MD.design_masonry_walls(model, [_stress("w-a", 0, 40.0)], None, MD.MasonryOptions(storeys=1))

    assert "W_ASSUMED_OPENINGS" in [entry.code for entry in model.warnings]
    assert any("net bearing length equals the gross wall length" in text for text in results[0].warnings)


def test_assumed_opening_geometry_is_named_as_a_net_bearing_length_deduction():
    """N31: a non-dressed opening is deducted, not falsely reported as gross length."""
    opening = M.Opening(
        id="o-assumed",
        kind=M.OpeningKind.DOOR,
        offset_m=1.5,
        width_m=0.9,
        provenance=M.Provenance.ASSUMED_MID_WALL,
    )
    model = M.StructuralModel(id="assumed-opening-length")
    model.storeys = _storeys(1, height_m=3.0)
    model.walls.append(_wall("w-assumed", 0, (0.0, 0.0), (3.0, 0.0), openings=[opening]))

    results = MD.design_masonry_walls(model, [_stress("w-assumed", 0, 40.0)], None, MD.MasonryOptions(storeys=1))
    ladder = [entry for entry in model.warnings if entry.code == "W_ASSUMED_OPENINGS"]

    assert results[0].extras["masonry"]["segment"]["net_length_mm"] == pytest.approx(2100.0)
    assert any("net bearing length deducts the assumed opening geometry" in text for text in results[0].warnings)
    assert len(ladder) == 1
    assert ladder[0].element_ids == ["w-assumed"]
    assert "net bearing length deducts the assumed opening geometry" in ladder[0].message


def test_non_masonry_and_non_bearing_walls_are_not_designed():
    model = M.StructuralModel(id="mixed")
    model.storeys = _storeys(1, height_m=3.0)
    rc = _wall("w-rc", 0, (0.0, 0.0), (3.0, 0.0))
    rc.material = M.Material.RC
    parapet = _wall("w-parapet", 0, (0.0, 1.0), (3.0, 1.0), role=M.WallRole.PARAPET)
    partition = _wall("w-part", 0, (0.0, 2.0), (3.0, 2.0))
    partition.bearing = False
    model.walls.extend([rc, parapet, partition, _wall("w-ok", 0, (0.0, 3.0), (3.0, 3.0))])

    stresses = [_stress(wall.id, 0, 40.0) for wall in model.walls]
    segments = MD.resolve_segments(model, stresses, None, MD.MasonryOptions(storeys=1))
    assert [segment.wall_id for segment in segments] == ["w-ok"]


def test_the_takedown_dead_base_load_beats_the_assumed_fraction():
    model = M.StructuralModel(id="dead")
    model.storeys = _storeys(1, height_m=3.0)
    model.walls.append(_wall("w-a", 0, (0.0, 0.0), (3.0, 0.0)))
    takedown = {
        "wall_stresses": [_stress("w-a", 0, 40.0)],
        "footing_loads": {"walls": {"w-a": {"n_dl_kn_m": 31.0, "n_ll_kn_m": 9.0}}},
    }
    segments = MD.resolve_segments(model, takedown, None, MD.MasonryOptions(storeys=1))

    assert segments[0].dead_kn_per_m == pytest.approx(31.0)
    assert "takedown footing loads" in segments[0].dead_source


def test_the_lateral_result_shape_is_consumed_as_it_arrives():
    from ..analysis.diaphragm import ElementShare, LateralResult, StoreyLateral

    share = ElementShare(
        element_id="w-a",
        element_type="wall",
        storey=0,
        direction="x",
        k_kn_m=1000.0,
        x_m=1.5,
        y_m=0.0,
        d_m=0.0,
        v_direct_kn=70.0,
        v_torsion_kn=5.0,
        v_kn=75.0,
        length_m=3.0,
        v_per_m_kn_m=25.0,
    )
    block = StoreyLateral(
        storey=0,
        direction="x",
        height_m=3.0,
        shear_kn=75.0,
        sum_k_kn_m=1000.0,
        cr_x_m=1.5,
        cr_y_m=0.0,
        cm_x_m=1.5,
        cm_y_m=0.0,
        esi_m=0.0,
        bi_m=3.0,
        ed_amplified_m=0.0,
        ed_reduced_m=0.0,
        ed_governing_m=0.0,
        j_knm=0.0,
        drift_m=0.0,
        drift_limit_m=0.012,
        drift_ratio=0.0,
        drift_exceeded=False,
        torsion_irregular=False,
        overturning_moment_knm=225.0,
        elements=[share],
    )
    lateral = LateralResult(storeys=[block])

    model = M.StructuralModel(id="lat")
    model.storeys = _storeys(1, height_m=3.0)
    model.walls.append(_wall("w-a", 0, (0.0, 0.0), (3.0, 0.0)))
    segments = MD.resolve_segments(model, [_stress("w-a", 0, 40.0)], lateral, MD.MasonryOptions(storeys=1))

    assert segments[0].shear_kn == pytest.approx(75.0)
    assert "diaphragm share along x" in segments[0].shear_source
    # The serialized form of the same result reads the same.
    from_dict = MD.resolve_segments(model, [_stress("w-a", 0, 40.0)], lateral.to_dict(), MD.MasonryOptions(storeys=1))
    assert from_dict[0].shear_kn == pytest.approx(75.0)


def test_pilasters_stiffen_the_effective_thickness_through_table_6():
    model = M.StructuralModel(id="pilaster")
    model.storeys = _storeys(1, height_m=3.0)
    model.walls.append(_wall("w-long", 0, (0.0, 0.0), (9.0, 0.0)))
    model.meta["masonry_placement"] = {
        "pilasters": [
            {"id": "pil-1", "wall_id": "w-long", "storey": 0, "x_m": 3.0, "y_m": 0.0, "t_mm": 230.0, "projection_mm": 690.0},
            {"id": "pil-2", "wall_id": "w-long", "storey": 0, "x_m": 6.0, "y_m": 0.0, "t_mm": 230.0, "projection_mm": 690.0},
        ]
    }
    options = MD.MasonryOptions(storeys=1)
    stresses = [_stress("w-long", 0, 40.0)]

    stiffened = MD.resolve_segments(model, stresses, None, options)[0]
    assert stiffened.pier_spacing_mm == pytest.approx(3000.0)
    assert stiffened.pier_width_mm == pytest.approx(230.0)
    assert stiffened.pier_depth_mm == pytest.approx(920.0)

    plain = MD.resolve_segments(model, stresses, None, MD.MasonryOptions(storeys=1, use_pilasters=False))[0]
    material = options.assumed_material()
    assert MD.evaluate_segment(stiffened, material, options).teff_m > MD.evaluate_segment(plain, material, options).teff_m


def test_confined_tie_columns_reach_the_pier_parameter_handoff():
    model = M.StructuralModel(id="confined-ties")
    model.storeys = _storeys(1, height_m=3.0)
    model.walls.append(_wall("w-long", 0, (0.0, 0.0), (9.0, 0.0)))
    model.meta["masonry_placement"] = {
        "tie_columns": [
            {
                "id": "tie-1",
                "wall_id": "w-long",
                "x_m": 3.0,
                "y_m": 0.0,
                "w_mm": 230.0,
                "d_mm": 230.0,
                "storeys": [0],
            },
            {
                "id": "tie-2",
                "wall_id": "w-long",
                "x_m": 6.0,
                "y_m": 0.0,
                "w_mm": 230.0,
                "d_mm": 230.0,
                "storeys": [0],
            },
        ]
    }

    segment = MD.resolve_segments(
        model,
        [_stress("w-long", 0, 40.0)],
        None,
        MD.MasonryOptions(storeys=1),
    )[0]

    assert segment.pier_spacing_mm == pytest.approx(3000.0)
    assert segment.pier_width_mm == pytest.approx(230.0)
    assert segment.pier_depth_mm == pytest.approx(230.0)


# ---------------------------------------------------------------------------
# options, tension policy, dispatch, determinism
# ---------------------------------------------------------------------------


def test_the_cost_order_is_a_total_order_starting_at_the_weakest_pair():
    options = MD.MasonryOptions()
    pairs = options.candidate_pairs()

    assert len(pairs) == len(options.unit_strengths_mpa) * len(options.mortar_grades)
    assert (pairs[0].unit_strength_mpa, pairs[0].mortar_grade) == (3.5, "M2")
    assert (pairs[-1].unit_strength_mpa, pairs[-1].mortar_grade) == (12.5, "H1")
    ranks = [options.cost_rank(pair) for pair in pairs]
    assert ranks == sorted(ranks)


def test_options_come_from_a_mapping_and_reject_a_grade_that_is_not_in_table_1():
    options = MD.MasonryOptions.coerce({"zone": "V", "masonry": {"assumed_mortar_grade": "h1"}})
    assert options.assumed_mortar_grade == "H1"
    assert options.zone == "V"
    assert MD.MasonryOptions.coerce(options) is options
    assert MD.MasonryOptions.coerce(None).assumed_mortar_grade == "M1"

    with pytest.raises(ValueError):
        MD.MasonryOptions(assumed_mortar_grade="M9")
    with pytest.raises(ValueError):
        MD.MasonryOptions(tension_policy="whatever")


def test_the_default_tension_policy_fails_a_wall_past_the_kern():
    segment = MD.WallSegment(
        wall_id="w-ecc",
        storey=0,
        storeys_total=1,
        thickness_mm=230.0,
        length_mm=3000.0,
        net_length_mm=3000.0,
        height_mm=3000.0,
        n_kn_per_m=30.0,
        e_over_t=0.25,
        dead_kn_per_m=22.0,
        shear_kn=0.0,
        end_conditions=("cross_wall", "cross_wall"),
    )
    options = MD.MasonryOptions()
    check = MD.evaluate_segment(segment, options.assumed_material(), options)

    # e/t = 1/4 is past the kern of 1/6, so the far face is in tension:
    # fa (6 e/t - 1) = (30 / 230) x 0.5 = 0.065217 MPa against a permissible zero.
    assert check.tension_demand_mpa == pytest.approx((30.0 / 230.0) * 0.5, rel=1e-9)
    assert check.ft_mpa == 0.0
    assert check.utilization_tension >= 999.0
    assert check.governing_check == MD.CHECK_TENSION
    assert check.ok is False

    allowed = MD.MasonryOptions(tension_policy="allow_flexural_tension")
    relaxed = MD.evaluate_segment(segment, allowed.assumed_material(), allowed)
    assert relaxed.ft_mpa == pytest.approx(0.07)
    assert relaxed.ok is True


def test_relaxing_the_tension_policy_is_disclosed_on_the_ladder():
    model = M.StructuralModel(id="tension")
    model.storeys = _storeys(1, height_m=3.0)
    model.walls.append(_wall("w-a", 0, (0.0, 0.0), (3.0, 0.0)))
    options = MD.MasonryOptions(storeys=1, tension_policy="allow_flexural_tension")
    results = MD.design_masonry_walls(model, [_stress("w-a", 0, 30.0, e_over_t=0.25)], None, options)

    assert "W_RELEASED_CAP" in [entry.code for entry in model.warnings]
    assert any("laterally loaded panel" in text for text in results[0].warnings)
    rows = {row.name: row for row in results[0].checks}
    assert rows[MD.CHECK_TENSION].clause == "IS1905:1987 Cl 5.4.2"
    warning = next(entry for entry in model.warnings if "flexural tension was allowed" in entry.message)
    assert warning.clause == "IS1905:1987 Cl 5.4.2"


def test_an_eccentricity_off_table_9_fails_without_a_guessed_stress():
    segment = MD.WallSegment(
        wall_id="w-off",
        storey=0,
        storeys_total=1,
        thickness_mm=230.0,
        length_mm=3000.0,
        net_length_mm=3000.0,
        height_mm=3000.0,
        n_kn_per_m=30.0,
        e_over_t=0.40,
        dead_kn_per_m=22.0,
        shear_kn=0.0,
        end_conditions=("cross_wall", "cross_wall"),
    )
    options = MD.MasonryOptions()
    check = MD.evaluate_segment(segment, options.assumed_material(), options)

    assert check.ks is None
    assert check.fc_mpa is None
    assert "1/3" in check.ks_reason
    assert check.ok is False


def test_the_designer_is_registered_for_dispatch():
    assert CM.get_designer("masonry") is MD.design_masonry_walls
    assert MD.MATERIAL in CM.MATERIALS


def test_an_empty_model_designs_nothing_rather_than_failing():
    model = M.StructuralModel(id="empty")
    model.storeys = _storeys(1)
    assert MD.design_masonry_walls(model, [], None, None) == []
    assert MD.design_masonry_walls(model, None, None, None) == []


def test_a_wall_the_tables_refuse_still_returns_a_populated_result():
    model = M.StructuralModel(id="refuse")
    model.storeys = _storeys(1, height_m=3.0)
    model.walls.append(_wall("w-free", 0, (0.0, 0.0), (3.0, 0.0)))
    # A wall free at the bottom is not an IS 1905 Table 4 case at all.
    options = MD.MasonryOptions(storeys=1, bottom_restraint="free")
    results = MD.design_masonry_walls(model, [_stress("w-free", 0, 40.0)], None, options)

    wall = results[0].to_dict()
    assert wall["status"] == CM.STATUS_FAIL
    assert len(wall["checks"]) == 4
    assert wall["prescription"]["steps"][-1]["step"] == MD.STEP_RC_FRAME
    assert "free at the bottom" in wall["prescription"]["steps"][0]["detail"]


def test_the_whole_run_is_deterministic():
    model_a, stresses, options = _two_storey_house()
    model_b, _stresses_b, _options_b = _two_storey_house()
    lateral = {("w-s0-south", 0): 20.0, "w-s1-south@s1": 10.0}

    first = [row.to_dict() for row in MD.design_masonry_walls(model_a, stresses, lateral, options)]
    second = [row.to_dict() for row in MD.design_masonry_walls(model_b, stresses, lateral, options)]

    assert json.dumps(first, sort_keys=True) == json.dumps(second, sort_keys=True)
    assert [row["element_id"] for row in first] == [
        "w-s0-east@s0",
        "w-s0-north@s0",
        "w-s0-south@s0",
        "w-s0-west@s0",
        "w-s1-east@s1",
        "w-s1-north@s1",
        "w-s1-south@s1",
        "w-s1-west@s1",
        MD.BUILDING_ELEMENT_ID,
    ]


def test_every_storey_is_checked_and_the_bottom_one_governs():
    model, stresses, options = _two_storey_house()
    results = MD.design_masonry_walls(model, stresses, None, options)
    walls = {row.element_id: row.to_dict() for row in results if row.element_type == MD.ELEMENT_TYPE_WALL}

    # Eight segments, four walls on each of the two storeys: no storey is skipped
    # on the argument that the one below it is worse.
    assert len(walls) == 8
    assert sorted(row["masonry"]["segment"]["storey"] for row in walls.values()) == [0, 0, 0, 0, 1, 1, 1, 1]

    ground = walls["w-s0-south@s0"]["masonry"]["check"]
    upper = walls["w-s1-south@s1"]["masonry"]["check"]
    assert ground["fa_mpa"] > upper["fa_mpa"]
    assert ground["utilization_compression"] > upper["utilization_compression"]
    # Same wall line, same brick, so the difference is the load and nothing else.
    assert ground["fc_mpa"] == pytest.approx(upper["fc_mpa"], rel=1e-9)


def test_results_round_trip_through_the_shared_contract():
    model, stresses, options = _two_storey_house()
    results = MD.design_masonry_walls(model, stresses, None, options)
    for row in results:
        rebuilt = CM.DesignResult.from_dict(row.to_dict())
        assert rebuilt.to_dict() == row.to_dict()
        assert sorted(rebuilt.extras) in (["masonry", "prescription"], ["prescription"])
