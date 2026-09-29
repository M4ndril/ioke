// Pagina do celular: entrar na fila para cantar, controlar a musica quando e a
// sua vez, ver a fila e buscar musicas novas nas fontes dos complementos.
import {
  $, $$, adminToken, aosPoucos, api, authHeaders, avatar, biblioteca, dobrar, esc, fmtTime, h, icon, openModal,
  storageOk, store, toast,
} from "./common.js";
import { bindTomSteppers, etaText, rankingRows, renderQueue, showNotices, tomStepper } from "./partyui.js";
import { jobEl, setupSearch, signature } from "./ui.js";
import { escolherIdiomaCelular, idioma, initI18n, t } from "./i18n.js";

await initI18n({ celular: true }); // os textos antes de desenhar a pagina

// ------------------------------------------------ celular administrador
// O QR code das Configuracoes do PC abre /m?admin=CODIGO: o codigo fica guardado
// aqui e vai em toda chamada. Este celular pode tudo o que o PC pode (menos a
// nuvem e os complementos) e ganha a aba "Controle" (controle remoto da TV).
{
  const params = new URLSearchParams(location.search);
  if (params.get("admin")) {
    store("karaoke.admin", params.get("admin"));
    history.replaceState(null, "", "/m");
  }
}
let isAdmin = false;
async function checkAdmin() {
  try {
    isAdmin = !!(await api("/api/info")).is_admin; // pelo codigo do QR ou pela conta administradora
  } catch {
    return;
  }
  if (adminToken() && !isAdmin) {
    store("karaoke.admin", "");
    toast(t("celular.nao_admin"), { error: true, ms: 6000 });
  }
  $("#adminBadge").classList.toggle("hidden", !isAdmin);
  $("#remoteTab").classList.toggle("hidden", !isAdmin);
  if (isAdmin) mountRemote();
}

// ------------------------------------------------------------------ conta
// Nome + PIN, guardados no PC do karaoke: a pessoa volta a ser ela mesma em
// qualquer aba, aparelho ou endereco (o navegador pode esquecer o login).
let account = null;
const getName = () => (account && account.name) || "";

function applyAccount(a) {
  account = a;
  $("#acctAvatar").outerHTML = avatar(a).replace('class="avatar ', 'id="acctAvatar" class="avatar ');
  $("#acctName").textContent = a.name;
}

async function uploadPhoto(file) {
  const form = new FormData();
  form.append("photo", file);
  const res = await fetch("/api/account/photo", { method: "POST", headers: authHeaders(), body: form });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(data.error || `erro ${res.status}`);
  return data.account;
}

/** Tela de entrar: nome -> "crie um PIN" (nome novo) ou "digite o PIN" (ja tem conta). */
function showLogin(prefill = "") {
  const box = $("#welcome");
  const form = $("#loginForm");
  const name = $("#loginName");
  const pin = $("#loginPin");
  const go = $("#loginGo");
  const hint = $("#loginHint");
  const photoBtn = $("#loginPhoto");
  const photoFile = $("#loginPhotoFile");
  let step = "name";
  let photo = null;

  const setStep = (next) => {
    step = next;
    const isPin = step !== "name";
    const first = name.value.trim().split(/\s+/)[0];
    $("#loginTitle").textContent = step === "login" ? t("celular.oi", { nome: first }) : step === "create" ? t("celular.crie_pin") : t("celular.bem_vindo");
    $("#loginText").textContent = step === "login" ? t("celular.digite_pin")
      : step === "create" ? t("celular.crie_pin_texto")
        : t("celular.como_aparecer");
    name.readOnly = isPin;
    pin.classList.toggle("hidden", !isPin);
    pin.value = "";
    pin.autocomplete = step === "create" ? "new-password" : "current-password";
    photoBtn.classList.toggle("hidden", step !== "create");
    $("#loginBack").classList.toggle("hidden", !isPin);
    $("#loginBack").textContent = step === "login" ? t("celular.nao_e_voce") : t("celular.trocar_nome");
    $("#loginForgot").classList.toggle("hidden", step !== "login");
    go.textContent = step === "login" ? t("celular.entrar") : step === "create" ? t("celular.criar_conta") : t("celular.continuar");
    hint.textContent = "";
    setTimeout(() => (isPin ? pin : name).focus(), 100);
  };

  const done = (a, token) => {
    store("karaoke.session", token);
    applyAccount(a);
    box.classList.add("hidden"); // formulario some depois de dar certo: o celular oferece salvar o PIN
    document.body.classList.remove("sheet-open");
    toast(t("celular.oi", { nome: a.name.split(/\s+/)[0] }));
    checkAdmin();
    refresh();
  };

  form.onsubmit = async (e) => {
    e.preventDefault();
    hint.textContent = "";
    const n = name.value.trim().replace(/\s+/g, " ");
    if (!n) return name.focus();
    go.disabled = true;
    try {
      if (step === "name") {
        const r = await api(`/api/account/exists?name=${encodeURIComponent(n)}`);
        if (r.exists) name.value = r.name; // como esta na conta (e como o celular salva o usuario)
        setStep(r.exists ? "login" : "create");
      } else {
        if (!/^\d{4}$/.test(pin.value)) {
          hint.textContent = t("conta.pin_4");
          return pin.focus();
        }
        const r = await api(step === "login" ? "/api/account/login" : "/api/account", { method: "POST", body: { name: n, pin: pin.value } });
        let a = r.account;
        if (photo) {
          store("karaoke.session", r.token);
          a = await uploadPhoto(photo).catch((err) => {
            toast(t("celular.foto_falhou", { erro: err.message }), { error: true });
            return a;
          });
        }
        done(a, r.token);
      }
    } catch (err) {
      hint.textContent = err.message;
      if (err.data && err.data.code === "existe") setStep("login"); // alguem criou esse nome agora
      else if (step !== "name") pin.select();
    } finally {
      go.disabled = false;
    }
  };
  pin.oninput = () => {
    pin.value = pin.value.replace(/\D/g, "").slice(0, 4);
    if (step === "login" && pin.value.length === 4) form.requestSubmit(); // entrar direto (ou preenchido pelo celular)
  };
  $("#loginBack").onclick = () => setStep("name");
  photoBtn.onclick = () => photoFile.click();
  photoFile.onchange = () => {
    photo = photoFile.files[0] || null;
    if (photo) $("#loginAvatar").innerHTML = `<img src="${URL.createObjectURL(photo)}" alt="">`;
  };
  $("#loginStorage").classList.toggle("hidden", storageOk);
  name.value = prefill;
  box.classList.remove("hidden");
  document.body.classList.add("sheet-open");
  setStep("name");
}

