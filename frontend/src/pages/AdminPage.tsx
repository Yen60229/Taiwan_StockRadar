import { useState } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { adminApi, errMessage, type AdminUser } from "../api/client";
import { useAuth } from "../store/auth";

type Tab = "pending" | "all";

const STATUS_LABEL: Record<AdminUser["status"], { text: string; color: string; bg: string }> = {
  pending:  { text: "待審核", color: "#ffcc00", bg: "rgba(255,204,0,.12)" },
  active:   { text: "使用中", color: "#00e49a", bg: "rgba(0,228,154,.12)" },
  rejected: { text: "已拒絕", color: "#ff6b8a", bg: "rgba(255,107,138,.12)" },
  disabled: { text: "已停用", color: "#8fa6bd", bg: "rgba(143,166,189,.12)" },
};

export default function AdminPage() {
  const nav = useNavigate();
  const qc = useQueryClient();
  const { user } = useAuth();
  const [searchParams] = useSearchParams();
  // 從核准通知信的連結來的：?user=<id>，把那一筆標示出來。
  // 純粹是「哪一筆」的提示，核准動作本身還是要手動按——
  // 連結本身不帶任何權限。
  const highlightId = searchParams.get("user");
  const [tab, setTab] = useState<Tab>(highlightId ? "all" : "pending");
  const [err, setErr] = useState("");

  const { data: users = [], isLoading } = useQuery({
    queryKey: ["admin-users", tab],
    queryFn: () => adminApi.listUsers(tab === "pending" ? "pending" : undefined),
  });

  const act = useMutation({
    mutationFn: ({ id, action }: { id: string; action: "approve" | "reject" | "disable" | "enable" }) =>
      adminApi[action](id),
    onSuccess: () => {
      setErr("");
      qc.invalidateQueries({ queryKey: ["admin-users"] });
    },
    onError: (e) => setErr(errMessage(e)),
  });

  const pendingCount = users.filter((u) => u.status === "pending").length;
  // 被連結進來的那筆排到最前面，不用在清單裡自己找
  const sortedUsers = highlightId
    ? [...users].sort((a, b) => (a.id === highlightId ? -1 : b.id === highlightId ? 1 : 0))
    : users;

  return (
    <div style={{ minHeight: "100vh", background: "#04080f" }}>
      <header style={{
        position: "sticky", top: 0, zIndex: 20,
        background: "rgba(4,8,15,.93)", backdropFilter: "blur(24px)",
        borderBottom: "1px solid rgba(0,150,255,.13)",
        padding: "0 28px", height: 60, display: "flex", alignItems: "center", gap: 16,
      }}>
        <button onClick={() => nav("/")} style={{ color: "var(--accent)", fontSize: 13, fontWeight: 600 }}>
          ← 回選股
        </button>
        <div style={{ fontSize: 15, fontWeight: 800 }}>帳號管理</div>
        <div style={{ flex: 1 }} />
        <div style={{ fontSize: 12, color: "#5a7ca8" }}>{user?.email}</div>
      </header>

      <div style={{ maxWidth: 1000, margin: "0 auto", padding: "24px 28px" }}>
        <div style={{ display: "flex", gap: 8, marginBottom: 18 }}>
          <TabButton active={tab === "pending"} onClick={() => setTab("pending")}>
            待審核{tab === "pending" && pendingCount > 0 ? ` (${pendingCount})` : ""}
          </TabButton>
          <TabButton active={tab === "all"} onClick={() => setTab("all")}>全部帳號</TabButton>
        </div>

        {err && (
          <div style={{
            marginBottom: 14, padding: "10px 14px", borderRadius: 8, fontSize: 13,
            background: "rgba(255,77,106,.1)", border: "1px solid rgba(255,77,106,.35)",
            color: "#ff8fa3",
          }}>⚠️ {err}</div>
        )}

        {isLoading ? (
          <Empty>載入中…</Empty>
        ) : users.length === 0 ? (
          <Empty>{tab === "pending" ? "目前沒有待審核的申請 🎉" : "還沒有任何帳號"}</Empty>
        ) : (
          <div style={{ display: "grid", gap: 10 }}>
            {sortedUsers.map((u) => (
              <UserRow
                key={u.id}
                u={u}
                isSelf={u.id === user?.id}
                highlighted={u.id === highlightId}
                busy={act.isPending}
                onAct={(action) => act.mutate({ id: u.id, action })}
              />
            ))}
          </div>
        )}
      </div>
    </div>
  );
}

