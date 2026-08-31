"""Pins for report.py: the ladder, the caps, the trace flag, and the disclaimer.

The disclaimer is product-legal (finding 29), so it gets the widest net here:
every path this module can produce is asserted to carry it verbatim, and the
returned envelope is asserted to refuse every way a caller could remove it.
"""

from __future__ import annotations

import copy
import json

import pytest

# Relative: see the note in test_model_roundtrip.py.
from .. import model as MM
from .. import report as R
from ..codes.trace import TraceEntry, clause, trace_into
from ..design.common import CheckRow, DesignResult


# ---------------------------------------------------------------------------
# builders
# ---------------------------------------------------------------------------


def _model(storeys=2):
    model = MM.StructuralModel(id="m1", system=MM.System.RC_FRAME)
    for index in range(storeys):
        model.storeys.append(
            MM.Storey(index=index, name="L" + str(index), bottom_z_m=3.0 * index, height_m=3.0)
        )
    for index in range(storeys):
        model.columns.append(
            MM.Column(
                id="col-1-A-s" + str(index),
                stack_id="stk-1-A",
                storey=index,
                x_m=0.0,
                y_m=0.0,
                width_m=0.23,
                depth_m=0.45,
            )
        )
        model.beams.append(
            MM.Beam(
                id="beam-s" + str(index) + "-x1-0",
                storey=index,
                a=(0.0, 0.0),
                b=(4.0, 0.0),
                width_m=0.23,
                depth_m=0.45,
            )
        )
        model.slabs.append(
            MM.SlabPanel(
                id="slab-s" + str(index) + "-0",
                storey=index,
                polygon=[(0.0, 0.0), (4.0, 0.0), (4.0, 3.0), (0.0, 3.0)],
                thickness_m=0.125,
            )
        )
    model.footings.append(
        MM.Footing(id="ftg-stk-1-A", kind=MM.FootingKind.ISOLATED, supports=["stk-1-A"])
    )
    model.walls.append(
        MM.WallLine(
            id="wall-s0-h-0-0",
            storey=0,
            a=(0.0, 0.0),
            b=(4.0, 0.0),
            thickness_m=0.23,
            bearing=True,
        )
    )
    model.walls.append(
        MM.WallLine(
            id="wall-s0-v-0-0",
            storey=0,
            a=(0.0, 0.0),
            b=(0.0, 3.0),
            thickness_m=0.115,
            bearing=False,
        )
    )
    return model


def _beam_result(element_id="beam-s0-x1-0", status="pass", ratio=0.83):
    result = DesignResult(element_id=element_id, element_type="beam")
    result.section = {"b_mm": 230.0, "D_mm": 450.0, "d_mm": 410.0, "cover_mm": 25.0}
    result.materials = {"fck_mpa": 25.0, "fy_mpa": 500.0, "concrete_grade": "M25", "steel_grade": "Fe500"}
    result.add_bar(role="bottom", count=4, dia_mm=16.0, ld_mm=800.0, zone_mm=[0.0, 4000.0])
    result.add_bar(role="top", count=2, dia_mm=12.0, ld_mm=600.0, zone_mm=[0.0, 1000.0])
    result.add_stirrup(zone_mm=[0.0, 900.0], legs=2, dia_mm=8.0, spacing_mm=100.0, kind="shear")
    result.add_stirrup(zone_mm=[900.0, 3100.0], legs=2, dia_mm=8.0, spacing_mm=150.0, kind="shear")
    result.add_check("flexure", "IS456:2000 G-1.1", 83.0, 100.0, units="kNm")
    result.add_check("shear", "IS456:2000 40.4", 40.0, 100.0, units="kN")
    result.checks[0].ratio = ratio
    result.status = status
    result.governing_check = "flexure"
    result.utilization_max = ratio
    return result


def _column_result(element_id="col-1-A-s0", ratio=0.55):
    result = DesignResult(element_id=element_id, element_type="column")
    result.section = {"b_mm": 230.0, "D_mm": 450.0, "cover_mm": 40.0, "length_mm": 3000.0}
    result.materials = {"concrete_grade": "M25", "steel_grade": "Fe500"}
    result.add_bar(role="longitudinal", count=6, dia_mm=16.0, ld_mm=800.0, zone_mm=[0.0, 3000.0])
    result.add_stirrup(zone_mm=[0.0, 3000.0], legs=2, dia_mm=8.0, spacing_mm=150.0, kind="tie")
    result.add_check("axial_moment", "IS456:2000 39.6", 550.0, 1000.0, units="kN")
    result.checks[0].ratio = ratio
    result.utilization_max = ratio
    result.governing_check = "axial_moment"
    return result


def _dict_result(element_id, element_class="beam", status="pass", ratio=0.5):
    return {
        "element_id": element_id,
        "element_type": element_class,
        "status": status,
        "utilization_max": ratio,
        "governing_check": "flexure",
        "section": {"b_mm": 230.0, "D_mm": 450.0},
        "materials": {"concrete_grade": "M25"},
        "bars": [{"role": "bottom", "count": 3, "dia_mm": 16.0, "ld_mm": 800.0, "zone_mm": [0.0, 1.0]}],
        "stirrups": [],
        "checks": [
            {
                "name": "flexure",
                "clause": "IS456:2000 G-1.1",
                "demand": ratio * 100.0,
                "capacity": 100.0,
                "ratio": ratio,
                "status": "pass" if ratio <= 1.0 else "fail",
                "units": "kNm",
            }
        ],
    }


def _takeoff():
    return {
        "concrete": [
            {"class": "column", "grade": "M25", "volume_m3": 1.24, "basis": "b x D x clear height"},
            {"class": "beam", "grade": "M25", "volume_m3": 2.06, "basis": "b x D x clear span"},
            {"class": "slab", "grade": "M20", "volume_m3": 3.7, "basis": "panel area x thickness"},
        ],
        "formwork": [
            {"class": "column", "area_m2": 12.5, "basis": "perimeter x clear height"},
            {"class": "beam", "area_m2": 18.0, "basis": "2 sides + soffit"},
        ],
        "masonry": [
            {
                "thickness_mm": 230,
                "bearing": True,
                "volume_m3": 8.4,
                "deductions_m3": 1.1,
                "basis": "IS 1200 Part 3",
            },
        ],
        "earthwork": {
            "excavation_m3": 9.6,
            "pcc_m3": 0.8,
            "backfill_m3": 5.2,
            "disposal_m3": 4.4,
            "basis": "working space 0.3 m",
        },
    }


