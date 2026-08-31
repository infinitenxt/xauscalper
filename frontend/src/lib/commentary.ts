// 50 hunter-style market comments, grouped by market mood. One is spoken every
// few seconds while voice is on, chosen from the group that matches what the
// engine is currently seeing. Static text — no AI, no cost, no network.

export type Mood =
  | "strong_bull"
  | "bull"
  | "strong_bear"
  | "bear"
  | "waiting"
  | "volatile"
  | "quiet"
  | "in_trade_winning"
  | "in_trade_losing"
  | "near_target"
  | "blocked";

export const COMMENTARY: Record<Mood, string[]> = {
  strong_bull: [
    "bitcoiny is taking a huge jump, buyers are all over this one.",
    "Momentum is stacked to the upside, the bulls have the wheel.",
    "Every timeframe is pointing north, this is a clean bullish run.",
    "bitcoin is climbing with conviction, volume is backing the move.",
    "Buyers are pressing hard, resistance is starting to look thin.",
  ],
  bull: [
    "bitcoin is leaning up, buyers have a slight edge here.",
    "Mild upward drift, nothing to hunt just yet.",
    "Bulls are nudging price higher, the read is bullish but soft.",
    "Upside bias building, waiting for the confirmations to line up.",
    "bitcoin is grinding upward, patient bulls are in control.",
  ],
  strong_bear: [
    "bitcoiny is dropping hard, sellers are in full control.",
    "Heavy selling pressure, the floor keeps giving way.",
    "This is a steep slide, every bounce is getting sold.",
    "Bears are dominating, momentum is firmly to the downside.",
    "bitcoin is falling fast, support levels are breaking one by one.",
  ],
  bear: [
    "bitcoin is leaning down, sellers have the slight edge.",
    "Soft bearish drift, no clean setup yet.",
    "Sellers are nudging price lower, the read is bearish but weak.",
    "Downside bias forming, still waiting on confirmation.",
    "bitcoin is bleeding slowly, bears are quietly in front.",
  ],
  waiting: [
    "We are waiting for the hunt, no clean prey yet.",
    "Confirmations are split, so we sit on our hands.",
    "Patience is the position right now, nothing worth risking capital on.",
    "The market is undecided, and undecided markets pay nothing.",
    "Sitting flat and watching, a bad entry costs more than a missed one.",
    "No edge on the table, so we keep the powder dry.",
    "Bulls and bears are trading blows, no winner yet.",
    "Choppy and directionless, exactly where scalpers get chopped up.",
    "Still stalking, still not shooting.",
    "We only take the trades that come to us, and this one has not.",
  ],
  volatile: [
    "Volatility is spiking, bitcoin is swinging wide, stay sharp.",
    "The range is expanding fast, stops need room here.",
    "Wild candles printing, this is where discipline pays.",
    "Big moves in both directions, the market is hunting stops.",
    "Volatility is elevated, the engine is sizing down accordingly.",
  ],
  quiet: [
    "The market has gone quiet, barely a heartbeat in the candles.",
    "Volatility has dried up, there is nothing here to scalp.",
    "Dead tape, tight range, no reason to be involved.",
    "bitcoin is asleep, we wait for it to wake up.",
    "Too quiet to trade, the spread would eat any edge.",
  ],
  in_trade_winning: [
    "Position is in profit, letting the runner run.",
    "This one is working, stop is being pulled up behind it.",
    "Green on the screen, managing it rather than hoping.",
    "The thesis is paying, we protect what the market gave us.",
    "In the money, and now it is all about the exit.",
  ],
  in_trade_losing: [
    "Position is offside, the stop is doing its job as insurance.",
    "This one is against us, no averaging down, no hoping.",
    "Underwater but within plan, the risk was defined before entry.",
    "Not working yet, the clock and the stop are both watching it.",
    "Red for now, and that is exactly what the stop was sized for.",
  ],
  near_target: [
    "Closing in on target, the hunt is nearly done.",
    "Almost at take profit, we do not get greedy here.",
    "Target is in sight, the plan finishes the trade, not emotion.",
    "One more push and this one banks.",
  ],
  blocked: [
    "Trading is paused by the risk guards, protecting the account comes first.",
    "A guard is blocking new entries, the account rules outrank the signal.",
    "Standing down, we have hit a risk limit for now.",
  ],
};

export const TOTAL_COMMENTS = Object.values(COMMENTARY).reduce((n, g) => n + g.length, 0);

export interface MoodInput {
  direction: string | undefined;
  confidence: number | undefined;
  atrPct: number | undefined;
  blocked: boolean;
  inTrade: boolean;
  tradePnl: number | null | undefined;
  tpProgress: number | null | undefined;
}

export function pickMood(input: MoodInput): Mood {
  const { direction, confidence = 0, atrPct, blocked, inTrade, tradePnl, tpProgress } = input;

  if (inTrade) {
    if ((tpProgress ?? 0) >= 70) return "near_target";
    return (tradePnl ?? 0) >= 0 ? "in_trade_winning" : "in_trade_losing";
  }
  if (blocked) return "blocked";
  if (atrPct !== undefined && atrPct > 0.35) return "volatile";
  if (atrPct !== undefined && atrPct < 0.02) return "quiet";
  if (direction === "BUY") return confidence >= 55 ? "strong_bull" : "bull";
  if (direction === "SELL") return confidence >= 55 ? "strong_bear" : "bear";
  return "waiting";
}

// Avoid repeating a line until its group has been cycled through.
const recent = new Map<Mood, Set<number>>();

export function nextComment(mood: Mood): string {
  const group = COMMENTARY[mood];
  if (!group?.length) return "";
  let used = recent.get(mood);
  if (!used || used.size >= group.length) {
    used = new Set<number>();
    recent.set(mood, used);
  }
  const options = group.map((_, i) => i).filter((i) => !used!.has(i));
  const idx = options[Math.floor(Math.random() * options.length)];
  used.add(idx);
  return group[idx];
}
