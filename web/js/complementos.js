// Configuracoes -> Complementos: instalar pelo link, e um cartao por complemento (estado, acoes,
// opcoes desenhadas a partir do manifesto, atualizar, voltar, ligar/desligar e remover).
// So o PC do karaoke (o servidor recusa os outros).
import { $$, api, esc, icon, openModal, toast } from "./common.js";
import { t } from "./i18n.js";
import { appApi } from "./appwin.js";

/* icons: extension check_circle error warning pending toggle_on toggle_off */
// Os icones que os complementos podem usar no manifesto ("icone" e o das acoes): a fonte de icones
// do app so tem os que aparecem no codigo, entao a lista fica aqui (e em docs/COMPLEMENTOS.md).
/* icons: folder folder_open login logout tag music_note lyrics image album search library_music smart_display radio cloud_download download sync refresh settings link key person queue_music graphic_eq mic headphones public travel_explore podcasts */
const ESTADO_ICONE = { ligado: "check_circle", desligado: "pending", iniciando: "pending", com_problema: "error" };

function opcaoHtml(c, o) {
  const v = c.valores[o.id];
  const nome = `data-op="${esc(o.id)}"`;
  const ajuda = o.ajuda ? `<div class="small muted">${esc(o.ajuda)}</div>` : "";
  if (o.tipo === "sim_nao") {
    return `<label class="toggle-row small"><input type="checkbox" ${nome}${v ? " checked" : ""}> ${esc(o.rotulo)}</label>${ajuda}`;
  }
  let campo;
  if (o.tipo === "escolha") {
    campo = `<select class="input" ${nome}>${o.valores.map((x) => `<option value="${esc(x.id)}"${x.id === v ? " selected" : ""}>${esc(x.rotulo)}</option>`).join("")}</select>`;
  } else if (o.tipo === "segredo") {
    const definido = v && v.definido;
    campo = `<input class="input" type="password" ${nome} autocomplete="off" placeholder="${t(definido ? "complementos.segredo_definido" : "complementos.segredo_vazio")}">`;
  } else if (o.tipo === "pasta") {
    campo = `<div class="row" style="gap:6px"><input class="input grow" ${nome} value="${esc(v || "")}">
      <button class="btn outline sm" data-pasta="${esc(o.id)}">${icon("folder_open")}</button></div>`;
  } else {
    campo = `<input class="input" ${o.tipo === "numero" ? 'type="number"' : ""} ${nome} value="${esc(v ?? "")}">`;
  }
  return `<label><span class="label">${esc(o.rotulo)}</span>${campo}</label>${ajuda}`;
}

function cartaoHtml(c) {
  const oferece = c.oferece.map((o) => t(`complementos.oferece.${o}`)).join(" · ");
  const versao = c.sem_versao ? t("complementos.sem_versao", { commit: c.commit || "" }) : c.versao;
  return `
    <div class="comp-card" data-comp="${esc(c.id)}">
      <div class="comp-head">
        <span class="comp-icone ms">${esc(c.icone || "extension")}</span>
        <div class="grow" style="min-width:0">
          <b>${esc(c.nome)}</b> <span class="small muted">${esc(versao)}${c.autor ? ` · ${esc(c.autor)}` : ""}</span>
          <div class="small muted">${esc(oferece)}${c.celular ? ` · ${t("complementos.no_celular")}` : ""}</div>
        </div>
        <span class="badge ${c.estado === "ligado" ? "ok" : c.estado === "com_problema" ? "warn" : "gray"}">
          ${icon(ESTADO_ICONE[c.estado] || "pending", "sm")} ${t(`complementos.estado.${c.estado}`)}</span>
      </div>
      ${c.descricao ? `<p class="small" style="margin:8px 0 0">${esc(c.descricao)}</p>` : ""}
      ${c.info && c.info.texto ? `<p class="small comp-info ${esc(c.info.nivel || "ok")}">${esc(c.info.texto)}</p>` : ""}
      ${c.estado === "com_problema" ? `<p class="small" style="color:var(--danger)">${esc(c.motivo || "")}</p>
        ${c.log ? `<details><summary class="small">${t("complementos.ver_log")}</summary><pre class="upd-log">${esc(c.log)}</pre></details>` : ""}` : ""}
      ${c.acoes.length && c.estado === "ligado" ? `<div class="row wrap" style="gap:8px;margin-top:10px">${c.acoes.map((a) =>
        `<button class="btn outline sm" data-acao="${esc(a.id)}">${a.icone ? icon(a.icone) : ""} ${esc(a.rotulo)}</button>`).join("")}</div>` : ""}
      ${c.opcoes.length ? `
        <details class="comp-opcoes"><summary class="small">${t("complementos.opcoes")}</summary>
          <div class="form-grid">${c.opcoes.map((o) => opcaoHtml(c, o)).join("")}</div>
          <div class="row"><span class="grow"></span><button class="btn sm" data-salvar>${icon("check")} ${t("complementos.salvar")}</button></div>
        </details>` : ""}
      <div class="row wrap comp-botoes">
        ${c.atualizacao ? `<button class="btn sm" data-atualizar>${icon("system_update")} ${t("complementos.atualizar_para", { versao: c.atualizacao })}</button>`
          : `<button class="btn ghost sm" data-verificar>${icon("refresh")} ${t("complementos.verificar")}</button>`}
        ${c.anterior ? `<button class="btn ghost sm" data-voltar>${icon("history")} ${t("complementos.voltar", { versao: c.anterior })}</button>` : ""}
        <span class="grow"></span>
        <button class="btn outline sm" data-ligar="${c.ligado ? 0 : 1}">${icon(c.ligado ? "toggle_off" : "toggle_on")} ${t(c.ligado ? "complementos.desligar" : "complementos.ligar")}</button>
        <button class="btn danger sm" data-remover>${icon("delete")} ${t("complementos.remover")}</button>
      </div>
      ${c.repositorio ? `<a class="small muted" href="https://github.com/${esc(c.repositorio)}" target="_blank" rel="noopener">github.com/${esc(c.repositorio)}</a>` : ""}
    </div>`;
}

