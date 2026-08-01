"""Geometric post-processing of dimensioned floorplans against the NBC rulebook.

The dimensioned catalogue (door_connectivity + minDimEnabled) delivers plans as
gapless rectangular tilings. That gaplessness is exactly what inflates service
rooms: the bounding box's leftover area must go SOMEWHERE, and whichever room
can reach a notch absorbs all of it - the documented 54x8 ft bathroom. This
module trades the perfect rectangle for architectural validity: rooms are
brought inside their aspect band and NBC ceilings, and the outer boundary is
allowed to step inward (notches) where that is the only way to get there.

Three phases, all pure geometry on (x0, y0, x1, y1) rects in feet, y-down:

1. REPAIR (reuse): api.repair_dimensions moves the shared coordinate lines of
   the dissection - gapless-preserving, adjacency-preserving - with bounds
   built from the NBC rules and the aspect band.
2. TRIM (new): a room still past its ceiling or aspect band is trimmed inward
   from a FULLY EXTERIOR side (the whole strip from that side to the plan
   bounding box is empty), so every notch created is connected to the outside.
   Door adjacencies keep at least `min_door_overlap` ft of shared wall; NBC
   and user minimums are floors.
3. ABSORB (new, capped): rooms grow into the notches left by trimming, but
   only within their own ceilings and aspect band - the uncapped fill that
   caused the original inflation is never run.
4. CLOSE (rectangle preference): a plan that entered gapless and leaves notched
   gets one more absorption round with the SPAN and AREA ceilings relaxed by
   `notch_close_slack`; the aspect band stays hard, so nothing can become a
   corridor. Kept only when it actually closes the outline back to a rectangle.
   When even that cannot close it, the trims are REVERTED to the last gapless
   state (the repaired tiling): a rectangular outline outranks the NBC
   ceilings, and every room left over its ceiling is named in the report.
   `prefer_rectangle: False` restores the old behaviour (ship the notches).
5. FILL (plot preference): a gapless plan smaller than the requested plot grows
   toward it by advancing WHOLE boundary sides, each by the smallest headroom
   its rooms have inside their own ceilings - so the outline stays a rectangle
   and no room passes its cap. `plot_width`/`plot_height` are a HARD cap on
   every phase: no phase may push the plan outside the plot.

Priority order, highest first: plot cap, room floors + doors + no overlap/hole,
rectangular outline, NBC ceilings. Phases 4 and 5 are what makes the outline
outrank the ceilings, and both report exactly what they traded.

Every phase is validated (no overlaps, no interior holes, door overlaps kept);
a phase that breaks an invariant is rolled back for that plan and reported.
"""

import copy

from GPLAN.source.postprocessing import nbc_rules

_INF = float("inf")

# Minimum shared wall length for a door, matching the min-dim solver's black
# edge overlap constant (small_positive = 2 in minimum_dimensioning.py).
DEFAULT_MIN_DOOR_OVERLAP = 2.0

DEFAULT_OPTIONS = {
    "repair": True,          # phase 1: in-tile coordinate-line repair
    "trim": True,            # phase 2: exterior trimming (creates notches)
    "absorb": True,          # phase 3: capped re-absorption of notches
    "max_passes": 3,         # trim+absorb rounds
    "min_door_overlap": DEFAULT_MIN_DOOR_OVERLAP,
    "aspect": None,          # optional {"min": 0.5, "max": 1.5} w/h band,
                             # intersected with each room type's own band
    "rules": None,           # optional {"Bathroom": {"max_area": 60, ...}}
    "tolerance": 0.02,       # fraction past a limit before we act (2%)
    "max_bbox_growth": 0.03, # in-tile repair may grow the plan extent by at
                             # most this fraction per axis, else it rolls back
                             # (NBC minimum floors must rebalance the tiling,
                             # not balloon the footprint)
    "max_notch_ratio": 0.25, # a trim+absorb round that leaves notches beyond
                             # this fraction of the bounding box rolls back:
                             # past it the outline is a shape nobody would
                             # build. Provisional default pending measurement
                             # on live batches (plan open question 5); the
                             # synthetic worst-case fixture (a bathroom 2.4x
                             # over its ceiling) legitimately needs ~0.15.
    # -- plot and outline (phases 4 and 5) ---------------------------------
    "plot_width": None,      # HARD cap on the plan extent, ft. No phase may
    "plot_height": None,     # push the bounding box outside it. Orientation
                             # agnostic: a plan fitting the plot rotated fits.
    "target_width": None,    # the extent to GROW toward when the plan is
    "target_height": None,   # smaller (the real unit footprint, not the
                             # rejection cap). None disables phase 5.
    "prefer_rectangle": True,# phase 4: reclose the outline of a plan that was
                             # gapless before post-processing
    "fill_target": True,     # phase 5: grow a gapless plan to the target
    "notch_close_slack": 0.25,
                             # phase 4 only: how far past its span/area ceiling
                             # a room may go to close the outline. The aspect
                             # band is NOT relaxed, so the reclose can never
                             # reproduce the 54x8 bathroom this module exists
                             # to prevent; every room that uses the slack is
                             # named in the report.
}


def _merged_options(options):
    opts = dict(DEFAULT_OPTIONS)
    for key, value in (options or {}).items():
        if key in opts and value is not None:
            opts[key] = value
    return opts


# ---------------------------------------------------------------------------
# geometry helpers
# ---------------------------------------------------------------------------

def _bbox(rects):
    return (min(r[0] for r in rects), min(r[1] for r in rects),
            max(r[2] for r in rects), max(r[3] for r in rects))


def _plan_eps(rects):
    x0, y0, x1, y1 = _bbox(rects)
    return max(x1 - x0, y1 - y0, 1e-6) * 1e-4


def _rects_overlap(rects, eps):
    for i in range(len(rects)):
        x0, y0, x1, y1 = rects[i]
        for j in range(i + 1, len(rects)):
            a0, b0, a1, b1 = rects[j]
            if min(x1, a1) - max(x0, a0) > eps and min(y1, b1) - max(y0, b0) > eps:
                return True
    return False


def _shared_wall(rect_a, rect_b, touch_eps):
    """Length of the wall segment two rects share, or 0.0.

    Touching means one rect's edge coordinate coincides with the other's
    (within touch_eps); the shared length is the overlap on the other axis.
    """
    ax0, ay0, ax1, ay1 = rect_a
    bx0, by0, bx1, by1 = rect_b
    if abs(ax1 - bx0) <= touch_eps or abs(bx1 - ax0) <= touch_eps:
        return max(0.0, min(ay1, by1) - max(ay0, by0))
    if abs(ay1 - by0) <= touch_eps or abs(by1 - ay0) <= touch_eps:
        return max(0.0, min(ax1, bx1) - max(ax0, bx0))
    return 0.0


def _fully_exterior(rects, i, side, eps):
    """True when the whole strip from room i's `side` to the plan bounding box
    is free of other rooms, so trimming that side can only widen a channel
    that reaches the outside - never create an interior hole."""
    bx0, by0, bx1, by1 = _bbox(rects)
    x0, y0, x1, y1 = rects[i]
    if side == "E":
        sx0, sy0, sx1, sy1 = x1, y0, bx1, y1
    elif side == "W":
        sx0, sy0, sx1, sy1 = bx0, y0, x0, y1
    elif side == "N":
        sx0, sy0, sx1, sy1 = x0, by0, x1, y0
    else:  # "S"
        sx0, sy0, sx1, sy1 = x0, y1, x1, by1
    for j, r in enumerate(rects):
        if j == i:
            continue
        if min(r[2], sx1) - max(r[0], sx0) > eps and min(r[3], sy1) - max(r[1], sy0) > eps:
            return False
    return True


