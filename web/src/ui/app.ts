/** The monitor: one armband, its streams on screen, OSC through the relay. The page markup is in
 * index.html; this file wires it to a Bridge (Web Bluetooth or the simulator). */

import * as P from "../myo/protocol";
import { Bridge, type LogEntry } from "../bridge";
import { errText, type DeviceState } from "../myo/device";
import { MockTransport } from "../myo/mock";
import type { Transport } from "../myo/transport";
import { WebBluetoothTransport, webBluetoothProblem } from "../myo/webbluetooth";
import { RelayClient, type RelayState } from "../osc/relay";
import { DEFAULT_STREAMS } from "../osc/sender";
import * as C from "../credits";
import { ArmView, VIEWS, VIEW_HELP, type View } from "./orientation";
import { Bars, History, Strip, autoRange } from "./plots";
import { palette } from "./theme";
import * as S from "./settings";

const $ = <T extends HTMLElement = HTMLElement>(id: string) => document.getElementById(id) as T;

function el<K extends keyof HTMLElementTagNameMap>(tag: K, cls = "", text = ""): HTMLElementTagNameMap[K] {
  const e = document.createElement(tag);
  if (cls) e.className = cls;
  if (text) e.textContent = text;
  return e;
}

// EMG sources, as gui/widgets/emg_grid.py
interface Source { rate: number; scales: number[]; autoMin: number; signed: boolean }
const SOURCES: Record<"emg" | "fv", Source> = {
  emg: { rate: P.EMG_SAMPLE_RATE_HZ, scales: [2, 4, 8, 16, 32, 64, 128], autoMin: 2, signed: true },
  fv: { rate: 50, scales: [16, 32, 64, 128, 256, 512, 1024, 2048], autoMin: 16, signed: false },
};

const TILE_POSES = [P.Pose.FIST, P.Pose.WAVE_IN, P.Pose.WAVE_OUT, P.Pose.FINGERS_SPREAD, P.Pose.DOUBLE_TAP];
const POSE_NAMES: Record<number, string> = {
  [P.Pose.FIST]: "FIST", [P.Pose.WAVE_IN]: "WAVE IN", [P.Pose.WAVE_OUT]: "WAVE OUT",
  [P.Pose.FINGERS_SPREAD]: "SPREAD", [P.Pose.DOUBLE_TAP]: "2× TAP",
};
// line pictograms on a 24 grid, 1.5 stroke, round caps (gui/widgets/pose_feed.py)
const spread = [-160, -125, -90, -55, -20].map((d) => {
  const a = (d * Math.PI) / 180, c = Math.cos(a), s = Math.sin(a);
  return `<line x1="${(12 + c * 5).toFixed(2)}" y1="${(15 + s * 5).toFixed(2)}" x2="${(12 + c * 9.4).toFixed(2)}" y2="${(15 + s * 9.4).toFixed(2)}"/>`;
}).join("");
const GLYPHS: Record<number, string> = {
  [P.Pose.FIST]: `<rect x="6" y="7" width="12" height="10" rx="3"/><line x1="9" y1="7" x2="9" y2="10.3"/><line x1="12" y1="7" x2="12" y2="10.3"/><line x1="15" y1="7" x2="15" y2="10.3"/>`,
  [P.Pose.FINGERS_SPREAD]: `<circle cx="12" cy="15" r="3.3"/>${spread}`,
  [P.Pose.WAVE_IN]: `<path d="M18.6 15.9Q13.1 7 6 11.4"/><line x1="6" y1="11.4" x2="9.5" y2="9"/><line x1="6" y1="11.4" x2="7.9" y2="14.7"/>`,
  [P.Pose.WAVE_OUT]: `<path d="M5.4 15.9Q10.9 7 18 11.4"/><line x1="18" y1="11.4" x2="14.5" y2="9"/><line x1="18" y1="11.4" x2="16.1" y2="14.7"/>`,
  [P.Pose.DOUBLE_TAP]: `<circle cx="8.6" cy="12" r="1.5" fill="currentColor" stroke="none"/><circle cx="15.4" cy="12" r="1.5" fill="currentColor" stroke="none"/><circle cx="8.6" cy="12" r="3.6" stroke-width="1"/><circle cx="15.4" cy="12" r="3.6" stroke-width="1"/>`,
};

// slot dot colour per state (widgets/device_list.py DOT)
const DOT: Record<DeviceState, string> = {
  disconnected: "--ui-ghost", connecting: "--ui-amber", connected: "--ui-cyan", streaming: "--ui-ok",
  reconnecting: "--ui-copper",
};

const pad = (n: number, w = 2) => String(n).padStart(w, "0");
const clock = (d: Date) => `${pad(d.getHours())}:${pad(d.getMinutes())}:${pad(d.getSeconds())}`;
const short = (n: number) => (n >= 1e6 ? `${(n / 1e6).toFixed(1)}M` : n >= 1e4 ? `${Math.round(n / 1000)}k` : String(n));

/** JSON as Python's json.dumps(separators=(", ", ": ")) writes it, like the app's event log. */
const pyJson = (v: unknown): string =>
  Array.isArray(v) ? `[${v.map(pyJson).join(", ")}]`
  : v !== null && typeof v === "object"
    ? `{${Object.entries(v).map(([k, x]) => `${JSON.stringify(k)}: ${pyJson(x)}`).join(", ")}}`
    : JSON.stringify(v) ?? String(v);

