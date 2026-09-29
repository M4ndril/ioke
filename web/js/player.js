// Player em tela cheia: mixa os stems com Web Audio (sincronia perfeita entre
// as faixas), mostra a letra linha a linha, sincroniza o clipe de fundo e
// envia o tom para o autotune via MIDI.
//
// Em /palco vira o "palco" da fila de cantores: mostra quem esta na vez,
// espera o play (daqui ou do celular de quem vai cantar) e, quando a musica
// acaba, carrega a proxima SEM recarregar a pagina (o navegador so libera o
// som depois de um clique, e esse clique precisa valer para a festa toda).
import {
  $, $$, api, avatar, chooseCover, chooseLyrics, esc, fmtTime, icon, keyLabel, NOTES, num, openModal, readyIn, SCALES, shiftText, store, toast,
  transposeKey,
} from "./common.js";
import { openPiano } from "./floating.js";
import { initMidi, mountMidiPicker, sendKey } from "./midi.js";
import { pickSongForQueue } from "./partyui.js";
import { Mic, Scorer, drawLane, scoreVerdict } from "./score.js";
import { openLyricsEditor } from "./lyricsedit.js";
import { IS_TV } from "./tvnav.js";
import { appApi } from "./appwin.js";
import { applyLook as paintLook, effectiveLook, loadGlobalLook, LOOK_KEYS, lookModeHtml, mountLookControls } from "./look.js";
import { queueDrawer } from "./queuedrawer.js";
import { initI18n, t as tr } from "./i18n.js";

await initI18n(); // os textos antes de desenhar a pagina

const STEMS = ["original", "instrumental", "lead", "backing"];
const LEAD_IN = 0.15; // acende a linha um tiquinho antes (tempo de leitura)
const PARTY = location.pathname === "/palco";
let songId = new URLSearchParams(location.search).get("id");

let song = null;
let settings = {};
let lines = [];
let lyricsType = null;
let activeIndex = -2;
let syncing = false;
let dragging = false;
let loadToken = 0; // cada troca de musica invalida os carregamentos antigos
let shift = 0; // semitons aplicados nas faixas carregadas (mudanca de tom)

// ===================================================================== mixer
class Mixer {
  constructor() {
    const Ctx = window.AudioContext || window.webkitAudioContext;
    this.ctx = new Ctx({ latencyHint: "playback" });
    this.master = this.ctx.createGain();
    this.master.connect(this.ctx.destination);
    this.gains = {};
    this.buffers = {};
    this.sources = {};
    for (const s of STEMS) {
      const g = this.ctx.createGain();
      g.gain.value = 0;
      g.connect(this.master);
      this.gains[s] = g;
    }
    this.playing = false;
    this.offset = 0;
    this.startAt = 0;
    this.duration = 0;
  }

  get time() {
    if (!this.playing) return this.offset;
    return Math.min(this.duration, Math.max(0, this.ctx.currentTime - this.startAt));
  }

  get unlocked() {
    return this.ctx.state === "running";
  }

  /** Esquece a musica atual (para carregar outra na mesma pagina). */
  reset() {
    this._stopAll();
    this.playing = false;
    this.offset = 0;
    this.startAt = 0;
    this.duration = 0;
    this.buffers = {};
    for (const g of Object.values(this.gains)) {
      g.gain.cancelScheduledValues(this.ctx.currentTime);
      g.gain.value = 0;
    }
  }

  /** Baixa e decodifica uma faixa (nao mexe no que esta tocando). */
  async fetch(name, url, onProgress, isStale) {
    const res = await fetch(url);
    if (!res.ok) throw new Error(tr("player.erro_faixa", { nome: name }));
    const total = Number(res.headers.get("Content-Length")) || 0;
    const reader = res.body.getReader();
    const chunks = [];
    let got = 0;
    for (;;) {
      const { done, value } = await reader.read();
      if (done) break;
      if (isStale && isStale()) {
        reader.cancel();
        return;
      }
      chunks.push(value);
      got += value.length;
      onProgress && onProgress(got, total);
    }
    const bytes = new Uint8Array(got);
    let pos = 0;
    for (const c of chunks) {
      bytes.set(c, pos);
      pos += c.length;
    }
    const buffer = await this.ctx.decodeAudioData(bytes.buffer);
    if (isStale && isStale()) return; // trocou de musica enquanto decodificava
    return buffer;
  }

  /** Coloca faixas no mixer. Tocando, entram juntas no ponto certo (e trocam as antigas). */
  setBuffers(map) {
    const when = this.ctx.currentTime + 0.05;
    for (const [name, buffer] of Object.entries(map)) {
      if (!buffer) continue;
      this.buffers[name] = buffer;
      this.duration = Math.max(this.duration, buffer.duration);
      if (this.playing) this._start(name, when);
    }
  }

  /** Tira uma faixa (ex.: a versao no tom antigo, enquanto a nova carrega). */
  drop(name) {
    delete this.buffers[name];
    this._stop(name);
  }

  _start(name, when) {
    const buffer = this.buffers[name];
    if (!buffer) return;
    this._stop(name, when);
    const off = when - this.startAt;
    if (off >= buffer.duration) return;
    const src = this.ctx.createBufferSource();
    src.buffer = buffer;
    src.connect(this.gains[name]);
    src.start(when, Math.max(0, off));
    this.sources[name] = src;
  }

  _stop(name, when = 0) {
    const src = this.sources[name];
    if (!src) return;
    delete this.sources[name];
    try {
      src.stop(when);
    } catch {
      /* ja parado */
    }
    src.onended = () => src.disconnect();
  }

  _stopAll() {
    for (const name of Object.keys(this.sources)) this._stop(name);
  }

  async play() {
    if (this.ctx.state === "suspended") await this.ctx.resume().catch(() => {});
    if (this.playing || !this.duration) return;
    if (this.offset >= this.duration - 0.1) this.offset = 0;
    const when = this.ctx.currentTime + 0.06;
    this.startAt = when - this.offset;
    for (const name of Object.keys(this.buffers)) this._start(name, when);
    this.playing = true;
  }

  pause() {
    if (!this.playing) return;
    this.offset = this.time;
    this._stopAll();
    this.playing = false;
  }

  seek(t) {
    const target = Math.max(0, Math.min(this.duration || 0, t));
    if (this.playing) {
      this._stopAll();
      this.playing = false;
      this.offset = target;
      this.play();
    } else {
      this.offset = target;
    }
  }

  setGains(map) {
    for (const [name, value] of Object.entries(map)) {
      this.gains[name].gain.setTargetAtTime(value, this.ctx.currentTime, 0.05);
    }
  }

  setMaster(v) {
    this.master.gain.setTargetAtTime(v, this.ctx.currentTime, 0.03);
  }
}

const mixer = new Mixer();

// ==================================================================== letra
const stampTime = (m) => Number(m[1]) * 60 + Number(m[2]) + (m[3] ? Number(m[3]) / 10 ** m[3].length : 0);

function parseLrc(text) {
  const out = [];
  let lrcShift = 0;
  for (const raw of text.split(/\r?\n/)) {
    const off = raw.match(/^\s*\[offset:\s*([+-]?\d+)\s*\]/i);
    if (off) {
      lrcShift = Number(off[1]) / 1000;
      continue;
    }
    const stamps = [...raw.matchAll(/\[(\d{1,3}):(\d{1,2})(?:[.:](\d{1,3}))?\]/g)];
    if (!stamps.length) continue;
    const body = raw.replace(/\[[^\]]*\]/g, "");
    const content = body.replace(/<\d{1,3}:\d{1,2}(?:[.:]\d{1,3})?>/g, "").trim();
    // LRC "enhanced": <mm:ss.xx> antes de cada palavra. Uma marca seguida so de
    // espaco (ou no fim da linha) e o FIM da palavra anterior: dali ate a proxima
    // palavra e silencio, e a pintura fica parada em vez de se arrastar.
    const tags = [...body.matchAll(/<(\d{1,3}):(\d{1,2})(?:[.:](\d{1,3}))?>([^<]*)/g)];
    const words = [];
    for (const m of tags) {
      const t = stampTime(m) - lrcShift;
      if (m[4].trim()) words.push({ t, text: m[4] });
      else if (words.length) {
        const w = words[words.length - 1];
        if (w.e == null) w.e = t;
        w.text += m[4];
      }
    }
    const first = stampTime(stamps[0]) - lrcShift;
    for (const m of stamps) {
      const t = stampTime(m) - lrcShift;
      const line = { t, text: content };
      if (words.length >= 2 && content) {
        const d = t - first; // a mesma linha repetida em outro tempo
        line.words = words.map((w) => ({ t: w.t + d, e: w.e == null ? null : w.e + d, text: w.text }));
      }
      out.push(line);
    }
  }
  out.sort((a, b) => a.t - b.t);
  // Linha vazia = "a frase anterior acabou". Vira marcador ♪ so em pausas
  // longas; em pausas curtas (ou repetidas) some.
  return out.filter((l, i) => {
    if (l.text) return true;
    const next = out.slice(i + 1).find((n) => n.text);
    const prevEmpty = out[i - 1] && !out[i - 1].text;
    return !prevEmpty && (!next || next.t - l.t >= 5);
  });
}

function clearLyrics() {
  lines = [];
  lyricsType = null;
  activeIndex = -2;
  setCountdown(null);
  $("#lyricsInner").innerHTML = "";
  $("#noLyrics").classList.add("hidden");
}

async function loadLyrics() {
  const id = songId;
  const data = await api(`/api/songs/${id}/lyrics`);
  if (id !== songId) return;
  clearLyrics();
  lyricsType = data.type;
  const inner = $("#lyricsInner");
  $("#noLyrics").classList.toggle("hidden", !!data.type);
  inner.classList.toggle("synced", data.type === "lrc");
  if (data.type === "lrc") {
    lines = parseLrc(data.text);
    const carry = carriedParens(lines);
    lines.forEach((l, i) => {
      l.depth0 = carry[i];
      const el = document.createElement("div");
      el.className = `line${l.text ? "" : " music"}`;
      el.dataset.i = i;
      if (l.text) buildWords(l, el, lines[i + 1]);
      else el.innerHTML = "♪ ♪ ♪";
      inner.append(el);
      l.el = el;
    });
  } else if (data.type === "plain") {
    for (const text of data.text.split(/\r?\n/)) {
      const el = document.createElement("div");
      el.className = "line plain";
      el.style.opacity = ".9";
      el.innerHTML = text.trim() ? esc(text) : "&nbsp;";
      inner.append(el);
    }
  }
  updateLyrics(true);
}

