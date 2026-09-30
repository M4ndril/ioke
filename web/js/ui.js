// Pedacos de interface usados em varias paginas (PC e celular).
import { api, esc, fmtTime, h, icon, perguntarOnde, readyIn, toast, togglePreview } from "./common.js";
import { idioma, t } from "./i18n.js";

/** Barra de navegacao: transparente no topo, solida ao rolar. */
export function bindNav(nav = document.querySelector(".nav")) {
  if (!nav) return;
  const update = () => nav.classList.toggle("solid", window.scrollY > 20);
  window.addEventListener("scroll", update, { passive: true });
  update();
}

/** Um resultado de uma fonte (complemento) no formato que a lista desenha. */
function daFonte(fonte, r) {
  return { fonte, ref: r.ref, info: r, title: r.titulo || r.ref, channel: r.artista || "", duration: r.duracao,
    thumb: r.capa_url || "", tem_trecho: !!r.tem_trecho, library: r.library };
}

/** Busca na fonte getFonte() (um complemento) e mostra os resultados com trecho e "Adicionar". */
export function setupSearch({ form, input, button, results, getName, onResults, sing = false, getFonte = () => "" }) {
  const label = button.innerHTML;
  form.addEventListener("submit", async (e) => {
    e.preventDefault();
    const q = input.value.trim();
    if (!q) return;
    button.disabled = true;
    button.innerHTML = '<span class="spinner"></span>';
    results.innerHTML = "";
    try {
      const fonte = getFonte();
      if (!fonte) return;
      const r = { results: (await api(`/api/fontes/${encodeURIComponent(fonte)}/buscar?q=${encodeURIComponent(q)}`)).resultados.map((x) => daFonte(fonte, x)) };
      if (!r.results.length) results.innerHTML = `<div class="empty">${esc(t("comum.nada"))}</div>`;
      for (const it of r.results) results.append(resultEl(it, getName, sing));
      onResults && onResults(r.results.length);
    } catch (err) {
      results.innerHTML = `<div class="empty">${esc(err.message)}</div>`;
    } finally {
      button.disabled = false;
      button.innerHTML = label;
    }
  });
}

