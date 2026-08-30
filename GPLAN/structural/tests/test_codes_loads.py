"""Pins for the load code callables: IS 875 parts 1, 2 and 3, and IS 1893 part 1.

Every numeric expectation below is hand-checkable from the printed clause it
names; nothing is copied back out of the implementation. The registry and sink
tests hold the finding 7 contract (one decorator, one sink, plain returns) for
all 27 callables at once.
"""

from __future__ import annotations

import math

import pytest

# Relative: see the note in test_model_roundtrip.py. An absolute GPLAN.structural
# import would give the clause registry a second module identity.
from ..codes import is875, is1893
from ..codes.trace import CLAUSE_REGISTRY, trace_into
from ..data._loader import load_yaml
from ..model import Occupancy

DATA_TABLES = (
    "is875_1_unit_weights",
    "is875_2_imposed",
    "is875_3_wind",
    "is1893",
)


# ---------------------------------------------------------------------------
# data tables carry their provenance
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("name", DATA_TABLES)
def test_every_table_names_its_document_and_edition(name):
    table = load_yaml(name)
    assert isinstance(table["source"], str) and table["source"].strip()
    assert isinstance(table["edition"], str) and table["edition"].strip()
    # The document is named, not just the standard number.
    assert "IS " in table["source"]


def test_values_the_spec_did_not_vet_are_flagged_for_print_verification():
    wind = load_yaml("is875_3_wind")
    seismic = load_yaml("is1893")
    # Only the 10 m row of Table 2 is spec-vetted; the grid needs the print.
    assert wind["k2"]["verify"] == "print"
    assert wind["cpe_walls"]["verify"] == "print"
    assert wind["cpe_pitched_roof"]["verify"] == "print"
    # The spec asks for the exact Table 9 rows at authoring, so R stays flagged.
    assert seismic["response_reduction"]["verify"] == "print"
    # Composite dead load allowances are not single printed rows either.
    unit_weights = load_yaml("is875_1_unit_weights")
    assert unit_weights["area_loads"]["floor_finish"]["verify"] == "print"


def test_the_table_cache_is_read_live_not_snapshotted_at_import():
    # The loader hands back the shared cache entry, read-only by contract. This
    # pins that no callable copied a number into a module constant at import.
    before = is875.part1_unit_weight("rcc")
    load_yaml("is875_1_unit_weights")["materials"]["rcc"]["gamma_kn_m3"] = 99.0
    try:
        assert is875.part1_unit_weight("rcc") == 99.0
    finally:
        load_yaml("is875_1_unit_weights")["materials"]["rcc"]["gamma_kn_m3"] = before
    assert is875.part1_unit_weight("rcc") == 25.0


# ---------------------------------------------------------------------------
# IS 875 (Part 1): dead loads
# ---------------------------------------------------------------------------


def test_part1_unit_weights():
    # Table 1: reinforced cement concrete, the value IS 456 Cl 19.2.1 uses too.
    assert is875.part1_unit_weight("rcc") == 25.0
    assert is875.part1_unit_weight("pcc") == 24.0
    assert is875.part1_unit_weight("brick_masonry") == 20.0
    assert is875.part1_unit_weight("cement_plaster") == 20.4
    # Keys normalize, so an adapter that shouts does not break the lookup.
    assert is875.part1_unit_weight(" RCC ") == 25.0


def test_part1_area_loads():
    assert is875.part1_area_load("floor_finish") == 1.5
    assert is875.part1_area_load("roof_finish_flat") == 2.0
    assert is875.part1_area_load("sunken_fill") == 4.25
    assert is875.part1_area_load("roof_sheet_light") == 0.35
    assert is875.part1_area_load("roof_tile") == 0.85
    # The sunken fill is quoted per 250 mm of sink; the caller scales it.
    assert is875.area_load_reference_depth_m("sunken_fill") == 0.25
    assert is875.area_load_reference_depth_m("floor_finish") is None