const fmt = (v: number, digits: number, width = 0) => {
  const s = (v >= 0 ? "+" : "") + v.toFixed(digits);
  return width ? s.padStart(width) : s;
};

export class App {
  private settings = S.load();
  private relay = new RelayClient(this.settings.relayUrl);
  private bridge: Bridge | null = null;
  private transport: Transport | null = null;
  private mock: MockTransport | null = null;
  private lastFvT = 0;
  private poseT = new Map<number, number>();
  private elbow: boolean | null = null; // last x_direction from a sync
  private emg = { source: "emg" as "emg" | "fv", paused: false, ranges: new Array(8).fill(64) as number[] };
  private lastSlow = 0;
  private eventCount = 0;
  private kitApp = false; // served by the test kit's app
  private logLines: string[] = []; // everything, for SAVE LOG (the box on screen keeps 400)
  private lastStatsLine = 0;
  private linkHist: number[] = []; // LINK panel: % of the expected packets, one per second
  private lastLinkT = 0;
  private lastBatt: number | null = null;
  private frameT: number[] = []; // for the GUI FPS in the status bar

  private arm = new ArmView($<HTMLCanvasElement>("cv-arm"));
  private gyro = new Strip($<HTMLCanvasElement>("cv-gyro"));
  private accel = new Strip($<HTMLCanvasElement>("cv-accel"));
  private quat = new Strip($<HTMLCanvasElement>("cv-quat"));
  private bars = new Bars($<HTMLCanvasElement>("cv-bars"));
  private link = new History($<HTMLCanvasElement>("cv-link"));
  private pods: Strip[] = [];
  private tiles = new Map<number, HTMLElement>();

  start(): void {
    if (matchMedia("(pointer: coarse)").matches) document.documentElement.dataset.density = "touch";
    this.buildStatic();
    this.wireTop();
    this.wireControls();
    this.wireSettings();
    this.buildAbout();
    this.applyRelay();
    const problem = webBluetoothProblem();
    if (problem) {
      const b = $("problem");
      b.textContent = `Web Bluetooth is not available: ${problem}. DEMO still works.`;
      b.hidden = false; // slow() keeps CONNECT disabled
    }
    void this.kit();
    this.slow(true);
    const frame = () => {
      this.draw();
      requestAnimationFrame(frame);
    };
    requestAnimationFrame(frame);
  }

  private save(): void {
    S.save(this.settings);
  }

  // ------------------------------------------------------------------ static parts
  private buildStatic(): void {
    const view = $<HTMLSelectElement>("sel-view");
    for (const v of VIEWS) view.append(new Option(v.toUpperCase(), v));
    view.value = this.settings.view;
    this.arm.view = this.settings.view;
    view.title = VIEW_HELP[this.settings.view];
    view.onchange = () => {
      this.settings.view = this.arm.view = view.value as View;
      view.title = VIEW_HELP[this.arm.view];
      this.save();
    };
    const flip = $("btn-flip");
    flip.classList.toggle("on", this.settings.flip);
    flip.onclick = () => {
      this.settings.flip = !this.settings.flip;
      flip.classList.toggle("on", this.settings.flip);
      this.save();
    };

    for (const legend of document.querySelectorAll<HTMLElement>(".legend")) {
      [...(legend.dataset.axes ?? "")].forEach((a, i) => {
        const s = el("span", `lbl ax${i}`, a.toUpperCase());
        legend.append(s);
      });
    }

    const tiles = $("tiles");
    for (const pose of TILE_POSES) {
      const t = el("div", "tile");
      t.innerHTML = `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">${GLYPHS[pose]}</svg>`;
      t.append(el("span", "", POSE_NAMES[pose]));
      t.title = P.poseLabel(pose);
      tiles.append(t);
      this.tiles.set(pose, t);
    }

    const pods = $("pods");
    for (let i = 0; i < 8; i++) {
      const cv = el("canvas");
      cv.setAttribute("aria-label", `EMG pod ${i}`);
      pods.append(cv);
      this.pods.push(new Strip(cv));
    }
    this.fillEmgScales();

    const win = $<HTMLSelectElement>("sel-emg-window");
    win.value = String(this.settings.emgWindowS);
    win.onchange = () => {
      this.settings.emgWindowS = Number(win.value);
      this.save();
    };
    const iwin = $<HTMLSelectElement>("sel-imu-window");
    iwin.value = String(this.settings.imuWindowS);
    iwin.onchange = () => {
      this.settings.imuWindowS = Number(iwin.value);
      this.save();
    };
    const auto = $<HTMLInputElement>("ck-emg-auto");
    auto.checked = this.settings.emgAuto;
    auto.onchange = () => {
      this.settings.emgAuto = auto.checked;
      $<HTMLSelectElement>("sel-emg-scale").disabled = this.settings.emgAuto;
      this.emg.ranges.fill(this.scale());
      this.save();
    };
    $<HTMLSelectElement>("sel-emg-scale").disabled = this.settings.emgAuto;
    const pause = $("btn-emg-pause");
    pause.onclick = () => {
      this.emg.paused = !this.emg.paused;
      pause.textContent = this.emg.paused ? "RESUME" : "PAUSE";
      pause.classList.toggle("on", this.emg.paused);
    };
    $("btn-save-log").onclick = () => void this.saveLog();
    $("btn-events-clear").onclick = () => {
      for (const e of [...$("events").querySelectorAll(".ev")]) e.remove();
      this.eventCount = 0;
      $("events-empty").hidden = false;
    };
  }

