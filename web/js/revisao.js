// A janela de revisao: antes de importar muitas musicas de uma vez (uma pasta, o iTunes, uma pasta vigiada,
// depois um CD), a pessoa ve o que foi achado, agrupado por album, marca o que quer e corrige os nomes.
// O servidor guarda os caminhos: a pagina so conhece as referencias (karaoke/importacoes.py).
import { $, $$, api, esc, h, icon, openModal, perguntarOnde, toast } from "./common.js";
import { t } from "./i18n.js";
import { reconhecerDisco } from "./disco.js";

/* icons: album folder lyrics movie lock play_arrow stop expand_more chevron_right content_paste search check_box check_box_outline_blank library_add */
const LOTE = 40; // etiquetas por pedido
const MUITAS = 150; // acima disso, os grupos comecam fechados (o primeiro aberto)
const tempo = (s) => (s ? `${Math.floor(s / 60)}:${String(Math.round(s % 60)).padStart(2, "0")}` : "");
const semAcento = (s) => String(s || "").normalize("NFD").replace(/[\u0300-\u036f]/g, "").toLowerCase();

/**
 * Abre a revisao. `itens`: [{ref, nome, pasta, titulo, artista, faixa, video, etiquetas?}] (o que o servidor
 * listou; `etiquetas` ja lidas, como as do iTunes, pulam a leitura). `titulo`: o nome do que esta sendo importado
 * (a pasta, "iTunes"). `tipo`: "pasta" | "itunes" | "vigiada"... Resolve com o id da importacao, ou null.
 */