def _bbs(items=None):
    items = items if items is not None else [
        {
            "bar_mark": "B1-L1",
            "element_id": "beam-s0-x1-0",
            "element_class": "beam",
            "shape_code": "STR",
            "dia_mm": 16,
            "count": 4,
            "cut_length_m": 4.8,
            "unit_mass_kg_m": 1.578,
            "total_mass_kg": 30.3,
            "notes": [],
        },
        {
            "bar_mark": "C1-L1",
            "element_id": "col-1-A-s0",
            "element_class": "column",
            "shape_code": "STR",
            "dia_mm": 16,
            "count": 6,
            "cut_length_m": 3.8,
            "unit_mass_kg_m": 1.578,
            "total_mass_kg": 36.0,
            "notes": [],
        },
    ]
    total = round(sum(item["total_mass_kg"] for item in items), 3)
    return {
        "shape_codes_deferred": True,
        "items": items,
        "mass_by_dia": {"16": total},
        "mass_by_class": {"beam": 30.3, "column": 36.0},
        "total_kg": total,
        "wastage_pct": 3.0,
        "total_with_wastage_kg": round(total * 1.03, 3),
    }


def _boq(items=None):
    items = items if items is not None else [
        {
            "sl": 1,
            "item": "RCC M25",
            "spec": "columns and beams",
            "unit": "m3",
            "qty": 3.3,
            "rate": 7800.0,
            "amount": 25740.0,
            "rate_source": "default_india",
        }
    ]
    return {
        "schedule": "default_india",
        "currency": "INR",
        "placeholder_rates": True,
        "items": items,
        "subtotals": {"concrete": 25740.0, "steel": 5148.0},
        "total": 30888.0,
        "builtup_area_m2": 96.0,
        "cost_per_m2": 321.75,
        "steel_kg_per_m2": 0.688,
        "concrete_m3_per_m2": 0.07,
    }


def _layout():
    return {
        "score": 82,
        "score_version": "frame-1",
        "hard_violations": {"E_TRANSFER_REQUIRED": 0},
        "span_histogram": {
            "lt_2_5": 0,
            "2_5_3": 1,
            "3_4": 4,
            "4_5": 3,
            "5_6": 0,
            "6_7_5": 0,
            "gt_7_5": 0,
            "pct_in_2_5_to_5": 100.0,
        },
        "axis_count": {"x": 3, "y": 3, "x_inserted": 0, "y_inserted": 1},
        "column_eccentricity_mm": {"mean": 12, "max": 40},
        "torsion_proxy_pct": {"x": 1.2, "y": 3.4},
        "columns_per_100m2": 5.4,
        "beams_under_walls_pct": 96,
        "load_path_depth": 2,
    }


def _seismic():
    return {
        "code": "IS1893:2016",
        "zone": "III",
        "z": 0.16,
        "i": 1.0,
        "r": 3.0,
        "seismic_weight_kn": 1840.0,
        "directions": {
            "x": {"ta_s": 0.31, "ah": 0.0267, "base_shear_kn": 49.1},
            "y": {"ta_s": 0.42, "ah": 0.0267, "base_shear_kn": 44.0},
        },
    }


def _log(*specs):
    log = MM.DisclosureLog()
    for code, message, ids in specs:
        log.add(code, message, ids, stage="test")
    return log


def _full_report(**kwargs):
    args = {
        "model": _model(),
        "placement": {"metrics": _layout(), "system": "rc_frame"},
        "analysis": {},
        "design_results": [_beam_result(), _column_result()],
        "takeoff": _takeoff(),
        "bbs": _bbs(),
        "boq": _boq(),
        "layout_score": _layout(),
        "disclosures": _log(("N_WASTAGE_3PCT", "3 percent wastage", ())),
    }
    args.update(kwargs)
    return R.build_report(
        args["model"],
        args["placement"],
        args["analysis"],
        args["design_results"],
        args["takeoff"],
        args["bbs"],
        args["boq"],
        args["layout_score"],
        args["disclosures"],
        args.get("options"),
    )


# ---------------------------------------------------------------------------
# the disclaimer: every path, verbatim, unstrippable (finding 29)
# ---------------------------------------------------------------------------


def test_disclaimer_is_the_spec_text_verbatim():
    assert R.DISCLAIMER.startswith(
        "PRELIMINARY ENGINEERING NOTICE. This structural scheme, analysis, design,"
    )
    assert R.DISCLAIMER.endswith("Rates marked PLACEHOLDER are indicative only.")
    assert "NOT a construction-ready design" in R.DISCLAIMER
    assert "licensed structural engineer" in R.DISCLAIMER
    assert "geotechnical investigation is" in R.DISCLAIMER
    assert "PLACEHOLDER" in R.DISCLAIMER
    assert R.DISCLAIMER.count("\n") == 8


def test_disclaimer_is_ascii_and_carries_no_dashes_of_any_kind():
    assert R.DISCLAIMER.encode("ascii")
    assert not any(ord(ch) > 127 for ch in R.DISCLAIMER)
    assert chr(8212) not in R.DISCLAIMER  # em dash
    assert chr(8211) not in R.DISCLAIMER  # en dash
    assert "--" not in R.DISCLAIMER


def test_disclaimer_one_line_is_the_same_notice_reflowed():
    assert "\n" not in R.DISCLAIMER_ONE_LINE
    assert R.disclaimer_matches(R.DISCLAIMER)
    assert R.disclaimer_matches(R.DISCLAIMER_ONE_LINE)
    assert not R.disclaimer_matches("PRELIMINARY ENGINEERING NOTICE.")
    assert not R.disclaimer_matches(None)


@pytest.mark.parametrize(
    "report",
    [
        R.build_report(),
        R.build_report(_model()),
        _full_report(),
        _full_report(disclosures=_log(("W_ASSUMED_SBC", "default sbc", ("ftg-stk-1-A",)))),
        _full_report(disclosures=_log(("E_TRANSFER_REQUIRED", "floating column", ()))),
        _full_report(disclosures=_log(("E_CANTILEVER_SPAN", "too long", ("beam-s0-x1-0",)))),
        _full_report(design_results=[], takeoff=None, bbs=None, boq=None, layout_score=None),
        _full_report(options={"include_trace": True}),
    ],
)
def test_disclaimer_is_present_on_every_path(report):
    assert report["disclaimer"] == R.DISCLAIMER
    assert R.disclaimer_matches(report["disclaimer"])