  private scales: Record<"emg" | "fv", number> = { emg: this.settings.emgScale, fv: 1024 };
  private scale(): number {
    return this.scales[this.emg.source];
  }

  private fillEmgScales(): void {
    const sel = $<HTMLSelectElement>("sel-emg-scale");
    const src = SOURCES[this.emg.source];
    sel.replaceChildren(...src.scales.map((v) => new Option(src.signed ? `±${v}` : `0–${v}`, String(v))));
    const cur = src.scales.reduce((a, b) => (Math.abs(b - this.scale()) < Math.abs(a - this.scale()) ? b : a));
    sel.value = String(cur);
    this.scales[this.emg.source] = cur;
    sel.onchange = () => {
      this.scales[this.emg.source] = Number(sel.value);
      if (this.emg.source === "emg") {
        this.settings.emgScale = Number(sel.value);
        this.save();
      }
    };
    this.emg.ranges.fill(this.scale());
  }

  // ------------------------------------------------------------------ top bar: connect, relay
  private wireTop(): void {
    // CONNECT / DISCONNECT sit in the sidebar and in the Controls panel, as in the app
    for (const b of document.querySelectorAll<HTMLButtonElement>("[data-act=connect]"))
      b.onclick = () => {
        // the chooser must open straight from the click, before any await
        WebBluetoothTransport.request()
          .then((t) => this.connect(t))
          .catch((e) => this.message("warning", errText(e)));
      };
    for (const b of document.querySelectorAll<HTMLButtonElement>("[data-act=disconnect]"))
      b.onclick = () => {
        this.bridge?.device.disconnect().catch((e) => this.message("warning", errText(e)));
      };
    $("btn-demo").onclick = () => this.connect(new MockTransport({ posePeriodS: 4 }));

    const url = $<HTMLInputElement>("relay-url");
    url.value = this.settings.relayUrl;
    const applyUrl = () => {
      this.settings.relayUrl = url.value.trim() || S.defaults().relayUrl;
      url.value = this.settings.relayUrl;
      this.save();
      this.applyRelay();
    };
    url.onchange = applyUrl;
    $("btn-relay-apply").onclick = applyUrl;
    const send = $<HTMLInputElement>("ck-send");
    send.onchange = () => {
      this.settings.send = send.checked;
      this.save();
      this.applyRelay();
    };
    this.relay.onState = (s) => this.relayState(s);
    this.relay.onControl = (m) => {
      this.bridge?.control(m).catch((e) => this.message("warning", errText(e)));
    };
    $("btn-settings").onclick = () => this.openSettings();
    $("btn-about").onclick = $("wordmark").onclick = () => $<HTMLDialogElement>("dlg-about").showModal();
  }

  private applyRelay(): void {
    $<HTMLInputElement>("ck-send").checked = this.settings.send;
    if (this.settings.send) this.relay.start(this.settings.relayUrl);
    else this.relay.stop();
    this.applyOsc();
    this.relayState(this.relay.state);
  }

  private relayState(s: RelayState): void {
    const lamp = $("relay-state");
    lamp.dataset.state = s;
    lamp.textContent = { off: "OFF", connecting: "…", open: "OPEN", closed: "NO RELAY" }[s];
    lamp.title = s === "closed" ? "No relay at this address: start it (npm run relay in web/, or the test kit's launcher)" : "";
  }

  private applyOsc(): void {
    const b = this.bridge;
    if (!b) return;
    const s = this.settings;
    b.osc.setSink(s.send ? this.relay.send : null);
    b.osc.streams = { ...DEFAULT_STREAMS, ...s.streams };
    b.osc.setRates(s.imuRateHz, s.rmsRateHz);
  }