def _coverage_grid(rects):
    """Irregular grid over all rect edges: (xs, ys, covered[ix][iy]).

    Containment tolerance (2e-6) must exceed the grid-line rounding (1e-6),
    or a rect edge like 10.0000004 rounded onto the 10.0 line leaves a
    phantom uncovered sliver."""
    xs = sorted({round(v, 6) for r in rects for v in (r[0], r[2])})
    ys = sorted({round(v, 6) for r in rects for v in (r[1], r[3])})
    tol = 2e-6
    covered = [[False] * (len(ys) - 1) for _ in range(len(xs) - 1)]
    for (x0, y0, x1, y1) in rects:
        for ix in range(len(xs) - 1):
            if xs[ix] < x0 - tol or xs[ix + 1] > x1 + tol:
                continue
            for iy in range(len(ys) - 1):
                if ys[iy] >= y0 - tol and ys[iy + 1] <= y1 + tol:
                    covered[ix][iy] = True
    return xs, ys, covered


def _void_metrics(rects):
    """(notch_area, interior_hole_area) of the empty space inside the bbox.

    Notches are empty cells reachable from the bounding-box border; interior
    holes are empty cells that are not - those are never acceptable.
    """
    xs, ys, covered = _coverage_grid(rects)
    nx, ny = len(xs) - 1, len(ys) - 1
    reached = [[False] * ny for _ in range(nx)]
    stack = []
    for ix in range(nx):
        for iy in range(ny):
            if covered[ix][iy]:
                continue
            if ix == 0 or iy == 0 or ix == nx - 1 or iy == ny - 1:
                stack.append((ix, iy))
                reached[ix][iy] = True
    while stack:
        cx, cy = stack.pop()
        for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
            mx, my = cx + dx, cy + dy
            if 0 <= mx < nx and 0 <= my < ny and not covered[mx][my] \
                    and not reached[mx][my]:
                reached[mx][my] = True
                stack.append((mx, my))
    notch = 0.0
    interior = 0.0
    for ix in range(nx):
        for iy in range(ny):
            if covered[ix][iy]:
                continue
            cell = (xs[ix + 1] - xs[ix]) * (ys[iy + 1] - ys[iy])
            notch += cell
            if not reached[ix][iy]:
                interior += cell
    return notch, interior


def _dim_pair(opts, key_w, key_h):
    """(w, h) from two options, or None when either is missing/non-positive."""
    try:
        w = float(opts.get(key_w) or 0)
        h = float(opts.get(key_h) or 0)
    except (TypeError, ValueError):
        return None
    if w <= 0 or h <= 0 or w >= 99999 or h >= 99999:
        return None
    return (w, h)


def _oriented(pair, rects):
    """`pair` reoriented so its longer side lies on the plan's longer axis.

    The engine's rotation pass may have swapped a plan's axes, so a 36x28 plot
    constrains a 28x36 plan exactly as well; comparing raw w-to-w would reject
    or shrink a plan that fits perfectly turned a quarter.
    """
    if pair is None:
        return None
    w, h = pair
    x0, y0, x1, y1 = _bbox(rects)
    if (x1 - x0) >= (y1 - y0):
        return (max(w, h), min(w, h))
    return (min(w, h), max(w, h))


def _within_limits(rects, limits, eps):
    """True when the plan's extent fits `limits` (already oriented)."""
    if limits is None:
        return True
    x0, y0, x1, y1 = _bbox(rects)
    return (x1 - x0) <= limits[0] + eps and (y1 - y0) <= limits[1] + eps


# ---------------------------------------------------------------------------
# bounds and door requirements
# ---------------------------------------------------------------------------

def build_bounds(names, opts, user_min_w=None, user_min_h=None,
                 user_max_w=None, user_max_h=None,
                 user_min_a=None, user_max_a=None):
    """Per-room bound dicts driving all three phases.

    Orientation-agnostic on purpose: the engine's rotation pass may have
    swapped a plan's axes, so NBC W x H pairs are applied as (short, long)
    ceilings/floors, and user per-axis minimums collapse to their smaller
    value as the trim floor. `user_min_a`/`user_max_a` are the request's
    explicit per-room area rule; a user area cap tightens the NBC one,
    never loosens it.
    """
    overrides = opts.get("rules")
    aspect_override = opts.get("aspect") or {}
    ovr_lo = float(aspect_override.get("min") or 0) or None
    ovr_hi = float(aspect_override.get("max") or 0) or None

    def user_at(values, i):
        if not values or i >= len(values):
            return None
        try:
            v = float(values[i])
        except (TypeError, ValueError):
            return None
        return v if 0 < v < 99999 else None

    bounds = []
    for i, name in enumerate(names):
        rule = nbc_rules.rule_or_fallback(name, overrides)
        known = nbc_rules.rule_for(name, overrides) is not None
        ar_hi = float(rule["max_aspect"])
        ar_lo = 1.0 / ar_hi
        if ovr_lo:
            ar_lo = max(ar_lo, ovr_lo)
        if ovr_hi:
            ar_hi = min(ar_hi, ovr_hi)
        if ar_lo > ar_hi:
            ar_lo = ar_hi
        floor_short = min(rule["min_width"], rule["min_height"])
        floor_long = floor_short
        umw, umh = user_at(user_min_w, i), user_at(user_min_h, i)
        if umw is not None and umh is not None:
            # A user minimum is a per-axis pair, satisfied up to a whole-plan
            # rotation (fits_over semantics). The short axis must clear the
            # smaller of the two AND the long axis the larger, or a trim from
            # 10x14 toward a 10x10 square would violate a 10x12 request.
            floor_short = max(floor_short, min(umw, umh))
            floor_long = max(floor_long, max(umw, umh))
        floor_long = max(floor_long, floor_short)
        cap_short = min(rule["max_width"], rule["max_height"])
        cap_long = max(rule["max_width"], rule["max_height"])
        uxw, uxh = user_at(user_max_w, i), user_at(user_max_h, i)
        if uxw is not None and uxh is not None:
            cap_short = min(cap_short, min(uxw, uxh))
            cap_long = min(cap_long, max(uxw, uxh))
        cap_short = max(cap_short, floor_short)
        cap_long = max(cap_long, cap_short, floor_long)
        max_area = float(rule["max_area"])
        min_area = float(rule["min_area"]) if known else 0.0
        uxa = user_at(user_max_a, i)
        if uxa is not None:
            max_area = min(max_area, uxa)
        uma = user_at(user_min_a, i)
        if uma is not None:
            min_area = max(min_area, uma)
        max_area = max(max_area, min_area)
        bounds.append({
            # keys consumed by api._axis_targets / repair_dimensions:
            "minw": floor_short, "minh": floor_short,
            "maxw": cap_long, "maxh": cap_long,
            "minarea": min_area,
            "maxarea": max_area,
            "aspect": _INF,          # superseded by the asymmetric band below
            "ar_lo": ar_lo, "ar_hi": ar_hi,
            # extra keys for trim/absorb/reporting:
            "cap_short": cap_short, "cap_long": cap_long,
            "floor_short": floor_short, "floor_long": floor_long,
            "known": known, "room_class": rule["room_class"],
        })
    return bounds


def build_door_requirements(rects, names, edges, min_door, eps):
    """[(i, j, required_overlap_ft)] pairs whose shared wall must survive.

    `edges` may be index pairs ([0, 2]), name pairs (["Kitchen", "Living"]),
    or None. With edges (the requested adjacencies = doors), every listed pair
    that currently shares a wall is protected. Without, the fallback keeps
    every room's LARGEST current shared wall - each room retains at least one
    doorable neighbour, but engine-invented adjacencies stay expendable.

    Name resolution handles duplicates: a name maps to ALL rooms carrying it
    ("Bathroom" x2 in a 2BHK), and the pair is taken as every (i, j)
    combination that actually shares a wall right now. A numeric edge element
    is treated as a room name first (door_connectivity renames rooms to
    "1", "2", ...) and as an index otherwise. If a non-empty `edges` list
    resolves to no protectable pair at all, the largest-shared-wall fallback
    runs instead - an unresolvable edge list must never silently disable
    door protection.
    """
    touch = eps * 10
    by_name = {}
    for i, name in enumerate(names):
        by_name.setdefault(str(name), []).append(i)

    def resolve(value):
        """Edge element -> list of candidate room indices."""
        if isinstance(value, bool):
            return []
        if isinstance(value, (int, float)):
            idx = int(value)
            return [idx] if 0 <= idx < len(rects) else []
        key = str(value)
        if key in by_name:
            return by_name[key]
        if key.lstrip("-").isdigit():
            idx = int(key)
            return [idx] if 0 <= idx < len(rects) else []
        return []

    reqs = []

    def add(i, j):
        pair = (min(i, j), max(i, j))
        overlap = _shared_wall(rects[pair[0]], rects[pair[1]], touch)
        if overlap > eps and all(p[:2] != pair for p in reqs):
            reqs.append((pair[0], pair[1], min(min_door, overlap - eps)))

    if edges:
        for edge in edges:
            try:
                a_candidates = resolve(edge[0])
                b_candidates = resolve(edge[1])
            except (TypeError, IndexError, KeyError):
                continue
            for a in a_candidates:
                for b in b_candidates:
                    if a != b:
                        add(a, b)
    if not reqs:
        for i in range(len(rects)):
            best_j, best_overlap = -1, 0.0
            for j in range(len(rects)):
                if j == i:
                    continue
                overlap = _shared_wall(rects[i], rects[j], touch)
                if overlap > best_overlap:
                    best_j, best_overlap = j, overlap
            if best_j >= 0 and best_overlap > eps:
                add(i, best_j)
    return reqs


