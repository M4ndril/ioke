// Gaveta lateral com a fila de cantores (PC): usada no palco e na biblioteca.
// Mostra quem esta no palco, a fila (reordenar, subir ao palco, tirar), o
// rodizio, o ranking da festa, quem ja cantou e o botao "Nova festa".
import { $, api, avatar, esc, h, icon, toast } from "./common.js";
import { pickSongForQueue, rankingRows, renderQueue } from "./partyui.js";
import { t } from "./i18n.js";

const HTML = () => `
  <aside class="drawer" id="queueDrawer" aria-hidden="true">
    <div class="drawer-head">
      <h3>${icon("queue_music")} ${esc(t("player.fila_cantores"))}</h3>
      <button class="icon-btn plain" data-qd="close" title="${esc(t("comum.fechar"))}">${icon("close")}</button>
    </div>
    <div class="drawer-now" data-qd="now"></div>
    <div class="drawer-tools">
      <button class="btn sm" data-qd="add">${icon("playlist_add")} ${esc(t("fila.adicionar"))}</button>
      <label class="toggle-row small"><input type="checkbox" data-qd="rotation"> ${esc(t("fila.rodizio"))}</label>
      <span class="drawer-tools-end">
        <button class="btn ghost xs" data-qd="clear" title="${esc(t("fila.limpar_explica"))}">${esc(t("fila.limpar"))}</button>
        <button class="btn ghost xs" data-qd="new" title="${esc(t("festa.nova_explica"))}">${icon("celebration", "sm")} ${esc(t("festa.nova"))}</button>
      </span>
    </div>
    <div class="drawer-list" data-qd="list"></div>
    <div class="drawer-history" data-qd="history"></div>
  </aside>`;

/**
 * Cria (uma vez) a gaveta. `onChange` e chamado depois de mexer na fila (quem ja
 * busca a fila sozinho, como o palco, passa a propria funcao). Com `autoRefresh`,
 * a gaveta busca a fila a cada 2 s enquanto esta aberta.
 */
export function queueDrawer({ onChange, onOpen, autoRefresh = false, parent = document.body } = {}) {
  const el = $("#queueDrawer") || h(HTML());
  if (!el.isConnected) parent.append(el);
  const q = (name) => $(`[data-qd="${name}"]`, el);
  let isOpen = false;
  let timer = null;

  async function refresh() {
    try {
      render(await api("/api/party"));
    } catch {
      /* servidor reiniciando */
    }
  }
  const changed = () => (onChange ? onChange() : refresh());

  function render(p) {
    const cur = p.current;
    const pb = (cur && cur.playback) || {};
    q("now").innerHTML = cur
      ? `<div class="now-singing">${cur.person && cur.person.id ? avatar(cur.person) : icon("mic", "fill")}<div class="grow"><b>${esc(cur.singer)}</b>
         <div class="small muted">${esc(cur.song.track || cur.song.title)} · ${esc(t(pb.state === "playing" ? "fila.cantando" : pb.state === "paused" ? "fila.pausado" : "fila.esperando_play"))}</div></div></div>`
      : `<div class="small muted">${esc(t("fila.ninguem_palco"))}</div>`;
    renderQueue(q("list"), p, { host: true, onChange: changed });
    q("rotation").checked = !!p.rotation;
    const ranking = (p.ranking || []).length
      ? `<div class="drawer-title">${icon("trophy", "sm")} ${esc(t("festa.ranking"))}</div>${rankingRows(p.ranking)}`
      : "";
    q("history").innerHTML = ranking + ((p.history || []).length
      ? `<div class="drawer-title">${esc(t("fila.ja_cantaram"))}</div>${p.history.map((x) =>
        `<div class="small muted hist">${esc(x.singer)} · ${esc(x.title || "")}${x.score != null ? ` · <b>${esc(t("fila.pontos", { n: x.score }))}</b>` : ""}${x.state === "skipped" ? ` ${esc(t("fila.pulou"))}` : ""}</div>`).join("")}`
      : "");
    const count = $("#queueCount");
    if (count) count.textContent = (p.queue || []).length ? String(p.queue.length) : "";
  }

  function set(on) {
    isOpen = on;
    el.classList.toggle("open", on);
    el.setAttribute("aria-hidden", String(!on));
    clearInterval(timer);
    if (on && autoRefresh) {
      refresh();
      timer = setInterval(refresh, 2000);
    }
    if (on && onOpen) onOpen();
  }

  q("close").onclick = () => set(false);
  el.addEventListener("click", (e) => e.stopPropagation());
  q("add").onclick = () => pickSongForQueue({ onDone: changed });
  q("rotation").onchange = async (e) => {
    await api("/api/party/rotation", { method: "POST", body: { on: e.target.checked } }).catch((err) => toast(err.message, { error: true }));
    changed();
  };
  q("clear").onclick = async () => {
    if (!confirm(t("fila.limpar_confirmar"))) return;
    await api("/api/party/clear", { method: "POST" }).catch((err) => toast(err.message, { error: true }));
    changed();
  };
  q("new").onclick = async () => {
    if (!confirm(t("festa.nova_confirmar"))) return;
    await api("/api/party/new", { method: "POST" }).catch((err) => toast(err.message, { error: true }));
    changed();
  };
  document.addEventListener("keydown", (e) => {
    if (e.key === "Escape" && isOpen && !document.querySelector(".modal-backdrop")) set(false);
  });

  return {
    render,
    refresh,
    open: () => set(true),
    close: () => set(false),
    toggle: () => set(!isOpen),
    get isOpen() {
      return isOpen;
    },
  };
}
