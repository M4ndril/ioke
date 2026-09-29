// Pacotes .karaoke (so no PC): exportar musicas prontas e importar pacotes de outro PC.
import { api, esc, icon, openModal, toast } from "./common.js";
import { appApi } from "./appwin.js";
import { t } from "./i18n.js";

/* icons: inventory_2 download */

/** Exporta as musicas `ids`. No app, pergunta a pasta; no navegador, baixa cada pacote. */
export async function exportarPacotes(ids) {
  if (!ids.length) return;
  const app = await appApi();
  let destino = null;
  if (app && app.choose_folder) {
    destino = await app.choose_folder("");
    if (!destino) return;
  }
  let tarefa;
  try {
    tarefa = await api("/api/pacotes/exportar", { method: "POST", body: { ids, destino } });
  } catch (err) {
    return toast(err.message, { error: true });
  }
  toast(t("pacotes.exportando", { n: ids.length }), { key: "pacotes", ms: 60000 });
  for (;;) {
    await new Promise((r) => setTimeout(r, 1000));
    const st = await api(`/api/pacotes/tarefas/${tarefa.id}`).catch(() => null);
    if (!st) return toast(t("pacotes.falhou"), { error: true, key: "pacotes" });
    if (st.estado !== "pronta") {
      toast(t("pacotes.exportando_n", { feitos: st.feitos, total: st.total }), { key: "pacotes", ms: 60000 });
      continue;
    }
    if (st.baixar) {
      for (const a of st.arquivos) {
        const link = document.createElement("a");
        link.href = `/api/pacotes/baixar/${st.id}/${encodeURIComponent(a.nome)}`;
        link.download = a.nome;
        document.body.append(link);
        link.click();
        link.remove();
        await new Promise((r) => setTimeout(r, 400));
      }
    }
    const erros = st.erros.length ? ` ${t("pacotes.com_erros", { n: st.erros.length })}` : "";
    toast(t("pacotes.exportados", { n: st.arquivos.length }) + erros, { key: "pacotes", error: !!st.erros.length, ms: 6000 });
    return;
  }
}

/** A musica do pacote ja existe: a pessoa escolhe (e pode valer para as proximas). */
function perguntar(item) {
  return new Promise((resolve) => {
    const m = openModal(t("pacotes.existe_titulo"), `
      <p style="margin-top:0">${t("pacotes.existe_texto", { titulo: esc(item.titulo || item.nome) })}</p>
      <label class="toggle-row small"><input type="checkbox" data-todas> ${t("pacotes.todas")}</label>
      <div class="row wrap" style="gap:10px;justify-content:flex-end;margin-top:14px">
        <button class="btn outline" data-e="pular">${t("pacotes.pular")}</button>
        <button class="btn outline" data-e="manter">${t("pacotes.manter")}</button>
        <button class="btn light" data-e="substituir">${t("pacotes.substituir")}</button>
      </div>`, { fixo: true });
    m.querySelectorAll("[data-e]").forEach((b) => (b.onclick = () => {
      const todas = m.querySelector("[data-todas]").checked;
      m.close();
      resolve({ escolha: b.dataset.e, todas });
    }));
  });
}

/** Resolve os pacotes com id repetido (um de cada vez). `marcar(item, resultado)` atualiza a linha. */
export async function resolverRepetidos(resultados, marcar, lembrada = { escolha: null }) {
  for (const r of resultados) {
    if (r.estado !== "existe") {
      marcar(r, r);
      continue;
    }
    let escolha = lembrada.escolha;
    if (!escolha) {
      const resp = await perguntar(r);
      escolha = resp.escolha;
      if (resp.todas) lembrada.escolha = escolha;
    }
    try {
      marcar(r, await api("/api/pacotes/decidir", { method: "POST", body: { token: r.token, escolha } }));
    } catch (err) {
      marcar(r, { estado: "erro", erro: err.message });
    }
  }
}

/** O botao "Exportar pacote" (menu da musica). */
export function botaoExportar(song) {
  return `<button class="btn outline sm" data-exportar-pacote="${esc(song.id)}">${icon("inventory_2")} ${t("pacotes.exportar")}</button>`;
}