def test_disclaimer_survives_a_json_round_trip_on_the_refusal_path():
    report = _full_report(disclosures=_log(("E_MASONRY_LIMIT", "four storeys of masonry", ())))
    assert report["summary"]["status"] == R.STATUS_REFUSED
    wire = json.loads(json.dumps(report))
    assert wire["disclaimer"] == R.DISCLAIMER


def test_the_envelope_refuses_every_way_of_stripping_the_disclaimer():
    report = _full_report()
    with pytest.raises(ValueError):
        del report["disclaimer"]
    with pytest.raises(ValueError):
        report.pop("disclaimer")
    with pytest.raises(ValueError):
        report["disclaimer"] = ""
    with pytest.raises(ValueError):
        report.update({"disclaimer": "see terms"})
    with pytest.raises(ValueError):
        report.clear()
    assert report["disclaimer"] == R.DISCLAIMER


def test_the_envelope_allows_every_other_mutation():
    report = _full_report()
    report["extra"] = 1
    report.update({"another": 2})
    del report["extra"]
    assert report.pop("another") == 2
    report["disclaimer"] = R.DISCLAIMER
    assert report["disclaimer"] == R.DISCLAIMER


def test_popitem_refuses_only_when_the_disclaimer_is_last():
    report = R.build_report()
    report["tail"] = 1
    assert report.popitem() == ("tail", 1)
    while list(report.keys())[-1] != "disclaimer":
        report.popitem()
    with pytest.raises(ValueError):
        report.popitem()


def test_deepcopy_keeps_the_guard_and_the_text():
    clone = copy.deepcopy(_full_report())
    assert clone["disclaimer"] == R.DISCLAIMER
    with pytest.raises(ValueError):
        del clone["disclaimer"]


def test_with_disclaimer_stamps_and_protects_any_envelope():
    envelope = R.with_disclaimer({"status": "ERROR", "message": "bad plan"})
    assert envelope["disclaimer"] == R.DISCLAIMER
    assert envelope["status"] == "ERROR"
    with pytest.raises(ValueError):
        del envelope["disclaimer"]
    assert R.with_disclaimer(None)["disclaimer"] == R.DISCLAIMER
    assert R.with_disclaimer({"disclaimer": "nope"})["disclaimer"] == R.DISCLAIMER


# ---------------------------------------------------------------------------
# collect_disclosures
# ---------------------------------------------------------------------------


def test_collect_disclosures_merges_stages_and_dedupes_by_code_and_message():
    # identical condition from two stages: one entry, element ids merged
    first = _log(("W_ASSUMED_SBC", "default sbc", ("ftg-a",)), ("N_WASTAGE_3PCT", "3 pct", ()))
    second = _log(("W_ASSUMED_SBC", "default sbc", ("ftg-b", "ftg-a")))
    merged = R.collect_disclosures(first, second)
    assert [entry.code for entry in merged.entries] == ["W_ASSUMED_SBC", "N_WASTAGE_3PCT"]
    assert merged.entries[0].element_ids == ["ftg-a", "ftg-b"]
    assert merged.entries[0].message == "default sbc"


def test_collect_disclosures_does_not_mutate_the_stage_logs():
    first = _log(("W_ASSUMED_SBC", "default sbc", ("ftg-a",)))
    second = _log(("W_ASSUMED_SBC", "again", ("ftg-b",)))
    R.collect_disclosures(first, second)
    assert first.entries[0].element_ids == ["ftg-a"]
    assert second.entries[0].element_ids == ["ftg-b"]


def test_collect_disclosures_accepts_every_stage_shape():
    model = _model()
    model.add_warning("W_NO_STAIR", "no stair core", ["core-1"])
    single = MM.make_disclosure("W_TALL", "six storeys", ["col-1-A-s0"])
    as_dicts = [MM.make_disclosure("N_LAP_50D_FLAT", "flat laps", []).to_dict()]
    stage_dict = {"disclosures": [MM.make_disclosure("W_TORSION", "offset", []).to_dict()]}
    merged = R.collect_disclosures(model, single, as_dicts, stage_dict, None, [])
    assert merged.codes() == ["N_LAP_50D_FLAT", "W_NO_STAIR", "W_TALL", "W_TORSION"]
    assert merged.counts() == {"error": 0, "warning": 3, "note": 1}


def test_collect_disclosures_of_nothing_is_an_empty_log():
    merged = R.collect_disclosures()
    assert isinstance(merged, MM.DisclosureLog)
    assert merged.entries == []
    assert merged.counts() == {"error": 0, "warning": 0, "note": 0}


def test_collect_disclosures_sorts_the_severity_ladder():
    log = _log(
        ("N_WASTAGE_3PCT", "note", ()),
        ("W_TALL", "warning", ()),
        ("E_GRID_COARSE", "error", ("col-1-A-s0",)),
    )
    report = _full_report(disclosures=log)
    assert [row["severity"] for row in report["disclosures"]] == ["error", "warning", "note"]


# ---------------------------------------------------------------------------
# the ERROR rule
# ---------------------------------------------------------------------------


def test_an_error_blocks_its_element_and_zeroes_its_quantity_rows():
    log = _log(("E_CANTILEVER_SPAN", "cantilever over the cap", ("beam-s0-x1-0",)))
    report = _full_report(disclosures=log)

    card = [c for c in report["element_cards"] if c["element_id"] == "beam-s0-x1-0"][0]
    assert card["status"] == R.CARD_BLOCKED
    assert card["disclosure_codes"] == ["E_CANTILEVER_SPAN"]
    assert card["governing"]["utilization"] == 0.83

    rows = {item["element_id"]: item for item in report["bbs"]["items"]}
    assert rows["beam-s0-x1-0"]["total_mass_kg"] == 0.0
    assert rows["beam-s0-x1-0"]["count"] == 0
    assert rows["beam-s0-x1-0"]["blocked_by"] == ["E_CANTILEVER_SPAN"]
    assert rows["col-1-A-s0"]["total_mass_kg"] == 36.0

    assert report["bbs"]["blocked_mass_kg"] == 30.3
    assert report["bbs"]["total_kg"] == 36.0
    assert report["bbs"]["mass_by_class"] == {"beam": 0.0, "column": 36.0}
    assert report["bbs"]["total_with_wastage_kg"] == round(36.0 * 1.03, 3)

    assert report["blocked_elements"] == [
        {
            "element_id": "beam-s0-x1-0",
            "element_class": "beam",
            "codes": ["E_CANTILEVER_SPAN"],
            "reason": "blocked by E_CANTILEVER_SPAN",
            "quantities_zeroed": True,
        }
    ]
    assert report["summary"]["blocked_element_count"] == 1


