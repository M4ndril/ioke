// Nuvem (Configuracoes -> Nuvem): conectar a conta Modal, o aviso de custos, gastos, teto,
// placa e onde separar. So o PC do karaoke (o servidor recusa os outros).
import { $$, api, esc, icon, openModal, toast } from "./common.js";
import { t } from "./i18n.js";

const MODAL_URL = "https://modal.com/signup";
const dinheiro = (v) => (v == null ? "—" : `US$ ${Number(v).toFixed(v < 1 ? 3 : 2)}`);

function minutosAtras(ts) {
  if (!ts) return "";
  const min = Math.max(0, Math.round((Date.now() / 1000 - ts) / 60));
  return min < 1 ? t("nuvem.agora") : t("nuvem.ha_min", { n: min });
}

/** O tutorial "Como configurar a conta" (web/tutorial-nuvem.html), numa janela grande. */
export function abrirTutorial() {
  const m = openModal(t("nuvem.tutorial.titulo"), `<iframe class="tutorial-frame" src="/tutorial-nuvem.html"></iframe>`);
  m.querySelector(".modal").classList.add("tutorial-modal");
}

/** O aviso da primeira vez (e do fim do "Conectar"): so fecha pelos botoes. true = aceitou. */
export function avisoCustos(teto = 25) {
  return new Promise((resolve) => {
    const m = openModal(t("nuvem.aviso.titulo"), `
      <p style="margin-top:0">${t("nuvem.aviso.custo")}</p>
      <p>${t("nuvem.aviso.cartao")}</p>
      <p>${t("nuvem.aviso.orcamento")} <a href="#" data-tut>${t("nuvem.tutorial.link")}</a></p>
      <p>${t("nuvem.aviso.teto", { teto: Number(teto).toFixed(0) })}</p>
      <label class="toggle-row small" style="margin:14px 0"><input type="checkbox" data-ok> ${t("nuvem.aviso.configurei")}</label>
      <div class="row" style="gap:10px;justify-content:flex-end">
        <button class="btn outline" data-no>${t("comum.cancelar")}</button>
        <button class="btn light" data-yes disabled>${icon("cloud")} ${t("nuvem.aviso.aceitar")}</button>
      </div>`, { fixo: true });
    const yes = m.querySelector("[data-yes]");
    m.querySelector("[data-ok]").onchange = (e) => (yes.disabled = !e.target.checked);
    m.querySelector("[data-tut]").onclick = (e) => {
      e.preventDefault();
      abrirTutorial();
    };
    m.querySelector("[data-no]").onclick = () => {
      m.close();
      resolve(false);
    };
    yes.onclick = async () => {
      try {
        await api("/api/nuvem", { method: "PUT", body: { aceitou_custos: true } });
        m.close();
        resolve(true);
      } catch (err) {
        toast(err.message, { error: true });
      }
    };
  });
}

