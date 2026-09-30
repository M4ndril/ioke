// Enviar os proprios arquivos (so no PC). No app instalado, a janela do Windows
// escolhe e o servidor copia do disco (o arquivo da pessoa fica onde estava); no
// navegador, cada arquivo vai por HTTP, com a barra do envio.
import { $, $$, api, esc, h, icon, openModal, perguntarOnde, toast } from "./common.js";
import { appApi } from "./appwin.js";
import { idioma, t } from "./i18n.js";
import { resolverRepetidos } from "./pacotes.js";

/* icons: upload_file audio_file folder_open check_circle error content_copy */
export const ACEITAS = [".mp3", ".m4a", ".aac", ".flac", ".wav", ".ogg", ".opus", ".wma", ".aiff", ".aif",
  ".mp4", ".m4v", ".mkv", ".webm", ".mov", ".avi"];
// pacote .karaoke de outro PC; o Google Drive (e outros) as vezes acrescenta ".zip" no nome: vale tambem
const ePacote = (nome) => /\.(karaoke|zip)$/i.test(nome);
const ok = (nome) => ACEITAS.some((ext) => nome.toLowerCase().endsWith(ext)) || nome.toLowerCase().endsWith(".m4p") || ePacote(nome);
const mb = (n) => (n >= 1e9 ? `${(n / 1e9).toFixed(1)} GB` : `${Math.max(0.1, n / 1e6).toFixed(1)} MB`);

