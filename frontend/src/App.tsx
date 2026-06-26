import { useState } from "react";
import { ChunkDebugPanel } from "./components/ChunkDebugPanel";
import { ConnectionPanel } from "./components/ConnectionPanel";
import { Controls } from "./components/Controls";
import { EventLog } from "./components/EventLog";
import { TranscriptPanel } from "./components/TranscriptPanel";
import { useVoiceSession } from "./hooks/useVoiceSession";
import { localDevWsUrl } from "./lib/types";

export default function App() {
  const [wsUrl, setWsUrl] = useState(localDevWsUrl);

  const session = useVoiceSession(wsUrl);

  return (
    <div className="app">
      <header className="app-header">
        <div className="brand">
          <img
            src="/assets/vad-proxy-logo.png"
            alt="vad-proxy"
            width={40}
            height={40}
            className="brand-logo"
          />
          <div className="brand-text">
            <h1>vad-proxy Voice Lab</h1>
            <p className="subtitle">
              Live-test mic → VAD → STT → transcript against your local Docker
              container.
            </p>
          </div>
        </div>
      </header>

      {session.error && (
        <div className="error-toast" role="alert">
          {session.error}
        </div>
      )}

      <ConnectionPanel
        wsUrl={wsUrl}
        health={session.health}
        healthError={session.healthError}
        status={session.status}
        onWsUrlChange={setWsUrl}
        onRefreshHealth={session.refreshHealth}
      />

      <Controls
        status={session.status}
        onStart={session.start}
        onStop={session.stop}
        onEndUtterance={session.endUtterance}
      />

      <TranscriptPanel
        latest={session.latest}
        liveInterim={session.liveInterim}
        transcripts={session.transcripts}
      />

      <ChunkDebugPanel
        turns={session.chunkDebugTurns}
        enabled={session.health?.debug_interim_chunks === true}
        interimEnabled={session.health?.interim_enabled !== false}
      />

      <EventLog logs={session.logs} />
    </div>
  );
}
