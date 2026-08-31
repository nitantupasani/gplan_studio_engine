# Engine plan: the structural module

STATUS 2026-08-31, fourth entry (structural review fix wave): the confirmed
review ledger is closed except for two explicit policy choices. The review
record contains 90 findings: 9 critical, 33 major, 41 minor, and 7 notes. The
fix wave regression-pinned 88 of them. B2 is NOT FIXED pending a choice about
frontend-versus-adapter rotation ownership. B11 is NOT FIXED pending a choice
about the default infill idealization; explicit modes and the current default
are disclosed and tested. Five deeper re-read clusters and every PRINT row
remain owed. Six `REVIEW_PENDING.md` markers now retain 21 rows: eight OWED
rows representing those five clusters, two policy-open rows, seven PRINT rows,
and five FABLE-BUILT provenance rows, with the diaphragm row counted in both
the OWED and policy-open sets.

The independent verifier state is 1709 passed, 0 failed in the full structural
engine suite, 181/181 in the root API battery, and 73/73 in backend structural
smoke. C1, C4, and C7 pass end to end. The compact `building_3storey` response
is 1,499,992 canonical JSON bytes. Repeated `housing_masonry` output is
byte-identical at 170,600 bytes with SHA256
`872cce570dd4f04d2f04265511a639aecf156244da93705bbf5ac52411fbc493`.
Fresh processes agree on structural fingerprint `st-5001740edadf76e9`.

Fixture counts use the order
`storeys/rooms/walls/cores/columns/beams/slabs/bands/lintels/footings/design`:

| fixture and system | count vector | base shear (kN) |
|---|---:|---:|
| `plan` / `rc_frame` | `2/16/48/0/48/110/26/0/26/24/208` | 213.306467 |
| `building` / `rc_frame` | `3/6/32/2/177/422/130/0/0/46/781` | 1060.906699 |
| `housing` / `rc_frame` | `2/10/22/1/62/142/25/0/4/26/259` | 214.713586 |
| `housing_masonry` / `load_bearing_masonry` | `2/20/20/1/8/0/0/2/0/7/30` | 233.300131 |

The masonry base shear is about 1.55710 times, or 55.71 percent, above the
recorded pre-F1 value of 149.83 kN. The shared test battery changed only four
B25 numeric expectations in `test_masonry_pipeline.py`:
`224.73910327680005` to `233.30013128755218`, `0.0224` to `0.02329`,
`404.53038589824007` to `419.94023631759393`, and `231.9801454368` to
`240.83081513395234`. `test_api_pipeline.py` was unchanged. Cantilever
root-edge torsion remains a disclosed v1 limitation, not a failed C7 result.

The deployment record now treats structural cache keys as content-addressed
over Python plus every sorted raw YAML table byte and requires matching web and
worker fingerprints. Normal rebuilt deployments require no Redis flush; db 0
must never be flushed. VM planning now includes both Redis db 1 response bytes
and `django-db` Postgres `TaskResult` rows, a six-hour cleanup cadence, exactly
one beat scheduler, and up to approximately 30 hours of retained rows. Nothing
was committed, pushed, or deployed.

STATUS 2026-08-30, third entry (wave 9, the two gaps and the paperwork): the
first wave that added no feature. It closed both gaps the entry below records
as open, read the first slice of the data tables back against the printed
standards, and wrote the deploy rehearsal on paper. Four tracks ran in
parallel. Package battery 1580 passed, 0 xfailed in 76 to 87 s over two runs;
root battery 181 passed, 0 failed. Nothing was committed, pushed or deployed.

GAP 1 IS CLOSED. `design/rcc/footings.py` (2745 to 3654) gained
`design_strip_footing`, with `strip_geometry_from_model` in `design/rcc/__init__.py`
(708 to 843) reading the placed rectangle and the takedown's wall line ledger.
It sizes the strip width on bearing and returns either a plain concrete spread
footing checked against the IS 456 Cl 34.1.3 projection rule or a reinforced
strip on a 1 m run with transverse steel, nominal distribution steel and the
shear and flexure checks that sized it, `governing_check` naming whichever
decided the section. It never raises: a strip with no wall or no load is refused
by name. `api.py` (3418 to 3466) routes a footing of kind `strip` BEFORE the
column loop, since it is keyed by the walls it carries and not by a stack.
`UNDESIGNED_FOOTING_KINDS` is down to `strap` alone. `model.py` (1551 to 1556)
gained the two NOTE codes that the borrowed disclosure needed:
`N_ELEMENT_UNDESIGNED` "placed and quantified, but no designer reached it",
which `_disclose_undesigned` now uses instead of `N_SHAFT_WALL_UNDESIGNED`, and
`N_PLAIN_CONCRETE_FOOTING` "footing adequate as plain concrete; no reinforcement
is required", so a reader can tell "designed, needs no steel" from "nobody
designed it". Measured on `housing_masonry.json`: 7 of 7 strip footings
designed, `undesigned_count` 0, all seven plain concrete and disclosed as such.

