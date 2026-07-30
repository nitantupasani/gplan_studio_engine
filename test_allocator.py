"""Tests for the area-budget allocator (source/dimensioning/allocator.py).

T1 pins the worked example from
documentation/plans/DOOR_CONNECTIVITY_SIZING_AND_POSTPROCESS_PLAN.md 4.6;
the rest are the Phase 2 acceptance properties: the allocation sums to the
plot, never leaves the room envelopes, is monotone in plot area, and the
infeasible case reports instead of raising.

Run from the repository root:

    python test_allocator.py
"""

import os
import random
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from GPLAN.source.dimensioning.allocator import allocate

PASSED = []
FAILED = []


def check(name, condition, detail=""):
    if condition:
        PASSED.append(name)
        print("  PASS  %s" % name)
    else:
        FAILED.append((name, detail))
        print("  FAIL  %s %s" % (name, detail))


TWO_BHK = [
    {"name": "Living Room"},
    {"name": "Dining"},
    {"name": "Kitchen"},
    {"name": "Utility"},
    {"name": "Master Bedroom"},
    {"name": "Bedroom"},
    {"name": "Bathroom"},
    {"name": "Toilet"},
]

ROOM_POOL = ["Living Room", "Dining", "Kitchen", "Utility", "Master Bedroom",
             "Bedroom", "Bathroom", "Toilet", "Study", "Store", "Pooja",
             "Balcony", "Gym"]


def t1_worked_example():
    print("\nT1: the 4.6 worked example, 2BHK on 36 x 28")
    out = allocate(TWO_BHK, 36, 28)
    expected = {
        "Living Room": (123.8, 436.6, 255.7, False),
        "Dining": (97.8, 221.8, 97.8, False),
        "Kitchen": (62.2, 118.6, 118.6, True),
        "Utility": (28.2, 58.0, 28.2, False),
        "Master Bedroom": (118.6, 273.1, 245.0, False),
        "Bedroom": (118.6, 201.2, 201.2, True),
        "Bathroom": (40.0, 74.8, 40.0, False),
        "Toilet": (21.6, 38.8, 21.6, False),
    }
    check("T1 fits", out["fits"])
    check("T1 program rectangle minimum 610.5",
          abs(out["program_min_area"] - 610.5) <= 0.1,
          str(out["program_min_area"]))
    check("T1 program rectangle maximum 1422.9",
          abs(out["program_max_area"] - 1422.9) <= 0.1,
          str(out["program_max_area"]))
    check("T1 surplus 397.5", abs(out["surplus"] - 397.5) <= 0.1,
          str(out["surplus"]))
    check("T1 remainder 0.0", abs(out["remainder"]) <= 0.1,
          str(out["remainder"]))
    for room in out["rooms"]:
        lo, hi, alloc, capped = expected[room["name"]]
        ok = (abs(room["min_area"] - lo) <= 0.1
              and abs(room["max_area"] - hi) <= 0.1
              and abs(room["allocated_area"] - alloc) <= 0.1
              and room["at_cap"] == capped)
        check("T1 %s -> %.1f sqft%s" % (room["name"], alloc,
                                        " (cap)" if capped else ""),
              ok, "min %(min_area)s max %(max_area)s got %(allocated_area)s"
              " at_cap %(at_cap)s" % room)
    total = sum(r["allocated_area"] for r in out["rooms"])
    check("T1 total is the plot area", abs(total - 1008.0) <= 0.5, str(total))
    check("T1 target bbox is the plot",
          out["target_bbox"] == {"width": 36, "height": 28},
          str(out["target_bbox"]))


def t2_shapes_inside_envelopes():
    print("\nT2: targets stay inside their envelopes and bands")
    out = allocate(TWO_BHK, 36, 28)
    ok_bounds = ok_band = ok_span = True
    for room in out["rooms"]:
        w, h = room["target_width"], room["target_height"]
        # 0.25 slack for the 0.5 ft readability rounding
        if not (room["min_width"] - 0.26 <= w <= room["max_width"] + 0.26
                and room["min_height"] - 0.26 <= h <= room["max_height"] + 0.26):
            ok_bounds = False
            print("     %s target %sx%s outside [%s..%s]x[%s..%s]"
                  % (room["name"], w, h, room["min_width"], room["max_width"],
                     room["min_height"], room["max_height"]))
        aspect = max(w, h) / min(w, h)
        if aspect > room["ar_hi"] * 1.1:
            ok_band = False
            print("     %s target aspect %.2f past band %.2f"
                  % (room["name"], aspect, room["ar_hi"]))
        if min(w, h) < 2.0:
            ok_span = False
    check("T2 targets inside rectangle bounds", ok_bounds)
    check("T2 target aspect inside the band", ok_band)
    check("T2 no span below 2.0 ft", ok_span)


