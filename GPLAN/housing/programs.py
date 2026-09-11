"""Explicit NL concept assumptions; no NBC names or legacy downgrade rules.

Bands use the building footprint, not plot or summed house area. Numerical
values are design assumptions for concept search, not Dutch legal certification.
"""
from copy import deepcopy
import hashlib
import json


def _rule(w, d, area, max_w=14000, max_d=16000, max_area=150):
    return {"min_width_mm": w, "min_depth_mm": d, "min_area_m2": area,
            "max_width_mm": max_w, "max_depth_mm": max_d, "max_area_m2": max_area}


NL_CONCEPT_PROFILE = {
    "id": "NL_concept_v1", "version": 1, "region": "NL", "status": "concept_design_assumptions",
    "band_basis": "building_footprint_area_m2", "measurement_basis": "finished_wall_faces",
    "regular_floor_height_mm": 3000, "minimum_door_width_mm": 850, "door_jamb_mm": 100,
    "minimum_arrival_headroom_mm": 2100, "occupied_headroom_mm": 2100,
    "room_rules": {
        "entrance": _rule(1000, 1300, 2.0, 4000, 7000, 20),
        "stair": _rule(1700, 2700, 4.5, 3000, 5000, 15),
        "wc": _rule(900, 1200, 1.15, 2400, 3000, 5),
        "living": _rule(2500, 2500, 14.0, max_area=85),
        "kitchen": _rule(2200, 2200, 7.0, max_area=55),
        "landing": _rule(1000, 1000, 1.3, max_area=30),
        "bedroom": _rule(2400, 2500, 7.5, max_area=50),
        "bathroom_wc": _rule(1700, 2000, 3.7, 4000, 7000, 20),
        "bathroom": _rule(1700, 1800, 3.2, 4000, 7000, 20),
        "utility": _rule(1700, 1800, 3.0, max_area=50),
        "study": _rule(2300, 2400, 6.0, max_area=60),
        "attic_landing": _rule(1000, 1000, 1.3, max_area=30),
        "hobby": _rule(2000, 2000, 6.0, max_area=140),
        "eaves_storage": _rule(200, 200, 0.1, max_area=90),
    },
    "assumptions": [
        "Concept dimensional profile; regulation, structure, fire and daylight calculations are not certified.",
        "One rectangular detached plot; public frontage assumed to permit the illustrated access.",
        "Front bay access is geometrically reserved; swept vehicle manoeuvres and road permission are not assessed.",
        "Gable attic area is estimated from roof headroom; it is not a NEN measured usable area.",
    ],
}


def get_profile(name="NL_concept_v1"):
    if name != NL_CONCEPT_PROFILE["id"]:
        raise ValueError(f"Unsupported programme profile {name}.")
    return deepcopy(NL_CONCEPT_PROFILE)


def profile_fingerprint(profile=None):
    return hashlib.sha256(json.dumps(profile or NL_CONCEPT_PROFILE, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def program_id(role, footprint_area_m2, variant="standard"):
    band = "under60m2" if footprint_area_m2 < 60 else "60to100m2" if footprint_area_m2 < 100 else "100m2plus"
    return f"{role}floor_NL_{band}_{variant}_v1"


ROOM_KINDS = {"living": "living", "kitchen": "kitchen", "bedroom": "bedroom", "bathroom_wc": "bath", "bathroom": "bath", "wc": "bath", "utility": "utility", "study": "study", "hobby": "study"}
ROOM_NAMES = {"entrance": "Entrance hall", "stair": "Staircase", "wc": "WC", "living": "Living / dining", "kitchen": "Kitchen / dining", "landing": "Landing", "bedroom": "Bedroom", "bathroom_wc": "Bathroom + WC", "bathroom": "Bathroom", "utility": "Laundry / utility", "study": "Study / playroom", "attic_landing": "Attic landing", "hobby": "Attic hobby space", "eaves_storage": "Low eaves storage"}
