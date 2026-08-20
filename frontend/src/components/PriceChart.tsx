import {
  Bar,
  CartesianGrid,
  ComposedChart,
  Line,
  ReferenceLine,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import { fmt } from "@/lib/types";
import type { Candle, Signal, Trade } from "@/lib/types";

interface Point {
  label: string;
  range: [number, number];
  open: number;
  high: number;
  low: number;
  close: number;
  ema20: number | null;
  ema50: number | null;
  vwap: number | null;
  bbUpper: number | null;
  bbLower: number | null;
}

function emaSeries(values: number[], period: number): (number | null)[] {
  const out: (number | null)[] = values.map(() => null);
  if (values.length < period) return out;
  const k = 2 / (period + 1);
  let prev = values.slice(0, period).reduce((a, b) => a + b, 0) / period;
  out[period - 1] = prev;
  for (let i = period; i < values.length; i += 1) {
    prev = values[i] * k + prev * (1 - k);
    out[i] = prev;
  }
  return out;
}

function bollinger(values: number[], period = 20, mult = 2) {
  const upper: (number | null)[] = values.map(() => null);
  const lower: (number | null)[] = values.map(() => null);
  for (let i = period - 1; i < values.length; i += 1) {
    const w = values.slice(i - period + 1, i + 1);
    const mid = w.reduce((a, b) => a + b, 0) / period;
    const sd = Math.sqrt(w.reduce((a, b) => a + (b - mid) ** 2, 0) / period);
    upper[i] = mid + mult * sd;
    lower[i] = mid - mult * sd;
  }
  return { upper, lower };
}

function vwapSeries(candles: Candle[], period = 60): (number | null)[] {
  return candles.map((_, i) => {
    const w = candles.slice(Math.max(0, i - period + 1), i + 1);
    const vol = w.reduce((a, c) => a + c.volume, 0);
    if (vol <= 0) return null;
    return w.reduce((a, c) => a + ((c.high + c.low + c.close) / 3) * c.volume, 0) / vol;
  });
}

interface ShapeProps {
  x?: number;
  y?: number;
  width?: number;
  height?: number;
  payload?: Point;
}

function CandleShape({ x = 0, y = 0, width = 6, height = 0, payload }: ShapeProps) {
  if (!payload || height <= 0) return null;
  const { high, low, open, close } = payload;
  const span = high - low || 1e-9;
  const scale = height / span;
  const bodyTop = y + (high - Math.max(open, close)) * scale;
  const bodyH = Math.max(Math.abs(close - open) * scale, 1);
  const bull = close >= open;
  const color = bull ? "#10b981" : "#f43f5e";
  const cx = x + width / 2;
  const bodyW = Math.max(width * 0.62, 1.2);
  return (
    <g>
      <line x1={cx} x2={cx} y1={y} y2={y + height} stroke={color} strokeWidth={1} />
      <rect x={cx - bodyW / 2} y={bodyTop} width={bodyW} height={bodyH} fill={color} />
    </g>
  );
}

interface Props {
  candles: Candle[] | undefined;
  timeframe: string;
  signal: Signal | undefined;
  openTrade: Trade | null | undefined;
  livePrice: number | null | undefined;
  loading: boolean;
}

export default function PriceChart({
  candles,
  timeframe,
  signal,
  openTrade,
  livePrice,
  loading,
}: Props) {
  const rows = candles ?? [];
  const closes = rows.map((c) => c.close);
  const e20 = emaSeries(closes, 20);
  const e50 = emaSeries(closes, 50);
  const bb = bollinger(closes);
  const vw = vwapSeries(rows);

  const data: Point[] = rows.map((c, i) => ({
    label: new Date(c.time).toLocaleTimeString("en-GB", { hour: "2-digit", minute: "2-digit" }),
    range: [c.low, c.high],
    open: c.open,
    high: c.high,
    low: c.low,
    close: c.close,
    ema20: e20[i],
    ema50: e50[i],
    vwap: vw[i],
    bbUpper: bb.upper[i],
    bbLower: bb.lower[i],
  }));

  const entry = openTrade?.entry ?? null;
  const sl = openTrade?.sl ?? signal?.sl ?? null;
  const tp = openTrade?.tp ?? signal?.tp ?? null;
  const planned = !openTrade;
  const live = livePrice ?? (rows.length ? rows[rows.length - 1].close : null);
  const lastClose = rows.length ? rows[rows.length - 1].close : null;
  const liveUp = live !== null && lastClose !== null ? live >= lastClose : true;

  const extremes = data.flatMap((d) => [d.high, d.low]);
  [entry, sl, tp, live].forEach((v) => {
    if (v !== null && v !== undefined) extremes.push(v);
  });
  const min = extremes.length ? Math.min(...extremes) : 0;
  const max = extremes.length ? Math.max(...extremes) : 1;
  const pad = (max - min) * 0.06 || 1;

  return (
    <section
      className="col-span-12 flex min-h-[520px] flex-col rounded-md border border-slate-800 bg-[#111827] p-4 lg:col-span-8"
      data-testid="price-chart-panel"
    >
      <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
        <div>
          <h2 className="text-sm font-semibold text-slate-100">
            XAUUSDT · <span className="text-amber-400">{timeframe}</span>
          </h2>
          <p className="text-[11px] text-slate-500">
            Candles with EMA20 / EMA50 / VWAP / Bollinger, plus Entry, SL and TP levels
          </p>
        </div>
        <div className="flex flex-wrap items-center gap-3 text-[10px] text-slate-400">
          <Legend color="#38bdf8" label={planned ? "Planned Entry" : "Entry"} dashed={planned} />
          <Legend color="#f43f5e" label="Stop Loss" dashed={planned} />
          <Legend color="#10b981" label="Take Profit" dashed={planned} />
          <Legend color="#eab308" label="EMA20" />
          <Legend color="#a78bfa" label="EMA50" />
          <Legend color="#64748b" label="VWAP" />
          <Legend color="#f1f5f9" label="Live price" />
        </div>
      </div>

      <div className="min-h-[420px] flex-1">
        {data.length === 0 ? (
          <div
            className="flex h-[420px] flex-col items-center justify-center gap-2 rounded border border-dashed border-slate-800 text-center"
            data-testid="chart-empty-state"
          >
            <p className="text-sm text-slate-400">
              {loading ? "Loading gold market candles…" : "Market data unavailable right now."}
            </p>
            <p className="max-w-sm text-[11px] text-slate-600">
              The chart fills in as soon as the Binance gold feed responds. Signals and the paper
              wallet keep their last known state meanwhile.
            </p>
          </div>
        ) : (
          <ResponsiveContainer width="100%" height={440}>
            <ComposedChart data={data} margin={{ top: 8, right: 66, left: 4, bottom: 4 }}>
              <CartesianGrid stroke="#1e293b" strokeDasharray="2 4" vertical={false} />
              <XAxis
                dataKey="label"
                tick={{ fill: "#64748b", fontSize: 10 }}
                stroke="#1e293b"
                minTickGap={40}
              />
              <YAxis
                domain={[min - pad, max + pad]}
                orientation="right"
                tick={{ fill: "#94a3b8", fontSize: 10 }}
                stroke="#1e293b"
                tickFormatter={(v: number) => v.toFixed(1)}
                width={62}
              />
              <Tooltip
                contentStyle={{
                  background: "rgba(2,6,23,0.94)",
                  border: "1px solid #1e293b",
                  borderRadius: 6,
                  fontSize: 11,
                }}
                labelStyle={{ color: "#94a3b8" }}
                formatter={(value: unknown, name: unknown) => {
                  if (Array.isArray(value)) return [`${fmt(value[0])} – ${fmt(value[1])}`, "Low–High"];
                  return [fmt(typeof value === "number" ? value : null), String(name ?? "")];
                }}
              />
              <Line dataKey="bbUpper" stroke="#334155" dot={false} strokeWidth={1} name="BB Upper" />
              <Line dataKey="bbLower" stroke="#334155" dot={false} strokeWidth={1} name="BB Lower" />
              <Bar dataKey="range" shape={<CandleShape />} isAnimationActive={false} name="OHLC" />
              <Line dataKey="ema20" stroke="#eab308" dot={false} strokeWidth={1.4} name="EMA20" />
              <Line dataKey="ema50" stroke="#a78bfa" dot={false} strokeWidth={1.4} name="EMA50" />
              <Line
                dataKey="vwap"
                stroke="#64748b"
                dot={false}
                strokeWidth={1.2}
                strokeDasharray="4 3"
                name="VWAP"
              />
              {entry !== null && (
                <ReferenceLine
                  y={entry}
                  stroke="#38bdf8"
                  strokeWidth={1.4}
                  label={{ value: `ENTRY ${fmt(entry)}`, position: "left", fill: "#38bdf8", fontSize: 10 }}
                />
              )}
              {sl !== null && (
                <ReferenceLine
                  y={sl}
                  stroke="#f43f5e"
                  strokeWidth={1.4}
                  strokeDasharray={planned ? "5 4" : undefined}
                  label={{ value: `SL ${fmt(sl)}`, position: "left", fill: "#f43f5e", fontSize: 10 }}
                />
              )}
              {tp !== null && (
                <ReferenceLine
                  y={tp}
                  stroke="#10b981"
                  strokeWidth={1.4}
                  strokeDasharray={planned ? "5 4" : undefined}
                  label={{ value: `TP ${fmt(tp)}`, position: "left", fill: "#10b981", fontSize: 10 }}
                />
              )}
              {live !== null && live !== undefined && (
                <ReferenceLine
                  y={live}
                  stroke={liveUp ? "#34d399" : "#fb7185"}
                  strokeWidth={1.2}
                  strokeDasharray="2 3"
                  ifOverflow="extendDomain"
                  label={{
                    value: `● ${fmt(live)}`,
                    position: "right",
                    fill: liveUp ? "#34d399" : "#fb7185",
                    fontSize: 11,
                    fontWeight: 700,
                  }}
                />
              )}
            </ComposedChart>
          </ResponsiveContainer>
        )}
      </div>

      {planned && (sl !== null || tp !== null) ? (
        <p className="mt-2 text-[11px] text-slate-500" data-testid="chart-planned-note">
          Dashed SL/TP are the levels the engine <em>would</em> use if this setup passed every gate —
          no position is open.
        </p>
      ) : null}
    </section>
  );
}

function Legend({ color, label, dashed }: { color: string; label: string; dashed?: boolean }) {
  return (
    <span className="flex items-center gap-1.5">
      <span
        className="inline-block h-0 w-4 border-t-2"
        style={{ borderColor: color, borderStyle: dashed ? "dashed" : "solid" }}
      />
      {label}
    </span>
  );
}
