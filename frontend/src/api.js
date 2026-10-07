const BASE = "/api";

async function get(path) {
  const res = await fetch(BASE + path);
  if (!res.ok) throw new Error(`GET ${path} -> ${res.status}`);
  return res.json();
}

async function post(path, body) {
  const res = await fetch(BASE + path, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body || {}),
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error(err.error || `POST ${path} -> ${res.status}`);
  }
  return res.json();
}

export const api = {
  status: () => get("/status"),
  health: () => get("/health"),
  submitIntent: (text) => post("/intents", { text }),
  setStrategy: (strategy) => post("/strategy", { strategy }),
  injectFault: (service, count = 1) => post("/faults", { service, count }),
};

export default api;
