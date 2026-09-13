"""Flask commercial API matching the Django office job/receipt contract.

Development jobs expire after a day; every solve executes in a fresh child
process. The process watchdog bounds a stuck legacy call, including Windows.
"""
import concurrent.futures
import copy
import hashlib
import json
import subprocess
import sys
import threading
import time
import uuid
from pathlib import Path

from flask import jsonify, request, Response

TERMINAL = {"complete", "cancelled", "error"}


def parse_request(body):
    if not isinstance(body, dict) or not isinstance(body.get("brief"), dict):
        raise ValueError("Request must contain a commercial brief object.")
    design_id, revision, budget = body.get("designId"), body.get("revision"), body.get("budgetMs", 30000)
    if not isinstance(design_id, str) or not design_id.strip() or len(design_id) > 200:
        raise ValueError("designId must be a nonempty string of at most 200 characters.")
    if isinstance(revision, str) and revision.isascii() and revision.isdigit() and len(revision) <= 16:
        revision = int(revision)
    if isinstance(revision, bool) or not isinstance(revision, int) or revision < 0 or revision > 9007199254740991:
        raise ValueError("revision must be a nonnegative integer.")
    if isinstance(budget, bool) or not isinstance(budget, int) or not 1000 <= budget <= 120000:
        raise ValueError("budgetMs must be an integer between 1000 and 120000.")
    encoded = json.dumps(body["brief"], sort_keys=True, separators=(",", ":"), allow_nan=False)
    return json.loads(encoded), {"designId": design_id, "revision": str(revision),
                                "briefFingerprint": hashlib.sha256(encoded.encode()).hexdigest()}, budget


