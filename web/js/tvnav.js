// Controle remoto nas paginas do PC: recebe os comandos do celular
// administrador (setas, OK, voltar, pesquisa...) e navega pela pagina como um
// app de TV, com um destaque no item selecionado.
//
// Paginas podem tratar um comando antes (ex.: o player usa play/pausa e
// volume): escutam "karaoke:remote" no document e chamam preventDefault().
import { $, $$, api, esc, openModal } from "./common.js";
import { t } from "./i18n.js";
import "./appwin.js"; // F11 na janela do app instalado

const PAGE = Math.random().toString(36).slice(2, 12);
const TV = (() => {
  // a janela do "Palco na TV" abre com ?tv=1 e continua sendo a TV ao navegar
  try {
    if (new URLSearchParams(location.search).get("tv") === "1") sessionStorage.setItem("karaoke.tv", "1");
    return sessionStorage.getItem("karaoke.tv") === "1";
  } catch {
    return false;
  }
})();

/** Esta pagina esta na janela do "Palco na TV"? */
export const IS_TV = TV;

const SELECTOR = 'a[href], button, input, select, textarea, [tabindex]:not([tabindex="-1"]), [data-nav]';
// botoes que so aparecem com o mouse em cima do card: o card inteiro e um item so
const SKIP = ".scard button, .shelf-arrow, [data-nav-skip]";

const HIDDEN = [
  ".hidden", "[hidden]", "[aria-hidden='true']",
  ".drawer:not(.open)", // gavetas fechadas (ficam fora da tela)
  ".menu-wrap:not(.open) > .menu", // menus fechados
  ".player:not(.ui-on) .ui", // controles do player escondidos
].join(", ");

let current = null;
let editing = null; // barra/controle deslizante "pego" com OK: as setas mudam o valor
let memX = null; // coluna em que estava (subir/descer mantem a coluna, como na TV)
let returnTo = []; // quem abriu o menu/modal/gaveta: o "voltar" devolve o foco para ele

// ------------------------------------------------------------ o que da para focar
function shown(el) {
  // escondido "de proposito" (por classe) - nao pela opacidade, que pode estar no meio de uma animacao
  if (el.disabled || el.closest(HIDDEN)) return false;
  const r = el.getBoundingClientRect();
  if (r.width < 2 || r.height < 2) return false;
  if (el.checkVisibility) {
    return el.checkVisibility({ checkVisibilityCSS: true, visibilityProperty: true });
  }
  const cs = getComputedStyle(el);
  return cs.visibility !== "hidden" && cs.display !== "none";
}

/** Onde o foco pode andar agora: o modal aberto, a gaveta aberta... ou a pagina. */
function scope() {
  const modals = $$(".modal-backdrop");
  if (modals.length) return modals[modals.length - 1];
  return $("#lyricsEditor.open") || $("#queueDrawer.open") || $(".menu-wrap.open .menu") || document.body;
}

function candidates() {
  return $$(SELECTOR, scope()).filter((el) => !el.matches(SKIP) && shown(el));
}

// ------------------------------------------------------------------ destaque
/** Traz o item para a tela rolando so o que rola de verdade (listas, prateleiras,
 *  a pagina). Nunca mexe em containers com overflow hidden (o player nao rola). */
