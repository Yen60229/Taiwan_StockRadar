import { useRef, useState, useCallback, useMemo } from "react";
import { useNavigate } from "react-router-dom";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { screenApi, watchlistApi, type ScreenItem } from "../api/client";
import { useAuth } from "../store/auth";

// ── TWSE 產業代碼 → 中文 ─────────────────────────────────────
const INDUSTRY_MAP: Record<string, string> = {
  "01":"水泥","02":"食品","03":"塑膠","04":"紡纖","05":"電機","06":"電纜",
  "07":"化學","08":"玻璃","09":"造紙","10":"鋼鐵","11":"橡膠","12":"汽車",
  "13":"建材","14":"航運","15":"觀光","16":"金融","17":"貿易","18":"綜合",
  "20":"其他","21":"化學","22":"生技","23":"油電","24":"半導體","25":"電腦周邊",
  "26":"光電","27":"通信","28":"電子零組件","29":"電子通路","30":"資訊服務",
  "31":"其他電子","32":"文創","33":"農科","34":"電商","35":"建設",
  "36":"運動休閒","37":"觀光餐旅","38":"居家",
};
const industryLabel = (v?: string) =>
  !v ? "—" : (INDUSTRY_MAP[v.trim().padStart(2,"0")] ?? v);

export default function DashboardPage() {
  const nav = useNavigate();
  const qc  = useQueryClient();
  const { user, logout } = useAuth();

  const [minAvgVol, setMinAvgVol] = useState(2000);
  const [minConc,   setMinConc]   = useState(40);
  const [onlyBuy,   setOnlyBuy]   = useState(false);
  const [search,    setSearch]    = useState("");
  const [market,    setMarket]    = useState<"ALL" | "TWSE" | "TPEX">("ALL");
  const [sort, setSort] = useState<{ key: string; dir: "asc" | "desc" }>({ key: "conc_ratio", dir: "desc" });

  const handleSort = useCallback((key: string) => {
    setSort(prev => prev.key === key ? { key, dir: prev.dir === "desc" ? "asc" : "desc" } : { key, dir: "desc" });
  }, []);

  const { data: screen, isLoading } = useQuery({
    queryKey: ["screen", minAvgVol, minConc, onlyBuy],
    queryFn: () => screenApi.list({
      min_avg_vol:   minAvgVol,
      min_conc:      minConc,
      only_inst_buy: onlyBuy,
    }),
  });

  const addWl = useMutation({
    mutationFn: (code: string) => watchlistApi.add(code),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["screen"] }),
  });
  const rmWl = useMutation({
    mutationFn: (code: string) => watchlistApi.remove(code),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["screen"] }),
  });

  const items = useMemo(() => {
    const getSortVal = (s: ScreenItem): number | null => {
      if (sort.key === "big_chip") {
        const c = s.conc_ratio != null ? Number(s.conc_ratio) : null;
        const f = s.foreign_hold_ratio != null ? Number(s.foreign_hold_ratio) : null;
        return c != null && f != null ? c - f : null;
      }
      const v = s[sort.key as keyof ScreenItem];
      return v != null ? Number(v) : null;
    };

    const filtered = (screen?.items || []).filter(s => {
      if (search && !s.code.includes(search) && !(s.short_name || s.name).includes(search)) return false;
      if (market !== "ALL" && s.market !== market) return false;
      return true;
    });

    return [...filtered].sort((a, b) => {
      if (sort.key === "code") {
        return sort.dir === "asc"
          ? a.code.localeCompare(b.code)
          : b.code.localeCompare(a.code);
      }
      const av = getSortVal(a), bv = getSortVal(b);
      if (av == null && bv == null) return 0;
      if (av == null) return 1;
      if (bv == null) return -1;
      return sort.dir === "asc" ? av - bv : bv - av;
    });
  }, [screen?.items, search, market, sort]);

  const exportCSV = () => {
    const header = ["代號","名稱","市場","產業","收盤","均量(張)","籌碼集中度%","外資持股%","大戶籌碼%","董監持股%","外資買賣超(張)","投信買賣超(張)"];
    const rows = items.map(s => {
      const forHold = s.foreign_hold_ratio != null ? Number(s.foreign_hold_ratio) : null;
      const conc    = s.conc_ratio != null ? Number(s.conc_ratio) : null;
      const bigChip = conc != null && forHold != null ? Math.max(0, Number((conc - forHold).toFixed(2))) : "";
      return [
        s.code, s.short_name || s.name, s.market === "TWSE" ? "上市" : "上櫃",
        industryLabel(s.industry), s.close ?? "", s.avg_vol_20d != null ? Math.round(Number(s.avg_vol_20d)) : "",
        conc    != null ? conc.toFixed(2)    : "",
        forHold != null ? forHold.toFixed(2) : "",
        bigChip,
        s.director_hold_ratio != null ? Number(s.director_hold_ratio).toFixed(2) : "",
        s.foreign_net != null ? Math.round(Number(s.foreign_net)) : "",
        s.trust_net   != null ? Math.round(Number(s.trust_net))   : "",
      ];
    });
    const csv = "﻿" + [header, ...rows].map(r => r.join(",")).join("\n");
    const a = Object.assign(document.createElement("a"), {
      href: URL.createObjectURL(new Blob([csv], { type: "text/csv;charset=utf-8" })),
      download: `stockradar_${new Date().toISOString().slice(0,10)}.csv`,
    });
    a.click();
  };

  return (
    <div style={{ minHeight:"100vh", background:"#04080f" }}>

      {/* ── Header ─────────────────────────────────────────── */}
      <header style={{
        position:"sticky", top:0, zIndex:20,
        backdropFilter:"blur(24px) saturate(180%)",
        background:"rgba(4,8,15,.93)",
        borderBottom:"1px solid rgba(0,150,255,.13)",
        borderTop:"3px solid transparent",
        borderImage:"linear-gradient(90deg,#0044aa 0%,#00aaff 40%,#00d8ff 70%,#0044aa 100%) 1",
        padding:"0 28px", height:60,
        display:"flex", alignItems:"center", gap:20,
      }}>
        {/* Logo */}
        <div style={{ display:"flex", alignItems:"center", gap:10, flexShrink:0 }}>
          <div style={{
            width:34, height:34, borderRadius:9,
            background:"linear-gradient(135deg,#00d2ff 0%,#0070c0 100%)",
            display:"grid", placeItems:"center", fontSize:17, boxShadow:"0 2px 12px rgba(0,180,255,.35)",
          }}>📡</div>
          <div>
            <div style={{ fontSize:15, fontWeight:800, letterSpacing:".02em", lineHeight:1.15 }}>StockRadar</div>
            <div style={{ fontSize:10.5, color:"#5a7ca8", letterSpacing:".08em", lineHeight:1 }}>
              {screen?.last_update ? `更新 ${screen.last_update.slice(0,10)}` : "台股籌碼"}
            </div>
          </div>
        </div>

        {/* Search */}
        <div style={{ position:"relative", flex:1, maxWidth:360, marginLeft:8 }}>
          <span style={{ position:"absolute", left:11, top:"50%", transform:"translateY(-50%)", fontSize:14, opacity:.4 }}>🔍</span>
          <input
            placeholder="搜尋代號或名稱…"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            style={{
              width:"100%", padding:"8px 12px 8px 32px",
              borderRadius:8, background:"rgba(255,255,255,.06)",
              border:"1px solid rgba(255,255,255,.1)", outline:"none",
              fontSize:13.5, color:"var(--text)", boxSizing:"border-box",
            }}
          />
        </div>

        {/* Actions */}
        <div style={{ marginLeft:"auto", display:"flex", alignItems:"center", gap:8 }}>
          <button onClick={exportCSV} style={btnStyle("#0070c0")}>📥 CSV</button>
          <div style={{ width:1, height:20, background:"rgba(255,255,255,.1)", margin:"0 4px" }} />
          <span style={{ fontSize:13, color:"#5a7ca8" }}>👤 {user?.name || user?.email?.split("@")[0]}</span>
          <button onClick={() => { logout(); nav("/login"); }} style={btnStyle()}>登出</button>
        </div>
      </header>

      {/* ── Filter Bar ─────────────────────────────────────── */}
      <section style={{
        padding:"14px 28px",
        background:"rgba(0,20,50,.30)",
        borderBottom:"1px solid rgba(0,150,255,.09)",
        display:"flex", gap:36, flexWrap:"wrap", alignItems:"center",
      }}>
        <Slider label="日均量門檻" suffix="張" min={500} max={10000} step={500} value={minAvgVol} onChange={setMinAvgVol} />
        <Slider label="籌碼集中度下限" suffix="%" min={0} max={100} step={1} value={minConc} onChange={setMinConc} />
        {/* 上市 / 上櫃 切換 */}
        <MarketToggle value={market} onChange={setMarket} />

        <label style={{ display:"flex", alignItems:"center", gap:7, cursor:"pointer", fontSize:13, color:"#8ca8c8", userSelect:"none" }}>
          <input type="checkbox" checked={onlyBuy} onChange={(e) => setOnlyBuy(e.target.checked)}
                 style={{ accentColor:"var(--accent)", width:15, height:15 }} />
          僅顯示三大法人買超
        </label>
        <div style={{ marginLeft:"auto", display:"flex", alignItems:"center", gap:8 }}>
          <span style={{ fontSize:13, color:"#5a7ca8" }}>符合條件</span>
          <span style={{ fontSize:20, fontWeight:800, color:"var(--accent)", fontFamily:"var(--font-mono)", lineHeight:1 }}>
            {items.length}
          </span>
          <span style={{ fontSize:13, color:"#5a7ca8" }}>/ 全部 {screen?.total ?? 0} 檔</span>
        </div>
      </section>

      {/* ── Table ──────────────────────────────────────────── */}
      <main style={{ padding:"20px 28px" }}>
        <div style={{
          background:"rgba(4,8,15,.92)",
          border:"1px solid rgba(0,150,255,.12)",
          borderRadius:14,
          overflow:"auto",
          boxShadow:"0 4px 40px rgba(0,0,0,.7), 0 0 0 1px rgba(0,180,255,.04)",
        }}>
          {isLoading ? (
            <div style={{ padding:70, textAlign:"center", color:"#5a7ca8", fontSize:15 }}>📡 篩選中…</div>
          ) : items.length === 0 ? (
            <div style={{ padding:70, textAlign:"center", color:"#5a7ca8", fontSize:15 }}>
              沒有符合條件的標的，試著放寬篩選參數
            </div>
          ) : (
            <ResizableTable
              items={items}
              onRowClick={(code) => nav(`/stock/${code}`)}
              onToggleWl={(code, inWl) => inWl ? rmWl.mutate(code) : addWl.mutate(code)}
              sort={sort}
              onSort={handleSort}
            />
          )}
        </div>
      </main>
    </div>
  );
}

