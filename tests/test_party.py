import json

import pytest

from karaoke import party as party_mod
from karaoke.history import History


class FakeLib:
    """So o que a fila usa da biblioteca."""

    def __init__(self, ids=("s1", "s2", "s3", "s4", "s5", "s6")):
        self.songs = {sid: {"id": sid, "status": "ready", "duration": 200, "title": sid, "settings": {}} for sid in ids}

    def get(self, sid):
        return self.songs.get(sid)

    def summary(self, meta):
        return {"id": meta["id"], "status": meta["status"], "duration": meta["duration"], "title": meta["title"]}

    def stem_path(self, sid, stem):
        return None


PEOPLE = {"acc-lu": {"id": "acc-lu", "name": "Lucas", "photo": 123}, "acc-jo": {"id": "acc-jo", "name": "João", "photo": 0}}


class Clock:
    def __init__(self):
        self.now = 1_000_000.0

    def __call__(self):
        return self.now


@pytest.fixture
def clock():
    return Clock()


@pytest.fixture
def make_party(tmp_path, monkeypatch, clock):
    """Party nova sobre o mesmo banco e o mesmo party.json (como reiniciar o servidor)."""
    monkeypatch.setattr(party_mod, "STATE_FILE", tmp_path / "party.json")
    logs = []

    def make():
        logs.append(History(tmp_path / "karaoke.db", clock=clock))
        return party_mod.Party(FakeLib(), logs[-1], people=PEOPLE.get, clock=clock)

    yield make
    for h in logs:
        h.db.close()


@pytest.fixture
def party(make_party):
    return make_party()


def sing(party, clock, score=None, minutes=4):
    """A musica no palco acaba (com nota) depois de alguns minutos."""
    clock.now += minutes * 60
    party.ended(party.current["id"], score=score)


def mine_ids(view):
    items = ([view["current"]] if view["current"] else []) + view["queue"]
    return {e["song_id"] for e in items if e["mine"]}


def test_account_entry_is_mine_on_any_device(party):
    party.add("s1", "Lucas", client="celular-1", account="acc-lu")
    assert mine_ids(party.view("celular-2", "acc-lu")) == {"s1"}  # outro aparelho, mesma conta
    assert mine_ids(party.view("celular-1", None)) == set()  # mesmo aparelho, sem a conta: nao
    assert mine_ids(party.view("celular-9", "acc-jo")) == set()


def test_guest_entry_belongs_to_device(party):
    party.add("s1", "Tia Rosa", client="pc")  # colocada pelo PC, sem conta
    assert mine_ids(party.view("pc", None)) == {"s1"}
    assert mine_ids(party.view("celular-1", "acc-lu")) == set()


def test_claim_moves_device_entries_to_account(party):
    party.add("s1", "lu", client="celular-1")  # antes de ter conta
    party.add("s2", "lu", client="celular-1")
    party.add("s3", "Tia Rosa", client="pc")
    party.ended(party.current["id"], score=90)  # s1 cantada: vai para o historico
    assert party.claim("celular-1", "acc-lu", "Lucas") == 2
    view = party.view("celular-7", "acc-lu")
    assert mine_ids(view) == {"s2"}  # o que sobrou na fila dela, visto de outro aparelho
    assert view["ranking"][0]["singer"] == "Lucas" and view["ranking"][0]["person"]["photo"] == 123
    assert party.claim("celular-1", "acc-lu", "Lucas") == 0  # de novo: nada muda
    assert party.can_touch(next(e["id"] for e in party.queue if e["song_id"] == "s3"), "celular-1", "acc-lu") is False


def test_claim_needs_device_and_account(party):
    party.add("s1", "lu", client="celular-1")
    assert party.claim("", "acc-lu", "Lucas") == 0
    assert party.claim("celular-1", None, "Lucas") == 0