export function abrirRevisao({ titulo, itens, tipo = "pasta", cortado = false }) {
  const estado = itens.map((it, i) => ({
    ...it,
    i,
    marcado: true,
    editado: {}, // o que a pessoa mudou: so isso vai para o servidor (o resto, ele le das etiquetas)
    tags: it.etiquetas || null,
  }));
  for (const it of estado) if (it.tags) aplicarTags(it);
  const fechados = new Set();
  let filtro = "";
  let lidas = estado.filter((it) => it.tags).length;
  let pendenteRender = false;

  return new Promise((resolve) => {
    let resultado = null;
    const modal = openModal(t("revisao.titulo", { nome: titulo }), `
      <div class="rev-tools">
        <label class="rev-busca"><span class="ms">search</span><input class="input" data-busca placeholder="${esc(t("revisao.filtrar"))}"></label>
        <button class="btn outline sm" data-todas>${icon("check_box")} ${esc(t("revisao.marcar_todas"))}</button>
        <button class="btn outline sm" data-nenhuma>${icon("check_box_outline_blank")} ${esc(t("revisao.desmarcar"))}</button>
      </div>
      <p class="small muted rev-lendo" data-lendo></p>
      ${cortado ? `<p class="small rev-aviso">${esc(t("revisao.cortado", { n: itens.length }))}</p>` : ""}
      <div class="rev-lista" data-lista></div>
      <div class="rev-foot">
        <span class="small muted grow" data-conta></span>
        <button class="btn outline" data-cancelar>${esc(t("comum.cancelar"))}</button>
        <button class="btn light" data-importar data-nav-default>${icon("library_add")} <span data-rotulo></span></button>
      </div>`);
    modal.querySelector(".modal").classList.add("modal-wide", "rev-modal");
    const lista = $("[data-lista]", modal);
    const audio = new Audio();
    let tocando = null;

    // ------------------------------------------------------------ grupos (album, senao a pasta)
    function grupos() {
      const mapa = new Map();
      for (const it of estado) {
        const album = valor(it, "album");
        const chave = album ? `a:${semAcento(it.tags?.artista_album || valor(it, "artista"))}|${semAcento(album)}` : `p:${it.pasta}`;
        if (!mapa.has(chave)) mapa.set(chave, { chave, itens: [], album, pasta: it.pasta });
        mapa.get(chave).itens.push(it);
      }
      const out = [...mapa.values()];
      for (const g of out) {
        g.itens.sort((a, b) => (valor(a, "disco") || 1) - (valor(b, "disco") || 1)
          || (valor(a, "faixa") || 999) - (valor(b, "faixa") || 999) || a.i - b.i);
        const comTags = g.itens.find((it) => it.tags) || g.itens[0];
        g.artista = comTags.tags?.artista_album || valor(comTags, "artista") || "";
        g.ano = valor(comTags, "ano") || "";
        const comCapa = g.itens.find((it) => it.tags?.capa) || {};
        g.capa = comCapa.ref;
        g.capaV = comCapa.capaV || 0;
        g.disco = (g.itens.find((it) => it.disco) || {}).disco; // um album com .cue (ou o CD): da para reconhecer
        g.variosDiscos = new Set(g.itens.map((it) => valor(it, "disco") || 1)).size > 1; // faixa "2-3": disco 2
      }
      return out;
    }
    const visivel = (it) => !filtro || semAcento(`${valor(it, "titulo")} ${valor(it, "artista")} ${valor(it, "album")} ${it.nome}`).includes(filtro);
    const pode = (it) => !(it.tags && (it.tags.protegido || it.tags.sem_audio || it.tags.erro || it.tags.motivo));

    function render() {
      if (lista.contains(document.activeElement) && document.activeElement.tagName === "INPUT") {
        pendenteRender = true; // a pessoa esta digitando: redesenha quando sair do campo
        return;
      }
      pendenteRender = false;
      const rolagem = lista.closest(".modal-body").scrollTop;
      const gs = grupos();
      if (!render.iniciado && estado.length > MUITAS) gs.slice(1).forEach((g) => fechados.add(g.chave));
      render.iniciado = true;
      lista.innerHTML = "";
      for (const g of gs) {
        const vis = g.itens.filter(visivel);
        if (!vis.length) continue;
        const fechado = fechados.has(g.chave) && !filtro;
        const marcados = g.itens.filter((it) => it.marcado).length;
        const nome = g.album || g.pasta || titulo;
        const el = h(`
          <section class="rev-grupo${fechado ? " fechado" : ""}">
            <header class="rev-cab">
              <input type="checkbox" data-g ${marcados === g.itens.length ? "checked" : ""} title="${esc(t("revisao.marcar_grupo"))}">
              ${g.capa ? `<img class="rev-capa" src="/api/importar/capa/${encodeURIComponent(g.capa)}?v=${g.capaV}" alt="" loading="lazy">`
                : `<span class="rev-capa ms">${g.album ? "album" : "folder"}</span>`}
              <div class="grow rev-cab-txt">
                ${g.album ? `<input class="rev-album" data-album value="${esc(g.album)}" title="${esc(t("revisao.album"))}">`
                  : `<b>${esc(nome)}</b>`}
                <div class="small muted">${esc([g.artista, g.ano, t("comum.musicas", { n: g.itens.length })].filter(Boolean).join(" · "))}</div>
              </div>
              ${g.disco ? `<button class="btn ghost xs" data-reconhecer title="${esc(t("disco.reconhecer_ajuda"))}">${icon("album")} ${esc(t("disco.reconhecer"))}</button>` : ""}
              <button class="btn ghost xs" data-colar title="${esc(t("revisao.colar_ajuda"))}">${icon("content_paste")} ${esc(t("revisao.colar"))}</button>
              <button class="icon-btn plain" data-abrir title="${esc(t(fechado ? "revisao.abrir" : "revisao.fechar"))}">${icon(fechado ? "chevron_right" : "expand_more")}</button>
            </header>
            <div class="rev-faixas"></div>
          </section>`);
        const img = $("img.rev-capa", el);
        if (img) img.onerror = () => img.replaceWith(h(`<span class="rev-capa ms">${g.album ? "album" : "folder"}</span>`));
        const marcaG = $("[data-g]", el);
        marcaG.indeterminate = marcados > 0 && marcados < g.itens.length;
        marcaG.onchange = () => {
          g.itens.forEach((it) => (it.marcado = marcaG.checked && pode(it)));
          render();
        };
        $("[data-abrir]", el).onclick = () => {
          fechados.has(g.chave) ? fechados.delete(g.chave) : fechados.add(g.chave);
          render();
        };
        $("[data-colar]", el).onclick = () => colarNomes(g.itens.filter(visivel));
        const rec = $("[data-reconhecer]", el);
        if (rec) rec.onclick = () => reconhecer(g.disco, true);
        const alb = $("[data-album]", el);
        if (alb) alb.onchange = () => {
          g.itens.forEach((it) => editar(it, "album", alb.value.trim()));
          render();
        };
        if (!fechado) {
          const corpo = $(".rev-faixas", el);
          for (const it of vis) corpo.append(linha(it, g.variosDiscos));
        }
        lista.append(el);
      }
      if (!lista.children.length) lista.innerHTML = `<div class="empty small">${esc(t("revisao.nada_filtro"))}</div>`;
      lista.closest(".modal-body").scrollTop = rolagem;
      contar();
    }

    function linha(it, variosDiscos) {
      const num = valor(it, "faixa") ? `${variosDiscos ? `${valor(it, "disco") || 1}-` : ""}${valor(it, "faixa")}` : "";
      const tg = it.tags || {};
      const badges = [
        tg.letra ? `<span class="badge ok" title="${esc(t(`revisao.letra_${tg.letra}`))}">${icon("lyrics", "sm")} ${esc(t("revisao.tem_letra"))}</span>` : "",
        tg.video || it.video ? `<span class="badge gray">${icon("movie", "sm")} ${esc(t("revisao.video"))}</span>` : "",
        tg.protegido ? `<span class="badge warn" title="${esc(t("revisao.protegido_ajuda"))}">${icon("lock", "sm")} ${esc(t("revisao.protegido"))}</span>` : "",
        tg.sem_audio ? `<span class="badge warn">${esc(t("revisao.sem_audio"))}</span>` : "",
        tg.erro ? `<span class="badge warn" title="${esc(tg.erro)}">${esc(t("revisao.erro"))}</span>` : "",
        tg.motivo ? `<span class="badge warn" title="${esc(tg.motivo)}">${esc(t("revisao.indisponivel"))}</span>` : "",
      ].join("");
      const el = h(`
        <div class="rev-linha${pode(it) ? "" : " off"}">
          <input type="checkbox" data-m ${it.marcado ? "checked" : ""} ${pode(it) ? "" : "disabled"}>
          <span class="rev-num small muted">${num}</span>
          <input class="rev-campo" data-c="titulo" value="${esc(valor(it, "titulo"))}" placeholder="${esc(t("revisao.titulo_musica"))}" title="${esc(it.nome)}">
          <input class="rev-campo" data-c="artista" value="${esc(valor(it, "artista"))}" placeholder="${esc(t("revisao.artista"))}">
          <span class="rev-badges">${badges}</span>
          <span class="small muted rev-dur">${tempo(tg.duracao)}</span>
          <button class="icon-btn plain sm" data-ouvir title="${esc(t("revisao.ouvir"))}" ${pode(it) ? "" : "disabled"}>${icon(tocando === it.ref ? "stop" : "play_arrow")}</button>
        </div>`);
      $("[data-m]", el).onchange = (e) => {
        it.marcado = e.target.checked;
        contar();
        const g = el.closest(".rev-grupo");
        const caixas = $$("[data-m]:not(:disabled)", g);
        const m = $("[data-g]", g);
        m.checked = caixas.every((c) => c.checked);
        m.indeterminate = !m.checked && caixas.some((c) => c.checked);
      };
      $$("[data-c]", el).forEach((inp) => {
        inp.onchange = () => editar(it, inp.dataset.c, inp.value.trim());
        inp.onblur = () => pendenteRender && setTimeout(render, 0);
      });
      $("[data-ouvir]", el).onclick = (e) => ouvir(it, e.currentTarget);
      return el;
    }

    function contar() {
      const n = estado.filter((it) => it.marcado && pode(it)).length;
      $("[data-conta]", modal).textContent = t("revisao.marcadas", { n, total: estado.length });
      $("[data-rotulo]", modal).textContent = t("revisao.importar", { n });
      $("[data-importar]", modal).disabled = !n;
    }

    // ------------------------------------------------------------ ouvir um trecho
    function ouvir(it, botao) {
      if (tocando === it.ref) {
        audio.pause();
        tocando = null;
        botao.innerHTML = icon("play_arrow");
        return;
      }
      $$("[data-ouvir]", lista).forEach((b) => (b.innerHTML = icon("play_arrow")));
      tocando = it.ref;
      botao.innerHTML = '<span class="spinner"></span>';
      audio.src = `/api/importar/trecho/${encodeURIComponent(it.ref)}`;
      audio.play().then(() => tocando === it.ref && (botao.innerHTML = icon("stop"))).catch(() => {
        if (tocando !== it.ref) return;
        tocando = null;
        botao.innerHTML = icon("play_arrow");
        toast(t("importar.sem_trecho"), { error: true });
      });
    }
    audio.onended = () => {
      tocando = null;
      $$("[data-ouvir]", lista).forEach((b) => (b.innerHTML = icon("play_arrow")));
    };

    // ------------------------------------------------------------ colar uma lista de nomes (encarte, site)
    function colarNomes(alvos) {
      const m = openModal(t("revisao.colar_titulo"), `
        <p class="small muted" style="margin-top:0">${esc(t("revisao.colar_texto", { n: alvos.length }))}</p>
        <textarea class="input" rows="10" data-txt style="width:100%"></textarea>
        <div class="row" style="gap:10px;justify-content:flex-end;margin-top:12px">
          <button class="btn outline" data-no>${esc(t("comum.cancelar"))}</button>
          <button class="btn light" data-ok>${esc(t("revisao.colar_usar"))}</button>
        </div>`);
      $("[data-txt]", m).focus();
      $("[data-no]", m).onclick = () => m.close();
      $("[data-ok]", m).onclick = () => {
        const linhas = $("[data-txt]", m).value.split(/\r?\n/).map(nomeDaLinha).filter((l) => l.titulo);
        linhas.slice(0, alvos.length).forEach((l, k) => {
          editar(alvos[k], "titulo", l.titulo);
          if (l.artista) editar(alvos[k], "artista", l.artista);
        });
        m.close();
        render();
        if (linhas.length !== alvos.length) toast(t("revisao.colar_diferente", { linhas: linhas.length, n: alvos.length }));
      };
    }

    // ------------------------------------------------------------ reconhecer um disco (album com .cue, CD)
    async function reconhecer(did, perguntarSempre) {
      const novas = await reconhecerDisco(did, { perguntarSempre });
      if (!novas) return;
      for (const it of estado) {
        if (!novas[it.ref]) continue;
        it.tags = it.etiquetas = { ...it.tags, ...novas[it.ref] };
        it.capaV = Date.now();
        it.sem_nomes = false;
      }
      render();
    }

    // ------------------------------------------------------------ etiquetas aos poucos
    async function lerEtiquetas() {
      const faltam = estado.filter((it) => !it.tags);
      const total = estado.length;
      const aviso = $("[data-lendo]", modal);
      for (let k = 0; k < faltam.length && !resultado && modal.isConnected; k += LOTE) {
        aviso.textContent = t("revisao.lendo", { feitos: lidas, n: total });
        let r = {};
        try {
          r = await api("/api/importar/etiquetas", { method: "POST", body: { refs: faltam.slice(k, k + LOTE).map((it) => it.ref) } });
        } catch {
          /* le o resto mesmo assim: os sem etiquetas ficam com o palpite pelo nome */
        }
        for (const it of faltam.slice(k, k + LOTE)) {
          it.tags = r[it.ref] || { erro: "" };
          aplicarTags(it);
          lidas++;
        }
        render();
      }
      aviso.textContent = "";
    }

    // ------------------------------------------------------------ importar
    $("[data-busca]", modal).oninput = (e) => {
      filtro = semAcento(e.target.value.trim());
      render();
    };
    $("[data-todas]", modal).onclick = () => (estado.forEach((it) => (it.marcado = pode(it) && (visivel(it) || it.marcado))), render());
    $("[data-nenhuma]", modal).onclick = () => (estado.forEach((it) => visivel(it) && (it.marcado = false)), render());
    $("[data-cancelar]", modal).onclick = () => modal.close();
    $("[data-importar]", modal).onclick = async () => {
      const escolhidos = estado.filter((it) => it.marcado && pode(it));
      if (!escolhidos.length) return;
      const onde = await perguntarOnde("musica");
      if (onde === null) return;
      const botao = $("[data-importar]", modal);
      botao.disabled = true;
      try {
        const r = await api("/api/importar", { method: "POST", body: {
          titulo, tipo, onde, itens: escolhidos.map((it) => ({ ref: it.ref, dados: dadosDe(it) })),
          revisados: estado.map((it) => it.ref) } });
        resultado = r.id;
        toast(t("revisao.comecou", { n: r.total }));
        document.dispatchEvent(new CustomEvent("karaoke:refresh"));
        modal.close();
      } catch (err) {
        botao.disabled = false;
        toast(err.message, { error: true });
      }
    };
    modal.addEventListener("closed", () => {
      audio.pause();
      audio.removeAttribute("src");
      resolve(resultado);
    });

    render();
    lerEtiquetas();
    // album com .cue sem os nomes das faixas: reconhece sozinho (com varias edicoes, pergunta qual)
    (async () => {
      for (const did of new Set(estado.filter((it) => it.sem_nomes && it.disco).map((it) => it.disco))) {
        if (!modal.isConnected) return;
        await reconhecer(did, false);
      }
    })();
  });
}