  // ------------------------------------------------------------------ connection
  private async connect(transport: Transport): Promise<void> {
    if (this.bridge && this.bridge.device.state !== "disconnected") return;
    const s = this.settings;
    this.transport = transport;
    this.mock = transport instanceof MockTransport ? transport : null;
    const b = new Bridge(transport, {
      device: {
        emgMode: s.emgMode as P.EmgModeValue, imuMode: s.imuMode as P.ImuModeValue,
        classifierMode: s.classifierMode as P.ClassifierModeValue, neverSleep: s.neverSleep,
        vibrateOnConnect: s.vibrateOnConnect, unlockOnSync: s.unlockOnSync,
      },
      processing: {
        rmsWindowMs: s.rmsWindowMs, zeroMode: s.zeroMode, tapThresholdG: s.tapThresholdG, tapCooldownMs: s.tapCooldownMs,
      },
      doubleTapOrigin: s.doubleTapOrigin,
    });
    this.bridge = b;
    this.elbow = null;
    this.poseT.clear();
    this.linkHist = [];
    this.lastBatt = null;
    const saved = s.origins[transport.address];
    if (saved) b.processor.reference.setReference(saved);
    b.onZero = (ref) => {
      if (ref) s.origins[transport.address] = ref;
      else delete s.origins[transport.address];
      this.save();
    };
    b.onLog = (e) => this.addEvent(e);
    b.device.onFv.connect((_p, t) => (this.lastFvT = t));
    b.device.onClassifier.connect((ev, t) => {
      if (ev.type === P.ClassifierEventType.POSE) this.poseT.set(ev.pose, t);
    });
    b.device.onState.connect(() => this.slow(true));
    this.applyOsc();
    for (const e of document.querySelectorAll<HTMLElement>(".demo-only")) e.hidden = !this.mock;
    $("badge-sim").hidden = !this.mock;
    this.message("info", `${this.mock ? "demo: simulated armband" : "connecting"} ${transport.address}`);
    try {
      await b.device.connect();
    } catch (e) {
      this.message("error", `connect failed: ${errText(e)}`);
    }
    this.slow(true);
  }

  private message(kind: string, text: string): void {
    if (this.bridge) this.bridge.emit(kind, text);
    else this.addEvent({ t: performance.now() / 1000, kind, text });
  }

  // ------------------------------------------------------------------ controls panel
  private wireControls(): void {
    const dev = () => this.bridge?.device;
    const run = (p: Promise<unknown> | undefined) => p?.catch((e) => this.message("warning", errText(e)));
    $("btn-unlock").onclick = () => run(dev()?.unlock(P.UnlockType.HOLD));
    $("btn-lock").onclick = () => run(dev()?.lock());
    for (const b of document.querySelectorAll<HTMLElement>("[data-vibrate]"))
      b.onclick = () => {
        const kind = Number(b.dataset.vibrate);
        run(dev()?.vibrate(kind)?.then(() => this.message("log", `vibrate ${b.textContent?.toLowerCase()}`)));
      };
    $("btn-origin").onclick = () => this.bridge?.zero();
    $("btn-origin-clear").onclick = () => this.bridge?.clearZero();
    $("btn-resync").onclick = () => run(dev()?.resync());
    $("btn-poweroff").onclick = () => {
      if (confirm("Switch the armband off? It stays off until it is plugged into USB power.")) run(dev()?.powerOff());
    };

    const modes = [["sel-emg", "emgMode"], ["sel-imu", "imuMode"], ["sel-cls", "classifierMode"]] as const;
    for (const [id, key] of modes) {
      const sel = $<HTMLSelectElement>(id);
      sel.value = String(this.settings[key]);
      sel.onchange = () => {
        this.settings[key] = Number(sel.value);
        this.save();
        const d = dev();
        if (d && d.transport.isConnected) run(d.setMode(this.settings.emgMode, this.settings.imuMode, this.settings.classifierMode));
      };
    }
    const sleep = $("btn-sleep");
    const showSleep = (on: boolean) => {
      sleep.classList.toggle("on", on);
      sleep.textContent = on ? "NEVER SLEEP" : "NORMAL SLEEP";
    };
    showSleep(this.settings.neverSleep);
    sleep.onclick = () => {
      const on = (this.settings.neverSleep = !this.settings.neverSleep);
      showSleep(on);
      this.save();
      const d = dev();
      if (d) {
        d.config.neverSleep = on;
        if (d.transport.isConnected) run(d.setSleepMode(on ? P.SleepMode.NEVER_SLEEP : P.SleepMode.NORMAL));
      }
    };

    const tapOrigin = $("btn-tap-origin");
    tapOrigin.classList.toggle("on", this.settings.doubleTapOrigin);
    tapOrigin.onclick = () => {
      const on = (this.settings.doubleTapOrigin = !this.settings.doubleTapOrigin);
      tapOrigin.classList.toggle("on", on);
      if (this.bridge) this.bridge.doubleTapOrigin = on;
      this.save();
    };

    $("btn-sim-tap").onclick = () => this.mock?.triggerTap(1.2);
    $("btn-sim-loss").onclick = () => this.mock?.simulateLinkLoss();
  }