// ── 欄位定義 ─────────────────────────────────────────────
// group: 0 基本 / 1 行情 / 2 籌碼 / 3 法人買賣超 / 4 關注
const COLS = [
  { key:"code",                label:"代號",      sub:"",   align:"left"   as const, width:72,  group:0, sortable:true  },
  { key:"name",                label:"名稱",      sub:"",   align:"left"   as const, width:148, group:0, sortable:false },
  { key:"industry",            label:"產業",      sub:"",   align:"left"   as const, width:108, group:0, sortable:false },
  { key:"close",               label:"收盤",      sub:"元", align:"right"  as const, width:72,  group:1, sortable:true  },
  { key:"avg_vol_20d",         label:"均量",      sub:"張", align:"right"  as const, width:88,  group:1, sortable:true  },
  { key:"conc_ratio",          label:"籌碼集中度", sub:"%", align:"right"  as const, width:108, group:2, sortable:true  },
  { key:"foreign_hold_ratio",  label:"外資持股",  sub:"%",  align:"right"  as const, width:92,  group:2, sortable:true  },
  { key:"big_chip",            label:"大戶籌碼",  sub:"%",  align:"right"  as const, width:92,  group:2, sortable:true  },
  { key:"director_hold_ratio", label:"董監持股",  sub:"%",  align:"right"  as const, width:92,  group:2, sortable:true  },
  { key:"foreign_net",         label:"外資買賣超", sub:"張", align:"right"  as const, width:104, group:3, sortable:true  },
  { key:"trust_net",           label:"投信買賣超", sub:"張", align:"right"  as const, width:104, group:3, sortable:true  },
  { key:"watchlist",           label:"",          sub:"",   align:"center" as const, width:52,  group:4, sortable:false },
];