def test_plaster_face_load_composes_from_the_table():
    # dead.py section 7.4: 20.4 kN/m3 over 12 mm per face.
    gamma = is875.part1_unit_weight("cement_plaster")
    thickness = is875.dead_load_default("plaster_thickness_m")
    assert gamma * thickness == pytest.approx(0.2448)
    assert is875.dead_load_default("parapet_height_m") == 0.9
    assert is875.dead_load_default("parapet_thickness_m") == 0.115
    assert is875.dead_load_default("partition_allowance_kpa") == 1.0
    assert is875.dead_load_default("opening_deduction") is False


def test_unknown_material_raises_and_names_the_known_keys():
    with pytest.raises(KeyError) as excinfo:
        is875.part1_unit_weight("unobtanium")
    message = str(excinfo.value)
    assert "unobtanium" in message
    assert "rcc" in message and "brick_masonry" in message


# ---------------------------------------------------------------------------
# IS 875 (Part 2): imposed loads
# ---------------------------------------------------------------------------


def test_part2_imposed_residential_rows():
    # Table 1, item 1(a), dwelling houses.
    assert is875.part2_imposed("residential_room") == 2.0
    assert is875.part2_imposed("toilet_bath") == 2.0
    assert is875.part2_imposed("corridor_stair") == 3.0
    assert is875.part2_imposed("balcony") == 3.0
    assert is875.part2_imposed("store") == 5.0
    assert is875.part2_imposed("garage_light") == 2.5
    # Table 2 roof rows resolve through the same call.
    assert is875.part2_imposed("roof_accessible") == 1.5
    assert is875.part2_imposed("roof_non_accessible") == 0.75


def test_part2_sloped_roof_live_follows_the_table_2_rule():
    # 0.75 kPa flat, less 0.02 kPa per degree above 10 deg, floor 0.4 kPa.
    assert is875.part2_sloped_roof_live(0.0) == 0.75
    assert is875.part2_sloped_roof_live(10.0) == 0.75
    assert is875.part2_sloped_roof_live(20.0) == pytest.approx(0.55)
    assert is875.part2_sloped_roof_live(25.0) == pytest.approx(0.45)
    # 0.75 - 0.02 * 20 = 0.35, under the floor, so the floor governs.
    assert is875.part2_sloped_roof_live(30.0) == pytest.approx(0.40)
    assert is875.part2_sloped_roof_live(60.0) == pytest.approx(0.40)


def test_part2_reduction_ladder():
    # Cl 3.2.1: 0, 10, 20, 30, 40 percent, then 50 above ten floors carried.
    expected = {1: 0.00, 2: 0.10, 3: 0.20, 4: 0.30, 5: 0.40, 10: 0.40, 11: 0.50, 20: 0.50}
    for floors, reduction in sorted(expected.items()):
        result = is875.part2_reduction_factor(floors)
        assert result.reduction == pytest.approx(reduction)
        assert result.factor == pytest.approx(1.0 - reduction)
        assert result.applied is True
        assert result.floors_carried == floors


def test_reduction_is_never_applied_above_five_kpa():
    # Cl 3.2.2. The five-floor reduction is 0.40 at or below the bar ...
    assert is875.part2_reduction_factor(5, q_kpa=5.0).reduction == pytest.approx(0.40)
    # ... and vanishes above it, factor 1.0 with the flag the takedown discloses.
    blocked = is875.part2_reduction_factor(5, q_kpa=5.5)
    assert blocked.reduction == 0.0
    assert blocked.factor == 1.0
    assert blocked.applied is False
    assert blocked.floors_carried == 5