  // ------------------------------------------------------------------ settings dialog
  private wireSettings(): void {
    const s = this.settings;
    const box = $("streams");
    for (const key of Object.keys(DEFAULT_STREAMS)) {
      const b = el("button", "ui-btn ui-toggle compact", key);
      b.type = "button";
      b.title = `/myo/1/${key.replace("_", "/")}`;
      b.classList.toggle("on", !!s.streams[key]);
      b.onclick = () => {
        s.streams[key] = !s.streams[key];
        b.classList.toggle("on", s.streams[key]);
        this.save();
        this.applyOsc();
      };
      box.append(b);
    }
    const num = (id: string, get: () => number, set: (v: number) => void) => {
      const i = $<HTMLInputElement>(id);
      i.value = String(get());
      i.onchange = () => {
        const v = Number(i.value);
        if (!Number.isFinite(v) || v < Number(i.min) || v > Number(i.max)) {
          i.value = String(get());
          return;
        }
        set(v);
        this.save();
      };
    };
    num("in-imu-rate", () => s.imuRateHz, (v) => { s.imuRateHz = v; this.applyOsc(); });
    num("in-rms-rate", () => s.rmsRateHz, (v) => { s.rmsRateHz = v; this.applyOsc(); });
    num("in-rms", () => s.rmsWindowMs, (v) => { s.rmsWindowMs = v; this.bridge?.processor.setRmsWindowMs(v); });
    num("in-tap-g", () => s.tapThresholdG, (v) => { s.tapThresholdG = v; this.bridge?.processor.setTapFilter(v, s.tapCooldownMs); });
    num("in-tap-ms", () => s.tapCooldownMs, (v) => { s.tapCooldownMs = v; this.bridge?.processor.setTapFilter(s.tapThresholdG, v); });
    const zero = $<HTMLSelectElement>("sel-zero");
    zero.value = s.zeroMode;
    zero.onchange = () => {
      s.zeroMode = zero.value as "yaw" | "full";
      this.bridge?.processor.setZeroMode(s.zeroMode);
      this.save();
    };
    const toggle = (id: string, key: "vibrateOnConnect" | "unlockOnSync") => {
      const b = $(id);
      b.classList.toggle("on", s[key]);
      b.onclick = () => {
        s[key] = !s[key];
        b.classList.toggle("on", s[key]);
        this.save();
      };
    };
    toggle("btn-vib-connect", "vibrateOnConnect");
    toggle("btn-unlock-sync", "unlockOnSync");
  }

  private openSettings(): void {
    $<HTMLDialogElement>("dlg-settings").showModal();
  }

  private buildAbout(): void {
    const body = $("about-body");
    const head = el("div", "about-head");
    const img = el("img");
    img.src = "./icon.png";
    img.alt = "";
    const wm = el("div");
    const mark = el("div", "ui-wordmark");
    mark.append(el("span", "wm-osa", "OSA"), " ", el("span", "wm-name", "MYO Controller"));
    wm.append(mark, el("p", "ui-label-txt", `web · version ${C.VERSION} · build ${__BUILD__} · ${C.TAGLINE}`));
    head.append(img, wm);
    body.append(head);

    const who = el("section");
    who.append(el("p", "ui-body", `By ${C.AUTHORS.join(" and ")}.`), el("p", "ui-body-sm", C.COPYRIGHT));
    const a = el("a", "", C.CONTACT);
    a.href = C.CONTACT_URL;
    a.target = "_blank";
    a.rel = "noopener";
    who.append(a);
    body.append(who);

    const list = (title: string, items: C.Credit[]) => {
      const sec = el("section");
      sec.append(el("h3", "ui-eyebrow", title));
      const ul = el("ul", "credits");
      for (const c of items) {
        const li = el("li");
        const link = el("a", "", c.name);
        link.href = c.url;
        link.target = "_blank";
        link.rel = "noopener";
        li.append(link, el("span", "lic", c.licence), el("span", "what", c.what));
        ul.append(li);
      }
      sec.append(ul);
      body.append(sec);
    };
    list("Built on the work of", C.SOURCES);
    list("Libraries and tools", C.LIBRARIES);
    list("Fonts", C.FONTS);
    const end = el("section");
    end.append(el("p", "ui-caption", C.DISCLAIMER));
    body.append(end);
  }

  // ------------------------------------------------------------------ events
  /** One line of the event box, as the app's EventFeed: time, band, kind, JSON payload. */
  private addEvent(e: LogEntry): void {
    const box = $("events");
    const d = new Date();
    const ts = `${clock(d)}.${pad(d.getMilliseconds(), 3)}`;
    const data = e.data && Object.keys(e.data).length ? e.data : null;
    const body = data ? pyJson(data) : e.text;
    const line = el("div", "ev");
    const kind = el("span", "k", e.kind);
    if (e.kind === "error" || e.kind === "warning") kind.classList.add("bad");
    else if (data && "ignored" in data) kind.className = "ig";
    const what = el("span", "w");  // kind and body wrap together in the last column
    what.append(kind, " ", el("span", "x", body));
    line.append(el("span", "t", ts), el("span", "m", "myo1"), what);
    line.title = e.text;
    this.logLine(`${e.kind}  ${e.text}${data ? `  ${body}` : ""}`, d);
    const atEnd = box.scrollHeight - box.scrollTop - box.clientHeight < 24;
    box.append(line);
    if (++this.eventCount > 400) box.querySelector(".ev")?.remove();
    if (atEnd) box.scrollTop = box.scrollHeight;
    $("events-empty").hidden = true;
  }

  /** Served by the test kit's app (kit/launcher.mjs): tell it this page is open (it quits a few
   * seconds after the last one closes), show the OSC MONITOR button, add its log to SAVE LOG. */
  private async kit(): Promise<void> {
    try {
      const k = (await (await fetch("__kit", { cache: "no-store" })).json()) as Record<string, string>;
      if (k.app !== "osa-myo-web-kit") return;
      new EventSource("__alive");
      $("btn-monitor").hidden = false;
      this.kitApp = true;
      this.logLine(`kit app build ${k.build}, relay ${k.relay} ${k.relayUrl}, OSC to ${k.osc}`);
      if (k.relayUrl && k.relayUrl !== this.settings.relayUrl) {
        // the kit's relay may not be on the default port: follow it
        this.settings.relayUrl = k.relayUrl;
        $<HTMLInputElement>("relay-url").value = k.relayUrl;
        this.save();
        this.applyRelay();
      }
    } catch {
      // not the kit (dev server, a web host): nothing to do
    }
  }

