// Fila de cantores: pedacos de interface usados no palco (/palco) e na biblioteca.
import {
  $$, api, avatar, biblioteca, esc, fmtTime, h, icon, keyLabel, openModal, readyIn, shiftText, store, toast,
  transposeKey,
} from "./common.js";
import { t } from "./i18n.js";

export function etaText(seconds) {
  if (seconds == null) return "";
  if (seconds < 60) return t("fila.a_seguir");
  return t("fila.em_min", { min: Math.round(seconds / 60) });
}

const coverOf = (s) => (s && (s.art_sm || s.cover || s.thumb)) || "";

/** Controle de tom de uma entrada da fila: [−] +2 [+] (e o tom resultante). */
export function tomStepper(e) {
  const n = e.transpose || 0;
  const key = e.song && e.song.key;
  const result = key && n ? `${keyLabel(transposeKey(key, n))}` : key ? keyLabel(key) : "";
  return `
    <div class="tom-step" data-tom-entry="${esc(e.id)}" data-tom="${n}">
      <span class="tom-label">${icon("tune")} ${esc(t("player.tom"))}${result ? ` <span class="muted">· ${esc(result)}</span>` : ""}</span>
      <button data-tom-d="-1" ${n <= -6 ? "disabled" : ""} aria-label="${esc(t("tom.mais_grave"))}">${icon("remove")}</button>
      <b class="${n ? "on" : ""}">${shiftText(n)}</b>
      <button data-tom-d="1" ${n >= 6 ? "disabled" : ""} aria-label="${esc(t("tom.mais_agudo"))}">${icon("add")}</button>
    </div>`;
}

/** Liga os botoes dos tomStepper() dentro de `box`. */
export function bindTomSteppers(box, onChange) {
  $$("[data-tom-entry]", box).forEach((wrap) => {
    $$("[data-tom-d]", wrap).forEach((b) => {
      b.onclick = async (ev) => {
        ev.stopPropagation();
        const value = Number(wrap.dataset.tom) + Number(b.dataset.tomD);
        wrap.dataset.tom = value;
        wrap.querySelector("b").textContent = shiftText(value); // resposta imediata
        try {
          const p = await api("/api/party/transpose", { method: "POST", body: { entry_id: wrap.dataset.tomEntry, value } });
          onChange && onChange(p);
        } catch (err) {
          toast(err.message, { error: true });
        }
      };
    });
  });
}

/** Avisos para quem pos a musica na fila (ex.: nao conseguiu baixar e saiu da fila).
 *  Cada aviso aparece uma vez por aparelho (o ultimo visto fica guardado). */
let lastNotice = null;
export function showNotices(p) {
  if (lastNotice === null) lastNotice = Number(store("karaoke.notice")) || 0;
  for (const n of (p && p.notices) || []) {
    if (n.id <= lastNotice) continue;
    lastNotice = n.id;
    store("karaoke.notice", n.id);
    if (n.kind === "download_error") {
      toast(t("fila.aviso_baixar", { titulo: n.title, nome: n.singer }),
        { error: true, ms: 9000 });
    }
  }
}

/** Ranking da festa (celular e gaveta da fila do PC): foto, nome, musica e nota. */
export function rankingRows(ranking) {
  return (ranking || []).map((r, i) =>
    `<div class="rank-row"><b class="rank-pos">${esc(t("sing.posicao", { n: i + 1 }))}</b>${avatar(r.person, "sm")}<span class="rank-text"><span class="rank-name">${esc(r.singer)}</span>${r.title ? `<span class="rank-sep">·</span><span class="rank-song">${esc(r.title)}</span>` : ""}</span><b class="rank-score">${r.score}</b></div>`).join("");
}

