// Mirrors backend/models/*.py. The canonical contract is documented in docs/incident-schema.md.

export type AgentStatus = "idle" | "listening" | "thinking" | "speaking" | "completed" | "error";

// --- Canonical Incident (the contract with the Mesa simulation) ---------------------

export interface LabeledValue {
  value: string;
  confidence: number | null;
}

export interface Incident {
  schema_version: string;
  incident_id: string;
  session_id: string | null;
  created_at: string | null; // null only in live drafts
  source: "voice_agent" | "synthetic_generator";
  location: { raw_text: string | null; latitude: number | null; longitude: number | null };
  incident: { description: string | null; mechanism: string | null; type: string; severity: string };
  patients: {
    count: number | null;
    primary_patient: {
      consciousness: string;
      breathing: string;
      severe_bleeding: string;
      symptoms: string[];
    };
  };
  scene: { entrapment: string; immediate_danger: string };
  classification: Record<"incident_type" | "severity" | "consciousness_concern" | "breathing_concern", LabeledValue>;
  status: "collecting" | "ready_for_dispatch"; // "collecting" = live draft, never sent to the MAS
}

export interface CompletedIncident {
  incident: Incident;
  persisted: boolean;
  persistence_error: string | null;
}

// --- Working state (internal, debug only) ---------------------------------------------

export type Topic =
  | "location"
  | "what_happened"
  | "consciousness"
  | "breathing"
  | "severe_bleeding"
  | "patient_count"
  | "entrapment"
  | "immediate_danger";

export interface TopicView {
  topic: Topic;
  status: "known" | "next" | "missing" | "unanswered" | "not_relevant";
  value: string | number | null;
}

/** The working state is shown as raw JSON, so only its envelope is typed. */
export interface WorkingState {
  session_id: string;
  incident_id: string;
  status: "collecting" | "classifying" | "clarifying" | "completed";
  [key: string]: unknown;
}

// --- Debug views ------------------------------------------------------------------------

export interface LabelView {
  value: string;
  confidence: number | null;
  final: string;
  probabilities: Record<string, number>;
}

export interface ClassificationRun {
  run: number;
  model: string | null;
  error: string | null;
  threshold: number;
  labels: Record<"incident_type" | "severity" | "consciousness_concern" | "breathing_concern", LabelView>;
  uncertain_fields: string[];
}

export interface TranscriptLine {
  speaker: "user" | "agent";
  text: string;
}

export interface AgentErrorInfo {
  source: string;
  message: string;
  recoverable: boolean;
}

/** Events sent by the backend over the WebSocket (see backend/main.py). */
export type ServerEvent =
  | { type: "state"; state: AgentStatus }
  | { type: "transcript"; speaker: "user"; text: string; final: boolean }
  | { type: "agent_response"; text: string }
  | { type: "audio"; format: "wav"; data: string }
  | { type: "incident_state"; state: WorkingState; topics: TopicView[]; next_topic: Topic | null; incident: Incident }
  | { type: "classification"; data: ClassificationRun }
  | ({ type: "incident_complete" } & CompletedIncident)
  | ({ type: "error" } & AgentErrorInfo)
  | { type: "session_ended"; incident_saved: boolean };
