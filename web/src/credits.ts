/** Authors and credits, shown by the About panel. The same content as src/myo_bridge/credits.py
 * (tests/credits.test.ts keeps the authors and sources in step); the web build adds its own
 * tooling and leaves out the Python-only libraries of the macOS app. */

export const VERSION = "0.1.0";
export const AUTHORS = ["Daniele Fabris", "Simone Arganini"];
export const YEAR = 2026;
export const CONTACT = "www.oscillacreations.com";
export const CONTACT_URL = "https://www.oscillacreations.com";
export const COPYRIGHT = `© ${YEAR} ${AUTHORS.join(", ")}`;
export const TAGLINE = "Open-source project, MIT licence";

export interface Credit {
  name: string; // owner/project
  url: string;
  licence: string;
  what: string; // what this project owes it
}

const c = (name: string, url: string, licence: string, what: string): Credit => ({ name, url, licence, what });

// open implementations of the Myo protocol this bridge was written from (no code copied from GPL ones)
export const SOURCES: Credit[] = [
  c("thalmiclabs/myo-bluetooth", "https://github.com/thalmiclabs/myo-bluetooth", "Apache-2.0",
    "myohw.h: UUIDs, commands, data layouts, scale factors"),
  c("PerlinWarp/pyomyo", "https://github.com/PerlinWarp/pyomyo", "MIT",
    "BLED112 dongle commands, EMG modes, never-sleep and restore"),
  c("Crimson-Crow/pymyo", "https://github.com/Crimson-Crow/pymyo", "MIT",
    "bleak reference: mode payload, IMU / EMG / classifier formats, smooth EMG"),
  c("jshahbazi/FreeMyo.py", "https://github.com/jshahbazi/FreeMyo.py", "MIT",
    "macOS specifics and troubleshooting"),
  c("iomz/dl-myo", "https://github.com/iomz/dl-myo", "GPL-3.0",
    "protocol knowledge only (GATT table, motion events); no code reused"),
  c("francesco-di-maggio/pyomyosc", "https://github.com/francesco-di-maggio/pyomyosc", "MIT",
    "OSC namespace and control messages"),
  c("balandinodidonato/MyoMapper", "https://github.com/balandinodidonato/MyoMapper", "MIT-style",
    "the myomapper OSC preset"),
  c("balandinodidonato/MyoToolkit", "https://github.com/balandinodidonato/MyoToolkit", "n/a",
    "pointers to the Myo OSC tools"),
  c("samyk/myo-osc", "https://github.com/samyk/myo-osc", "unstated", "historical OSC layout"),
  c("francocruces/MioConnect", "https://github.com/francocruces/MioConnect", "MIT",
    "several bands at once: clean-up, retries, command spacing"),
  c("cortinico/myonnaise", "https://github.com/cortinico/myonnaise", "MIT",
    "confirmation of the commands, keep-alive"),
];

// the web version has no runtime libraries: these build and test it
export const LIBRARIES: Credit[] = [
  c("Web Bluetooth API", "https://webbluetoothcg.github.io/web-bluetooth/", "W3C CG", "Bluetooth LE in the browser"),
  c("TypeScript", "https://www.typescriptlang.org", "Apache-2.0", "language"),
  c("Vite", "https://vite.dev", "MIT", "build"),
  c("Vitest", "https://vitest.dev", "MIT", "tests"),
  c("Node.js", "https://nodejs.org", "MIT", "the OSC relay"),
];

export const FONTS: Credit[] = [
  c("Sora, Archivo, IBM Plex Mono, Newsreader", "https://openfontlicense.org", "SIL OFL 1.1", "type, bundled in the page"),
];

export const DISCLAIMER = "Myo is a trademark of Thalmic Labs / North. Not affiliated with or endorsed by them; " +
  "no Thalmic SDK code or assets are included.";
