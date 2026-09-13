"""Pins for API disclosure policy and the emitted code-set summary."""

from __future__ import annotations

import shutil
from pathlib import Path

from .. import api
from ..data import _loader


def _policy(block):
    return next(row for row in api.DETAIL_POLICY if row["block"] == block)


def test_compact_policy_names_report_disclosure_elision_and_the_ladder_that_remains():
    """N33: compact report disclosures retain only ERROR rows; the ladder stays whole."""
    policy = _policy("report.bbs.items / report.disclosures")

    assert "WARNING and NOTE report disclosures at compact" in policy["elided"]
    assert "every ERROR disclosure" in policy["kept"]
    assert "entry-level errors and warnings carry the whole ladder" in policy["reason"]


def test_compact_policy_names_passing_member_extras_that_are_elided_or_preserved():
    """N34: compact preserves masonry prescription while documenting other extras."""
    policy = _policy("structural_model.design[]")

    assert "masonry and prescription extras for masonry walls" in policy["kept"]
    assert "ductile, flexure, serviceability and shear extras for beams" in policy["elided"]
    assert "deflection_route, edges, method and slab_mode extras for slabs" in policy["elided"]
    assert "si extras for footings" in policy["elided"]


def test_compact_masonry_row_keeps_the_wall_waterfall_and_prescription():
    """N34: a passing masonry compact row must retain its adopted material record."""
    full = {
        "element_id": "wall-1@s0",
        "element_type": "masonry_wall",
        "status": "resized",
        "section": {"thickness_mm": 230.0},
        "checks": [],
        "bars": [],
        "stirrups": [],
        "utilization_max": 0.7,
        "masonry": {"check": {"utilization_max": 0.7}},
        "prescription": {"mortar_grade": "M1", "thickness_mm": 230.0},
        "ductile": {"applied": False},
    }

    compact = api._compact_design_row(full, ())

    assert compact["masonry"] == full["masonry"]
    assert compact["prescription"] == full["prescription"]
    assert "ductile" not in compact


def test_code_set_is_derived_from_emitted_code_bearing_fields_only():
    """N35: code_set follows published clauses and sources, never imported modules."""
    rows = [
        {
            "checks": [
                {"clause": "IS456:2000 Cl 26.5.1.1"},
                {"clause": "IS13920:2016 Cl 6.3.5"},
                {"clause": "IS1905:1987 Cl 5.4.1"},
            ],
            "prescription": {"bands": [{"code": "IS4326:1993 Table 7"}]},
            "extras": {"source": "IS 6403:1981, imported but not emitted as a code field"},
        }
    ]
    load_wire = {"cases": [{"source": "IS 875-2:1987 Table 1"}]}
    seismic = {"code": "IS 1893-1:2016 Cl 7.8", "note": "IS 6403 stays absent"}

    assert api._design_code_set(rows, load_wire, seismic) == [
        "IS 456:2000",
        "IS 875-2:1987",
        "IS 1893-1:2016",
        "IS 13920:2016",
        "IS 1905:1987",
        "IS 4326:1993",
    ]


def test_structural_fingerprint_hashes_all_table_bytes_and_the_table_roster(tmp_path):
    """B33: value edits and added or removed YAML files invalidate dedup."""
    source_dir = Path(_loader.DATA_DIR)
    copied_dir = tmp_path / "data"
    copied_dir.mkdir()
    for source in sorted(source_dir.glob("*.yaml")):
        shutil.copyfile(str(source), str(copied_dir / source.name))

    saved_dir = _loader.DATA_DIR
    saved_fingerprint_cache = list(api._FINGERPRINT_CACHE)

    def fresh_fingerprint():
        _loader.clear_cache()
        api._FINGERPRINT_CACHE[:] = []
        return api.structural_fingerprint()

    try:
        _loader.DATA_DIR = str(copied_dir)
        baseline = fresh_fingerprint()

        table = copied_dir / "is875_2_imposed.yaml"
        contents = table.read_text(encoding="utf-8")
        corrected = contents.replace(
            "  residential_room:\n    q_kpa: 2.0",
            "  residential_room:\n    q_kpa: 3.5",
            1,
        )
        assert corrected != contents
        table.write_text(corrected, encoding="utf-8")
        value_edit = fresh_fingerprint()
        assert value_edit != baseline

        extra = copied_dir / "new_code_table.yaml"
        extra.write_bytes(b"edition: test\nvalue: 1\n")
        added_table = fresh_fingerprint()
        assert added_table != value_edit

        extra.unlink()
        assert fresh_fingerprint() == value_edit
    finally:
        _loader.DATA_DIR = saved_dir
        _loader.clear_cache()
        api._FINGERPRINT_CACHE[:] = saved_fingerprint_cache