/** Conectar pelo navegador: tres passos, abre a pagina do Modal e espera a autorizacao. */
function conectar(onDone) {
  let timer = null;
  const m = openModal(t("nuvem.conectar.titulo"), `
    <ol class="nuvem-passos">
      <li>${t("nuvem.conectar.passo1")}</li>
      <li>${t("nuvem.conectar.passo2")} <a href="#" data-tut>${t("nuvem.tutorial.link")}</a></li>
      <li>${t("nuvem.conectar.passo3")}</li>
    </ol>
    <div data-estado></div>
    <div class="row wrap" style="gap:10px;justify-content:flex-end;margin-top:14px">
      <a href="#" class="small" data-manual style="margin-right:auto">${t("nuvem.chave.link")}</a>
      <a class="btn outline" href="${MODAL_URL}" target="_blank" rel="noopener">${icon("open_in_new")} ${t("nuvem.conectar.criar")}</a>
      <button class="btn light" data-go>${icon("login")} ${t("nuvem.conectar.autorizar")}</button>
    </div>`);
  const estado = m.querySelector("[data-estado]");
  const fim = () => clearTimeout(timer);
  m.addEventListener("closed", () => {
    fim();
    api("/api/nuvem/conectar", { method: "DELETE" }).catch(() => {});
  });
  m.querySelector("[data-tut]").onclick = (e) => {
    e.preventDefault();
    abrirTutorial();
  };
  m.querySelector("[data-manual]").onclick = (e) => {
    e.preventDefault();
    m.close();
    chaveManual(onDone);
  };
  const acompanhar = async () => {
    const r = await api("/api/nuvem/conectar").catch(() => null);
    if (!r || !document.contains(estado)) return;
    if (r.estado === "pronto") {
      fim();
      m.close();
      toast(t("nuvem.conectada_como", { conta: r.conta || "Modal" }));
      await avisoCustos();
      return onDone();
    }
    if (r.estado === "erro") {
      estado.innerHTML = `<p class="small" style="color:var(--danger)">${esc(r.erro || "")}</p>`;
      return;
    }
    timer = setTimeout(acompanhar, 2000);
  };
  m.querySelector("[data-go]").onclick = async (e) => {
    e.currentTarget.disabled = true;
    estado.innerHTML = `<p class="small"><span class="spinner"></span> ${t("nuvem.conectar.abrindo")}</p>`;
    try {
      const r = await api("/api/nuvem/conectar", { method: "POST" });
      window.open(r.url, "_blank", "noopener");
      estado.innerHTML = `<p class="small"><span class="spinner"></span> ${t("nuvem.conectar.esperando")}
        ${r.codigo ? `<br>${t("nuvem.conectar.codigo")} <b class="nuvem-codigo">${esc(r.codigo)}</b>` : ""}
        <br><a href="${esc(r.url)}" target="_blank" rel="noopener">${t("nuvem.conectar.abrir_de_novo")}</a></p>`;
      acompanhar();
    } catch (err) {
      e.currentTarget.disabled = false;
      estado.innerHTML = `<p class="small" style="color:var(--danger)">${esc(err.message)}</p>`;
    }
  };
}

/** Plano B: colar a chave criada em modal.com -> Settings -> API Tokens. */
function chaveManual(onDone) {
  const m = openModal(t("nuvem.chave.titulo"), `
    <p class="small" style="margin-top:0">${t("nuvem.chave.texto")}</p>
    <label><span class="label">token-id</span><input class="input" data-id placeholder="ak-..." autocomplete="off"></label>
    <label><span class="label">token-secret</span><input class="input" data-secret type="password" placeholder="as-..." autocomplete="off"></label>
    <div class="row" style="gap:10px;justify-content:flex-end;margin-top:14px">
      <button class="btn outline" data-no>${t("comum.cancelar")}</button>
      <button class="btn light" data-yes>${icon("key")} ${t("nuvem.chave.salvar")}</button>
    </div>`);
  m.querySelector("[data-no]").onclick = () => m.close();
  m.querySelector("[data-yes]").onclick = async (e) => {
    e.currentTarget.disabled = true;
    try {
      await api("/api/nuvem/chave", { method: "POST", body: {
        token_id: m.querySelector("[data-id]").value, token_secret: m.querySelector("[data-secret]").value } });
      m.close();
      await avisoCustos();
      onDone();
    } catch (err) {
      e.currentTarget.disabled = false;
      toast(err.message, { error: true });
    }
  };
}

function desconectar(onDone) {
  const m = openModal(t("nuvem.desconectar.titulo"), `
    <p style="margin-top:0">${t("nuvem.desconectar.texto")}</p>
    <label class="toggle-row small"><input type="checkbox" data-remover checked> ${t("nuvem.desconectar.remover")}</label>
    <div class="row" style="gap:10px;justify-content:flex-end;margin-top:14px">
      <button class="btn outline" data-no>${t("comum.cancelar")}</button>
      <button class="btn danger" data-yes>${icon("logout")} ${t("nuvem.desconectar.botao")}</button>
    </div>`);
  m.querySelector("[data-no]").onclick = () => m.close();
  m.querySelector("[data-yes]").onclick = async (e) => {
    e.currentTarget.disabled = true;
    const remover = m.querySelector("[data-remover]").checked;
    try {
      await api(`/api/nuvem${remover ? "?remover_da_conta=1" : ""}`, { method: "DELETE" });
      m.close();
      toast(t("nuvem.desconectada"));
      onDone();
    } catch (err) {
      e.currentTarget.disabled = false;
      toast(err.message, { error: true });
    }
  };
}