  private logLine(text: string, d = new Date()): void {
    this.logLines.push(`${clock(d)}.${pad(d.getMilliseconds(), 3)}  ${text}`);
    if (this.logLines.length > 20000) this.logLines.splice(0, this.logLines.length - 20000);
  }

  /** The whole session as a text file, for test reports: build, browser, band, settings, events
   * and a stats line every 10 s. */
  private async saveLog(): Promise<void> {
    const d = this.bridge?.device;
    const now = new Date();
    const head = [
      `OSA MYO Controller web ${C.VERSION} build ${__BUILD__}`,
      `saved ${now.toString()}`,
      `browser ${navigator.userAgent}`,
      `page ${location.origin}`,
      `band ${d ? `${d.name ?? "?"} address=${d.address || "?"} serial=${d.info ? P.serialString(d.info) : "?"} ` +
        `firmware=${d.firmware ? P.firmwareString(d.firmware) : "?"} state=${d.state}` : "none"}`,
      `simulated ${this.mock ? "yes" : "no"}`,
      `settings ${JSON.stringify({ ...this.settings, origins: Object.keys(this.settings.origins) })}`,
      "",
    ];
    const tail: string[] = [];
    if (this.kitApp) {
      try {
        tail.push("", "---- kit app log", (await (await fetch("__log", { cache: "no-store" })).text()).trimEnd());
      } catch {
        tail.push("", "---- kit app log: not reachable (the app has quit?)");
      }
    }
    const blob = new Blob([[...head, ...this.logLines, ...tail, ""].join("\n")], { type: "text/plain" });
    const a = el("a");
    a.download = `osa-myo-web-log-${now.getFullYear()}${pad(now.getMonth() + 1)}${pad(now.getDate())}-` +
      `${pad(now.getHours())}${pad(now.getMinutes())}${pad(now.getSeconds())}.txt`;
    a.href = URL.createObjectURL(blob);
    a.click();
    setTimeout(() => URL.revokeObjectURL(a.href), 1000);
  }

