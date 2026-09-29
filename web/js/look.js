// Visual do player: o padrao (Configuracoes -> Player) e o de cada musica
// ("Visual: Padrao | Proprio"). Aqui ficam o que da para ajustar, como aplicar
// num palco (o do player ou a previa das Configuracoes) e os controles, os
// mesmos nos dois lugares. O padrao fica no servidor (karaoke/look.py).
import { $$, api, esc, icon, store } from "./common.js";
import { t } from "./i18n.js";

export const LOOK_KEYS = [
  "background", "blur", "tint_color", "tint_opacity", "text_size", "text_color", "brightness",
  "stroke_color", "stroke_width", "shadow_color", "shadow_opacity", "shadow_x", "shadow_y", "shadow_blur",
  "wipe", "wipe_color",
];

const PALETTES = {
  text: ["#ffffff", "#fff4c2", "#ffd23f", "#4fc3f7", "#ff9ecf", "#000000"],
  wipe: ["#4fc3f7", "#ffd23f", "#ff5fa2", "#5ee27a", "#ff3b47", "#ffffff"],
  tint: ["#000000", "#12082e", "#06213d", "#2e0808", "#06301a", "#ffffff"],
  dark: ["#000000", "#1b1b1f", "#2e0808", "#06213d", "#ffffff", "#ffd23f"],
};
const pct = (v) => `${Math.round(v * 100)}%`;
const px = (v) => `${Math.round(v * 10) / 10}px`;

/* icons: wallpaper blur_on format_color_fill opacity format_size format_color_text contrast format_paint palette */
/* icons: border_style border_color blur_linear swap_horiz swap_vert light_mode */
// o que aparece em cada grupo (a ordem e a da tela)
const GROUPS = {
  fundo: [
    { k: "background", key: "visual.c_background", type: "seg", icon: "wallpaper", options: [["cover", "visual.capa"], ["video", "visual.video"]] },
    { k: "blur", key: "visual.c_blur", type: "range", icon: "blur_on", min: 0, max: 80, step: 1, fmt: (v) => `${Math.round(v)}` },
    { k: "tint_color", key: "visual.c_tint_color", type: "color", icon: "format_color_fill", palette: "tint" },
    { k: "tint_opacity", key: "visual.c_tint_opacity", type: "range", icon: "opacity", min: 0, max: 1, step: 0.01, fmt: pct },
  ],
  letra: [
    { k: "text_size", key: "visual.c_text_size", type: "range", icon: "format_size", min: 0.6, max: 2.2, step: 0.05, fmt: pct },
    { k: "text_color", key: "visual.c_text_color", type: "color", icon: "format_color_text", palette: "text" },
    { k: "brightness", key: "visual.c_brightness", type: "range", icon: "contrast", min: 0.05, max: 1, step: 0.01, fmt: pct,
      title: "visual.t_brightness" },
    { k: "wipe", key: "visual.c_wipe", type: "seg", icon: "format_paint", options: [[false, "comum.nao"], [true, "comum.sim"]],
      title: "visual.t_wipe" },
    { k: "wipe_color", key: "visual.c_wipe_color", type: "color", icon: "palette", palette: "wipe", needs: "wipe" },
  ],
  borda: [
    { k: "stroke_width", key: "visual.c_stroke_width", type: "range", icon: "border_style", min: 0, max: 8, step: 0.5, fmt: px },
    { k: "stroke_color", key: "visual.c_stroke_color", type: "color", icon: "border_color", palette: "dark" },
    { k: "shadow_opacity", key: "visual.c_shadow_opacity", type: "range", icon: "light_mode", min: 0, max: 1, step: 0.01, fmt: pct },
    { k: "shadow_color", key: "visual.c_shadow_color", type: "color", icon: "format_color_fill", palette: "dark" },
    { k: "shadow_blur", key: "visual.c_shadow_blur", type: "range", icon: "blur_linear", min: 0, max: 60, step: 1, fmt: px },
    { k: "shadow_x", key: "visual.c_shadow_x", type: "range", icon: "swap_horiz", min: -30, max: 30, step: 1, fmt: px },
    { k: "shadow_y", key: "visual.c_shadow_y", type: "range", icon: "swap_vert", min: -30, max: 30, step: 1, fmt: px },
  ],
};
const GROUP_TITLES = { fundo: "visual.fundo", letra: "visual.letra", borda: "visual.borda" };