def _doors_ok(rects, door_reqs, eps):
    touch = eps * 10
    for a, b, req in door_reqs:
        if _shared_wall(rects[a], rects[b], touch) < req - eps:
            return False
    return True


# ---------------------------------------------------------------------------
# phase 2: exterior trimming
# ---------------------------------------------------------------------------

def _axis_ceilings(bounds, w, h, aspect_floors=True):
    """(ceiling_w, ceiling_h) given the current spans, orientation-aware.

    With `aspect_floors` (the trim/violation callers) the LOWER side of the
    aspect band is a floor too: a trim may not leave a room more slender than
    its band allows, which is how a 12x7 bathroom used to end up 12x5.7 (2.1:1
    against a 2.0 band) because only the ceiling side was applied. The absorb
    caller passes aspect_floors=False: growth exists to fill notches within
    ceilings, and a floor must never DRIVE growth (clients assert that
    post-processing does not grow rooms past their pre-trim spans).

    At w == h the span caps deliberately allow cap_long on BOTH axes rather
    than forcing an arbitrary landscape trim on a square room; the pair cap
    binds again as soon as the room actually elongates, and the area ceiling
    keeps a square room from exploiting the tie.
    """
    if w > h:
        cap_w, cap_h = bounds["cap_long"], bounds["cap_short"]
    elif h > w:
        cap_w, cap_h = bounds["cap_short"], bounds["cap_long"]
    else:
        cap_w = cap_h = bounds["cap_long"]
    floor_w = bounds.get("floor_long", bounds["minw"]) if w >= h \
        else bounds.get("floor_short", bounds["minw"])
    floor_h = bounds.get("floor_long", bounds["minh"]) if h > w \
        else bounds.get("floor_short", bounds["minh"])
    tw = min(cap_w,
             bounds["maxarea"] / h if bounds["maxarea"] < _INF else _INF,
             bounds["ar_hi"] * h)
    th = min(cap_h,
             bounds["maxarea"] / w if bounds["maxarea"] < _INF else _INF,
             w / bounds["ar_lo"])
    # floors win over ceilings; a conflict is reported, never silently forced
    tw = max(tw, floor_w,
             bounds["minarea"] / h if h > 0 else 0.0,
             bounds["ar_lo"] * h if aspect_floors else 0.0)
    th = max(th, floor_h,
             bounds["minarea"] / w if w > 0 else 0.0,
             w / bounds["ar_hi"] if aspect_floors else 0.0)
    return tw, th


def _aspect_of(rect):
    w, h = rect[2] - rect[0], rect[3] - rect[1]
    return max(w, h) / max(min(w, h), 1e-9)


def _slender_limit(bounds):
    """Slenderness cap (long/short) implied by the room's w/h band."""
    if bounds is None:
        return _INF
    ar_lo = bounds.get("ar_lo") or 0.0
    ar_hi = bounds.get("ar_hi") or _INF
    return max(ar_hi, (1.0 / ar_lo) if ar_lo > 0 else _INF)


def _aspect_allowances(rects, bounds, eps_ratio=1e-6):
    """Per-room hard ceiling on slenderness for every phase: no phase may
    leave a room more slender than where it STARTED or its band, whichever
    is looser. The band alone is not enough - a room that entered at 2.4
    against a 2.2 band must not drift to 2.6 just because it was already
    past the limit."""
    return [max(_aspect_of(r), _slender_limit(b)) * (1.0 + eps_ratio) + 1e-9
            for r, b in zip(rects, bounds)]


def _rooms_connected(rects, eps):
    """True when every room is reachable from every other through shared
    walls. Trims sever walls; only explicitly protected door pairs are
    length-checked, so a plan could otherwise split into islands."""
    n = len(rects)
    if n <= 1:
        return True
    touch = eps * 10
    seen = [False] * n
    stack = [0]
    seen[0] = True
    found = 1
    while stack:
        i = stack.pop()
        for j in range(n):
            if not seen[j] and _shared_wall(rects[i], rects[j], touch) > eps:
                seen[j] = True
                found += 1
                stack.append(j)
    return found == n


def _quality_vector(rect, bounds):
    """Per-room booleans, True = defect. Tolerances mirror plan_issues so the
    gate and the report cannot disagree about whether a limit is crossed.
    Components: (aspect past band, below minimum area, below minimum width,
    over area ceiling, over span ceiling)."""
    if bounds is None:
        return (False, False, False, False, False)
    w, h = rect[2] - rect[0], rect[3] - rect[1]
    short, long_ = min(w, h), max(w, h)
    area = w * h
    limit = _slender_limit(bounds)
    minarea = bounds.get("minarea") or 0.0
    maxarea = bounds.get("maxarea", _INF)
    floor_short = bounds.get("floor_short", bounds.get("minw", 0.0))
    cap_short = bounds.get("cap_short", _INF)
    cap_long = bounds.get("cap_long", _INF)
    return (
        limit < _INF and short > 0 and long_ / short > limit * 1.02,
        minarea > 0 and area < minarea * 0.98,
        floor_short > 0 and short < floor_short * 0.98,
        maxarea < _INF and area > maxarea * 1.02,
        (cap_long < _INF and long_ > cap_long * 1.02)
        or (cap_short < _INF and short > cap_short * 1.02),
    )


def _door_trim_limit(rects, door_reqs, i, side, eps):
    """Largest trim of room i's `side` that keeps every protected shared wall
    at its required length. Perpendicular neighbours lose overlap from the
    trimmed end; parallel ones are unaffected (the trimmed side is exterior,
    so nothing sits beyond it)."""
    x0, y0, x1, y1 = rects[i]
    limit = _INF
    # Same touching tolerance as the one that registered the door
    # (_shared_wall via build_door_requirements) - a mismatch here would let
    # a registered door pair fail the perpendicular test and go unprotected.
    touch = eps * 10
    for a, b, req in door_reqs:
        if i not in (a, b):
            continue
        j = b if a == i else a
        jx0, jy0, jx1, jy1 = rects[j]
        # overlap along x (neighbour above/below) shrinks on E/W trims;
        # overlap along y (neighbour left/right) shrinks on N/S trims.
        if side == "E":
            allowed = (x1 - max(x0, jx0)) - req
        elif side == "W":
            allowed = (min(x1, jx1) - x0) - req
        elif side == "N":
            allowed = (min(y1, jy1) - y0) - req
        else:  # "S"
            allowed = (y1 - max(y0, jy0)) - req
        # Only pairs actually sharing a wall on the perpendicular axis matter;
        # _shared_wall decides that, the formulas above just bound the trim.
        if side in ("E", "W"):
            perpendicular = (abs(y1 - jy0) <= touch or abs(jy1 - y0) <= touch)
        else:
            perpendicular = (abs(x1 - jx0) <= touch or abs(jx1 - x0) <= touch)
        if perpendicular:
            limit = min(limit, max(0.0, allowed))
    return limit


