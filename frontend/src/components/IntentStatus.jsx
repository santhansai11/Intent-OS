import React, { useState } from "react";

const STATE_CLASS = {
  NEW: "st-new",
  READY: "st-ready",
  RUNNING: "st-running",
  WAITING: "st-waiting",
  RECOVERY: "st-recovery",
  COMPLETED: "st-completed",
  FAILED: "st-failed",
};

const STEP_ICON = {
  DONE: "✓",
  BLOCKED: "⊘",
  STEP_FAILED: "✗",
  PENDING: "○",
};

function StepRow({ intent, step }) {
  const state = intent.step_state[step.id] || "PENDING";
  const result = (intent.step_results[step.id] || {}).result;
  return (
    <li className={`step step-${state.toLowerCase()}`}>
      <span className="step-icon">{STEP_ICON[state] || "○"}</span>
      <span className="step-name">{step.service}.{step.capability}</span>
      <span className="step-desc">{step.description}</span>
      {result && (
        <pre className="step-result">{JSON.stringify(result, null, 1).slice(0, 220)}</pre>
      )}
    </li>
  );
}

export default function IntentStatus({ intents, metrics, strategy, artifacts }) {
  const [openId, setOpenId] = useState(null);

  if (!intents || intents.length === 0) {
    return (
      <section className="panel">
        <h2>Intent Processes</h2>
        <p className="muted">
          No intents yet. Describe a goal above — IntentOS will create a managed
          process with priority, deadline, resources and permissions.
        </p>
      </section>
    );
  }

  return (
    <section className="panel">
      <h2>
        Intent Processes{" "}
        <span className="badge">strategy: {strategy}</span>{" "}
        <span className="badge">
          {metrics ? `${metrics.completed}/${metrics.submitted} completed` : ""}
        </span>
      </h2>
      <ul className="intent-list">
        {intents.map((intent) => {
          const open = openId === intent.id;
          const p = intent.progress || {};
          return (
            <li key={intent.id} className="intent-item">
              <button
                className="intent-head"
                onClick={() => setOpenId(open ? null : intent.id)}
              >
                <span className={`state-badge ${STATE_CLASS[intent.state] || ""}`}>
                  {intent.state}
                </span>
                <span className="intent-id">{intent.id}</span>
                <span className="intent-goal">{intent.goal}</span>
                <span className={`prio prio-${intent.priority.toLowerCase()}`}>
                  {intent.priority}
                </span>
                <span className="muted">
                  {intent.deadline ? `⏰ ${intent.deadline.slice(11, 16)}` : "no deadline"}
                </span>
                <span className="muted">
                  {p.DONE || 0}✓ / {p.BLOCKED || 0}⊘ / {p.STEP_FAILED || 0}✗ /{" "}
                  {p.PENDING || 0}○
                </span>
                {intent.deadline_missed && <span className="miss">MISSED</span>}
              </button>
              {open && (
                <div className="intent-detail">
                  <div className="meta">
                    type: {intent.intent_type} · entities:{" "}
                    {JSON.stringify(intent.entities)} · resources:{" "}
                    {JSON.stringify(intent.resource_requirements)}
                  </div>
                  <ul className="steps">
                    {intent.plan.map((step) => (
                      <StepRow key={step.id} intent={intent} step={step} />
                    ))}
                  </ul>
                  {artifacts && artifacts.filter((a) => a.intent_id === intent.id).length > 0 && (
                    <div className="artifacts">
                      {artifacts
                        .filter((a) => a.intent_id === intent.id)
                        .map((a, i) => (
                          <div key={i} className="artifact">
                            📄 {a.display_path || a.path}{" "}
                            <span className="muted">
                              ({a.bytes} bytes{a.words ? `, ${a.words} words` : ""})
                            </span>
                          </div>
                        ))}
                    </div>
                  )}
                  {intent.blocked && intent.blocked.length > 0 && (
                    <div className="blocked">
                      {intent.blocked.map((b, i) => (
                        <div key={i}>
                          ⛔ {b.service} ({b.decision}): {b.reason}
                        </div>
                      ))}
                    </div>
                  )}
                  {intent.execution_log && (
                    <pre className="log">
                      {intent.execution_log.slice(-12).join("\n")}
                    </pre>
                  )}
                </div>
              )}
            </li>
          );
        })}
      </ul>
    </section>
  );
}
