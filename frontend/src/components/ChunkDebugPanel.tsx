import type { ChunkDebugTurn, InterimChunk } from "../lib/types";

type Props = {
  turns: ChunkDebugTurn[];
  enabled: boolean;
  interimEnabled: boolean;
};

function wavDataUrl(audioBase64: string): string {
  return `data:audio/wav;base64,${audioBase64}`;
}

function reasonClass(reason: string): string {
  if (reason === "dip") return "chunk-reason dip";
  if (reason === "max") return "chunk-reason max";
  if (reason === "tail") return "chunk-reason tail";
  return "chunk-reason";
}

function ChunkRow({ chunk }: { chunk: InterimChunk }) {
  const duration = (chunk.endSecs - chunk.startSecs).toFixed(2);
  return (
    <li className="chunk-row">
      <div className="chunk-meta">
        <span className="chunk-index">#{chunk.index}</span>
        <span className={reasonClass(chunk.reason)}>{chunk.reason}</span>
        <span className="chunk-time">
          {chunk.startSecs.toFixed(2)}–{chunk.endSecs.toFixed(2)}s ({duration}s)
        </span>
      </div>
      {chunk.text ? <p className="chunk-text">{chunk.text}</p> : null}
      <audio controls preload="none" src={wavDataUrl(chunk.audioBase64)} />
    </li>
  );
}

export function ChunkDebugPanel({ turns, enabled, interimEnabled }: Props) {
  const latest = turns[0] ?? null;

  return (
    <section className="panel chunk-debug-panel">
      <h2>Chunk debug</h2>
      {!interimEnabled ? (
        <p className="muted">Set VAD_PROXY_INTERIM_ENABLED=true to use interim chunking.</p>
      ) : !enabled ? (
        <p className="muted">
          Set VAD_PROXY_DEBUG_INTERIM_CHUNKS=true in .env and restart Docker to replay
          interim slice audio after each turn.
        </p>
      ) : latest ? (
        <>
          <p className="chunk-turn-label">
            Latest turn {latest.startSecs.toFixed(2)}–{latest.endSecs.toFixed(2)}s ·{" "}
            {latest.chunks.length} chunk{latest.chunks.length === 1 ? "" : "s"}
          </p>
          <ul className="chunk-list">
            {latest.chunks.map((chunk) => (
              <ChunkRow key={`chunk-${chunk.index}`} chunk={chunk} />
            ))}
          </ul>
          {turns.length > 1 ? (
            <details className="chunk-history">
              <summary>Previous turns ({turns.length - 1})</summary>
              {turns.slice(1).map((turn, i) => (
                <div key={`turn-${turn.startSecs}-${i}`} className="chunk-history-turn">
                  <p className="chunk-turn-label">
                    {turn.startSecs.toFixed(2)}–{turn.endSecs.toFixed(2)}s
                  </p>
                  <ul className="chunk-list">
                    {turn.chunks.map((chunk) => (
                      <ChunkRow key={`hist-${i}-${chunk.index}`} chunk={chunk} />
                    ))}
                  </ul>
                </div>
              ))}
            </details>
          ) : null}
        </>
      ) : (
        <p className="muted">
          Complete a speaking turn to see how interim chunking sliced your audio.
        </p>
      )}
    </section>
  );
}
