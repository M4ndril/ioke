// Pagina "Cantar": biblioteca com destaque, filtros e prateleiras.
import {
  $, $$, aosPoucos, api, avatar, biblioteca, chooseCover, chooseLyrics, dobrar, editSong, esc, fmtTime, h, icon, keyLabel,
  stopPreview, store, toast, togglePreview,
} from "./common.js";
import { mountFabs } from "./floating.js";
import { IS_TV } from "./tvnav.js";
import "./stageopen.js";
import { queueDrawer } from "./queuedrawer.js";
import { addToQueue, showNotices } from "./partyui.js";
import { bindNav, signature, timeAgo } from "./ui.js";
import { idioma, initI18n, t } from "./i18n.js";

await initI18n(); // os textos antes de desenhar a pagina

bindNav();
mountFabs({ qr: true, piano: true, midi: true, settings: true });

const SORTS = {
  added: { asc: t("sing.antigas"), desc: t("sing.novas"), def: "desc" },
  played: { asc: t("sing.cantadas_antes"), desc: t("sing.cantadas_ultimo"), def: "desc" },
  alpha: { asc: "A → Z", desc: "Z → A", def: "asc" },
};
const GROUPS = {
  genre: { label: t("sing.sem_estilo"), key: (s) => s.genre },
  artist: { label: t("sing.artista_desconhecido"), key: (s) => s.artist },
  album: { label: t("sing.sem_album"), key: (s) => (s.album ? `${s.album}${s.artist ? " · " + s.artist : ""}` : "") },
};

let view = { sort: "added", dir: "desc", group: "none", ...(store("karaoke.view") || {}) };
let songs = [];
let libSig = "";
let busca = new Map(); // id -> texto da busca (sem acentos), feito uma vez por versao da lista
let aberto = null; // o que esta sendo criado aos poucos (grade ou prateleiras)
const LOTE = 60; // cards por vez na grade
const LOTE_PRATELEIRA = 24;
const LOTE_PRATELEIRAS = 8;

const nameOf = (s) => (s.track || s.title || "").trim();
const coverOf = (s) => s.cover || s.thumb;

// ------------------------------------------------------------------ toolbar
function updateToolbar() {
  $$("[data-sort]").forEach((b) => b.classList.toggle("on", b.dataset.sort === view.sort));
  $$("[data-group]").forEach((b) => b.classList.toggle("on", b.dataset.group === view.group));
  $("#dirLabel").textContent = SORTS[view.sort][view.dir];
}

function setView(patch) {
  view = { ...view, ...patch };
  store("karaoke.view", view);
  render(true);
}

$$("[data-sort]").forEach((b) => (b.onclick = () => {
  const sort = b.dataset.sort;
  setView({ sort, dir: sort === view.sort ? view.dir : SORTS[sort].def });
}));
$$("[data-group]").forEach((b) => (b.onclick = () => setView({ group: b.dataset.group })));
$("#dirBtn").onclick = () => setView({ dir: view.dir === "asc" ? "desc" : "asc" });
let filtroTimer = null; // digitando: filtra quando para (milhares de musicas)
$("#filter").addEventListener("input", () => {
  clearTimeout(filtroTimer);
  filtroTimer = setTimeout(() => render(), songs.length > 2000 ? 180 : 60);
});

// ------------------------------------------------------------ ordenacao
function sortSongs(list) {
  const dir = view.dir === "asc" ? 1 : -1;
  if (view.sort === "played") {
    // musicas nunca cantadas ficam sempre no fim
    const sung = list.filter((s) => s.last_played_at).sort((a, b) => (a.last_played_at - b.last_played_at) * dir);
    const never = list.filter((s) => !s.last_played_at).sort((a, b) => (b.ready_at || 0) - (a.ready_at || 0));
    return [...sung, ...never];
  }
  if (view.sort === "alpha") {
    return [...list].sort((a, b) => nameOf(a).localeCompare(nameOf(b), idioma(), { sensitivity: "base", numeric: true }) * dir);
  }
  return [...list].sort((a, b) => ((a.ready_at || 0) - (b.ready_at || 0)) * dir);
}

function indexar(list) {
  busca = new Map(list.map((s) => [s.id, dobrar([s.title, s.track, s.artist, s.album, s.genre, s.added_by, s.year].join(" "))]));
}

/** As musicas com todas as palavras da busca (sem acentos, em qualquer campo). */
function filtrar(list, q) {
  const words = dobrar(q).split(/\s+/).filter(Boolean);
  if (!words.length) return list;
  return list.filter((s) => {
    const hay = busca.get(s.id) || "";
    return words.every((w) => hay.includes(w));
  });
}