// 每個 group 的左邊起始欄加粗分隔線
const GROUP_START = new Set([3, 5, 9, 11]); // close, conc_ratio, foreign_net, watchlist

// ── Table ────────────────────────────────────────────────
function ResizableTable({ items, onRowClick, onToggleWl, sort, onSort }: {
  items: ScreenItem[];
  onRowClick: (code: string) => void;
  onToggleWl: (code: string, inWl: boolean) => void;
  sort: { key: string; dir: "asc" | "desc" };
  onSort: (key: string) => void;
}) {
  const [widths, setWidths] = useState<number[]>(COLS.map(c => c.width));
  const [hovered, setHovered] = useState<string | null>(null);
  const dragRef = useRef<{ colIdx: number; startX: number; startW: number } | null>(null);

  const onMouseDown = useCallback((colIdx: number, e: React.MouseEvent) => {
    e.preventDefault();
    dragRef.current = { colIdx, startX: e.clientX, startW: widths[colIdx] };
    const onMove = (ev: MouseEvent) => {
      if (!dragRef.current) return;
      const newW = Math.max(40, dragRef.current.startW + ev.clientX - dragRef.current.startX);
      setWidths(ws => ws.map((w, i) => i === dragRef.current!.colIdx ? newW : w));
    };
    const onUp = () => {
      dragRef.current = null;
      window.removeEventListener("mousemove", onMove);
      window.removeEventListener("mouseup", onUp);
    };
    window.addEventListener("mousemove", onMove);
    window.addEventListener("mouseup", onUp);
  }, [widths]);

  const LAST = COLS.length - 1;

  return (
    <table style={{ tableLayout:"fixed", width:"max-content", minWidth:"100%", borderCollapse:"collapse" }}>
      <colgroup>
        {widths.map((w, i) => <col key={i} style={{ width: w }} />)}
      </colgroup>

      {/* THEAD */}
      <thead>
        <tr style={{ background:"rgba(0,44,100,.22)" }}>
          {COLS.map((col, i) => {
            const isGroupStart = GROUP_START.has(i);
            const isActive = col.sortable && sort.key === col.key;
            return (
              <th key={col.key}
                onClick={col.sortable ? () => onSort(col.key) : undefined}
                style={{
                  padding:"11px 14px 10px",
                  textAlign: col.align,
                  fontSize: 11.5,
                  fontWeight: 700,
                  letterSpacing: ".07em",
                  color: isActive ? "#00d8ff" : "#5a8ab8",
                  textTransform: "uppercase",
                  position: "relative",
                  userSelect: "none",
                  whiteSpace: "nowrap",
                  overflow: "hidden",
                  borderBottom: isActive ? "2px solid #00d8ff" : "1px solid rgba(0,150,255,.15)",
                  borderLeft: isGroupStart ? "2px solid rgba(0,150,255,.28)" : undefined,
                  cursor: col.sortable ? "pointer" : "default",
                  transition: "color .15s, border-bottom .15s",
                }}>
                <span style={{ display:"inline-flex", alignItems:"center", gap:4 }}>
                  {col.label}
                  {col.sub && <span style={{ fontSize:9.5, opacity:.6, fontWeight:400 }}>{col.sub}</span>}
                  {col.sortable && (
                    <span style={{ fontSize:11, opacity: isActive ? 1 : 0.3, marginLeft:1, transition:"opacity .15s" }}>
                      {isActive ? (sort.dir === "asc" ? "↑" : "↓") : "↕"}
                    </span>
                  )}
                </span>
                {i < LAST && (
                  <span onMouseDown={(e) => { e.stopPropagation(); onMouseDown(i, e); }} style={{
                    position:"absolute", right:0, top:0, bottom:0,
                    width:5, cursor:"col-resize",
                  }} />
                )}
              </th>
            );
          })}
        </tr>
      </thead>

      {/* TBODY */}
      <tbody>
        {items.map((s, rowIdx) => {
          const forHold = s.foreign_hold_ratio != null ? Number(s.foreign_hold_ratio) : null;
          const conc    = s.conc_ratio != null ? Number(s.conc_ratio) : null;
          const bigChip = conc != null && forHold != null ? Math.max(0, Number((conc - forHold).toFixed(2))) : null;
          const dirHold = s.director_hold_ratio != null ? Number(s.director_hold_ratio) : null;
          const fNet    = s.foreign_net != null ? Number(s.foreign_net) : null;
          const tNet    = s.trust_net   != null ? Number(s.trust_net)   : null;
          const isHov   = hovered === s.code;
          const isEven  = rowIdx % 2 === 1;

          return (
            <tr key={s.code}
              onMouseEnter={() => setHovered(s.code)}
              onMouseLeave={() => setHovered(null)}
              style={{
                borderBottom: "1px solid rgba(0,80,160,.12)",
                background: isHov ? "rgba(0,130,255,.08)" : isEven ? "rgba(0,130,255,.025)" : "transparent",
                transition: "background .12s",
              }}
            >
              {/* 代號 */}
              <td onClick={() => onRowClick(s.code)} style={{
                ...tdc("left", true),
                borderLeft: isHov ? "3px solid #00d8ff" : "3px solid transparent",
                transition: "border-left .12s",
              }}>
                <span style={{ fontFamily:"var(--font-mono)", color:"#00d8ff", fontWeight:800, fontSize:14.5, letterSpacing:".02em" }}>
                  {s.code}
                </span>
              </td>

              {/* 名稱 + Badge */}
              <td onClick={() => onRowClick(s.code)} style={tdc("left", true)}>
                <div style={{ display:"flex", alignItems:"center", gap:6 }}>
                  <span style={{ fontWeight:700, fontSize:13.5, color:"#ddeeff", whiteSpace:"nowrap" }}>{s.short_name || s.name}</span>
                  <MarketBadge market={s.market} />
                </div>
              </td>

              {/* 產業 */}
              <td onClick={() => onRowClick(s.code)} style={tdc("left", true)}>
                <span style={{ fontSize:12, color:"#4a6a88", whiteSpace:"nowrap" }}>
                  {industryLabel(s.industry)}
                </span>
              </td>

              {/* 收盤 — group start */}
              <td onClick={() => onRowClick(s.code)}
                  style={{ ...tdc("right", true), borderLeft:"2px solid rgba(0,150,255,.18)" }}>
                <span style={{ fontFamily:"var(--font-mono)", fontSize:14.5, fontWeight:600, color:"#b8ccec" }}>
                  {s.close ? Number(s.close).toFixed(2) : "—"}
                </span>
              </td>

              {/* 均量 */}
              <td onClick={() => onRowClick(s.code)} style={tdc("right", true)}>
                <span style={{ fontFamily:"var(--font-mono)", fontSize:13.5, color:"#6a8aaa" }}>
                  {s.avg_vol_20d ? Math.round(Number(s.avg_vol_20d)).toLocaleString() : "—"}
                </span>
              </td>

              {/* 籌碼集中度 — group start */}
              <td onClick={() => onRowClick(s.code)}
                  style={{ ...tdc("right", true), borderLeft:"2px solid rgba(0,150,255,.18)" }}>
                <ConcCell value={conc} />
              </td>

              {/* 外資持股 */}
              <td onClick={() => onRowClick(s.code)} style={tdc("right", true)}>
                <PctTag value={forHold} color="#00aaff" bg="rgba(0,170,255,.13)" border="rgba(0,170,255,.40)" />
              </td>

              {/* 大戶籌碼 */}
              <td onClick={() => onRowClick(s.code)} style={tdc("right", true)}>
                <PctTag value={bigChip} color="#ff4da6" bg="rgba(255,77,166,.10)" border="rgba(255,77,166,.38)" />
              </td>

              {/* 董監持股 */}
              <td onClick={() => onRowClick(s.code)} style={tdc("right", true)}>
                <PctTag value={dirHold} color="#ffcc00" bg="rgba(255,204,0,.10)" border="rgba(255,204,0,.38)" />
              </td>

              {/* 外資買賣超 — group start */}
              <td onClick={() => onRowClick(s.code)}
                  style={{ ...tdc("right", true), borderLeft:"2px solid rgba(0,150,255,.18)" }}>
                <NetTag value={fNet} />
              </td>

              {/* 投信買賣超 */}
              <td onClick={() => onRowClick(s.code)} style={tdc("right", true)}>
                <NetTag value={tNet} />
              </td>

              {/* 關注 — group start */}
              <td style={{ ...tdc("center", false), borderLeft:"2px solid rgba(0,150,255,.18)" }}>
                <button
                  onClick={() => onToggleWl(s.code, s.in_watchlist)}
                  title={s.in_watchlist ? "移除關注" : "加入關注"}
                  style={{
                    fontSize:18, lineHeight:1, padding:"2px 4px",
                    background:"transparent", border:"none", cursor:"pointer",
                    color: s.in_watchlist ? "#ffd700" : "#1e3050",
                    textShadow: s.in_watchlist ? "0 0 10px rgba(255,210,0,.65)" : "none",
                    transition:"color .15s, transform .15s, text-shadow .15s",
                    transform: s.in_watchlist ? "scale(1.2)" : "scale(1)",
                  }}
                >
                  {s.in_watchlist ? "★" : "☆"}
                </button>
              </td>
            </tr>
          );
        })}
      </tbody>
    </table>
  );
}