def test_the_costed_gross_steel_reconciles_to_the_blocked_net_schedule():
    """B32: the display correction cannot silently change the costed headline.

    The old report replaced `steel_kg` with whichever net mass it could derive
    from the displayed BBS rows. It exposed neither the removed mass nor the
    fact that the BOQ still priced the original gross schedule.
    """
    log = _log(("E_CANTILEVER_SPAN", "cantilever over the cap", ("beam-s0-x1-0",)))
    report = _full_report(disclosures=log)
    totals = report["summary"]["totals"]
    assert totals["steel_kg"] == round(66.3 * 1.03, 3)
    assert totals["steel_kg_blocked"] == round(30.3 * 1.03, 3)
    assert totals["steel_kg_net"] == round(36.0 * 1.03, 3)
    assert totals["steel_kg_net"] == report["bbs"]["total_with_wastage_kg"]
    assert totals["steel_kg"] == pytest.approx(totals["steel_kg_blocked"] + totals["steel_kg_net"])
    assert totals["steel_cost_basis"] == "steel_kg"


def test_no_error_leaves_the_schedule_untouched():
    bbs = _bbs()
    report = _full_report(bbs=copy.deepcopy(bbs))
    assert report["bbs"]["items"] == bbs["items"]
    assert report["bbs"]["total_kg"] == bbs["total_kg"]
    assert "blocked_mass_kg" not in report["bbs"]
    assert report["blocked_elements"] == []


def test_a_failed_design_blocks_its_element_even_without_an_error_code():
    report = _full_report(design_results=[_beam_result(status="fail", ratio=1.4), _column_result()])
    card = [c for c in report["element_cards"] if c["element_id"] == "beam-s0-x1-0"][0]
    assert card["status"] == R.CARD_BLOCKED
    assert card["design_status"] == "fail"
    assert card["utilization_max"] == 1.4
    assert report["blocked_elements"][0]["codes"] == []
    assert report["blocked_elements"][0]["reason"] == "design failed on flexure"


def test_a_failed_design_zeroes_its_rows_with_a_marker_not_a_registry_code():
    report = _full_report(design_results=[_beam_result(status="fail", ratio=1.4), _column_result()])
    rows = {item["element_id"]: item for item in report["bbs"]["items"]}
    assert rows["beam-s0-x1-0"]["total_mass_kg"] == 0.0
    assert rows["beam-s0-x1-0"]["blocked_by"] == ["design_status:fail"]
    assert rows["beam-s0-x1-0"]["blocked_by"][0] not in MM.REGISTRY
    assert report["blocked_elements"][0]["quantities_zeroed"] is True
    totals = report["summary"]["totals"]
    assert totals["steel_kg"] == round(66.3 * 1.03, 3)
    assert totals["steel_kg_net"] == round(36.0 * 1.03, 3)
    assert totals["steel_kg_blocked"] == round(30.3 * 1.03, 3)


def test_quantities_zeroed_is_false_when_the_blocked_element_has_no_rows():
    log = _log(("E_SPAN_OVER_MAX", "over the cap", ("slab-s0-0",)))
    report = _full_report(
        design_results=[_dict_result("slab-s0-0", element_class="slab")], disclosures=log
    )
    assert report["blocked_elements"][0]["element_id"] == "slab-s0-0"
    assert report["blocked_elements"][0]["quantities_zeroed"] is False
    assert "blocked_mass_kg" not in report["bbs"]


def test_zeroing_survives_a_schedule_that_carries_no_aggregates():
    bare = {"items": _bbs()["items"]}
    log = _log(("E_CANTILEVER_SPAN", "over the cap", ("beam-s0-x1-0",)))
    report = _full_report(bbs=bare, disclosures=log)
    rows = {item["element_id"]: item for item in report["bbs"]["items"]}
    assert rows["beam-s0-x1-0"]["total_mass_kg"] == 0.0
    assert report["bbs"]["blocked_mass_kg"] == 30.3
    assert "total_kg" not in report["bbs"]


def test_a_system_error_names_no_element_and_blocks_nothing_element_wise():
    report = _full_report(disclosures=_log(("E_NO_BEARING_DIRECTION", "no bearing line in y", ())))
    assert report["summary"]["status"] == R.STATUS_REFUSED
    assert report["blocked_elements"] == []
    assert all(card["status"] != R.CARD_BLOCKED for card in report["element_cards"])


def test_an_element_error_does_not_refuse_the_whole_system():
    report = _full_report(disclosures=_log(("E_SPAN_OVER_MAX", "span over the cap", ("beam-s0-x1-0",))))
    assert report["summary"]["status"] == R.STATUS_OK_WITH_WARNINGS
    assert report["summary"]["refusal_reasons"] == []


# ---------------------------------------------------------------------------
# the review trigger set
# ---------------------------------------------------------------------------


def test_the_review_trigger_set_fires_exactly_on_its_members():
    for code in sorted(MM.REGISTRY):
        report = _full_report(disclosures=_log((code, "condition " + code, ())))
        expected = code in R.REVIEW_TRIGGER_CODES
        assert report["summary"]["engineer_review_required"] is expected, code


def test_review_triggers_are_registered_codes():
    for code in R.REVIEW_TRIGGER_CODES:
        assert code in MM.REGISTRY


def test_no_disclosures_means_no_review_flag_but_the_disclaimer_still_ships():
    report = _full_report(disclosures=MM.DisclosureLog())
    assert report["summary"]["engineer_review_required"] is False
    assert report["summary"]["status"] == R.STATUS_OK
    assert report["disclaimer"] == R.DISCLAIMER


# ---------------------------------------------------------------------------
# status and the refusal envelope
# ---------------------------------------------------------------------------


def test_status_ok_with_warnings_when_the_ladder_carries_a_warning():
    report = _full_report(disclosures=_log(("W_PLACEHOLDER_RATES", "placeholder rates", ())))
    assert report["summary"]["status"] == R.STATUS_OK_WITH_WARNINGS


