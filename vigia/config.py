"""
Configuración central: términos de búsqueda, fuentes y constantes.

Perfil objetivo (informe.md):
  - Cuerpo 0590 PES, especialidad 005 Geografía e Historia (oposición/interinidad pública).
  - Cuerpo 0592 EOI, español para extranjeros (ELE).
  - Colegios privados/concertados de la zona noroeste de Madrid.
  - Academias y universidades ELE (TodoELE, ProfesoresdeELE, Cervantes, lectorados).

Filtro de exclusión: roles que requieren impartir todo en inglés (no aplica al perfil).
"""
import os
import unicodedata
import re

# ---------------------------------------------------------------------------
# Credenciales (leídas de entorno; nunca hardcodeadas)
# ---------------------------------------------------------------------------
TELEGRAM_BOT_TOKEN: str = os.environ.get("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID: str = os.environ.get("TELEGRAM_CHAT_ID", "")

# ---------------------------------------------------------------------------
# User-Agent
# ---------------------------------------------------------------------------
# UA de navegador estándar — algunos sitios (sede.madrid.es y similares)
# devuelven 403 con UAs identificables. Como hacemos pocos requests/día por
# fuente, usamos un UA Firefox uniforme.
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:128.0) "
    "Gecko/20100101 Firefox/128.0"
)

# ---------------------------------------------------------------------------
# Patrones de matching (informe.md, regex maestro)
# ---------------------------------------------------------------------------

# Match fuerte: cualquiera de estos patrones en el texto normalizado → alerta.
# El texto se normaliza con `normalize()` antes de aplicar (sin tildes,
# minúsculas, sólo [a-z0-9 ]). Por eso los patrones aquí NO llevan tildes.
STRONG_PATTERNS: list[str] = [
    # --- Especialidad principal (Geografía e Historia) ---
    r"geografia\s+e\s+historia",
    r"especialidad\s+005\b",
    r"\b005\s+geografia",
    # --- Cuerpo 0590 (Profesores de Enseñanza Secundaria) ---
    r"cuerpo\s+0590",
    r"profesor(?:ado|es)?\s+(?:de\s+)?(?:ensenanza\s+)?secundaria",
    r"profesores?\s+de\s+secundaria",
    # --- Cuerpo 0592 (EOI) y especialidad ELE ---
    r"cuerpo\s+0592",
    r"escuelas?\s+oficiales?\s+de\s+idiomas",
    r"\beoi\b",
    r"espanol\s+para\s+extranjeros",
    r"espanol\s+como\s+lengua\s+extranjera",
    r"\bele\b",
    # --- Listas, bolsas, interinidad ---
    r"interinidad",
    r"interin[oa]s?\s+docente",
    r"listas?\s+extraordinaria",
    r"bolsa\s+de\s+empleo.{0,40}docente",
    r"bolsa\s+de\s+(?:trabajo|empleo)\s+(?:de\s+)?(?:profesor|docente)",
    r"bolsa\s+(?:de\s+)?(?:trabajo|empleo).{0,40}(?:secundaria|profesor)",
    r"profesorado\s+interino",
    # --- Concursos de traslados y procesos selectivos docentes ---
    r"concurso\s+de\s+traslados.{0,40}docente",
    r"concurso\s+de\s+traslados.{0,40}(?:profesor|secundaria|cuerpo)",
    r"proceso\s+selectivo.{0,40}(?:profesor|docente|secundaria|cuerpo\s+05)",
    # --- Educación de adultos / compensatoria ---
    r"profesor\s+(?:de\s+)?adultos",
    r"educacion\s+(?:de\s+)?adultos",
    r"educacion\s+compensatoria",
    # --- Lectorados y auxiliares (Cervantes, AECID, MEFP, Fulbright) ---
    r"\blectorad[oa]s?\b",
    r"auxiliar(?:es)?\s+(?:de\s+)?conversacion",
    r"profesor(?:ado|es)?\s+visitante",
    r"profesor(?:ado|es)?\s+(?:de\s+)?espanol\s+(?:en|para)",
]

