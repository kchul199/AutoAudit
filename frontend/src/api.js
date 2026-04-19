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
export const getLiveConsensusReadiness = () => request("/api/live-consensus/readiness");
export const probeLiveConsensus = () =>
  request("/api/live-consensus/probe", {
    method: "POST",
  });
export const getReviewOpsDashboard = () => request("/api/dashboard/review-ops");
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
export const getLatestAnchorEval = (subscriber) =>
  request(`/api/subscribers/${encodeURIComponent(subscriber)}/evals/anchor/latest`);
export const getTurnDetail = (subscriber, convId, turnIndex) =>
  request(
    `/api/subscribers/${encodeURIComponent(subscriber)}/results/turn-detail?conv_id=${encodeURIComponent(convId)}&turn_index=${turnIndex}`,
  );
export const submitReviewAction = (subscriber, payload) =>
  request(`/api/subscribers/${encodeURIComponent(subscriber)}/results/review-actions`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
export const listPipelineJobs = (subscriber) =>
  request(
    `/api/pipeline/jobs${subscriber ? `?subscriber=${encodeURIComponent(subscriber)}` : ""}`,
  );
export const getPipelineJob = (jobId) => request(`/api/pipeline/jobs/${encodeURIComponent(jobId)}`);
export const streamPipelineJob = (jobId, onMessage, onError) =>
  openEventStream(`/api/pipeline/jobs/${encodeURIComponent(jobId)}/events`, onMessage, onError);
export const createPipelineJob = (payload) =>
  request("/api/pipeline/jobs", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
export const listAnchorEvalJobs = (subscriber) =>
  request(
    `/api/evals/anchor/jobs${subscriber ? `?subscriber=${encodeURIComponent(subscriber)}` : ""}`,
  );
export const getAnchorEvalJob = (jobId) =>
  request(`/api/evals/anchor/jobs/${encodeURIComponent(jobId)}`);
export const streamAnchorEvalJob = (jobId, onMessage, onError) =>
  openEventStream(`/api/evals/anchor/jobs/${encodeURIComponent(jobId)}/events`, onMessage, onError);
export const createAnchorEvalJob = (payload) =>
  request("/api/evals/anchor/jobs", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
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

function openEventStream(path, onMessage, onError) {
  const source = new EventSource(`${API_BASE}${path}`);
  source.addEventListener("job", (event) => {
    try {
      onMessage?.(JSON.parse(event.data));
    } catch (error) {
      onError?.(error);
    }
  });
  source.onerror = (error) => {
    onError?.(error);
  };
  return source;
}
