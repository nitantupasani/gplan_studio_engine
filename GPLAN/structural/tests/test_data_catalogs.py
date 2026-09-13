"""The catalogue tables, checked against the arithmetic they claim to encode.

A transcribed table is only as good as the relations it satisfies: bar areas
are pi/4 d^2, nominal masses are d^2/162, a rolled section's Zex is Ixx/(h/2),
its radii of gyration are sqrt(I/A) and its mass is 7.85 g/cm3 of its area.
None of that proves the handbook was read correctly (hence `verify: "print"` on
every section), but it catches the transcription slips that would otherwise
reach a member size.

Provenance is checked too: a table without `source` and `edition` cannot appear
in the report bibliography, and a disclosure code named in a table must exist
in model.REGISTRY or the producer would raise when it fired.
"""

from __future__ import annotations

import math

import pytest

# Relative: see the note in test_model_roundtrip.py (the engine repo root carries
# its own __init__.py, so an absolute GPLAN.structural import resolves wrongly).
from ..data._loader import load_yaml, require_keys
from ..design.steel import sections as sec
from ..model import REGISTRY

# Tables this spec owns. Other agents' tables are their own battery's business.
OWNED_TABLES = (
    "rates",
    "rebar",
    "sections_is808",
    "soil_defaults",
    "steel_mass",
)

MAIN_DIAS = (8, 10, 12, 16, 20, 25, 32)
STIRRUP_DIAS = (8, 10, 12)

# Steel density 7850 kg/m3 expressed per cm2 of section, kg/m.
MASS_PER_CM2 = 0.785

# Sections symmetric about the x axis: Zex = Ixx / (h/2) holds exactly.
X_SYMMETRIC = ("ISMB", "ISMC", "ISLB", "ISHB")
# I sections: Zey = Iyy / (bf/2) as well. A channel measures Zey to the back of
# the web and an angle to its centroid, so neither is included.
I_SECTIONS = ("ISMB", "ISLB", "ISHB")


# ---------------------------------------------------------------------------
# provenance
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("name", sorted(set(OWNED_TABLES)))
def test_table_carries_source_and_edition(name):
    table = load_yaml(name)
    require_keys(table, ("source", "edition", "schema_version"), name)
    assert str(table["source"]).strip(), name + " has an empty source"
    assert str(table["edition"]).strip(), name + " has an empty edition"


def test_named_disclosure_codes_are_registered():
    """A table that names a code the registry does not hold would raise later."""
    codes = [load_yaml("rates")["disclosure_code"]]
    codes.extend(load_yaml("soil_defaults")["defaults"]["disclosures"].values())
    for code in codes:
        assert code in REGISTRY, code + " is not in model.REGISTRY"


# ---------------------------------------------------------------------------
# rebar.yaml
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def rebar():
    return load_yaml("rebar")


def test_rebar_dia_lists(rebar):
    assert tuple(rebar["main_dias_mm"]) == MAIN_DIAS
    assert tuple(rebar["stirrup_dias_mm"]) == STIRRUP_DIAS
    assert sorted(rebar["bars"]) == sorted(MAIN_DIAS)
    assert set(STIRRUP_DIAS).issubset(set(rebar["bars"]))


@pytest.mark.parametrize("dia", MAIN_DIAS)
def test_rebar_area_is_pi_over_four_d_squared(rebar, dia):
    exact = math.pi / 4.0 * dia * dia
    assert rebar["bars"][dia]["area_mm2"] == pytest.approx(exact, rel=0.005)


@pytest.mark.parametrize("dia", MAIN_DIAS)
def test_rebar_unit_mass_is_the_nominal_formula(rebar, dia):
    """0.006165 d^2 as tabulated, and within 0.3 percent of d^2/162."""
    assert rebar["bars"][dia]["unit_mass_kg_m"] == pytest.approx(0.006165 * dia * dia, rel=1e-6)
    assert rebar["bars"][dia]["unit_mass_kg_m"] == pytest.approx(dia * dia / 162.0, rel=0.003)


def test_rebar_bend_allowances(rebar):
    bends = rebar["bend_allowances"]
    assert bends["hook_135_deg_dia"] == 10
    assert bends["hook_90_deg_dia"] == 8
    assert bends["stirrup_two_hook_dia"] == 2 * bends["hook_135_deg_dia"]
    assert bends["verify"] == "print"


def test_rebar_defines_no_covers(rebar):
    """Resolution 25: cover comes from DesignResult.section, never a default."""
    flat = " ".join(sorted(str(key) for key in rebar))
    assert "cover" not in flat


