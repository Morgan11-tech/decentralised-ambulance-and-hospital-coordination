# Conversational Agent: technical information for the report

This document describes the **conversational (voice) intake agent** of the *Decentralised Ambulance & Hospital Coordination* project: what it does, how it works, how it uses Jev, and the incident format it produces. It covers only the `conversational-agent/` component, not the Mesa simulation. It describes the code as of 28 October 2026.

> **Research prototype, not for real emergency use.** The agent does not give medical advice. Its classifications are *simulation labels*: not clinically validated triage, and not the Dutch A0/A1/A2 ambulance urgency codes.

---

## 1. Purpose and scope

The conversational agent is the **entry point** of the multi-agent system (MAS). A caller speaks to a simulated 112 call-taker in the browser. The agent holds a short, adaptive conversation and turns it into one structured **Incident JSON** object. The Mesa simulation (ambulance and hospital agents) then uses that object.

```
VOICE  →  CONVERSATION  →  CLASSIFICATION  →  INCIDENT JSON  →  MongoDB  →  Mesa simulation
```

The agent's job ends when a validated incident is stored. It does not dispatch ambulances. That belongs to the MAS (Incident Coordinator, Ambulance and Hospital agents, a Centralized Dispatcher as baseline, and Contract Net Protocol coordination for the decentralised experiments).

A future **synthetic incident generator** must produce exactly the same Incident format, so the simulation never needs to know whether an incident came from a voice call or was generated.

---

## 2. Technology stack

| Concern | Technology | Version / model | Role |
|---|---|---|---|
| Frontend | React + TypeScript, built with Vite | React 19, Vite 7 | Voice UI, debug panel |
| Visual agent | React Bits **Orb** (WebGL, `ogl`) | TS + CSS variant | Shows the agent's state |
| Backend | Python, FastAPI, Pydantic | Python 3.11+ | Session, WebSocket, decision loop |
| Speech-to-text | **Deepgram Flux** (streaming, `/v2/listen`) | `flux-general-en` | Transcription and end-of-turn detection |
| Conversation | **Google Gemini** (Interactions API, structured JSON output) | `gemini-3.8-flash`, thinking level `low` | Fact extraction and question phrasing |
| Text-to-speech | **Gemini TTS** | `gemini-3.8-flash-lite-tts`, voice `Kore` | Spoken replies (WAV) |
| Classification | **Jev** (TypeSafe AI, "System One" decision API) | `jev-latest` (= `jev-1.13.0` during development) | Bounded simulation labels with confidence |
| Storage | **MongoDB** | database `emergency_voice_agent`, collection `incidents` | Stores incidents and debug metadata |

All API keys stay in the backend (`.env`). The browser talks only to our own backend, never directly to Deepgram, Gemini or Jev.

---

## 3. Architecture

### 3.1 Components

```
 Browser (React)                               Backend (FastAPI, one process)
 ┌──────────────────────────┐   WebSocket    ┌────────────────────────────────────────────────┐
 │ Microphone → AudioWorklet│  16-bit PCM    │ VoiceSession (main.py)                          │
 │  (16 kHz, 80 ms chunks)  ├───────────────►│   audio is forwarded only while "listening",    │
 │                          │                │   otherwise replaced by silence                 │
 │ React Bits Orb (state)   │                │        │                                        │
 │ Caption + debug panel    │  JSON events   │        ▼                                        │
 │ WAV playback             │◄───────────────┤ Deepgram Flux STT ── EndOfTurn ──► IntakeAgent   │
 └──────────────────────────┘                │                                   (intake_agent.py)
                                             │                                        │        │
                                             │   ┌────────────────────────────────────┤        │
                                             │   ▼                    ▼               ▼        │
                                             │ Gemini            Intake policy       Jev       │
                                             │ extract facts +   (deterministic)    4 typed    │
                                             │ phrase questions  which question?    questions  │
                                             │                   stop?              + confidence│
                                             │        │                                │       │
                                             │        ▼                                ▼       │
                                             │ Gemini TTS (reply audio)       canonical Incident│
                                             └─────────────────────────────────────────┼───────┘
                                                                                       ▼
                                                                    MongoDB (incident + metadata)
```

### 3.2 Division of responsibilities

The central design decision: each part does one kind of work.

| Part | Responsible for | Not responsible for |
|---|---|---|
| **Gemini** (generative LLM) | Understanding free speech; extracting *observations* into a fixed schema; marking what is known, unknown or not relevant; phrasing natural questions | Choosing which question to ask; deciding when to stop; classification |
| **Intake policy** (deterministic Python) | *Which* piece of information is asked next, and *when* the conversation stops | Language |
| **Jev** (decision model) | Mapping the collected observations onto bounded simulation categories, with a calibrated confidence per answer | Generating text; talking to the caller |
| **Backend** | State, merging rules, clarification limit, building and validating the canonical incident, persistence, failure handling | — |

This separation keeps the system **predictable and testable**: the decisions that matter for the simulation (what to ask, when to stop, which label to accept) are deterministic code or calibrated, bounded answers, not free-form LLM output. The question-selection logic is covered by unit tests without any LLM.

### 3.3 Design principles

- **Adaptive, not a questionnaire.** Every caller turn is fully mined for facts, and nothing already answered is asked again.
- **One question at a time**, short and phrased for speech.
- **Observations, not diagnoses.** The agent records "left arm weakness", never "stroke".
- **Unknown is a valid answer.** The call does not continue just to fill fields.
- **Stateless LLM calls.** The backend keeps the conversation state and the transcript, and sends both with every Gemini request.
- **Server-side credentials** and a single backend process. No queues, agent frameworks or extra services.

