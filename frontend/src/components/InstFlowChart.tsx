import { useState } from "react";
import {
  Bar, BarChart, Cell, Legend, ReferenceLine,
  ResponsiveContainer, Tooltip, XAxis, YAxis,
} from "recharts";
import type { InstFlowPoint } from "../api/client";

// 買超紅、賣超綠（台股習慣，跟漲跌同一套顏色語言）
const BUY = "#ff4d6a";
const SELL = "#00c98a";

// recharts 預設進場動畫 1.5 秒，每按一次切換就要等圖長出來，體感很鈍。
// 切換是頻繁動作，縮短到 0.4 秒。
const ANIM_MS = 400;

type SeriesKey = "foreign_net" | "trust_net" | "dealer_net" | "total_net";
type View = SeriesKey | "all";

const SERIES: { key: SeriesKey; label: string; color: string }[] = [
  { key: "foreign_net", label: "外資", color: "#00d2ff" },
  { key: "trust_net",   label: "投信", color: "#a78bfa" },
  { key: "dealer_net",  label: "自營", color: "#ffb547" },
  { key: "total_net",   label: "合計", color: "#00e49a" },
];

const VIEWS: { value: View; label: string }[] = [
  ...SERIES.map((s) => ({ value: s.key as View, label: s.label })),
  { value: "all", label: "全部並列" },
];

function labelOf(key: SeriesKey): string {
  return SERIES.find((s) => s.key === key)?.label ?? key;
}

export default function InstFlowChart({ rows }: { rows: InstFlowPoint[] }) {
  const [view, setView] = useState<View>("foreign_net");
  const latest = rows.length ? rows[rows.length - 1].trade_date : "—";

  return (
    <>
      <div style={{ display: "flex", alignItems: "baseline", gap: 12,
                    marginTop: 28, marginBottom: 12, flexWrap: "wrap" }}>
        <h3 style={{ fontSize: 16, margin: 0 }}>📊 近 30 日法人買賣超（張）</h3>
        {/* 資料有沒有跟上，看這裡最快 */}
        <span style={{ fontSize: 12, color: "var(--text-dim)" }}>最新資料：{latest}</span>
      </div>

      <div style={{ display: "flex", gap: 6, marginBottom: 12, flexWrap: "wrap" }}>
        {VIEWS.map((v) => (
          <button
            key={v.value}
            onClick={() => setView(v.value)}
            style={{
              padding: "6px 14px", borderRadius: 7, fontSize: 12.5, fontWeight: 700,
              cursor: "pointer",
              background: view === v.value ? "rgba(0,210,255,.14)" : "transparent",
              color: view === v.value ? "#00d8ff" : "var(--text-mute)",
              border: `1px solid ${view === v.value ? "rgba(0,210,255,.35)" : "var(--line)"}`,
            }}
          >
            {v.label}
          </button>
        ))}
      </div>

      <div style={{ background: "var(--bg-elev)", padding: 16, borderRadius: 12, height: 320 }}>
        {rows.length === 0 ? (
          <div style={{ display: "grid", placeItems: "center", height: "100%", color: "var(--text-mute)" }}>
            無近期法人資料
          </div>
        ) : (
          <ResponsiveContainer width="100%" height="100%">
            <BarChart data={rows}>
              <XAxis dataKey="trade_date" stroke="#5e7a96" tick={{ fontSize: 11 }}
                     tickFormatter={(d: string) => d.slice(5)} />
              <YAxis stroke="#5e7a96" tick={{ fontSize: 11 }} />
              <Tooltip
                contentStyle={{ background: "#0a1628", border: "1px solid var(--line)", borderRadius: 8 }}
                formatter={(v: number, name: string) => [`${Number(v).toLocaleString()} 張`, name]}
              />
              <ReferenceLine y={0} stroke="#5e7a96" strokeDasharray="2 2" />
              {/* 不要用 <>…</> 包這些：recharts 靠掃 children 的型別認元件，
                  包進 Fragment 會讓它認不到 Bar/Legend，圖就整個不畫。 */}
              {view === "all" && <Legend />}
              {view === "all"
                ? SERIES.map((s) => (
                    <Bar key={s.key} dataKey={s.key} name={s.label}
                         fill={s.color} animationDuration={ANIM_MS} />
                  ))
                : (
                  // 單一法人：不用固定色，改用買超紅／賣超綠，一眼看出方向
                  <Bar dataKey={view} name={labelOf(view)} animationDuration={ANIM_MS}>
                    {rows.map((row, i) => (
                      <Cell key={i} fill={(row[view] ?? 0) >= 0 ? BUY : SELL} />
                    ))}
                  </Bar>
                )}
            </BarChart>
          </ResponsiveContainer>
        )}
      </div>

      {view !== "all" && (
        <div style={{ marginTop: 8, fontSize: 11.5, color: "var(--text-dim)", display: "flex", gap: 14 }}>
          <span><span style={{ color: BUY }}>■</span> 買超</span>
          <span><span style={{ color: SELL }}>■</span> 賣超</span>
        </div>
      )}
    </>
  );
}
