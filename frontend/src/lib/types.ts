/**
 * Pydantic v2 response models. Mirrored from backend/models/trading.py
 */

// =====================================================================
// TIMEFRAMES
// =====================================================================

export const TIMEFRAMES = [
  "1m",
  "5m",
  "15m", 
  "30m",
  "1h",
] as const;

export type Timeframe = typeof TIMEFRAMES[number];

// =====================================================================
// REST OF TYPES...
// =====================================================================

export interface Candle {
  time: number;
  open: number;
  high: number;
  low: number;
  close: number;
  volume: number;
}

export interface CandlesResponse {
  symbol: string;
  timeframe: string;
  provider: string;
  candles: Candle[];
}

// ... (rest of types from previous file)

// =====================================================================
// UTILITY FUNCTIONS
// =====================================================================

export const fmt = (value: number | null | undefined, decimals: number = 2): string => {
  if (value === null || value === undefined) return "—";
  if (!isFinite(value)) return "—";
  return Number(value).toFixed(decimals);
};

export const money = (value: number | null | undefined): string => {
  if (value === null || value === undefined) return "—";
  if (!isFinite(value)) return "—";
  return `$${fmt(value)}`;
};

export const rupees = (value: number | null | undefined): string => {
  if (value === null || value === undefined) return "—";
  if (!isFinite(value)) return "—";
  return `₹${fmt(value)}`;
};

export const duration = (seconds: number | null | undefined): string => {
  if (seconds === null || seconds === undefined || !isFinite(seconds)) return "—";
  if (seconds < 0) return "—";
  
  const hrs = Math.floor(seconds / 3600);
  const mins = Math.floor((seconds % 3600) / 60);
  const secs = Math.floor(seconds % 60);
  
  if (hrs > 0) {
    return `${hrs}h ${mins}m ${secs}s`;
  }
  if (mins > 0) {
    return `${mins}m ${secs}s`;
  }
  return `${secs}s`;
};

export const signed = (value: number | null | undefined): string => {
  if (value === null || value === undefined) return "—";
  if (!isFinite(value)) return "—";
  if (value > 0) return `+${value.toFixed(2)}`;
  if (value < 0) return `${value.toFixed(2)}`;
  return "0.00";
};

export const signedMoney = (value: number | null | undefined): string => {
  if (value === null || value === undefined) return "—";
  if (!isFinite(value)) return "—";
  if (value > 0) return `+$${value.toFixed(2)}`;
  if (value < 0) return `-$${Math.abs(value).toFixed(2)}`;
  return "$0.00";
};

export const signedPct = (value: number | null | undefined): string => {
  if (value === null || value === undefined) return "—";
  if (!isFinite(value)) return "—";
  if (value > 0) return `+${value.toFixed(2)}%`;
  if (value < 0) return `${value.toFixed(2)}%`;
  return "0.00%";
};

// =====================================================================
// Api Error
// =====================================================================

export class ApiError extends Error {
  status: number;
  detail?: any;

  constructor(status: number, message: string, detail?: any) {
    super(message);
    this.status = status;
    this.detail = detail;
    this.name = "ApiError";
  }
}