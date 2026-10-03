import { useEffect, useMemo, useRef, useState, type FormEvent, type ReactNode } from "react";
import type { VoiceAgentState } from "../hooks/useVoiceAgent";
import type { ClassificationRun, Topic, TopicView } from "../types/incident";

interface Props {
  open: boolean;
  onClose: () => void;
  agent: VoiceAgentState;
  onSendText: (text: string) => void;
}

export default function DebugPanel({ open, onClose, agent, onSendText }: Props) {
  const latestRun = agent.classifications.at(-1);
  const incident = agent.completed?.incident ?? agent.liveIncident;
  const persistText = !agent.completed
    ? "Live draft · becomes final when the call completes"
    : agent.completed.persisted
      ? "Final · persisted to MongoDB"
      : `Final · not persisted: ${agent.completed.persistence_error ?? "unknown error"}`;
  const persistClass = !agent.completed ? "debug__persist--draft" : agent.completed.persisted ? "" : "debug__persist--fail";

  return (
    <aside className={`debug ${open ? "debug--open" : ""}`} aria-hidden={!open} inert={!open}>
      <header className="debug__header">
        <span>Developer / Debug</span>
        <button className="debug__close" onClick={onClose} aria-label="Close debug panel">
          ×
        </button>
      </header>

      <div className="debug__body">
        <Section title="Transcript" count={agent.transcript.length} defaultOpen>
          <Transcript agent={agent} />
          <TextInput enabled={agent.status === "listening"} onSend={onSendText} />
        </Section>

        <Section title="Information needed" defaultOpen>
          {agent.topics.length ? <Topics topics={agent.topics} /> : <p className="debug__empty">Starts with the call.</p>}
        </Section>

        <Section title="Live working state" defaultOpen>
          {agent.workingState ? <LiveJson value={agent.workingState} /> : <p className="debug__empty">Nothing collected yet.</p>}
        </Section>

        <Section title="Jev classification" count={agent.classifications.length} defaultOpen>
          {latestRun ? <Classification run={latestRun} /> : <p className="debug__empty">Not classified yet.</p>}
        </Section>

        <Section title="Incident JSON · Mesa contract" defaultOpen>
          {incident ? (
            <>
              <p className={`debug__persist ${persistClass}`}>{persistText}</p>
              <LiveJson value={incident} copyable={!!agent.completed} />
            </>
          ) : (
            <p className="debug__empty">Fills up as the caller answers.</p>
          )}
        </Section>

        <Section title="Errors" count={agent.errorLog.length}>
          {agent.errorLog.length ? (
            <ul className="debug__errors">
              {agent.errorLog.map((e, i) => (
                <li key={i}>
                  <b>{e.source}</b> {e.message}
                </li>
              ))}
            </ul>
          ) : (
            <p className="debug__empty">No errors.</p>
          )}
        </Section>
      </div>
    </aside>
  );
}

function Section({
  title,
  count,
  defaultOpen,
  children,
}: {
  title: string;
  count?: number;
  defaultOpen?: boolean;
  children: ReactNode;
}) {
  return (
    <details className="debug__section" open={defaultOpen}>
      <summary>
        {title}
        {count !== undefined && <span className="debug__count">{count}</span>}
      </summary>
      <div className="debug__content">{children}</div>
    </details>
  );
}

function Transcript({ agent }: { agent: VoiceAgentState }) {
  const end = useRef<HTMLDivElement>(null);
  useEffect(() => {
    end.current?.scrollIntoView({ block: "nearest" });
  }, [agent.transcript.length, agent.interimText]);

  if (!agent.transcript.length) return <p className="debug__empty">No conversation yet.</p>;
  return (
    <div className="transcript">
      {agent.transcript.map((line, i) => (
        <p key={i} className={`transcript__line transcript__line--${line.speaker}`}>
          <span>{line.speaker === "agent" ? "Agent" : "User"}</span>
          {line.text}
        </p>
      ))}
      {agent.interimText && (
        <p className="transcript__line transcript__line--user transcript__line--interim">
          <span>User</span>
          {agent.interimText}…
        </p>
      )}
      <div ref={end} />
    </div>
  );
}