GAP 2 IS CLOSED. The density calibration bands are per SYSTEM now, out of a new
fifteenth data table `GPLAN/structural/data/density_bands.yaml` (181), and
`quantities.py` (2638 to 2966) resolves them against the take-off's system:
`rc_frame` unchanged at 2.50 to 7.00 kg/m2 and 0.10 to 0.20 m3/m2,
`load_bearing_masonry` measured on this repository's own runs, `confined_masonry`
and `mixed` interpolated and LABELLED `unmeasured` rather than passed off as
measurements. A third check joined the two, walling volume per m2. Every row
carries `basis` and `uncertainty`, the message names the system it judged, a
null band is a deliberate silence reported as one, an unknown system falls back
to the frame row and SAYS SO in the response, and `boq.density_checks` carries
the whole verdict whether or not a ladder entry was raised. Measured: the
masonry house is inside all three bands and raises neither warning. ONE RESIDUE,
open on purpose: `W_MASONRY_DENSITY_BAND` is not in `model.REGISTRY`, so the
third check reports with `disclosure_code_registered: false` and raises nothing
on the ladder. Registering it is two lines in `model.py` plus dropping
`pending_registration` from the table, and the table's own comment carries the
exact text.

PRINT VERIFICATION STARTED, 18 of 76 done. The record is
`GPLAN_Revamp/structural_research/TABLE_VERIFICATION.md`. There are 76
`verify: "print"` DATA keys, not the 83 quoted before, which counted seven
header-comment mentions of the phrase as well; 18 are settled and now carry a
`verified` string naming the standard, the table and the date, 58 still stand,
and six more hide in the nested `verify:` block of `is13920.yaml` that a literal
search does not find. Seven transcribed values were WRONG and six were
corrected: four blocks of IS 4326:1993 (Table 4 openings, Table 6 band steel,
Table 7 vertical steel, and the source line, which cited Table 1 for what is
printed as Table 2) and two of IS 1905:1987 (Table 8 basic compressive stress,
Table 10 shape modification factor). TWO OF THOSE MAKE THIS ENGINE LESS
CONSERVATIVE than it was and a licensed engineer should re-check them first: the
printed IS 1905 Table 8 stresses are higher than what was in the file, so a wall
that used to need a 10 N/mm2 unit in H2 mortar now passes in M1, and the printed
IS 4326 Table 4 opening limits are looser. Eleven test expectations across six
batteries moved with the values, and `tests/vectors/sp20/wall_examples.yaml`
(201 to 208) moved with Table 8, being hand worked against this repository's own
tables rather than printed vectors. Five discrepancies were found and
deliberately NOT corrected, each with its reason recorded; the IS 1893
(Part 1):2016 Table 9 masonry R factors are the one to settle first.

DEPLOY REHEARSAL WRITTEN, NOT RUN.
`GPLAN_Revamp/structural_research/DEPLOY_RUNBOOK.md` (1006) covers what ships
from each tree, the submodule pin bump and the shallow-fetch gotcha on the VM,
rebuild-never-restart, migrations, the post-deploy CORS, throttle and body-size
checks, a seven step smoke sequence against the deployed API, and rollback per
tree. It was written by READING the repositories: no git, gcloud or ssh command
was run to produce it, and every VM command in it is written as it runs on the
VM shell. Its section 1.1 was written before the sibling tracks landed, so it
lists the two gaps above as shipping as-is; they are closed. The two quality
gates it names do stand: the fable review pass is OPEN and explicitly DEFERRED
by the user for now, and the print verification is 18 entries in of 76.