  // ------------------------------------------------------------------ readouts (10 Hz)
  private slow(force = false): void {
    const now = performance.now() / 1000;
    if (!force && now - this.lastSlow < 0.1) return;
    this.lastSlow = now;
    const b = this.bridge, d = b?.device;
    const state: DeviceState = d?.state ?? "disconnected";
    const linked = state === "streaming";
    const live = linked || state === "connected";
    const text = (id: string, v: string) => {
      const e = $(id);
      if (e.textContent !== v) e.textContent = v;
      return e;
    };
    /** Pill: null = off (ghost), true = cyan, false = copper (theme.Pill). */
    const pill = (id: string, on: boolean | null, v?: string) => {
      const e = v === undefined ? $(id) : text(id, v);
      e.classList.toggle("on", on === true);
      e.classList.toggle("warn", on === false);
    };

    // device header (HeaderStrip)
    text("v-status", state.toUpperCase()).dataset.state = state;
    pill("v-sync", d && live ? d.synced : null, d?.synced ? "SYNCED" : "UNSYNCED");
    pill("v-lock", d && linked ? !d.locked : null, !d || d.locked ? "LOCKED" : "UNLOCKED");
    const arm = d && d.synced ? P.armLabel(d.arm) : "unknown";
    pill("arm-l", arm === "left" ? true : null);
    pill("arm-r", arm === "right" ? true : null);
    const xd = d ? P.xDirectionLabel(d.xDirection) : "unknown";
    text("v-arm", arm !== "unknown" ? `x → ${xd === "unknown" ? "—" : xd}` : "not on arm");
    const name = text("v-name", d?.name ?? "—");
    const addr = d?.address || this.transport?.address || "";
    name.title = [d?.name ? `Bluetooth name: ${d.name}` : "", addr ? `address: ${addr}` : ""].filter(Boolean).join("\n");
    text("v-serial", d?.info ? P.serialString(d.info) : "—");
    text("v-fw", d?.firmware ? P.firmwareShort(d.firmware) : "—").title = d?.firmware ? P.firmwareString(d.firmware) : "";

    // sidebar slot (SlotRow)
    const dot = $("s-dot");
    dot.style.setProperty("--led", `var(${DOT[state]})`);
    dot.classList.toggle("glow", linked);
    text("s-name", d?.name ?? "Myo 1");
    const batt = d?.battery ?? null;
    text("s-sub", state.toUpperCase() + (linked && batt !== null ? ` · ${batt}%` : "")).classList.toggle("live", state !== "disconnected");

    // buttons
    const busy = state !== "disconnected";
    for (const e of document.querySelectorAll<HTMLButtonElement>("[data-act=connect]")) e.disabled = busy || !!webBluetoothProblem();
    for (const e of document.querySelectorAll<HTMLButtonElement>("[data-act=disconnect]")) e.disabled = !busy;
    $<HTMLButtonElement>("btn-demo").disabled = busy;
    for (const e of document.querySelectorAll<HTMLButtonElement>("[data-needs=link]")) e.disabled = !linked;
    if (!d && this.mock === null) for (const e of document.querySelectorAll<HTMLElement>(".demo-only")) e.hidden = true;

    // modes reflect the band while linked (an OSC /mode can change them)
    if (d && linked) {
      const sync = (id: string, v: number) => {
        const s = $<HTMLSelectElement>(id);
        if (document.activeElement !== s && s.value !== String(v)) s.value = String(v);
      };
      sync("sel-emg", d.config.emgMode);
      sync("sel-imu", d.config.imuMode);
      sync("sel-cls", d.config.classifierMode);
    }
    for (const id of ["sel-emg", "sel-imu", "sel-cls"]) {
      const s = $<HTMLSelectElement>(id);
      s.title = s.selectedOptions[0]?.title ?? "";
    }

    // EMG source follows the band's mode
    const src = d && d.config.emgMode === P.EmgMode.SMOOTH ? "fv" : "emg";
    if (src !== this.emg.source) {
      this.emg.source = src;
      this.fillEmgScales();
    }
    text("cap-activity", src === "fv" ? "POD ACTIVITY · SMOOTH" : "POD ACTIVITY · RMS");

    // orientation
    if (d) {
      if (d.xDirection === P.XDirection.TOWARD_ELBOW) this.elbow = true;
      else if (d.xDirection === P.XDirection.TOWARD_WRIST) this.elbow = false;
      this.arm.setArm(d.synced ? P.armLabel(d.arm) : "unknown");
    }
    this.arm.towardElbow = !!this.elbow !== this.settings.flip;
    let band = this.elbow === null ? "band direction: not synced yet" : `band +x → ${this.elbow ? "elbow" : "wrist"} (sync)`;
    if (this.settings.flip) band += ", flipped";
    const hasOrigin = !!b?.processor.reference.reference;
    text("orient-hint", band + (hasOrigin ? "" : " · point at the screen, press SET ORIGIN"));
    $("btn-origin").classList.toggle("on", hasOrigin);

    const fr = b?.lastFrame;
    const imuLive = !!b && b.processor.imuLive(now, 0.5);
    if (fr && imuLive) {
      const deg = fr.euler.map((v) => (v * 180) / Math.PI);
      text("v-roll", `${fmt(deg[0], 1)}°`);
      text("v-pitch", `${fmt(deg[1], 1)}°`);
      text("v-yaw", `${fmt(deg[2], 1)}°`);
      const [w, x, y, z] = fr.quat;
      text("v-qx", fmt(x, 3));
      text("v-qy", fmt(y, 3));
      text("v-qz", fmt(z, 3));
      text("v-qw", fmt(w, 3));
    } else {
      for (const id of ["v-roll", "v-pitch", "v-yaw", "v-qx", "v-qy", "v-qz", "v-qw"]) text(id, "—");
    }

    // gesture
    const pose = d && linked ? d.pose : P.Pose.REST;
    const tilePose = linked && this.tiles.has(pose);
    text("v-pose", !d || !linked ? "—" : pose === P.Pose.REST ? "REST" : (POSE_NAMES[pose] ?? P.poseLabel(pose).replace(/_/g, " ")))
      .classList.toggle("on", tilePose);
    let gh = "";
    if (d && linked) {
      if (!d.config.classifierMode) gh = "pose detection is off (POSE in Controls)";
      else if (!d.synced) gh = "perform the sync gesture: wave out and hold";
      else if (d.locked) gh = "locked: double tap, or UNLOCK";
    }
    text("gesture-hint", gh);

    // battery panel
    text("b-pct", batt === null ? "—" : `${batt}%`);
    const fill = $("b-fill");
    fill.style.width = `${batt ?? 0}%`;
    fill.style.backgroundSize = batt ? `${10000 / batt}% 100%` : ""; // the spectrum spans the whole track
    fill.classList.toggle("bad", batt !== null && batt <= 20);
    if (batt !== this.lastBatt) {
      this.lastBatt = batt;
      text("b-checked", batt === null ? "not read yet" : `last checked ${clock(new Date())}`);
    }

    // link panel: Web Bluetooth has no RSSI, so the bars show the share of the expected packets
    const st = d?.stats;
    const fresh = (t: number) => linked && t > 0 && now - t < 1.5;
    const emgFresh = src === "fv" ? fresh(this.lastFvT) : fresh(st?.lastEmgT ?? 0);
    if (st && linked && now - this.lastLinkT >= 1) {
      this.lastLinkT = now;
      const m = d!.config;
      const pct = m.emgMode === P.EmgMode.SMOOTH ? st.fvRateHz / 50
        : m.emgMode ? st.emgRateHz / P.EMG_SAMPLE_RATE_HZ
        : m.imuMode && m.imuMode !== 2 ? st.imuRateHz / 50 : NaN;
      if (Number.isFinite(pct)) {
        this.linkHist.push(Math.round(Math.min(1, pct) * 100));
        if (this.linkHist.length > 60) this.linkHist.shift();
      }
    }
    this.link.draw(this.linkHist);
    text("l-pct", this.linkHist.length && linked ? `${this.linkHist[this.linkHist.length - 1]}%` : "—");
    text("l-emg", emgFresh && st ? (src === "fv" ? st.fvRateHz : st.emgRateHz).toFixed(0) : "—");
    text("l-imu", st && fresh(st.lastImuT) ? st.imuRateHz.toFixed(0) : "—");
    text("l-drop", st && linked ? String(st.emgDropped) : "—").classList.toggle("bad", !!st && linked && st.emgDropped > 0);
    text("l-osc", b && this.settings.send ? short(b.osc.sentMessages) : "—");

    // status bar: a message on the left, the counters on the right (as the app)
    let line = "";
    if (this.settings.send && this.relay.state === "closed") line = "OSC relay not running: start it (npm run relay in web/, or the test kit's launcher)";
    else if (b?.emgHint()) line = b.emgHint();
    else if (d && state === "reconnecting") line = "link lost, reconnecting…";
    else if (this.mock) line = "simulated armband: values are generated, not measured";
    text("sb-msg", line);
    const ft = this.frameT;
    const fps = ft.length > 10 ? (ft.length - 1) / (ft[ft.length - 1] - ft[0]) : 0;
    const relay = !this.settings.send ? "OFF" : this.relay.state === "open" ? "OPEN" : this.relay.state === "closed" ? "NO RELAY" : "…";
    text("sb-stats", `GUI ${fps.toFixed(0)} FPS    ·    RELAY ${this.settings.relayUrl.replace(/^wss?:\/\//, "")} ${relay}   ` +
      `MSGS ${b?.osc.sentMessages ?? 0}   PACKETS ${this.relay.sent}   DROPPED ${this.relay.dropped}    ·    CONTROL IN ${this.relay.received}`);

    if (st && linked && now - this.lastStatsLine >= 10) {
      this.lastStatsLine = now;
      this.logLine(`stats  emg=${(src === "fv" ? st.fvRateHz : st.emgRateHz).toFixed(1)}Hz imu=${st.imuRateHz.toFixed(1)}Hz ` +
        `drop=${st.emgDropped} battery=${d?.battery ?? "?"}% osc=${this.settings.send ? `${this.relay.state} ${b?.osc.sentPackets ?? 0}pkts` : "off"}`);
    }
  }

