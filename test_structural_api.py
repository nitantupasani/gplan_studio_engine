"""Root battery for the structural engine surface: the four Documents methods.

`GPLAN/structural/tests/` pins every stage of the module from the inside. This
battery stands where a caller stands: it imports `GPLAN.api.Documents` and
nothing else from the package, runs the four public methods over the three
shipped fixtures, and asserts the promises the HTTP layer is built on.

  * the envelope shape - `{status, message, response.Documents.structural[],
    batch_summary, disclaimer}` on every path, `structural` ALWAYS a list;
  * the verbatim disclaimer on EVERY path, refusals included (finding 29):
    options, layout, design, check, a validation failure, and a pipeline that
    stopped mid-run and came back as a partial;
  * determinism - two identical calls are byte-identical, because the backend
    hangs a Redis dedup key on exactly that;
  * layout is fast - it is the synchronous endpoint, so it carries the spec's
    5 s hard budget while design is the one that goes through Celery.

No Flask server is started and no HTTP client is used: the routes in
`local_engine_bridge.py` are thin wrappers over these same methods, and a
battery that boots a server tests the server. Run from the repository root:

    python test_structural_api.py
"""

import copy
import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from GPLAN.api import Documents

FIXTURES = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                        "GPLAN", "structural", "tests", "fixtures")

#: The synchronous endpoint's hard budget, seconds (spec 08 section 1: under
#: 1 s target, under 5 s hard). Measured locally at 0.05 - 0.25 s per fixture;
#: this is a guard against a regression, not a target.
LAYOUT_BUDGET_S = 5.0

PASSED = []
FAILED = []


def check(name, condition, detail=""):
    if condition:
        PASSED.append(name)
        print("  PASS  %s" % name)
    else:
        FAILED.append((name, detail))
        print("  FAIL  %s %s" % (name, detail))


def load(name):
    with open(os.path.join(FIXTURES, name), "r") as handle:
        return json.load(handle)


def payloads():
    """The three shipped fixtures as request payloads, one per source."""
    return {
        "plan": {"source": "plan", "plan": load("plan_2bhk.json"), "storeys": 2},
        "building": {"source": "building",
                     "building": load("building_3storey.json")},
        "housing": {"source": "housing", "housing": load("housing_2storey.json")},
    }


PAYLOADS = payloads()

# The pipeline runs are the expensive part (design is 1.5 - 10 s per fixture),
# so each fixture runs once and every assertion below reads the cached answer.
LAYOUTS = {}
DESIGNS = {}


def entries(envelope):
    return envelope["response"]["Documents"]["structural"]


def disclaimer_ok(text):
    """The notice, verbatim. Compared through the module that owns it so a
    reworded disclaimer fails here instead of drifting silently."""
    from GPLAN.structural import report as R
    return R.disclaimer_matches(text)


def envelope_shape(label, envelope, expect_status=None):
    """Every rule the wire envelope states, asserted once per response."""
    ok = (isinstance(envelope, dict)
          and envelope.get("status") in ("SUCCESS", "ERROR")
          and isinstance(envelope.get("message"), str)
          and isinstance(envelope.get("response"), dict))
    check("%s envelope is {status, message, response}" % label, ok,
          str(sorted(envelope))[:120] if isinstance(envelope, dict) else str(type(envelope)))
    if not ok:
        return
    if expect_status is not None:
        check("%s status is %s" % (label, expect_status),
              envelope["status"] == expect_status, envelope["status"])

    documents = envelope["response"].get("Documents")
    check("%s carries response.Documents" % label, isinstance(documents, dict))
    if not isinstance(documents, dict):
        return
    check("%s Documents.structural is always a list" % label,
          isinstance(documents.get("structural"), list),
          str(type(documents.get("structural"))))
    check("%s schema_version is structural-1.1" % label,
          documents.get("schema_version") == "structural-1.1",
          str(documents.get("schema_version")))
    check("%s engine_fingerprint is stamped" % label,
          str(documents.get("engine_fingerprint", "")).startswith("st-"),
          str(documents.get("engine_fingerprint")))

    summary = documents.get("batch_summary") or {}
    check("%s batch_summary counts every entry" % label,
          summary.get("plans") == len(documents["structural"])
          and (summary.get("ok", 0) + summary.get("warnings", 0)
               + summary.get("refused", 0)) == summary.get("plans"),
          json.dumps(summary))

    check("%s round trips through JSON" % label,
          json.loads(json.dumps(envelope)) == envelope)


