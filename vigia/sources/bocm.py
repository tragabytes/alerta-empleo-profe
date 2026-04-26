"""
Fuente BOCM: tres feeds RSS oficiales + descarga selectiva de PDFs.

A diferencia de vigia-enfermeria (que recurre a estimar números de edición y
forzar URLs XML), aquí explotamos los RSS oficiales descritos en informe.md:

  - https://www.bocm.es/boletines.rss     (últimos 20 boletines)
  - https://www.bocm.es/sumarios.rss      (últimos 20 sumarios)
  - https://www.bocm.es/ultimo-boletin.xml (anuncios detallados del día)

Estrategia:
  1. Descargar `ultimo-boletin.xml` para tener el detalle del día actual
  2. Filtrar disposiciones de la sección "I.B Autoridades y Personal" cuyo
     título mencione profesorado/educación/cuerpos 0590-0597 o 0592
  3. Para títulos ambiguos pero de Consejería de Educación o ayuntamientos
     del noroeste, descargar el PDF y extraer texto

Riesgo conocido: el RSS sólo guarda 20 entradas; si el bot cae más de un día
puede perderse publicaciones. Mitigación: el cron diario (08:00 UTC) tira del
feed a tiempo. Para backfill se recurriría a /advanced-search (POST), pendiente
de Sprint posterior.
"""
from __future__ import annotations

import io
import logging
import re
from datetime import date, datetime, timedelta
from xml.etree import ElementTree as ET

import requests

from vigia.config import normalize
from vigia.sources.base import RawItem, Source

logger = logging.getLogger(__name__)

BOCM_HOME = "https://www.bocm.es"
BOCM_ULTIMO_BOLETIN = "https://www.bocm.es/ultimo-boletin.xml"
BOCM_BOLETINES_RSS = "https://www.bocm.es/boletines.rss"
BOCM_SUMARIOS_RSS = "https://www.bocm.es/sumarios.rss"

# Patrones para descubrir boletines en los feeds:
# - El RSS expone enlaces HTML (`/boletin/bocm-YYYYMMDD-NN`) y PDF
#   (`/boletin/CM_Boletin_BOCM/YYYY/MM/DD/BOCM-YYYYMMDDNNN.PDF`).
# - El XML estructurado vive en la misma URL que el PDF pero con extensión
#   `.xml` y el número siempre con tres dígitos (`NNN`). Ejemplo:
#     PDF: BOCM-20260425097.PDF
#     XML: BOCM-20260425097.xml
# Por tanto: extraemos cualquier referencia a un boletín y construimos la URL
# XML canónica.
_BOLETIN_RE = re.compile(
    r"BOCM-(\d{4})(\d{2})(\d{2})(\d{3})\.(?:PDF|xml)", re.IGNORECASE
)
# Fallback: enlace HTML "/boletin/bocm-YYYYMMDD-N" donde N puede no estar
# zero-padded.
_HTML_LINK_RE = re.compile(
    r"/boletin/bocm-(\d{4})(\d{2})(\d{2})-(\d+)", re.IGNORECASE
)
BOCM_XML_URL = (
    "https://www.bocm.es/boletin/CM_Boletin_BOCM/{year}/{month:02d}/{day:02d}/"
    "BOCM-{year}{month:02d}{day:02d}{num:03d}.xml"
)

# Organismos que justifican descargar el PDF para inspeccionar el cuerpo
# cuando el título del sumario es ambiguo pero el contexto sugiere docencia.
EDUCATION_ORGS = [
    "consejeria de educacion",
    "consejeria de educacion ciencia",
    "direccion general de recursos humanos",
    "direccion general de educacion",
    "direccion general de bilinguismo",
    "viceconsejeria de educacion",
    # Universidades públicas Madrid
    "universidad complutense",
    "universidad autonoma de madrid",
    "universidad carlos iii",
    "universidad rey juan carlos",
    "universidad politecnica",
    # Ayuntamientos noroeste (informe.md)
    "ayuntamiento de alcobendas",
    "ayuntamiento de san sebastian",
    "ayuntamiento de tres cantos",
    "ayuntamiento de las rozas",
    "ayuntamiento de majadahonda",
    "ayuntamiento de pozuelo",
    "ayuntamiento de boadilla",
    "ayuntamiento de torrelodones",
    "ayuntamiento de collado villalba",
    "ayuntamiento de villanueva de la canada",
    "ayuntamiento de galapagar",
    "ayuntamiento de hoyo de manzanares",
]

