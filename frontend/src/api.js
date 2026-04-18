const API_BASE = import.meta.env.VITE_API_BASE_URL || "http://localhost:8000";

async function request(path, options = {}) {
  const response = await fetch(`${API_BASE}${path}`, options);
  if (!response.ok) {
    const text = await response.text();
    throw new Error(text || `Request failed: ${response.status}`);
  }
  const contentType = response.headers.get("content-type") || "";
  if (contentType.includes("application/json")) {
    return response.json();
  }
  return response.text();
}

export const apiBase = API_BASE;

export const getHealth = () => request("/health");
export const getSubscribers = () => request("/api/subscribers");
export const createSubscriber = (payload) =>
  request("/api/subscribers", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
export const getDocuments = (subscriber) =>
  request(`/api/subscribers/${encodeURIComponent(subscriber)}/documents`);
export const getLogs = (subscriber) =>
  request(`/api/subscribers/${encodeURIComponent(subscriber)}/logs`);
export const getLatestResults = (subscriber) =>
  request(`/api/subscribers/${encodeURIComponent(subscriber)}/results/latest`);
export const runPipeline = (payload) =>
  request("/api/pipeline/run", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
export const runSimulator = (payload) =>
  request("/api/simulator/evaluate", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });

export async function uploadFiles(path, files) {
  const formData = new FormData();
  files.forEach((file) => formData.append("files", file));
  return request(path, {
    method: "POST",
    body: formData,
  });
}