def _trim_pass(rects, bounds, names, door_reqs, eps, tolerance, actions,
               allowances=None):
    """One sweep of exterior trims. Returns True when anything moved."""
    progressed = False
    order = sorted(
        range(len(rects)),
        key=lambda k: -_violation_ratio(rects[k], bounds[k]))
    for i in order:
        if bounds[i] is None:
            continue
        for _ in range(3):  # a trim on one axis can retarget the other
            x0, y0, x1, y1 = rects[i]
            w, h = x1 - x0, y1 - y0
            if w <= 0 or h <= 0:
                break
            tw, th = _axis_ceilings(bounds[i], w, h)
            need_w = w - tw if w > tw * (1 + tolerance) else 0.0
            need_h = h - th if h > th * (1 + tolerance) else 0.0
            if need_w <= 0 and need_h <= 0:
                break
            # worse axis first, but an area violation can be fixed on either
            # axis, so fall through to the second when the first has no
            # fully-exterior side to trim from (e.g. a bathroom pinched
            # between neighbours left and right but open to the south).
            axes = []
            if need_w > 0:
                axes.append((need_w / max(tw, 1e-9), "x", need_w, ("E", "W")))
            if need_h > 0:
                axes.append((need_h / max(th, 1e-9), "y", need_h, ("S", "N")))
            axes.sort(reverse=True)
            trimmed = 0.0
            for _, axis, need, sides in axes:
                for side in sides:
                    if not _fully_exterior(rects, i, side, eps):
                        continue
                    allowed = min(need,
                                  _door_trim_limit(rects, door_reqs, i, side,
                                                   eps))
                    if allowed < 0.05:
                        continue
                    # Monotonicity: a trim may never leave the room more
                    # slender than it started or its band allows. The aspect
                    # floors in _axis_ceilings make this unreachable in
                    # theory; the check stays because a partial (door-limited)
                    # trim recomputes nothing and the promise is per-commit.
                    if axis == "x":
                        candidate = (x0, y0, x1 - allowed, y1) if side == "E" \
                            else (x0 + allowed, y0, x1, y1)
                    else:
                        candidate = (x0, y0 + allowed, x1, y1) if side == "N" \
                            else (x0, y0, x1, y1 - allowed)
                    if allowances is not None \
                            and _aspect_of(candidate) > allowances[i]:
                        continue
                    x0, y0, x1, y1 = rects[i]
                    if side == "E":
                        rects[i] = (x0, y0, x1 - allowed, y1)
                    elif side == "W":
                        rects[i] = (x0 + allowed, y0, x1, y1)
                    elif side == "N":
                        rects[i] = (x0, y0 + allowed, x1, y1)
                    else:
                        rects[i] = (x0, y0, x1, y1 - allowed)
                    trimmed = allowed
                    progressed = True
                    actions.setdefault(i, []).append(
                        "trimmed %.1f ft from %s" % (allowed, side))
                    break
                if trimmed > 0:
                    break
            if trimmed <= 0:
                break  # no exterior side available on any violating axis
    return progressed


def _violation_ratio(rect, bounds):
    if bounds is None:
        return 0.0
    w, h = rect[2] - rect[0], rect[3] - rect[1]
    if w <= 0 or h <= 0:
        return 0.0
    tw, th = _axis_ceilings(bounds, w, h)
    return max(w / max(tw, 1e-9), h / max(th, 1e-9), 1.0) - 1.0


# ---------------------------------------------------------------------------
# phase 3: capped absorption
# ---------------------------------------------------------------------------

def _absorb_pass(rects, bounds, eps, actions, allowances=None):
    """Grow rooms into empty space, hardest-capped last, never past their own
    ceilings or aspect band. The aspect-aware twin of api._fill_gaps with
    `enforce` permanently on. Returns True when anything moved.

    The ceilings are recomputed before EVERY directional growth: a room that
    just widened has less area headroom, so a ceiling computed once per sweep
    would let the next direction push it past maxarea (found in review: a
    5x7 bathroom absorbing east then south ended at 80 sqft against a 68
    ceiling because th was built from the pre-growth width).

    aspect_floors=False on the ceilings: a floor must never DRIVE growth
    (the aspect floor of a slender room can exceed its area ceiling, and
    clients assert post-processing does not grow rooms).
    """
    bx0, by0, bx1, by1 = _bbox(rects)

    def headroom(i):
        if bounds[i] is None:
            return _INF
        x0, y0, x1, y1 = rects[i]
        if bounds[i]["maxarea"] >= _INF:
            return _INF
        return bounds[i]["maxarea"] - (x1 - x0) * (y1 - y0)

    def ceilings(i, w, h):
        if bounds[i] is None:
            return _INF, _INF
        return _axis_ceilings(bounds[i], w, h, aspect_floors=False)

    def aspect_ok(i, candidate):
        # Growth along the long axis raises slenderness; the band ceilings
        # above already cap it, this guards the promise per-commit.
        return allowances is None or _aspect_of(candidate) <= allowances[i]

    def grow(i, side):
        """One directional growth of room i. Returns True when it moved."""
        x0, y0, x1, y1 = rects[i]
        tw, th = ceilings(i, x1 - x0, y1 - y0)
        if side in ("E", "W"):
            obst = bx1 if side == "E" else bx0
            for j, (a0, b0, a1, b1) in enumerate(rects):
                if j == i or min(y1, b1) - max(y0, b0) <= eps:
                    continue
                if side == "E" and a0 >= x1 - eps:
                    obst = min(obst, a0)
                elif side == "W" and a1 <= x0 + eps:
                    obst = max(obst, a1)
            if side == "E":
                obst = min(obst, x0 + tw)
                candidate = (x0, y0, obst, y1)
                delta = obst - x1
            else:
                obst = max(obst, x1 - tw)
                candidate = (obst, y0, x1, y1)
                delta = x0 - obst
        else:
            obst = by1 if side == "S" else by0
            for j, (a0, b0, a1, b1) in enumerate(rects):
                if j == i or min(x1, a1) - max(x0, a0) <= eps:
                    continue
                if side == "S" and b0 >= y1 - eps:
                    obst = min(obst, b0)
                elif side == "N" and b1 <= y0 + eps:
                    obst = max(obst, b1)
            if side == "S":
                obst = min(obst, y0 + th)
                candidate = (x0, y0, x1, obst)
                delta = obst - y1
            else:
                obst = max(obst, y1 - th)
                candidate = (x0, obst, x1, y1)
                delta = y0 - obst
        if delta <= 0.05 or not aspect_ok(i, candidate):
            return False
        rects[i] = candidate
        actions.setdefault(i, []).append(
            "absorbed %.1f ft toward %s" % (delta, side))
        return True

    progressed = False
    changed = True
    guard = 0
    while changed and guard < 60:
        changed = False
        guard += 1
        order = sorted(range(len(rects)), key=lambda i: (-headroom(i), i))
        for i in order:
            # SHORT axis first. Growing the long axis of an already slender
            # room fails the aspect check, and the check is per-step: a
            # bathroom that could legally regrow to 15x7 was refused at the
            # intermediate 15x6 and stayed 12x6, leaving the notch open.
            x0, y0, x1, y1 = rects[i]
            sides = (("S", "N", "E", "W") if (x1 - x0) >= (y1 - y0)
                     else ("E", "W", "S", "N"))
            for side in sides:
                if grow(i, side):
                    changed = progressed = True
    return progressed


# ---------------------------------------------------------------------------
# phase 4: reclose the outline / phase 5: grow to the plot
# ---------------------------------------------------------------------------

def _relaxed_bounds(bounds, slack):
    """Copy of `bounds` with the SPAN and AREA ceilings widened by `slack`.

    The aspect band (ar_lo/ar_hi) and every floor are copied untouched: the
    reclose may make a room bigger than the rulebook prefers, never more
    slender than the rulebook allows.
    """
    factor = 1.0 + max(0.0, float(slack))
    out = []
    for b in bounds:
        if b is None:
            out.append(None)
            continue
        nb = dict(b)
        for key in ("cap_short", "cap_long", "maxw", "maxh"):
            if nb.get(key, _INF) < _INF:
                nb[key] = nb[key] * factor
        if nb.get("maxarea", _INF) < _INF:
            nb["maxarea"] = nb["maxarea"] * factor
        out.append(nb)
    return out


