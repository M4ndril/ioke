// CDs: reconhecer o disco no MusicBrainz e escolher a edicao (o mesmo album sai em varias: a nacional, a importada,
// a remasterizada, com faixas a mais). Usado pela revisao (um album copiado com .cue) e pelo cartao do leitor de CD.
import { api, esc, h, icon, openModal, toast } from "./common.js";
import { t } from "./i18n.js";
import { abrirRevisao } from "./revisao.js";

/* icons: album album check search_off */

/**
 * Reconhece o disco e poe os nomes da edicao escolhida. Resolve com {ref: etiquetas} (os nomes novos das faixas)
 * ou null (sem internet, desconhecido ou a pessoa fechou). Com uma edicao so, usa ela sem perguntar.
 */
export async function reconhecerDisco(did, { perguntarSempre = false } = {}) {
  let r;
  try {
    r = await api(`/api/disco/${did}/identificar`, { method: "POST", timeout: 60000 });
  } catch (err) {
    toast(err.message, { error: true });
    return null;
  }
  if (!r.edicoes.length) {
    toast(t("disco.desconhecido_texto"), { ms: 6000 });
    return null;
  }
  const id = r.edicoes.length === 1 && !perguntarSempre ? r.edicoes[0].id : await escolherEdicao(r.edicoes, r.escolhida);
  if (id === undefined) return null;
  try {
    return (await api(`/api/disco/${did}/edicao`, { method: "POST", body: { id } })).etiquetas;
  } catch (err) {
    toast(err.message, { error: true });
    return null;
  }
}

/** A janela de escolher a edicao. Resolve com o id, null ("nenhuma destas") ou undefined (fechou). */
function escolherEdicao(edicoes, escolhida) {
  return new Promise((resolve) => {
    let feito = false;
    const detalhes = (e) => [e.ano, e.pais, [e.selo, e.catalogo].filter(Boolean).join(" "),
      e.discos > 1 ? t("disco.disco_de", { n: e.disco, de: e.discos }) : "", t("comum.musicas", { n: e.faixas })]
      .filter(Boolean).join(" · ");
    const modal = openModal(t("disco.escolher_titulo"), `
      <p class="small muted" style="margin-top:0">${esc(t("disco.escolher_texto", { n: edicoes.length }))}</p>
      <div class="ed-lista">${edicoes.map((e) => `
        <button class="ed-row${e.id === escolhida ? " on" : ""}" data-id="${esc(e.id)}">
          ${e.capa ? `<img class="ed-capa" src="${esc(e.capa)}" alt="" loading="lazy">` : `<span class="ed-capa ms">album</span>`}
          <span class="grow ed-txt">
            <b>${esc(e.titulo)}</b> <span class="muted">${esc(e.artista)}</span>
            <span class="small muted">${esc(detalhes(e))}</span>
            <span class="small muted ed-nomes">${esc(e.nomes.slice(0, 4).join(" · "))}${e.nomes.length > 4 ? " …" : ""}</span>
          </span>
          ${e.id === escolhida ? icon("check") : ""}
        </button>`).join("")}
      </div>
      <div class="row" style="justify-content:flex-end;margin-top:12px">
        <button class="btn outline" data-nenhuma>${icon("search_off")} ${esc(t("disco.nenhuma"))}</button>
      </div>`);
    modal.querySelectorAll("img.ed-capa").forEach((img) => (img.onerror = () => img.replaceWith(h('<span class="ed-capa ms">album</span>'))));
    const fim = (v) => {
      feito = true;
      modal.close();
      resolve(v);
    };
    modal.querySelectorAll("[data-id]").forEach((b) => (b.onclick = () => fim(b.dataset.id)));
    modal.querySelector("[data-nenhuma]").onclick = () => fim(null);
    modal.addEventListener("closed", () => !feito && resolve(undefined));
  });
}

/** O CD do leitor: reconhece (se ainda falta escolher a edicao) e abre a revisao. Resolve com o id da importacao. */
export async function importarDisco(disco) {
  if (disco.estado === "pronto" && !disco.escolhida && disco.edicoes > 1) await reconhecerDisco(disco.id);
  let r;
  try {
    r = await api(`/api/disco/${disco.id}/revisar`, { method: "POST" });
  } catch (err) {
    toast(err.message, { error: true });
    return null;
  }
  return abrirRevisao({ titulo: r.nome, itens: r.itens, tipo: "cd" });
}