---

## 4. The intake process

### 4.1 Dutch-112-inspired intake pattern

The conversation follows the general, publicly documented structure of Dutch emergency intake. It does **not** reproduce the proprietary ProQA/NTS protocols:

1. **Where** is the emergency?
2. **What** happened?
3. **Vital functions**, when relevant: responsiveness (consciousness), breathing, severe bleeding.
4. **Incident-specific context**, only when relevant: number of patients, entrapment, immediate danger at the scene.
5. **Stop** as soon as enough is known for a useful incident.

The greeting therefore starts with location: *"112 emergency assistance. Where is the emergency?"*

### 4.2 What happens in one caller turn

```
caller speech
   │  Deepgram Flux: EndOfTurn → final transcript
   ▼
1. Gemini call (one per turn): extract ALL facts from the transcript so far and
   write one natural question for every piece of information still needed
   ▼
2. Merge the extraction into the live working state (merge rules, §4.4)
   ▼
3. Intake policy: list the relevant, unknown, not-yet-asked topics in priority order
   │
   ├── something missing → ask the highest-priority one (Gemini's wording, or a fixed fallback)
   │                       → Gemini TTS → browser plays it → listening again
   │
   └── nothing missing   → Jev classification → labels written into the same state
                            ├── an important label is uncertain and no clarification used yet
                            │     → Gemini phrases ONE clarification question → caller answers
                            │     → state updated → Jev runs again → finalize
                            └── otherwise → build and validate the canonical Incident
                                          → MongoDB → closing sentence
```

After every step the backend sends the live state to the debug panel: the working state, a checklist of the information topics, and a draft of the final Incident JSON. The JSON therefore *fills up visibly during the call* instead of appearing only at the end.

### 4.3 The live working state

The working state (`backend/models/working_state.py`) is internal. It holds every fact the caller has supplied, plus bookkeeping:

```json
{
  "session_id": "…", "incident_id": "INC-…", "status": "collecting",
  "location":  { "value": "Outside the Vrijhof, University of Twente", "status": "known", "source_turn": 1 },
  "incident":  { "description": { "value": "…", "status": "known", "source_turn": 1 },
                 "mechanism":   { "value": "bicycle fall", "status": "known", "source_turn": 1 } },
  "patients":  { "count": { "value": 1, "status": "known", "source_turn": 1 } },
  "patient_state": {
    "consciousness":   { "value": "conscious", "status": "known", "source_turn": 1 },
    "breathing":       { "value": null, "status": "unknown", "source_turn": null },
    "severe_bleeding": { "value": null, "status": "unknown", "source_turn": null },
    "symptoms": ["head injury", "bleeding"]
  },
  "scene": { "entrapment":       { "value": null, "status": "not_relevant", "source_turn": 1 },
             "immediate_danger": { "value": null, "status": "not_relevant", "source_turn": 1 } },
  "conversation_summary": "…",
  "incident_type": "unknown", "severity": "unknown", "classification": null,
  "asked_topics": []
}
```

Every fact has a **status**:

| Status | Meaning |
|---|---|
| `known` | The caller supplied it (or it is obvious, e.g. someone who is talking is conscious). |
| `unknown` | Relevant, but not known yet. A candidate for a question. |
| `not_relevant` | Does not apply to this incident (e.g. entrapment for a collapse at home). Never asked. |

`source_turn` records which caller turn supplied the value. This is useful for analysis and for showing the state evolving in the demo.

### 4.4 Merge rules

Gemini returns the complete current picture every turn. The backend merges it conservatively (`intake_policy.merge_turn`):

- A known value is replaced only by another known value, so corrections work ("actually he is not breathing").
- `unknown` and `not_relevant` **never erase** a value the caller already gave.
- A `not_relevant` field may become `unknown` again when new information makes it relevant (e.g. the caller mentions a car crash, so entrapment becomes relevant).
- Symptoms: Gemini returns a refined, complete list, which replaces the old one. An empty list never erases symptoms.
- A patient count of 0 or less is ignored.

### 4.5 Question selection (backend policy)

`intake_policy.py` decides **what** to ask. Gemini only decides **how** to say it. The topics, in priority order:

| Priority | Topic | Fallback wording (used if Gemini gives none) |
|---|---|---|
| 1 | `location` | "Where is the emergency?" |
| 2 | `what_happened` | "Tell me what happened." |
| 3 | `consciousness` | "Are they responding to you?" |
| 4 | `breathing` | "Are they breathing normally?" |
| 5 | `severe_bleeding` | "Is there any severe bleeding?" |
| 6 | `patient_count` | "About how many people are injured?" |
| 7 | `entrapment` | "Is anyone trapped?" |
| 8 | `immediate_danger` | "Is there any immediate danger at the scene?" |

Rules:
- Only topics whose status is `unknown` are candidates. `known` and `not_relevant` topics are skipped.
- Each topic is asked **at most once**. If the caller cannot answer, the field stays `unknown` and the conversation moves on.
- The highest-priority candidate is asked. The greeting's location question does not count as asked, so if the caller ignores it, location is asked again.
- Gemini cannot add new kinds of questions: its question fields exist only for these eight topics.
- Hard limit: at most **8** questions (`MAX_INTAKE_QUESTIONS`).

