"""QR codes, pure rules: the animal list, picking animals, token and note rules,
names and entry paths (domain/codes.py)."""

from __future__ import annotations

import random
from collections import Counter

import pytest

from virtubooth.domain import codes as dc
from virtubooth.domain.names import _ANIMALS as GUEST_ANIMALS


def test_100_unique_animals_none_like_a_guest_pseudonym():
    assert len(dc.ANIMALS) == 100 == len(set(dc.ANIMALS))
    guests = [animal.lower() for animal, _ in GUEST_ANIMALS]
    for animal in dc.ANIMALS:
        low = animal.lower()
        clash = [g for g in guests if g in low or low in g]
        assert not clash, (animal, clash)
        assert animal == animal.strip() and " " not in animal


def test_pick_animal_prefers_unused_then_least_used():
    rng = random.Random(7)
    counts: Counter[str] = Counter()
    for _ in range(100):
        animal = dc.pick_animal(counts, rng)
        assert counts[animal] == 0
        counts[animal] += 1
    assert set(counts) == set(dc.ANIMALS)
    # all used once: the next round starts, again every animal once
    second = Counter[str]()
    for _ in range(100):
        animal = dc.pick_animal(counts, rng)
        assert counts[animal] == 1
        counts[animal] += 1
        second[animal] += 1
    assert set(second.values()) == {1}


def test_pick_animal_takes_the_least_used_one():
    counts = dict.fromkeys(dc.ANIMALS, 3) | {"Uhu": 1, "Gnu": 2}
    assert {dc.pick_animal(counts, random.Random(n)) for n in range(20)} == {"Uhu"}
    # unknown names in the counts (an old list) are ignored
    assert dc.pick_animal({"Giraffe": 0} | dict.fromkeys(dc.ANIMALS, 1), random.Random(1))


def test_pick_animal_is_random_but_seedable():
    picks = [dc.pick_animal({}, random.Random(n)) for n in range(30)]
    assert len(set(picks)) > 10
    assert dc.pick_animal({}, random.Random(3)) == dc.pick_animal({}, random.Random(3))


@pytest.mark.parametrize(
    ("token", "problem"),
    [
        ("short-token", dc.TOKEN_INVALID),
        ("a" * 129, dc.TOKEN_INVALID),
        ("has spaces in the token", dc.TOKEN_INVALID),
        (" leading-space-token", dc.TOKEN_INVALID),
        ("umlaut-token-äöü-xyz", dc.TOKEN_INVALID),
        ("https://party.example/?t=abcdefghijklmnop", dc.TOKEN_INVALID),
        ("abcdefghijklmnop+q", dc.TOKEN_INVALID),
        ("", dc.TOKEN_INVALID),
        ("aaaaaaaaaaaaaaaa", dc.TOKEN_TOO_SIMPLE),
        ("abababababababab", dc.TOKEN_TOO_SIMPLE),
        ("abcdeabcdeabcdeabcde", dc.TOKEN_TOO_SIMPLE),
        ("abcdefabcdefabcd", None),
        ("test-party-token-0123456789", None),
        ("A" * 60 + "bcdefg" + "_" * 62, None),
    ],
)
def test_token_problem(token, problem):
    assert dc.token_problem(token) == problem


def test_messages_are_the_contract():
    assert dc.TOKEN_INVALID == (
        "Das Token braucht 16 bis 128 Zeichen aus A–Z, a–z, 0–9, _ und - (ohne Leerzeichen)."
    )
    assert dc.TOKEN_TOO_SIMPLE == (
        "Das Token ist zu einfach. Nimm mehr verschiedene Zeichen oder lass eins erzeugen."
    )
    assert dc.NOTE_TOO_LONG == "Die Notiz darf höchstens 60 Zeichen haben."


def test_generated_tokens_pass_the_rules():
    tokens = {dc.new_token() for _ in range(200)}
    assert len(tokens) == 200
    for token in tokens:
        assert len(token) == 24 and dc.token_problem(token) is None


def test_note_problem():
    assert dc.note_problem("") is None
    assert dc.note_problem("Eingang 🍻") is None
    assert dc.note_problem("x" * 60) is None
    assert dc.note_problem("x" * 61) == dc.NOTE_TOO_LONG
    assert dc.note_problem("zwei\nZeilen") == dc.NOTE_CONTROL
    assert dc.note_problem("tab\there") == dc.NOTE_CONTROL
    assert dc.note_problem("del\x7f") == dc.NOTE_CONTROL


def test_hash_end_name_and_entry_path():
    assert dc.token_hash("abc") == (
        "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad"
    )
    assert dc.token_end("test-party-token-0123456789") == "6789"
    assert dc.code_name("Gorilla", 2) == "Gorilla 2"
    assert dc.entry_path("", "tok") == "/?t=tok"
    assert dc.entry_path("booth", "tok") == "/x/booth/?t=tok"


def test_party_code_name_and_state():
    code = dc.PartyCode(
        id=4, animal="Uhu", token="t" * 16, token_gen=1, target="", note="", created_at="x",
        created_by="system", updated_at="x", revoked_at=None, revoked_by=None,
    )  # fmt: skip
    assert code.name == "Uhu 4" and code.active
    assert not dc.PartyCode(**{**code.__dict__, "revoked_at": "y"}).active
    assert dc.CodeStats() == dc.CodeStats(0, 0, 0, 0, 0, 0, None, None)