def test_status_ok_when_only_notes_are_on_the_ladder():
    report = _full_report(disclosures=_log(("N_LAP_50D_FLAT", "flat laps", ())))
    assert report["summary"]["status"] == R.STATUS_OK


def test_a_refusal_returns_a_complete_envelope_with_reasons():
    log = _log(
        ("E_MASONRY_LIMIT", "four storeys over the IS 4326 cap", ()),
        ("W_TALL", "over the thumb range", ()),
    )
    report = R.build_report(_model(), disclosures=log)
    assert tuple(report.keys()) == R.REPORT_KEYS
    assert report["summary"]["status"] == R.STATUS_REFUSED
    assert report["summary"]["refusal_reasons"] == [
        {
            "code": "E_MASONRY_LIMIT",
            "clause": None,
            "message": "four storeys over the IS 4326 cap",
            "stage": "test",
        }
    ]
    assert report["summary"]["engineer_review_required"] is True
    assert report["summary"]["disclosure_counts"] == {"error": 1, "warning": 1, "note": 0}
    assert len(report["disclosures"]) == 2
    assert report["disclaimer"] == R.DISCLAIMER


def test_a_refusal_passed_through_options_is_reported_too():
    refusal = {
        "clause": "IS4326:1993 Cl 8.1 Table 3",
        "reason": "zone V unreinforced",
        "code": "E_MASONRY_LIMIT",
    }
    report = _full_report(options={"refusals": [refusal]})
    assert report["summary"]["status"] == R.STATUS_REFUSED
    assert report["summary"]["refusal_reasons"][0]["clause"] == "IS4326:1993 Cl 8.1 Table 3"
    assert report["summary"]["refusal_reasons"][0]["message"] == "zone V unreinforced"


def test_a_refusal_still_carries_its_cards_and_metrics():
    report = _full_report(disclosures=_log(("E_GRID_COARSE", "no admissible grid", ())))
    assert report["summary"]["status"] == R.STATUS_REFUSED
    assert len(report["element_cards"]) == 2
    assert report["layout_metrics"]["score_version"] == "frame-1"
    assert report["summary"]["totals"]["cost"] == 30888.0


def test_the_empty_design_edge_case_is_a_full_envelope():
    report = R.build_report()
    assert tuple(report.keys()) == R.REPORT_KEYS
    assert report["element_cards"] == []
    assert report["element_cards_total"] == 0
    assert report["cards_elided"] == 0
    assert report["bbs"] == {}
    assert report["boq"] == {}
    assert report["summary"]["seismic"] is None
    assert report["summary"]["status"] == R.STATUS_OK
    assert report["disclaimer"] == R.DISCLAIMER
    assert json.loads(json.dumps(report))["disclaimer"] == R.DISCLAIMER


# ---------------------------------------------------------------------------
# cards
# ---------------------------------------------------------------------------


def test_cards_sort_blocked_first_then_by_descending_utilization():
    results = [
        _dict_result("b-low", ratio=0.2),
        _dict_result("b-high", ratio=0.95),
        _dict_result("b-mid", ratio=0.6),
        _dict_result("b-blocked", ratio=0.1),
    ]
    log = _log(("E_SPAN_OVER_MAX", "over the cap", ("b-blocked",)))
    report = _full_report(design_results=results, disclosures=log)
    assert [card["element_id"] for card in report["element_cards"]] == [
        "b-blocked",
        "b-high",
        "b-mid",
        "b-low",
    ]


def test_card_sort_ties_break_on_the_element_id():
    results = [_dict_result("b-2", ratio=0.5), _dict_result("b-1", ratio=0.5), _dict_result("b-3", ratio=0.5)]
    report = _full_report(design_results=results)
    assert [card["element_id"] for card in report["element_cards"]] == ["b-1", "b-2", "b-3"]


def test_cards_elide_to_the_worst_fifty_per_class_past_the_cap():
    results = []
    for kind in ("beam", "column", "slab"):
        for index in range(70):
            results.append(
                _dict_result("%s-%03d" % (kind, index), element_class=kind, ratio=index / 100.0)
            )
    report = _full_report(design_results=results)
    assert report["element_cards_total"] == 210
    assert len(report["element_cards"]) == 150
    assert report["cards_elided"] == 60
    beams = [card for card in report["element_cards"] if card["element_class"] == "beam"]
    assert len(beams) == 50
    assert beams[0]["element_id"] == "beam-069"
    assert beams[-1]["element_id"] == "beam-020"


def test_cards_are_not_elided_at_exactly_the_cap():
    results = [_dict_result("b-%03d" % index, ratio=0.1) for index in range(R.CARD_CAP)]
    report = _full_report(design_results=results)
    assert len(report["element_cards"]) == R.CARD_CAP
    assert report["cards_elided"] == 0


def test_the_card_caps_are_option_overridable():
    results = [_dict_result("b-%03d" % index, ratio=index / 100.0) for index in range(12)]
    report = _full_report(design_results=results, options={"card_cap": 5, "cards_per_class": 3})
    assert len(report["element_cards"]) == 3
    assert report["cards_elided"] == 9


def test_a_card_carries_the_spec_fields_and_the_display_strings():
    report = _full_report()
    card = [c for c in report["element_cards"] if c["element_id"] == "beam-s0-x1-0"][0]
    assert tuple(card.keys()) == R.CARD_KEYS
    assert card["element_class"] == "beam"
    assert card["storey"] == 0
    assert card["geometry_ref"] == "placement.storeys[0].beams#beam-s0-x1-0"
    assert card["section"] == "230x450 M25"
    assert card["reinforcement"] == "bottom 4-16 + top 2-12, stirrups 8@150/100"
    assert card["governing"] == {"check": "flexure", "clause": "IS456:2000 G-1.1", "utilization": 0.83}
    assert card["checks"][0] == {
        "check": "flexure",
        "clause": "IS456:2000 G-1.1",
        "demand": 83.0,
        "capacity": 100.0,
        "unit": "kNm",
        "utilization": 0.83,
        "pass": True,
    }
    assert card["disclosure_codes"] == []


def test_a_warning_on_an_element_labels_its_card():
    log = _log(("W_ECCENTRIC_COLUMN", "off the wall centreline", ("col-1-A-s0",)))
    report = _full_report(disclosures=log)
    card = [c for c in report["element_cards"] if c["element_id"] == "col-1-A-s0"][0]
    assert card["status"] == R.CARD_WARNING
    assert card["disclosure_codes"] == ["W_ECCENTRIC_COLUMN"]


