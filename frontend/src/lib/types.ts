export type VoiceEventKind = "session_started" | "transcript";

export type VoiceEvent = {
  kind: VoiceEventKind;
  sessionId?: string | null;
  text?: string | null;
  turnComplete?: boolean | null;
  endPhrase?: boolean | null;
  startSecs?: number | null;
  endSecs?: number | null;
  sttBackend?: string | null;
  interim?: boolean | null;
};

export type HealthResponse = {
  status: string;
  sample_rate: number;
  stt_backend: string;
  llm_enabled: boolean;
  output: string;
  allowed_origins: string[];
};

export type SessionStatus = "idle" | "connecting" | "listening" | "error";

export type LogEntry = {
  id: number;
  ts: number;
  label: string;
  payload: unknown;
};

export const DEFAULT_WS_URL = "ws://127.0.0.1:8080/graphql";
export const PROD_WS_URL = "wss://voice.biosystems.dev/graphql";

export function healthUrlFromWs(wsUrl: string): string {
  try {
    const u = new URL(wsUrl);
    if (u.protocol !== "ws:" && u.protocol !== "wss:") {
      console.warn(`healthUrlFromWs: unexpected protocol "${u.protocol}"`);
    }
    u.protocol = u.protocol === "wss:" ? "https:" : "http:";
    u.pathname = "/health";
    u.search = "";
    return u.toString();
  } catch (e) {
    console.warn(`healthUrlFromWs: invalid wsUrl "${wsUrl}"`, e);
    return "http://127.0.0.1:8080/health";
  }
}
