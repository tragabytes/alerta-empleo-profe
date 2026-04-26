# Plan: alerta-empleo-profe — Bot de alertas de empleo docente

Bot de Telegram + dashboard web para alertas de empleo docente en Madrid (oposiciones, interinidad, colegios privados, ELE). Basado en la arquitectura de [vigia-enfermeria](https://github.com/tragabytes/vigia-enfermeria).

## Estado actual

| Recurso | URL |
|---|---|
| Repo | https://github.com/tragabytes/alerta-empleo-profe |
| Dashboard | https://tragabytes.github.io/alerta-empleo-profe/ |
| Cron | Lunes-viernes 08:00 UTC (~10:00 España) |
| Sprints completados | **Sprint 1** ✅ |
| Sprint en curso | — (siguiente: Sprint 2, InfoJobs + Jooble) |

---

## Arquitectura

Pipeline lineal heredado de vigia-enfermeria:

```
fetch (paralelo) → extract (regex) → store (SQLite) → enrich (Claude) → notify (Telegram) → dashboard (JSON + web estática)
```

Despliegue: GitHub Actions con cron diario, estado persistido en rama `state`, web publicada en `gh-pages`.

---

## Diferencias clave con vigia-enfermeria

| Aspecto | vigia-enfermeria | vigia-profe |
|---|---|---|
| BOCM | PDF scraping complejo | RSS feeds directos |
| APIs limpias | Solo BOE | BOE + InfoJobs API + Jooble API |
| Telegram canales | No | MTProto (Telethon) — 7 canales sindicales |
| Sector privado | No | ATS de Inspired, SEK, Brains, Colejobs |
| ELE | No | TodoELE, ProfesoresdeELE, Cervantes, lectorados |
| Municipios | Madrid capital | 12 ayuntamientos del noroeste |
| Alertas calendario | No | Convocatorias anuales (AECID, Fulbright, EOI) |

Reutilizable sin cambios (~70%): `storage.py`, `enricher.py`, `notifier.py`, `dashboard.py`, `web/`, GitHub Actions.

---

## Sprints

### Sprint 1 — Núcleo público ✅ Completado (2026-04-26)
Cubre el 80% del valor para oposiciones e interinidad oficial.

- ✅ `sources/boe.py`: filtrado por departamentos MEFD, AECID, Cervantes, Comunidad de Madrid, universidades.
- ✅ `sources/bocm.py`: descubrimiento desde RSS (`boletines.rss` + `sumarios.rss`) reconstruyendo URLs XML canónicas a partir de fecha + nº de boletín.
- ✅ `config.py` con regex maestro docente (Cuerpo 0590/0592, especialidad 005, lectorados, ELE), 16 municipios noroeste, 25 organismos en watchlist.
- ✅ Falsos positivos: maestros (cuerpo 0597), PDI universitario, roles bilingües 100% en inglés, nombramientos universitarios.
- ✅ Enricher Claude con system prompt adaptado al perfil docente.
- ✅ Notifier Telegram con labels docentes y categorías nuevas (lectorado, auxiliar, privada, ele).
- ✅ Web dashboard adaptada (título, tagline, diagrama de pipeline).
- ✅ CI/CD: GitHub Actions diario, ramas `state` y `gh-pages`.
- ✅ 41 tests verdes.

**Hallazgos durante el despliegue (lecciones para Sprints siguientes):**
- BOCM RSS no expone XMLs directos — hay que reconstruir la URL canónica desde el patrón `/boletin/CM_Boletin_BOCM/{Y}/{M}/{D}/BOCM-{YYYYMMDD}{NNN}.xml`.
- El runner de GitHub Actions sufre timeouts intermitentes contra `boe.es` — implementado fallback automático a `www.boe.es` (y viceversa) ante `ConnectionError`/`Timeout`. Timeouts subidos: API 45s, body 30s, probe 30s.
- El extractor heurístico es agresivo a propósito; el enricher Claude es el filtro discriminador real (en el primer run filtró 3/3 matches como `is_relevant=false`).

### Sprint 2 — APIs privadas
Mercado privado con dos integraciones limpias.

- `sources/infojobs.py`: API oficial con `client_id`/`client_secret` gratuitos en developer.infojobs.net
- `sources/jooble.py`: POST a `jooble.org/api/{KEY}`, agrega InfoJobs + Indeed + LinkedIn
- Keywords: `profesor historia`, `profesor secundaria`, `profesor español extranjeros`, `profesor ELE`
- Filtro provincia Madrid

### Sprint 3 — Telegram MTProto
Ventaja informativa de horas frente a competencia.

- Integrar Telethon para 7 canales: `@ANPEmadrid`, `@csifeducacionmadrid`, `@ugteducacionpublicamadrid`, `@educacion_ccoomadrid`, `@noticiasoposicionessecundaria`, `@bolsasdocentes`, `@opobusca`
- Fallback HTML público: `t.me/s/{canal}`

### Sprint 4 — ATS colegios privados noroeste

- `sources/inspired.py`: jobs.inspirededu.com (Mirabal, Kensington, King's, San Patricio, Everest)
- `sources/sek.py`: empleo.sek.es (Teamtailor)
- `sources/brains.py`: brainsinternationalschool.factorial.es
- `sources/colegios_rc.py`: jobs.lcred.net (SAP SuccessFactors, pausa 4-6s entre requests)

### Sprint 5 — Bolsas especializadas ELE

- `sources/colejobs.py`: colejobs.es (mayor densidad privada Madrid)
- `sources/profesoresele.py`: ProfesoresdeELE RSS WordPress
- `sources/todoele.py`: todoele.net (Drupal HTML simple)
- `sources/cervantes.py`: sede Cervantes + hispanismo.cervantes.es
- `sources/nebrija.py`: la universidad más activa en ELE

### Sprint 6 — Capa LinkedIn + Indeed
Implementar solo cuando el resto esté maduro.

- LinkedIn guest API (sin login, cadencia conservadora)
- Indeed RSS no oficial (frágil pero funciona)

### Sprint 7 — Capa municipal y universitaria
Polling semanal de los 12 ayuntamientos noroeste y webs UCM, UC3M, Comillas, CEU, URJC, UCJC, UFV, UEM.

### Sprint 8 — Alertas calendario
Disparar avisos por fecha:
- Septiembre: Fulbright FLTA, Auxiliares MEFP
- Enero: AECID lectorados, Profesores Visitantes
- Marzo-abril: oposiciones EOI Madrid
- Mayo-julio: becas Cervantes

### Sprint 9 — Recordatorios de registro manual
Para fuentes no automatizables: Talento ECM, FSIE, italki, Preply, Superprof, Lingoda.

---

## Stack técnico

Heredado de vigia-enfermeria + nuevo:
- `requests`, `beautifulsoup4`, `lxml`, `pdfplumber`, `anthropic` (existente)
- `feedparser` (RSS BOCM, WordPress, ProfesoresdeELE)
- `Telethon` (MTProto canales sindicales)

Variables de entorno nuevas:
- `INFOJOBS_CLIENT_ID`, `INFOJOBS_CLIENT_SECRET`
- `JOOBLE_API_KEY`
- `TELEGRAM_API_ID`, `TELEGRAM_API_HASH` (para Telethon)

---

## Estructura del proyecto

```
vigia-profe/
├── vigia/
│   ├── main.py              # reutilizar ~100%
│   ├── config.py            # reescribir (patrones docentes)
│   ├── extractor.py         # reutilizar + ajustar regex
│   ├── enricher.py          # reutilizar ~100%
│   ├── notifier.py          # reutilizar ~100%
│   ├── storage.py           # reutilizar ~100%
│   ├── dashboard.py         # reutilizar ~100%
│   └── sources/
│       ├── base.py
│       ├── boe.py           # adaptar filtros
│       ├── bocm.py          # reescribir (RSS)
│       ├── infojobs.py      # Sprint 2
│       ├── jooble.py        # Sprint 2
│       ├── telegram_channels.py  # Sprint 3
│       ├── inspired.py      # Sprint 4
│       ├── sek.py           # Sprint 4
│       ├── brains.py        # Sprint 4
│       ├── colegios_rc.py   # Sprint 4
│       ├── colejobs.py      # Sprint 5
│       ├── profesoresele.py # Sprint 5
│       ├── todoele.py       # Sprint 5
│       └── cervantes.py     # Sprint 5
├── web/                     # reutilizar estética, actualizar labels
├── tests/
├── .github/workflows/       # reutilizar casi sin cambios
├── requirements.txt
└── README.md
```

---

## Filtros de relevancia (regex maestro)

Heredado del informe:

```regex
(?i)\b(geograf[ií]a\s+e\s+historia|profesor(?:ado|es)?\s+(?:de\s+)?(?:ense[ñn]anza\s+)?secundaria|cuerpo\s+0590|especialidad\s+005|interinidad|listas?\s+extraordinaria|bolsa\s+de\s+empleo.+docente|espa[ñn]ol\s+(?:para\s+extranjeros|como\s+lengua\s+extranjera)|\bELE\b|escuelas\s+oficiales\s+de\s+idiomas|0592|concurso\s+de\s+traslados.*docente|profesor\s+(?:de\s+)?adultos|educaci[oó]n\s+compensatoria|lectorad[oa]|auxiliar\s+conversaci[oó]n)
```

Municipios objetivo: Alcobendas, San Sebastián de los Reyes, Tres Cantos, Las Rozas, Majadahonda, Pozuelo, Boadilla, Torrelodones, Collado Villalba, Villanueva de la Cañada, Galapagar, Hoyo de Manzanares, Moraleja, Soto de Viñuelas, Ciudalcampo, Villafranca del Castillo.

Exclusión: roles `bilingüe.{0,30}inglés` (totalmente en inglés).

---

## Cadencia de polling

| Capa | Frecuencia | Fuentes |
|---|---|---|
| L1 — Tiempo real | continuo | Canales Telegram sindicales |
| L2 — Diaria | 1×/día (07:00 ES) | BOE, BOCM, comunidad.madrid, InfoJobs, Jooble, Indeed, Colejobs, Cervantes |
| L3 — Cada 6-12h | 2-4×/día | ATS colegios privados, ANPE, CSIF, ProfesoresdeELE |
| L4 — Semanal | 1×/semana | Webs ayuntamientos, universidades, lectorados |