The 37 new tests, 1543 to 1580, are all in three batteries:
`test_design_footings` +13, `test_quantities` +21, `test_masonry_pipeline` +3.
No frontend or backend file was touched, so the sibling-repo figures in the
entry below still stand.

STATUS 2026-08-30, second entry (waves 5 to 8, and the measured run): the
module is feature complete on ALL THREE surfaces.

Waves 5 and 6 are the entry below, with two things it did not say. Wave 5 built
the tail and the orchestrator: `quantities.py` (2530 lines as it landed, 2638
today), `report.py` (1340, now 1426), `api.py` with `run_layout`, `run_design`,
`run_check` and `run_options`, and the shipped
`GPLAN/structural/schema/structural_response.schema.json`. Wave 6 then fixed
SEVEN source defects that the first true end-to-end runs exposed in modules that
were green under their own unit batteries: worst was `run_rcc_design` calling
`design_slab` and `design_footing` with the wrong signatures, so every slab and
every footing in the package had been returning a failed design and combined
footings were never designed at all. Also fixed there: `DisclosureLog`
collapsing distinct messages under one code, `storey_weight_rows` on the load
model so seismic no longer forces a second takedown pass, `build_live` honouring
a live load override, and `package_data` in `setup.py`, without which an
installed package would carry the Python and none of the YAML tables or the
schema. The compact and full detail regime was documented in the same wave, and
a load-bearing masonry fixture proved the masonry branch end to end.

Waves 7 and 8 took it out of this repo. The Django half landed in the
sibling repo `gplan_backend`: four views, the two PINNED Celery task names, urls
as `re_path` with an optional trailing slash so both forms answer as they do on
the bridge, the three throttle scopes, Redis dedup folding `ENGINE_FINGERPRINT`
and `structural_fingerprint()`, and `smoke_test_structural.py` at 55 passed,
0 failed. The frontend landed in `gplan-building-designer`: the typed client
with the SINGLE client-side down-conversion to the existing `StructuralGrid`
type, the building page Structure action with its 2D and 3D layers, the summary
store field and the score and warnings drawer, the assistant `design_structure`
tool, the housing Structure pill with a read-only overlay and a session-only
cache, IFC footings and designed sections through to the Python worker, and the
measure battery. `npx tsc --noEmit -p tsconfig.app.json` exits 0, the structural
battery is 188/188, the IFC battery passes including the new footing assertions.

Also in this pass: the three defects the masonry battery had pinned as xfail are
closed AT THE SOURCE, not in the test (masonry wall design coverage keying, the
delivered system as the single source of truth for the report, and confined tie
columns exempted from the IS 13920 frame geometry minimum that IS 4326 does not
impose). The package battery was 1543 passed, 0 xfailed in about 84 s on the day
of this entry (1580 today, see the entry above), and the root battery 181
passed, 0 failed.

MEASURED end to end through this bridge over HTTP, door_connectivity plans,
default compact detail, all four successful:

| run | system | cols | beams | slabs | bearing walls | footings | score | layout | design | design KB | summary KB |
|---|---|---|---|---|---|---|---|---|---|---|---|
| 2BHK leading plan | rc_frame | 20 | 55 | 8 | 0 | 20 | 85 | 0.03 s | 0.87 s | 339.3 | 46.1 |
| 3BHK leading plan | rc_frame | 24 | 69 | 12 | 0 | 24 | 79 | 0.02 s | 1.00 s | 340.5 | 53.6 |
| housing 2 storey | rc_frame | 62 | 142 | 25 | 0 | 26 | 75 | 0.05 s | 2.01 s | 743.2 | 106.0 |
| housing masonry | load_bearing_masonry | 8 | 0 | 0 | 14 | 7 | none | 0.04 s | 0.08 s | 133.7 | 16.6 |

Every summary at these sizes fits the 150 KB client store budget; the 202 KB
figure recorded earlier was the 788 element building fixture, which does not.
The detail regime, measured on the fixtures: the plan is 2.93 MB full and
0.63 MB compact, housing 3.41 MB and 0.76 MB, the 775 member building 8.45 MB
and 1.48 MB. Full detail returns the old payload plus about 3 KB of regime
metadata.

TWO GAPS the measured run exposed, both open AS OF THAT WAVE and both CLOSED by
wave 9 in the entry above; neither ever blocked a run:

1. On the masonry path 7 footings reached no designer. Strip footings under
   bearing walls are placed and quantified but never designed, and
   `api._disclose_undesigned` reports them under `N_SHAFT_WALL_UNDESIGNED`,
   whose registry text means something else. Two fixes, independent: design
   them, and add a registry code that names the condition so the disclosure
   stops borrowing one.
2. The steel and concrete density calibration bands are RC frame numbers and
   they fire on every masonry house (measured: 1.02 kg/m2 against a 2.50 to
   7.00 band, 0.020 m3/m2 against 0.10 to 0.20). They must become system aware
   or a correct masonry design will always read as a wrong one.

OPEN, in order, AS OF THAT WAVE and superseded by the entry above: the deploy
rehearsal (engine pin bump and image rebuild, then backend rebuild, THEN
frontend: the backend consumes this engine as a submodule pinned to a SHA that
predates this package, so a frontend shipped first gets 404 on all four routes),
now written on paper and still not run; the print verification of every
`verify: "print"` entry in `GPLAN/structural/data/` against IS 456, IS 875,
IS 1893, IS 1905, IS 4326, IS 13920, IS 6403, SP 16 and SP 20, now 18 of 76
done; the fable review pass tracked in
`GPLAN_Revamp/structural_research/FABLE_REVIEW_QUEUE.md` with `REVIEW_PENDING.md`
markers in the package folders, which must all be deleted before the package is
first committed, still open and now deferred by the user; the two gaps above,
now closed; then the phases below.

STATUS 2026-08-30, first entry (wave 6, the engine surface): the module is
feature complete ENGINE SIDE and its public surface is wired. `GPLAN/api.py`
gained four thin `Documents` methods
(`layout_structure`, `design_structure`, `check_structure`,
`structural_options`), each importing `GPLAN.structural.api` lazily INSIDE the
method so a structural package that fails to import cannot take `get_floorplans`
down with it. `local_engine_bridge.py` gained the four routes in both their
trailing-slash and bare forms (finding 37), registered before the
`/api/generate/<shape>` catch-all: options and layout and check answer 200
synchronously in the engine envelope, design is fake-async exactly like the
generate routes (computed inline, stored under a uuid in `_results`, answered
202 so the existing `GET /api/task/<id>/` serves it). A request the engine will
not run comes back as HTTP 400 carrying the engine's own error envelope
verbatim, so the caller keeps the field name AND the disclaimer; an exception is
500, and every engine call sits inside the route body so a broken structural
package cannot kill an unrelated bridge route. Two new documents landed with it:
`documentation/structural_api.md` (request, response, algorithm, options, tests
- every field name generated by running the pipeline, not transcribed from the
spec) and this plan. New battery `test_structural_api.py` at the repository
root: 181 checks over the three shipped fixtures, green. Package battery
1514 passed, 3 xfailed in 70 s (the count stated at the start of this wave was
1448; the difference is tests added by the sibling agents working inside the
package at the same time, none of them in a file this work touched). Measured
per fixture, in process at full detail: layout 0.03 to 0.09 s, design 1.6 s
(plan), 10.8 s (building), 3.2 s (housing), which is why layout is the
synchronous endpoint and design is the queued one.

Those counts and timings are the dated observation of that wave and are
superseded by the entries above: the three xfails are closed, the battery was
1543 passed and 0 xfailed on the day of the second entry and is 1580 today, and
the timings over HTTP at the compact default are the table above.

## What this is

The structural module turns a GPLAN floorplan, Building or HousingDesign into a
structural scheme: grid, frame or bearing walls, loads, analysis, code-checked
member design, quantities and a clause-traceable report, all to the Indian
standards. It lives at `GPLAN/structural/` and is reached through four public
entry points and no others.

The full corpus is OUTSIDE this repository, in `GPLAN_Revamp/structural_research/`:

```
structural_research/specs/                nine submodule specifications
  01-model-adapters.md .. 09-frontend.md  (08-api-backend.md is the HTTP surface)
structural_research/CRITIC_RESOLUTIONS.md 42 numbered resolutions plus the eight
                                          frozen hand-off contracts. NORMATIVE
                                          over the specs: where they disagree,
                                          the resolution wins.
structural_research/TABLE_VERIFICATION.md which values in structural/data/*.yaml
                                          were read back against the printed
                                          standard, which were corrected, and
                                          which discrepancies are still open.
                                          Read it before changing a data table.
structural_research/DEPLOY_RUNBOOK.md     the deploy rehearsal on paper, tree by
                                          tree, with the smoke sequence and the
                                          rollback. Nothing in it has been run.
```