/** Conta: trocar a foto ou sair. */
$("#acctChip").onclick = () => {
  if (!account) return showLogin();
  const modal = openModal(t("celular.sua_conta"), `
    <div class="acct-menu">
      ${avatar(account, "xl")}
      <b>${esc(account.name)}</b>
      <div class="row wrap">
        <button class="btn outline sm" data-photo>${icon("add_a_photo")} ${esc(t(account.photo ? "celular.trocar_foto" : "celular.por_foto"))}</button>
        <button class="btn ghost sm" data-out>${icon("logout")} ${esc(t("celular.sair"))}</button>
      </div>
      <label class="acct-lang"><span class="ms">translate</span> <span>${esc(t("config.idioma.titulo"))}</span>
        <select class="input compact" data-idioma>${["pt-BR", "en"].map((v) => `<option value="${v}"${idioma() === v ? " selected" : ""}>${esc(t(v === "en" ? "config.idioma.en" : "config.idioma.pt"))}</option>`).join("")}</select></label>
      <input type="file" accept="image/*" hidden data-file>
      ${storageOk ? "" : `<p class="small login-warn"><span class="ms">warning</span> ${esc(t("celular.sem_armazenamento_curto"))}</p>`}
    </div>`);
  const file = modal.querySelector("[data-file]");
  modal.querySelector("[data-idioma]").onchange = (e) => escolherIdiomaCelular(e.target.value);
  modal.querySelector("[data-photo]").onclick = () => file.click();
  file.onchange = async () => {
    if (!file.files[0]) return;
    try {
      applyAccount(await uploadPhoto(file.files[0]));
      toast(t("celular.foto_salva"));
      modal.close();
    } catch (err) {
      toast(err.message, { error: true });
    }
  };
  modal.querySelector("[data-out]").onclick = async () => {
    await api("/api/account/logout", { method: "POST" }).catch(() => {});
    store("karaoke.session", "");
    account = null;
    modal.close();
    showLogin();
  };
};

function needName() {
  if (!account) showLogin();
}
document.addEventListener("karaoke:need-name", needName);

// ------------------------------------------------ fontes (complementos com "celular")
// A aba Buscar so existe com alguma fonte; ligar ou desligar um complemento com a festa
// rolando redesenha as abas sozinho (o /api/party traz a versao dos recursos).
let fonte = store("karaoke.fonte") || "";
let fontes = [];
let recursosVersao = null;
async function carregarRecursos() {
  const r = await api("/api/recursos").catch(() => null);
  if (!r) return;
  fontes = r.fontes || [];
  if (!fontes.some((f) => f.id === fonte)) fonte = fontes.length ? fontes[0].id : "";
  $("#buscarTab").classList.toggle("hidden", !fontes.length);
  if (!fontes.length && tab === "buscar") $('[data-tab="sing"]').click();
  const bar = $("#fontes");
  bar.classList.toggle("hidden", fontes.length < 2);
  bar.innerHTML = fontes.map((f) => `
    <button class="chip${f.id === fonte ? " on" : ""}" data-fonte="${esc(f.id)}">${icon(f.icone || "extension", "sm")} ${esc(f.nome)}</button>`).join("");
  bar.querySelectorAll("[data-fonte]").forEach((b) => (b.onclick = () => {
    fonte = b.dataset.fonte;
    store("karaoke.fonte", fonte);
    $("#results").innerHTML = "";
    carregarRecursos();
  }));
  const atual = fontes.find((f) => f.id === fonte);
  if (atual) $("#q").placeholder = t("buscar.placeholder", { fonte: atual.nome });
  document.dispatchEvent(new CustomEvent("karaoke:fontes"));
}

