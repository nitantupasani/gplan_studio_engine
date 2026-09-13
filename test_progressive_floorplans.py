"""Progressive floorplan and local-bridge task lifecycle tests.

Run from the housing engine root::

    python -m pytest -q test_progressive_floorplans.py
"""
from collections import Counter
import copy
import json
import os
import re
import threading
import time

import local_engine_bridge as bridge
from GPLAN.api import Documents, _publish_progress_snapshot


HERE = os.path.dirname(os.path.abspath(__file__))
HOUSING_2BHK = os.path.join(
    HERE, "test_api_fixed_rooms_housing_2bhk.json")


def _load_housing_kwargs():
    with open(HOUSING_2BHK, "r") as handle:
        payload = json.load(handle)
    return bridge._prepare(payload, "door_connectivity")


def _plan_fingerprint(plan):
    return tuple(
        (
            str(room.get("name", "")),
            tuple(
                (round(float(point[0]), 5), round(float(point[1]), 5))
                for point in (room.get("circular_coordinates") or [])
            ),
        )
        for room in plan
    )


def _snapshot_fingerprints(snapshot):
    plans = snapshot["response"]["Documents"]["floorPlans"]
    return Counter(_plan_fingerprint(plan) for plan in plans)


def test_fixed_housing_progress_is_final_gated_bounded_and_non_intrusive():
    """Every published 2BHK plan survives into the unchanged terminal batch."""
    kwargs = _load_housing_kwargs()
    assert kwargs["dim_inputs"]["optimal_floorplan"] == 1

    snapshots = []

    def collect_then_fail(snapshot):
        snapshots.append(copy.deepcopy(snapshot))
        # User callback failures are deliberately ignored by the engine.
        raise RuntimeError("observer failed")

    response, message = Documents.get_floorplans(
        **kwargs, progress_callback=collect_then_fail)
    final_documents = response.to_dict()["Documents"]
    final_plans = final_documents["floorPlans"]

    assert len(final_plans) >= 20, message
    assert snapshots, "fixed-room solving did not expose any progressive batch"

    counts = []
    previous = Counter()
    final_fingerprints = Counter(
        _plan_fingerprint(plan) for plan in final_plans)
    for snapshot in snapshots:
        assert set(snapshot) == {"provisional", "message", "response"}
        assert snapshot["provisional"] is True
        # Enforces the public callback's JSON-only boundary, including NaN.
        json.dumps(snapshot, allow_nan=False)
        documents = snapshot["response"]["Documents"]
        plans = documents["floorPlans"]
        counts.append(documents["count"])
        assert documents["count"] == len(plans) > 0
        for field in ("postprocess", "adjacency_shortfalls", "plot_fit"):
            if field in documents:
                assert len(documents[field]) == len(plans)
        current = _snapshot_fingerprints(snapshot)
        assert previous <= current, "a published plan disappeared"
        assert current <= final_fingerprints, "a transient plan escaped"
        previous = current

        # The external snapshot has already crossed every hard production
        # gate: exact plot frame and immutable south-west 7 x 10 ft stair.
        for plan in plans:
            stair = next(room for room in plan
                         if room["name"] == "Staircase")
            points = stair["circular_coordinates"]
            xs = [float(point[0]) for point in points]
            ys = [float(point[1]) for point in points]
            assert abs((max(xs) - min(xs)) - 7) <= 0.05
            assert abs((max(ys) - min(ys)) - 10) <= 0.05
            assert abs(min(xs)) <= 0.05
            assert abs(max(ys) - 40) <= 0.05

    assert counts == sorted(set(counts)), counts

    # Observing progress must not alter terminal selection or ordering.
    baseline, baseline_message = Documents.get_floorplans(
        **_load_housing_kwargs())
    baseline_plans = baseline.to_dict()["Documents"]["floorPlans"]
    assert [_plan_fingerprint(plan) for plan in final_plans] == [
        _plan_fingerprint(plan) for plan in baseline_plans]
    strip_timing = lambda value: re.sub(
        r"(?:Average )?Time taken: [0-9.]+ ms", "Time taken: <elapsed>",
        value)
    assert strip_timing(message) == strip_timing(baseline_message)


class _FakeDocuments:
    def __init__(self, plans):
        self.plans = plans

    def to_dict(self):
        return {
            "Documents": {
                "documentID": "bridge-test",
                "name": "Bridge test",
                "count": len(self.plans),
                "floorPlans": self.plans,
            }
        }


