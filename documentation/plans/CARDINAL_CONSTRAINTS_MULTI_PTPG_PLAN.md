# Cardinal constraints on the alternative-arrangements engine

Implementation plan, written 2026-08-01 against engine `9d971447`
(`nitantupasani/gplan_engine` main), designer `6dbd927`, backend `gplan_backend` main.

Scope: the **multi-PTPG endpoint only** (`POST /api/generate/multi-ptpg`, the
"alternative arrangements" engine). The `door_connectivity` path is the reference
implementation here, not the subject: it is touched only where a helper moves or a
shared normalizer gains a guard.

Companion documents: `cardinal_constraints.md` (the door path's cardinal feature,
as built), `multi_ptpg_api.md` (this endpoint's contract),
`DOOR_CONNECTIVITY_SIZING_AND_POSTPROCESS_PLAN.md` Section 12 (which declared
multi-PTPG out of scope and named the allocator follow-up this plan's Phase 6
picks up).

---

## 1. What already ships

Cardinal pins were added to this endpoint on 2026-07-30 (`de5474bf`). The first
cut is real and it works on the graphs it was tested against. It is not a stub,
and this plan is parity and hardening work, not a from-scratch build.

| Layer | Where | Behaviour today |
|---|---|---|
| Normalization | `multi_ptpg_pipeline.py:185-198` -> `api.py:127-159` | Same wire format and the same normalizer as `door_connectivity`, so one client payload serves both endpoints |
| Variant pruning | `multi_ptpg_pipeline.py:388-423` | Pinned rooms are unioned into `exterior_required`; `filter_variants_by_constraints` drops any variant whose outer cycle does not contain them |
| Keep-all fallback | `multi_ptpg_pipeline.py:399-410` | If pruning would empty the set, all variants are kept and a warning says geometry will decide instead |
| Boundary ordering | `ptpg_floorplanner.py:251-271` | Candidate boundaries sort pin-first, and are never dropped |
| Geometric gate | `ptpg_floorplanner.py:185-248` | y-up strip test with a recess-not-void rule (allowance = smallest room dimension), run **inside** the candidate loop so `floorplans_per_variant` counts satisfying plans |
| Ladder | `multi_ptpg_pipeline.py:516-534` | One rung: zero plans with pins -> re-dimension everything unpinned, set `cardinal.ignored`, warn naming each pin |
| Response | `multi_ptpg_pipeline.py:586-598` | `cardinal.{requested,applied,ignored}`, per-variant and per-plan `cardinal_satisfied`, `stats.variants_dropped_by_cardinal` |
| Backend | `gplan_apis/views/multi_ptpg.py:110-139` | Rejects malformed pins with a 400 rather than letting the engine drop them silently; the cache key covers `params` plus `ENGINE_FINGERPRINT` |
| Designer | `services/engine/multiPtpg.ts` | Sends the same `buildCardinalConstraints` payload, sorts arrangements pins-first, chips each arrangement in the gallery, stamps `NOTE_IGNORED` when the engine reports `ignored` |

What is missing is everything the door path learned between 2026-07-15 and
2026-07-18, plus the reporting and client contract that a two-engine picker needs.

### Settled priority (product owner, 2026-08-01). Do not re-litigate.

**A cardinal pin outranks a room-to-room adjacency, and pins should be satisfied
as close to always as the graph allows. Subject to that, keep as many of the
user's adjacencies as possible.**

This is the same ranking the door path already implements, where the ladder trades
adjacencies away to hold a pin and says so. It was never stated for this endpoint,
and the code here encodes the exact opposite. The two ladders' own comments are
the clearest statement of the inversion:

| | |
|---|---|
| `api.py:1455-1458` (door) | "Cardinal constraints take priority over adjacency wishes: retry with the adjacency set relaxed to a spanning tree ... then as a last resort drop the cardinal filter." |
| `multi_ptpg_pipeline.py:518-519` (this endpoint) | "Relaxation ladder, mirroring door_connectivity's: **pins outrank nothing**." |

A pin is the first thing sacrificed here and the last thing sacrificed there, so
the module docstring's claim at `multi_ptpg_pipeline.py:32-34` that the ladder
"mirrors door_connectivity's" is false in the one property that matters. The
client repeats it: `multiPtpg.ts:182-187` records "adjacency never loses to a pin
here". **Correcting that docstring and that comment is part of this work**, not a
tidy-up; shipping the current text against the new behaviour is the single thing
most likely to mislead the next reader.

Three consequences run through the rest of this document:

1. Unpinning is a **last** resort, not the second rung. Every option that keeps
   the pins is exhausted first, including ones that cost arrangements.
2. Where two designs both satisfy the pins, prefer the one that keeps more
   adjacencies. This is what promotes the ring from a fallback to the default
   under pins (Section 6), and it is not a tie-breaker: it changes which design
   wins outright.
3. Arrangement **count** is the thing that gives way. It ranks below both pins and
   adjacency. That answers what was open question 1 in the first draft of this
   plan.

---

## 2. The finding that shapes this plan

**The door path's cardinal outer-ring augmentation changes the variant search
underneath itself: it disables Stage 1 of the two transformations outright.** That
is a fact about the code, verified below. Whether it is a cost or a benefit is
decided by the priority in Section 1, and under that priority it is mostly a
benefit. Read this section before porting anything.

This is the first thing to know, because the ring is the obvious port. It is the
change that took the door path's 13-room 4BHK from 0 satisfying plans to 11 of 11
and from 302 s to 8.6 s (`cardinal_constraints.md:100-135`), and this pipeline
never calls it: `build_base_ptpg` (`multi_ptpg_pipeline.py:122-141`) constructs an
`InputGraph` from four constructor arguments and calls `door_connectivity()` with
`cardinal_constraints` left at its `[]` default, so every cardinal branch inside
`inputgraph.py` is switched off and `apply_cardinal_ring` is never reached (its
only call sites are `api.py:1374`, `1440`, `1476`, all inside the door path).

The reason a verbatim port backfires is a guard in the variant search:

```python
# multiple_ptpg.py:204-220, STAGE 1: boundary edge removal
for u, v in outer_edges:
    ...
    # The triangle collapsing into the outer face must hang off an interior
    # apex; otherwise removal would leave a chord across the new outer face.
    if set(nx.common_neighbors(G, u, v)) & outer_node_set:
        continue
```

`build_cardinal_ring` adds a **Hamiltonian** outer cycle: every room lands on the
boundary by construction, which is precisely what makes every pin satisfiable. But
then `outer_node_set` is the entire node set. In a triangulated planar graph the
unique interior triangle on an outer edge has an apex that is some node, and every
node is now an outer node, so the guard fires on every outer edge and Stage 1
returns nothing. Only Stage 2, the 4-cycle diagonal flip, survives.

Stage 1 is not a minor contributor. It is one of the two operations behind the
measured depth-2 closures the shipped defaults are tuned around (26 for 2BHK, 41
for 3BHK, 107 for 4BHK, `multi_ptpg_api.md:297-301`).

**But it does not collapse the catalogue. It grew it.** The first draft of this
plan assumed the loss and was wrong. Measured in-process on a 10-room chain tree
with two pins: without the ring, 12 variants at depth 2 with both pins infeasible;
with the ring, **35 variants**, every pin on the outer face, and the operation mix
`{base: 1, flip_diagonal: 34, remove_boundary_edge: 0}`. A ring-augmented graph
with no interior vertices is a triangulated polygon, and the flip closure of a
triangulated polygon is rich, so losing Stage 1 cost less than gaining a fully
boundary-exposed graph won.

**And the regime it creates is the one this feature wants.** Stage 2 provably
cannot change the outer face: `find_4_cycles_filtered` excludes outer edges and
the guards at `multiple_ptpg.py:234` and `:237` force the two off-diagonal nodes
to meet only at the diagonal's endpoints, so every node's common-neighbour count
is preserved. Measured: **0 of 32,852 flips across depth 4 moved a single node on
or off the outer face.** With a ring the outer cycle is therefore invariant across
the entire closure, which means every arrangement in the catalogue keeps every pin
feasible. Compare that with today, where pin feasibility varies arrangement by
arrangement and most arrangements fail it.

So the ring does not merely pay an acceptable price under the Section 1 priority.
It wins on all three criteria at once on the graphs measured. Do not treat the
count as settled for every program, though: re-measure per shipped unit type,
because the depth table at `multiple_ptpg.py:41-54` was measured without a ring
and goes stale the moment this lands.

The same guard, read the other way, is what limits the current pin-blind pipeline,
and it gives an exact statement of the gap. Stage 1 removes an outer edge only
when the collapsing triangle's apex is **interior**, and that removal is what puts
the apex on the outer face. So:

- **Only Stage 1 can surface an interior room. Stage 2 never can**, by the
  invariance argument above. So the entire reach of the pin-blind search rests on
  boundary-edge removal.
- Removal is blocked on any edge in `user_needs`, and `preserve_input_edges`
  **defaults to `True`** (`multi_ptpg_pipeline.py:274`, `:345-346`), which makes
  `user_needs` the whole client edge list. On the default the search therefore
  relaxes only the engine's own augmentation edges and can barely move at all. The
  designer sends `false`, so for the shipped client removal is unblocked and each
  promotion may delete an adjacency the user drew.
- Reach is bounded to **one layer per depth level**, proved and measured: a node
  exposed at depth 2 is still adjacent to a base-outer node, so depth-2 reach is
  layer 1 only. A layer-2 room first reaches the outer face at depth 3, past the
  shipped `max_depth: 2`, whose own comment argues against raising it.

Measured on five realistic sparse designer-shaped graphs at the default settings,
**four had interior rooms, and in every one of those at least one interior room
was still buried after the full depth-2 closure.** The worst case is instructive:
an 8-room hub-and-ring 2BHK has Living interior and all seven outer edges
user-drawn, so Stage 1 is completely frozen and the search returns **exactly one
variant, the base**. Living can never be pinned, at any depth, at any budget.

That is the honest characterization of gap G1: not "pins never work on sparse
graphs" but "pins work only for rooms within one layer of the boundary in whatever
embedding `bcn.biconnect` and `nx.planar_layout` happened to choose, and reaching
even that layer is paid for out of the user's adjacency list."

One correction to an earlier draft of this document and to
`cardinal_constraints.md:106-108`, which calls the designer's unit graphs "usually
forests": they are not, and have not been since the 2BHK default was re-derived
from a dissection on 2026-07-30. The shipped programs are 8 rooms with 14 edges,
10 with 10, and 12 with 13. All are cyclic. They are sparse and not biconnected,
which is the property that matters here, but arguments that lean on acyclicity do
not hold.

**That last clause is the argument for the ring, not against it.** Under the
Section 1 priority the two designs compare like this:

| | Pins satisfied | Adjacencies kept | Arrangements offered |
|---|---|---|---|
| Pin-blind search, pinned room buried | Only within one layer, and 4 of 5 measured graphs failed | Fewer: each promotion may delete a user edge | 12 on the measured chain tree, 1 on the hub 2BHK |
| Ring-augmented base | At depth 0, and invariant across the whole closure | **All of them**: the base variant is the full user edge set | 35 on the same chain tree |

Satisfying a pin by walking the variant search **is** the mechanism that deletes
adjacencies, because Stage 1 promotes an interior room precisely by removing a
boundary edge, and with `preserve_input_edges: false` (what the designer sends)
nothing stops that edge being one the user drew. The ring reaches the same pin
with no deletion at all, because the depth-0 base variant carries every user edge.

So the ring is not a pins-versus-adjacency trade at all. On the graphs measured it
wins on every criterion, which is why Section 6 makes it the default under pins
rather than the fallback rung the first draft proposed.

**Where the ring legitimately refuses.** `build_cardinal_ring` returns `None` when
no crossing-free Hamiltonian order exists, and that is not a limitation to work
around: on the hub-and-ring 2BHK it refuses because a wheel is not outerplanar and
its hub is interior in **every** planar embedding. Living genuinely cannot reach an
outer wall with that adjacency graph. Today the endpoint answers such a request
with `ignored: true` plus a catalogue, which reads as "we tried and your room sizes
did not work". It should say the pin is impossible and why. See Section 6 item B.

---

## 3. Gaps, ranked

Severity is ranked against the Section 1 priority, so a gap that costs a pin or
costs an adjacency outranks one that costs an arrangement or a label.

| # | Gap | Severity | Phase |
|---|---|---|---|
| G1 | Pin-blind base embedding on sparse graphs. Measured: 4 of 5 realistic graphs keep a room permanently buried at depth 2, and reaching even layer 1 spends the user's adjacencies. Violates both ranked criteria at once | Critical | 3 |
| G2 | The boundary cap truncates the **symmetry orbit**, not just the tail. Measured: on a 10-node outer cycle it keeps zero rotations and zero reflections, and an 8-room ring returns 5 plans instead of 13 with a false "no layout realises this topology" reason | Critical | 1 |
| G4 | The ladder is binary: all pins or none. A brief that could hold 2 of 3 pins holds 0 | Critical | 2, 3 |
| G9 | An impossible pin (room interior in every planar embedding) is reported as `ignored` with a catalogue, indistinguishable from "your sizes did not fit" | High | 3 |
| G3 | Variant pruning is outer-cycle **membership** only, never arc assignability | Medium | 1, 2 |
| G5 | Reporting states `applied: true` over an empty gallery, zeroes its own funnel metric, and misdiagnoses contradictory pins | High | 1 |
| G6 | Client reads the arrangement verdict but never the per-plan one; catalogue cards carry no pin state; mixed batches disclose nothing per engine | Medium | 4 |
| G7 | No sparse-graph or corner-pin test, and both existing pin tests skip their assertions when the engine says `ignored` | High | 5 |
| G10 | The two endpoints serialize opposite vertical axes (door y-down, this one y-up) under one N/E/S/W vocabulary | Medium | 4 |
| G11 | Pin validation differs across the Django view, the local bridge and the pipeline, and `interior_rooms` gets none at all | Medium | 7 |
| G8 | Allocator targets land on a 0.5 ft grid that `int(round())` destroys | Medium | 6 |

### G2 in detail, because it is the cheapest large win

First, kill a plausible misdiagnosis. The placer is **not** missing the mirror.
`ptpg_floorplanner.py:391-401` builds the full 8-element dihedral orbit of every
raw boundary, matching `inputgraph.filter_boundaries_by_cardinal` in coverage, and
the E, N, W clockwise case that `cardinal_constraints.md:88-98` documents
succeeds end to end when tested directly. The reflection is also load-bearing
rather than redundant: on a 6-room ring, of 152 boundaries only 5 are placeable at
all and **all 5 are reflections**, so deleting those lines makes that graph
produce nothing. Anyone tempted to prune them as dead code should be stopped by a
test (Section 8).

The real defect is that the cap eats the orbit. `get_boundaries` appends every
rotation and reflection **after** the whole raw list (line 391 iterates a
snapshot), then `bdys[:max_boundaries]` truncates at 48 (lines 403-404), and only
afterwards does `generate_floorplans` sort by `order_boundaries_by_cardinal`
(line 963). The cap therefore cuts orbit-first, exactly backwards, and the sort
runs on an already-truncated list and provably cannot restore anything.

Measured at the default `max_boundaries = 48`:

| Outer cycle | Raw | Total after orbit | Orbit variants kept |
|---|---|---|---|
| 6 | 19 | 152 | 29 of 133 |
| 8 | 34 | 272 | 14 of 238 |
| 10 | 53 | 424 | **0 of 371** |

Consequences reproduced on an 8-room ring: of 272 boundaries only two are
placeable, both past the cap, so the default returns **5 plans where lifting the
cap returns 13**, and the emptied arrangement reports the reason "no layout
realises this topology at the requested exact room sizes"
(`multi_ptpg_pipeline.py:501`), which is false. With pins it is worse: 163 E/N/W
triples on that graph have an arc-satisfying boundary uncapped and **zero** after
the cap.

Two framings to correct. The loss is not mirror-specific (the two placeable
boundaries on the 8-ring are rotations), so this is orbit-tail truncation of which
mirror loss is one case. And the fix is not "add the reflection" but "stop the cap
from selecting against symmetry": count **raw** boundaries rather than orbit
members, or expand each raw boundary's orbit before moving to the next so every
surviving candidate is symmetry-complete. `max_boundaries` then bounds exactly
what its docstring says it bounds, the O(k^4) 4-split blowup, which lives entirely
in the raw list.

This is also the highest-leverage item in Phase 1 for pins specifically. An
independent experiment on a 10-room cyclic brief found that of 12 single-pin
requests, 11 were honoured and 1 was dropped; re-running the failing one with the
cap lifted **honoured the pin**, while raising `max_depth` to 3 with
`max_variants` at 150 did not. Sequencing note: Phase 3 puts every room on the
outer cycle, which grows the raw list as C(k,4), so this must land first or it
will bite harder.

---

## 4. Phase 1: correctness fixes with no behavioural risk

Small, independently shippable, each with a test. None of them changes what a
successful request returns today; they change what happens on requests that
currently fail or misreport.

**1.1 Stop the cap selecting against symmetry, then make it pin-aware (G2).**
Three changes in `ptpg_floorplanner.py:382-404` and `:963`, in this order:

- Expand each raw boundary's full orbit before moving to the next, and make
  `max_boundaries` count **raw** boundaries. Every surviving candidate is then
  symmetry-complete, and the cap bounds the O(k^4) blowup it was written for.
- Thread `cardinal_pairs` into `get_boundaries` so the retained slice is pin-scored,
  or move `order_boundaries_by_cardinal` ahead of the truncation. Keep the
  never-drop principle: this decides which survive, not whether any are dropped.
- Retune `DEFAULT_MAX_BOUNDARIES` afterwards. Under a raw-counting cap, 48 means
  48 x 8 = 384 candidates and the placer cost is per candidate, so validate the
  runtime against the budget before landing. This is the one item in Phase 1 that
  can make things slower.

Also fix the false diagnosis this produces. When a variant returns nothing because
the cap bound, `multi_ptpg_pipeline.py:496-505` still reports "no layout realises
this topology at the requested exact room sizes", blaming the room sizes for a
truncation. Have `generate_floorplans` report whether the cap bound and surface it
in the reason plus a `boundaries_truncated` stat.

**1.2 Ring-order feasibility in the variant filter (G3).** Today
`filter_variants_by_constraints` (`multiple_ptpg.py:385-405`) asks only whether
each pinned room appears in `set(outer_cycle)`. With two or more pins that is
necessary and not sufficient: the cyclic order also has to admit a rotation or
reflection that puts each pin in its own N/E/S/W arc. `api._ring_order_satisfies`
(`api.py:162-207`) is exactly that predicate, it is pure, and it already checks
both orientations and all rotations, which is the same 8 symmetries the downstream
boundary filter can accept. Reuse it per variant.

Two guards are needed on reuse, both from reading the door path's assumptions:
its corner-pin branch does `d1, d2 = tuple(ds)` and therefore raises `ValueError`
rather than returning `False` when a room carries three or more directions,
because `build_cardinal_ring` rejects that case before calling it. Wrap or
pre-filter. Second, the multi-PTPG outer cycle can come from the open-path
fallback in `boundary_nodes` when the outer face is not a simple cycle; treat that
as "unknown, do not prune" rather than feeding a non-cycle to a cyclic predicate.

**1.3 Reporting honesty (G5).** Four separate misstatements, all in
`multi_ptpg_pipeline.py`:

- `cardinal.applied` is `bool(cardinal_pairs) and not cardinal_ignored`, so when
  both the pinned pass and the unpinned retry return nothing, or when the deadline
  expires before the retry can run (line 522 guards on `time.monotonic() <
  deadline`), the response claims the pins were applied over an empty gallery.
  Report a third state, or set `applied` from "at least one returned plan
  satisfies the pins" rather than from the absence of the ignore flag.
- `stats.variants_dropped_by_cardinal` is reset to 0 by the keep-all fallback
  (line 410), which zeroes the metric in exactly the case where the filter was
  most aggressive. Keep the count and add a `variants_kept_by_cardinal_fallback`
  flag beside it.
- The per-variant reason after a failed retry is wrong too: the kept payloads still
  say "no layout puts every pinned room on the direction you asked for"
  (`:498-500`), blaming pins the unpinned retry had just proved were not the cause.
  Choose the reason from the retry's outcome.
- Contradictory pins (one room pinned N and S) survive normalization, because
  `normalize_cardinal_constraints` dedupes exact pairs only. Verified live: such a
  request runs the **full pinned pass and the full unpinned retry** before
  answering `ignored`. Detect them up front with the same `(d2 - d1) % 4 == 2` test
  `build_cardinal_ring` uses at `api.py:239-242`, plus the 3-directions-per-room
  rejection beside it, and warn naming the room.
- A room in both `interior_rooms` and `cardinal_constraints` is unsatisfiable by
  construction, and today the filter empties, the fallback keeps everything, and
  the warning blames the pins. Reject it or state which wins.
- Pins on rooms `door_connectivity` invented are silently dropped, because
  normalization runs against `len(nodes)` before the PTPG exists. That is the
  right behaviour and it should be stated in the response rather than inferred.

**1.4 Wire the unused deadline. This is not housekeeping.** `build_base_ptpg`
takes a `deadline` parameter and never passes it anywhere
(`multi_ptpg_pipeline.py:122` against `128-141`), so `door_connectivity` runs
unbounded. Observed while probing: a **disconnected 9-node forest ran for over
four minutes** there and had to be killed, against 1.2 s for a 13-node tree.
"Sometimes disconnected" is exactly the input class this plan targets, so an
unbounded call at the front of the pipeline will mask every other improvement.
Bound it or pre-check it in the same change.

---

## 5. Phase 2: graded pin satisfaction

Replace the binary ladder. Today the pipeline honours every pin or drops all of
them, and with three pins a request that could have satisfied two returns plans
that satisfy none, with a warning naming all three.

The mechanism that makes this cheap is 1.2. Once `_ring_order_satisfies` can be
evaluated against a variant's outer cycle, the **maximal satisfiable pin subset**
per variant is computable before any dimensioning: with k pins there are at most
2^k subsets and k is 1 to 4 in practice, so this is free next to a single
compaction pass.

The design:

1. Per variant, compute the largest pin subset the outer cycle admits.
2. Order dimensioning by subset size descending, then by the existing base-first
   and depth ordering.
3. Pass **that variant's** subset to `generate_floorplans` as `cardinal_pairs`, so
   the geometric gate enforces what this arrangement can actually hold.
4. Report per pin, not per request: which pins hold on every returned plan, which
   hold on some, which hold on none. This is also what finally gives the per-plan
   `cardinal_satisfied` field real content. Today it is assigned `bool(pins)`
   (`multi_ptpg_pipeline.py:493`), the same value for every plan in the batch, so
   it carries no information the request did not already have.

This is what fills the middle of the ladder in Section 6. The all-pins case is the
k-subset, the current `ignored` case is the empty subset, and everything between
is new: it is the difference between telling a user "two of your three directions
held, here is the one that could not" and telling them all three were ignored. It
also removes the full re-dimensioning of every variant that the retry rung costs
today.

Keep the topological subset as a **scheduling and reporting** device only. The
arcs are a topological assignment and the rectangles are the truth, which is the
principle `ptpg_floorplanner.py:254` already states as its reason for ordering
rather than filtering; the geometric gate stays the only authority on whether a
returned plan satisfies a pin.

**What about the door path's spanning-tree rung?** It should not be ported. It is
a no-op on exactly the inputs that need it: `spanning_tree_edges` returns every
edge of a forest, the rung is guarded on `len(tree_edges) < len(edges_list)`
(`api.py:1467`), and the designer's unit graphs are forests. More to the point,
this engine already relaxes adjacency structurally: a variant **is** a dropped
adjacency, the search explores that space by construction, and every arrangement
reports what it traded. Adding an adjacency-relaxation rung on top would duplicate
the engine's own premise. The multi-PTPG analogue of "relax the brief to hold the
pins" is the pin-ordered variant search, not a second graph.

This is not a softening of the Section 1 priority. Rung 3 of the Section 6 ladder
**is** the rung that spends adjacencies to hold a pin, which is what the door
path's spanning tree does; the difference is that this engine already has the
mechanism and does not need a second graph built for it.

---

## 6. Phase 3: pin-aware embedding, the default whenever pins are present

**Apply `build_cardinal_ring` whenever the request carries pins.** Section 2 gives
the measured reasoning: the ring reaches every pin at depth 0, keeps the user's
entire edge set, makes pin feasibility invariant across the whole closure, and on
the graph tested produced a larger catalogue rather than a smaller one.

Call it inside `build_base_ptpg`, mirroring `api.py:1440-1442`: thread the pins
(already normalized at `:280`, before the `:284` call) and apply the ring to the
`InputGraph` **before** the deepcopy at `:134`. Red edges are already stripped at
`:259`, so `apply_cardinal_ring`'s non-adjacency refusal cannot fire. The node
count must stay the client count, which it is at that point, so it agrees with
`_normalize_cardinal`'s range check.

**The ladder, top to bottom, ordered by what each rung costs the user.** Each rung
keeps the pins; unpinning is reached only when everything above it produced
nothing. Check the deadline before each rung and record which one fired in `stats`
so a slow request is explainable.

| Rung | What it changes | What it costs |
|---|---|---|
| 1 | Ring-augmented base, full variant search, pin subsets from Phase 2 driving the order | Nothing |
| 2 | Retry with the boundary cap lifted (`max_boundaries = 0`, or a multiple) | Time only. Empirically rescued a pin the shipped ladder gives up on |
| 3 | Re-enumerate with `user_needs = []` and retry the pins | Adjacencies. Warn naming the pairs given up, and surface them in `stats` |
| 4 | Drop the single least satisfiable pin, repeat from rung 1 | One pin, named |
| 5 | Unpinned retry, `cardinal.ignored` | Every pin. Last resort |

Rung 2 is first among the retries because it sacrifices nothing of the brief, and
it may make itself unnecessary: with Phase 1.1 landed, the cap already keeps the
best-aimed boundaries, so most of what rung 2 recovers today should be recovered
before the ladder is reached.

Rung 3 is the true analogue of the door path's spanning-tree rung, and `user_needs
= []` strictly dominates that construction: it enumerates every single-edge-removal
descendant instead of one arbitrary BFS tree. It needs the enumeration hoisted into
a helper so it can run twice, since `dimension_all` currently closes over
`variants`. Two guardrails: skip it when `user_needs` is already empty, since it
would repeat rung 1 exactly, and when the caller passed `protected_edges` by hand,
treat that as a hard statement and either skip the rung or relax only the
`preserve_input_edges`-derived needs. Do not silently discard adjacencies someone
named explicitly.

Rung 4 is where the "try to always satisfy" instruction bites hardest: with three
pins, two held beats none, and today the pipeline jumps straight from rung 1 to
rung 5.

Note what is deliberately **not** a rung: raising `max_depth`. Tested on the
failing single-pin case, `max_depth: 3` with `max_variants: 150` still dropped the
pin, while lifting the boundary cap held it. Depth buys arrangements, not pins.

Mechanically the change is small, because the door path already proved the pieces
are pure and engine-agnostic: `build_cardinal_ring` takes `(nodecnt, edge triples,
pairs)` and returns `(ring_edges, coords)`, and `apply_cardinal_ring` needs only a
duck-typed graph exposing `.matrix`, `.edgecnt` and `.coordinates`, which
`InputGraph` satisfies. The ring survives into the embedding by making the graph
biconnected, so `bcn.biconnect` is skipped and `trng.triangulate` keeps the
supplied circle coordinates instead of replacing them with `nx.planar_layout`
(`inputgraph.py:374-376`, `triangularity.py:270-277`).

Six consequences to handle, none of which the door path had to. The first is the
highest-risk item in this plan, because making the ring the default makes it
unavoidable rather than occasional:

- **A. Ring edges must not become required adjacencies.** `generate_floorplans`
  treats every edge in `variant_edges` as a hard requirement
  (`ptpg_floorplanner.py:1057`, `require_all_adjacencies=True`) and rejects any
  layout that misses one (`:899-904`). A Hamiltonian ring would demand all n rooms
  form a closed chain of shared walls at exact sizes, which is a far harder problem
  than the graph the user drew, and this pipeline already returns zero plans easily
  at exact sizes. Add a `soft_edges` argument that is excluded from `required` and
  from the adjacency score, and pass the ring edges through it. The door path never
  needed this because its min-dim solver can grow rooms until the adjacency
  materializes; this placer cannot. **If Phase 3 returns no plans, check this
  first.**
- **B. Treat a refusal as an answer, not a silent no-op.** `build_cardinal_ring`
  returns `None` for three or more directions on one room, for opposite directions
  on one room, and, the common real case, for a graph with no crossing-free
  Hamiltonian order. On the hub-and-ring 2BHK it refuses **correctly**: a wheel is
  not outerplanar and its hub is interior in every planar embedding. Emit a
  distinct warning naming the room and the reason, and set an explicit `impossible`
  flag rather than `ignored`. This is a user-facing win independent of everything
  else, and it is the difference between "your brief cannot do this" and "we tried
  and your sizes did not work". Note the refusal search is first-fit within a
  500-combination budget, so `None` is not always a proof; word the message so it
  does not overclaim.
- **C. Expect the closure to become flip-only, and do not "fix" it.** Measured
  `{base: 1, flip_diagonal: 34, remove_boundary_edge: 0}`. That is the desired
  regime, because flips provably cannot move the outer cycle, so every variant
  keeps every pin feasible. Do **not** relax the `multiple_ptpg.py:211` guard for
  ring edges. Instead add the ring edges to `user_needs`, so that if
  separating-triangle removal ever perturbs the boundary and a removal does become
  legal, it cannot rotate a node into the cycle and destroy the order the ring
  engineered, which the membership-only filter could not detect.
- **D. Report ring edges separately.** `edges_added_by_door_connectivity` is
  computed as base edges minus input pairs (`multi_ptpg_pipeline.py:303-306`), so
  ring edges would be filed under a name that blames the wrong stage, and a client
  could draw a door on an adjacency that does not exist. Add a `ring_edges` field.
- **E. Client-facing adjacency accounting is already safe**, and should stay that
  way. `realisedCount` and `kept` in `multiPtpg.ts:314-343` both measure against
  `params.edges`, the user's own list, so engine-added edges cannot inflate them.
  Do not "fix" them to read the engine's totals.
- **F. Re-scope the keep-all fallback.** `multi_ptpg_pipeline.py:399-410` keeps
  every variant when the cardinal filter empties, reasoning that a buried room
  "usually still has SOME layout in which its wall reaches the boundary". In a
  rectangular dual an interior graph node has no rectangle touching the outer
  bound, so that is wishful: it buys a full second dimensioning pass over every
  variant for nothing. With a ring in place an empty filter means genuinely
  impossible, so it should say so and skip the pass.

**The follow-up, and it is now purely about recovering arrangement count:** a
minimal pin-aware biconnection rather than a Hamiltonian one. The ring solves two
problems at once, making the graph biconnected so the coordinates survive
`triangulate`, and putting pinned rooms on the outer face. Only the second is
about pins. Adding the fewest edges that biconnect the graph **and** land the
pinned rooms on the outer face in a feasible cyclic order would leave unpinned
rooms free to be interior apexes, which is exactly what Stage 1 needs to keep
working. Typical units carry one to three pins, so that augmentation is far
smaller than n edges, and it should preserve both the pins and the variant search.

Under the Section 1 priority this is an optimization, not a prerequisite: it buys
back arrangements, which rank last. Do it only if the Section 2 measurement shows
the Hamiltonian ring costing real catalogue size. It is a design task with its own
measurement, not a refactor.

---

## 7. Phase 4: the client contract

**4.1 Make the per-plan verdict real, then consume it.** Two defects stack here.
The client's `MultiPtpgPlan` type has no `cardinal_satisfied` field
(`multiPtpg.ts:66-72`), so the channel is dropped on arrival. But the channel is
also empty: the engine sets `plan["cardinal_satisfied"] = bool(pins)`
(`multi_ptpg_pipeline.py:493`), a **batch constant**, not a geometric verdict. It
restates "pins were requested" for every plan alike. Adding the client field
without fixing the engine value would surface nothing.

So the whole stack currently has exactly one geometric authority for a multi-PTPG
pin: `plan_satisfies_cardinal` called inside the candidate loop at
`ptpg_floorplanner.py:979` and `:1029`. Everything downstream is an echo. Phase 2
makes the per-plan value genuinely per-plan (which pin subset this layout holds),
which is what gives 4.1 something to read.

**4.2 Mark pin state on catalogue cards.** `engineNote` renders only as a warning
suffix on the **active** plan's status label (`UnitEditor.tsx:2177-2179`), and the
`A<n>` badge tooltip talks about adjacencies. A plan from an arrangement chipped
"N/E/S/W not honoured" in the gallery is visually identical to a satisfying one in
the catalogue. Within the multi-PTPG block the round-robin takes one plan from
**every** arrangement including the non-honouring ones (`generators.ts:119-123`),
so page 1 mixes them. Put the verdict on the card.

**4.3 Disclose per engine in a mixed batch.** With both engines ticked and pins
set, `door_connectivity` plans are geometrically re-verified and have
`NOTE_IGNORED` stripped from the survivors (`doorConnectivity.ts:447-469`) while
multi-PTPG plans are trusted from the response. Plans are **concatenated per
engine**, not interleaved (registry order, `generators.ts:100` and `:153`), so a
mixed batch runs door plans first and then multi-PTPG plans, relabelled into one
`Plan 1..N` sequence whose only cue is a small "mixed engines" line.

`GenerationOutcome` (`generators.ts:79-86`) merges `warnings` flat with no
attribution while the adjacent `errors` field is already attributed
(`{id, label, message}`), so the shape exists and was not used. Note the
asymmetry this creates: `door_connectivity` returns `warnings: []` unconditionally
(`generators.ts:113`) and reports its pin outcome only by mutating `engineNote`,
so if **it** is the engine that ignored the pins there is no batch-level statement
at all. Attribute the warnings, or carry a per-engine cardinal record.

**4.4 Fix two pieces of wrong copy.** The cardinal-edge inspector caption says
"If it conflicts with adjacencies, the engine drops adjacencies first"
unconditionally (`UnitEditor.tsx:1834-1837`), which is the door path's behaviour
and the opposite of this engine's. The gallery header says an arrangement that
cannot face a pinned room "is not offered"
(`LayoutVariantGallery.tsx:124-125`), which the keep-all fallback and the
`ignored` rung both contradict in the same modal that renders "not honoured"
chips.

**4.5 Detect a backend that drops the field.** The door path distinguishes "the
engine could not satisfy the pins" from "the engine ignored the field", with a
bridge hint in dev. On this path a backend without cardinal support marks every
arrangement `cardinalSatisfied: false`, which is indistinguishable from genuine
failure.

**4.6 Settle the vertical axis on the wire (G10).** The two endpoints serialize
opposite conventions under one N/E/S/W vocabulary: `door_connectivity` emits rooms
y-down from `final_traversal` (`api.py:1541-1564`), this one emits them y-up
(`ptpg_floorplanner.py:122-133`), and within a single multi-PTPG plan `rooms` is
y-up while `encoded_matrix` is y-down (`:90`, `:906`). Both **gates** are
internally correct and neither should be touched. The hazard is a shared client
renderer, which silently swaps north and south on one endpoint if it assumes one
convention. The designer happens to flip correctly today, so this is latent rather
than live. Either flip multi-PTPG's `y` on the wire to match, or add an explicit
axis marker to the payload and document the split.

On **not** re-verifying client-side: treat the comment at `multiPtpg.ts:294-301`
as a correct premise with an unsound conclusion, and say so in the code so it is
not re-litigated. The premise holds: `planSatisfiesCardinal` in
`shared/cardinal.ts` is byte-for-byte the `api.py` rule, strip-only with no void
allowance, so reusing it here really would pass a room floating across a void.

The conclusion does not follow, for two reasons. First, the correct predicate is
already written in this repo: `facesSide` in `scripts/checkGenerators.ts:152-174`
applies the engine's exact rule, recess allowance and all, and its own comment
says T6 verifies geometrically "rather than trusting the engine's own verdict".
The battery does not trust the verdict; the shipped client does. Lift it into
`src/shared/cardinal.ts` as a second named export beside `planSatisfiesCardinal`,
have the battery import it so the two cannot drift, and document the pair:
strip-only is the door rule, strip-plus-recess is the multi-PTPG rule.

Second, "two predicates disagreeing about one plan is worse than one" does not
apply, because these two do not disagree symmetrically. The engine rule
(`ptpg_floorplanner.py:240`) is **strictly stronger** than the strip test, and
`floorplanFromMultiPtpgPlan`'s y-flip reconciles the frames, so engine-pass
implies client-pass. A client re-check can only ever catch a backend that did not
run the gate. It cannot contradict a correct one.

Two implementation notes. Run the check on `plan.rooms` in the **engine** frame,
before the y-flip at `multiPtpg.ts:226`, and match `room.id` against the
constraint's room index rather than by name: `findPlacement`
(`shared/cardinal.ts:120-128`) resolves by name, and a 2BHK has two rooms called
"Bathroom". And disclose rather than filter, mirroring
`doorConnectivity.ts:447-469`: keep the plans, keep the engine verdict primary,
and separate the three failure modes, which are `cardinal.ignored` true (the
existing note), the cardinal block absent entirely (today completely silent, and
the case a stale backend produces), and engine-says-satisfied-but-geometry-
disagrees (a backend regression worth naming the room and direction for, since
the `ptpg_floorplanner.py:191-194` docstring warns that getting the y-up flip
wrong silently swaps north and south).

---

## 8. Phase 5: tests

The current coverage has a shape problem, and it is the same one on both sides of
the wire: **every pin assertion is skipped when the engine reports the pins
ignored.** Engine `test_multi_ptpg.py` T7 and designer `check:generators` T6 both
do this. An engine that ignored pins on every hard input would pass both suites.

| Test | Why |
|---|---|
| A sparse designer-like graph, pinned | Both engine test graphs are biconnected (5-node pinwheel, 6-node ring plus chord). The shipped programs are forests (2BHK 8/8, 3BHK 10/10, 4BHK 12/13) and that family, which is the production case, has no pin coverage at all on this endpoint. Port the door path's 13-room T8 unit from `test_api_cardinal_constraints.py:190-235` |
| A pin that **must** hold | Pick a configuration known satisfiable in the base variant and assert satisfaction unconditionally, with no ignored-escape. This is the test that would fail if any phase here regressed |
| Corner pin (N+E on one room) | Untested on both endpoints, though probing found the behaviour **correct**: the arcs share endpoints, a corner room genuinely occupies two adjacent arcs, and the gate ANDs the two pins. Lock it in before something breaks it, and assert that opposite pins are rejected up front rather than after two full dimensioning passes |
| Boundary cap parity | The G2 regression, and the sharpest one available: on an 8-room ring, the default cap and `max_boundaries_per_variant: 0` must return the same `floorplan_count` and the same variant statuses. Today it is 5 versus 13, with a false reason string on the emptied arrangement |
| Reflections are load-bearing | On a 6-room ring, no forward-orientation boundary is placeable and all five placeable ones are reflections. Assert it, so nobody prunes `ptpg_floorplanner.py:396-401` as dead code |
| Graded satisfaction | Three pins where only two are jointly feasible: assert two hold and the response says which one did not |
| Contradictory pins | Assert the up-front warning names the room, rather than the current message blaming room sizes |
| Ring default | With and without, on the sparse unit: assert pins hold, assert **no user adjacency is dropped** in the base variant (this is the Section 1 priority as an assertion), and assert any arrangement-count change is reported rather than silent |
| Ladder order | A graph where the ring is unbuildable (opposite pins on one room, or a non-adjacency request) must reach rung 3 and still hold the pins, not skip to `ignored` |
| Stale backend (client) | Extend `checkGenerators` T6 with a response whose `cardinal` block and per-variant field are stripped, and assert the new "engine did not apply the constraints" note fires. That path has no coverage today and is the case a backend without Phase 1-3 deployed will produce |

---

## 9. Phase 6: the allocator follow-up

Section 12 of the sizing plan named this: "the allocator's output is exactly the
'exact dimensions' input multi-PTPG wants, so pointing it at the allocator is a
natural follow-up, but it is a separate piece of work with its own measurement."
It belongs in this plan only because pins and allocation interact.

**The unit bug to fix first.** `/api/allocate` rounds `target_width` and
`target_height` to a 0.5 ft grid (`allocate_api.md:117-123`). This pipeline coerces
with `int(round(float(w)))` (`multi_ptpg_pipeline.py:154-167`), and Python 3 rounds
half to even, so a 14.5 ft target silently becomes 14 and can drop a room below its
NBC rectangle minimum. Either request whole-foot targets or scale by 2 into
half-foot integer units on the way in, with the inverse on returned coordinates and
the same scaling on the plot dimensions.

**Where pins help.** Open question 1 of the sizing plan
(`DOOR_CONNECTIVITY_SIZING_AND_POSTPROCESS_PLAN.md:1199-1203`) records that the
flat 0.4 ft wall allowance under-counts a room's loss on an exterior side, and
that "which rooms are exterior is unknown before layout". A pin removes that
unknown for the pinned room specifically: it is guaranteed exterior on its
direction, before anything is dimensioned. A per-room exterior allowance for
pinned rooms is a new allocator request field and the cheapest partial answer to
that question.

**What does not transfer.** The measured correction in `allocate_api.md:128-166`
is that allocated targets must be sent as an **envelope** over `band()` minimums,
not as minimums. That mechanism is post-solve and door-path only. This endpoint has
no bands and no post-processing, so it would consume `target_width`/`target_height`
directly as exact sizes, where areas summing to the plot does not imply an exact
rectangular tiling. The strictness ladder absorbs the mismatch, and T4 already
shows `exact` returning nothing for feasible-area programs. Measure before
shipping.

---

## 10. Phase 7: transport, validation and budget

Everything above is engine-internal. Three layers between the pipeline and the
browser will break or mislead if they are not moved with it.

**10.1 Decide where pin validation lives (G11).** Three layers disagree today.
The Django view (`views/multi_ptpg.py:113-139`) already rejects non-integer rooms,
out-of-range rooms and bad directions with a 400, so the engine's silent-drop
semantics are unreachable in production and `test_multi_ptpg.py` T7's "junk pins
drop non-fatally" only describes the dev bridge, which validates nothing at all
(`local_engine_bridge.py:188-220`). The view is also **stricter** than the engine
in one place: it rejects the spelled-out directions that
`normalize_cardinal_constraints` accepts, so a payload the engine understands is
400'd. Meanwhile `interior_rooms` and `exterior_rooms` get no validation anywhere,
so `interior_rooms: [99]` is a silent no-op while the same index in
`cardinal_constraints` is a 400. Pick one policy, and decide whether the new
contradictory-pin and impossible-pin outcomes are 400s or 200s with warnings. If
they are 400s, note that the client's `errorMessage()` path will flatten them into
a generic failure, which defeats the purpose.

**10.2 Make the budget arithmetic close.** The pipeline defaults to 900 s and
Celery allows 1500 s, but the shipped client sends `time_budget_seconds: 240` and
stops polling at 300 s. The **unpinned** 4BHK already exhausts 240 s with 24
arrangements skipped, and pins make rung 1 strictly slower, so
`if ... time.monotonic() < deadline` at `:522` will be false on the 4BHK and every
rung this plan adds becomes dead code in production. Specify each rung's share as a
fraction of remaining time rather than the whole deadline, and move four numbers
together: the client's `timeBudgetSeconds`, its poll timeout, the Celery
`soft_time_limit`, and the proxy read timeout. Also decide whether the pipeline
returns partial results on an internal deadline hit, because `SoftTimeLimitExceeded`
currently discards every plan already computed.

**10.3 Predict the pinned cost, do not only measure it.** Unpinned, `run_pass`
breaks once it has `limit` plans, so it stops after a few boundaries. Pinned, the
gate sits before the append, so a variant that cannot satisfy the pins walks every
boundary across all three strictness passes, paying placement and compaction each
time. The client also sends `max_floorplans: 0`, which disables the engine's own
round-robin early-skip, so all 107 4BHK arrangements are dimensioned. The unasked
design question: should a **cheap topological pin pre-check** run before
`_pdf_place`, rather than only reordering candidates? That is plausibly the only
change that makes a cap-lifting rung affordable inside 240 s.

**10.4 Cache keys.** `ENGINE_FINGERPRINT` hashes every engine `.py`, so the
`mptpg:` cache self-invalidates on deploy. State the corollary: the acceptance
measurement is always cold-cache and the first user after a deploy pays full
pinned cost against a 30/hour throttle. Separately, `json.dumps(sort_keys=True)`
sorts dict keys but not list order, and `buildCardinalConstraints` emits pins in
`unit.spaces` order, so reordering rooms in the UI produces a different cache key
for an identical constraint set. Canonicalise the pin list before hashing.

**10.5 Prove pin indices survive `door_connectivity`.** Pins are
`(client_index, dir_idx)` and are applied to the **post**-`door_connectivity`
graph, while separating-triangle removal populates `mergednodes` and can append
rooms. If it ever renumbers or merges a client room, the geometric gate validates
the wrong rectangle and reports success. The invariant is believed to hold, since
normalization is bounded by `len(nodes)` and the ring is applied before the
deepcopy while the matrix still has exactly that many rows, but it should be
asserted in a test rather than assumed. Related: a synthetic `Room N (added)` is
treated like any other room by the strip test, so an engine-invented rectangle can
reject an otherwise-satisfying plan.

---

## 11. Acceptance

Measure on the three shipped programs (2BHK, 3BHK, 4BHK) through the real client
against the local bridge, at the frontend's `time_budget_seconds: 240` and
`best_effort`, with and without pins. The existing baselines to beat are in
`multi_ptpg_api.md:309-315`: 2BHK 13 arrangements / 18 plans / 14 s with one E pin,
3BHK 41 / 49 / 76 s, 4BHK 107 / 90 / 240 s with 24 arrangements skipped.

Acceptance:

The acceptance criteria are ordered by the Section 1 priority, so 1 and 2 are the
ones that decide whether this ships.

1. **Pins hold.** On the sparse 13-room unit with three pins, plans are returned
   that satisfy the pins, where today the endpoint reports `ignored`. This is the
   headline number and it is the same one the door path's ring was measured on.
   Target the door path's result on that unit: 11 of 11 satisfying.
2. **Adjacencies are not spent to get there.** On every shipped program with pins,
   the best plan keeps at least as many of the user's adjacencies as the best plan
   from the same program **without** pins. This is the criterion that distinguishes
   the ring from the pin-blind search, which buys pins by deleting boundary edges,
   and it is the one to watch if someone later proposes reverting Phase 3.
3. `cardinal.ignored` becomes rare. Record how often each ladder rung fires across
   the three programs; rung 5 firing on a satisfiable brief is a defect now, not a
   documented degradation.
4. No shipped program loses arrangements on a **pin-free** request. Phases 1, 2, 4
   and 5 must be invisible to an unpinned batch, and Phase 3 must not run at all
   when there are no pins.
5. Arrangement count under pins is **measured and reported**, in either direction.
   Section 2 argues the ring could plausibly increase it (triangulations of a
   polygon) or decrease it (Stage 1 disabled), and nobody knows which. A drop is
   acceptable per the priority; an unreported drop is not.
6. The mirror-order pin set returns satisfying plans (G2 regression).
7. Wall-clock does not regress on the pinned 4BHK. Phase 1.1 and Phase 2 should
   both **improve** it, since fewer infeasible boundaries and variants reach the
   compactor.

---

## 12. Out of scope

- **`stacked_oneconnected_floorplans`** (`api.py:998-1204`), the door path's
  two-component composition that reuses the cardinal machinery as a fusion tool. It
  is door-path only and there is no evidence this endpoint needs it.
- **The `count == 1` door path**, which applies pins and the ring but never
  verifies geometrically and has no ladder (`api.py:1368-1376`). Documented as
  "effective for `count > 1`", so it is a known unguarded corner, not a discovery,
  and it is not this endpoint.
- **The suspected ring-edge door semantics on the door path.** Reading
  `inputgraph.py:360, 512-516` against `minimum_dimensioning.py:257-260` suggests
  ring edges reach the solver as black (door) edges with a 2 ft overlap constraint,
  contradicting `apply_cardinal_ring`'s docstring claim that no doors are placed on
  them. It is unverified at runtime and it is a door-path question; it matters here
  only if Phase 3 ships, and Phase 3 excludes ring edges from the firewall anyway.
- **The sparse-graph root cause.** The shipped programs carry roughly half the
  edges a rectangular dual wants. Section 12 of the sizing plan already declared
  this out of scope and the reasoning has not changed: per-room tuning does not
  transfer between unit types.

---

## 13. Open questions for the implementer

Raise these; do not guess and bury the answer in code.

~~1. How much arrangement variety is a pin worth?~~ **Answered 2026-08-01 by the
product owner and recorded in Section 1: pins outrank adjacency, adjacency
outranks arrangement count.** Left visible rather than deleted, because the first
draft of this plan chose the opposite default and the reasoning for the reversal
is worth keeping.

1. **Should a partially satisfied request rank above an unpinned one?** Phase 2
   returns plans holding 2 of 3 pins. The Section 1 priority implies yes, they
   outrank plans holding 0, but the client's sort keys off a boolean
   (`multiPtpg.ts:394`) and would need a count. Confirm the ordering is
   pins-held descending, then adjacencies-kept descending, before building it.
2. **Does "always satisfy the pins" extend to overriding a plot rejection?** Plot
   dimensions are a reject filter on this endpoint and the check runs before the
   cardinal gate (`ptpg_floorplanner.py:880-881` inside `_pdf_place`). A layout
   that holds every pin but overflows the plot is discarded today. The designer
   sends `plot_width: -1`, so this is dormant for the shipped client and live for
   API callers.
3. **Is an impossible pin an error or a warning?** Section 6 item B introduces a
   third outcome, "this graph cannot put that room on an outer wall at all". A 400
   is the honest status code and the worst user experience, since the client
   flattens error envelopes. A 200 with an empty-ish catalogue and a named warning
   is kinder and less precise. This one is a product call, not an engineering one.
4. **Should the pinned pre-check be topological or geometric?** Section 10.3 asks
   whether to reject a boundary on arc membership before paying for placement. It
   would make the ladder affordable, but it contradicts the principle stated at
   `ptpg_floorplanner.py:254` that arcs are topological and only rectangles are the
   truth, so a cheap pre-check can reject a boundary that would in fact have placed.
   Decide whether that principle is absolute or a default.
3. **Is the recess allowance right?** It is the smallest room dimension **in that
   layout** (`ptpg_floorplanner.py:222`), so a plan containing a small toilet gates
   more strictly than a plan of uniformly large rooms, and two plans with identical
   pinned-room geometry can disagree. Defensible, and worth confirming against real
   output before it is copied into the client for Phase 4.5.
4. **Does the failsafe path report a boundary it did not build?** The
   positions-seeded failsafe reports `boundaries[0]` regardless of what it placed
   (`ptpg_floorplanner.py:1041`), so a client drawing the N/E/S/W arc lists could
   contradict the geometry the cardinal gate actually validated.
