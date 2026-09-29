// Configuracoes: player, musicas novas, nuvem, complementos, festa, contas, programa e atualizacoes.
import { $$, api, avatar, biblioteca, esc, gb, icon, openModal, store, toast } from "./common.js";
import { timeAgo } from "./ui.js";
import { idioma, t, t as tr } from "./i18n.js"; // tr: onde "t" ja e outra coisa (TABS.map((t) => ...))
import { mountNuvem } from "./nuvem.js";
import { mountComplementos } from "./complementos.js";
import { appApi } from "./appwin.js";
import { quitApp } from "./floating.js";
import { applyLook, loadGlobalLook, mountLookControls, saveGlobalLook } from "./look.js";

const ORDER = ["rapida", "equilibrada", "alta", "maxima"];

/** Texto curto da qualidade atual, ex.: "Equilibrada". */
export async function qualityLabel() {
  const s = await api("/api/settings");
  const p = s.quality.preset;
  return p === "personalizada" ? tr("qualidade.personalizada_curta") : s.presets[p].label;
}

// -------------------------------------------------- celular administrador
function mountAdmin(box) {
  const render = (url) => {
    box.innerHTML = `
      <div class="admin-qr">
        <img src="/api/admin/qr.svg?v=${Date.now()}" alt="${tr("admin.qr_alt")}">
        <div class="grow small">
          <p style="margin-top:0">${tr("admin.texto")}</p>
          <p class="muted">${tr("admin.cuidado")}</p>
          <div class="row wrap" style="gap:8px">
            <button class="btn outline sm" data-reset>${icon("autorenew")} ${tr("admin.trocar")}</button>
            <button class="btn ghost sm" data-copy>${icon("link")} ${tr("admin.copiar")}</button>
          </div>
        </div>
      </div>`;
    box.querySelector("[data-reset]").onclick = async () => {
      if (!confirm(tr("admin.trocar_confirmar"))) return;
      try {
        render((await api("/api/admin/reset", { method: "POST" })).url);
        toast(tr("admin.trocado"));
      } catch (err) {
        toast(err.message, { error: true });
      }
    };
    box.querySelector("[data-copy]").onclick = async () => {
      try {
        await navigator.clipboard.writeText(url);
        toast(tr("admin.copiado"));
      } catch {
        prompt(tr("admin.link"), url);
      }
    };
  };
  api("/api/admin")
    .then((r) => render(r.url))
    .catch((err) => (box.innerHTML = `<p class="small muted">${esc(err.message)}</p>`));
}

// ------------------------------------------------------------------ contas
/** Quem entrou pelo celular (nome + PIN). Esqueceu o PIN: o PC define um novo. */
function mountPeople(box) {
  const render = (list) => {
    if (!list.length) {
      box.innerHTML = `<p class="small muted" style="margin:0">${tr("contas.nenhuma")}</p>`;
      return;
    }
    box.innerHTML = list.map((a) => `
      <div class="people-row" data-id="${esc(a.id)}">
        ${avatar(a)}
        <div class="grow"><b>${esc(a.name)}</b>${a.admin ? ' <span class="badge gray">admin</span>' : ""}
          <div class="small muted">${a.seen_at ? tr("contas.visto", { quando: timeAgo(a.seen_at) }) : tr("contas.nunca")}</div></div>
        <button class="btn outline sm" data-pin>${icon("password")} ${tr("contas.redefinir")}</button>
      </div>`).join("");
    box.querySelectorAll("[data-pin]").forEach((b) => {
      const a = list.find((x) => x.id === b.closest("[data-id]").dataset.id);
      b.onclick = () => resetPin(a);
    });
  };
  const load = () => api("/api/accounts").then((r) => render(r.accounts))
    .catch((err) => (box.innerHTML = `<p class="small muted">${esc(err.message)}</p>`));

  function resetPin(a) {
    const modal = openModal(tr("contas.novo_pin", { nome: a.name }), `
      <p class="small muted" style="margin-top:0">${tr("contas.novo_pin_texto")}</p>
      <div class="row">
        <input class="input grow pin-new" data-pin inputmode="numeric" pattern="[0-9]*" maxlength="4" placeholder="• • • •" autocomplete="off">
        <button class="btn" data-save>${icon("check")} ${tr("comum.salvar")}</button>
      </div>`);
    const input = modal.querySelector("[data-pin]");
    setTimeout(() => input.focus(), 50);
    input.oninput = () => (input.value = input.value.replace(/\D/g, "").slice(0, 4));
    const save = async () => {
      if (!/^\d{4}$/.test(input.value)) return toast(tr("contas.pin_4"), { error: true });
      try {
        await api(`/api/account/${a.id}/pin`, { method: "POST", body: { pin: input.value } });
        toast(tr("contas.pin_redefinido", { nome: a.name }), { ms: 5000 });
        modal.close();
      } catch (err) {
        toast(err.message, { error: true });
      }
    };
    modal.querySelector("[data-save]").onclick = save;
    input.addEventListener("keydown", (e) => e.key === "Enter" && save());
  }
  load();
}

