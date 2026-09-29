// "Abrir o palco": o mesmo botao em todo lugar (inicio, barra de cima, fila da
// biblioteca). Todo link com [data-open-stage] abre a janela propria do palco
// (som liberado, tela cheia): com mais de uma tela ligada no PC, pergunta em
// qual; com uma, abre direto. Escolher a tela onde esta a janela em que a pessoa
// clicou abre o palco NESTA janela (outra janela por cima dela, na mesma tela,
// nao faz sentido); no app, em tela cheia.
//
// Sem laco: dentro da janela do palco, o link so volta para o palco nela mesma.
// "Nesta janela" tambem e o caminho quando a janela propria nao abre (sem
// Chrome/Edge) e em outro computador da rede. Ctrl+clique / botao do meio tambem
// abrem o /palco numa aba, como qualquer link.
import { $, $$, api, esc, icon, openModal, toast } from "./common.js";
import { appApi } from "./appwin.js";
import { IS_TV } from "./tvnav.js";
import { t } from "./i18n.js";

/* icons: computer tv tab */
const here = () => (location.href = "/palco");

/** O palco nesta janela, na tela onde ela ja esta (fecha a janela do palco, se estiver aberta em outra). */
async function hereFull(st) {
  if (st.open) await api("/api/stage/close", { method: "POST" }).catch(() => {});
  const app = await appApi();
  if (app && app.set_fullscreen) await app.set_fullscreen(true);
  here();
}

async function launch(monitor) {
  try {
    const r = await api("/api/stage/open", { method: "POST", body: monitor ? { monitor } : {} });
    toast(r.monitor_missing ? t("palco.tela_desligada", { tela: r.opened_on }) : r.opened_on ? t("palco.aberto_em", { tela: r.opened_on }) : t("palco.aberto"),
      { error: r.monitor_missing, ms: 4000 });
  } catch (err) {
    failed(err.message);
  }
}

function failed(message) {
  const modal = openModal(t("palco.falhou"), `
    <p style="margin-top:0">${esc(message)}</p>
    <div class="row" style="gap:10px;justify-content:flex-end">
      <button class="btn outline" data-close-it>${esc(t("comum.cancelar"))}</button>
      <button class="btn light" data-here data-nav-default>${icon("tab")} ${esc(t("palco.nesta_janela"))}</button>
    </div>`);
  $("[data-close-it]", modal).onclick = () => modal.close();
  $("[data-here]", modal).onclick = here;
}

function chooseScreen(st) {
  const mons = st.monitors;
  const last = mons.some((m) => m.id === st.monitor) ? st.monitor : (mons.find((m) => m.primary) || mons[0]).id;
  const aqui = mons.find((m) => m.aqui); // a tela desta janela: o palco abre aqui mesmo
  const modal = openModal(t("palco.qual_tela"), `
    <div class="screen-pick">
      ${mons.map((m) => `
        <button class="screen-opt${m.id === last ? " on" : ""}" data-mon="${esc(m.id)}"${m.id === last ? " data-nav-default" : ""}>
          ${icon(m === aqui ? "tab" : m.primary ? "computer" : "tv")}
          <span><b>${esc(m.name || m.label)}</b><span class="small muted">${esc(m.label)}${m === aqui ? ` · ${esc(t("palco.nesta_tela"))}` : ""}${m.id === last ? ` · ${esc(t("palco.ultima"))}` : ""}</span></span>
        </button>`).join("")}
    </div>
    ${st.open ? `<p class="small muted">${esc(t("palco.reabre"))}</p>` : ""}
    ${aqui ? "" : `<p class="small muted" style="margin-bottom:0"><a href="/palco" data-here style="text-decoration:underline">${esc(t("palco.nesta_janela"))}</a> ${esc(t("palco.nesta_janela_explica"))}</p>`}`);
  $$("[data-mon]", modal).forEach((b) => (b.onclick = () => {
    modal.close();
    if (aqui && b.dataset.mon === aqui.id) return hereFull(st);
    launch(b.dataset.mon);
  }));
}

export async function openStage() {
  if (IS_TV) return here(); // janela do palco: nunca abre outra
  let st;
  try {
    st = await api("/api/stage");
  } catch {
    return here(); // outro computador da rede: o palco abre nesta aba
  }
  if (!st.browser) return failed(t("palco.precisa_navegador"));
  if ((st.monitors || []).length > 1) return chooseScreen(st);
  return launch();
}

document.addEventListener("click", (e) => {
  const link = e.target.closest("[data-open-stage]");
  if (!link || e.button !== 0 || e.ctrlKey || e.metaKey || e.shiftKey || e.altKey) return;
  e.preventDefault();
  openStage();
});