def test_can_touch_and_on_stage(party):
    e1 = party.add("s1", "Lucas", client="celular-1", account="acc-lu")  # sobe ao palco
    e2 = party.add("s2", "João", client="celular-2", account="acc-jo")
    assert party.on_stage_is("outro", "acc-lu") and not party.on_stage_is("celular-2", "acc-jo")
    assert party.can_touch(e2["id"], "celular-5", "acc-jo")
    assert not party.can_touch(e2["id"], "celular-2", None)
    assert party.can_touch(e1["id"], "x", "acc-lu")


def test_move_own_by_account_across_devices(party):
    party.add("s1", "João", client="c-jo", account="acc-jo")  # palco
    a = party.add("s2", "Lucas", client="c-lu-1", account="acc-lu")
    party.add("s3", "João", client="c-jo", account="acc-jo")
    b = party.add("s4", "Lucas", client="c-lu-2", account="acc-lu")  # mesma conta, outro celular
    assert party.move_own(b["id"], -1)
    order = [e["song_id"] for e in party.view()["queue"]]
    assert order == ["s4", "s3", "s2"]  # trocou so entre as do Lucas; o João ficou no lugar
    assert a["id"] and not party.move_own(b["id"], -1)  # ja e a primeira dele


def test_person_in_views(party):
    party.add("s1", "Lucas", client="c1", account="acc-lu")
    party.add("s2", "Tia Rosa", client="pc")
    view = party.view()
    assert view["current"]["person"] == {"id": "acc-lu", "name": "Lucas", "photo": 123}
    assert view["queue"][0]["person"] == {"name": "Tia Rosa"}  # sem conta: so o nome


def test_rotation_uses_account_as_person(party):
    party.set_rotation(True)
    party.add("s1", "Lucas", client="c-lu-1", account="acc-lu")  # palco
    party.add("s2", "Lucas", client="c-lu-2", account="acc-lu")  # mesma pessoa, outro aparelho
    party.add("s3", "João", client="c-jo", account="acc-jo")
    assert [e["song_id"] for e in party.view()["queue"]] == ["s3", "s2"]  # João antes da 2a do Lucas


def test_old_saved_queue_keeps_working(tmp_path, make_party, clock):
    """party.json de antes das contas (sem "account"): continua por aparelho + nome."""
    (tmp_path / "party.json").write_text(json.dumps({
        "queue": [{"id": "e1", "song_id": "s1", "singer": "Ana", "client": "c1", "added_at": clock.now - 60,
                   "state": "queued"}], "current": None, "history": []}))
    p = make_party()
    assert mine_ids(p.view("c1", None)) == {"s1"}


# ------------------------------------------------------ historico por festa
def test_ranking_keeps_the_whole_party(party, clock):
    """Antes, so as ultimas 30 musicas contavam: a melhor nota do comeco da noite sumia."""
    party.add("s1", "Lucas", client="c1", account="acc-lu")
    sing(party, clock, score=99)
    for i in range(40):
        party.add("s2", f"Pessoa {i}", client="pc")
        sing(party, clock, score=50)
    view = party.view()
    assert view["ranking"][0]["singer"] == "Lucas" and view["ranking"][0]["score"] == 99
    assert len(view["history"]) == 10  # "ja cantaram" continua mostrando as ultimas


def test_history_survives_restart(make_party, clock):
    p1 = make_party()
    p1.add("s1", "Lucas", client="c1", account="acc-lu")
    sing(p1, clock, score=87)
    p2 = make_party()  # servidor reiniciou
    view = p2.view(None, "acc-lu")
    assert view["ranking"][0]["score"] == 87 and view["history"][0]["mine"]


