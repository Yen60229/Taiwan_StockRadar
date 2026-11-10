import { useMemo } from "react";
import { useQuery } from "@tanstack/react-query";
import {
  CartesianGrid, Line, LineChart, ReferenceLine, ResponsiveContainer, Tooltip, XAxis, YAxis,
} from "recharts";
import { valuationApi, type StockDetail } from "../api/client";
import { RATING_META, RatingBadge, num } from "./PbRating";

/**
 * 個股頁：過去 5 年 PB 走勢（每月一點）＋ 自己歷史的低檔／中位數／高檔參考線，
 * 以及換算成股價的參考價位（每股淨值 × 歷史 PB）。
 */
export default function PbHistoryChart({ detail }: { detail: StockDetail }) {
  const { data, isLoading } = useQuery({
    queryKey: ["pb-history", detail.code],
    queryFn: () => valuationApi.history(detail.code),
  });

  // 用時間戳當橫軸，缺幾個月的資料時，間距仍然照實際時間排，不會被壓縮
  const points = useMemo(
    () => (data?.points ?? []).map((p) => ({ t: Date.parse(p.date), date: p.date, pb: p.pb })),
    [data],
  );
  const enoughHistory = (detail.history_n ?? 0) >= 36;
  const close = num(detail.latest_close);

  return (
    <section style={{ marginTop: 28 }}>
      <div style={{ display: "flex", alignItems: "baseline", gap: 12, marginBottom: 12, flexWrap: "wrap" }}>
        <h3 style={{ fontSize: 16, margin: 0 }}>📈 股價淨值比・跟自己的歷史比</h3>
        <span style={{ fontSize: 12, color: "var(--text-dim)" }}>
          {detail.history_n
            ? `過去 ${detail.history_n} 個月（${detail.history_since?.slice(0, 7)} 起，每月一點）`
            : "還沒有歷史資料"}
        </span>
        <span style={{ marginLeft: "auto" }}><RatingBadge v={detail} basis="history" /></span>
      </div>

      {/* 參考價位：歷史滿 36 個月才提供，跟評級同一個門檻 */}
      {!enoughHistory && detail.history_n ? (
        <Note>歷史只有 {detail.history_n} 個月，滿 36 個月才提供評級與參考價位。</Note>
      ) : null}
      <div style={{ display: "grid", gridTemplateColumns: "repeat(4,1fr)", gap: 12, marginBottom: 16 }}>
        <PriceCard label="便宜價" hint="淨值 × 歷史 PB 低檔（第 25 百分位）" value={num(detail.price_cheap)} color={RATING_META.cheap.color} />
        <PriceCard label="合理價" hint="淨值 × 歷史 PB 中位數" value={num(detail.price_fair)} color={RATING_META.fair.color} />
        <PriceCard label="昂貴價" hint="淨值 × 歷史 PB 高檔（第 75 百分位）" value={num(detail.price_expensive)} color={RATING_META.expensive.color} />
        <PriceCard label="目前收盤" hint="" value={close} color="var(--text)" />
      </div>

      {isLoading ? (
        <Note>載入中…</Note>
      ) : points.length < 2 ? (
        <Note>歷史資料不足，無法畫出走勢。上線後要先執行一次歷史回補（scripts/backfill_valuation.py）。</Note>
      ) : (
        <div style={{ height: 280, background: "var(--bg-elev)", borderRadius: 12, padding: "16px 8px 8px" }}>
          <ResponsiveContainer width="100%" height="100%">
            <LineChart data={points} margin={{ top: 8, right: 16, bottom: 0, left: 0 }}>
              <CartesianGrid stroke="rgba(255,255,255,.05)" vertical={false} />
              <XAxis dataKey="t" type="number" scale="time" domain={["dataMin", "dataMax"]}
                     tickFormatter={(t: number) => new Date(t).toISOString().slice(0, 7)} minTickGap={40}
                     tick={{ fill: "#5a7ca8", fontSize: 11 }} stroke="#1a2d44" />
              <YAxis width={44} tick={{ fill: "#5a7ca8", fontSize: 11 }} stroke="#1a2d44"
                     domain={["auto", "auto"]} tickFormatter={(v: number) => v.toFixed(1)} />
              <Tooltip
                contentStyle={{ background: "#0f1e35", border: "1px solid rgba(0,150,255,.3)", borderRadius: 8 }}
                labelFormatter={(t: number) => new Date(t).toISOString().slice(0, 10)}
                formatter={(v: number) => [v.toFixed(2), "PB"]}
              />
              {refLine(data?.p25, "低檔", RATING_META.cheap.color)}
              {refLine(data?.p50, "中位數", RATING_META.fair.color)}
              {refLine(data?.p75, "高檔", RATING_META.expensive.color)}
              <Line type="monotone" dataKey="pb" stroke="#00d2ff" strokeWidth={2}
                    dot={false} activeDot={{ r: 4 }} isAnimationActive={false} />
            </LineChart>
          </ResponsiveContainer>
        </div>
      )}

      {points.length >= 2 && (
        <div style={{ display: "flex", gap: 18, flexWrap: "wrap", marginTop: 8, fontSize: 12 }}>
          <Legend color="#00d2ff" solid text="每月 PB" />
          <Legend color={RATING_META.cheap.color}     text={`低檔（第 25 百分位）${fmt(data?.p25)}`} />
          <Legend color={RATING_META.fair.color}      text={`中位數 ${fmt(data?.p50)}`} />
          <Legend color={RATING_META.expensive.color} text={`高檔（第 75 百分位）${fmt(data?.p75)}`} />
        </div>
      )}

      <Note>
        PB 落在自己歷史的低檔，代表市場現在給的價格比過去便宜，但不代表公司沒有變差。
        參考價位用的是目前的每股淨值，淨值變動後價位也會跟著變。
      </Note>
    </section>
  );
}

// 用一般函式而不是元件：recharts 只認得直接放在圖表裡的 ReferenceLine，
// 包成 <RefLine /> 元件會被忽略、線畫不出來。
// 數值不標在線上：三條線常常很接近，文字會疊在一起，改放在圖下方的圖例。
function refLine(y: number | null | undefined, label: string, color: string) {
  if (y == null) return null;
  return (
    <ReferenceLine key={label} y={y} ifOverflow="extendDomain" stroke={color} strokeDasharray="4 4"
                   strokeOpacity={0.85} />
  );
}

const fmt = (v: number | null | undefined) => (v == null ? "—" : v.toFixed(2));

function Legend({ color, text, solid }: { color: string; text: string; solid?: boolean }) {
  return (
    <span style={{ display: "inline-flex", alignItems: "center", gap: 6, color: "var(--text-mute)" }}>
      <span style={{ width: 18, borderTop: `2px ${solid ? "solid" : "dashed"} ${color}` }} />
      {text}
    </span>
  );
}

function PriceCard({ label, hint, value, color }: { label: string; hint: string; value: number | null; color: string }) {
  return (
    <div title={hint || undefined} style={{ background: "var(--bg-elev)", padding: "12px 16px", borderRadius: 10, cursor: hint ? "help" : undefined }}>
      <div style={{ fontSize: 11, color: "var(--text-dim)" }}>{label}</div>
      <div className="mono" style={{ fontSize: 20, fontWeight: 700, color, marginTop: 4 }}>
        {value != null ? value.toFixed(2) : "—"}
      </div>
    </div>
  );
}

function Note({ children }: { children: React.ReactNode }) {
  return <p style={{ fontSize: 12, color: "var(--text-dim)", lineHeight: 1.7, margin: "10px 0" }}>{children}</p>;
}