  // ------------------------------------------------------------------ plots (every frame)
  private draw(): void {
    const now = performance.now() / 1000;
    this.frameT.push(now);
    if (this.frameT.length > 120) this.frameT.splice(0, 60);
    this.slow();
    const b = this.bridge;
    const pal = palette();
    const d = b?.device;
    const linked = d?.state === "streaming";

    // poses: lit while held, and briefly after a transient one (double tap)
    for (const [pose, tile] of this.tiles) {
      const on = !!d && linked && (d.pose === pose || now - (this.poseT.get(pose) ?? -1e9) < 0.6);
      tile.classList.toggle("on", on);
    }

    const imuLive = !!b && b.processor.imuLive(now, 0.5);
    if (b?.lastFrame && imuLive) this.arm.q = b.lastFrame.quat;
    this.arm.live = imuLive;
    this.arm.draw();

    // IMU strips: fixed ranges as the app (widgets/imu_strips.py), left axis 36 px
    const iw = this.settings.imuWindowS;
    const imu = { rate: 50, windowS: iw, zero: true, axisW: 36 };
    const strips: [Strip, number, number[], "gyro" | "accel" | "quat"][] = [
      [this.gyro, 500, [0, 1, 2], "gyro"], [this.accel, 5, [0, 1, 2], "accel"], [this.quat, 1, [0, 1, 2, 3], "quat"],
    ];
    for (const [s, r, ch, key] of strips) {
      if (b) s.draw(b[key], { ...imu, min: -r, max: r, channels: ch, colors: pal.axis }, imuLive);
      else s.frame({ min: -r, max: r, zero: true, axisW: 36 });
    }

    const src = SOURCES[this.emg.source];
    const ring = b ? (this.emg.source === "fv" ? b.fv : b.emg) : null;
    const emgLive = !!b && (this.emg.source === "fv"
      ? now - this.lastFvT < 0.5
      : now - (d?.stats.lastEmgT ?? 0) < 0.5);
    if (!this.emg.paused) {
      const n = Math.round(this.settings.emgWindowS * src.rate);
      this.pods.forEach((p, ch) => {
        let r = this.scale();
        if (this.settings.emgAuto && ring) {
          r = this.emg.ranges[ch] = autoRange(ring, ch, n, this.emg.ranges[ch], src.autoMin, src.signed);
        }
        const tag = this.settings.emgAuto ? `POD ${ch}  ${src.signed ? "±" : "0–"}${r.toFixed(0)}` : `POD ${ch}`;
        const o = { min: src.signed ? -r : 0, max: r, zero: src.signed, tag, axisW: 32 };
        if (!ring) p.frame(o);
        else p.draw(ring, { ...o, rate: src.rate, windowS: this.settings.emgWindowS, channels: [ch], colors: [pal.copper], lineWidth: 1 }, emgLive);
      });
    }

    this.bars.draw(b && emgLive ? b.activity : new Array(8).fill(0), emgLive);
  }
}