def test_new_party_starts_from_zero_and_keeps_the_old_one(party, clock):
    party.add("s1", "Lucas", client="c1", account="acc-lu")
    sing(party, clock, score=90)
    party.add("s2", "João", client="c2", account="acc-jo")  # palco
    party.add("s3", "João", client="c2", account="acc-jo")  # fila
    old = party.party_id
    party.new_party()
    view = party.view()
    assert not view["current"] and not view["queue"] and not view["ranking"] and not view["history"]
    rows = party.archive.db.query("SELECT id, ended_at FROM parties")
    assert [(r["id"], r["ended_at"] is not None) for r in rows] == [(old, True)]  # guardada e fechada
    assert len(party.archive.performances(old)) == 1


def test_clear_keeps_the_ranking(party, clock):
    party.add("s1", "Lucas", client="c1", account="acc-lu")
    sing(party, clock, score=90)
    party.add("s2", "João", client="c2", account="acc-jo")
    party.clear()
    view = party.view()
    assert not view["queue"] and not view["current"] and view["ranking"][0]["score"] == 90


def test_party_without_songs_is_not_kept(party):
    party.add("s1", "Lucas", client="c1", account="acc-lu")  # ninguem cantou
    party.new_party()
    assert party.archive.db.query("SELECT COUNT(*) FROM parties")[0][0] == 0


def test_idle_hours_start_a_new_party(party, clock):
    party.add("s1", "Lucas", client="c1", account="acc-lu")
    sing(party, clock, score=90)
    party.add("s2", "João", client="c2", account="acc-jo")  # ficou no palco, ninguem deu play
    party.add("s3", "João", client="c2", account="acc-jo")
    clock.now += party_mod.IDLE_HOURS * 3600 - 60
    assert party.view()["ranking"]  # ainda e a mesma festa
    clock.now += 120
    view = party.view()  # dia seguinte: festa nova, sem a fila velha
    assert not view["ranking"] and not view["queue"] and not view["current"]
    ended = party.archive.db.query("SELECT ended_at FROM parties")[0][0]
    assert ended < clock.now - party_mod.IDLE_HOURS * 3600  # terminou quando parou, nao quando percebeu


def test_singing_keeps_the_party_alive(party, clock):
    for i in range(5):  # 5 musicas, uma a cada 2 h: nunca 6 h parada
        party.add("s1", "Lucas", client="c1", account="acc-lu")
        sing(party, clock, score=80 + i, minutes=120)
    assert len(party.view()["history"]) == 5


def test_idle_is_checked_when_adding_too(party, clock):
    party.add("s1", "Lucas", client="c1", account="acc-lu")
    sing(party, clock, score=90)
    clock.now += party_mod.IDLE_HOURS * 3600 + 1
    party.add("s2", "João", client="c2", account="acc-jo")  # primeira do dia seguinte
    view = party.view()
    assert not view["ranking"] and view["current"]["song_id"] == "s2"


def test_legacy_history_moves_to_database(tmp_path, make_party, clock):
    """party.json de antes do banco (com "history"): o ranking da noite nao se perde."""
    (tmp_path / "party.json").write_text(json.dumps({"queue": [], "current": None, "history": [
        {"id": "h1", "song_id": "s1", "singer": "Ana", "client": "c1", "state": "done", "score": 70,
         "finished_at": clock.now - 600, "title": "s1"},
        {"id": "h2", "song_id": "s2", "singer": "Lucas", "client": "c2", "account": "acc-lu", "state": "done",
         "score": 95, "finished_at": clock.now - 300, "title": "s2"}]}))
    p = make_party()
    assert [r["score"] for r in p.view()["ranking"]] == [95, 70]
    assert "history" not in json.loads((tmp_path / "party.json").read_text())
    again = make_party()  # reiniciar de novo nao importa duas vezes
    assert len(again.view()["ranking"]) == 2 and len(again.archive.performances(again.party_id)) == 2


def test_claim_moves_history_in_database(make_party, clock):
    p1 = make_party()
    p1.add("s1", "lu", client="celular-1")  # antes de ter conta
    sing(p1, clock, score=88)
    p1.claim("celular-1", "acc-lu", "Lucas")
    p2 = make_party()
    top = p2.view(None, "acc-lu")["ranking"][0]
    assert top["singer"] == "Lucas" and top["person"]["id"] == "acc-lu"


