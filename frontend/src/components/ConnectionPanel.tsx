import type { HealthResponse } from "../lib/types";
import { DEFAULT_WS_URL, PROD_WS_URL } from "../lib/types";

type Props = {
  wsUrl: string;
  token: string;
  health: HealthResponse | null;
  healthError: string | null;
  status: string;
  onWsUrlChange: (url: string) => void;
  onTokenChange: (token: string) => void;
  onRefreshHealth: () => void;
};

export function ConnectionPanel({
  wsUrl,
  token,
  health,
  healthError,
  status,
  onWsUrlChange,
  onTokenChange,
  onRefreshHealth,
}: Props) {
  return (
    <section className="panel">
      <h2>Connection</h2>
      <div className="row">
        <button
          type="button"
          className="btn secondary"
          onClick={() => onWsUrlChange(DEFAULT_WS_URL)}
        >
          Local
        </button>
        <button
          type="button"
          className="btn secondary"
          onClick={() => onWsUrlChange(PROD_WS_URL)}
        >
          Production
        </button>
        <button type="button" className="btn secondary" onClick={onRefreshHealth}>
          Refresh health
        </button>
      </div>
      <label>
        WebSocket URL
        <input
          value={wsUrl}
          onChange={(e) => onWsUrlChange(e.target.value)}
          spellCheck={false}
        />
      </label>
      <label>
        Auth token
        <input
          type="password"
          value={token}
          onChange={(e) => onTokenChange(e.target.value)}
          placeholder="VAD_PROXY_AUTH_TOKEN from .env"
        />
      </label>
      <div className="health-banner">
        {healthError ? (
          <span className="bad">Health: {healthError}</span>
        ) : health ? (
          <span>
            Server OK — STT: <strong>{health.stt_backend}</strong>, rate{" "}
            {health.sample_rate} Hz, auth required:{" "}
            <strong>{health.graphql_auth_required ? "yes" : "no"}</strong>
          </span>
        ) : (
          <span>Checking server…</span>
        )}
        <span className="muted"> · session: {status}</span>
      </div>
    </section>
  );
}
