"""Write the canonical Incident JSON Schema to conversational-agent/schemas/incident.schema.json.

The synthetic incident generator and the MAS can validate against this file
(or import `models.incident.Incident` directly). Re-run after changing the model;
a test fails if the file is out of date.

    python export_schema.py
"""

import json

from config import PROJECT_ROOT
from models.incident import Incident

SCHEMA_PATH = PROJECT_ROOT / "schemas" / "incident.schema.json"


def incident_schema_json() -> str:
    return json.dumps(Incident.model_json_schema(), indent=2) + "\n"


if __name__ == "__main__":
    SCHEMA_PATH.parent.mkdir(exist_ok=True)
    SCHEMA_PATH.write_text(incident_schema_json())
    print(f"Wrote {SCHEMA_PATH}")