// ------------------------------------------------------------ aplicar
export function rgba(hex, a) {
  const n = parseInt(String(hex || "#000000").slice(1), 16);
  return `rgba(${(n >> 16) & 255}, ${(n >> 8) & 255}, ${n & 255}, ${Math.round(a * 1000) / 1000})`;
}

/** Poe o visual num palco (variaveis CSS que o player.css / a previa usam). */
export function applyLook(el, look) {
  const s = el.style;
  s.setProperty("--blur", `${look.blur}px`);
  s.setProperty("--dim", look.brightness);
  s.setProperty("--ts", look.text_size);
  s.setProperty("--lyric", look.text_color);
  s.setProperty("--tint", rgba(look.tint_color, look.tint_opacity));
  s.setProperty("--stroke-w", `${look.stroke_width}px`);
  s.setProperty("--stroke-c", look.stroke_color);
  // a linha da vez usa a sombra escolhida; as outras, a mesma mais suave (como antes)
  const shadow = (k, a) => `${look.shadow_x * k}px ${look.shadow_y * k}px ${look.shadow_blur * k}px ${rgba(look.shadow_color, look.shadow_opacity * a)}`;
  s.setProperty("--shadow", look.shadow_opacity > 0 ? shadow(1, 1) : "none");
  s.setProperty("--shadow-rest", look.shadow_opacity > 0 ? shadow(0.55, 0.83) : "none");
  s.setProperty("--sung", look.wipe_color);
  el.classList.toggle("wipe-on", !!look.wipe);
}

// ----------------------------------------------------- o padrao (servidor)
let globalCache = null;

/** O visual padrao. Na primeira vez, traz o que ficava so neste navegador (preenchimento, fundo). */
export async function loadGlobalLook({ fresh = false } = {}) {
  if (globalCache && !fresh) return globalCache;
  const r = await api("/api/player-look");
  globalCache = r.look;
  if (!r.migrated) {
    const patch = {};
    const wipe = store("karaoke.wipe");
    if (wipe && typeof wipe === "object") {
      if (typeof wipe.on === "boolean") patch.wipe = wipe.on;
      if (wipe.color) patch.wipe_color = wipe.color;
    }
    const bg = store("karaoke.bg");
    if (bg === "cover" || bg === "video") patch.background = bg;
    try {
      globalCache = (await api("/api/player-look", { method: "PUT", body: { look: patch, migrated: true } })).look;
    } catch {
      /* celular sem permissao: fica para o PC */
    }
  }
  return globalCache;
}

export async function saveGlobalLook(patch) {
  const r = await api("/api/player-look", { method: "PUT", body: { look: patch } });
  globalCache = r.look;
  if ("BroadcastChannel" in window) new BroadcastChannel("karaoke").postMessage({ type: "look" }); // o player aberto atualiza
  return r.look;
}

export const effectiveLook = (base, mode, own) => (mode === "own" ? { ...base, ...own } : { ...base });

