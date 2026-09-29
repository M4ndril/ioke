// Pagina "Adicionar musicas": enviar arquivos, buscar nas fontes dos complementos, fila e QR.
import { $, api, esc, fmtTime, h, icon, store } from "./common.js";
import { mountFabs } from "./floating.js";
import "./tvnav.js";
import "./stageopen.js";
import { openSettings, qualityLabel } from "./settings.js";
import { bindNav, jobEl, setupSearch, signature } from "./ui.js";
import { initI18n, t } from "./i18n.js";
import { mountEnviar } from "./enviar.js";
import { avisoCustos } from "./nuvem.js";

await initI18n(); // os textos antes de desenhar a pagina

bindNav();
mountFabs({ qr: true, settings: true });
mountEnviar($("#upload"), { onDone: () => document.dispatchEvent(new CustomEvent("karaoke:refresh")) });
// "Buscar em:": as fontes de musicas dos complementos ligados (sem nenhuma, a busca some)
let fonte = store("karaoke.fonte") || "";
async function mostrarFontes() {
  const r = await api("/api/recursos").catch(() => null);
  const fontes = (r && r.fontes) || [];
  if (!fontes.some((f) => f.id === fonte)) fonte = fontes.length ? fontes[0].id : "";
  const bar = $("#fontes");
  bar.classList.toggle("hidden", fontes.length < 2);
  $("#searchArea").classList.toggle("hidden", !fontes.length);
  $("#semFontes").classList.toggle("hidden", !!fontes.length);
  bar.innerHTML = `<span class="small muted">${t("buscar.em")}</span>` + fontes.map((f) => `
    <button class="chip${f.id === fonte ? " on" : ""}" data-fonte="${esc(f.id)}">${icon(f.icone || "extension", "sm")} ${esc(f.nome)}</button>`).join("");
  const atual = fontes.find((f) => f.id === fonte);
  if (atual) $("#q").placeholder = t("buscar.placeholder", { fonte: atual.nome });
  bar.querySelectorAll("[data-fonte]").forEach((b) => (b.onclick = () => {
    fonte = b.dataset.fonte;
    store("karaoke.fonte", fonte);
    $("#results").innerHTML = "";
    mostrarFontes();
    $("#q").focus();
  }));
}
mostrarFontes();
document.addEventListener("karaoke:fontes", mostrarFontes);

setupSearch({
  form: $("#searchForm"),
  input: $("#q"),
  button: $("#searchBtn"),
  results: $("#results"),
  onResults: (n) => $("#tips").classList.toggle("hidden", n > 0),
  getFonte: () => fonte,
});

// pesquisa vinda do controle remoto: /adicionar?q=...&fonte=...
const incoming = new URLSearchParams(location.search).get("q");
const fonteVinda = new URLSearchParams(location.search).get("fonte");
if (fonteVinda) {
  fonte = fonteVinda;
  store("karaoke.fonte", fonte);
  mostrarFontes();
}
document.addEventListener("karaoke:fonte", (e) => {
  fonte = e.detail;
  store("karaoke.fonte", fonte);
  mostrarFontes();
});
if (incoming) {
  $("#q").value = incoming;
  history.replaceState(null, "", "/adicionar");
  setTimeout(() => $("#searchForm").requestSubmit(), 100);
}

const showQuality = () => qualityLabel().then((l) => ($("#qualityLabel").textContent = t("qualidade.escolhida", { nome: l }))).catch(() => {});
const refreshSettings = () => showQuality();
$("#qualityBtn").onclick = () => openSettings({ onChange: refreshSettings, tab: "musicas" });
// fechar as Configuracoes: os complementos podem ter mudado (fontes da busca)
document.addEventListener("karaoke:settings-closed", mostrarFontes);
refreshSettings();

$("#qr").src = `/api/qr.svg?t=${Date.now()}`;
api("/api/info").then((info) => ($("#lanUrl").textContent = info.lan_url)).catch(() => {});

let jobsSig = "";
let recentSig = "";

function renderJobs(jobs) {
  const sig = signature(jobs, ["id", "status", "stage", "progress", "error", "cover", "title", "queue", "nuvem"]);
  if (sig === jobsSig) return;
  pedirAvisoCustos(jobs);
  jobsSig = sig;
  $("#queueCount").textContent = jobs.length;
  $("#jobsEmpty").classList.toggle("hidden", jobs.length > 0);
  const box = $("#jobs");
  box.innerHTML = "";
  for (const job of jobs) box.append(jobEl(job, { canDelete: true, canRetry: true, canCloud: true }));
}

// a primeira musica mandada para a nuvem: o aviso de custos (uma vez por abertura da pagina)
let avisoMostrado = false;
async function pedirAvisoCustos(jobs) {
  if (avisoMostrado || !jobs.some((j) => j.nuvem && j.nuvem.espera === "aceitar")) return;
  avisoMostrado = true;
  if (await avisoCustos()) document.dispatchEvent(new CustomEvent("karaoke:refresh"));
}

function renderRecent(songs) {
  const recent = songs.slice(0, 6);
  const sig = signature(recent, ["id", "cover", "title"]);
  if (sig === recentSig) return;
  recentSig = sig;
  const box = $("#recent");
  box.innerHTML = recent.length ? "" : `<div class="empty small">${esc(t("adicionar.nenhuma"))}</div>`;
  for (const s of recent) {
    box.append(h(`
      <a class="mini" href="/player?id=${s.id}" title="${esc(t("adicionar.cantar_agora"))}">
        <img src="${esc(s.art_sm || s.cover || s.thumb)}" alt="" loading="lazy">
        <div class="grow"><div class="t">${esc(s.track || s.title)}</div><div class="a">${esc(s.artist || "")}${s.duration ? " · " + fmtTime(s.duration) : ""}</div></div>
        <span class="go">${icon("play_arrow", "fill")}</span>
      </a>`));
  }
}

let timer = null;
async function refresh() {
  clearTimeout(timer);
  let state = { jobs: [], songs: [] };
  try {
    state = await api("/api/state?musicas=0&recentes=6");
    renderJobs(state.jobs);
    renderRecent(state.recentes || []);
    const dev = state.device || {};
    $("#device").innerHTML = dev.device === "cuda" ? `${icon("bolt", "sm")} GPU: ${esc(dev.name)}` : dev.device === "cpu" ? esc(t("adicionar.cpu")) : "";
  } catch {
    /* servidor reiniciando */
  }
  timer = setTimeout(refresh, state.jobs.length ? 1000 : 4000);
}
document.addEventListener("karaoke:refresh", refresh);
refresh();
