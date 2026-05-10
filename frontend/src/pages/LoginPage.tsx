import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { authApi } from "../api/client";
import { useAuth } from "../store/auth";

export default function LoginPage() {
  const nav = useNavigate();
  const setAuth = useAuth((s) => s.setAuth);
  const [mode, setMode] = useState<"login" | "register">("login");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [name, setName] = useState("");
  const [err, setErr] = useState("");
  const [loading, setLoading] = useState(false);

  async function onSubmit(e: React.FormEvent) {
    e.preventDefault();
    setErr(""); setLoading(true);
    try {
      const fn = mode === "login" ? authApi.login : authApi.register;
      const data = await fn({ email, password, ...(mode === "register" && { name }) });
      setAuth(data.user, data.access_token);
      nav("/");
    } catch (e: any) {
      setErr(e.response?.data?.detail || "請檢查輸入內容");
    } finally { setLoading(false); }
  }

  return (
    <div style={{
      minHeight: "100vh", display: "grid", placeItems: "center",
      padding: 24,
    }}>
      <div style={{
        width: "100%", maxWidth: 420,
        background: "var(--bg-card)", borderRadius: 16,
        padding: 36, boxShadow: "var(--shadow-md)",
        border: "1px solid var(--line)",
      }}>
        <div style={{ display: "flex", alignItems: "center", gap: 10, marginBottom: 6 }}>
          <div style={{ width: 36, height: 36, borderRadius: 10, background: "linear-gradient(135deg,#00d2ff,#0080a0)", display: "grid", placeItems: "center", fontSize: 20 }}>📡</div>
          <div>
            <div style={{ fontSize: 18, fontWeight: 700, letterSpacing: ".02em" }}>StockRadar</div>
            <div style={{ fontSize: 11, color: "var(--text-dim)", letterSpacing: ".1em" }}>選股雷達 / TW</div>
          </div>
        </div>

        <h1 style={{ fontSize: 22, margin: "20px 0 24px" }}>
          {mode === "login" ? "登入帳號" : "註冊新帳號"}
        </h1>

        <form onSubmit={onSubmit} style={{ display: "grid", gap: 14 }}>
          {mode === "register" && (
            <Field label="姓名" value={name} onChange={setName} placeholder="可選填" />
          )}
          <Field label="Email" type="email" value={email} onChange={setEmail} placeholder="you@example.com" required />
          <Field label="密碼" type="password" value={password} onChange={setPassword} placeholder="至少 6 字元" required />
          {err && <div style={{ color: "var(--sell)", fontSize: 13 }}>⚠️ {err}</div>}
          <button type="submit" disabled={loading} style={{
            marginTop: 8, padding: "12px 20px",
            background: "linear-gradient(135deg,#00d2ff,#00a8d4)",
            color: "#02121e", borderRadius: 10, fontWeight: 700,
            opacity: loading ? .6 : 1,
          }}>
            {loading ? "處理中…" : mode === "login" ? "登入" : "建立帳號"}
          </button>
        </form>

        <div style={{ textAlign: "center", marginTop: 20, fontSize: 13, color: "var(--text-mute)" }}>
          {mode === "login" ? "還沒有帳號？" : "已有帳號？"}
          <button onClick={() => setMode(mode === "login" ? "register" : "login")}
                  style={{ color: "var(--accent)", marginLeft: 6, fontWeight: 600 }}>
            {mode === "login" ? "註冊" : "登入"}
          </button>
        </div>
      </div>
    </div>
  );
}

function Field({ label, value, onChange, type = "text", placeholder, required }: {
  label: string; value: string; onChange: (v: string) => void;
  type?: string; placeholder?: string; required?: boolean;
}) {
  return (
    <label style={{ display: "block" }}>
      <div style={{ fontSize: 12, color: "var(--text-mute)", marginBottom: 6, letterSpacing: ".06em" }}>{label}</div>
      <input type={type} value={value} required={required}
             onChange={(e) => onChange(e.target.value)} placeholder={placeholder}
             style={{
               width: "100%", padding: "11px 14px",
               background: "var(--bg-elev)", border: "1px solid var(--line)",
               borderRadius: 8, color: "var(--text)", outline: "none",
             }} />
    </label>
  );
}
