"""Palco na TV: abre o /palco numa janela propria do Chrome/Edge, ja em tela
cheia (ou em modo quiosque) no monitor escolhido.

A janela usa um perfil separado (data/palco-navegador) e sobe com
--autoplay-policy=no-user-gesture-required: o navegador deixa o palco tocar
som sem ninguem clicar na tela (numa aba comum, a regra dos navegadores exige
um clique antes de qualquer som). Por isso o palco pode ser aberto pelo
celular administrador sem encostar no PC.

  tela cheia: F11 / Esc no teclado do PC saem da tela cheia
  quiosque:   trava a tela cheia; so fecha com Alt+F4 ou pelo botao "Fechar"

No app instalado (Karaoke.exe), o palco e uma segunda janela do proprio app (sem
Chrome): o servidor pede para a janela abrir/fechar pelo canal local dela
(KARAOKE_APP_CONTROL). O som ja e liberado la tambem.
"""
import json
import logging
import os
import subprocess
import sys
import threading
import time
import urllib.request

from . import i18n
from .config import CONFIG, DATA_DIR, save_config
from .util import NO_WINDOW
from .util import find_browser

log = logging.getLogger("karaoke.stage")

PROFILE = DATA_DIR / "palco-navegador"
MODES = ("fullscreen", "kiosk")
# fabricantes (codigo EDID de 3 letras) que aparecem em TVs e monitores
MAKERS = {
    "GSM": "LG", "LGD": "LG", "SAM": "Samsung", "SEC": "Samsung", "SDC": "Samsung", "SNY": "Sony",
    "PHL": "Philips", "PHI": "Philips", "DEL": "Dell", "ACR": "Acer", "AOC": "AOC", "BNQ": "BenQ",
    "HWP": "HP", "HPN": "HP", "LEN": "Lenovo", "AUS": "ASUS", "VSC": "ViewSonic", "TCL": "TCL",
    "HEC": "Hisense", "HSD": "HannStar", "MEI": "Panasonic", "TOS": "Toshiba", "SHP": "Sharp",
    "IVM": "Iiyama", "MSI": "MSI", "GBT": "Gigabyte", "XMI": "Xiaomi", "AOP": "AOPEN", "PNP": "Genérico",
}

_lock = threading.Lock()
_proc = None
APP_CONTROL = os.environ.get("KARAOKE_APP_CONTROL")  # canal da janela do app (so no app instalado)
APP_TOKEN = os.environ.get("KARAOKE_APP_TOKEN", "")


