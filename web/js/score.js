// Pontuacao pelo microfone (estilo SingStar): compara a afinacao de quem canta
// com a melodia da voz original (notas tiradas do stem "lead" no servidor) e
// desenha a faixa de notas. A oitava nao importa: vale cantar mais grave ou
// mais agudo que o cantor original.
import { t as tr } from "./i18n.js";

const MIN_HZ = 70;
const MAX_HZ = 1000;

/** Distancia em semitons ignorando a oitava, em [-6, 6). */
export const foldSemis = (d) => ((((d % 12) + 18) % 12) - 6);

// ================================================================ microfone
export class Mic {
  constructor(ctx) {
    this.ctx = ctx;
    this.stream = null;
    this.analyser = null;
    this.buf = null;
    this.noise = 0.01;
    this.deviceId = null;
  }

  get on() {
    return !!this.stream;
  }

  async start(deviceId) {
    this.stop();
    const audio = { echoCancellation: false, noiseSuppression: false, autoGainControl: false };
    if (deviceId) audio.deviceId = { exact: deviceId };
    this.stream = await navigator.mediaDevices.getUserMedia({ audio });
    this.deviceId = deviceId || null;
    this.source = this.ctx.createMediaStreamSource(this.stream);
    this.analyser = this.ctx.createAnalyser();
    this.analyser.fftSize = 2048;
    this.source.connect(this.analyser); // nao vai para as caixas (sem microfonia)
    this.buf = new Float32Array(this.analyser.fftSize);
    const factor = Math.max(1, Math.round(this.ctx.sampleRate / 16000));
    this.factor = factor;
    this.small = new Float32Array(Math.floor(this.buf.length / factor));
    this.rate = this.ctx.sampleRate / factor;
  }

  stop() {
    if (this.stream) this.stream.getTracks().forEach((t) => t.stop());
    if (this.source) this.source.disconnect();
    this.stream = null;
    this.source = null;
    this.analyser = null;
  }

  /** Afinacao agora: { midi, level } ou null (silencio / sem nota clara). */
  read() {
    if (!this.analyser) return null;
    this.analyser.getFloatTimeDomainData(this.buf);
    let sum = 0;
    for (let i = 0; i < this.buf.length; i++) sum += this.buf[i] * this.buf[i];
    const rms = Math.sqrt(sum / this.buf.length);
    // piso de ruido que se adapta (a musica vazando no microfone tambem conta)
    this.noise = rms < this.noise ? rms : this.noise * 1.0015 + 1e-6;
    const level = Math.min(1, rms * 8);
    if (rms < Math.max(0.006, this.noise * 3)) return { midi: null, level };
    const f = this.factor;
    for (let i = 0; i < this.small.length; i++) {
      let s = 0;
      for (let k = 0; k < f; k++) s += this.buf[i * f + k];
      this.small[i] = s / f;
    }
    const hz = yin(this.small, this.rate);
    if (!hz) return { midi: null, level };
    return { midi: 69 + 12 * Math.log2(hz / 440), level };
  }
}

/** YIN (de Cheveigne & Kawahara) simplificado. */
function yin(buf, rate) {
  const maxTau = Math.min(Math.floor(rate / MIN_HZ), Math.floor(buf.length / 2));
  const minTau = Math.max(2, Math.floor(rate / MAX_HZ));
  const w = buf.length - maxTau - 1;
  if (w < 64) return null;
  const d = new Float32Array(maxTau + 2);
  for (let tau = 1; tau <= maxTau + 1; tau++) {
    let s = 0;
    for (let i = 0; i < w; i++) {
      const x = buf[i] - buf[i + tau];
      s += x * x;
    }
    d[tau] = s;
  }
  let run = 0;
  d[0] = 1;
  for (let tau = 1; tau < d.length; tau++) {
    run += d[tau];
    d[tau] = run ? (d[tau] * tau) / run : 1;
  }
  let tau = -1;
  for (let t = minTau; t <= maxTau; t++) {
    if (d[t] < 0.15) {
      while (t + 1 <= maxTau && d[t + 1] < d[t]) t++;
      tau = t;
      break;
    }
  }
  if (tau < 1) return null;
  const a = d[tau - 1];
  const c = d[tau + 1];
  const den = a + c - 2 * d[tau];
  const better = den > 0 ? tau + (a - c) / (2 * den) : tau;
  return rate / better;
}

