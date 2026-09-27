// AudioWorklet: converts microphone samples (float32) into 16-bit PCM chunks
// of ~80 ms, the chunk size Deepgram recommends for Flux.
// `sampleRate` is a global inside the AudioWorklet scope.

class PcmProcessor extends AudioWorkletProcessor {
  constructor(options) {
    super();
    const chunkMs = options.processorOptions?.chunkMs ?? 80;
    this.chunkSize = Math.round((sampleRate * chunkMs) / 1000);
    this.buffer = new Int16Array(this.chunkSize);
    this.offset = 0;
  }

  process(inputs) {
    const channel = inputs[0]?.[0];
    if (channel) {
      for (let i = 0; i < channel.length; i++) {
        const s = Math.max(-1, Math.min(1, channel[i]));
        this.buffer[this.offset++] = s < 0 ? s * 0x8000 : s * 0x7fff;
        if (this.offset === this.chunkSize) {
          this.port.postMessage(this.buffer.buffer, [this.buffer.buffer]);
          this.buffer = new Int16Array(this.chunkSize);
          this.offset = 0;
        }
      }
    }
    return true;
  }
}

registerProcessor("pcm-processor", PcmProcessor);
