// Utilidades compartilhadas por todas as paginas.
import { idioma, t } from "./i18n.js"; // (ciclo com o i18n.js: so usado dentro das funcoes)

export const NOTES = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"];
export const SCALES = [
  { id: "major", label: "Major" },
  { id: "minor", label: "Minor" },
];

export const $ = (sel, root = document) => root.querySelector(sel);
export const $$ = (sel, root = document) => [...root.querySelectorAll(sel)];

// Id anonimo deste aparelho (usado para saber quais musicas sao "suas").
// crypto.randomUUID nao existe em http:// fora do localhost, por isso o fallback.
export const clientId = (() => {
  const make = () =>
    (crypto.randomUUID && window.isSecureContext)
      ? crypto.randomUUID()
      : Date.now().toString(36) + Math.random().toString(36).slice(2, 12);
  try {
    let id = localStorage.getItem("karaoke.client");
    if (!id) {
      id = make();
      localStorage.setItem("karaoke.client", id);
    }
    return id;
  } catch {
    return make();
  }
})();

export function store(key, value) {
  try {
    if (value === undefined) return JSON.parse(localStorage.getItem(key));
    localStorage.setItem(key, JSON.stringify(value));
  } catch {
    return undefined;
  }
}

/** Codigo do celular administrador (vem do QR code das Configuracoes do PC). */
export const adminToken = () => store("karaoke.admin") || "";

/** Sessao da conta (nome + PIN) deste aparelho. O servidor tambem guarda um cookie de reserva. */
export const sessionToken = () => store("karaoke.session") || "";

/** O navegador guarda dados? (aba anonima / "bloquear cookies" do iOS: nao — o login nao fica) */
export const storageOk = (() => {
  try {
    localStorage.setItem("karaoke.test", "1");
    const ok = localStorage.getItem("karaoke.test") === "1";
    localStorage.removeItem("karaoke.test");
    return ok;
  } catch {
    return false;
  }
})();

/** Cabecalhos de identidade de todo pedido: aparelho, conta e administrador. */
export function authHeaders() {
  const admin = adminToken();
  const session = sessionToken();
  return {
    "X-Client-Id": clientId,
    ...(session ? { "X-Session": session } : {}),
    ...(admin ? { "X-Admin-Token": admin } : {}),
  };
}

/** A mensagem de "sem conexao" (no idioma da pagina). */
export const offlineMessage = () => t("comum.offline");

/**
 * Chama a API do servidor. `timeout` (ms): desiste de uma requisicao travada (ex.: o
 * celular trocou de Wi-Fi). Sem resposta do servidor, o erro tem `offline = true` e
 * uma mensagem no idioma da pagina (no lugar do "Failed to fetch" do navegador).
 */
// idioma das paginas (i18n.js): vai em cada pedido, para o servidor responder no mesmo idioma
let idiomaAtual = "pt-BR";
export const setIdiomaAtual = (idioma) => (idiomaAtual = idioma);

export async function api(path, { method = "GET", body, timeout = 0 } = {}) {
  const ctrl = timeout ? new AbortController() : null;
  const timer = ctrl && setTimeout(() => ctrl.abort(), timeout);
  let res;
  try {
    res = await fetch(path, {
      method,
      headers: { ...authHeaders(), "X-Idioma": idiomaAtual, ...(body ? { "Content-Type": "application/json" } : {}) },
      body: body ? JSON.stringify(body) : undefined,
      signal: ctrl ? ctrl.signal : undefined,
    });
  } catch {
    const err = new Error(offlineMessage());
    err.offline = true;
    throw err;
  } finally {
    clearTimeout(timer);
  }
  let data = null;
  try {
    data = await res.json();
  } catch {
    /* sem corpo */
  }
  if (!res.ok) {
    const err = new Error((data && data.error) || `erro ${res.status}`);
    err.status = res.status;
    err.data = data; // ex.: {busy: true} quando tem alguem cantando
    throw err;
  }
  return data;
}

// ------------------------------------------------------------- biblioteca
// As musicas prontas (so o que as listas usam). A pagina guarda a lista e a versao: o servidor so
// manda a lista de novo quando ela muda (com milhares de musicas, faz diferenca a cada 2-5 s).
const bib = { versao: "", songs: [], pedido: null };

/** {songs, mudou}: a lista atual (mudou: e diferente da ultima que esta pagina recebeu). */
export function biblioteca() {
  if (bib.pedido) return bib.pedido; // duas partes da pagina pedindo ao mesmo tempo: um pedido so
  bib.pedido = api(`/api/biblioteca?v=${encodeURIComponent(bib.versao)}`).then((r) => {
    if (r.mudou) Object.assign(bib, { versao: r.versao, songs: r.songs || [] });
    return { songs: bib.songs, mudou: !!r.mudou };
  }).finally(() => (bib.pedido = null));
  return bib.pedido;
}

/** Texto sem acentos e em minusculas (buscas). */
export const dobrar = (s) => String(s || "").toLowerCase().normalize("NFD").replace(/[̀-ͯ]/g, "");

/** Poe os itens no container aos poucos, em lotes, conforme a rolagem chega perto do fim: com milhares
 *  de musicas a pagina so cria o que esta perto da tela. `minimo`: quantos criar ja (redesenhar sem perder
 *  a posicao). `horizontal`: uma prateleira que rola para o lado. Devolve {quantos(), parar()}. */
