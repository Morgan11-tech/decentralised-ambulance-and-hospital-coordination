# Mesa integration

How the Mesa simulation consumes incidents. The full field reference is [incident-schema.md](incident-schema.md).

```
voice agent ──┐
              ├──► Incident JSON ──► validate ──► Incident agent / object in Mesa
synthetic  ───┘     (schema 1.0)                    uses: location, type, severity,
generator                                           patient count, patient condition
```

The simulation never talks to the voice agent. It only reads incident JSON objects: from files, or from MongoDB (`emergency_voice_agent.incidents`, field `incident`).

## Load and validate

```python
import json

from jsonschema import validate  # pip install jsonschema

with open("conversational-agent/schemas/incident.schema.json") as f:
    schema = json.load(f)

with open("conversational-agent/examples/sample_incident.json") as f:
    incident = json.load(f)

validate(instance=incident, schema=schema)  # raises jsonschema.ValidationError if invalid
```

Fields you will typically use:

```python
incident["incident_id"]                          # "INC-7C41A2E9B05D"
incident["location"]["raw_text"]                 # "Outside the Vrijhof, University of Twente"
incident["incident"]["type"]                     # "trauma"
incident["incident"]["severity"]                 # "urgent"
incident["patients"]["count"]                    # 1 (or None)
patient = incident["patients"]["primary_patient"]
patient["consciousness"], patient["breathing"]   # "conscious", "normal"
patient["severe_bleeding"], patient["symptoms"]  # "absent", ["head injury", "bleeding from the head"]
incident["scene"]["entrapment"]                  # "not_relevant"
```

## Reading from MongoDB

```python
from pymongo import MongoClient

incidents = MongoClient("mongodb://localhost:27017")["emergency_voice_agent"]["incidents"]
for document in incidents.find({}, {"incident": 1}).sort("created_at", 1):
    incident = document["incident"]  # ignore document["metadata"]
```

## Suggestions for the simulation

These are suggestions only. The contract does not prescribe dispatch logic.

- **Priority:** use `incident.severity` (`critical` > `urgent` > `non_urgent`). Decide a policy for `uncertain`, e.g. treat it as `urgent`.
- **Hospital choice:** `incident.type` can map to hospital capabilities (e.g. `cardiac_or_circulatory` → cardiac care, `neurological` → stroke unit, `trauma` → trauma centre).
- **Number of ambulances:** `patients.count`. Treat `null` as 1.
- **On-scene time:** `scene.entrapment == "yes"` or `scene.immediate_danger == "yes"` can lengthen it.
- **Location:** `latitude`/`longitude` are `null` for now. Map `location.raw_text` to a simulation location yourself, e.g. a lookup table of campus locations, or a random grid cell.
- **Unknown values:** `unknown`, `not_relevant`, `uncertain` and `null` are normal values. Do not treat them as errors.
- **Ignore:** `session_id`, `classification.*.confidence` (unless you study classifier confidence) and `source` (the simulation must not depend on it).
