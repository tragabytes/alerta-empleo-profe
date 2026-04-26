"""
Enriquecimiento estructurado con Claude (Sonnet 4.6) — opcional.

Recibe items detectados por el extractor y devuelve los mismos items con
campos estructurados (relevancia, plazas, deadline, organismo, fase, etc.).

Si `ANTHROPIC_API_KEY` no está definida, devuelve los items sin tocar
(graceful degradation).

Encaja como punto de extensión entre extractor y notifier:
    sources/*.py → extractor.py → enricher.py → notifier.py + dashboard.py
"""
from __future__ import annotations

import io
import json
import logging
import os
import re
from datetime import datetime, timezone
from typing import Any, Optional
from urllib.parse import urlparse

import requests

from vigia.config import USER_AGENT
from vigia.storage import ENRICHMENT_VERSION, Item, Storage

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Configuración del modelo
# ---------------------------------------------------------------------------

MODEL = "claude-sonnet-4-6"
MAX_TOKENS = 2048
MAX_TOOL_ITERATIONS = 4   # tope de loops para evitar runaway costs
MAX_TEXT_CHARS = 1500     # del raw_text inyectado en el prompt inicial

# ---------------------------------------------------------------------------
# Configuración del fetcher (anti-SSRF + límites)
# ---------------------------------------------------------------------------

# Whitelist estricta de hostnames permitidos en `fetch_url`. Cubre BOE/BOCM
# (Sprint 1) y se ampliará en Sprints siguientes con InfoJobs, Cervantes,
# Universidad Nebrija, etc. Cualquier dominio fuera de la lista devuelve
# error inmediato — incluido tras seguir redirects.
ALLOWED_FETCH_HOSTS: set[str] = {
    # BOE
    "boe.es", "www.boe.es",
    # BOCM
    "bocm.es", "www.bocm.es",
    # Comunidad de Madrid
    "comunidad.madrid", "www.comunidad.madrid",
    "sede.comunidad.madrid", "transparencia.comunidad.madrid",
    # AECID / Cooperación Española (lectorados)
    "aecid.es", "www.aecid.es",
    # Instituto Cervantes
    "cervantes.es", "www.cervantes.es",
    "cervantes.sede.gob.es", "hispanismo.cervantes.es",
    # Ministerio de Educación, FP y Deportes
    "educacionfpydeportes.gob.es", "www.educacionfpydeportes.gob.es",
    "educacion.gob.es", "www.educacion.gob.es",
    # Sindicatos (públicos, sin login)
    "anpemadrid.es", "www.anpemadrid.es",
    "csif.es", "www.csif.es",
}

MAX_FETCH_BYTES = 5 * 1024 * 1024     # 5 MB
FETCH_TIMEOUT_SECONDS = 15
MAX_FETCH_TEXT_CHARS = 30_000          # truncamos antes de devolverlo al LLM


# ---------------------------------------------------------------------------
# Definición de la tool registrada con el modelo
# ---------------------------------------------------------------------------

FETCH_URL_TOOL: dict[str, Any] = {
    "name": "fetch_url",
    "description": (
        "Descarga el contenido de una URL oficial (BOE, BOCM, sede de la "
        "Comunidad de Madrid, Ministerio de Educación, AECID, Instituto "
        "Cervantes, sindicatos docentes públicos) y devuelve el texto "
        "extraído. Usar para consultar el cuerpo de una convocatoria, sus "
        "bases o un PDF anexo cuando el título no contiene los datos pedidos. "
        "Acepta HTML y PDF. Solo URLs https. Tamaño máximo 5MB. Resultado "
        "truncado a 30k caracteres."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "url": {
                "type": "string",
                "description": "URL absoluta de la convocatoria, anexo o PDF de bases.",
            },
        },
        "required": ["url"],
    },
}


# ---------------------------------------------------------------------------
# Schema de salida esperada del modelo (JSON estructurado)
# ---------------------------------------------------------------------------

