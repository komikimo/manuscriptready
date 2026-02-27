/**
 * ManuscriptReady API Client
 * ═══════════════════════════
 * Connects to the real backend. No demo mode. No regex fallbacks.
 * All processing goes through the AI pipeline on the server.
 */

const BASE = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000/api/v1";

let _token = null;

function setToken(t) { _token = t; if (typeof window !== "undefined") localStorage.setItem("mr_token", t); }
function getToken() { if (_token) return _token; if (typeof window !== "undefined") return localStorage.getItem("mr_token"); return null; }
function clearToken() { _token = null; if (typeof window !== "undefined") localStorage.removeItem("mr_token"); }

async function api(path, options = {}) {
  const headers = { "Content-Type": "application/json", ...options.headers };
  const token = getToken();
  if (token) headers["Authorization"] = `Bearer ${token}`;

  const res = await fetch(`${BASE}${path}`, { ...options, headers });

  if (res.status === 401) {
    clearToken();
    throw new Error("Session expired. Please sign in again.");
  }
  if (!res.ok) {
    const body = await res.json().catch(() => ({}));
    throw new Error(body.detail || `Request failed: ${res.status}`);
  }
  return res.json();
}

// ── Auth ──
export async function signup(email, password, fullName, institution) {
  const data = await api("/auth/signup", {
    method: "POST",
    body: JSON.stringify({ email, password, full_name: fullName, institution }),
  });
  setToken(data.access_token);
  return data;
}

export async function login(email, password) {
  const data = await api("/auth/login", {
    method: "POST",
    body: JSON.stringify({ email, password }),
  });
  setToken(data.access_token);
  return data;
}

export function logout() { clearToken(); }

export async function getMe() { return api("/auth/me"); }

// ── Processing ──
export async function processText(text, mode, sectionType, sourceLanguage = "auto") {
  return api("/process/text", {
    method: "POST",
    body: JSON.stringify({ text, mode, section_type: sectionType, source_language: sourceLanguage }),
  });
}

export async function uploadFile(file) {
  const form = new FormData();
  form.append("file", file);
  const token = getToken();
  const headers = {};
  if (token) headers["Authorization"] = `Bearer ${token}`;

  const res = await fetch(`${BASE}/process/upload`, { method: "POST", headers, body: form });
  if (!res.ok) throw new Error("Upload failed");
  return res.json();
}

export async function downloadDocx(improvedText) {
  const token = getToken();
  const headers = {};
  if (token) headers["Authorization"] = `Bearer ${token}`;

  const form = new FormData();
  form.append("improved_text", improvedText);

  const res = await fetch(`${BASE}/process/download`, { method: "POST", headers, body: form });
  if (!res.ok) throw new Error("Download failed");
  return res.blob();
}

// ── Journal ──
export async function getJournalStyles() { return api("/journal/styles"); }
export async function checkJournalCompliance(text, style, section) {
  return api("/journal/check", {
    method: "POST",
    body: JSON.stringify({ text, style, section }),
  });
}

// ── Versions ──
export async function getHistory(docId) { return api(`/versions/${docId}/history`); }
export async function getChanges(docId) { return api(`/versions/${docId}/changes`); }
export async function acceptChange(docId, idx) { return api(`/versions/${docId}/accept/${idx}`, { method: "POST" }); }
export async function rejectChange(docId, idx) { return api(`/versions/${docId}/reject/${idx}`, { method: "POST" }); }
export async function acceptAll(docId) { return api(`/versions/${docId}/accept_all`, { method: "POST" }); }
export async function applyDecisions(docId) { return api(`/versions/${docId}/apply`, { method: "POST" }); }

// ── Feedback ──
export async function rateFeedback(docId, rating, helpful = true, comment = "") {
  return api("/feedback/rate", {
    method: "POST",
    body: JSON.stringify({ doc_id: docId, rating, helpful, comment }),
  });
}

// ── Dashboard ──
export async function getDashboard() { return api("/dashboard/"); }

// ── Analytics ──
export async function getMyStats() { return api("/stats/me"); }

// ── Subscription ──
export async function getSubscription() { return api("/billing/subscription"); }

// ── Evaluation (dev only) ──
export async function runEvaluation() { return api("/eval/run"); }
