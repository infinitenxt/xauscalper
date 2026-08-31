// Browser text-to-speech via the Web Speech API. No API key, no network calls.
// A tiny queue keeps announcements in order instead of cutting each other off.

const KEY = "bitcoin-terminal-speech";

export const speechSupported = (): boolean =>
  typeof window !== "undefined" && "speechSynthesis" in window;

export const isSpeechOn = (): boolean => {
  if (typeof localStorage === "undefined") return false;
  return localStorage.getItem(KEY) === "on";
};

export const setSpeechOn = (on: boolean): void => {
  if (typeof localStorage !== "undefined") localStorage.setItem(KEY, on ? "on" : "off");
  if (!on) cancelSpeech();
};

let rate = 1.05;

export const setSpeechRate = (value: number): void => {
  rate = Math.max(0.5, Math.min(2, value));
};

export const getSpeechRate = (): number => rate;

function pickVoice(): SpeechSynthesisVoice | null {
  if (!speechSupported()) return null;
  const voices = window.speechSynthesis.getVoices();
  if (!voices.length) return null;
  const preferred = ["Google UK English Male", "Daniel", "Google US English", "Samantha"];
  for (const name of preferred) {
    const hit = voices.find((v) => v.name === name);
    if (hit) return hit;
  }
  return voices.find((v) => v.lang.startsWith("en")) ?? voices[0];
}

// Strip characters that make a screen-reader voice stumble.
function clean(text: string): string {
  return text
    .replace(/[·•]/g, ",")
    .replace(/&/g, " and ")
    .replace(/%/g, " percent")
    .replace(/R:R/gi, "reward to risk")
    .replace(/\+DI/g, "plus D I")
    .replace(/-DI/g, "minus D I")
    .replace(/\bATR\b/g, "A T R")
    .replace(/\bADX\b/g, "A D X")
    .replace(/\bRSI\b/g, "R S I")
    .replace(/\bMACD\b/g, "mac dee")
    .replace(/\bVWAP\b/g, "V W A P")
    .replace(/\bEMA(\d+)\b/g, "E M A $1")
    .replace(/\bSL\b/g, "stop loss")
    .replace(/\bTP\b/g, "take profit")
    .replace(/\bP&L\b/gi, "profit and loss")
    .replace(/\s+/g, " ")
    .trim();
}

export function cancelSpeech(): void {
  if (speechSupported()) window.speechSynthesis.cancel();
}

/** True while something is being spoken or is queued. */
export function isSpeaking(): boolean {
  if (!speechSupported()) return false;
  return window.speechSynthesis.speaking || window.speechSynthesis.pending;
}

/** Speak one or more lines in order. Silently no-ops when muted/unsupported. */
export function speak(lines: string | string[], opts: { force?: boolean } = {}): void {
  if (!speechSupported()) return;
  if (!opts.force && !isSpeechOn()) return;
  const list = (Array.isArray(lines) ? lines : [lines]).map(clean).filter(Boolean);
  if (!list.length) return;
  const voice = pickVoice();
  for (const line of list) {
    const utter = new SpeechSynthesisUtterance(line);
    utter.rate = rate;
    utter.pitch = 1;
    utter.volume = 1;
    if (voice) utter.voice = voice;
    window.speechSynthesis.speak(utter);
  }
}

/** Interrupt whatever is queued and say this instead. */
export function speakNow(lines: string | string[]): void {
  cancelSpeech();
  speak(lines, { force: true });
}

// Voice lists load asynchronously in Chrome; warm them up once.
if (speechSupported()) {
  window.speechSynthesis.getVoices();
  window.speechSynthesis.addEventListener?.("voiceschanged", () => pickVoice());
}