SYSTEM_PROMPT = """Eres un asistente que extrae datos estructurados de convocatorias de empleo docente en España.

Tu trabajo: recibir el dato bruto de una convocatoria y devolver un JSON con los campos clave. Puedes (y debes, cuando los datos no estén en el resumen recibido) usar la tool `fetch_url` para descargar el cuerpo del boletín o el PDF de bases.

PERFIL OBJETIVO (para evaluar `is_relevant`):
- Cuerpo 0590 PES (Profesores de Enseñanza Secundaria), especialidad 005 Geografía e Historia.
- Cuerpo 0592 EOI (Escuelas Oficiales de Idiomas), especialidad Español para Extranjeros / ELE.
- Bolsas/listas extraordinarias e interinidades de las dos anteriores.
- Concursos de traslados con cupo en Madrid para esas especialidades.
- Lectorados (AECID-MAEC), auxiliares de conversación (MEFP/Profex 2), profesores visitantes y Fulbright FLTA.
- Plazas docentes en colegios privados/concertados de Madrid o academias/universidades ELE.

CRITERIOS PARA `is_relevant`:
- TRUE → la convocatoria/oferta encaja con uno de los puntos del perfil.
- FALSE → falsos positivos típicos:
    * Cuerpo 0597 (Maestros, infantil/primaria).
    * Universidad: PDI, Ayudante Doctor, Profesor Contratado, Titular, Asociado.
    * Otras especialidades de secundaria sin solapamiento (Matemáticas, Física, etc.).
    * Roles "bilingüe" donde se exige impartir TODO en inglés (el perfil tiene C1 sólido pero no es bilingüe nativo).
    * Nombramientos / ceses individuales sin plazas nuevas.
- En la duda, prioriza FALSE — el sistema reduce ruido eliminando items con is_relevant=false.

CRITERIOS PARA `process_type`:
- "oposicion" → proceso selectivo / pruebas selectivas / concurso-oposición de acceso libre
- "bolsa" → bolsa de empleo, lista extraordinaria, interinidad estructurada
- "concurso_traslados" → concurso de traslados / concurso de méritos entre funcionarios
- "interinaje" → nombramiento de interino / sustitución concreta
- "temporal" → contrato temporal puntual no incluido en bolsa
- "lectorado" → lectorado AECID/Fulbright/MAEUEC/Cervantes
- "auxiliar" → auxiliar de conversación
- "privada" → vacante en colegio privado/concertado
- "ele" → vacante en academia/universidad/centro ELE
- "otro" → cualquier otro caso

CRITERIOS PARA `fase`:
- "convocatoria" → publicación inicial con plazo de inscripción abierto
- "admitidos_provisional" / "admitidos_definitivo" → listas de admitidos
- "examen" → fechas/sedes del ejercicio
- "calificacion" → resultados de un ejercicio o calificación final
- "propuesta_nombramiento" → resolución de adjudicación
- "otro" → cualquier otro estado intermedio

REGLAS DE EXTRACCIÓN:
- Fechas en formato `YYYY-MM-DD`. Si solo conoces el mes y año, deja `null`.
- `plazas`: solo el TOTAL de plazas convocadas; si no aparece, `null`.
- `tasas_eur`: tasa de inscripción base en euros (no descuentos ni reducciones).
- `url_bases`: URL al PDF/HTML con las bases completas (a veces es un anexo distinto del que recibes).
- `requisitos_clave`: lista corta (≤4) de requisitos imprescindibles (titulación específica, idiomas, experiencia mínima). No copies todo el listado del BOE — solo lo más diferenciador.
- `next_action`: una frase ≤140 chars con la acción inmediata que el usuario debe tomar (ej. "Presentar instancia online en sede.educacion.gob.es antes del 15/05/2026").
- `summary`: ~200 caracteres en estilo telegrama, factual, sin frases introductorias.
- `confidence`: 0..1 según lo seguro que estés del extracto general.
- Si un campo no es deducible con razonable certeza, devuélvelo como `null`. NO INVENTES NADA.

USO DE LA TOOL:
- Si el título y `raw_text` son suficientes para todos los campos pedidos, NO llames a la tool — responde directamente con el JSON.
- Si te falta algún dato clave (deadline, plazas, tasas, bases, especialidad concreta) y la URL principal está en dominio oficial, llámala una vez para inspeccionar el cuerpo.
- Como mucho 2 llamadas a tool por item. Después responde con lo que tengas.

FORMATO DE SALIDA OBLIGATORIO:
Responde SOLO con un bloque JSON válido (puedes envolverlo en ```json … ``` si quieres). Sin texto antes ni después. El JSON debe seguir este schema (todos los campos opcionales pueden ser null):

{
  "is_relevant": true|false,
  "relevance_reason": "string",
  "process_type": "oposicion|bolsa|concurso_traslados|interinaje|temporal|lectorado|auxiliar|privada|ele|otro",
  "summary": "string ~200 chars",
  "organismo": "string|null",
  "centro": "string|null",
  "plazas": int|null,
  "deadline_inscripcion": "YYYY-MM-DD|null",
  "fecha_publicacion_oficial": "YYYY-MM-DD|null",
  "tasas_eur": float|null,
  "url_bases": "string|null",
  "url_inscripcion": "string|null",
  "requisitos_clave": ["string", ...] | [],
  "fase": "convocatoria|admitidos_provisional|admitidos_definitivo|examen|calificacion|propuesta_nombramiento|otro",
  "next_action": "string|null",
  "confidence": 0.0..1.0
}"""


