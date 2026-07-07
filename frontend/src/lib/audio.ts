/** Browser mic capture helpers: downsample to 16 kHz mono Int16 PCM. */

import { downsample } from "./resample";

export { downsample } from "./resample";

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

export type MicCapture = {
  stop: () => Promise<void>;
};

function formatMicError(
  err: unknown,
  stage: "permission" | "worklet",
  audioInputCount = 0,
): string {
  const name = err instanceof DOMException ? err.name : "";
  const message = err instanceof Error ? err.message : String(err);

  if (stage === "permission") {
    if (name === "NotAllowedError" || name === "PermissionDeniedError") {
      return (
        "Microphone permission denied in Firefox. Click the lock icon in the " +
        "address bar and set Microphone to Allow, then reload."
      );
    }
    if (name === "NotFoundError" || name === "DevicesNotFoundError") {
      if (audioInputCount === 0) {
        return (
          "Firefox cannot see any microphone inputs. On macOS, enable Firefox " +
          "under System Settings → Privacy & Security → Microphone (site Allow " +
          "is not enough). Private/incognito windows work once OS access is granted. " +
          "Then quit and reopen Firefox."
        );
      }
      return (
        "Firefox blocked the microphone at the OS level (common on macOS). " +
        "You may have clicked Allow in the browser, but also enable Firefox in " +
        "System Settings → Privacy & Security → Microphone, quit Firefox, and retry. " +
        `(${audioInputCount} input device${audioInputCount === 1 ? "" : "s"} visible.)`
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

async function listAudioInputs(): Promise<MediaDeviceInfo[]> {
  try {
    const devices = await navigator.mediaDevices.enumerateDevices();
    return devices.filter((d) => d.kind === "audioinput");
  } catch {
    return [];
  }
}

/** Request mic access with relaxed constraints (Firefox rejects channelCount: 1). */
async function getAudioStream(): Promise<MediaStream> {
  if (!navigator.mediaDevices?.getUserMedia) {
    throw new Error(
      "Microphone API unavailable. Open Voice Lab over http://localhost (not file://).",
    );
  }

  let lastError: unknown;

  const attempts: MediaStreamConstraints[] = [
    { audio: true, video: false },
    { audio: { echoCancellation: true, noiseSuppression: true }, video: false },
  ];

  for (const constraints of attempts) {
    try {
      return await navigator.mediaDevices.getUserMedia(constraints);
    } catch (err) {
      lastError = err;
    }
  }

  const inputs = await listAudioInputs();
  for (const device of inputs) {
    if (!device.deviceId) continue;
    try {
      return await navigator.mediaDevices.getUserMedia({
        audio: { deviceId: { ideal: device.deviceId } },
        video: false,
      });
    } catch (err) {
      lastError = err;
    }
  }

  throw new Error(formatMicError(lastError, "permission", inputs.length));
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
    const rawChunks: Float32Array[] = [];
    let stopping = false;
    let chunkTimer: ReturnType<typeof setTimeout> | null = null;

    worklet.port.onmessage = (event: MessageEvent<Float32Array>) => {
      if (stopping) return;
      const samples = event.data;
      if (!samples?.length) return;
      rawChunks.push(samples);
    };

    // Keep the worklet in the render graph (required for processing).
    const silent = audioContext.createGain();
    silent.gain.value = 0;
    source.connect(worklet);
    worklet.connect(silent);
    silent.connect(audioContext.destination);

    const flush = () => {
      if (stopping || rawChunks.length === 0) return;
      const total = rawChunks.reduce((n, c) => n + c.length, 0);
      const merged = new Float32Array(total);
      let off = 0;
      for (const c of rawChunks) {
        merged.set(c, off);
        off += c.length;
      }
      rawChunks.length = 0;
      if (!stopping) onChunk(floatToInt16(downsample(merged, inputRate, 16000)));
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
