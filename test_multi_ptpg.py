"""Tests for the multi-PTPG dimensioned floorplan pipeline.

Run from the repository root (the directory containing this file):

    python test_multi_ptpg.py

No Django, no Redis, no Celery: this exercises the engine entry point that the
backend's ``generate/multi-ptpg`` endpoint wraps.
"""

import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from GPLAN.api import Documents


PASSED = []
FAILED = []


def check(name, condition, detail=""):
    if condition:
        PASSED.append(name)
        print(f"  PASS  {name}")
    else:
        FAILED.append((name, detail))
        print(f"  FAIL  {name} {detail}")


def node(i, x, y, w, h, label=None):
    return {"id": i, "x": x, "y": y, "width": w, "height": h,
            "label": label or f"R{i}", "color": "#1C4C82"}


def edge(a, b):
    return {"source": a, "target": b, "color": "black"}


# A 5-room graph whose exact sizes admit a true rectangular dual: four rooms
# pinwheeled around a central one.
FIVE_ROOM_NODES = [node(0, 0, 0, 3, 2), node(1, 2, 0, 2, 3), node(2, 4, 0, 2, 2),
                   node(3, 4, 3, 3, 2), node(4, 0, 3, 2, 3)]
FIVE_ROOM_EDGES = [edge(0, 1), edge(1, 2), edge(2, 3), edge(3, 4),
                   edge(0, 2), edge(0, 4), edge(1, 3)]

# A 6-room ring where door_connectivity has to add chords, so the variant
# search has something to transform.
SIX_ROOM_NODES = [node(0, 0, 0, 4, 3), node(1, 4, 0, 3, 3), node(2, 8, 0, 4, 3),
                  node(3, 8, 4, 4, 4), node(4, 4, 4, 3, 4), node(5, 0, 4, 4, 4)]
SIX_ROOM_EDGES = [edge(0, 1), edge(1, 2), edge(2, 3), edge(3, 4), edge(4, 5),
                  edge(5, 0), edge(1, 4)]


def call(params, request_id="test"):
    return Documents.get_multi_ptpg_floorplans({"request_id": request_id, "params": params})


def test_five_room_exact():
    print("\nT1: 5-room graph, sizes that admit an exact rectangular dual")
    started = time.time()
    res = call({"nodes": FIVE_ROOM_NODES, "edges": FIVE_ROOM_EDGES,
                "strictness": "relaxed"})
    elapsed = time.time() - started

    check("T1 status ok", res["status"] == "ok", res.get("error"))
    check("T1 engine name", res["engine"] == "MultiPTPG_FloorPlan")
    try:
        json.dumps(res)
        serializable = True
    except Exception as exc:
        serializable = False
        print("    ", exc)
    check("T1 response is JSON-serializable", serializable)

    data = res["data"]
    check("T1 produced floorplans", data["floorplan_count"] > 0,
          f"got {data['floorplan_count']}")
    check("T1 finished quickly", elapsed < 30, f"{elapsed:.1f}s")

    requested = {n["id"]: (n["width"], n["height"]) for n in FIVE_ROOM_NODES}
    exact = True
    for variant in data["variants"]:
        for plan in variant["floorplans"]:
            for room in plan["rooms"]:
                want = requested.get(room["id"])
                if want and (room["width"], room["height"]) != want:
                    exact = False
                    print(f"     room {room['id']}: got "
                          f"{room['width']}x{room['height']}, want {want[0]}x{want[1]}")
    check("T1 every room keeps its exact requested size", exact)

    compact = [p for v in data["variants"] for p in v["floorplans"] if not p["is_relaxed"]]
    check("T1 at least one gap-free plan", len(compact) > 0)
    if compact:
        adj = compact[0]["adjacency"]
        check("T1 compact plan realises every adjacency", not adj["missing"], adj["missing"])
        check("T1 compact plan invents no adjacency", not adj["extra"], adj["extra"])


