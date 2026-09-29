// Traducao dos textos (portugues e ingles). A fonte e web/i18n/<idioma>.json, a mesma
// que o servidor usa (karaoke/i18n.py). No PC vale o idioma do PC (/api/info); no
// celular, o do aparelho, com a opcao de trocar (guardada neste aparelho).
import { $$, api, setIdiomaAtual, store } from "./common.js";

export const IDIOMAS = ["pt-BR", "en"];
let atual = "pt-BR";
const cache = {};

export function normalizar(tag) {
  const s = String(tag || "").trim().replace("_", "-").toLowerCase();
  if (!s || s === "auto") return null;
  return s.startsWith("pt") ? "pt-BR" : "en";
}

async function carregar(idioma) {
  if (!cache[idioma]) {
    try {
      cache[idioma] = await (await fetch(`/static/i18n/${idioma}.json`, { cache: "no-cache" })).json();
    } catch {
      cache[idioma] = {};
    }
  }
  return cache[idioma];
}

/** Descobre o idioma e carrega os textos. `celular`: o idioma do aparelho (ou o escolhido nele). */
export async function initI18n({ celular = false } = {}) {
  let idioma = null;
  if (celular) idioma = normalizar(store("karaoke.idioma")) || normalizar(navigator.language);
  else {
    try {
      idioma = normalizar((await api("/api/info")).idioma);
    } catch {
      idioma = normalizar(navigator.language);
    }
  }
  atual = idioma || "pt-BR";
  setIdiomaAtual(atual);
  document.documentElement.lang = atual;
  await Promise.all([carregar("pt-BR"), carregar(atual)]);
  traduzirDom();
  return atual;
}

export const idioma = () => atual;

/** Texto traduzido. Parametros entre chaves; plural pelo parametro `n`. */
export function t(key, params = {}) {
  let msg = (cache[atual] || {})[key];
  if (msg === undefined) msg = (cache["pt-BR"] || {})[key];
  if (msg === undefined) return key;
  if (typeof msg === "object") msg = (params.n === 1 ? msg.one : msg.other) ?? msg.other ?? key;
  return String(msg).replace(/\{(\w+)\}/g, (m, k) => (k in params ? String(params[k]) : m));
}

/** Preenche os elementos com data-i18n (texto), data-i18n-html, data-i18n-title, -placeholder e -aria. */
export function traduzirDom(raiz = document) {
  $$("[data-i18n]", raiz).forEach((el) => (el.textContent = t(el.dataset.i18n)));
  $$("[data-i18n-html]", raiz).forEach((el) => (el.innerHTML = t(el.dataset.i18nHtml))); // textos nossos, com <b>
  $$("[data-i18n-title]", raiz).forEach((el) => (el.title = t(el.dataset.i18nTitle)));
  $$("[data-i18n-placeholder]", raiz).forEach((el) => (el.placeholder = t(el.dataset.i18nPlaceholder)));
  $$("[data-i18n-alt]", raiz).forEach((el) => (el.alt = t(el.dataset.i18nAlt)));
  $$("[data-i18n-aria]", raiz).forEach((el) => el.setAttribute("aria-label", t(el.dataset.i18nAria)));
}

/** No celular: trocar o idioma (fica neste aparelho) e recarregar. */
export function escolherIdiomaCelular(novo) {
  store("karaoke.idioma", novo);
  location.reload();
}