def disclaimer_everywhere(label, envelope):
    """Finding 29: the notice at the envelope AND on every entry, always."""
    check("%s carries the top-level disclaimer" % label,
          disclaimer_ok(envelope.get("disclaimer")),
          repr(envelope.get("disclaimer"))[:80])
    missing = [index for index, entry in enumerate(entries(envelope))
               if not disclaimer_ok(entry.get("disclaimer"))]
    check("%s carries the disclaimer on every entry" % label,
          not missing, "entries %s" % missing)


# ---------------------------------------------------------------------------
# T1: structural_options
# ---------------------------------------------------------------------------

def t1_options():
    print("\nT1: Documents.structural_options - static capability discovery")
    started = time.time()
    envelope = Documents.structural_options()
    elapsed = time.time() - started
    envelope_shape("T1 options", envelope, expect_status="SUCCESS")
    disclaimer_everywhere("T1 options", envelope)

    rows = entries(envelope)
    check("T1 options answer is one entry", len(rows) == 1, str(len(rows)))
    if not rows:
        return
    documents = rows[0]

    for key in ("sources", "systems", "code_profiles", "scopes",
                "seismic_zones", "soils", "grades", "spans", "limits",
                "endpoints", "defaults", "disclosure_codes"):
        check("T1 options publish %s" % key, key in documents,
              str(sorted(documents))[:200])

    check("T1 sources are the four the engine dispatches on",
          documents["sources"] == ["plan", "building", "housing", "model"],
          str(documents["sources"]))
    check("T1 the frozen system vocabulary is on the wire (finding 26)",
          documents["systems"] == ["auto", "rc_frame", "load_bearing_masonry",
                                   "confined_masonry"]
          and "masonry" not in documents["systems"],
          str(documents["systems"]))
    check("T1 the endpoint modes are declared",
          documents["endpoints"] == {"layout": "sync", "design": "async",
                                     "check": "auto", "options": "sync"},
          json.dumps(documents["endpoints"]))

    # the limits a client reads must be the constants the pipeline enforces,
    # imported rather than a second copy of the same numbers
    from GPLAN.structural import api as engine
    limits = documents["limits"]
    mismatched = sorted(key for key in engine.LIMITS
                        if limits.get(key) != engine.LIMITS[key])
    check("T1 limits are the engine's own constants, not a second literal",
          not mismatched, str(mismatched))
    check("T1 the cantilever caps are METRES, 2.0 and 2.5 (finding 3)",
          limits["max_cantilever_m"] == 2.0
          and limits["refuse_cantilever_m"] == 2.5,
          json.dumps({k: limits[k] for k in
                      ("max_cantilever_m", "refuse_cantilever_m")}))
    check("T1 options are cheap", elapsed < 2.0, "%.3f s" % elapsed)


# ---------------------------------------------------------------------------
# T2: layout_structure over the three fixtures
# ---------------------------------------------------------------------------