// ── 籌碼集中度（數字 + mini bar）────────────────────────────
function ConcCell({ value }: { value: number | null }) {
  if (value == null) return <Dash />;
  const pct = Math.min(100, Math.max(0, value));
  return (
    <div style={{ display:"flex", flexDirection:"column", alignItems:"flex-end", gap:4 }}>
      <span style={{
        fontFamily:"var(--font-mono)", fontSize:15, fontWeight:800,
        color:"#b04cff",
        textShadow:"0 0 16px rgba(176,76,255,.55)",
      }}>
        {value.toFixed(2)}%
      </span>
      <div style={{ width:60, height:5, borderRadius:3, background:"rgba(176,76,255,.12)", overflow:"hidden" }}>
        <div style={{ width:`${pct}%`, height:"100%", borderRadius:3, background:"linear-gradient(90deg,#6a1fc2,#b04cff,#d890ff)" }} />
      </div>
    </div>
  );
}

// ── % Tag（數字 + 彩色背景 pill）────────────────────────────
function PctTag({ value, color, bg, border }: { value: number | null; color: string; bg: string; border: string }) {
  if (value == null) return <Dash />;
  return (
    <span style={{
      display:"inline-block",
      padding:"3px 9px",
      borderRadius:6,
      background: bg,
      color, fontFamily:"var(--font-mono)",
      fontSize:13.5, fontWeight:700,
      border:`1px solid ${border}`,
      letterSpacing:".01em",
    }}>
      {value.toFixed(2)}%
    </span>
  );
}

