import { useState } from "react";
import type { LogEntry } from "../lib/types";

type Props = {
  logs: LogEntry[];
};

export function EventLog({ logs }: Props) {
  const [open, setOpen] = useState(false);

  return (
    <section className="panel">
      <button
        type="button"
        className="collapse-toggle"
        onClick={() => setOpen((v) => !v)}
      >
        Event log ({logs.length}) {open ? "▾" : "▸"}
      </button>
      {open && (
        <pre className="event-log">
          {logs.length === 0
            ? "No events yet."
            : logs
                .map((e) => {
                  const time = new Date(e.ts).toLocaleTimeString();
                  return `[${time}] ${e.label}\n${JSON.stringify(e.payload, null, 2)}`;
                })
                .join("\n\n")}
        </pre>
      )}
    </section>
  );
}
