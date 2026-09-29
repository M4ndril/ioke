// Envio do tom/escala para o autotune via MIDI (Web MIDI API do Chrome/Edge).
//
// Ideia: um cabo MIDI virtual (loopMIDI) liga o navegador ao Reaper. No Reaper,
// use "Learn" nos parametros Key e Scale do plugin de autotune e mapeie para os
// CCs configurados aqui. Ao abrir uma musica, o tom detectado e enviado sozinho.
import { NOTES, esc, h, icon, openModal, store, toast } from "./common.js";
import { t } from "./i18n.js";

const CFG_KEY = "karaoke.midi.cfg";
const OUT_KEY = "karaoke.midi.out";

export const MIDI_DEFAULTS = {
  channel: 1,
  ccKey: 20,
  ccScale: 21,
  // spread: valor = indice espalhado em 0-127 (ideal para "Learn" do Reaper)
  // direct: valor = indice (0-11 / 0-1)
  // program: Program Change = tom + 12 * escala
  mode: "spread",
  keySteps: 12,
  scaleSteps: 2,
  majorIndex: 0,
  minorIndex: 1,
};

let access = null;
let lastSent = null;

export const midiConfig = () => ({ ...MIDI_DEFAULTS, ...(store(CFG_KEY) || {}) });

export async function initMidi() {
  if (access) return access;
  if (!navigator.requestMIDIAccess) return null;
  try {
    access = await navigator.requestMIDIAccess({ sysex: false });
  } catch {
    access = null;
  }
  return access;
}

function currentOutput() {
  const id = store(OUT_KEY);
  return id && access ? access.outputs.get(id) : null;
}

/** Envia o tom. tonic = "A#", scale = "major" | "minor". */
export function sendKey(tonic, scale, { force = false } = {}) {
  const out = currentOutput();
  const idx = NOTES.indexOf(tonic);
  if (!out || idx < 0) return false;
  const sig = `${out.id}|${tonic}|${scale}`;
  if (!force && sig === lastSent) return true;
  const c = midiConfig();
  const ch = (Number(c.channel) - 1) & 15;
  const scaleIdx = scale === "minor" ? Number(c.minorIndex) : Number(c.majorIndex);
  const spread = (i, steps) => Math.round((i * 127) / Math.max(1, steps - 1));
  if (c.mode === "program") {
    out.send([0xc0 | ch, (idx + 12 * (scale === "minor" ? 1 : 0)) & 127]);
  } else if (c.mode === "direct") {
    out.send([0xb0 | ch, c.ccKey & 127, idx & 127]);
    out.send([0xb0 | ch, c.ccScale & 127, scaleIdx & 127]);
  } else {
    out.send([0xb0 | ch, c.ccKey & 127, spread(idx, Number(c.keySteps)) & 127]);
    out.send([0xb0 | ch, c.ccScale & 127, spread(scaleIdx, Number(c.scaleSteps)) & 127]);
  }
  lastSent = sig;
  return true;
}

/** Monta o <select> de dispositivo MIDI (+ botao de configuracoes). */
export async function mountMidiPicker(container, { getKey } = {}) {
  container.innerHTML = `
    <span>MIDI Device</span>
    <select class="input compact" data-midi-out><option value="">${esc(t("midi.nenhum"))}</option></select>
    <button class="icon-btn plain" data-midi-cfg title="${esc(t("midi.configurar"))}">${icon("settings")}</button>`;
  const select = container.querySelector("[data-midi-out]");
  const acc = await initMidi();

  const fill = () => {
    const saved = store(OUT_KEY) || "";
    select.innerHTML = `<option value="">${esc(t("midi.nenhum"))}</option>`;
    if (!acc) {
      select.innerHTML = `<option value="">${esc(t("midi.indisponivel"))}</option>`;
      select.disabled = true;
      return;
    }
    for (const out of acc.outputs.values()) {
      select.append(h(`<option value="${esc(out.id)}">${esc(out.name)}</option>`));
    }
    select.value = [...acc.outputs.keys()].includes(saved) ? saved : "";
  };
  fill();
  if (acc) acc.onstatechange = fill;
  select.onchange = () => {
    store(OUT_KEY, select.value);
    lastSent = null;
    const key = getKey && getKey();
    if (key) sendKey(key.tonic, key.mode, { force: true });
  };
  container.querySelector("[data-midi-cfg]").onclick = () => openMidiSettings(getKey);
}

