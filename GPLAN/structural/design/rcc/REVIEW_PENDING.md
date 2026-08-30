# Review pending (design/rcc)

Queue: `GPLAN_Revamp/structural_research/FABLE_REVIEW_QUEUE.md`. Working-tree scaffolding, delete before the first commit.

Every module here was scoped fable tier and built by an opus agent at max effort. This is the arithmetic that decides steel in a real building, so the pass matters more here than anywhere else in the package.

| File | Built by | Status | Check |
|---|---|---|---|
| `_interaction_fallback.py` | opus max | PENDING | the strain-plane sweep against the closed-form anchors at both ends, the balanced point, displaced-concrete netting on compression bars, and that the lru_cache key cannot collide across layouts |
| `columns.py` | opus max | PENDING | additional-moment k iteration convergence, biaxial alpha_n interpolation, the 0.8 to 6 percent ladder ordering, tie leg patterns |
| `slabs.py` | opus max | PENDING | Annex D case matching from the continuity mask (the easiest place to silently pick the wrong case), corner torsion only where an edge is discontinuous, the 150 mm stop with the add_secondary_beams referral, the stair waist derivation |
| `footings.py` | opus max | PENDING | which check actually governs (punching versus one-way versus flexure) on both a square and a 2:1 rectangular case, the kern enlargement, band steel distribution, the strap referral path |
| `beams.py`, `detailing.py` | opus max | PENDING | the capacity-design shear recomputation from PROVIDED steel (safety critical), hoop zone geometry, the Table 20 cap treated as a section failure not a stirrup problem, curtailment conventions |