// ------------------------------------------------ efeito karaoke (preenchimento)
// A linha da vez vai sendo "pintada" enquanto e cantada. Com o tempo de cada
// palavra (LRC enhanced, ex.: NetEase), pinta palavra a palavra. Sem ele, o
// preenchimento segue a voz original: so anda enquanto tem voz no stem "lead".
let voice = null; // envelope da voz: { id, rate, cum } (quadros com voz acumulados)

/** Parentese de vocal de apoio que abre numa linha e fecha numa das 3 seguintes:
 * as linhas do meio sao de apoio inteiras (sem precisar mexer no texto). */
function carriedParens(ls) {
  const after = (text, d) => {
    for (const ch of text) d = ch === "(" ? d + 1 : ch === ")" ? Math.max(0, d - 1) : d;
    return d;
  };
  const carry = new Array(ls.length).fill(0);
  let depth = 0;
  for (let i = 0; i < ls.length; i++) {
    carry[i] = depth;
    depth = after(ls[i].text || "", depth);
    if (depth) {
      let probe = depth;
      let closes = false;
      for (let k = i + 1; k < Math.min(ls.length, i + 4) && !closes; k++) closes = !(probe = after(ls[k].text || "", probe));
      if (!closes) depth = 0;
    }
  }
  return carry;
}

function buildWords(l, el, next) {
  const parts = l.words ? l.words.map((w) => w.text) : l.text.split(/(?<=\s)/);
  let chars = 0;
  // vocais de apoio: o que esta entre parenteses (e a linha inteira, se for toda assim)
  let depth = l.depth0 || 0;
  const bg = parts.map((txt) => {
    const inside = depth > 0 || txt.trim().startsWith("(");
    for (const ch of txt) depth = Math.max(0, depth + (ch === "(" ? 1 : ch === ")" ? -1 : 0));
    return inside;
  });
  l.bgLine = bg.length > 0 && bg.every(Boolean); // "(A) voz (B)" nao e linha de apoio inteira
  el.classList.toggle("bg-line", l.bgLine);
  el.innerHTML = parts.map((txt, k) =>
    `<span class="w${bg[k] && !l.bgLine ? " bv" : ""}" data-t="${esc(txt)}">${esc(txt)}</span>`).join(""); // bv: vocal de apoio (".bg" e o fundo do palco)
  l.spans = [...el.children].map((span, k) => {
    const a = chars;
    chars += parts[k].length;
    return { el: span, a, b: chars, p: -1 };
  });
  l.chars = chars;
  // fim estimado da linha: a proxima linha (no maximo 12 s depois)
  l.until = Math.min(next ? next.t : l.t + 8, l.t + 12);
}

function buildVoice(buffer) {
  const rate = 25;
  const hop = Math.floor(buffer.sampleRate / rate);
  const a = buffer.getChannelData(0);
  const b = buffer.numberOfChannels > 1 ? buffer.getChannelData(1) : a;
  const n = Math.floor(a.length / hop);
  const rms = new Float32Array(n);
  for (let i = 0; i < n; i++) {
    let sum = 0;
    const end = (i + 1) * hop;
    for (let j = i * hop; j < end; j += 4) {
      const v = a[j] + b[j];
      sum += v * v;
    }
    rms[i] = Math.sqrt(sum / (hop / 4));
  }
  const sorted = Float32Array.from(rms).sort();
  const threshold = Math.max((sorted[Math.floor(n * 0.95)] || 0) * 0.12, 1e-4);
  const cum = new Float32Array(n + 1);
  for (let i = 0; i < n; i++) cum[i + 1] = cum[i] + (rms[i] > threshold ? 1 : 0);
  return { rate, cum, n };
}

function ensureVoice() {
  if (!song || (voice && voice.id === songId) || !mixer.buffers.lead) return;
  const id = songId;
  setTimeout(() => {
    if (id !== songId || !mixer.buffers.lead) return;
    voice = { id, ...buildVoice(mixer.buffers.lead) };
  }, 30);
}

function voicedUpTo(t) {
  const x = Math.max(0, Math.min(voice.n, t * voice.rate));
  const i = Math.floor(x);
  const frac = x - i;
  return voice.cum[i] + (i < voice.n ? frac * (voice.cum[i + 1] - voice.cum[i]) : 0);
}

const clamp01 = (v) => (v < 0 ? 0 : v > 1 ? 1 : v);

/** Progresso (0..1) da linha pelo tempo do audio: pela voz ou, sem ela, linear. */
function estimateProgress(l, t, off) {
  const t0 = l.t + off;
  const t1 = l.until + off;
  if (voice && voice.id === songId) {
    const a = voicedUpTo(t0 - 0.1);
    const total = voicedUpTo(t1) - a;
    if (total >= 4) return clamp01((voicedUpTo(t) - a) / (total * 0.97));
  }
  const dur = Math.min(t1 - t0, Math.max(1.2, l.chars * 0.075));
  return clamp01((t - t0) / dur);
}

function updateWipe(l) {
  if (!look.wipe || !l || !l.spans) return;
  const off = settings.offset || 0;
  const t = mixer.time;
  const set = (sp, p) => {
    p = Math.round(p * 1000) / 1000;
    if (p !== sp.p) {
      sp.p = p;
      sp.el.style.setProperty("--p", p);
    }
  };
  if (l.words) {
    l.words.forEach((w, k) => {
      const next = l.words[k + 1];
      const end = w.e ?? (next ? next.t : Math.min(w.t + 0.8, l.until));
      set(l.spans[k], clamp01((t - off - w.t) / Math.max(0.05, end - w.t)));
    });
  } else {
    const pos = estimateProgress(l, t, off) * l.chars;
    for (const sp of l.spans) set(sp, clamp01((pos - sp.a) / Math.max(1, sp.b - sp.a)));
  }
}


const stageHeight = () => $("#stage").clientHeight;

// Letra sincronizada: TODAS as linhas sao montadas no tamanho da linha da vez
// (entao a quebra de linha ja esta definida e nao muda quando ela vira a da
// vez); as outras so aparecem menores por escala. As posicoes finais sao
// calculadas antes e tudo desliza junto numa curva so: sem "subir e voltar".
const INACTIVE_SCALE = 0.6;
let measured = false;

function measureLines() {
  if (!lines.length) return;
  for (const l of lines) l.h = l.el.offsetHeight;
  const fs = parseFloat(getComputedStyle(lines[0].el).fontSize) || 40;
  lines.gap = fs * 0.32;
  measured = true;
}

function layoutLines(active) {
  if (!lines.length) return;
  if (!measured) measureLines();
  const gap = lines.gap;
  let y = 0;
  let focusTop = 0;
  let focusH = 0;
  const focus = active >= 0 ? active : 0;
  lines.forEach((l, i) => {
    const s = (i === active ? 1 : INACTIVE_SCALE) * (l.bgLine ? 0.8 : 1);
    l.el.style.transform = `translate3d(0, ${y.toFixed(1)}px, 0) scale(${s})`;
    if (i === focus) {
      focusTop = y;
      focusH = l.h * s;
    }
    y += l.h * s + gap;
  });
  // com a faixa de notas em cima, a letra desce um pouco
  const center = $("#stage").classList.contains("lane-on") ? 0.6 : 0.44;
  $("#lyricsInner").style.transform = `translate3d(0, ${(stageHeight() * center - focusTop - focusH / 2).toFixed(1)}px, 0)`;
}

let countdownEl = null;
function setCountdown(beforeEl, remaining) {
  if (!beforeEl || remaining == null) {
    countdownEl && countdownEl.remove();
    countdownEl = null;
    return;
  }
  if (!countdownEl) {
    countdownEl = document.createElement("div");
    countdownEl.className = "countdown";
    countdownEl.innerHTML = "<i></i><i></i><i></i>";
  }
  // fica dentro da linha (anda junto com ela)
  if (countdownEl.parentElement !== beforeEl) beforeEl.prepend(countdownEl);
  const on = Math.ceil(remaining);
  [...countdownEl.children].forEach((dot, i) => dot.classList.toggle("off", i >= on));
}

const currentLyricTime = () => mixer.time - (settings.offset || 0) + LEAD_IN;

function updateLyrics(force = false) {
  if (lyricsType === "plain") {
    const inner = $("#lyricsInner");
    const p = mixer.duration ? mixer.time / mixer.duration : 0;
    const range = Math.max(0, inner.scrollHeight - stageHeight() * 0.6);
    inner.style.transform = `translateY(${stageHeight() * 0.3 - p * range}px)`;
    return;
  }
  if (!lines.length) return;
  const t = currentLyricTime();
  let idx = -1;
  let lo = 0;
  let hi = lines.length - 1;
  while (lo <= hi) {
    const mid = (lo + hi) >> 1;
    if (lines[mid].t <= t) {
      idx = mid;
      lo = mid + 1;
    } else hi = mid - 1;
  }
  if (idx !== activeIndex || force) {
    if (activeIndex >= 0 && lines[activeIndex]) lines[activeIndex].el.classList.remove("active");
    if (lines[activeIndex] && lines[activeIndex].spans) lines[activeIndex].spans.forEach((sp) => (sp.p = -1));
    activeIndex = idx;
    if (idx >= 0) lines[idx].el.classList.add("active");
    if (force) measured = false; // tamanho da letra/tela mudou: mede de novo
    layoutLines(idx);
  }
  updateWipe(lines[idx]);
  // Contagem regressiva no comeco e depois de pausas longas
  const next = lines[idx + 1];
  const cur = lines[idx];
  const remaining = next ? next.t - t : null;
  const longGap = next && (!cur || !cur.text || next.t - cur.t >= 8);
  if (next && longGap && remaining > 0 && remaining <= 3 && next.text) setCountdown(next.el, remaining);
  else setCountdown(null);
}

// ================================================================ ajustes
let saveTimer = null;
function scheduleSave() {
  // guarda QUAL musica e QUAIS ajustes agora: se trocar de musica antes de
  // salvar, nao grava os ajustes de uma na outra
  const id = songId;
  const body = { settings: { ...settings } };
  if (lookMode !== "own") LOOK_KEYS.forEach((k) => delete body.settings[k]); // seguindo o padrao: o visual nao e dela
  clearTimeout(saveTimer);
  saveTimer = setTimeout(() => {
    api(`/api/songs/${id}`, { method: "PATCH", body }).catch((err) => toast(err.message, { error: true }));
  }, 600);
}

