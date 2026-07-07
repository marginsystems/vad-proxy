/** Anti-aliased downsampling for mic capture (Float32 → lower sample rate). */

export type BiquadCoeffs = {
  b0: number;
  b1: number;
  b2: number;
  a1: number;
  a2: number;
};

/** 2nd-order Butterworth low-pass coefficients (normalized). */
export function lowpassBiquadCoeffs(
  sampleRate: number,
  cutoffHz: number,
  q = Math.SQRT1_2,
): BiquadCoeffs {
  const w0 = (2 * Math.PI * cutoffHz) / sampleRate;
  const cos = Math.cos(w0);
  const sin = Math.sin(w0);
  const alpha = sin / (2 * q);
  const b0 = (1 - cos) / 2;
  const b1 = 1 - cos;
  const b2 = (1 - cos) / 2;
  const a0 = 1 + alpha;
  const a1 = -2 * cos;
  const a2 = 1 - alpha;
  return {
    b0: b0 / a0,
    b1: b1 / a0,
    b2: b2 / a0,
    a1: a1 / a0,
    a2: a2 / a0,
  };
}

export function applyBiquad(input: Float32Array, coeffs: BiquadCoeffs): Float32Array {
  const out = new Float32Array(input.length);
  let z1 = 0;
  let z2 = 0;
  const { b0, b1, b2, a1, a2 } = coeffs;
  for (let i = 0; i < input.length; i++) {
    const x = input[i];
    const y = b0 * x + z1;
    z1 = b1 * x - a1 * y + z2;
    z2 = b2 * x - a2 * y;
    out[i] = y;
  }
  return out;
}

const _coeffCache = new Map<string, BiquadCoeffs>();

/** Low-pass then decimate/resample. Cutoff is set just below the output Nyquist limit. */
export function lowpassForDownsample(
  buffer: Float32Array,
  fromRate: number,
  toRate: number,
  stages = 2,
): Float32Array {
  const nyquist = toRate / 2;
  const cutoff = Math.min(fromRate / 2, nyquist) * 0.95;
  let filtered = buffer;
  const key = `${fromRate}_${cutoff}`;
  let coeffs = _coeffCache.get(key);
  if (!coeffs) {
    coeffs = lowpassBiquadCoeffs(fromRate, cutoff);
    _coeffCache.set(key, coeffs);
  }
  for (let s = 0; s < stages; s++) {
    filtered = applyBiquad(filtered, coeffs);
  }
  return filtered;
}

export function downsample(
  buffer: Float32Array,
  fromRate: number,
  toRate: number,
): Float32Array {
  if (fromRate === toRate) return buffer;
  const filtered = lowpassForDownsample(buffer, fromRate, toRate);
  const ratio = fromRate / toRate;
  const outLen = Math.floor(filtered.length / ratio);
  const out = new Float32Array(outLen);
  for (let i = 0; i < outLen; i++) {
    const idx = i * ratio;
    const i0 = Math.floor(idx);
    const i1 = Math.min(i0 + 1, filtered.length - 1);
    const frac = idx - i0;
    out[i] = filtered[i0] * (1 - frac) + filtered[i1] * frac;
  }
  return out;
}

/** Linear interpolation only (legacy / test comparison). */
export function downsampleLinear(
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

export function rms(buffer: Float32Array): number {
  if (buffer.length === 0) return 0;
  let sum = 0;
  for (let i = 0; i < buffer.length; i++) {
    sum += buffer[i] * buffer[i];
  }
  return Math.sqrt(sum / buffer.length);
}

export function sineWave(
  freqHz: number,
  sampleRate: number,
  durationSecs: number,
  amplitude = 0.5,
): Float32Array {
  const len = Math.floor(sampleRate * durationSecs);
  const out = new Float32Array(len);
  for (let i = 0; i < len; i++) {
    out[i] = amplitude * Math.sin((2 * Math.PI * freqHz * i) / sampleRate);
  }
  return out;
}
