import { useState } from "react";
import ConversationStatus from "./components/ConversationStatus";
import DebugPanel from "./components/DebugPanel";
import VoiceOrb from "./components/VoiceOrb";
import { useVoiceAgent, type Mode } from "./hooks/useVoiceAgent";

export default function App() {
  const agent = useVoiceAgent();
  const [debugOpen, setDebugOpen] = useState(false);
  const { status, blockingError } = agent;
  const inCall = status === "listening" || status === "thinking" || status === "speaking";
  const canRetry = status === "error" && blockingError?.recoverable && agent.mode !== null;

  const start = (mode: Mode) => {
    if (mode === "text") setDebugOpen(true); // the text box lives in the debug panel
    void agent.start(mode);
  };

  return (
    <div className="app" data-status={status}>
      <header className="topbar">
        <div className="brand">
          <span className="brand__mark">112</span>
          <h1>Emergency Voice Agent</h1>
        </div>
        <button className="topbar__debug" onClick={() => setDebugOpen((o) => !o)} aria-expanded={debugOpen}>
          {debugOpen ? "Hide debug" : "Debug"}
        </button>
      </header>

      <main className={`stage ${debugOpen ? "stage--shifted" : ""}`}>
        <VoiceOrb status={status} level={agent.level} />

        <ConversationStatus
          status={status}
          agentText={agent.agentText}
          interimText={agent.interimText}
          error={blockingError}
          completed={agent.completed}
        />

        <div className="controls">
          {status === "idle" && (
            <>
              <button className="btn btn--primary" onClick={() => start("voice")}>
                Start conversation
              </button>
              <button className="btn btn--link" onClick={() => start("text")}>
                or type instead
              </button>
            </>
          )}

          {inCall && (
            <button className="btn btn--danger" onClick={agent.end}>
              End conversation
            </button>
          )}

          {status === "error" && (
            <>
              {canRetry ? (
                <button className="btn btn--primary" onClick={agent.retry}>
                  Retry
                </button>
              ) : (
                <button className="btn btn--primary" onClick={() => start(agent.mode ?? "voice")}>
                  Restart
                </button>
              )}
              <button className="btn btn--link" onClick={canRetry ? agent.end : agent.reset}>
                {canRetry ? "End conversation" : "Back"}
              </button>
            </>
          )}

          {status === "completed" && (
            <>
              <button className="btn btn--primary" onClick={() => start(agent.mode ?? "voice")}>
                New conversation
              </button>
              <button className="btn btn--link" onClick={() => setDebugOpen(true)}>
                View incident JSON
              </button>
            </>
          )}
        </div>
      </main>

      <footer className="disclaimer">
        <span className="disclaimer__dot" />
        Research prototype — not for real emergency use.
      </footer>

      <DebugPanel open={debugOpen} onClose={() => setDebugOpen(false)} agent={agent} onSendText={agent.sendText} />
    </div>
  );
}
