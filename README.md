# alerta-empleo-profe

Bot de Telegram + dashboard web para alertas de empleo docente en Madrid (oposiciones, interinidad, colegios privados, ELE).

Hermano de [vigia-enfermeria](https://github.com/tragabytes/vigia-enfermeria), reutiliza su arquitectura aplicada al perfil docente del informe `informe.md`.

## Estado

**Sprint 1 — Núcleo público** ✅ desplegado (2026-04-26). Cubre BOE + BOCM (vía RSS).

- Dashboard en vivo: https://tragabytes.github.io/alerta-empleo-profe/
- Cron diario: lunes-viernes 08:00 UTC (~10:00 hora España)
- 41 tests verdes

Ver [`plan_profe.md`](plan_profe.md) para el roadmap completo (sprints 2-9).

## Arquitectura

```
sources/*.py → extractor.py → enricher.py (opcional) → notifier.py + dashboard.py
```

- **Sources**: cada fuente implementa `Source.fetch(since_date) -> list[RawItem]`.
- **Extractor**: aplica patrones STRONG / WEAK / FALSE_POSITIVE de `config.py`.
- **Storage**: SQLite (`state/seen.db`) con dedup por hash, persistido en rama `state`.
- **Enricher**: opcional, Claude Sonnet 4.6 con tool-use anti-SSRF.
- **Notifier**: Telegram Markdown agrupado por fuente.
- **Dashboard**: JSON estático + frontend vanilla en `web/`, publicado en `gh-pages`.

## Uso local

```bash
pip install -r requirements.txt

# Pipeline completo (necesita TELEGRAM_BOT_TOKEN + TELEGRAM_CHAT_ID)
python -m vigia.main

# Sin notificar, solo imprimir matches
python -m vigia.main --dry-run

# Backfill desde fecha
python -m vigia.main --since 2026-04-01

# Probe de salud de las fuentes
python -m vigia.main --probe

# Reclasificar + enriquecer items históricos
python -m vigia.main --maintenance
```

## Variables de entorno

| Variable | Obligatoria | Uso |
|---|---|---|
| `TELEGRAM_BOT_TOKEN` | sí (en CI) | Token del bot |
| `TELEGRAM_CHAT_ID` | sí (en CI) | Destino(s), separados por comas |
| `ANTHROPIC_API_KEY` | no | Activa el enricher v2 |
| `DASHBOARD_URL` | no | URL pública del dashboard (footer Telegram) |

Sprint 2+ añadirá `INFOJOBS_CLIENT_ID`, `INFOJOBS_CLIENT_SECRET`, `JOOBLE_API_KEY`, `TELEGRAM_API_ID`, `TELEGRAM_API_HASH`.

## Despliegue

GitHub Actions (`.github/workflows/daily.yml`) corre el pipeline cada día laborable a las 08:00 UTC. La BD se guarda en la rama `state`; el dashboard se publica en `gh-pages`.

## Tests

```bash
python -m pytest tests/ -v
```
