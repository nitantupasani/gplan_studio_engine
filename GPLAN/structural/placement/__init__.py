"""Placement: the normalized StructuralModel to a positioned structural scheme.

Two placement families share this package:

  - `frame.py`  RC frame placement: columns, beams, slab panels, plinth and tie
    levels, the layout metrics/score block, and `place_lintels_for_infill` for
    openings in masonry infill walls. Entry point `run_frame_placement`.
  - `cores.py`  stair and lift cores: shaft-wall vs corner-column mode, opening
    trimmers, landing beams and stair flight records. Runs before column
    placement so core faces anchor the grid.
  - `masonry.py` (separate module, separate spec) routes load-bearing and
    confined masonry systems.

Units follow finding 1: the model is SI metres; these modules quantize to
integer millimetres privately and return metres, with only section dimensions
named `*_mm`. Every fallback and repair is disclosed through the registry codes
in `model.REGISTRY`; nothing is silently dropped.
"""

from __future__ import annotations
