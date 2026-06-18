const API_BASE = import.meta.env.VITE_API_BASE_URL || (import.meta.env.DEV ? "http://localhost:8000" : "");
const GUEST_ID_KEY = "voc_guest_id";
const AUTH_TOKEN_KEY = "voc_auth_token";
const AUTH_USER_KEY = "voc_auth_user";

export type AuthUser = {
  id: string;
  email: string;
  display_name?: string | null;
  created_at: string;
};

export type Company = {
  id: string;
  name: string;
  play_id?: string | null;
  app_id?: string | null;
  domain?: string | null;
  brand_keyword: string;
  maps_enabled: boolean;
  maps_location_hint: string;
  reddit_enabled: boolean;
  created_at: string;
};

export type Run = {
  id: string;
  company_id: string;
  status: "queued" | "scraping" | "classifying" | "done" | "partial" | "failed";
  model_used?: string | null;
  source_counts: Record<string, number>;
  completeness: Record<string, { status: string; count?: number; error?: string; mode?: string }>;
  cost_estimate: number;
  budget_cap: number;
  dedup_ratio: number;
  quarantine_rate: number;
  started_at?: string | null;
  finished_at?: string | null;
  error?: string | null;
  created_at: string;
  company?: Company;
  current_stage: string;
  stage_detail: string;
  progress: number;
};

export type Review = {
  id: string;
  review_hash: string;
  source: string;
  date?: string | null;
  rating?: number | null;
  text: string;
  theme?: string | null;
  l2_theme?: string | null;
  representative_flag: boolean;
};

export type Theme = {
  id: string;
  theme: string;
  count: number;
  normalized_frequency: number;
  share: number;
  theme_score: number;
  rank: number;
  top_quotes: Array<Record<string, unknown>>;
  l2_subthemes: Array<{
    label: string;
    display_label?: string;
    count: number;
    score: number;
    top_quotes: Array<Record<string, unknown>>;
  }>;
};

export type ReviewPage = {
  items: Review[];
  total: number;
  page: number;
  page_size: number;
  pages: number;
};

export type RunLog = {
  id: string;
  run_id: string;
  company_id: string;
  stage: string;
  event: string;
  status: string;
  source?: string | null;
  provider?: string | null;
  model?: string | null;
  attempt?: number | null;
  cost_usd: number;
  input_tokens: number;
  output_tokens: number;
  total_tokens: number;
  details: Record<string, unknown>;
  created_at: string;
};

export type Results = {
  company: Company;
  run: Run;
  reviews: Review[];
  themes: Theme[];
  logs: RunLog[];
  summary: Record<string, any>;
  deck_spec: string;
};

export type Settings = {
  provider: string;
  model: string;
  max_reviews: number;
  batch_size: number;
  recency_window_days: number;
  dedup_threshold: number;
  per_run_budget_usd: number;
  source_weights: Record<string, number>;
};

function makeGuestId() {
  if (typeof crypto !== "undefined" && "randomUUID" in crypto) {
    return crypto.randomUUID();
  }
  return `guest_${Math.random().toString(36).slice(2)}_${Date.now().toString(36)}`;
}

export function getGuestId() {
  const existing = window.localStorage.getItem(GUEST_ID_KEY);
  if (existing) return existing;
  const next = makeGuestId();
  window.localStorage.setItem(GUEST_ID_KEY, next);
  return next;
}

export function getAuthUser(): AuthUser | null {
  const raw = window.localStorage.getItem(AUTH_USER_KEY);
  if (!raw) return null;
  try {
    return JSON.parse(raw) as AuthUser;
  } catch {
    return null;
  }
}

export function clearAuth() {
  window.localStorage.removeItem(AUTH_TOKEN_KEY);
  window.localStorage.removeItem(AUTH_USER_KEY);
}

function isOperatorMode() {
  const path = window.location.pathname;
  return path.startsWith("/kabir") || path.startsWith("/runs/") || path.startsWith("/companies/");
}

function authHeaders() {
  const headers: Record<string, string> = {
    "X-Guest-Id": getGuestId(),
  };
  const token = window.localStorage.getItem(AUTH_TOKEN_KEY);
  if (token) headers.Authorization = `Bearer ${token}`;
  if (isOperatorMode()) headers["X-Operator-Mode"] = "true";
  return headers;
}