def test_occupancy_enum_maps_onto_the_is875_keys():
    # Finding 22: the adapter parses room names; this is the only enum bridge.
    assert is875.is875_occupancy_key(Occupancy.HABITABLE) == ("residential_room", True)
    assert is875.is875_occupancy_key(Occupancy.KITCHEN).key == "residential_room"
    assert is875.is875_occupancy_key(Occupancy.BATH).key == "toilet_bath"
    assert is875.is875_occupancy_key(Occupancy.WC).key == "toilet_bath"
    assert is875.is875_occupancy_key(Occupancy.BALCONY).key == "balcony"
    assert is875.is875_occupancy_key(Occupancy.STAIR).key == "corridor_stair"
    assert is875.is875_occupancy_key(Occupancy.PARKING).key == "garage_light"
    assert is875.is875_occupancy_key(Occupancy.STORAGE).key == "store"
    # A str Enum keys the dict by value, so a raw wire string resolves too.
    assert is875.is875_occupancy_key("corridor").key == "corridor_stair"


def test_unmapped_occupancy_falls_back_and_says_so():
    for occupancy in (Occupancy.VOID, Occupancy.OTHER):
        mapping = is875.is875_occupancy_key(occupancy)
        assert mapping.key == is875.OCCUPANCY_FALLBACK_KEY == "residential_room"
        assert mapping.mapped is False
    # The caller raises this code; the registry owns it (findings 8 and 22).
    from ..model import REGISTRY

    assert is875.OCCUPANCY_FALLBACK_CODE in REGISTRY


def test_every_mapped_occupancy_key_exists_in_the_table():
    for key in sorted(set(is875.OCCUPANCY_TO_IS875.values())):
        assert is875.part2_imposed(key) > 0.0


# ---------------------------------------------------------------------------
# IS 875 (Part 3): wind
# ---------------------------------------------------------------------------


def test_basic_wind_speed_zones():
    speeds = [is875.part3_basic_wind_speed(str(zone)) for zone in range(1, 7)]
    assert speeds == [33.0, 39.0, 44.0, 47.0, 50.0, 55.0]
    assert is875.part3_basic_wind_speed("Mumbai") == 44.0
    with pytest.raises(KeyError):
        is875.part3_basic_wind_speed("7")


def test_k2_at_the_exact_table_points():
    # Table 2, the 10 m row, the one row the loads spec vets.
    assert is875.part3_k2(1, 10.0) == pytest.approx(1.05)
    assert is875.part3_k2(2, 10.0) == pytest.approx(1.00)
    assert is875.part3_k2(3, 10.0) == pytest.approx(0.91)
    assert is875.part3_k2(4, 10.0) == pytest.approx(0.80)
    # A second tabulated height, straight off the grid.
    assert is875.part3_k2(2, 15.0) == pytest.approx(1.05)
    assert is875.part3_k2(3, 30.0) == pytest.approx(1.06)


def test_k2_interpolates_and_clamps():
    # Midway between the 10 m and 15 m rows for category 2: (1.00 + 1.05) / 2.
    assert is875.part3_k2(2, 12.5) == pytest.approx(1.025)
    # Midway between categories 2 and 3 at 10 m: (1.00 + 0.91) / 2.
    assert is875.part3_k2(2.5, 10.0) == pytest.approx(0.955)
    # Below the table the 10 m row stands, which is the whole low-rise range.
    assert is875.part3_k2(2, 6.0) == pytest.approx(1.00)
    assert is875.part3_k2_range(6.0) == "below_table"
    assert is875.part3_k2_range(30.0) == "in_table"
    assert is875.part3_k2_range(900.0) == "above_table"


def test_design_wind_speed_and_pressure():
    # Cl 6.2 with every factor at unity leaves the basic speed alone ...
    Vb = is875.part3_basic_wind_speed("3")
    Vz = is875.part3_design_wind_speed(Vb, 1.0, 1.0, 1.0, 1.0)
    assert Vz == pytest.approx(44.0)
    # ... and Cl 6.3: 0.6 * 44^2 = 1161.6 N/m2 = 1.1616 kPa.
    assert is875.part3_wind_pressure(Vz) == pytest.approx(1.1616)
    # A worked height: terrain 2 at 12.5 m, k1 = k3 = k4 = 1.
    Vz_12 = is875.part3_design_wind_speed(44.0, 1.0, is875.part3_k2(2, 12.5), 1.0, 1.0)
    assert Vz_12 == pytest.approx(45.1)
    assert is875.part3_wind_pressure(Vz_12) == pytest.approx(0.6 * 45.1 * 45.1 / 1000.0)


