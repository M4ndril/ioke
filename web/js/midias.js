// Os cartoes "de onde vem as musicas" do Adicionar (so no PC): a biblioteca do iTunes / Apple Music e as pastas
// vigiadas. Cada um abre a revisao (revisao.js) antes de importar.
import { $, api, esc, icon, openModal, toast } from "./common.js";
import { appApi } from "./appwin.js";
import { t } from "./i18n.js";
import { abrirRevisao } from "./revisao.js";
import { revisarNovas, vigiarPasta } from "./pastas.js";
import { openSettings } from "./settings.js";

/* icons: library_music queue_music folder_special chevron_right */
const POLL = 30000;

export function mountMidias(box, { onDone } = {}) {
  box.innerHTML = `
    <button class="fonte-card hidden" data-itunes>
      <span class="ms fonte-ic">library_music</span>
      <span class="grow"><b>${esc(t("itunes.titulo"))}</b><span class="small muted" data-sub></span></span>
      <span class="ms">chevron_right</span>
    </button>
    <button class="fonte-card hidden" data-pastas>
      <span class="ms fonte-ic">folder_special</span>
      <span class="grow"><b>${esc(t("pastas.titulo"))}</b><span class="small muted" data-sub></span></span>
      <span class="badge ok hidden" data-n></span>
      <span class="ms">chevron_right</span>
    </button>`;
  const itunes = $("[data-itunes]", box);
  const pastas = $("[data-pastas]", box);
  let infoItunes = null;
  let infoPastas = null;
  const feito = (id) => id && onDone && onDone();

  async function olharItunes() {
    try {
      infoItunes = await api("/api/bibliotecas/itunes");
    } catch {
      return; // outro computador (so o PC importa) ou servidor antigo
    }
    itunes.classList.remove("hidden");
    $("[data-sub]", itunes).textContent = infoItunes.xml
      ? t("itunes.achou", { n: infoItunes.total, p: infoItunes.playlists.length })
      : infoItunes.pasta ? t("itunes.so_pasta") : t("itunes.nao_achou");
  }

  async function olharPastas() {
    try {
      const [lista, novas] = await Promise.all([api("/api/pastas"), api("/api/pastas/novas")]);
      infoPastas = { n: lista.pastas.length, novas: novas.n };
    } catch {
      return;
    }
    pastas.classList.remove("hidden");
    $("[data-sub]", pastas).textContent = !infoPastas.n ? t("pastas.cartao_nenhuma")
      : infoPastas.novas ? t("pastas.cartao_novas", { n: infoPastas.novas }) : t("pastas.cartao_nada", { n: infoPastas.n });
    const badge = $("[data-n]", pastas);
    badge.textContent = infoPastas.novas;
    badge.classList.toggle("hidden", !infoPastas.novas);
  }

  itunes.onclick = async () => {
    if (!infoItunes) return;
    if (infoItunes.xml && infoItunes.playlists.length) return escolherPlaylist();
    if (infoItunes.xml || infoItunes.pasta) return revisarItunes();
    semItunes();
  };

  async function revisarItunes(playlist, nome) {
    const sub = $("[data-sub]", itunes);
    const antes = sub.textContent;
    itunes.disabled = true;
    sub.textContent = t("itunes.lendo");
    let r;
    try {
      r = await api("/api/bibliotecas/itunes/itens", { method: "POST", body: { playlist } });
    } catch (err) {
      toast(err.message, { error: true });
    }
    itunes.disabled = false;
    sub.textContent = antes;
    if (!r) return;
    if (!r.itens.length) return toast(t("itunes.vazia"));
    feito(await abrirRevisao({ titulo: nome || r.nome, itens: r.itens, tipo: "itunes", cortado: r.cortado }));
  }

  function escolherPlaylist() {
    const linha = (id, nome, n, ic) => `<button class="pl-row" data-pl="${esc(id)}" data-nome="${esc(nome)}">${icon(ic)}
      <span class="grow">${esc(nome)}</span><span class="small muted">${esc(t("comum.musicas", { n }))}</span></button>`;
    const modal = openModal(t("itunes.titulo"), `
      <p class="small muted" style="margin-top:0">${esc(t("itunes.escolha"))}</p>
      <div class="pl-lista">
        ${linha("", t("itunes.tudo"), infoItunes.total, "library_music")}
        ${infoItunes.playlists.map((p) => linha(p.id, p.nome, p.n, "queue_music")).join("")}
      </div>`);
    modal.querySelectorAll("[data-pl]").forEach((b) => (b.onclick = () => {
      modal.close();
      revisarItunes(b.dataset.pl || undefined, b.dataset.pl ? b.dataset.nome : "iTunes");
    }));
  }

  function semItunes() {
    const modal = openModal(t("itunes.titulo"), `
      <p style="margin-top:0">${esc(t("itunes.nao_achou_texto"))}</p>
      <p class="small muted">${esc(t("itunes.compartilhar"))}</p>
      <div class="row" style="gap:10px;justify-content:flex-end;margin-top:12px">
        <button class="btn light" data-xml>${esc(t("itunes.procurar_xml"))}</button>
      </div>`);
    $("[data-xml]", modal).onclick = async () => {
      const app = await appApi();
      const caminho = app && app.escolher_xml_itunes ? await app.escolher_xml_itunes() : prompt(t("itunes.digite_xml"));
      if (!caminho) return;
      try {
        infoItunes = await api("/api/bibliotecas/itunes/xml", { method: "POST", body: { caminho } });
        modal.close();
        olharItunes();
        itunes.click();
      } catch (err) {
        toast(err.message, { error: true });
      }
    };
  }

  pastas.onclick = async () => {
    if (!infoPastas) return;
    if (infoPastas.novas) {
      feito(await revisarNovas());
    } else if (!infoPastas.n) {
      if (await vigiarPasta()) toast(t("pastas.primeira"), { ms: 8000 });
    } else {
      openSettings({ tab: "musicas" });
    }
    olharPastas();
  };

  olharItunes();
  olharPastas();
  setInterval(olharPastas, POLL);
  document.addEventListener("karaoke:refresh", olharPastas);
}