function ensureVisible(el) {
  for (let box = el.parentElement; box && box !== document.body; box = box.parentElement) {
    const cs = getComputedStyle(box);
    const sx = /(auto|scroll)/.test(cs.overflowX) && box.scrollWidth > box.clientWidth;
    const sy = /(auto|scroll)/.test(cs.overflowY) && box.scrollHeight > box.clientHeight;
    if (!sx && !sy) continue;
    const r = el.getBoundingClientRect();
    const b = box.getBoundingClientRect();
    const pad = 24;
    let dx = 0;
    let dy = 0;
    if (sx) dx = r.left < b.left + pad ? r.left - b.left - pad : r.right > b.right - pad ? r.right - b.right + pad : 0;
    if (sy) dy = r.top < b.top + pad ? r.top - b.top - pad : r.bottom > b.bottom - pad ? r.bottom - b.bottom + pad : 0;
    if (dx || dy) box.scrollBy({ left: dx, top: dy, behavior: "smooth" });
  }
  if (document.body.classList.contains("player-body")) return; // o player ocupa a tela, nao rola
  const r = el.getBoundingClientRect();
  const top = (($(".nav") || {}).offsetHeight || 0) + (($("#toolbar") || {}).offsetHeight || 0) + 16;
  if (r.top < top) window.scrollBy({ top: r.top - top - innerHeight * 0.2, behavior: "smooth" });
  else if (r.bottom > innerHeight - 16) window.scrollBy({ top: r.bottom - innerHeight + innerHeight * 0.25, behavior: "smooth" });
}

// ---------------------------------------------------- rotulo do item em foco
// Pelo controle nao ha mouse para a dica aparecer: o botao so com icone em foco
// mostra o nome embaixo (ou em cima, perto da borda de baixo da tela).
let label = null;
let labelTimer = null;

/** O nome de um item so com icone ("Fila de cantores"); "" se ele ja mostra texto. */
function nameOf(el) {
  let text = el.innerText || "";
  for (const i of el.querySelectorAll(".ms")) text = text.replace(i.innerText, "");
  if (text.trim().length > 1) return ""; // ja tem texto (um numero sozinho, como a contagem da fila, nao conta)
  const name = el.getAttribute("aria-label") || el.title || "";
  return name.replace(/\s*\([^)]*\)\s*$/, ""); // sem o atalho do teclado: "Tela cheia (F)" -> "Tela cheia"
}

function hideLabel() {
  clearInterval(labelTimer);
  labelTimer = null;
  if (label) label.classList.add("hidden");
}

function placeLabel() {
  if (!current || !document.contains(current) || !shown(current)) return hideLabel();
  const r = current.getBoundingClientRect();
  const below = r.bottom + 44 < innerHeight;
  label.style.top = `${below ? r.bottom + 8 : r.top - 8}px`;
  label.classList.toggle("above", !below);
  // perto das bordas o rotulo nao sai da tela
  const w = label.offsetWidth;
  const x = Math.min(innerWidth - 12 - w / 2, Math.max(12 + w / 2, r.left + r.width / 2));
  label.style.left = `${x}px`;
}

function showLabel() {
  const name = current && nameOf(current);
  if (!name) return hideLabel();
  if (!label) {
    label = document.createElement("div");
    label.className = "tv-label hidden";
    document.body.append(label);
  }
  label.textContent = name;
  label.classList.remove("hidden");
  placeLabel();
  // acompanha a rolagem suave e some junto com o item (os controles do player se escondem)
  clearInterval(labelTimer);
  labelTimer = setInterval(placeLabel, 250);
}

function setCurrent(el) {
  if (current) current.classList.remove("tv-focus", "tv-edit");
  editing = null;
  current = el || null;
  if (!current) return hideLabel();
  current.classList.add("tv-focus");
  if (current.matches("input:not([type=range]), textarea")) current.focus({ preventScroll: true });
  else if (document.activeElement && document.activeElement !== document.body && !current.contains(document.activeElement)) {
    document.activeElement.blur();
  }
  ensureVisible(current);
  showLabel();
}

function initial(items) {
  const def = $$("[data-nav-default]").find((el) => items.includes(el));
  if (def) return def;
  // o primeiro item "de conteudo" da tela (pula a barra de navegacao do topo)
  const navH = ($(".nav") || {}).offsetHeight || 0;
  const inView = items.filter((el) => {
    const r = el.getBoundingClientRect();
    return r.top >= navH && r.bottom <= innerHeight;
  });
  return inView[0] || items[0];
}

