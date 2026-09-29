"""O manifesto de um complemento: karaoke-complemento.json, na raiz do repositorio dele.

Diz quem e o complemento (id, nome, autor, versao), com qual contrato ele conversa ("api"),
o que oferece (fonte de musicas, de letras, de capas), as opcoes e as acoes. O app desenha a
interface a partir daqui: o complemento nunca poe codigo na tela.
Docs para quem escreve complementos: docs/COMPLEMENTOS.md.
"""
import json
import re
from pathlib import Path

from ..versoes import SEMVER, Refused, inside, version_key

ARQUIVO = "karaoke-complemento.json"
FORMATO = 1
APIS = (1,)  # os contratos que este app conhece
OFERECE = ("fonte_musicas", "fonte_letras", "fonte_capas")  # "catalogo": reservado (depois da 1.0.0)
TIPOS_OPCAO = ("texto", "numero", "sim_nao", "escolha", "pasta", "segredo")
ID_RE = re.compile(r"^[a-z0-9-]{2,40}$")
ACAO_ID_RE = re.compile(r"^[a-z0-9_-]{1,40}$")
# "migrar": dados antigos do app que passaram a ser de um complemento (copiados, nunca movidos, da
# pasta data/ do app para a pasta do complemento, uma vez). Isto nunca pode sair de la:
PROTEGIDOS = ("songs", "cache", "logs", "backups", "complementos", "karaoke.db", "karaoke.db-wal", "karaoke.db-shm",
              "admin.json", "nuvem.json", "nuvem-gastos.json", "complementos-opcoes.json", "party.json", "rede.json")


class ManifestoInvalido(ValueError):
    """O manifesto nao serve: a mensagem diz o motivo (em portugues; a interface mostra)."""


def _texto(valor, campo, obrigatorio=True):
    """Texto nos dois idiomas: {"pt-BR": ..., "en": ...} (o "en" e o minimo). Um texto so vale
    para os dois."""
    if isinstance(valor, str) and valor.strip():
        return {"en": valor.strip(), "pt-BR": valor.strip()}
    if isinstance(valor, dict) and isinstance(valor.get("en"), str) and valor["en"].strip():
        out = {k: str(v).strip() for k, v in valor.items() if k in ("en", "pt-BR") and isinstance(v, str) and v.strip()}
        out.setdefault("pt-BR", out["en"])
        return out
    if not obrigatorio and valor in (None, ""):
        return None
    raise ManifestoInvalido(f'"{campo}" precisa de um texto em inglês ("en"), e de preferência também em português')


def texto(valor, idioma):
    """O texto no idioma pedido (ou em ingles)."""
    if not valor:
        return ""
    if isinstance(valor, str):
        return valor
    return valor.get(idioma) or valor.get("en") or next(iter(valor.values()), "")


def _opcao(o, i):
    if not isinstance(o, dict):
        raise ManifestoInvalido(f"opção {i + 1}: precisa ser um objeto")
    oid = str(o.get("id") or "")
    if not ACAO_ID_RE.match(oid):
        raise ManifestoInvalido(f"opção {i + 1}: id inválido ({oid!r})")
    tipo = o.get("tipo")
    if tipo not in TIPOS_OPCAO:
        raise ManifestoInvalido(f'opção "{oid}": tipo desconhecido ({tipo!r}; use {", ".join(TIPOS_OPCAO)})')
    out = {"id": oid, "tipo": tipo, "rotulo": _texto(o.get("rotulo"), f"opções.{oid}.rotulo"),
           "ajuda": _texto(o.get("ajuda"), f"opções.{oid}.ajuda", obrigatorio=False), "padrao": o.get("padrao")}
    if tipo == "escolha":
        valores = o.get("valores")
        if not isinstance(valores, list) or not valores:
            raise ManifestoInvalido(f'opção "{oid}": "escolha" precisa da lista "valores"')
        out["valores"] = [{"id": str(v.get("id")), "rotulo": _texto(v.get("rotulo"), f"opções.{oid}.valores")}
                          for v in valores if isinstance(v, dict) and v.get("id") is not None]
        if out["padrao"] is not None and out["padrao"] not in [v["id"] for v in out["valores"]]:
            raise ManifestoInvalido(f'opção "{oid}": o padrão não está entre os valores')
    if tipo == "segredo":
        out["padrao"] = None  # segredo nunca tem padrao no manifesto
    return out


def _acao(a, i, campo):
    if not isinstance(a, dict) or not ACAO_ID_RE.match(str(a.get("id") or "")):
        raise ManifestoInvalido(f"{campo} {i + 1}: id inválido")
    return {"id": a["id"], "rotulo": _texto(a.get("rotulo"), f"{campo}.{a['id']}.rotulo"),
            "icone": str(a.get("icone") or "")[:40] or None, "onde": a.get("onde") or "configuracoes"}


