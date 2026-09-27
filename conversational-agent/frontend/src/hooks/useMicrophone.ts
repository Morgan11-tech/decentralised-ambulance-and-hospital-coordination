import { useCallback, useMemo, useRef } from "react";

export class MicrophoneDeniedError extends Error {
  constructor() {
    super("Microphone access is required.");
  }
}

/**
 * Captures the microphone as 16-bit mono PCM chunks (~80 ms each).
 * Tries a 16 kHz AudioContext (Deepgram's recommended rate) and falls back to
 * the device's native rate; the actual rate is returned so the backend can
 * tell Deepgram.
 */
export function useMicrophone() {
  const ctxRef = useRef<AudioContext | null>(null);
  const streamRef = useRef<MediaStream | null>(null);
  const analyserRef = useRef<AnalyserNode | null>(null);
  const samples = useRef(new Float32Array(1024));

  const stop = useCallback(() => {
    streamRef.current?.getTracks().forEach((t) => t.stop());
    void ctxRef.current?.close();
    streamRef.current = null;
    ctxRef.current = null;
    analyserRef.current = null;
  }, []);

  const start = useCallback(
    async (onChunk: (pcm: ArrayBuffer) => void): Promise<number> => {
      let stream: MediaStream;
      try {
        stream = await navigator.mediaDevices.getUserMedia({
          audio: { channelCount: 1, echoCancellation: true, noiseSuppression: true, autoGainControl: true },
        });
      } catch {
        throw new MicrophoneDeniedError();
      }
      streamRef.current = stream;

      let ctx: AudioContext;
      let source: MediaStreamAudioSourceNode;
      try {
        ctx = new AudioContext({ sampleRate: 16000 });
        source = ctx.createMediaStreamSource(stream);
      } catch {
        // Some browsers cannot resample a live stream; use the native rate instead.
        ctx = new AudioContext();
        source = ctx.createMediaStreamSource(stream);
      }
      ctxRef.current = ctx;

      await ctx.audioWorklet.addModule("/pcm-processor.js");
      const worklet = new AudioWorkletNode(ctx, "pcm-processor", { processorOptions: { chunkMs: 80 } });
      worklet.port.onmessage = (event: MessageEvent<ArrayBuffer>) => onChunk(event.data);

      const analyser = ctx.createAnalyser();
      analyser.fftSize = 1024;
      analyserRef.current = analyser;

      const mute = ctx.createGain();
      mute.gain.value = 0; // keeps the worklet running without playing the mic back
      source.connect(analyser);
      source.connect(worklet).connect(mute).connect(ctx.destination);

      return ctx.sampleRate;
    },
    [],
  );

  /** Current input loudness, roughly 0..1 (for the orb animation). */
  const getLevel = useCallback(() => rmsLevel(analyserRef.current, samples.current), []);

  return useMemo(() => ({ start, stop, getLevel }), [start, stop, getLevel]);
}

export function rmsLevel(analyser: AnalyserNode | null, buffer: Float32Array): number {
  if (!analyser) return 0;
  analyser.getFloatTimeDomainData(buffer as Float32Array<ArrayBuffer>);
  let sum = 0;
  for (let i = 0; i < buffer.length; i++) sum += buffer[i] * buffer[i];
  return Math.min(1, Math.sqrt(sum / buffer.length) * 4);
}
