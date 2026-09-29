// Botoes flutuantes no canto superior direito: sessao (QR), piano, MIDI e qualidade.
import { api, esc, gb, h, icon, keyLabel, openModal, store, toast } from "./common.js";
import { mountMidiPicker } from "./midi.js";
import { openSettings } from "./settings.js";
import { appApi } from "./appwin.js";
import { t } from "./i18n.js";

/* icons: power_settings_new */
/** "Fechar o Karaoke": com gente na fila ou cantando, pergunta antes. */
export async function quitApp(app) {
  let busy = false;
  try {
    const p = await api("/api/party");
    busy = !!(p.current || (p.queue || []).length);
  } catch {
    /* sem servidor: fecha */
  }
  if (busy && !confirm(t("app.fechar_ocupado"))) return;
  app.quit();
}

export function openPiano() {
  window.open("/piano", "karaoke-piano", "width=800,height=460");
}

export async function showSessionQr() {
  const modal = openModal(t("qr.titulo"), `
    <div class="qr-modal">
      <img src="/api/qr.svg?t=${Date.now()}" alt="${esc(t("qr.alt"))}">
      <div>
        <div class="small muted">${esc(t("qr.aponte"))}</div>
        <div class="url" data-url>...</div>
        <p class="small muted" style="max-width:320px">${esc(t("qr.texto"))}</p>
      </div>
    </div>`);
  try {
    const info = await api("/api/info");
    modal.querySelector("[data-url]").textContent = info.lan_url;
  } catch {
    /* sem servidor */
  }
}

/** Avisos do PC: o IP mudou (o QR ja mudou junto) e disco quase cheio. Cada um uma vez. */
async function checkAddress() {
  try {
    const info = await api("/api/info");
    const c = info.address_change;
    if (c && store("karaoke.addressSeen") !== c.at) {
      store("karaoke.addressSeen", c.at);
      toast(t("qr.endereco_mudou", { de: c.from, para: c.to }), { ms: 12000 });
    }
    const d = info.disk;
    const today = new Date().toDateString();
    if (d && d.low && store("karaoke.diskWarned") !== today) {
      store("karaoke.diskWarned", today); // uma vez por dia
      toast(t("disco.pouco", { livre: gb(d.free), minimo: gb(d.min) }), { ms: 12000, error: true });
    }
  } catch {
    /* sem servidor */
  }
}

/** Monta os botoes. Opcoes: qr, piano, midi, settings, getKey (tom atual para o MIDI). */
export function mountFabs({ qr = false, piano = false, midi = false, settings = false, getKey = null } = {}) {
  const box = h('<div class="fabs"></div>');
  const add = (name, title, onclick) => {
    const b = h(`<button class="fab" title="${esc(title)}" aria-label="${esc(title)}">${icon(name)}</button>`);
    b.onclick = onclick;
    box.append(b);
    return b;
  };
  if (qr) {
    add("qr_code_2", t("qr.botao"), showSessionQr);
    checkAddress();
    setInterval(checkAddress, 60000);
  }
  if (piano) add("piano", t("piano.botao"), openPiano);
  if (midi) {
    let pop = null;
    const btn = add("tune", t("player.autotune_midi"), async (e) => {
      e.stopPropagation();
      if (pop) return close();
      pop = h(`
        <div class="popover">
          <h4>${esc(t("player.autotune_midi"))}</h4>
          <div class="midi-box" data-picker></div>
          <p class="small muted" data-key style="margin:12px 0 0"></p>
        </div>`);
      document.body.append(pop);
      pop.addEventListener("click", (ev) => ev.stopPropagation());
      await mountMidiPicker(pop.querySelector("[data-picker]"), { getKey });
      const key = getKey && getKey();
      pop.querySelector("[data-key]").textContent = key
        ? t("midi.tom_atual", { tom: keyLabel(key) })
        : t("midi.tom_automatico");
      pop.querySelector("select").addEventListener("change", refreshDot);
    });
    const close = () => {
      pop && pop.remove();
      pop = null;
    };
    document.addEventListener("click", close);
    const refreshDot = () => btn.classList.toggle("on", !!store("karaoke.midi.out"));
    refreshDot();
  }
  if (settings) add("settings", t("config.titulo"), () => openSettings());
  // app instalado (tela cheia, sem barra de titulo): a saida do programa
  appApi().then((app) => app && add("power_settings_new", t("app.fechar"), () => quitApp(app)));
  document.body.append(box);
  return box;
}