function metaLine(s) {
  if (view.sort === "played") {
    return s.last_played_at ? esc(t("sing.cantada_vezes", { n: s.play_count, quando: timeAgo(s.last_played_at) })) : esc(t("sing.nao_cantada"));
  }
  if (view.sort === "added") {
    return esc(s.added_by ? t("sing.adicionada_por", { quando: timeAgo(s.ready_at), nome: s.added_by }) : t("sing.adicionada", { quando: timeAgo(s.ready_at) }));
  }
  return [s.genre, s.year, fmtTime(s.duration)].filter(Boolean).map(esc).join(" · ");
}

// ------------------------------------------------------------------ cards
function cardEl(s) {
  const el = h(`
    <article class="scard" tabindex="0" aria-label="${esc(nameOf(s))}">
      <div class="art">
        <img src="${esc(s.art_sm || coverOf(s))}" alt="" loading="lazy">
        ${!s.lyrics ? `<div class="art-badges"><span class="badge warn">${esc(t("sing.sem_letra"))}</span></div>` : ""}
        <div class="art-hover">
          <button class="mini-btn corner left" data-queue title="${esc(t("fila.entrar_titulo"))}">${icon("playlist_add")}</button>
          <button class="mini-btn corner right danger" data-del title="${esc(t("sing.excluir"))}">${icon("delete")}</button>
          ${palcoAberto // palco aberto em outra janela: aqui a musica vai para a fila
            ? `<button class="play-circle" data-play title="${esc(t("fila.entrar_titulo"))}">${icon("playlist_add", "xl")}</button>`
            : `<button class="play-circle" data-play title="${esc(t("sing.cantar"))}">${icon("play_arrow", "fill xl")}</button>`}
          <div class="art-actions">
            ${palcoAberto ? "" : `<button class="mini-btn" data-prev title="${esc(t("sing.ouvir_trecho"))}">${icon("headphones")}</button>`}
            <button class="mini-btn" data-lyr title="${esc(t("player.trocar_letra"))}">${icon("lyrics")}</button>
            <button class="mini-btn" data-art title="${esc(t("player.trocar_capa"))}">${icon("image")}</button>
            <button class="mini-btn" data-edit title="${esc(t("sing.editar"))}">${icon("edit")}</button>
          </div>
        </div>
      </div>
      <div class="scard-info">
        <div class="t" title="${esc(s.title)}">${esc(nameOf(s))}</div>
        <div class="a">${esc(s.artist || s.channel || "")}</div>
        <div class="m">${metaLine(s)}</div>
      </div>
    </article>`);
  const open = () => (palcoAberto ? addToQueue(s, { onDone: refreshParty }) : (location.href = `/player?id=${s.id}`));
  el.addEventListener("click", (e) => !e.target.closest("[data-queue],[data-prev],[data-lyr],[data-art],[data-edit],[data-del]") && open());
  el.querySelector("[data-queue]").onclick = () => addToQueue(s, { onDone: refreshParty });
  el.addEventListener("keydown", (e) => e.key === "Enter" && e.target === el && open());
  const prev = el.querySelector("[data-prev]");
  if (prev) prev.onclick = (e) =>
    togglePreview(e.currentTarget, `/api/songs/${s.id}/audio/instrumental`, { start: 0.4, relative: true, seconds: 12 });
  el.querySelector("[data-lyr]").onclick = async () => (await chooseLyrics(s)) && refresh();
  el.querySelector("[data-art]").onclick = async () => (await chooseCover(s)) && refresh();
  el.querySelector("[data-edit]").onclick = async () => {
    const genres = [...new Set(songs.map((x) => x.genre).filter(Boolean))].sort();
    let full = s; // a lista so tem o que o card mostra: o Editar precisa do resto
    try {
      full = await api(`/api/songs/${s.id}`);
    } catch (err) {
      return toast(err.message, { error: true });
    }
    if (await editSong(full, { genres })) refresh();
  };
  el.querySelector("[data-del]").onclick = async () => {
    if (!confirm(t("sing.excluir_confirmar", { nome: nameOf(s) }))) return;
    try {
      await api(`/api/songs/${s.id}`, { method: "DELETE" });
      toast(t("sing.excluida"));
      refresh();
    } catch (err) {
      toast(err.message, { error: true });
    }
  };
  return el;
}

