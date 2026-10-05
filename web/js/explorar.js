// O explorador de pastas do proprio app: quando o IOkê esta aberto no navegador do PC (sem a janela de pastas do
// Windows), a pessoa navega pelas pastas com cliques. O servidor lista (karaoke/explorar.py); so no PC.
import { api, esc, icon, openModal, toast } from "./common.js";
import { t } from "./i18n.js";
import { ACEITAS } from "./enviar.js";

/* icons: folder folder_open hard_drive library_music download desktop_windows description home arrow_upward description audio_file */

/** Escolher uma pasta. Resolve com o caminho ou null (fechou). */
export function escolherPasta({ titulo } = {}) {
  return explorar({ titulo: titulo || t("explorar.titulo_pasta") });
}

/** Escolher um arquivo com uma destas extensoes (".xml"). Resolve com o caminho ou null. */
export function escolherArquivo({ titulo, extensoes }) {
  return explorar({ titulo: titulo || t("explorar.titulo_arquivo"), extensoes });
}

function explorar({ titulo, extensoes = null }) {
  const arquivo = !!extensoes;
  return new Promise((resolve) => {
    let resposta = null;
    let atual = null; // a pasta aberta (null: o comeco, com os lugares e os discos)
    const modal = openModal(titulo, `
      <div class="exp-topo">
        <button class="icon-btn plain sm" data-acima title="${esc(t("explorar.acima"))}">${icon("arrow_upward")}</button>
        <div class="exp-caminho grow" data-caminho></div>
      </div>
      <div class="exp-lista" data-lista></div>
      <div class="row exp-rodape">
        <span class="small muted grow" data-info></span>
        <button class="btn outline" data-cancelar>${esc(t("comum.cancelar"))}</button>
        ${arquivo ? "" : `<button class="btn light" data-escolher data-nav-default>${icon("folder_open")} ${esc(t("explorar.escolher_esta"))}</button>`}
      </div>`);
    modal.querySelector(".modal").classList.add("modal-explorar");
    const lista = modal.querySelector("[data-lista]");
    const fim = (v) => {
      resposta = v;
      modal.close();
    };
    modal.addEventListener("closed", () => resolve(resposta));
    modal.querySelector("[data-cancelar]").onclick = () => fim(null);
    const escolher = modal.querySelector("[data-escolher]");
    if (escolher) escolher.onclick = () => atual && fim(atual.caminho);

    const linha = (ic, nome, extra = "") =>
      `<button class="exp-item" ${extra}><span class="ms">${ic}</span><span class="grow exp-nome">${esc(nome)}</span></button>`;

    async function abrir(caminho) {
      lista.innerHTML = `<div class="empty small"><span class="spinner"></span></div>`;
      let r;
      try {
        // escolhendo pasta, as musicas dela aparecem (apagadas): para conferir que e a pasta certa
        const ext = arquivo ? extensoes : ACEITAS;
        r = await api(`/api/explorar?caminho=${encodeURIComponent(caminho || "")}&ext=${ext.join(",")}`);
      } catch (err) {
        toast(err.message, { error: true });
        if (caminho) return abrir(atual ? atual.caminho : ""); // sem permissao: fica onde estava
        lista.innerHTML = `<div class="empty small">${esc(err.message)}</div>`;
        return;
      }
      atual = caminho ? r : null;
      modal.querySelector("[data-acima]").disabled = !caminho;
      modal.querySelector("[data-caminho]").textContent = caminho ? r.caminho : t("explorar.este_pc");
      if (escolher) escolher.disabled = !caminho;
      const info = modal.querySelector("[data-info]");
      info.textContent = caminho && !arquivo ? (r.musicas ? t("explorar.musicas_aqui", { n: r.musicas }) : t("explorar.sem_musicas_aqui")) : "";
      if (!caminho) {
        lista.innerHTML = [
          `<div class="exp-grupo">${esc(t("explorar.lugares"))}</div>`,
          ...r.lugares.map((l) => linha(l.icone || "folder", l.nome, `data-ir="${esc(l.caminho)}"`)),
          `<div class="exp-grupo">${esc(t("explorar.discos"))}</div>`,
          ...r.discos.map((d) => linha("hard_drive", d.nome, `data-ir="${esc(d.caminho)}"`)),
        ].join("");
      } else {
        lista.innerHTML = [
          ...r.pastas.map((p) => linha("folder", p.nome, `data-ir="${esc(p.caminho)}"`)),
          ...r.arquivos.map((a) => (arquivo ? linha("description", a.nome, `data-arquivo="${esc(a.caminho)}"`)
            : `<div class="exp-item off"><span class="ms">audio_file</span><span class="grow exp-nome">${esc(a.nome)}</span></div>`)),
        ].join("") || `<div class="empty small">${esc(t(arquivo ? "explorar.nada_arquivo" : "explorar.sem_subpastas"))}</div>`;
      }
      lista.querySelectorAll("[data-ir]").forEach((b) => (b.onclick = () => abrir(b.dataset.ir)));
      lista.querySelectorAll("[data-arquivo]").forEach((b) => (b.onclick = () => fim(b.dataset.arquivo)));
      lista.scrollTop = 0;
    }

    modal.querySelector("[data-acima]").onclick = () => atual && abrir(atual.pai || "");
    abrir("");
  });
}
