import React, { useState } from "react";

function Bar({ label, used, capacity, unit }) {
  const pct = capacity ? Math.min(100, (used / capacity) * 100) : 0;
  return (
    <div className="bar-row">
      <span className="bar-label">{label}</span>
      <div className="bar">
        <div className="bar-fill" style={{ width: `${pct}%` }} />
      </div>
      <span className="bar-value">
        {used} / {capacity} {unit}
      </span>
    </div>
  );
}

export default function ResourceView({ resources, system, services, onInjectFault }) {
  const [openService, setOpenService] = useState(null);

  return (
    <section className="panel">
      <h2>Resources &amp; Services</h2>

      {resources && (
        <>
          <h3>Kernel resource allocations</h3>
          <Bar label="CPU" used={resources.allocated?.cpu_percent || 0}
               capacity={resources.capacity?.cpu_percent} unit="%" />
          <Bar label="Memory" used={resources.allocated?.memory_mb || 0}
               capacity={resources.capacity?.memory_mb} unit="MB" />
          <Bar label="Network" used={resources.allocated?.network_mbps || 0}
               capacity={resources.capacity?.network_mbps} unit="Mbps" />
          <div className="muted small">
            Active intent allocations:{" "}
            {(resources.active_intents || []).join(", ") || "none"}
          </div>
        </>
      )}

      {system && (
        <div className="muted small system-box">
          Host: {system.platform} · {system.cpu_count} logical CPUs ·
          monitor: {system.source}
          {system.cpu_percent != null && ` · system CPU ${system.cpu_percent}%`}
          {system.memory_percent != null && ` · system RAM ${system.memory_percent}%`}
        </div>
      )}

      {services && (
        <>
          <h3>Service registry (headless services)</h3>
          <ul className="service-list">
            {services.map((svc) => (
              <li key={svc.name}>
                <button
                  className="svc-head"
                  onClick={() => setOpenService(openService === svc.name ? null : svc.name)}
                >
                  <span className="svc-name">{svc.name}</span>
                  <span className="muted">{svc.description}</span>
                  {onInjectFault && (
                    <span
                      className="fault-btn"
                      role="button"
                      onClick={(e) => {
                        e.stopPropagation();
                        onInjectFault(svc.name);
                      }}
                      title="Inject a transient failure into this service (recovery demo)"
                    >
                      ⚡ fail next call
                    </span>
                  )}
                </button>
                {openService === svc.name && (
                  <ul className="caps">
                    {svc.capabilities.map((c) => (
                      <li key={c.name}>
                        <code>{svc.name}.{c.name}</code>{" "}
                        <span className="badge">{c.access}</span> {c.description}
                      </li>
                    ))}
                  </ul>
                )}
              </li>
            ))}
          </ul>
        </>
      )}
    </section>
  );
}
