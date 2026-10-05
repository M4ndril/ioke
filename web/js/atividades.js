// Central de atividades (so nas telas do PC: inicio, Adicionar e Cantar): uma pilula no canto com o que esta
// rodando em segundo plano (musicas sendo preparadas ou separadas, letra por IA, refazer voz/apoio, videos,
// acoes de complemento) e uma gaveta com os detalhes. Nao aparece no player, no palco nem no celular: nada
// que distraia quem esta cantando.
import { api, esc, h, icon } from "./common.js";
import { jobEl, signature } from "./ui.js";
import { t } from "./i18n.js";

/* icons: auto_awesome record_voice_over movie extension pending pending_actions error library_add close album */
const ICONES = { letra: "auto_awesome", voz_apoio: "record_voice_over", video: "movie", acao: "extension", importacao: "library_add" };
const comErro = (a) => a.estado === "error" || a.estado === "erro";

/** Poe a pilula no comeco de `box` (os botoes flutuantes) e cria a gaveta. */
export function mountAtividades(box) {
  try {
    if (sessionStorage.getItem("karaoke.tv") === "1") return; // a janela do palco nunca mostra
  } catch {
    /* sem armazenamento: segue */
  }
  const pill = h('<button class="ativ-pill hidden"></button>');
  box.prepend(pill);
  const drawer = h(`
    <aside class="drawer" id="ativDrawer" aria-hidden="true">
      <div class="drawer-head">
        <h3>${icon("pending_actions")} ${esc(t("atividades.titulo"))}</h3>
        <button class="icon-btn plain" data-close title="${esc(t("comum.fechar"))}">${icon("close")}</button>
      </div>
      <div class="drawer-list" data-list></div>
    </aside>`);
  document.body.append(drawer);

  let aberto = false;
  let timer = null;
  let dados = { jobs: [], outras: [] };
  let assinatura = "";

  function set(on) {
    aberto = on;
    drawer.classList.toggle("open", on);
    drawer.setAttribute("aria-hidden", String(!on));
    if (on) {
      assinatura = "";
      render();
      refresh();
    }
  }
  pill.onclick = (e) => {
    e.stopPropagation();
    set(!aberto);
  };
  drawer.querySelector("[data-close]").onclick = () => set(false);
  drawer.addEventListener("click", (e) => e.stopPropagation());
  document.addEventListener("click", () => aberto && set(false));
  document.addEventListener("keydown", (e) => {
    if (e.key === "Escape" && aberto && !document.querySelector(".modal-backdrop")) set(false);
  });
  document.addEventListener("karaoke:refresh", () => refresh()); // cancelou, tentou de novo...

  function outraEl(a) {
    const pct = Math.round((a.progresso || 0) * 100);
    const erro = comErro(a);
    const fila = a.estado === "queued";
    const texto = erro ? a.erro || ""
      : [t(`atividades.${a.tipo}`), a.etapa, fila ? "" : `${pct}%`].filter(Boolean).join(" · ");
    const el = h(`
      <div class="song job ativ">
        <div class="song-main">
          <span class="job-art ms">${ICONES[a.tipo] || "pending"}</span>
          <div class="info">
            <div class="title">${esc(a.titulo)}</div>
            <div class="meta"><span>${esc(a.artista || "")}</span></div>
            <div class="stage ${erro ? "err" : ""}">${esc(texto)}</div>
            ${erro && a.detalhes ? `<details class="small muted"><summary>${esc(t("atividades.detalhes"))}</summary>${a.detalhes.map((d) => `<div>${esc(d)}</div>`).join("")}</details>` : ""}
            ${erro ? "" : `<div class="progress ${fila ? "indeterminate" : ""}"><i style="width:${pct}%"></i></div>`}
          </div>
          ${a.cancelar ? `<button class="icon-btn plain sm" data-cancelar title="${esc(t(erro ? "atividades.dispensar" : "comum.cancelar"))}">${icon("close")}</button>` : ""}
        </div>
      </div>`);
    const cancelar = el.querySelector("[data-cancelar]");
    if (cancelar) cancelar.onclick = async () => {
      cancelar.disabled = true;
      try {
        await api(a.cancelar, { method: "DELETE" });
      } catch {
        /* a proxima atualizacao mostra como ficou */
      }
      refresh();
    };
    return el;
  }

  function render() {
    const { jobs, outras } = dados;
    const total = jobs.length + outras.length;
    const erros = jobs.filter((j) => j.status === "error").length + outras.filter(comErro).length;
    const rodando = total - erros;
    pill.classList.toggle("hidden", !total);
    pill.classList.toggle("err", !rodando && erros > 0);
    pill.title = t("atividades.titulo");
    pill.innerHTML = rodando
      ? `<span class="spinner"></span> ${esc(t("atividades.rodando", { n: rodando }))}${erros ? ` <span class="ativ-err">${icon("error", "sm")}${erros}</span>` : ""}`
      : `${icon("error")} ${esc(t("atividades.erros", { n: erros }))}`;
    if (!aberto) return;
    const sig = signature(jobs, ["id", "status", "stage", "progress", "error", "queue"]) + "#" + JSON.stringify(outras);
    if (sig === assinatura) return;
    assinatura = sig;
    const list = drawer.querySelector("[data-list]");
    list.innerHTML = total ? "" : `<div class="empty small">${esc(t("atividades.nada"))}</div>`;
    for (const j of jobs) list.append(jobEl(j, { canDelete: true, canRetry: true, canCloud: true }));
    for (const a of outras) list.append(outraEl(a));
  }

  // CD no leitor: um aviso (uma vez por disco) com o atalho para importar. No Adicionar, o cartao ja mostra.
  const avisados = new Set();
  try {
    JSON.parse(sessionStorage.getItem("karaoke.discos") || "[]").forEach((id) => avisados.add(id));
  } catch {
    /* sem armazenamento: avisa de novo em cada pagina */
  }
  async function olharDisco() {
    let r;
    try {
      r = await api("/api/disco", { timeout: 8000 });
    } catch {
      return setTimeout(olharDisco, 60000);
    }
    if (!r.leitores.length) return setTimeout(olharDisco, 60000); // sem leitor de CD
    const d = (r.leitores.find((l) => l.disco) || {}).disco;
    const pronto = d && !["novo", "identificando"].includes(d.estado);
    if (pronto && !avisados.has(d.id) && location.pathname !== "/adicionar") {
      avisados.add(d.id);
      try {
        sessionStorage.setItem("karaoke.discos", JSON.stringify([...avisados]));
      } catch {
        /* sem armazenamento */
      }
      const e = d.escolhida;
      const aviso = h(`
        <div class="disco-aviso">
          ${e && e.capa ? `<img src="${esc(e.capa)}" alt="">` : `<span class="ms">album</span>`}
          <div class="grow"><b>${esc(t("disco.aviso"))}</b><div class="small muted">${esc(e || d.palpite ? `${(e || d.palpite).titulo} · ${(e || d.palpite).artista}` : t("comum.musicas", { n: d.faixas }))}</div></div>
          <a class="btn light sm" href="/adicionar#disco">${esc(t("disco.importar"))}</a>
          <button class="icon-btn plain sm" title="${esc(t("comum.fechar"))}">${icon("close")}</button>
        </div>`);
      aviso.querySelector("button").onclick = () => aviso.remove();
      document.body.append(aviso);
      setTimeout(() => aviso.remove(), 30000);
    }
    setTimeout(olharDisco, 5000);
  }
  olharDisco();

  async function refresh() {
    clearTimeout(timer);
    try {
      dados = await api("/api/atividades", { timeout: 8000 });
      render();
    } catch {
      /* servidor reiniciando (ou outro computador: sem a central) */
    }
    const total = dados.jobs.length + dados.outras.length;
    timer = setTimeout(refresh, aberto ? 2000 : total ? 4000 : 10000);
  }
  refresh();
}
