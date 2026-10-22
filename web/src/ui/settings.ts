/** Saved monitor settings: one JSON object in localStorage. Storage can be missing or blocked
 * (private window, previews), so every access is in try/catch and the defaults always work. */

import * as P from "../myo/protocol";
import { DEFAULT_STREAMS } from "../osc/sender";
import type { Quat } from "../myo/protocol";
import type { View } from "./orientation";

export interface Settings {
  relayUrl: string;
  send: boolean;
  streams: Record<string, boolean>;
  imuRateHz: number;
  rmsRateHz: number;
  rmsWindowMs: number;
  zeroMode: "yaw" | "full";
  tapThresholdG: number;
  tapCooldownMs: number;
  doubleTapOrigin: boolean;
  emgMode: number;
  imuMode: number;
  classifierMode: number;
  neverSleep: boolean;
  vibrateOnConnect: boolean;
  unlockOnSync: boolean;
  view: View;
  flip: boolean;
  emgWindowS: number;
  emgScale: number;
  emgAuto: boolean;
  imuWindowS: number;
  origins: Record<string, Quat>; // per armband address
}

export const defaults = (): Settings => ({
  relayUrl: "ws://127.0.0.1:8765",
  send: false,
  streams: { ...DEFAULT_STREAMS },
  imuRateHz: 50,
  rmsRateHz: 50,
  rmsWindowMs: 50,
  zeroMode: "yaw",
  tapThresholdG: 0,
  tapCooldownMs: 0,
  doubleTapOrigin: false,
  emgMode: P.EmgMode.RAW,
  imuMode: P.ImuMode.ALL,
  classifierMode: P.ClassifierMode.ENABLED,
  neverSleep: true,
  vibrateOnConnect: true,
  unlockOnSync: true,
  view: "behind",
  flip: false,
  emgWindowS: 2,
  emgScale: 64,
  emgAuto: false,
  imuWindowS: 5,
  origins: {},
});

const KEY = "osa-myo-web.settings.v1";

export function load(): Settings {
  const s = defaults();
  try {
    const raw = localStorage.getItem(KEY);
    if (!raw) return s;
    const saved = JSON.parse(raw) as Partial<Settings>;
    for (const k of Object.keys(s) as Array<keyof Settings>) {
      const v = saved[k];
      if (v !== undefined && typeof v === typeof s[k]) (s as unknown as Record<string, unknown>)[k] = v;
    }
    s.streams = { ...DEFAULT_STREAMS, ...(saved.streams ?? {}) };
  } catch {
    /* no storage: defaults */
  }
  return s;
}

export function save(s: Settings): void {
  try {
    localStorage.setItem(KEY, JSON.stringify(s));
  } catch {
    /* no storage: the settings last until the page closes */
  }
}