def test_a_resized_design_is_a_warning_card():
    result = _beam_result(status="resized")
    report = _full_report(design_results=[result])
    assert report["element_cards"][0]["status"] == R.CARD_WARNING
    assert report["element_cards"][0]["design_status"] == "resized"


def test_utilization_is_emitted_even_when_it_is_over_one():
    report = _full_report(design_results=[_dict_result("b-1", status="fail", ratio=1.73)])
    card = report["element_cards"][0]
    assert card["utilization_max"] == 1.73
    assert card["governing"]["utilization"] == 1.73
    assert card["checks"][0]["pass"] is False


def test_build_element_card_reads_a_footing_without_a_storey():
    result = {
        "element_id": "ftg-stk-1-A",
        "element_type": "footing",
        "status": "pass",
        "section": {"bx_mm": 1500.0, "ly_mm": 1500.0, "D_mm": 450.0},
        "materials": {"concrete_grade": "M25"},
        "bars": [{"role": "mesh_x_bottom", "count": 9, "dia_mm": 12.0, "spacing_mm": 150.0, "ld_mm": 600.0}],
        "checks": [],
    }
    card = R.build_element_card(result)
    assert card.storey is None
    assert card.geometry_ref == "placement.footings#ftg-stk-1-A"
    assert card.section == "1500x1500x450 M25"
    assert card.reinforcement == "12@150"
    assert card.status == R.CARD_OK


# ---------------------------------------------------------------------------
# display strings
# ---------------------------------------------------------------------------


def test_section_text_covers_the_shapes_designers_emit():
    assert R.section_text({"b_mm": 230.0, "D_mm": 450.0}, {"concrete_grade": "M25"}) == "230x450 M25"
    assert R.section_text({"thickness_mm": 230.0}, {"mortar_grade": "M1"}) == "230 thk M1"
    assert R.section_text({"D_mm": 125.0}, {}) == "125 thk"
    assert R.section_text({"waist_mm": 150.0}, {}) == "150 waist"
    assert R.section_text({}, {}) == "-"
    assert R.section_text({"b_mm": 232.5, "D_mm": 450.0}, {}) == "232.5x450"


def test_reinforcement_text_merges_roles_and_names_them_only_when_mixed():
    single = [{"role": "bottom", "count": 4, "dia_mm": 16.0}, {"role": "bottom", "count": 2, "dia_mm": 16.0}]
    assert R.reinforcement_text(single, []) == "6-16"
    mixed = [{"role": "bottom", "count": 4, "dia_mm": 16.0}, {"role": "top", "count": 2, "dia_mm": 12.0}]
    assert R.reinforcement_text(mixed, []) == "bottom 4-16 + top 2-12"
    assert R.reinforcement_text([], []) == "-"


def test_reinforcement_text_speaks_ties_hoops_and_stirrups():
    bars = [{"role": "longitudinal", "count": 6, "dia_mm": 16.0}]
    ties = [
        {"kind": "tie", "dia_mm": 8.0, "spacing_mm": 150.0},
        {"kind": "tie", "dia_mm": 8.0, "spacing_mm": 100.0},
    ]
    assert R.reinforcement_text(bars, ties) == "6-16, ties 8@150/100"
    hoops = [{"kind": "confinement", "dia_mm": 10.0, "spacing_mm": 75.0}]
    assert R.reinforcement_text(bars, hoops) == "6-16, hoops 10@75"
    mixed = [
        {"kind": "shear", "dia_mm": 8.0, "spacing_mm": 150.0},
        {"kind": "shear", "dia_mm": 10.0, "spacing_mm": 100.0},
    ]
    assert R.reinforcement_text(bars, mixed) == "6-16, stirrups 8@150 + 10@100"


# ---------------------------------------------------------------------------
# summary blocks
# ---------------------------------------------------------------------------


def test_summary_reports_the_system_storeys_and_element_counts():
    report = _full_report()
    summary = report["summary"]
    assert summary["system"] == "rc_frame"
    assert summary["storeys"] == 2
    assert summary["height_m"] == 6.0
    assert summary["element_counts"] == {
        "columns": 2,
        "beams": 2,
        "slabs": 2,
        "footings": 1,
        "bands": 0,
        "lintels": 0,
        "walls_bearing": 1,
    }


def test_totals_are_read_from_the_quantity_blocks_never_reinvented():
    report = _full_report()
    totals = report["summary"]["totals"]
    assert tuple(totals.keys()) == R.TOTALS_KEYS
    assert totals["concrete_m3"] == 7.0
    assert totals["formwork_m2"] == 30.5
    assert totals["masonry_m3"] == 8.4
    assert totals["excavation_m3"] == 9.6
    assert totals["steel_kg"] == round(66.3 * 1.03, 3)
    assert totals["steel_kg_blocked"] == 0.0
    assert totals["steel_kg_net"] == totals["steel_kg"]
    assert totals["steel_cost_basis"] == "steel_kg"
    assert totals["cost"] == 30888.0
    assert totals["currency"] == "INR"
    assert totals["cost_per_m2"] == 321.75
    assert totals["steel_kg_per_m2"] == 0.688


def test_a_stated_total_wins_over_adding_the_rows_up():
    takeoff = _takeoff()
    takeoff["totals"] = {"concrete_m3": 6.99}
    report = _full_report(takeoff=takeoff)
    assert report["summary"]["totals"]["concrete_m3"] == 6.99


def test_the_seismic_block_mirrors_the_report_and_takes_the_governing_direction():
    model = _model()
    model.seismic = _seismic()
    report = _full_report(model=model)
    seismic = report["summary"]["seismic"]
    assert seismic["zone"] == "III"
    assert seismic["z"] == 0.16
    assert seismic["r"] == 3.0
    assert seismic["i"] == 1.0
    assert seismic["ta_s"] == 0.42
    assert seismic["base_shear_kn"] == 49.1
    assert seismic["seismic_weight_kn"] == 1840.0
    assert seismic["by_direction"]["x"]["base_shear_kn"] == 49.1
    assert seismic["by_direction"]["y"]["ta_s"] == 0.42


def test_the_seismic_block_falls_back_to_the_analysis_slot():
    report = _full_report(analysis={"seismic": _seismic()})
    assert report["summary"]["seismic"]["zone"] == "III"


