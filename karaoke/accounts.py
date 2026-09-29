"""Contas das pessoas da festa: nome + PIN de 4 numeros, guardadas no PC do
karaoke (SQLite em data/karaoke.db). A identidade nao depende do navegador do
celular: se ele esquecer o login (iOS, aba anonima, IP novo), a pessoa entra de
novo com nome + PIN e volta a ser ela mesma.

Seguranca do tamanho do problema (rede local de uma festa): PIN com hash scrypt,
sessao guardada so como hash, 5 PINs errados seguidos -> 1 minuto de espera.
"""
import hashlib
import hmac
import io
import os
import secrets
import sqlite3
import threading
import time
from pathlib import Path

from . import i18n
from .db import Database
from .util import norm

NAME_MAX = 30
MAX_FAILS = 5  # PINs errados seguidos...
LOCK_SECONDS = 60  # ...e a espera depois deles
SEEN_EVERY = 300  # s: "visto por ultimo" e gravado no maximo a cada 5 min (menos escrita no disco)
PHOTO_SIZE = 256
PHOTO_MAX_BYTES = 15 * 1024 * 1024


class AccountError(Exception):
    """Erro para mostrar a pessoa (nome invalido, PIN errado...).
    code: "nome", "pin", "existe", "nao_existe", "pin_errado", "espera", "foto"."""

    def __init__(self, message, code, retry_after=0):
        super().__init__(message)
        self.code = code
        self.retry_after = retry_after


def name_key(name):
    return norm(name)


def clean_name(name):
    name = " ".join((name or "").split())
    if not name_key(name):
        raise AccountError(i18n.t("conta.digite_nome"), "nome")
    if len(name) > NAME_MAX:
        raise AccountError(i18n.t("conta.nome_longo", max=NAME_MAX), "nome")
    return name


def clean_pin(pin):
    pin = (pin or "").strip()
    if not (len(pin) == 4 and pin.isascii() and pin.isdigit()):
        raise AccountError(i18n.t("conta.pin_4"), "pin")
    return pin


def _hash_pin(pin, salt):
    return hashlib.scrypt(pin.encode(), salt=salt, n=2 ** 14, r=8, p=1, dklen=32)


def _token_hash(token):
    return hashlib.sha256(token.encode()).hexdigest()


def _public(row):
    """O que pode sair do servidor sobre uma conta (nunca o PIN)."""
    return {"id": row["id"], "name": row["name"], "photo": row["photo"], "admin": bool(row["admin"]),
            "created_at": row["created_at"]}