**Relevance** is judged by Gemini, guided by the prompt:
- severe bleeding is relevant for injuries, accidents and reported bleeding, and not relevant for e.g. chest pain or a collapse without injury;
- entrapment only for vehicle collisions, machinery or collapsed structures;
- immediate danger only for traffic scenes, fire, smoke, gas, electricity, water or violence;
- patient count is 1 when the caller clearly talks about one person ("my father") and is asked only when unclear.

### 4.6 Stopping condition

The conversation stops collecting when **no relevant topic is still missing**: every topic is known, not relevant, or already asked once. Unknown values are acceptable. The agent never asks just to complete the JSON.

### 4.7 Prompting Gemini

The system prompt (`backend/prompts/emergency_agent.py`) tells Gemini to:
- **Extract** every useful fact each turn into fixed fields (location, description, mechanism, patient count, consciousness, breathing, severe bleeding, entrapment, immediate danger, symptoms, summary), keeping earlier values.
- Infer only the obvious, and never invent. In particular, it must not turn silence into "normal" or "absent".
- Record **observations, not diagnoses** ("speech difficulty", not "stroke").
- Write one short, natural question for each still-needed topic, e.g. "Are they responding to you?" rather than "Please specify consciousness status."
- Never ask for BSN, insurance, GP, medication lists, medical history or identity details.
- Give no medical advice and make no promises. The only allowed reassurance is "Help is being arranged.", and only when the caller asks something or begs for help.

Gemini returns **structured output**: a JSON object validated against a Pydantic schema (`GeminiTurn`), never free text that needs parsing.

### 4.8 Example conversation (real Gemini and Jev output, 3 October 2026)

```
Agent:  112 emergency assistance. Where is the emergency?
Caller: I'm outside the Vrijhof at the University of Twente. My friend fell off his bike
        and hit his head. He's awake but bleeding.
        → known in one turn: location, what happened, mechanism "bicycle fall",
          consciousness "conscious", patient count 1; symptoms ["head injury", "bleeding"]
        → entrapment and scene danger: not relevant
Agent:  Is he breathing normally?
Caller: Yes.
Agent:  Is the bleeding heavy or pouring out?
Caller: No, it's not that much, it's slowing down.
        → nothing relevant missing → Jev: trauma (1.00), urgent (0.79), no (0.99), no (1.00)
Agent:  Thank you. I have recorded the incident and passed it on for dispatch.
        Please stay with the patient.
```

Location, what happened and consciousness were never asked: the caller had already said them.

Behaviour on the scenarios from the requirements, checked against the real APIs (`tests/test_live_scenarios.py`):

| Scenario | Caller's first sentence | Observed behaviour |
|---|---|---|
| A | "I'm at the Vrijhof. My friend fell from his bike. He's conscious and breathing normally." | Asked only about severe bleeding |
| B | "My father collapsed." | Asked one question: the location |
| C | "There's been a car crash at the Hengelosestraat. Three people are injured and one is trapped." | Extracted 3 patients and entrapment = yes; next asked whether the injured are responding |
| D | "My husband can't move his left arm and his speech sounds strange. We're at home at Calslaan 12 in Enschede." | Symptoms "left arm weakness", "speech difficulty"; no diagnosis stored |
| E | "My dad collapsed at the station and he's making weird breathing noises." | Breathing recorded as abnormal, never "normal" |

---

## 5. Jev classification

### 5.1 What Jev is

Jev (TypeSafe AI) is a **"System One" decision model**. It does not generate text. It receives a *state* (text or JSON) and a set of *typed questions*, and returns structured answers. A **Choice** question returns the chosen option, a **probability for every option** and a **confidence** between 0 and 1 derived from that distribution. TypeSafe describes the model as trained for calibrated probabilities, so confidence is a usable signal for "the model is not sure".

In this project Gemini *understands* what the caller said, and Jev *maps* it onto what the simulation needs.

### 5.2 API usage

- Endpoint: `POST https://api.typesafe.ai/v1/systemone`, `Authorization: Bearer <JEV_API_KEY>`, model `jev-latest`.
- One request per classification run, with all four questions answered in parallel.
- Retries on `429` (rate limited) and `529` (overloaded): up to 3 attempts with 0.5 s and 1 s back-off; 15 s timeout.
- All Jev-specific code is in **one adapter**, `backend/services/jev_service.py`. It builds the request and converts the response into the project's own `ClassificationResult`. No other file reads Jev's JSON.

### 5.3 Input (the "state" sent to Jev)

Only information relevant to classification. No location, IDs or bookkeeping:

```json
{
  "incident_description": "Friend fell off his bike and hit his head.",
  "mechanism": "bicycle fall",
  "patient_state": { "consciousness": "conscious", "breathing": "normal", "severe_bleeding": "absent" },
  "symptoms": ["head injury", "minor bleeding"],
  "number_of_patients": 1,
  "scene": { "entrapment": "not_relevant", "immediate_danger": "not_relevant" },
  "conversation_summary": "…",
  "call_transcript": ["Call-taker: 112 emergency assistance. Where is the emergency?", "Caller: …"]
}
```

Unknown facts are sent as the word `"unknown"` or `"not_relevant"`, so Jev sees explicitly what is missing. The short transcript is included because it grounds vague wording (e.g. "strange noises") that a summary may lose.

### 5.4 The four questions

