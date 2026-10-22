/** OSC 1.0 encoding and decoding: messages with int32 (i), float32 (f) and string (s) arguments,
 * and bundles. Just what the bridge sends and the control port receives; no dependencies. */

export type OscArg = number | string | { type: "i" | "f"; value: number };
export interface OscMessage {
  address: string;
  args: OscArg[];
}

const enc = new TextEncoder();
const dec = new TextDecoder();

const pad4 = (n: number) => (n + 3) & ~3;

function oscString(s: string): Uint8Array {
  const b = enc.encode(s);
  const out = new Uint8Array(pad4(b.length + 1)); // NUL-terminated, padded to 4
  out.set(b);
  return out;
}

/** Typed argument: plain numbers are float32 unless wrapped as { type: "i" }. */
function argType(a: OscArg): "i" | "f" | "s" {
  if (typeof a === "string") return "s";
  if (typeof a === "number") return "f";
  return a.type;
}

export const int = (value: number): OscArg => ({ type: "i", value });
export const float = (value: number): OscArg => ({ type: "f", value });

export function encodeMessage(address: string, args: OscArg[]): Uint8Array {
  const parts: Uint8Array[] = [oscString(address), oscString("," + args.map(argType).join(""))];
  for (const a of args) {
    const t = argType(a);
    if (t === "s") {
      parts.push(oscString(a as string));
      continue;
    }
    const v = typeof a === "number" ? a : (a as { value: number }).value;
    const b = new Uint8Array(4);
    const dv = new DataView(b.buffer);
    if (t === "i") dv.setInt32(0, Math.trunc(v), false);
    else dv.setFloat32(0, v, false);
    parts.push(b);
  }
  return concat(parts);
}

/** A bundle with timetag "immediately" (1), like python-osc's IMMEDIATELY. */
export function encodeBundle(elements: Uint8Array[]): Uint8Array {
  const head = new Uint8Array(16);
  head.set(oscString("#bundle"));
  new DataView(head.buffer).setUint32(12, 1, false);
  const parts: Uint8Array[] = [head];
  for (const e of elements) {
    const size = new Uint8Array(4);
    new DataView(size.buffer).setInt32(0, e.length, false);
    parts.push(size, e);
  }
  return concat(parts);
}

function concat(parts: Uint8Array[]): Uint8Array {
  const out = new Uint8Array(parts.reduce((n, p) => n + p.length, 0));
  let o = 0;
  for (const p of parts) {
    out.set(p, o);
    o += p.length;
  }
  return out;
}

function readString(b: Uint8Array, o: number): [string, number] {
  let end = o;
  while (end < b.length && b[end] !== 0) end++;
  if (end >= b.length) throw new RangeError("unterminated OSC string");
  return [dec.decode(b.subarray(o, end)), pad4(end + 1)];
}

/** Decode a packet into its messages (bundles are flattened). Unknown argument types throw. */
export function decodePacket(data: Uint8Array): OscMessage[] {
  const dv = new DataView(data.buffer, data.byteOffset, data.byteLength);
  if (data.length >= 16 && dec.decode(data.subarray(0, 8)) === "#bundle\0") {
    const out: OscMessage[] = [];
    let o = 16;
    while (o + 4 <= data.length) {
      const n = dv.getInt32(o, false);
      o += 4;
      out.push(...decodePacket(data.subarray(o, o + n)));
      o += n;
    }
    return out;
  }
  let [address, o] = readString(data, 0);
  let tags = ",";
  if (o < data.length) [tags, o] = readString(data, o);
  const args: OscArg[] = [];
  for (const t of tags.slice(1)) {
    if (t === "i") {
      args.push(dv.getInt32(o, false));
      o += 4;
    } else if (t === "f") {
      args.push(dv.getFloat32(o, false));
      o += 4;
    } else if (t === "s") {
      let s: string;
      [s, o] = readString(data, o);
      args.push(s);
    } else if (t === "T" || t === "F") {
      args.push(t === "T" ? 1 : 0);
    } else {
      throw new RangeError(`unsupported OSC type tag '${t}'`);
    }
  }
  return [{ address, args }];
}