async function request<T>(path: string, options?: RequestInit): Promise<T> {
  if (!API_BASE) {
    throw new Error("API backend is not configured. Set VITE_API_BASE_URL to the deployed FastAPI backend URL and redeploy the frontend.");
  }
  const response = await fetch(`${API_BASE}${path}`, {
    ...options,
    headers: {
      "Content-Type": "application/json",
      ...authHeaders(),
      ...(options?.headers || {}),
    },
  });
  if (!response.ok) {
    const body = await response.text();
    throw new Error(body || response.statusText);
  }
  return response.json() as Promise<T>;
}

export const api = {
  baseUrl: API_BASE,
  login(email: string) {
    return request<{ user: AuthUser; token: string; claimed_runs: number }>("/api/auth/login", {
      method: "POST",
      body: JSON.stringify({ email, guest_id: getGuestId() }),
    }).then((response) => {
      window.localStorage.setItem(AUTH_TOKEN_KEY, response.token);
      window.localStorage.setItem(AUTH_USER_KEY, JSON.stringify(response.user));
      return response;
    });
  },
  me() {
    return request<AuthUser>("/api/auth/me").then((user) => {
      window.localStorage.setItem(AUTH_USER_KEY, JSON.stringify(user));
      return user;
    });
  },
  logout() {
    clearAuth();
  },
  submitRun(payload: { name: string; play_link?: string; app_store_link?: string; website?: string; maps_enabled?: boolean; maps_location_hint?: string; reddit_enabled?: boolean }) {
    return request<{ run: Run; deduped_existing: boolean }>("/api/runs", {
      method: "POST",
      body: JSON.stringify({
        play_link: "",
        app_store_link: "",
        website: "",
        maps_location_hint: "India",
        maps_enabled: false,
        reddit_enabled: false,
        ...payload,
      }),
    });
  },
  submitPublicRun(payload: { name: string; website: string }) {
    return request<{ run: Run; deduped_existing: boolean }>("/api/runs", {
      method: "POST",
      body: JSON.stringify({
        name: payload.name,
        website: payload.website,
        play_link: "",
        app_store_link: "",
        maps_enabled: true,
        maps_location_hint: "India",
        reddit_enabled: true,
      }),
    });
  },
  runs() {
    return request<Run[]>("/api/runs");
  },
  run(id: string) {
    return request<Run>(`/api/runs/${id}`);
  },
  rerun(id: string) {
    return request<{ run: Run; deduped_existing: boolean }>(`/api/runs/${id}/rerun`, {
      method: "POST",
    });
  },
  deleteRun(id: string) {
    if (!API_BASE) {
      return Promise.reject(new Error("API backend is not configured. Set VITE_API_BASE_URL to the deployed FastAPI backend URL and redeploy the frontend."));
    }
    return fetch(`${API_BASE}/api/runs/${id}`, { method: "DELETE", headers: authHeaders() }).then(async (response) => {
      if (!response.ok) {
        const body = await response.text();
        let message = body || response.statusText;
        try {
          const parsed = JSON.parse(body);
          message = parsed.detail || message;
        } catch {
          // Keep the raw response text.
        }
        throw new Error(message);
      }
    });
  },
  results(id: string) {
    return request<Results>(`/api/runs/${id}/results`);
  },
  reviews(id: string, params: Record<string, string | number | undefined>) {
    const search = new URLSearchParams();
    Object.entries(params).forEach(([key, value]) => {
      if (value !== undefined && value !== "") search.set(key, String(value));
    });
    return request<ReviewPage>(`/api/runs/${id}/reviews?${search.toString()}`);
  },
  logs(id: string) {
    return request<RunLog[]>(`/api/runs/${id}/logs`);
  },
  settings() {
    return request<Settings>("/api/settings");
  },
  updateSettings(payload: Partial<Settings>) {
    return request<Settings>("/api/settings", {
      method: "PUT",
      body: JSON.stringify(payload),
    });
  },
  downloadUrl(runId: string, fmt: "xlsx" | "csv" | "json") {
    return `${API_BASE}/api/runs/${runId}/downloads/${fmt}`;
  },
  async downloadRun(runId: string, fmt: "xlsx" | "csv" | "json") {
    if (!API_BASE) {
      throw new Error("API backend is not configured. Set VITE_API_BASE_URL to the deployed FastAPI backend URL and redeploy the frontend.");
    }
    const response = await fetch(`${API_BASE}/api/runs/${runId}/downloads/${fmt}`, { headers: authHeaders() });
    if (!response.ok) {
      const body = await response.text();
      throw new Error(body || response.statusText);
    }
    const blob = await response.blob();
    const url = URL.createObjectURL(blob);
    const link = document.createElement("a");
    link.href = url;
    link.download = `tagged_reviews.${fmt}`;
    link.click();
    URL.revokeObjectURL(url);
  },
};
