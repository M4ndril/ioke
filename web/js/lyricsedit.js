// Editor de letra no player: edita o texto e sincroniza "no toque" — com a
// musica tocando, aperte ESPACO quando cada linha comecar. Serve para criar
// uma letra sincronizada a partir de uma letra sem tempo e para corrigir so
// uma linha de uma letra que ja existe.
import { $, $$, api, confirmar, esc, fmtTime, icon, toast } from "./common.js";
import { t as tr } from "./i18n.js";

const REACTION = 0.12; // quem aperta o botao sempre atrasa um pouquinho
const BREAK = "♪";

function parse(data) {
  if (!data || !data.type) return [];
  if (data.type === "plain") {
    return data.text.split(/\r?\n/).map((l) => l.trim()).filter(Boolean).map((text) => ({ text, t: null }));
  }
  const rows = [];
  let shift = 0;
  for (const raw of data.text.split(/\r?\n/)) {
    const off = raw.match(/^\s*\[offset:\s*([+-]?\d+)\s*\]/i);
    if (off) {
      shift = Number(off[1]) / 1000;
      continue;
    }
    const stamps = [...raw.matchAll(/\[(\d{1,3}):(\d{1,2})(?:[.:](\d{1,3}))?\]/g)];
    if (!stamps.length) continue;
    const body = raw.replace(/\[[^\]]*\]/g, "");
    const text = body.replace(/<[^>]*>/g, "").trim();
    // guarda o tempo de cada palavra: se a linha mudar de lugar, as palavras vao junto
    const words = /<\d{1,3}:\d{1,2}/.test(body) && stamps.length === 1 && !shift ? body.trim() : null;
    for (const m of stamps) {
      const t = Number(m[1]) * 60 + Number(m[2]) + (m[3] ? Number(m[3]) / 10 ** m[3].length : 0) - shift;
      rows.push({ text: text || BREAK, t, words, t0: t });
    }
  }
  rows.sort((a, b) => a.t - b.t);
  // varias linhas vazias seguidas viram uma pausa so
  return rows.filter((r, i) => r.text !== BREAK || !rows[i - 1] || rows[i - 1].text !== BREAK);
}

const stamp = (t) => {
  const cs = Math.max(0, Math.round(t * 100));
  return `${String(Math.floor(cs / 6000)).padStart(2, "0")}:${String(Math.floor((cs % 6000) / 100)).padStart(2, "0")}.${String(cs % 100).padStart(2, "0")}`;
};

/**
 * Abre o editor. `player` tem: time(), seek(t), play(), pause(), playing(), offset().
 * Os tempos ficam no "tempo da letra" (musica - ajuste de sincronia), como no player.
 */
