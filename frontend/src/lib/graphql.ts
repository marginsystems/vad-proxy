import { createClient, type Client } from "graphql-ws";
import { int16ToBase64 } from "./audio";
import type { VoiceEvent } from "./types";

const LISTEN_SUB = `subscription Listen {
  listen(sampleRate: 16000) {
    kind sessionId text turnComplete endPhrase startSecs endSecs sttBackend
  }
}`;

const APPEND_MUTATION = `mutation Append($sessionId: ID!, $audio: String!) {
  appendAudio(sessionId: $sessionId, audioBase64: $audio)
}`;

const END_MUTATION = `mutation End($sessionId: ID!) {
  endUtterance(sessionId: $sessionId)
}`;

const STOP_MUTATION = `mutation Stop($sessionId: ID!) {
  stopSession(sessionId: $sessionId)
}`;

export type VoiceSessionCallbacks = {
  onEvent: (event: VoiceEvent) => void;
  onError: (message: string) => void;
  onStatus: (message: string) => void;
};

export class VoiceGraphqlSession {
  private client: Client | null = null;
  private disposeSub: (() => void) | null = null;
  private sessionId: string | null = null;

  constructor(
    private readonly wsUrl: string,
    private readonly token: string,
    private readonly callbacks: VoiceSessionCallbacks,
  ) {}

  start(): void {
    this.client = createClient({
      url: this.wsUrl,
      connectionParams: this.token ? { token: this.token } : {},
      on: {
        connected: () => this.callbacks.onStatus("WebSocket connected"),
        closed: (event: unknown) => {
          const code =
            event && typeof event === "object" && "code" in event
              ? (event as { code?: number }).code
              : undefined;
          if (code === 4403) {
            this.callbacks.onError("Authentication failed (4403 Forbidden)");
          }
        },
      },
    });

    this.disposeSub = this.client.subscribe(
      { query: LISTEN_SUB },
      {
        next: (msg) => {
          const ev = msg.data?.listen as VoiceEvent | undefined;
          if (!ev) return;
          this.callbacks.onEvent(ev);
          if (ev.kind === "session_started" && ev.sessionId) {
            this.sessionId = ev.sessionId;
            this.callbacks.onStatus(`Session started: ${ev.sessionId}`);
          }
        },
        error: (err) => {
          this.callbacks.onError(
            err instanceof Error ? err.message : String(err),
          );
        },
        complete: () => this.callbacks.onStatus("Subscription complete"),
      },
    );
  }

  async appendAudio(pcm: Int16Array): Promise<void> {
    if (!this.client || !this.sessionId) return;
    const audio = int16ToBase64(pcm);
    try {
      for await (const _ of this.client.iterate({
        query: APPEND_MUTATION,
        variables: { sessionId: this.sessionId, audio },
      })) {
        /* one-shot mutation */
      }
    } catch (err) {
      this.callbacks.onError(
        `appendAudio failed: ${err instanceof Error ? err.message : String(err)}`,
      );
    }
  }

  async endUtterance(): Promise<void> {
    if (!this.client || !this.sessionId) return;
    try {
      for await (const _ of this.client.iterate({
        query: END_MUTATION,
        variables: { sessionId: this.sessionId },
      })) {
        /* one-shot */
      }
    } catch (err) {
      this.callbacks.onError(
        `endUtterance failed: ${err instanceof Error ? err.message : String(err)}`,
      );
    }
  }

  async stop(): Promise<void> {
    if (this.client && this.sessionId) {
      try {
        for await (const _ of this.client.iterate({
          query: STOP_MUTATION,
          variables: { sessionId: this.sessionId },
        })) {
          /* one-shot */
        }
      } catch {
        /* best-effort */
      }
    }
    this.disposeSub?.();
    this.disposeSub = null;
    this.client?.dispose();
    this.client = null;
    this.sessionId = null;
  }
}

export async function fetchHealth(healthUrl: string) {
  const res = await fetch(healthUrl);
  if (!res.ok) throw new Error(`Health check failed: ${res.status}`);
  return res.json();
}