Read the resolution before changing a behaviour it names. Findings are cited by
number in the code comments and in `documentation/structural_api.md`, and the
eight frozen contracts (adapters, placement, loads and analysis, design,
quantities and report, wire schema, HTTP surface, frontend) are cross-module:
changing one is a change to every spec it touches.

In this repository:

```
GPLAN/structural/                  the module
GPLAN/structural/api.py            the four entry points and the fixed sequence
GPLAN/structural/schema/           structural_response.schema.json, shipped
GPLAN/api.py                       the four Documents methods (thin delegation)
GPLAN/local_engine_bridge.py       eight routes for local dev (four, both forms)
GPLAN/documentation/structural_api.md   the API reference
GPLAN/structural/tests/            the package battery
GPLAN/test_structural_api.py       the root battery, at the caller's altitude
```

## Phases

| Phase | Scope | Status | Verified by |
|---|---|---|---|
| v1.0 model and adapters | `StructuralModel` (SI metres, y-down, storey 0 = ground, registry disclosure codes), plan / building / housing adapters, opening synthesis, wire schema | DONE | `tests/test_model_roundtrip.py`, `test_adapter_plan.py`, `test_adapter_building.py`, `test_adapter_housing.py`, `test_fixtures.py` |
| v1.1 grid and placement | axis extraction, frame placement (columns, primary and secondary beams, slabs, plinth beams, lintels over infill), cores, layout score with `score_version` | DONE | `test_grid.py`, `test_placement_frame.py`, `test_placement_cores.py` |
| v1.2 loads and analysis | IS 875-1 dead, IS 875-2 imposed by occupancy, IS 1893 equivalent static, IS 875-3 wind, IS 456 combinations, tributary takedown, rigid diaphragm | DONE | `test_loads_gravity.py`, `test_codes_loads.py`, `test_takedown.py`, `test_lateral.py` |
| v1.3 RC design | beams, columns, slabs, footings to IS 456 / IS 13920 / IS 6403, detailing, the strain-plane interaction fallback (no `structuralcodes` in v1, finding 31) | DONE | `test_design_beams.py`, `test_design_columns.py`, `test_design_slabs.py`, `test_design_footings.py`, `test_codes_is456.py`, `test_codes_13920_6403.py` |
| v1.4 masonry | `choose_system`, bearing-wall placement, bands and lintels, IS 1905 and IS 4326 design. Brought forward from v2: the system decision cannot be honest without it | DONE 2026-08-30: the strip footing gap is closed, 7 of 7 designed on the masonry fixture | `test_placement_masonry.py`, `test_design_masonry.py`, `test_codes_masonry.py`, `test_masonry_pipeline.py` |
| v1.5 foundations and quantities | `layout_foundations` (pads, strips, combined, straps) from takedown service loads, IS 1200 take-off, bar bending schedule, priced bill, the report and the disclosure ladder | DONE | `test_foundations.py`, `test_quantities.py`, `test_report.py`, `test_trace.py` |
| v1.6 engine API | `run_options` / `run_layout` / `run_design` / `run_check`, the fixed orchestration sequence, the one bounded referral re-pass, validation, determinism, the compact and full detail regime | DONE | `test_api_pipeline.py`, `test_wave6_fixes.py` |
| v1.7 public surface | the four `Documents` methods, the eight bridge routes, `documentation/structural_api.md`, this plan, the root battery | DONE 2026-08-30 | `test_structural_api.py` (181 checks) |
| v1.8 Django | `gplan_apis/views/structural.py`, `tasks/structural.py` with the PINNED names `gplan_apis.tasks.structural_design_task` and `structural_check_task`, urls as `re_path` with an optional trailing slash, throttle scopes `structural_layout` 300/hour, `structural_design` 60/hour, `structural_check` 120/hour, Redis dedup on `structural_fingerprint()`, 413 over `max_body_bytes`, `smoke_test_structural.py` | DONE 2026-08-30 (sibling repo `gplan_backend`) | `smoke_test_structural.py` (55 passed, 0 failed) |
| v1.9 frontend | `src/services/engine/structural.ts` exported through the `gplanApi` barrel, the single client-side down-conversion to the seed `StructuralGrid`, the building page Structure action with its 2D and 3D layers, the assistant `design_structure` tool, the housing pill with results session-cached and never in localStorage, IFC footings and designed sections, all tags rendered, refusals via `pushNotice` | DONE 2026-08-30 (sibling repo `gplan-building-designer`) | `check:structural` (188/188), `check:ifc`, `measure:structural`, `tsc --noEmit` clean |
| deploy | engine pin bump and image rebuild, then backend rebuild, THEN frontend. The order is load bearing: the backend's engine submodule is pinned to a SHA that predates this package | REHEARSED ON PAPER 2026-08-30, NOT RUN | `GPLAN_Revamp/structural_research/DEPLOY_RUNBOOK.md` |
| v2 FE analysis | `analysis/frame_fe.py` is an ADAPTER today, not a solver: the takedown is the v1 analysis. Open question, to be recorded here when decided: PyNite as a pinned dependency versus a hand-rolled numpy stiffness solve | ADAPTER ONLY | `test_frame_fe.py` |
| v2 steel | `design/steel/sections.py` carries the IS 808 section tables; no IS 800 member design exists yet | TABLES ONLY | `test_data_catalogs.py` |
| v3 EC-NL | the `EC-NL` code profile via Blueprints, for the Dutch work. `params.code_profile` already refuses anything but `IS`, so the request contract does not change when it lands | NOT STARTED | pending |
| v3 MCP | the backend MCP server gains a `structural_design` tool wrapping the same `Documents.design_structure` call with the design request schema. No v1 work | NOT STARTED | pending |

