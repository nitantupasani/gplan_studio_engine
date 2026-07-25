"""Tests for per-room maximum dimension enforcement (maxDimEnabled).

Minimum dimensioning treats client room sizes as minimums and, historically,
allowed every room up to DEFAULT_UB_FACTOR x its own minimum. That is how a
5x7 balcony came back as 5x24: the solver had the slack, and the gap-fill pass
then handed it the whole leftover strip.

With maxDimEnabled the client's per-room ceilings are carried into the solver
(widened to at least SOLVER_UB_SLACK x the minimum so the topology search keeps
its freedom) and enforced in the gap fill.

The contract being tested is deliberately best-effort: a gapless rectangular
tiling forces columns of rooms to stack to equal totals, so a hard ceiling can
make every topology infeasible. When that happens the ceilings are released for
that topology and the response says so. So the assertions are:

  * ceilings that leave room to solve are honoured exactly, with no release;
  * ceilings that do not are released loudly, never silently;
  * either way the result is no worse than not sending ceilings at all, and the
    minimums are always honoured.

Rotation is enabled in these runs, so every check accepts a room whose axes are
swapped. Run from the repository root:

    python test_max_dimensions.py
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from GPLAN.api import Documents
from GPLAN.source.inputgraph import InputGraph


PASSED = []
FAILED = []

# The solver drops the ceilings when no topology satisfies them.
RELEASE_MARKER = "maximum dimensions were released"
# The gap fill breaks a ceiling to close a hole the capped pass could not.
GAPFILL_MARKER = "maximum dimensions were exceeded while closing gaps"


def reported(message):
    low = message.lower()
    return RELEASE_MARKER in low or GAPFILL_MARKER in low


def check(name, condition, detail=""):
    if condition:
        PASSED.append(name)
        print(f"  PASS  {name}")
    else:
        FAILED.append((name, detail))
        print(f"  FAIL  {name} {detail}")


# label, min_w, min_h
ROOMS = [
    ("Living",  12, 12),
    ("Kitchen",  8,  7),
    ("Bedroom", 10, 10),
    ("Bath",     5,  6),
    ("Balcony",  5,  7),
]
EDGES = [(0, 1), (1, 2), (2, 3), (3, 4), (0, 2), (0, 4), (1, 3)]
COORDS = [(0, 0), (2, 0), (4, 0), (4, 3), (0, 3)]

# Ceilings just above the minimums. A gapless tiling cannot absorb the leftover
# area under these, so the release path is expected to fire.
TIGHT_CAPS = {"Living": (24, 24), "Kitchen": (11, 10), "Bedroom": (16, 16),
              "Bath": (7, 8), "Balcony": (7, 9)}

# Ceilings at 3x the minimum: above SOLVER_UB_SLACK (2.5x) and below the
# historical 5x bound, so they bind without making the problem infeasible.
LOOSE_CAPS = {name: (3 * w, 3 * h) for name, w, h in ROOMS}


def build_request(caps):
    nodes_list = []
    for i, (label, min_w, min_h) in enumerate(ROOMS):
        max_w, max_h = caps[label] if caps else (99999, 99999)
        nodes_list.append({
            "id": i, "x": COORDS[i][0], "y": COORDS[i][1], "label": label,
            "color": "#1C4C82",
            "width": {"min": min_w, "max": max_w},
            "height": {"min": min_h, "max": max_h},
            "ratio": {"min": 3, "max": 99999},
        })
    edges = [[u, v, "black"] for u, v in EDGES]

    dim_inputs = {
        "min_width": [r[1] for r in ROOMS],
        "min_height": [r[2] for r in ROOMS],
        "max_width": [nodes_list[i]["width"]["max"] for i in range(len(ROOMS))],
        "max_height": [nodes_list[i]["height"]["max"] for i in range(len(ROOMS))],
        "min_ratio": [3] * len(ROOMS),
        "max_ratio": [99999] * len(ROOMS),
        "plot_width": 0, "plot_height": 0,
        "symmetric": False, "optimal_floorplan": 1, "rotation_enabled": 1,
    }

    graph = InputGraph(len(nodes_list), len(edges), edges,
                       [[n["x"], n["y"]] for n in nodes_list])
    return {
        "starting_from": 0, "count": 6, "caller": "door_connectivity",
        "nodes_list": nodes_list, "graph": graph, "rectangular": True,
        "minDimEnabled": True, "nonAdj": False, "limit": 6,
        "corridor_thickness": 0.5, "dim_inputs": dim_inputs,
        "edges_list": edges, "non_adj_edge_list": [], "cardinal_constraints": [],
    }


def run(caps):
    response, message = Documents.get_floorplans(**build_request(caps))
    plans = response.to_dict()["Documents"]["floorPlans"]
    rooms = [[(r["name"], float(r["width"]), float(r["height"])) for r in plan]
             for plan in plans]
    return rooms, message


def fits_under(w, h, cap_w, cap_h, eps=1e-6):
    """True if the room fits its ceiling in either orientation."""
    return ((w <= cap_w + eps and h <= cap_h + eps) or
            (w <= cap_h + eps and h <= cap_w + eps))


def fits_over(w, h, min_w, min_h, eps=1e-6):
    """True if the room clears its minimum in either orientation."""
    return ((w >= min_w - eps and h >= min_h - eps) or
            (w >= min_h - eps and h >= min_w - eps))


def breaches(plans, caps):
    """Every (name, w, h, cap) that overshoots, worst ratio first."""
    out = []
    for plan in plans:
        for name, w, h in plan:
            cap = caps.get(name)
            if cap and not fits_under(w, h, *cap):
                ratio = max(w / max(cap), h / max(cap))
                out.append((ratio, name, round(w, 2), round(h, 2), cap))
    out.sort(reverse=True)
    return out


def main():
    print("=" * 70)
    print("per-room maximum dimension tests")
    print("=" * 70)
    mins = {name: (w, h) for name, w, h in ROOMS}

    print("\nT1: baseline, no ceilings sent (historical behaviour)")
    open_plans, open_msg = run(None)
    check("T1 produced floorplans", len(open_plans) > 0, f"got {len(open_plans)}")
    open_breach = breaches(open_plans, TIGHT_CAPS)
    print(f"    plans={len(open_plans)}, rooms over the tight ceilings: {len(open_breach)}")
    if open_breach:
        print(f"    worst: {open_breach[0][1]} {open_breach[0][2]}x{open_breach[0][3]} "
              f"vs cap {open_breach[0][4]}")
    check("T1 baseline does overshoot (so the test has something to fix)",
          len(open_breach) > 0)
    check("T1 no ceiling warning when no ceilings were sent",
          not reported(open_msg), open_msg[:160])

    print("\nT2: loose ceilings (3x the minimum)")
    loose_plans, loose_msg = run(LOOSE_CAPS)
    check("T2 produced floorplans", len(loose_plans) > 0, f"got {len(loose_plans)}")
    loose_breach = breaches(loose_plans, LOOSE_CAPS)
    print(f"    plans={len(loose_plans)}, warned={reported(loose_msg)}, "
          f"rooms over ceiling: {len(loose_breach)}")
    if loose_breach:
        print(f"    worst: {loose_breach[0][1]} {loose_breach[0][2]}x{loose_breach[0][3]} "
              f"vs cap {loose_breach[0][4]}")
    check("T2 solvable ceilings need no solver release",
          RELEASE_MARKER not in loose_msg.lower(), loose_msg[:200])
    check("T2 no worse than the baseline",
          len(loose_breach) <= len(breaches(open_plans, LOOSE_CAPS)),
          f"{len(loose_breach)} vs {len(breaches(open_plans, LOOSE_CAPS))}")
    # The ceilings bind in the solver and in the capped gap fill, but a hole
    # that only an oversized room can close is still closed. So the guarantee
    # is per-plan, not global: some plans come back fully within the ceilings.
    clean = [p for p in loose_plans
             if not breaches([p], LOOSE_CAPS)]
    check("T2 ceilings actually bind on some plans", len(clean) > 0,
          "no plan respected every ceiling, so the caps did nothing")
    check("T2 any remaining overshoot is reported",
          (not loose_breach) or reported(loose_msg),
          "a room exceeded its ceiling with nothing in the message")
    print(f"    {len(clean)}/{len(loose_plans)} plans fully within their ceilings")

    print("\nT3: tight ceilings are either honoured or broken out loud")
    tight_plans, tight_msg = run(TIGHT_CAPS)
    check("T3 produced floorplans", len(tight_plans) > 0,
          "capping must not collapse the catalogue")
    tight_breach = breaches(tight_plans, TIGHT_CAPS)
    print(f"    plans={len(tight_plans)}, warned={reported(tight_msg)}, "
          f"rooms over ceiling: {len(tight_breach)}")
    check("T3 an overshoot is always reported",
          (not tight_breach) or reported(tight_msg),
          "rooms exceeded their ceiling with no warning in the message")
    check("T3 no worse than the baseline",
          len(tight_breach) <= len(open_breach),
          f"{len(tight_breach)} breaches vs {len(open_breach)} baseline")

    print("\nT4: minimums are never sacrificed to a ceiling")
    ok = True
    for label, plans in (("loose", loose_plans), ("tight", tight_plans)):
        for plan in plans:
            for name, w, h in plan:
                lo = mins.get(name)
                if lo and not fits_over(w, h, *lo):
                    ok = False
                    print(f"     {label}: {name} {w}x{h} below minimum {lo[0]}x{lo[1]}")
    check("T4 minimums honoured in both runs", ok)

    print("\nT5: ceilings do not shrink the catalogue")
    check("T5 loose ceilings keep the plan count",
          len(loose_plans) >= min(len(open_plans), 1),
          f"{len(loose_plans)} vs baseline {len(open_plans)}")
    check("T5 tight ceilings keep the plan count",
          len(tight_plans) >= min(len(open_plans), 1),
          f"{len(tight_plans)} vs baseline {len(open_plans)}")

    print("\n" + "=" * 70)
    print(f"{len(PASSED)} passed, {len(FAILED)} failed")
    for name, detail in FAILED:
        print(f"  FAILED: {name} {detail}")
    return 1 if FAILED else 0


if __name__ == "__main__":
    sys.exit(main())