def t2_layout():
    print("\nT2: Documents.layout_structure - the three shipped fixtures")
    for name in ("plan", "building", "housing"):
        started = time.time()
        envelope = Documents.layout_structure(copy.deepcopy(PAYLOADS[name]))
        LAYOUTS[name] = (envelope, time.time() - started)

    for name in ("plan", "building", "housing"):
        envelope, elapsed = LAYOUTS[name]
        label = "T2 %s layout" % name
        envelope_shape(label, envelope, expect_status="SUCCESS")
        disclaimer_everywhere(label, envelope)

        rows = entries(envelope)
        check("%s produced at least one entry" % label, bool(rows))
        for entry in rows:
            model = entry.get("structural_model") or {}
            check("%s placed columns and beams" % label,
                  bool(model.get("columns")) and bool(model.get("beams")),
                  "%d columns, %d beams" % (len(model.get("columns") or []),
                                            len(model.get("beams") or [])))
            check("%s scores the layout and versions the score" % label,
                  entry["layout_score"].get("score") is not None
                  and bool(entry["layout_score"].get("score_version")),
                  json.dumps({k: entry["layout_score"].get(k)
                              for k in ("score", "score_version")}))
            # finding 18: a footing is sized from a takedown layout never runs
            check("%s carries markers, never a sized footing (finding 18)"
                  % label,
                  entry["footings_sized"] is False
                  and bool(model.get("footings"))
                  and all(footing["w_ft"] is None
                          and footing["h_ft"] is None
                          and footing["depth_ft"] is None
                          for footing in model["footings"]),
                  "%d footings" % len(model.get("footings") or []))
            check("%s reports the system it actually used" % label,
                  entry["system"] in ("rc_frame", "load_bearing_masonry",
                                      "confined_masonry", "mixed"),
                  str(entry.get("system")))
            check("%s geometry crosses the wire in feet, sections in mm"
                  % label,
                  entry["units"]["geometry"] == "ft"
                  and entry["units"]["sections"] == "mm",
                  json.dumps(entry["units"]))

    print("    layout wall clock: %s"
          % ", ".join("%s %.2f s" % (name, LAYOUTS[name][1])
                      for name in ("plan", "building", "housing")))
    slow = [name for name in LAYOUTS if LAYOUTS[name][1] >= LAYOUT_BUDGET_S]
    check("T2 layout is fast enough to stay synchronous (< %.0f s)"
          % LAYOUT_BUDGET_S, not slow,
          ", ".join("%s %.2f s" % (name, LAYOUTS[name][1]) for name in slow))


# ---------------------------------------------------------------------------
# T3: design_structure over the three fixtures
# ---------------------------------------------------------------------------

def t3_design():
    print("\nT3: Documents.design_structure - the full pipeline per fixture")
    for name in ("plan", "building", "housing"):
        started = time.time()
        envelope = Documents.design_structure(copy.deepcopy(PAYLOADS[name]))
        DESIGNS[name] = (envelope, time.time() - started)

    for name in ("plan", "building", "housing"):
        envelope, elapsed = DESIGNS[name]
        label = "T3 %s design" % name
        envelope_shape(label, envelope, expect_status="SUCCESS")
        disclaimer_everywhere(label, envelope)

        for entry in entries(envelope):
            model = entry.get("structural_model") or {}
            check("%s sized every footing" % label,
                  entry["footings_sized"] is True
                  and all(footing["w_ft"] is not None
                          for footing in model.get("footings") or []),
                  str(entry.get("footings_sized")))
            check("%s designed the members it placed" % label,
                  bool(model.get("design"))
                  and entry["design"]["results_count"] == len(model["design"]),
                  "%d results" % len(model.get("design") or []))
            check("%s took off quantities and priced them" % label,
                  entry["quantities"]["totals"]["concrete_m3"] > 0.0
                  and entry["quantities"]["boq_total"] > 0.0,
                  json.dumps(entry["quantities"]["totals"]))
            check("%s carries the report and its own disclaimer" % label,
                  disclaimer_ok(entry["report"].get("disclaimer"))
                  and bool(entry["report"]["summary"]))
            check("%s report reads no clock unless one is injected" % label,
                  entry["report"]["meta"]["generated_at"] is None,
                  str(entry["report"]["meta"]["generated_at"]))
            check("%s names every member that failed a check" % label,
                  entry["design"]["failed_count"] == len(entry["design"]["failed"])
                  and all(row["element_id"] and row["check"]
                          for row in entry["design"]["failed"]),
                  "%d failed" % entry["design"]["failed_count"])
            check("%s ran the loads and the seismic case roster" % label,
                  entry["analysis"]["method"] == "tributary_takedown_v1"
                  and set(entry["analysis"]["cases_used"]) >= {"DL", "LL", "LLR"},
                  json.dumps(entry["analysis"]["cases_used"]))

    print("    design wall clock: %s"
          % ", ".join("%s %.2f s" % (name, DESIGNS[name][1])
                      for name in ("plan", "building", "housing")))

    # a design with failed members is still SUCCESS: the report is the product
    failed = sum(entry["design"]["failed_count"]
                 for name in DESIGNS
                 for entry in entries(DESIGNS[name][0]))
    check("T3 member failures are disclosed, not turned into a refusal",
          all(DESIGNS[name][0]["status"] == "SUCCESS" for name in DESIGNS),
          "%d member failure(s) across the three fixtures" % failed)

    # layout and design run the same placement prefix, so the frames agree
    layout_entry = entries(LAYOUTS["plan"][0])[0]
    design_entry = entries(DESIGNS["plan"][0])[0]
    same = all([row["id"] for row in layout_entry["structural_model"][slot]]
               == [row["id"] for row in design_entry["structural_model"][slot]]
               for slot in ("columns", "beams", "slabs"))
    check("T3 layout and design never disagree on the geometry", same)