def test_variants_multiply():
    print("\nT2: unprotected edges yield several distinct PTPG variants")
    started = time.time()
    res = call({"nodes": SIX_ROOM_NODES, "edges": SIX_ROOM_EDGES,
                "preserve_input_edges": False, "max_variants": 12, "max_depth": 2,
                "strictness": "best_effort", "time_budget_seconds": 120})
    elapsed = time.time() - started

    check("T2 status ok", res["status"] == "ok", res.get("error"))
    data = res["data"]
    check("T2 more than one variant", data["variant_count"] > 1,
          f"got {data['variant_count']}")
    check("T2 floorplans across variants", data["floorplan_count"] > 0,
          f"got {data['floorplan_count']}")
    check("T2 respects max_variants", data["variant_count"] <= 12)
    check("T2 within budget", elapsed < 120, f"{elapsed:.1f}s")

    keys = {tuple(sorted(tuple(e) for e in v["edges"])) for v in data["variants"]}
    check("T2 variants are all distinct graphs", len(keys) == data["variant_count"],
          f"{len(keys)} distinct of {data['variant_count']}")

    bases = [v for v in data["variants"] if v["is_base"]]
    check("T2 exactly one base variant", len(bases) == 1)

    node_counts = {len(v["nodes"]) for v in data["variants"]}
    check("T2 every variant keeps the full room set", node_counts == {len(SIX_ROOM_NODES)},
          str(node_counts))


def test_protected_edges():
    print("\nT3: protected_edges keeps the named adjacencies in every variant")
    protect = [[0, 1], [3, 4]]
    res = call({"nodes": SIX_ROOM_NODES, "edges": SIX_ROOM_EDGES,
                "protected_edges": protect, "max_variants": 10, "max_depth": 2,
                "strictness": "best_effort", "time_budget_seconds": 120})
    check("T3 status ok", res["status"] == "ok", res.get("error"))
    data = res["data"]
    kept = True
    for variant in data["variants"]:
        edges = {tuple(sorted(e)) for e in variant["edges"]}
        for pair in protect:
            if tuple(sorted(pair)) not in edges:
                kept = False
                print(f"     variant {variant['variant_id']} dropped {pair}")
    check("T3 protected edges survive every variant", kept)
    check("T3 reports what it protected",
          data["stats"]["protected_edges"] == [list(p) for p in protect],
          str(data["stats"]["protected_edges"]))


def test_strictness_ladder():
    print("\nT4: strictness ladder on sizes that admit no exact dual")
    equal = [node(i, x, y, 4, 3) for i, (x, y) in
             enumerate([(0, 0), (2, 0), (4, 0), (4, 3), (0, 3)])]
    common = {"nodes": equal, "edges": FIVE_ROOM_EDGES}

    strict = call(dict(common, strictness="exact"))
    relaxed = call(dict(common, strictness="relaxed"))
    best = call(dict(common, strictness="best_effort"))

    check("T4 all three succeed",
          all(r["status"] == "ok" for r in (strict, relaxed, best)))
    check("T4 exact finds nothing", strict["data"]["floorplan_count"] == 0,
          f"got {strict['data']['floorplan_count']}")
    check("T4 best_effort finds something", best["data"]["floorplan_count"] > 0,
          f"got {best['data']['floorplan_count']}")
    check("T4 best_effort >= relaxed",
          best["data"]["floorplan_count"] >= relaxed["data"]["floorplan_count"])

    empty = [v for v in relaxed["data"]["variants"] if v["floorplan_count"] == 0]
    check("T4 empty variants explain themselves",
          all(v["status"] == "no_floorplan" and v["reason"] for v in empty))


