"""NBC 2016 room rulebook, mirrored from the designer frontend.

Source of truth for the values:
gplan-building-designer/src/constants/nbcRules.ts (NBC_RULES, ROOM_FALLBACK,
AREA_ORDERING, planIssues). Keep the two in sync: a change here without the
frontend, or vice versa, makes the server post-process to one standard and the
client score to another.

All lengths are FEET, all areas SQUARE FEET, matching the engine units the
designer flow uses. maxAspect is a slenderness cap: long side / short side.
"""

_INF = float("inf")

# Rooms that must never be outgrown by wet/service space, whatever the unit size.
HABITABLE_ROOMS = ["Kitchen", "Dining", "Living Room", "Bedroom",
                   "Master Bedroom", "Study"]

NBC_RULES = {
    "Living Room": {
        "room_class": "social",
        "min_area": 115, "max_area": 420,
        "min_width": 10, "min_height": 11.5,
        "max_width": 22, "max_height": 24,
        "max_aspect": 2.2,
    },
    "Dining": {
        "room_class": "social",
        "min_area": 90, "max_area": 210,
        "min_width": 9, "min_height": 10,
        "max_width": 16, "max_height": 16,
        "max_aspect": 2.0,
    },
    "Kitchen": {
        "room_class": "service",
        "min_area": 56, "max_area": 110,
        "min_width": 7, "min_height": 8,
        "max_width": 12, "max_height": 13,
        "max_aspect": 2.4,
    },
    "Master Bedroom": {
        "room_class": "private",
        "min_area": 110, "max_area": 260,
        "min_width": 10, "min_height": 11,
        "max_width": 16, "max_height": 18,
        "max_aspect": 1.8,
    },
    "Bedroom": {
        "room_class": "private",
        "min_area": 110, "max_area": 190,
        "min_width": 10, "min_height": 11,
        "max_width": 14, "max_height": 16,
        "max_aspect": 1.8,
    },
    "Study": {
        "room_class": "private",
        "min_area": 56, "max_area": 120,
        "min_width": 7, "min_height": 8,
        "max_width": 12, "max_height": 13,
        "max_aspect": 2.0,
    },
    "Bathroom": {
        "room_class": "wet",
        "min_area": 35, "max_area": 68,
        "min_width": 5, "min_height": 7,
        "max_width": 8, "max_height": 10,
        "max_aspect": 2.0,
    },
    "Toilet": {
        "room_class": "wet",
        "min_area": 18, "max_area": 34,
        "min_width": 3.5, "min_height": 5,
        "max_width": 6, "max_height": 8,
        "max_aspect": 2.2,
    },
    "Utility": {
        "room_class": "service",
        "min_area": 24, "max_area": 52,
        "min_width": 4, "min_height": 6,
        "max_width": 6, "max_height": 9,
        "max_aspect": 2.4,
    },
    "Store": {
        "room_class": "service",
        "min_area": 20, "max_area": 44,
        "min_width": 4, "min_height": 5,
        "max_width": 6, "max_height": 8,
        "max_aspect": 2.4,
    },
    "Pooja": {
        "room_class": "service",
        "min_area": 12, "max_area": 28,
        "min_width": 3, "min_height": 4,
        "max_width": 5, "max_height": 6,
        "max_aspect": 2.0,
    },
    "Balcony": {
        "room_class": "open",
        "min_area": 20, "max_area": 84,
        "min_width": 4, "min_height": 5,
        "max_width": 7, "max_height": 14,
        "max_aspect": 3.5,
    },
}

# Fallback for room types with no rule (user-created types). No min/max area
# is enforced for unknown types (mirrors planIssues, which skips them); the
# postprocessor still uses the aspect cap and span ceiling to stop a custom
# room from becoming a corridor.
ROOM_FALLBACK = {
    "room_class": "service",
    "min_area": 0, "max_area": _INF,
    "min_width": 6, "min_height": 8,
    "max_width": 18, "max_height": 18,
    "max_aspect": 3.0,
}

