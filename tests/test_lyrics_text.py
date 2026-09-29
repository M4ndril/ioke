"""Sincronizar com IA nunca muda o texto: nem troca de letra, nem muda a ordem das linhas."""
import numpy as np

from karaoke import aligner, lyrics
from karaoke.library import base_lyrics

ORIGINAL = "[00:10.00]Primeira linha\n[00:20.00]Segunda (apoio)\n[00:30.00]Refrão aqui"
# a mesma letra depois da IA (tempo de cada palavra), com uma linha fora de ordem
FROM_AI = ("[00:09.75]<00:10.00>Primeira <00:10.50>linha<00:11.00>\n"
           "[00:29.75]<00:30.00>Refrão <00:30.50>aqui<00:31.00>\n"
           "[00:19.75]<00:20.00>Segunda <00:20.50>(apoio)<00:21.00>")
OTHER = "[00:10.00]Uma letra\n[00:20.00]totalmente diferente"


def test_same_text_ignores_timing_and_order():
    assert lyrics.same_text(ORIGINAL, FROM_AI)
    assert not lyrics.same_text(ORIGINAL, OTHER)
    assert lyrics.text_lines("[ar: X]\n[00:01.00][00:40.00]Refrão\n\n[00:05.00]") == ["Refrão", "Refrão"]


def ai_lyrics(**extra):
    return {"source": "ia", "base": "lrclib", **extra}


def test_sync_after_going_back_uses_the_text_on_screen(tmp_path):
    """Letra da IA -> "Usar" outra -> "Voltar para a anterior": o original guardado se
    perdeu e o lyrics-anterior e a OUTRA letra. Sincronizar tem que usar o texto da tela."""
    (tmp_path / "lyrics-anterior.lrc").write_text(OTHER, encoding="utf-8")
    base = base_lyrics(tmp_path, ai_lyrics(), FROM_AI, "sync")
    assert base["text"] == FROM_AI and base["source"] == "lrclib"
    assert base["guide"] is False  # os tempos sao da IA anterior: nao valem como referencia


def test_sync_prefers_saved_original_when_it_is_the_same_text(tmp_path):
    (tmp_path / "lyrics-base.lrc").write_text(ORIGINAL, encoding="utf-8")
    base = base_lyrics(tmp_path, ai_lyrics(), FROM_AI, "sync")
    assert base["text"] == ORIGINAL and base["guide"] is True  # ordem e tempos da letra de origem


def test_sync_ignores_saved_original_with_other_text(tmp_path):
    (tmp_path / "lyrics-base.lrc").write_text(OTHER, encoding="utf-8")
    assert base_lyrics(tmp_path, ai_lyrics(), FROM_AI, "sync")["text"] == FROM_AI


def test_sync_after_adapt_keeps_the_adapted_text(tmp_path):
    (tmp_path / "lyrics-base.lrc").write_text(ORIGINAL, encoding="utf-8")
    assert base_lyrics(tmp_path, ai_lyrics(mode="adapt"), FROM_AI + "\n[00:40.00]Refrão aqui",
                       "sync")["text"].endswith("Refrão aqui")


def test_adapt_starts_from_the_original(tmp_path):
    (tmp_path / "lyrics-base.lrc").write_text(ORIGINAL, encoding="utf-8")
    assert base_lyrics(tmp_path, ai_lyrics(mode="adapt"), FROM_AI, "adapt")["text"] == ORIGINAL


def test_downloaded_lyrics_are_used_as_they_are(tmp_path):
    (tmp_path / "lyrics-anterior.lrc").write_text(OTHER, encoding="utf-8")
    base = base_lyrics(tmp_path, {"source": "extras:rede"}, ORIGINAL, "sync")
    assert base == {"source": "extras:rede", "text": ORIGINAL, "guide": True}


# ------------------------------------------------------------ ordem das linhas
def words_of(text):
    return aligner._word_list(aligner.parse_lines(text))


def test_line_out_of_order_goes_back_between_neighbours(monkeypatch):
    monkeypatch.setattr(aligner, "_align_window", lambda *a, **k: None)  # sem modelo: espalha entre as vizinhas
    words = words_of("[00:01.00]um dois\n[00:02.00]tres quatro\n[00:03.00]cinco seis")
    times = [[10, 10.5, 1], [10.5, 11, 1], [5, 5.5, 1], [5.5, 6, 1], [20, 20.5, 1], [20.5, 21, 1]]
    fixed = aligner.keep_order(words, times, np.zeros((2000, 1)), 0.02)
    assert fixed == [{"line": 1, "why": "ordem"}]
    starts = [times[0][0], times[2][0], times[4][0]]
    assert starts == sorted(starts) and 11 <= times[2][0] < times[3][1] <= 20


