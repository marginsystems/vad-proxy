import { useCallback, useEffect, useRef, useState } from "react";
import { startMicCapture } from "../lib/audio";
import { formatError, formatFetchError } from "../lib/errors";
import { fetchHealth, VoiceGraphqlSession } from "../lib/graphql";
import type {
  ChunkDebugTurn,
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
  const [chunkDebugTurns, setChunkDebugTurns] = useState<ChunkDebugTurn[]>([]);
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
    const healthUrl = healthUrlFromWs(wsUrl);
    try {
      const data = (await fetchHealth(healthUrl)) as HealthResponse;
      setHealth(data);
      setHealthError(null);
    } catch (e) {
      setHealth(null);
      setHealthError(formatFetchError(e, healthUrl));
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
    setChunkDebugTurns([]);
    setLogs([]);

    const session = new VoiceGraphqlSession(wsUrl, {
      onEvent: (ev) => {
        pushLog(ev.kind, ev);
        if (ev.kind === "chunk_debug" && ev.chunks?.length) {
          const chunks = ev.chunks;
          setChunkDebugTurns((prev) => [
            {
              startSecs: ev.startSecs ?? chunks[0].startSecs,
              endSecs: ev.endSecs ?? chunks[chunks.length - 1].endSecs,
              chunks,
            },
            ...prev.slice(0, 4),
          ]);
          return;
        }
        if (ev.kind === "error") {
          if (ev.fatal) {
            setLiveInterim("");
            setError(ev.message ?? "Session error");
            setStatus("error");
          } else {
            setError(ev.message ?? "STT slice dropped");
          }
          return;
        }
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
      const msg = formatError(e);
      setError(msg.startsWith("Microphone") || msg.startsWith("Firefox") || msg.startsWith("Audio capture") ? msg : `Session failed: ${msg}`);
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
    // Session.stop() flushes the utterance and waits for chunk_debug before closing WS.
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
    chunkDebugTurns,
    logs,
    refreshHealth,
    start,
    stop,
    endUtterance,
  };
}