setupSearch({
  form: $("#searchForm"),
  input: $("#q"),
  button: $("#searchBtn"),
  results: $("#results"),
  getName,
  sing: true,
  getFonte: () => fonte,
});

// ------------------------------------------------------------------ abas
let tab = "sing";
$$("[data-tab]").forEach((b) => {
  b.onclick = () => {
    tab = b.dataset.tab;
    $$("[data-tab]").forEach((x) => x.classList.toggle("on", x === b));
    $$(".tab").forEach((t) => t.classList.toggle("hidden", t.id !== `tab-${tab}`));
    // mostra o comeco da aba (logo abaixo do cartao do palco)
    const top = $(".m-head").offsetHeight;
    if (window.scrollY > top) window.scrollTo({ top: 0, behavior: "smooth" });
  };
});

let state = { jobs: [], songs: [] };
let party = { queue: [], history: [] };
const sigs = {};
const changed = (key, value) => {
  if (sigs[key] === value) return false;
  sigs[key] = value;
  return true;
};

// ------------------------------------------------------- palco / sua vez
async function command(action) {
  try {
    party = await api("/api/party/command", { method: "POST", body: { action } });
    renderStage();
  } catch (err) {
    toast(err.message, { error: true });
  }
}

// ------------------------------------------- "tocando agora"
let sheetOpen = false;

function openSheet() {
  if (sheetOpen) return;
  sheetOpen = true;
  $("#npSheet").classList.add("open");
  $("#npSheet").setAttribute("aria-hidden", "false");
  document.body.classList.add("sheet-open");
  history.pushState({ sheet: 1 }, ""); // o "voltar" do Android fecha a tela
}

function closeSheet(fromHistory = false) {
  if (!sheetOpen) return;
  sheetOpen = false;
  $("#npSheet").classList.remove("open");
  $("#npSheet").setAttribute("aria-hidden", "true");
  document.body.classList.remove("sheet-open");
  if (!fromHistory && history.state && history.state.sheet) history.back();
}

window.addEventListener("popstate", () => closeSheet(true));
$("#mpOpen").onclick = openSheet;
$("#npClose").onclick = () => closeSheet();
// arrastar para baixo (a partir do topo) fecha
{
  let startY = null;
  const sheet = $("#npSheet");
  sheet.addEventListener("touchstart", (e) => {
    startY = $(".np-scroll", sheet).scrollTop <= 0 ? e.touches[0].clientY : null;
  }, { passive: true });
  sheet.addEventListener("touchend", (e) => {
    if (startY != null && e.changedTouches[0].clientY - startY > 90) closeSheet();
    startY = null;
  }, { passive: true });
}

async function react(kind) {
  if (navigator.vibrate) navigator.vibrate(15);
  try {
    await api("/api/party/react", { method: "POST", body: { kind, name: getName() } });
  } catch {
    /* sem conexao: tudo bem */
  }
}

/** Barrinha acima das abas: quem canta, a musica e um botao rapido. */
function renderMini() {
  const cur = party.current;
  const mini = $("#miniPlayer");
  mini.classList.toggle("hidden", !cur);
  document.body.classList.toggle("has-mini", !!cur);
  if (!cur) return;
  const s = cur.song || {};
  const pb = cur.playback || {};
  const playing = pb.state === "playing";
  const song = s.track || s.title || "";
  mini.classList.toggle("mine", !!cur.mine);
  const cover = s.art_sm || s.cover || s.thumb || "";
  if ($("#mpCover").getAttribute("src") !== cover) $("#mpCover").src = cover;
  $("#mpTitle").textContent = cur.mine ? `${t("celular.sua_vez")} ${song}` : `${cur.singer} · ${song}`;
  $("#mpSub").textContent = playing
    ? `${t(cur.mine ? "celular.voce_cantando" : "sing.cantando_agora")}${pb.duration ? ` · ${fmtTime(pb.position)} / ${fmtTime(pb.duration)}` : ""}`
    : t(cur.mine ? "celular.toque_comecar" : "celular.subindo");
  $("#mpBar").style.width = `${pb.duration ? Math.min(100, (pb.position / pb.duration) * 100) : 0}%`;
  // quem canta (ou o administrador) controla; a plateia manda um coracao
  const control = cur.mine || isAdmin;
  const btn = $("#mpAction");
  btn.innerHTML = control ? icon(playing ? "pause" : "play_arrow", "fill") : icon("favorite", "fill");
  btn.classList.toggle("heart", !control);
  btn.setAttribute("aria-label", t(control ? (playing ? "celular.pausar" : "controle.tocar") : "celular.coracao"));
  btn.onclick = () => {
    if (control) return command(playing ? "pause" : "play");
    btn.classList.remove("pop");
    void btn.offsetWidth;
    btn.classList.add("pop");
    react("heart");
  };
  // chegou a sua vez: abre a tela inteira sozinha (uma vez por musica)
  if (cur.mine && sigs.autoOpened !== cur.id) {
    sigs.autoOpened = cur.id;
    openSheet();
  }
}

