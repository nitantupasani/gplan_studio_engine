"""Isolated JSON-lines worker for a single bounded commercial solve."""
import json
import sys
import time


def main():
    payload = json.load(sys.stdin)
    # Keep an explicit marker so legacy solver stdout cannot be mistaken for
    # structured task events or a completed candidate.
    def emit(kind, value):
        sys.stdout.write("GPLAN_COMMERCIAL " + json.dumps({"type": kind, "value": value}, allow_nan=False) + "\n")
        sys.stdout.flush()
    try:
        from GPLAN.commercial import generate_commercial_options
        result = generate_commercial_options(
            payload["brief"], progress=lambda event: emit("progress", event),
            deadline=time.monotonic() + payload["budgetMs"] / 1000)
        emit("result", result)
    except Exception as error:
        detail = error.to_dict() if callable(getattr(error, "to_dict", None)) else {
            "code": type(error).__name__, "message": str(error)}
        emit("error", detail)


if __name__ == "__main__":
    main()