# ---------------------------------------------------------------------------
# T4: check_structure round trip
# ---------------------------------------------------------------------------

def t4_check():
    print("\nT4: Documents.check_structure - re-check a returned model")
    model = copy.deepcopy(entries(DESIGNS["plan"][0])[0]["structural_model"])

    envelope = Documents.check_structure({"source": "model",
                                          "model": copy.deepcopy(model)})
    envelope_shape("T4 full check", envelope, expect_status="SUCCESS")
    disclaimer_everywhere("T4 full check", envelope)
    entry = entries(envelope)[0]
    check("T4 a designed model round trips to PASS",
          entry["verdict"] == "PASS" and entry["hard_violations"] == [],
          "%s, %d violation(s)" % (entry["verdict"],
                                   len(entry["hard_violations"])))
    check("T4 scope full re-checks every designed member",
          bool(entry["element_checks"])
          and all(row["element_id"] and row["clause"]
                  for row in entry["element_checks"]),
          "%d element check(s)" % len(entry["element_checks"]))
    check("T4 a check answers about a model, it never restates one",
          "structural_model" not in entry, str(sorted(entry))[:160])

    started = time.time()
    placement = Documents.check_structure({"source": "model",
                                           "model": copy.deepcopy(model),
                                           "scope": "placement"})
    elapsed = time.time() - started
    entry = entries(placement)[0]
    check("T4 placement scope runs no member design",
          entry["element_checks"] == [] and entry["verdict"] == "PASS",
          "%d check(s)" % len(entry["element_checks"]))
    check("T4 placement scope is the fast branch", elapsed < LAYOUT_BUDGET_S,
          "%.2f s" % elapsed)

    nudged = copy.deepcopy(model)
    nudged["columns"][0]["x_ft"] = nudged["columns"][0]["x_ft"] + 3.0
    envelope = Documents.check_structure({"source": "model", "model": nudged,
                                          "scope": "placement"})
    entry = entries(envelope)[0]
    named = [item for item in entry["hard_violations"]
             if model["columns"][0]["id"] in item["element_ids"]]
    check("T4 a column dragged off its axis FAILS and is named",
          entry["verdict"] == "FAIL" and bool(named),
          "%s, %d violation(s)" % (entry["verdict"],
                                   len(entry["hard_violations"])))
    disclaimer_everywhere("T4 failing check", envelope)


# ---------------------------------------------------------------------------
# T5: the disclaimer on the two paths that are easiest to lose it on
# ---------------------------------------------------------------------------

