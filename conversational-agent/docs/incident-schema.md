# Incident JSON contract (schema version 1.0)

One incident = one JSON object. It is the interface between **incident sources** (the voice agent today, a synthetic generator later) and the **Multi-Agent (Mesa) simulation**. The simulation does not need to know which source produced an incident.

| | |
|---|---|
| Example | [`examples/sample_incident.json`](../examples/sample_incident.json) |
| JSON Schema | [`schemas/incident.schema.json`](../schemas/incident.schema.json) (draft 2020-12) |
| Python model | `backend/models/incident.py` → `Incident` (Pydantic) |

> All classifications are **simulation labels** for research. They are not clinical triage, not medically validated, and not the Dutch A0/A1/A2 ambulance urgency codes.

## Structure

```json
{
  "schema_version": "1.0",
  "incident_id": "INC-7C41A2E9B05D",
  "session_id": "3f2b8c1e-9d4a-4e7b-a6c2-81d5f0e93a47",
  "created_at": "2026-10-03T14:22:37.418Z",
  "source": "voice_agent",
  "location": { "raw_text": "...", "latitude": null, "longitude": null },
  "incident": { "description": "...", "mechanism": "...", "type": "trauma", "severity": "urgent" },
  "patients": {
    "count": 1,
    "primary_patient": { "consciousness": "...", "breathing": "...", "severe_bleeding": "...", "symptoms": ["..."] }
  },
  "scene": { "entrapment": "...", "immediate_danger": "..." },
  "classification": {
    "incident_type":         { "value": "trauma", "confidence": 0.91 },
    "severity":              { "value": "urgent", "confidence": 0.84 },
    "consciousness_concern": { "value": "no",     "confidence": 0.96 },
    "breathing_concern":     { "value": "no",     "confidence": 0.94 }
  },
  "status": "ready_for_dispatch"
}
```

The confidence numbers above are illustrative, not real classifier output. **Every key is always present.** Values may be `null` where stated below. No other keys are allowed (`additionalProperties: false` everywhere).

## Fields

### Top level

| Field | Type | Meaning |
|---|---|---|
| `schema_version` | `"1.0"` | Contract version. Changes when the structure changes. |
| `incident_id` | string | Unique id. The voice agent uses `INC-` + 12 uppercase hex characters, e.g. `INC-7C41A2E9B05D`. |
| `session_id` | string \| null | Id of the voice conversation; `null` for synthetic incidents. Do not rely on it in the simulation. |
| `created_at` | string | ISO-8601 UTC timestamp, e.g. `2026-10-03T14:22:37.418Z`. |
| `source` | enum | `voice_agent`, `synthetic_generator` |
| `status` | `"ready_for_dispatch"` | Always this value. Anything else is not an incident to dispatch. |

### `location`

| Field | Type | Meaning |
|---|---|---|
| `raw_text` | string \| null | Location as described, e.g. `"Outside the Vrijhof, University of Twente"`. `null` if the caller could not say. |
| `latitude` | number \| null | −90…90. Currently always `null` from the voice agent (no geocoding yet). |
| `longitude` | number \| null | −180…180. Currently always `null` from the voice agent. |

### `incident`

| Field | Type | Meaning |
|---|---|---|
| `description` | string (non-empty) | One short factual sentence, e.g. `"Friend fell off his bicycle and hit his head."`. If nothing was said: `"No description provided by caller."` |
| `mechanism` | string \| null | How it happened in a few words, e.g. `"bicycle fall"`, `"car collision"`; `null` if not applicable or unknown. |
| `type` | enum | Simulation incident type (see enums). Always equal to `classification.incident_type.value`. |
| `severity` | enum | Simulation severity (see enums). Always equal to `classification.severity.value`. |

### `patients`

| Field | Type | Meaning |
|---|---|---|
| `count` | integer ≥ 1 \| null | Number of patients; `null` if unknown. |
| `primary_patient.consciousness` | enum | See enums. |
| `primary_patient.breathing` | enum | See enums. |
| `primary_patient.severe_bleeding` | enum | See enums. |
| `primary_patient.symptoms` | list of strings | Observations in plain words, e.g. `["head injury", "left arm weakness", "speech difficulty"]`. Never diagnoses. May be empty. |

