// The web credits must say what src/myo_bridge/credits.py says.
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { expect, it } from "vitest";
import * as C from "../src/credits";

const py = readFileSync(fileURLToPath(new URL("../../src/myo_bridge/credits.py", import.meta.url)), "utf8");
const block = (name: string) => py.slice(py.indexOf(`${name} = (`), py.indexOf("\n)\n", py.indexOf(`${name} = (`)));
const credits = (src: string) => [...src.matchAll(/Credit\("([^"]+)", "([^"]+)", "([^"]+)"/g)].map((m) => [m[1], m[2], m[3]]);

it("authors, year, contact and sources match credits.py", () => {
  expect(py).toContain(`AUTHORS = (${C.AUTHORS.map((a) => `"${a}"`).join(", ")})`);
  expect(py).toContain(`YEAR = ${C.YEAR}`);
  expect(py).toContain(`CONTACT = "${C.CONTACT}"`);
  expect(py).toContain(`TAGLINE = "${C.TAGLINE}"`);
  expect(C.SOURCES.map((s) => [s.name, s.url, s.licence])).toEqual(credits(block("SOURCES")));
  expect(C.FONTS.map((s) => s.licence)).toEqual(credits(block("FONTS")).map((f) => f[2]));
});

it("version matches the Python package", () => {
  expect(readFileSync(fileURLToPath(new URL("../../src/myo_bridge/__init__.py", import.meta.url)), "utf8"))
    .toContain(`__version__ = "${C.VERSION}"`);
});