// ── 法人買賣超（張；台股慣例紅漲綠跌：買超紅、賣超綠）──────────
function NetTag({ value }: { value: number | null }) {
  if (value == null) return <Dash />;
  const v = Math.round(value);
  const color = v > 0 ? "#ff5a5a" : v < 0 ? "#00e49a" : "#6a8aaa";
  return (
    <span style={{ fontFamily:"var(--font-mono)", fontSize:13.5, fontWeight:700, color, letterSpacing:".01em" }}>
      {v > 0 ? "+" : ""}{v.toLocaleString()}
    </span>
  );
}

// ── Market Badge ─────────────────────────────────────────
function MarketBadge({ market }: { market: string }) {
  const isTwse = market === "TWSE";
  return (
    <span style={{
      display:"inline-block", padding:"1px 5px", borderRadius:4,
      fontSize:10, fontWeight:700, letterSpacing:".05em", whiteSpace:"nowrap",
      background: isTwse ? "rgba(0,130,255,.18)" : "rgba(0,200,130,.18)",
      color:       isTwse ? "#5ab4ff" : "#34d399",
      border:      `1px solid ${isTwse ? "rgba(0,130,255,.35)" : "rgba(0,200,130,.35)"}`,
    }}>
      {isTwse ? "上市" : "上櫃"}
    </span>
  );
}