All four are **Choice** questions. A Noul (yes/no) question returns only a probability and no confidence, which is why Choice is used even for yes/no concerns. Every question has an explicit `uncertain` option ("The information provided is not enough to decide."), so Jev can say "insufficient information" instead of being forced to guess.

| Question | Options and criteria given to Jev |
|---|---|
| `incident_type`: "What is the main type of this simulated emergency incident?" | `cardiac_or_circulatory`: chest pain, cardiac arrest, sudden collapse with suspected heart cause, fainting from circulation problems · `respiratory`: breathing problem as the main issue (asthma, choking, severe shortness of breath) · `trauma`: physical injury from an external cause (fall, traffic accident, sports injury, blow to the head) · `neurological`: stroke symptoms, seizure, sudden confusion or unresponsiveness without an injury · `bleeding`: bleeding is the main problem, no other major injury · `other` · `uncertain` |
| `severity`: "How severe is the patient's condition for this simulation?" | `critical`: immediately life-threatening (unconscious, not breathing or breathing abnormally, or severe bleeding) · `urgent`: serious, needs help soon, but conscious and breathing · `non_urgent`: minor problem, stable · `uncertain` |
| `consciousness_concern` | `yes`: unconscious, unresponsive, confused or drowsy · `no`: awake, alert, responding normally · `uncertain` |
| `breathing_concern` | `yes`: not breathing, or breathing abnormally (gasping, struggling, noisy or strange sounds) · `no`: breathing normally · `uncertain` |

### 5.5 Confidence rule

A label is **accepted** only if Jev did not choose `uncertain` **and** its confidence is at least the threshold `JEV_CONFIDENCE_THRESHOLD` (default **0.70**). Otherwise the stored value is `uncertain`, and the low confidence is kept for transparency.

### 5.6 Clarification (at most one)

If any of the four labels is not accepted:
1. The backend tells Gemini which information is missing for the classifier (e.g. "whether the patient is breathing normally right now").
2. Gemini phrases **one** clarification question, worded differently from earlier questions. If Gemini fails, a fixed fallback is used.
3. The caller answers, the state is updated, and Jev runs **again**.
4. Whatever is still uncertain is stored as `uncertain`. `MAX_CLASSIFICATION_CLARIFICATIONS = 1` prevents loops.

No clarification is asked when Jev is unavailable: asking the caller cannot fix an outage.

### 5.7 Enrichment of the incident

Jev's results are written into the **same** working state and the same Incident JSON, not into a separate object. Before Jev, the draft shows `"type": "unknown"` and empty classifications. After Jev:

```json
"incident": { "description": "Friend fell off his bike and hit his head.", "mechanism": "bicycle fall",
              "type": "trauma", "severity": "urgent" },
"classification": {
  "incident_type":         { "value": "trauma", "confidence": 1.0 },
  "severity":              { "value": "urgent", "confidence": 0.79 },
  "consciousness_concern": { "value": "no",     "confidence": 0.99 },
  "breathing_concern":     { "value": "no",     "confidence": 1.0 }
}
```

### 5.8 Observed Jev results during development

These are real Jev answers (`jev-1.13.0`), from single development runs, not a systematic evaluation. Inputs from 27 September used the earlier, simpler state format.

| Date | Situation (input state) | incident_type | severity | consciousness_concern | breathing_concern |
|---|---|---|---|---|---|
| 27 Sep | Father collapsed, unresponsive, gasping | cardiac_or_circulatory 1.00 | critical 1.00 | yes 1.00 | yes 1.00 |
| 27 Sep | Cyclist, awake, head wound, breathing normally | trauma 1.00 | urgent 0.99 | no 0.99 | no 1.00 |
| 27 Sep | Man collapsed, "strange noises", nothing else known | cardiac_or_circulatory 0.63 → **uncertain** | critical 0.66 → **uncertain** | yes 0.43 → **uncertain** | yes 0.99 |
| 27 Sep | Caller cannot see the patient, answers "I don't know" | `uncertain` chosen (0.99) | `uncertain` (0.99) | `uncertain` (0.92) | `uncertain` (0.99) → one clarification → still uncertain |
| 3 Oct | Bicycle fall at the Vrijhof, ordinary bleeding | trauma 1.00 | urgent 0.89 | no 1.00 | no 1.00 |
| 3 Oct | Same, but heavy bleeding (`severe_bleeding: present`) | trauma 1.00 | **critical** 0.94 | no 1.00 | no 1.00 |

Observations useful for the report:
- With clear caller answers, Jev is highly confident and no clarification is needed.
- Gemini tends to normalise vague phrases into clear fields ("making strange noises" becomes `breathing: abnormal`), after which Jev is confident. Clarification is therefore triggered mainly when information is genuinely **missing** (e.g. the caller cannot see the patient), less by vague wording.
- The explicit `uncertain` option works: with no information, Jev chooses `uncertain` with high confidence rather than guessing.
- The bleeding pair shows Jev's severity responds to the `severe_bleeding` field. This motivated the definition "present = heavy or uncontrolled bleeding" (§6.5): ordinary bleeding would otherwise be rated critical.

### 5.9 Failure handling

If Jev is unreachable, returns an error, or returns something malformed, all four labels become `uncertain` with `confidence: null`, and the error is shown in the debug panel. The incident is **still created and stored**: a Jev failure never ends the conversation.

---

## 6. Incident format (the contract with the simulation)

### 6.1 Design goals

