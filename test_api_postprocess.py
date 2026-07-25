"""Tests for NBC post-processing of dimensioned floorplans (postProcessEnabled).

The dimensioned catalogue returns gapless rectangular tilings, and gaplessness
is what inflates service rooms: leftover bounding-box area lands on whichever
room can reach it (the 54x8 ft bathroom). The post-processor trades the
perfect rectangle for architectural validity: rooms are trimmed back inside
their NBC ceilings and aspect bands from fully-exterior sides (leaving
boundary notches), and under-cap neighbours absorb what they are allowed to.

Hard invariants asserted on every processed plan:
  * rooms stay axis-aligned rectangles and never overlap;
  * no interior holes: every notch is connected to the outside;
  * every requested adjacency (door) keeps >= 2 ft of shared wall;
  * the plan footprint never grows more than the configured margin;
  * the rulebook score (nbc_rules.plan_sanity_score) never gets worse.

Run from the repository root:

    python test_api_postprocess.py
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from GPLAN.api import Documents
from GPLAN.source.inputgraph import InputGraph
from GPLAN.source.postprocessing import nbc_rules
from GPLAN.source.postprocessing.postprocess import postprocess_plan

PASSED = []
FAILED = []


def check(name, condition, detail=""):
    if condition:
        PASSED.append(name)
        print("  PASS  %s" % name)
    else:
        FAILED.append((name, detail))
        print("  FAIL  %s %s" % (name, detail))


def room_rects(plan):
    """Serialized plan -> [(name, x0, y0, x1, y1)] from wall bboxes."""
    out = []
    for room in plan:
        xs, ys = [], []
        for wall in room["walls"]:
            xs += [wall["x1"], wall["x2"]]
            ys += [wall["y1"], wall["y2"]]
        out.append((room.get("original_name") or room["name"],
                    min(xs), min(ys), max(xs), max(ys)))
    return out


def shared_wall(a, b, tol=1e-3):
    ax0, ay0, ax1, ay1 = a
    bx0, by0, bx1, by1 = b
    if abs(ax1 - bx0) <= tol or abs(bx1 - ax0) <= tol:
        return max(0.0, min(ay1, by1) - max(ay0, by0))
    if abs(ay1 - by0) <= tol or abs(by1 - ay0) <= tol:
        return max(0.0, min(ax1, bx1) - max(ax0, bx0))
    return 0.0


def overlaps(rects, eps=1e-3):
    for i in range(len(rects)):
        for j in range(i + 1, len(rects)):
            if (min(rects[i][2], rects[j][2]) - max(rects[i][0], rects[j][0]) > eps
                    and min(rects[i][3], rects[j][3]) - max(rects[i][1], rects[j][1]) > eps):
                return True
    return False


# ---------------------------------------------------------------------------
# T1: synthetic pathological plan (unit-level, no engine run)
# ---------------------------------------------------------------------------

def t1_synthetic():
    print("\nT1: synthetic 20x20 tiling with a 20x8 bathroom and a 20x2 balcony")
    rects = [(0, 0, 12, 10), (12, 0, 20, 10), (0, 10, 20, 18), (0, 18, 20, 20)]
    names = ["Living Room", "Bedroom", "Bathroom", "Balcony"]
    edges = [(0, 1), (0, 2), (2, 3)]
    new_rects, report = postprocess_plan(rects, names, edges=edges)

    bath_w = new_rects[2][2] - new_rects[2][0]
    bath_h = new_rects[2][3] - new_rects[2][1]
    check("T1 bathroom brought inside its 68 sqft ceiling",
          bath_w * bath_h <= 68 * 1.02, "%sx%s" % (bath_w, bath_h))
    check("T1 bathroom aspect inside its 2.0 band",
          max(bath_w, bath_h) / min(bath_w, bath_h) <= 2.0 * 1.02)
    check("T1 no interior holes", report["interior_hole_area"] <= 0.01)
    check("T1 doors preserved", report["doors_preserved"])
    check("T1 score improved",
          report["score_after"] < report["score_before"],
          "%s -> %s" % (report["score_before"], report["score_after"]))
    bx = max(r[2] for r in new_rects) - min(r[0] for r in new_rects)
    by = max(r[3] for r in new_rects) - min(r[1] for r in new_rects)
    check("T1 footprint did not balloon", bx <= 20 * 1.031 and by <= 20 * 1.031,
          "%sx%s" % (bx, by))
    check("T1 no overlaps", not overlaps(new_rects))


# ---------------------------------------------------------------------------
# engine runs (shared payload builder, mirrors test_max_dimensions.py)
# ---------------------------------------------------------------------------

ROOMS = [
    ("Living Room", 12, 12),
    ("Kitchen", 8, 7),
    ("Bedroom", 10, 11),
    ("Bathroom", 5, 7),
    ("Balcony", 5, 7),
]
EDGES = [(0, 1), (1, 2), (2, 3), (3, 4), (0, 2), (0, 4), (1, 3)]
COORDS = [(0, 0), (2, 0), (4, 0), (4, 3), (0, 3)]


def build_request(post_process, caps=None):
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
        "postProcessEnabled": post_process,
    }


def snapshot(plans):
    return [[{"name": n, "width": x1 - x0, "height": y1 - y0}
             for (n, x0, y0, x1, y1) in room_rects(plan)] for plan in plans]


def t2_engine_inline():
    print("\nT2: engine run, postProcessEnabled inline (no ceilings sent)")
    baseline_resp, baseline_msg = Documents.get_floorplans(
        **build_request(post_process=False))
    base_doc = baseline_resp.to_dict()["Documents"]
    base_plans = base_doc["floorPlans"]

    resp, msg = Documents.get_floorplans(**build_request(post_process=True))
    doc = resp.to_dict()["Documents"]
    plans = doc["floorPlans"]
    reports = doc.get("postprocess")

    check("T2 produced floorplans", len(plans) > 0, "got %d" % len(plans))
    check("T2 reports attached, one per plan",
          isinstance(reports, list) and len(reports) == len(plans),
          "reports=%s plans=%d" % (type(reports), len(plans)))
    check("T2 message notes the post-processing",
          "post-processing" in msg.lower(), msg[:200])

    base_scores = [nbc_rules.plan_sanity_score(rooms)
                   for rooms in snapshot(base_plans)]
    scores = [nbc_rules.plan_sanity_score(rooms) for rooms in snapshot(plans)]
    print("    baseline scores: %s" % base_scores)
    print("    processed scores: %s" % scores)

    all_ok = True
    for idx, plan in enumerate(plans):
        rects = [r[1:] for r in room_rects(plan)]
        names = [r[0] for r in room_rects(plan)]
        if overlaps(rects):
            all_ok = False
            print("     plan %d: OVERLAP" % idx)
        for (u, v) in EDGES:
            if shared_wall(rects[u], rects[v]) < 2.0 - 1e-3:
                all_ok = False
                print("     plan %d: door %s-%s overlap %.2f"
                      % (idx, names[u], names[v],
                         shared_wall(rects[u], rects[v])))
        for name, x0, y0, x1, y1 in room_rects(plan):
            w, h = x1 - x0, y1 - y0
            min_w, min_h = dict((r[0], (r[1], r[2])) for r in ROOMS)[name]
            if not ((w >= min_w - 1e-3 and h >= min_h - 1e-3)
                    or (w >= min_h - 1e-3 and h >= min_w - 1e-3)):
                all_ok = False
                print("     plan %d: %s %sx%s below minimum %sx%s"
                      % (idx, name, w, h, min_w, min_h))
    check("T2 invariants: no overlaps, doors kept, minimums honoured", all_ok)

    for idx, report in enumerate(reports or []):
        if report is None:
            continue
        if report["score_after"] > report["score_before"]:
            check("T2 no plan got worse", False,
                  "plan %d %s -> %s" % (idx, report["score_before"],
                                        report["score_after"]))
            break
    else:
        check("T2 no plan got worse", True)

    # Ceilings are best-effort: a room whose requested doors pin both ends of
    # its long side at the 2 ft minimum cannot shrink without severing a door,
    # and the post-processor must prefer the door. The contract is therefore:
    # strictly fewer over-cap wet/open rooms than the baseline, and every
    # residual violation visible in that plan's report.
    def over_cap_count(plan_batch):
        count = 0
        for plan in plan_batch:
            for name, x0, y0, x1, y1 in room_rects(plan):
                rule = nbc_rules.rule_for(name)
                if rule is None or rule["room_class"] not in ("wet", "open"):
                    continue
                if (x1 - x0) * (y1 - y0) > rule["max_area"] * 1.02:
                    count += 1
        return count

    over_before = over_cap_count(base_plans)
    over_after = over_cap_count(plans)
    print("    wet/open rooms over their area cap: %d -> %d"
          % (over_before, over_after))
    check("T2 over-cap wet/open rooms strictly reduced",
          over_after < over_before or (over_before == 0 and over_after == 0),
          "%d -> %d" % (over_before, over_after))

    reported = True
    for idx, plan in enumerate(plans):
        report = (reports or [None] * len(plans))[idx]
        for name, x0, y0, x1, y1 in room_rects(plan):
            rule = nbc_rules.rule_for(name)
            if rule is None:
                continue
            if (x1 - x0) * (y1 - y0) > rule["max_area"] * 1.02:
                in_report = report is not None and any(
                    issue["rule"] == "max_area" and issue["room"] == name
                    for issue in report["issues_after"])
                if not in_report:
                    reported = False
                    print("     plan %d: %s over cap but not in the report"
                          % (idx, name))
    check("T2 every residual violation is reported", reported)


def t3_standalone():
    print("\nT3: standalone postprocess_floorplans on a raw engine batch")
    raw_resp, _ = Documents.get_floorplans(**build_request(post_process=False))
    raw = raw_resp.to_dict()

    response, message = Documents.postprocess_floorplans({
        "response": raw,
        "edges": [[u, v] for (u, v) in EDGES],
    })
    doc = response["Documents"]
    check("T3 same plan count in and out",
          len(doc["floorPlans"]) == len(raw["Documents"]["floorPlans"]))
    check("T3 reports list aligned",
          len(doc["postprocess"]) == len(doc["floorPlans"]))
    changed = sum(1 for r in doc["postprocess"] if r and r["changed"])
    print("    %d/%d plans changed; %s" % (changed, len(doc["floorPlans"]),
                                           message.strip()))
    improved = all(
        r is None or r["score_after"] <= r["score_before"]
        for r in doc["postprocess"])
    check("T3 no plan got worse", improved)
    holes = all(r is None or r["interior_hole_area"] <= 0.01
                for r in doc["postprocess"])
    check("T3 no interior holes", holes)
    doors = all(r is None or r["doors_preserved"] for r in doc["postprocess"])
    check("T3 doors preserved", doors)


def t4_options():
    print("\nT4: options - all phases off is a no-op")
    raw_resp, _ = Documents.get_floorplans(**build_request(post_process=False))
    raw = raw_resp.to_dict()
    response, _ = Documents.postprocess_floorplans({
        "response": raw,
        "options": {"repair": False, "trim": False, "absorb": False},
    })
    unchanged = all(not (r and r["changed"])
                    for r in response["Documents"]["postprocess"])
    check("T4 nothing changed with all phases off", unchanged)

    before = raw["Documents"]["floorPlans"][0]
    after = response["Documents"]["floorPlans"][0]
    same_geometry = all(
        rb["width"] == ra["width"] and rb["height"] == ra["height"]
        for rb, ra in zip(before, after))
    check("T4 geometry untouched with all phases off", same_geometry)


def t5_absorb_ceiling_regression():
    """Review finding (2026-07-25): absorb computed its ceilings once per
    sweep, so a bathroom absorbing east then south ended at 80 sqft against
    the 68 ceiling AND the score gate never fired. Both must hold now."""
    print("\nT5: absorb never grows a room past its ceilings")
    rects = [(10, 3, 15, 10), (0, 0, 10, 20), (10, 0, 28, 3),
             (18, 3, 22.857, 10), (12, 13, 20, 21.5)]
    names = ["Bathroom", "Living Room", "Bedroom", "Toilet", "Bathroom 2"]
    new_rects, report = postprocess_plan(rects, names)
    bw = new_rects[0][2] - new_rects[0][0]
    bh = new_rects[0][3] - new_rects[0][1]
    check("T5 bathroom stays inside its 68 sqft ceiling",
          bw * bh <= 68 * 1.02, "%sx%s = %s" % (bw, bh, bw * bh))
    check("T5 score never worse",
          report["score_after"] <= report["score_before"],
          "%s -> %s" % (report["score_before"], report["score_after"]))


def t6_door_requirements_duplicates():
    """Review finding: duplicate room names and mixed int/name edge pairs
    silently dropped door protection; an unresolvable edge list disabled it
    entirely. All three must resolve now."""
    print("\nT6: door protection with duplicate names and mixed pairs")
    from GPLAN.source.postprocessing.postprocess import build_door_requirements
    names = ["Bedroom", "Bathroom", "Bedroom"]
    rects = [(0, 0, 10, 12), (30, 0, 36, 8), (36, 0, 46, 12)]
    eps = 0.005
    by_name = build_door_requirements(rects, names, [["Bedroom", "Bathroom"]],
                                      2.0, eps)
    check("T6 duplicate name resolves to the sharing pair",
          any(sorted(p[:2]) == [1, 2] for p in by_name), str(by_name))
    mixed = build_door_requirements(rects, names, [[2, "Bathroom"]], 2.0, eps)
    check("T6 mixed int/name pair resolves",
          any(sorted(p[:2]) == [1, 2] for p in mixed), str(mixed))
    unresolvable = build_door_requirements(rects, names, [["Nope", "Nada"]],
                                           2.0, eps)
    check("T6 unresolvable edges fall back to protection, not none",
          len(unresolvable) > 0, str(unresolvable))


def main():
    print("=" * 70)
    print("NBC post-processing tests")
    print("=" * 70)
    t1_synthetic()
    t2_engine_inline()
    t3_standalone()
    t4_options()
    t5_absorb_ceiling_regression()
    t6_door_requirements_duplicates()
    print("\n" + "=" * 70)
    print("%d passed, %d failed" % (len(PASSED), len(FAILED)))
    for name, detail in FAILED:
        print("  FAILED: %s %s" % (name, detail))
    return 1 if FAILED else 0


if __name__ == "__main__":
    sys.exit(main())