def test_design_pressure_defaults_every_modifier_off():
    pz = is875.part3_wind_pressure(44.0)
    assert is875.part3_design_pressure(pz) == pytest.approx(pz)
    # Kd 0.9 and Kc 0.9 are stored but only applied when asked for.
    assert is875.part3_stored_factor("kd") == 0.9
    assert is875.part3_stored_factor("kc") == 0.9
    assert is875.part3_design_pressure(pz, 0.9, 1.0, 0.9) == pytest.approx(pz * 0.81)


def test_area_averaging_factor():
    # Table 4: 1.0 at 10 m2, 0.9 at 25 m2, 0.8 at 100 m2, linear between.
    assert is875.part3_ka(10.0) == pytest.approx(1.0)
    assert is875.part3_ka(25.0) == pytest.approx(0.9)
    assert is875.part3_ka(100.0) == pytest.approx(0.8)
    assert is875.part3_ka(4.0) == pytest.approx(1.0)
    assert is875.part3_ka(500.0) == pytest.approx(0.8)
    # Midway between 10 and 25 m2: (1.0 + 0.9) / 2.
    assert is875.part3_ka(17.5) == pytest.approx(0.95)


def test_cpe_walls_bands_and_the_frame_net():
    # Table 5, h/w <= 1/2 and l/w <= 3/2: windward +0.7, leeward -0.2.
    low = is875.part3_cpe_walls(0.4, 1.2)
    assert low.windward == pytest.approx(0.7)
    assert low.leeward == pytest.approx(-0.2)
    assert low.side == pytest.approx(-0.5)
    assert low.net == pytest.approx(0.9)
    assert low.out_of_table is False
    # A taller, longer box moves band: 1/2 < h/w <= 3/2 and 3/2 < l/w < 4.
    tall = is875.part3_cpe_walls(1.0, 2.0)
    assert tall.leeward == pytest.approx(-0.3)
    assert tall.net == pytest.approx(1.0)
    # Past the printed bands the widest row stands, flagged for the caller.
    assert is875.part3_cpe_walls(8.0, 5.0).out_of_table is True


def test_cpe_pitched_roof_interpolates_on_the_roof_angle():
    # Table 6, h/w <= 1/2: windward -1.2 at 10 deg and -0.4 at 20 deg, so the
    # midpoint is -0.8.
    assert is875.part3_cpe_pitched_roof(10.0, 0.4).windward == pytest.approx(-1.2)
    assert is875.part3_cpe_pitched_roof(20.0, 0.4).windward == pytest.approx(-0.4)
    assert is875.part3_cpe_pitched_roof(15.0, 0.4).windward == pytest.approx(-0.8)
    # The gable default of the housing path, tan theta = 0.6, is about 31 deg.
    gable = is875.part3_cpe_pitched_roof(math.degrees(math.atan(0.6)), 0.4)
    assert gable.leeward == pytest.approx(-0.4, abs=0.05)
    assert gable.out_of_table is False
    assert is875.part3_cpe_pitched_roof(75.0, 0.4).out_of_table is True


def test_internal_pressure_coefficients_act_both_ways():
    normal = is875.part3_cpi("normal")
    assert (normal.magnitude, normal.plus, normal.minus) == (0.2, 0.2, -0.2)
    assert is875.part3_cpi("low").magnitude == 0.2
    assert is875.part3_cpi("medium").magnitude == 0.5
    assert is875.part3_cpi("large").magnitude == 0.7
    assert is875.part3_cpi().magnitude == 0.2
    with pytest.raises(KeyError):
        is875.part3_cpi("sieve")