/** Passar a vez: as proximas pessoas cantam antes; a entrada nao sai da fila. */
async function passTurn(entry, question) {
  if (!confirm(question)) return;
  try {
    onParty(await api("/api/party/pass", { method: "POST", body: { entry_id: entry.id } }));
    toast(entry.mine ? t("celular.voce_passou") : t("celular.passou", { nome: entry.singer }), { ms: 4000 });
  } catch (err) {
    toast(err.message, { error: true });
  }
}
const PASS_MINE = () => t("celular.passar_confirmar");

/** A sua vez e a proxima: aviso fixo + vibracao (uma vez por musica). */
function renderNextBanner() {
  const cur = party.current;
  const next = (party.queue || []).find((e) => e.ready);
  const show = !!(cur && !cur.mine && next && next.mine);
  $("#nextBanner").classList.toggle("hidden", !show);
  document.body.classList.toggle("has-next", show);
  if (!show) return;
  const s = next.song || {};
  $("#nbSub").textContent = t("celular.depois_de", { nome: cur.singer, musica: s.track || s.title || "" });
  $("#nbPass").onclick = () => passTurn(next, PASS_MINE());
  if (sigs.nextWarned !== next.id) {
    sigs.nextWarned = next.id;
    if (navigator.vibrate) navigator.vibrate([120, 80, 120]);
  }
}

function renderNext() {
  const next = (party.queue || []).filter((e) => e.ready).slice(0, 3);
  const sig = JSON.stringify(next.map((e) => [e.id, e.eta]));
  if (!changed("next", sig)) return;
  $("#npNext").innerHTML = next.length
    ? `<h3 class="m-sub-title">${esc(t("player.a_seguir"))}</h3>${next.map((e) => `
      <div class="np-next-item"><img src="${esc((e.song && (e.song.art_sm || e.song.thumb)) || "")}" alt="">
        <div class="grow"><b>${esc(e.singer)}</b><div class="small muted">${esc((e.song && (e.song.track || e.song.title)) || "")}</div></div>
        <span class="small muted">${esc(etaText(e.eta))}</span></div>`).join("")}`
    : "";
}