def t5_refusal_and_validation_still_disclose():
    print("\nT5: a validation failure and a refusal carry the notice too")

    # (a) a request the engine will not run: no plan carries storey counts
    bad = {"source": "plan", "plan": load("plan_2bhk.json")}
    envelope = Documents.layout_structure(bad)
    envelope_shape("T5 validation failure", envelope, expect_status="ERROR")
    check("T5 a validation failure carries the disclaimer",
          disclaimer_ok(envelope.get("disclaimer")),
          repr(envelope.get("disclaimer"))[:80])
    documents = envelope["response"]["Documents"]
    error = documents.get("error") or {}
    check("T5 the failure names the field and its type",
          error.get("field") == "storeys"
          and error.get("type") == "ValidationError"
          and bool(error.get("message")),
          json.dumps(error))
    check("T5 a refused request returns no entries and says so",
          documents["structural"] == []
          and documents["batch_summary"]["plans"] == 0,
          json.dumps(documents["batch_summary"]))

    # the same refusal from every entry point, so no endpoint can lose it
    for method_name, method, payload in (
            ("design", Documents.design_structure, bad),
            ("check", Documents.check_structure,
             {"source": "model", "model": {"schema_version": "structural-1.0"}})):
        refused = method(copy.deepcopy(payload))
        check("T5 %s refuses with the disclaimer intact" % method_name,
              refused["status"] == "ERROR"
              and disclaimer_ok(refused.get("disclaimer"))
              and bool((refused["response"]["Documents"].get("error") or {})
                       .get("message")),
              json.dumps(refused["response"]["Documents"].get("error")))

    # (b) a stage that cannot run: the geometry placed so far still ships, as
    # a labeled partial, with the notice on it. The takedown is swapped at the
    # module attribute the orchestrator reads, and put back afterwards.
    from GPLAN.structural.analysis import takedown as takedown_module

    real_run = takedown_module.run

    def exploding(model, loadmodel, opts=None):
        raise takedown_module.AnalysisError(
            "E_ANA_CONSERVATION",
            "synthetic conservation failure for the root battery")

    try:
        takedown_module.run = exploding
        envelope = Documents.design_structure(copy.deepcopy(PAYLOADS["plan"]))
    finally:
        takedown_module.run = real_run

    envelope_shape("T5 stopped pipeline", envelope, expect_status="ERROR")
    check("T5 a stopped pipeline still carries the disclaimer",
          disclaimer_ok(envelope.get("disclaimer")),
          repr(envelope.get("disclaimer"))[:80])
    entry = entries(envelope)[0]
    check("T5 the partial is labeled, disclosed and still drawable",
          entry["status"] == "refused"
          and entry["partial"] is True
          and "synthetic conservation failure" in entry["stopped_at"]
          and bool(entry["structural_model"]["columns"])
          and "E_ANA_CONSERVATION" in {item["code"] for item in entry["errors"]},
          json.dumps({"status": entry["status"], "partial": entry["partial"]}))
    disclaimer_everywhere("T5 stopped pipeline", envelope)

    # the swap must not have leaked into the rest of the battery
    check("T5 the takedown was restored", takedown_module.run is real_run)


# ---------------------------------------------------------------------------
# T6: determinism (the backend's Redis dedup key rests on it)
# ---------------------------------------------------------------------------

def t6_determinism():
    print("\nT6: two identical calls are byte-identical")

    first = json.dumps(Documents.layout_structure(
        copy.deepcopy(PAYLOADS["plan"])), sort_keys=True)
    second = json.dumps(Documents.layout_structure(
        copy.deepcopy(PAYLOADS["plan"])), sort_keys=True)
    check("T6 two layout runs are byte-identical", first == second,
          "%d vs %d bytes" % (len(first), len(second)))

    cached = json.dumps(DESIGNS["housing"][0], sort_keys=True)
    repeat = json.dumps(Documents.design_structure(
        copy.deepcopy(PAYLOADS["housing"])), sort_keys=True)
    check("T6 two design runs are byte-identical", cached == repeat,
          "%d vs %d bytes" % (len(cached), len(repeat)))

    check("T6 options are pure",
          json.dumps(Documents.structural_options(), sort_keys=True)
          == json.dumps(Documents.structural_options(), sort_keys=True))

    model = copy.deepcopy(entries(DESIGNS["plan"][0])[0]["structural_model"])
    checks = [json.dumps(Documents.check_structure(
        {"source": "model", "model": copy.deepcopy(model),
         "scope": "placement"}), sort_keys=True) for _ in range(2)]
    check("T6 two check runs are byte-identical", checks[0] == checks[1])

    # a run must not mutate the request the caller still holds
    payload = copy.deepcopy(PAYLOADS["plan"])
    before = json.dumps(payload, sort_keys=True)
    Documents.layout_structure(payload)
    check("T6 a run does not mutate the request it was given",
          json.dumps(payload, sort_keys=True) == before)

    # the same request wrapped in the engine envelope is the same request
    wrapped = {"response": {"Documents": copy.deepcopy(PAYLOADS["plan"])}}
    check("T6 the request is accepted inside the engine envelope",
          json.dumps(Documents.layout_structure(wrapped), sort_keys=True)
          == first)


def main():
    print("=" * 70)
    print("Structural engine API tests (Documents facade)")
    print("=" * 70)
    t1_options()
    t2_layout()
    t3_design()
    t4_check()
    t5_refusal_and_validation_still_disclose()
    t6_determinism()
    print("\n" + "=" * 70)
    print("%d passed, %d failed" % (len(PASSED), len(FAILED)))
    for name, detail in FAILED:
        print("  FAILED: %s %s" % (name, detail))
    return 1 if FAILED else 0


if __name__ == "__main__":
    sys.exit(main())