function setSetting(key, value, { persist = true } = {}) {
  settings[key] = value;
  if (persist) scheduleSave();
}

const pct = (v) => `${Math.round(v * 100)}%`;
const masterVolume = () => Number(store("karaoke.master") ?? 1);

let waitingOriginal = false;
let stemsStarted = false;

function applyMix() {
  const g = (song && song.stem_gain) || 1; // devolve a folga de volume usada na separacao
  const original = settings.mode === "original";
  if (original) mixer.setGains({ original: 1, instrumental: 0, lead: 0, backing: 0 });
  else mixer.setGains({ original: 0, instrumental: g, lead: settings.lead_vol * g, backing: settings.backing_vol * g });
  $$("#modeSeg button").forEach((b) => b.classList.toggle("on", b.dataset.mode === settings.mode));
  $$(".instr-only").forEach((r) => r.classList.toggle("disabled", original));
  $("#leadVolVal").textContent = pct(settings.lead_vol);
  $("#backVolVal").textContent = pct(settings.backing_vol);
  $("#mixNote").textContent = original
    ? tr("player.mix_original")
    : settings.lead_vol > 0
      ? tr("player.mix_guia")
      : tr("player.mix_karaoke");
  const wasWaiting = waitingOriginal;
  waitingOriginal = original && stemsStarted && !mixer.buffers.original;
  if (waitingOriginal) showLoading(tr("player.carregando_original"));
  else if (wasWaiting) showLoading(null);
}

function applyVolume() {
  const v = masterVolume();
  mixer.setMaster(v);
  $("#master").value = v;
  $("#masterVal").textContent = pct(v);
  $("#volIcon").textContent = v === 0 ? "volume_off" : v < 0.5 ? "volume_down" : "volume_up";
  /* icons: volume_off volume_down volume_up */
}

/** Indicador de volume (um so, como na TV): aparece ao mudar e some sozinho. */
let volOsdTimer = null;
function showVolumeOsd(v) {
  const osd = $("#volOsd");
  $("#volOsdIcon").textContent = v === 0 ? "volume_off" : v < 0.5 ? "volume_down" : "volume_up";
  $("#volOsdBar").style.width = `${Math.round(v * 100)}%`;
  $("#volOsdVal").textContent = pct(v);
  osd.classList.add("on");
  clearTimeout(volOsdTimer);
  volOsdTimer = setTimeout(() => osd.classList.remove("on"), 1500);
}

// ------------------------------------------------ visual (look.js)
// A musica segue o visual padrao (Configuracoes -> Player) ou tem o dela.
let globalLook = null; // o padrao (servidor)
let lookMode = "global"; // "global" | "own"
let ownLook = {}; // os ajustes proprios desta musica
let look = {}; // o que vale agora
let lookControls = [];

function refreshLook() {
  look = effectiveLook(globalLook || {}, lookMode, ownLook);
  paintLook($("#stage"), look);
  lookControls.forEach((c) => c.update(look));
  $$(".lk-mode button").forEach((b) => b.classList.toggle("on", b.dataset.mode === lookMode));
  requestAnimationFrame(() => updateLyrics(true));
}

/** Padrao | Proprio. Virar "Proprio" copia o padrao inteiro (mudar o padrao depois nao mexe nela). */
function setLookMode(mode) {
  if (!song || mode === lookMode) return;
  const before = look.background;
  lookMode = mode;
  settings.look = mode;
  if (mode === "own") {
    ownLook = { ...globalLook, ...ownLook };
    LOOK_KEYS.forEach((k) => (settings[k] = ownLook[k]));
  }
  scheduleSave();
  refreshLook();
  if (look.background !== before) applyBackground();
  toast(mode === "own" ? tr("player.visual_proprio") : tr("player.visual_padrao"), { key: "look" });
}

/** Mexeu num controle do visual: com "Padrao", a musica passa a ter o visual dela (o padrao nao muda). */
function changeLook(k, v) {
  if (!song) return;
  if (lookMode === "global") {
    lookMode = "own";
    settings.look = "own";
    ownLook = { ...globalLook };
    LOOK_KEYS.forEach((key) => (settings[key] = ownLook[key]));
    toast(tr("player.visual_agora_proprio"), { key: "look", ms: 4500 });
  }
  ownLook[k] = v;
  settings[k] = v;
  scheduleSave();
  refreshLook();
  if (k === "background") {
    if (v === "video" && song.video && song.video.status === "error") requestVideo(true);
    else applyBackground();
  }
}

function applyOffset() {
  const o = settings.offset || 0;
  $("#offsetVal").textContent = `${o > 0 ? "+" : ""}${num(o, 1)} s`;
  updateLyrics(true);
}

/** Os sliders mostram os ajustes da musica carregada. */
function syncControlValues() {
  $("#leadVol").value = settings.lead_vol;
  $("#backVol").value = settings.backing_vol;
}

function showLoading(text) {
  const box = $("#loading");
  if (!text) return box.classList.add("hidden");
  $("#loadingText").textContent = text;
  box.classList.remove("hidden");
}

// ---------------------------------------------------------------- tom/MIDI
const channel = "BroadcastChannel" in window ? new BroadcastChannel("karaoke") : null;

function effectiveKey() {
  const det = (song && song.detected_key) || {};
  const tonic = settings.key || det.tonic;
  const mode = settings.scale || det.mode;
  return tonic && mode ? { tonic, mode } : null;
}

/** Tom em que a musica esta tocando agora (o original + a transposicao). */
const sungKey = () => transposeKey(effectiveKey(), shift);

function announceKey({ midi = true } = {}) {
  const key = sungKey();
  if (!key || !song) return;
  if (midi) sendKey(key.tonic, key.mode);
  channel && channel.postMessage({ type: "key", ...key, title: song.track || song.title });
}

// Relativa maior/menor: mesmas notas, entao o autotune corrige igual
function relativeKey(tonic, mode) {
  const i = NOTES.indexOf(tonic);
  return keyLabel({ tonic: NOTES[(i + (mode === "minor" ? 3 : 9)) % 12], mode: mode === "minor" ? "major" : "minor" });
}

function updateKeyUi() {
  const det = song.detected_key || {};
  const key = effectiveKey();
  const sung = sungKey();
  $("#keyLabel").innerHTML = `${sung ? esc(keyLabel(sung)) : esc(tr("player.tom"))}${shift ? ` <span class="shift-badge">${shiftText(shift)}</span>` : ""}`;
  $("#tVal").textContent = shift ? shiftText(shift) : tr("player.original");
  $("#tVal").classList.toggle("offset", !!shift);
  $("#tDown").disabled = shift <= -6;
  $("#tUp").disabled = shift >= 6;
  const steps = Math.abs(shift);
  $("#tNote").textContent = shift
    ? tr(shift > 0 ? "player.semitons_agudo" : "player.semitons_grave", { n: steps }) +
      (key ? tr("player.tocando_em", { tom: keyLabel(sung), original: keyLabel(key) }) : "") + "."
    : tr("player.tom_explica");
  const alt = (det.alternatives || []).map((a) => keyLabel(a)).join(", ");
  const parts = [];
  if (key) parts.push(tr("player.mesmas_notas", { tom: relativeKey(key.tonic, key.mode) }));
  if (det.tonic) parts.push(alt ? tr("player.detectado_alt", { tom: keyLabel(det), alt }) : tr("player.detectado", { tom: keyLabel(det) }));
  $("#keyInfo").textContent = parts.join(" ");
}

function fillKeySelects() {
  const det = song.detected_key || {};
  $("#keySel").innerHTML = NOTES.map((n) => `<option value="${n}">${n}${n === det.tonic ? " •" : ""}</option>`).join("");
  $("#scaleSel").innerHTML = SCALES.map((s) => `<option value="${s.id}">${s.label}${s.id === det.mode ? " •" : ""}</option>`).join("");
  const key = effectiveKey() || { tonic: "C", mode: "major" };
  $("#keySel").value = key.tonic;
  $("#scaleSel").value = key.mode;
  updateKeyUi();
}

function setKey(tonic, mode) {
  setSetting("key", tonic);
  setSetting("scale", mode);
  $("#keySel").value = tonic;
  $("#scaleSel").value = mode;
  updateKeyUi();
  announceKey();
}

if (channel) {
  channel.addEventListener("message", async (e) => {
    // o visual padrao mudou (Configuracoes -> Player): as musicas em "Padrao" mudam na hora (PC e TV)
    if (!e.data || e.data.type !== "look" || !song) return;
    globalLook = await loadGlobalLook({ fresh: true }).catch(() => globalLook);
    const before = look.background;
    refreshLook();
    if (look.background !== before) applyBackground();
  });
  channel.onmessage = (e) => {
    const msg = e.data || {};
    if (!song) return;
    if (msg.type === "hello") announceKey({ midi: false });
    if (msg.type === "set-key" && NOTES.includes(msg.tonic)) {
      // o piano mostra o tom cantado; o ajuste guarda o tom da gravacao
      const original = transposeKey({ tonic: msg.tonic, mode: msg.mode }, -shift);
      setKey(original.tonic, msg.mode === "minor" ? "minor" : "major");
      toast(tr("player.tom_alterado", { tom: keyLabel({ tonic: msg.tonic, mode: msg.mode }) }));
    }
  };
}

// ============================================================ fundo em video
const bgVideo = $("#bgVideo");
let videoPoll = null;

const backgroundMode = () => look.background || "cover";

function showVideoStatus(html) {
  const pill = $("#videoStatus");
  pill.classList.toggle("hidden", !html);
  if (html) pill.innerHTML = html;
}

function resetVideo() {
  clearTimeout(videoPoll);
  bgVideo.pause();
  bgVideo.removeAttribute("src");
  bgVideo.load();
  $("#stage").classList.remove("video-on");
  showVideoStatus(null);
}

