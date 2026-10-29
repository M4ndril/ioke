// Home: metade "Adicionar musicas" e metade "Cantar" com o carrossel de capas.
import { $, api, biblioteca, confirmar, esc, icon, openModal, store, toast } from "./common.js";
import { mountFabs } from "./floating.js";
import "./tvnav.js";
import "./stageopen.js";
import { initI18n, t } from "./i18n.js";

await initI18n(); // os textos antes de desenhar a pagina

mountFabs({ qr: true, settings: true, atividades: true });

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

// app instalado: ao abrir ele procura atualizacoes sozinho e aqui pergunta se quer atualizar. "Depois" pergunta de
// novo na proxima vez que o app abrir; "Pular" so na versao seguinte. Nunca instala sem a pessoa mandar.
const sessao = (v) => {
  try {
    if (v === undefined) return sessionStorage.getItem("karaoke.updateLater");
    sessionStorage.setItem("karaoke.updateLater", v);
  } catch {
    /* sem sessionStorage: pergunta de novo ao voltar ao inicio */
  }
};

async function updateNotice(tries = 6) {
  try {
    const st = await api("/api/app");
    if (!st.app || document.body.classList.contains("mobile")) return;
    if (!st.checked_at) return tries > 0 && setTimeout(() => updateNotice(tries - 1), 20000);
    const v = st.latest;
    if (!st.update_available || store("karaoke.updateSkip") === v || sessao() === v) return;
    // outra janela aberta (o aviso de primeiro uso, por exemplo): espera ela fechar
    if (document.querySelector(".modal-backdrop")) return tries > 0 && setTimeout(() => updateNotice(tries - 1), 5000);
    sessao(v);
    updateModal(st);
  } catch {
    /* sem servidor ou outro aparelho */
  }
}
setTimeout(updateNotice, 5000);

function updateModal(st) {
  const v = st.latest;
  const notas = ((st.available || []).find((x) => x.version === v)?.notes || []).slice(0, 8);
  const modal = openModal(t("inicio.atualizacao_titulo"), `
    <p style="margin-top:0">${esc(t("inicio.atualizacao_texto", { versao: v, atual: st.version }))}</p>
    ${notas.length ? `<b class="small">${esc(t("inicio.atualizacao_novidades"))}</b>
      <ul class="upd-notes">${notas.map((n) => `<li>${esc(n)}</li>`).join("")}</ul>` : ""}
    <div data-job style="margin-top:12px"></div>
    <div class="row wrap" style="gap:8px;justify-content:flex-end;margin-top:14px" data-botoes>
      <button class="btn ghost sm" data-pular>${esc(t("inicio.atualizacao_pular"))}</button>
      <button class="btn outline sm" data-depois>${esc(t("inicio.atualizacao_depois"))}</button>
      <button class="btn sm" data-atualizar data-nav-default>${icon("system_update")} ${esc(t("atualizacoes.atualizar"))}</button>
    </div>`);
  const q = (s) => modal.querySelector(s);
  q("[data-depois]").onclick = modal.close;
  q("[data-pular]").onclick = () => {
    store("karaoke.updateSkip", v);
    modal.close();
  };
  q("[data-atualizar]").onclick = async (e) => {
    e.currentTarget.disabled = true;
    try {
      await api("/api/app/install", { method: "POST", body: { version: v } });
      acompanhar();
    } catch (err) {
      e.currentTarget.disabled = false;
      toast(err.message, { error: true });
    }
  };
  // prepara a versao nova (minutos, com o app funcionando) e depois oferece reiniciar
  async function acompanhar() {
    if (!document.contains(modal)) return;
    const job = (await api("/api/app").catch(() => ({}))).job;
    const box = q("[data-job]");
    q("[data-botoes]").style.display = "none";
    if (!job || job.state === "running") {
      box.innerHTML = `<div class="upd-job"><span class="spinner"></span> ${esc(t("atualizacoes.preparando", { versao: v }))}
        ${esc(t("atualizacoes.continuar_usando"))}<pre class="upd-log">${esc(((job && job.log) || []).slice(-6).join("\n"))}</pre></div>`;
      setTimeout(acompanhar, 1500);
    } else if (job.state === "ready") {
      box.innerHTML = `<div class="upd-job ok">${esc(t("atualizacoes.pronta", { versao: v }))}
        <button class="btn sm" data-restart data-nav-default>${icon("restart_alt")} ${esc(t("atualizacoes.reiniciar"))}</button>
        <div class="small muted">${esc(t("atualizacoes.reiniciar_dica"))}</div></div>`;
      box.querySelector("[data-restart]").onclick = reiniciar;
    } else {
      box.innerHTML = `<div class="upd-job err">${esc(t("atualizacoes.falhou", { versao: v, erro: job.error || "" }))}</div>`;
    }
  }
}

async function reiniciar() {
  try {
    await api("/api/app/restart", { method: "POST", body: {} });
  } catch (err) {
    if (!(err.data && err.data.busy) || !(await confirmar(t("config.reiniciar_cantando"), { sim: t("config.reiniciar_mesmo"), perigo: true }))) {
      return toast(err.message, { error: true });
    }
    await api("/api/app/restart", { method: "POST", body: { force: true } });
  }
  toast(t("programa.reiniciando"), { ms: 10000 });
}
