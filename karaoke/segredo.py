"""Segredos guardados no disco (a chave da nuvem, as opcoes "segredo" dos complementos):
protegidos pelo DPAPI do Windows, que so este usuario, neste PC, consegue abrir (copiar a
pasta para outro PC nao leva o segredo). Fora do Windows (testes, desenvolvimento), sem
protecao: quem guarda marca "sem_protecao".
"""
import base64
import sys


def _dpapi(dados, proteger):
    import ctypes
    from ctypes import wintypes

    class BLOB(ctypes.Structure):
        _fields_ = [("cbData", wintypes.DWORD), ("pbData", ctypes.POINTER(ctypes.c_char))]

    buf = ctypes.create_string_buffer(dados, len(dados))
    entrada = BLOB(len(dados), ctypes.cast(buf, ctypes.POINTER(ctypes.c_char)))
    saida = BLOB()
    crypt32 = ctypes.windll.crypt32
    f = crypt32.CryptProtectData if proteger else crypt32.CryptUnprotectData
    # sem descricao, sem entropia extra, sem janela (0x1 = CRYPTPROTECT_UI_FORBIDDEN)
    if not f(ctypes.byref(entrada), None, None, None, None, 0x1, ctypes.byref(saida)):
        raise OSError("DPAPI falhou")
    try:
        return ctypes.string_at(saida.pbData, saida.cbData)
    finally:
        ctypes.windll.kernel32.LocalFree(saida.pbData)


def proteger(segredo):
    """-> (texto guardavel, protegido?)."""
    dados = segredo.encode("utf-8")
    if sys.platform == "win32":
        return base64.b64encode(_dpapi(dados, True)).decode("ascii"), True
    return base64.b64encode(dados).decode("ascii"), False


def abrir(guardado, protegido):
    dados = base64.b64decode(guardado)
    if protegido:
        if sys.platform != "win32":
            raise OSError("chave protegida pelo Windows")
        dados = _dpapi(dados, False)
    return dados.decode("utf-8")