// ================================================================ pontuacao
export class Scorer {
  constructor(melody) {
    this.notes = (melody && melody.notes) || [];
    this.range = melody && melody.range;
    this.reset();
  }

  reset() {
    this.total = 0; // segundos de voz na musica original ate agora
    this.hit = 0; // quanto disso a pessoa acertou (ponderado)
    this.sung = 0; // segundos em que a pessoa cantou alguma nota
    this.trail = []; // { t, midi (dobrado), hit }
    this.hits = new Float32Array(this.notes.length); // acerto por nota (para colorir)
  }

  get ready() {
    return this.notes.length > 0;
  }

  /** Indice da primeira nota que termina depois de t. */
  _from(t) {
    let lo = 0;
    let hi = this.notes.length;
    while (lo < hi) {
      const mid = (lo + hi) >> 1;
      if (this.notes[mid][1] <= t) lo = mid + 1;
      else hi = mid;
    }
    return lo;
  }

  /** t = tempo da musica em que a voz lida AGORA foi cantada; shift = transposicao. */
  update(t, reading, dt, shift = 0) {
    if (!this.notes.length || dt <= 0 || dt > 0.25) return;
    const tol = 0.14; // folga de tempo (latencia, respiro)
    let main = -1;
    const cands = [];
    for (let i = this._from(t - tol); i < this.notes.length && this.notes[i][0] <= t + tol; i++) {
      cands.push(i);
      if (this.notes[i][0] <= t && t < this.notes[i][1]) main = i;
    }
    if (main >= 0) this.total += dt;
    const midi = reading && reading.midi;
    if (midi == null) return;
    this.sung += dt;
    let best = null;
    for (const i of cands) {
      const d = foldSemis(midi - (this.notes[i][2] + shift));
      if (!best || Math.abs(d) < Math.abs(best.d)) best = { i, d };
    }
    const dist = best ? Math.abs(best.d) : 99;
    const credit = dist <= 0.6 ? 1 : dist <= 1.5 ? (1.5 - dist) / 0.9 : 0;
    if (main >= 0 && credit > 0) {
      this.hit += dt * credit;
      this.hits[best.i] += dt * credit;
    }
    // para desenhar: a voz dobrada para perto da nota de referencia
    const ref = best ? this.notes[best.i][2] + shift : this._nearbyRef(t, shift);
    const shown = ref == null ? null : ref + foldSemis(midi - ref);
    this.trail.push({ t, midi: shown, hit: credit });
    while (this.trail.length && this.trail[0].t < t - 2) this.trail.shift();
  }

  _nearbyRef(t, shift) {
    const i = Math.min(this.notes.length - 1, this._from(t));
    return i >= 0 && this.notes[i] ? this.notes[i][2] + shift : null;
  }

  /** Nota de 0 a 100 (null enquanto ha pouco para avaliar). */
  get score() {
    if (this.total < 3) return null;
    const ratio = Math.min(1, this.hit / this.total);
    return Math.round(100 * Math.pow(ratio, 0.7));
  }
}

export function scoreVerdict(score) {
  if (score == null) return "";
  const nivel = score >= 95 ? 5 : score >= 85 ? 4 : score >= 70 ? 3 : score >= 50 ? 2 : score >= 30 ? 1 : 0;
  return tr(`pontuacao.nivel${nivel}`);
}

// ============================================================ faixa de notas
const PAST = 1.6;
const AHEAD = 4.4;