# Match débil: solo si ADEMÁS aparece el confirmador en una ventana de 100 chars.
# Útil para captar contextos amplios donde "profesor" o "docente" aparece
# cerca de un disparador de empleo público.
WEAK_CONTEXT_PATTERNS: list[tuple[str, str]] = [
    (r"convocatoria",          r"profesor|docente|secundaria|cuerpo\s+05"),
    (r"proceso\s+selectivo",   r"profesor|docente|secundaria|cuerpo\s+05"),
    (r"oposicion(?:es)?",      r"profesor|docente|secundaria|cuerpo\s+05"),
    (r"plazas?",               r"profesor|docente|interino|cuerpo\s+05"),
    (r"consejeria\s+de\s+educacion", r"profesor|docente|interino"),
    (r"ministerio\s+de\s+educacion", r"profesor|docente|cuerpo"),
]

# Falsos positivos a descartar antes de cualquier check:
#   - Maestros (cuerpo 0597, primaria) — no aplica al perfil de secundaria.
#   - Roles totalmente bilingües en inglés (el perfil tiene C1, no es bilingüe nativo).
#   - Universidad pública (PDI / contratado doctor / titular) — proceso
#     diferente a las oposiciones de secundaria.
#   - Plazas asociadas a áreas STEM ajenas (matemáticas, física…) que matchean
#     "profesor de secundaria" pero no son la especialidad.
FALSE_POSITIVE_PATTERNS: list[str] = [
    r"\bmaestros?\b.{0,40}(?:cuerpo\s+0597|infantil|primaria)",
    r"cuerpo\s+0597",
    r"educacion\s+infantil",
    # Roles 100% en inglés — el filtro intencional del informe
    r"bilingue.{0,40}ingles",
    r"impartir.{0,40}en\s+ingles",
    r"clases.{0,30}en\s+ingles",
    r"english\s+(?:teacher|speaking)",
    # Universidad: PDI, ayudante doctor, profesor contratado, titular
    r"profesor(?:a|es)?\s+(?:ayudante|contratado|titular|asociado|colaborador|emerito)",
    r"\bpdi\b",
    r"personal\s+docente\s+e\s+investigador",
    # Nombramientos universitarios (resoluciones BOE de tomas de posesión etc.)
    r"resoluci[oó]n.{0,60}universidad.{0,60}por\s+la\s+que\s+se\s+nombra",
    r"resoluci[oó]n.{0,60}por\s+la\s+que\s+se\s+nombra.{0,80}universidad",
    r"toma\s+de\s+posesion.{0,40}universidad",
]

# ---------------------------------------------------------------------------
# Categorías de hallazgos
# ---------------------------------------------------------------------------
CATEGORIES = {
    "oposicion": "Oposición",
    "bolsa": "Bolsa / interinidad",
    "traslado": "Concurso de traslados",
    "lectorado": "Lectorado / auxiliar conversación",
    "privada": "Colegio privado / concertado",
    "ele": "ELE / academia / universidad",
    "nombramiento": "Nombramiento / resolución",
    "oep": "Oferta de Empleo Público (OEP)",
    "otro": "Otro",
}

# Pistas para clasificación automática. Orden importa: primera categoría que
# matchea gana. Hints normalizados (sin tildes, minúsculas).
CATEGORY_HINTS: dict[str, list[str]] = {
    "lectorado": [
        "lectorado",
        "auxiliar de conversacion",
        "auxiliares de conversacion",
        "profesor visitante",
        "profesores visitantes",
        "fulbright",
        "aecid",
    ],
    "ele": [
        "ele ",
        "espanol para extranjeros",
        "espanol como lengua extranjera",
        "escuela oficial de idiomas",
        "instituto cervantes",
        "academia de espanol",
    ],
    "traslado": [
        "concurso de traslados",
        "concurso de meritos",
        "concurso traslado",
    ],
    "bolsa": [
        "bolsa de empleo",
        "bolsa de trabajo",
        "bolsa unica",
        "lista extraordinaria",
        "listas extraordinarias",
        "interinidad",
        "interinos",
        "contratacion temporal",
    ],
    "oposicion": [
        "convocatoria",
        "proceso selectivo",
        "pruebas selectivas",
        "concurso oposicion",
        "oposicion",
        "estabilizacion",
        "acceso libre",
    ],
    "oep": ["oferta de empleo publico", "oep "],
    "nombramiento": ["nombramiento", "resolucion", "adjudicacion"],
    "privada": [
        "colegio",
        "colegios",
        "school",
        "international school",
    ],
}


