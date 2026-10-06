"""Encerrar um processo leva junto os que ele abriu: no Windows, terminate() mata so ele, e os filhos (os complementos,
o servidor de verdade atras do lancador da .venv) ficavam rodando sozinhos depois de fechar o app."""
import os
import subprocess
import sys
import time

import pytest

from karaoke.util import NO_WINDOW, encerrar_arvore

FILHO = "import subprocess, sys, time; subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(60)']); time.sleep(60)"


def _vivo(pid):
    out = subprocess.run(["tasklist", "/FI", f"PID eq {pid}", "/NH"], capture_output=True, text=True,
                         creationflags=NO_WINDOW).stdout
    return str(pid) in out


@pytest.mark.skipif(os.name != "nt", reason="a arvore de processos do Windows")
def test_the_children_go_too():
    pai = subprocess.Popen([sys.executable, "-c", FILHO], creationflags=NO_WINDOW)
    filhos = []
    for _ in range(50):
        out = subprocess.run(["powershell", "-NoProfile", "-Command",
                              f"Get-CimInstance Win32_Process -Filter 'ParentProcessId = {pai.pid}' | Select -Expand ProcessId"],
                             capture_output=True, text=True).stdout.split()
        filhos = [int(x) for x in out]
        if filhos:
            break
        time.sleep(0.2)
    assert filhos
    encerrar_arvore(pai)
    time.sleep(0.5)
    assert pai.poll() is not None and not any(_vivo(f) for f in filhos)


def test_already_finished_or_missing():
    encerrar_arvore(None)
    p = subprocess.Popen([sys.executable, "-c", "pass"], creationflags=NO_WINDOW)
    p.wait()
    encerrar_arvore(p)  # ja tinha acabado: nada a fazer