`primary_patient` describes the patient the caller talked about, or the most seriously affected one when there are several. The other patients are only counted.

### `scene`

| Field | Type | Meaning |
|---|---|---|
| `entrapment` | enum | Is anyone trapped (vehicle, machinery, collapsed structure)? |
| `immediate_danger` | enum | Immediate danger at the scene (traffic, fire, smoke, gas, electricity, water, violence)? |

### `classification`

Four labels, each `{ "value": <enum>, "confidence": number | null }`:

| Field | `value` enum |
|---|---|
| `incident_type` | incident types (see enums) |
| `severity` | severities |
| `consciousness_concern` | `yes`, `no`, `uncertain` |
| `breathing_concern` | `yes`, `no`, `uncertain` |

- `confidence` is the classifier's confidence in its answer, between 0 and 1. It is `null` when no confidence exists: the classifier was unavailable, or the incident is synthetic.
- If the classifier's confidence was below the threshold (default 0.70), `value` is `uncertain`. `confidence` then shows the (low) confidence of the answer that was rejected.

## Enums

| Field | Values |
|---|---|
| `incident.type` | `cardiac_or_circulatory`, `respiratory`, `trauma`, `neurological`, `bleeding`, `other`, `uncertain` |
| `incident.severity` | `critical`, `urgent`, `non_urgent`, `uncertain` |
| `consciousness` | `conscious`, `unconscious`, `unknown` |
| `breathing` | `normal`, `abnormal`, `not_breathing`, `unknown` |
| `severe_bleeding` | `present`, `absent`, `unknown` |
| `entrapment` | `yes`, `no`, `unknown`, `not_relevant` |
| `immediate_danger` | `yes`, `no`, `unknown`, `not_relevant` |
| `consciousness_concern`, `breathing_concern` | `yes`, `no`, `uncertain` |
| `source` | `voice_agent`, `synthetic_generator` |

Meaning of the values that need explaining:

| Value | Meaning |
|---|---|
| `conscious` / `unconscious` | Responds (e.g. awake, talking) / does not respond. Confusion or drowsiness goes into `symptoms`. |
| `abnormal` (breathing) | Struggling, gasping, noisy or strange breathing. |
| `severe_bleeding: present` | Heavy or uncontrolled bleeding. Ordinary bleeding is `absent` and appears in `symptoms` (e.g. `"bleeding from the head"`). |
| `critical` | Immediately life-threatening, e.g. unconscious, not breathing or breathing abnormally, severe bleeding. |
| `urgent` | Serious and needs help soon, but conscious and breathing. |
| `non_urgent` | Minor problem, patient stable. |

## `null`, `unknown`, `not_relevant`, `uncertain`

| | Used for | Means |
|---|---|---|
| `null` | free-text and number fields | No value: not said or not applicable. |
| `unknown` | observation enums | Relevant, but the information is not available. |
| `not_relevant` | `scene` fields | The question does not apply to this incident (e.g. entrapment for a collapse at home). |
| `uncertain` | classification labels | The classifier could not decide confidently. |

The simulation should accept all of these. They are normal outcomes, not errors.

## Rules

1. `incident.type == classification.incident_type.value` and `incident.severity == classification.severity.value`. The Pydantic model enforces this. The JSON Schema cannot express it.
2. Producers must not add fields. Voice-only data (transcript, extraction bookkeeping, raw classifier output) lives in the database metadata, never in the incident.
3. The voice agent's debug panel also shows a *live draft* of this JSON while the call is in progress (`status: "collecting"`, labels `"unknown"`, `created_at: null`). Drafts are never stored or sent to the simulation.

## Where incidents are stored

MongoDB, database `emergency_voice_agent`, collection `incidents`, one document per incident:

```json
{ "_id": "<incident_id>", "incident": { ...this contract... }, "metadata": { ...debug data... }, "created_at": "<datetime>" }
```

Read only `incident`. `metadata` (transcript, working state, raw classifier responses) is for debugging and may change at any time.

## Changing the contract

Change `backend/models/incident.py`, then run `python export_schema.py` (a test fails if `schemas/incident.schema.json` is out of date), update this document, the sample, and `schema_version` if the change is not backwards compatible.