# The engine's room labels are free text ("Bath", "WC", "Master", numeric
# door_connectivity aliases with original_name carrying the label). Map the
# common spellings onto rulebook keys; exact matches win first.
_NAME_ALIASES = {
    "living": "Living Room", "living room": "Living Room", "hall": "Living Room",
    "drawing room": "Living Room", "lounge": "Living Room",
    "dining": "Dining", "dining room": "Dining",
    "kitchen": "Kitchen", "kitchenette": "Kitchen",
    "master bedroom": "Master Bedroom", "master": "Master Bedroom",
    "mbr": "Master Bedroom", "master bed": "Master Bedroom",
    "bedroom": "Bedroom", "bed": "Bedroom", "bed room": "Bedroom",
    "guest bedroom": "Bedroom", "kids bedroom": "Bedroom",
    "study": "Study", "office": "Study", "home office": "Study",
    "bathroom": "Bathroom", "bath": "Bathroom", "washroom": "Bathroom",
    "toilet": "Toilet", "wc": "Toilet", "water closet": "Toilet",
    "powder room": "Toilet",
    "utility": "Utility", "laundry": "Utility",
    "store": "Store", "storage": "Store", "store room": "Store",
    "pooja": "Pooja", "puja": "Pooja", "pooja room": "Pooja",
    # NOTE: "terrace"/"deck" are deliberately NOT aliased to Balcony - a
    # terrace legitimately exceeds balcony ceilings, and aliasing it would
    # actively trim it. Unknown types get the permissive fallback instead.
    "balcony": "Balcony",
}


def base_room_name(name):
    """'Bedroom 2' -> 'Bedroom'. Instance names carry a numeric suffix."""
    if not isinstance(name, str):
        return ""
    base = name.strip()
    parts = base.rsplit(None, 1)
    if len(parts) == 2 and parts[1].isdigit():
        base = parts[0]
    return base


def canonical_name(name):
    """Rulebook key for a room label ("Bath 2" -> "Bathroom"), or the bare
    base name when no rule matches. Drives rule lookup AND the AREA_ORDERING
    hierarchy, so an alias-resolved room is never exempt from either."""
    base = base_room_name(name)
    if base in NBC_RULES:
        return base
    alias = _NAME_ALIASES.get(base.lower())
    if alias:
        return alias
    # tolerate suffixes the digit-strip missed ("Bathroom2", "bath-2")
    low = base.lower().rstrip("0123456789 -_").strip()
    alias = _NAME_ALIASES.get(low)
    if alias:
        return alias
    return base


def rule_for(name, overrides=None):
    """Rulebook entry for a room label, or None for unknown types.

    `overrides` is an optional {name: {field: value}} patch (per-request rule
    tuning); patched fields are merged over the base rule. Overrides are
    looked up by canonical rulebook key first, then by the literal base name,
    so {"Bathroom": ...} also applies to a room labelled "Bath 2".
    """
    canonical = canonical_name(name)
    rule = NBC_RULES.get(canonical)
    if rule is not None and overrides:
        patch = overrides.get(canonical) or overrides.get(base_room_name(name))
        if patch:
            rule = dict(rule)
            rule.update({k: v for k, v in patch.items() if v is not None})
    return rule


def rule_or_fallback(name, overrides=None):
    rule = rule_for(name, overrides)
    return rule if rule is not None else dict(ROOM_FALLBACK)


# (smaller, larger, severity, strict). `strict` means the smaller room must be
# strictly smaller; otherwise only exceeding is flagged.
AREA_ORDERING = (
    [(small, big, "error", True)
     for small in ("Toilet", "Bathroom", "Utility", "Store", "Pooja")
     for big in HABITABLE_ROOMS]
    + [
        ("Balcony", "Living Room", "error", True),
        ("Balcony", "Master Bedroom", "warning", False),
        ("Balcony", "Bedroom", "warning", False),
        ("Kitchen", "Living Room", "error", True),
        ("Dining", "Living Room", "warning", False),
        ("Bedroom", "Master Bedroom", "warning", False),
    ]
)


def _band_slender_limit(aspect_band):
    """Slenderness cap implied by a caller {"min", "max"} w/h band, or None.

    The band straddles 1, so its worst legal slenderness is the larger of
    max and 1/min. Post-processing accepts such a band as an option and works
    toward it; without this, an issue check judging only the room type's own
    limit scores that work neutral-or-worse.
    """
    if not isinstance(aspect_band, dict):
        return None
    try:
        hi = float(aspect_band.get("max") or 0)
        lo = float(aspect_band.get("min") or 0)
    except (TypeError, ValueError):
        return None
    limit = None
    if hi > 0:
        limit = hi
    if 0 < lo < 1:
        limit = max(limit if limit is not None else 0.0, 1.0 / lo)
    return limit