export function aosPoucos(box, items, make, { lote = 60, minimo = 0, horizontal = false } = {}) {
  let n = 0;
  const fim = document.createElement("div");
  fim.className = "aos-poucos";
  box.append(fim);
  const mais = (qtd) => {
    const frag = document.createDocumentFragment();
    const ate = Math.min(items.length, n + qtd);
    for (; n < ate; n++) frag.append(make(items[n]));
    fim.before(frag);
    if (n >= items.length) parar();
  };
  const obs = new IntersectionObserver((vistos) => {
    if (!vistos.some((v) => v.isIntersecting)) return;
    mais(lote);
    if (n < items.length) {
      obs.unobserve(fim); // ainda perto da tela depois do lote: observar de novo avisa de novo
      obs.observe(fim);
    }
  }, {
    root: horizontal ? box : null,
    rootMargin: horizontal ? "0px 1200px 0px 0px" : "0px 0px 1600px 0px",
  });
  function parar() {
    obs.disconnect();
    fim.remove();
  }
  mais(Math.max(lote, minimo));
  if (n < items.length) obs.observe(fim);
  return { quantos: () => n, parar };
}

/** Foto da conta, ou as iniciais numa cor fixa para cada nome. */
export function avatar(account, cls = "") {
  if (!account || !account.name) return `<span class="avatar ${cls}"></span>`;
  if (account.photo) return `<span class="avatar ${cls}"><img src="/api/account/${account.id}/photo?v=${account.photo}" alt=""></span>`;
  const words = account.name.trim().split(/\s+/);
  const initials = (words[0][0] + (words.length > 1 ? words[words.length - 1][0] : "")).toUpperCase();
  let hue = 0;
  for (const ch of account.name) hue = (hue * 31 + ch.charCodeAt(0)) % 360;
  return `<span class="avatar ${cls}" style="background:hsl(${hue} 55% 38%)">${esc(initials)}</span>`;
}

export function esc(text) {
  return String(text ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]);
}

/** Bytes em GB, no formato do idioma: "3,2 GB" / "3.2 GB". */
export const gb = (bytes) => `${num(bytes / 1024 ** 3, 1)} GB`;

/** Numero com `casas` decimais no formato do idioma da pagina. */
export const num = (n, casas = 0) =>
  new Intl.NumberFormat(idioma(), { minimumFractionDigits: casas, maximumFractionDigits: casas }).format(n);

/** Previsao de uma musica na fila de trabalho (s): "pronta em ~12 min". */
export function readyIn(eta) {
  if (eta == null) return "";
  return eta < 60 ? t("fila.quase_pronta") : t("fila.pronta_em", { min: Math.round(eta / 60) });
}

export function fmtTime(sec) {
  if (sec == null || !isFinite(sec)) return "–:––";
  sec = Math.max(0, sec);
  const m = Math.floor(sec / 60);
  const s = Math.floor(sec % 60);
  return `${m}:${String(s).padStart(2, "0")}`;
}

/** Icone do Material Symbols (Google). fill=true usa a versao preenchida. */
export function icon(name, cls = "") {
  return `<span class="ms${cls ? " " + cls : ""}" aria-hidden="true">${name}</span>`;
}

export function keyLabel(key) {
  if (!key || !key.tonic) return "";
  return `${key.tonic} ${key.mode === "minor" ? "Minor" : "Major"}`;
}

/** Tom depois de transpor n semitons (ex.: G Major +2 = A Major). */
export function transposeKey(key, n) {
  if (!key || !key.tonic || !n) return key;
  const i = NOTES.indexOf(key.tonic);
  return i < 0 ? key : { ...key, tonic: NOTES[(((i + n) % 12) + 12) % 12] };
}

/** "+2", "−3" (com o sinal de menos de verdade) ou "original". */
export function shiftText(n) {
  return n ? `${n > 0 ? "+" : "−"}${Math.abs(n)}` : t("tom.original");
}

export function h(html) {
  const t = document.createElement("template");
  t.innerHTML = html.trim();
  return t.content.firstElementChild;
}

export function toast(msg, { error = false, ms = 3200, key = null } = {}) {
  let box = $(".toasts");
  if (!box) {
    box = h('<div class="toasts"></div>');
    document.body.append(box);
  }
  // mesma chave (ex.: "voz guia"): atualiza o aviso que ja esta na tela
  let el = key ? [...box.children].find((t) => t.dataset.key === key) : null;
  if (el) {
    el.textContent = msg;
    el.classList.toggle("err", error);
    clearTimeout(el._timer);
  } else {
    el = h(`<div class="toast${error ? " err" : ""}">${esc(msg)}</div>`);
    if (key) el.dataset.key = key;
    box.append(el);
    while (box.children.length > 4) box.firstElementChild.remove();
  }
  el._timer = setTimeout(() => el.remove(), ms);
}

// ---------------------------------------------------------------- preview
// Um unico <audio> para os previews, para nunca tocar dois ao mesmo tempo.
const previewAudio = new Audio();
let previewBtn = null;
let previewTimer = null;