export async function openLyricsEditor(song, player, { onSaved, onClose } = {}) {
  const aiOk = song.status === "ready" && song.stems && song.stems.lead; // a IA precisa da voz separada
  const box = $("#lyricsEditor");
  let rows = [];
  try {
    rows = parse(await api(`/api/songs/${song.id}/lyrics`));
  } catch (err) {
    toast(err.message, { error: true });
  }
  let mode = rows.length && rows.every((r) => r.t != null) ? "sync" : "text";
  let cursor = 0;
  let undo = [];
  let dirty = false;
  let raf = null;

  const offset = () => player.offset() || 0;
  // tempo da letra = tempo da musica - offset (igual ao player)
  const now = () => Math.max(0, player.time() - offset() - REACTION);

  async function close(force = false) {
    if (dirty && !force && !(await confirmar(tr("editor.sair_sem_salvar"), { sim: tr("editor.sair"), perigo: true }))) return;
    box.classList.remove("open");
    box.setAttribute("aria-hidden", "true");
    window.removeEventListener("keydown", onKey, true);
    cancelAnimationFrame(raf);
    onClose && onClose();
  }

  function onKey(e) {
    if (mode !== "sync" || e.target.closest("textarea, input, select") || document.querySelector(".modal-backdrop")) return;
    const k = e.key;
    if (k === " " || k === "Enter") {
      e.preventDefault();
      e.stopImmediatePropagation();
      mark();
    } else if (k === "Backspace") {
      e.preventDefault();
      e.stopImmediatePropagation();
      back();
    } else if (k === "Escape") {
      e.stopImmediatePropagation();
      close();
    } else if (k.toLowerCase() === "p") {
      e.preventDefault();
      e.stopImmediatePropagation();
      if (player.playing()) player.pause();
      else player.play();
    }
  }

  function mark() {
    if (cursor >= rows.length) return toast(tr("editor.todas_com_tempo"));
    if (!player.playing()) player.play();
    const t = now();
    undo.push({ i: cursor, t: rows[cursor].t });
    rows[cursor].t = t;
    // se as proximas ficaram "antes" desta, perdem o tempo (precisam ser marcadas de novo)
    for (let j = cursor + 1; j < rows.length && rows[j].t != null && rows[j].t <= t; j++) rows[j].t = null;
    cursor++;
    dirty = true;
    renderSync(true);
  }

  function back() {
    const last = undo.pop();
    if (!last) return;
    rows[last.i].t = last.t;
    cursor = last.i;
    const prev = rows.slice(0, cursor).reverse().find((r) => r.t != null);
    player.seek(Math.max(0, (prev ? prev.t : player.time() - 4) + offset() - 1));
    renderSync(true);
  }

  function goTo(i) {
    cursor = i;
    const ref = rows[i].t ?? (rows.slice(0, i).reverse().find((r) => r.t != null) || {}).t;
    player.seek(Math.max(0, (ref ?? 0) + offset() - 2.5));
    player.play();
    renderSync(true);
  }

  function lrc() {
    // linha ainda sem tempo nao fica de fora: tempo estimado entre as vizinhas
    const ts = rows.map((r) => r.t);
    for (let i = 0; i < ts.length; i++) {
      if (ts[i] != null) continue;
      let j = i;
      while (j < ts.length && ts[j] == null) j++;
      const prev = i > 0 ? ts[i - 1] : null;
      const next = j < ts.length ? ts[j] : null;
      for (let k = i; k < j; k++) {
        ts[k] = prev != null && next != null ? prev + ((next - prev) * (k - i + 1)) / (j - i + 1)
          : prev != null ? prev + 3 * (k - i + 1) : Math.max(0, next - 3 * (j - k));
      }
      i = j - 1;
    }
    return rows.map((r, i) => ({ r, t: ts[i] })).sort((a, b) => a.t - b.t)
      .map(({ r, t }) => `[${stamp(t)}]${r.text === BREAK ? "" : r.t != null ? wordsOf(r) : r.text}`).join("\n");
  }

  /** Texto da linha; com tempo por palavra (e o texto igual), as marcas vao junto com a linha. */
  function wordsOf(r) {
    if (!r.words || r.words.replace(/<[^>]*>/g, "").trim() !== r.text) return r.text;
    const d = r.t - r.t0;
    return r.words.replace(/<(\d{1,3}):(\d{1,2})(?:[.:](\d{1,3}))?>/g, (_, mm, ss, frac) => {
      const t = Number(mm) * 60 + Number(ss) + (frac ? Number(frac) / 10 ** frac.length : 0) + d;
      return `<${stamp(t)}>`;
    });
  }

  /** ai: salva o texto exatamente como esta e pede para a IA so encaixar os tempos. */
  async function save(ai = false) {
    const missing = rows.filter((r) => r.t == null && r.text !== BREAK).length;
    const timed = rows.filter((r) => r.t != null).length;
    const typed = () => ($(".le-text", box) ? $(".le-text", box).value : rows.map((r) => r.text).join("\n"));
    let payload;
    if (ai) {
      const text = typed().split("\n").filter((l) => l.trim() !== BREAK).join("\n");
      if (!text.trim()) return toast(tr("editor.vazia"), { error: true });
      payload = { text, source: "manual", sync: true };
    } else if (mode === "text" || !timed) {
      const text = typed();
      if (!text.trim()) return toast(tr("editor.vazia"), { error: true });
      if (!(await confirmar(tr("editor.sem_tempo_confirmar"), { sim: tr("editor.salvar_assim") }))) return;
      payload = { text: text.split("\n").filter((l) => l.trim() !== BREAK).join("\n"), source: "manual" };
    } else {
      if (missing && !(await confirmar(tr("editor.faltam_confirmar", { n: missing }), { sim: tr("editor.salvar_assim") }))) return;
      payload = { text: lrc(), source: "manual" };
    }
    try {
      await api(`/api/songs/${song.id}/lyrics`, { method: "POST", body: payload });
      dirty = false;
      toast(tr(ai ? "editor.salva_ia" : "editor.salva"));
      close(true);
      onSaved && onSaved();
    } catch (err) {
      toast(err.message, { error: true });
    }
  }

  // ------------------------------------------------------------ texto
  function renderText() {
    mode = "text";
    cancelAnimationFrame(raf);
    $(".le-body", box).innerHTML = `
      <p class="small muted" style="margin:0">${tr("editor.texto_explica", { pausa: `<b>${BREAK}</b>` })}</p>
      <textarea class="input le-text" spellcheck="false" placeholder="${esc(tr("editor.cole_aqui"))}">${esc(rows.map((r) => r.text).join("\n"))}</textarea>
      <div class="row wrap le-actions">
        <button class="btn" data-le="sync">${icon("touch_app")} ${esc(tr("editor.sincronizar"))}</button>
        ${aiOk ? `<button class="btn outline" data-le="ai" title="${esc(tr("editor.ia_explica"))}">${icon("auto_awesome")} ${esc(tr("editor.salvar_ia"))}</button>` : ""}
        <button class="btn ghost sm" data-le="save">${esc(tr("editor.salvar_sem_tempo"))}</button>
      </div>`;
    const ta = $(".le-text", box);
    ta.addEventListener("input", () => (dirty = true));
    $("[data-le=sync]", box).onclick = () => {
      const lines = ta.value.split(/\r?\n/).map((l) => l.trim()).filter(Boolean);
      if (!lines.length) return toast(tr("editor.cole_primeiro"), { error: true });
      // guarda os tempos das linhas que nao mudaram
      rows = lines.map((text, i) => ({ text, t: rows[i] && rows[i].text === text ? rows[i].t : null }));
      cursor = Math.max(0, rows.findIndex((r) => r.t == null));
      if (rows.every((r) => r.t != null)) cursor = rows.length;
      renderSync();
      if (cursor === 0) {
        player.seek(0);
        player.play();
      }
    };
    $("[data-le=save]", box).onclick = () => save();
    const aiBtn = $("[data-le=ai]", box);
    if (aiBtn) aiBtn.onclick = () => save(true);
  }

  // ------------------------------------------------------ sincronizar
  function renderSync(scroll = false) {
    mode = "sync";
    const done = rows.filter((r) => r.t != null).length;
    $(".le-body", box).innerHTML = `
      <div class="le-hint">${icon("keyboard")} <span>${tr("editor.sync_explica")}</span></div>
      <div class="le-list">${rows.map((r, i) => `
        <button class="le-row${i === cursor ? " cur" : ""}${r.t == null ? " todo" : ""}" data-i="${i}">
          <span class="le-t">${r.t == null ? "–:––" : fmtTime(r.t) + "." + String(Math.floor((r.t % 1) * 10))}</span>
          <span class="le-txt${r.text === BREAK ? " brk" : ""}">${esc(r.text)}</span>
        </button>`).join("")}</div>
      <div class="le-progress small muted">${esc(tr("editor.progresso", { feitas: done, n: rows.length }))}</div>
      <div class="le-controls">
        <button class="btn outline sm" data-le="back" title="${esc(tr("editor.desfazer"))}">${icon("undo")}</button>
        <button class="btn le-mark" data-le="mark">${icon("touch_app")} ${esc(tr("editor.marcar"))} <span class="kbd">${esc(tr("editor.espaco"))}</span></button>
        <button class="btn outline sm" data-le="play" title="${esc(tr("editor.tocar_pausar"))}">${icon(player.playing() ? "pause" : "play_arrow")}</button>
      </div>
      <div class="row wrap le-actions">
        <button class="btn ghost sm" data-le="text">${icon("edit")} ${esc(tr("editor.editar_texto"))}</button>
        <span class="grow"></span>
        ${aiOk ? `<button class="btn outline sm" data-le="ai" title="${esc(tr("editor.ia_explica2"))}">${icon("auto_awesome")} ${esc(tr("editor.salvar_ia"))}</button>` : ""}
        <button class="btn sm" data-le="save">${icon("save")} ${esc(tr("comum.salvar"))}</button>
      </div>`;
    $$(".le-row", box).forEach((b) => (b.onclick = () => goTo(Number(b.dataset.i))));
    $("[data-le=mark]", box).onclick = mark;
    $("[data-le=back]", box).onclick = back;
    $("[data-le=play]", box).onclick = () => {
      if (player.playing()) player.pause();
      else player.play();
      renderSync();
    };
    $("[data-le=text]", box).onclick = renderText;
    $("[data-le=save]", box).onclick = () => save();
    const aiBtn = $("[data-le=ai]", box);
    if (aiBtn) aiBtn.onclick = () => save(true);
    const cur = $(".le-row.cur", box);
    if (cur && scroll) cur.scrollIntoView({ block: "center", behavior: "smooth" });
    else if (cur) cur.scrollIntoView({ block: "center" });
    // destaca a linha que esta tocando agora (pelos tempos ja marcados)
    cancelAnimationFrame(raf);
    const tick = () => {
      const t = player.time() - offset();
      let playingIdx = -1;
      rows.forEach((r, i) => {
        if (r.t != null && r.t <= t) playingIdx = i;
      });
      $$(".le-row", box).forEach((b, i) => b.classList.toggle("playing", i === playingIdx));
      raf = requestAnimationFrame(tick);
    };
    tick();
  }

  box.innerHTML = `
    <div class="drawer-head">
      <h3>${icon("edit_note")} ${esc(tr("editor.titulo", { nome: song.track || song.title }))}</h3>
      <button class="icon-btn plain" data-le="close" title="${esc(tr("comum.fechar"))}">${icon("close")}</button>
    </div>
    <div class="le-body"></div>`;
  $("[data-le=close]", box).onclick = () => close();
  box.onclick = (e) => e.stopPropagation();
  box.classList.add("open");
  box.setAttribute("aria-hidden", "false");
  window.addEventListener("keydown", onKey, true);
  if (mode === "sync") {
    cursor = rows.length;
    renderSync();
  } else renderText();
  return { close };
}