function shelfEl(title, items) {
  const el = h(`
    <section class="shelf">
      <div class="shelf-head"><h2>${esc(title)}</h2><span class="count">${items.length}</span></div>
      <div class="shelf-row">
        <button class="shelf-arrow left" aria-label="${esc(t("sing.voltar"))}">‹</button>
        <div class="shelf-track"></div>
        <button class="shelf-arrow right" aria-label="${esc(t("sing.avancar"))}">›</button>
      </div>
    </section>`);
  const track = el.querySelector(".shelf-track");
  aosPoucos(track, items, cardEl, { lote: LOTE_PRATELEIRA, horizontal: true });
  const scroll = (dir) => track.scrollBy({ left: dir * track.clientWidth * 0.85, behavior: "smooth" });
  el.querySelector(".left").onclick = () => scroll(-1);
  el.querySelector(".right").onclick = () => scroll(1);
  const arrows = () => {
    el.querySelector(".left").classList.toggle("hidden", track.scrollLeft < 8);
    el.querySelector(".right").classList.toggle("hidden", track.scrollLeft + track.clientWidth >= track.scrollWidth - 8);
  };
  track.addEventListener("scroll", arrows, { passive: true });
  requestAnimationFrame(arrows);
  return el;
}

/** Desenha a biblioteca. So refaz se a lista, a busca ou a visao mudaram; a grade e as prateleiras vem
 *  aos poucos com a rolagem (so os cards perto da tela existem). Redesenhar pela lista nova mantem
 *  quantos cards ja estavam na tela (a posicao da rolagem nao pula). */
function render(force = false, { mudou = false } = {}) {
  const q = $("#filter").value.trim();
  const sig = JSON.stringify(view) + "#" + q;
  if (sig === libSig && !force && !mudou) return;
  const mesmaVisao = sig === libSig;
  const antes = mesmaVisao && aberto ? aberto.quantos() : 0;
  libSig = sig;
  const list = sortSongs(filtrar(songs, q));
  if (aberto) aberto.parar();
  aberto = null;
  stopPreview();
  updateToolbar();
  const lib = $("#library");
  lib.innerHTML = "";
  if (!songs.length) {
    lib.innerHTML = `
      <div class="empty-lib">
        <div class="big">${icon("mic", "fill")}</div>
        <h2>${esc(t("sing.vazia"))}</h2>
        <p class="muted">${esc(t("sing.vazia_texto"))}</p>
        <a class="btn lg" href="/adicionar">${icon("add")} ${esc(t("nav.adicionar"))}</a>
      </div>`;
    return;
  }
  if (!list.length) {
    lib.innerHTML = `<div class="empty">${esc(t("sing.nada_para", { q }))}</div>`;
    return;
  }
  if (view.group === "none") {
    lib.append(h(`<div class="lib-head"><h2>${esc(t(q ? "sing.resultados" : "sing.todas"))}</h2><span class="count">${list.length}</span></div>`));
    const grid = h('<div class="grid"></div>');
    lib.append(grid);
    aberto = aosPoucos(grid, list, cardEl, { lote: LOTE, minimo: antes });
    return;
  }
  const g = GROUPS[view.group];
  const groups = new Map();
  for (const s of list) {
    const k = (g.key(s) || "").trim() || g.label;
    if (!groups.has(k)) groups.set(k, []);
    groups.get(k).push(s);
  }
  const keys = [...groups.keys()].sort(
    (a, b) => (a === g.label) - (b === g.label) || a.localeCompare(b, idioma(), { sensitivity: "base" }),
  );
  aberto = aosPoucos(lib, keys, (k) => shelfEl(k, groups.get(k)), { lote: LOTE_PRATELEIRAS, minimo: antes });
}

// ------------------------------------------------------------------ destaque
let heroList = [];
let heroIndex = 0;
let heroTimer = null;
let heroHover = false;
const heroVideo = $("#heroVideo");
let ultimasRecentes = [];

// O palco aberto em outra janela (a TV): o destaque com os videos sai (os videos daqui pesavam no palco) e
// nada toca nesta janela: escolher uma musica coloca ela na fila. Fechou o palco, volta tudo.
let palcoAberto = false;

function pararHero() {
  clearTimeout(heroTimer);
  heroVideo.pause();
  heroVideo.removeAttribute("src");
  heroVideo.load();
  $("#hero").classList.remove("has-video");
}

/** Muda o estado; true se mudou (os cards precisam ser feitos de novo). */
function aplicarPalco(aberto, redesenhar = true) {
  if (aberto === palcoAberto) return false;
  palcoAberto = aberto;
  stopPreview();
  $("#hero").classList.toggle("hidden", aberto);
  $("#palcoAviso").classList.toggle("hidden", !aberto);
  if (aberto) pararHero();
  else {
    heroList = [];
    setupHero(ultimasRecentes);
  }
  if (redesenhar) render(true);
  return true;
}

