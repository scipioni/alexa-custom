from __future__ import annotations

import logging
import re
import unicodedata

logger = logging.getLogger(__name__)

_UNITS: list[tuple[str, int]] = [
    ("zero", 0),
    ("uno", 1),
    ("due", 2),
    ("tre", 3),
    ("quattro", 4),
    ("cinque", 5),
    ("sei", 6),
    ("sette", 7),
    ("otto", 8),
    ("nove", 9),
]

_TEENS: list[tuple[str, int]] = [
    ("dieci", 10),
    ("undici", 11),
    ("dodici", 12),
    ("tredici", 13),
    ("quattordici", 14),
    ("quindici", 15),
    ("sedici", 16),
    ("diciassette", 17),
    ("diciotto", 18),
    ("diciannove", 19),
]

_TENS: list[tuple[str, int]] = [
    ("venti", 20),
    ("trenta", 30),
    ("quaranta", 40),
    ("cinquanta", 50),
    ("sessanta", 60),
    ("settanta", 70),
    ("ottanta", 80),
    ("novanta", 90),
]


def _build_number_map() -> dict[str, int]:
    m: dict[str, int] = {}
    for word, val in _UNITS:
        m[word] = val
    for word, val in _TEENS:
        m[word] = val
    for word, val in _TENS:
        m[word] = val
    m["cento"] = 100

    for tens_word, tens_val in _TENS:
        for unit_word, unit_val in _UNITS:
            if unit_val == 0:
                continue
            if unit_val in (1, 8):
                compound = tens_word[:-1] + unit_word
            else:
                compound = tens_word + unit_word
            if unit_val == 3:
                m[compound] = tens_val + unit_val
                m[compound.replace("tré", "tre")] = tens_val + unit_val
            else:
                m[compound] = tens_val + unit_val
    return m


_NUMBERS = _build_number_map()


def _normalize(text: str) -> str:
    nfd = unicodedata.normalize("NFD", text.lower())
    stripped = "".join(c for c in nfd if not unicodedata.combining(c))
    return unicodedata.normalize("NFC", stripped).strip()


def parse_percentage(transcript: str) -> float | None:
    text = _normalize(transcript)
    if not text:
        return None

    value: int | None = None

    m = re.search(r"(\d+)\s*%", text)
    if m:
        value = int(m.group(1))
    else:
        m = re.search(r"(\d+)\s+per\s+cento", text)
        if m:
            value = int(m.group(1))
        else:
            m = re.search(r"(\d+)", text)
            if m:
                val = int(m.group(1))
                if val <= 100:
                    value = val

    if value is None:
        stripped = text.replace("per cento", "").replace("%", "")
        tokens = re.findall(r"[a-z]+", stripped)
        found = [_NUMBERS[t] for t in tokens if t in _NUMBERS]
        if found:
            value = sum(found)

    if value is None:
        return None

    result = max(0.0, min(1.0, value / 100.0))
    return result
