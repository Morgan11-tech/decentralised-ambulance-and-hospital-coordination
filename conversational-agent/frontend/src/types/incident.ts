// Mirrors backend/models/*.py. The canonical schema lives in schemas/incident.schema.json.

export type AgentStatus = "idle" | "listening" | "thinking" | "speaking" | "completed" | "error";

export interface PatientState {
  consciousness: "conscious" | "altered" | "unconscious" | "unknown";
  breathing: "normal" | "abnormal" | "not_breathing" | "unknown";
  bleeding: "none" | "present" | "severe" | "unknown";
}

export interface IncidentState {
  location: string | null;
  incident_description: string | null;
  conversation_summary: string | null;
  patient: PatientState;
  number_of_patients: number | null;
  incident_type: string;
  severity: string;
  status: "collecting" | "classifying" | "clarifying" | "completed";
}

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

export interface Incident {
  schema_version: string;
  incident_id: string;
  session_id: string | null;
  created_at: string;
  location: { raw_text: string | null; latitude: number | null; longitude: number | null };
  incident_description: string;
  incident_type: string;
  severity: string;
  patient: PatientState;
  number_of_patients: number | null;
  classification: Record<string, string | number | null>;
  source: "voice_agent" | "synthetic_generator";
  status: "ready_for_dispatch";
}

export interface CompletedIncident {
  incident: Incident;
  persisted: boolean;
  persistence_error: string | null;
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
  | { type: "incident_state"; state: IncidentState }
  | { type: "classification"; data: ClassificationRun }
  | ({ type: "incident_complete" } & CompletedIncident)
  | ({ type: "error" } & AgentErrorInfo)
  | { type: "session_ended"; incident_saved: boolean };