// ── Helpers ───────────────────────────────────────────────
function Dash() {
  return <span style={{ color:"#1a2d44", fontSize:13 }}>—</span>;
}

function tdc(align: "left" | "right" | "center", clickable: boolean): React.CSSProperties {
  return {
    padding:"10px 14px",
    textAlign: align,
    cursor: clickable ? "pointer" : "default",
    overflow:"hidden", textOverflow:"ellipsis", whiteSpace:"nowrap",
    maxWidth:0, verticalAlign:"middle",
  };
}

function Slider({ label, suffix, value, min, max, step, onChange }: {
  label:string; suffix:string; value:number; min:number; max:number; step:number;
  onChange:(v:number) => void;
}) {
  return (
    <div>
      <div style={{ fontSize:10.5, letterSpacing:".1em", color:"#3d5a7a", textTransform:"uppercase", marginBottom:5, fontWeight:600 }}>
        {label}
      </div>
      <div style={{ display:"flex", alignItems:"center", gap:10 }}>
        <input type="range" min={min} max={max} step={step} value={value}
               onChange={(e) => onChange(+e.target.value)}
               style={{ width:150, accentColor:"var(--accent)", cursor:"pointer" }} />
        <span style={{
          fontFamily:"var(--font-mono)", color:"var(--accent)", fontWeight:800,
          minWidth:70, fontSize:15,
        }}>
          {value.toLocaleString()}{suffix}
        </span>
      </div>
    </div>
  );
}

