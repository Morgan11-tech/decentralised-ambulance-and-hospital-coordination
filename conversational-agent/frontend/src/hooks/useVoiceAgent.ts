import { useCallback, useEffect, useReducer, useRef, useState } from "react";
import { createSession, voiceSocketUrl } from "../services/api";
import { AudioPlayer } from "../services/audioPlayer";
import type {
  AgentErrorInfo,
  AgentStatus,
  ClassificationRun,
  CompletedIncident,
  Incident,
  ServerEvent,
  TopicView,
  TranscriptLine,
  WorkingState,
} from "../types/incident";
import { MicrophoneDeniedError, useMicrophone } from "./useMicrophone";

export type Mode = "voice" | "text";

export interface VoiceAgentState {
  status: AgentStatus;
  mode: Mode | null;
  agentText: string;
  interimText: string;
  transcript: TranscriptLine[];
  /** Live working state, information checklist and draft Incident JSON (debug panel). */
  workingState: WorkingState | null;
  topics: TopicView[];
  liveIncident: Incident | null;
  classifications: ClassificationRun[];
  completed: CompletedIncident | null;
  errorLog: AgentErrorInfo[];
  /** The error shown on the main screen (Jev/TTS problems only go to the debug panel). */
  blockingError: AgentErrorInfo | null;
}

type Action =
  | { type: "reset"; mode: Mode | null }
  | { type: "status"; status: AgentStatus }
  | { type: "event"; event: ServerEvent }
  | { type: "localError"; source: string; message: string };

const initialState: VoiceAgentState = {
  status: "idle",
  mode: null,
  agentText: "",
  interimText: "",
  transcript: [],
  workingState: null,
  topics: [],
  liveIncident: null,
  classifications: [],
  completed: null,
  errorLog: [],
  blockingError: null,
};

const NON_BLOCKING_SOURCES = new Set(["jev", "tts"]);

function reducer(state: VoiceAgentState, action: Action): VoiceAgentState {
  switch (action.type) {
    case "reset":
      return { ...initialState, mode: action.mode };
    case "status":
      return { ...state, status: action.status };
    case "localError": {
      const error = { source: action.source, message: action.message, recoverable: false };
      return { ...state, status: "error", blockingError: error, errorLog: [...state.errorLog, error] };
    }
    case "event":
      return applyEvent(state, action.event);
  }
}

function applyEvent(state: VoiceAgentState, event: ServerEvent): VoiceAgentState {
  switch (event.type) {
    case "state":
      return {
        ...state,
        status: event.state,
        interimText: event.state === "listening" ? state.interimText : "",
        blockingError: event.state === "error" ? state.blockingError : null,
      };
    case "transcript":
      return event.final
        ? { ...state, interimText: "", transcript: [...state.transcript, { speaker: "user", text: event.text }] }
        : { ...state, interimText: event.text };
    case "agent_response":
      return {
        ...state,
        agentText: event.text,
        transcript: [...state.transcript, { speaker: "agent", text: event.text }],
      };
    case "incident_state":
      return { ...state, workingState: event.state, topics: event.topics, liveIncident: event.incident };
    case "classification":
      return { ...state, classifications: [...state.classifications, event.data] };
    case "incident_complete":
      return {
        ...state,
        completed: { incident: event.incident, persisted: event.persisted, persistence_error: event.persistence_error },
      };
    case "error": {
      const error = { source: event.source, message: event.message, recoverable: event.recoverable };
      return {
        ...state,
        errorLog: [...state.errorLog, error],
        blockingError: NON_BLOCKING_SOURCES.has(event.source) ? state.blockingError : error,
      };
    }
    default:
      return state;
  }
}