function resultEl(it, getName, sing = false) {
  const lib = it.library;
  const ready = lib && lib.status === "ready";
  const badge = ready ? `<span class="badge ok">${icon("check", "sm")} ${esc(t("busca.na_biblioteca"))}</span>`
    : lib ? `<span class="badge gray">${esc(t("busca.sendo_preparada"))}</span>` : "";
  const actions = ready
    ? (sing ? `<button class="btn sm" data-sing-lib>${icon("mic")} ${esc(t("sing.cantar"))}</button>`
      : `<a class="btn sm" href="/player?id=${esc(lib.id)}">${icon("play_arrow", "fill")} ${esc(t("sing.cantar"))}</a>`)
    : `<button class="btn ${sing ? "ghost " : ""}sm" data-add>${icon("add")} ${esc(t(sing ? "busca.baixar" : "fila.adicionar"))}</button>
       ${sing ? `<button class="btn sm" data-sing>${icon("mic")} ${esc(t("busca.baixar_cantar"))}</button>` : ""}`;
  const el = h(`
    <div class="result fonte">
      <div class="thumb">
        ${it.thumb ? `<img src="${esc(it.thumb)}" alt="" loading="lazy">` : `<span class="job-art ms">music_note</span>`}
        ${it.duration ? `<span class="dur">${fmtTime(it.duration)}</span>` : ""}
      </div>
      <div class="grow">
        <div class="title">${esc(it.title)}</div>
        <div class="sub">${esc(it.channel)} ${badge}</div>
        <div class="actions">
          ${!it.tem_trecho ? "" : `<button class="btn ghost sm" data-prev data-stop>${icon("headphones")} ${esc(t("sing.ouvir_trecho"))}</button>`}
          ${actions}
        </div>
      </div>
    </div>`);
  const singLib = el.querySelector("[data-sing-lib]");
  if (singLib) {
    singLib.onclick = async () => {
      const name = getName ? getName() : "";
      if (!name) {
        document.dispatchEvent(new CustomEvent("karaoke:need-name")); // tela de entrar
        return;
      }
      singLib.disabled = true;
      try {
        await api("/api/party/add", { method: "POST", body: { song_id: lib.id, name } });
        singLib.innerHTML = `${icon("check")} ${esc(t("busca.na_fila"))}`;
        toast(t("busca.na_fila_cantar"));
        document.dispatchEvent(new CustomEvent("karaoke:refresh"));
      } catch (err) {
        singLib.disabled = false;
        toast(err.message, { error: true });
      }
    };
  }
  const prev = el.querySelector("[data-prev]");
  if (prev) {
    prev.onclick = (e) => togglePreview(e.currentTarget,
      `/api/fontes/${encodeURIComponent(it.fonte)}/trecho?ref=${encodeURIComponent(it.ref)}`, { start: 0 });
  }
  const origem = { fonte: it.fonte, ref: it.ref, info: it.info }; // o que vai para o servidor
  const singBtn = el.querySelector("[data-sing]");
  if (singBtn) {
    singBtn.onclick = async () => {
      const name = getName ? getName() : "";
      if (!name) {
        document.dispatchEvent(new CustomEvent("karaoke:need-name")); // tela de entrar
        return;
      }
      singBtn.disabled = true;
      try {
        await api("/api/party/add", { method: "POST", body: { ...origem, name } });
        singBtn.innerHTML = `${icon("check")} ${esc(t("busca.na_fila_para_cantar"))}`;
        toast(t("busca.baixando_entra"));
        document.dispatchEvent(new CustomEvent("karaoke:refresh"));
      } catch (err) {
        singBtn.disabled = false;
        toast(err.message, { error: true });
      }
    };
  }
  const add = el.querySelector("[data-add]");
  if (!add) return el;
  add.onclick = async () => {
    const onde = await perguntarOnde("musica");
    if (onde === null) return;
    add.disabled = true;
    try {
      const r = await api("/api/songs", { method: "POST", body: { ...origem, name: getName ? getName() : "", onde } });
      if (r.created) {
        add.innerHTML = `${icon("check")} ${esc(t("busca.na_fila"))}`;
        toast(t("busca.adicionada"));
      } else {
        add.innerHTML = `${icon("check")} ${esc(t(r.song.status === "ready" ? "busca.ja_biblioteca" : "busca.ja_fila"))}`;
      }
      document.dispatchEvent(new CustomEvent("karaoke:refresh"));
    } catch (err) {
      add.disabled = false;
      toast(err.message, { error: true });
    }
  };
  return el;
}