function entryHtml(e, { host, rotation, index, total, ownPrev, ownNext }) {
  const s = e.song || {};
  const status = e.ready ? `<span class="small muted">${esc(etaText(e.eta))}</span>`
    : `<span class="badge gray">${icon("hourglass_top", "sm")} ${esc(t("fila.preparando"))} ${Math.round((s.progress || 0) * 100)}%${s.queue ? ` · ${readyIn(s.queue.eta)}` : ""}</span>`;
  const canRemove = host || e.mine;
  return `
    <div class="q-entry${e.ready ? "" : " not-ready"}" data-entry="${e.id}">
      <span class="q-pos">${index + 1}</span>
      <img src="${esc(coverOf(s))}" alt="" loading="lazy">
      <div class="grow">
        <div class="q-singer">${avatar(e.person, "sm")}${esc(e.singer)}${e.mine ? ` <span class="badge gray">${esc(t("fila.voce"))}</span>` : ""}</div>
        <div class="q-song">${esc(s.track || s.title || "?")}${s.artist ? ` · ${esc(s.artist)}` : ""}${e.transpose ? ` <span class="badge gray">${esc(t("player.tom_badge", { tom: shiftText(e.transpose) }))}</span>` : ""}</div>
        <div>${status}</div>
      </div>
      <div class="q-actions">
        ${host && !rotation && index > 0 ? `<button class="icon-btn plain" data-q="up" title="${esc(t("fila.subir"))}">${icon("arrow_upward")}</button>` : ""}
        ${host && !rotation && index < total - 1 ? `<button class="icon-btn plain" data-q="down" title="${esc(t("fila.descer"))}">${icon("arrow_downward")}</button>` : ""}
        ${e.mine && !(host && !rotation) && ownPrev ? `<button class="icon-btn plain" data-q="own-up" title="${esc(t("fila.antes_da_sua"))}">${icon("arrow_upward")}</button>` : ""}
        ${e.mine && !(host && !rotation) && ownNext ? `<button class="icon-btn plain" data-q="own-down" title="${esc(t("fila.depois_da_sua"))}">${icon("arrow_downward")}</button>` : ""}
        ${host && e.ready ? `<button class="icon-btn plain" data-q="start" title="${esc(t("fila.palco_agora"))}">${icon("mic")}</button>` : ""}
        ${canRemove ? `<button class="icon-btn plain danger" data-q="remove" title="${esc(t("fila.tirar"))}">${icon("close")}</button>` : ""}
      </div>
    </div>`;
}

/** Desenha a fila num container. host = PC do karaoke (pode reordenar tudo). */
export function renderQueue(box, state, { host = false, onChange } = {}) {
  const queue = state.queue || [];
  if (!queue.length) {
    box.innerHTML = `<div class="empty small">${esc(t("fila.vazia"))}</div>`;
    return;
  }
  // as suas musicas: da para trocar a ordem entre elas (sem mexer no lugar dos outros)
  const mine = queue.map((e, i) => (e.mine ? i : -1)).filter((i) => i >= 0);
  box.innerHTML = queue.map((e, i) => entryHtml(e, {
    host, rotation: state.rotation, index: i, total: queue.length,
    ownPrev: e.mine && mine[0] !== i, ownNext: e.mine && mine[mine.length - 1] !== i,
  })).join("");
  $$("[data-q]", box).forEach((b) => {
    b.onclick = async (ev) => {
      ev.stopPropagation();
      const id = b.closest("[data-entry]").dataset.entry;
      const action = b.dataset.q;
      try {
        if (action === "remove") await api(`/api/party/${id}`, { method: "DELETE" });
        else if (action === "start") await api("/api/party/start", { method: "POST", body: { entry_id: id } });
        else if (action === "own-up" || action === "own-down") {
          await api("/api/party/move-own", { method: "POST", body: { entry_id: id, delta: action === "own-up" ? -1 : 1 } });
        }
        else await api("/api/party/move", { method: "POST", body: { entry_id: id, delta: action === "up" ? -1 : 1 } });
        onChange && onChange();
      } catch (err) {
        toast(err.message, { error: true });
      }
    };
  });
}

/** Pergunta o nome (lembrado neste aparelho) e coloca a musica na fila. */
const foldName = (s) => (s || "").toLowerCase().normalize("NFD").replace(/[\u0300-\u036f]/g, "").replace(/[^a-z0-9]+/g, " ").trim();

/**
 * Pelo PC: escolher quem vai cantar. Quem tem conta aparece com a foto (e controla
 * pelo celular); quem nao tem entra como convidado, so com o nome. O PC nao lembra
 * o ultimo nome (a proxima pessoa nao ve o nome da anterior).
 */
