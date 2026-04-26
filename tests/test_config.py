"""Pruebas básicas de config: normalización y consistencia de patrones."""
import re

from vigia.config import (
    CATEGORY_HINTS,
    FALSE_POSITIVE_PATTERNS,
    STRONG_PATTERNS,
    TARGET_MUNICIPIOS,
    WATCHLIST_ORGS,
    WEAK_CONTEXT_PATTERNS,
    normalize,
)


def test_normalize_quita_tildes_y_minusculas():
    assert normalize("Geografía e Historia") == "geografia e historia"
    assert normalize("ESPAÑOL para extranjeros") == "espanol para extranjeros"


def test_normalize_colapsa_no_alfanumericos():
    assert normalize("BOCM-12/04 (núm. 87)") == "bocm 12 04  num  87 "


def test_strong_patterns_compilan():
    for p in STRONG_PATTERNS:
        re.compile(p)


def test_weak_patterns_compilan():
    for ctx, conf in WEAK_CONTEXT_PATTERNS:
        re.compile(ctx)
        re.compile(conf)


def test_false_positive_patterns_compilan():
    for p in FALSE_POSITIVE_PATTERNS:
        re.compile(p)


def test_category_hints_normalizados():
    """Los hints se buscan por substring contra texto normalizado."""
    for cat, hints in CATEGORY_HINTS.items():
        for hint in hints:
            assert hint == normalize(hint), (
                f"Hint '{hint}' en categoría '{cat}' no está normalizado"
            )


def test_municipios_normalizados():
    for muni in TARGET_MUNICIPIOS:
        assert muni == normalize(muni), f"Municipio '{muni}' no normalizado"


def test_watchlist_patterns_normalizados():
    for org in WATCHLIST_ORGS:
        for p in org["patterns"]:
            # Los patrones pueden tener espacios al inicio/fin para evitar
            # matches parciales. La normalización debe ser idempotente.
            assert p == normalize(p), (
                f"Pattern '{p}' del organismo {org['id']} no está normalizado"
            )


def test_watchlist_ids_unicos():
    ids = [o["id"] for o in WATCHLIST_ORGS]
    assert len(ids) == len(set(ids)), "IDs duplicados en WATCHLIST_ORGS"