/** Acompanha uma tarefa (instalar/atualizar) ate terminar, mostrando o registro em `box`. */
async function acompanhar(tarefa, box) {
  for (;;) {
    const st = await api(`/api/complementos/tarefas/${tarefa.id}`).catch(() => null);
    if (!st) return false;
    box.innerHTML = `
      <p class="small">${st.estado === "rodando" ? `<span class="spinner"></span> ${t("complementos.instalando")}`
        : st.estado === "pronta" ? t("complementos.instalado") : `<span style="color:var(--danger)">${esc(st.erro || "")}</span>`}</p>
      <details${st.estado === "erro" ? " open" : ""}><summary class="small">${t("complementos.ver_log")}</summary>
        <pre class="upd-log">${esc((st.log || []).join("\n"))}</pre></details>`;
    if (st.estado !== "rodando") return st.estado === "pronta";
    await new Promise((r) => setTimeout(r, 1200));
  }
}

function remover(c, onDone) {
  const m = openModal(t("complementos.remover_titulo", { nome: c.nome }), `
    <p style="margin-top:0">${t("complementos.remover_texto")}</p>
    <label class="toggle-row small"><input type="checkbox" data-dados> ${t("complementos.apagar_dados")}</label>
    <div class="row" style="gap:10px;justify-content:flex-end;margin-top:14px">
      <button class="btn outline" data-no>${t("comum.cancelar")}</button>
      <button class="btn danger" data-yes>${icon("delete")} ${t("complementos.remover")}</button>
    </div>`);
  m.querySelector("[data-no]").onclick = () => m.close();
  m.querySelector("[data-yes]").onclick = async () => {
    const dados = m.querySelector("[data-dados]").checked ? 1 : 0;
    try {
      await api(`/api/complementos/${c.id}?apagar_dados=${dados}`, { method: "DELETE" });
      m.close();
      toast(t("complementos.removido"));
      onDone();
    } catch (err) {
      toast(err.message, { error: true });
    }
  };
}