def test_static_method_limits_are_data_not_code():
    limits = is875.part3_static_limits()
    assert limits["max_height_m"] == 20.0
    assert limits["max_height_over_least_width"] == 5.0


# ---------------------------------------------------------------------------
# IS 1893 (Part 1)
# ---------------------------------------------------------------------------


def test_zone_importance_and_response_reduction():
    assert is1893.zone_factor("II") == pytest.approx(0.10)
    assert is1893.zone_factor("III") == pytest.approx(0.16)
    assert is1893.zone_factor("IV") == pytest.approx(0.24)
    assert is1893.zone_factor("V") == pytest.approx(0.36)
    # Zones arrive from JSON as "iv" or 4 as often as "IV".
    assert is1893.zone_factor("iv") == is1893.zone_factor(4) == pytest.approx(0.24)
    assert is1893.importance_factor("residential") == 1.0
    assert is1893.importance_factor("important") == 1.2
    assert is1893.response_reduction("omrf") == 3.0
    assert is1893.response_reduction("smrf") == 5.0
    assert is1893.response_reduction("urm") == 1.5


def test_response_reduction_defaults_nothing():
    # Finding 41: the resolved system default lives in structural/api.py, and an
    # unknown system is an error here, never a quiet OMRF.
    with pytest.raises(KeyError) as excinfo:
        is1893.response_reduction("whatever_frame")
    assert "omrf" in str(excinfo.value)
    with pytest.raises(TypeError):
        is1893.response_reduction()  # no default argument either


def test_sa_over_g_soil_two():
    # Cl 6.4.2, medium soil. Rising branch: 1 + 15 * 0.05 = 1.75.
    assert is1893.sa_over_g(0.05, "II").sa_g == pytest.approx(1.75)
    assert is1893.sa_over_g(0.05, "II").branch == "rising"
    # Plateau to the 0.55 s corner period.
    assert is1893.sa_over_g(0.3, "II").sa_g == pytest.approx(2.5)
    assert is1893.sa_over_g(0.3, "II").branch == "plateau"
    assert is1893.sa_over_g(0.55, "II").sa_g == pytest.approx(2.5)
    # Decay branch: 1.36 / T, so 1.36 at one second.
    assert is1893.sa_over_g(1.0, "II").sa_g == pytest.approx(1.36)
    assert is1893.sa_over_g(1.0, "II").branch == "decay"
    # The branches meet at 0.10 s: 1 + 15 * 0.1 = 2.5 = the plateau.
    assert is1893.sa_over_g(0.1, "II").sa_g == pytest.approx(2.5)


def test_sa_over_g_soils_one_and_three():
    assert is1893.sa_over_g(0.40, "I").sa_g == pytest.approx(2.5)
    assert is1893.sa_over_g(1.0, "I").sa_g == pytest.approx(1.00)
    assert is1893.sa_over_g(2.0, "I").sa_g == pytest.approx(0.50)
    assert is1893.sa_over_g(0.67, "III").sa_g == pytest.approx(2.5)
    assert is1893.sa_over_g(1.0, "III").sa_g == pytest.approx(1.67)
    with pytest.raises(KeyError):
        is1893.sa_over_g(0.5, "IV")


def test_long_periods_clamp_with_a_flag_and_no_print(capsys):
    # The spectrum is printed to 4 s; past it the 4 s value stands, flagged.
    clamped = is1893.sa_over_g(6.0, "II")
    assert clamped.sa_g == pytest.approx(1.36 / 4.0)
    assert clamped.clamped is True
    assert is1893.sa_over_g(4.0, "II").clamped is False
    assert capsys.readouterr().out == ""


