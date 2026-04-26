"""Pruebas del fallback de host boe.es ↔ www.boe.es en BOESource."""
from unittest.mock import patch, MagicMock

import pytest
import requests

from vigia.sources.boe import BOESource


def _ok_response(status: int = 200, text: str = "ok") -> MagicMock:
    r = MagicMock()
    r.status_code = status
    r.text = text
    r.reason = "OK"
    r.json = MagicMock(return_value={})
    r.raise_for_status = MagicMock()
    r.close = MagicMock()
    return r


def test_fallback_se_dispara_en_timeout():
    """Si el host primario timeoutea, debe reintentar en el otro host."""
    src = BOESource()
    calls = []

    def fake_request(method, url, **kw):
        calls.append(url)
        if "www.boe.es" in url:
            raise requests.Timeout("simulated timeout")
        return _ok_response()

    with patch("vigia.sources.boe.requests.request", side_effect=fake_request):
        resp = src._get_with_host_fallback(
            "https://www.boe.es/datosabiertos/",
            timeout=10,
        )

    assert resp.status_code == 200
    # Debe haber probado primero www.boe.es y luego boe.es
    assert len(calls) == 2
    assert "www.boe.es" in calls[0]
    assert "://boe.es/" in calls[1]


def test_fallback_se_dispara_en_connection_error():
    src = BOESource()
    calls = []

    def fake_request(method, url, **kw):
        calls.append(url)
        if "www.boe.es" in url:
            raise requests.ConnectionError("simulated refused")
        return _ok_response()

    with patch("vigia.sources.boe.requests.request", side_effect=fake_request):
        resp = src._get_with_host_fallback(
            "https://www.boe.es/diario_boe/txt.php?id=BOE-X",
            timeout=10,
        )

    assert resp.status_code == 200
    assert len(calls) == 2


def test_no_fallback_en_4xx():
    """Errores HTTP 4xx no deben disparar fallback — el host responde, sólo
    es que el recurso no existe ahí."""
    src = BOESource()
    calls = []

    def fake_request(method, url, **kw):
        calls.append(url)
        return _ok_response(status=404)

    with patch("vigia.sources.boe.requests.request", side_effect=fake_request):
        resp = src._get_with_host_fallback(
            "https://www.boe.es/datosabiertos/api/boe/sumario/20991231",
            timeout=10,
        )

    assert resp.status_code == 404
    assert len(calls) == 1   # sin reintento


def test_fallback_propaga_si_ambos_hosts_fallan():
    src = BOESource()

    def always_timeout(method, url, **kw):
        raise requests.Timeout("simulated timeout")

    with patch("vigia.sources.boe.requests.request", side_effect=always_timeout):
        with pytest.raises(requests.Timeout):
            src._get_with_host_fallback(
                "https://www.boe.es/datosabiertos/",
                timeout=10,
            )


def test_url_externa_no_intenta_fallback():
    """URLs fuera del dominio BOE deben pasar tal cual sin lógica de fallback."""
    src = BOESource()
    calls = []

    def fake_request(method, url, **kw):
        calls.append(url)
        raise requests.Timeout("simulated")

    with patch("vigia.sources.boe.requests.request", side_effect=fake_request):
        with pytest.raises(requests.Timeout):
            src._get_with_host_fallback(
                "https://example.com/foo",
                timeout=10,
            )

    assert len(calls) == 1   # sin reintento