/** A aba Complementos das Configuracoes. */
export function mountComplementos(box) {
  box.innerHTML = `
    <section class="set-section">
      <h4>${icon("add_link")} ${t("complementos.instalar_titulo")}</h4>
      <div class="row" style="gap:8px">
        <input class="input grow" data-link placeholder="https://github.com/…" autocomplete="off">
        <button class="btn sm" data-ver>${t("complementos.ver")}</button>
      </div>
      <div data-previa></div>
    </section>
    <section class="set-section">
      <h4>${icon("extension")} ${t("complementos.instalados")}</h4>
      <div data-lista><div class="empty"><span class="spinner"></span></div></div>
    </section>`;
  const lista = box.querySelector("[data-lista]");
  const previa = box.querySelector("[data-previa]");
  const link = box.querySelector("[data-link]");

  const render = async (dados) => {
    let r = dados;
    if (!r) {
      try {
        r = await api("/api/complementos");
      } catch (err) {
        lista.innerHTML = `<p class="small muted">${esc(err.message)}</p>`;
        return;
      }
    }
    const itens = r.complementos || [];
    lista.innerHTML = itens.length ? itens.map(cartaoHtml).join("") : `<p class="small muted" style="margin:0">${t("complementos.nenhum")}</p>`;
    for (const c of itens) ligarCartao(c, lista.querySelector(`[data-comp="${CSS.escape(c.id)}"]`));
    if (itens.some((c) => c.estado === "iniciando")) setTimeout(() => document.contains(lista) && render(), 1500);
  };

  const pedir = async (fn) => {
    try {
      const r = await fn();
      if (r && r.complementos) render(r);
      else render();
    } catch (err) {
      toast(err.message, { error: true });
      render();
    }
  };

  function ligarCartao(c, el) {
    const on = (sel, fn) => el.querySelector(sel) && (el.querySelector(sel).onclick = fn);
    on("[data-ligar]", (e) => {
      e.currentTarget.disabled = true;
      pedir(() => api(`/api/complementos/${c.id}/${e.currentTarget.dataset.ligar === "1" ? "ligar" : "desligar"}`, { method: "POST" }));
    });
    on("[data-remover]", () => remover(c, () => render()));
    on("[data-voltar]", () => pedir(() => api(`/api/complementos/${c.id}/voltar`, { method: "POST" })));
    on("[data-verificar]", async (e) => {
      e.currentTarget.disabled = true;
      try {
        const r = await api(`/api/complementos/${c.id}/verificar-atualizacao`, { method: "POST" });
        toast(r.atualizacao ? t("complementos.tem_versao", { versao: r.atualizacao }) : t("complementos.mais_nova"));
      } catch (err) {
        toast(err.message, { error: true });
      }
      render();
    });
    on("[data-atualizar]", async (e) => {
      e.currentTarget.disabled = true;
      try {
        const tarefa = await api(`/api/complementos/${c.id}/atualizar`, { method: "POST" });
        const area = document.createElement("div");
        el.append(area);
        await acompanhar(tarefa, area);
      } catch (err) {
        toast(err.message, { error: true });
      }
      render();
    });
    $$("[data-acao]", el).forEach((b) => (b.onclick = async () => {
      b.disabled = true;
      try {
        const r = await api(`/api/complementos/${c.id}/acoes/${b.dataset.acao}`, { method: "POST", body: {} });
        if (r.abrir_url) window.open(r.abrir_url, "_blank", "noopener");
        if (r.texto) toast(r.texto, { ms: 6000 });
      } catch (err) {
        toast(err.message, { error: true });
      }
      b.disabled = false;
      render();
    }));
    $$("[data-pasta]", el).forEach((b) => (b.onclick = async () => {
      const app = await appApi();
      const campo = el.querySelector(`[data-op="${CSS.escape(b.dataset.pasta)}"]`);
      if (!app) return campo.focus();
      const p = await app.choose_folder(campo.value || "");
      if (p) campo.value = p;
    }));
    on("[data-salvar]", () => {
      const valores = {};
      for (const o of c.opcoes) {
        const campo = el.querySelector(`[data-op="${CSS.escape(o.id)}"]`);
        if (!campo) continue;
        if (o.tipo === "sim_nao") valores[o.id] = campo.checked;
        else if (o.tipo === "segredo") {
          if (campo.value) valores[o.id] = campo.value;
        } else valores[o.id] = campo.value;
      }
      pedir(async () => {
        const r = await api(`/api/complementos/${c.id}/opcoes`, { method: "PUT", body: { valores } });
        toast(t("complementos.salvo"));
        return r;
      });
    });
  }

  box.querySelector("[data-ver]").onclick = async (e) => {
    const botao = e.currentTarget;
    botao.disabled = true;
    previa.innerHTML = `<p class="small"><span class="spinner"></span> ${t("complementos.lendo")}</p>`;
    try {
      const p = await api("/api/complementos/previa", { method: "POST", body: { link: link.value } });
      previa.innerHTML = `
        <div class="comp-card previa">
          <div class="comp-head"><span class="comp-icone ms">${esc(p.icone || "extension")}</span>
            <div class="grow"><b>${esc(p.nome)}</b> <span class="small muted">${esc(p.versao)}${p.autor ? ` · ${esc(p.autor)}` : ""}</span>
              <div class="small muted">${esc(p.oferece.map((o) => t(`complementos.oferece.${o}`)).join(" · "))}</div></div></div>
          ${p.descricao ? `<p class="small">${esc(p.descricao)}</p>` : ""}
          <p class="small"><a href="${esc(p.link)}" target="_blank" rel="noopener">${esc(p.link)}</a></p>
          <p class="small warn-text">${t("complementos.aviso")}</p>
          ${p.instalado ? `<p class="small muted">${t("complementos.ja_instalado", { versao: p.instalado })}</p>` : ""}
          <div class="row"><span class="grow"></span><button class="btn sm" data-instalar>${icon("download")} ${t("complementos.instalar")}</button></div>
          <div data-andamento></div>
        </div>`;
      previa.querySelector("[data-instalar]").onclick = async (ev) => {
        ev.currentTarget.disabled = true;
        try {
          const tarefa = await api("/api/complementos/instalar", { method: "POST", body: { link: link.value } });
          if (await acompanhar(tarefa, previa.querySelector("[data-andamento]"))) {
            link.value = "";
            setTimeout(() => (previa.innerHTML = ""), 2500);
          }
        } catch (err) {
          toast(err.message, { error: true });
        }
        render();
      };
    } catch (err) {
      previa.innerHTML = `<p class="small" style="color:var(--danger)">${esc(err.message)}</p>`;
    }
    botao.disabled = false;
  };
  link.addEventListener("keydown", (e) => e.key === "Enter" && box.querySelector("[data-ver]").click());
  render();
}