export function stopPreview() {
  previewAudio.pause();
  clearTimeout(previewTimer);
  if (previewBtn) {
    previewBtn.classList.remove("playing");
    previewBtn.innerHTML = previewBtn.dataset.icon || icon("play_arrow", "fill");
  }
  previewBtn = null;
}

previewAudio.addEventListener("ended", stopPreview);

/** Toca um trecho. `start` em segundos (ou fracao 0-1 se `relative`). */
export async function togglePreview(btn, src, { start = 0, relative = false, seconds = 0 } = {}) {
  if (previewBtn === btn) {
    stopPreview();
    return;
  }
  stopPreview();
  previewBtn = btn;
  btn.dataset.icon = btn.dataset.icon || btn.innerHTML;
  btn.innerHTML = '<span class="spinner"></span>';
  try {
    previewAudio.src = src;
    await new Promise((resolve, reject) => {
      previewAudio.onloadedmetadata = resolve;
      previewAudio.onerror = () => reject(new Error(t("comum.preview_falhou")));
    });
    if (previewBtn !== btn) return;
    previewAudio.currentTime = relative ? previewAudio.duration * start : start;
    await previewAudio.play();
    btn.classList.add("playing");
    btn.innerHTML = "stop" in btn.dataset ? `${icon("stop", "fill")} ${esc(t("comum.parar"))}` : icon("stop", "fill");
    if (seconds) previewTimer = setTimeout(stopPreview, seconds * 1000);
  } catch (err) {
    if (previewBtn === btn) {
      stopPreview();
      toast(err.message, { error: true });
    }
  }
}

// ------------------------------------------------------------------ modal
/** fixo: so fecha pelos botoes da propria janela (nem clicando fora, nem com Esc). */
export function openModal(title, bodyHtml, { fixo = false } = {}) {
  const back = h(`
    <div class="modal-backdrop">
      <div class="modal" role="dialog" aria-label="${esc(title)}">
        <div class="modal-head"><h3>${esc(title)}</h3>${fixo ? "" : `<button class="icon-btn plain" data-close title="${t("comum.fechar")}">${icon("close")}</button>`}</div>
        <div class="modal-body">${bodyHtml}</div>
      </div>
    </div>`);
  const close = () => {
    back.remove();
    if (!document.querySelector(".modal-backdrop")) document.documentElement.classList.remove("modal-open");
    document.removeEventListener("keydown", onKey);
    back.dispatchEvent(new CustomEvent("closed"));
  };
  const onKey = (e) => e.key === "Escape" && close();
  if (!fixo) {
    back.addEventListener("mousedown", (e) => e.target === back && close());
    back.querySelector("[data-close]").onclick = close;
    document.addEventListener("keydown", onKey);
  }
  document.body.append(back);
  document.documentElement.classList.add("modal-open");
  back.close = close;
  return back;
}

// ------------------------------------------------------- escolher a letra
const SOURCE_LABEL = { lrclib: "LRCLIB", manual: "Manual", ia: "IA" };
/** O nome de uma fonte de letra: as do nucleo, ou "<complemento>:<fonte>" (mostra a fonte). */
const sourceLabel = (s) => SOURCE_LABEL[s] || (String(s || "").split(":").pop() || "").replace(/^\w/, (c) => c.toUpperCase());

function diffClass(itemDur, songDur) {
  if (!itemDur || !songDur) return "";
  const d = Math.abs(itemDur - songDur);
  return d <= 2 ? "diff-ok" : d <= 6 ? "diff-meh" : "diff-bad";
}

