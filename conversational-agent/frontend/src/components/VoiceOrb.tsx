import type { CSSProperties } from "react";
import type { AgentStatus } from "../types/incident";
import Orb from "./Orb/Orb";

/**
 * Maps agent state onto the Orb's real props (hue, hoverIntensity,
 * forceHoverState, rotateOnHover). `level` is live audio loudness (0..1):
 * the caller's voice while listening, the agent's voice while speaking.
 */
const ORB_BY_STATUS: Record<AgentStatus, { hue: number; intensity: number; active: boolean; label: string }> = {
  idle: { hue: 0, intensity: 0.2, active: false, label: "Ready" },
  listening: { hue: 60, intensity: 0.12, active: true, label: "Listening" },
  thinking: { hue: -100, intensity: 0.35, active: true, label: "Thinking" },
  speaking: { hue: 0, intensity: 0.3, active: true, label: "Speaking" },
  completed: { hue: 125, intensity: 0.1, active: false, label: "Incident recorded" },
  error: { hue: -80, intensity: 0.05, active: false, label: "Interrupted" },
};

const LEVEL_GAIN: Partial<Record<AgentStatus, number>> = { listening: 1.6, speaking: 1.4 };

export default function VoiceOrb({ status, level }: { status: AgentStatus; level: number }) {
  const config = ORB_BY_STATUS[status];
  const gain = LEVEL_GAIN[status] ?? 0;
  const style = { "--level": level * gain } as CSSProperties;

  return (
    <div className="voice-orb" data-status={status} style={style}>
      <div className="voice-orb__canvas">
        <Orb
          hue={config.hue}
          hoverIntensity={config.intensity + level * gain}
          forceHoverState={config.active}
          rotateOnHover
          backgroundColor="#07080b"
        />
      </div>
      <div className="voice-orb__label" aria-live="polite">
        <span className="voice-orb__dot" />
        {config.label}
      </div>
    </div>
  );
}
