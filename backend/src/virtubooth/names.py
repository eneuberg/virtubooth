"""Pseudonyms for guests: "Durstige Giraffe #17". No real names, ever."""

from __future__ import annotations

# adjective stems; the ending is picked to match the animal's grammatical gender
_ADJ = (
    "Tanzend", "Durstig", "Glitzernd", "Fröhlich", "Wild", "Lustig", "Laut",
    "Verrückt", "Schick", "Cool", "Flauschig", "Mutig", "Neugierig", "Funkelnd",
    "Hüpfend", "Singend", "Lässig", "Feurig", "Strahlend", "Kichernd",
)  # fmt: skip
_ENDING = {"m": "er", "f": "e", "n": "es"}
_ANIMALS = (
    ("Waschbär", "m"), ("Giraffe", "f"), ("Känguru", "n"), ("Pinguin", "m"),
    ("Otter", "m"), ("Ente", "f"), ("Lama", "n"), ("Flamingo", "m"),
    ("Eule", "f"), ("Faultier", "n"), ("Alpaka", "n"), ("Igel", "m"),
    ("Qualle", "f"), ("Koala", "m"), ("Panda", "m"), ("Robbe", "f"),
    ("Zebra", "n"), ("Krake", "m"), ("Biber", "m"), ("Möwe", "f"),
    ("Erdmännchen", "n"), ("Fuchs", "m"), ("Katze", "f"), ("Nashorn", "n"),
)  # fmt: skip


def pseudonym(user_id: int) -> str:
    # step through adjectives and animals at coprime strides so neighbours differ
    adj = _ADJ[(user_id * 7) % len(_ADJ)]
    animal, gender = _ANIMALS[(user_id * 5) % len(_ANIMALS)]
    return f"{adj}{_ENDING[gender]} {animal} #{user_id}"