def test_serialization_fallback_uses_the_same_provisional_contract():
    plans = [[{"name": "Room 1", "circular_coordinates": []}],
             [{"name": "Room 2", "circular_coordinates": []}]]
    observed = []
    _publish_progress_snapshot(
        observed.append, _FakeDocuments(plans), "one ready", 1)
    assert observed == [{
        "provisional": True,
        "message": "one ready",
        "response": {"Documents": {
            "documentID": "bridge-test",
            "name": "Bridge test",
            "count": 1,
            "floorPlans": plans[:1],
        }},
    }]

    # The shared fallback is best effort just like the early fixed collector.
    _publish_progress_snapshot(
        lambda _snapshot: (_ for _ in ()).throw(RuntimeError("observer")),
        _FakeDocuments(plans), "one ready", 1)


def _wait_for_task(client, task_id, wanted, timeout=3.0):
    deadline = time.monotonic() + timeout
    last = None
    while time.monotonic() < deadline:
        last = client.get("/api/task/%s/" % task_id).get_json()
        if last.get("status") == wanted:
            return last
        time.sleep(0.01)
    raise AssertionError("task %s never reached %s: %r" %
                         (task_id, wanted, last))


def test_local_bridge_returns_immediately_and_serializes_one_worker(monkeypatch):
    release_first = threading.Event()
    first_started = threading.Event()
    active_lock = threading.Lock()
    active = 0
    max_active = 0
    invocation = 0

    plans = [[{"name": "Room 1", "circular_coordinates": []}],
             [{"name": "Room 2", "circular_coordinates": []}]]

    def fake_get_floorplans(*, progress_callback=None, **_kwargs):
        nonlocal active, max_active, invocation
        with active_lock:
            invocation += 1
            this_invocation = invocation
            active += 1
            max_active = max(max_active, active)
        try:
            progress_callback({
                "message": "one ready",
                "response": {"Documents": {
                    "documentID": "bridge-test",
                    "name": "Bridge test",
                    "count": 1,
                    "floorPlans": plans[:1],
                }},
            })
            if this_invocation == 1:
                first_started.set()
                assert release_first.wait(3.0), "test did not release worker"
            progress_callback({
                "message": "two ready",
                "response": {"Documents": {
                    "documentID": "bridge-test",
                    "name": "Bridge test",
                    "count": 2,
                    "floorPlans": plans,
                }},
            })
            return _FakeDocuments(plans), "done"
        finally:
            with active_lock:
                active -= 1

    monkeypatch.setattr(bridge.Documents, "get_floorplans",
                        fake_get_floorplans)
    client = bridge.app.test_client()
    request_body = {
        "count": 2,
        "nodes": [
            {"id": 0, "x": 0, "y": 0, "label": "Room 1"},
            {"id": 1, "x": 1, "y": 0, "label": "Room 2"},
        ],
        "edges": [{"source": 0, "target": 1, "color": "black"}],
    }

    started_at = time.monotonic()
    first_post = client.post(
        "/api/generate/door_connectivity", json=request_body)
    elapsed = time.monotonic() - started_at
    assert first_post.status_code == 202
    assert elapsed < 0.5, "POST waited for the generation worker"
    first_id = first_post.get_json()["task_id"]
    assert first_started.wait(1.0)

    first_progress = _wait_for_task(client, first_id, "PROGRESS")
    metadata = first_progress["result"]
    assert metadata["partial"] is True
    assert metadata["complete"] is False
    assert metadata["provisional"] is True
    assert metadata["progress"] == {
        "sequence": 1, "ready": 1, "requested": 2}
    assert len(metadata["response"]["Documents"]["floorPlans"]) == 1

    # A second request queues behind the first instead of running GPLAN in a
    # concurrent thread while its process-global print suppression is active.
    second_post = client.post(
        "/api/generate/door_connectivity", json=request_body)
    second_id = second_post.get_json()["task_id"]
    second_pending = client.get("/api/task/%s/" % second_id).get_json()
    assert second_pending["status"] == "PENDING"
    assert max_active == 1

    release_first.set()
    first_final = _wait_for_task(client, first_id, "SUCCESS")
    second_final = _wait_for_task(client, second_id, "SUCCESS")
    assert max_active == 1
    assert first_final["message"] == second_final["message"] == "done"
    assert len(first_final["response"]["Documents"]["floorPlans"]) == 2
    assert len(second_final["response"]["Documents"]["floorPlans"]) == 2
