"""
Punto de entrada del pipeline vigia-profe.

Uso:
    python -m vigia.main                     # procesa desde ayer (o viernes si es lunes)
    python -m vigia.main --since 2024-01-01  # backfill desde fecha
    python -m vigia.main --dry-run           # imprime sin guardar ni notificar
    python -m vigia.main --probe             # comprueba salud de fuentes
    python -m vigia.main --maintenance       # reclasifica + enriquece pendientes

Flujo:
    sources/*.py → extractor.py → enricher.py (opcional) → notifier.py + dashboard.py
"""
from __future__ import annotations

import argparse
import logging
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date, timedelta
from pathlib import Path

from vigia import dashboard, enricher, maintenance
from vigia.config import SOURCES_ENABLED
from vigia.extractor import extract
from vigia.notifier import send
from vigia.sources.bocm import BOCMSource
from vigia.sources.boe import BOESource
from vigia.storage import Storage

logger = logging.getLogger(__name__)

# Directorio donde se vuelcan los JSON que consume el dashboard web.
# El workflow lo pushea a la rama gh-pages tras cada run.
DASHBOARD_OUT_DIR = "docs/data"

SOURCE_REGISTRY = {
    "boe": BOESource,
    "bocm": BOCMSource,
    # Sprint 2+: infojobs, jooble, telegram_channels…
}


def _default_since() -> date:
    """Devuelve la fecha de inicio por defecto: ayer en días laborables,
    o el viernes anterior si hoy es lunes."""
    today = date.today()
    if today.weekday() == 0:  # lunes → cubre el viernes anterior
        return today - timedelta(days=3)
    return today - timedelta(days=1)


def _collect_probe_results(enabled_classes: list) -> list[dict]:
    """Ejecuta probe() en paralelo sobre cada fuente y devuelve los resultados."""
    with ThreadPoolExecutor(max_workers=4) as pool:
        futures = {pool.submit(cls().probe): cls.name for cls in enabled_classes}
        results = []
        for future in as_completed(futures):
            try:
                results.append(future.result())
            except Exception as exc:
                results.append({
                    "name": futures[future],
                    "status": "error",
                    "code": None,
                    "url": "?",
                    "detail": f"unexpected: {exc}",
                })
    return results


def _run_probe(enabled_classes: list) -> int:
    results = _collect_probe_results(enabled_classes)

    print(f"\n{'FUENTE':<22} {'ESTADO':<10} {'CODE':<6} URL")
    print("-" * 100)
    any_error = False
    for r in sorted(results, key=lambda x: x["name"]):
        if r["status"] == "error":
            any_error = True
        code = str(r["code"] or "-")
        url = (r["url"] or "")[:60]
        print(f"{r['name']:<22} {r['status']:<10} {code:<6} {url}")
        if r["status"] == "error" and r["detail"]:
            print(f"{'':>22} {'':<10} {'':<6} → {r['detail'][:200]}")
    print()

    try:
        storage = Storage()
        dashboard.export_all(storage, Path(DASHBOARD_OUT_DIR), probe_results=results)
        storage.close()
    except Exception as exc:
        logger.warning("No se pudo exportar el dashboard tras --probe: %s", exc)

    return 1 if any_error else 0


def _run_maintenance() -> int:
    storage = Storage()
    n_recat = maintenance.reclassify_all(storage)
    logger.info("Maintenance: %d items reclasificados", n_recat)
    n_enriched = enricher.enrich_pending(storage)
    logger.info("Maintenance: %d items enriquecidos", n_enriched)
    try:
        dashboard.export_all(storage, Path(DASHBOARD_OUT_DIR))
    except Exception as exc:
        logger.warning("No se pudo exportar el dashboard tras maintenance: %s", exc)
    storage.close()
    return 0


def _run_source(source_cls, since_date: date) -> tuple[str, list, list[str]]:
    source = source_cls()
    items = source.fetch(since_date)
    return source.name, items, list(source.last_errors)


def main() -> None:
    parser = argparse.ArgumentParser(description="vigia-profe: monitor de empleo docente")
    parser.add_argument("--since", metavar="YYYY-MM-DD", default=None,
                        help="Fecha de inicio del rango (defecto: ayer o último viernes)")
    parser.add_argument("--dry-run", action="store_true",
                        help="Imprime hallazgos sin guardar en BD ni notificar")
    parser.add_argument("--probe", action="store_true",
                        help="Solo comprueba la salud de cada fuente y termina")
    parser.add_argument("--maintenance", action="store_true",
                        help="Reclasifica items existentes y enriquece pendientes")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)-8s %(name)s: %(message)s",
        stream=sys.stdout,
    )

    enabled_classes = [
        SOURCE_REGISTRY[name]
        for name in SOURCES_ENABLED
        if name in SOURCE_REGISTRY
    ]

    if args.probe:
        sys.exit(_run_probe(enabled_classes))

    if args.maintenance:
        sys.exit(_run_maintenance())

    since_date = date.fromisoformat(args.since) if args.since else _default_since()
    logger.info(
        "Pipeline iniciado — since_date=%s dry_run=%s", since_date, args.dry_run
    )

    raw_items_all = []
    errors: list[tuple[str, str]] = []

    with ThreadPoolExecutor(max_workers=4) as pool:
        futures = {
            pool.submit(_run_source, cls, since_date): cls.name
            for cls in enabled_classes
        }
        for future in as_completed(futures):
            source_name = futures[future]
            try:
                name, items, src_errors = future.result()
                logger.info(
                    "%-22s %d raw items, %d errores",
                    name, len(items), len(src_errors),
                )
                raw_items_all.extend(items)
                for err in src_errors:
                    errors.append((name, err))
            except Exception as exc:
                logger.error("Fuente %s falló: %s", source_name, exc)
                errors.append((source_name, str(exc)))

    logger.info("Total raw items: %d", len(raw_items_all))

    matched = []
    for raw in raw_items_all:
        item = extract(raw)
        if item:
            matched.append(item)

    logger.info("Matches tras extractor: %d", len(matched))

    if args.dry_run:
        # En Windows el stdout por defecto va en cp1252 y rompe con caracteres
        # no-Latin1. Forzamos UTF-8 si está disponible (Python 3.7+).
        try:
            sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
        except Exception:
            pass
        for item in matched:
            print(f"[{item.source}] [{item.categoria}] {item.titulo[:100]}")
            print(f"  -> {item.url}")
        if errors:
            for src, err in errors:
                print(f"ERROR {src}: {err}")
        return

    storage = Storage()
    new_items = storage.filter_new(matched)
    logger.info("Nuevos (no vistos antes): %d", len(new_items))

    new_items = enricher.enrich(new_items)
    for item in new_items:
        if item.enriched_version is not None:
            storage.update_enrichment(item)
        else:
            storage.update_summary(item)

    try:
        dashboard.export_all(storage, Path(DASHBOARD_OUT_DIR))
    except Exception as exc:
        logger.warning("No se pudo exportar el dashboard: %s", exc)

    storage.close()

    notifiable = [it for it in new_items if it.is_relevant is not False]
    discarded = len(new_items) - len(notifiable)
    if discarded:
        logger.info(
            "Notifier: %d items descartados (is_relevant=false) — no se envían",
            discarded,
        )

    if notifiable or errors:
        send(notifiable, errors)
    else:
        logger.info("Sin novedades relevantes hoy — no se envía notificación Telegram")


if __name__ == "__main__":
    main()
