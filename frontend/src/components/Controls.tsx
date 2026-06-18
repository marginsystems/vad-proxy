type Props = {
  status: string;
  onStart: () => void;
  onStop: () => void;
  onEndUtterance: () => void;
};

export function Controls({ status, onStart, onStop, onEndUtterance }: Props) {
  const listening = status === "listening";
  const busy = status === "connecting";

  return (
    <section className="panel controls">
      <button
        type="button"
        className="btn primary"
        disabled={listening || busy}
        onClick={onStart}
      >
        Start listening
      </button>
      <button
        type="button"
        className="btn"
        disabled={!listening}
        onClick={onEndUtterance}
      >
        End utterance
      </button>
      <button
        type="button"
        className="btn danger"
        disabled={status === "idle"}
        onClick={onStop}
      >
        Stop
      </button>
    </section>
  );
}