# ---------------------------------------------------------------------------
# API pública
# ---------------------------------------------------------------------------

def enrich(items: list[Item]) -> list[Item]:
    """Enriquece cada Item con información estructurada del LLM.

    Si `ANTHROPIC_API_KEY` no está configurada, devuelve la lista sin tocar.
    Si una llamada concreta falla, ese item queda sin enriquecimiento y los
    demás siguen procesándose.
    """
    if not items:
        return items

    if not os.environ.get("ANTHROPIC_API_KEY"):
        logger.info(
            "Enricher: ANTHROPIC_API_KEY no configurada — saltando enriquecimiento"
        )
        return items

    try:
        import anthropic  # noqa: F401
    except ImportError:
        logger.warning(
            "Enricher: paquete 'anthropic' no instalado — saltando enriquecimiento"
        )
        return items

    import anthropic as _anthropic
    client = _anthropic.Anthropic()
    enriched = 0
    failed = 0

    for item in items:
        try:
            data = _enrich_one(client, item)
            _apply_enrichment(item, data)
            enriched += 1
        except Exception as exc:
            failed += 1
            logger.warning(
                "Enricher: fallo al enriquecer [%s] %s: %s",
                item.source, item.titulo[:60], exc,
            )

    logger.info(
        "Enricher v%d: %d/%d items enriquecidos (%d fallidos)",
        ENRICHMENT_VERSION, enriched, len(items), failed,
    )
    return items


def enrich_pending(storage: Storage) -> int:
    """Enriquece los items de BD que aún no estén en `ENRICHMENT_VERSION`."""
    pending = storage.iter_items_for_enrichment()
    if not pending:
        logger.info("Enricher: no hay items pendientes de enriquecimiento")
        return 0

    logger.info(
        "Enricher: %d items pendientes (objetivo v%d)",
        len(pending), ENRICHMENT_VERSION,
    )
    enriched = enrich(pending)
    n = 0
    for item in enriched:
        if item.enriched_version is not None:
            storage.update_enrichment(item)
            n += 1
    logger.info(
        "Enricher: %d/%d items recibieron enriquecimiento v%d",
        n, len(pending), ENRICHMENT_VERSION,
    )
    return n


# ---------------------------------------------------------------------------
# Loop interno con tool use
# ---------------------------------------------------------------------------

def _enrich_one(client, item: Item) -> dict[str, Any]:
    user_content = _build_initial_user_content(item)
    messages: list[dict[str, Any]] = [
        {"role": "user", "content": user_content},
    ]

    for iteration in range(MAX_TOOL_ITERATIONS):
        resp = client.messages.create(
            model=MODEL,
            max_tokens=MAX_TOKENS,
            system=SYSTEM_PROMPT,
            tools=[FETCH_URL_TOOL],
            messages=messages,
        )

        if resp.stop_reason == "tool_use":
            messages.append({"role": "assistant", "content": resp.content})
            tool_results = []
            for block in resp.content:
                if getattr(block, "type", None) == "tool_use":
                    if block.name != "fetch_url":
                        result_text = (
                            f"ERROR: tool '{block.name}' no soportada"
                        )
                    else:
                        url = (block.input or {}).get("url", "")
                        result_text = _run_fetch_url(url)
                    tool_results.append({
                        "type": "tool_result",
                        "tool_use_id": block.id,
                        "content": result_text,
                    })
            if not tool_results:
                raise RuntimeError("tool_use sin bloques tool_use")
            messages.append({"role": "user", "content": tool_results})
            continue

        if resp.stop_reason in ("end_turn", "stop_sequence"):
            text = "".join(
                b.text for b in resp.content
                if getattr(b, "type", None) == "text"
            ).strip()
            if not text:
                raise ValueError("respuesta final vacía del LLM")
            return _parse_json_block(text)

        raise RuntimeError(
            f"stop_reason inesperado: {resp.stop_reason!r}"
        )

    raise RuntimeError(
        f"loop excedió {MAX_TOOL_ITERATIONS} iteraciones sin respuesta final"
    )