function applyBackground() {
  const mode = backgroundMode();
  const stage = $("#stage");
  const v = song.video;
  if (mode !== "video") {
    stage.classList.remove("video-on");
    bgVideo.pause();
    showVideoStatus(null);
    return;
  }
  if (v && v.status === "ready") {
    if (bgVideo.getAttribute("src") !== v.url) {
      bgVideo.src = v.url;
      bgVideo.addEventListener("loadeddata", () => syncVideo(true), { once: true });
    }
    stage.classList.add("video-on");
    showVideoStatus(null);
  } else if (v && v.status === "error") {
    stage.classList.remove("video-on");
    showVideoStatus(`${esc(tr("player.video_falhou"))} <button class="btn xs" id="videoRetry">${esc(tr("player.tentar_de_novo"))}</button>`);
    $("#videoRetry").onclick = () => requestVideo(true);
  } else {
    stage.classList.remove("video-on");
    requestVideo();
  }
}

/** Pede o video ao servidor (musicas antigas) e acompanha o download. */
async function requestVideo(force = false) {
  const id = songId;
  if (force || !song.video || song.video.status !== "downloading") {
    try {
      song.video = (await api(`/api/songs/${id}/video`, { method: "POST" })).video;
    } catch (err) {
      showVideoStatus(esc(err.message));
      return;
    }
  }
  clearTimeout(videoPoll);
  const poll = async () => {
    if (id !== songId) return; // trocou de musica
    try {
      song.video = (await api(`/api/songs/${id}`)).video;
    } catch {
      /* tenta de novo */
    }
    if (id !== songId) return;
    const v = song.video || {};
    if (v.status === "downloading") {
      showVideoStatus(`<span class="spinner"></span> ${esc(tr("player.baixando_video"))} ${Math.round((v.progress || 0) * 100)}%`);
      videoPoll = setTimeout(poll, 1200);
    } else if (backgroundMode() === "video") {
      applyBackground();
    }
  };
  poll();
}

/** Mantem o video colado no tempo do audio (o audio manda). */
function syncVideo(force = false) {
  if (!song || backgroundMode() !== "video" || !bgVideo.getAttribute("src") || bgVideo.readyState < 1) return;
  const t = mixer.time;
  const dur = bgVideo.duration || 0;
  if (dur && t >= dur - 0.05) {
    if (!bgVideo.paused) bgVideo.pause();
    return;
  }
  const drift = bgVideo.currentTime - t;
  if (mixer.playing) {
    if (bgVideo.paused) bgVideo.play().catch(() => {});
    if ((Math.abs(drift) > 0.3 || force) && !bgVideo.seeking) {
      bgVideo.currentTime = t;
      bgVideo.playbackRate = 1;
    } else if (Math.abs(drift) > 0.04) {
      bgVideo.playbackRate = Math.min(1.08, Math.max(0.92, 1 - drift * 0.8)); // corrige sem "pulos"
    } else {
      bgVideo.playbackRate = 1;
    }
  } else {
    if (!bgVideo.paused) bgVideo.pause();
    if ((Math.abs(drift) > 0.12 || force) && !bgVideo.seeking) bgVideo.currentTime = t;
  }
}

// ============================================== pontuacao pelo microfone
let scoreCfg = { on: false, lane: true, device: "", ...(store("karaoke.score") || {}) };
const mic = new Mic(mixer.ctx);
let scorer = null;
let lastScoreFrame = 0;
let lastScoreT = 0;
let liveShownAt = 0;

const saveScoreCfg = () => store("karaoke.score", scoreCfg);

/** Tempo da musica que a pessoa esta ouvindo (e cantando) agora. */
function heardTime() {
  const ctx = mixer.ctx;
  return mixer.time - (mixer.playing ? (ctx.outputLatency || 0) + (ctx.baseLatency || 0) : 0);
}

async function loadMelody() {
  scorer = null;
  if (!scoreCfg.on || !song) return;
  const id = songId;
  try {
    const melody = await api(`/api/songs/${id}/melody`);
    if (id === songId) scorer = new Scorer(melody);
  } catch {
    scorer = null; // musica sem voz separada: sem pontuacao
  }
  applyScoreUi();
}

async function fillMics() {
  const sel = $("#micSel");
  try {
    const devices = (await navigator.mediaDevices.enumerateDevices()).filter((d) => d.kind === "audioinput");
    sel.innerHTML = devices.map((d, i) =>
      `<option value="${esc(d.deviceId)}">${esc(d.label || `Microfone ${i + 1}`)}</option>`).join("");
    const current = mic.stream && mic.stream.getAudioTracks()[0];
    const settingsId = current && current.getSettings().deviceId;
    sel.value = scoreCfg.device || settingsId || (devices[0] && devices[0].deviceId) || "";
  } catch {
    sel.innerHTML = `<option>${esc(tr("player.sem_microfones"))}</option>`;
  }
}

async function setScoring(on) {
  scoreCfg = { ...scoreCfg, on };
  saveScoreCfg();
  if (on) {
    try {
      await mic.start(scoreCfg.device);
    } catch (err) {
      try {
        if (scoreCfg.device) await mic.start(""); // o microfone salvo sumiu: usa o padrao
        else throw err;
      } catch (err2) {
        scoreCfg = { ...scoreCfg, on: false };
        saveScoreCfg();
        toast(tr("player.microfone_falhou", { erro: err2.message || err2.name }), { error: true });
      }
    }
    if (mic.on) {
      await fillMics();
      await loadMelody();
    }
  } else {
    mic.stop();
    scorer = null;
  }
  applyScoreUi();
}

function applyScoreUi() {
  const on = scoreCfg.on && mic.on;
  $$("#scoreSeg button").forEach((b) => b.classList.toggle("on", (b.dataset.score === "on") === on));
  $("#scoreIcon").textContent = on ? "mic" : "mic_off"; /* icons: mic mic_off star trophy */
  $("#scoreMenuBody").classList.toggle("disabled", !on);
  $("#laneToggle").checked = scoreCfg.lane;
  const lane = !!(on && scoreCfg.lane && scorer && scorer.ready);
  $("#lane").classList.toggle("hidden", !lane);
  if ($("#stage").classList.contains("lane-on") !== lane) {
    $("#stage").classList.toggle("lane-on", lane);
    updateLyrics(true);
  }
  $("#liveScore").classList.toggle("hidden", !(on && scorer && scorer.ready));
  $("#scoreNote").textContent = !on ? tr("player.pontuacao_explica")
    : scorer && scorer.ready ? tr("player.pontuacao_valendo")
      : song ? tr("player.pontuacao_sem_melodia") : "";
}

/** Roda a cada quadro: le o microfone, pontua e desenha a faixa de notas. */
function updateScore() {
  const now = performance.now();
  const dt = Math.min(0.1, (now - lastScoreFrame) / 1000);
  lastScoreFrame = now;
  if (!scorer || !mic.on) return;
  const t = heardTime();
  if (t + 1 < lastScoreT && t < 3) scorer.reset(); // voltou para o comeco
  lastScoreT = t;
  const reading = mic.read();
  if (openMenu && openMenu.id === "scoreMenu") $("#micLevel").style.width = `${Math.round((reading ? reading.level : 0) * 100)}%`;
  if (mixer.playing) scorer.update(t - 0.05, reading, dt, shift);
  if (scoreCfg.lane && scorer.ready) drawLane($("#lane"), scorer, t, shift);
  if (now - liveShownAt > 500) {
    liveShownAt = now;
    const sc = scorer.score;
    $("#liveScore").innerHTML = `<span class="ms">mic</span>${sc == null ? "–" : sc}`;
  }
}

/** Nota final (ou null se ninguem cantou de verdade). */
function finalScore() {
  if (!scorer || !mic.on || scorer.sung < 4) return null;
  return scorer.score;
}

let scoreCardTimer = null;
function showScoreCard(score, singer) {
  clearTimeout(scoreCardTimer);
  const card = $("#scoreCard");
  if (score == null) return card.classList.add("hidden");
  $("#scNumber").textContent = score;
  $("#scVerdict").textContent = scoreVerdict(score);
  $("#scSinger").textContent = singer ? `${singer} cantou ${song ? song.track || song.title : ""}` : song ? song.track || song.title : "";
  $("#scStars").innerHTML = [1, 2, 3, 4, 5].map((i) =>
    `<span class="ms${score >= i * 20 - 10 ? " fill on" : ""}">star</span>`).join("");
  $("#scActions").classList.toggle("hidden", PARTY);
  card.classList.remove("hidden");
  card.classList.remove("pop");
  void card.offsetWidth;
  card.classList.add("pop");
  if (PARTY) scoreCardTimer = setTimeout(() => card.classList.add("hidden"), 9000);
}

// ================================================= "cantadas recentemente"
let listened = 0;
let playedSent = false;
let lastFrame = performance.now();

function trackListening() {
  const now = performance.now();
  if (mixer.playing) listened += Math.min(0.5, (now - lastFrame) / 1000);
  lastFrame = now;
  if (!playedSent && song && listened >= 30) {
    playedSent = true;
    api(`/api/songs/${songId}/played`, { method: "POST" }).catch(() => {});
  }
}

// ======================================================= controles na tela
const player = $("#player");
let hideTimer = null;
let openMenu = null;

/** Mostra as barras; somem depois de 3s parado (so enquanto toca). */
function showUi() {
  player.classList.add("ui-on");
  player.classList.remove("no-cursor");
  clearTimeout(hideTimer);
  hideTimer = setTimeout(maybeHideUi, 3000);
}

function maybeHideUi() {
  const busy = !mixer.playing || openMenu || syncing || drawerIsOpen() || document.querySelector(".modal-backdrop, #lyricsEditor.open") ||
    document.querySelector(".top-bar:hover, .bottom-bar:hover");
  if (busy) {
    hideTimer = setTimeout(maybeHideUi, 1500);
    return;
  }
  player.classList.remove("ui-on");
  player.classList.add("no-cursor");
}

["mousemove", "pointerdown", "keydown", "touchstart"].forEach((ev) => document.addEventListener(ev, showUi, { passive: true }));

// Menus: abrem com o mouse em cima (e fecham ao sair) ou com clique (ficam fixos).
function closeMenu(wrap) {
  wrap.classList.remove("open");
  wrap.pinned = false;
  if (openMenu === wrap) openMenu = null;
}