function renderStage() {
  const cur = party.current;
  const box = $("#stageCard");
  const pb = (cur && cur.playback) || {};
  renderMini();
  renderNextBanner();
  renderNext();
  const sig = JSON.stringify([cur && cur.id, cur && cur.mine, cur && cur.transpose, pb.state, pb.guide, Math.floor((pb.position || 0) / 2), isAdmin,
    (party.queue || []).some((e) => e.ready)]);
  if (!changed("stage", sig)) return;
  if (!cur) {
    box.className = "stage-card idle";
    box.innerHTML = `${icon("mic_off")}<div><b>${esc(t("player.palco_livre"))}</b><div class="small muted">${esc(t("celular.palco_livre_texto"))}</div></div>`;
    return;
  }
  const s = cur.song || {};
  const playing = pb.state === "playing";
  const pctDone = pb.duration ? Math.min(100, (pb.position / pb.duration) * 100) : 0;
  const progress = `<div class="progress"><i style="width:${pctDone}%"></i></div>
    <div class="small muted stage-time">${pb.duration ? `${fmtTime(pb.position)} / ${fmtTime(pb.duration)}` : esc(t("fila.esperando_play"))}</div>`;
  // antes de comecar: "passar a vez" (se tem alguem pronto para cantar antes) no lugar de "recomecar"
  const fresh = !playing && !(pb.position > 1);
  const canPass = fresh && (party.queue || []).some((e) => e.ready);
  const second = canPass
    ? `<button class="st-small" data-pass>${icon("low_priority")}<span>${esc(t("player.passar"))}</span></button>`
    : `<button class="st-small" data-cmd="restart">${icon("replay")}<span>${esc(t("celular.recomecar"))}</span></button>`;
  if (cur.mine) {
    box.className = "stage-card mine";
    box.innerHTML = `
      <div class="st-top">
        <img src="${esc(s.art_sm || s.cover || s.thumb || "")}" alt="">
        <div class="grow"><span class="st-eyebrow">${icon("mic", "fill")} ${esc(t("celular.sua_vez"))}</span>
          <b class="st-song">${esc(s.track || s.title)}</b><div class="small muted">${esc(s.artist || "")}</div></div>
      </div>
      ${progress}
      <div class="st-controls">
        <button class="st-main" data-cmd="${playing ? "pause" : "play"}">${playing ? icon("pause", "fill") : icon("play_arrow", "fill")}<span>${esc(t(playing ? "celular.pausar" : pb.position > 1 ? "celular.continuar_tocar" : "player.comecar"))}</span></button>
        ${second}
        <button class="st-small" data-cmd="skip">${icon("skip_next")}<span>${esc(t("comum.pular"))}</span></button>
      </div>
      <button class="guide-toggle${pb.guide ? " on" : ""}" data-cmd="${pb.guide ? "guide_off" : "guide_on"}">
        ${icon("record_voice_over")}<span class="grow">${t("celular.voz_guia")}</span>
        <span class="switch"><i></i></span>
      </button>
      ${tomStepper(cur)}`;
    bindTomSteppers(box, onParty);
    const pass = $("[data-pass]", box);
    if (pass) pass.onclick = () => passTurn(cur, PASS_MINE());
    $$("[data-cmd]", box).forEach((b) => {
      b.onclick = () => {
        if (b.dataset.cmd === "skip" && !confirm(t("celular.pular_sua"))) return;
        command(b.dataset.cmd);
      };
    });
    if (navigator.vibrate && sigs.vibrated !== cur.id) {
      sigs.vibrated = cur.id;
      navigator.vibrate([200, 100, 200]); // avisa que chegou a vez
    }
    return;
  }
  box.className = "stage-card";
  const adminControls = isAdmin ? `
      <div class="st-controls admin">
        <button class="st-small" data-cmd="${playing ? "pause" : "play"}">${playing ? icon("pause", "fill") : icon("play_arrow", "fill")}<span>${esc(t(playing ? "celular.pausar" : "controle.tocar"))}</span></button>
        ${second}
        <button class="st-small" data-cmd="skip">${icon("skip_next")}<span>${esc(t("comum.pular"))}</span></button>
      </div>` : "";
  box.innerHTML = `
    <div class="st-top">
      <img src="${esc(s.art_sm || s.cover || s.thumb || "")}" alt="">
      <div class="grow"><span class="st-eyebrow">${playing ? icon("graphic_eq") : icon("hourglass_top")} ${esc(t(playing ? "sing.cantando_agora" : "celular.subindo"))}</span>
        <b class="st-song">${avatar(cur.person, "sm")}${esc(cur.singer)}</b><div class="small muted">${esc(s.track || s.title)}${s.artist ? " · " + esc(s.artist) : ""}</div></div>
    </div>
    ${progress}${adminControls}`;
  const pass = $("[data-pass]", box);
  if (pass) pass.onclick = () => passTurn(cur, t("celular.passar_de_confirmar", { nome: cur.singer }));
  $$("[data-cmd]", box).forEach((b) => {
    b.onclick = () => {
      if (b.dataset.cmd === "skip" && !confirm(t("celular.pular_nome", { nome: cur.singer }))) return;
      command(b.dataset.cmd);
    };
  });
}

// reacoes: a plateia manda palmas, coracao... que sobem na tela do palco
const REACTIONS = [
  ["clap", "sign_language", "#ffd23f"], ["heart", "favorite", "#ff4d6d"], ["fire", "local_fire_department", "#ff8a00"],
  ["laugh", "sentiment_very_satisfied", "#ffd23f"], ["star", "star", "#fff176"], ["wow", "auto_awesome", "#8be9fd"],
]; /* icons: sign_language favorite local_fire_department sentiment_very_satisfied star auto_awesome */

function mountReactions() {
  const bar = $("#reactBar");
  bar.innerHTML = REACTIONS.map(([kind, ico, color]) =>
    `<button data-react="${kind}" style="--c:${color}" aria-label="${esc(t(`reacao.${kind}`))}">${icon(ico, "fill")}</button>`).join("");
  $$("[data-react]", bar).forEach((b) => {
    b.onclick = () => {
      b.classList.remove("pop");
      void b.offsetWidth;
      b.classList.add("pop");
      react(b.dataset.react);
    };
  });
}
mountReactions();

function renderReactBar() {
  const cur = party.current;
  // aparece quando tem alguem no palco (a pessoa que canta tambem pode mandar)
  $("#reactWrap").classList.toggle("hidden", !cur);
  if (cur) $("#reactWho").textContent = cur.mine ? t("celular.anime") : t("celular.mande_energia", { nome: cur.singer });
}

function onParty(p) {
  party = p;
  renderAll();
}