def test_the_seismic_scalar_fallback_keeps_the_coefficient_precision():
    model = _model()
    model.seismic = {
        "zone": "IV",
        "z": 0.24,
        "i": 1.0,
        "r": 5.0,
        "ta_s": 0.28,
        "ah": 0.0267,
        "base_shear_kn": 61.4,
    }
    report = _full_report(model=model)
    seismic = report["summary"]["seismic"]
    assert seismic["ah"] == 0.0267
    assert seismic["ta_s"] == 0.28
    assert seismic["base_shear_kn"] == 61.4
    assert seismic["by_direction"] == {}


# ---------------------------------------------------------------------------
# layout metrics (finding 33)
# ---------------------------------------------------------------------------


def test_layout_metrics_are_mirrored_field_for_field():
    layout = _layout()
    report = _full_report(layout_score=copy.deepcopy(layout))
    assert report["layout_metrics"] == layout
    assert report["summary"]["layout_score"] == {"score": 82, "score_version": "frame-1"}


def test_score_version_is_mandatory_even_when_placement_omitted_it():
    layout = _layout()
    del layout["score_version"]
    report = _full_report(layout_score=layout)
    assert report["layout_metrics"]["score_version"] == R.UNVERSIONED_SCORE
    assert report["summary"]["layout_score"]["score_version"] == R.UNVERSIONED_SCORE
    assert report["layout_metrics"]["score"] == 82


def test_layout_metrics_fall_back_to_the_placement_block():
    report = _full_report(layout_score=None)
    assert report["layout_metrics"]["score"] == 82
    assert report["layout_metrics"]["score_version"] == "frame-1"


def test_a_missing_layout_block_still_carries_a_score_version():
    report = R.build_report(_model())
    assert report["layout_metrics"] == {"score_version": R.UNVERSIONED_SCORE}
    assert report["summary"]["layout_score"] == {"score": None, "score_version": R.UNVERSIONED_SCORE}


# ---------------------------------------------------------------------------
# embedded schedules
# ---------------------------------------------------------------------------


def test_the_bbs_and_boq_ride_inside_the_report_with_their_aggregates():
    report = _full_report()
    assert report["bbs"]["shape_codes_deferred"] is True
    assert report["bbs"]["items_elided"] is False
    assert report["bbs"]["items_total"] == 2
    assert report["bbs"]["wastage_pct"] == 3.0
    assert report["boq"]["placeholder_rates"] is True
    assert report["boq"]["items_elided"] is False
    assert report["boq"]["subtotals"] == {"concrete": 25740.0, "steel": 5148.0}


def test_the_schedules_elide_past_the_row_cap_and_keep_their_aggregates():
    items = []
    for index in range(520):
        items.append(
            {
                "bar_mark": "B%03d" % index,
                "element_id": "beam-%03d" % index,
                "element_class": "beam",
                "shape_code": "STR",
                "dia_mm": 12,
                "count": 2,
                "cut_length_m": 3.0,
                "unit_mass_kg_m": 0.888,
                "total_mass_kg": 5.328,
                "notes": [],
            }
        )
    boq_items = [dict(_boq()["items"][0], sl=index) for index in range(600)]
    report = _full_report(bbs=_bbs(items), boq=_boq(boq_items))
    assert len(report["bbs"]["items"]) == R.ROW_CAP
    assert report["bbs"]["items_elided"] is True
    assert report["bbs"]["items_total"] == 520
    assert report["bbs"]["items_shown"] == R.ROW_CAP
    assert report["bbs"]["total_kg"] == round(520 * 5.328, 3)
    assert len(report["boq"]["items"]) == R.ROW_CAP
    assert report["boq"]["items_elided"] is True
    assert report["boq"]["items_total"] == 600
    assert report["boq"]["total"] == 30888.0


def test_the_row_cap_preserves_an_upstream_producers_honest_elision():
    """B31: a truncated input may never be relabelled as a complete schedule.

    The old `_cap_rows` replaced both producer fields from `len(items)`, so 500
    received rows from a 4519-row BBS became `items_total=500, items_elided=false`.
    """
    bbs = _bbs()
    bbs["items_total"] = 4519
    bbs["items_elided"] = True

    report = _full_report(bbs=bbs)

    assert report["bbs"]["items_total"] == 4519
    assert report["bbs"]["items_shown"] == 2
    assert report["bbs"]["items_elided"] is True


def test_the_row_cap_is_option_overridable():
    report = _full_report(options={"row_cap": 1})
    assert len(report["bbs"]["items"]) == 1
    assert report["bbs"]["items_elided"] is True


def test_wrapped_quantity_blocks_are_unwrapped():
    report = _full_report(takeoff={"takeoff": _takeoff()}, bbs={"bbs": _bbs()}, boq={"boq": _boq()})
    assert report["summary"]["totals"]["concrete_m3"] == 7.0
    assert report["boq"]["currency"] == "INR"
    assert report["bbs"]["total_kg"] == 66.3


# ---------------------------------------------------------------------------
# the clause trace (finding 7)
# ---------------------------------------------------------------------------


@clause(code="IS456:2000", ref="40.2.1", title="Design shear strength", symbol="tau_c", units="MPa")
def _demo_tau_c(pt, fck):
    return 0.36 + 0.1 * pt + 0.001 * fck


def test_trace_on_and_off_differ_only_in_trace_available():
    traced = _beam_result()
    entries = []
    with trace_into(entries):
        _demo_tau_c(pt=0.75, fck=25)
    traced.trace = list(entries)

    with_trace = _full_report(design_results=[traced, _column_result()], options={"trace": True})
    without_trace = _full_report(design_results=[_beam_result(), _column_result()])

    assert with_trace["trace_available"] is True
    assert without_trace["trace_available"] is False
    left = dict(with_trace)
    right = dict(without_trace)
    del left["trace_available"]
    del right["trace_available"]
    assert left == right


def test_render_trace_formats_sink_entries_without_recomputing():
    entries = []
    with trace_into(entries):
        value = _demo_tau_c(pt=0.75, fck=25)
    rows = R.render_trace(entries)
    assert len(rows) == 1
    assert rows[0]["clause"] == "IS456:2000 40.2.1"
    assert rows[0]["symbol"] == "tau_c"
    assert rows[0]["inputs"] == {"pt": 0.75, "fck": 25}
    assert rows[0]["output"] == value
    assert rows[0]["units"] == "MPa"