function setupMenus() {
  const hoverable = matchMedia("(hover: hover)").matches;
  $$(".menu-wrap").forEach((wrap) => {
    let closeTimer = null;
    const open = (pinned) => {
      if (openMenu && openMenu !== wrap) closeMenu(openMenu);
      clearTimeout(closeTimer);
      if (!wrap.classList.contains("open")) wrap.dispatchEvent(new Event("menuopen"));
      wrap.classList.add("open");
      wrap.pinned = wrap.pinned || pinned;
      openMenu = wrap;
    };
    if (hoverable) {
      wrap.addEventListener("mouseenter", () => open(false));
      wrap.addEventListener("mouseleave", () => {
        const active = document.activeElement;
        if (wrap.pinned || (wrap.contains(active) && active.tagName === "SELECT")) return;
        closeTimer = setTimeout(() => closeMenu(wrap), 260);
      });
    }
    wrap.querySelector(".trigger").addEventListener("click", (e) => {
      e.stopPropagation();
      if (wrap.classList.contains("open") && wrap.pinned) closeMenu(wrap);
      else open(true);
    });
    wrap.querySelector(".menu").addEventListener("click", (e) => e.stopPropagation());
  });
  document.addEventListener("click", () => openMenu && closeMenu(openMenu));
}

async function toggleFullscreen() {
  const app = await appApi(); // app instalado: a propria janela entra/sai da tela cheia
  if (app) return app.toggle_fullscreen();
  if (document.fullscreenElement) document.exitFullscreen();
  else document.documentElement.requestFullscreen().catch(() => toast(tr("player.tela_cheia_bloqueada"), { error: true }));
}

document.addEventListener("fullscreenchange", () => {
  $("#fsBtn").innerHTML = document.fullscreenElement ? icon("fullscreen_exit") : icon("fullscreen");
  setTimeout(() => updateLyrics(true), 80);
});
window.addEventListener("resize", () => updateLyrics(true));
if (document.fonts) document.fonts.ready.then(() => updateLyrics(true));

// ================================================================== sync
function setSyncing(on) {
  syncing = on;
  $("#syncMouse").classList.toggle("on", on);
  $("#syncHint").classList.toggle("hidden", !on);
  $("#stage").classList.toggle("syncing", on);
  if (on && openMenu) closeMenu(openMenu);
}

$("#lyricsInner").addEventListener("click", (e) => {
  const el = e.target.closest(".line[data-i]");
  if (!el) return;
  e.stopPropagation();
  const line = lines[Number(el.dataset.i)];
  if (syncing) {
    setSetting("offset", Math.round((mixer.time - line.t) * 100) / 100); // esta linha comeca AGORA
    applyOffset();
    setSyncing(false);
    toast(tr("player.letra_ajustada", { s: `${settings.offset > 0 ? "+" : ""}${num(settings.offset, 2)}` }));
  } else {
    mixer.seek(line.t + (settings.offset || 0) - 0.4);
    updateLyrics(true);
  }
});

// ============================================================ play / loop
let wakeLock = null;
async function setPlaying(on) {
  if (on) {
    await mixer.play();
    if (!mixer.unlocked) {
      // o navegador ainda nao deixou tocar som nesta aba
      if (PARTY) $("#unlock").classList.remove("hidden");
      toast(tr("player.clique_liberar_som"), { error: true });
    }
    if (mixer.playing) {
      $("#bigPlay").classList.add("hidden");
      $("#stageOverlay").classList.add("hidden");
    }
  } else mixer.pause();
  $("#playBtn").innerHTML = mixer.playing ? icon("pause", "fill") : icon("play_arrow", "fill");
  showUi();
  partyReport(mixer.playing ? "playing" : "paused");
  try {
    if (mixer.playing && navigator.wakeLock && !wakeLock) {
      wakeLock = await navigator.wakeLock.request("screen");
      wakeLock.addEventListener("release", () => (wakeLock = null));
    } else if (!mixer.playing && wakeLock) {
      wakeLock.release();
    }
  } catch {
    /* sem wake lock, tudo bem */
  }
}

function seekBy(delta) {
  mixer.seek(mixer.time + delta);
  updateLyrics(true);
  syncVideo(true);
}

let lastSecond = -1;
let lastReportAt = 0;

/** Fim da musica. Roda no loop de animacao E num timer: o navegador congela a
 *  animacao com a janela minimizada, e a fila nao pode travar por isso. */
function checkEnd() {
  // o controle remoto pergunta antes de sair de uma musica tocando
  const flag = mixer.playing ? "1" : "";
  if (document.body.dataset.playing !== flag) document.body.dataset.playing = flag;
  if (mixer.playing && mixer.duration && mixer.time >= mixer.duration - 0.02) {
    mixer.pause();
    mixer.offset = mixer.duration;
    setPlaying(false);
    const score = finalScore();
    showScoreCard(score, PARTY && stagedEntry ? stagedEntry.singer : null);
    songEnded(score);
  }
  if (PARTY && mixer.playing && performance.now() - lastReportAt > 3000) partyReport("playing");
}
setInterval(checkEnd, 500);

function loop() {
  const t = mixer.time;
  checkEnd();
  if (Math.floor(t) !== lastSecond) {
    lastSecond = Math.floor(t);
    $("#curTime").textContent = fmtTime(t);
    $("#remTime").textContent = mixer.duration ? `-${fmtTime(mixer.duration - t)}` : "0:00";
    updateUpNext(t);
  }
  const seek = $("#seek");
  if (!dragging) seek.value = t;
  seek.style.setProperty("--p", `${mixer.duration ? (Number(seek.value) / mixer.duration) * 100 : 0}%`);
  updateLyrics();
  syncVideo();
  trackListening();
  updateScore();
  requestAnimationFrame(loop);
}

// ============================================================ carregar musica
async function refreshSong() {
  song = await api(`/api/songs/${songId}`);
  $("#bg").style.backgroundImage = `url("${song.cover || song.thumb}")`;
  bgVideo.poster = song.cover || song.thumb;
}

async function pickLyrics() {
  if (!song) return;
  if (await chooseLyrics(song)) {
    await refreshSong();
    await loadLyrics();
    // a letra escolhida vai para a IA (sincronia palavra a palavra): acompanha
    if (song.lyrics_ai && (song.lyrics_ai.state === "queued" || song.lyrics_ai.state === "running")) watchAi(songId);
  }
}

// ======================================================== letra por IA
// Sincronizar: acha a letra que mais combina com o audio e encaixa cada palavra
// dela (sem mudar o texto). Ajustar a versao: bis e linhas nao cantadas. No servidor.
let aiTimer = null;
let aiWatching = null;
const AI_SRC = { lrclib: "LRCLIB", netease: "NetEase", musixmatch: "Musixmatch" };

function aiText(ai) {
  if (!ai) return tr("ia.explica");
  if (ai.state === "queued") return ai.busy_with ? tr("ia.na_fila_ocupada", { atividade: ai.busy_with }) : tr("ia.na_fila");
  if (ai.state === "running") return `${ai.stage || tr("ia.trabalhando")} ${Math.round((ai.progress || 0) * 100)}%`;
  if (ai.state === "error") return tr("ia.nao_conseguiu", { erro: ai.error || "" });
  const parts = [ai.mode === "adapt" ? tr("ia.ajustada") : tr("ia.palavra_a_palavra")];
  if (ai.source) parts.push(ai.source === "ia" ? tr("ia.texto_anterior") : ai.source === "manual" ? tr("ia.texto_manual")
    : tr("ia.texto_de", { fonte: AI_SRC[ai.source] || ai.source }));
  if (ai.repeats) parts.push(tr("ia.repetidas", { n: ai.repeats }));
  if (ai.skips) parts.push(tr("ia.removidas", { n: ai.skips }));
  return parts.join(" · ") + ".";
}

function renderAi(ai) {
  const changes = ai && ai.state === "done" && ai.mode === "adapt" && ai.changes;
  $("#aiNote").innerHTML = esc(aiText(ai)) + (changes ? ` <button class="link-btn" id="aiChanges">${esc(tr("ia.ver_mudancas"))}</button>` : "");
  const btn = $("#aiChanges");
  if (btn) btn.onclick = () => reviewChanges();
  const busy = ai && (ai.state === "queued" || ai.state === "running");
  $("#aiLyrics").disabled = !!busy;
  $("#aiAdapt").disabled = !!busy || !song || !song.lyrics;
  const pill = $("#aiPill");
  pill.classList.toggle("hidden", !busy || ai.quiet); // automatica (musica nova): sem aviso no palco
  if (busy) pill.innerHTML = `<span class="spinner"></span> ${esc(tr(ai.mode === "adapt" ? "ia.ajustando" : "ia.letra_por_ia"))}: ${esc(aiText(ai))}`;
}

function aiDoneText(ai) {
  if (ai.mode !== "adapt") return tr("ia.sincronizada");
  const bits = [];
  if (ai.repeats) bits.push(tr("ia.repetidas", { n: ai.repeats }));
  if (ai.skips) bits.push(tr("ia.removidas", { n: ai.skips }));
  if (bits.length) return tr("ia.ajustada_com", { lista: bits.join(", ") });
  return ai.changes ? tr("ia.refeita") : tr("ia.nada_ajustar");
}

/** Acompanha a IA ate terminar; entao recarrega a letra. */
function watchAi(id) {
  clearTimeout(aiTimer);
  aiWatching = id;
  const tick = async () => {
    if (aiWatching !== songId) return;
    let s;
    try {
      s = await api(`/api/songs/${id}`);
    } catch {
      aiTimer = setTimeout(tick, 3000);
      return;
    }
    if (id !== songId) return;
    const ai = s.lyrics_ai;
    renderAi(ai);
    if (ai && (ai.state === "queued" || ai.state === "running")) {
      aiTimer = setTimeout(tick, 1500);
      return;
    }
    if (ai && ai.state === "done") {
      song = s;
      settings.offset = s.settings.offset; // a IA zera o ajuste (os tempos ja sao do audio)
      syncControlValues();
      applyOffset();
      renderAi(ai);
      await loadLyrics();
      if (!ai.quiet) toast(aiDoneText(ai), { ms: 5000 });
    } else if (ai && ai.state === "error" && !ai.quiet) {
      toast(`${tr("ia.letra_por_ia")}: ${ai.error}`, { error: true, ms: 6000 });
    }
  };
  tick();
}

async function startAi(body = {}) {
  if (!song) return;
  try {
    const s = await api(`/api/songs/${songId}/align`, { method: "POST", body });
    renderAi(s.lyrics_ai);
    watchAi(songId);
  } catch (err) {
    toast(err.message, { error: true });
  }
}