def test_validation_errors():
    print("\nT5: input validation")
    ok_nodes = FIVE_ROOM_NODES

    missing_dims = [dict(n) for n in ok_nodes]
    missing_dims[2] = {k: v for k, v in missing_dims[2].items() if k != "width"}
    res = call({"nodes": missing_dims, "edges": FIVE_ROOM_EDGES})
    check("T5 missing width rejected", res["status"] == "error")
    check("T5 missing width names the node", "2" in res["error"]["message"],
          res["error"]["message"])

    res = call({"nodes": ok_nodes[:2], "edges": [edge(0, 1)]})
    check("T5 too few rooms rejected", res["status"] == "error")

    res = call({"nodes": ok_nodes, "edges": FIVE_ROOM_EDGES, "strictness": "nonsense"})
    check("T5 bad strictness rejected", res["status"] == "error")

    gapped = [dict(n) for n in ok_nodes]
    gapped[3]["id"] = 9
    res = call({"nodes": gapped, "edges": FIVE_ROOM_EDGES})
    check("T5 non-contiguous ids rejected", res["status"] == "error")

    res = call({"nodes": ok_nodes,
                "edges": [{"source": 0, "target": 1, "color": "red"}]})
    check("T5 red-only edges rejected", res["status"] == "error")


def test_plot_constraint():
    print("\nT6: plot dimensions reject oversized layouts")
    unbounded = call({"nodes": FIVE_ROOM_NODES, "edges": FIVE_ROOM_EDGES})
    tight = call({"nodes": FIVE_ROOM_NODES, "edges": FIVE_ROOM_EDGES,
                  "plot_width": 3, "plot_height": 3})
    check("T6 unbounded produces plans", unbounded["data"]["floorplan_count"] > 0)
    check("T6 impossible plot produces none", tight["data"]["floorplan_count"] == 0,
          f"got {tight['data']['floorplan_count']}")

    generous = call({"nodes": FIVE_ROOM_NODES, "edges": FIVE_ROOM_EDGES,
                     "plot_width": 20, "plot_height": 20})
    within = all(p["width"] <= 20 and p["height"] <= 20
                 for v in generous["data"]["variants"] for p in v["floorplans"])
    check("T6 plans fit inside a generous plot", within)


def _faces_side(plan, room_id, direction):
    """Independent geometric check, in the engine's own y-UP frame (N = high y).

    Deliberately not a call into ptpg_floorplanner.plan_satisfies_cardinal: a test
    that reuses the implementation it is checking proves only self-consistency.
    Includes the recess-not-void rule, without which a room floating well short of
    the edge across empty space passes.
    """
    rects = {r["id"]: (r["x"], r["x"] + r["width"], r["y"], r["y"] + r["height"])
             for r in plan["rooms"]}
    if room_id not in rects:
        return False
    bx0 = min(v[0] for v in rects.values()); bx1 = max(v[1] for v in rects.values())
    by0 = min(v[2] for v in rects.values()); by1 = max(v[3] for v in rects.values())
    eps = max(bx1 - bx0, by1 - by0, 1e-6) * 1e-4
    recess = min(min(r["width"], r["height"]) for r in plan["rooms"])
    rx0, rx1, ry0, ry1 = rects[room_id]
    if direction == "N":
        strip, gap = (rx0, rx1, ry1, by1), by1 - ry1
    elif direction == "S":
        strip, gap = (rx0, rx1, by0, ry0), ry0 - by0
    elif direction == "E":
        strip, gap = (rx1, bx1, ry0, ry1), bx1 - rx1
    else:
        strip, gap = (bx0, rx0, ry0, ry1), rx0 - bx0
    if gap > eps and gap >= recess:
        return False
    for other, (ox0, ox1, oy0, oy1) in rects.items():
        if other == room_id:
            continue
        if (min(ox1, strip[1]) - max(ox0, strip[0]) > eps and
                min(oy1, strip[3]) - max(oy0, strip[2]) > eps):
            return False
    return True


