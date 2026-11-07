import { useEffect, useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import {
  Bar, BarChart, Cell, ReferenceLine, ResponsiveContainer, Tooltip, XAxis, YAxis,
} from "recharts";
import { valuationApi, type IndustryValuationItem } from "../api/client";
import { RATING_META, RatingBadge, ValuationTags, bvpsTitle, num } from "./PbRating";

type Scope = "all" | "screened";

const ROW_H = 22;          // 橫條圖每一檔的高度
const UNRATED = "#3d5a7a";

/**
 * 同產業股價淨值比比較。
 * 「全市場同產業」由後端回傳；「只看篩選結果」直接用篩選結果的代號在前端過濾，不再打 API。
 */
export default function IndustryValuationPanel({
  industry, highlight, screenedCodes, onClose, onOpenStock,
}: {
  industry: string;
  highlight?: string;
  screenedCodes: Set<string>;
  onClose: () => void;
  onOpenStock: (code: string) => void;
}) {
  const [scope, setScope] = useState<Scope>("all");
  const { data, isLoading, isError } = useQuery({
    queryKey: ["valuation-industry", industry],
    queryFn: () => valuationApi.industry(industry),
  });

  // Esc 關閉
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => { if (e.key === "Escape") onClose(); };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  const rows = useMemo(() => {
    const all = data?.items ?? [];
    return scope === "all" ? all : all.filter((r) => screenedCodes.has(r.code));
  }, [data, scope, screenedCodes]);

  // 名次只算有 PB 的，與後端的產業排名一致（後端已依 PB 由低到高排序）
  const rankOf = useMemo(() => {
    const m = new Map<string, number>();
    (data?.items ?? []).filter((r) => r.pb_ratio != null).forEach((r, i) => m.set(r.code, i + 1));
    return m;
  }, [data]);

  const chartRows = useMemo(
    () => rows.filter((r) => r.pb_ratio != null).map((r) => ({
      code: r.code,
      label: `${r.code} ${r.short_name || r.name}`,
      pb: num(r.pb_ratio)!,
      rating: r.pb_rating,
    })),
    [rows],
  );

  const median = num(data?.median);

  return (
    <>
      <div onClick={onClose} style={{ position: "fixed", inset: 0, background: "rgba(0,0,0,.55)", zIndex: 40 }} />
      <aside style={{
        position: "fixed", top: 0, right: 0, bottom: 0, zIndex: 50,
        width: "min(680px, 100vw)", overflowY: "auto",
        background: "#07101e", borderLeft: "1px solid rgba(0,150,255,.2)",
        boxShadow: "-12px 0 40px rgba(0,0,0,.6)", padding: "20px 22px 28px",
      }}>
        {/* 標題 */}
        <div style={{ display: "flex", alignItems: "center", gap: 10, marginBottom: 14 }}>
          <h2 style={{ margin: 0, fontSize: 18 }}>{industry}・股價淨值比</h2>
          <button onClick={onClose} title="關閉（Esc）"
                  style={{ marginLeft: "auto", fontSize: 20, color: "#5a7ca8", padding: "2px 8px" }}>✕</button>
        </div>

        {/* 產業統計 */}
        <div style={{ display: "grid", gridTemplateColumns: "repeat(4,1fr)", gap: 10, marginBottom: 14 }}>
          <Stat label="檔數" value={data ? String(data.n) : "—"} />
          <Stat label="中位數" value={median != null ? median.toFixed(2) : "—"} />
          <Stat label="最低" value={data?.min != null ? Number(data.min).toFixed(2) : "—"} />
          <Stat label="最高" value={data?.max != null ? Number(data.max).toFixed(2) : "—"} />
        </div>
        {data && data.n > 0 && data.n < 10 && (
          <Note>同產業只有 {data.n} 檔，樣本太少，不給評級。</Note>
        )}

        {/* 範圍切換 */}
        <div style={{ display: "flex", borderRadius: 8, overflow: "hidden", border: "1px solid rgba(0,150,255,.22)",
                      width: "fit-content", marginBottom: 14 }}>
          {([["all", "全市場同產業"], ["screened", "只看篩選結果"]] as [Scope, string][]).map(([k, label]) => (
            <button key={k} onClick={() => setScope(k)} style={{
              padding: "6px 14px", fontSize: 12.5, fontWeight: 700,
              background: scope === k ? "rgba(0,120,255,.2)" : "rgba(0,0,0,.25)",
              color: scope === k ? "var(--accent)" : "#3d5a7a",
            }}>{label}</button>
          ))}
        </div>

        {isLoading && <Note>載入中…</Note>}
        {isError && <Note>讀取失敗，請稍後再試。</Note>}
        {!isLoading && !isError && rows.length === 0 && <Note>沒有資料。</Note>}

        {/* 橫條圖：PB 由低到高，虛線為產業中位數 */}
        {chartRows.length > 0 && (
          <div style={{ height: Math.max(160, chartRows.length * ROW_H + 60), marginBottom: 18 }}>
            <ResponsiveContainer width="100%" height="100%">
              <BarChart data={chartRows} layout="vertical" margin={{ top: 22, right: 36, bottom: 4, left: 4 }}>
                <XAxis type="number" tick={{ fill: "#5a7ca8", fontSize: 11 }} stroke="#1a2d44" />
                <YAxis type="category" dataKey="label" width={118} interval={0}
                       tick={{ fill: "#8ca8c8", fontSize: 11 }} stroke="#1a2d44" />
                <Tooltip
                  cursor={{ fill: "rgba(0,130,255,.08)" }}
                  contentStyle={{ background: "#0f1e35", border: "1px solid rgba(0,150,255,.3)", borderRadius: 8 }}
                  formatter={(v: number) => [v.toFixed(2), "PB"]}
                />
                {median != null && (
                  <ReferenceLine x={median} ifOverflow="extendDomain" stroke="#00d8ff" strokeDasharray="4 4"
                                 label={{ value: `中位數 ${median.toFixed(2)}`, fill: "#00d8ff", fontSize: 11, position: "top" }} />
                )}
                <Bar dataKey="pb" isAnimationActive={false} onClick={(d: { code: string }) => onOpenStock(d.code)}>
                  {chartRows.map((r) => (
                    <Cell key={r.code} cursor="pointer"
                          fill={r.rating ? RATING_META[r.rating].color : UNRATED}
                          fillOpacity={!highlight || r.code === highlight ? 0.95 : 0.45}
                          stroke={r.code === highlight ? "#ffffff" : undefined} strokeWidth={1.5} />
                  ))}
                </Bar>
              </BarChart>
            </ResponsiveContainer>
          </div>
        )}

        {/* 明細表 */}
        {rows.length > 0 && (
          <table style={{ fontSize: 12.5 }}>
            <thead>
              <tr style={{ color: "#5a8ab8", textAlign: "right" }}>
                <Th align="left">代號</Th><Th align="left">名稱</Th><Th>收盤</Th><Th>每股淨值</Th>
                <Th>PB</Th><Th>本益比</Th><Th>名次</Th><Th align="center">評級</Th>
              </tr>
            </thead>
            <tbody>
              {rows.map((r) => <Row key={r.code} r={r} rank={rankOf.get(r.code)} n={data?.n ?? 0}
                                    active={r.code === highlight} onClick={() => onOpenStock(r.code)} />)}
            </tbody>
          </table>
        )}

        <Note>
          PB 低不代表該買。常見原因是公司本身不太賺錢，請一併查看獲利與現金流。
          各產業的 PB 水準本來就不同，只適合跟同產業比較。
        </Note>
      </aside>
    </>
  );
}

function Row({ r, rank, n, active, onClick }: {
  r: IndustryValuationItem; rank?: number; n: number; active: boolean; onClick: () => void;
}) {
  const fmt = (v: number | null, d = 2) => (v == null ? "—" : v.toFixed(d));
  return (
    <tr onClick={onClick} style={{
      cursor: "pointer", borderBottom: "1px solid rgba(0,80,160,.12)", textAlign: "right",
      background: active ? "rgba(0,210,255,.10)" : undefined,
    }}>
      <Td align="left"><span className="mono" style={{ color: "#00d8ff", fontWeight: 700 }}>{r.code}</span></Td>
      <Td align="left">
        {r.short_name || r.name}
        <span style={{ marginLeft: 4, fontSize: 10, color: "#4a6a88" }}>{r.market === "TWSE" ? "上市" : "上櫃"}</span>
      </Td>
      <Td><span className="mono">{fmt(num(r.close))}</span></Td>
      <Td><span className="mono" title={bvpsTitle(r)}>{fmt(num(r.bvps))}</span></Td>
      <Td><span className="mono" style={{ fontWeight: 700 }}>{fmt(num(r.pb_ratio))}</span></Td>
      <Td><span className="mono">{fmt(num(r.pe_ratio))}</span></Td>
      <Td><span className="mono" style={{ color: "#5a7ca8" }}>{rank ? `${rank}/${n}` : "—"}</span></Td>
      <Td align="center"><RatingBadge v={r} /><ValuationTags v={r} /></Td>
    </tr>
  );
}

function Stat({ label, value }: { label: string; value: string }) {
  return (
    <div style={{ background: "rgba(0,40,90,.25)", borderRadius: 8, padding: "8px 10px" }}>
      <div style={{ fontSize: 10.5, color: "#3d5a7a", fontWeight: 600 }}>{label}</div>
      <div className="mono" style={{ fontSize: 17, fontWeight: 800, color: "#b8ccec", marginTop: 2 }}>{value}</div>
    </div>
  );
}

function Note({ children }: { children: React.ReactNode }) {
  return <p style={{ fontSize: 12, color: "#5a7ca8", lineHeight: 1.7, margin: "10px 0" }}>{children}</p>;
}

function Th({ children, align = "right" }: { children: React.ReactNode; align?: "left" | "right" | "center" }) {
  return <th style={{ padding: "6px 8px", fontWeight: 700, fontSize: 11, textAlign: align, whiteSpace: "nowrap" }}>{children}</th>;
}

function Td({ children, align = "right" }: { children: React.ReactNode; align?: "left" | "right" | "center" }) {
  return <td style={{ padding: "6px 8px", textAlign: align, whiteSpace: "nowrap" }}>{children}</td>;
}