/** O que o "Ajustar a versao" mudou: ouvir cada trecho e desfazer (ou refazer). */
function reviewChanges() {
  const report = (song && song.lyrics_ai && song.lyrics_ai.report) || {};
  const list = report.changes || [];
  if (!list.length) return toast(tr("ia.nenhuma_mudanca"));
  if (openMenu) closeMenu(openMenu);
  const modal = openModal(tr("ia.mudancas_titulo"), `
    <p class="small muted" style="margin-top:0">${esc(tr("ia.mudancas_texto"))}</p>
    <div class="ai-sugs">${list.map((c) => `
      <label class="ai-sug">
        <input type="checkbox" data-key="${esc(c.key)}"${c.applied === false ? "" : " checked"}>
        ${icon(c.type === "repeat" ? "repeat" : "remove_circle_outline", "sm")}
        <span class="grow">${esc(tr(c.type === "repeat" ? "ia.repetida_aqui" : "ia.nao_cantada"))} — <b>${esc(c.text)}</b>
          <span class="small muted">· ${fmtTime(c.at)}</span></span>
        <button class="btn ghost xs" data-play="${c.at}">${icon("play_arrow", "fill")} ${esc(tr("ia.ouvir"))}</button>
      </label>`).join("")}</div>
    <div class="row" style="margin-top:14px;justify-content:flex-end;gap:8px">
      <button class="btn ghost sm" data-close2>${esc(tr("comum.fechar"))}</button>
      <button class="btn sm" data-apply>${icon("check")} ${esc(tr("ia.aplicar"))}</button>
    </div>`);
  $$("[data-play]", modal).forEach((b) => {
    b.onclick = (e) => {
      e.preventDefault();
      mixer.seek(Math.max(0, Number(b.dataset.play) - 1.5));
      updateLyrics(true);
      setPlaying(true);
    };
  });
  $("[data-close2]", modal).onclick = () => modal.close();
  $("[data-apply]", modal).onclick = () => {
    const reject = $$("input[data-key]", modal).filter((c) => !c.checked).map((c) => c.dataset.key);
    modal.close();
    startAi({ mode: "adapt", reject });
  };
}

function editLyrics() {
  if (!song) return;
  if (openMenu) closeMenu(openMenu);
  setSyncing(false);
  openLyricsEditor(song, {
    time: () => mixer.time,
    seek: (t) => {
      mixer.seek(t);
      updateLyrics(true);
      syncVideo(true);
    },
    play: () => setPlaying(true),
    pause: () => setPlaying(false),
    playing: () => mixer.playing,
    offset: () => settings.offset || 0,
  }, {
    onSaved: async () => {
      await refreshSong();
      await loadLyrics();
      // "Salvar e sincronizar com IA": acompanha
      if (song.lyrics_ai && (song.lyrics_ai.state === "queued" || song.lyrics_ai.state === "running")) watchAi(songId);
    },
  });
}

async function pickCover() {
  if (song && (await chooseCover(song))) await refreshSong();
}

const stemUrl = (name, n) => `${song.stems[name]}${n ? `${song.stems[name].includes("?") ? "&" : "?"}tom=${n}` : ""}`;
let stemToken = 0;
let changingKey = false;

/** Carrega as faixas no tom `shift`. Resolve quando da para tocar; o resto
 *  continua em segundo plano. Tambem serve para trocar o tom no meio da musica:
 *  a musica segue tocando e as faixas novas entram no mesmo ponto. */
async function loadStems() {
  const token = ++stemToken;
  const songToken = loadToken;
  const n = shift;
  const stale = () => token !== stemToken || songToken !== loadToken;
  const initial = !stemsStarted;
  changingKey = !initial;
  const progress = {};
  const label = initial ? (n ? tr("player.carregando_tom", { tom: shiftText(n) }) : tr("player.carregando"))
    : n ? tr("player.mudando_tom", { tom: shiftText(n) }) : tr("player.voltando_tom");
  const report = () => {
    const vals = Object.values(progress);
    const p = vals.length ? Math.round((vals.reduce((a, b) => a + b, 0) / vals.length) * 100) : 0;
    showLoading(`${label}... ${p ? `${p}%` : ""}`);
  };
  // primeiro as faixas que estao tocando (as mudas vem depois, em segundo plano)
  const first = (settings.mode === "original" ? ["original"]
    : ["instrumental", ...(settings.backing_vol > 0 ? ["backing"] : []), ...(settings.lead_vol > 0 ? ["lead"] : [])])
    .filter((s) => song.stems[s]);
  const rest = STEMS.filter((s) => !first.includes(s) && song.stems[s]);
  // as outras faixas estao no tom antigo: saem ate a versao nova chegar
  if (!initial) rest.forEach((name) => mixer.drop(name));
  const fetchOne = (name, foreground) =>
    mixer.fetch(name, stemUrl(name, n), (got, total) => {
      progress[name] = total ? got / total : 0;
      if (foreground && !stale()) report();
    }, stale);
  report();
  let buffers;
  try {
    buffers = await Promise.all(first.map((name) => fetchOne(name, true)));
  } catch (err) {
    if (stale()) return false;
    changingKey = false;
    if (initial) throw err;
    showLoading(null);
    toast(tr("player.tom_falhou", { erro: err.message }), { error: true });
    return false;
  }
  if (stale()) return false;
  mixer.setBuffers(Object.fromEntries(first.map((name, i) => [name, buffers[i]])));
  ensureVoice();
  changingKey = false;
  stemsStarted = true;
  showLoading(null);
  $("#durTime").textContent = fmtTime(mixer.duration);
  $("#seek").max = mixer.duration;
  lastSecond = -1;
  $("#playBtn").disabled = false;
  $("#bigPlay").disabled = false;
  (async () => {
    for (const name of rest) {
      if (stale()) return;
      try {
        const buffer = await fetchOne(name, false);
        if (stale()) return;
        mixer.setBuffers({ [name]: buffer });
        ensureVoice();
      } catch (err) {
        toast(err.message, { error: true });
      }
      if (name === "original" && waitingOriginal && !stale()) {
        waitingOriginal = false;
        showLoading(null);
      }
    }
    if (!stale()) applyMix();
  })();
  return true;
}

let shiftChangedAt = 0;

/** Muda o tom (semitons). No palco, o tom e de quem esta cantando. */
async function setTranspose(n, { fromServer = false } = {}) {
  n = Math.max(-6, Math.min(6, Math.round(Number(n) || 0)));
  if (!song || n === shift) return;
  shift = n;
  if (!fromServer) {
    shiftChangedAt = performance.now();
    if (PARTY && stagedEntry) {
      stagedEntry.transpose = n;
      api("/api/party/transpose", { method: "POST", body: { entry_id: stagedEntry.id, value: n } }).catch(() => {});
    } else {
      setSetting("transpose", n);
    }
  }
  updateKeyUi();
  announceKey();
  if (stemToken) await loadStems();
}

/** Troca a musica do player (sem recarregar a pagina). */
async function loadSong(id, { askLyrics = !PARTY } = {}) {
  const token = ++loadToken;
  mixer.reset();
  setSyncing(false);
  resetVideo();
  clearLyrics();
  $("#playBtn").innerHTML = icon("play_arrow", "fill");
  $("#playBtn").disabled = true;
  $("#bigPlay").disabled = true;
  listened = 0;
  playedSent = false;
  scorer = null;
  if (!PARTY) showScoreCard(null);
  waitingOriginal = false;
  stemsStarted = false;
  changingKey = false;
  stemToken++; // cancela uma troca de tom em andamento
  lastSecond = -1;
  songId = id;
  showLoading(tr("comum.carregando"));
  try {
    await refreshSong();
  } catch (err) {
    if (token === loadToken) showLoading(err.message);
    return false;
  }
  if (token !== loadToken) return false;
  const name = song.track || song.title;
  $("#nowTitle").innerHTML = `${esc(name)}${song.artist ? ` <span class="artist">· ${esc(song.artist)}</span>` : ""}`;
  document.title = `${name} — ${tr("app.nome")}`;
  if (!PARTY) history.replaceState(null, "", `/player?id=${id}`);
  if (song.status !== "ready") {
    showLoading(tr("player.processando"));
    $("#bigPlay").classList.add("hidden");
    return false;
  }
  settings = { ...song.settings };
  lookMode = (song.look && song.look.mode) || "global";
  ownLook = { ...((song.look && song.look.own) || {}) };
  settings.look = lookMode;
  globalLook = await loadGlobalLook({ fresh: true }).catch(() => globalLook || {}); // o padrao pode ter mudado
  shift = PARTY && stagedEntry ? stagedEntry.transpose || 0 : settings.transpose || 0;
  fillKeySelects();
  syncControlValues();
  applyVolume();
  applyMix();
  refreshLook();
  applyOffset();
  applyBackground();
  announceKey();
  loadMelody();
  renderAi(song.lyrics_ai);
  if (song.lyrics_ai && (song.lyrics_ai.state === "queued" || song.lyrics_ai.state === "running")) watchAi(id);
  if (!PARTY) $("#bigPlay").classList.remove("hidden");
  await loadLyrics();
  if (token !== loadToken) return false;
  const ready = loadStems().catch((err) => {
    showLoading(err.message);
    return false;
  });
  if (askLyrics && !song.lyrics) {
    // Se nao tem letra, ja abre a busca; depois a capa.
    const got = await chooseLyrics(song);
    if (got && token === loadToken) {
      await refreshSong();
      await loadLyrics();
    }
    if (!song.cover && token === loadToken) await pickCover();
  }
  return ready;
}

// ======================================================= controle remoto
// (setas/OK/voltar sao do tvnav.js; aqui o que e so do player)
document.addEventListener("karaoke:remote", (e) => {
  const { cmd } = e.detail;
  if (cmd === "playpause") {
    e.preventDefault();
    if ($("#stageOverlay").classList.contains("hidden") || mixer.playing || !mixer.duration) {
      if (mixer.duration) setPlaying(!mixer.playing);
    } else setPlaying(true);
    return;
  }
  if (cmd === "vol_up" || cmd === "vol_down") {
    e.preventDefault();
    const v = Math.max(0, Math.min(1, Math.round((masterVolume() + (cmd === "vol_up" ? 0.1 : -0.1)) * 10) / 10));
    store("karaoke.master", v);
    applyVolume();
    showVolumeOsd(v);
    return;
  }
  // com os controles escondidos, o primeiro toque so mostra os controles (igual TV)
  const nav = ["up", "down", "left", "right", "ok"].includes(cmd);
  const overlay = !$("#stageOverlay").classList.contains("hidden") || !$("#partyIdle").classList.contains("hidden");
  if (nav && !player.classList.contains("ui-on") && !overlay && !document.querySelector(".modal-backdrop")) {
    e.preventDefault();
    showUi();
  }
});

