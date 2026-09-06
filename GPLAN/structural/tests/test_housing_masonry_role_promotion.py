"""Eligible adjacent wall pieces close a real line without leaking core roles."""

import copy

import pytest

from ..model import ModelSource, Storey, StructuralModel, System, WallLine, WallRole
from ..placement import masonry as PM


def _model(source=ModelSource.HOUSING, storeys=1):
    model = StructuralModel(source=source)
    model.storeys = [Storey(i, str(i), 3.0 * i, 3.0) for i in range(storeys)]
    segments = [
        ("south", (0., 0.), (8., 0.), WallRole.EXTERIOR),
        ("north", (0., 8.), (8., 8.), WallRole.EXTERIOR),
        ("west", (0., 0.), (0., 8.), WallRole.EXTERIOR),
        ("east", (8., 0.), (8., 8.), WallRole.EXTERIOR),
        ("interior", (0., 4.), (4., 4.), WallRole.INTERIOR),
        ("core", (4., 4.), (8., 4.), WallRole.CORE),
    ]
    model.walls = [WallLine(name, 0, a, b, .23, role) for name, a, b, role in segments]
    return model


def _cover(model, **kwargs):
    params = PM.MasonryParams()
    walls = PM._masonry_walls(model, 0)
    eligibility = PM._eligibility(model, params, walls, PM._stack_index(model))
    return PM._cover_storey(PM._StoreyGrid(model, 0, walls), walls, eligibility,
                           System.LOAD_BEARING_MASONRY.value, params, **kwargs)


@pytest.mark.parametrize("storeys", [1, 2, 3])
def test_adjacent_eligible_role_pieces_close_cover_only_as_a_group(storeys):
    model = _model(storeys=storeys)
    original_walls = copy.deepcopy(model.walls)
    assert _cover(model, banned=["core"]).gaps
    assert _cover(model, banned=["interior"]).gaps
    result = _cover(model)
    assert not result.gaps
    assert {"core", "interior"}.issubset(result.bearing)
    assert all(panel.short_span_m == 4.0 for panel in result.panels)
    assert any("promoted contiguous eligible Housing wall pieces" in row for row in result.trace)
    assert model.walls == original_walls


@pytest.mark.parametrize("source,storeys", [
    (ModelSource.BUILDING, 1), (ModelSource.PLAN_JSON, 1), (ModelSource.HOUSING, 4),
])
def test_nonhousing_and_four_storeys_never_enter_group_fallback(monkeypatch, source, storeys):
    def unexpected(*args):
        pytest.fail("out-of-scope model entered Housing group fallback")
    monkeypatch.setattr(PM, "_housing_role_split_groups", unexpected)
    assert _cover(_model(source, storeys)).gaps


@pytest.mark.parametrize("change", ["gap", "parallel", "thin", "same_role"])
def test_role_group_never_bridges_gaps_or_bypasses_individual_eligibility(change):
    model = _model()
    core = next(wall for wall in model.walls if wall.id == "core")
    if change == "gap":
        core.a = (4.01, 4.)
    elif change == "parallel":
        core.a, core.b = (4., 4.01), (8., 4.01)
    elif change == "thin":
        core.thickness_m = .09
    else:
        core.role = WallRole.INTERIOR
    assert _cover(model).gaps


def test_single_wall_improvement_does_not_enter_group_fallback(monkeypatch):
    model = _model()
    model.walls = [wall for wall in model.walls if wall.id != "core"]
    next(wall for wall in model.walls if wall.id == "interior").b = (8., 4.)
    def unexpected(*args):
        pytest.fail("group fallback entered before available single-wall improvement")
    monkeypatch.setattr(PM, "_housing_role_split_groups", unexpected)
    assert not _cover(model).gaps