def test_cardinal_constraints():
    print("\nT7: N/E/S/W pins")
    base = {"nodes": SIX_ROOM_NODES, "edges": SIX_ROOM_EDGES,
            "preserve_input_edges": False, "strictness": "best_effort"}

    unpinned = call(base)
    check("T7 unpinned baseline produces plans",
          unpinned["data"]["floorplan_count"] > 0)
    check("T7 no pins reports none requested",
          unpinned["data"]["cardinal"]["requested"] == []
          and unpinned["data"]["cardinal"]["applied"] is False)
    check("T7 no pins leaves the verdict unset, not false",
          all(v["cardinal_satisfied"] is None for v in unpinned["data"]["variants"]),
          "absent must never read as failed")

    for direction in ("N", "E", "S", "W"):
        res = call(dict(base, cardinal_constraints=[{"room": 0, "direction": direction}]))
        data = res["data"]
        check(f"T7 {direction} pin returns plans", data["floorplan_count"] > 0,
              f"got {data['floorplan_count']}")
        if data["cardinal"]["ignored"]:
            # Legal outcome, but it has to be stated rather than silently unpinned.
            check(f"T7 {direction} unsatisfiable pin is disclosed",
                  any("ignored" in w for w in data["warnings"]))
            continue
        bad = [(v["variant_id"], p) for v in data["variants"] for p in v["floorplans"]
               if not _faces_side(p, 0, direction)]
        check(f"T7 {direction} every returned plan really faces {direction}",
              not bad, f"{len(bad)} violate")
        check(f"T7 {direction} variants claiming the pin hold it",
              all(v["cardinal_satisfied"] for v in data["variants"] if v["floorplans"]))
        check(f"T7 {direction} pinning never adds arrangements",
              data["variant_count"] <= unpinned["data"]["variant_count"],
              f"{data['variant_count']} vs {unpinned['data']['variant_count']}")

    # Opposite pins on one room can never both hold. They are rejected UP FRONT
    # with a warning naming the room, not discovered after two full dimensioning
    # passes and blamed on the room sizes (the old behaviour).
    both = call(dict(base, cardinal_constraints=[{"room": 0, "direction": "N"},
                                                 {"room": 0, "direction": "S"}]))
    check("T7 contradictory pins still return plans",
          both["data"]["floorplan_count"] > 0)
    check("T7 contradictory pins are dropped up front, naming the room",
          any("opposite" in w and "R0" in w for w in both["data"]["warnings"]),
          f"warnings: {both['data']['warnings']}")
    check("T7 contradictory pins are not reported as ignored",
          both["data"]["cardinal"]["ignored"] is False)
    check("T7 contradictory pins stay visible in requested",
          len(both["data"]["cardinal"]["requested"]) == 2)
    check("T7 contradictory pins are not attempted",
          both["data"]["cardinal"]["attempted"] == [])

    # A room id outside the graph is dropped by the normalizer, so nothing is
    # pinned - and the drop is now disclosed in warnings instead of silent.
    junk = call(dict(base, cardinal_constraints=[{"room": 99, "direction": "N"},
                                                 {"room": 0, "direction": "sideways"}]))
    check("T7 invalid pins are dropped, not fatal", junk["status"] == "ok")
    check("T7 invalid pins pin nothing", junk["data"]["cardinal"]["requested"] == [])
    check("T7 invalid pins are disclosed",
          any("dropped during normalization" in w for w in junk["data"]["warnings"]),
          f"warnings: {junk['data']['warnings']}")


