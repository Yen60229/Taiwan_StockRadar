import axios from "axios";

const API_BASE = import.meta.env.VITE_API_BASE || "/api";

export const api = axios.create({
  baseURL: API_BASE,
  timeout: 20000,
});

api.interceptors.request.use((config) => {
  const token = localStorage.getItem("token");
  if (token) config.headers.Authorization = `Bearer ${token}`;
  return config;
});

api.interceptors.response.use(
  (res) => res,
  (err) => {
    if (err.response?.status === 401) {
      localStorage.removeItem("token");
      if (location.pathname !== "/login") location.href = "/login";
    }
    return Promise.reject(err);
  }
);

// ── Types ────────────────────────────────────────────────
export interface User {
  id: string;
  email: string;
  name?: string;
  notify_email: boolean;
}

export interface ScreenItem {
  code: string;
  name: string;
  short_name?: string;
  market: string;
  industry?: string;
  close?: number;
  volume?: number;
  avg_vol_20d?: number;
  conc_ratio?: number;
  foreign_net?: number;
  trust_net?: number;
  dealer_net?: number;
  total_net?: number;
  foreign_hold_ratio?: number;
  trust_hold_ratio?: number;
  director_hold_ratio?: number;
  in_watchlist: boolean;
}

export interface ScreenResponse {
  total: number;
  items: ScreenItem[];
  filters: any;
  last_update?: string;
}

export interface InstFlowPoint {
  trade_date: string;
  foreign_net?: number;
  trust_net?: number;
  dealer_net?: number;
  total_net?: number;
}

export interface StockDetail {
  code: string;
  name: string;
  market: string;
  industry?: string;
  latest_close?: number;
  avg_vol_20d?: number;
  conc_ratio?: number;
  inst_flow_30d: InstFlowPoint[];
}

// ── Endpoints ────────────────────────────────────────────
export const authApi = {
  register: (data: { email: string; password: string; name?: string }) =>
    api.post("/auth/register", data).then((r) => r.data),
  login: (data: { email: string; password: string }) =>
    api.post("/auth/login", data).then((r) => r.data),
  me: () => api.get<User>("/auth/me").then((r) => r.data),
};

export const screenApi = {
  list: (params: {
    min_avg_vol?: number;
    min_conc?: number;
    industries?: string[];
    markets?: string[];
    only_inst_buy?: boolean;
  }) => api.get<ScreenResponse>("/screen", { params }).then((r) => r.data),
  industries: () => api.get<string[]>("/screen/industries").then((r) => r.data),
};

export const stockApi = {
  detail: (code: string) =>
    api.get<StockDetail>(`/stocks/${code}`).then((r) => r.data),
};

export const watchlistApi = {
  list: () => api.get("/watchlist").then((r) => r.data),
  add: (code: string) => api.post("/watchlist", { stock_code: code }).then((r) => r.data),
  remove: (code: string) => api.delete(`/watchlist/${code}`).then((r) => r.data),
};