// ------------------------------------------------------------ controles
function controlHtml(c) {
  const label = t(c.key);
  const head = `<span class="ms">${c.icon}</span><span class="lk-label"${c.title ? ` title="${esc(t(c.title))}"` : ""}>${esc(label)}</span>`;
  if (c.type === "range") {
    return `<label class="lk-row" data-k="${c.k}">${head}
      <input type="range" min="${c.min}" max="${c.max}" step="${c.step}" aria-label="${esc(label)}"><b class="lk-val"></b></label>`;
  }
  if (c.type === "seg") {
    return `<div class="lk-row" data-k="${c.k}">${head}
      <div class="seg lk-seg">${c.options.map(([v, k]) => `<button type="button" data-v="${v}">${esc(t(k))}</button>`).join("")}</div></div>`;
  }
  return `<div class="lk-row lk-color" data-k="${c.k}">${head}
    <div class="lk-swatches">${PALETTES[c.palette].map((hex) => `<button type="button" data-c="${hex}" style="--c:${hex}" title="${hex}" aria-label="${hex}"></button>`).join("")}
      <label class="lk-custom" title="${esc(t("visual.outra_cor"))}"><input type="color" aria-label="${esc(t("visual.outra_cor_para", { nome: label }))}"><span class="ms">colorize</span></label>
    </div></div>`;
}
/* icons: colorize */

/** Desenha os controles dos `groups` em `box`. `onChange(k, v, final)` a cada mudanca
 *  (final=false enquanto arrasta). Devolve { update(look) } para mostrar outros valores. */
export function mountLookControls(box, groups, onChange, { details = [] } = {}) {
  box.innerHTML = groups.map((g) => {
    const rows = GROUPS[g].map(controlHtml).join("");
    return details.includes(g)
      ? `<details class="lk-group lk-more" data-g="${g}"><summary>${esc(t(GROUP_TITLES[g]))}</summary>${rows}</details>`
      : `<div class="lk-group" data-g="${g}">${rows}</div>`;
  }).join("");
  const spec = Object.fromEntries(Object.values(GROUPS).flat().map((c) => [c.k, c]));
  $$(".lk-row", box).forEach((row) => {
    const c = spec[row.dataset.k];
    if (c.type === "range") {
      const input = row.querySelector("input");
      input.addEventListener("input", () => onChange(c.k, Number(input.value), false));
      input.addEventListener("change", () => onChange(c.k, Number(input.value), true));
    } else if (c.type === "seg") {
      $$("button", row).forEach((b) => (b.onclick = () => {
        const v = b.dataset.v === "true" ? true : b.dataset.v === "false" ? false : b.dataset.v;
        onChange(c.k, v, true);
      }));
    } else {
      $$(".lk-swatches button", row).forEach((b) => (b.onclick = () => onChange(c.k, b.dataset.c, true)));
      const input = row.querySelector("input[type=color]");
      input.addEventListener("input", () => onChange(c.k, input.value, false));
      input.addEventListener("change", () => onChange(c.k, input.value, true));
    }
  });
  const update = (look) => {
    $$(".lk-row", box).forEach((row) => {
      const c = spec[row.dataset.k];
      const v = look[c.k];
      if (c.type === "range") {
        const input = row.querySelector("input");
        if (document.activeElement !== input || !input.matches(":active")) input.value = v;
        row.querySelector(".lk-val").textContent = c.fmt(v);
      } else if (c.type === "seg") {
        $$("button", row).forEach((b) => b.classList.toggle("on", String(v) === b.dataset.v));
      } else {
        let known = false;
        $$(".lk-swatches button", row).forEach((b) => {
          const on = b.dataset.c.toLowerCase() === String(v).toLowerCase();
          known = known || on;
          b.classList.toggle("on", on);
        });
        const custom = row.querySelector(".lk-custom");
        custom.classList.toggle("on", !known);
        custom.style.setProperty("--c", v);
        row.querySelector("input[type=color]").value = v;
      }
      if (c.needs) row.classList.toggle("disabled", !look[c.needs]);
    });
  };
  return { update };
}

/** "Visual: Padrao | Proprio" (no topo dos menus Fundo e Letra do player). */
export function lookModeHtml() {
  return `<div class="lk-mode" title="${esc(t("visual.modo_explica"))}">
    <span class="lk-label">${esc(t("visual.modo"))}</span>
    <div class="seg lk-seg"><button type="button" data-mode="global">${esc(t("visual.padrao"))}</button><button type="button" data-mode="own">${esc(t("visual.proprio"))}</button></div>
  </div>`;
}
