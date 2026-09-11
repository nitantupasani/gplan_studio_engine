"""Shared HTTP envelope for Django and the canonical development bridge.

Callers enforce MAX_BODY_BYTES before parsing. Algorithms stay in the service.
"""
from .models import CirculationError, MAX_BODY_BYTES
from .registry import get_capabilities
from .service import generate_circulation, validate_circulation


def error_response(code, message, status, request_id="unknown", details=None):
    return {"request_id": request_id, "status": "error", "data": {},
            "error": {"code": code, "type": "CirculationError", "message": message,
                      "details": details or {}}}, status


def dispatch(operation, payload=None):
    request_id = payload.get("request_id", "unknown") if isinstance(payload, dict) else "unknown"
    try:
        if operation == "options":
            return get_capabilities(), 200
        if operation == "generate":
            return generate_circulation(payload), 200
        if operation == "validate":
            return validate_circulation(payload), 200
        return error_response("unknown_operation", "Unknown circulation operation.", 404, request_id)
    except CirculationError as exc:
        status = 400 if exc.code in ("invalid_input", "invalid_schema", "invalid_candidate") else exc.http_status
        return error_response(exc.code, exc.message, status, request_id, exc.details)