export function useVoiceAgent() {
  const [state, dispatch] = useReducer(reducer, initialState);
  const [level, setLevel] = useState(0);
  const mic = useMicrophone();
  const [player] = useState(() => new AudioPlayer());
  const wsRef = useRef<WebSocket | null>(null);
  const statusRef = useRef<AgentStatus>("idle");
  useEffect(() => {
    statusRef.current = state.status;
  }, [state.status]);

  const send = useCallback((message: object) => {
    const ws = wsRef.current;
    if (ws?.readyState === WebSocket.OPEN) ws.send(JSON.stringify(message));
  }, []);

  /** Stop the microphone, playback and connection (without touching UI state). */
  const teardown = useCallback(() => {
    mic.stop();
    player.stop();
    const ws = wsRef.current;
    wsRef.current = null; // mark as intentional before closing
    ws?.close();
  }, [mic, player]);

  const handleEvent = useCallback(
    (event: ServerEvent) => {
      dispatch({ type: "event", event });
      if (event.type === "audio") {
        player
          .playWav(event.data)
          .catch(() => undefined)
          .finally(() => send({ type: "playback_done" }));
      } else if (event.type === "state" && event.state === "completed") {
        teardown();
      } else if (event.type === "session_ended") {
        teardown();
        dispatch({ type: "status", status: event.incident_saved ? "completed" : "idle" });
      }
    },
    [send, teardown, player],
  );

  const start = useCallback(
    async (mode: Mode) => {
      teardown();
      dispatch({ type: "reset", mode });
      dispatch({ type: "status", status: "thinking" });
      player.unlock(); // must happen inside the click handler, before any await

      try {
        let sampleRate = 16000;
        if (mode === "voice") {
          sampleRate = await mic.start((chunk) => {
            if (wsRef.current?.readyState === WebSocket.OPEN) wsRef.current.send(chunk);
          });
        }
        const sessionId = await createSession();
        const ws = new WebSocket(voiceSocketUrl(sessionId));
        ws.binaryType = "arraybuffer";
        wsRef.current = ws;
        ws.onopen = () => ws.send(JSON.stringify({ type: "start", mode, sample_rate: sampleRate }));
        ws.onmessage = (message) => handleEvent(JSON.parse(message.data as string) as ServerEvent);
        ws.onclose = () => {
          if (wsRef.current === ws) {
            teardown();
            dispatch({ type: "localError", source: "backend", message: "Connection to the backend was lost." });
          }
        };
      } catch (err) {
        teardown();
        const source = err instanceof MicrophoneDeniedError ? "microphone" : "backend";
        dispatch({ type: "localError", source, message: (err as Error).message });
      }
    },
    [mic, teardown, handleEvent, player],
  );

  const end = useCallback(() => {
    if (wsRef.current?.readyState === WebSocket.OPEN) {
      send({ type: "end" }); // the backend saves what it has, then replies "session_ended"
      player.stop();
      mic.stop();
    } else {
      teardown();
      dispatch({ type: "reset", mode: null });
    }
  }, [send, teardown, mic, player]);

  const retry = useCallback(() => send({ type: "retry" }), [send]);

  const sendText = useCallback((text: string) => send({ type: "user_text", text }), [send]);

  const reset = useCallback(() => {
    teardown();
    dispatch({ type: "reset", mode: null });
  }, [teardown]);

  // Feed the orb with microphone loudness while listening, playback loudness while speaking.
  useEffect(() => {
    let raf = 0;
    let smoothed = 0;
    let lastSent = 0;
    const tick = (t: number) => {
      raf = requestAnimationFrame(tick);
      const status = statusRef.current;
      const raw = status === "listening" ? mic.getLevel() : status === "speaking" ? player.getLevel() : 0;
      smoothed += (raw - smoothed) * 0.25;
      if (t - lastSent > 50) {
        lastSent = t;
        setLevel(Math.round(smoothed * 100) / 100);
      }
    };
    raf = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(raf);
  }, [mic, player]);

  useEffect(
    () => () => {
      teardown();
      player.close();
    },
    [teardown, player],
  );

  return { ...state, level, start, end, retry, sendText, reset };
}
