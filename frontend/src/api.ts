import { keepPreviousData, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useSearchParams } from "react-router-dom";

// eslint-disable-next-line @typescript-eslint/no-explicit-any
export type Any = any;

export class ApiError extends Error {
  status: number;
  constructor(status: number, message: string) {
    super(message);
    this.status = status;
  }
}

const API_KEY_STORAGE = "dex.apiKey";
export function getApiKey(): string {
  try { return localStorage.getItem(API_KEY_STORAGE) || ""; } catch { return ""; }
}
export function setApiKey(v: string) {
  try { v ? localStorage.setItem(API_KEY_STORAGE, v) : localStorage.removeItem(API_KEY_STORAGE); } catch { /* storage unavailable */ }
}

export async function api<T = Any>(path: string, init: RequestInit = {}): Promise<T> {
  const headers = new Headers(init.headers);
  const key = getApiKey();
  if (key) headers.set("X-API-Key", key);
  if (init.body && !(init.body instanceof FormData)) headers.set("Content-Type", "application/json");
  const res = await fetch(`/api${path}`, { ...init, headers });
  const text = await res.text();
  const data = text ? JSON.parse(text) : null;
  if (!res.ok) {
    const err = data?.error;
    const msg = typeof err === "string" ? err : err?.message || (data?.details ? "Invalid input" : res.statusText);
    throw new ApiError(res.status, msg);
  }
  return data as T;
}

/** Download a file from the API (a plain <a href> cannot send the X-API-Key header). */
export async function downloadFile(path: string, filename: string): Promise<void> {
  const key = getApiKey();
  const res = await fetch(`/api${path}`, { headers: key ? { "X-API-Key": key } : {} });
  if (!res.ok) throw new ApiError(res.status, res.status === 401 ? "Access key required" : res.statusText);
  const url = URL.createObjectURL(await res.blob());
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  a.click();
  URL.revokeObjectURL(url);
}

// ---------------------------------------------------------------- global filters (URL-backed)
export interface Filters { department?: string; device_model?: string; work_mode?: string; week_from?: string; week_to?: string }
const FILTER_KEYS: (keyof Filters)[] = ["department", "device_model", "work_mode", "week_from", "week_to"];

export function useFilters() {
  const [params, setParams] = useSearchParams();
  const filters: Filters = {};
  FILTER_KEYS.forEach((k) => { const v = params.get(k); if (v) filters[k] = v; });
  const set = (patch: Partial<Filters>) => {
    const next = new URLSearchParams(params);
    Object.entries(patch).forEach(([k, v]) => (v ? next.set(k, String(v)) : next.delete(k)));
    setParams(next, { replace: true });
  };
  const clear = () => {
    const next = new URLSearchParams(params);
    FILTER_KEYS.forEach((k) => next.delete(k));
    setParams(next, { replace: true });
  };
  const qs = qsOf(filters);
  const active = FILTER_KEYS.filter((k) => filters[k]).length;
  return { filters, set, clear, qs, active };
}

export function qsOf(obj: object): string {
  const p = new URLSearchParams();
  Object.entries(obj).forEach(([k, v]) => { if (v !== undefined && v !== null && v !== "") p.set(k, String(v)); });
  const s = p.toString();
  return s ? `?${s}` : "";
}

export function useApi<T = Any>(path: string | null, opts: { enabled?: boolean } = {}) {
  return useQuery<T, ApiError>({
    queryKey: [path],
    queryFn: () => api<T>(path as string),
    enabled: !!path && opts.enabled !== false,
    placeholderData: keepPreviousData,
    staleTime: 60_000,
    retry: (n, e) => e.status >= 500 && n < 2,
  });
}

export function useMeta() {
  return useApi("/v1/meta");
}

export function usePost<TBody, TResp = Any>(path: string, invalidate: string[] = []) {
  const qc = useQueryClient();
  return useMutation<TResp, ApiError, TBody>({
    mutationFn: (body) => api<TResp>(path, { method: "POST", body: JSON.stringify(body) }),
    onSuccess: () => invalidate.forEach((k) => qc.invalidateQueries({ predicate: (q) => String(q.queryKey[0]).startsWith(k) })),
  });
}

// ---------------------------------------------------------------- formatting
export const fmt = {
  n: (v: number | null | undefined, d = 1) => (v === null || v === undefined || Number.isNaN(v) ? "—" : Number(v).toLocaleString(undefined, { minimumFractionDigits: d, maximumFractionDigits: d })),
  i: (v: number | null | undefined) => (v === null || v === undefined ? "—" : Math.round(v).toLocaleString()),
  pct: (v: number | null | undefined, d = 1) => (v === null || v === undefined ? "—" : `${Number(v).toFixed(d)}%`),
  usd: (v: number | null | undefined) => (v === null || v === undefined ? "—" : `$${Math.round(v).toLocaleString()}`),
  signed: (v: number | null | undefined, d = 1, suffix = "") => (v === null || v === undefined ? "—" : `${v > 0 ? "+" : ""}${Number(v).toFixed(d)}${suffix}`),
  x: (v: number | null | undefined) => (v === null || v === undefined ? "—" : `${(Math.round(v * 10 + 1e-9) / 10).toFixed(1)}×`),
};

export const SIGNAL_LABEL: Record<string, string> = {
  boot: "Boot duration", latency: "Network latency", packet_loss: "Packet loss", hangs: "App hangs / wk",
  hw_health: "Hardware health", battery: "Battery health", disk: "Disk health", noncompliant: "Policy non-compliance",
  severity: "Telemetry severity",
};

export function bandColor(band: string): string {
  return ({ Excellent: "var(--good-text)", Good: "var(--machine)", Fair: "var(--human)", Poor: "var(--critical)",
    Healthy: "var(--machine)", Degraded: "var(--human)" } as Record<string, string>)[band] || "var(--text-dim)";
}

export function sevColor(sev: string): string {
  return ({ Critical: "var(--critical)", High: "var(--serious)", Medium: "var(--human)", Low: "var(--machine)" } as Record<string, string>)[sev] || "var(--text-dim)";
}
