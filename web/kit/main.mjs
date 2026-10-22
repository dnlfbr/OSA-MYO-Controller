// Entry of the compiled kit app (deno compile, scripts/make-kit.mjs): the built page is embedded
// as base64 in app-files.gen.mjs, which make-kit writes before compiling.

import { Buffer } from "node:buffer";
import { startRelay } from "../relay/relay.mjs";
import { BUILD, FILES } from "./app-files.gen.mjs";
import { run } from "./launcher.mjs";

const cache = new Map();
const files = (p) => {
  if (!(p in FILES)) return null;
  if (!cache.has(p)) cache.set(p, Buffer.from(FILES[p], "base64"));
  return cache.get(p);
};

run({ files, startRelay, build: BUILD });