// ------------------------------------------------------------ palco na TV
function mountStage(box) {
  const render = (st) => {
    if (!st.browser) {
      box.innerHTML = `<p class="small" style="color:var(--danger)">${tr("erro.precisa_navegador")}</p>`;
      return;
    }
    const mons = st.monitors || [];
    const current = mons.some((m) => m.id === st.monitor) ? st.monitor : (mons.find((m) => m.primary) || {}).id;
    box.innerHTML = `
      <div class="row wrap" style="gap:12px;align-items:center">
        <div class="seg" data-mode>
          <button data-v="fullscreen" class="${st.mode === "fullscreen" ? "on" : ""}">${tr("palco.tela_cheia")}</button>
          <button data-v="kiosk" class="${st.mode === "kiosk" ? "on" : ""}">${tr("palco.quiosque")}</button>
        </div>
        <select class="input compact grow" data-mon>${mons.map((m) =>
          `<option value="${esc(m.id)}"${m.id === current ? " selected" : ""}>${esc(m.label)}</option>`).join("")}</select>
        <button class="btn ghost sm" data-refresh title="${tr("palco.monitores")}">${icon("refresh")}</button>
      </div>
      <p class="small muted">${st.mode === "kiosk" ? tr("palco.quiosque_dica") : tr("palco.tela_cheia_dica")}</p>
      <div class="row wrap" style="gap:8px">
        <button class="btn sm" data-open>${icon("cast")} ${st.open ? tr("palco.reabrir") : tr("palco.abrir")}</button>
        ${st.open ? `<button class="btn outline sm" data-close-stage>${icon("close")} ${tr("palco.fechar")}</button>` : ""}
        <span class="small muted">${st.open ? tr("palco.aberto") : ""}</span>
        <span class="grow"></span>
        <a class="small muted" style="text-decoration:underline" href="/palco" title="${tr("palco.nesta_aba_dica")}">${tr("palco.nesta_aba")}</a>
      </div>`;
    const save = async (body) => render(await api("/api/stage", { method: "PUT", body }).catch((err) => (toast(err.message, { error: true }), st)));
    $$("[data-mode] button", box).forEach((b) => (b.onclick = () => save({ mode: b.dataset.v })));
    box.querySelector("[data-mon]").onchange = (e) => save({ monitor: e.target.value });
    box.querySelector("[data-refresh]").onclick = load;
    box.querySelector("[data-open]").onclick = async (e) => {
      e.currentTarget.disabled = true;
      try {
        const r = await api("/api/stage/open", { method: "POST" });
        toast(r.monitor_missing ? tr("palco.tela_sumiu", { tela: r.opened_on }) : tr("palco.aberto_em", { tela: r.opened_on || tr("palco.tela_cheia") }), { error: r.monitor_missing });
        render(r);
      } catch (err) {
        toast(err.message, { error: true });
        load();
      }
    };
    const closeBtn = box.querySelector("[data-close-stage]");
    if (closeBtn) closeBtn.onclick = async () => render(await api("/api/stage/close", { method: "POST" }).catch(() => st));
  };
  async function load() {
    try {
      render(await api("/api/stage"));
    } catch (err) {
      box.innerHTML = `<p class="small muted">${esc(err.message)}</p>`;
    }
  }
  load();
}

