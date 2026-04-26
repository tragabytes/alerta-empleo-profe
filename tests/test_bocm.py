"""Pruebas del descubrimiento de URLs XML del BOCM desde sus feeds RSS.

Cubre el bug observado durante Sprint 1: el RSS sólo expone enlaces HTML y
PDF, nunca XML directo. Hay que reconstruir la URL XML canónica desde la
combinación (fecha, número de boletín).
"""
from datetime import date

from vigia.sources.bocm import BOCMSource


def test_discover_extrae_de_pdf_url():
    """Si el RSS contiene una URL PDF, debemos generar el XML equivalente."""
    src = BOCMSource()
    rss_text = (
        '<item><link>https://www.bocm.es/boletin/bocm-20260425-97</link>'
        '<description>... '
        'https://www.bocm.es/boletin/CM_Boletin_BOCM/2026/04/25/'
        'BOCM-20260425097.PDF ...</description></item>'
    )
    candidates: dict = {}
    seen: set = set()
    # Reaprovechamos el helper privado y simulamos el regex de descubrimiento
    # parseando el RSS directamente con la API pública.
    import re
    from vigia.sources import bocm as bocm_mod
    for m in bocm_mod._BOLETIN_RE.finditer(rss_text):
        file_date = date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
        num = int(m.group(4))
        src._maybe_register(file_date, num, {file_date}, candidates, seen)

    assert len(candidates) == 1
    url, d = next(iter(candidates.items()))
    assert d == date(2026, 4, 25)
    assert url == (
        "https://www.bocm.es/boletin/CM_Boletin_BOCM/2026/04/25/"
        "BOCM-20260425097.xml"
    )


def test_discover_extrae_de_html_link():
    """El enlace HTML `/boletin/bocm-YYYYMMDD-N` también debe valer."""
    src = BOCMSource()
    rss_text = (
        '<item><title>BOCM 87</title>'
        '<link>https://www.bocm.es/boletin/bocm-20260412-87</link>'
        '</item>'
    )
    candidates: dict = {}
    seen: set = set()
    from vigia.sources import bocm as bocm_mod
    for m in bocm_mod._HTML_LINK_RE.finditer(rss_text):
        file_date = date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
        num = int(m.group(4))
        src._maybe_register(file_date, num, {file_date}, candidates, seen)

    assert len(candidates) == 1
    url, d = next(iter(candidates.items()))
    assert d == date(2026, 4, 12)
    assert "BOCM-20260412087.xml" in url


def test_descarta_fechas_fuera_de_rango():
    src = BOCMSource()
    candidates: dict = {}
    seen: set = set()
    src._maybe_register(
        date(2026, 4, 25), 97,
        target_dates={date(2026, 4, 1)},  # rango distinto
        candidates=candidates, seen_keys=seen,
    )
    assert candidates == {}


def test_no_duplica_misma_fecha_y_numero():
    src = BOCMSource()
    candidates: dict = {}
    seen: set = set()
    target = {date(2026, 4, 25)}
    src._maybe_register(date(2026, 4, 25), 97, target, candidates, seen)
    src._maybe_register(date(2026, 4, 25), 97, target, candidates, seen)
    assert len(candidates) == 1
