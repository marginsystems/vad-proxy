/** Normalize unknown errors (graphql-ws often passes DOM Event objects). */
export function formatError(err: unknown): string {
  if (err instanceof Error) return err.message;
  if (err instanceof Event) {
    const target = err.target;
    if (target instanceof WebSocket) {
      return `WebSocket connection failed (${target.url}). Is vad-proxy running?`;
    }
    return "WebSocket connection failed. Is vad-proxy running?";
  }
  if (typeof err === "object" && err !== null) {
    if ("message" in err && typeof (err as { message: unknown }).message === "string") {
      return (err as { message: string }).message;
    }
    if ("reason" in err && typeof (err as { reason: unknown }).reason === "string") {
      return (err as { reason: string }).reason;
    }
  }
  return String(err);
}

export function formatFetchError(err: unknown, url: string): string {
  const msg = formatError(err);
  if (msg === "Failed to fetch" || msg.includes("NetworkError")) {
    return (
      `Cannot reach vad-proxy at ${url}. ` +
      "Start Docker (`docker compose up -d`) or use Local mode so requests go through the Vite dev proxy."
    );
  }
  return msg;
}
