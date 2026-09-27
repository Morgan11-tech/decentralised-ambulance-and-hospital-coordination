import type { AgentErrorInfo, AgentStatus, CompletedIncident } from "../types/incident";

interface Props {
  status: AgentStatus;
  agentText: string;
  interimText: string;
  error: AgentErrorInfo | null;
  completed: CompletedIncident | null;
}

const SOURCE_NAMES: Record<string, string> = {
  gemini: "The language model",
  deepgram: "Speech recognition",
  backend: "The backend",
  microphone: "Microphone",
};

/** The spoken caption under the orb, plus live caller transcript and errors. */
export default function ConversationStatus({ status, agentText, interimText, error, completed }: Props) {
  if (status === "error" && error) {
    const who = SOURCE_NAMES[error.source] ?? error.source;
    const text = error.source === "microphone" ? error.message : `${who} ran into a problem.`;
    return (
      <div className="caption caption--error" role="alert">
        <p className="caption__agent">{text}</p>
        {error.source !== "microphone" && <p className="caption__meta">{error.message}</p>}
      </div>
    );
  }

  if (status === "idle") {
    return (
      <div className="caption">
        <p className="caption__agent caption__agent--muted">Press start and describe the emergency out loud.</p>
      </div>
    );
  }

  return (
    <div className="caption">
      {agentText && (
        <p key={agentText} className="caption__agent">
          “{agentText}”
        </p>
      )}
      {status === "listening" && interimText && <p className="caption__caller">{interimText}</p>}
      {status === "completed" && completed && (
        <p className={`caption__meta ${completed.persisted ? "" : "caption__meta--warn"}`}>
          {completed.persisted
            ? `Stored in MongoDB · ${completed.incident.incident_id.slice(0, 8)}`
            : "Incident created, but saving to MongoDB failed. It is kept in memory. See the debug panel."}
        </p>
      )}
    </div>
  );
}