// ── 上市 / 上櫃 Toggle ────────────────────────────────────
function MarketToggle({
  value,
  onChange,
}: {
  value: "ALL" | "TWSE" | "TPEX";
  onChange: (v: "ALL" | "TWSE" | "TPEX") => void;
}) {
  const opts: { key: "ALL" | "TWSE" | "TPEX"; label: string }[] = [
    { key: "ALL",  label: "全部" },
    { key: "TWSE", label: "上市" },
    { key: "TPEX", label: "上櫃" },
  ];
  return (
    <div>
      <div style={{ fontSize:10.5, letterSpacing:".1em", color:"#3d5a7a", textTransform:"uppercase", marginBottom:5, fontWeight:600 }}>
        市場
      </div>
      <div style={{ display:"flex", borderRadius:8, overflow:"hidden", border:"1px solid rgba(0,150,255,.22)" }}>
        {opts.map(({ key, label }) => {
          const active = value === key;
          const twse   = key === "TWSE";
          const tpex   = key === "TPEX";
          const activeColor  = twse ? "#5ab4ff" : tpex ? "#34d399" : "var(--accent)";
          const activeBg     = twse ? "rgba(0,130,255,.22)"  : tpex ? "rgba(0,200,130,.22)"  : "rgba(0,120,255,.18)";
          return (
            <button
              key={key}
              onClick={() => onChange(key)}
              style={{
                padding:"5px 14px",
                fontSize:12.5, fontWeight:700,
                letterSpacing:".04em",
                border:"none",
                borderRight: key !== "TPEX" ? "1px solid rgba(0,150,255,.22)" : "none",
                cursor:"pointer",
                transition:"background .15s, color .15s",
                background: active ? activeBg : "rgba(0,0,0,.25)",
                color:      active ? activeColor : "#3d5a7a",
              }}
            >
              {label}
            </button>
          );
        })}
      </div>
    </div>
  );
}

function btnStyle(color?: string): React.CSSProperties {
  return {
    padding:"6px 13px",
    background: color ? `${color}22` : "rgba(255,255,255,.05)",
    border:`1px solid ${color ? `${color}44` : "rgba(255,255,255,.1)"}`,
    borderRadius:7,
    fontSize:12.5,
    color: color ? "#7ec8ff" : "#8ca8c8",
    cursor:"pointer",
    fontWeight:600,
  };
}
