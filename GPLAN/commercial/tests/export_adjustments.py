"""Export real modified-programme results for UI and API contract checks."""

import json
from pathlib import Path

from GPLAN.commercial import generate_commercial_options
from GPLAN.commercial.tests.test_adjustments import meeting_twenty_brief, large_single_floor_brief


if __name__ == "__main__":
    root = Path(__file__).resolve().parents[4] / "tmp"
    root.mkdir(exist_ok=True)
    for name, brief in [("commercial-adjusted-meeting-fixture.json", meeting_twenty_brief()),
                         ("commercial-adjusted-single-fixture.json", large_single_floor_brief())]:
        result = generate_commercial_options(brief)
        (root / name).write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
        print(json.dumps({"path": str(root / name), "status": result["status"], "search": result["search"],
                          "options": [{"floors": len(c["floors"]), "capacity": c["capacity"], "differences": c.get("constraint_deviations", [])} for c in result["candidates"]]}, ensure_ascii=True))
