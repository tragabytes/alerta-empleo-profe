"""Pruebas del storage: dedup, migración idempotente, persistencia."""
from datetime import date
from pathlib import Path

import pytest

from vigia import storage as storage_mod
from vigia.storage import Item, Storage


@pytest.fixture
def temp_storage(tmp_path, monkeypatch):
    db_path = tmp_path / "seen.db"
    monkeypatch.setattr(storage_mod, "DB_PATH", db_path)
    s = Storage()
    yield s
    s.close()


def _make_item(titulo: str, source: str = "boe", url: str = "http://x/1") -> Item:
    return Item(
        source=source, url=url, titulo=titulo,
        fecha=date(2026, 4, 1), categoria="oposicion",
    )


def test_filter_new_dedupes(temp_storage):
    item = _make_item("Convocatoria 005 GH")
    new1 = temp_storage.filter_new([item])
    new2 = temp_storage.filter_new([item])
    assert len(new1) == 1
    assert len(new2) == 0


def test_save_and_is_new(temp_storage):
    item = _make_item("Plazas Cuerpo 0590")
    assert temp_storage.is_new(item) is True
    temp_storage.save(item)
    assert temp_storage.is_new(item) is False


def test_diferentes_titulos_son_distintos(temp_storage):
    a = _make_item("Convocatoria A", url="http://x/a")
    b = _make_item("Convocatoria B", url="http://x/b")
    new = temp_storage.filter_new([a, b])
    assert len(new) == 2


def test_update_summary_persiste(temp_storage):
    item = _make_item("Convocatoria con resumen")
    temp_storage.save(item)
    item.summary = "200 plazas, plazo cierra 30/04"
    temp_storage.update_summary(item)
    pending = temp_storage.iter_items_without_summary()
    # El item con summary ya no debe aparecer en pending
    assert all(p.id_hash != item.id_hash for p in pending)


def test_update_enrichment_v2(temp_storage):
    item = _make_item("Lectorado AECID 2026")
    temp_storage.save(item)
    item.is_relevant = True
    item.process_type = "lectorado"
    item.plazas = 150
    item.deadline_inscripcion = "2026-01-30"
    item.organismo = "AECID"
    item.summary = "150 plazas en 70 países"
    item.enriched_version = 2
    temp_storage.update_enrichment(item)

    # Vuelve a leerlo de la BD vía iter_items_for_enrichment: ya no debe aparecer
    pending = temp_storage.iter_items_for_enrichment()
    assert all(p.id_hash != item.id_hash for p in pending)