The canonical Incident JSON is the **interface between the voice agent and the Mesa simulation** (and later the synthetic generator). It is designed to be:
- **deterministic in structure:** every key is always present; no extra keys allowed;
- **fully enumerated:** all categorical fields have documented values;
- **source-independent:** nothing voice-specific is required, and `session_id` may be `null`;
- **free of LLM/Jev internals:** no field statuses, transcripts or raw model output;
- **easy to parse in Python** and validated by both a Pydantic model and a JSON Schema.

### 6.2 Three related objects

| Object | Where | Purpose |
|---|---|---|
| **Working state** | backend memory; saved in MongoDB `metadata` | Field statuses, source turns, asked topics, Jev labels. Internal only. |
| **Live draft** | debug panel only | Canonical structure built from the working state during the call: `status: "collecting"`, labels `"unknown"`, `created_at: null`. Never stored or sent to the MAS. |
| **Canonical Incident** | MongoDB `incident`; the contract | Built by the same function as the draft, then validated. `status: "ready_for_dispatch"`. |

### 6.3 Structure and fields (schema version 1.0)

| Field | Type | Meaning |
|---|---|---|
| `schema_version` | `"1.0"` | Contract version |
| `incident_id` | string | Unique ID, format `INC-` + 12 uppercase hex characters (e.g. `INC-7C41A2E9B05D`) |
| `session_id` | string \| null | Voice session ID; `null` for synthetic incidents |
| `created_at` | ISO-8601 UTC string | Time the incident was finalized |
| `source` | enum | `voice_agent` \| `synthetic_generator` |
| `location.raw_text` | string \| null | Location as described by the caller |
| `location.latitude`, `location.longitude` | number \| null | Currently always `null` (no geocoding in the agent) |
| `incident.description` | string (non-empty) | One factual sentence; `"No description provided by caller."` if nothing was said |
| `incident.mechanism` | string \| null | How it happened, e.g. `"bicycle fall"` |
| `incident.type` | enum | Simulation incident type (equals `classification.incident_type.value`) |
| `incident.severity` | enum | Simulation severity (equals `classification.severity.value`) |
| `patients.count` | integer ≥ 1 \| null | Number of patients |
| `patients.primary_patient.consciousness` | enum | |
| `patients.primary_patient.breathing` | enum | |
| `patients.primary_patient.severe_bleeding` | enum | |
| `patients.primary_patient.symptoms` | list of strings | Observations in plain words; never diagnoses |
| `scene.entrapment` | enum | Is anyone trapped? |
| `scene.immediate_danger` | enum | Danger at the scene? |
| `classification.{incident_type, severity, consciousness_concern, breathing_concern}` | `{ value, confidence }` | Final label and Jev's confidence (0–1, or `null`) |
| `status` | `"ready_for_dispatch"` | Always this value in a canonical incident |

`primary_patient` describes the patient the caller talked about, or the most seriously affected one when there are several. Other patients are only counted.

### 6.4 Enumerations

| Field | Values |
|---|---|
| `incident.type` | `cardiac_or_circulatory`, `respiratory`, `trauma`, `neurological`, `bleeding`, `other`, `uncertain` |
| `incident.severity` | `critical`, `urgent`, `non_urgent`, `uncertain` |
| `consciousness` | `conscious`, `unconscious`, `unknown` |
| `breathing` | `normal`, `abnormal`, `not_breathing`, `unknown` |
| `severe_bleeding` | `present`, `absent`, `unknown` |
| `entrapment`, `immediate_danger` | `yes`, `no`, `unknown`, `not_relevant` |
| `consciousness_concern`, `breathing_concern` | `yes`, `no`, `uncertain` |

### 6.5 Semantics of special values

| Value | Used in | Meaning |
|---|---|---|
| `null` | free text, numbers | No value (not said, or not applicable) |
| `unknown` | observation enums | Relevant, but the information is not available |
| `not_relevant` | scene fields | The question does not apply to this incident |
| `uncertain` | classification labels | The classifier could not decide confidently (below the threshold, or chose `uncertain`) |
| `severe_bleeding: present` | patient | Heavy or uncontrolled bleeding. Ordinary bleeding is `absent` and appears in `symptoms`. |
| `conscious` | patient | Responds (awake, talking). Confusion or drowsiness goes into `symptoms`. |

### 6.6 Validation

- **Pydantic model** `Incident` (`backend/models/incident.py`): `extra="forbid"` on every object, enums as `Literal` types, numeric ranges (confidence 0–1, latitude ±90, longitude ±180, count ≥ 1). A model validator enforces `incident.type == classification.incident_type.value` and `incident.severity == classification.severity.value`.
- **JSON Schema** `schemas/incident.schema.json`, generated from the model (`python export_schema.py`). Every key is marked *required*. A unit test fails if the file is out of date.
- `examples/sample_incident.json` is validated against both in the tests. Its confidences are `null`, so it does not present fabricated values as Jev measurements.

### 6.7 Example (`examples/sample_incident.json`)