function TextInput({ enabled, onSend }: { enabled: boolean; onSend: (text: string) => void }) {
  const [text, setText] = useState("");
  const submit = (e: FormEvent) => {
    e.preventDefault();
    if (!text.trim()) return;
    onSend(text.trim());
    setText("");
  };
  return (
    <form className="debug__input" onSubmit={submit}>
      <input
        value={text}
        onChange={(e) => setText(e.target.value)}
        placeholder={enabled ? "Type a caller message…" : "Available while listening"}
        disabled={!enabled}
      />
      <button disabled={!enabled || !text.trim()}>Send</button>
    </form>
  );
}

function Classification({ run }: { run: ClassificationRun }) {
  return (
    <div className="classification">
      <p className="classification__meta">
        run {run.run} · {run.model ?? "no model"} · threshold {run.threshold.toFixed(2)}
      </p>
      {run.error && <p className="classification__error">{run.error}</p>}
      {Object.entries(run.labels).map(([name, label]) => {
        const pct = (label.confidence ?? 0) * 100;
        return (
          <div key={name} className="classification__row">
            <div className="classification__head">
              <span>{name}</span>
              <b className={label.final === "uncertain" ? "classification__uncertain" : ""}>
                {label.final}
                {label.final !== label.value && <em> (jev: {label.value})</em>}
              </b>
            </div>
            <div className="classification__bar" title={`confidence ${label.confidence ?? "n/a"}`}>
              <div className="classification__fill" style={{ width: `${pct}%` }} />
              <div className="classification__threshold" style={{ left: `${run.threshold * 100}%` }} />
            </div>
            <span className="classification__conf">
              confidence {label.confidence === null ? "n/a" : label.confidence.toFixed(2)}
            </span>
          </div>
        );
      })}
      {run.uncertain_fields.length > 0 && (
        <p className="classification__meta">below threshold: {run.uncertain_fields.join(", ")}</p>
      )}
    </div>
  );
}

const TOPIC_LABELS: Record<Topic, string> = {
  location: "Location",
  what_happened: "What happened",
  consciousness: "Responsive",
  breathing: "Breathing",
  severe_bleeding: "Severe bleeding",
  patient_count: "Patients",
  entrapment: "Trapped",
  immediate_danger: "Scene danger",
};

const STATUS_TEXT: Record<TopicView["status"], string> = {
  known: "",
  next: "asking now",
  missing: "missing",
  unanswered: "caller unsure",
  not_relevant: "not relevant",
};

function Topics({ topics }: { topics: TopicView[] }) {
  return (
    <ul className="topics">
      {topics.map((t) => (
        <li key={t.topic} className={`topic topic--${t.status}`}>
          <span>{TOPIC_LABELS[t.topic]}</span>
          <em>{t.status === "known" ? String(t.value) : STATUS_TEXT[t.status]}</em>
        </li>
      ))}
    </ul>
  );
}

/** Pretty JSON where lines that changed since the previous update briefly light up. */
function LiveJson({ value, copyable }: { value: unknown; copyable?: boolean }) {
  const text = JSON.stringify(value, null, 2);
  const [snapshot, setSnapshot] = useState({ current: text, previous: text });
  if (snapshot.current !== text) setSnapshot({ current: text, previous: snapshot.current });
  const before = useMemo(() => new Set(snapshot.previous.split("\n")), [snapshot.previous]);
  const [copied, setCopied] = useState(false);

  const copy = async () => {
    await navigator.clipboard.writeText(text);
    setCopied(true);
    setTimeout(() => setCopied(false), 1500);
  };

  return (
    <div className="json">
      {copyable && (
        <button className="json__copy" onClick={copy}>
          {copied ? "Copied" : "Copy"}
        </button>
      )}
      <pre>
        {text.split("\n").map((line, i) => (
          <span key={`${i}:${line}`} className={before.has(line) ? "json__line" : "json__line json__line--changed"}>
            {line}
          </span>
        ))}
      </pre>
    </div>
  );
}
