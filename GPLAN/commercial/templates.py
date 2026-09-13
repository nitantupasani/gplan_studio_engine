"""Furniture-backed planning modules; no NEN/construction certification implied."""

import math

from .models import EPS, polygon, rect

AISLE = 1.2
PARTITION = 0.12
EXTERIOR = 0.25


def item(kind, x, y, width, height, capacity=0):
    return {"kind": kind, "rect": rect(x, y, width, height), "capacity": capacity}


def fit_template(room, width, spacious=False):
    """Return clear rectangle and explicit equipment at origin; door at x=width.

    All furniture stays left of a 1.2 m internal access aisle. The transverse
    front aisle is also 1.2 m. The generator may mirror the module for a right
    wing; clearances are part of the room area, not the shared corridor.
    """
    role, capacity = room["role"], room["required_capacity"]
    furniture, aisles = [], []
    depth = 0
    if role in {"open_office", "private_office", "focus"}:
        columns = math.floor((width - AISLE + EPS) / 1.8)
        if columns < 1 or capacity < 1:
            return None
        rows = math.ceil(capacity / columns)
        depth = AISLE + rows * 2.7
        for n in range(capacity):
            x, y = (n % columns) * 1.8 + 0.1, AISLE + (n // columns) * 2.7
            furniture += [item("desk", x, y, 1.6, .8, 1), item("chair", x + .5, y + .85, .6, .6)]
        for row in range(rows):
            aisles.append(rect(0, AISLE + row * 2.7 + 1.5, width, AISLE))
    elif role in {"meeting", "lunch"}:
        if width < 4.2 - EPS or capacity < 1:
            return None
        # A continuous conference table has two lines of chairs and real access
        # on both sides; a larger lunch brief uses the same generous seated fit.
        per_side = math.ceil(capacity / 2)
        length = max(1.6, per_side * .7)
        depth = 2 * AISLE + length
        if width + EPS >= length + 2 * AISLE and depth > 4.8:
            # A wide room can carry the same real table/chair schedule across
            # the wing. Keep front, back and corridor-side aisles clear; rotating
            # furniture without those approach reservations is not acceptance.
            depth = 4.8
            furniture.append(item("meeting_table" if role == "meeting" else "lunch_table", AISLE, 1.8, length, 1.2))
            for n in range(capacity):
                side, seat = n % 2, n // 2
                furniture.append(item("meeting_chair" if role == "meeting" else "lunch_chair",
                                      AISLE + seat * .7 + .05, 1.2 if side == 0 else 3.05, .6, .55, 1))
            furniture.append(item("wheelchair_position", .05, 1.8, 1.1, .9))
            aisles.append(rect(0, 3.6, width, AISLE))
        else:
            furniture.append(item("meeting_table" if role == "meeting" else "lunch_table", 1.2, AISLE, 1.2, length))
            for n in range(capacity):
                side, seat = n % 2, n // 2
                furniture.append(item("meeting_chair" if role == "meeting" else "lunch_chair",
                                      .6 if side == 0 else 2.4, AISLE + seat * .7 + .05, .55, .6, 1))
            furniture.append(item("wheelchair_position", 1.2, .05, .9, 1.1))
        aisles.append(rect(width - AISLE, 0, AISLE, depth))
    elif role == "accessible_wc":
        if width < 3.0 - EPS:
            return None
        depth = 2.8
        furniture += [item("wc_fixture", .25, 1.75, .7, .8, 1),
                      item("handwash", .1, 1.25, .55, .45),
                      item("wheelchair_turning", width - 1.65, 1.0, 1.5, 1.5),
                      item("transfer_clearance", .95, 1.7, .9, .9)]
    elif role == "wc":
        if width < 2.7 - EPS:
            return None
        count = max(1, capacity)
        columns = max(1, math.floor((width - AISLE + EPS) / 1.8)) if count > 1 else 1
        rows = math.ceil(count / columns)
        pitch = 2.7 if count > 1 else 1.8
        depth = AISLE + rows * pitch
        for n in range(count):
            x, y = (n % columns) * 1.8, AISLE + (n // columns) * pitch
            furniture += [item("wc_fixture", x + .3, y + .6, .7, .8, 1),
                          item("handwash", x + 1.05, y + .3, .4, .45)]
        if count > 1:
            for row in range(rows):
                aisles.append(rect(0, AISLE + row * pitch + 1.5, width, AISLE))
    elif role == "pantry":
        if width < 3.0 - EPS:
            return None
        cooking = room.get("equipment") == "cooking"
        depth = 4.2 if cooking else 2.7
        furniture += [item("worktop", .1, AISLE, min(2.4, width - AISLE - .1), .6),
                      item("sink", .2, AISLE + .05, .5, .45)]
        if cooking:
            furniture.append(item("cooking_equipment", .1, 2.4, 1.2, .6))
    elif role == "reception":
        if width < 3.0 - EPS:
            return None
        columns = max(1, math.floor((width - AISLE) / .8))
        rows = math.ceil(capacity / columns)
        depth = max(2.7, 2.4 + rows * 1.8)
        furniture.append(item("reception_desk", .1, AISLE, min(1.6, width - AISLE - .1), .6))
        for n in range(capacity):
            furniture.append(item("reception_chair", .1 + (n % columns) * .8, 2.4 + (n // columns) * 1.8, .55, .6, 1))
        for row in range(rows):
            aisles.append(rect(0, 3.0 + row * 1.8, width, AISLE))
    elif role == "rest":
        if width < 3.2 - EPS:
            return None
        depth = 3.4
        furniture.append(item("rest_bed", .1, AISLE, 1.9, .8, max(1, capacity)))
    elif role == "shower":
        if width < 2.7 - EPS:
            return None
        depth = 3.0
        furniture.append(item("shower_tray", .1, AISLE, 1.2, 1.2, max(1, capacity)))
    else:
        if width < 2.5 - EPS:
            return None
        depth = 2.7
        furniture.append(item("reception_desk" if role == "reception" else "storage_cabinet",
                              .1, AISLE, min(1.8, width - AISLE - .1), .6, capacity))
    min_area = room["min_area_m2"]
    if spacious:
        min_area = max(min_area, room["preferred_area_m2"])
    depth = max(depth, min_area / width)
    aisles.extend([rect(width - AISLE, 0, AISLE, depth), rect(0, 0, width, AISLE)])
    return {"width": width, "depth": depth, "furniture": furniture, "aisles": aisles,
            "template_id": f"office-{role}-2026-09-11", "door_y": .6}


def stair_template(height, clear_width=1.2):
    risers = math.ceil(height / .18)
    if risers % 2:
        risers += 1
    per_flight = risers // 2
    landing = max(1.5, clear_width)
    run = (per_flight - 1) * .28
    width = 2 * clear_width + .2 + .4
    depth = 2 * landing + run + .4
    return {"width": width, "depth": depth, "flight_width_m": clear_width,
            "riser_count": risers, "riser_height_m": height / risers, "going_m": .28,
            "landing_depth_m": landing, "floor_height_m": height, "headroom_m": 2.1,
            "slab_thickness_m": .25, "enclosure_thickness_m": .2,
            "flights": [rect(.2, .2 + landing, clear_width, run),
                        rect(.4 + clear_width, .2 + landing, clear_width, run)],
            "landings": [rect(.2, .2, width - .4, landing),
                         rect(.2, .2 + landing + run, width - .4, landing)],
            "void": rect(.2, .2 + landing, width - .4, run),
            "climbing_line_length_m": 2 * math.hypot(run, height / 2) + 2 * landing,
            "template_status": "planning_geometry_requires_construction_review"}
