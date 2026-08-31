"""Pins for the FE adapter: the generic frame model, the node cap, the backend.

The contract this file protects is that shipping `frame_fe.py` costs no
dependency: nothing imports Pynite at module import time, and a missing
PyNiteFEA comes back as `BackendUnavailable` whose message names the numpy pin
that blocks the adoption.

Imports are relative for the reason given in the other test modules.
"""

from __future__ import annotations

import importlib.util
import json
import sys

import pytest

from ..analysis import diaphragm, frame_fe
from ..analysis.frame_fe import (
    BackendUnavailable,
    FEResult,
    GenericModelParams,
    PyniteBackend,
    analyze_lateral,
    assemble_storey_shears,
    build_generic_model,
)
from ..loads import CaseKind, LineLoad, LoadCase, LoadModel
from ..loads.seismic import SeismicContext, build_seismic
from ..model import (
    AxisDir,
    Beam,
    BeamKind,
    Column,
    DisclosureLog,
    GridAxis,
    Occupancy,
    RoomPoly,
    Storey,
    StructuralModel,
    axis_id,
    column_id,
    stack_id,
)

XS = (0.0, 6.0)
YS = (0.0, 4.0)

PYNITE_INSTALLED = importlib.util.find_spec("Pynite") is not None


def _grid_model(storeys=2, height_m=3.0):
    """A 2 x 2 grid, `storeys` storeys, four columns and four beams per storey."""
    model = StructuralModel(
        id="fe-fixture",
        storeys=[
            Storey(index=index, name="S" + str(index), bottom_z_m=height_m * index, height_m=height_m)
            for index in range(storeys)
        ],
    )
    for label, x in zip(("1", "2"), XS):
        model.axes.append(GridAxis(id=axis_id(AxisDir.X, label), dir=AxisDir.X, pos_m=x, label=label))
    for label, y in zip(("A", "B"), YS):
        model.axes.append(GridAxis(id=axis_id(AxisDir.Y, label), dir=AxisDir.Y, pos_m=y, label=label))
    for storey in range(storeys):
        model.rooms.append(
            RoomPoly(
                id="room-s" + str(storey),
                storey=storey,
                name="hall",
                occupancy=Occupancy.HABITABLE,
                polygon=[(XS[0], YS[0]), (XS[1], YS[0]), (XS[1], YS[1]), (XS[0], YS[1])],
                area_m2=24.0,
            )
        )
        for x in XS:
            for y in YS:
                model.columns.append(
                    Column(
                        id=column_id(storey, x_m=x, y_m=y),
                        stack_id=stack_id(x_m=x, y_m=y),
                        storey=storey,
                        x_m=x,
                        y_m=y,
                        width_m=0.3,
                        depth_m=0.3,
                    )
                )
        index = 0
        for y in YS:
            model.beams.append(
                Beam(
                    id="beam-s" + str(storey) + "-x" + str(index),
                    storey=storey,
                    a=(XS[0], y),
                    b=(XS[1], y),
                    width_m=0.23,
                    depth_m=0.45,
                )
            )
            index += 1
        for x in XS:
            model.beams.append(
                Beam(
                    id="beam-s" + str(storey) + "-y" + str(index),
                    storey=storey,
                    a=(x, YS[0]),
                    b=(x, YS[1]),
                    width_m=0.23,
                    depth_m=0.45,
                )
            )
            index += 1
    return model