def test_approximate_periods():
    # Cl 7.6.2(c): 0.09 * 10 / sqrt(12).
    assert is1893.period_infilled(10.0, 12.0) == pytest.approx(0.09 * 10.0 / math.sqrt(12.0))
    assert is1893.period_infilled(10.0, 12.0) == pytest.approx(0.2598, abs=1e-4)
    # Cl 7.6.2(a): 0.075 * 10^0.75.
    assert is1893.period_bare_rc(10.0) == pytest.approx(0.075 * 10.0 ** 0.75)
    assert is1893.period_bare_rc(10.0) == pytest.approx(0.4218, abs=1e-4)
    with pytest.raises(ValueError):
        is1893.period_infilled(10.0, 0.0)


def test_design_horizontal_coefficient():
    # Zone III, I = 1.0, R = 5, Sa/g = 2.5: (0.16 / 2) * 2.5 / 5 = 0.04.
    Ah = is1893.design_horizontal_coeff(
        is1893.zone_factor("III"),
        is1893.importance_factor("residential"),
        is1893.response_reduction("smrf"),
        is1893.sa_over_g(0.3, "II").sa_g,
    )
    assert Ah == pytest.approx(0.04)
    # An OMRF in the same zone is 5/3 heavier.
    assert is1893.design_horizontal_coeff(0.16, 1.0, 3.0, 2.5) == pytest.approx(0.04 * 5.0 / 3.0)
    assert is1893.base_shear(0.04, 5000.0) == pytest.approx(200.0)


def test_minimum_base_shear_coefficients():
    # Cl 7.2.2, as fractions, never percentages.
    assert is1893.min_base_shear_coeff("II") == pytest.approx(0.007)
    assert is1893.min_base_shear_coeff("III") == pytest.approx(0.011)
    assert is1893.min_base_shear_coeff("IV") == pytest.approx(0.016)
    assert is1893.min_base_shear_coeff("V") == pytest.approx(0.024)


def test_seismic_live_load_fraction():
    # Table 10: a quarter up to 3 kPa, a half above it.
    assert is1893.seismic_ll_fraction(2.0) == pytest.approx(0.25)
    assert is1893.seismic_ll_fraction(3.0) == pytest.approx(0.25)
    assert is1893.seismic_ll_fraction(3.01) == pytest.approx(0.50)
    assert is1893.seismic_ll_fraction(5.0) == pytest.approx(0.50)


def test_vertical_distribution_on_the_classic_four_storey_case():
    # Four equal storey weights at 3, 6, 9 and 12 m above the base.
    # Wi hi^2 goes 900, 3600, 8100, 14400 for W = 100 kN, summing to 27000,
    # so the shares are 1, 4, 9 and 16 parts of 30. With VB = 300 kN that is
    # 10, 40, 90 and 160 kN.
    pairs = [(100.0, 3.0), (100.0, 6.0), (100.0, 9.0), (100.0, 12.0)]
    Qi = is1893.vertical_distribution(pairs, 300.0)
    assert Qi == pytest.approx([10.0, 40.0, 90.0, 160.0])
    assert sum(Qi) == pytest.approx(300.0)
    # Index-free (finding 2): the order of the pairs is the order of the answer.
    reversed_Qi = is1893.vertical_distribution(list(reversed(pairs)), 300.0)
    assert reversed_Qi == pytest.approx([160.0, 90.0, 40.0, 10.0])
    # Unequal weights still land proportional to Wi hi^2.
    assert is1893.vertical_distribution([(200.0, 3.0), (100.0, 6.0)], 60.0) == pytest.approx([20.0, 40.0])


def test_vertical_distribution_refuses_a_degenerate_ledger():
    with pytest.raises(ValueError):
        is1893.vertical_distribution([(100.0, 0.0)], 300.0)
    with pytest.raises(ValueError):
        is1893.vertical_distribution([(100.0, 3.0, 7.0)], 300.0)