export function mountEnviar(box, { onDone } = {}) {
  box.innerHTML = `
    <div class="drop" data-drop>
      <span class="ms drop-icon">upload_file</span>
      <div class="grow"><b>${t("enviar.titulo")}</b><div class="small muted">${t("enviar.texto")}</div></div>
      <div class="row wrap drop-actions">
        <button class="btn sm" data-files>${icon("audio_file")} ${t("enviar.escolher_arquivos")}</button>
        <button class="btn outline sm" data-folder>${icon("folder_open")} ${t("enviar.escolher_pasta")}</button>
      </div>
    </div>
    <input type="file" data-input multiple hidden accept="${[...ACEITAS, ".karaoke", ".zip"].join(",")}">
    <input type="file" data-input-folder multiple hidden webkitdirectory>
    <div class="upload-list" data-list></div>
    <p class="small muted upload-formats">${t("enviar.formatos", { formatos: ACEITAS.join(" ") })}</p>`;
  const list = box.querySelector("[data-list]");
  const drop = box.querySelector("[data-drop]");

  const linha = (nome, tamanho) => {
    const el = h(`<div class="up-row"><span class="ms">audio_file</span>
      <div class="grow"><div class="up-name">${esc(nome)}</div>
        <div class="progress"><i style="width:0%"></i></div><div class="small muted up-state">${t("enviar.enviando")}</div></div>
      <span class="small muted">${tamanho ? mb(tamanho) : ""}</span></div>`);
    list.prepend(el);
    return el;
  };
  const marcar = (el, estado, texto) => {
    el.classList.add(estado);
    el.querySelector(".progress").classList.add("hidden");
    el.querySelector(".up-state").textContent = texto;
    el.querySelector(".ms").textContent = estado === "err" ? "error" : estado === "rep" ? "content_copy" : "check_circle";
  };
  const resultado = (r, linhas) => {
    const porNome = (nome) => linhas.find((l) => l.nome === nome && !l.feito) || linhas.find((l) => !l.feito);
    for (const m of r.musicas || []) {
      const l = porNome(m.origem && m.origem.nome);
      if (l) (l.feito = true), marcar(l.el, "ok", t("enviar.na_fila"));
    }
    for (const m of r.repetidas || []) {
      const l = porNome(m.origem && m.origem.nome);
      if (l) (l.feito = true), marcar(l.el, "rep", t("enviar.repetida"));
    }
    for (const x of r.recusados || []) {
      const l = porNome(x.nome);
      if (l) (l.feito = true), marcar(l.el, "err", x.motivo);
    }
    onDone && onDone();
  };

  // pacotes: importados prontos (sem separar); id repetido, a pessoa escolhe
  const lembrada = { escolha: null };
  const pacotesProntos = async (r, linhas) => {
    await resolverRepetidos(r.resultados || [], (item, res) => {
      const l = linhas.find((x) => x.nome === item.nome && !x.feito);
      if (!l) return;
      l.feito = true;
      if (res.estado === "importada") marcar(l.el, "ok", t("pacotes.importada"));
      else if (res.estado === "pulada") marcar(l.el, "rep", t("pacotes.pulada"));
      else marcar(l.el, "err", res.erro || res.estado);
    }, lembrada);
    onDone && onDone();
  };

  // navegador: um arquivo por pedido, com a barra do envio
  const enviarArquivo = (file, onde) => new Promise((resolve) => {
    const el = linha(file.name, file.size);
    if (!ok(file.name)) {
      marcar(el, "err", t("arquivo.recusado.formato", { nome: file.name }));
      return resolve();
    }
    const pacote = ePacote(file.name);
    const form = new FormData();
    form.append(pacote ? "pacote" : "arquivos", file, file.name);
    if (onde && !pacote) form.append("onde", onde);
    const xhr = new XMLHttpRequest();
    xhr.open("POST", pacote ? "/api/pacotes/importar" : "/api/arquivos");
    xhr.setRequestHeader("X-Idioma", idioma()); // as mensagens do servidor no idioma da pagina
    xhr.upload.onprogress = (e) => e.lengthComputable && (el.querySelector(".progress i").style.width = `${(e.loaded / e.total) * 100}%`);
    xhr.onload = () => {
      let r = {};
      try {
        r = JSON.parse(xhr.responseText);
      } catch {
        /* sem corpo */
      }
      if (xhr.status >= 400) marcar(el, "err", r.error || `erro ${xhr.status}`);
      else if (pacote) {
        el.querySelector(".up-state").textContent = t("pacotes.importando");
        return pacotesProntos(r, [{ nome: file.name, el }]).then(resolve);
      } else {
        el.querySelector(".up-state").textContent = t("enviar.preparando");
        resultado(r, [{ nome: file.name, el }]);
      }
      resolve();
    };
    xhr.onerror = () => (marcar(el, "err", t("enviar.falhou")), resolve());
    xhr.send(form);
  });
  const enviarLista = async (files) => {
    // pacote nao separa: so pergunta onde separar se tiver musica para separar
    const onde = files.some((f) => ok(f.name) && !ePacote(f.name)) ? await perguntarOnde("musica") : undefined;
    if (onde === null) return;
    for (const f of files) await enviarArquivo(f, onde); // um de cada vez: o PC nao engasga
  };

  // app: caminhos do disco (copia; o arquivo da pessoa fica onde estava)
  const enviarCaminhos = async (todos) => {
    const pacotes = todos.filter(ePacote);
    if (pacotes.length) {
      const lp = pacotes.map((c) => ({ nome: c.split(/[\\/]/).pop(), el: null }));
      lp.forEach((l) => (l.el = linha(l.nome)));
      for (const [i, c] of pacotes.entries()) {
        try {
          await pacotesProntos(await api("/api/pacotes/importar", { method: "POST", body: { caminhos: [c] } }), [lp[i]]);
        } catch (err) {
          marcar(lp[i].el, "err", err.message);
        }
      }
    }
    const caminhos = todos.filter((c) => !ePacote(c));
    if (!caminhos.length) return;
    const onde = await perguntarOnde("musica");
    if (onde === null) return;
    const linhas = caminhos.map((c) => ({ nome: c.split(/[\\/]/).pop(), el: null }));
    linhas.forEach((l) => (l.el = linha(l.nome)));
    for (let i = 0; i < caminhos.length; i += 10) {
      const lote = caminhos.slice(i, i + 10);
      try {
        resultado(await api("/api/arquivos/caminhos", { method: "POST", body: { caminhos: lote, onde } }), linhas.slice(i, i + 10));
      } catch (err) {
        linhas.slice(i, i + 10).forEach((l) => marcar(l.el, "err", err.message));
      }
    }
  };

  box.querySelector("[data-files]").onclick = async () => {
    const app = await appApi();
    if (app && app.escolher_arquivos) {
      const caminhos = await app.escolher_arquivos();
      if (caminhos && caminhos.length) enviarCaminhos(caminhos);
    } else box.querySelector("[data-input]").click();
  };
  box.querySelector("[data-folder]").onclick = async () => {
    const app = await appApi();
    if (!app || !app.escolher_pasta_musicas) return box.querySelector("[data-input-folder]").click();
    const pasta = await app.escolher_pasta_musicas();
    if (!pasta) return;
    let r;
    try {
      r = await api("/api/arquivos/pasta", { method: "POST", body: { pasta } });
    } catch (err) {
      return toast(err.message, { error: true });
    }
    if (!r.arquivos.length) return toast(t("enviar.pasta_vazia"));
    const modal = openModal(t("enviar.pasta_titulo"), `
      <p style="margin-top:0">${t("enviar.pasta_achou", { n: r.arquivos.length })}${r.cortado ? ` ${t("enviar.pasta_cortado")}` : ""}</p>
      <div class="upload-list" style="max-height:40vh;overflow:auto">${r.arquivos.map((a) =>
        `<div class="up-row"><span class="ms">audio_file</span><div class="grow up-name">${esc(a.nome)}</div><span class="small muted">${mb(a.tamanho)}</span></div>`).join("")}</div>
      <div class="row" style="gap:10px;justify-content:flex-end;margin-top:12px">
        <button class="btn outline" data-no>${t("comum.cancelar")}</button>
        <button class="btn light" data-yes data-nav-default>${icon("upload_file")} ${t("enviar.enviar_todos")}</button>
      </div>`);
    $("[data-no]", modal).onclick = () => modal.close();
    $("[data-yes]", modal).onclick = () => {
      modal.close();
      enviarCaminhos(r.arquivos.map((a) => a.caminho));
    };
  };
  box.querySelector("[data-input]").onchange = (e) => enviarLista([...e.target.files]).then(() => (e.target.value = ""));
  box.querySelector("[data-input-folder]").onchange = (e) =>
    enviarLista([...e.target.files].filter((f) => ok(f.name))).then(() => (e.target.value = ""));

  // arrastar e soltar: na area ou em qualquer lugar da pagina
  const temArquivos = (e) => [...(e.dataTransfer?.types || [])].includes("Files");
  document.addEventListener("dragover", (e) => {
    if (!temArquivos(e)) return;
    e.preventDefault();
    drop.classList.add("over");
  });
  document.addEventListener("dragleave", (e) => e.relatedTarget === null && drop.classList.remove("over"));
  document.addEventListener("drop", (e) => {
    if (!temArquivos(e)) return;
    e.preventDefault();
    drop.classList.remove("over");
    enviarLista([...e.dataTransfer.files]);
  });
}
