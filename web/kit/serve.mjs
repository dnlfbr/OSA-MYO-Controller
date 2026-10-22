#!/usr/bin/env node
// The kit app under Node, from web/dist on disk (npm run build first): for trying the launcher
// without compiling it, and on systems the kit has no binary for.
//
//   node kit/serve.mjs [launcher options, see kit/launcher.mjs]

import { existsSync, readFileSync, statSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { startRelay } from "../relay/relay.mjs";
import { run } from "./launcher.mjs";

const dist = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..", "dist");
if (!existsSync(path.join(dist, "index.html"))) {
  console.error(`no build in ${dist}: run npm run build first`);
  process.exit(1);
}
const files = (p) => {
  const f = path.join(dist, path.normalize(p));
  return f.startsWith(dist) && existsSync(f) && statSync(f).isFile() ? readFileSync(f) : null;
};

run({ files, startRelay, build: process.env.MYO_BUILD || "dev" });