def test_phase1_hardening():
    """Phase 1 of CARDINAL_CONSTRAINTS_MULTI_PTPG_PLAN.md: correctness fixes."""
    print("\nT10: boundary-cap symmetry, arc-order filter, honest reporting")

    # -- G2: the boundary cap counts raw boundaries and keeps whole orbits, so
    # the default cap and no cap agree on an 8-room ring. Before the fix the
    # flat-list cap cut every orbit member past position 48 and this graph
    # returned 5 plans against 13 uncapped, with a reason blaming room sizes.
    ring_nodes = [node(i, 0, 0, 10, 10) for i in range(8)]
    ring_edges = [edge(i, (i + 1) % 8) for i in range(8)]
    ring = {"nodes": ring_nodes, "edges": ring_edges,
            "preserve_input_edges": False, "strictness": "best_effort",
            "max_floorplans": 0, "time_budget_seconds": 300}
    capped = call(ring)
    uncapped = call(dict(ring, max_boundaries_per_variant=0))
    check("T10 default boundary cap loses no plans vs uncapped",
          capped["data"]["floorplan_count"] == uncapped["data"]["floorplan_count"],
          f"{capped['data']['floorplan_count']} vs "
          f"{uncapped['data']['floorplan_count']}")
    check("T10 variant statuses agree with the uncapped run",
          [v["status"] for v in capped["data"]["variants"]]
          == [v["status"] for v in uncapped["data"]["variants"]])

    # -- Orbit completeness at the placer level: every raw boundary's full
    # 8-element dihedral orbit survives the cap (reflections are load-bearing:
    # on a 6-ring, all placeable boundaries were reflections).
    from GPLAN.source import ptpg_floorplanner as pfp
    stats = {}
    node_ids = list(range(6))
    hexagon = [(i, (i + 1) % 6) for i in range(6)] + [(0, 2), (0, 3), (3, 5)]
    bdys = pfp.get_boundaries(node_ids, hexagon, already_ptpg=False,
                              max_boundaries=4, stats=stats)
    check("T10 truncation is reported by get_boundaries", stats["truncated"] is True)
    check("T10 raw_kept respects the cap", stats["raw_kept"] == 4,
          f"kept {stats['raw_kept']}")
    keys = {str(b) for b in bdys}

    def orbit_of(b):
        out = [b]
        cur = b
        for _ in range(3):
            cur = [cur[1], cur[2], cur[3], cur[0]]
            out.append(cur)
        for rot in range(4):
            rb = b
            for _ in range(rot):
                rb = [rb[1], rb[2], rb[3], rb[0]]
            out.append([list(reversed(rb[3])), list(reversed(rb[2])),
                        list(reversed(rb[1])), list(reversed(rb[0]))])
        return out
    orbit_complete = all(str(m) in keys for b in bdys for m in orbit_of(b))
    check("T10 every kept boundary carries its whole orbit", orbit_complete)

    # -- Arc-order filter: four pins whose N,E,W,S order contradicts every
    # rotation AND the reflection of the outer cycle. Membership alone passes
    # (all four rooms are on the cycle); the order predicate must catch it,
    # keep-all must fire, and the outcome must be disclosed.
    sq_nodes = [node(i, 0, 0, 10, 10) for i in range(4)]
    sq_edges = [edge(0, 1), edge(1, 2), edge(2, 3), edge(3, 0), edge(0, 2)]
    impossible = call({"nodes": sq_nodes, "edges": sq_edges,
                       "preserve_input_edges": False, "strictness": "best_effort",
                       "cardinal_constraints": [
                           {"room": 0, "direction": "N"}, {"room": 1, "direction": "E"},
                           {"room": 2, "direction": "W"}, {"room": 3, "direction": "S"}]})
    d = impossible["data"]
    check("T10 impossible arc order still returns plans", d["floorplan_count"] > 0)
    check("T10 keep-all fallback is flagged in stats",
          d["stats"]["variants_kept_by_cardinal_fallback"] is True
          or d["cardinal"]["ignored"] is True,
          f"stats: {d['stats']}")
    # The arc order is impossible on a GAPLESS boundary, but relaxed layouts
    # with voids can genuinely face all four pins (that is what the keep-all
    # fallback is for). So the contract is: either the pins were ignored and
    # disclosed, or every returned plan really faces every pin.
    if d["cardinal"]["ignored"]:
        check("T10 impossible pins are disclosed when dropped",
              any("ignored" in w for w in d["warnings"]))
    else:
        four = [(0, "N"), (1, "E"), (2, "W"), (3, "S")]
        bad = [p for v in d["variants"] for p in v["floorplans"]
               if not all(_faces_side(p, r, dr) for r, dr in four)]
        check("T10 kept pins are geometrically true on every plan", not bad,
              f"{len(bad)} violate")

    # -- applied is evidence, not the absence of a flag: with pins and zero
    # returned plans the response must not claim applied: true.
    tiny = call({"nodes": sq_nodes, "edges": sq_edges,
                 "preserve_input_edges": False, "strictness": "exact",
                 "cardinal_constraints": [{"room": 0, "direction": "N"}]})
    dd = tiny["data"]
    if dd["floorplan_count"] == 0:
        check("T10 zero plans never report applied: true",
              dd["cardinal"]["applied"] is False)
        check("T10 zero plans set the undetermined state",
              dd["cardinal"]["undetermined"] is True or dd["cardinal"]["ignored"] is True)
    else:
        check("T10 plans returned with pins report applied: true",
              dd["cardinal"]["applied"] is True)

    # -- interior_rooms vs a pin on the same room: the pin wins, and the
    # response says so instead of blaming the pins for an emptied filter.
    conflict = call({"nodes": SIX_ROOM_NODES, "edges": SIX_ROOM_EDGES,
                     "preserve_input_edges": False, "strictness": "best_effort",
                     "interior_rooms": [0],
                     "cardinal_constraints": [{"room": 0, "direction": "N"}]})
    check("T10 interior+pin conflict is disclosed and the pin wins",
          any("pin won" in w for w in conflict["data"]["warnings"]),
          f"warnings: {conflict['data']['warnings']}")

    # -- 1.4: disconnected input is rejected up front with a fixable message,
    # not run unbounded through door_connectivity.
    started = time.time()
    disc = call({"nodes": [node(i, 0, 0, 10, 10) for i in range(6)],
                 "edges": [edge(0, 1), edge(1, 2), edge(3, 4), edge(4, 5)],
                 "strictness": "best_effort"})
    elapsed = time.time() - started
    check("T10 disconnected input is a validation error", disc["status"] == "error")
    check("T10 disconnected error names the problem",
          "disconnected" in str(disc.get("error", {}).get("message", "")))
    check("T10 disconnected input fails fast", elapsed < 5, f"{elapsed:.1f}s")


