import axios, { AxiosError } from "axios";

export const API_BASE = "/api/v1";
const TOKEN_KEY = "bpi_token";

export const tokenStore = {
  get: () => {
    try {
      return sessionStorage.getItem(TOKEN_KEY);
    } catch {
      return null;
    }
  },
  set: (t: string | null) => {
    try {
      if (t) sessionStorage.setItem(TOKEN_KEY, t);
      else sessionStorage.removeItem(TOKEN_KEY);
    } catch {
      /* storage unavailable */
    }
  },
};

export const api = axios.create({ baseURL: API_BASE, timeout: 600_000 });

api.interceptors.request.use((config) => {
  const t = tokenStore.get();
  if (t) config.headers.Authorization = `Bearer ${t}`;
  return config;
});

api.interceptors.response.use(
  (r) => r,
  (err: AxiosError) => {
    if (err.response?.status === 401 && !String(err.config?.url).includes("/auth/login")) {
      tokenStore.set(null);
      if (window.location.pathname !== "/login") window.location.assign("/login");
    }
    return Promise.reject(err);
  },
);

export function errorMessage(err: unknown): string {
  if (axios.isAxiosError(err)) {
    const d = err.response?.data as { detail?: unknown } | undefined;
    if (typeof d?.detail === "string") return d.detail;
    if (Array.isArray(d?.detail)) return d.detail.map((x: { msg?: string }) => x.msg).join("; ");
    if (err.code === "ERR_NETWORK") return "Backend not reachable. Is the API server running on port 8000?";
    return err.message;
  }
  return err instanceof Error ? err.message : String(err);
}

/** URL for resources loaded directly by the browser (<img>, links): token passed as query parameter. */
export function authedUrl(path: string, params: Record<string, string | number | undefined> = {}) {
  const q = new URLSearchParams();
  Object.entries(params).forEach(([k, v]) => v !== undefined && v !== "" && q.set(k, String(v)));
  const t = tokenStore.get();
  if (t) q.set("token", t);
  return `${API_BASE}${path}?${q.toString()}`;
}

export async function downloadFile(path: string, params: Record<string, string>, fallbackName: string) {
  const r = await api.get(path, { params, responseType: "blob" });
  const cd = String(r.headers["content-disposition"] ?? "");
  const name = /filename="?([^"]+)"?/.exec(cd)?.[1] ?? fallbackName;
  const url = URL.createObjectURL(r.data as Blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = name;
  a.click();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}
