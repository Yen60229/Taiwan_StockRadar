import type { PbRating, ValuationFields } from "../api/client";

// 便宜綠、普通灰、昂貴橘。不用紅色：台股紅色代表上漲，容易看錯。
export const RATING_META: Record<PbRating, { label: string; color: string; bg: string; border: string }> = {
  cheap:     { label: "便宜", color: "#34d399", bg: "rgba(52,211,153,.12)",  border: "rgba(52,211,153,.40)" },
  fair:      { label: "普通", color: "#8ca8c8", bg: "rgba(140,168,200,.10)", border: "rgba(140,168,200,.30)" },
  expensive: { label: "昂貴", color: "#ffa94d", bg: "rgba(255,169,77,.12)",  border: "rgba(255,169,77,.40)" },
};

export const RATING_ORDER: PbRating[] = ["cheap", "fair", "expensive"];

export const num = (v: number | string | null | undefined): number | null =>
  v == null || v === "" ? null : Number(v);

export type RatingBasis = "industry" | "history";

/** 不評級的原因，給滑鼠提示用 */
function unratedReason(v: ValuationFields, basis: RatingBasis): string {
  if (!v.valuation_date) return "還沒有估值資料";
  if (v.pb_ratio == null) return "淨值為負或交易所未提供 PB";
  if (basis === "history") {
    return v.history_n ? `歷史只有 ${v.history_n} 個月，滿 36 個月才評級` : "還沒有歷史資料";
  }
  if ((v.industry_n ?? 0) < 10) return `同產業只有 ${v.industry_n ?? 0} 檔，樣本太少不評級`;
  return "不評級";
}

const pctText = (p: number | null) => (p != null ? `${Math.round(p * 100)}%` : "—");
const fix2 = (v: number | null | undefined) => (v == null ? "—" : Number(v).toFixed(2));

/** 評級的說明文字 */
export function ratingTitle(v: ValuationFields, basis: RatingBasis = "industry"): string {
  if (basis === "history") {
    if (!v.history_rating) return unratedReason(v, basis);
    return [
      `跟自己過去 ${v.history_n} 個月比，目前 PB 由低到高排在 ${pctText(num(v.history_pb_pct))} 的位置`,
      `歷史 PB：低檔 ${fix2(v.history_pb_p25)}／中位數 ${fix2(v.history_pb_p50)}／高檔 ${fix2(v.history_pb_p75)}`,
      "最低的 25% 為便宜、最高的 25% 為昂貴",
    ].join("\n");
  }
  if (!v.pb_rating) return unratedReason(v, basis);
  const median = num(v.industry_pb_median);
  return [
    `同產業 ${v.industry_n} 檔，PB 由低到高排在 ${pctText(num(v.industry_pb_pct))} 的位置`,
    median != null ? `產業中位數 ${median.toFixed(2)}` : "",
    "最低的 25% 為便宜、最高的 25% 為昂貴",
  ].filter(Boolean).join("\n");
}

export function RatingBadge({ v, size = "md", basis = "industry" }: {
  v: ValuationFields; size?: "md" | "lg"; basis?: RatingBasis;
}) {
  const big = size === "lg";
  const rating = basis === "history" ? v.history_rating : v.pb_rating;
  if (!rating) {
    return (
      <span title={unratedReason(v, basis)} style={{ fontSize: big ? 14 : 11.5, color: "#3d5a7a", cursor: "help" }}>
        {v.pb_ratio == null ? "—" : "不評級"}
      </span>
    );
  }
  const m = RATING_META[rating];
  return (
    <span title={ratingTitle(v, basis)} style={{
      display: "inline-block", padding: big ? "4px 12px" : "2px 9px", borderRadius: 6,
      background: m.bg, color: m.color, border: `1px solid ${m.border}`,
      fontSize: big ? 15 : 12.5, fontWeight: 700, letterSpacing: ".04em", cursor: "help",
    }}>
      {m.label}
    </span>
  );
}

/** 附加提醒：PB < 1「低於淨值」、有 PB 但本益比空白「虧損中」。不影響評級。 */
export function ValuationTags({ v }: { v: ValuationFields }) {
  const pb = num(v.pb_ratio);
  const tags: { text: string; title: string; color: string }[] = [];
  if (pb != null && pb < 1) {
    tags.push({ text: "低於淨值", title: "股價低於每股淨值（PB < 1）", color: "#5ab4ff" });
  }
  if (pb != null && v.pe_ratio == null) {
    tags.push({
      text: "虧損中",
      title: "近四季每股盈餘為 0 或負數，交易所不計算本益比。PB 低可能是因為公司不賺錢，留意價值陷阱。",
      color: "#ff8a8a",
    });
  }
  if (!tags.length) return null;
  return (
    <>
      {tags.map((t) => (
        <span key={t.text} title={t.title} style={{
          marginLeft: 5, padding: "1px 5px", borderRadius: 4, fontSize: 10, fontWeight: 700,
          color: t.color, border: `1px solid ${t.color}55`, whiteSpace: "nowrap", cursor: "help",
        }}>
          {t.text}
        </span>
      ))}
    </>
  );
}

/** 每股淨值的滑鼠提示 */
export function bvpsTitle(v: ValuationFields): string {
  return [
    v.fin_period ? `財報季別：${v.fin_period}` : "",
    v.valuation_date ? `資料日期：${v.valuation_date}` : "",
    "每股淨值依交易所公布的股價淨值比推算（收盤價 ÷ PB）",
  ].filter(Boolean).join("\n");
}
