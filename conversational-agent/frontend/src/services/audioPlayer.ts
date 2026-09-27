import { rmsLevel } from "../hooks/useMicrophone";

/** Plays the agent's WAV replies and exposes the output loudness for the orb. */
export class AudioPlayer {
  private ctx: AudioContext | null = null;
  private analyser: AnalyserNode | null = null;
  private current: AudioBufferSourceNode | null = null;
  private samples = new Float32Array(1024);

  /** Must be called from a user gesture (e.g. the Start button) so audio may play. */
  unlock() {
    if (!this.ctx) {
      this.ctx = new AudioContext();
      this.analyser = this.ctx.createAnalyser();
      this.analyser.fftSize = 1024;
      this.analyser.connect(this.ctx.destination);
    }
    void this.ctx.resume();
  }

  /** Resolves when playback has finished (or failed). */
  async playWav(base64: string): Promise<void> {
    this.unlock();
    const ctx = this.ctx!;
    const bytes = Uint8Array.from(atob(base64), (c) => c.charCodeAt(0));
    const buffer = await ctx.decodeAudioData(bytes.buffer);
    this.stop();
    const source = ctx.createBufferSource();
    source.buffer = buffer;
    source.connect(this.analyser!);
    this.current = source;
    await new Promise<void>((resolve) => {
      source.onended = () => resolve();
      source.start();
    });
    if (this.current === source) this.current = null;
  }

  stop() {
    try {
      this.current?.stop();
    } catch {
      /* already stopped */
    }
    this.current = null;
  }

  getLevel(): number {
    return this.current ? rmsLevel(this.analyser, this.samples) : 0;
  }

  close() {
    this.stop();
    void this.ctx?.close();
    this.ctx = null;
    this.analyser = null;
  }
}