def register_commercial_routes(app):
    jobs, processes = {}, {}
    lock = threading.Lock()
    executor = concurrent.futures.ThreadPoolExecutor(max_workers=1, thread_name_prefix="commercial-supervisor")

    def owner():
        identity = request.headers.get("Authorization", "").strip() or request.remote_addr or "local"
        return hashlib.sha256(identity.encode()).hexdigest()

    def public(job):
        return copy.deepcopy({key: value for key, value in job.items() if key not in {"owner", "deadlineAt", "expiresAt"}})

    def failure(error, code=400):
        detail = error.to_dict() if callable(getattr(error, "to_dict", None)) else {"code": type(error).__name__, "message": str(error)}
        return jsonify({"status": "error", "error": detail}), code

    def run(task_id, brief, budget):
        with lock:
            job = jobs[task_id]
            if job["status"] in TERMINAL:
                return
            remaining = min(budget / 1000, job["deadlineAt"] - time.time() - 15)
            if remaining <= 0:
                job.update(status="error", error={"code": "task_deadline", "message": "The task expired before a worker became available."})
                return
        process = None
        watchdog = None
        try:
            process = subprocess.Popen([sys.executable, str(Path(__file__).with_name("commercial_worker.py"))],
                                       stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                                       text=True, encoding="utf-8", creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
            with lock:
                if jobs[task_id]["status"] in TERMINAL:
                    process.terminate()
                    return
                processes[task_id] = process
            watchdog = threading.Timer(remaining + 5, lambda: process.kill() if process.poll() is None else None)
            watchdog.daemon = True
            watchdog.start()
            process.stdin.write(json.dumps({"brief": brief, "budgetMs": int(remaining * 1000)}, allow_nan=False))
            process.stdin.close()
            for line in process.stdout:
                if not line.startswith("GPLAN_COMMERCIAL "):
                    continue
                event = json.loads(line[len("GPLAN_COMMERCIAL "):])
                with lock:
                    job = jobs[task_id]
                    if job["status"] in TERMINAL:
                        continue
                    if event["type"] == "progress":
                        events = job["events"]
                        value = event["value"]
                        value["sequence"] = (events[-1]["sequence"] if events else 0) + 1
                        job.update(status="running", events=(events + [value])[-100:])
                    elif event["type"] == "result":
                        job.update(status="cancelled" if event["value"].get("status") == "cancelled" else "complete", result=event["value"])
                    elif event["type"] == "error":
                        job.update(status="error", error=event["value"])
            process.wait(timeout=5)
            with lock:
                if jobs[task_id]["status"] not in TERMINAL:
                    jobs[task_id].update(status="error", error={"code": "worker_exit", "message": "The bounded generation worker stopped without a result."})
        except Exception as error:
            with lock:
                if jobs[task_id]["status"] not in TERMINAL:
                    jobs[task_id].update(status="error", error={"code": type(error).__name__, "message": str(error)})
        finally:
            if watchdog:
                watchdog.cancel()
            if process and process.poll() is None:
                process.kill()
                process.wait()
            if process and process.stdout:
                process.stdout.close()
            with lock:
                processes.pop(task_id, None)

    @app.post("/api/commercial/estimate", strict_slashes=False)
    def commercial_estimate():
        try:
            from GPLAN.commercial import estimate_commercial_fit
            brief, receipt, _budget = parse_request(request.get_json())
            return jsonify({**receipt, "result": estimate_commercial_fit(brief)})
        except ImportError:
            return failure(ValueError("This engine does not support commercial_office_v1."), 503)
        except (ValueError, TypeError, KeyError) as error:
            return failure(error)

    @app.post("/api/commercial/validate", strict_slashes=False)
    def commercial_validate():
        try:
            from GPLAN.commercial import validate_commercial_option
            body = request.get_json()
            brief, receipt, _budget = parse_request(body)
            if not isinstance(body.get("option"), dict):
                raise ValueError("A whole-building option is required.")
            return jsonify({**receipt, "result": validate_commercial_option(body["option"], brief)})
        except ImportError:
            return failure(ValueError("This engine does not support commercial_office_v1."), 503)
        except (ValueError, TypeError, KeyError) as error:
            return failure(error)

    @app.post("/api/commercial/generate", strict_slashes=False)
    def commercial_generate():
        try:
            from GPLAN.commercial import estimate_commercial_fit
            brief, receipt, budget = parse_request(request.get_json())
            estimate_commercial_fit(brief)
            task_id = str(uuid.uuid4())
            now = time.time()
            with lock:
                for expired in [key for key, value in jobs.items() if value["expiresAt"] < now and value["status"] in TERMINAL]:
                    jobs.pop(expired, None)
                if sum(job["status"] not in TERMINAL for job in jobs.values()) >= 16:
                    return failure(ValueError("The local commercial queue is full. Retry after an active task completes."), 429)
                job = {"task_id": task_id, "status": "queued", **receipt, "events": [], "owner": owner(),
                       "deadlineAt": now + budget / 1000 + 15, "expiresAt": now + 86400}
                jobs[task_id] = job
                response = public(job)
            executor.submit(run, task_id, brief, budget)
            return jsonify(response), 202
        except ImportError:
            return failure(ValueError("This engine does not support commercial_office_v1."), 503)
        except (ValueError, TypeError, KeyError) as error:
            return failure(error)

    @app.post("/api/commercial/export/<format>", strict_slashes=False)
    def commercial_export(format):
        try:
            from commercial_exports import export_commercial
            body = request.get_json()
            brief, receipt, _budget = parse_request(body)
            if not isinstance(body.get("option"), dict):
                raise ValueError("A whole-building option is required.")
            content, content_type = export_commercial(brief, body["option"], receipt, format)
            response = Response(content, mimetype=content_type)
            response.headers["Content-Disposition"] = 'attachment; filename="office-design-study.%s"' % format
            return response
        except ImportError:
            return failure(ValueError("This export format is unavailable on the installed engine. Check its export dependencies."), 503)
        except (ValueError, TypeError, KeyError) as error:
            return failure(error)

    @app.route("/api/commercial/tasks/<task_id>", methods=["GET", "DELETE"], strict_slashes=False)
    @app.post("/api/commercial/tasks/<task_id>/cancel", strict_slashes=False)
    def commercial_task(task_id):
        with lock:
            job = jobs.get(task_id)
            if not job or job["expiresAt"] < time.time():
                return failure(ValueError("Commercial task not found or expired."), 404)
            if job["owner"] != owner():
                return failure(ValueError("This commercial task belongs to another caller."), 403)
            if job["status"] not in TERMINAL and time.time() > job["deadlineAt"]:
                job.update(status="error", error={"code": "task_deadline", "message": "The task exceeded its time allowance."})
            if request.method != "GET" and job["status"] not in TERMINAL:
                job.update(status="cancelled")
                job.pop("result", None)
            process = processes.get(task_id) if job["status"] in {"cancelled", "error"} else None
            response = public(job)
        if process and process.poll() is None:
            process.terminate()
        return jsonify(response)

    # Expose only for deterministic test shutdown, never in HTTP responses.
    app.extensions["commercial_jobs"] = {"jobs": jobs, "lock": lock, "executor": executor}
