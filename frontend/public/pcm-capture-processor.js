/**
 * AudioWorklet processor: forwards mic samples to the main thread.
 * Loaded from /pcm-capture-processor.js (Vite public/).
 */
class PcmCaptureProcessor extends AudioWorkletProcessor {
  process(inputs) {
    const channel = inputs[0]?.[0];
    if (channel?.length) {
      // Copy — the engine reuses the underlying buffer.
      this.port.postMessage(channel.slice(0));
    }
    return true;
  }
}

registerProcessor("pcm-capture-processor", PcmCaptureProcessor);