/** Resolve com true se uma letra foi escolhida, false se pulou. */
export function chooseLyrics(song) {
  return new Promise((resolve) => {
    let chosen = false;
    const query = `${song.artist || ""} ${song.track || song.title || ""}`.trim();
    const modal = openModal(t("letra.escolha_titulo", { titulo: song.title }), `
      <div class="row">
        <input class="input grow" data-q value="${esc(query)}" placeholder="${t("letra.busca_placeholder")}">
        <button class="btn" data-search>${t("comum.buscar")}</button>
      </div>
      <div class="source-tabs">
        <label class="badge gray"><input type="checkbox" value="lrclib" checked> LRCLIB</label>
        <span data-fontes-letras></span>
        <span class="spacer grow"></span>
        ${song.status === "ready" ? `<button class="btn outline xs" data-rank title="${t("letra.rank_dica")}">${icon("auto_awesome", "sm")} ${t("letra.rank")}</button>` : ""}
        <span class="small muted">${t("letra.duracao")} <b>${fmtTime(song.duration)}</b></span>
      </div>
      <div class="results" data-results><div class="empty">${t("comum.buscando")}</div></div>
      <div class="row wrap" style="margin-top:14px">
        <button class="btn ghost sm" data-paste>${t("letra.colar")}</button>
        ${song.lyrics_previous ? `<button class="btn ghost sm" data-restore>${icon("undo")} ${t("letra.voltar_anterior")}</button>` : ""}
        ${song.lyrics ? `<button class="btn danger sm" data-clear>${t("letra.remover")}</button>` : ""}
        <span class="grow"></span>
        <button class="btn ghost sm" data-skip>${t("comum.pular")}</button>
      </div>`);
    modal.addEventListener("closed", () => resolve(chosen));
    // as fontes de letras dos complementos ligados (NetEase, Musixmatch...)
    api("/api/recursos").then((r) => {
      $("[data-fontes-letras]", modal).innerHTML = (r.letras || []).map((f) =>
        `<label class="badge gray"><input type="checkbox" value="${esc(f.id)}" checked> ${esc(f.nome)}</label>`).join(" ");
      $$("[data-fontes-letras] input", modal).forEach((i) => (i.onchange = search));
    }).catch(() => {});
    const results = $("[data-results]", modal);
    const qInput = $("[data-q]", modal);

    let shown = [];
    let rankTimer = null;
    modal.addEventListener("closed", () => clearTimeout(rankTimer));

    async function use(payload, sync = false) {
      try {
        await api(`/api/songs/${song.id}/lyrics`, { method: "POST", body: { ...payload, sync } });
        chosen = true;
        toast(sync ? t("letra.salva_ia") : t("letra.salva"));
        modal.close();
      } catch (err) {
        toast(err.message, { error: true });
      }
    }

    function render(items, errors) {
      if (!items.length) {
        const errs = Object.entries(errors || {}).map(([s, e]) => `${sourceLabel(s)}: ${esc(e)}`).join("<br>");
        results.innerHTML = `<div class="empty">${t("letra.nenhuma")}${errs ? `<br><span class="small">${errs}</span>` : ""}</div>`;
        return;
      }
      results.innerHTML = "";
      shown = items;
      const canSync = song.status === "ready";
      const statusOf = (it) => it.words ? `<span class="badge ok">${icon("format_color_text", "sm")} ${t("letra.palavra_a_palavra")}</span>`
        : it.synced === true ? `<span class="badge ok">${t("letra.sincronizada")}</span>`
          : it.synced === false ? `<span class="badge warn">${t("letra.sem_tempo")}</span>`
            : String(it.source).includes(":") ? `<span class="badge gray">${t("letra.pode_ter_palavras")}</span>` : "";
      for (const it of items) {
        const el = h(`
          <div class="result lyric-item">
            <div class="head">
              <div class="grow">
                <div class="title">${esc(it.artist ? `${it.artist} — ${it.title}` : it.title)}</div>
                <div class="sub">
                  <span class="${diffClass(it.duration, song.duration)}">${fmtTime(it.duration)}</span>
                  · ${sourceLabel(it.source)} ${it.album ? "· " + esc(it.album) : ""} <span data-status>${statusOf(it)}</span>
                </div>
              </div>
              <button class="btn ghost xs" data-view>${t("comum.ver")}</button>
              <button class="btn xs" data-use>${t("letra.usar")}</button>
              ${canSync ? `<button class="btn outline xs" data-use-ai title="${t("letra.usar_ia_dica")}">${icon("auto_awesome", "sm")} ${t("letra.usar_ia")}</button>` : ""}
            </div>
          </div>`);
        it.el = el;
        const getText = async () => {
          if (it.text) return it.text;
          const r = await api(`/api/lyrics/fetch?source=${it.source}&id=${encodeURIComponent(it.id)}`);
          it.text = r.text;
          it.synced = r.synced;
          it.words = r.words;
          $("[data-status]", el).innerHTML = statusOf(it);
          return it.text;
        };
        $("[data-view]", el).onclick = async () => {
          const old = $("pre", el);
          if (old) return old.remove();
          try {
            const text = await getText();
            el.append(h(`<pre>${esc(text || t("letra.vazia"))}</pre>`));
          } catch (err) {
            toast(err.message, { error: true });
          }
        };
        const choose = async (sync) => {
          try {
            const text = await getText();
            if (!text) return toast(t("erro.fonte_sem_letra"), { error: true });
            use({ text, source: it.source, title: it.title, artist: it.artist }, sync);
          } catch (err) {
            toast(err.message, { error: true });
          }
        };
        $("[data-use]", el).onclick = () => choose(false);
        const useAi = $("[data-use-ai]", el);
        if (useAi) useAi.onclick = () => choose(true);
        results.append(el);
      }
    }

    async function search() {
      const sources = $$(".source-tabs input:checked", modal).map((i) => i.value).join(",");
      results.innerHTML = `<div class="empty"><span class="spinner"></span> ${t("comum.buscando")}</div>`;
      try {
        const q = encodeURIComponent(qInput.value.trim());
        const r = await api(`/api/lyrics/search?q=${q}&duration=${song.duration || ""}&sources=${sources}`);
        render(r.results, r.errors);
      } catch (err) {
        results.innerHTML = `<div class="empty">${esc(err.message)}</div>`;
      }
    }

    /** A IA da uma nota para cada letra: quanto ela encaixa no que foi cantado. */
    async function rank(btn) {
      const items = shown.filter((it) => !String(it.source).endsWith(":musixmatch") || it.text);
      if (!items.length) return toast(t("letra.busque_primeiro"), { error: true });
      btn.disabled = true;
      btn.innerHTML = `<span class="spinner"></span> ${t("letra.comparando")}`;
      try {
        await api(`/api/songs/${song.id}/lyrics/rank`, {
          method: "POST",
          body: { items: items.map((it) => ({ source: it.source, id: it.id, text: it.text || "", album: it.album || "" })) },
        });
      } catch (err) {
        btn.disabled = false;
        btn.innerHTML = `${icon("auto_awesome", "sm")} ${t("letra.rank")}`;
        return toast(err.message, { error: true });
      }
      const poll = async () => {
        let s;
        try {
          s = await api(`/api/songs/${song.id}`);
        } catch {
          rankTimer = setTimeout(poll, 2000);
          return;
        }
        const r = s.lyrics_rank || {};
        if (r.state === "queued" || r.state === "running") {
          rankTimer = setTimeout(poll, 1200);
          return;
        }
        btn.disabled = false;
        btn.innerHTML = `${icon("auto_awesome", "sm")} ${t("letra.comparar_de_novo")}`;
        if (r.state !== "done") return toast(r.error || t("letra.comparar_falhou"), { error: true });
        showRank(items, r.results || []);
      };
      poll();
    }

    // notas da IA: letra = quanto das palavras bate com o que foi cantado; tempo = quantas linhas ja
    // comecam onde a voz canta (um atraso igual na letra toda aparece a parte: a IA acerta sozinha)
    function showRank(items, results) {
      for (const r of results) {
        const it = items[r.i];
        if (!it || !it.el) continue;
        it.best = !!r.best;
        it.content = r.content ?? -1;
        it.timing = r.timing ?? -1;
        $$(".rank-tags", it.el).forEach((t) => t.remove());
        const tags = [];
        if (r.best) tags.push(`<span class="badge ok">${icon("star", "sm")} ${t("letra.melhor")}</span>`);
        if (r.content != null) tags.push(`<span class="badge gray" title="${t("letra.nota_letra_dica")}">${t("letra.nota_letra", { p: Math.round(r.content * 100) })}</span>`);
        if (r.timing != null) {
          tags.push(`<span class="badge gray" title="${t("letra.nota_tempo_dica")}">${t("letra.nota_tempo", { p: Math.round(r.timing * 100) })}</span>`);
          if (Math.abs(r.offset || 0) > 0.3) {
            tags.push(`<span class="badge gray" title="${t("letra.deslocada_dica")}">${t(r.offset < 0 ? "letra.atrasada" : "letra.adiantada", { s: num(Math.abs(r.offset), 1) })}</span>`);
          }
        }
        if (r.same) tags.push(`<span class="badge gray">${t("letra.mesmo_texto", { n: r.same + 1 })}</span>`);
        if (r.video) tags.push(`<span class="badge gray">${icon("smart_display", "sm")} ${t("letra.desta_versao")}</span>`);
        $(".sub", it.el).append(h(`<span class="rank-tags">${tags.join(" ")}</span>`));
      }
      // a escolhida primeiro; depois letra e tempo (empate: a ordem da busca)
      [...items].sort((a, b) => (b.best ? 1 : 0) - (a.best ? 1 : 0) || (b.content ?? -1) - (a.content ?? -1) || (b.timing ?? -1) - (a.timing ?? -1))
        .forEach((it) => it.el && results.length && it.el.parentNode && it.el.parentNode.append(it.el));
    }

    const rankBtn = $("[data-rank]", modal);
    if (rankBtn) rankBtn.onclick = () => rank(rankBtn);
    $("[data-search]", modal).onclick = search;
    qInput.addEventListener("keydown", (e) => e.key === "Enter" && search());
    $$(".source-tabs input", modal).forEach((i) => (i.onchange = search));
    $("[data-skip]", modal).onclick = () => modal.close();
    const restoreBtn = $("[data-restore]", modal);
    if (restoreBtn) {
      restoreBtn.onclick = async () => {
        try {
          await api(`/api/songs/${song.id}/lyrics/restore`, { method: "POST" });
          chosen = true;
          toast(t("letra.anterior_de_volta"));
          modal.close();
        } catch (err) {
          toast(err.message, { error: true });
        }
      };
    }
    const clearBtn = $("[data-clear]", modal);
    if (clearBtn) {
      clearBtn.onclick = async () => {
        await api(`/api/songs/${song.id}/lyrics`, { method: "DELETE" });
        chosen = true;
        toast(t("letra.removida"));
        modal.close();
      };
    }
    $("[data-paste]", modal).onclick = () => {
      results.innerHTML = `
        <div class="small muted" style="margin-bottom:8px">${t("letra.colar_texto")}</div>
        <textarea class="input" data-text placeholder="${t("letra.colar_placeholder")}"></textarea>
        <div class="row" style="margin-top:8px"><span class="grow"></span><button class="btn sm" data-save>${t("letra.salvar")}</button></div>`;
      const ta = $("[data-text]", results);
      ta.addEventListener("dragover", (e) => e.preventDefault());
      ta.addEventListener("drop", async (e) => {
        e.preventDefault();
        const file = e.dataTransfer.files[0];
        if (file) ta.value = await file.text();
      });
      $("[data-save]", results).onclick = () => ta.value.trim() && use({ text: ta.value, source: "manual" });
      ta.focus();
    };
    search();
  });
}