## Invariants that outlive any phase

- **One public surface.** `run_layout`, `run_design`, `run_check`, `run_options`
  and nothing else (finding 17). `place` and `analyze` are internal steps these
  four sequence. The Celery task names are pinned at deploy and must never be
  renamed.
- **The fixed sequence.** `run_design` is the single orchestrator: adapt,
  validate, place, load model, gravity takedown, `layout_foundations`,
  diaphragm, member design, at most ONE bounded referral re-pass, quantities,
  report (finding 18). `run_layout` runs the same prefix and stops after
  placement, which is why the two never disagree on geometry.
- **No sized footing in a layout response** (finding 18): a footing is sized
  from a takedown layout never runs, so layout ships unsized markers.
- **The disclaimer on every path** (finding 29), refusals and validation
  failures included, verbatim, guarded by `report.with_disclaimer`.
- **Determinism.** Sorted iteration, no RNG, no wall clock inside a computed
  value. Two identical requests must produce byte-identical JSON: the backend's
  Redis dedup key rests on it, and the root battery asserts it.
- **Units.** Feet and y-down on the wire, mm for section dimensions, SI for
  engineering quantities, and SI metres internally after a single conversion at
  ingest. Every numeric key carries its unit suffix.
- **Registry codes only.** Every disclosure carries a code from
  `model.REGISTRY`, upper-snake `E_*` / `W_*` / `N_*`, defined once and carried
  unchanged from producer to report to API to the frontend tag key (finding 8).
- **Disclose, never hide.** A member that fails is a `SUCCESS` response with the
  failure named, its check, its utilization and its clause. `ERROR` means the
  pipeline could not run.

## Running it

```
python -m pytest GPLAN/structural/tests -q     # 1580 passed, 0 xfailed, 76 to 87 s
python test_structural_api.py                  # 181 passed, 0 failed
python GPLAN/local_engine_bridge.py            # the eight routes on :8027
```

`test_structural_api.py` is a SCRIPT battery in this repo's own style, like
`test_multi_ptpg.py`. It exposes no `test_*` functions, so pytest collects
nothing from it and proves nothing. Run it with `python`.

The two sibling repos carry the rest: `python smoke_test_structural.py` in
`gplan_backend` (55 passed, 0 failed) and `check:structural` (188/188) plus
`check:ifc` in `gplan-building-designer`, both of which need a global esbuild
and are invoked through `npx` rather than `npm run` on this machine.

The detailed status file is OUTSIDE this repository, at
`GPLAN_Revamp/structural_research/IMPLEMENTATION_STATUS.md`. It is the long
form: this file is the short pointer with the phase table. Keep the two
consistent, and update this file with every push that changes the module, per
the standing document-and-push rule.