def _build_initial_user_content(item: Item) -> str:
    raw_text = ""
    if isinstance(item.extra, dict):
        raw_text = item.extra.get("raw_text", "") or ""
    raw_section = raw_text[:MAX_TEXT_CHARS] if raw_text else "(no disponible)"
    return (
        "Convocatoria detectada por el sistema:\n"
        f"- Fuente: {item.source}\n"
        f"- Categoría heurística: {item.categoria}\n"
        f"- Título: {item.titulo[:300]}\n"
        f"- URL: {item.url}\n"
        f"- Fecha de detección: {item.fecha}\n"
        f"- Texto adicional disponible (truncado):\n{raw_section}\n\n"
        "Devuelve el JSON estructurado siguiendo el schema definido en las "
        "instrucciones del sistema. Llama a `fetch_url` solo si necesitas "
        "datos que no están arriba."
    )


# ---------------------------------------------------------------------------
# Tool runner — fetch_url con whitelist anti-SSRF
# ---------------------------------------------------------------------------

def _run_fetch_url(url: str) -> str:
    if not url or not isinstance(url, str):
        return "ERROR: url ausente o no es string"

    try:
        parsed = urlparse(url)
    except Exception:
        return "ERROR: url malformada"

    if parsed.scheme not in ("http", "https"):
        return f"ERROR: scheme '{parsed.scheme}' no permitido (solo http/https)"

    host = (parsed.hostname or "").lower()
    if host not in ALLOWED_FETCH_HOSTS:
        return (
            f"ERROR: dominio '{host}' fuera de la whitelist. "
            f"Permitidos: {', '.join(sorted(ALLOWED_FETCH_HOSTS))}"
        )

    try:
        resp = requests.get(
            url,
            timeout=FETCH_TIMEOUT_SECONDS,
            stream=True,
            headers={
                "User-Agent": USER_AGENT,
                "Accept": "text/html,application/xhtml+xml,application/pdf,application/json,*/*",
            },
            allow_redirects=True,
        )
    except requests.RequestException as exc:
        return f"ERROR: request fallida ({exc.__class__.__name__}: {exc})"

    final_host = (urlparse(resp.url).hostname or "").lower()
    if final_host not in ALLOWED_FETCH_HOSTS:
        resp.close()
        return f"ERROR: redirect a dominio no permitido ('{final_host}')"

    if resp.status_code != 200:
        resp.close()
        return f"ERROR: HTTP {resp.status_code}"

    body = bytearray()
    for chunk in resp.iter_content(chunk_size=8192):
        if not chunk:
            continue
        body.extend(chunk)
        if len(body) >= MAX_FETCH_BYTES:
            body = body[:MAX_FETCH_BYTES]
            break
    resp.close()

    content_type = (resp.headers.get("content-type") or "").lower()
    is_pdf = "pdf" in content_type or url.lower().endswith(".pdf")

    if is_pdf:
        text = _extract_pdf_text(bytes(body))
    else:
        text = _extract_html_text(bytes(body))

    if not text.strip():
        return "ERROR: contenido vacío tras extracción"

    if len(text) > MAX_FETCH_TEXT_CHARS:
        return text[:MAX_FETCH_TEXT_CHARS] + "\n[…texto truncado…]"
    return text


def _extract_pdf_text(data: bytes) -> str:
    try:
        import pdfplumber
    except ImportError:
        return "ERROR: pdfplumber no instalado"

    try:
        with pdfplumber.open(io.BytesIO(data)) as pdf:
            chunks = []
            for page in pdf.pages[:30]:
                t = page.extract_text() or ""
                if t:
                    chunks.append(t)
            return "\n\n".join(chunks)
    except Exception as exc:
        return f"ERROR: parseo PDF falló ({exc})"


