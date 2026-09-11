"""HTTP coverage for house schema, task lifecycle, progress and cancellation.

Run from the engine repository (preload the inner GPLAN package because this
repository also carries an outer package marker)::

    python -c "import GPLAN.api, pytest; raise SystemExit(pytest.main(['-q', '--import-mode=importlib', 'test_house_concepts_bridge.py']))"
"""
import copy
import threading
import time

import pytest

import local_engine_bridge as bridge
from GPLAN.housing.schema import normalize_request


def request_body():
    return {"schema_version": "house_concepts_v1", "units": "mm",
            "plot": {"polygon": [[0, 0], [10000, 0], [10000, 22000], [0, 22000]],
                     "front_edge": 0},
            "programme_profile": "NL_concept_v1", "requested_options": 1,
            "search": {"budget_ms": 15000}}


def transport_catalogue():
    # These are protocol fixtures, never geometric feasibility assertions.
    return {"schema_version": "house_concepts_v1", "units": "mm",
            "programme_profile": "NL_concept_v1", "notices": [],
            "options": [{"id": "house-a", "validation": {"valid": True},
                         "floors": [{"rooms": [{"id": "%s-room" % role}]} for role in
                                    ("ground", "first", "attic")]}]}


def wait_task(client, task_id, wanted, timeout=3):
    deadline = time.monotonic() + timeout
    last = None
    while time.monotonic() < deadline:
        last = client.get("/api/task/%s/" % task_id).get_json()
        if last.get("status") == wanted:
            return last
        time.sleep(0.01)
    raise AssertionError("Task did not reach %s: %r" % (wanted, last))


@pytest.fixture(autouse=True)
def isolated_cache():
    with bridge._results_lock:
        bridge._house_cache.clear()


def test_house_capability_requires_callable_installed_engine(monkeypatch):
    client = bridge.app.test_client()
    monkeypatch.setattr(bridge, "_house_engine", lambda: (lambda _p: None, normalize_request))
    assert "house_concepts_v1" in client.get("/api/capabilities/").get_json()["capabilities"]
    assert "fixed_rooms_v1" in client.get("/api/local-bridge/health/").get_json()["capabilities"]

    def unavailable():
        raise ImportError("old pinned engine")

    monkeypatch.setattr(bridge, "_house_engine", unavailable)
    assert "house_concepts_v1" not in client.get("/api/local-bridge/health/").get_json()["capabilities"]
    response = client.post("/api/generate/house_concepts", json=request_body())
    assert response.status_code == 503
    assert response.get_json()["error"]["type"] == "CapabilityUnavailable"


@pytest.mark.parametrize("change", [
    lambda p: p.update(schema_version="future-v99"),
    lambda p: p.update(units="ft"),
    lambda p: p.update(programme_profile="unsupported"),
    lambda p: p["search"].update(budget_ms=120001),
    lambda p: p.update(locked_cores=[{"id": "unimplemented-interior-lock"}]),
    lambda p: p["plot"]["polygon"][0].__setitem__(0, 0.1),
])
def test_invalid_house_requests_fail_before_dispatch(monkeypatch, change):
    def should_not_run(*_args, **_kwargs):
        raise AssertionError("Invalid request reached a worker")

    monkeypatch.setattr(bridge, "_house_engine", lambda: (should_not_run, normalize_request))
    body = request_body()
    change(body)
    response = bridge.app.test_client().post("/api/generate/house_concepts/", json=body)
    assert response.status_code == 400
    assert response.get_json()["error"]["type"] == "ValidationError"


@pytest.mark.parametrize("body", ["[]", "null", "{broken"])
def test_malformed_json_has_client_error_envelope(body):
    response = bridge.app.test_client().post(
        "/api/generate/house_concepts", data=body, content_type="application/json")
    assert response.status_code == 400
    assert response.get_json()["error"]["type"] == "ValidationError"


