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
  ema9: number | null;
  ema21: number | null;
  ema50: number | null;
  ema200: number | null;
  vwap: number | null;
  bbUpper: number | null;
  bbLower: number | null;
}

function emaSeries(
  values: number[],
  period: number,
): (number | null)[] {
  const result: (number | null)[] = values.map(() => null);

  if (values.length < period) {
    return result;
  }

  const multiplier = 2 / (period + 1);

  let previous =
    values
      .slice(0, period)
      .reduce((sum, value) => sum + value, 0) / period;

  result[period - 1] = previous;

  for (let i = period; i < values.length; i += 1) {
    previous =
      values[i] * multiplier +
      previous * (1 - multiplier);

    result[i] = previous;
  }

  return result;
}

function bollinger(
  values: number[],
  period = 20,
  multiplier = 2,
) {
  const upper: (number | null)[] = values.map(() => null);
  const lower: (number | null)[] = values.map(() => null);

  if (values.length < period) {
    return { upper, lower };
  }

  for (let i = period - 1; i < values.length; i += 1) {
    const window = values.slice(
      i - period + 1,
      i + 1,
    );

    const mean =
      window.reduce(
        (sum, value) => sum + value,
        0,
      ) / period;

    const variance =
      window.reduce(
        (sum, value) =>
          sum + (value - mean) ** 2,
        0,
      ) / period;

    const deviation = Math.sqrt(variance);

    upper[i] = mean + multiplier * deviation;
    lower[i] = mean - multiplier * deviation;
  }

  return { upper, lower };
}

function vwapSeries(
  candles: Candle[],
  period = 60,
): (number | null)[] {
  return candles.map((_, index) => {
    const window = candles.slice(
      Math.max(0, index - period + 1),
      index + 1,
    );

    const volume = window.reduce(
      (sum, candle) =>
        sum + Number(candle.volume || 0),
      0,
    );

    if (volume <= 0) {
      return null;
    }

    const weightedValue = window.reduce(
      (sum, candle) => {
        const typicalPrice =
          (candle.high +
            candle.low +
            candle.close) /
          3;

        return (
          sum +
          typicalPrice *
            Number(candle.volume || 0)
        );
      },
      0,
    );

    return weightedValue / volume;
  });
}

interface ShapeProps {
  x?: number;
  y?: number;
  width?: number;
  height?: number;
  payload?: Point;
}

