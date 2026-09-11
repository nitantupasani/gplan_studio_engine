"""The sole registry of supported headless circulation algorithms."""

from copy import deepcopy
from .models import MAX_BODY_BYTES, MAX_ROOMS, MAX_OPENINGS

ALGORITHMS = {
    "existing": {"id": "existing", "version": "1.0.0", "label": "Existing landing/circulation",
                 "objective": "validate and reuse explicitly designated existing public circulation without editing rooms or openings",
                 "optimality": "not_optimized", "coverage": ["all", "selected"],
                 "method": "existing clear-floor geometry and saved doorway access; no room allocation or route search"},
    "spanning": {"id": "spanning", "version": "1.0.0", "label": "Spanning circulation",
                 "objective": "entry-rooted traversal covering required rooms", "optimality": "heuristic",
                 "coverage": ["all", "selected"], "method": "deterministic breadth-first wall-group traversal"},
    "compact": {"id": "compact", "version": "1.0.0", "label": "Compact circulation",
                "objective": "reduce total activated wall-group length while retaining connected coverage", "optimality": "heuristic",
                "coverage": ["all", "selected"], "method": "connected incremental shortest attachments and connected pruning"},
    "shortest": {"id": "shortest", "version": "1.0.0", "label": "Shortest route",
                 "objective": "minimum sum of activated full wall-group lengths from entry to one destination", "optimality": "exact_fixed_wall_graph",
                 "coverage": ["single_destination"], "method": "Dijkstra on positive node-weighted fixed wall-group graph"},
}


def get_capabilities():
    return {"schema_version": "1.0", "engine": "rectangular-boundary-shift", "engine_version": "1.0.0",
            "modes": deepcopy(list(ALGORITHMS.values())), "units": ["ft", "m"],
            "contribution_policies": [
                {"id": "area", "label": "Larger rooms contribute more", "default": True},
                {"id": "surplus", "label": "Share available area above minimum"},
                {"id": "equal", "label": "Equal area sharing"},
                {"id": "protected", "label": "Protect selected rooms; larger rooms share the remainder"}],
            "geometry": {"rooms": "axis-aligned rectangles for boundary shifting; unchanged valid room polygons for explicit existing reuse", "partial_walls": "supported when contiguous shared contacts cover each shifted full side",
                         "boundary": "valid polygon with retained holes", "corridors_have_walls": False,
                         "strategy": "derive only authorized room-before minus room-after gaps; coordinate collinear offsets",
                         "existing_strategy": "explicit public circulation room union minus existing wall material; all source rooms/openings preserved",
                         "width": "clear surface width in model units; boundary-shift walls stay inside adjusted rooms, reused existing walls retain their original location",
                         "existing_wall_convention": "half interior thickness at shared room edges; full exterior thickness inside the outer-face envelope"},
            "entry": {"prerequisite": "shared room wall termination on exterior boundary",
                      "existing_circulation": "saved exterior entrance or protected stair-to-landing opening_id with explicit stair_room_id; circulation_room_ids plus wall_thickness required",
                      "replacement": "existing exterior entrance must meet the corridor unless entry.replace_existing is explicitly true"},
            "constraints": ["room identity", "fixed envelope and holes", "locked and protected room geometry", "minimum dimensions and area",
                            "maximum aspect ratio", "obstacles", "finite-width entry connectivity", "room doorway access", "opening alignment"],
            "limits": {"rooms": MAX_ROOMS, "openings": MAX_OPENINGS, "body_bytes": MAX_BODY_BYTES,
                       "candidate_limit": 12, "wall_groups": 96, "seconds": 12, "allocation_iterations": 160},
            "limitations": ["No new polygon notching or route through private room interiors; explicit existing public orthogonal landing shapes may be reused unchanged.",
                            "Shortest is exact only for one required room on the fixed full-wall-group graph, before allocation feasibility; no all-room or Euclidean optimum is claimed.",
                            "Protected and locked rooms never contribute under any policy.",
                            "Furniture conflicts require the floorplan adapter to validate placement against adjusted room bounds.",
                            "Existing reuse takes zero room area and preserves all openings and inherited room-size exceptions; it does not recertify the original architectural design.",
                            "Multiple reused rooms require a saved fully open shared separator; this mode does not erase existing walls or doors.",
                            "Unsupported entrances, incomplete shared sides, or narrow junctions are rejected, never silently substituted."]}
