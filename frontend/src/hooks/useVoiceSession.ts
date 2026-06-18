import { useCallback, useEffect, useRef, useState } from "react";
import { startMicCapture } from "../lib/audio";
import { fetchHealth, VoiceGraphqlSession } from "../lib/graphql";
import type {
  HealthResponse,
  LogEntry,
  SessionStatus,
  VoiceEvent,
} from "../lib/types";
import { healthUrlFromWs } from "../lib/types";

let logId = 0;

export function useVoiceSession(wsUrl: string, token: string) {
  const [status, setStatus] = useState<SessionStatus>("idle");
  const [error, setError] = useState<string | null>(null);
  const [health, setHealth] = useState<HealthResponse | null>(null);
  const [healthError, setHealthError] = useState<string | null>(null);
  const [events, setEvents] = useState<VoiceEvent[]>([]);
  const [logs, setLogs] = useState<LogEntry[]>([]);

  const sessionRef = useRef<VoiceGraphqlSession | null>(null);
  const micRef = useRef<Awaited<ReturnType<typeof startMicCapture>> | null>(
    null,
  );

  const pushLog = useCallback((label: string, payload: unknown) => {
    setLogs((prev) => [
      { id: ++logId, ts: Date.now(), label, payload },
      ...prev.slice(0, 199),
    ]);
  }, []);

  const refreshHealth = useCallback(async () => {
    try {
      const data = (await fetchHealth(healthUrlFromWs(wsUrl))) as HealthResponse;
      setHealth(data);
      setHealthError(null);
    } catch (e) {
      setHealth(null);
      setHealthError((e as Error).message);
    }
  }, [wsUrl]);

  useEffect(() => {
    void refreshHealth();
  }, [refreshHealth]);

  const start = useCallback(async () => {
    setError(null);
    setStatus("connecting");
    setEvents([]);
    setLogs([]);

    const session = new VoiceGraphqlSession(wsUrl, token, {
      onEvent: (ev) => {
        pushLog(ev.kind, ev);
        setEvents((prev) => [...prev, ev]);
      },
      onError: (msg) => {
        setError(msg);
        setStatus("error");
      },
      onStatus: (msg) => pushLog("status", msg),
    });

    sessionRef.current = session;
    session.start();

    try {
      const mic = await startMicCapture((pcm) => {
        void session.appendAudio(pcm);
      });
      micRef.current = mic;
      setStatus("listening");
      pushLog("status", "Microphone started");
    } catch (e) {
      setError(`Mic access failed: ${(e as Error).message}`);
      setStatus("error");
      await session.stop();
      sessionRef.current = null;
    }
  }, [wsUrl, token, pushLog]);

  const endUtterance = useCallback(async () => {
    await sessionRef.current?.endUtterance();
  }, []);

  const stop = useCallback(async () => {
    await micRef.current?.stop();
    micRef.current = null;
    await sessionRef.current?.stop();
    sessionRef.current = null;
    setStatus("idle");
    pushLog("status", "Session stopped");
  }, [pushLog]);

  useEffect(() => {
    return () => {
      void micRef.current?.stop();
      void sessionRef.current?.stop();
    };
  }, []);

  const transcripts = events.filter((e) => e.kind === "transcript");
  const latest = transcripts.at(-1) ?? null;

  return {
    status,
    error,
    health,
    healthError,
    events,
    transcripts,
    latest,
    logs,
    refreshHealth,
    start,
    stop,
    endUtterance,
  };
}