function CandleShape({
  x = 0,
  y = 0,
  width = 6,
  height = 0,
  payload,
}: ShapeProps) {
  if (!payload || height <= 0) {
    return null;
  }

  const {
    high,
    low,
    open,
    close,
  } = payload;

  if (
    !Number.isFinite(high) ||
    !Number.isFinite(low) ||
    !Number.isFinite(open) ||
    !Number.isFinite(close)
  ) {
    return null;
  }

  const priceRange = high - low;

  if (priceRange <= 0) {
    return null;
  }

  const scale = height / priceRange;

  const bodyHigh = Math.max(
    open,
    close,
  );

  const bodyLow = Math.min(
    open,
    close,
  );

  const bodyTop =
    y +
    (high - bodyHigh) *
      scale;

  const bodyHeight = Math.max(
    (bodyHigh - bodyLow) * scale,
    1,
  );

  const bullish = close >= open;

  const candleColor = bullish
    ? "#10b981"
    : "#f43f5e";

  const centerX = x + width / 2;

  const bodyWidth = Math.max(
    Math.min(width * 0.65, 12),
    2,
  );

  return (
    <g>
      <line
        x1={centerX}
        x2={centerX}
        y1={y}
        y2={y + height}
        stroke={candleColor}
        strokeWidth={1}
      />

      <rect
        x={centerX - bodyWidth / 2}
        y={bodyTop}
        width={bodyWidth}
        height={bodyHeight}
        fill={candleColor}
      />
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
  symbol?: string | null;
}

export default function PriceChart({
  candles,
  timeframe,
  signal,
  openTrade,
  livePrice,
  loading,
  symbol,
}: Props) {
  const rows = (candles ?? []).filter(
    (c) =>
      Number.isFinite(c.open) &&
      Number.isFinite(c.high) &&
      Number.isFinite(c.low) &&
      Number.isFinite(c.close) &&
      Number.isFinite(c.time),
  );

  const closes = rows.map(
    (c) => Number(c.close),
  );

  const ema9 = emaSeries(closes, 9);
  const ema21 = emaSeries(closes, 21);
  const ema50 = emaSeries(closes, 50);
  const ema200 = emaSeries(closes, 200);

  const bb = bollinger(closes, 20, 2);
  const vwap = vwapSeries(rows, 60);

  const data: Point[] = rows.map(
    (c, index) => ({
      label: new Date(
        c.time * 1000,  // ✅ Coinbase returns seconds
      ).toLocaleTimeString(
        "en-GB",
        {
          hour: "2-digit",
          minute: "2-digit",
        },
      ),

      range: [
        Number(c.low),
        Number(c.high),
      ],

      open: Number(c.open),
      high: Number(c.high),
      low: Number(c.low),
      close: Number(c.close),

      ema9: ema9[index],
      ema21: ema21[index],
      ema50: ema50[index],
      ema200: ema200[index],

      vwap: vwap[index],

      bbUpper: bb.upper[index],
      bbLower: bb.lower[index],
    }),
  );

  const entry =
    openTrade?.entry ??
    null;

  const sl =
    openTrade?.sl ??
    signal?.sl ??
    null;

  const tp =
    openTrade?.tp ??
    signal?.tp ??
    null;

  const planned = !openTrade;

  const breakEven =
    openTrade?.breakeven_done
      ? openTrade.entry
      : null;

  const trailing =
    openTrade?.trailing_active
      ? openTrade.sl
      : null;

  const live =
    livePrice ??
    (rows.length > 0
      ? rows[rows.length - 1].close
      : null);

  const lastClose =
    rows.length > 0
      ? rows[rows.length - 1].close
      : null;

  const liveUp =
    live !== null &&
    lastClose !== null
      ? live >= lastClose
      : true;

  const extremes: number[] = [];

  data.forEach((point) => {
    const values = [
      point.high,
      point.low,
      point.ema9,
      point.ema21,
      point.ema50,
      point.ema200,
      point.vwap,
      point.bbUpper,
      point.bbLower,
    ];

    values.forEach((value) => {
      if (
        value !== null &&
        Number.isFinite(value)
      ) {
        extremes.push(value);
      }
    });
  });

  [
    entry,
    sl,
    tp,
    breakEven,
    trailing,
    live,
  ].forEach((value) => {
    if (
      value !== null &&
      value !== undefined &&
      Number.isFinite(value)
    ) {
      extremes.push(value);
    }
  });

  let min = extremes.length
    ? Math.min(...extremes)
    : 0;

  let max = extremes.length
    ? Math.max(...extremes)
    : 1;

  if (max <= min) {
    const center = min || 1;
    const padding = Math.max(
      center * 0.001,
      1,
    );

    min = center - padding;
    max = center + padding;
  }

  const priceRange = max - min;

  const padding = Math.max(
    priceRange * 0.06,
    1,
  );

  const domainMin = min - padding;
  const domainMax = max + padding;

  const chartSymbol =
    symbol || "BTCUSDT";

  // ✅ Loading state
  if (loading) {
    return (
      <section className="col-span-12 flex min-h-[520px] flex-col rounded-md border border-slate-800 bg-[#111827] p-4 lg:col-span-8">
        <div className="flex h-[420px] items-center justify-center">
          <div className="text-center">
            <div className="mb-3 inline-block h-8 w-8 animate-spin rounded-full border-4 border-amber-500 border-t-transparent"></div>
            <p className="text-sm text-slate-400">Loading candles...</p>
          </div>
        </div>
      </section>
    );
  }

  // ✅ Empty state
  if (!candles || candles.length === 0 || data.length === 0) {
    return (
      <section className="col-span-12 flex min-h-[520px] flex-col rounded-md border border-slate-800 bg-[#111827] p-4 lg:col-span-8">
        <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
          <div>
            <h2 className="text-sm font-semibold text-slate-100">
              {chartSymbol} · <span className="text-amber-400">{timeframe}</span>
            </h2>
            <p className="text-[11px] text-slate-500">
              Live {chartSymbol} candles · EMA9 / EMA21 / EMA50 / EMA200 / VWAP / Bollinger
            </p>
          </div>
        </div>
        <div className="flex h-[420px] flex-col items-center justify-center rounded border border-dashed border-slate-800 text-center">
          <p className="text-sm text-slate-400">
            {loading ? "Loading market candles…" : "No candle data available"}
          </p>
          <p className="max-w-sm text-[11px] text-slate-600">
            {loading ? "Fetching data from Coinbase…" : "Try selecting a different timeframe or symbol."}
          </p>
        </div>
      </section>
    );
  }

  // ✅ Full chart
  return (
    <section
      className="col-span-12 flex min-h-[520px] flex-col rounded-md border border-slate-800 bg-[#111827] p-4 lg:col-span-8"
      data-testid="price-chart-panel"
    >
      <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
        <div>
          <h2
            className="text-sm font-semibold text-slate-100"
            data-testid="chart-symbol"
          >
            {chartSymbol} ·{" "}
            <span className="text-amber-400">
              {timeframe}
            </span>
          </h2>

          <p className="text-[11px] text-slate-500">
            Live {chartSymbol} candles · EMA9 / EMA21 /
            EMA50 / EMA200 / VWAP / Bollinger
          </p>
        </div>

        <div className="flex flex-wrap items-center gap-3 text-[10px] text-slate-400">
          <Legend
            color="#38bdf8"
            label={
              planned
                ? "Planned Entry"
                : "Entry"
            }
            dashed={planned}
          />

          <Legend
            color="#f43f5e"
            label="Stop Loss"
            dashed={planned}
          />

          <Legend
            color="#10b981"
            label="Take Profit"
            dashed={planned}
          />

          <Legend
            color="#38f8c8"
            label="EMA9"
          />

          <Legend
            color="#eab308"
            label="EMA21"
          />

          <Legend
            color="#a78bfa"
            label="EMA50"
          />

          <Legend
            color="#fb923c"
            label="EMA200"
          />

          <Legend
            color="#64748b"
            label="VWAP"
          />

          <Legend
            color="#f1f5f9"
            label="Live price"
          />
        </div>
      </div>

      <div className="min-h-[420px] flex-1">
        <ResponsiveContainer
          width="100%"
          height={440}
        >
          <ComposedChart
            data={data}
            margin={{
              top: 8,
              right: 72,
              left: 4,
              bottom: 4,
            }}
          >
            <CartesianGrid
              stroke="#1e293b"
              strokeDasharray="2 4"
              vertical={false}
            />

            <XAxis
              dataKey="label"
              tick={{
                fill: "#64748b",
                fontSize: 10,
              }}
              stroke="#1e293b"
              minTickGap={40}
            />

            <YAxis
              type="number"
              domain={[
                domainMin,
                domainMax,
              ]}
              orientation="right"
              tick={{
                fill: "#94a3b8",
                fontSize: 10,
              }}
              stroke="#1e293b"
              tickFormatter={(value: number) =>
                value.toLocaleString(
                  "en-US",
                  {
                    maximumFractionDigits: 2,
                  },
                )
              }
              width={72}
              allowDataOverflow={false}
            />

            <Tooltip
              contentStyle={{
                background:
                  "rgba(2,6,23,0.94)",
                border:
                  "1px solid #1e293b",
                borderRadius: 6,
                fontSize: 11,
              }}
              labelStyle={{
                color: "#94a3b8",
              }}
              formatter={(
                value: unknown,
                name: unknown,
              ) => {
                if (
                  Array.isArray(value)
                ) {
                  return [
                    `${fmt(
                      Number(value[0]),
                    )} – ${fmt(
                      Number(value[1]),
                    )}`,
                    "Low–High",
                  ];
                }

                return [
                  fmt(
                    typeof value ===
                      "number"
                      ? value
                      : null,
                  ),
                  String(
                    name ?? "",
                  ),
                ];
              }}
            />

            <Line
              dataKey="bbUpper"
              stroke="#334155"
              dot={false}
              strokeWidth={1}
              name="BB Upper"
              connectNulls
              isAnimationActive={false}
            />

            <Line
              dataKey="bbLower"
              stroke="#334155"
              dot={false}
              strokeWidth={1}
              name="BB Lower"
              connectNulls
              isAnimationActive={false}
            />

            <Bar
              dataKey="range"
              shape={<CandleShape />}
              isAnimationActive={false}
              name="OHLC"
            />

            <Line
              dataKey="ema9"
              stroke="#38f8c8"
              dot={false}
              strokeWidth={1.2}
              name="EMA9"
              connectNulls
              isAnimationActive={false}
            />

            <Line
              dataKey="ema21"
              stroke="#eab308"
              dot={false}
              strokeWidth={1.4}
              name="EMA21"
              connectNulls
              isAnimationActive={false}
            />

            <Line
              dataKey="ema50"
              stroke="#a78bfa"
              dot={false}
              strokeWidth={1.4}
              name="EMA50"
              connectNulls
              isAnimationActive={false}
            />

            <Line
              dataKey="ema200"
              stroke="#fb923c"
              dot={false}
              strokeWidth={1.2}
              name="EMA200"
              connectNulls
              isAnimationActive={false}
            />

            <Line
              dataKey="vwap"
              stroke="#64748b"
              dot={false}
              strokeWidth={1.2}
              strokeDasharray="4 3"
              name="VWAP"
              connectNulls
              isAnimationActive={false}
            />

            {breakEven !== null && (
              <ReferenceLine
                y={breakEven}
                stroke="#22d3ee"
                strokeWidth={1}
                strokeDasharray="2 3"
                ifOverflow="extendDomain"
                label={{
                  value: `BE ${fmt(
                    breakEven,
                  )}`,
                  position: "left",
                  fill: "#22d3ee",
                  fontSize: 9,
                }}
              />
            )}

            {trailing !== null && (
              <ReferenceLine
                y={trailing}
                stroke="#fbbf24"
                strokeWidth={1}
                strokeDasharray="5 3"
                ifOverflow="extendDomain"
                label={{
                  value: `TRAIL ${fmt(
                    trailing,
                  )}`,
                  position: "left",
                  fill: "#fbbf24",
                  fontSize: 9,
                }}
              />
            )}

            {entry !== null && (
              <ReferenceLine
                y={entry}
                stroke="#38bdf8"
                strokeWidth={1.4}
                ifOverflow="extendDomain"
                label={{
                  value: `ENTRY ${fmt(
                    entry,
                  )}`,
                  position: "left",
                  fill: "#38bdf8",
                  fontSize: 10,
                }}
              />
            )}

            {sl !== null && (
              <ReferenceLine
                y={sl}
                stroke="#f43f5e"
                strokeWidth={1.4}
                strokeDasharray={
                  planned
                    ? "5 4"
                    : undefined
                }
                ifOverflow="extendDomain"
                label={{
                  value: `SL ${fmt(sl)}`,
                  position: "left",
                  fill: "#f43f5e",
                  fontSize: 10,
                }}
              />
            )}

            {tp !== null && (
              <ReferenceLine
                y={tp}
                stroke="#10b981"
                strokeWidth={1.4}
                strokeDasharray={
                  planned
                    ? "5 4"
                    : undefined
                }
                ifOverflow="extendDomain"
                label={{
                  value: `TP ${fmt(tp)}`,
                  position: "left",
                  fill: "#10b981",
                  fontSize: 10,
                }}
              />
            )}

            {live !== null &&
              live !== undefined && (
                <ReferenceLine
                  y={live}
                  stroke={
                    liveUp
                      ? "#34d399"
                      : "#fb7185"
                  }
                  strokeWidth={1.2}
                  strokeDasharray="2 3"
                  ifOverflow="extendDomain"
                  label={{
                    value: `● ${live.toLocaleString(
                      "en-US",
                      {
                        maximumFractionDigits: 2,
                      },
                    )}`,
                    position: "right",
                    fill: liveUp
                      ? "#34d399"
                      : "#fb7185",
                    fontSize: 11,
                    fontWeight: 700,
                  }}
                />
              )}
          </ComposedChart>
        </ResponsiveContainer>
      </div>

      {planned &&
      (sl !== null ||
        tp !== null) ? (
        <p
          className="mt-2 text-[11px] text-slate-500"
          data-testid="chart-planned-note"
        >
          Dashed SL/TP are the levels the
          engine would use if this setup
          passed every gate — no position is
          open.
        </p>
      ) : null}
    </section>
  );
}

function Legend({
  color,
  label,
  dashed,
}: {
  color: string;
  label: string;
  dashed?: boolean;
}) {
  return (
    <span className="flex items-center gap-1.5">
      <span
        className="inline-block h-0 w-4 border-t-2"
        style={{
          borderColor: color,
          borderStyle: dashed
            ? "dashed"
            : "solid",
        }}
      />
      {label}
    </span>
  );
}