def test_must_hold_pin():
    """A pin the base arrangement demonstrably satisfies must hold, with no
    ignored-escape: this is the assertion that fails if pins regress."""
    print("\nT11: a satisfiable pin is never dropped")
    for direction in ("N", "E", "S", "W"):
        res = call({"nodes": FIVE_ROOM_NODES, "edges": FIVE_ROOM_EDGES,
                    "strictness": "best_effort", "preserve_input_edges": False,
                    "cardinal_constraints": [{"room": 2, "direction": direction}]})
        data = res["data"]
        check(f"T11 {direction} pin on room 2 is applied, not ignored",
              data["cardinal"]["ignored"] is False
              and data["cardinal"]["applied"] is True,
              f"cardinal: {data['cardinal']}")
        bad = [p for v in data["variants"] for p in v["floorplans"]
               if not _faces_side(p, 2, direction)]
        check(f"T11 {direction} every plan faces {direction}", not bad,
              f"{len(bad)} violate")


def test_variant_cap_is_reported():
    print("\nT8: the variant cap never passes for a complete closure")
    full = call({"nodes": SIX_ROOM_NODES, "edges": SIX_ROOM_EDGES,
                 "preserve_input_edges": False, "max_depth": 2,
                 "max_variants": 200, "strictness": "best_effort"})
    total = full["data"]["variant_count"]
    check("T8 uncapped run does not report a cap",
          full["data"]["stats"]["variant_cap_hit"] is False)
    check("T8 uncapped run warns about no cap",
          not any("max_variants" in w for w in full["data"]["warnings"]))

    if total > 2:
        capped = call({"nodes": SIX_ROOM_NODES, "edges": SIX_ROOM_EDGES,
                       "preserve_input_edges": False, "max_depth": 2,
                       "max_variants": 2, "strictness": "best_effort"})
        check("T8 a binding cap is reported in stats",
              capped["data"]["stats"]["variant_cap_hit"] is True)
        check("T8 a binding cap is warned about",
              any("max_variants" in w for w in capped["data"]["warnings"]),
              "; ".join(capped["data"]["warnings"]))
        check("T8 a binding cap actually bounds the set",
              capped["data"]["variant_count"] <= 2)
    else:
        print(f"     skipped cap assertions: closure is only {total} variants")