// -------------------------------------------------------- escolher a capa
export function chooseCover(song) {
  return new Promise((resolve) => {
    let chosen = false;
    const query = `${song.artist || ""} ${song.track || song.title || ""}`.trim();
    // a miniatura que veio da fonte (se tiver) tambem pode ser a capa
    const fonteThumb = song.thumb && song.thumb.startsWith("/api/songs/") ? song.thumb : null;
    const modal = openModal(t("capa.escolha_titulo", { titulo: song.title }), `
      <div class="row">
        <input class="input grow" data-q value="${esc(query)}" placeholder="${t("capa.busca_placeholder")}">
        <button class="btn" data-search>${t("comum.buscar")}</button>
      </div>
      <label class="cover-drop" data-drop>
        <input type="file" accept="image/*" data-file hidden>
        ${icon("upload")}
        <span><b>${t("capa.enviar")}</b><span class="small muted"> — ${t("capa.enviar_dica")}</span></span>
      </label>
      <div class="cover-grid" data-grid><div class="empty">${t("comum.buscando")}</div></div>
      <div class="row" style="margin-top:14px">
        <span class="small muted">${fonteThumb ? t("capa.ultima_miniatura") : ""}</span>
        <span class="grow"></span>
        <button class="btn ghost sm" data-skip>${t("comum.pular")}</button>
      </div>`);
    modal.addEventListener("closed", () => resolve(chosen));
    const grid = $("[data-grid]", modal);
    const qInput = $("[data-q]", modal);

    async function pick(body) {
      grid.style.opacity = 0.5;
      try {
        await api(`/api/songs/${song.id}/cover`, { method: "POST", body });
        chosen = true;
        toast(t("capa.salva"));
        modal.close();
      } catch (err) {
        grid.style.opacity = 1;
        toast(err.message, { error: true });
      }
    }

    async function search() {
      grid.innerHTML = `<div class="empty"><span class="spinner"></span> ${t("comum.buscando")}</div>`;
      try {
        const r = await api(`/api/covers/search?q=${encodeURIComponent(qInput.value.trim())}`);
        grid.innerHTML = "";
        const items = [...r.results];
        if (fonteThumb) items.push({ thumb: fonteThumb, title: t("capa.miniatura"), artist: "", daFonte: true });
        if (!items.length) grid.innerHTML = `<div class="empty">${t("comum.nada")}</div>`;
        for (const it of items) {
          const b = h(`<button title="${esc(it.artist + " — " + it.title)}"><img loading="lazy" src="${esc(it.thumb)}" alt=""><span class="cap">${esc(it.title)}</span></button>`);
          b.onclick = () =>
            pick(it.daFonte ? { clear: true } : { url: it.full, source: "itunes", album: it.album, genre: it.genre, year: it.year });
          grid.append(b);
        }
      } catch (err) {
        grid.innerHTML = `<div class="empty">${esc(err.message)}</div>`;
      }
    }

    // imagem do computador/celular: escolher, arrastar ou colar
    async function upload(file) {
      if (!file || !file.type.startsWith("image/")) return toast(t("capa.nao_imagem"), { error: true });
      const drop = $("[data-drop]", modal);
      drop.classList.add("busy");
      const form = new FormData();
      form.append("file", file);
      try {
        const res = await fetch(`/api/songs/${song.id}/cover/upload`, { method: "POST", headers: authHeaders(), body: form });
        const data = await res.json().catch(() => ({}));
        if (!res.ok) throw new Error(data.error || `erro ${res.status}`);
        chosen = true;
        toast(t("capa.salva"));
        modal.close();
      } catch (err) {
        drop.classList.remove("busy");
        toast(err.message, { error: true });
      }
    }
    const fileInput = $("[data-file]", modal);
    fileInput.onchange = () => upload(fileInput.files[0]);
    const drop = $("[data-drop]", modal);
    modal.addEventListener("dragover", (e) => {
      e.preventDefault();
      drop.classList.add("over");
    });
    modal.addEventListener("dragleave", (e) => e.target === modal && drop.classList.remove("over"));
    modal.addEventListener("drop", (e) => {
      e.preventDefault();
      drop.classList.remove("over");
      upload(e.dataTransfer.files[0]);
    });
    const onPaste = (e) => {
      const item = [...(e.clipboardData || {}).items || []].find((i) => i.type.startsWith("image/"));
      if (item) {
        e.preventDefault();
        upload(item.getAsFile());
      }
    };
    document.addEventListener("paste", onPaste);
    modal.addEventListener("closed", () => document.removeEventListener("paste", onPaste));

    $("[data-search]", modal).onclick = search;
    qInput.addEventListener("keydown", (e) => e.key === "Enter" && search());
    $("[data-skip]", modal).onclick = () => modal.close();
    search();
  });
}