```json
{
  "schema_version": "1.0",
  "incident_id": "INC-7C41A2E9B05D",
  "session_id": "3f2b8c1e-9d4a-4e7b-a6c2-81d5f0e93a47",
  "created_at": "2026-10-03T14:22:37.418Z",
  "source": "voice_agent",
  "location": { "raw_text": "Outside the Vrijhof, University of Twente", "latitude": null, "longitude": null },
  "incident": { "description": "Friend fell off his bicycle and hit his head.", "mechanism": "bicycle fall",
                "type": "trauma", "severity": "urgent" },
  "patients": { "count": 1,
                "primary_patient": { "consciousness": "conscious", "breathing": "normal", "severe_bleeding": "absent",
                                     "symptoms": ["head injury", "bleeding from the head"] } },
  "scene": { "entrapment": "not_relevant", "immediate_danger": "not_relevant" },
  "classification": {
    "incident_type": { "value": "trauma", "confidence": null },
    "severity": { "value": "urgent", "confidence": null },
    "consciousness_concern": { "value": "no", "confidence": null },
    "breathing_concern": { "value": "no", "confidence": null }
  },
  "status": "ready_for_dispatch"
}
```

### 6.8 Storage in MongoDB

Database `emergency_voice_agent`, collection `incidents`, one document per finalized incident. The canonical incident is kept separate from debugging data:

```json
{
  "_id": "<incident_id>",
  "incident": { "…canonical Incident (the contract)…" },
  "metadata": {
    "session_id": "…",
    "transcript": [{ "speaker": "agent|user", "text": "…", "timestamp": "…" }],
    "working_state": { "…field statuses, source turns, asked topics…" },
    "classification_runs": [{ "run": 1, "labels": { "…" }, "uncertain_fields": [] }],
    "jev_raw": [{ "…raw Jev response per run…" }],
    "clarifications_used": 0,
    "confidence_threshold": 0.7,
    "models": { "llm": "…", "tts": "…", "stt": "…", "jev": "…" }
  },
  "created_at": "<datetime>"
}
```

The simulation reads only `incident`. No audio is stored. A local MongoDB can be started with `docker compose up -d` (`docker-compose.yml`); MongoDB Atlas or another hosted instance works via `MONGODB_URI`.

---

## 7. Voice pipeline and real-time behaviour

### 7.1 Audio path

1. **Capture:** the browser opens the microphone (`getUserMedia`, with echo cancellation and noise suppression). An **AudioWorklet** (`public/pcm-processor.js`) converts it to 16-bit mono PCM at 16 kHz (falling back to the device rate if needed), in 80 ms chunks as recommended by Deepgram.
2. **Transport:** chunks go over **one WebSocket** to the backend, which forwards them to **Deepgram Flux**. The Deepgram key never reaches the browser.
3. **Turn-taking:** Flux's built-in end-of-turn detection emits `EndOfTurn` when the caller has finished speaking. This triggers the agent. Interim transcripts are shown live.
4. **Half-duplex:** while the agent is thinking or speaking, the backend sends **silence** to Deepgram instead of microphone audio, so the agent never transcribes itself. Barge-in (interrupting the agent) is not implemented.
5. **Reply:** Gemini TTS produces a complete WAV (24 kHz, mono). It is sent base64-encoded over the WebSocket and played in the browser. When playback ends, the browser reports `playback_done` and the state returns to *listening*.
6. **Keyterm prompting:** Deepgram receives a list of local place names (`DEEPGRAM_KEYTERMS`, default "University of Twente, Twente, Enschede, Hengelo") to reduce mis-hearings.

### 7.2 WebSocket protocol

| Browser → server | Meaning |
|---|---|
| binary frame | 16-bit PCM microphone audio (~80 ms) |
| `{"type":"start","mode":"voice"\|"text","sample_rate":16000}` | Start; the agent greets |
| `{"type":"user_text","text":"…"}` | Typed caller message (text mode / testing) |
| `{"type":"playback_done"}` | Agent audio finished playing |
| `{"type":"retry"}` | Retry the last turn after a recoverable error |
| `{"type":"end"}` | Caller ends the call. What is known is classified and saved. |

| Server → browser | Meaning |
|---|---|
| `state` | `listening` / `thinking` / `speaking` / `completed` / `error`. Drives the Orb. |
| `transcript` | Live (interim) or final caller text |
| `agent_response` | What the agent says |
| `audio` | The spoken reply (WAV, base64) |
| `incident_state` | Working state, topic checklist, next topic, and the draft Incident JSON |
| `classification` | One Jev run: raw value, confidence, final label and probabilities per question |
| `incident_complete` | Final canonical incident + whether it was persisted |
| `error` | Source (`deepgram`, `gemini`, `tts`, `jev`, `backend`, `microphone`) + message + recoverable flag |
| `session_ended` | Reply to `end` |

### 7.3 User interface

- **Main screen:** the React Bits Orb, a status label inside the orb, the agent's current sentence as a caption, the caller's live transcript, an *End conversation* button, and the disclaimer "Research prototype — not for real emergency use."
- **Orb states:** the Orb's own properties (`hue`, `hoverIntensity`, `forceHoverState`, `rotateOnHover`) are mapped to the agent state. Idle uses hue 0 with subtle motion. Listening uses hue 60, with intensity following microphone loudness. Thinking uses hue −100, with a constant stronger distortion and a slow pulse. Speaking uses hue 0, with intensity following the agent's voice. Completed uses hue 125 (green); error uses hue −80 (red). The React Bits component was changed locally only to read its properties every frame instead of rebuilding the WebGL context, so the transitions are smooth.
- **Developer / Debug panel:** transcript (with a text box to type as the caller); *Information needed* checklist (each topic shown as known, asking now, missing, caller unsure or not relevant); live working state; Jev classification (confidence bars with the threshold marked); and the Incident JSON (live draft, then final, with persistence status). Lines in the JSON views that changed since the last update briefly light up.