def test_design_eccentricity_returns_both_branches():
    # Cl 7.8.2 with esi = 0.5 m and bi = 10 m: 1.5 * 0.5 + 0.5 and 0.5 - 0.5.
    ecc = is1893.design_eccentricity(0.5, 10.0)
    assert ecc.amplified == pytest.approx(1.25)
    assert ecc.reduced == pytest.approx(0.0)
    # A centred diaphragm still carries the accidental five percent, both ways.
    centred = is1893.design_eccentricity(0.0, 12.0)
    assert centred.amplified == pytest.approx(0.6)
    assert centred.reduced == pytest.approx(-0.6)


def test_storey_drift_limit():
    assert is1893.drift_limit_ratio() == pytest.approx(0.004)
    assert is1893.storey_drift_limit(3.0) == pytest.approx(0.012)
    assert is1893.storey_drift_limit(3.2) == pytest.approx(0.0128)


# ---------------------------------------------------------------------------
# the finding 7 contract: one decorator, one sink, plain returns
# ---------------------------------------------------------------------------

# One sample call per decorated callable. A new clause with no sample fails
# test_every_decorated_callable_has_a_sample, so this table cannot go stale.
CLAUSE_SAMPLES = {
    ("is875", "part1_unit_weight"): (("rcc",), {}),
    ("is875", "part1_area_load"): (("floor_finish",), {}),
    ("is875", "part2_imposed"): (("residential_room",), {}),
    ("is875", "part2_sloped_roof_live"): ((20.0,), {}),
    ("is875", "part2_reduction_factor"): ((3,), {}),
    ("is875", "part3_basic_wind_speed"): (("3",), {}),
    ("is875", "part3_k2"): ((2, 10.0), {}),
    ("is875", "part3_design_wind_speed"): ((44.0, 1.0, 1.0, 1.0, 1.0), {}),
    ("is875", "part3_wind_pressure"): ((44.0,), {}),
    ("is875", "part3_design_pressure"): ((1.1616,), {}),
    ("is875", "part3_ka"): ((25.0,), {}),
    ("is875", "part3_cpe_walls"): ((0.4, 1.2), {}),
    ("is875", "part3_cpe_pitched_roof"): ((30.0, 0.4), {}),
    ("is875", "part3_cpi"): (("normal",), {}),
    ("is1893", "zone_factor"): (("III",), {}),
    ("is1893", "importance_factor"): (("residential",), {}),
    ("is1893", "response_reduction"): (("omrf",), {}),
    ("is1893", "sa_over_g"): ((0.3, "II"), {}),
    ("is1893", "period_infilled"): ((10.0, 12.0), {}),
    ("is1893", "period_bare_rc"): ((10.0,), {}),
    ("is1893", "design_horizontal_coeff"): ((0.16, 1.0, 5.0, 2.5), {}),
    ("is1893", "min_base_shear_coeff"): (("IV",), {}),
    ("is1893", "base_shear"): ((0.04, 5000.0), {}),
    ("is1893", "seismic_ll_fraction"): ((2.0,), {}),
    ("is1893", "vertical_distribution"): (([(100.0, 3.0), (100.0, 6.0)], 100.0), {}),
    ("is1893", "design_eccentricity"): ((0.5, 10.0), {}),
    ("is1893", "storey_drift_limit"): ((3.0,), {}),
}

MODULES = {"is875": is875, "is1893": is1893}


def _decorated(module):
    """Every `@clause` callable a module exports, sorted by name."""
    found = []
    for name in sorted(dir(module)):
        attribute = getattr(module, name)
        if callable(attribute) and hasattr(attribute, "clause_meta"):
            found.append((name, attribute))
    return found


def test_every_decorated_callable_has_a_sample():
    declared = {(module_name, name) for module_name, module in sorted(MODULES.items()) for name, _ in _decorated(module)}
    assert declared == set(CLAUSE_SAMPLES)
    assert len(declared) == 27