// ============================================================ controles
function bindControls() {
  $("#playBtn").onclick = () => setPlaying(!mixer.playing);
  $("#bigPlay").onclick = (e) => {
    e.stopPropagation();
    setPlaying(true);
  };
  $("#back10").onclick = () => seekBy(-10);
  $("#fwd10").onclick = () => seekBy(10);

  // clique no fundo = tocar/pausar; duplo clique = tela cheia (igual a Netflix)
  let menuOpenOnDown = false;
  $("#stage").addEventListener("pointerdown", () => (menuOpenOnDown = !!openMenu || drawerIsOpen()));
  $("#stage").addEventListener("click", (e) => {
    if (menuOpenOnDown || syncing || e.target.closest(".line, button")) return;
    if (drawerIsOpen()) return setDrawer(false);
    if (!mixer.duration) return;
    setPlaying(!mixer.playing);
  });
  $("#stage").addEventListener("dblclick", (e) => !e.target.closest(".line, button") && toggleFullscreen());

  $$("#modeSeg button").forEach((b) => {
    b.onclick = () => {
      setSetting("mode", b.dataset.mode);
      applyMix();
    };
  });
  const range = (id, key, after) => {
    $(id).addEventListener("input", (e) => {
      setSetting(key, Number(e.target.value));
      after();
    });
  };
  range("#leadVol", "lead_vol", applyMix);
  range("#backVol", "backing_vol", applyMix);
  $$(".lk-mode-slot").forEach((slot) => (slot.innerHTML = lookModeHtml()));
  $$(".lk-mode button").forEach((b) => (b.onclick = () => setLookMode(b.dataset.mode)));
  lookControls = [
    mountLookControls($("#lookBg"), ["fundo"], changeLook),
    mountLookControls($("#lookText"), ["letra", "borda"], changeLook, { details: ["borda"] }),
  ];
  $("#master").addEventListener("input", (e) => {
    store("karaoke.master", Number(e.target.value));
    applyVolume();
  });

  const seek = $("#seek");
  seek.addEventListener("input", () => {
    dragging = true;
    $("#curTime").textContent = fmtTime(Number(seek.value));
  });
  seek.addEventListener("change", () => {
    dragging = false;
    mixer.seek(Number(seek.value));
    updateLyrics(true);
    syncVideo(true);
  });

  $("#keySel").onchange = () => setKey($("#keySel").value, $("#scaleSel").value);
  $("#scaleSel").onchange = () => setKey($("#keySel").value, $("#scaleSel").value);
  $("#pianoBtn").onclick = openPiano;
  $("#tDown").onclick = () => setTranspose(shift - 1);
  $("#tUp").onclick = () => setTranspose(shift + 1);
  $("#tVal").onclick = () => setTranspose(0);
  let midiMounted = false;
  $("#keyMenu").addEventListener("menuopen", () => {
    if (midiMounted) return;
    midiMounted = true;
    mountMidiPicker($("#midiBox"), { getKey: sungKey });
  });


  $$("[data-off]").forEach((b) => {
    b.onclick = () => {
      setSetting("offset", Math.round(((settings.offset || 0) + Number(b.dataset.off)) * 100) / 100);
      applyOffset();
    };
  });
  $("#offsetVal").onclick = () => {
    setSetting("offset", 0);
    applyOffset();
  };
  $("#syncMouse").onclick = () => {
    if (!lines.length) return toast(tr("player.precisa_sincronizada"), { error: true });
    setSyncing(!syncing);
    if (syncing && !mixer.playing) setPlaying(true);
  };
  $$("#scoreSeg button").forEach((b) => (b.onclick = () => setScoring(b.dataset.score === "on")));
  $("#micSel").onchange = async (e) => {
    scoreCfg = { ...scoreCfg, device: e.target.value };
    saveScoreCfg();
    if (scoreCfg.on) await setScoring(true);
  };
  $("#laneToggle").onchange = (e) => {
    scoreCfg = { ...scoreCfg, lane: e.target.checked };
    saveScoreCfg();
    applyScoreUi();
  };
  $("#scAgain").onclick = () => {
    showScoreCard(null);
    mixer.seek(0);
    if (scorer) scorer.reset();
    setPlaying(true);
  };
  $("#scClose").onclick = () => showScoreCard(null);
  $("#scoreCard").addEventListener("click", (e) => {
    e.stopPropagation();
    if (e.target === e.currentTarget) showScoreCard(null); // clique fora fecha
  });
  applyScoreUi();
  if (scoreCfg.on) setScoring(true);
  $("#fsBtn").onclick = toggleFullscreen;
  $("#lyricsBtn").onclick = pickLyrics;
  $("#findLyrics").onclick = pickLyrics;
  $("#writeLyrics").onclick = editLyrics;
  $("#editLyrics").onclick = editLyrics;
  $("#aiLyrics").onclick = () => {
    if (openMenu) closeMenu(openMenu);
    startAi({ mode: "sync" });
  };
  $("#aiAdapt").onclick = () => {
    if (openMenu) closeMenu(openMenu);
    startAi({ mode: "adapt" });
  };
  $("#coverBtn").onclick = pickCover;

  // Tira o foco dos botoes depois do clique, senao o espaco "clica" de novo
  document.addEventListener("click", (e) => {
    const b = e.target.closest("button");
    if (b && !b.closest(".modal")) b.blur();
  });

  document.addEventListener("keydown", (e) => {
    const k = e.key.toLowerCase();
    const field = e.target.closest && e.target.closest("input, select, textarea");
    if (field && (field.type !== "range" || k.startsWith("arrow"))) return;
    if (document.querySelector(".modal-backdrop")) return;
    if (k === " " || k === "k") {
      e.preventDefault();
      if (mixer.duration) setPlaying(!mixer.playing);
    } else if (k === "arrowleft" || k === "arrowright") {
      e.preventDefault();
      seekBy(k === "arrowleft" ? -5 : 5);
    } else if (k === "f") {
      toggleFullscreen();
    } else if (k === "m") {
      const v = masterVolume();
      if (v > 0) store("karaoke.lastMaster", v);
      store("karaoke.master", v > 0 ? 0 : Number(store("karaoke.lastMaster") || 1));
      applyVolume();
      showVolumeOsd(masterVolume());
    } else if (k === "v") {
      settings._lastLead = settings.lead_vol > 0 ? settings.lead_vol : settings._lastLead || 1;
      setSetting("lead_vol", settings.lead_vol > 0 ? 0 : settings._lastLead);
      $("#leadVol").value = settings.lead_vol;
      applyMix();
      toast(tr(settings.lead_vol > 0 ? "player.voz_ligada" : "player.voz_desligada"), { key: "guia" });
    } else if (k === "," || k === ".") {
      setSetting("offset", Math.round(((settings.offset || 0) + (k === "," ? -0.1 : 0.1)) * 100) / 100);
      applyOffset();
    } else if (k === "-" || k === "_" || k === "=" || k === "+") {
      if (song) setTranspose(shift + (k === "-" || k === "_" ? -1 : 1));
    } else if (k === "n" && PARTY) {
      skipSinger();
    } else if (k === "escape") {
      if (syncing) setSyncing(false);
      if (openMenu) closeMenu(openMenu);
      if (drawerIsOpen()) setDrawer(false);
    }
  });
}

// ============================================================ modo palco
let partyState = null;
let stagedEntry = null; // entrada da fila carregada no palco
let lastCommand = null; // ultimo comando executado (null = ainda nao sabe)
let endedSent = null;
let drawer = null; // gaveta da fila (queuedrawer.js), so no palco
let stageBlocked = false;

const drawerIsOpen = () => !!(drawer && drawer.isOpen);
function setDrawer(open) {
  if (!drawer) return;
  if (open) drawer.open();
  else drawer.close();
}

/** Palco aberto na TV: este (numa janela comum) fica parado. */
function blockStage(on) {
  if (on === stageBlocked) return;
  stageBlocked = on;
  $("#stageBlock").classList.toggle("hidden", !on);
  if (on) {
    // esquece a entrada ANTES de pausar: esta janela nao avisa o servidor (quem manda e a TV)
    stagedEntry = null; // quando liberar, carrega de novo quem estiver no palco
    mixer.pause();
    setPlaying(false);
    mixer.reset();
    clearLyrics();
    resetVideo();
    song = null;
    setDrawer(false);
    $("#stageOverlay").classList.add("hidden");
    $("#partyIdle").classList.add("hidden");
    $("#unlock").classList.add("hidden");
  }
}

function partyReport(state) {
  if (!PARTY || !stagedEntry) return;
  lastReportAt = performance.now();
  api("/api/party/playback", {
    method: "POST",
    body: { entry_id: stagedEntry.id, state, position: mixer.time, duration: mixer.duration, guide: settings.lead_vol > 0 },
  }).catch(() => {});
}

function songEnded(score = null) {
  if (!PARTY || !stagedEntry || endedSent === stagedEntry.id) return;
  endedSent = stagedEntry.id;
  partyReport("ended");
  api("/api/party/ended", { method: "POST", body: { entry_id: stagedEntry.id, score } })
    .then((p) => applyParty(p))
    .catch(() => {});
}

async function passTurn() {
  if (!stagedEntry) return;
  const who = stagedEntry.singer;
  try {
    applyParty(await api("/api/party/pass", { method: "POST", body: { entry_id: stagedEntry.id } }));
    toast(tr("player.passou_vez", { nome: who }), { ms: 4000 });
  } catch (err) {
    toast(err.message, { error: true });
  }
}

async function skipSinger() {
  try {
    applyParty(await api("/api/party/command", { method: "POST", body: { action: "skip" } }));
  } catch (err) {
    toast(err.message, { error: true });
  }
}