def test_progress_gates_complete_houses_and_cancel_is_job_local(monkeypatch):
    first_started = threading.Event()
    release = threading.Event()
    invocations = []
    active = 0
    max_active = 0

    def controlled_engine(payload, progress_callback=None):
        nonlocal active, max_active
        active += 1
        max_active = max(max_active, active)
        invocations.append(payload)
        try:
            catalogue = transport_catalogue()
            incomplete = copy.deepcopy(catalogue)
            incomplete["options"][0]["floors"] = incomplete["options"][0]["floors"][:1]
            progress_callback(incomplete)
            progress_callback(catalogue)
            # Exposed snapshots must not share memory with the engine.
            catalogue["options"][0]["id"] = "mutated-after-publish"
            if len(invocations) == 1:
                first_started.set()
                assert release.wait(3)
                assert progress_callback.is_cancelled()
            return transport_catalogue()
        finally:
            active -= 1

    monkeypatch.setattr(bridge, "_house_engine", lambda: (controlled_engine, normalize_request))
    client = bridge.app.test_client()
    try:
        started_at = time.monotonic()
        first = client.post("/api/generate/house_concepts", json=request_body())
        assert first.status_code == 202
        assert time.monotonic() - started_at < 0.5
        first_id = first.get_json()["task_id"]
        assert first_started.wait(1)
        progress = wait_task(client, first_id, "PROGRESS")["result"]
        assert progress["progress"] == {"sequence": 1, "ready": 1, "requested": 1}
        assert progress["response"]["HouseConcepts"]["options"][0]["id"] == "house-a"
        assert progress["partial"] is True and progress["complete"] is False

        second = client.post("/api/generate/house_concepts", json=request_body())
        second_id = second.get_json()["task_id"]
        assert first_id != second_id
        assert wait_task(client, second_id, "PENDING")
        assert max_active == 1
        wrong_owner = client.post("/api/task/%s/cancel/" % first_id,
                                  headers={"Authorization": "Bearer another-caller"})
        assert wrong_owner.status_code == 403
        cancelled = client.post("/api/task/%s/cancel/" % first_id)
        assert cancelled.get_json()["status"] == "cancelled"
        release.set()
        assert wait_task(client, first_id, "CANCELLED")
        final = wait_task(client, second_id, "SUCCESS")
        assert final["response"]["HouseConcepts"]["options"][0]["validation"]["valid"]
        assert len(invocations) == 2 and max_active == 1
        # Complete cache reuse retains another unique public job identity.
        third = client.post("/api/generate/house_concepts", json=request_body())
        third_id = third.get_json()["task_id"]
        assert third_id not in {first_id, second_id}
        assert wait_task(client, third_id, "SUCCESS")
        assert len(invocations) == 2
        assert client.post("/api/task/legacy-floorplan/cancel/").status_code == 404
    finally:
        release.set()


def test_queued_house_cancellation_does_not_call_engine(monkeypatch):
    blocker_started = threading.Event()
    release = threading.Event()

    def blocker():
        blocker_started.set()
        assert release.wait(3)

    future = bridge._generation_executor.submit(blocker)
    assert blocker_started.wait(1)
    calls = []
    monkeypatch.setattr(bridge, "_house_engine", lambda: (
        lambda payload, **_kw: calls.append(payload), normalize_request))
    try:
        client = bridge.app.test_client()
        task_id = client.post("/api/generate/house_concepts", json=request_body()).get_json()["task_id"]
        assert client.post("/api/task/%s/cancel/" % task_id).status_code == 200
        release.set()
        future.result(3)
        bridge._generation_executor.submit(lambda: None).result(3)
        assert calls == []
        assert wait_task(client, task_id, "CANCELLED")
    finally:
        release.set()


@pytest.mark.parametrize("invalid_result", [False, True])
def test_engine_failure_and_invalid_terminal_catalogue_stay_failures(monkeypatch, invalid_result):
    def failing_engine(_payload, progress_callback=None):
        if not invalid_result:
            raise RuntimeError("solver failed")
        catalogue = transport_catalogue()
        catalogue["options"][0]["validation"]["valid"] = False
        return catalogue

    monkeypatch.setattr(bridge, "_house_engine", lambda: (failing_engine, normalize_request))
    client = bridge.app.test_client()
    task_id = client.post("/api/generate/house_concepts", json=request_body()).get_json()["task_id"]
    result = wait_task(client, task_id, "FAILURE")
    assert result["error"]["type"] == ("ValueError" if invalid_result else "RuntimeError")
    assert "response" not in result


def test_real_bridge_house_route_generates_validated_stack():
    """The actual facade and solver cross POST/poll, with no engine mocking."""
    client = bridge.app.test_client()
    response = client.post("/api/generate/house_concepts", json=request_body())
    assert response.status_code == 202, response.get_json()
    final = wait_task(client, response.get_json()["task_id"], "SUCCESS", timeout=45)
    catalogue = final["response"]["HouseConcepts"]
    assert catalogue["schema_version"] == "house_concepts_v1"
    assert catalogue["programme_profile"] == "NL_concept_v1"
    assert catalogue["options"], catalogue
    for option in catalogue["options"]:
        assert option["validation"]["valid"] is True
        assert len(option["floors"]) >= 3
        assert all(floor["rooms"] for floor in option["floors"])