def _over_ceiling_rooms(rects, bounds, names, eps_ratio=0.02):
    """Names of rooms past their own span or area ceiling."""
    over = []
    for r, b, name in zip(rects, bounds, names):
        if b is None:
            continue
        w, h = r[2] - r[0], r[3] - r[1]
        short, long_ = min(w, h), max(w, h)
        if (long_ > b.get("cap_long", _INF) * (1 + eps_ratio)
                or short > b.get("cap_short", _INF) * (1 + eps_ratio)
                or w * h > b.get("maxarea", _INF) * (1 + eps_ratio)):
            over.append(str(name))
    return sorted(set(over))


def _rectangle_safe_trims(base, bounds, door_reqs, eps, tolerance,
                          allowances, plot_limits, max_rounds=3):
    """Redo the trimming, keeping ONLY the trims the tiling can close again.

    The plain trim pass is greedy: it cuts every over-cap room from an exterior
    side and leaves whatever notch that opens. Most of those notches cannot be
    absorbed (the neighbour that could grow does not span the void), so the
    rectangle-first policy would throw the whole pass away - including the
    trims a neighbour CAN swallow, which are exactly the ones that move slack
    from a bathroom into a living room.

    Each candidate trim is therefore committed only if a capped absorption
    round closes the outline right back to a rectangle. Returns
    (rects, actions).
    """
    work = list(base)
    actions = {}

    def gapless(rects):
        return _void_metrics(rects)[0] <= max(_bbox_area(rects), 1e-9) * 1e-3

    def valid(rects):
        return (not _rects_overlap(rects, eps)
                and _void_metrics(rects)[1] <= eps
                and _doors_ok(rects, door_reqs, eps)
                and _within_limits(rects, plot_limits, eps)
                and all(_aspect_of(r) <= a for r, a in zip(rects, allowances)))

    for _ in range(max_rounds):
        order = sorted(range(len(work)),
                       key=lambda k: -_violation_ratio(work[k], bounds[k]))
        moved = False
        for i in order:
            if bounds[i] is None or _violation_ratio(work[i], bounds[i]) <= tolerance:
                continue
            x0, y0, x1, y1 = work[i]
            w, h = x1 - x0, y1 - y0
            tw, th = _axis_ceilings(bounds[i], w, h)
            for side in ("E", "W", "S", "N"):
                need = (w - tw) if side in ("E", "W") else (h - th)
                if need <= 0 or not _fully_exterior(work, i, side, eps):
                    continue
                allowed = min(need,
                              _door_trim_limit(work, door_reqs, i, side, eps))
                if allowed < 0.05:
                    continue
                trial = list(work)
                if side == "E":
                    trial[i] = (x0, y0, x1 - allowed, y1)
                elif side == "W":
                    trial[i] = (x0 + allowed, y0, x1, y1)
                elif side == "N":
                    trial[i] = (x0, y0 + allowed, x1, y1)
                else:
                    trial[i] = (x0, y0, x1, y1 - allowed)
                trial_actions = copy.deepcopy(actions)
                trial_actions.setdefault(i, []).append(
                    "trimmed %.1f ft from %s" % (allowed, side))
                _absorb_pass(trial, bounds, eps, trial_actions,
                             allowances=allowances)
                if valid(trial) and gapless(trial):
                    work = trial
                    actions = trial_actions
                    moved = True
                    break
        if not moved:
            break
    return work, actions


def _close_notches(work, bounds, door_reqs, eps, opts, actions,
                   allowances, plot_limits, fallback, fallback_actions):
    """Phase 4. Turn a notched outline back into a full rectangle.

    Ladder, cheapest first:
      A. capped absorption (within every ceiling),
      B. one relaxed round inside `notch_close_slack` (aspect band still hard),
      C. revert to `fallback` - the last geometry that WAS a rectangle.

    A and B are all-or-nothing: the geometry is kept only if the plan comes out
    gapless, so a room never trades its ceiling for a partial improvement
    nobody can see. C is what makes the outline outrank the ceilings; the
    rooms it leaves over-cap are named by the caller.

    Returns (closed_by_growth, slack_used, reverted).
    """
    def gapless(rects):
        return _void_metrics(rects)[0] <= max(_bbox_area(rects), 1e-9) * 1e-3

    def valid(rects):
        return (not _rects_overlap(rects, eps)
                and _void_metrics(rects)[1] <= eps
                and _doors_ok(rects, door_reqs, eps)
                and _within_limits(rects, plot_limits, eps))

    if gapless(work):
        return False, False, False
    # tier A: within every ceiling
    snapshot = list(work)
    action_snapshot = copy.deepcopy(actions)
    _absorb_pass(work, bounds, eps, actions, allowances=allowances)
    if valid(work) and gapless(work):
        return True, False, False
    work[:] = snapshot
    actions.clear()
    actions.update(action_snapshot)
    # tier B: ceilings relaxed by the slack, aspect band still hard
    slack = float(opts.get("notch_close_slack") or 0)
    if slack > 0:
        relaxed = _relaxed_bounds(bounds, slack)
        _absorb_pass(work, relaxed, eps, actions, allowances=allowances)
        if valid(work) and gapless(work):
            return True, True, False
        work[:] = snapshot
        actions.clear()
        actions.update(action_snapshot)
    # tier C: redo the trims, keeping only the reclosable ones
    if fallback is None or not gapless(fallback):
        return False, False, False
    safe, safe_actions = _rectangle_safe_trims(
        fallback, bounds, door_reqs, eps, float(opts["tolerance"]),
        allowances, plot_limits)
    work[:] = list(safe)
    actions.clear()
    merged = copy.deepcopy(fallback_actions)
    for i, entries in safe_actions.items():
        merged.setdefault(i, []).extend(entries)
    actions.update(merged)
    return False, False, True


def _bbox_area(rects):
    x0, y0, x1, y1 = _bbox(rects)
    return (x1 - x0) * (y1 - y0)


def _side_growth_limit(rects, bounds, i, side, allowances):
    """How far room i may push `side` outward inside its own ceilings."""
    if bounds[i] is None:
        return _INF
    x0, y0, x1, y1 = rects[i]
    w, h = x1 - x0, y1 - y0
    tw, th = _axis_ceilings(bounds[i], w, h, aspect_floors=False)
    room = (tw - w) if side in ("E", "W") else (th - h)
    if room <= 0:
        return 0.0
    if allowances is not None:
        # binary-search-free check: the grown rect's slenderness must stay
        # inside the allowance, and growth is monotone in the delta.
        if side in ("E", "W"):
            candidate = (x0, y0, x1 + room, y1)
        else:
            candidate = (x0, y0, x1, y1 + room)
        if _aspect_of(candidate) > allowances[i]:
            # shrink the step until it fits (10 halvings is plenty at ft scale)
            step = room
            for _ in range(10):
                step /= 2.0
                trial = ((x0, y0, x1 + step, y1) if side in ("E", "W")
                         else (x0, y0, x1, y1 + step))
                if _aspect_of(trial) <= allowances[i]:
                    return step
            return 0.0
    return room