# ---------------------------------------------------------------------------
# Municipios objetivo (zona noroeste de Madrid, informe.md)
# ---------------------------------------------------------------------------
# Substrings normalizados para detectar en títulos/cuerpos. Se usan tanto
# para matchear ofertas como para construir la watchlist de organismos.
TARGET_MUNICIPIOS: list[str] = [
    "alcobendas",
    "san sebastian de los reyes",
    "tres cantos",
    "las rozas",
    "majadahonda",
    "pozuelo",
    "boadilla",
    "torrelodones",
    "collado villalba",
    "villanueva de la canada",
    "galapagar",
    "hoyo de manzanares",
    "moraleja",
    "soto de vinuelas",
    "ciudalcampo",
    "villafranca del castillo",
]


# ---------------------------------------------------------------------------
# Watchlist de organismos vigilados (sección 06 del dashboard)
# ---------------------------------------------------------------------------
# `patterns` son substrings YA NORMALIZADOS que se buscan dentro del texto
# normalizado de cada item para contar hits del organismo. Pensar en variantes.
WATCHLIST_ORGS: list[dict] = [
    # --- Empleo público estatal y autonómico ---
    {"id": "T-01", "name": "Consejería de Educación CM",
     "desc": "Comunidad de Madrid — Consejería de Educación, Ciencia y Universidades",
     "patterns": ["consejeria de educacion", "direccion general de recursos humanos",
                  "comunidad de madrid"]},
    {"id": "T-02", "name": "Ministerio de Educación",
     "desc": "Ministerio de Educación, Formación Profesional y Deportes (MEFD)",
     "patterns": ["ministerio de educacion", "mefd", "mefp"]},
    {"id": "T-03", "name": "Instituto Cervantes",
     "desc": "Sede Cervantes — convocatorias de profesorado y becas",
     "patterns": ["instituto cervantes", "cervantes"]},
    {"id": "T-04", "name": "AECID Lectorados",
     "desc": "MAEC-AECID — lectorados MAEC en universidades extranjeras",
     "patterns": ["aecid", "maec aecid", "lectorad"]},
    {"id": "T-05", "name": "MEFP Auxiliares",
     "desc": "Profex 2 — auxiliares de conversación en el extranjero",
     "patterns": ["auxiliares de conversacion", "auxiliar de conversacion", "profex"]},
    {"id": "T-06", "name": "Fulbright FLTA",
     "desc": "Fulbright España — Foreign Language Teaching Assistant",
     "patterns": ["fulbright", "flta"]},
    {"id": "T-07", "name": "EOI Madrid",
     "desc": "Escuelas Oficiales de Idiomas (especialidad 008)",
     "patterns": ["escuela oficial de idiomas", "escuelas oficiales de idiomas",
                  " eoi ", "cuerpo 0592"]},
    # --- Sindicatos / canales de información en tiempo real ---
    {"id": "T-08", "name": "ANPE Madrid",
     "desc": "Sindicato ANPE Madrid — bolsas y convocatorias",
     "patterns": ["anpe madrid", "anpemadrid", " anpe "]},
    {"id": "T-09", "name": "CSIF Educación",
     "desc": "CSIF Educación Madrid — resoluciones BOCM en directo",
     "patterns": ["csif", "csi f"]},
    {"id": "T-10", "name": "FeSP-UGT",
     "desc": "UGT Servicios Públicos Madrid — enseñanza pública",
     "patterns": ["fesp ugt", "ugt educacion", "ugt ensenanza"]},
    {"id": "T-11", "name": "CCOO Educación",
     "desc": "CCOO Madrid — federación de enseñanza",
     "patterns": ["ccoo", "feccoo", "comisiones obreras"]},
    # --- ATS de colegios privados zona noroeste ---
    {"id": "T-12", "name": "Inspired Education",
     "desc": "Inspired Education — Mirabal, Kensington, King's, San Patricio, Everest",
     "patterns": ["inspired", "mirabal", "kensington", "kings college",
                  "san patricio", "everest"]},
    {"id": "T-13", "name": "SEK Group",
     "desc": "SEK Education — El Castillo, Ciudalcampo, UCJC",
     "patterns": ["sek el castillo", "sek ciudalcampo", "sek group", "sek education",
                  "camilo jose cela", "ucjc"]},
    {"id": "T-14", "name": "Brains Schools",
     "desc": "Brains International Schools — La Moraleja",
     "patterns": ["brains international", "brains schools"]},
    {"id": "T-15", "name": "Highlands / Colegios RC",
     "desc": "Colegios RC — Highlands Los Fresnos, El Encinar, Everest Monteclaro",
     "patterns": ["highlands", "colegios rc", "los fresnos", "el encinar",
                  "everest monteclaro", "monteclaro"]},
    # --- Ayuntamientos noroeste ---
    {"id": "T-16", "name": "Ayto. Alcobendas",
     "desc": "Alcobendas — OEP con plazas docentes (ESO/adultos)",
     "patterns": ["alcobendas"]},
    {"id": "T-17", "name": "Ayto. Tres Cantos",
     "desc": "Tres Cantos — convocatorias de empleo público",
     "patterns": ["tres cantos"]},
    {"id": "T-18", "name": "Ayto. Las Rozas",
     "desc": "Las Rozas — convocatorias en plazo",
     "patterns": ["las rozas"]},
    {"id": "T-19", "name": "Ayto. Pozuelo",
     "desc": "Pozuelo de Alarcón — Patronato de Cultura (música, plástica)",
     "patterns": ["pozuelo de alarcon", "pozuelo"]},
    {"id": "T-20", "name": "Ayto. Majadahonda",
     "desc": "Majadahonda — profesor de pintura/música/cerámica",
     "patterns": ["majadahonda"]},
    {"id": "T-21", "name": "Ayto. Boadilla",
     "desc": "Boadilla del Monte — eAdmin estándar",
     "patterns": ["boadilla del monte", "boadilla"]},
    {"id": "T-22", "name": "Ayto. SS Reyes",
     "desc": "San Sebastián de los Reyes",
     "patterns": ["san sebastian de los reyes", "ss reyes", "ssreyes"]},
    # --- Universidades de la zona ---
    {"id": "T-23", "name": "Universidad Nebrija",
     "desc": "Nebrija — CEHI, máster ELE, vacantes regulares",
     "patterns": ["universidad nebrija", "nebrija"]},
    {"id": "T-24", "name": "UCM",
     "desc": "Universidad Complutense de Madrid — empleo PDI",
     "patterns": ["complutense", "ucm "]},
    {"id": "T-25", "name": "UC3M",
     "desc": "Universidad Carlos III — Centro de Idiomas",
     "patterns": ["uc3m", "carlos iii"]},
]

# Días de antigüedad de la fecha de publicación a partir de los cuales se
# considera que un organismo ya no tiene proceso activo (mismo criterio
# heurístico que vigia-enfermeria).
WATCHLIST_RECENCY_DAYS = 90

# ---------------------------------------------------------------------------
# Fuentes habilitadas — Sprint 1 sólo BOE + BOCM
# ---------------------------------------------------------------------------
SOURCES_ENABLED: list[str] = [
    "boe",
    "bocm",
]


# ---------------------------------------------------------------------------
# Helpers de normalización
# ---------------------------------------------------------------------------
def normalize(text: str) -> str:
    """Minúsculas, sin acentos, sin caracteres especiales → solo [a-z0-9 ]."""
    nfkd = unicodedata.normalize("NFKD", text.lower())
    ascii_text = nfkd.encode("ascii", "ignore").decode("ascii")
    return re.sub(r"[^a-z0-9\s]", " ", ascii_text)