---

## 8. Error handling

| Failure | Behaviour |
|---|---|
| Microphone denied | "Microphone access is required." with a **Restart** button |
| Deepgram unavailable or invalid key | Error shown; the user can restart the conversation |
| Gemini error | Error shown with **Retry**: the same caller message is processed again, without duplicating it |
| Gemini fails while phrasing a clarification | A fixed fallback question is used |
| Gemini gives no wording for the chosen topic | The fixed fallback wording for that topic is used |
| TTS error | The reply is shown as text; the conversation continues |
| Jev unavailable | Labels become `uncertain`; no clarification; incident still created and stored |
| MongoDB unavailable | Incident kept in backend memory (still retrievable via `GET /api/incidents/{id}`); the UI shows that saving failed |
| Caller ends the call mid-turn | The current step finishes silently, then whatever is known is classified and saved |

---

## 9. Testing and evaluation

### 9.1 Automated tests (`backend/tests/`, run with `pytest`)

63 tests, using fake providers, so no API keys or network are needed:

| File | Tests | Covers |
|---|---|---|
| `test_intake_policy.py` | 14 | Scenarios A–E for question selection, merge rules, relevance switching, ask-once rule, draft JSON filling up, Jev enrichment, final JSON construction |
| `test_intake_agent.py` | 13 | Full conversation flows: the example above, the collapse flow, clarification (and its fallback), Jev outage, Jev exception, MongoDB outage, Gemini retry, caller who knows nothing, ending early |
| `test_incident_model.py` | 18 | Contract validation: the sample file, enums, ranges, extra fields rejected, type/severity consistency, synthetic-generator compatibility, schema file up to date |
| `test_confidence.py` | 8 | Confidence threshold logic |
| `test_jev_service.py` | 5 | Jev response normalisation (including malformed answers), the question label sets, the Jev input state |
| `test_websocket.py` | 4 | The WebSocket protocol end to end in text mode, ending during a turn, unknown session, health endpoint |
| `test_deepgram_service.py` | 1 | Flux connection URL (model, audio format, keyterms) |

`test_live_scenarios.py` holds 5 extra tests that call the **real** Gemini and Jev for scenarios A–E. They are opt-in (`RUN_LIVE_TESTS=1`) because LLM output varies; their assertions check behaviour, not exact wording.

### 9.2 End-to-end checks performed

- Each provider was checked live (MongoDB write/read/delete, Jev, Gemini LLM, Gemini TTS, Deepgram).
- **Full voice conversation:** Gemini TTS generated the caller's sentences, which were fed to the real app in the browser in place of the microphone. They passed through the worklet, WebSocket, Deepgram, Gemini, Jev, TTS playback and MongoDB. The incident was stored and validated.
- **Text-mode conversation** in the browser, with screenshots of the debug panel during and after the call.

### 9.3 Measured latency (development machine, 27 September 2026, small sample)

| Step | Observed |
|---|---|
| Gemini turn (`gemini-3.8-flash`, thinking `low`) | ~1.5–3 s (one call of 4.3 s) |
| Gemini TTS | ~2.7 s for a reply of ~5 s audio |
| Deepgram end-of-turn after the caller stops | ~1 s (1.4 s in a separate test) |
| Caller stops speaking → agent starts speaking | ~4.3 s on a normal turn; ~7.8 s on the final turn (adds Jev and a longer closing sentence) |

### 9.4 Findings from development (useful for the report)

- **Gemini invented a value.** It once recorded "no bleeding" although bleeding was never mentioned. Fixed with an explicit prompt and schema rule ("do not turn silence into normal or absent"), and verified afterwards.
- **Gemini over-promised.** It once said "Emergency services are on their way" unprompted. The allowed reassurance is now restricted to "Help is being arranged.", and only when the caller asks for it.
- **Bleeding semantics.** Jev rated "heavy bleeding" critical and ordinary bleeding urgent. So `severe_bleeding: present` is reserved for heavy or uncontrolled bleeding, and ordinary bleeding goes into `symptoms`.
- **Place names.** Deepgram heard "Twente" as "twenty" or "Tuente", and a stored incident contains "Rablin" (probably "Ravelijn"). With keyterm prompting, both TTS test sentences were transcribed correctly, against neither without it (a small test with synthetic speech).
- **Confidence-gated clarification** is rarely needed with cooperative callers (§5.8). The clarification step is mainly exercised by callers who lack information.

---

## 10. Limitations and future work

- **Not a medical system.** Labels are simulation categories; neither the classification nor the threshold of 0.70 has been validated.
- **English only** (`flux-general-en`; Jev is most accurate in English). Dutch would need `flux-general-multi` and testing.
- **No barge-in:** the caller has to wait for the agent to finish speaking.
- **No geocoding:** the location is free text and coordinates are `null`. The simulation maps place names to coordinates itself.
- **One primary patient:** with several patients, only the most affected one is described; the others are only counted.
- **Latency** of roughly 4–8 s per turn. Streaming TTS or a faster LLM (e.g. `gemini-3.5-flash-lite`) would reduce it.
- **LLM non-determinism:** wording and relevance judgements vary between runs. The deterministic policy limits the effect on *which* information is collected.
- **Single process, in-memory sessions,** no authentication. Intended for local demos only.
- **Evaluation** consists of scenario tests and single runs, not a systematic study.

