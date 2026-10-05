// Pastas vigiadas (Configuracoes -> Musicas novas): as pastas que o IOkê olha de tempos em tempos. Musica nova que
// aparece numa delas vai para a revisao (o cartao no Adicionar) ou entra sozinha (karaoke/pastas.py).
import { api, confirmar, esc, h, icon, pedirTexto, toast } from "./common.js";
import { appApi } from "./appwin.js";
import { t } from "./i18n.js";
import { abrirRevisao } from "./revisao.js";

/* icons: folder create_new_folder delete fact_check cloud_off */

/** Pede a pasta (a janela do Windows no app; no navegador, digitando o caminho) e passa a vigiar. */
export async function vigiarPasta() {
  const app = await appApi();
  const caminho = app && app.escolher_pasta_musicas ? await app.escolher_pasta_musicas() : await pedirTexto(t("pastas.digite"), { titulo: t("pastas.vigiar") });
  if (!caminho) return null;
  try {
    const r = await api("/api/pastas", { method: "POST", body: { caminho, subpastas: true, modo: "perguntar" } });
    toast(t("pastas.adicionada", { nome: r.pasta.caminho }));
    return r;
  } catch (err) {
    toast(err.message, { error: true });
    return null;
  }
}

/** A revisao do que ja esta numa pasta vigiada (a primeira olhada nunca importa nada sozinha). */
export async function revisarPasta(id) {
  try {
    const r = await api(`/api/pastas/${id}/revisar`, { method: "POST" });
    if (!r.itens.length) return toast(t("enviar.pasta_vazia"));
    return abrirRevisao({ titulo: r.nome, itens: r.itens, tipo: "vigiada", cortado: r.cortado });
  } catch (err) {
    toast(err.message, { error: true });
  }
}

/** A revisao das musicas novas das pastas vigiadas (de todas, ou de uma). */
export async function revisarNovas(id) {
  try {
    const r = await api("/api/pastas/novas/revisar", { method: "POST", body: { id } });
    if (!r.itens.length) return toast(t("pastas.nada_novo"));
    return abrirRevisao({ titulo: r.nome, itens: r.itens, tipo: "vigiada" });
  } catch (err) {
    toast(err.message, { error: true });
  }
}

/** A secao das Configuracoes. */
export function mountPastas(box) {
  async function carregar() {
    try {
      render((await api("/api/pastas")).pastas);
    } catch (err) {
      box.innerHTML = `<p class="small muted">${esc(err.message)}</p>`;
    }
  }
  function render(pastas) {
    box.innerHTML = `
      <div class="pastas-lista">${pastas.length ? "" : `<p class="small muted" style="margin:0">${esc(t("pastas.nenhuma"))}</p>`}</div>
      <button class="btn sm" data-nova style="margin-top:10px">${icon("create_new_folder")} ${esc(t("pastas.vigiar"))}</button>`;
    const lista = box.querySelector(".pastas-lista");
    for (const p of pastas) {
      const estado = p.fora ? `<span class="badge warn">${icon("cloud_off", "sm")} ${esc(t("pastas.fora_do_ar"))}</span>`
        : p.novas ? `<span class="badge ok">${esc(t("pastas.novas", { n: p.novas }))}</span>` : "";
      const el = h(`
        <div class="pasta-row">
          <span class="ms">folder</span>
          <div class="grow" style="min-width:0">
            <div class="pasta-nome"><b>${esc(p.nome)}</b> ${estado}</div>
            <div class="small muted pasta-caminho" title="${esc(p.caminho)}">${esc(p.caminho)}</div>
            <div class="row wrap pasta-opcoes">
              <select class="input compact" data-modo>
                <option value="perguntar"${p.modo === "perguntar" ? " selected" : ""}>${esc(t("pastas.modo_perguntar"))}</option>
                <option value="sozinho"${p.modo === "sozinho" ? " selected" : ""}>${esc(t("pastas.modo_sozinho"))}</option>
              </select>
              <label class="toggle-row small"><input type="checkbox" data-sub${p.subpastas ? " checked" : ""}> ${esc(t("pastas.subpastas"))}</label>
            </div>
          </div>
          <button class="btn outline xs" data-revisar title="${esc(t("pastas.revisar_ajuda"))}">${icon("fact_check")} ${esc(t("pastas.revisar"))}</button>
          <button class="icon-btn plain sm" data-tirar title="${esc(t("pastas.parar"))}">${icon("delete")}</button>
        </div>`);
      const mudar = async (patch, msg) => {
        try {
          await api(`/api/pastas/${p.id}`, { method: "PATCH", body: patch });
          toast(msg);
        } catch (err) {
          toast(err.message, { error: true });
        }
      };
      el.querySelector("[data-modo]").onchange = (e) =>
        mudar({ modo: e.target.value }, t(e.target.value === "sozinho" ? "pastas.modo_sozinho_salvo" : "pastas.modo_perguntar_salvo"));
      el.querySelector("[data-sub]").onchange = (e) => mudar({ subpastas: e.target.checked }, t("pastas.salva"));
      el.querySelector("[data-revisar]").onclick = () => revisarPasta(p.id);
      el.querySelector("[data-tirar]").onclick = async () => {
        if (!(await confirmar(t("pastas.parar_confirmar", { nome: p.nome }), { sim: t("pastas.parar"), perigo: true }))) return;
        try {
          render((await api(`/api/pastas/${p.id}`, { method: "DELETE" })).pastas);
        } catch (err) {
          toast(err.message, { error: true });
        }
      };
      lista.append(el);
    }
    box.querySelector("[data-nova]").onclick = async () => {
      const r = await vigiarPasta();
      if (r) render(r.pastas);
    };
  }
  carregar();
}