def _app(path, body=None):
    """Pede algo para a janela do app (abrir/fechar o palco)."""
    data = None if body is None else json.dumps(body).encode()
    req = urllib.request.Request(APP_CONTROL + path, data=data, method="GET" if body is None else "POST",
                                 headers={"X-Token": APP_TOKEN, "Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=15) as r:
        return json.loads(r.read() or b"{}")
_names_cache = (0.0, {})


def settings():
    s = CONFIG.get("stage") or {}
    mode = s.get("mode") if s.get("mode") in MODES else "fullscreen"
    return {"mode": mode, "monitor": s.get("monitor") or ""}


def save_settings(mode=None, monitor=None):
    s = settings()
    if mode in MODES:
        s["mode"] = mode
    if monitor is not None:
        s["monitor"] = str(monitor)
    CONFIG["stage"] = s
    save_config()
    return s


# ------------------------------------------------------------------ monitores
def _friendly_names(keys=()):
    """Nome de cada monitor (ex.: "LG 27GN7"), pelo WMI. Chave: "GSM5B8E#5&2b97...&UID20737".
    Guarda por 1 min, mas le de novo se aparecer um monitor que ainda nao conhece."""
    global _names_cache
    at, names = _names_cache
    if time.time() - at < 60 and all(k in names for k in keys if k):
        return names
    names = {}
    script = (
        "Get-CimInstance -Namespace root\\wmi -ClassName WmiMonitorID | ForEach-Object {"
        " $n = -join ($_.UserFriendlyName | Where-Object { $_ -ne 0 } | ForEach-Object { [char]$_ });"
        " $m = -join ($_.ManufacturerName | Where-Object { $_ -ne 0 } | ForEach-Object { [char]$_ });"
        " \"$($_.InstanceName)|$m|$n\" }"
    )
    try:
        out = subprocess.run(["powershell", "-NoProfile", "-Command", script], capture_output=True, text=True,
                             encoding="utf-8", errors="replace", timeout=15, creationflags=NO_WINDOW).stdout
        for line in out.splitlines():
            parts = line.strip().split("|")
            if len(parts) != 3:
                continue
            inst, maker, model = parts
            key = "#".join(inst.split("\\")[1:3]).rsplit("_", 1)[0].upper()  # GSM5B8E#5&...&UID20737
            maker = MAKERS.get(maker.upper(), maker)
            # "LG 27GN7"; sem repetir quando o modelo ja traz a marca ("LG TV SSCR2")
            names[key] = model if maker.lower() in model.lower() else f"{maker} {model}".strip()
    except Exception as exc:  # noqa: BLE001
        log.info("nao consegui ler os nomes dos monitores: %s", exc)
    _names_cache = (time.time(), names)
    return names


def monitors():
    """Monitores plugados AGORA (lidos do Windows a cada chamada): nome, posicao e
    tamanho. O "id" identifica o aparelho (fabricante + modelo + porta), e nao o
    numero do Windows (DISPLAY1, 2...), que muda quando se pluga/despluga telas.
    "aqui": o monitor da janela em primeiro plano (a do app, ou o navegador, onde a
    pessoa acabou de clicar em "Abrir o palco")."""
    if sys.platform != "win32":
        return []
    import ctypes
    from ctypes import wintypes

    user32 = ctypes.windll.user32

    class MONITORINFOEXW(ctypes.Structure):
        _fields_ = [("cbSize", wintypes.DWORD), ("rcMonitor", wintypes.RECT), ("rcWork", wintypes.RECT),
                    ("dwFlags", wintypes.DWORD), ("szDevice", wintypes.WCHAR * 32)]

    class DISPLAY_DEVICEW(ctypes.Structure):
        _fields_ = [("cb", wintypes.DWORD), ("DeviceName", wintypes.WCHAR * 32),
                    ("DeviceString", wintypes.WCHAR * 128), ("StateFlags", wintypes.DWORD),
                    ("DeviceID", wintypes.WCHAR * 128), ("DeviceKey", wintypes.WCHAR * 128)]

    found = []
    user32.MonitorFromWindow.restype = wintypes.HMONITOR
    user32.MonitorFromWindow.argtypes = (wintypes.HWND, wintypes.DWORD)
    user32.GetForegroundWindow.restype = wintypes.HWND
    aqui = user32.MonitorFromWindow(user32.GetForegroundWindow(), 2)  # 2: o mais perto
    proc_type = ctypes.WINFUNCTYPE(ctypes.c_int, wintypes.HMONITOR, wintypes.HDC,
                                   ctypes.POINTER(wintypes.RECT), wintypes.LPARAM)

    def callback(hmon, _hdc, _rect, _data):
        info = MONITORINFOEXW()
        info.cbSize = ctypes.sizeof(info)
        user32.GetMonitorInfoW(hmon, ctypes.byref(info))
        dev = DISPLAY_DEVICEW()
        dev.cb = ctypes.sizeof(dev)
        interface = ""
        if user32.EnumDisplayDevicesW(info.szDevice, 0, ctypes.byref(dev), 1):  # 1 = nome da interface
            interface = dev.DeviceID
        r = info.rcMonitor
        found.append({"display": info.szDevice, "interface": interface, "x": r.left, "y": r.top,
                      "width": r.right - r.left, "height": r.bottom - r.top, "primary": bool(info.dwFlags & 1),
                      "aqui": bool(aqui) and hmon == aqui})
        return 1

    user32.EnumDisplayMonitors(None, None, proc_type(callback), 0)
    for m in found:
        parts = m.pop("interface").split("#")
        m["id"] = "#".join(parts[1:3]).upper() if len(parts) >= 3 else m["display"]
    names = _friendly_names([m["id"] for m in found])
    primary = next((m for m in found if m["primary"]), found[0] if found else None)
    for i, m in enumerate(sorted(found, key=lambda m: (not m["primary"], m["x"], m["y"])), 1):
        m["name"] = names.get(m["id"]) or i18n.t("palco.monitor", n=i)
        where = ""
        if not m["primary"] and primary:
            dx, dy = m["x"] - primary["x"], m["y"] - primary["y"]
            where = i18n.t(("palco.esquerda" if dx < 0 else "palco.direita") if abs(dx) >= abs(dy)
                           else ("palco.acima" if dy < 0 else "palco.abaixo"))
        m["label"] = f"{m['name']} · {m['width']}×{m['height']}" + (f" · {i18n.t('palco.principal')}" if m["primary"] else f" · {where}")
    found.sort(key=lambda m: (not m["primary"], m["x"], m["y"]))
    return found


def pick_monitor(mons, wanted):
    """Monitor escolhido; se ele nao estiver plugado agora, o principal (e avisa).
    Devolve (monitor ou None, faltou_o_escolhido)."""
    chosen = next((m for m in mons if wanted and m["id"] == wanted), None)
    fallback = next((m for m in mons if m["primary"]), mons[0] if mons else None)
    return chosen or fallback, bool(wanted) and not chosen


def _target_monitor():
    return pick_monitor(monitors(), settings()["monitor"])


# ----------------------------------------------------------------- a janela
def _prepare_profile(origin):
    """Ajusta o perfil do navegador do palco antes de abrir:
    - sem o balao "o Chrome nao foi fechado corretamente";
    - MIDI (autotune) e microfone (pontuacao) ja liberados para o proprio karaoke,
      senao o pedido de permissao apareceria por cima do palco (e no quiosque
      nao da para clicar nele sem teclado/mouse)."""
    prefs = PROFILE / "Default" / "Preferences"
    try:
        data = json.loads(prefs.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        data = {}
    profile = data.setdefault("profile", {})
    profile["exit_type"] = "Normal"
    profile["exited_cleanly"] = True
    exceptions = profile.setdefault("content_settings", {}).setdefault("exceptions", {})
    for kind in ("midi", "midi_sysex", "media_stream_mic"):
        exceptions.setdefault(kind, {})[f"{origin},*"] = {"setting": 1}  # 1 = permitir
    try:
        prefs.parent.mkdir(parents=True, exist_ok=True)
        prefs.write_text(json.dumps(data), encoding="utf-8")
    except OSError:
        pass


def _find_pids():
    """PIDs do navegador do palco (pelo perfil na linha de comando), p/ quando o servidor reiniciou."""
    script = ("Get-CimInstance Win32_Process | Where-Object { $_.CommandLine -like '*palco-navegador*' } "
              "| Where-Object { $_.CommandLine -notlike '*--type=*' } | ForEach-Object { $_.ProcessId }")
    try:
        out = subprocess.run(["powershell", "-NoProfile", "-Command", script], capture_output=True, text=True,
                             timeout=15, creationflags=NO_WINDOW).stdout
        return [int(x) for x in out.split() if x.strip().isdigit()]
    except Exception:  # noqa: BLE001
        return []


def is_open():
    if APP_CONTROL:
        try:
            return bool(_app("/palco").get("open"))
        except OSError:
            return False
    with _lock:
        if _proc is not None:
            return _proc.poll() is None
    return bool(_find_pids())


def open_stage(url, monitor=None):
    """Abre a janela do palco. Palco e um so: se ja houver uma janela aberta, ela
    e fechada antes (reabrir tambem serve para valer o modo/monitor atual).
    `monitor`: a tela escolhida agora (fica guardada como a ultima usada)."""
    global _proc
    if APP_CONTROL:
        return _open_in_app(url, monitor)
    found = find_browser()
    if not found:
        raise RuntimeError("erro.precisa_navegador")
    _name, browser = found
    if monitor:
        save_settings(monitor=monitor)
    close_stage()
    mon, missing = _target_monitor()
    s = settings()
    PROFILE.mkdir(parents=True, exist_ok=True)
    _prepare_profile(url.split("/palco")[0])
    args = [
        browser,
        f"--user-data-dir={PROFILE}",
        "--no-first-run",
        "--no-default-browser-check",
        "--autoplay-policy=no-user-gesture-required",  # som sem clique
        "--hide-crash-restore-bubble",
        "--disable-session-crashed-bubble",
        "--noerrdialogs",
        "--disable-features=Translate,MediaRouter",
        "--disable-pinch",
        "--overscroll-history-navigation=0",
    ]
    if mon:
        # a janela nasce dentro do monitor escolhido; a tela cheia ocupa esse monitor
        args += [f"--window-position={mon['x'] + 40},{mon['y'] + 40}",
                 f"--window-size={max(640, mon['width'] - 80)},{max(480, mon['height'] - 80)}"]
    if s["mode"] == "kiosk":
        args += ["--kiosk", url + ("&" if "?" in url else "?") + "quiosque=1"]  # o palco explica como sair
    else:
        args += ["--start-fullscreen", f"--app={url}"]
    with _lock:
        _proc = subprocess.Popen(args, creationflags=NO_WINDOW)
    log.info("palco aberto (%s) em %s", s["mode"], mon["label"] if mon else "?")
    result = status()
    result["opened_on"] = mon["label"] if mon else None
    result["monitor_missing"] = missing  # a TV escolhida nao estava plugada: abriu no principal
    return result


def _open_in_app(url, monitor=None):
    """App instalado: o palco e uma segunda janela do app, em tela cheia no monitor escolhido."""
    if monitor:
        save_settings(monitor=monitor)
    mon, missing = _target_monitor()
    if settings()["mode"] == "kiosk":
        url += ("&" if "?" in url else "?") + "quiosque=1"
    box = {k: mon[k] for k in ("x", "y", "width", "height")} if mon else {}
    _app("/palco/abrir", {"url": url, **box})  # a janela troca o palco anterior, se houver
    log.info("palco aberto na janela do app em %s", mon["label"] if mon else "?")
    result = status()
    result["opened_on"] = mon["label"] if mon else None
    result["monitor_missing"] = missing
    return result


def close_stage():
    global _proc
    if APP_CONTROL:
        try:
            _app("/palco/fechar", {})
        except OSError:
            return False
        return True
    with _lock:
        pids = [_proc.pid] if _proc is not None and _proc.poll() is None else []
        _proc = None
    if not pids:
        pids = _find_pids()
    for pid in pids:
        # primeiro pede para fechar (como clicar no X); se nao fechar, forca
        subprocess.run(["taskkill", "/PID", str(pid), "/T"], capture_output=True, creationflags=NO_WINDOW)
    deadline = time.time() + 4
    while pids and time.time() < deadline and _find_pids():
        time.sleep(0.5)
    for pid in _find_pids():
        subprocess.run(["taskkill", "/PID", str(pid), "/T", "/F"], capture_output=True, creationflags=NO_WINDOW)
    return bool(pids)


def status():
    found = ("IOkê", None) if APP_CONTROL else find_browser()
    return {
        **settings(),
        "open": is_open(),
        "browser": found[0] if found else None,
        "monitors": monitors(),
    }