export async function addToQueue(song, { onDone } = {}) {
  let people = [];
  try {
    people = (await api("/api/accounts")).accounts || []; // so o PC / administrador ve a lista
  } catch {
    /* outro computador (sem ser o do karaoke): so o nome */
  }
  people.sort((a, b) => (b.seen_at || 0) - (a.seen_at || 0)); // quem entrou por ultimo primeiro (esta na festa)
  return new Promise((resolve) => {
    let added = false;
    const modal = openModal(t("fila.entrar_titulo"), `
      <div class="add-q">
        <img src="${esc(coverOf(song))}" alt="">
        <div class="grow">
          <div class="q-song-big">${esc(song.track || song.title)}</div>
          <div class="muted">${esc(song.artist || "")}</div>
        </div>
      </div>
      <label class="label" for="qName">${esc(t("fila.quem_canta"))}</label>
      <input class="input" id="qName" maxlength="40" autocomplete="off"
        placeholder="${esc(t(people.length ? "fila.buscar_pessoa" : "fila.nome_de_quem"))}">
      <div class="people-pick" data-people></div>
      <p class="small muted">${esc(t("fila.quem_tem_conta"))}</p>`);
    modal.addEventListener("closed", () => resolve(added));
    const input = modal.querySelector("#qName");
    const box = modal.querySelector("[data-people]");

    const go = async (body, who) => {
      try {
        const r = await api("/api/party/add", { method: "POST", body: { song_id: song.id, ...body } });
        added = true;
        const pos = (r.party.queue || []).findIndex((e) => e.id === r.entry.id);
        toast(r.party.current && r.party.current.id === r.entry.id ? t("fila.no_palco", { nome: who }) : t("fila.na_fila_posicao", { nome: who, pos: pos + 1 }));
        if (r.name_taken) toast(t("fila.nome_repetido", { nome: who }), { ms: 7000 });
        onDone && onDone(r);
        modal.close();
      } catch (err) {
        toast(err.message, { error: true });
      }
    };
    const render = () => {
      const typed = input.value.trim();
      const q = foldName(typed);
      const found = people.filter((a) => !q || foldName(a.name).includes(q));
      const exact = found.find((a) => foldName(a.name) === q);
      const shown = q ? [...(exact ? [exact] : []), ...found.filter((a) => a !== exact)] : found.slice(0, 12);
      box.innerHTML = shown.map((a) =>
        `<button class="person-chip" data-id="${esc(a.id)}">${avatar(a, "sm")}<span>${esc(a.name)}</span></button>`).join("") +
        (typed && !exact ? `<button class="person-chip guest" data-guest>${icon("person_add", "sm")}<span>${t("fila.convidado", { nome: `<b>${esc(typed)}</b>` })}</span></button>` : "") +
        (!shown.length && !typed ? `<span class="small muted">${esc(t("fila.digite_nome"))}</span>` : "");
      box.querySelectorAll("[data-id]").forEach((b) => {
        const a = people.find((x) => x.id === b.dataset.id);
        b.onclick = () => go({ account_id: a.id }, a.name);
      });
      const guest = box.querySelector("[data-guest]");
      if (guest) guest.onclick = () => go({ name: typed }, typed);
    };
    input.addEventListener("input", render);
    // Enter = a primeira opcao da lista (o nome exato vem primeiro; sem conta, o convidado)
    input.addEventListener("keydown", (e) => {
      const first = box.querySelector("button");
      if (e.key === "Enter" && input.value.trim() && first) first.click();
    });
    render();
    setTimeout(() => input.focus(), 50);
  });
}

/** Escolher uma musica da biblioteca para a fila (usado no palco). */
export async function pickSongForQueue({ onDone } = {}) {
  let songs = [];
  try {
    songs = (await biblioteca()).songs;
  } catch (err) {
    return toast(err.message, { error: true });
  }
  const modal = openModal(t("fila.adicionar_titulo"), `
    <input class="input" data-filter placeholder="${esc(t("fila.buscar_biblioteca"))}" autocomplete="off">
    <div class="pick-list" data-list></div>`);
  const list = modal.querySelector("[data-list]");
  const render = () => {
    const q = modal.querySelector("[data-filter]").value.trim().toLowerCase();
    const items = songs.filter((s) => !q || `${s.title} ${s.artist} ${s.track}`.toLowerCase().includes(q));
    list.innerHTML = items.length ? "" : `<div class="empty small">${esc(t("comum.nada"))}</div>`;
    for (const s of items.slice(0, 80)) {
      const row = h(`
        <button class="pick-row">
          <img src="${esc(coverOf(s))}" alt="" loading="lazy">
          <span class="grow"><b>${esc(s.track || s.title)}</b><span class="muted small"> · ${esc(s.artist || "")} · ${fmtTime(s.duration)}</span></span>
          ${icon("playlist_add")}
        </button>`);
      row.onclick = async () => {
        modal.close();
        await addToQueue(s, { onDone });
      };
      list.append(row);
    }
  };
  modal.querySelector("[data-filter]").addEventListener("input", render);
  render();
  setTimeout(() => modal.querySelector("[data-filter]").focus(), 50);
}