function renderQueueTools() {
  const box = $("#queueTools");
  const sig = JSON.stringify([isAdmin, party.rotation]);
  if (!changed("qtools", sig)) return;
  if (isAdmin) {
    box.innerHTML = `
      <button class="guide-toggle rot-toggle${party.rotation ? " on" : ""}" id="rotToggle">
        ${icon("sync")}<span class="grow">${esc(t("fila.rodizio"))}
          <span class="small muted" style="display:block;font-weight:500">${esc(t("celular.rodizio_texto"))}</span></span>
        <span class="switch"><i></i></span>
      </button>
      <button class="btn outline sm new-party" id="newParty">${icon("celebration")} ${esc(t("festa.nova"))}</button>`;
    $("#newParty").onclick = async () => {
      if (!confirm(t("festa.nova_confirmar"))) return;
      try {
        await api("/api/party/new", { method: "POST" });
        toast(t("celular.festa_nova"));
        refresh();
      } catch (err) {
        toast(err.message, { error: true });
      }
    };
    $("#rotToggle").onclick = async () => {
      try {
        await api("/api/party/rotation", { method: "POST", body: { on: !party.rotation } });
        toast(t(!party.rotation ? "celular.rodizio_ligado" : "celular.rodizio_desligado"), { key: "rodizio" });
        refresh();
      } catch (err) {
        toast(err.message, { error: true });
      }
    };
  } else {
    box.innerHTML = party.rotation
      ? `<div class="small muted rot-note">${icon("sync", "sm")} ${esc(t("celular.rodizio_nota"))}</div>`
      : "";
  }
}

function renderQueueTab() {
  renderQueueTools();
  const n = (party.queue || []).length;
  $("#queueCount").textContent = n ? String(n) : "";
  const sig = signature(party.queue || [], ["id", "eta", "ready", "singer", "person"]) +
    JSON.stringify((party.queue || []).map((e) => e.song && e.song.progress));
  if (changed("queue", sig + isAdmin)) renderQueue($("#queueList"), party, { host: isAdmin, onChange: refresh });
  const hsig = JSON.stringify([party.history || [], party.ranking || []]);
  if (changed("history", hsig)) {
    $("#historyList").innerHTML = (party.history || []).length
      ? `${(party.ranking || []).length ? `<h3 class="m-sub-title">${icon("trophy")} ${esc(t("festa.ranking"))}</h3>${rankingRows(party.ranking)}` : ""}
        <h3 class="m-sub-title">${esc(t("fila.ja_cantaram"))}</h3>${party.history.map((x) =>
        `<div class="small muted hist">${esc(x.singer)} · ${esc(x.title || "")}${x.score != null ? ` · <b>${esc(t("fila.pontos", { n: x.score }))}</b>` : ""}</div>`).join("")}`
      : "";
  }
}

// ---------------------------------------------------- biblioteca (cantar)
let libBusca = new Map(); // id -> texto da busca (sem acentos), refeito so quando a lista muda
let libAberta = null; // a lista criada aos poucos (milhares de musicas)
let libVersao = null;

function renderLibrary() {
  const q = dobrar($("#libFilter").value.trim());
  const todas = state.songs || [];
  const songs = q ? todas.filter((s) => (libBusca.get(s.id) || "").includes(q)) : todas;
  const queued = new Set((party.queue || []).filter((e) => e.mine).map((e) => e.song_id));
  const mesma = libVersao === todas;
  if (!changed("lib", `${q}#${songs.length}#${mesma}#${[...queued].join()}`) && mesma) return;
  libVersao = todas;
  const antes = libAberta ? libAberta.quantos() : 0;
  if (libAberta) libAberta.parar();
  const box = $("#libList");
  box.innerHTML = songs.length ? "" : `<div class="empty">${esc(todas.length ? t("comum.nada") : t("celular.biblioteca_vazia"))}</div>`;
  libAberta = aosPoucos(box, songs, (s) => libItem(s, queued), { lote: 50, minimo: antes });
}

function libItem(s, queued) {
  const inQueue = queued.has(s.id);
  const el = h(`
    <div class="lib-item">
      <img src="${esc(s.art_sm || s.cover || s.thumb)}" alt="" loading="lazy">
      <div class="grow">
        <div class="t">${esc(s.track || s.title)}</div>
        <div class="a">${esc(s.artist || "")}${s.duration ? " · " + fmtTime(s.duration) : ""}</div>
      </div>
      <button class="lib-play${inQueue ? " on" : ""}" data-sing aria-label="${esc(t(inQueue ? "busca.ja_fila" : "celular.cantar_entrar"))}">${icon(inQueue ? "check" : "play_arrow", "fill")}</button>
    </div>`);
  el.querySelector("[data-sing]").onclick = async (ev) => {
    const b = ev.currentTarget;
    const name = getName();
    if (!name) return needName();
    b.disabled = true;
    try {
      const r = await api("/api/party/add", { method: "POST", body: { song_id: s.id, name } });
      party = r.party;
      const pos = (party.queue || []).findIndex((e) => e.id === r.entry.id);
      toast(party.current && party.current.id === r.entry.id ? t("celular.sua_vez_play") : t("celular.na_fila_pos", { pos: pos + 1 }));
      renderAll();
    } catch (err) {
      toast(err.message, { error: true });
    }
    b.disabled = false;
  };
  return el;
}

let libTimer = null; // digitando: filtra quando para
$("#libFilter").addEventListener("input", () => {
  clearTimeout(libTimer);
  libTimer = setTimeout(renderLibrary, 150);
});

