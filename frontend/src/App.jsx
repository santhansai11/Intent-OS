import React, { useCallback, useEffect, useState } from "react";
import IntentInput from "./components/IntentInput.jsx";
import IntentStatus from "./components/IntentStatus.jsx";
import ResourceView from "./components/ResourceView.jsx";
import { api } from "./api.js";

export default function App() {
  const [status, setStatus] = useState(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  const refresh = useCallback(async () => {
    try {
      setStatus(await api.status());
      setError("");
    } catch (e) {
      setError("Cannot reach the IntentOS kernel. Is `python run_intentos.py --server` running?");
    }
  }, []);

  useEffect(() => {
    refresh();
    const timer = setInterval(refresh, 1200);
    return () => clearInterval(timer);
  }, [refresh]);

  const handleSubmit = async (text) => {
    setBusy(true);
    try {
      await api.submitIntent(text);
      await refresh();
    } catch (e) {
      setError(String(e.message || e));
    } finally {
      setBusy(false);
    }
  };

  const handleFault = async (service) => {
    try {
      await api.injectFault(service, 1);
      await refresh();
    } catch (e) {
      setError(String(e.message || e));
    }
  };

  return (
    <div className="app">
      <header>
        <h1>⌘ IntentOS</h1>
        <p className="tagline">
          Don't tell the computer which application to open — tell it what you want
          to accomplish. The Intent Kernel schedules, authorizes, allocates,
          executes and recovers on your behalf.
        </p>
        <div className="toolbar">
          <span className="badge auto-policy" title={status?.scheduler_reason || ""}>
            ⚙ auto scheduler: {status?.scheduler_policy || "…"}
          </span>
          {status?.scheduler_reason && (
            <span className="muted small">{status.scheduler_reason}</span>
          )}
          {status?.metrics && (
            <span className="metrics">
              submitted {status.metrics.submitted} · completed{" "}
              {status.metrics.completed} · failed {status.metrics.failed} · retries{" "}
              {status.metrics.retries} · deadline misses{" "}
              {status.metrics.deadline_misses}
            </span>
          )}
        </div>
        {error && <div className="error">{error}</div>}
      </header>

      <main className="grid">
        <div className="col">
          <IntentInput onSubmit={handleSubmit} busy={busy} />
          <IntentStatus
            intents={status?.intents}
            metrics={status?.metrics}
            artifacts={status?.artifacts}
            strategy={status?.strategy}
          />
        </div>
        <div className="col">
          <ResourceView
            resources={status?.resources}
            system={status?.system}
            services={status?.services}
            onInjectFault={handleFault}
          />
        </div>
      </main>

      <footer className="muted small">
        IntentOS prototype — intent-level scheduling, permissions, resource
        allocation and checkpoint/recovery on top of the host OS.
      </footer>
    </div>
  );
}