// ------------------------------------------------------------------ andar
const gap = (a0, a1, b0, b1) => (b1 < a0 ? a0 - b1 : b0 > a1 ? b0 - a1 : 0); // distancia entre intervalos
const toInterval = (x, b0, b1) => (x < b0 ? b0 - x : x > b1 ? x - b1 : 0);
/** Um item em cima do outro: a intersecao cobre boa parte (1/4) do menor. */
function overlaps(a, b) {
  const w = Math.min(a.right, b.right) - Math.max(a.left, b.left);
  const h = Math.min(a.bottom, b.bottom) - Math.max(a.top, b.top);
  return w > 0 && h > 0 && w * h > 0.25 * Math.min(a.width * a.height, b.width * b.height);
}

function pick(items, dir, strict) {
  const a = current.getBoundingClientRect();
  const ax = a.left + a.width / 2;
  const ay = a.top + a.height / 2;
  const vertical = dir === "up" || dir === "down";
  const refX = vertical && memX != null ? memX : ax;
  let best = null;
  let bestScore = Infinity;
  for (const el of items) {
    if (el === current || el.contains(current) || current.contains(el)) continue;
    const b = el.getBoundingClientRect();
    const bx = b.left + b.width / 2;
    const by = b.top + b.height / 2;
    // um por cima do outro (o botao flutuante sobre uma area grande, como as metades da tela inicial):
    // a direcao vale pelos centros e a distancia tambem
    const over = overlaps(a, b);
    // estrito: o item tem que estar TODO naquela direcao (uma barra larga que
    // comeca a esquerda nao conta como "a direita" dos botoes)
    const loose = !strict || over;
    if (dir === "right" && (loose ? bx <= ax + 1 : b.left < a.right - 8)) continue;
    if (dir === "left" && (loose ? bx >= ax - 1 : b.right > a.left + 8)) continue;
    if (dir === "down" && (loose ? by <= ay + 1 : b.top < a.bottom - 8)) continue;
    if (dir === "up" && (loose ? by >= ay - 1 : b.bottom > a.top + 8)) continue;
    // para os lados, so na mesma faixa da tela (senao o fim de uma fileira de
    // cards pulava para os botoes flutuantes do topo)
    if (!vertical && gap(a.top, a.bottom, b.top, b.bottom) > (strict ? 0 : a.height * 0.5)) continue;
    let score;
    if (vertical) {
      const main = over ? Math.abs(by - ay) * 0.5
        : dir === "down" ? Math.max(0, b.top - a.bottom) : Math.max(0, a.top - b.bottom);
      score = main + toInterval(refX, b.left, b.right) * 2 + Math.abs(bx - refX) * 0.05;
    } else {
      const main = over ? Math.abs(bx - ax) * 0.5
        : dir === "right" ? Math.max(0, b.left - a.right) : Math.max(0, a.left - b.right);
      score = main + gap(a.top, a.bottom, b.top, b.bottom) * 3 + Math.abs(by - ay) * 0.1;
    }
    if (score < bestScore) {
      bestScore = score;
      best = el;
    }
  }
  return best;
}

const OPOSTO = { up: "down", down: "up", left: "right", right: "left" };
let lastMove = null; // {from, to, dir}: voltar pela seta contraria volta para onde estava

function move(dir) {
  const items = candidates();
  if (!items.length) return;
  if (!current || !items.includes(current)) return setCurrent(initial(items));
  const back = lastMove && lastMove.to === current && lastMove.dir === OPOSTO[dir] && items.includes(lastMove.from)
    ? lastMove.from : null;
  const best = back || pick(items, dir, true) || pick(items, dir, false);
  if (!best) return;
  const r = best.getBoundingClientRect();
  const vertical = dir === "up" || dir === "down";
  // guarda a coluna; itens bem largos (a barra de progresso) nao mudam a coluna
  if (!vertical || r.width < innerWidth * 0.5) memX = r.left + r.width / 2;
  lastMove = { from: current, to: best, dir };
  setCurrent(best);
}

