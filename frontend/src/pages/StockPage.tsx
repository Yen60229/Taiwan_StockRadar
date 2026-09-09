import { useNavigate, useParams } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { stockApi } from "../api/client";
import InstFlowChart from "../components/InstFlowChart";

export default function StockPage() {
  const { code } = useParams();
  const nav = useNavigate();
  const { data, isLoading } = useQuery({
    queryKey: ["stock", code],
    queryFn: () => stockApi.detail(code!),
    enabled: !!code,
  });

  if (isLoading) return <Center>📡 載入中…</Center>;
  if (!data) return <Center>找不到 {code}</Center>;

  return (
    <div style={{ padding: 28 }}>
      <button onClick={() => nav(-1)} style={{ marginBottom: 20, color: "var(--accent)" }}>← 返回</button>

      <div style={{ background: "var(--bg-card)", padding: 28, borderRadius: 16, border: "1px solid var(--line)" }}>
        <div style={{ display: "flex", alignItems: "baseline", gap: 12 }}>
          <h1 className="mono" style={{ fontSize: 28, color: "var(--accent)", margin: 0 }}>{data.code}</h1>
          <h2 style={{ margin: 0, fontSize: 22 }}>{data.name}</h2>
          <span style={{ padding: "3px 8px", background: "var(--bg-elev)", borderRadius: 6, fontSize: 12, color: "var(--text-mute)" }}>
            {data.market} · {data.industry || "其他"}
          </span>
        </div>

        <div style={{ display: "grid", gridTemplateColumns: "repeat(3,1fr)", gap: 20, margin: "24px 0" }}>
          <Stat label="收盤價"     value={data.latest_close ? Number(data.latest_close).toFixed(2) : "—"} />
          <Stat label="20日均量"   value={data.avg_vol_20d ? `${Number(data.avg_vol_20d).toLocaleString()} 張` : "—"} />
          <Stat label="籌碼集中度" value={data.conc_ratio != null ? `${Number(data.conc_ratio).toFixed(2)}%` : "—"} accent />
        </div>

        <InstFlowChart rows={data.inst_flow_30d} />
      </div>
    </div>
  );
}

function Stat({ label, value, accent }: { label: string; value: string; accent?: boolean }) {
  return (
    <div style={{ background: "var(--bg-elev)", padding: 20, borderRadius: 12 }}>
      <div style={{ fontSize: 11, letterSpacing: ".1em", color: "var(--text-dim)", textTransform: "uppercase" }}>{label}</div>
      <div className="mono" style={{ marginTop: 6, fontSize: 26, fontWeight: 700, color: accent ? "var(--neutral)" : "var(--text)" }}>{value}</div>
    </div>
  );
}

function Center({ children }: { children: React.ReactNode }) {
  return <div style={{ display: "grid", placeItems: "center", height: "60vh", color: "var(--text-mute)" }}>{children}</div>;
}