def _expand_to_target(work, bounds, door_reqs, eps, target,
                      plot_limits, actions, allowances):
    """Phase 5. Grow a gapless plan toward `target` (already oriented).

    A whole boundary side advances at once, by the SMALLEST headroom among the
    rooms on it, so the outline stays a rectangle and no room passes its own
    ceiling. Never shrinks (the min-dim minimums are floors) and never crosses
    the plot cap. Returns the feet gained per axis.
    """
    if target is None:
        return (0.0, 0.0)
    limit_w, limit_h = target
    if plot_limits is not None:
        limit_w = min(limit_w, plot_limits[0])
        limit_h = min(limit_h, plot_limits[1])
    gained_x = gained_y = 0.0
    sides = ("E", "S", "W", "N")
    for _ in range(6):
        moved = False
        for side in sides:
            bx0, by0, bx1, by1 = _bbox(work)
            gap = (limit_w - (bx1 - bx0)) if side in ("E", "W") \
                else (limit_h - (by1 - by0))
            if gap <= 0.05:
                continue
            if side == "E":
                idxs = [i for i, r in enumerate(work) if r[2] >= bx1 - eps]
            elif side == "W":
                idxs = [i for i, r in enumerate(work) if r[0] <= bx0 + eps]
            elif side == "S":
                idxs = [i for i, r in enumerate(work) if r[3] >= by1 - eps]
            else:
                idxs = [i for i, r in enumerate(work) if r[1] <= by0 + eps]
            if not idxs:
                continue
            advance = min([gap] + [_side_growth_limit(work, bounds, i, side,
                                                      allowances)
                                   for i in idxs])
            if advance <= 0.05:
                continue
            snapshot = list(work)
            for i in idxs:
                x0, y0, x1, y1 = work[i]
                if side == "E":
                    work[i] = (x0, y0, x1 + advance, y1)
                elif side == "W":
                    work[i] = (x0 - advance, y0, x1, y1)
                elif side == "S":
                    work[i] = (x0, y0, x1, y1 + advance)
                else:
                    work[i] = (x0, y0 - advance, x1, y1)
            if (_rects_overlap(work, eps) or _void_metrics(work)[0] > eps
                    or not _doors_ok(work, door_reqs, eps)
                    or not _within_limits(work, plot_limits, eps)):
                work[:] = snapshot
                continue
            for i in idxs:
                actions.setdefault(i, []).append(
                    "grew %.1f ft toward %s to fill the plot" % (advance, side))
            if side in ("E", "W"):
                gained_x += advance
            else:
                gained_y += advance
            moved = True
        if not moved:
            break
    return (gained_x, gained_y)


# ---------------------------------------------------------------------------
# the per-plan driver
# ---------------------------------------------------------------------------

def _room_snapshot(rects, names):
    out = []
    for (x0, y0, x1, y1), name in zip(rects, names):
        w, h = x1 - x0, y1 - y0
        out.append({"name": name, "width": round(w, 4), "height": round(h, 4),
                    "area": round(w * h, 4),
                    "aspect": round(max(w, h) / max(min(w, h), 1e-9), 4)})
    return out