# ---------------------------------------------------------------------------
# steel_mass.yaml
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def steel_mass():
    return load_yaml("steel_mass")


@pytest.mark.parametrize("dia", MAIN_DIAS)
def test_steel_mass_table_is_d_squared_over_162(steel_mass, dia):
    assert steel_mass["unit_mass_kg_m"][dia] == pytest.approx(dia * dia / 162.0, rel=0.003)


def test_steel_mass_stock_length(steel_mass):
    assert steel_mass["stock_length_m"] == 12.0


@pytest.mark.parametrize("dia", MAIN_DIAS)
def test_steel_mass_agrees_with_rebar(rebar, steel_mass, dia):
    """The two tables carry the same bars; resolution 25 forbids them drifting."""
    assert steel_mass["unit_mass_kg_m"][dia] == pytest.approx(
        rebar["bars"][dia]["unit_mass_kg_m"], rel=0.003
    )


def test_steel_mass_points_at_the_canonical_table(steel_mass):
    assert steel_mass["canonical_table"] == "rebar.yaml"


# ---------------------------------------------------------------------------
# rates.yaml
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def rates():
    return load_yaml("rates")


def test_rates_default_schedule_resolves(rates):
    name = rates["default_schedule"]
    assert name in rates["schedules"]


def test_rates_placeholder_flag_is_set(rates):
    """The flag is what forces W_PLACEHOLDER_RATES onto every priced response."""
    schedule = rates["schedules"]["default_india"]
    assert schedule["placeholder"] is True
    assert schedule["currency"] == "INR"
    assert schedule["basis_year"] == 2026
    assert schedule["verify"] == "print"
    assert "PLACEHOLDER" in schedule["label"]


def test_rates_items(rates):
    items = rates["schedules"]["default_india"]["items"]
    assert items["concrete_m3"] == {"M20": 7200, "M25": 7800, "M30": 8400}
    assert items["steel_kg"] == {"Fe500": 78}
    assert items["masonry_m3"] == {"brick_230": 6800, "block_190": 5900}
    assert items["formwork_m2"] == {"column": 620, "beam": 560, "slab": 480, "footing": 380}
    assert items["excavation_m3"] == 220
    assert items["pcc_m3"] == 5600
    assert items["backfill_m3"] == 140


def test_rates_are_all_positive(rates):
    def walk(node):
        if isinstance(node, dict):
            for key in sorted(node):
                walk(node[key])
        else:
            assert isinstance(node, (int, float)) and node > 0

    walk(rates["schedules"]["default_india"]["items"])


# ---------------------------------------------------------------------------
# soil_defaults.yaml
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def soil():
    return load_yaml("soil_defaults")


def test_soil_defaults_keys_present(soil):
    defaults = soil["defaults"]
    require_keys(
        defaults,
        (
            "type",
            "sbc_kpa",
            "soft",
            "founding_depth_m",
            "gamma_knm3",
            "phi_deg",
            "c_kpa",
        ),
        "soil_defaults.defaults",
    )
    assert defaults["type"] == "II"
    assert defaults["sbc_kpa"] == 150.0
    assert defaults["soft"] is False
    assert defaults["founding_depth_m"] == 1.5
    assert defaults["gamma_knm3"] == 18.0
    assert defaults["phi_deg"] == 30.0
    assert defaults["c_kpa"] == 0.0


def test_soil_types_are_the_three_code_types(soil):
    assert sorted(soil["types"]) == ["I", "II", "III"]
    for name in sorted(soil["types"]):
        entry = soil["types"][name]
        require_keys(entry, ("label", "description", "soft", "typical_sbc_kpa"), "soil type " + name)
        assert str(entry["description"]).strip()
    assert soil["types"]["III"]["soft"] is True
    assert soil["types"]["I"]["soft"] is False


def test_soil_aliases_map_onto_the_types(soil):
    assert soil["aliases"] == {"hard": "I", "medium": "II", "soft": "III"}
    for value in sorted(soil["aliases"].values()):
        assert value in soil["types"]


def test_soil_default_type_matches_its_softness(soil):
    defaults = soil["defaults"]
    assert soil["types"][defaults["type"]]["soft"] == defaults["soft"]


# ---------------------------------------------------------------------------
# sections_is808.yaml and the loader
# ---------------------------------------------------------------------------