def test_build_keeps_the_text_order():
    lines = aligner.parse_lines("[00:01.00]um dois\n[00:02.00]...\n[00:03.00]tres quatro")
    words = aligner._word_list(lines)
    times = [[30, 30.5, 1], [30.5, 31, 1], [10, 10.5, 1], [10.5, 11, 1]]  # tempos trocados de proposito
    lrc, _stats = aligner._build(lines, words, times)
    assert lyrics.text_lines(lrc) == ["um dois", "...", "tres quatro"]  # na ordem do arquivo, como no texto


# ------------------------------------------------------- tempos da letra de origem
SRC = "[00:10.00]um dois\n[00:20.00]tres quatro\n[00:30.00]cinco seis\n[00:40.00]sete oito\n[00:50.00]nove dez"


def aligned(starts):
    """Tempos da IA: cada linha com 2 palavras de 0,5 s a partir do inicio dado."""
    return [[s + k * 0.5, s + (k + 1) * 0.5, 1.0] for s in starts for k in range(2)]


def test_ai_lost_in_the_middle_goes_back_to_the_lyric_time(monkeypatch):
    monkeypatch.setattr(aligner, "_align_window", lambda *a, **k: None)  # sem modelo: espalha no tempo da letra
    lines = aligner.parse_lines(SRC)
    words = aligner._word_list(lines)
    times = aligned([10.2, 20.2, 52.0, 40.2, 50.2])  # a 3a linha foi parar 22 s depois
    fixed, off = aligner.guide_by_source(words, times, lines, np.zeros((5000, 1)), 0.02)
    assert off == 0.2 and [f["line"] for f in fixed] == [2]
    assert abs(times[4][0] - 30.2) < 0.01 and times[5][1] <= 40.2  # no tempo da letra, antes da proxima
    assert abs(times[0][0] - 10.2) < 0.01 and abs(times[8][0] - 50.2) < 0.01  # as certas continuam no lugar


def test_lyric_from_another_version_is_not_used(monkeypatch):
    monkeypatch.setattr(aligner, "_align_window", lambda *a, **k: None)
    lines = aligner.parse_lines(SRC)
    words = aligner._word_list(lines)
    times = aligned([3.0, 25.0, 33.0, 61.0, 70.0])  # nada bate: e outra versao (ao vivo, remix...)
    before = [list(t) for t in times]
    fixed, off = aligner.guide_by_source(words, times, lines, np.zeros((5000, 1)), 0.02)
    assert fixed == [] and off is None and times == before


def test_plain_text_has_no_guide():
    lines = aligner.parse_lines("um dois\ntres quatro")
    words = aligner._word_list(lines)
    assert aligner.guide_by_source(words, aligned([1, 5]), lines, np.zeros((500, 1)), 0.02) == ([], None)


def test_lyric_wrong_in_one_line_when_whisper_agrees_with_the_ai(monkeypatch):
    """A letra pode errar uma linha: se o Whisper ouviu a linha onde a IA pos, fica a IA."""
    monkeypatch.setattr(aligner, "_align_window", lambda *a, **k: None)
    lines = aligner.parse_lines(SRC)
    words = aligner._word_list(lines)
    times = aligned([10.2, 20.2, 35.0, 40.2, 50.2])  # 3a linha: a IA pos em 35 s, a letra diz 30 s
    heard = {4: {"start": 35.1}, 5: {"start": 35.6}}  # e o Whisper ouviu em 35 s
    fixed, _off = aligner.guide_by_source(words, times, lines, np.zeros((5000, 1)), 0.02, heard)
    assert times[4][0] == 35.0 and fixed == []  # ficou onde a IA e o Whisper concordam
    fixed, _off = aligner.guide_by_source(words, times := aligned([10.2, 20.2, 35.0, 40.2, 50.2]), lines,
                                          np.zeros((5000, 1)), 0.02, {})  # sem Whisper: vale a letra
    assert abs(times[4][0] - 30.2) < 0.01 and [f["line"] for f in fixed] == [2]