// ------------------------------------------- o programa: janela e atualizacoes
/* icons: fullscreen system_update restore power_settings_new */
/** Aba Programa (janela, pasta dos dados, fechar) e aba Atualizacoes (versoes). */
function mountApp(progBox, updBox, setBadge) {
  let timer = null;
  const fmtDate = (iso) => (iso ? new Date(iso).toLocaleDateString(idioma(), { day: "2-digit", month: "short", year: "numeric" }) : "");
  const boxes = [progBox, updBox];
  const render = async (st) => {
    const app = await appApi();
    if (!document.contains(progBox)) return;
    setBadge(!!st.update_available);
    const winHtml = app ? `
      <div class="reprocess" style="margin-top:0">
        <div><b>${tr("programa.janela")}</b><div class="small muted">${tr("programa.janela_texto")}</div></div>
        <div class="seg" data-win><button data-v="1">${tr("palco.tela_cheia")}</button><button data-v="0">${tr("programa.janela")}</button></div>
      </div>` : "";
    const d = st.data;
    const found = (info) => [
      tr("comum.musicas", { n: info.songs }),
      info.database ? tr("programa.contas_historico") : "",
      info.models ? tr("programa.modelos") : "",
    ].filter(Boolean).join(" · ");
    const dataHtml = d ? `
      <div class="reprocess">
        <div style="min-width:0"><b>${tr("programa.pasta_dados")}</b>
          <div class="small muted" style="word-break:break-all">${esc(d.path)}</div>
          <div class="small muted">${esc(found(d))}</div></div>
        ${app ? `<button class="btn outline sm" data-folder>${icon("folder_open")} ${tr("programa.trocar_pasta")}</button>` : ""}
      </div>` : "";
    const quitHtml = app ? `
      <div class="reprocess">
        <div><b>${tr("programa.fechar")}</b><div class="small muted">${tr("programa.fechar_texto")}</div></div>
        <button class="btn outline sm" data-quit>${icon("power_settings_new")} ${tr("comum.fechar")}</button>
      </div>` : "";
    const perfis = [["leve", "config.perfil.leve"], ["cpu", "config.perfil.cpu"], ["nvidia", "config.perfil.nvidia"]];
    const perfilHtml = st.app && st.perfil ? `
      <div class="reprocess">
        <div><b>${tr("config.perfil.titulo")}</b><div class="small muted">${tr("config.perfil.texto")}</div></div>
        <select class="input compact" data-perfil${st.job && st.job.state === "running" ? " disabled" : ""}>
          ${perfis.map(([v, k]) => `<option value="${v}"${st.perfil === v ? " selected" : ""}${v === "nvidia" && st.nvidia === false ? " disabled" : ""}>${tr(k)}</option>`).join("")}
        </select>
      </div>` : "";
    progBox.innerHTML = winHtml + dataHtml + perfilHtml + quitHtml ||
      `<p class="small muted" style="margin:0">${tr("programa.navegador")}</p>`;
    if (!st.app) {
      updBox.innerHTML = `<p class="small muted" style="margin:0">${tr("atualizacoes.dev", { versao: esc(st.version) })}</p>`;
    } else {
      const job = st.job;
      const failed = st.state && st.state.falhou;
      const list = (st.available || []).map((v) => {
        const action = v.current ? `<span class="badge">${tr("atualizacoes.em_uso")}</span>`
          : `<button class="btn ${v.newer ? "" : "outline "}sm" data-install="${esc(v.version)}" data-newer="${v.newer ? 1 : ""}"${job && job.state === "running" ? " disabled" : ""}>
              ${v.newer ? tr("atualizacoes.atualizar") : tr("atualizacoes.voltar")}</button>`;
        return `
          <div class="upd-item${v.current ? " on" : ""}">
            <div class="upd-head"><b>${esc(v.version)}</b>${v.prerelease ? ` <span class="badge" title="${tr("atualizacoes.pre_dica")}">${tr("atualizacoes.pre")}</span>` : ""}
              <span class="small muted">${fmtDate(v.date)}${v.installed && !v.current ? ` · ${tr("atualizacoes.guardada")}` : ""}</span>
              <span class="grow"></span>${action}</div>
            ${(v.notes || []).length ? `<ul class="upd-notes">${v.notes.slice(0, 8).map((n) => `<li>${esc(n)}</li>`).join("")}</ul>` : ""}
          </div>`;
      }).join("");
      const jobHtml = !job ? "" : job.state === "running"
        ? `<div class="upd-job"><span class="spinner"></span> ${job.perfil ? tr("config.perfil.preparando", { perfil: tr(`config.perfil.${job.perfil}`) }) : tr("atualizacoes.preparando", { versao: esc(job.version) })} ${tr("atualizacoes.continuar_usando")}
             <pre class="upd-log">${esc((job.log || []).slice(-6).join("\n"))}</pre></div>`
        : job.state === "ready"
          ? `<div class="upd-job ok">${tr("atualizacoes.pronta", { versao: esc(job.version) })} <button class="btn sm" data-restart>${icon("restart_alt")} ${tr("atualizacoes.reiniciar")}</button>
               <span class="small muted">${tr("atualizacoes.reiniciar_dica")}</span></div>`
          : `<div class="upd-job err">${tr("atualizacoes.falhou", { versao: esc(job.version), erro: esc(job.error || "") })}</div>`;
      updBox.innerHTML = `
        ${failed ? `<div class="upd-job err">${tr("atualizacoes.voltou", { versao: esc(failed.versao), atual: esc(st.version) })}
          <details><summary class="small">${tr("atualizacoes.motivo")}</summary><pre class="upd-log">${esc(failed.motivo || "")}</pre></details>
          <button class="btn ghost sm" data-dismiss>${tr("comum.ok")}</button></div>` : ""}
        <div class="row wrap" style="gap:10px;align-items:center;margin-bottom:10px">
          <div><b>${tr("atualizacoes.versao", { versao: esc(st.version) })}</b><div class="small muted">${st.update_available ? tr("atualizacoes.disponivel", { versao: esc(st.latest) }) : st.checked_at ? tr("atualizacoes.mais_nova") : ""}
            ${st.check_error ? `<span style="color:var(--danger)">${esc(st.check_error)}</span>` : ""}</div></div>
          <span class="grow"></span>
          <button class="btn outline sm" data-check${st.checking ? " disabled" : ""}>${st.checking ? '<span class="spinner"></span>' : icon("system_update")} ${tr("atualizacoes.procurar")}</button>
        </div>
        ${jobHtml}
        <div class="upd-list">${list}</div>
        <div class="row wrap" style="gap:8px;align-items:center;margin:10px 0 0">
          <span class="small">${tr("atualizacoes.canal")}</span>
          <select class="input sm" data-channel style="width:auto">
            <option value="estavel"${(st.channel || {}).canal !== "testes" ? " selected" : ""}>${tr("atualizacoes.estavel")}</option>
            <option value="testes"${(st.channel || {}).canal === "testes" ? " selected" : ""}>${tr("atualizacoes.testes")}</option>
          </select>
        </div>
        <p class="small muted" style="margin:8px 0 0">${tr("atualizacoes.explica")}</p>`;
    }
    if (app) {
      const info = await app.info();
      $$("[data-win] button", progBox).forEach((b) => {
        b.classList.toggle("on", (b.dataset.v === "1") === !!info.fullscreen);
        b.onclick = async () => {
          await app.set_fullscreen(b.dataset.v === "1");
          render(st);
        };
      });
    }
    const on = (sel, fn) => boxes.forEach((box) => box.querySelector(sel) && (box.querySelector(sel).onclick = fn));
    on("[data-folder]", () => changeDataFolder(app, st.data));
    const perfilSel = progBox.querySelector("[data-perfil]");
    if (perfilSel) {
      perfilSel.onchange = async () => {
        const v = perfilSel.value;
        if (!confirm(tr("config.perfil.confirmar", { perfil: tr(`config.perfil.${v}`) }))) {
          perfilSel.value = st.perfil;
          return;
        }
        try {
          render(await api("/api/app/perfil", { method: "POST", body: { perfil: v } }));
          poll();
        } catch (err) {
          perfilSel.value = st.perfil;
          toast(err.message, { error: true });
        }
      };
    }
    on("[data-quit]", () => quitApp(app));
    on("[data-check]", async () => render(await api("/api/app/check", { method: "POST" })).then(poll));
    on("[data-dismiss]", async () => render(await api("/api/app/dismiss", { method: "POST" })));
    on("[data-restart]", async () => {
      try {
        await api("/api/app/restart", { method: "POST", body: {} });
      } catch (err) {
        if (!(err.data && err.data.busy) || !confirm(tr("config.reiniciar_cantando"))) return toast(err.message, { error: true });
        await api("/api/app/restart", { method: "POST", body: { force: true } });
      }
      toast(tr("programa.reiniciando"), { ms: 10000 });
    });
    const channelSel = updBox.querySelector("[data-channel]");
    if (channelSel) {
      channelSel.onchange = async () => {
        try {
          render(await api("/api/app/channel", { method: "PUT", body: { canal: channelSel.value } }));
          poll();
        } catch (err) {
          toast(err.message, { error: true });
        }
      };
    }
    $$("[data-install]", updBox).forEach((b) => (b.onclick = async () => {
      const v = b.dataset.install;
      if (!b.dataset.newer && !confirm(tr("atualizacoes.voltar_confirmar", { versao: v }))) return;
      try {
        render(await api("/api/app/install", { method: "POST", body: { version: v } }));
        poll();
      } catch (err) {
        toast(err.message, { error: true });
      }
    }));
  };
  // enquanto procura ou prepara, atualiza a tela a cada 1,5 s
  async function poll() {
    clearTimeout(timer);
    if (!document.contains(progBox)) return;
    const st = await api("/api/app").catch(() => null);
    if (!st) return;
    await render(st);
    if (st.checking || (st.job && st.job.state === "running")) timer = setTimeout(poll, 1500);
  }
  api("/api/app").then(async (st) => {
    await render(st);
    if (st.app && !st.checked_at && !st.checking) {
      // ainda nao procurou nesta abertura: procura agora
      await api("/api/app/check", { method: "POST" }).catch(() => {});
      poll();
    }
  }).catch((err) => (progBox.innerHTML = `<p class="small muted">${esc(err.message)}</p>`));
}