def plan_issues(rooms, overrides=None, aspect_band=None):
    """Rulebook check of one plan. `rooms` = [{"name", "width", "height"}, ...].

    Port of nbcRules.ts planIssues: per-room min/max area, min short side,
    max span, and slenderness, then the cross-room area hierarchy. Returns a
    list of {"severity", "room", "rule", "message"} dicts; severity "error" |
    "warning". `aspect_band` is an optional caller {"min", "max"} w/h band
    that tightens (never loosens) each room type's own slenderness limit.
    """
    issues = []
    band_limit = _band_slender_limit(aspect_band)

    def r1(v):
        # Math.round semantics (half away from zero for positives), NOT
        # Python's banker's rounding - keeps messages identical to the
        # frontend's for the same numbers.
        import math
        return math.floor(v * 10 + 0.5) / 10

    for room in rooms:
        rule = rule_for(room["name"], overrides)
        if rule is None:
            continue
        w, h = float(room["width"]), float(room["height"])
        a = w * h
        short, long_ = min(w, h), max(w, h)
        if a < rule["min_area"] * 0.98:
            issues.append({"severity": "error", "room": room["name"],
                           "rule": "min_area",
                           "message": "%s is %s sqft, below the %s sqft minimum."
                                      % (room["name"], r1(a), rule["min_area"])})
        if a > rule["max_area"] * 1.02:
            issues.append({"severity": "warning", "room": room["name"],
                           "rule": "max_area",
                           "message": "%s is %s sqft, above the %s sqft practical"
                                      " maximum for its type."
                                      % (room["name"], r1(a), rule["max_area"])})
        min_short = min(rule["min_width"], rule["min_height"])
        if short < min_short * 0.98:
            issues.append({"severity": "error", "room": room["name"],
                           "rule": "min_width",
                           "message": "%s is %s ft on its short side, below the"
                                      " %s ft minimum width."
                                      % (room["name"], r1(short), min_short)})
        # Span ceilings, orientation-agnostic like the trim path's
        # (cap_short, cap_long). Without this a trim done purely to satisfy
        # a span cap earns zero credit and can only be reverted.
        cap_long = max(rule["max_width"], rule["max_height"])
        cap_short = min(rule["max_width"], rule["max_height"])
        if long_ > cap_long * 1.02:
            issues.append({"severity": "warning", "room": room["name"],
                           "rule": "max_width",
                           "message": "%s is %s ft on its long side, above the"
                                      " %s ft maximum for its type."
                                      % (room["name"], r1(long_), cap_long)})
        elif short > cap_short * 1.02:
            issues.append({"severity": "warning", "room": room["name"],
                           "rule": "max_width",
                           "message": "%s is %s ft on its short side, above the"
                                      " %s ft maximum for its type."
                                      % (room["name"], r1(short), cap_short)})
        max_aspect = rule["max_aspect"]
        if band_limit is not None:
            max_aspect = min(max_aspect, band_limit)
        if short > 0 and long_ / short > max_aspect * 1.02:
            # Past 10% over the slenderness limit it is a corridor, not a room.
            issues.append({
                "severity": "error" if long_ / short > max_aspect * 1.1
                else "warning",
                "room": room["name"], "rule": "aspect",
                "message": "%s is %s:1, more slender than the %s:1 limit for"
                           " its type." % (room["name"], r1(long_ / short),
                                           max_aspect),
            })

    def area_of(base):
        # canonical, not literal: "Bath 2" must participate in the Bathroom
        # orderings, or alias-resolved rooms silently escape the hierarchy
        return [(room, float(room["width"]) * float(room["height"]))
                for room in rooms if canonical_name(room["name"]) == base]

    for smaller, larger, severity, strict in AREA_ORDERING:
        for s_room, s_area in area_of(smaller):
            for l_room, l_area in area_of(larger):
                broken = s_area >= l_area if strict else s_area > l_area
                if not broken:
                    continue
                issues.append({"severity": severity, "room": s_room["name"],
                               "rule": "hierarchy",
                               "message": "%s (%s sqft) is %s %s (%s sqft)."
                               % (s_room["name"], r1(s_area),
                                  "not smaller than" if strict else "larger than",
                                  l_room["name"], r1(l_area))})
    return issues


def plan_sanity_score(rooms, overrides=None, aspect_band=None):
    """Lower is better. Errors dominate warnings; ties keep the input order."""
    return sum(10 if issue["severity"] == "error" else 1
               for issue in plan_issues(rooms, overrides, aspect_band))
