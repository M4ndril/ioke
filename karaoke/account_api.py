"""Rotas das contas (/api/account/...). Ficam num blueprint proprio para poderem
ser testadas sem subir o app inteiro (biblioteca, GPU, complementos).

Sessao: o token vai no cabecalho X-Session (guardado pelo app no aparelho) e,
como reserva, num cookie HttpOnly. Qualquer um dos dois vale."""
from flask import Blueprint, jsonify, request, send_file

from .accounts import AccountError

COOKIE = "sessao"
COOKIE_AGE = 365 * 24 * 3600


def session_token():
    return (request.headers.get("X-Session") or request.cookies.get(COOKIE) or "")[:200]


def make_blueprint(accounts, can_manage, on_sign_in=None):
    """accounts: Accounts. can_manage(): o pedido vem do PC do karaoke ou de um administrador?
    on_sign_in(conta) -> conta: chamado ao entrar/criar (ex.: celular que ja era administrador)."""
    bp = Blueprint("account", __name__)

    def device():
        return request.headers.get("User-Agent") or ""

    def signed_in(account, token):
        if on_sign_in:
            account = on_sign_in(account)
        resp = jsonify({"account": account, "token": token})
        resp.set_cookie(COOKIE, token, max_age=COOKIE_AGE, httponly=True, samesite="Lax")
        return resp

    @bp.errorhandler(AccountError)
    def on_account_error(exc):
        body = {"error": str(exc), "code": exc.code}
        if exc.retry_after:
            body["retry_after"] = exc.retry_after
        return jsonify(body), 429 if exc.code == "espera" else 400

    @bp.get("/api/account")
    def me():
        """Quem e este aparelho (account: null se nao entrou)."""
        return jsonify({"account": accounts.session(session_token())})

    @bp.get("/api/account/exists")
    def exists():
        """Esse nome ja tem conta? (a tela decide entre "crie um PIN" e "digite o PIN")"""
        name = accounts.find_name(request.args.get("name") or "")
        return jsonify({"exists": name is not None, "name": name})

    @bp.post("/api/account")
    def create():
        body = request.get_json(silent=True) or {}
        account, token = accounts.create(body.get("name"), body.get("pin"), device())
        return signed_in(account, token)

    @bp.post("/api/account/login")
    def login():
        body = request.get_json(silent=True) or {}
        account, token = accounts.login(body.get("name") or "", body.get("pin"), device())
        return signed_in(account, token)

    @bp.post("/api/account/logout")
    def logout():
        accounts.logout(session_token())
        resp = jsonify({"ok": True})
        resp.delete_cookie(COOKIE)
        return resp

    @bp.post("/api/account/photo")
    def photo():
        account = accounts.session(session_token())
        if not account:
            return jsonify({"error": "erro.entre_primeiro", "code": "sessao"}), 401
        file = request.files.get("photo")
        version = accounts.set_photo(account["id"], file.read() if file else b"")
        return jsonify({"account": {**account, "photo": version}})

    @bp.get("/api/account/<account_id>/photo")
    def get_photo(account_id):
        path = accounts.photo_path(account_id)
        if not path:
            return jsonify({"error": "erro.sem_foto"}), 404
        return send_file(path, mimetype="image/jpeg", max_age=7 * 24 * 3600)  # a URL leva ?v=versao

    @bp.get("/api/accounts")
    def list_accounts():
        """Contas para o PC do karaoke (ou um administrador) gerenciar."""
        if not can_manage():
            return jsonify({"error": "erro.so_pc_ou_admin"}), 403
        return jsonify({"accounts": accounts.list()})

    @bp.post("/api/account/<account_id>/pin")
    def reset_pin(account_id):
        """Esqueceu o PIN: o PC do karaoke (ou um administrador) define um novo."""
        if not can_manage():
            return jsonify({"error": "erro.so_pc_ou_admin"}), 403
        accounts.reset_pin(account_id, (request.get_json(silent=True) or {}).get("pin"))
        return jsonify({"ok": True})

    return bp