function nudge(el, delta) {
  const min = Number(el.min || 0);
  const max = Number(el.max || 100);
  const step = Number(el.dataset.navStep) || (el.id === "seek" ? 10 : (max - min) / 20);
  el.value = Math.max(min, Math.min(max, Number(el.value) + delta * step));
  el.dispatchEvent(new Event("input", { bubbles: true }));
  el.dispatchEvent(new Event("change", { bubbles: true }));
}

function setEditing(on) {
  editing = on ? current : null;
  if (current) current.classList.toggle("tv-edit", !!on);
}

function ok() {
  const items = candidates();
  if (!current || !items.includes(current)) return setCurrent(initial(items));
  if (current.matches("input[type=range]")) return setEditing(editing !== current); // pega / solta
  if (current.matches("select")) {
    current.selectedIndex = (current.selectedIndex + 1) % current.options.length;
    current.dispatchEvent(new Event("change", { bubbles: true }));
    return;
  }
  if (current.matches("input:not([type=range]):not([type=checkbox]), textarea")) return current.focus();
  // link para outra pagina com musica tocando: pergunta antes
  if (current.matches("a[href]") && isPlaying()) {
    const url = new URL(current.href, location.href);
    if (url.origin === location.origin && url.pathname !== location.pathname) return leave(url.pathname + url.search);
  }
  const before = scope();
  const opener = current;
  current.click();
  // abriu um menu/modal/gaveta? lembra quem abriu
  setTimeout(() => {
    if (scope() !== before) returnTo.push(opener);
  }, 60);
}

/** Depois de fechar algo, o foco volta para quem abriu (se ainda estiver na tela). */
function restoreFocus() {
  setTimeout(() => {
    const items = candidates();
    while (returnTo.length) {
      const el = returnTo.pop();
      if (document.contains(el) && items.includes(el)) return setCurrent(el);
    }
    if (current && !items.includes(current)) setCurrent(null);
  }, 80);
}

function back() {
  const modals = $$(".modal-backdrop");
  if (modals.length) {
    const close = $("[data-close]", modals[modals.length - 1]);
    if (close) close.click();
    else if (modals[modals.length - 1].close) modals[modals.length - 1].close();
    else modals[modals.length - 1].remove();
    return restoreFocus();
  }
  const esc = () => document.dispatchEvent(new KeyboardEvent("keydown", { key: "Escape", bubbles: true }));
  if ($("#lyricsEditor.open, #queueDrawer.open, .menu-wrap.open")) {
    esc();
    return restoreFocus();
  }
  if (document.activeElement && document.activeElement.matches("input, textarea")) {
    document.activeElement.blur();
    return;
  }
  const path = location.pathname;
  if (path === "/player") leave("/cantar");
  else if (path === "/cantar" || path === "/adicionar" || path === "/add" || path === "/piano") location.href = "/";
}

// ------------------------------------------------------ sair de uma musica
const isPlaying = () => document.body.dataset.playing === "1";

/** Vai para outra pagina; se alguem esta cantando, pergunta antes (na TV, com o
 *  foco em "Continuar cantando": um toque sem querer no celular nao corta ninguem). */
function leave(url) {
  if (!isPlaying()) {
    location.href = url;
    return;
  }
  if ($(".modal-backdrop .leave-ask")) return;
  const modal = openModal(t("tv.cantando"), `
    <div class="leave-ask">
      <p style="margin-top:0">${esc(t("tv.sair_para"))}</p>
      <div class="row" style="gap:10px;justify-content:flex-end">
        <button class="btn light" data-stay>${esc(t("tv.continuar"))}</button>
        <button class="btn outline" data-go>${esc(t("tv.parar_sair"))}</button>
      </div>
    </div>`);
  $("[data-stay]", modal).onclick = () => modal.close();
  $("[data-go]", modal).onclick = () => (location.href = url);
  setTimeout(() => setCurrent($("[data-stay]", modal)), 30);
}