function runCommand(action) {
  if (action === "play") setPlaying(true);
  else if (action === "pause") setPlaying(false);
  else if (action === "restart") {
    mixer.seek(0);
    setPlaying(true);
  } else if (action === "skip") {
    mixer.pause();
  } else if (action === "guide_on" || action === "guide_off") {
    // voz guia pedida pelo celular: vale so para esta vez (nao muda o padrao da musica)
    const on = action === "guide_on";
    if (on) settings.lead_vol = settings._lastLead > 0 ? settings._lastLead : 0.6;
    else {
      if (settings.lead_vol > 0) settings._lastLead = settings.lead_vol;
      settings.lead_vol = 0;
    }
    $("#leadVol").value = settings.lead_vol;
    applyMix();
    toast(tr(on ? "player.guia_ligada" : "player.guia_desligada"), { key: "guia" });
    partyReport(mixer.playing ? "playing" : "paused");
  }
}

function nextUp(p, count = 3) {
  return (p.queue || []).filter((e) => e.ready).slice(0, count);
}

function showStage(entry, p) {
  const s = entry.song || {};
  $("#poCover").src = s.cover || s.thumb || "";
  $("#poSinger").innerHTML = `${entry.person && entry.person.id ? avatar(entry.person) : ""}${esc(entry.singer)}`;
  $("#poSong").innerHTML = `${esc(s.track || s.title || "")}${s.artist ? ` <span class="muted">· ${esc(s.artist)}</span>` : ""}${entry.transpose ? ` <span class="shift-badge">${esc(tr("player.tom_badge", { tom: shiftText(entry.transpose) }))}</span>` : ""}`;
  $("#poHint").textContent = entry.mine ? "" : tr("player.play_pelo_celular", { nome: entry.singer });
  const next = nextUp(p);
  $("#poPass").classList.toggle("hidden", !next.length);
  $("#poNext").innerHTML = next.length
    ? `<span class="po-next-title">${esc(tr("player.a_seguir"))}</span>${next.map((e) => `<span class="po-next-item">${e.person && e.person.id ? avatar(e.person, "sm") : ""}<b>${esc(e.singer)}</b> · ${esc(e.song.track || e.song.title)}</span>`).join("")}`
    : "";
  $("#stageOverlay").classList.remove("hidden");
}

async function showIdle(p) {
  $("#stageOverlay").classList.add("hidden");
  $("#partyIdle").classList.remove("hidden");
  const waiting = (p.queue || []).filter((e) => !e.ready);
  $("#idleText").textContent = waiting.length
    ? tr("player.fila_preparando")
    : tr("player.ninguem_fila");
  // a previsao da fila de trabalho ("pronta em ~8 min"), como na biblioteca e no celular
  $("#idleWaiting").innerHTML = waiting.map((e) => {
    const q = e.song.queue;
    return `<div class="idle-item"><b>${esc(e.singer)}</b> · ${esc(e.song.track || e.song.title)} <span class="badge gray">${Math.round((e.song.progress || 0) * 100)}%${q ? ` · ${readyIn(q.eta)}` : ""}</span></div>`;
  }).join("");

}

/** QR e endereco para entrar pelo celular. Se o IP do PC mudar, troca sozinho e avisa. */
let qrUrl = null;
function updateQr(p) {
  if (!p.lan_url || p.lan_url === qrUrl) return;
  if (qrUrl) toast(tr("player.endereco_mudou"), { ms: 12000 });
  qrUrl = p.lan_url;
  const src = `/api/qr.svg?u=${encodeURIComponent(qrUrl)}`;
  $("#poQr").src = src;
  $("#idleQr").src = src;
  $("#poUrl").textContent = qrUrl.replace(/^https?:\/\//, "");
  $("#idleUrl").textContent = qrUrl;
}

function renderDrawer(p) {
  if (drawer) drawer.render(p);
}

function updateUpNext(t) {
  const pill = $("#upNext");
  if (!PARTY || !partyState || !mixer.playing || !mixer.duration) return pill.classList.add("hidden");
  const next = nextUp(partyState, 1)[0];
  const left = mixer.duration - t;
  if (next && left < 25) {
    pill.innerHTML = `${icon("skip_next", "sm")} ${esc(tr("player.a_seguir"))}: <b>${esc(next.singer)}</b> · ${esc(next.song.track || next.song.title)}`;
    pill.classList.remove("hidden");
  } else pill.classList.add("hidden");
}

let applying = false;
async function applyParty(p) {
  if (!p || applying) return;
  // o palco ja esta aberto na TV (e esta janela nao e a TV): fica parado
  blockStage(!IS_TV && !!p.tv_stage);
  if (stageBlocked) return;
  applying = true;
  try {
    partyState = p;
    updateQr(p);
    renderDrawer(p);
    // na primeira leitura so anota o ultimo comando (nao executa comandos antigos)
    if (lastCommand === null) lastCommand = p.command ? p.command.id : 0;
    const cur = p.current;
    document.body.classList.toggle("stage-free", !cur || !cur.ready);
    if (!cur || !cur.ready) {
      if (stagedEntry) {
        stagedEntry = null;
        mixer.reset();
        clearLyrics();
        resetVideo();
        song = null;
        $("#nowTitle").textContent = tr("player.palco_livre");
        document.title = tr("player.pagina_palco");
        $("#playBtn").disabled = true;
      }
      showIdle(p);
      return;
    }
    $("#partyIdle").classList.add("hidden");
    if (!stagedEntry || stagedEntry.id !== cur.id) {
      stagedEntry = cur;
      endedSent = null;
      showStage(cur, p);
      await loadSong(cur.song_id, { askLyrics: false });
      if (stagedEntry && stagedEntry.id === cur.id && !mixer.playing) partyReport("waiting");
    } else {
      // o tom pode ter mudado pelo celular (ignora logo depois de mudar aqui)
      stagedEntry.transpose = cur.transpose;
      if (song && stemsStarted && (cur.transpose || 0) !== shift && performance.now() - shiftChangedAt > 4000) {
        toast(tr("player.mudou_tom", { nome: cur.singer, tom: shiftText(cur.transpose || 0) }));
        setTranspose(cur.transpose || 0, { fromServer: true });
      }
      if (!mixer.playing && mixer.offset === 0 && !$("#stageOverlay").classList.contains("hidden")) {
        showStage(cur, p); // atualiza "a seguir"
      }
    }
    if (p.command && p.command.id > lastCommand) {
      lastCommand = p.command.id;
      if (p.command.entry === cur.id) runCommand(p.command.action);
    }
  } finally {
    applying = false;
  }
}

// reacoes da plateia (pelos celulares), subindo pela tela
const REACTION_ICONS = {
  clap: ["sign_language", "#ffd23f"],
  heart: ["favorite", "#ff4d6d"],
  fire: ["local_fire_department", "#ff8a00"],
  laugh: ["sentiment_very_satisfied", "#ffd23f"],
  star: ["star", "#fff176"],
  wow: ["auto_awesome", "#8be9fd"],
}; /* icons: sign_language favorite local_fire_department sentiment_very_satisfied star auto_awesome */
let reactionSeq = null;

function floatReaction(r, i) {
  const [name, color] = REACTION_ICONS[r.kind] || REACTION_ICONS.heart;
  const el = document.createElement("div");
  el.className = "reaction";
  el.style.left = `${6 + Math.random() * 88}%`;
  el.style.setProperty("--drift", `${(Math.random() - 0.5) * 120}px`);
  el.style.setProperty("--size", `${44 + Math.random() * 30}px`);
  el.style.animationDelay = `${Math.min(i, 12) * 0.12}s`;
  el.innerHTML = `<span class="ms fill" style="color:${color}">${name}</span>${r.name ? `<small>${esc(r.name)}</small>` : ""}`;
  $("#reactions").append(el);
  setTimeout(() => el.remove(), 4200 + Math.min(i, 12) * 120);
}

function showReactions(p) {
  if (reactionSeq === null) {
    reactionSeq = p.reaction_seq || 0; // nao mostra as antigas ao abrir o palco
    return;
  }
  const list = p.reactions || [];
  if ($$(".reaction").length < 40) list.forEach(floatReaction);
  reactionSeq = Math.max(reactionSeq, p.reaction_seq || 0);
}

let pollTimer = null;
async function pollNow() {
  clearTimeout(pollTimer);
  try {
    const p = await api(`/api/party${reactionSeq !== null ? `?since=${reactionSeq}` : ""}`);
    showReactions(p);
    await applyParty(p);
  } catch {
    /* servidor reiniciando */
  }
  pollTimer = setTimeout(pollNow, 1000);
}

function startParty() {
  document.body.classList.add("party", "stage-free"); // livre ate a fila dizer quem canta
  $("#bigPlay").classList.add("hidden");
  showLoading(null);
  $("#nowTitle").textContent = tr("player.palco");
  document.title = tr("player.pagina_palco");
  $("#unlock").classList.remove("hidden");
  if (IS_TV && new URLSearchParams(location.search).get("quiosque") === "1") {
    // o quiosque trava a tela cheia: diz na TV como sair (so ao abrir)
    toast(tr("player.quiosque"), { ms: 12000 });
  }
  // janela do "Palco na TV" (som liberado pelo navegador): nao precisa do clique
  Promise.race([mixer.ctx.resume().catch(() => {}), new Promise((r) => setTimeout(r, 400))]).then(() => {
    if (mixer.unlocked) $("#unlock").classList.add("hidden");
  });
  $("#unlockBtn").onclick = async () => {
    await mixer.ctx.resume().catch(() => {});
    $("#unlock").classList.add("hidden");
    showUi();
  };
  $("#poStart").onclick = (e) => {
    e.stopPropagation();
    setPlaying(true);
  };
  $("#skipBtn").onclick = skipSinger;
  $("#poPass").onclick = (e) => {
    e.stopPropagation();
    passTurn();
  };
  drawer = queueDrawer({ onChange: pollNow, onOpen: showUi, parent: $("#player") });
  $("#queueBtn").onclick = (e) => {
    e.stopPropagation();
    setDrawer(!drawerIsOpen());
  };
  $("#idleAdd").onclick = () => pickSongForQueue({ onDone: pollNow });
  $("#sbTakeOver").onclick = async () => {
    if (!confirm(tr("player.usar_este_confirmar"))) return;
    await api("/api/stage/close", { method: "POST" }).catch((err) => toast(err.message, { error: true }));
    toast(tr("player.palco_tv_fechado"));
  };
  pollNow();
}

// ================================================================== init
async function init() {
  setupMenus();
  bindControls();
  initMidi().then(() => announceKey());
  requestAnimationFrame(loop);
  showUi();
  if (PARTY) return startParty();
  if (!songId) {
    location.href = "/cantar";
    return;
  }
  await loadSong(songId);
}

init();