function heroMeta(s) {
  const bits = [s.album, s.year, s.genre, fmtTime(s.duration)].filter(Boolean).map(esc);
  const badges = [
    s.key ? `<span class="badge key">${esc(keyLabel(s.key))}</span>` : "",
    s.resplit && (s.resplit.state === "queued" || s.resplit.state === "running")
      ? `<span class="badge gray">${icon("record_voice_over", "sm")} ${esc(t("sing.refazendo_apoio"))} ${Math.round((s.resplit.progress || 0) * 100)}%</span>` : "",
    s.resplit && s.resplit.state === "error" ? `<span class="badge warn">${esc(t("sing.refazer_falhou"))}</span>` : "",
    s.lyrics_ai && (s.lyrics_ai.state === "queued" || s.lyrics_ai.state === "running")
      ? `<span class="badge gray">${icon("auto_awesome", "sm")} ${esc(t("sing.ia_sincronizando"))}</span>`
      : s.lyrics ? (s.lyrics.source === "ia" ? `<span class="badge ok">${icon("auto_awesome", "sm")} ${esc(t("sing.letra_ia"))}</span>`
        : s.lyrics.words ? `<span class="badge ok">${esc(t("sing.letra_palavra"))}</span>` : s.lyrics.synced ? `<span class="badge ok">${esc(t("sing.letra_sincronizada"))}</span>`
          : `<span class="badge warn">${esc(t("sing.letra_sem_tempo"))}</span>`) : `<span class="badge warn">${esc(t("sing.sem_letra"))}</span>`,
  ].join("");
  return `<span>${bits.join('<i class="sep">•</i>')}</span>${badges}`;
}

function showHero(i) {
  if (!heroList.length || palcoAberto) return;
  heroIndex = (i + heroList.length) % heroList.length;
  const s = heroList[heroIndex];
  stopPreview();
  const content = $("#heroContent");
  content.classList.add("swap");
  $("#hero").classList.remove("has-video");
  heroVideo.pause();
  setTimeout(() => {
    $("#heroEyebrow").textContent = t(heroIndex === 0 ? "sing.por_ultimo" : "sing.recente");
    $("#heroTitle").textContent = nameOf(s);
    $("#heroArtist").textContent = s.artist || "";
    $("#heroMeta").innerHTML = heroMeta(s);
    $("#heroPlay").href = `/player?id=${s.id}`;
    $("#heroBg").style.backgroundImage = `url("${coverOf(s)}")`;
    $("#heroArt").src = coverOf(s);
    $$("#heroDots button").forEach((d, n) => d.classList.toggle("on", n === heroIndex));
    content.classList.remove("swap");
    // Como na Netflix: se tiver o clipe, ele roda mudo no fundo
    if (s.video && s.video.status === "ready" && !palcoAberto) {
      heroVideo.preload = "auto";
      heroVideo.src = s.video.url;
      heroVideo.load();
      heroVideo.onloadedmetadata = () => {
        heroVideo.currentTime = Math.min(heroVideo.duration * 0.3, Math.max(0, heroVideo.duration - 20));
        heroVideo.play().catch(() => {});
      };
      heroVideo.onplaying = () => heroList[heroIndex] === s && $("#hero").classList.add("has-video");
    } else {
      heroVideo.removeAttribute("src");
      heroVideo.load();
    }
  }, 260);
  clearTimeout(heroTimer);
  heroTimer = setTimeout(function next() {
    if (heroHover) heroTimer = setTimeout(next, 3000);
    else showHero(heroIndex + 1);
  }, 12000);
}

function setupHero(recent) {
  ultimasRecentes = recent;
  if (palcoAberto) return;
  const same = signature(recent, ["id", "cover", "video", "title", "key", "lyrics"]) === signature(heroList, ["id", "cover", "video", "title", "key", "lyrics"]);
  if (same) return;
  const current = heroList[heroIndex] && heroList[heroIndex].id;
  heroList = recent;
  const hero = $("#hero");
  hero.classList.toggle("empty-hero", !heroList.length);
  if (!heroList.length) {
    $("#heroTitle").textContent = t("sing.nada_ainda");
    $("#heroArtist").textContent = "";
    $("#heroMeta").innerHTML = "";
    $("#heroEyebrow").textContent = t("sing.bem_vindo");
    $("#heroPlay").href = "/adicionar";
    $("#heroPlay").innerHTML = `${icon("add")} ${esc(t("nav.adicionar"))}`;
    return;
  }
  $("#heroPlay").innerHTML = `${icon("play_arrow", "fill")} ${esc(t("sing.cantar"))}`;
  const dots = $("#heroDots");
  dots.innerHTML = heroList.length > 1 ? heroList.map((_, n) => `<button aria-label="${esc(t("sing.destaque", { n: n + 1 }))}"></button>`).join("") : "";
  $$("#heroDots button").forEach((d, n) => (d.onclick = () => showHero(n)));
  const idx = heroList.findIndex((s) => s.id === current);
  showHero(idx >= 0 ? idx : 0);
}

