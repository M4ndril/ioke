// Home: metade "Adicionar musicas" e metade "Cantar" com o carrossel de capas.
import { $, api, biblioteca, esc, icon, store, toast } from "./common.js";
import { mountFabs } from "./floating.js";
import "./tvnav.js";
import "./stageopen.js";
import { initI18n, t } from "./i18n.js";

await initI18n(); // os textos antes de desenhar a pagina

mountFabs({ qr: true });

const ROWS = 6;
const MIN_TILES = 14; // por fileira, antes de duplicar para o loop infinito
const MAX_PER_ROW = 18; // capas diferentes por fileira
const SECONDS_PER_TILE = 9; // quanto maior, mais devagar

let lastSig = null;

function shuffle(list, seed) {
  // embaralhamento deterministico por fileira (nao "pula" a cada atualizacao)
  const a = [...list];
  let s = seed * 9301 + 49297;
  for (let i = a.length - 1; i > 0; i--) {
    s = (s * 9301 + 49297) % 233280;
    const j = Math.floor((s / 233280) * (i + 1));
    [a[i], a[j]] = [a[j], a[i]];
  }
  return a;
}

const PLACEHOLDER_COLORS = [
  ["#e50914", "#5a0208"], ["#7b2cff", "#1d0647"], ["#00a8e8", "#032c44"],
  ["#ff7a00", "#4a1f00"], ["#15c39a", "#023d30"], ["#ff3fa4", "#4a0630"],
];

function tileHtml(src) {
  return `<div class="tile"><img src="${esc(src)}" alt="" decoding="async" draggable="false"></div>`;
}

function placeholderHtml(i) {
  const [a, b] = PLACEHOLDER_COLORS[i % PLACEHOLDER_COLORS.length];
  const name = i % 2 ? icon("queue_music") : icon("music_note");
  return `<div class="tile placeholder" style="background:linear-gradient(135deg,${a},${b})">${name}</div>`;
}

function build(songs) {
  const plane = $("#plane");
  const covers = songs.map((s) => s.art_sm || s.cover || s.thumb).filter(Boolean);
  const rows = [];
  for (let r = 0; r < ROWS; r++) {
    let seq = [];
    if (covers.length) {
      // bibliotecas grandes: cada fileira mostra um "recorte" diferente, sem pesar
      let pool = covers;
      if (covers.length > MAX_PER_ROW) {
        const start = (r * 11) % covers.length;
        pool = Array.from({ length: MAX_PER_ROW }, (_, i) => covers[(start + i) % covers.length]);
      }
      while (seq.length < MIN_TILES) seq.push(...shuffle(pool, r + seq.length + 1));
      seq = seq.map(tileHtml);
    } else {
      seq = Array.from({ length: MIN_TILES }, (_, i) => placeholderHtml(i + r * 3));
    }
    const html = seq.join("");
    const duration = seq.length * SECONDS_PER_TILE * (1 + (r % 3) * 0.18);
    const delay = -((r * 0.37) % 1) * duration;
    rows.push(`
      <div class="row">
        <div class="track${r % 2 ? " rev" : ""}" style="animation-duration:${duration}s;animation-delay:${delay}s">${html}${html}</div>
      </div>`);
  }
  plane.innerHTML = rows.join("");
}

function showParty(p) {
  const cur = p.current;
  const n = (p.queue || []).length;
  const parts = [];
  if (cur) parts.push(t("inicio.no_palco", { nome: cur.singer }));
  if (n) parts.push(t("inicio.na_fila", { n }));
  $("#partyInfo").textContent = parts.join(" · ") || t("inicio.fila_celular");
  $("#partyPill").classList.toggle("live", !!(cur || n));
}

async function refresh() {
  api("/api/party").then(showParty).catch(() => {});
  try {
    const [state, bib] = await Promise.all([api("/api/state?musicas=0"), biblioteca()]);
    const songs = bib.songs;
    const sig = songs.map((s) => s.id + (s.cover || s.thumb)).join("|");
    if (sig !== lastSig) {
      const plane = $("#plane");
      if (lastSig === null) build(songs);
      else {
        // troca suave quando entram musicas novas
        plane.classList.add("fading");
        setTimeout(() => {
          build(songs);
          plane.classList.remove("fading");
        }, 800);
      }
      lastSig = sig;
    }
    const n = songs.length;
    $("#singEyebrow").textContent = n ? t("inicio.prontas", { n }) : t("sing.biblioteca");
    const jobs = (state.jobs || []).filter((j) => j.status !== "error").length;
    $("#addEyebrow").textContent = jobs ? t("inicio.processando", { n: jobs }) : t("inicio.adicionar_eyebrow");
  } catch {
    /* servidor reiniciando */
  }
  setTimeout(refresh, 5000);
}

refresh();

// app instalado: ao abrir ele procura atualizacoes sozinho e aqui so avisa (uma vez por versao)
async function updateNotice(tries = 6) {
  try {
    const st = await api("/api/app");
    if (!st.app) return;
    if (st.update_available && store("karaoke.updateSeen") !== st.latest) {
      store("karaoke.updateSeen", st.latest);
      toast(t("inicio.atualizacao", { versao: st.latest }), { ms: 12000 });
    } else if (!st.checked_at && tries > 0) setTimeout(() => updateNotice(tries - 1), 20000);
  } catch {
    /* sem servidor ou outro aparelho */
  }
}
setTimeout(updateNotice, 5000);
