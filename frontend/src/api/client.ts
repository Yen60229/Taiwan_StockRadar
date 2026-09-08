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

/** 帳號被停權 / 尚未核准時後端回的錯誤碼（見 backend/api/deps.py） */
const ACCOUNT_BLOCKED_CODES = [
  "pending_approval",
  "registration_rejected",
  "account_disabled",
  "account_not_active",
];

api.interceptors.response.use(
  (res) => res,
  (err) => {
    const status = err.response?.status;
    const code = err.response?.data?.detail?.code;

    // 403 + 帳號類錯誤碼＝手上這張 token 對應的帳號已經不能用了
    // （例如管理員把它停權）。跟 401 一樣要把人踢回登入頁，
    // 否則畫面會停在一個每個請求都失敗的空殼上。
    const accountBlocked = status === 403 && ACCOUNT_BLOCKED_CODES.includes(code);

    if (status === 401 || accountBlocked) {
      localStorage.removeItem("token");
      if (location.pathname !== "/login") location.href = "/login";
    }
    return Promise.reject(err);
  }
);

/**
 * 從 axios 錯誤裡取出可以直接顯示給人看的訊息。
 * FastAPI 的 detail 可能是字串，也可能是 {code, message} 物件——
 * 直接把物件塞進 JSX 會讓 React 整個 crash，所以一律在這裡收斂成字串。
 */
export function errMessage(e: any, fallback = "發生錯誤，請稍後再試"): string {
  const detail = e?.response?.data?.detail;
  if (typeof detail === "string") return detail;
  if (detail?.message) return detail.message;
  if (Array.isArray(detail) && detail[0]?.msg) return detail[0].msg;  // pydantic 422
  return fallback;
}

// ── Types ────────────────────────────────────────────────
export interface User {
  id: string;
  email: string;
  name?: string;
  notify_email: boolean;
  role: "user" | "admin";
  status: "pending" | "active" | "rejected" | "disabled";
}

/** 註冊回應：刻意沒有 access_token —— 帳號要等管理員核准才能用 */
export interface RegisterResponse {
  status: "pending_approval";
  message: string;
}

export interface AdminUser {
  id: string;
  email: string;
  name?: string;
  role: "user" | "admin";
  status: "pending" | "active" | "rejected" | "disabled";
  created_at?: string;
  approved_at?: string;
  last_login_at?: string;
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
    api.post<RegisterResponse>("/auth/register", data).then((r) => r.data),
  login: (data: { email: string; password: string }) =>
    api.post("/auth/login", data).then((r) => r.data),
  me: () => api.get<User>("/auth/me").then((r) => r.data),
};

export const adminApi = {
  listUsers: (status?: string) =>
    api.get<AdminUser[]>("/admin/users", { params: status ? { status } : {} })
       .then((r) => r.data),
  approve: (id: string) =>
    api.post<AdminUser>(`/admin/users/${id}/approve`).then((r) => r.data),
  reject: (id: string) =>
    api.post<AdminUser>(`/admin/users/${id}/reject`).then((r) => r.data),
  disable: (id: string) =>
    api.post<AdminUser>(`/admin/users/${id}/disable`).then((r) => r.data),
  enable: (id: string) =>
    api.post<AdminUser>(`/admin/users/${id}/enable`).then((r) => r.data),
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