class Accounts:
    def __init__(self, database, photo_dir, clock=time.time):
        """`database`: o banco do karaoke (Database) ou o caminho do arquivo."""
        self.database = database if isinstance(database, Database) else Database(database)
        self.db = self.database.conn
        self.lock = self.database.lock
        self._tx = self.database.tx
        self.photo_dir = Path(photo_dir)
        self.clock = clock  # os testes trocam o relogio
        self._fails = {}  # chave do nome -> (erros seguidos, bloqueado ate)
        self._fails_lock = threading.Lock()

    def close(self):
        self.database.close()

    # -------------------------------------------------------------- banco

    def _new_session(self, db, account_id, device):
        token = secrets.token_urlsafe(32)
        now = self.clock()
        db.execute("INSERT INTO sessions (token_hash, account_id, device, created_at, seen_at) VALUES (?, ?, ?, ?, ?)",
                   (_token_hash(token), account_id, (device or "")[:200], now, now))
        db.execute("UPDATE accounts SET seen_at = ? WHERE id = ?", (now, account_id))
        return token

    # -------------------------------------------------------------- contas
    def find_name(self, name):
        """O nome como esta na conta ("joao b" -> "João B."), ou None se nao tem conta."""
        key = name_key(name)
        if not key:
            return None
        with self.lock:
            row = self.db.execute("SELECT name FROM accounts WHERE name_key = ?", (key,)).fetchone()
        return row[0] if row else None

    def exists(self, name):
        return self.find_name(name) is not None

    def get(self, account_id):
        with self.lock:
            row = self.db.execute("SELECT * FROM accounts WHERE id = ?", (account_id,)).fetchone()
        return _public(row) if row else None

    def create(self, name, pin, device=""):
        """Conta nova + sessao. Devolve (conta, token)."""
        name, pin = clean_name(name), clean_pin(pin)
        salt = os.urandom(16)
        pin_hash = _hash_pin(pin, salt)  # fora do lock: leva alguns milissegundos
        account_id = secrets.token_hex(8)
        try:
            with self._tx() as db:
                db.execute("INSERT INTO accounts (id, name, name_key, pin_hash, pin_salt, created_at) VALUES (?, ?, ?, ?, ?, ?)",
                           (account_id, name, name_key(name), pin_hash, salt, self.clock()))
                token = self._new_session(db, account_id, device)
        except sqlite3.IntegrityError:
            raise AccountError(i18n.t("conta.existe"), "existe") from None
        return self.get(account_id), token

    def login(self, name, pin, device=""):
        """Entrar com nome + PIN. Devolve (conta, token)."""
        key = name_key(name)
        pin = clean_pin(pin)
        now = self.clock()
        with self._fails_lock:
            until = self._fails.get(key, (0, 0))[1]
        if until > now:
            wait = int(until - now) + 1
            raise AccountError(i18n.t("conta.espera", s=wait), "espera", wait)
        with self.lock:
            row = self.db.execute("SELECT * FROM accounts WHERE name_key = ?", (key,)).fetchone()
        if not row:
            raise AccountError(i18n.t("conta.nao_achei"), "nao_existe")
        if not hmac.compare_digest(_hash_pin(pin, row["pin_salt"]), row["pin_hash"]):
            with self._fails_lock:
                fails = self._fails.get(key, (0, 0))[0] + 1
                self._fails[key] = (0, now + LOCK_SECONDS) if fails >= MAX_FAILS else (fails, 0)
            if fails >= MAX_FAILS:
                raise AccountError(i18n.t("conta.espera", s=LOCK_SECONDS), "espera", LOCK_SECONDS)
            raise AccountError(i18n.t("conta.pin_errado"), "pin_errado")
        with self._fails_lock:
            self._fails.pop(key, None)
        with self._tx() as db:
            token = self._new_session(db, row["id"], device)
        return _public(row), token

    def session(self, token):
        """A conta dona deste token (ou None)."""
        if not token:
            return None
        th = _token_hash(token)
        with self.lock:
            row = self.db.execute("SELECT a.*, s.seen_at AS s_seen FROM sessions s JOIN accounts a ON a.id = s.account_id "
                                  "WHERE s.token_hash = ?", (th,)).fetchone()
        if not row:
            return None
        now = self.clock()
        if now - row["s_seen"] > SEEN_EVERY:
            with self._tx() as db:
                db.execute("UPDATE sessions SET seen_at = ? WHERE token_hash = ?", (now, th))
                db.execute("UPDATE accounts SET seen_at = ? WHERE id = ?", (now, row["id"]))
        return _public(row)

    def logout(self, token):
        if token:
            with self._tx() as db:
                db.execute("DELETE FROM sessions WHERE token_hash = ?", (_token_hash(token),))

    def reset_pin(self, account_id, pin):
        """Esqueceu o PIN (pelo administrador): PIN novo e todos os aparelhos saem."""
        pin = clean_pin(pin)
        salt = os.urandom(16)
        pin_hash = _hash_pin(pin, salt)
        with self._tx() as db:
            cur = db.execute("UPDATE accounts SET pin_hash = ?, pin_salt = ? WHERE id = ?", (pin_hash, salt, account_id))
            if not cur.rowcount:
                raise AccountError(i18n.t("conta.nao_encontrada"), "nao_existe")
            db.execute("DELETE FROM sessions WHERE account_id = ?", (account_id,))
        with self.lock:
            key = self.db.execute("SELECT name_key FROM accounts WHERE id = ?", (account_id,)).fetchone()[0]
        with self._fails_lock:
            self._fails.pop(key, None)

    def set_admin(self, account_id, admin=True):
        with self._tx() as db:
            db.execute("UPDATE accounts SET admin = ? WHERE id = ?", (1 if admin else 0, account_id))

    def clear_admins(self):
        """O codigo do QR de administrador foi trocado: nenhuma conta continua administradora."""
        with self._tx() as db:
            db.execute("UPDATE accounts SET admin = 0")

    def list(self):
        """Todas as contas (para o PC do karaoke), com quando foram vistas por ultimo."""
        with self.lock:
            rows = self.db.execute("SELECT * FROM accounts ORDER BY name COLLATE NOCASE").fetchall()
        return [{**_public(r), "seen_at": r["seen_at"]} for r in rows]

    # -------------------------------------------------------------- foto
    def photo_path(self, account_id):
        path = self.photo_dir / f"{account_id}.jpg"
        return path if path.exists() else None

    def set_photo(self, account_id, data):
        """Foto tirada na hora ou da galeria: quadrada, 256 px, JPEG."""
        from PIL import Image, ImageOps

        if not self.get(account_id):
            raise AccountError(i18n.t("conta.nao_encontrada"), "nao_existe")
        if not data or len(data) > PHOTO_MAX_BYTES:
            raise AccountError(i18n.t("conta.foto_tamanho"), "foto")
        try:
            img = ImageOps.exif_transpose(Image.open(io.BytesIO(data)))  # celular grava "de lado" + EXIF
            img = ImageOps.fit(img.convert("RGB"), (PHOTO_SIZE, PHOTO_SIZE), Image.LANCZOS)
        except Exception:  # noqa: BLE001
            raise AccountError(i18n.t("conta.foto_invalida"), "foto") from None
        self.photo_dir.mkdir(parents=True, exist_ok=True)
        tmp = self.photo_dir / f"{account_id}.tmp"
        img.save(tmp, "JPEG", quality=86)
        os.replace(tmp, self.photo_dir / f"{account_id}.jpg")
        version = int(self.clock() * 1000)
        with self._tx() as db:
            db.execute("UPDATE accounts SET photo = ? WHERE id = ?", (version, account_id))
        return version