export function openMidiSettings(getKey) {
  const c = midiConfig();
  const modal = openModal(t("midi.titulo"), `
    <p class="small muted" style="margin-top:0">${t("midi.texto")}</p>
    <div class="row wrap" style="gap:14px">
      <label>${esc(t("midi.canal"))}<br><input class="input" type="number" min="1" max="16" data-f="channel" value="${c.channel}" style="width:80px"></label>
      <label>${esc(t("midi.cc_tom"))}<br><input class="input" type="number" min="0" max="127" data-f="ccKey" value="${c.ccKey}" style="width:90px"></label>
      <label>${esc(t("midi.cc_escala"))}<br><input class="input" type="number" min="0" max="127" data-f="ccScale" value="${c.ccScale}" style="width:90px"></label>
      <label>${esc(t("midi.modo"))}<br>
        <select class="input" data-f="mode" style="width:230px">
          <option value="spread">${esc(t("midi.spread"))}</option>
          <option value="direct">${esc(t("midi.direct"))}</option>
          <option value="program">Program Change</option>
        </select>
      </label>
    </div>
    <div class="row wrap" style="gap:14px;margin-top:12px">
      <label>${esc(t("midi.opcoes_tom"))}<br><input class="input" type="number" min="2" max="128" data-f="keySteps" value="${c.keySteps}" style="width:120px"></label>
      <label>${esc(t("midi.opcoes_escala"))}<br><input class="input" type="number" min="2" max="128" data-f="scaleSteps" value="${c.scaleSteps}" style="width:120px"></label>
      <label>${esc(t("midi.posicao", { nome: "Major" }))}<br><input class="input" type="number" min="0" max="127" data-f="majorIndex" value="${c.majorIndex}" style="width:100px"></label>
      <label>${esc(t("midi.posicao", { nome: "Minor" }))}<br><input class="input" type="number" min="0" max="127" data-f="minorIndex" value="${c.minorIndex}" style="width:100px"></label>
    </div>
    <p class="small muted">${esc(t("midi.exemplo"))}</p>
    <div class="row wrap" style="margin-top:12px">
      <button class="btn ghost sm" data-test-key>${esc(t("midi.teste_tom"))}</button>
      <button class="btn ghost sm" data-test-scale>${esc(t("midi.teste_escala"))}</button>
      <button class="btn ghost sm" data-test-all>${esc(t("midi.enviar_tom"))}</button>
      <span class="grow"></span>
      <button class="btn sm" data-save>${esc(t("comum.salvar"))}</button>
    </div>`);
  modal.querySelector('[data-f="mode"]').value = c.mode;
  const read = () => {
    const cfg = { ...c };
    modal.querySelectorAll("[data-f]").forEach((el) => {
      cfg[el.dataset.f] = el.dataset.f === "mode" ? el.value : Number(el.value);
    });
    return cfg;
  };
  const sendRaw = (bytes) => {
    const out = currentOutput();
    if (!out) return toast(t("midi.escolha"), { error: true });
    out.send(bytes);
    toast(t("midi.enviado"));
  };
  modal.querySelector("[data-test-key]").onclick = () => {
    const cfg = read();
    sendRaw([0xb0 | ((cfg.channel - 1) & 15), cfg.ccKey & 127, 64]);
  };
  modal.querySelector("[data-test-scale]").onclick = () => {
    const cfg = read();
    sendRaw([0xb0 | ((cfg.channel - 1) & 15), cfg.ccScale & 127, 64]);
  };
  modal.querySelector("[data-test-all]").onclick = () => {
    store(CFG_KEY, read());
    const key = (getKey && getKey()) || { tonic: "C", mode: "major" };
    if (sendKey(key.tonic, key.mode, { force: true })) toast(t("midi.enviado_tom", { tom: `${key.tonic} ${key.mode}` }));
    else toast(t("midi.escolha"), { error: true });
  };
  modal.querySelector("[data-save]").onclick = () => {
    store(CFG_KEY, read());
    lastSent = null;
    toast(t("midi.salva"));
    modal.close();
  };
}
