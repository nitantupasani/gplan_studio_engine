"""Structural steel design: interface and section database.

What ships now is the database (`sections.py`, reading `data/sections_is808.yaml`)
and this package boundary. The member checks in `members.py` and the clause
callables in `codes/is800.py` land in phase S1; until then the entry point
`design_steel_members` raises NotImplementedError, which api.py turns into a
disclosed per-element warning rather than a crash.

No placement stage emits steel members, so this package is reachable only
through an explicit `options.materials.steel` request.

Importing this package does not read the section table: import
`GPLAN.structural.design.steel.sections` when you want it.
"""

from __future__ import annotations
