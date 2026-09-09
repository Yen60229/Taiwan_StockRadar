import React from "react";
import ReactDOM from "react-dom/client";
import { BrowserRouter, Routes, Route, Navigate, useLocation } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import "./index.css";

import LoginPage     from "./pages/LoginPage";
import DashboardPage from "./pages/DashboardPage";
import StockPage     from "./pages/StockPage";
import AdminPage     from "./pages/AdminPage";
import { useAuth } from "./store/auth";

const queryClient = new QueryClient({
  defaultOptions: { queries: { staleTime: 60_000, retry: 1 } },
});

/**
 * 未登入就導去登入頁，並把「本來想去哪」記在 location state 裡，
 * 登入成功後再送回去。信件裡的 /admin?user=xxx 連結就是靠這個
 * 才不會在登入之後掉到首頁、把連結的用意弄丟。
 */
function PrivateRoute({ children }: { children: React.ReactNode }) {
  const token = useAuth((s) => s.token);
  const location = useLocation();
  if (token) return <>{children}</>;
  return <Navigate to="/login" replace state={{ from: location }} />;
}

/**
 * 管理頁專用。這只是「不要顯示不能用的畫面」的體驗處理——
 * 真正的權限把關在後端（api/deps.py 的 require_admin），
 * 因為前端這段程式碼任何人都能改。
 */
function AdminRoute({ children }: { children: React.ReactNode }) {
  const token = useAuth((s) => s.token);
  const user  = useAuth((s) => s.user);
  const location = useLocation();
  if (!token) return <Navigate to="/login" replace state={{ from: location }} />;
  return user?.role === "admin" ? <>{children}</> : <Navigate to="/" replace />;
}

ReactDOM.createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <QueryClientProvider client={queryClient}>
      <BrowserRouter>
        <Routes>
          <Route path="/login" element={<LoginPage />} />
          <Route path="/" element={<PrivateRoute><DashboardPage /></PrivateRoute>} />
          <Route path="/stock/:code" element={<PrivateRoute><StockPage /></PrivateRoute>} />
          <Route path="/admin" element={<AdminRoute><AdminPage /></AdminRoute>} />
          <Route path="*" element={<Navigate to="/" />} />
        </Routes>
      </BrowserRouter>
    </QueryClientProvider>
  </React.StrictMode>
);