def test_total_floorplan_cap():
    print("\nT9: the total floorplan cap binds, spreads, and is reported")
    base = {"nodes": SIX_ROOM_NODES, "edges": SIX_ROOM_EDGES,
            "preserve_input_edges": False, "max_depth": 2, "max_variants": 200,
            "floorplans_per_variant": 5, "strictness": "best_effort"}

    uncapped = call({**base, "max_floorplans": 0})["data"]
    check("T9 uncapped run does not report a cap",
          uncapped["stats"]["floorplan_cap_hit"] is False)
    check("T9 uncapped run warns about no cap",
          not any("max_floorplans" in w for w in uncapped["warnings"]),
          "; ".join(uncapped["warnings"]))
    available = uncapped["floorplan_count"]
    producing = sum(1 for v in uncapped["variants"] if v["floorplan_count"] > 0)

    if available <= 4:
        print(f"     skipped cap assertions: only {available} plans available")
        return

    cap = max(2, producing // 2)
    capped = call({**base, "max_floorplans": cap})["data"]
    check("T9 a binding cap is reported in stats",
          capped["stats"]["floorplan_cap_hit"] is True)
    check("T9 a binding cap is warned about",
          any("max_floorplans" in w or "floorplans in total" in w
              for w in capped["warnings"]),
          "; ".join(capped["warnings"]))
    check("T9 the cap actually bounds the batch",
          capped["floorplan_count"] <= cap,
          f"got {capped['floorplan_count']} for a cap of {cap}")
    check("T9 floorplan_count matches what was returned",
          capped["floorplan_count"] == sum(len(v["floorplans"]) for v in capped["variants"]))
    check("T9 every variant's count matches its list",
          all(v["floorplan_count"] == len(v["floorplans"]) for v in capped["variants"]))

    # The point of the round robin: spend the cap on breadth, not on every
    # option of the first arrangement. Counts differing by at most one means no
    # arrangement was left on zero while another kept a spare.
    kept = [v["floorplan_count"] for v in capped["variants"] if v["floorplan_count"] > 0]
    check("T9 the cap is spent breadth-first",
          bool(kept) and max(kept) - min(kept) <= 1,
          f"kept counts {sorted(kept, reverse=True)[:8]}")
    check("T9 the cap fills as many arrangements as it can",
          len(kept) == min(cap, producing),
          f"{len(kept)} arrangements kept, cap {cap}, {producing} could produce")

    # Time skips and cap skips share a status, so they must not share a reason:
    # telling a user to raise time_budget_seconds for a cap is a dead end.
    dropped = [v for v in capped["variants"] if v["floorplan_count"] == 0]
    check("T9 dropped arrangements blame the cap, not the clock",
          all("cap" in (v.get("reason") or "") or v["status"] != "skipped"
              for v in dropped),
          "; ".join(f"{v['status']}:{v.get('reason')}" for v in dropped[:3]))
    check("T9 the cap does not report a time truncation",
          capped["stats"]["truncated"] is False)


def main():
    print("=" * 70)
    print("multi-PTPG pipeline tests")
    print("=" * 70)
    for test in (test_five_room_exact, test_variants_multiply, test_protected_edges,
                 test_strictness_ladder, test_validation_errors, test_plot_constraint,
                 test_cardinal_constraints, test_phase1_hardening, test_must_hold_pin,
                 test_variant_cap_is_reported, test_total_floorplan_cap):
        try:
            test()
        except Exception:
            import traceback
            traceback.print_exc()
            FAILED.append((test.__name__, "raised"))

    print("\n" + "=" * 70)
    print(f"{len(PASSED)} passed, {len(FAILED)} failed")
    for name, detail in FAILED:
        print(f"  FAILED: {name} {detail}")
    return 1 if FAILED else 0


if __name__ == "__main__":
    sys.exit(main())
