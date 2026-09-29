// Piano para conferir de ouvido se o tom detectado bate com a musica.
import { $, keyLabel, NOTES, SCALES, h, toast } from "./common.js";
import { initI18n, t } from "./i18n.js";

await initI18n(); // os textos antes de desenhar a pagina

const INTERVALS = { major: [0, 2, 4, 5, 7, 9, 11], minor: [0, 2, 3, 5, 7, 8, 10] };
const START = 60; // C4
const END = 84; // C6
const KEYMAP = "awsedftgyhujkolp;";
const BLACK = new Set([1, 3, 6, 8, 10]);

const keySel = $("#keySel");
const scaleSel = $("#scaleSel");
keySel.innerHTML = NOTES.map((n) => `<option>${n}</option>`).join("");
scaleSel.innerHTML = SCALES.map((s) => `<option value="${s.id}">${s.label}</option>`).join("");

let ctx = null;
let octaveShift = 0;
const keyEls = new Map();

// ---------------------------------------------------------------- som
function audio() {
  if (!ctx) ctx = new (window.AudioContext || window.webkitAudioContext)();
  if (ctx.state === "suspended") ctx.resume();
  return ctx;
}

function playNote(midi, when = 0, length = 1.6) {
  const ac = audio();
  const t0 = ac.currentTime + when;
  const f = 440 * 2 ** ((midi - 69) / 12);
  const out = ac.createGain();
  const filter = ac.createBiquadFilter();
  filter.type = "lowpass";
  filter.frequency.setValueAtTime(Math.min(8000, f * 8), t0);
  filter.frequency.exponentialRampToValueAtTime(Math.max(300, f * 2), t0 + length);
  out.gain.setValueAtTime(0.0001, t0);
  out.gain.exponentialRampToValueAtTime(0.35, t0 + 0.006);
  out.gain.exponentialRampToValueAtTime(0.12, t0 + 0.25);
  out.gain.exponentialRampToValueAtTime(0.0001, t0 + length);
  filter.connect(out).connect(ac.destination);
  for (const [mult, type, gain] of [[1, "triangle", 1], [2, "sine", 0.35], [3, "sine", 0.12], [0.5, "sine", 0.15]]) {
    const o = ac.createOscillator();
    const g = ac.createGain();
    o.type = type;
    o.frequency.value = f * mult;
    g.gain.value = gain;
    o.connect(g).connect(filter);
    o.start(t0);
    o.stop(t0 + length + 0.05);
  }
  const el = keyEls.get(midi);
  if (el) {
    setTimeout(() => el.classList.add("down"), when * 1000);
    setTimeout(() => el.classList.remove("down"), when * 1000 + 180);
  }
}

// ------------------------------------------------------------- teclado
function build() {
  const kb = $("#keyboard");
  kb.innerHTML = "";
  keyEls.clear();
  const whites = [];
  for (let m = START; m <= END; m++) if (!BLACK.has(m % 12)) whites.push(m);
  const w = Math.min(52, Math.floor((window.innerWidth - 44) / whites.length));
  kb.style.width = `${w * whites.length}px`;
  let x = 0;
  for (let m = START; m <= END; m++) {
    const pc = m % 12;
    const name = NOTES[pc];
    let el;
    if (BLACK.has(pc)) {
      const bw = Math.round(w * 0.62);
      el = h(`<div class="black" style="left:${x - bw / 2}px;width:${bw}px">${name}</div>`);
    } else {
      el = h(`<div class="white" style="left:${x}px;width:${w}px">${name}${pc === 0 ? `<sub>${Math.floor(m / 12) - 1}</sub>` : ""}</div>`);
      x += w;
    }
    el.dataset.midi = m;
    el.addEventListener("pointerdown", (e) => {
      e.preventDefault();
      playNote(m);
    });
    kb.append(el);
    keyEls.set(m, el);
  }
  highlight();
}

function scaleNotes() {
  const root = NOTES.indexOf(keySel.value);
  return INTERVALS[scaleSel.value].map((i) => (root + i) % 12);
}

function highlight() {
  const root = NOTES.indexOf(keySel.value);
  const inScale = new Set(scaleNotes());
  for (const [m, el] of keyEls) {
    el.classList.toggle("in", inScale.has(m % 12));
    el.classList.toggle("root", m % 12 === root);
  }
}

keySel.onchange = highlight;
scaleSel.onchange = highlight;
window.addEventListener("resize", build);

$("#playScale").onclick = () => {
  const root = START + NOTES.indexOf(keySel.value);
  [...INTERVALS[scaleSel.value], 12].forEach((i, n) => playNote(root + i, n * 0.28, 0.9));
};
$("#playChord").onclick = () => {
  const root = START + NOTES.indexOf(keySel.value);
  const third = scaleSel.value === "minor" ? 3 : 4;
  [0, third, 7].forEach((i) => playNote(root + i, 0, 2.2));
  playNote(root - 12, 0, 2.2);
};

// ------------------------------------------------- teclado do computador
document.addEventListener("keydown", (e) => {
  if (e.repeat || e.target.closest("select, input")) return;
  const k = e.key.toLowerCase();
  if (k === "z") octaveShift = Math.max(-2, octaveShift - 1);
  else if (k === "x") octaveShift = Math.min(2, octaveShift + 1);
  const idx = KEYMAP.indexOf(k);
  if (idx >= 0) playNote(START + idx + octaveShift * 12);
});

// ----------------------------------------------- conversa com o player
const channel = "BroadcastChannel" in window ? new BroadcastChannel("karaoke") : null;
if (channel) {
  channel.onmessage = (e) => {
    const msg = e.data || {};
    if (msg.type === "key" && $("#follow").checked && NOTES.includes(msg.tonic)) {
      keySel.value = msg.tonic;
      scaleSel.value = msg.mode === "minor" ? "minor" : "major";
      $("#songLine").textContent = t("piano.musica", { nome: msg.title || t("piano.musica_aberta"), tom: keyLabel(msg) });
      highlight();
    }
  };
  channel.postMessage({ type: "hello" });
}

$("#apply").onclick = () => {
  if (!channel) return toast(t("piano.sem_suporte"), { error: true });
  channel.postMessage({ type: "set-key", tonic: keySel.value, mode: scaleSel.value });
  toast(t("piano.enviado", { tom: keyLabel({ tonic: keySel.value, mode: scaleSel.value }) }));
};

build();