@pytest.mark.parametrize("key", sorted(CLAUSE_SAMPLES))
def test_callable_is_registered_and_traces_into_a_sink(key):
    module_name, name = key
    function = getattr(MODULES[module_name], name)
    meta = function.clause_meta
    # Registered under its clause id, and the registry holds this very meta.
    assert CLAUSE_REGISTRY[meta.clause_id] is meta
    assert meta.func == name
    assert meta.code.startswith("IS ")
    assert meta.ref and meta.title

    args, kwargs = CLAUSE_SAMPLES[key]
    entries = []
    with trace_into(entries):
        value = function(*args, **kwargs)
    assert len(entries) == 1
    entry = entries[0]
    assert entry.code == meta.code
    assert entry.ref == meta.ref
    assert entry.units == meta.units
    # Plain returns (finding 7): a float, or a NamedTuple flattened to a dict,
    # or the list of storey forces. Never a wrapper object.
    assert isinstance(value, (float, int, tuple, list))
    if isinstance(entry.output, dict):
        assert entry.output  # a NamedTuple return, stored as its fields
    # And nothing is recorded when no sink is open.
    function(*args, **kwargs)
    assert len(entries) == 1


def test_clause_ids_are_unique_across_the_two_load_codes():
    ids = []
    for _, module in sorted(MODULES.items()):
        ids.extend(function.clause_meta.clause_id for _, function in _decorated(module))
    assert len(ids) == len(set(ids))


def test_a_seismic_walkthrough_traces_in_call_order():
    entries = []
    with trace_into(entries):
        Z = is1893.zone_factor("III")
        I = is1893.importance_factor("residential")
        R = is1893.response_reduction("omrf")
        Ta = is1893.period_infilled(9.0, 12.0)
        SaG = is1893.sa_over_g(Ta, "II").sa_g
        Ah = is1893.design_horizontal_coeff(Z, I, R, SaG)
        VB = is1893.base_shear(Ah, 4000.0)
        is1893.vertical_distribution([(1400.0, 3.0), (1400.0, 6.0), (1200.0, 9.0)], VB)
    assert [entry.ref for entry in entries] == [
        "Table 3",
        "Table 8",
        "Table 9",
        "7.6.2(c)",
        "6.4.2(b)",
        "6.4.2",
        "7.6.1",
        "7.6.3",
    ]
    # Ta = 0.09 * 9 / sqrt(12) = 0.2338 s, inside the plateau, so Sa/g is 2.5
    # and Ah = (0.16 / 2) * 2.5 / 3 = 0.06667, giving VB = 266.67 kN on 4000 kN.
    assert Ta == pytest.approx(0.2338, abs=1e-4)
    assert SaG == pytest.approx(2.5)
    assert Ah == pytest.approx(0.16 / 2.0 * 2.5 / 3.0)
    assert VB == pytest.approx(266.667, abs=0.01)
    # Wi hi^2 = 12600, 50400, 97200 of 160200, which reduces to 7 : 28 : 54 of 89.
    assert entries[-1].output == pytest.approx([VB * 7 / 89.0, VB * 28 / 89.0, VB * 54 / 89.0])
    assert sum(entries[-1].output) == pytest.approx(VB)


def test_results_are_deterministic():
    first = [
        is875.part3_k2(2, 12.5),
        is875.part3_cpe_walls(0.4, 1.2),
        is875.part2_reduction_factor(5),
        is1893.sa_over_g(0.3, "II"),
        is1893.vertical_distribution([(100.0, 3.0), (100.0, 6.0)], 100.0),
    ]
    second = [
        is875.part3_k2(2, 12.5),
        is875.part3_cpe_walls(0.4, 1.2),
        is875.part2_reduction_factor(5),
        is1893.sa_over_g(0.3, "II"),
        is1893.vertical_distribution([(100.0, 3.0), (100.0, 6.0)], 100.0),
    ]
    assert first == second