function UserRow({ u, isSelf, highlighted, busy, onAct }: {
  u: AdminUser;
  isSelf: boolean;
  highlighted?: boolean;
  busy: boolean;
  onAct: (a: "approve" | "reject" | "disable" | "enable") => void;
}) {
  const s = STATUS_LABEL[u.status];
  return (
    <div style={{
      display: "flex", alignItems: "center", gap: 14, flexWrap: "wrap",
      padding: "14px 18px", borderRadius: 12,
      background: highlighted ? "rgba(0,210,255,.10)" : "rgba(0,130,255,.04)",
      border: `1px solid ${highlighted ? "rgba(0,210,255,.5)" : "rgba(0,150,255,.14)"}`,
      boxShadow: highlighted ? "0 0 0 1px rgba(0,210,255,.3)" : "none",
    }}>
      {highlighted && (
        <span style={{
          fontSize: 10.5, fontWeight: 700, padding: "2px 8px", borderRadius: 5,
          background: "rgba(0,210,255,.18)", color: "#00d8ff", whiteSpace: "nowrap",
        }}>來自通知信</span>
      )}
      <div style={{ flex: 1, minWidth: 220 }}>
        <div style={{ display: "flex", alignItems: "center", gap: 8, flexWrap: "wrap" }}>
          <span style={{ fontWeight: 700, fontSize: 14, color: "#ddeeff" }}>{u.email}</span>
          {u.role === "admin" && (
            <span style={{
              fontSize: 10.5, fontWeight: 700, padding: "2px 7px", borderRadius: 5,
              background: "rgba(0,210,255,.14)", color: "#00d8ff", letterSpacing: ".05em",
            }}>ADMIN</span>
          )}
          {isSelf && (
            <span style={{ fontSize: 11, color: "#5a7ca8" }}>（你自己）</span>
          )}
        </div>
        <div style={{ fontSize: 11.5, color: "#5a7ca8", marginTop: 4 }}>
          {u.name ? `${u.name} · ` : ""}
          申請於 {fmt(u.created_at)}
          {u.last_login_at ? ` · 最後登入 ${fmt(u.last_login_at)}` : " · 從未登入"}
        </div>
      </div>

      <span style={{
        fontSize: 11.5, fontWeight: 700, padding: "4px 10px", borderRadius: 6,
        background: s.bg, color: s.color, whiteSpace: "nowrap",
      }}>{s.text}</span>

      <div style={{ display: "flex", gap: 6 }}>
        {u.status === "pending" && (
          <>
            <Action kind="primary" disabled={busy} onClick={() => onAct("approve")}>核准</Action>
            <Action disabled={busy || isSelf} onClick={() => onAct("reject")}>拒絕</Action>
          </>
        )}
        {u.status === "active" && !isSelf && (
          <Action disabled={busy} onClick={() => onAct("disable")}>停用</Action>
        )}
        {(u.status === "disabled" || u.status === "rejected") && (
          <Action kind="primary" disabled={busy} onClick={() => onAct("enable")}>啟用</Action>
        )}
      </div>
    </div>
  );
}

function Action({ children, onClick, disabled, kind }: {
  children: React.ReactNode; onClick: () => void; disabled?: boolean; kind?: "primary";
}) {
  return (
    <button onClick={onClick} disabled={disabled} style={{
      padding: "6px 14px", borderRadius: 7, fontSize: 12.5, fontWeight: 700,
      cursor: disabled ? "not-allowed" : "pointer", opacity: disabled ? 0.4 : 1,
      background: kind === "primary" ? "linear-gradient(135deg,#00d2ff,#00a8d4)" : "transparent",
      color: kind === "primary" ? "#02121e" : "#8fa6bd",
      border: kind === "primary" ? "none" : "1px solid rgba(143,166,189,.3)",
    }}>{children}</button>
  );
}

function TabButton({ children, active, onClick }: {
  children: React.ReactNode; active: boolean; onClick: () => void;
}) {
  return (
    <button onClick={onClick} style={{
      padding: "8px 16px", borderRadius: 8, fontSize: 13, fontWeight: 700,
      background: active ? "rgba(0,210,255,.14)" : "transparent",
      color: active ? "#00d8ff" : "#5a7ca8",
      border: `1px solid ${active ? "rgba(0,210,255,.35)" : "rgba(0,150,255,.14)"}`,
    }}>{children}</button>
  );
}

function Empty({ children }: { children: React.ReactNode }) {
  return (
    <div style={{
      padding: "48px 20px", textAlign: "center", color: "#5a7ca8", fontSize: 14,
      border: "1px dashed rgba(0,150,255,.2)", borderRadius: 12,
    }}>{children}</div>
  );
}

function fmt(iso?: string): string {
  if (!iso) return "—";
  const d = new Date(iso);
  return Number.isNaN(d.getTime()) ? "—" : d.toLocaleString("zh-TW", { hour12: false });
}