// o valor que vale de um campo: o que a pessoa editou, senao o das etiquetas, senao o palpite pelo nome
function valor(it, campo) {
  if (campo in it.editado) return it.editado[campo];
  const tg = it.tags || {};
  if (tg[campo] !== undefined && tg[campo] !== null && tg[campo] !== "") return tg[campo];
  return it[campo] ?? "";
}

// o que vai para o servidor: o que a pessoa mudou; quando os nomes vieram da fonte (o iTunes), eles tambem (o servidor
// so le as etiquetas do arquivo, que podem estar diferentes do que a pessoa organizou la)
const CAMPOS = ["titulo", "artista", "album", "ano", "genero", "faixa", "disco"];
function dadosDe(it) {
  if (!it.etiquetas) return it.editado;
  const daFonte = Object.fromEntries(CAMPOS.filter((c) => it.etiquetas[c]).map((c) => [c, it.etiquetas[c]]));
  return { ...daFonte, ...it.editado };
}

function editar(it, campo, v) {
  if (String(valor(it, campo) ?? "") === String(v)) return;
  it.editado[campo] = v;
}

function aplicarTags(it) {
  const tg = it.tags || {};
  if (tg.protegido || tg.sem_audio || tg.motivo) it.marcado = false;
}

/** "03 - Artista - Musica (3:45)" -> {titulo: "Musica", artista: "Artista"} (a lista colada de um encarte). */
export function nomeDaLinha(linha) {
  let s = String(linha || "").trim().replace(/^\s*\d{1,3}\s*[-.)]\s*/, "").replace(/\s*\(?\d{1,2}:\d{2}\)?\s*$/, "").trim();
  const partes = s.split(/\s+[-–—]\s+/);
  if (partes.length >= 2) return { artista: partes[0].trim(), titulo: partes.slice(1).join(" - ").trim() };
  s = s.replace(/^["“]|["”]$/g, "");
  return { titulo: s, artista: "" };
}
