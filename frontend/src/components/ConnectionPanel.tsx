import type { HealthResponse } from "../lib/types";
import { localDevWsUrl, PROD_WS_URL } from "../lib/types";

type Props = {
  wsUrl: string;
  health: HealthResponse | null;
  healthError: string | null;
  status: string;
  onWsUrlChange: (url: string) => void;
  onRefreshHealth: () => void;
};

export function ConnectionPanel({
  wsUrl,
  health,
  healthError,
  status,
  onWsUrlChange,
  onRefreshHealth,
}: Props) {
  return (
    <section className="panel">
      <h2>Connection</h2>
      <div className="row">
        <button
          type="button"
          className="btn secondary"
          onClick={() => onWsUrlChange(localDevWsUrl())}
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
      <div className="health-banner">
        {healthError ? (
          <>
            <span className="health-status-pill error">Error</span>
            <span className="health-message" title={healthError}>
              {healthError}
            </span>
            <span className="health-chip">session: {status}</span>
          </>
        ) : health ? (
          <>
            <span className="health-status-pill">OK</span>
            <span className="health-chip">STT: {health.stt_backend}</span>
            <span className="health-chip">{health.sample_rate} Hz</span>
            <span
              className="health-chip origins"
              title={health.allowed_origins.join(", ")}
            >
              {health.allowed_origins.join(", ")}
            </span>
            <span className="health-chip">session: {status}</span>
          </>
        ) : (
          <>
            <span className="health-status-pill skeleton">Checking</span>
            <span className="health-chip skeleton">STT: ...</span>
            <span className="health-chip skeleton">rate ...</span>
            <span className="health-chip skeleton origins">origins ...</span>
            <span className="health-chip skeleton">session: {status}</span>
          </>
        )}
      </div>
    </section>
  );
}