def test_database_failure_does_not_stop_the_queue(party, clock, monkeypatch):
    party.add("s1", "Lucas", client="c1", account="acc-lu")
    party.add("s2", "João", client="c2", account="acc-jo")

    def broken(*_args):
        raise OSError("disco cheio")

    monkeypatch.setattr(party.archive, "record", broken)
    sing(party, clock, score=90)
    assert party.view()["current"]["song_id"] == "s2"  # a fila andou



# ------------------------------------------------------------ passar a vez
def singers(party):
    view = party.view()
    return [view["current"]["singer"] if view["current"] else None] + [e["singer"] for e in view["queue"]]


def fill(party, names):
    """Uma musica por pessoa (sem conta, colocadas pelo PC), na ordem."""
    return {n: party.add(f"s{i + 1}", n, client="pc") for i, n in enumerate(names)}


@pytest.mark.parametrize("rotation", [False, True])
def test_pass_on_stage_lets_two_people_go_first(party, clock, rotation):
    party.set_rotation(rotation)
    e = fill(party, ["Ana", "Bia", "Caio", "Duda"])  # Ana no palco
    assert party.pass_turn(e["Ana"]["id"])
    assert singers(party) == ["Bia", "Caio", "Ana", "Duda"]  # nao saiu da fila
    sing(party, clock, score=80)
    assert singers(party) == ["Caio", "Ana", "Duda"]
    sing(party, clock, score=80)
    assert singers(party) == ["Ana", "Duda"]
    assert "Ana" not in [h["singer"] for h in party.view()["history"]]  # passar a vez nao conta como cantada


def test_pass_from_queue_when_next(party):
    e = fill(party, ["Ana", "Bia", "Caio", "Duda"])  # Ana no palco, Bia e a proxima
    assert party.pass_turn(e["Bia"]["id"])
    assert singers(party) == ["Ana", "Caio", "Duda", "Bia"]


def test_pass_with_nobody_ready_behind(party, clock):
    e = fill(party, ["Ana"])
    assert not party.pass_turn(e["Ana"]["id"])  # ninguem para passar na frente: continua no palco
    assert singers(party) == ["Ana"]
    party.lib.songs["s2"]["status"] = "processing"
    party.add("s2", "Bia", client="pc")  # ainda baixando: nao pode subir ao palco
    assert not party.pass_turn(e["Ana"]["id"])


def test_pass_skips_songs_not_ready(party):
    party.lib.songs["s2"]["status"] = "processing"
    e = fill(party, ["Ana", "Bia", "Caio"])  # Bia ainda baixando
    assert party.pass_turn(e["Ana"]["id"])
    assert party.view()["current"]["singer"] == "Caio"
    assert party.queue[0]["let_first"] == [e["Caio"]["id"]]  # so esperou quem podia cantar


def test_pass_twice_adds_up(party, clock):
    e = fill(party, ["Ana", "Bia", "Caio", "Duda", "Edu"])
    party.pass_turn(e["Ana"]["id"])  # Bia no palco; Caio, Ana, Duda, Edu
    party.pass_turn(e["Ana"]["id"])  # de novo, ainda na fila: deixa Duda e Edu tambem
    assert singers(party) == ["Bia", "Caio", "Duda", "Edu", "Ana"]


def test_pass_needs_existing_entry(party):
    fill(party, ["Ana", "Bia"])
    assert not party.pass_turn("nao-existe")