def test_ismb_300_spot_values():
    """The one section a reviewer will check by hand against SP 6(1)."""
    s = sec.get_section("ISMB 300")
    assert s.family == "ISMB"
    assert s.mass_kg_m == 44.2
    assert s.a_cm2 == 56.26
    assert s.ixx_cm4 == 8603.6
    assert s.zex_cm3 == 573.6
    assert s.h_mm == 300
    assert s.bf_mm == 140
    assert s.tf_mm == 12.4
    assert s.tw_mm == 7.5


def test_ismb_300_unit_conversions():
    s = sec.get_section("ISMB 300")
    assert s.a_mm2() == pytest.approx(5626.0)
    assert s.ixx_mm4() == pytest.approx(86036000.0)
    assert s.zex_mm3() == pytest.approx(573600.0)
    assert s.rx_mm() == pytest.approx(123.7)
    assert s.web_area_mm2() == pytest.approx(2250.0)


def test_expected_families_are_all_present():
    assert sec.families() == ["ISA", "ISHB", "ISLB", "ISMB", "ISMC"]
    assert len(sec.sections("ISMB")) == 14
    assert len(sec.sections()) == len(load_yaml("sections_is808")["sections"])


def test_sections_are_returned_lightest_first():
    masses = [s.mass_kg_m for s in sec.sections()]
    assert masses == sorted(masses)


def test_every_section_is_flagged_for_print_verification():
    for s in sec.sections():
        assert s.verify == "print", s.designation + " is not flagged verify: print"


@pytest.mark.parametrize("designation", sorted(load_yaml("sections_is808")["sections"]))
def test_section_internal_consistency(designation):
    s = sec.get_section(designation)
    assert s.mass_kg_m == pytest.approx(MASS_PER_CM2 * s.a_cm2, rel=0.015)
    assert s.rx_cm == pytest.approx(math.sqrt(s.ixx_cm4 / s.a_cm2), rel=0.01)
    assert s.ry_cm == pytest.approx(math.sqrt(s.iyy_cm4 / s.a_cm2), rel=0.01)
    if s.family in X_SYMMETRIC:
        assert s.zex_cm3 == pytest.approx(s.ixx_cm4 / (s.h_mm / 20.0), rel=0.01)
    if s.family in I_SECTIONS:
        assert s.zey_cm3 == pytest.approx(s.iyy_cm4 / (s.bf_mm / 20.0), rel=0.01)
    if s.zp_computed:
        assert abs(s.zpx_cm3 - 1.12 * s.zex_cm3) <= 0.051


def test_angles_carry_the_minor_principal_radius():
    """An angle strut buckles about vv, so ry alone would flatter the section."""
    for s in sec.sections("ISA"):
        assert s.rvv_cm is not None
        assert s.rvv_cm < s.ry_cm
        assert s.ixx_cm4 == s.iyy_cm4  # equal leg
        assert s.zey_cm3 == s.zex_cm3


def test_lightest_section_by_plastic_modulus():
    """ISMB 250 gives Zpx 459.8 and misses; ISMB 300 gives 642.4 and is next."""
    chosen = sec.lightest_section("ISMB", "zpx_cm3", 500.0)
    assert chosen is not None
    assert chosen.designation == "ISMB 300"
    assert sec.lightest_section("ISMB", "zpx_cm3", 459.0).designation == "ISMB 250"


def test_lightest_section_returns_none_when_exhausted():
    assert sec.lightest_section("ISMB", "zex_cm3", 1.0e9) is None


def test_lightest_section_rejects_unknown_family_and_criterion():
    with pytest.raises(ValueError) as exc:
        sec.lightest_section("ISWB", "zex_cm3", 100.0)
    assert "ISMB" in str(exc.value)
    with pytest.raises(ValueError) as exc:
        sec.lightest_section("ISMB", "iuu_cm4", 100.0)
    assert "zex_cm3" in str(exc.value)


def test_get_section_unknown_raises_with_suggestions():
    with pytest.raises(KeyError) as exc:
        sec.get_section("ISMB 3000")
    message = str(exc.value)
    assert "ISMB 3000" in message
    assert "ISMB 300" in message

    with pytest.raises(KeyError) as exc:
        sec.get_section("UB 305x165")
    assert "known families" in str(exc.value)


def test_get_section_folds_spelling():
    target = sec.get_section("ISMB 300")
    assert sec.get_section("ismb300") is target
    assert sec.get_section("  ISMB   300 ") is target


def test_table_provenance_is_reportable():
    prov = sec.table_provenance()
    assert prov["table"] == "sections_is808"
    assert "SP 6(1)" in prov["source"]
    assert prov["edition"]
    assert prov["count"] == len(sec.sections())
    assert prov["zp_estimate_factor"] == 1.12