/** Aba Player: o visual padrao das musicas, com uma previa ao vivo. */
async function mountLook(box) {
  let info;
  try {
    await loadGlobalLook(); // na primeira vez traz o que ficava so no navegador
    info = await api("/api/player-look");
  } catch (err) {
    box.innerHTML = `<p class="small muted">${esc(err.message)}</p>`;
    return;
  }
  let look = info.look;
  let cover = "";
  try {
    const withCover = (await biblioteca()).songs.filter((x) => x.cover || x.thumb);
    const pick = withCover[Math.floor(Math.random() * withCover.length)];
    cover = pick ? pick.cover || pick.thumb : "";
  } catch {
    /* sem musicas: a previa fica com o fundo escuro */
  }
  box.innerHTML = `
    <div class="look-tab">
      <div>
        <section class="lk-section"><h4>${tr("visual.fundo")}</h4><div data-g="fundo"></div></section>
        <section class="lk-section"><h4>${tr("visual.letra")}</h4><div data-g="letra"></div></section>
        <section class="lk-section"><h4>${tr("visual.borda")}</h4><div data-g="borda"></div></section>
      </div>
      <div class="look-side">
        <div class="look-preview" data-preview>
          <div class="pv-bg"${cover ? ` style="background-image:url('${esc(cover)}')"` : ""}></div>
          <div class="pv-shade"></div><div class="pv-tint"></div>
          <div class="pv-lines">
            <div class="pv-line">${tr("visual.previa1")}</div>
            <div class="pv-line cur"><span class="pv-sung">${tr("visual.previa2a")} </span>${tr("visual.previa2b")}</div>
            <div class="pv-line">${tr("visual.previa3")}</div>
          </div>
        </div>
        <div class="look-actions"><span data-saved></span><span class="grow"></span>
          <button class="btn ghost sm" data-reset>${icon("restart_alt")} ${tr("visual.original")}</button></div>
        <p class="small muted" style="margin:0">${tr("visual.explica")}</p>
      </div>
    </div>`;
  const preview = box.querySelector("[data-preview]");
  const saved = box.querySelector("[data-saved]");
  let pending = {};
  let timer = null;
  const paint = () => {
    applyLook(preview, look);
    controls.forEach((c) => c.update(look));
  };
  const save = () => {
    clearTimeout(timer);
    timer = setTimeout(async () => {
      const patch = pending;
      pending = {};
      try {
        await saveGlobalLook(patch);
        saved.textContent = tr("comum.salvo");
        setTimeout(() => (saved.textContent = ""), 1500);
      } catch (err) {
        toast(err.message, { error: true });
      }
    }, 300);
  };
  const onChange = (k, v) => {
    look = { ...look, [k]: v };
    pending[k] = v;
    paint();
    save();
  };
  const controls = ["fundo", "letra", "borda"].map((g) => mountLookControls(box.querySelector(`[data-g="${g}"]`), [g], onChange));
  box.querySelector("[data-reset]").onclick = () => {
    if (!confirm(tr("visual.original_confirmar"))) return;
    look = { ...info.defaults };
    pending = { ...info.defaults };
    paint();
    save();
  };
  paint();
}