def test_render_trace_accepts_dicts_and_ignores_junk():
    entry = TraceEntry(
        code="IS1893:2016",
        ref="7.6.2",
        title="Approximate fundamental period",
        symbol="Ta",
        inputs={"h_m": 6.0},
        output=0.31,
        units="s",
    )
    rows = R.render_trace([entry, entry.to_dict(), None, 7])
    assert len(rows) == 2
    assert rows[0] == rows[1]
    assert rows[0]["clause"] == "IS1893:2016 7.6.2"
    assert R.render_trace(None) == []


def test_include_trace_renders_the_sink_into_the_report():
    traced = _beam_result()
    entries = []
    with trace_into(entries):
        _demo_tau_c(pt=0.5, fck=20)
    traced.trace = list(entries)
    report = _full_report(design_results=[traced], options={"trace": True, "include_trace": True})
    assert report["trace_available"] is True
    assert report["trace"][0]["clause"] == "IS456:2000 40.2.1"
    assert report["disclaimer"] == R.DISCLAIMER


# ---------------------------------------------------------------------------
# schema shape and determinism
# ---------------------------------------------------------------------------


def test_the_emitted_report_has_exactly_the_documented_shape():
    report = _full_report()
    assert tuple(report.keys()) == R.REPORT_KEYS
    assert tuple(report["summary"].keys()) == R.SUMMARY_KEYS
    assert tuple(report["summary"]["totals"].keys()) == R.TOTALS_KEYS
    assert tuple(report["summary"]["element_counts"].keys()) == R.ELEMENT_COUNT_KEYS
    assert report["summary"]["status"] in (R.STATUS_OK, R.STATUS_OK_WITH_WARNINGS, R.STATUS_REFUSED)
    assert isinstance(report["summary"]["engineer_review_required"], bool)
    assert isinstance(report["trace_available"], bool)
    assert isinstance(report["element_cards"], list)
    assert isinstance(report["disclosures"], list)
    assert isinstance(report["blocked_elements"], list)
    assert report["meta"]["schema_version"] == "structural-1.0"
    assert report["meta"]["report_version"] == R.REPORT_VERSION
    for card in report["element_cards"]:
        assert tuple(card.keys()) == R.CARD_KEYS
        assert card["status"] in (R.CARD_OK, R.CARD_WARNING, R.CARD_BLOCKED)
    for row in report["disclosures"]:
        assert sorted(row.keys()) == ["clause", "code", "element_ids", "message", "severity", "stage"]
        assert row["code"] in MM.REGISTRY


def test_the_report_is_json_serializable_end_to_end():
    model = _model()
    model.seismic = _seismic()
    report = _full_report(model=model, disclosures=_log(("W_TALL", "tall", ("col-1-A-s0",))))
    wire = json.loads(json.dumps(report))
    assert wire["summary"]["seismic"]["zone"] == "III"
    assert wire["disclaimer"] == R.DISCLAIMER


def test_the_report_never_reads_the_clock_unless_a_timestamp_is_injected():
    assert _full_report()["meta"]["generated_at"] is None
    stamped = _full_report(options={"generated_at": "2026-08-30T00:00:00Z"})
    assert stamped["meta"]["generated_at"] == "2026-08-30T00:00:00Z"


def test_two_identical_calls_produce_identical_reports():
    first = _full_report(disclosures=_log(("W_TORSION", "offset", ("col-1-A-s0",))))
    second = _full_report(disclosures=_log(("W_TORSION", "offset", ("col-1-A-s0",))))
    assert json.dumps(first, sort_keys=True) == json.dumps(second, sort_keys=True)


def test_warnings_summary_counts_by_severity_and_lists_the_codes():
    log = _log(
        ("W_TALL", "tall", ()),
        ("N_WASTAGE_3PCT", "wastage", ()),
        ("E_TRANSFER_REQUIRED", "floating column", ("col-1-A-s0",)),
    )
    report = _full_report(disclosures=log)
    assert report["warnings_summary"]["counts"] == {"error": 1, "warning": 1, "note": 1}
    assert report["warnings_summary"]["codes"] == ["E_TRANSFER_REQUIRED", "N_WASTAGE_3PCT", "W_TALL"]
    assert report["summary"]["disclosure_counts"] == report["warnings_summary"]["counts"]


def test_the_ladder_is_merged_from_the_stages_when_no_log_is_passed():
    model = _model()
    model.add_warning("W_NO_STAIR", "no stair core", ["core-1"])
    report = R.build_report(model, {"disclosures": [MM.make_disclosure("W_TALL", "tall", []).to_dict()]})
    assert [row["code"] for row in report["disclosures"]] == ["W_NO_STAIR", "W_TALL"]


def test_design_results_may_arrive_as_objects_or_as_dicts():
    from_objects = _full_report(design_results=[_beam_result()])
    from_dicts = _full_report(design_results=[_beam_result().to_dict()])
    assert from_objects["element_cards"] == from_dicts["element_cards"]


def test_build_report_never_raises_on_junk_inputs():
    report = R.build_report(
        model="not a model",
        placement=7,
        analysis=[1, 2],
        design_results=[None, 3, "x", {}],
        takeoff="nope",
        bbs=object(),
        boq=[],
        layout_score=42,
        disclosures="nothing",
        options="not options",
    )
    assert tuple(report.keys()) == R.REPORT_KEYS
    assert report["element_cards"] == []
    assert report["disclaimer"] == R.DISCLAIMER
    assert report["summary"]["status"] == R.STATUS_OK


def test_a_stage_that_cannot_serialize_does_not_crash_the_report():
    class Broken(object):
        def to_dict(self):
            raise RuntimeError("boom")

    report = R.build_report(_model(), design_results=[Broken()], bbs=Broken())
    assert report["element_cards"] == []
    assert report["bbs"] == {}
    assert report["disclaimer"] == R.DISCLAIMER


def test_a_check_row_object_renders_the_same_as_its_dict():
    row = CheckRow.evaluate("flexure", "IS456:2000 G-1.1", 83.0, 100.0, units="kNm")
    card = R.build_element_card(
        {"element_id": "b-1", "element_type": "beam", "status": "pass", "checks": [row]}
    )
    assert card.checks[0]["check"] == "flexure"
    assert card.checks[0]["pass"] is True
    assert card.governing["clause"] == "IS456:2000 G-1.1"