export function drawLane(canvas, scorer, t, shift = 0) {
  const dpr = window.devicePixelRatio || 1;
  const w = canvas.clientWidth;
  const h = canvas.clientHeight;
  if (!w || !h) return;
  if (canvas.width !== Math.round(w * dpr) || canvas.height !== Math.round(h * dpr)) {
    canvas.width = Math.round(w * dpr);
    canvas.height = Math.round(h * dpr);
  }
  const g = canvas.getContext("2d");
  g.setTransform(dpr, 0, 0, dpr, 0, 0);
  g.clearRect(0, 0, w, h);
  const range = scorer.range || [55, 70];
  const lo = range[0] + shift - 2;
  const hi = Math.max(range[1] + shift + 2, lo + 10);
  const pad = 8;
  const x = (tt) => ((tt - (t - PAST)) / (PAST + AHEAD)) * w;
  const y = (m) => h - pad - ((Math.max(lo, Math.min(hi, m)) - lo) / (hi - lo)) * (h - pad * 2);
  const barH = Math.max(6, Math.min(16, ((h - pad * 2) / (hi - lo)) * 0.9));

  // linhas de fundo (cada tom inteiro)
  g.strokeStyle = "rgba(255,255,255,0.05)";
  g.lineWidth = 1;
  for (let m = Math.ceil(lo); m <= hi; m += 2) {
    g.beginPath();
    g.moveTo(0, y(m) + 0.5);
    g.lineTo(w, y(m) + 0.5);
    g.stroke();
  }
  // notas da voz original
  const notes = scorer.notes;
  for (let i = scorer._from(t - PAST); i < notes.length && notes[i][0] < t + AHEAD; i++) {
    const [a, b, m] = notes[i];
    const x0 = x(a);
    const x1 = Math.max(x0 + 3, x(b) - 1);
    const yy = y(m + shift) - barH / 2;
    const dur = b - a;
    const got = dur > 0 ? Math.min(1, scorer.hits[i] / dur / 0.8) : 0;
    g.fillStyle = b >= t ? "rgba(255,255,255,0.28)" : got > 0.05 ? `rgba(94,226,122,${0.3 + got * 0.6})` : "rgba(255,255,255,0.1)";
    roundRect(g, x0, yy, x1 - x0, barH, barH / 2);
    g.fill();
  }
  // linha do "agora"
  const nx = x(t);
  g.fillStyle = "rgba(255,255,255,0.7)";
  g.fillRect(nx - 1, 0, 2, h);
  // voz de quem canta
  let prev = null;
  g.lineCap = "round";
  for (const p of scorer.trail) {
    if (p.midi == null) {
      prev = null;
      continue;
    }
    const px = x(p.t);
    const py = y(p.midi);
    const color = p.hit >= 0.99 ? "#5ee27a" : p.hit > 0 ? "#ffd23f" : "#ff5f6d";
    if (prev && p.t - prev.t < 0.12) {
      g.strokeStyle = color;
      g.lineWidth = 4;
      g.beginPath();
      g.moveTo(prev.x, prev.y);
      g.lineTo(px, py);
      g.stroke();
    }
    prev = { x: px, y: py, t: p.t };
  }
  const last = scorer.trail[scorer.trail.length - 1];
  if (last && last.midi != null && t - last.t < 0.15) {
    g.fillStyle = "#fff";
    g.beginPath();
    g.arc(nx, y(last.midi), 5, 0, Math.PI * 2);
    g.fill();
  }
}

function roundRect(g, x, y, w, h, r) {
  r = Math.min(r, w / 2, h / 2);
  g.beginPath();
  g.moveTo(x + r, y);
  g.arcTo(x + w, y, x + w, y + h, r);
  g.arcTo(x + w, y + h, x, y + h, r);
  g.arcTo(x, y + h, x, y, r);
  g.arcTo(x, y, x + w, y, r);
  g.closePath();
}