def t3_property_random():
    print("\nT3: property test over randomised programs and plots")
    rng = random.Random(20260730)
    violations = []
    for trial in range(300):
        rooms = [{"name": rng.choice(ROOM_POOL)}
                 for _ in range(rng.randint(2, 12))]
        plot_w = rng.uniform(12, 80)
        plot_h = rng.uniform(12, 80)
        out = allocate(rooms, plot_w, plot_h)
        plot_area = plot_w * plot_h
        total = sum(r["allocated_area"] for r in out["rooms"])
        for r in out["rooms"]:
            if r["allocated_area"] < r["min_area"] - 1e-6:
                violations.append("trial %d: %s below floor" % (trial, r["name"]))
            if r["allocated_area"] > r["max_area"] + 1e-6:
                violations.append("trial %d: %s above ceiling" % (trial, r["name"]))
        if out["fits"]:
            expected = min(plot_area, out["program_max_area"])
            if abs(total - expected) > 0.5:
                violations.append(
                    "trial %d: total %.1f != min(plot %.1f, cap %.1f)"
                    % (trial, total, plot_area, out["program_max_area"]))
        else:
            if abs(total - out["program_min_area"]) > 0.5:
                violations.append("trial %d: infeasible total %.1f != floor %.1f"
                                  % (trial, total, out["program_min_area"]))
    check("T3 300 random programs: floors, ceilings and totals all hold",
          not violations, "; ".join(violations[:5]))


def t4_infeasible():
    print("\nT4: the program does not fit")
    out = allocate(TWO_BHK, 28, 20)
    check("T4 fits is false", out["fits"] is False)
    check("T4 shortfall reported",
          abs(out["shortfall_sqft"] - (out["program_min_area"] - 560)) <= 0.1,
          str(out.get("shortfall_sqft")))
    check("T4 smallest plot present and larger than the given one",
          out["smallest_plot"]["width"] * out["smallest_plot"]["height"]
          >= out["program_min_area"] - 1.0, str(out.get("smallest_plot")))
    check("T4 drivers name the largest minimums",
          out["drivers"][0]["room"] == "Living Room", str(out.get("drivers")))
    at_floor = all(abs(r["allocated_area"] - r["min_area"]) <= 0.1
                   for r in out["rooms"])
    check("T4 every room allocated at its floor", at_floor)


def t5_monotone():
    print("\nT5: allocation is monotone in plot area")
    prev = None
    ok = True
    for width in range(20, 60, 4):
        out = allocate(TWO_BHK, width, 28)
        current = {r["name"]: r["allocated_area"] for r in out["rooms"]}
        if prev is not None:
            for name, area in current.items():
                if area < prev[name] - 1e-6:
                    ok = False
                    print("     %s shrank %.1f -> %.1f at width %d"
                          % (name, prev[name], area, width))
        prev = current
    check("T5 no room shrinks as the plot grows", ok)


def t6_tier_share():
    print("\nT6: tier_share releases surplus to tier 2")
    default = allocate(TWO_BHK, 36, 28)
    softened = allocate(TWO_BHK, 36, 28, tier_share=[0.5, 1.0, 1.0])
    d_default = next(r for r in default["rooms"] if r["name"] == "Dining")
    d_soft = next(r for r in softened["rooms"] if r["name"] == "Dining")
    check("T6 default keeps Dining at its floor",
          abs(d_default["allocated_area"] - d_default["min_area"]) <= 0.1,
          str(d_default["allocated_area"]))
    check("T6 tier_share 0.5 grows Dining above its floor",
          d_soft["allocated_area"] > d_soft["min_area"] + 1.0,
          str(d_soft["allocated_area"]))
    total = sum(r["allocated_area"] for r in softened["rooms"])
    check("T6 softened total still fills the plot",
          abs(total - 1008.0) <= 0.5, str(total))


def t7_validation():
    print("\nT7: user maximum below the NBC minimum is an error")
    try:
        allocate([{"name": "Living Room", "max_width": 8}], 36, 28)
        check("T7 raises ValueError", False, "no exception")
    except ValueError as exc:
        check("T7 raises ValueError", True)
        check("T7 message names the room and the rule",
              "Living Room" in str(exc) and "minimum" in str(exc), str(exc))
    try:
        allocate([], 36, 28)
        check("T7 empty program raises", False, "no exception")
    except ValueError:
        check("T7 empty program raises", True)


def t8_speed():
    print("\nT8: 12-room program allocates in well under 50 ms")
    rooms = [{"name": n} for n in ROOM_POOL[:12]]
    started = time.perf_counter()
    for _ in range(100):
        allocate(rooms, 48, 36)
    per_call_ms = (time.perf_counter() - started) * 10
    check("T8 under 50 ms per call", per_call_ms < 50,
          "%.2f ms" % per_call_ms)


def main():
    print("=" * 70)
    print("Area-budget allocator tests")
    print("=" * 70)
    t1_worked_example()
    t2_shapes_inside_envelopes()
    t3_property_random()
    t4_infeasible()
    t5_monotone()
    t6_tier_share()
    t7_validation()
    t8_speed()
    print("\n" + "=" * 70)
    print("%d passed, %d failed" % (len(PASSED), len(FAILED)))
    for name, detail in FAILED:
        print("  FAILED: %s %s" % (name, detail))
    return 1 if FAILED else 0


if __name__ == "__main__":
    sys.exit(main())
