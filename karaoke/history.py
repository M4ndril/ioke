"""Historico das festas, no banco do karaoke: cada musica cantada (ou pulada) vira um
registro -- quem, qual musica, nota, quando -- dentro de uma festa. O ranking e as
listas de "ja cantaram" sao da festa de agora; as festas anteriores ficam guardadas
(base para historico por pessoa).

Quem decide quando uma festa acaba e a fila (karaoke/party.py).
"""
import time

from .db import Database

FIELDS = ("entry_id", "song_id", "title", "account_id", "singer", "singer_key", "client", "state", "score",
          "started_at", "finished_at")


def _entry(row):
    """Registro do banco -> o formato das entradas da fila (a fila usa "id" e "account")."""
    return {"id": row["entry_id"], "song_id": row["song_id"], "title": row["title"], "account": row["account_id"],
            "singer": row["singer"], "singer_key": row["singer_key"], "client": row["client"], "state": row["state"],
            "score": row["score"], "started_at": row["started_at"], "finished_at": row["finished_at"]}


class History:
    def __init__(self, database, clock=time.time):
        self.db = database if isinstance(database, Database) else Database(database)
        self.clock = clock

    def open_party(self):
        """A festa de agora: {"id", "started_at"} (ou None)."""
        rows = self.db.query("SELECT id, started_at FROM parties WHERE ended_at IS NULL ORDER BY id DESC LIMIT 1")
        return dict(rows[0]) if rows else None

    def start_party(self, started_at=None):
        """Festa nova (a anterior, se ainda aberta, termina agora)."""
        now = self.clock()
        with self.db.tx() as db:
            db.execute("UPDATE parties SET ended_at = ? WHERE ended_at IS NULL", (now,))
            cur = db.execute("INSERT INTO parties (started_at) VALUES (?)", (started_at or now,))
            return cur.lastrowid

    def end_party(self, party_id, ended_at=None):
        """Fecha a festa; se ninguem cantou nela, ela nem fica guardada."""
        with self.db.tx() as db:
            if not db.execute("SELECT 1 FROM performances WHERE party_id = ? LIMIT 1", (party_id,)).fetchone():
                db.execute("DELETE FROM parties WHERE id = ?", (party_id,))
            else:
                db.execute("UPDATE parties SET ended_at = ? WHERE id = ?", (ended_at or self.clock(), party_id))

    def record(self, party_id, entry):
        """Guarda uma musica que acabou (entrada da fila ja com state/score/title/finished_at)."""
        values = {"entry_id": entry["id"], "account_id": entry.get("account"),
                  **{k: entry.get(k) for k in FIELDS if k not in ("entry_id", "account_id")}}
        values["singer"] = values["singer"] or ""
        values["client"] = values["client"] or ""
        with self.db.tx() as db:
            db.execute(f"INSERT INTO performances (party_id, {', '.join(FIELDS)}) VALUES (?{', ?' * len(FIELDS)})",
                       (party_id, *(values[k] for k in FIELDS)))

    def performances(self, party_id):
        """Tudo o que foi cantado na festa, na ordem."""
        rows = self.db.query("SELECT * FROM performances WHERE party_id = ? ORDER BY finished_at, id", (party_id,))
        return [_entry(r) for r in rows]

    def claim(self, client, account_id, name, singer_key):
        """Aparelho que entrou numa conta: o que ele cantou antes, sem conta, passa para a conta."""
        with self.db.tx() as db:
            cur = db.execute("UPDATE performances SET account_id = ?, singer = ?, singer_key = ? "
                             "WHERE account_id IS NULL AND client = ?", (account_id, name, singer_key, client))
            return cur.rowcount