// --------------------------------------------------- buscar: sendo preparadas
function renderJobs() {
  const jobs = state.jobs || [];
  const sig = signature(jobs, ["id", "status", "stage", "progress", "error", "mine", "queue"]);
  if (!changed("jobs", sig)) return;
  $("#jobsTitle").classList.toggle("hidden", !jobs.length);
  const box = $("#jobsList");
  box.innerHTML = "";
  for (const j of jobs) box.append(jobEl(j, { canDelete: j.mine, canRetry: j.mine }));
}

/** Avisa quando a sua musica acaba com a nota (pontuacao pelo microfone). */
let seenFinish = null; // o que ja estava no historico quando a pagina abriu nao avisa
function notifyMyScore() {
  const last = (party.history || [])[0];
  const key = last ? String(last.finished_at) : "";
  if (seenFinish === null) {
    seenFinish = key;
    return;
  }
  if (key === seenFinish) return;
  seenFinish = key;
  if (!last.mine || last.score == null) return;
  toast(t("celular.pontos", { n: last.score, musica: last.title || t("celular.a_musica") }), { ms: 6000 });
  if (navigator.vibrate) navigator.vibrate([100, 60, 100, 60, 300]);
}

function renderAll() {
  notifyMyScore();
  showNotices(party);
  renderStage();
  renderReactBar();
  renderQueueTab();
  renderLibrary();
  renderJobs();
}

// ------------------------------------------------------------ atualizacao
let timer = null;
let failures = 0; // leituras seguidas sem resposta do servidor
let refreshing = false;

function setOffline(on) {
  const bar = $("#offlineBar");
  if (on === !bar.classList.contains("hidden")) return;
  bar.classList.toggle("hidden", !on);
  if (!on) toast(t("celular.conectado"), { key: "conexao" });
}

async function refresh() {
  if (refreshing) return;
  refreshing = true;
  clearTimeout(timer);
  let ok = false;
  try {
    // desiste de uma leitura travada (troca de Wi-Fi) em vez de segurar as proximas
    let bib;
    [state, party, bib] = await Promise.all([api("/api/state?musicas=0", { timeout: 6000 }),
      api("/api/party", { timeout: 6000 }), biblioteca()]);
    state.songs = bib.songs;
    if (bib.mudou) libBusca = new Map(bib.songs.map((s) => [s.id, dobrar(`${s.title} ${s.track} ${s.artist} ${s.album || ""}`)]));
    ok = true;
  } catch (err) {
    if (!err.offline) console.warn(err); // erro do servidor (nao e falta de conexao)
    else failures += 1;
  }
  if (ok) failures = 0;
  if (ok && !accountChecked) loadAccount(); // a pagina abriu sem conexao: confere a conta agora
  setOffline(failures >= 2); // ~4 s sem resposta
  refreshing = false;
  // mais rapido quando e a sua vez (para os botoes responderem na hora)
  timer = setTimeout(refresh, party.my_turn ? 1000 : 2000);
  if (ok) renderAll();
  if (ok && party.recursos_versao !== recursosVersao) {
    recursosVersao = party.recursos_versao;
    carregarRecursos();
  }
}
// o navegador do celular pausa a pagina em segundo plano: ao voltar, atualiza na hora
document.addEventListener("visibilitychange", () => document.visibilityState === "visible" && refresh());
window.addEventListener("online", refresh);
window.addEventListener("pageshow", (e) => e.persisted && refresh());
const syncTabbarHeight = () =>
  document.documentElement.style.setProperty("--tabbar-h", `${$("#tabbar").offsetHeight}px`);
syncTabbarHeight();
window.addEventListener("resize", syncTabbarHeight);

document.addEventListener("karaoke:refresh", refresh);
refresh();
// quem e este aparelho: sem conta (ou o navegador esqueceu), a tela de entrar
let accountChecked = false;
let accountLoading = false;
function loadAccount() {
  if (accountLoading) return;
  accountLoading = true;
  api("/api/account", { timeout: 6000 }).then((r) => {
    accountChecked = true;
    if (r.account) {
      applyAccount(r.account);
      checkAdmin();
    } else {
      showLogin();
    }
  }).catch(() => checkAdmin()).finally(() => (accountLoading = false));
}
loadAccount();
try {
  localStorage.removeItem("karaoke.name"); // nome do modelo antigo (antes das contas)
} catch {
  /* navegador sem armazenamento */
}