# Palabras que disparan descarga de PDF si el organismo es relevante
PDF_TRIGGER_WORDS = [
    "concurso de meritos",
    "proceso selectivo",
    "convocatoria proceso selectivo",
    "convocatoria",
    "bolsa de empleo",
    "bolsa de trabajo",
    "lista extraordinaria",
    "listas extraordinarias",
    "interinidad",
    "interino",
]

# Para el match rápido en título antes de descargar body
TITLE_FAST_KEYWORDS = [
    "profesor",
    "docente",
    "secundaria",
    "cuerpo 0590",
    "cuerpo 0592",
    "geografia e historia",
    "interinidad",
    "interino",
    "lectorad",
    "auxiliar de conversacion",
    "espanol para extranjeros",
    " ele ",
    "escuelas oficiales de idiomas",
    "concurso de traslados",
    "educacion",
]


class BOCMSource(Source):
    name = "bocm"
    probe_url = BOCM_ULTIMO_BOLETIN

    def fetch(self, since_date: date) -> list[RawItem]:
        """
        Tira de tres feeds RSS y consolida los XML que cubran el rango.

        - Para el día corriente y muy reciente: `ultimo-boletin.xml`
          (anuncios completos con `<disposicion>`).
        - Para fechas anteriores dentro del rango: enumeramos URLs XML
          presentes en `boletines.rss` y `sumarios.rss` y filtramos por
          fecha extraída del nombre del fichero (BOCM-YYYYMMDD-NN.xml).
        """
        target_dates = set()
        for delta in range((date.today() - since_date).days + 1):
            d = since_date + timedelta(days=delta)
            if d.weekday() < 5:  # BOCM no publica los domingos; sábado ocasional
                target_dates.add(d)

        if not target_dates:
            return []

        xml_urls = self._discover_xml_urls(target_dates)
        if not xml_urls:
            logger.info("BOCM: ninguna URL XML descubierta en el rango")
            return []

        items: list[RawItem] = []
        for xml_url, target in xml_urls:
            try:
                items.extend(self._parse_xml(xml_url, target))
            except Exception as exc:
                logger.warning("BOCM %s error: %s", xml_url, exc)
                self.last_errors.append(f"{xml_url}: {exc}")
        return items

    def _discover_xml_urls(
        self, target_dates: set[date]
    ) -> list[tuple[str, date]]:
        """
        Descubre URLs XML que coincidan con cualquiera de las fechas objetivo.

        El RSS oficial sólo expone enlaces HTML y PDF, no la URL XML directa.
        Pero el XML vive en la misma ruta que el PDF cambiando la extensión:
            PDF: .../BOCM-{YYYYMMDD}{NNN}.PDF
            XML: .../BOCM-{YYYYMMDD}{NNN}.xml

        Estrategia:
          1. Bajar `boletines.rss` y `sumarios.rss` (entre los dos cubren los
             últimos ~20 boletines).
          2. Extraer (fecha, num) de cada referencia BOCM-YYYYMMDDNNN.{PDF,xml}
             o de los enlaces HTML `/boletin/bocm-YYYYMMDD-N`.
          3. Construir la URL XML canónica para cada (fecha, num) que caiga
             dentro del rango objetivo.

        Devuelve lista deduplicada de (url_xml, fecha).
        """
        candidates: dict[str, date] = {}
        seen_keys: set[tuple[date, int]] = set()

        for rss_url in (BOCM_BOLETINES_RSS, BOCM_SUMARIOS_RSS):
            try:
                resp = requests.get(
                    rss_url, headers=self._default_headers(), timeout=15
                )
                resp.raise_for_status()
            except Exception as exc:
                logger.warning("BOCM RSS %s: %s", rss_url, exc)
                self.last_errors.append(f"{rss_url}: {exc}")
                continue

            for m in _BOLETIN_RE.finditer(resp.text):
                try:
                    file_date = date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
                except ValueError:
                    continue
                num = int(m.group(4))
                self._maybe_register(file_date, num, target_dates,
                                     candidates, seen_keys)

            for m in _HTML_LINK_RE.finditer(resp.text):
                try:
                    file_date = date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
                except ValueError:
                    continue
                num = int(m.group(4))
                self._maybe_register(file_date, num, target_dates,
                                     candidates, seen_keys)

        return [(url, d) for url, d in candidates.items()]

    def _maybe_register(
        self,
        file_date: date,
        num: int,
        target_dates: set[date],
        candidates: dict[str, date],
        seen_keys: set[tuple[date, int]],
    ) -> None:
        """Si (fecha, num) cae dentro del rango y no estaba ya, construye
        la URL XML canónica y la registra como candidata."""
        if file_date not in target_dates:
            return
        key = (file_date, num)
        if key in seen_keys:
            return
        seen_keys.add(key)
        url = BOCM_XML_URL.format(
            year=file_date.year,
            month=file_date.month,
            day=file_date.day,
            num=num,
        )
        candidates[url] = file_date

    def _parse_xml(self, xml_url: str, target: date) -> list[RawItem]:
        resp = requests.get(xml_url, headers=self._default_headers(), timeout=30)
        resp.raise_for_status()
        try:
            root = ET.fromstring(resp.content)
        except ET.ParseError as exc:
            logger.error("BOCM: error parseando XML %s: %s", xml_url, exc)
            return []

        items: list[RawItem] = []
        seen_ids: set[str] = set()

        for disp in root.iter("disposicion"):
            id_elem = disp.find("identificador")
            if id_elem is None:
                continue
            item_id = id_elem.text or ""
            if item_id in seen_ids:
                continue
            seen_ids.add(item_id)

            titulo_elem = disp.find("titulo")
            titulo = (titulo_elem.text or "").strip() if titulo_elem is not None else ""
            # Algunos títulos llegan con un encabezado corto antes de '•'
            if "•" in titulo or "\n" in titulo:
                titulo = titulo.replace("•", "\n").split("\n", 1)[-1].strip()

            url_html_elem = disp.find("url_html")
            url_html = (url_html_elem.text or "") if url_html_elem is not None else ""
            url_pdf_elem = disp.find("url_pdf")
            url_pdf = (url_pdf_elem.text or "") if url_pdf_elem is not None else ""

            org_name = self._find_organismo(root, item_id)
            titulo_norm = normalize(titulo)
            has_fast_kw = any(kw in titulo_norm for kw in TITLE_FAST_KEYWORDS)

            pdf_text = ""
            if not has_fast_kw and url_pdf:
                org_norm = normalize(org_name)
                is_education_org = any(kw in org_norm for kw in EDUCATION_ORGS)
                has_trigger = any(kw in titulo_norm for kw in PDF_TRIGGER_WORDS)
                if is_education_org and has_trigger:
                    try:
                        pdf_text = self._extract_pdf_text(url_pdf)
                    except Exception as exc:
                        logger.debug("BOCM PDF fetch error %s: %s", url_pdf, exc)

            combined = f"{titulo} {pdf_text}"
            if not any(kw in normalize(combined) for kw in TITLE_FAST_KEYWORDS):
                continue

            items.append(
                RawItem(
                    source=self.name,
                    url=url_html or url_pdf,
                    title=titulo,
                    date=target,
                    text=pdf_text,
                )
            )

        return items

    def _find_organismo(self, root: ET.Element, item_id: str) -> str:
        """Busca el nombre del organismo para un item_id dado."""
        for org in root.iter("organismo"):
            for disp in org:
                id_e = disp.find("identificador")
                if id_e is not None and id_e.text == item_id:
                    return org.get("nombre", "")
        return ""

    def _extract_pdf_text(self, pdf_url: str, max_pages: int | None = None) -> str:
        """Descarga el PDF y extrae texto completo (PDFs individuales son ~200-500KB)."""
        import pdfplumber

        resp = requests.get(pdf_url, headers=self._default_headers(), timeout=60)
        resp.raise_for_status()
        with pdfplumber.open(io.BytesIO(resp.content)) as pdf:
            pages = pdf.pages if max_pages is None else pdf.pages[:max_pages]
            text_parts = [t for page in pages if (t := page.extract_text())]
        return " ".join(text_parts)