---

## 11. Structure of the conversational agent

```
conversational-agent/
├── README.md                     setup and run instructions
├── info.md                       this document
├── .env.example                  configuration template (copy to .env; .env is git-ignored)
├── docker-compose.yml            local MongoDB 8 (bound to 127.0.0.1, persistent volume)
├── docs/
│   ├── incident-schema.md        the Incident JSON contract, field by field
│   └── mesa-integration.md       how the Mesa simulation loads and uses incidents
├── examples/
│   └── sample_incident.json      realistic example incident (schema 1.0)
├── schemas/
│   └── incident.schema.json      JSON Schema generated from the Pydantic model
├── backend/                      Python / FastAPI
│   ├── main.py                   FastAPI app: REST endpoints and the WebSocket VoiceSession
│   │                             (audio routing, UI states, half-duplex muting, TTS)
│   ├── intake_agent.py           the agent's decision loop (no audio/web code)
│   ├── intake_policy.py          deterministic logic: merge rules, question priority,
│   │                             stopping condition, Jev enrichment, Incident JSON builder
│   ├── config.py                 settings from .env (pydantic-settings)
│   ├── chat_cli.py               text-only conversation in the terminal
│   ├── export_schema.py          writes schemas/incident.schema.json
│   ├── requirements.txt
│   ├── pytest.ini
│   ├── models/
│   │   ├── incident.py           canonical Incident contract (Pydantic) + enums
│   │   ├── working_state.py      live working state (facts with status and source turn)
│   │   ├── conversation.py       transcript entry; Gemini's structured output schema
│   │   └── classification.py     provider-independent classification result + threshold rule
│   ├── prompts/
│   │   └── emergency_agent.py    greeting, closing, system prompt, per-turn and clarification prompts
│   ├── services/
│   │   ├── deepgram_service.py   Deepgram Flux streaming STT client (WebSocket)
│   │   ├── gemini_service.py     Gemini structured calls (extraction, clarification)
│   │   ├── gemini_tts_service.py Gemini text-to-speech (WAV)
│   │   ├── jev_service.py        Jev adapter: questions, request, response normalisation
│   │   └── mongodb_service.py    store and fetch incidents
│   └── tests/                    63 automated tests + 5 opt-in live tests (see §9.1)
└── frontend/                     React + TypeScript (Vite)
    ├── index.html
    ├── vite.config.ts            dev server; proxies /api and /ws to the backend
    ├── public/
    │   └── pcm-processor.js      AudioWorklet: microphone → 16-bit PCM chunks
    └── src/
        ├── App.tsx               page layout and controls
        ├── main.tsx              entry point
        ├── index.css             styling (dark theme, orb glow, debug panel)
        ├── components/
        │   ├── Orb/Orb.tsx       React Bits Orb (WebGL), lightly adapted
        │   ├── VoiceOrb.tsx      maps agent state + audio level to Orb properties
        │   ├── ConversationStatus.tsx  caption, live transcript, errors
        │   └── DebugPanel.tsx    transcript, checklist, live state, Jev, Incident JSON
        ├── hooks/
        │   ├── useMicrophone.ts  microphone capture and loudness
        │   └── useVoiceAgent.ts  WebSocket protocol, conversation state, playback
        ├── services/
        │   ├── api.ts            session creation, WebSocket URL
        │   └── audioPlayer.ts    WAV playback and output loudness
        └── types/incident.ts     TypeScript types mirroring the backend models
```

### Backend endpoints

| Endpoint | Purpose |
|---|---|
| `GET /health` | Status, and which credentials are configured |
| `POST /api/session` | Creates a conversation session |
| `WS /ws/voice/{session_id}` | Audio and events (§7.2) |
| `GET /api/incidents/{incident_id}` | A stored incident (MongoDB, or in-memory fallback) |

---

## 12. Configuration

Configuration comes from `conversational-agent/.env` (template: `.env.example`).

| Variable | Default | Meaning |
|---|---|---|
| `DEEPGRAM_API_KEY`, `GEMINI_API_KEY`, `JEV_API_KEY` | — | Provider credentials |
| `MONGODB_URI` | `mongodb://localhost:27017` (in the template) | MongoDB connection |
| `GEMINI_LLM_MODEL` | `gemini-3.8-flash` | Conversation model |
| `GEMINI_THINKING_LEVEL` | `low` | Gemini reasoning effort |
| `GEMINI_TTS_MODEL` / `GEMINI_TTS_VOICE` | `gemini-3.8-flash-lite-tts` / `Kore` | Speech output |
| `DEEPGRAM_STT_MODEL` | `flux-general-en` | Speech recognition |
| `DEEPGRAM_KEYTERMS` | `University of Twente,Twente,Enschede,Hengelo` | Words Deepgram should listen for |
| `JEV_MODEL` / `JEV_API_URL` | `jev-latest` / `https://api.typesafe.ai/v1/systemone` | Classifier |
| `JEV_CONFIDENCE_THRESHOLD` | `0.70` | Minimum confidence to accept a label |
| `MAX_CLASSIFICATION_CLARIFICATIONS` | `1` | Clarification questions allowed after classification |
| `MONGODB_DATABASE` / `MONGODB_INCIDENT_COLLECTION` | `emergency_voice_agent` / `incidents` | Storage location |
| `FRONTEND_ORIGIN` | `http://localhost:5173` | Allowed browser origin |

How to install and run is in `README.md`.
