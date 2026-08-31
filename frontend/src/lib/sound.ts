// Short WebAudio alert tones. No audio files, no network. Browsers require a
// user gesture before audio plays, so unlock() is called from the first click.

const KEY = "bitcoin-terminal-sound";

let ctx: AudioContext | null = null;

export const isSoundOn = (): boolean =>
  typeof localStorage !== "undefined" && localStorage.getItem(KEY) !== "off";

export const setSoundOn = (on: boolean): void => {
  if (typeof localStorage !== "undefined") localStorage.setItem(KEY, on ? "on" : "off");
};

function audio(): AudioContext | null {
  if (typeof window === "undefined") return null;
  const Ctor = window.AudioContext ?? (window as unknown as { webkitAudioContext?: typeof AudioContext }).webkitAudioContext;
  if (!Ctor) return null;
  if (!ctx) ctx = new Ctor();
  return ctx;
}

export function unlockAudio(): void {
  const a = audio();
  if (a && a.state === "suspended") void a.resume();
}

function tone(freq: number, start: number, duration: number, gain = 0.14): void {
  const a = audio();
  if (!a) return;
  const osc = a.createOscillator();
  const vol = a.createGain();
  osc.type = "sine";
  osc.frequency.value = freq;
  vol.gain.setValueAtTime(0.0001, a.currentTime + start);
  vol.gain.exponentialRampToValueAtTime(gain, a.currentTime + start + 0.012);
  vol.gain.exponentialRampToValueAtTime(0.0001, a.currentTime + start + duration);
  osc.connect(vol).connect(a.destination);
  osc.start(a.currentTime + start);
  osc.stop(a.currentTime + start + duration + 0.02);
}

function play(notes: [number, number, number][]): void {
  if (!isSoundOn()) return;
  unlockAudio();
  notes.forEach(([freq, start, dur]) => tone(freq, start, dur));
}

/** Rising two-tone: a position was opened. */
export const beepEntry = (): void => play([[660, 0, 0.1], [990, 0.11, 0.14]]);

/** Bright rising triad: target hit. */
export const beepProfit = (): void =>
  play([[784, 0, 0.09], [1046, 0.1, 0.09], [1318, 0.2, 0.18]]);

/** Low descending pair: stop hit. */
export const beepLoss = (): void => play([[330, 0, 0.14], [220, 0.15, 0.24]]);

/** Neutral single blip: timed out / manual / flat close. */
export const beepNeutral = (): void => play([[520, 0, 0.16]]);