def postprocess_plan(rects, names, options=None, edges=None,
                     user_min_w=None, user_min_h=None,
                     user_max_w=None, user_max_h=None,
                     user_min_a=None, user_max_a=None):
    """Post-process one plan. Returns (new_rects, report).

    rects  : [(x0, y0, x1, y1), ...] axis-aligned, non-overlapping, feet.
    names  : room labels, same order (drive the NBC rule lookup).
    edges  : requested adjacencies (doors) as index or name pairs; optional.
    user_* : optional per-room bound lists from the original request.
    """
    opts = _merged_options(options)
    eps = _plan_eps(rects)
    tolerance = float(opts["tolerance"])
    work = [tuple(map(float, r)) for r in rects]
    start = list(work)
    bounds = build_bounds(names, opts, user_min_w, user_min_h,
                          user_max_w, user_max_h,
                          user_min_a, user_max_a)
    door_reqs = build_door_requirements(
        work, names, edges, float(opts["min_door_overlap"]), eps)

    issues_before = nbc_rules.plan_issues(_room_snapshot(work, names),
                                          opts.get("rules"),
                                          aspect_band=opts.get("aspect"))
    score_before = sum(10 if i["severity"] == "error" else 1
                       for i in issues_before)
    bbox_before = _bbox(work)
    actions = {}
    phase_notes = []

    def note(text):
        # A rolled-back phase retried on unchanged geometry produces the
        # identical note; one entry carries the information.
        if not phase_notes or phase_notes[-1] != text:
            phase_notes.append(text)

    # No phase may leave any room more slender than it started or its band
    # allows, and the per-room quality vector may not regress on any
    # component. Both are judged against the ORIGINAL geometry.
    allowances = _aspect_allowances(work, bounds)
    connected_before = _rooms_connected(work, eps)
    vec_before = [_quality_vector(r, b) for r, b in zip(work, bounds)]

    # The plot is the highest-priority constraint: it caps every phase below.
    # A plan that ALREADY overflows the plot (the engine's expand fallback) is
    # not cut down here - trimming it to the cap would break room minimums -
    # so the cap is applied from whichever extent is larger.
    plot_limits = _oriented(_dim_pair(opts, "plot_width", "plot_height"), work)
    if plot_limits is not None:
        plot_limits = (max(plot_limits[0], bbox_before[2] - bbox_before[0]),
                       max(plot_limits[1], bbox_before[3] - bbox_before[1]))
    target = _oriented(_dim_pair(opts, "target_width", "target_height"), work)

    # -- phase 1: in-tile repair (only meaningful on a gapless tiling) -------
    notch0, hole0 = _void_metrics(work)
    bbox_area = (bbox_before[2] - bbox_before[0]) * (bbox_before[3] - bbox_before[1])
    gapless_before = notch0 <= bbox_area * 1e-3
    if opts["repair"] and gapless_before:
        from GPLAN import api as _api   # lazy: api imports this module
        candidate = _api.repair_dimensions([tuple(r) for r in work], bounds)
        growth = 1.0 + float(opts["max_bbox_growth"])
        cand_bbox = _bbox(candidate)
        # The margin exists so NBC floors rebalance the tiling instead of
        # ballooning the footprint. A plot makes that judgement exactly: any
        # extent the PLOT still contains is not a balloon, whatever the margin
        # says, and growing into the plot is what the caller asked for.
        # Judged against the TARGET when the caller sent one, not the plot:
        # generation's plot carries deliberate slack (a rejection cap, 1.6x the
        # footprint on the shipped client), and letting the repair grow into
        # that slack would oversize every plan. With no target the plot is the
        # only rectangle available and stands in for it.
        growth_limits = target if target is not None else plot_limits
        fits_plot = (growth_limits is not None
                     and _within_limits(candidate, growth_limits, eps))
        grew_too_much = (
            ((cand_bbox[2] - cand_bbox[0])
             > (bbox_before[2] - bbox_before[0]) * growth
             or (cand_bbox[3] - cand_bbox[1])
             > (bbox_before[3] - bbox_before[1]) * growth)
            and not fits_plot)
        if grew_too_much:
            note("repair rolled back (would grow the plan"
                 " footprint beyond the allowed margin)")
        elif not _within_limits(candidate, plot_limits, eps):
            note("repair rolled back (would push the plan outside the plot)")
        elif (_rects_overlap(candidate, eps)
                or not _doors_ok(candidate, door_reqs, eps)
                or _void_metrics(candidate)[1] > eps):
            note("repair rolled back (invariant check failed)")
        elif any(_aspect_of(r) > a for r, a in zip(candidate, allowances)):
            # Most measured aspect drift came from this phase, inside the
            # band but away from where the room started; the repair is
            # all-or-nothing, so the whole candidate goes.
            note("repair rolled back (would leave a room more slender"
                 " than it started or its band allows)")
        else:
            for i, (old, new) in enumerate(zip(work, candidate)):
                if any(abs(a - b) > 1e-4 for a, b in zip(old, new)):
                    actions.setdefault(i, []).append("repaired in-tile")
            work = list(candidate)

    # The last state known to be a full rectangle. Phase 4 falls back to it
    # when the trims below cannot be reclosed.
    rect_state = list(work) if gapless_before else None
    rect_actions = copy.deepcopy(actions)

    # -- phases 2+3: trim to ceilings, absorb what is allowed back ----------
    # Both the geometry AND the action log are snapshotted per phase: a
    # rolled-back phase must not leave phantom "trimmed ..." entries claiming
    # changes that never shipped.
    max_notch = float(opts["max_notch_ratio"])
    for _ in range(int(opts["max_passes"])):
        round_start = list(work)
        round_actions = copy.deepcopy(actions)
        if opts["trim"]:
            snapshot = list(work)
            action_snapshot = copy.deepcopy(actions)
            if _trim_pass(work, bounds, names, door_reqs, eps, tolerance,
                          actions, allowances=allowances):
                why = None
                if _rects_overlap(work, eps) \
                        or not _doors_ok(work, door_reqs, eps):
                    why = "door check failed"
                elif _void_metrics(work)[1] > eps:
                    why = "would open an interior hole"
                elif connected_before and not _rooms_connected(work, eps):
                    why = "would disconnect the plan"
                if why is not None:
                    work[:] = snapshot
                    actions.clear()
                    actions.update(action_snapshot)
                    note("trim rolled back (%s)" % why)
        if opts["absorb"]:
            snapshot = list(work)
            action_snapshot = copy.deepcopy(actions)
            if _absorb_pass(work, bounds, eps, actions,
                            allowances=allowances):
                if (_rects_overlap(work, eps)
                        or _void_metrics(work)[1] > eps
                        or not _doors_ok(work, door_reqs, eps)
                        or not _within_limits(work, plot_limits, eps)):
                    work[:] = snapshot
                    actions.clear()
                    actions.update(action_snapshot)
                    note("absorb rolled back (invariant check failed)")
        # The notch budget is judged AFTER absorb: trims transiently open
        # space that absorption is meant to reclaim, and a plan may only
        # keep a round whose residual notches stay buildable.
        r_notch, _ = _void_metrics(work)
        r_bbox = _bbox(work)
        r_area = max((r_bbox[2] - r_bbox[0]) * (r_bbox[3] - r_bbox[1]), 1e-9)
        if r_notch > r_area * max_notch:
            work[:] = round_start
            actions.clear()
            actions.update(round_actions)
            note("round rolled back (notches would exceed %d%% of the plan)"
                 % round(max_notch * 100))
            break
        # Progress is a geometry question, not a bookkeeping one: a round
        # whose phases were all rolled back must stop, or the next round
        # re-attempts the identical doomed work.
        if all(abs(a - b) <= 1e-9
               for r0, r1 in zip(round_start, work)
               for a, b in zip(r0, r1)):
            break

    # -- phase 4: reclose the outline ---------------------------------------
    # Runs BEFORE the quality gate below, unlike phases 1-3 in the first
    # version of this module: the gate is what decides whether the whole
    # sequence was worth shipping, and reverting the trims for the rectangle
    # changes that answer.
    rectangle_restored = False
    reclose_slack_used = False
    trims_reverted = False
    if opts["prefer_rectangle"] and gapless_before:
        rectangle_restored, reclose_slack_used, trims_reverted = \
            _close_notches(work, bounds, door_reqs, eps, opts, actions,
                           allowances, plot_limits, rect_state, rect_actions)
        if rectangle_restored:
            note("outline reclosed to a rectangle"
                 + (" (a room was allowed past its ceiling to do it)"
                    if reclose_slack_used else ""))
        elif trims_reverted:
            over = _over_ceiling_rooms(work, bounds, names)
            note("trims reverted to keep a rectangular outline"
                 + ((" (%s stay past their NBC ceiling)" % ", ".join(over))
                    if over else ""))

    # -- phase 5: fill the plot ---------------------------------------------
    filled = (0.0, 0.0)
    if opts["fill_target"] and target is not None \
            and _void_metrics(work)[0] <= max(_bbox_area(work), 1e-9) * 1e-3:
        filled = _expand_to_target(work, bounds, door_reqs, eps,
                                   target, plot_limits, actions, allowances)
        if filled[0] > 0.05 or filled[1] > 0.05:
            note("grown %.1f x %.1f ft toward the plot within the room"
                 " ceilings" % filled)

    # -- the gate: is the whole sequence worth shipping? ---------------------
    # The promise that outranks all heuristics: post-processing never makes
    # any single room worse on any rulebook dimension, and never makes the
    # plan-wide score worse. The per-room vector is the real gate (a plan
    # total can improve while one room crosses its band); the integer score
    # stays as a tiebreak for what the vector cannot see (area hierarchy).
    # `start` is itself the original rectangle whenever gapless_before, so
    # reverting here never costs the outline.
    issues_after = nbc_rules.plan_issues(_room_snapshot(work, names),
                                         opts.get("rules"),
                                         aspect_band=opts.get("aspect"))
    score_after = sum(10 if i["severity"] == "error" else 1
                      for i in issues_after)
    vec_after = [_quality_vector(r, b) for r, b in zip(work, bounds)]
    regressed = sorted({
        str(names[i]) for i in range(len(names))
        if any((not before) and after
               for before, after in zip(vec_before[i], vec_after[i]))
    })
    if regressed or score_after > score_before:
        work = list(start)
        actions.clear()
        rectangle_restored = False
        trims_reverted = False
        reclose_slack_used = False
        filled = (0.0, 0.0)
        if regressed:
            phase_notes.append(
                "all changes reverted (%s would have regressed on a"
                " rulebook limit)" % ", ".join(regressed))
        else:
            phase_notes.append(
                "all changes reverted (rulebook score would have"
                " worsened %s -> %s)" % (score_before, score_after))
        issues_after = list(issues_before)
        score_after = score_before

    notch_after, hole_after = _void_metrics(work)
    bbox_after = _bbox(work)
    bbox_after_area = max((bbox_after[2] - bbox_after[0])
                          * (bbox_after[3] - bbox_after[1]), 1e-9)

    before_rooms = _room_snapshot(rects, names)
    after_rooms = _room_snapshot(work, names)
    report = {
        "changed": any(actions.values()),
        "score_before": score_before,
        "score_after": score_after,
        "issues_before": issues_before,
        "issues_after": issues_after,
        "gapless_before": gapless_before,
        "gapless_after": notch_after <= bbox_after_area * 1e-3,
        "notch_area": round(notch_after, 2),
        "notch_ratio": round(notch_after / bbox_after_area, 4),
        "interior_hole_area": round(hole_after, 2),
        "doors_preserved": _doors_ok(work, door_reqs, eps),
        "rectangle_restored": rectangle_restored,
        "trims_reverted_for_rectangle": trims_reverted,
        "over_ceiling_rooms": (_over_ceiling_rooms(work, bounds, names)
                               if reclose_slack_used or trims_reverted else []),
        "plot_fit": _within_limits(work, plot_limits, eps),
        "filled_toward_plot": [round(filled[0], 2), round(filled[1], 2)],
        "extent_before": [round(bbox_before[2] - bbox_before[0], 2),
                          round(bbox_before[3] - bbox_before[1], 2)],
        "extent_after": [round(bbox_after[2] - bbox_after[0], 2),
                         round(bbox_after[3] - bbox_after[1], 2)],
        "phase_notes": phase_notes,
        "rooms": [
            {"name": names[i], "before": before_rooms[i],
             "after": after_rooms[i], "actions": actions.get(i, [])}
            for i in range(len(names))
        ],
    }
    return work, report


# ---------------------------------------------------------------------------
# adapters
# ---------------------------------------------------------------------------

def _polyline_rect(poly, eps):
    """(x0, y0, x1, y1) if the polyline is an axis-aligned rectangle, else None
    (same shoelace-equals-bbox test as api._polyline_rect)."""
    xs = [pt[0] for pt in poly]
    ys = [pt[1] for pt in poly]
    if not xs:
        return None
    x0, x1, y0, y1 = min(xs), max(xs), min(ys), max(ys)
    area2 = 0.0
    n = len(poly)
    for i in range(n):
        ax, ay = poly[i][0], poly[i][1]
        bx, by = poly[(i + 1) % n][0], poly[(i + 1) % n][1]
        area2 += ax * by - bx * ay
    if abs(abs(area2) / 2 - (x1 - x0) * (y1 - y0)) > eps:
        return None
    return (x0, y0, x1, y1)