def _sparse_twelve_storey_model():
    """19 by 19 axes, but only 91 stacked columns use the grid intersections."""
    model = StructuralModel(
        id="fe-sparse-12",
        storeys=[
            Storey(index=index, name="S" + str(index), bottom_z_m=3.0 * index, height_m=3.0)
            for index in range(12)
        ],
    )
    positions = [float(index) for index in range(19)]
    for index, x in enumerate(positions):
        label = str(index + 1)
        model.axes.append(GridAxis(id=axis_id(AxisDir.X, label), dir=AxisDir.X, pos_m=x, label=label))
    for index, y in enumerate(positions):
        label = chr(ord("A") + index)
        model.axes.append(GridAxis(id=axis_id(AxisDir.Y, label), dir=AxisDir.Y, pos_m=y, label=label))
    used = [(positions[index // 19], positions[index % 19]) for index in range(91)]
    for storey in range(12):
        for x, y in used:
            model.columns.append(
                Column(
                    id=column_id(storey, x_m=x, y_m=y),
                    stack_id=stack_id(x_m=x, y_m=y),
                    storey=storey,
                    x_m=x,
                    y_m=y,
                    width_m=0.3,
                    depth_m=0.3,
                )
            )
    return model


# ---------------------------------------------------------------------------
# the generic model
# ---------------------------------------------------------------------------


def test_node_and_member_counts_on_a_two_by_two_grid_over_two_storeys():
    description = build_generic_model(_grid_model(2))
    diagnostics = description["diagnostics"]

    # Three levels (base plus two floors) x four intersections = twelve nodes,
    # plus one rigid-diaphragm master per floor.
    assert diagnostics["levels"] == 3
    assert diagnostics["grid_x"] == 2 and diagnostics["grid_y"] == 2
    assert diagnostics["nodes"] == 14
    assert sum(1 for node in description["nodes"] if node["master"]) == 2
    # Four columns and four beams per storey.
    assert diagnostics["columns"] == 8
    assert diagnostics["beams"] == 8
    assert diagnostics["members"] == 16
    assert diagnostics["unmapped_elements"] == []
    assert description["refused"] is False


def test_columns_span_between_levels_and_beams_sit_on_their_floor():
    description = build_generic_model(_grid_model(2))
    nodes = {node["id"]: node for node in description["nodes"]}
    columns = [member for member in description["members"] if member["type"] == "column"]
    beams = [member for member in description["members"] if member["type"] == "beam"]

    for member in columns:
        lower, upper = nodes[member["i"]], nodes[member["j"]]
        assert upper["level"] == lower["level"] + 1
        assert upper["z_m"] - lower["z_m"] == pytest.approx(3.0)
        assert (lower["x_m"], lower["y_m"]) == (upper["x_m"], upper["y_m"])
    for member in beams:
        start, end = nodes[member["i"]], nodes[member["j"]]
        assert start["level"] == end["level"] > 0
        assert start["z_m"] == end["z_m"]
    # Sections travel in millimetres, geometry in metres (finding 1).
    assert columns[0]["section"] == {"b_mm": 300, "d_mm": 300}
    assert beams[0]["section"] == {"b_mm": 230, "d_mm": 450}


def test_bases_are_supported_and_no_other_level_is():
    description = build_generic_model(_grid_model(2))
    base = [node for node in description["nodes"] if node["level"] == 0]
    assert len(base) == 4
    assert all(node["support"] == "fixed" for node in base)
    assert all(node["support"] is None for node in description["nodes"] if node["level"] > 0)

    pinned = build_generic_model(_grid_model(1), params=GenericModelParams(base_fixity="pinned"))
    assert all(
        node["support"] == "pinned" for node in pinned["nodes"] if node["level"] == 0
    )


def test_secondary_beam_ends_are_moment_released():
    model = _grid_model(1)
    model.beams[0].kind = BeamKind.SECONDARY
    description = build_generic_model(model)
    released = [
        member for member in description["members"] if member["releases"]["i"] == ["My", "Mz"]
    ]
    assert [member["id"] for member in released] == [model.beams[0].id]
    assert released[0]["releases"]["j"] == ["My", "Mz"]

    kept = build_generic_model(model, params=GenericModelParams(release_secondary_ends=False))
    assert all(member["releases"]["i"] == [] for member in kept["members"])


def test_lateral_cases_are_applied_at_the_diaphragm_masters():
    model = _grid_model(2)
    cases, _ = build_seismic(
        [{"storey": index, "w_dl_kn": 1500.0, "z_top_m": 3.0 * (index + 1)} for index in range(2)],
        {"x_m": 6.0, "y_m": 4.0},
        SeismicContext(system="smrf"),
    )
    description = build_generic_model(model, cases)

    masters = {node["level"]: node["id"] for node in description["nodes"] if node["master"]}
    assert description["cases"] == ["EQX+", "EQX-", "EQY+", "EQY-"]
    assert len(description["loads"]) == 8
    for load in description["loads"]:
        assert load["node"] == masters[load["level"]]
    # Level 1 is the top of storey 0.
    first = [load for load in description["loads"] if load["case"] == "EQX+"]
    assert [load["storey"] for load in first] == [0, 1]
    assert [load["level"] for load in first] == [1, 2]
    assert first[0]["fy_kn"] == 0.0 and first[0]["fx_kn"] > 0.0

    unconstrained = build_generic_model(
        model, cases, params=GenericModelParams(rigid_diaphragm=False)
    )
    assert unconstrained["constraints"] == []
    assert all(load["node"] is None for load in unconstrained["loads"])


def test_the_node_cap_refuses_with_a_fallback_disclosure():
    log = DisclosureLog()
    description = build_generic_model(
        _grid_model(2), params=GenericModelParams(node_cap=5), log=log
    )
    assert description["refused"] is True
    assert description["nodes"] == []
    assert description["members"] == []
    assert "node cap" in description["refusal_reason"]
    assert "takedown + diaphragm" in description["refusal_reason"]
    assert "W_COARSE_ITER" in log.codes()

    # The cap counts the diaphragm masters too: 14 nodes, so 14 passes.
    assert build_generic_model(_grid_model(2), params=GenericModelParams(node_cap=14))[
        "refused"
    ] is False
    assert build_generic_model(_grid_model(2), params=GenericModelParams(node_cap=13))[
        "refused"
    ] is True


def test_emitted_nodes_are_authoritative_after_a_bounded_candidate_pre_screen():
    """The 12-storey cap case is 4,705 candidates but only 1,195 emitted nodes."""
    description = build_generic_model(_sparse_twelve_storey_model())
    assert description["refused"] is False
    assert description["diagnostics"]["candidate_nodes"] == 4705
    assert description["diagnostics"]["nodes"] == 1195
    assert description["diagnostics"]["nodes"] < GenericModelParams().node_cap


def test_the_default_cap_is_the_spec_number():
    assert frame_fe.NODE_CAP == 3000
    assert GenericModelParams().node_cap == 3000
    assert GenericModelParams().stations == 11
    assert GenericModelParams().p_delta is False


def test_a_degenerate_member_is_reported_not_silently_dropped():
    log = DisclosureLog()
    model = _grid_model(1)
    model.beams.append(
        Beam(id="beam-nowhere", storey=0, a=(XS[0], YS[0]), b=(XS[0], YS[0]), width_m=0.23)
    )
    description = build_generic_model(model, log=log)
    assert description["diagnostics"]["unmapped_elements"] == ["beam-nowhere"]
    assert "W_CLIENT_GRID_DIFFERS" in log.codes()


def test_the_generic_model_serializes_and_is_deterministic():
    first = build_generic_model(_grid_model(2))
    second = build_generic_model(_grid_model(2))
    assert json.dumps(first, sort_keys=True) == json.dumps(second, sort_keys=True)
    assert first["schema"] == "structural.frame_fe.generic/1"
    assert first["units"]["length"] == "m"
    assert first["units"]["section"] == "mm"
    # Nodes come out in a fixed order: level, then masters last, then position.
    levels = [node["level"] for node in first["nodes"]]
    assert levels == sorted(levels)


def test_generic_model_carries_materials_gravity_line_loads_and_storey_cm():
    model = _grid_model(2)
    beam_id = model.beams[0].id
    load_model = LoadModel(
        cases={
            "DL": LoadCase(
                "DL",
                CaseKind.DEAD,
                line=[LineLoad(beam_id, 10.0, 12.0, 0.2, 0.8, CaseKind.DEAD, "takedown")],
            ),
            "EQX+": LoadCase("EQX+", CaseKind.SEISMIC),
        }
    )
    materials = {
        "rc": {"fck_mpa": 30.0, "fy_mpa": 500.0, "ec_mpa": 27386.0},
    }
    centres = {0: (1.25, 2.5), 1: (2.75, 1.5)}
    description = build_generic_model(
        model,
        materials=materials,
        load_model=load_model,
        centres_of_mass=centres,
    )

    assert description["materials"] == materials
    assert description["units"]["line_load"] == "kN/m"
    assert description["gravity_cases"] == [
        {
            "name": "DL",
            "kind": "dead",
            "line_loads": [
                {
                    "element_id": beam_id,
                    "w1_kn_m": 10.0,
                    "w2_kn_m": 12.0,
                    "a": 0.2,
                    "b": 0.8,
                    "kind": "dead",
                    "source": "takedown",
                    "note": "",
                }
            ],
        }
    ]
    assert description["levels"][1]["cm_m"] == [1.25, 2.5]
    masters = {node["level"]: node for node in description["nodes"] if node["master"]}
    assert (masters[1]["x_m"], masters[1]["y_m"]) == pytest.approx((1.25, 2.5))

    model.loads = load_model.to_dict()
    from_model = build_generic_model(model)
    assert from_model["gravity_cases"] == description["gravity_cases"]


def test_fe_result_round_trips_to_a_sorted_dict():
    result = FEResult(
        envelopes={"b": {"m_max": 2.0}, "a": {"m_max": 1.0}},
        reactions={"n2": {"fz_kn": 5.0}, "n1": {"fz_kn": 4.0}},
        drifts=[{"storey": 0, "drift_m": 0.001}],
        diagnostics={"backend": "none"},
    )
    payload = result.to_dict()
    assert list(payload["envelopes"]) == ["a", "b"]
    assert list(payload["reactions"]) == ["n1", "n2"]
    assert payload["drifts"][0]["storey"] == 0
    json.dumps(payload, sort_keys=True)


# ---------------------------------------------------------------------------
# the backend
# ---------------------------------------------------------------------------


def test_nothing_imports_pynite_at_module_import_time():
    # Importing the adapter must not pull the dependency in; the whole point of
    # shipping frame_fe.py in v1 is that it costs nothing.
    assert "Pynite" not in sys.modules
    assert not hasattr(frame_fe, "Pynite")


def test_backend_unavailable_names_the_numpy_pin(monkeypatch):
    def _missing():
        raise ImportError("No module named 'Pynite'")

    monkeypatch.setattr(frame_fe, "_import_pynite", _missing)
    with pytest.raises(BackendUnavailable) as excinfo:
        PyniteBackend().build(_grid_model(1), [])
    message = str(excinfo.value)
    assert "PyNiteFEA" in message
    assert "numpy" in message
    assert "1.26.0" in message
    assert "takedown + diaphragm" in message


@pytest.mark.skipif(PYNITE_INSTALLED, reason="PyNiteFEA is installed in this environment")
def test_the_real_import_path_refuses_cleanly_when_pynite_is_absent():
    with pytest.raises(BackendUnavailable) as excinfo:
        PyniteBackend().build(_grid_model(1), [])
    assert "numpy==1.26.0" in str(excinfo.value)


def test_solving_refuses_too_and_the_backend_names_itself():
    backend = PyniteBackend()
    assert backend.name == "pynite"
    with pytest.raises(BackendUnavailable):
        backend.solve([])


# ---------------------------------------------------------------------------
# the v1 path
# ---------------------------------------------------------------------------


def test_assemble_storey_shears_envelopes_the_cases_it_is_given():
    cases, _ = build_seismic(
        [{"storey": index, "w_dl_kn": 2000.0, "z_top_m": 3.0 * (index + 1)} for index in range(2)],
        {"x_m": 20.0, "y_m": 20.0},
        SeismicContext(zone="III", soil="II", system="smrf"),
    )
    shears = assemble_storey_shears(cases)
    base = cases[0]["base_shear_kn"]
    assert shears["x"][0] == pytest.approx(base, rel=1e-12)
    assert shears["y"][0] == pytest.approx(base, rel=1e-12)
    # The plus and minus cases of one axis carry the same magnitudes.
    assert shears["x"] == pytest.approx(diaphragm.storey_shears_from_case(cases[0])["x"])
    assert list(shears["x"]) == [0, 1]


def test_analyze_lateral_runs_the_cases_through_the_diaphragm():
    model = _grid_model(2)
    cases, report = build_seismic(
        [{"storey": index, "w_dl_kn": 2000.0, "z_top_m": 3.0 * (index + 1)} for index in range(2)],
        {"x_m": 6.0, "y_m": 4.0},
        SeismicContext(zone="III", soil="II", system="smrf"),
    )
    result = analyze_lateral(model, cases, centres_of_mass={0: (3.0, 2.0), 1: (3.0, 2.0)})

    shears = assemble_storey_shears(cases)
    assert result.storey(0, "x").shear_kn == pytest.approx(shears["x"][0], rel=1e-12)
    assert result.storey(1, "y").shear_kn == pytest.approx(shears["y"][1], rel=1e-12)
    # The ground storey carries the whole base shear of its direction.
    assert result.storey(0, "x").shear_kn == pytest.approx(
        report["directions"]["x"]["base_shear_kn"], rel=1e-12
    )
    assert [share.v_direct_kn for share in result.storey(0, "x").elements] == pytest.approx(
        [result.storey(0, "x").shear_kn / 4.0] * 4, rel=1e-12
    )
    json.dumps(result.to_dict(), sort_keys=True)