// ------------------------------------------------- editar informacoes
/** Modal para corrigir titulo/artista/album/estilo. Resolve true se salvou. */
export function editSong(song, { genres = [] } = {}) {
  return new Promise((resolve) => {
    let saved = false;
    const podeTrocar = ["ready", "error"].includes(song.status) && !document.body.classList.contains("mobile");
    const field = (name, label, value, extra = "") =>
      `<label class="${extra}"><span class="label">${label}</span><input class="input" data-f="${name}" value="${esc(value || "")}"${name === "genre" ? ' list="genreList"' : ""}></label>`;
    const modal = openModal(t("musica.editar"), `
      <div class="form-grid">
        ${field("title", t("musica.titulo"), song.title, "full")}
        ${field("artist", t("musica.artista"), song.artist)}
        ${field("track", t("musica.nome"), song.track)}
        ${field("album", t("musica.album"), song.album)}
        ${field("genre", t("musica.estilo"), song.genre)}
        ${field("year", t("musica.ano"), song.year)}
      </div>
      <datalist id="genreList">${genres.map((g) => `<option value="${esc(g)}">`).join("")}</datalist>
      <div class="reprocess stack">
        <div>
          <b>${t("musica.audio_sep")}</b>
          <div class="small muted">
            ${song.audio ? t("musica.audio", { audio: `<b>${esc(song.audio)}</b>` }) : t("musica.audio_desconhecido")} ·
            ${song.quality ? t("musica.qualidade", { q: `<b>${esc(song.quality)}</b>` }) : t("musica.qualidade_antiga")}<span data-bm>${song.backing_model ? `; ${t("musica.voz_apoio")} <b>${esc(song.backing_model)}</b>` : ""}</span>.
            <span data-rp-hint></span>
          </div>
          ${song.troca_erro ? `<div class="small" style="color:var(--danger);margin-top:6px">${t("musica.trocar_audio_falhou")} ${esc(song.troca_erro)}</div>` : ""}
          <div class="small" data-acao-estado style="margin-top:6px" hidden></div>
        </div>
        <div class="row wrap">
          ${podeTrocar ? `<button class="btn sm" data-trocar-audio>${icon("swap_horiz")} ${t("musica.trocar_audio")}</button>
            <input type="file" data-trocar-input accept="audio/*,video/*" hidden>` : ""}
          ${(song.acoes || []).map((a) => `<button class="btn outline sm" data-acao-musica="${esc(a.id)}" data-complemento="${esc(a.complemento)}">${icon(a.icone || "extension")} ${esc(a.rotulo)}</button>`).join("")}
          <button class="btn outline sm" data-reprocess>${icon("graphic_eq")} ${t("musica.separar_de_novo")}</button>
          ${song.status === "ready" && !document.body.classList.contains("mobile")
            ? `<button class="btn outline sm" data-exportar-pacote>${icon("inventory_2")} ${t("pacotes.exportar")}</button>` : ""}
        </div>
        <div class="row wrap">
          <select class="input" data-resplit-model style="flex:1;min-width:240px"><option>${t("musica.carregando_modelos")}</option></select>
          <button class="btn outline sm" data-resplit disabled>${icon("record_voice_over")} ${t("musica.resplit")}</button>
        </div>
        <p class="small muted" style="margin:0">${t("musica.explica")}</p>
      </div>
      <div class="row wrap" style="margin-top:18px">
        <button class="btn outline sm" data-itunes>${icon("travel_explore")} ${t("musica.itunes")}</button>
        <span class="grow"></span>
        <button class="btn ghost sm" data-cancel>${t("comum.cancelar")}</button>
        <button class="btn sm" data-save>${t("comum.salvar")}</button>
      </div>`);
    modal.addEventListener("closed", () => resolve(saved));
    const get = (f) => modal.querySelector(`[data-f="${f}"]`);
    modal.querySelector("[data-cancel]").onclick = () => modal.close();
    // trocar o audio por outro arquivo (so no PC): pela janela do app ou pelo navegador
    const trocar = modal.querySelector("[data-trocar-audio]");
    if (trocar) {
      const input = modal.querySelector("[data-trocar-input]");
      const enviarTroca = async (pedido) => {
        trocar.disabled = true;
        try {
          await pedido();
          saved = true;
          toast(t("etapa.fila_trocar_audio"));
          modal.close();
        } catch (err) {
          toast(err.message, { error: true });
          trocar.disabled = false;
        }
      };
      trocar.onclick = async () => {
        if (!confirm(t("musica.trocar_audio_confirmar"))) return;
        const app = await import("./appwin.js").then((m) => m.appApi());
        if (!app || !app.escolher_audio) return input.click();
        const caminho = await app.escolher_audio();
        if (caminho) enviarTroca(() => api(`/api/arquivos/trocar/${song.id}`, { method: "POST", body: { caminho } }));
      };
      input.onchange = () => {
        const file = input.files[0];
        if (!file) return;
        const form = new FormData();
        form.append("arquivo", file, file.name);
        enviarTroca(async () => {
          const res = await fetch(`/api/arquivos/trocar/${song.id}`, {
            method: "POST", headers: { ...authHeaders(), "X-Idioma": idiomaAtual }, body: form,
          });
          const data = await res.json().catch(() => ({}));
          if (!res.ok) throw new Error(data.error || `erro ${res.status}`);
        });
      };
    }
    // botoes do complemento de onde a musica veio: rodam em segundo plano (andamento em fresh.acao)
    const acaoBtns = [...modal.querySelectorAll("[data-acao-musica]")];
    acaoBtns.forEach((b) => (b.onclick = async () => {
      const a = (song.acoes || []).find((x) => x.id === b.dataset.acaoMusica && x.complemento === b.dataset.complemento);
      acaoBtns.forEach((x) => (x.disabled = true));
      try {
        await api(`/api/songs/${song.id}/acoes/${encodeURIComponent(b.dataset.complemento)}/${encodeURIComponent(b.dataset.acaoMusica)}`, { method: "POST" });
        saved = true;
        toast(t("musica.acao_iniciada", { nome: a ? a.rotulo : "" }));
      } catch (err) {
        toast(err.message, { error: true });
      }
      refreshResplit();
    }));
    const renderAcao = () => {
      const el = modal.querySelector("[data-acao-estado]");
      const a = fresh.acao;
      const rodando = a && a.estado === "rodando";
      acaoBtns.forEach((x) => (x.disabled = rodando));
      el.hidden = !a;
      if (!a) return;
      el.style.color = a.estado === "erro" ? "var(--danger)" : "";
      el.innerHTML = rodando
        ? esc(t("musica.acao_andamento", { nome: a.rotulo || "", etapa: a.etapa || "", p: Math.round((a.progresso || 0) * 100) }))
        : a.estado === "erro" ? `${esc(t("musica.acao_falhou", { nome: a.rotulo || "" }))} ${esc(a.erro || "")}` : esc(a.texto || "");
      return rodando;
    };
    // voz x apoio: estado atual da musica (a lista da biblioteca pode estar alguns segundos atrasada)
    const pick = modal.querySelector("[data-resplit-model]");
    const resplitBtn = modal.querySelector("[data-resplit]");
    let models = null;
    let fresh = song;
    let resplitTimer = null;
    modal.addEventListener("closed", () => clearTimeout(resplitTimer));
    const renderResplit = () => {
      const r = fresh.resplit;
      const busy = r && ["queued", "running"].includes(r.state);
      resplitBtn.disabled = busy || !models;
      resplitBtn.innerHTML = `${icon("record_voice_over")} ${busy ? t("musica.resplit_andamento", { p: Math.round((r.progress || 0) * 100) }) : t("musica.resplit")}`;
      modal.querySelector("[data-bm]").innerHTML = fresh.backing_model ? `; ${t("musica.voz_apoio")} <b>${esc(fresh.backing_model)}</b>` : "";
      if (models) {
        const used = (models.list.find((m) => m.label === fresh.backing_model) || {}).id || models.default;
        const chosen = pick.dataset.touched ? pick.value : used;
        pick.innerHTML = models.list.map(({ id, label }) =>
          `<option value="${esc(id)}"${id === chosen ? " selected" : ""}>${esc(label)}${id === used ? ` — ${t("musica.o_desta")}` : ""}</option>`).join("");
      }
      if (r && r.state === "error") resplitBtn.title = t("musica.ultima_falhou", { erro: r.error || "" });
      const acaoRodando = renderAcao();
      clearTimeout(resplitTimer);
      if (busy || acaoRodando) resplitTimer = setTimeout(refreshResplit, 2000);
    };
    const refreshResplit = () => api(`/api/songs/${song.id}`).then((s) => { fresh = s; renderResplit(); }).catch(() => {
      resplitTimer = setTimeout(refreshResplit, 4000);
    });
    pick.onchange = () => (pick.dataset.touched = "1");
    api("/api/backing-models").then((r) => {
      // lista [{id, label}] (ou objeto {id: label}, de um servidor mais antigo)
      const list = Array.isArray(r.models) ? r.models : Object.entries(r.models || {}).map(([id, label]) => ({ id, label }));
      models = { list, default: r.default };
      renderResplit();
    }).catch((err) => {
      pick.innerHTML = `<option>${t("musica.modelos_falhou", { erro: esc(err.message) })}</option>`;
    });
    refreshResplit();
    resplitBtn.onclick = async () => {
      try {
        await api(`/api/songs/${song.id}/resplit`, { method: "POST", body: { model: pick.value } });
        saved = true;
        delete pick.dataset.touched;
        toast(t("musica.resplit_iniciado"));
        refreshResplit();
      } catch (err) {
        toast(err.message, { error: true });
      }
    };
    const exportar = modal.querySelector("[data-exportar-pacote]");
    if (exportar) exportar.onclick = () => import("./pacotes.js").then((m) => m.exportarPacotes([song.id]));
    modal.querySelector("[data-reprocess]").onclick = async () => {
      if (!confirm(t("musica.separar_confirmar"))) return;
      try {
        await api(`/api/songs/${song.id}/reprocess`, { method: "POST" });
        saved = true;
        toast(t("etapa.fila_separar_de_novo"));
        modal.close();
      } catch (err) {
        toast(err.message, { error: true });
      }
    };
    modal.querySelector("[data-itunes]").onclick = async (e) => {
      const btn = e.currentTarget;
      btn.disabled = true;
      try {
        // salva artista/musica primeiro, para a busca usar o que foi digitado
        await api(`/api/songs/${song.id}`, { method: "PATCH", body: { artist: get("artist").value, track: get("track").value } });
        const r = await api(`/api/songs/${song.id}/enrich`, { method: "POST", body: { force: true } });
        if (!r.found) toast(t("musica.itunes_nada"), { error: true });
        else {
          for (const f of ["album", "genre", "year"]) if (r.found[f]) get(f).value = r.found[f];
          toast(t("musica.itunes_ok"));
        }
      } catch (err) {
        toast(err.message, { error: true });
      }
      btn.disabled = false;
    };
    modal.querySelector("[data-save]").onclick = async () => {
      const body = {};
      for (const f of ["title", "artist", "track", "album", "genre", "year"]) body[f] = get(f).value;
      try {
        await api(`/api/songs/${song.id}`, { method: "PATCH", body });
        saved = true;
        toast(t("musica.salva"));
        modal.close();
      } catch (err) {
        toast(err.message, { error: true });
      }
    };
  });
}
