import { describe, expect, it } from "vitest";
import {
  downsample,
  downsampleLinear,
  rms,
  sineWave,
} from "./resample";

describe("downsample", () => {
  it("passes through when rates match", () => {
    const input = sineWave(440, 16000, 0.1);
    const out = downsample(input, 16000, 16000);
    expect(out).toBe(input);
  });

  it("attenuates supra-Nyquist content vs linear-only (48kHz → 16kHz)", () => {
    const fromRate = 48000;
    const toRate = 16000;
    // 12 kHz is above 8 kHz output Nyquist — aliases without a low-pass.
    const input = sineWave(12000, fromRate, 0.25, 0.8);
    const filtered = downsample(input, fromRate, toRate);
    const naive = downsampleLinear(input, fromRate, toRate);
    expect(rms(filtered)).toBeLessThan(rms(naive) * 0.35);
  });

  it("preserves in-band speech-ish tones (1 kHz)", () => {
    const fromRate = 48000;
    const toRate = 16000;
    const input = sineWave(1000, fromRate, 0.25, 0.8);
    const filtered = downsample(input, fromRate, toRate);
    const naive = downsampleLinear(input, fromRate, toRate);
    expect(rms(filtered)).toBeGreaterThan(rms(naive) * 0.85);
  });
});