/** Item da fila de processamento. */
/* icons: cloud memory */
export function jobEl(job, { canDelete, canRetry, canCloud } = {}) {
  const pct = Math.round((job.progress || 0) * 100);
  const isErr = job.status === "error";
  const indeterminate = job.status === "queued" || job.status === "waiting" || job.status === "canceling";
  // na fila: quantas na frente e a previsao (a placa de video separa uma de cada vez)
  const q = job.queue;
  const when = q ? ` · ${readyIn(q.eta)}` : "";
  const nv = job.nuvem;
  const stage = isErr ? job.error
    : job.stalled ? job.stage // esperando espaco no disco
    : nv && (nv.espera || nv.falhou) ? job.stage // esperando a nuvem (conectar, aviso, teto) ou ela falhou
    : (job.status === "queued" || job.status === "waiting") && q
      ? `${t("busca.na_fila")} · ${q.ahead ? t("fila.na_frente", { n: q.ahead }) : t("fila.e_a_proxima")}${when}`
      : `${job.stage} · ${pct}%${when}`;
  const el = h(`
    <div class="song job" data-id="${job.id}">
      <div class="song-main">
        ${job.art_sm || job.cover || job.thumb ? `<img src="${esc(job.art_sm || job.cover || job.thumb)}" alt="" loading="lazy">`
          : `<span class="job-art ms">audio_file</span>`}
        <div class="info">
          <div class="title">${esc(job.track || job.title)}</div>
          <div class="meta">
            <span>${esc(job.artist || job.channel || "")}</span>
            ${job.origem && job.origem.tipo === "arquivo" ? `<span class="badge gray" title="${esc(job.origem.nome)}">${icon("audio_file", "sm")} ${esc(job.origem.nome)}</span>` : ""}
            ${job.origem && job.origem.tipo === "complemento" ? `<span class="badge gray">${icon("extension", "sm")} ${esc(job.origem.complemento)}</span>` : ""}
            ${job.added_by ? `<span class="badge gray">${esc(t("fila.por", { nome: job.added_by }))}</span>` : ""}
          </div>
          <div class="stage ${isErr || job.stalled || (nv && nv.falhou) ? "err" : ""}">${nv && nv.onde === "nuvem" && !isErr ? icon("cloud", "sm") + " " : ""}${esc(stage)}</div>
          ${isErr ? "" : `<div class="progress ${indeterminate ? "indeterminate" : ""}"><i style="width:${pct}%"></i></div>`}
        </div>
      </div>
      ${canCloud && nv && nv.alternativa ? `<button class="icon-btn" data-onde="${nv.alternativa}" title="${
        t(nv.alternativa === "nuvem" ? "nuvem.musica.na_nuvem" : "nuvem.musica.nesta_placa")}">${icon(nv.alternativa === "nuvem" ? "cloud" : "memory")}</button>` : ""}
      ${(isErr || (nv && nv.falhou)) && canRetry ? `<button class="icon-btn" data-retry title="${esc(t("player.tentar_de_novo"))}">${icon("refresh")}</button>` : ""}
      ${canDelete ? `<button class="icon-btn danger" data-del title="${esc(t(job.troca ? "fila.cancelar_manter" : "fila.cancelar_remover"))}">${icon("close")}</button>` : ""}
    </div>`);
  const del = el.querySelector("[data-del]");
  if (del) {
    del.onclick = async () => {
      del.disabled = true;
      try {
        await api(`/api/songs/${job.id}`, { method: "DELETE" });
        document.dispatchEvent(new CustomEvent("karaoke:refresh"));
      } catch (err) {
        del.disabled = false;
        toast(err.message, { error: true });
      }
    };
  }
  const onde = el.querySelector("[data-onde]");
  if (onde) {
    onde.onclick = async () => {
      onde.disabled = true;
      await api(`/api/nuvem/musica/${job.id}`, { method: "POST", body: { onde: onde.dataset.onde } })
        .catch((err) => toast(err.message, { error: true }));
      document.dispatchEvent(new CustomEvent("karaoke:refresh"));
    };
  }
  const retry = el.querySelector("[data-retry]");
  if (retry) {
    retry.onclick = async () => {
      await api(`/api/songs/${job.id}/retry`, { method: "POST" }).catch((err) => toast(err.message, { error: true }));
      document.dispatchEvent(new CustomEvent("karaoke:refresh"));
    };
  }
  return el;
}

/** Assinatura para so redesenhar quando algo mudou de verdade. */
export function signature(items, fields) {
  return items.map((i) => fields.map((f) => JSON.stringify(i[f] ?? "")).join(",")).join("|");
}

/** "hoje", "ontem", "há 3 dias"... (no idioma da pagina) */
export function timeAgo(ts) {
  if (!ts) return "";
  const days = Math.floor((Date.now() / 1000 - ts) / 86400);
  const fmt = new Intl.RelativeTimeFormat(idioma(), { numeric: "auto" });
  if (days < 30) return fmt.format(-Math.max(0, days), "day");
  return fmt.format(-Math.floor(days / 30), "month");
}
