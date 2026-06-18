/** Browser mic capture helpers: downsample to 16 kHz mono Int16 PCM. */

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

/** Capture mic audio and invoke onChunk with 16 kHz mono Int16 PCM on each flush. */
export async function startMicCapture(
  onChunk: (pcm: Int16Array) => void,
  flushMs = 200,
): Promise<MicCapture> {
  const stream = await navigator.mediaDevices.getUserMedia({
    audio: { channelCount: 1, echoCancellation: true, noiseSuppression: true },
    video: false,
  });

  const audioContext = new AudioContext();
  await audioContext.resume();
  const source = audioContext.createMediaStreamSource(stream);
  const processor = audioContext.createScriptProcessor(4096, 1, 1);
  const inputRate = audioContext.sampleRate;
  const pcmChunks: Int16Array[] = [];
  let stopping = false;
  let chunkTimer: ReturnType<typeof setTimeout> | null = null;

  processor.onaudioprocess = (e) => {
    if (stopping) return;
    const input = e.inputBuffer.getChannelData(0);
    const copy = new Float32Array(input.length);
    copy.set(input);
    pcmChunks.push(floatToInt16(downsample(copy, inputRate, 16000)));
  };

  source.connect(processor);

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
      processor.disconnect();
      source.disconnect();
      stream.getTracks().forEach((t) => t.stop());
      await audioContext.close();
    },
  };
}
