"""Design layer: demands in, sized members and clause traces out.

Every material designer returns the one DesignResult shape owned by
`design/common.py` (status pass|resized|fail, checks[], bars carrying ld_mm,
referrals, trace), so the report and the quantities take-off never branch on
material. Clause callables live under `codes/` and return plain floats; the
decorator sink in `codes/trace.py` is what records them.

Subpackages: `rcc` (beams, columns, slabs, footings, detailing), `masonry`,
`steel` (interface plus the IS 808 section database), `timber` (stub). This
module deliberately imports none of them: pulling in the design layer must not
cost a YAML read or a numpy import for callers that only wanted one designer.
"""

from __future__ import annotations
