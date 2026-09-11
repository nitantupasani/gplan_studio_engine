"""Export a real solver result for the commercial UI contract QA harness."""

import json
from pathlib import Path
import sys

from GPLAN.commercial import generate_commercial_options
from GPLAN.commercial.tests.test_commercial import default_brief


if __name__ == "__main__":
    destination = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(__file__).resolve().parents[4] / "tmp" / "commercial-ui-fixture.json"
    result = generate_commercial_options(default_brief())
    if not result["candidates"]:
        raise RuntimeError(json.dumps(result["diagnostics"]))
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"path": str(destination), "status": result["status"], "search": result["search"],
                      "options": [{"floors": len(c["floors"]), "capacity": c["capacity"]} for c in result["candidates"]]}))