def validar(dados, versao_app=None, pasta=None):
    """Confere o manifesto (dict) e devolve a versao limpa. Levanta ManifestoInvalido.
    versao_app: a versao deste app (confere o "app_minimo"). pasta: o pacote (confere a "entrada")."""
    if not isinstance(dados, dict):
        raise ManifestoInvalido("o manifesto precisa ser um objeto JSON")
    faltando = [c for c in ("formato", "api", "id", "nome", "versao", "entrada", "oferece") if c not in dados]
    if faltando:
        raise ManifestoInvalido("faltam campos no manifesto: " + ", ".join(faltando))
    if dados["formato"] != FORMATO:
        raise ManifestoInvalido(f"formato de manifesto desconhecido ({dados['formato']!r})")
    if dados["api"] not in APIS:
        raise ManifestoInvalido(f"este complemento usa a API {dados['api']!r}, que esta versão do Karaokê não "
                                "conhece: atualize o Karaokê")
    cid = str(dados["id"])
    if not ID_RE.match(cid):
        raise ManifestoInvalido(f"id inválido ({cid!r}): use de 2 a 40 letras minúsculas, números e hífen")
    versao = str(dados["versao"]).lstrip("v")
    if not SEMVER.match(versao):
        raise ManifestoInvalido(f"versão fora do padrão X.Y.Z ({dados['versao']!r})")
    minimo = dados.get("app_minimo")
    if minimo:
        if not SEMVER.match(str(minimo)):
            raise ManifestoInvalido(f"app_minimo fora do padrão X.Y.Z ({minimo!r})")
        if versao_app and not str(versao_app).startswith("0.0.0") and version_key(versao_app) < version_key(minimo):
            raise ManifestoInvalido(f"este complemento precisa do Karaokê {minimo} ou mais novo (você tem o "
                                    f"{versao_app}): atualize o Karaokê")
    oferece = dados["oferece"]
    if not isinstance(oferece, list) or not oferece:
        raise ManifestoInvalido('"oferece" precisa listar o que o complemento oferece')
    desconhecidos = [o for o in oferece if o not in OFERECE]
    if desconhecidos:
        raise ManifestoInvalido(f"o complemento oferece o que este Karaokê não conhece ({', '.join(map(str, desconhecidos))})")
    entrada = str(dados["entrada"])
    if pasta is not None:
        try:
            alvo = inside(Path(pasta) / entrada, pasta)
        except Refused:
            raise ManifestoInvalido(f'a entrada "{entrada}" fica fora do complemento') from None
        if not alvo.is_file():
            raise ManifestoInvalido(f'a entrada "{entrada}" não existe no complemento')
    elif Path(entrada).is_absolute() or ".." in Path(entrada).parts:
        raise ManifestoInvalido(f'a entrada "{entrada}" fica fora do complemento')
    dep = dados.get("dependencias")
    if dep and (Path(str(dep)).is_absolute() or ".." in Path(str(dep)).parts):
        raise ManifestoInvalido(f'as dependências "{dep}" ficam fora do complemento')
    opcoes = dados.get("opcoes") or []
    acoes = dados.get("acoes") or []
    acoes_musica = dados.get("acoes_musica") or []
    if not all(isinstance(x, list) for x in (opcoes, acoes, acoes_musica)):
        raise ManifestoInvalido('"opcoes", "acoes" e "acoes_musica" precisam ser listas')
    migrar = dados.get("migrar") or []
    if not isinstance(migrar, list) or any(
            not isinstance(m, str) or not m.strip() or Path(m).is_absolute() or ".." in Path(m).parts
            or Path(m).parts[0] in PROTEGIDOS for m in migrar):
        raise ManifestoInvalido('"migrar" só aceita arquivos da pasta de dados do app (nunca o banco, as músicas '
                                'nem as configurações)')
    limpo = {
        "formato": FORMATO,
        "api": dados["api"],
        "id": cid,
        "nome": _texto(dados["nome"], "nome"),
        "descricao": _texto(dados.get("descricao"), "descricao", obrigatorio=False),
        "autor": str(dados.get("autor") or "")[:80],
        "versao": versao,
        "app_minimo": minimo,
        "python": str(dados.get("python") or "3.12"),
        "entrada": entrada,
        "dependencias": str(dep) if dep else None,
        "oferece": oferece,
        "icone": str(dados.get("icone") or "extension")[:40],
        "celular": bool(dados.get("celular")),
        "opcoes": [_opcao(o, i) for i, o in enumerate(opcoes)],
        "acoes": [_acao(a, i, "ações") for i, a in enumerate(acoes)],
        "acoes_musica": [_acao(a, i, "ações da música") for i, a in enumerate(acoes_musica)],
        "migrar": migrar,
    }
    ids = [o["id"] for o in limpo["opcoes"]]
    if len(ids) != len(set(ids)):
        raise ManifestoInvalido("há opções com o mesmo id")
    return limpo


def ler(pasta, versao_app=None):
    """O manifesto de um pacote ja extraido."""
    p = Path(pasta) / ARQUIVO
    try:
        dados = json.loads(p.read_text(encoding="utf-8"))
    except FileNotFoundError:
        raise ManifestoInvalido(f"o repositório não tem o {ARQUIVO} na raiz: não é um complemento do Karaokê") from None
    except (OSError, ValueError) as exc:
        raise ManifestoInvalido(f"o {ARQUIVO} não é um JSON válido ({exc})") from None
    return validar(dados, versao_app, pasta)
