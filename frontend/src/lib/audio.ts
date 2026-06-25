/** Browser mic capture helpers: downsample to 16 kHz mono Int16 PCM. */

/** Inline worklet — Blob URL avoids Firefox path/MIME issues with external modules. */
const PCM_WORKLET_CODE = `
class PcmCaptureProcessor extends AudioWorkletProcessor {
  process(inputs) {
    const channel = inputs[0]?.[0];
    if (channel?.length) {
      this.port.postMessage(channel.slice(0));
    }
    return true;
  }
}
registerProcessor("pcm-capture-processor", PcmCaptureProcessor);
`;

export function floatToInt16(float32: Float32Array): Int16Array {
  const out = new Int16Array(float32.length);
  for (let i = 0; i < float32.length; i++) {
    const s = Math.max(-1, Math.min(1, float32[i]));
    out[i] = s < 0 ? s * 0x8000 : s * 0x7fff;
  }
  return out;
}

export function int16ToBase64(int16: Int16Array): string {
  const bytes = new Uint8Array(int16.buffer, int16.byteOffset, int16.byteLength);
  let binary = "";
  for (let i = 0; i < bytes.length; i += 8192) {
    binary += String.fromCharCode.apply(null, Array.from(bytes.subarray(i, i + 8192)));
  }
  return btoa(binary);
}

export function downsample(
  buffer: Float32Array,
  fromRate: number,
  toRate: number,
): Float32Array {
  if (fromRate === toRate) return buffer;
  const ratio = fromRate / toRate;
  const outLen = Math.floor(buffer.length / ratio);
  const out = new Float32Array(outLen);
  for (let i = 0; i < outLen; i++) {
    const idx = i * ratio;
    const i0 = Math.floor(idx);
    const i1 = Math.min(i0 + 1, buffer.length - 1);
    const frac = idx - i0;
    out[i] = buffer[i0] * (1 - frac) + buffer[i1] * frac;
  }
  return out;
}

export type MicCapture = {
  stop: () => Promise<void>;
};

function formatMicError(err: unknown, stage: "permission" | "worklet"): string {
  const name = err instanceof DOMException ? err.name : "";
  const message = err instanceof Error ? err.message : String(err);

  if (stage === "permission") {
    if (name === "NotAllowedError" || name === "PermissionDeniedError") {
      return "Microphone permission denied. Allow mic access for this site in Firefox settings.";
    }
    if (name === "NotFoundError" || name === "DevicesNotFoundError") {
      return (
        "No microphone found or Firefox cannot access it. " +
        "Check that a mic is connected, then allow microphone access for Firefox " +
        "in macOS System Settings → Privacy & Security → Microphone."
      );
    }
    if (name === "NotReadableError" || name === "TrackStartError") {
      return "Microphone is in use by another app. Close other apps using the mic and retry.";
    }
  }

  if (stage === "worklet") {
    return `Audio capture setup failed: ${message}`;
  }

  return message;
}

/** Request mic access with relaxed constraints (Firefox rejects channelCount: 1). */
async function getAudioStream(): Promise<MediaStream> {
  if (!navigator.mediaDevices?.getUserMedia) {
    throw new Error(
      "Microphone API unavailable. Open Voice Lab over http://localhost (not file://).",
    );
  }

  const attempts: MediaStreamConstraints[] = [
    { audio: { echoCancellation: true, noiseSuppression: true }, video: false },
    { audio: true, video: false },
  ];

  let lastError: unknown;
  for (const constraints of attempts) {
    try {
      return await navigator.mediaDevices.getUserMedia(constraints);
    } catch (err) {
      lastError = err;
    }
  }

  throw new Error(formatMicError(lastError, "permission"));
}

async function loadPcmWorklet(audioContext: AudioContext): Promise<void> {
  const blob = new Blob([PCM_WORKLET_CODE], { type: "application/javascript" });
  const workletUrl = URL.createObjectURL(blob);
  try {
    await audioContext.audioWorklet.addModule(workletUrl);
  } catch (err) {
    throw new Error(formatMicError(err, "worklet"));
  } finally {
    URL.revokeObjectURL(workletUrl);
  }
}

/** Capture mic audio and invoke onChunk with 16 kHz mono Int16 PCM on each flush. */
export async function startMicCapture(
  onChunk: (pcm: Int16Array) => void,
  flushMs = 200,
): Promise<MicCapture> {
  const stream = await getAudioStream();

  const audioContext = new AudioContext();
  try {
    await audioContext.resume();
    await loadPcmWorklet(audioContext);

    const source = audioContext.createMediaStreamSource(stream);
    const worklet = new AudioWorkletNode(audioContext, "pcm-capture-processor");
    const inputRate = audioContext.sampleRate;
    const pcmChunks: Int16Array[] = [];
    let stopping = false;
    let chunkTimer: ReturnType<typeof setTimeout> | null = null;

    worklet.port.onmessage = (event: MessageEvent<Float32Array>) => {
      if (stopping) return;
      const samples = event.data;
      if (!samples?.length) return;
      pcmChunks.push(floatToInt16(downsample(samples, inputRate, 16000)));
    };

    // Keep the worklet in the render graph (required for processing).
    const silent = audioContext.createGain();
    silent.gain.value = 0;
    source.connect(worklet);
    worklet.connect(silent);
    silent.connect(audioContext.destination);

    const flush = () => {
      if (stopping || pcmChunks.length === 0) return;
      const total = pcmChunks.reduce((n, c) => n + c.length, 0);
      const merged = new Int16Array(total);
      let off = 0;
      for (const c of pcmChunks) {
        merged.set(c, off);
        off += c.length;
      }
      pcmChunks.length = 0;
      if (!stopping) onChunk(merged);
    };

    const scheduleFlush = () => {
      if (stopping) return;
      flush();
      chunkTimer = setTimeout(scheduleFlush, flushMs);
    };

    chunkTimer = setTimeout(scheduleFlush, flushMs);

    return {
      stop: async () => {
        if (chunkTimer !== null) clearTimeout(chunkTimer);
        flush();
        stopping = true;
        worklet.port.onmessage = null;
        worklet.disconnect();
        source.disconnect();
        silent.disconnect();
        stream.getTracks().forEach((t) => t.stop());
        await audioContext.close();
      },
    };
  } catch (err) {
    stream.getTracks().forEach((t) => t.stop());
    await audioContext.close();
    throw err;
  }
}