// ------------------------------------------------------ controle remoto
let remoteMounted = false;
function mountRemote() {
  if (remoteMounted) return;
  remoteMounted = true;

  const showTarget = (target) => {
    const box = $("#rcTarget");
    box.classList.toggle("off", !target);
    box.innerHTML = target
      ? `<span class="dot on"></span>${t("controle.controlando", { tela: `<b>${esc(target)}</b>` })}`
      : `<span class="dot"></span>${esc(t("controle.nenhuma_tela"))}`;
  };
  async function rc(cmd, value) {
    if (navigator.vibrate) navigator.vibrate(8);
    try {
      const r = await api("/api/remote", { method: "POST", body: { cmd, value } });
      showTarget(r.delivered ? r.target : null);
    } catch (err) {
      toast(err.message, { error: true });
    }
  }

  // segurar uma seta repete (como no controle da TV)
  $$("[data-rc]").forEach((b) => {
    const cmd = b.dataset.rc;
    const repeat = ["up", "down", "left", "right", "vol_up", "vol_down"].includes(cmd);
    let timer = null;
    const stop = () => {
      clearTimeout(timer);
      clearInterval(timer);
      timer = null;
    };
    b.addEventListener("pointerdown", (e) => {
      e.preventDefault();
      b.classList.add("pressed");
      rc(cmd);
      if (repeat) timer = setTimeout(() => (timer = setInterval(() => rc(cmd), 170)), 450);
    });
    ["pointerup", "pointerleave", "pointercancel"].forEach((ev) => b.addEventListener(ev, () => {
      b.classList.remove("pressed");
      stop();
    }));
    b.addEventListener("contextmenu", (e) => e.preventDefault());
  });

  // pesquisa: so os botoes mexem na TV (digitar ou tocar na caixa nao faz nada la)
  const input = $("#rcSearch");
  const go = (cmd, fonte) => {
    const text = input.value.trim();
    if (!text) return input.focus();
    input.blur();
    rc(cmd, fonte ? { fonte, texto: text } : text);
  };
  input.addEventListener("keydown", (e) => e.key === "Enter" && go("submit"));
  $("#rcLib").onclick = () => go("submit");
  // um botao por fonte: busca na TV (pagina Adicionar) com aquela fonte
  const rcFontes = () => {
    $("#rcFontes").innerHTML = fontes.map((f) => `
      <button class="btn outline sm" data-rc-fonte="${esc(f.id)}">${icon(f.icone || "extension")} ${esc(f.nome)}</button>`).join("");
    $$("[data-rc-fonte]").forEach((b) => (b.onclick = () => go("buscar", b.dataset.rcFonte)));
  };
  rcFontes();
  document.addEventListener("karaoke:fontes", rcFontes);

  // palco na TV
  const renderStage = (st) => {
    $("#stageStatus").innerHTML = st.open
      ? `<span class="dot on"></span>${esc(t("controle.aberto"))} · ${esc(t(st.mode === "kiosk" ? "controle.quiosque_min" : "controle.tela_cheia_min"))}`
      : `<span class="dot"></span>${esc(t("controle.fechado"))}`;
    $("#stageOpen").innerHTML = `${icon("cast")} ${esc(t(st.open ? "controle.reabrir" : "controle.abrir"))}`;
    $("#stageClose").classList.toggle("hidden", !st.open);
    $$("#stageMode button").forEach((x) => x.classList.toggle("on", x.dataset.v === st.mode));
    const mons = st.monitors || [];
    const current = mons.some((m) => m.id === st.monitor) ? st.monitor : (mons.find((m) => m.primary) || {}).id;
    $("#stageMonitor").innerHTML = mons.map((m) =>
      `<option value="${esc(m.id)}"${m.id === current ? " selected" : ""}>${esc(m.label)}</option>`).join("");
  };
  $("#stageCfgBtn").onclick = () => {
    const cfg = $("#stageCfg");
    cfg.classList.toggle("hidden");
    $("#stageCfgBtn").classList.toggle("on", !cfg.classList.contains("hidden"));
  };
  const loadStage = () => api("/api/stage").then(renderStage).catch(() => {});
  $("#stageOpen").onclick = async (e) => {
    e.currentTarget.disabled = true;
    try {
      const r = await api("/api/stage/open", { method: "POST" });
      renderStage(r);
      toast(r.monitor_missing ? t("palco.tela_desligada", { tela: r.opened_on }) : t("palco.aberto_em", { tela: r.opened_on }), { error: r.monitor_missing });
    } catch (err) {
      toast(err.message, { error: true });
    }
    e.currentTarget.disabled = false;
  };
  $("#stageClose").onclick = async () => renderStage(await api("/api/stage/close", { method: "POST" }).catch(() => ({})));
  $$("#stageMode button").forEach((b) => {
    b.onclick = async () => renderStage(await api("/api/stage", { method: "PUT", body: { mode: b.dataset.v } }));
  });
  $("#stageMonitor").onchange = async (e) => renderStage(await api("/api/stage", { method: "PUT", body: { monitor: e.target.value } }));

  // quem esta sendo controlado (atualiza enquanto a aba esta aberta)
  const poll = async () => {
    if (tab === "remote") {
      try {
        showTarget((await api("/api/remote")).target);
      } catch {
        /* tenta de novo */
      }
    }
    setTimeout(poll, 4000);
  };
  $("#remoteTab").addEventListener("click", loadStage);
  loadStage();
  poll();
}