/* icons: folder_open */
/** Trocar a pasta dos dados: escolhe no Windows, mostra o que tem la e reinicia. Nada e movido nem apagado. */
async function changeDataFolder(app, current) {
  const path = await app.choose_folder(current ? current.path : "");
  if (!path) return;
  let info;
  try {
    info = await api("/api/app/data-folder/check", { method: "POST", body: { path } });
  } catch (err) {
    return toast(err.message, { error: true });
  }
  if (current && info.path === current.path) return toast(tr("programa.ja_e_a_pasta"));
  const empty = !info.songs && !info.database;
  const modal = openModal(tr("programa.usar_pasta"), `
    <p style="margin-top:0;word-break:break-all"><b>${esc(info.path)}</b></p>
    ${empty
      ? `<p class="small">${tr("programa.pasta_vazia")}</p>`
      : `<p class="small">${tr("programa.encontrei", { lista: [tr("comum.musicas", { n: info.songs }), info.database && tr("programa.contas_historico"), info.config && tr("programa.configuracoes"), info.models && tr("programa.modelos")].filter(Boolean).join(", ") })}</p>`}
    <p class="small muted">${tr("programa.nada_movido")}</p>
    <div class="row" style="gap:10px;justify-content:flex-end">
      <button class="btn outline" data-no>${tr("comum.cancelar")}</button>
      <button class="btn light" data-yes data-nav-default>${icon("folder_open")} ${tr("programa.usar_reiniciar")}</button>
    </div>`);
  $$("[data-no]", modal)[0].onclick = () => modal.close();
  $$("[data-yes]", modal)[0].onclick = async () => {
    const send = (force) => api("/api/app/data-folder", { method: "POST", body: { path: info.path, force } });
    try {
      await send(false);
    } catch (err) {
      if (!(err.data && err.data.busy) || !confirm(tr("config.reiniciar_cantando"))) {
        return toast(err.message, { error: true });
      }
      await send(true);
    }
    modal.close();
    toast(tr("programa.reiniciando_pasta"), { ms: 10000 });
  };
}

// ------------------------------------------------------------ o modal
/* icons: tune library_music cloud extension movie celebration manage_accounts desktop_windows system_update */
const TABS = [
  { id: "player", icon: "tune", label: "abas.player" },
  { id: "musicas", icon: "library_music", label: "abas.musicas" },
  { id: "nuvem", icon: "cloud", label: "nuvem.aba" },
  { id: "complementos", icon: "extension", label: "complementos.aba" },
  { id: "festa", icon: "celebration", label: "abas.festa" },
  { id: "contas", icon: "manage_accounts", label: "abas.contas" },
  { id: "programa", icon: "desktop_windows", label: "abas.programa" },
  { id: "atualizacoes", icon: "system_update", label: "abas.atualizacoes" },
];

