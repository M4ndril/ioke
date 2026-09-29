"""Conversar com um complemento ligado: HTTP em 127.0.0.1, com a senha e o tempo limite.
Erro vira ComplementoIndisponivel (nao respondeu) ou ComplementoErro (respondeu com erro)."""
import json
import socket
import urllib.error
import urllib.request

# tempos limite (s) de cada tipo de pedido
TEMPOS = {"saude": 3, "buscar": 20, "trecho": 60, "letras": 20, "acoes": 30, "tarefa": 5, "configurar": 10}


class ComplementoIndisponivel(RuntimeError):
    """O complemento nao respondeu (desligado, travado ou demorou demais)."""


class ComplementoErro(RuntimeError):
    """O complemento respondeu com erro; a mensagem ja e para a pessoa ler."""

    def __init__(self, mensagem, status=400):
        super().__init__(mensagem)
        self.status = status


def chamar(porta, senha, metodo, rota, dados=None, tempo=10, idioma="en"):
    corpo = json.dumps(dados).encode("utf-8") if dados is not None else None
    req = urllib.request.Request(f"http://127.0.0.1:{porta}{rota}", data=corpo, method=metodo,
                                 headers={"X-Senha": senha, "X-Idioma": idioma, "Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=tempo) as r:
            return json.loads(r.read().decode("utf-8") or "{}")
    except urllib.error.HTTPError as exc:
        try:
            msg = json.loads(exc.read().decode("utf-8")).get("erro")
        except (ValueError, OSError):
            msg = None
        raise ComplementoErro(msg or f"erro {exc.code}", exc.code) from None
    except (urllib.error.URLError, socket.timeout, TimeoutError, ConnectionError, OSError) as exc:
        raise ComplementoIndisponivel(str(getattr(exc, "reason", exc))) from None
    except ValueError as exc:
        raise ComplementoErro(f"resposta inválida do complemento ({exc})") from None
