import type { VoiceEvent } from "../lib/types";

type Props = {
  latest: VoiceEvent | null;
  transcripts: VoiceEvent[];
};

export function TranscriptPanel({ latest, transcripts }: Props) {
  return (
    <section className="panel">
      <h2>Transcripts</h2>
      <div className="latest-transcript">
        {latest?.text ? (
          <>
            <p className="quote">{latest.text}</p>
            <p className="meta">
              turnComplete={String(latest.turnComplete)} · endPhrase=
              {String(latest.endPhrase)} · {latest.sttBackend}
            </p>
          </>
        ) : (
          <p className="muted">Speak into the mic after starting a session.</p>
        )}
      </div>
      {transcripts.length > 0 && (
        <ul className="transcript-list">
          {[...transcripts].reverse().map((t, i) => (
            <li key={`${t.startSecs}-${i}`}>
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