/** Abre as Configuracoes (na aba `tab`, ou na ultima usada). */
export async function openSettings({ onChange, tab } = {}) {
  let s;
  try {
    s = await api("/api/settings");
  } catch (err) {
    toast(err.message, { error: true });
    return;
  }
  const q = s.quality;
  const option = (map, selected) =>
    Object.entries(map).map(([k, v]) => `<option value="${esc(k)}"${k === selected ? " selected" : ""}>${esc(v)}</option>`).join("");
  const cards = ORDER.map((id) => {
    const p = s.presets[id];
    return `
      <button class="q-card${q.preset === id ? " on" : ""}" data-preset="${id}">
        <div class="q-head">${esc(p.label)} ${id === "equilibrada" ? `<span class="rec">${tr("qualidade.recomendada")}</span>` : ""}<span class="speed">${esc(p.speed)}</span></div>
        <p>${esc(p.description)}</p>
        <p class="small">overlap ${p.overlap} · ${p.fp16 ? "FP16" : tr("qualidade.precisao_total")}</p>
      </button>`;
  }).join("");
  const gpu = s.device.device === "cuda";
  const pane = (id, title, lead, body) => `
    <section class="set-pane" data-pane="${id}" role="tabpanel" hidden>
      <h3 class="pane-title">${title}</h3>
      ${lead ? `<p class="pane-lead">${lead}</p>` : ""}
      ${body}
    </section>`;
  const panes = {
    player: pane("player", tr("abas.player"), tr("visual.lead"),
      `<div data-look><div class="empty"><span class="spinner"></span></div></div>`),
    musicas: pane("musicas", tr("abas.musicas"), tr("musicas.lead"), `
      <section class="set-section">
        <h4>${icon("graphic_eq")} ${tr("qualidade.titulo")}</h4>
        <p class="muted small" style="margin-top:0">${tr("qualidade.texto", { icone: icon("edit", "sm") })}</p>
        ${gpu ? "" : s.device.device === "nuvem" ? `<p class="small muted" style="margin:0 0 12px">${tr("nuvem.qualidade_leve")}</p>`
          : `<p class="badge warn" style="margin:0 0 12px">${tr("qualidade.sem_gpu")}</p>`}
        <div class="quality-grid">${cards}</div>
        <details class="advanced"${q.preset === "personalizada" ? " open" : ""}>
          <summary>${tr(q.preset === "personalizada" ? "qualidade.personalizada_em_uso" : "qualidade.personalizada")}</summary>
          <div class="form-grid">
            <label><span class="label">${tr("qualidade.modelo_voz")}</span><select class="input" data-f="vocals">${option(s.vocal_models, q.vocals)}</select></label>
            <label><span class="label">${tr("qualidade.modelo_apoio")}</span><select class="input" data-f="backing">${option(s.backing_models, q.backing)}</select></label>
            <label><span class="label">${tr("qualidade.overlap", { n: `<b data-ov>${q.overlap}</b>` })}</span>
              <input type="range" min="1" max="16" step="1" data-f="overlap" value="${q.overlap}" style="width:100%"></label>
            <label class="toggle-row"><input type="checkbox" data-f="fp16"${q.fp16 ? " checked" : ""}> ${tr("qualidade.fp16")}</label>
          </div>
          <p class="small muted">${tr("qualidade.modelos_baixados")}</p>
          <div class="row"><span class="grow"></span><button class="btn sm" data-custom>${icon("check")} ${tr("qualidade.usar_personalizada")}</button></div>
        </details>
      </section>
      <section class="set-section">
        <h4>${icon("movie")} ${tr("config.video.titulo")}</h4>
        <label class="toggle-row small"><input type="checkbox" data-video${s.download_video ? " checked" : ""}>
          ${tr("config.video.texto")}</label>
        <div class="reprocess" style="margin-top:10px">
          <div><b>${tr("config.video.altura")}</b><div class="small muted">${tr("config.video.altura_texto")}</div></div>
          <select class="input compact" data-video-altura>
            ${[480, 720, 1080].map((a) => `<option value="${a}"${s.video_max_height === a ? " selected" : ""}>${a}p</option>`).join("")}
          </select>
        </div>
      </section>
      <section class="set-section">
        <h4>${icon("auto_awesome")} ${tr("ia_config.titulo")}</h4>
        <p class="muted small" style="margin-top:0">${tr("ia_config.texto")}</p>
        <label class="toggle-row small" style="margin-bottom:10px"><input type="checkbox" data-ai-auto${s.ai_lyrics_auto ? " checked" : ""}>
          ${tr("ia_config.auto")}</label>
        <div class="row wrap">
          <button class="btn sm" data-ai-all>${icon("auto_awesome")} ${tr("ia_config.todas")}</button>
        </div>
      </section>`),
    nuvem: pane("nuvem", tr("nuvem.aba"), tr("nuvem.lead"), `<div data-nuvem><div class="empty"><span class="spinner"></span></div></div>`),
    complementos: pane("complementos", tr("complementos.aba"), tr("complementos.lead"), `<div data-complementos></div>`),
    festa: pane("festa", tr("abas.festa"), "", `
      <section class="set-section">
        <h4>${icon("tv")} ${tr("festa.palco")}</h4>
        <p class="muted small" style="margin-top:0">${tr("festa.palco_texto")}</p>
        <div data-stage><div class="empty"><span class="spinner"></span></div></div>
      </section>
      <section class="set-section">
        <h4>${icon("queue_music")} ${tr("festa.fila")}</h4>
        <label class="toggle-row small">${tr("festa.limite")}
          <select class="input sm-select" data-limit>
            ${[0, 1, 2, 3, 4, 5].map((n) => `<option value="${n}"${n === s.party_limit ? " selected" : ""}>${n ? n : tr("festa.sem_limite")}</option>`).join("")}
          </select></label>
        <p class="muted small" style="margin:6px 0 0">${tr("festa.limite_texto")}</p>
      </section>`),
    contas: pane("contas", tr("abas.contas"), "", `
      <section class="set-section">
        <h4>${icon("group")} ${tr("contas_config.titulo")}</h4>
        <p class="muted small" style="margin-top:0">${tr("contas_config.texto")}</p>
        <div data-people><div class="empty"><span class="spinner"></span></div></div>
      </section>
      <section class="set-section">
        <h4>${icon("admin_panel_settings")} ${tr("contas_config.admin")}</h4>
        <div data-admin></div>
      </section>`),
    programa: pane("programa", tr("abas.programa"), "", `
      <div data-app-prog><div class="empty"><span class="spinner"></span></div></div>
      <div class="reprocess">
        <div><b>${t("config.idioma.titulo")}</b><div class="small muted">${t("config.idioma.texto")}</div></div>
        <select class="input compact" data-idioma>
          ${["auto", "pt-BR", "en"].map((v) => `<option value="${v}"${(s.idioma || "auto") === v ? " selected" : ""}>${
            t({ auto: "config.idioma.auto", "pt-BR": "config.idioma.pt", en: "config.idioma.en" }[v])}</option>`).join("")}
        </select>
      </div>
      <section class="set-section">
        <h4>${icon("inventory_2")} ${tr("pacotes.titulo")}</h4>
        <p class="muted small" style="margin-top:0">${tr("pacotes.texto")}</p>
        <div class="reprocess" style="margin-top:0">
          <div><b>${tr("pacotes.formato")}</b><div class="small muted">${tr("pacotes.formato_texto")}</div></div>
          <select class="input compact" data-pacote-formato>
            ${["flac", "mp3", "opus"].map((f) =>
              `<option value="${f}"${(s.pacote_formato || "flac") === f ? " selected" : ""}>${tr(`pacotes.${f}`)}</option>`).join("")}
          </select>
        </div>
        <div class="row wrap" style="gap:8px">
          <button class="btn outline sm" data-exportar-todas>${icon("download")} ${tr("pacotes.exportar_todas")}</button>
        </div>
      </section>
      <section class="set-section">
        <h4>${icon("hard_drive")} ${tr("disco.titulo")}</h4>
        ${s.disk ? `<p class="small" style="margin-top:0">${tr("disco.ocupa", { tamanho: `<b>${gb(s.disk.library)}</b>`,
          musicas: tr("comum.musicas", { n: s.disk.songs }), cada: Math.round(s.disk.library / Math.max(1, s.disk.songs) / 1024 ** 2),
          livres: `<b class="${s.disk.low ? "warn-text" : ""}">${tr("disco.livres", { tamanho: gb(s.disk.free) })}</b>` })}</p>
        <p class="muted small" style="margin:0">${tr("disco.minimo", { tamanho: gb(s.disk.min) })}</p>` : ""}
      </section>`),
    atualizacoes: pane("atualizacoes", tr("abas.atualizacoes"), "", `<div data-app-upd><div class="empty"><span class="spinner"></span></div></div>`),
  };
  const tabs = TABS.map((t) => `
    <button class="set-tab" role="tab" data-tab="${t.id}">${icon(t.icon)}<span>${t.label.includes(".") ? tr(t.label) : t.label}</span><i class="tab-dot hidden"></i></button>`).join("");
  const modal = openModal(tr("config.titulo"), `
    <div class="set-layout">
      <nav class="set-tabs" role="tablist">${tabs}</nav>
      <div class="set-panes">${TABS.map((t) => panes[t.id]).join("")}</div>
    </div>`);
  modal.querySelector(".modal").classList.add("settings-modal");
  modal.addEventListener("closed", () => document.dispatchEvent(new CustomEvent("karaoke:settings-closed")));
  const showTab = (id) => {
    if (!panes[id]) id = TABS[0].id;
    $$(".set-tab", modal).forEach((b) => b.classList.toggle("on", b.dataset.tab === id));
    $$(".set-pane", modal).forEach((p) => (p.hidden = p.dataset.pane !== id));
    modal.querySelector(".set-panes").scrollTop = 0;
    store("karaoke.settingsTab", id);
  };
  $$(".set-tab", modal).forEach((b) => (b.onclick = () => showTab(b.dataset.tab)));
  showTab(tab || store("karaoke.settingsTab") || TABS[0].id);

  const mark = () => {
    $$(".q-card", modal).forEach((c) => c.classList.toggle("on", c.dataset.preset === s.quality.preset));
    modal.querySelector(".advanced summary").textContent =
      tr(s.quality.preset === "personalizada" ? "qualidade.personalizada_em_uso" : "qualidade.personalizada");
  };
  const save = async (body, message) => {
    if (!s.is_host) return toast(tr("config.so_pc"), { error: true });
    try {
      s = await api("/api/settings", { method: "PUT", body });
      mark();
      toast(message);
      onChange && onChange(s);
    } catch (err) {
      toast(err.message, { error: true });
    }
  };
  $$(".q-card", modal).forEach((c) => {
    c.onclick = () => save({ quality: { preset: c.dataset.preset } }, tr("qualidade.escolhida", { nome: s.presets[c.dataset.preset].label }));
  });
  const field = (f) => modal.querySelector(`[data-f="${f}"]`);
  field("overlap").addEventListener("input", () => (modal.querySelector("[data-ov]").textContent = field("overlap").value));
  modal.querySelector("[data-custom]").onclick = () =>
    save({
      quality: {
        preset: "personalizada",
        overlap: Number(field("overlap").value),
        fp16: field("fp16").checked,
        vocals: field("vocals").value,
        backing: field("backing").value,
      },
    }, tr("qualidade.personalizada_salva"));
  modal.querySelector("[data-limit]").onchange = (e) => {
    const n = Number(e.target.value);
    save({ party_limit: n }, n ? tr("festa.limite_salvo", { n }) : tr("festa.sem_limite_salvo"));
  };
  modal.querySelector("[data-ai-auto]").onchange = (e) =>
    save({ ai_lyrics_auto: e.target.checked }, e.target.checked ? tr("ia_config.auto_ligada") : tr("ia_config.auto_desligada"));
  modal.querySelector("[data-ai-all]").onclick = async (e) => {
    if (!confirm(tr("ia_config.todas_confirmar"))) return;
    e.currentTarget.disabled = true;
    try {
      const r = await api("/api/library/align-all", { method: "POST" });
      toast(tr("ia_config.na_fila", { n: r.count }));
    } catch (err) {
      e.currentTarget.disabled = false;
      toast(err.message, { error: true });
    }
  };
  mountStage(modal.querySelector("[data-stage]"));
  modal.querySelector("[data-idioma]").onchange = async (e) => {
    try {
      await api("/api/settings", { method: "PUT", body: { idioma: e.target.value } });
      toast(t("config.idioma.mudou"));
      setTimeout(() => location.reload(), 600);
    } catch (err) {
      toast(err.message, { error: true });
    }
  };
  modal.querySelector("[data-pacote-formato]").onchange = (e) =>
    save({ pacote_formato: e.target.value }, tr("pacotes.formato_salvo"));
  modal.querySelector("[data-exportar-todas]").onclick = async () => {
    const bib = await biblioteca().catch(() => null);
    const ids = ((bib && bib.songs) || []).map((x) => x.id);
    if (!ids.length) return toast(tr("pacotes.nenhuma"));
    if (!confirm(tr("pacotes.exportar_todas_confirmar", { n: ids.length }))) return;
    import("./pacotes.js").then((m) => m.exportarPacotes(ids));
  };
  mountApp(modal.querySelector("[data-app-prog]"), modal.querySelector("[data-app-upd]"), (on) =>
    modal.querySelector('[data-tab="atualizacoes"] .tab-dot').classList.toggle("hidden", !on));
  mountLook(modal.querySelector("[data-look]"));
  mountNuvem(modal.querySelector("[data-nuvem]"));
  mountComplementos(modal.querySelector("[data-complementos]"));
  mountAdmin(modal.querySelector("[data-admin]"));
  mountPeople(modal.querySelector("[data-people]"));
  modal.querySelector("[data-video]").onchange = (e) =>
    save({ download_video: e.target.checked }, e.target.checked ? tr("config.video.ligado") : tr("config.video.desligado"));
  modal.querySelector("[data-video-altura]").onchange = (e) =>
    save({ video_max_height: Number(e.target.value) }, tr("config.video.altura_salva"));
}

// nome antigo, usado em outras paginas
export const openQualitySettings = openSettings;
