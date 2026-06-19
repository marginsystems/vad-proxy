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

export function useVoiceSession(wsUrl: string) {
  const [status, setStatus] = useState<SessionStatus>("idle");
  const [error, setError] = useState<string | null>(null);
  const [health, setHealth] = useState<HealthResponse | null>(null);
  const [healthError, setHealthError] = useState<string | null>(null);
  const [events, setEvents] = useState<VoiceEvent[]>([]);
  const [liveInterim, setLiveInterim] = useState("");
  const [logs, setLogs] = useState<LogEntry[]>([]);

  const logIdRef = useRef(0);
  const sessionRef = useRef<VoiceGraphqlSession | null>(null);
  const micRef = useRef<Awaited<ReturnType<typeof startMicCapture>> | null>(
    null,
  );

  const pushLog = useCallback((label: string, payload: unknown) => {
    setLogs((prev) => [
      { id: ++logIdRef.current, ts: Date.now(), label, payload },
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
      setHealthError(e instanceof Error ? e.message : String(e));
    }
  }, [wsUrl]);

  useEffect(() => {
    void refreshHealth();
  }, [refreshHealth]);

  const start = useCallback(async () => {
    setError(null);
    setStatus("connecting");
    setEvents([]);
    setLiveInterim("");
    setLogs([]);

    const session = new VoiceGraphqlSession(wsUrl, {
      onEvent: (ev) => {
        pushLog(ev.kind, ev);
        if (ev.kind === "transcript" && ev.interim) {
          setLiveInterim(ev.text ?? "");
          return;
        }
        if (ev.kind === "transcript") {
          setLiveInterim("");
        }
        setEvents((prev) => [...prev, ev]);
      },
      onError: (msg) => {
        setLiveInterim("");
        setError(msg);
        setStatus("error");
      },
      onStatus: (msg) => pushLog("status", msg),
    });

    sessionRef.current = session;
    session.start();

    try {
      await session.waitForSession();
      const mic = await startMicCapture((pcm) => {
        void session.appendAudio(pcm);
      });
      micRef.current = mic;
      setStatus("listening");
      pushLog("status", "Microphone started");
    } catch (e) {
      setLiveInterim("");
      setError(`Mic access failed: ${e instanceof Error ? e.message : String(e)}`);
      setStatus("error");
      await session.stop();
      sessionRef.current = null;
    }
  }, [wsUrl, pushLog]);

  const endUtterance = useCallback(async () => {
    await sessionRef.current?.endUtterance();
  }, []);

  const stop = useCallback(async () => {
    await micRef.current?.stop();
    micRef.current = null;
    await sessionRef.current?.stop();
    sessionRef.current = null;
    setLiveInterim("");
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
    liveInterim,
    logs,
    refreshHealth,
    start,
    stop,
    endUtterance,
  };
}