def _extract_html_text(data: bytes) -> str:
    try:
        from bs4 import BeautifulSoup
    except ImportError:
        return data.decode("utf-8", errors="replace")

    try:
        soup = BeautifulSoup(data, "lxml")
    except Exception:
        soup = BeautifulSoup(data, "html.parser")

    for tag in soup(["script", "style", "noscript", "header", "footer", "nav"]):
        tag.decompose()
    text = soup.get_text(separator="\n")
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Parsing y aplicación del JSON al Item
# ---------------------------------------------------------------------------

_JSON_FENCE_RE = re.compile(r"```(?:json)?\s*(\{.*?\})\s*```", re.DOTALL)


def _parse_json_block(text: str) -> dict[str, Any]:
    text = text.strip()
    if text.startswith("{") and text.endswith("}"):
        return json.loads(text)
    m = _JSON_FENCE_RE.search(text)
    if m:
        return json.loads(m.group(1))
    start = text.find("{")
    end = text.rfind("}")
    if start != -1 and end != -1 and end > start:
        return json.loads(text[start:end + 1])
    raise ValueError("no se encontró bloque JSON en la respuesta del LLM")


_VALID_PROCESS_TYPES = {
    "oposicion", "bolsa", "concurso_traslados", "interinaje", "temporal",
    "lectorado", "auxiliar", "privada", "ele", "otro",
}
_VALID_FASES = {
    "convocatoria", "admitidos_provisional", "admitidos_definitivo",
    "examen", "calificacion", "propuesta_nombramiento", "otro",
}
_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def _apply_enrichment(item: Item, data: dict[str, Any]) -> None:
    item.is_relevant = _coerce_bool(data.get("is_relevant"))
    item.relevance_reason = _coerce_str(data.get("relevance_reason"))

    pt = _coerce_str(data.get("process_type"))
    item.process_type = pt if pt in _VALID_PROCESS_TYPES else (
        "otro" if pt else None
    )

    item.summary = _coerce_str(data.get("summary"))
    item.organismo = _coerce_str(data.get("organismo"))
    item.centro = _coerce_str(data.get("centro"))
    item.plazas = _coerce_int(data.get("plazas"))

    deadline = _coerce_str(data.get("deadline_inscripcion"))
    item.deadline_inscripcion = deadline if (deadline and _DATE_RE.match(deadline)) else None

    fpub = _coerce_str(data.get("fecha_publicacion_oficial"))
    item.fecha_publicacion_oficial = fpub if (fpub and _DATE_RE.match(fpub)) else None

    item.tasas_eur = _coerce_float(data.get("tasas_eur"))
    item.url_bases = _coerce_str(data.get("url_bases"))
    item.url_inscripcion = _coerce_str(data.get("url_inscripcion"))

    reqs = data.get("requisitos_clave")
    if isinstance(reqs, list):
        item.requisitos_clave = [str(x) for x in reqs if x is not None][:8]
    else:
        item.requisitos_clave = None

    fase = _coerce_str(data.get("fase"))
    item.fase = fase if fase in _VALID_FASES else (
        "otro" if fase else None
    )

    item.next_action = _coerce_str(data.get("next_action"))
    item.confidence = _coerce_float(data.get("confidence"))
    item.enriched_at = datetime.now(timezone.utc).isoformat()
    item.enriched_version = ENRICHMENT_VERSION


def _coerce_bool(v: Any) -> Optional[bool]:
    if isinstance(v, bool):
        return v
    if isinstance(v, str):
        s = v.strip().lower()
        if s in ("true", "yes", "si", "sí", "1"):
            return True
        if s in ("false", "no", "0"):
            return False
    return None


def _coerce_str(v: Any) -> Optional[str]:
    if v is None:
        return None
    if isinstance(v, str):
        s = v.strip()
        return s or None
    return str(v)


def _coerce_int(v: Any) -> Optional[int]:
    if v is None or isinstance(v, bool):
        return None
    if isinstance(v, int):
        return v
    if isinstance(v, float):
        return int(v)
    if isinstance(v, str):
        s = v.strip()
        try:
            return int(s)
        except ValueError:
            try:
                return int(float(s))
            except ValueError:
                return None
    return None


def _coerce_float(v: Any) -> Optional[float]:
    if v is None or isinstance(v, bool):
        return None
    if isinstance(v, (int, float)):
        return float(v)
    if isinstance(v, str):
        try:
            return float(v.strip().replace(",", "."))
        except ValueError:
            return None
    return None