$("#hero").addEventListener("mouseenter", () => (heroHover = true));
$("#hero").addEventListener("mouseleave", () => (heroHover = false));
$("#heroPreview").onclick = (e) => {
  const s = heroList[heroIndex];
  if (s) togglePreview(e.currentTarget, `/api/songs/${s.id}/audio/instrumental`, { start: 0.4, relative: true, seconds: 15 });
};

// ------------------------------------------------------- fila de cantores
let partySig = "";
let drawer = null;
function openQueue() {
  if (!drawer) drawer = queueDrawer({ autoRefresh: true, onChange: () => drawer.refresh().then(refreshParty) });
  drawer.open();
}

function renderPartyStrip(p) {
  const cur = p.current;
  const queue = p.queue || [];
  const sig = JSON.stringify([cur && cur.id, cur && cur.playback && cur.playback.state, queue.map((e) => [e.id, e.ready]), !!p.tv_stage]);
  if (sig === partySig) return;
  partySig = sig;
  const strip = $("#partyStrip");
  if (!cur && !queue.length) {
    strip.classList.add("hidden");
    return;
  }
  const chip = (e, label) => `
    <div class="ps-chip">
      <img src="${esc((e.song && (e.song.art_sm || e.song.cover || e.song.thumb)) || "")}" alt="">
      <div><span class="ps-label">${label}</span><b>${e.person && e.person.id ? avatar(e.person, "sm") : ""}${esc(e.singer)}</b><span class="small muted">${esc((e.song && (e.song.track || e.song.title)) || "")}</span></div>
    </div>`;
  strip.innerHTML = `
    <div class="ps-title">${icon("queue_music")} ${esc(t("player.fila_cantores"))}</div>
    <div class="ps-row">
      ${cur ? chip(cur, esc(t(cur.playback && cur.playback.state === "playing" ? "sing.cantando_agora" : "sing.no_palco"))) : ""}
      ${queue.slice(0, 4).map((e, i) => chip(e, i === 0 ? esc(t("player.a_seguir")) : esc(t("sing.posicao", { n: i + 1 })))).join("")}
      ${queue.length > 4 ? `<span class="small muted">+${queue.length - 4}</span>` : ""}
    </div>
    <div class="ps-actions">
      <button class="btn outline sm" data-ps="queue">${icon("format_list_bulleted")} ${esc(t("sing.ver_fila"))}</button>
      ${p.tv_stage && !IS_TV // na propria janela do palco, o botao so volta para o palco
        ? `<button class="btn ghost sm" data-ps="tv">${icon("cast_connected")} ${esc(t("sing.palco_na_tv"))}</button>`
        : `<a class="btn light sm" href="/palco" data-open-stage>${icon("tv")} ${esc(t("nav.palco"))}</a>`}
    </div>`;
  $('[data-ps="queue"]', strip).onclick = openQueue;
  const tv = $('[data-ps="tv"]', strip);
  if (tv) tv.onclick = () => toast(t("sing.palco_na_tv_aviso"), { ms: 5000 });
  strip.classList.remove("hidden");
}

async function refreshParty() {
  try {
    const p = await api("/api/party");
    aplicarPalco(!IS_TV && !!p.tv_stage);
    showNotices(p);
    renderPartyStrip(p);
  } catch {
    /* sem servidor */
  }
}

// ------------------------------------------------------------------ dados
let timer = null;
async function refresh() {
  clearTimeout(timer);
  try {
    // as 5 mais novas vem completas (o destaque); a lista toda so quando muda
    const [state, bib, p] = await Promise.all([api("/api/state?musicas=0&recentes=5"), biblioteca(),
      api("/api/party").catch(() => null)]);
    if (bib.mudou) {
      songs = bib.songs;
      indexar(songs);
    }
    // antes do destaque: com o palco aberto, o video nem comeca
    const mudouPalco = p ? aplicarPalco(!IS_TV && !!p.tv_stage, false) : false;
    setupHero(state.recentes || []);
    render(mudouPalco, { mudou: bib.mudou });
    if (p) {
      showNotices(p);
      renderPartyStrip(p);
    }
  } catch {
    /* servidor reiniciando */
  }
  timer = setTimeout(refresh, 5000);
}
refresh();