# ------------------------------------------------ musica que nao conseguiu baixar
def test_failed_download_leaves_queue_and_warns_owner(party):
    party.add("s1", "Ana", client="pc")  # palco
    party.lib.songs["s2"]["status"] = "downloading"
    party.add("s2", "Lucas", client="celular-1", account="acc-lu")
    party.add("s3", "João", client="c-jo", account="acc-jo")
    party.lib.songs["s2"]["status"] = "error"
    view = party.view("celular-9", "acc-lu")  # outro aparelho, mesma conta
    assert [e["song_id"] for e in view["queue"]] == ["s3"]
    assert [(n["kind"], n["singer"], n["title"]) for n in view["notices"]] == [("download_error", "Lucas", "s2")]
    assert party.view("c-jo", "acc-jo")["notices"] == []  # so o dono ve
    assert party.view("pc", None)["notices"] == []


def test_failed_guest_entry_warns_the_pc(party):
    party.add("s1", "Ana", client="pc")
    party.lib.songs["s2"]["status"] = "downloading"
    party.add("s2", "Tia Rosa", client="pc")
    party.lib.songs["s2"]["status"] = "error"
    assert [n["singer"] for n in party.view("pc", None)["notices"]] == ["Tia Rosa"]


def test_notices_expire(party, clock):
    party.lib.songs["s2"]["status"] = "downloading"
    party.add("s1", "Ana", client="pc")
    party.add("s2", "Ana", client="pc")
    party.lib.songs["s2"]["status"] = "error"
    first = party.view("pc", None)["notices"]
    assert len(first) == 1 and party.view("pc", None)["notices"] == first  # o mesmo aviso, sem repetir
    clock.now += party_mod.NOTICE_MINUTES * 60 + 1
    assert party.view("pc", None)["notices"] == []


def test_cannot_add_song_that_failed(party):
    party.lib.songs["s2"]["status"] = "error"
    with pytest.raises(ValueError):
        party.add("s2", "Ana", client="pc")



# ------------------------------------------------------ limite por pessoa
def test_limit_counts_waiting_songs_of_the_person(party):
    party.add("s1", "Lucas", client="c1", account="acc-lu", limit=3)  # vai ao palco: nao conta
    for sid in ("s2", "s3", "s4"):
        party.add(sid, "Lucas", client="c2", account="acc-lu", limit=3)  # outro aparelho, mesma conta
    assert party.waiting("c9", "acc-lu") == 3
    with pytest.raises(party_mod.LimitError) as e:
        party.add("s5", "Lucas", client="c1", account="acc-lu", limit=3)
    assert "3 músicas" in str(e.value)
    party.add("s5", "João", client="c-jo", account="acc-jo", limit=3)  # outra pessoa: tudo bem


def test_limit_frees_up_after_singing(party, clock):
    party.add("s1", "Ana", client="pc")  # palco
    party.add("s2", "Lucas", client="c1", account="acc-lu", limit=1)
    with pytest.raises(party_mod.LimitError):
        party.add("s3", "Lucas", client="c1", account="acc-lu", limit=1)
    sing(party, clock)  # Ana cantou; a do Lucas subiu ao palco
    party.add("s3", "Lucas", client="c1", account="acc-lu", limit=1)


def test_no_limit_by_default(party):
    for sid in ("s1", "s2", "s3", "s4", "s5", "s6"):
        party.add(sid, "Lucas", client="c1", account="acc-lu")
    assert party.waiting("c1", "acc-lu") == 5


# ----------------------------------------------- quem espera para cantar (biblioteca)
def test_wanted_songs_follow_the_queue(party, clock):
    party.lib.songs["s3"]["status"] = "downloading"
    party.add("s1", "Ana", client="pc")
    party.add("s3", "Bia", client="pc")  # ainda baixando: a biblioteca prepara esta primeiro
    assert party.wanted_songs() == {"s1", "s3"}
    party.remove(next(e["id"] for e in party.queue if e["song_id"] == "s3"))
    assert party.wanted_songs() == {"s1"}


def test_wanted_songs_after_restart(make_party):
    make_party().add("s2", "Ana", client="pc")
    assert make_party().wanted_songs() == {"s2"}
