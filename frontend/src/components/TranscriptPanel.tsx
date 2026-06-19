import type { VoiceEvent } from "../lib/types";

type Props = {
  latest: VoiceEvent | null;
  liveInterim: string;
  transcripts: VoiceEvent[];
};

export function TranscriptPanel({ latest, liveInterim, transcripts }: Props) {
  return (
    <section className="panel">
      <h2>Transcripts</h2>
      <div className="latest-transcript">
        {liveInterim ? (
          <p className="interim">{liveInterim}</p>
        ) : null}
        {latest?.text ? (
          <>
            <p className="quote">{latest.text}</p>
            <p className="meta">
              turnComplete={String(latest.turnComplete)} · endPhrase=
              {String(latest.endPhrase)} · {latest.sttBackend}
            </p>
          </>
        ) : !liveInterim ? (
          <p className="muted">Speak into the mic after starting a session.</p>
        ) : null}
      </div>
      {transcripts.length > 0 && (
        <ul className="transcript-list">
          {[...transcripts].reverse().map((t, i) => (
            <li key={`transcript-${i}`}>
              <span className="quote-sm">{t.text}</span>
              <span className="meta">
                [{t.startSecs?.toFixed(2)}–{t.endSecs?.toFixed(2)}s]{" "}
                {t.turnComplete ? "complete" : "partial"}
              </span>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}
