/** The kit's OSC monitor page (monitor.html): a table of the OSC the kit app receives on the OSC
 * port, pushed once a second over /__monitor (kit/launcher.mjs). */

import "./ui/app.css";
import "./ui/monitor.css";

interface Snapshot {
  port: number;
  state: "off" | "listening" | "busy";
  error: string;
  rows: [string, number, (number | string)[]][];
}

const $ = (id: string) => document.getElementById(id)!;
const hint = (s: string) => {
  $("m-hint").textContent = s;
  $("m-hint").hidden = !s;
};

function show(m: Snapshot): void {
  const lamp = $("m-state");
  lamp.dataset.state = m.state === "listening" ? "open" : m.state === "busy" ? "closed" : "off";
  lamp.textContent = m.state === "listening" ? "LISTENING" : m.state === "busy" ? "PORT BUSY" : "OFF";
  $("m-port").textContent = `UDP ${m.port}`;
  $("m-count").textContent = m.rows.length ? `${m.rows.length} addresses` : "";
  if (m.state === "busy") hint(`Port ${m.port} is in use by another program (Max?): close it and reload this page. ${m.error}`);
  else if (!m.rows.length) hint("Nothing yet: in the main page tick SEND (the lamp must say OPEN) and connect a band, or press DEMO.");
  else hint("");
  $("m-table").hidden = !m.rows.length;
  const body = $("m-rows");
  const rows = m.rows.map(([addr, rate, last]) => {
    const tr = document.createElement("tr");
    const v = last.join(" ");
    for (const [text, cls] of [[addr, "addr"], [rate.toFixed(1), "num val"], [v.length > 90 ? `${v.slice(0, 90)}…` : v, "vals"]]) {
      const td = document.createElement("td");
      td.className = cls;
      td.textContent = text;
      tr.append(td);
    }
    if (!rate) tr.classList.add("idle");
    return tr;
  });
  body.replaceChildren(...rows);
}

const es = new EventSource("__monitor");
es.onmessage = (e) => show(JSON.parse(e.data) as Snapshot);
es.onerror = () => {
  $("m-state").dataset.state = "off";
  $("m-state").textContent = "OFF";
  hint("The kit app is not running: start OSA MYO Controller web again.");
};