function gastosHtml(g, teto) {
  if (!g) return "";
  const lido = g.lido_em ? t("nuvem.gastos.real", { quando: minutosAtras(g.lido_em) }) : t("nuvem.gastos.estimativa");
  return `
    <div class="nuvem-gastos">
      <div><span class="small muted">${t("nuvem.gastos.mes")}</span><b>${dinheiro(g.mes)}</b><span class="small muted">${lido}</span></div>
      <div><span class="small muted">${t("nuvem.gastos.media")}</span><b>${dinheiro(g.media_musica)}</b><span class="small muted">${t("nuvem.gastos.estimativa")}</span></div>
      <div><span class="small muted">${t("nuvem.gastos.cabem", { teto: Number(teto).toFixed(0) })}</span><b>${g.cabem == null ? "—" : `~${g.cabem}`}</b></div>
    </div>
    ${g.erro ? `<p class="small warn-text">${t("nuvem.gastos.erro")}</p>` : ""}
    <p class="small muted" style="margin:6px 0 0">${t("nuvem.gastos.nota")} <a href="${esc(g.precos.link)}" target="_blank" rel="noopener">${t("nuvem.gastos.precos", { data: g.precos.data })}</a></p>`;
}

/** A aba Nuvem das Configuracoes. */
export function mountNuvem(box) {
  let timer = null;
  const render = async () => {
    clearTimeout(timer);
    if (!document.contains(box)) return;
    let st;
    try {
      st = await api("/api/nuvem");
    } catch (err) {
      box.innerHTML = `<p class="small muted">${esc(err.message)}</p>`;
      return;
    }
    const c = st.conta;
    const leve = st.perfil === "leve";
    const inst = st.instalacao || {};
    const instalando = inst.estado === "instalando";
    if (!st.modal) {
      box.innerHTML = `<p class="small muted">${t("nuvem.sem_modal")}</p>`;
      return;
    }
    const estado = !c.conectada ? t("nuvem.estado.desconectada")
      : instalando ? `<span class="spinner"></span> ${t("nuvem.estado.instalando")} <span class="small muted">(${t(`nuvem.instalar.${inst.etapa || "publicar"}`)})</span>`
        : st.instalado ? t("nuvem.estado.pronta", { conta: esc(c.conta || "Modal") })
          : t("nuvem.estado.conectada", { conta: esc(c.conta || "Modal") });
    const placa = st.gpus.map((g) => `
      <button data-gpu="${g.gpu}" class="${c.gpu === g.gpu ? "on" : ""}" title="${t(`nuvem.gpu.${g.gpu}`)}">${g.gpu}</button>`).join("");
    const onde = ["auto", "local", "nuvem"].map((v) => `
      <option value="${v}"${st.separar_onde === v ? " selected" : ""}${leve && v !== "nuvem" ? " disabled" : ""}>${t(`nuvem.onde.${v}`)}</option>`).join("");
    box.innerHTML = `
      <section class="set-section">
        <h4>${icon("cloud")} ${t("nuvem.conta")}</h4>
        <p class="muted small" style="margin-top:0">${t(leve ? "nuvem.intro_leve" : "nuvem.intro")}</p>
        <div class="reprocess" style="margin-top:0">
          <div><b>${estado}</b>${c.conectada && c.sem_protecao ? `<div class="small warn-text">${t("nuvem.sem_protecao")}</div>` : ""}
            ${inst.estado === "erro" ? `<div class="small" style="color:var(--danger)">${esc(inst.erro || "")}</div>` : ""}</div>
          ${c.conectada
            ? `<button class="btn outline sm" data-reinstalar${instalando ? " disabled" : ""}>${icon("cloud_upload")} ${t(st.instalado ? "nuvem.reinstalar" : "nuvem.instalar")}</button>
               <button class="btn danger sm" data-desconectar>${icon("logout")} ${t("nuvem.desconectar.botao")}</button>`
            : `<button class="btn sm" data-conectar>${icon("login")} ${t("nuvem.conectar.botao")}</button>`}
        </div>
        <div class="row wrap" style="gap:14px;margin-top:8px">
          <a href="#" class="small" data-tut>${icon("help", "sm")} ${t("nuvem.tutorial.titulo")}</a>
          ${c.conectada ? "" : `<a href="#" class="small" data-manual>${icon("key", "sm")} ${t("nuvem.chave.link")}</a>`}
          ${c.conectada && !c.aceitou_custos_em ? `<a href="#" class="small" data-aviso>${icon("info", "sm")} ${t("nuvem.aviso.ver")}</a>` : ""}
        </div>
      </section>
      ${c.conectada ? `
      <section class="set-section">
        <h4>${icon("savings")} ${t("nuvem.gastos.titulo")}</h4>
        ${gastosHtml(st.gastos, c.teto_usd)}
        <div class="row wrap" style="gap:10px;align-items:center;margin-top:12px">
          <button class="btn outline sm" data-gastos>${icon("refresh")} ${t("nuvem.gastos.atualizar")}</button>
        </div>
        <div class="reprocess">
          <div><b>${t("nuvem.teto.titulo")}</b><div class="small muted">${t("nuvem.teto.texto")}</div></div>
          <div class="row" style="gap:6px;align-items:center;flex:none">US$ <input class="input sm" data-teto type="number" min="1" max="1000" step="1" value="${c.teto_usd}" style="width:90px">
            <button class="btn outline sm" data-teto-salvar>${icon("check")}</button></div>
        </div>
      </section>
      <section class="set-section">
        <h4>${icon("memory")} ${t("nuvem.placa.titulo")}</h4>
        <div class="seg" data-placa>${placa}</div>
        <p class="small muted" style="margin:8px 0 0">${t(`nuvem.gpu.${c.gpu}`)} · ${dinheiro((st.gpus.find((g) => g.gpu === c.gpu) || {}).por_minuto)} ${t("nuvem.por_minuto")}</p>
      </section>` : ""}
      <section class="set-section">
        <h4>${icon("call_split")} ${t("nuvem.onde.titulo")}</h4>
        <select class="input compact" data-onde${leve ? " disabled" : ""}>${onde}</select>
        <p class="small muted" style="margin:8px 0 0">${t(leve ? "nuvem.onde.leve" : "nuvem.onde.texto")}</p>
      </section>`;
    const on = (sel, fn) => box.querySelector(sel) && (box.querySelector(sel).onclick = fn);
    const put = async (body, msg) => {
      try {
        await api("/api/nuvem", { method: "PUT", body });
        if (msg) toast(msg);
        render();
      } catch (err) {
        toast(err.message, { error: true });
      }
    };
    on("[data-conectar]", () => conectar(render));
    on("[data-manual]", (e) => {
      e.preventDefault();
      chaveManual(render);
    });
    on("[data-tut]", (e) => {
      e.preventDefault();
      abrirTutorial();
    });
    on("[data-aviso]", async (e) => {
      e.preventDefault();
      if (await avisoCustos(c.teto_usd)) render();
    });
    on("[data-desconectar]", () => desconectar(render));
    on("[data-reinstalar]", async () => {
      try {
        await api("/api/nuvem/instalar", { method: "POST", body: { de_novo: st.instalado } });
        render();
      } catch (err) {
        toast(err.message, { error: true });
      }
    });
    on("[data-gastos]", async (e) => {
      e.currentTarget.disabled = true;
      await api("/api/nuvem/gastos/atualizar", { method: "POST" }).catch((err) => toast(err.message, { error: true }));
      render();
    });
    on("[data-teto-salvar]", () => put({ teto_usd: box.querySelector("[data-teto]").value }, t("nuvem.teto.salvo")));
    $$("[data-gpu]", box).forEach((b) => (b.onclick = () => put({ gpu: b.dataset.gpu })));
    const ondeSel = box.querySelector("[data-onde]");
    if (ondeSel) {
      ondeSel.onchange = async () => {
        if (ondeSel.value !== "local" && c.conectada && !c.aceitou_custos_em && !(await avisoCustos(c.teto_usd))) {
          ondeSel.value = st.separar_onde;
          return;
        }
        put({ separar_onde: ondeSel.value }, t("nuvem.onde.salvo"));
      };
    }
    if (instalando) timer = setTimeout(render, 3000);
  };
  render();
}