// ------------------------------------------------------------------ pesquisa
/** Busca na biblioteca (/cantar): filtra e destaca a primeira musica encontrada. */
function searchLibrary(text) {
  const box = $("#filter");
  if (!box) return leave(`/cantar?busca=${encodeURIComponent(text || "")}`);
  box.value = text || "";
  box.dispatchEvent(new Event("input", { bubbles: true }));
  box.blur();
  focusFirstCard();
}

function focusFirstCard(tries = 30) {
  const first = candidates().find((el) => el.matches(".scard"));
  if (first) return setCurrent(first);
  if (tries > 0) setTimeout(() => focusFirstCard(tries - 1), 100); // a biblioteca ainda carregando
}

/** Buscar numa fonte de musicas (a de um complemento): na pagina Adicionar. */
function searchFonte(fonte, text) {
  const box = $("#q");
  if (!box) return leave(`/adicionar?q=${encodeURIComponent(text || "")}&fonte=${encodeURIComponent(fonte || "")}`);
  if (fonte) document.dispatchEvent(new CustomEvent("karaoke:fonte", { detail: fonte }));
  box.value = text || "";
  if (box.form) box.form.requestSubmit();
}

// ------------------------------------------------------------------ comandos
function handle({ cmd, value }) {
  const ev = new CustomEvent("karaoke:remote", { detail: { cmd, value }, cancelable: true });
  document.dispatchEvent(ev);
  if (ev.defaultPrevented) return;
  document.dispatchEvent(new Event("mousemove")); // o player mostra os controles
  if (cmd === "up" || cmd === "down" || cmd === "left" || cmd === "right") {
    if (editing && editing === current && document.contains(editing)) {
      // barra "pega": esquerda/direita mudam o valor; cima/baixo soltam e andam
      if (cmd === "left" || cmd === "right") return nudge(editing, cmd === "left" ? -1 : 1);
      setEditing(false);
    }
    move(cmd);
  } else if (cmd === "ok") ok();
  else if (cmd === "back") {
    if (editing) return setEditing(false);
    back();
  }
  else if (cmd === "home") leave("/");
  else if (cmd === "submit" || cmd === "search") searchLibrary(value);
  else if (cmd === "buscar") searchFonte(value && value.fonte, value && value.texto);
}

// o mouse volta a mandar: some o destaque
document.addEventListener("mousedown", () => setCurrent(null), true);

// ------------------------------------------------------------------ conexao
function presence() {
  api("/api/remote/presence", {
    method: "POST",
    body: { page: PAGE, visible: document.visibilityState === "visible", focused: document.hasFocus(), path: location.pathname },
  }).catch(() => {});
}

async function connect() {
  try {
    const info = await api("/api/info");
    if (!info.is_host) return; // outro computador da rede: sem controle remoto
  } catch {
    setTimeout(connect, 5000);
    return;
  }
  const url = `/api/remote/events?page=${PAGE}&tv=${TV ? 1 : 0}&path=${encodeURIComponent(location.pathname)}`;
  const es = new EventSource(url);
  es.onmessage = (e) => {
    try {
      handle(JSON.parse(e.data));
    } catch {
      /* comando invalido */
    }
  };
  es.onopen = presence;
  ["focus", "blur"].forEach((ev) => window.addEventListener(ev, presence));
  document.addEventListener("visibilitychange", presence);
  // saiu da pagina: avisa na hora (senao o proximo comando iria para ela)
  window.addEventListener("pagehide", () => {
    es.close();
    navigator.sendBeacon("/api/remote/presence", new Blob([JSON.stringify({ page: PAGE, gone: true })], { type: "application/json" }));
  });
}

connect();

// pesquisa vinda do controle remoto quando a pagina abre (/cantar?busca=... ou /adicionar?q=...)
const params = new URLSearchParams(location.search);
if (params.has("busca")) {
  const q = params.get("busca");
  history.replaceState(null, "", location.pathname);
  setTimeout(() => searchLibrary(q), 200);
}