def _summary_line(reports):
    changed = sum(1 for r in reports if r and r.get("changed"))
    total = sum(1 for r in reports if r is not None)
    skipped = sum(1 for r in reports if r is None)
    if total == 0 and skipped == 0:
        return ""
    line = (" Post-processing adjusted %d of %d floorplans toward NBC room"
            " limits and aspect bands." % (changed, total))
    notched = sum(1 for r in reports
                  if r and r.get("gapless_before")
                  and not r.get("gapless_after"))
    if notched:
        line += (" %d floorplan(s) kept boundary notches: the outline could"
                 " not be reclosed inside the room limits." % notched)
    else:
        line += " Every outline stayed a full rectangle."
    filled = sum(1 for r in reports
                 if r and any(v > 0.05
                              for v in (r.get("filled_toward_plot") or [0, 0])))
    if filled:
        line += " %d were grown toward the plot." % filled
    if skipped:
        line += (" %d floorplan(s) with non-rectangular rooms were left"
                 " untouched." % skipped)
    return line


def postprocess_ui_output(ui, nodes_list, edges_list, options, plan_count,
                          plan_validator=None):
    """Engine-internal adapter: rewrite the first `plan_count` plans held on
    `ui` (final_traversal / room_width / room_height / area / name_coords).

    Room order in final_traversal is node order (dummy rooms already merged
    away), so `edges_list` index pairs address rooms directly. Returns
    (reports, summary_note).

    `plan_validator(plan) -> bool`, when given, re-checks a mutated plan
    against caller-side guarantees (e.g. cardinal pins, which are verified
    BEFORE this runs and could be broken by a room growing into the strip
    between a pinned room and its side). A plan that fails validation is
    restored to its pre-processing geometry and reported unchanged.
    """
    plans = ui.get_output_data()
    names = [node["label"] for node in nodes_list]
    door_edges = [(int(e[0]), int(e[1])) for e in edges_list
                  if e is not None and len(e) >= 2
                  and str(e[2] if len(e) > 2 else "black").lower() != "red"]
    params = getattr(ui, "min_dim_inputs", None)

    def col(getter):
        if params is None:
            return None
        try:
            return getter() or None
        except Exception:
            return None

    user_min_w = col(lambda: params.get_min_width())
    user_min_h = col(lambda: params.get_min_height())
    user_max_w = col(lambda: params.get_max_width())
    user_max_h = col(lambda: params.get_max_height())
    user_min_a = col(lambda: params.get_min_area()
                     if hasattr(params, "get_min_area") else None)
    user_max_a = col(lambda: params.get_max_area()
                     if hasattr(params, "get_max_area") else None)

    # The plot the request already carries is the default hard cap, so a caller
    # gets plot-aware post-processing without sending it twice. An explicit
    # postprocess_options value still wins (the request's plot is a deliberately
    # slack REJECTION cap on this path; a client that knows the real footprint
    # sends it as target_width/target_height).
    options = dict(options or {})
    for key, getter in (("plot_width", "get_plot_width"),
                        ("plot_height", "get_plot_height")):
        if options.get(key) is None:
            value = col(lambda g=getter: getattr(params, g)())
            if value:
                options[key] = value

    reports = []
    for index in range(min(plan_count, len(plans))):
        plan = plans[index]
        polys = getattr(plan, "final_traversal", None) or []
        if len(polys) != len(names):
            reports.append(None)
            continue
        span_eps = _plan_eps([(min(p[0] for p in poly), min(p[1] for p in poly),
                               max(p[0] for p in poly), max(p[1] for p in poly))
                              for poly in polys])
        rects = []
        for poly in polys:
            rect = _polyline_rect(poly, span_eps * 10)
            if rect is None:
                rects = None
                break
            rects.append(rect)
        if rects is None or _rects_overlap(rects, span_eps):
            reports.append(None)
            continue
        new_rects, report = postprocess_plan(
            rects, names, options, edges=door_edges,
            user_min_w=user_min_w, user_min_h=user_min_h,
            user_max_w=user_max_w, user_max_h=user_max_h,
            user_min_a=user_min_a, user_max_a=user_max_a)
        if report["changed"]:
            saved = (plan.final_traversal, plan.room_width, plan.room_height,
                     plan.area,
                     copy.deepcopy(getattr(plan, "name_coords", None)))
            plan.final_traversal = [
                [[x0, y0], [x1, y0], [x1, y1], [x0, y1]]
                for (x0, y0, x1, y1) in new_rects
            ]
            plan.room_width = [r[2] - r[0] for r in new_rects]
            plan.room_height = [r[3] - r[1] for r in new_rects]
            plan.area = [(r[2] - r[0]) * (r[3] - r[1]) for r in new_rects]
            if getattr(plan, "name_coords", None):
                for k, (x0, y0, x1, y1) in enumerate(new_rects):
                    if k < len(plan.name_coords):
                        plan.name_coords[k] = [(x0 + x1) / 2, (y0 + y1) / 2]
            if plan_validator is not None and not plan_validator(plan):
                (plan.final_traversal, plan.room_width, plan.room_height,
                 plan.area, saved_coords) = saved
                if saved_coords is not None:
                    plan.name_coords = saved_coords
                report = dict(report)
                report["changed"] = False
                report["phase_notes"] = list(report.get("phase_notes", [])) + [
                    "all changes reverted (would break a verified cardinal pin)"]
                report["issues_after"] = report["issues_before"]
                report["score_after"] = report["score_before"]
        reports.append(report)
    return reports, _summary_line(reports)


def postprocess_serialized_plans(floorplans, options=None, edges=None):
    """JSON adapter for the standalone endpoint: takes the documented
    `floorPlans` array (each plan a list of Room dicts with walls /
    circular_coordinates), returns (new_floorplans, reports, summary).

    Rooms keep their name/original_name/color; geometry fields (walls,
    circular_coordinates, label_coord, width, height, area) are rewritten.
    Plans containing non-rectangular (merged, L-shaped) rooms pass through
    untouched with a null report entry.
    """
    import uuid as _uuid

    new_plans = []
    reports = []
    for plan in floorplans or []:
        rects = []
        names = []
        for room in plan:
            if not isinstance(room, dict):
                rects = None
                break
            rect = None
            poly = room.get("circular_coordinates")
            if poly:
                span = max(max(pt[0] for pt in poly) - min(pt[0] for pt in poly),
                           max(pt[1] for pt in poly) - min(pt[1] for pt in poly),
                           1e-6)
                rect = _polyline_rect(poly, span * 1e-3)
            else:
                xs, ys = [], []
                for wall in room.get("walls", []) or []:
                    xs += [wall["x1"], wall["x2"]]
                    ys += [wall["y1"], wall["y2"]]
                if xs:
                    rect = (min(xs), min(ys), max(xs), max(ys))
            if rect is None:
                # non-rectangular (merged L-shape) or no geometry at all -
                # this plan passes through untouched
                rects = None
                break
            rects.append(rect)
            names.append(room.get("original_name") or room.get("name") or "")
        if rects is None or not rects or _rects_overlap(rects, _plan_eps(rects)):
            new_plans.append(plan)
            reports.append(None)
            continue
        new_rects, report = postprocess_plan(rects, names, options, edges=edges)
        if not report["changed"]:
            # keep the original dicts byte-for-byte (wall _ids included)
            new_plans.append(plan)
            reports.append(report)
            continue
        rebuilt = []
        for room, (x0, y0, x1, y1) in zip(plan, new_rects):
            corners = [(x0, y0), (x1, y0), (x1, y1), (x0, y1)]
            walls = []
            for k in range(4):
                ax, ay = corners[k]
                bx, by = corners[(k + 1) % 4]
                walls.append({"_id": str(_uuid.uuid4()), "x1": ax, "y1": ay,
                              "x2": bx, "y2": by, "assets": []})
            new_room = dict(room)
            new_room["walls"] = walls
            new_room["circular_coordinates"] = [list(c) for c in corners]
            new_room["label_coord"] = [(x0 + x1) / 2, (y0 + y1) / 2]
            new_room["width"] = x1 - x0
            new_room["height"] = y1 - y0
            new_room["area"] = (x1 - x0) * (y1 - y0)
            rebuilt.append(new_room)
        new_plans.append(rebuilt)
        reports.append(report)
    return new_plans, reports, _summary_line(reports)
