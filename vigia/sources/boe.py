"""
Fuente BOE: API oficial de sumarios diarios.

Endpoint: GET https://boe.es/datosabiertos/api/boe/sumario/YYYYMMDD
          Accept: application/json

Estrategia:
  Las convocatorias docentes estatales (lectorados AECID, profesores visitantes,
  Cuerpo 0590 ámbito MEFD, EOI nacional) suelen aparecer en sección II.B
  (Oposiciones y concursos) bajo:
    - MINISTERIO DE EDUCACIÓN, FORMACIÓN PROFESIONAL Y DEPORTES
    - MINISTERIO DE ASUNTOS EXTERIORES (lectorados AECID)
    - MINISTERIO DE LA PRESIDENCIA, JUSTICIA Y RELACIONES CON LAS CORTES
    - COMUNIDAD DE MADRID

  El título suele indicar "convocatoria para proveer plazas" sin mencionar
  la especialidad exacta. Para items de departamentos relevantes se descarga
  el HTML del cuerpo y se busca el patrón en el texto completo.
"""
from __future__ import annotations

import logging
from datetime import date, timedelta
from urllib.parse import urlparse, urlunparse

import requests

from vigia.config import normalize
from vigia.sources.base import RawItem, Source

logger = logging.getLogger(__name__)

# Endpoints — usamos `www.boe.es` como canónico (boe.es a secas redirige
# casi siempre, pero el redirect es lo primero que falla cuando el runner
# de GitHub Actions cae en un rango IP problemático). El helper
# `_get_with_host_fallback` se encarga de probar el host alternativo si el
# primario timeoutea o rechaza la conexión.
BOE_SUMARIO_URL = "https://www.boe.es/datosabiertos/api/boe/sumario/{fecha}"

# Pareja primario / fallback. La elección de cuál es primario y cuál
# fallback la determina el host de la URL que se pasa al helper.
_HOST_FALLBACKS = {
    "www.boe.es": "boe.es",
    "boe.es": "www.boe.es",
}

# Timeouts (segundos). Subimos de los 20s originales tras observar timeouts
# intermitentes desde el runner de GitHub Actions; con 45s damos margen al
# servidor cuando está lento sin bloquear el run completo.
TIMEOUT_API = 45     # sumario JSON
TIMEOUT_BODY = 30    # HTML del cuerpo
TIMEOUT_PROBE = 30   # HEAD/GET ligero de probe

# Secciones que pueden contener convocatorias docentes
SECTIONS_TO_FETCH_BODY = {"2A", "2B", "3"}

# Departamentos relevantes (texto normalizado) que justifican descargar el HTML
# del cuerpo para buscar la especialidad. Cobertura amplia: el regex maestro
# se aplicará luego en el extractor.
DEPT_KEYWORDS_FOR_BODY = [
    "ministerio de educacion",
    "ministerio de asuntos exteriores",  # AECID lectorados
    "ministerio de la presidencia",      # auxiliares conversación
    "comunidad de madrid",
    "consejeria de educacion",
    "comunidades autonomas",
    "administracion local",
    "universidad",
    "instituto cervantes",
    "agencia espanola de cooperacion",
    "aecid",
]

# Para el match rápido en título antes de descargar body
TITLE_FAST_KEYWORDS = [
    "profesor",
    "docente",
    "ensenanza secundaria",
    "secundaria",
    "cuerpo 0590",
    "cuerpo 0592",
    "geografia e historia",
    "interinidad",
    "lectorado",
    "lectorad",
    "auxiliar de conversacion",
    "espanol para extranjeros",
    " ele ",
    "escuelas oficiales de idiomas",
    "concurso de traslados",
    "educacion",
]


class BOESource(Source):
    name = "boe"
    # Probe: la home del API de datos abiertos. No depende de fecha.
    probe_url = "https://www.boe.es/datosabiertos/"

    def _get_with_host_fallback(
        self,
        url: str,
        *,
        timeout: int,
        method: str = "GET",
        **kwargs,
    ) -> requests.Response:
        """
        GET/HEAD con fallback automático entre `boe.es` y `www.boe.es`.

        Si el host primario timeoutea o rechaza la conexión, reintenta en
        el otro. Errores HTTP (4xx/5xx) NO disparan fallback — sólo problemas
        de red, donde el otro host puede vivir en una IP distinta y responder.
        """
        parsed = urlparse(url)
        host = (parsed.hostname or "").lower()
        fallback_host = _HOST_FALLBACKS.get(host)

        try:
            return requests.request(method, url, timeout=timeout, **kwargs)
        except (requests.ConnectionError, requests.Timeout) as exc:
            if not fallback_host:
                raise
            new_url = urlunparse(parsed._replace(netloc=fallback_host))
            logger.warning(
                "BOE %s falló (%s); reintentando en %s",
                host, exc.__class__.__name__, fallback_host,
            )
            return requests.request(method, new_url, timeout=timeout, **kwargs)

    def probe(self, timeout: int = TIMEOUT_PROBE) -> dict:
        """Probe con fallback de host (sobreescribe al de Source)."""
        if not self.probe_url:
            return {
                "name": self.name, "status": "skipped", "code": None,
                "url": None, "detail": "fuente sin probe_url",
            }
        try:
            resp = self._get_with_host_fallback(
                self.probe_url,
                timeout=timeout,
                method="HEAD",
                headers=self._default_headers(),
                allow_redirects=True,
            )
            if resp.status_code >= 400:
                # Algunos servidores rechazan HEAD; reintenta con GET stream.
                resp = self._get_with_host_fallback(
                    self.probe_url,
                    timeout=timeout,
                    method="GET",
                    headers=self._default_headers(),
                    allow_redirects=True,
                    stream=True,
                )
                resp.close()
        except Exception as exc:
            return {
                "name": self.name, "status": "error", "code": None,
                "url": self.probe_url, "detail": str(exc),
            }
        return {
            "name": self.name,
            "status": "ok" if resp.status_code < 400 else "error",
            "code": resp.status_code,
            "url": self.probe_url,
            "detail": "" if resp.status_code < 400 else resp.reason,
        }

    def fetch(self, since_date: date) -> list[RawItem]:
        items: list[RawItem] = []
        for delta in range((date.today() - since_date).days + 1):
            target = since_date + timedelta(days=delta)
            if target.weekday() >= 5:  # no hay BOE los sábados y domingos normalmente
                continue
            try:
                items.extend(self._fetch_day(target))
            except Exception as exc:
                logger.warning("BOE %s error: %s", target, exc)
                self.last_errors.append(f"{target}: {exc}")
        return items

    def _fetch_day(self, target: date) -> list[RawItem]:
        url = BOE_SUMARIO_URL.format(fecha=target.strftime("%Y%m%d"))
        resp = self._get_with_host_fallback(
            url,
            timeout=TIMEOUT_API,
            headers={**self._default_headers(), "Accept": "application/json"},
        )
        if resp.status_code == 404:
            return []  # día sin BOE (festivo nacional)
        resp.raise_for_status()
        data = resp.json()
        return self._parse_sumario(data, target)

    def _parse_sumario(self, data: dict, target: date) -> list[RawItem]:
        items: list[RawItem] = []
        try:
            diario_list = data["data"]["sumario"]["diario"]
        except (KeyError, TypeError):
            logger.warning("BOE: estructura inesperada del sumario")
            return items

        if isinstance(diario_list, dict):
            diario_list = [diario_list]

        for diario in diario_list:
            secciones = diario.get("seccion", [])
            if isinstance(secciones, dict):
                secciones = [secciones]
            for sec in secciones:
                sec_code = sec.get("codigo", "")
                depts = sec.get("departamento", [])
                if isinstance(depts, dict):
                    depts = [depts]
                for dept in depts:
                    dept_name = dept.get("nombre", "")
                    raw_items = self._extract_items_from_node(dept)
                    for raw in raw_items:
                        titulo = raw.get("titulo", "")
                        url_html = raw.get("url_html", "") or raw.get("url_xml", "")
                        if not url_html:
                            continue
                        item = self._build_raw_item(
                            titulo, url_html, target, sec_code, dept_name
                        )
                        if item:
                            items.append(item)
        return items

    def _extract_items_from_node(self, node: dict) -> list[dict]:
        """Extrae items directos y de epígrafes de un nodo (departamento o epígrafe)."""
        results = []
        raw = node.get("item")
        if raw:
            if isinstance(raw, dict):
                results.append(raw)
            else:
                results.extend(raw)
        epigs = node.get("epigrafe", [])
        if isinstance(epigs, dict):
            epigs = [epigs]
        for epig in epigs:
            results.extend(self._extract_items_from_node(epig))
        return results

    def _build_raw_item(
        self,
        titulo: str,
        url_html: str,
        target: date,
        sec_code: str,
        dept_name: str,
    ) -> RawItem | None:
        """
        Construye un RawItem con el texto del body HTML si es necesario.
        Solo descarga el body para secciones 2A/2B/3 y departamentos relevantes.
        """
        titulo_norm = normalize(titulo)

        # Check rápido: ¿el título ya contiene algo relevante?
        has_fast_kw = any(kw in titulo_norm for kw in TITLE_FAST_KEYWORDS)

        # ¿Vale la pena descargar el body?
        dept_norm = normalize(dept_name)
        is_relevant_dept = any(kw in dept_norm for kw in DEPT_KEYWORDS_FOR_BODY)
        should_fetch_body = (
            sec_code in SECTIONS_TO_FETCH_BODY
            and (is_relevant_dept or has_fast_kw)
            and url_html
        )

        body_text = ""
        if should_fetch_body:
            try:
                body_text = self._fetch_html_text(url_html)
            except Exception as exc:
                logger.debug("BOE body fetch error %s: %s", url_html, exc)

        combined_text = f"{titulo} {body_text}"
        # Solo crear el item si hay algo relevante (título o body con fast keyword)
        if not has_fast_kw and not any(
            kw in normalize(combined_text) for kw in TITLE_FAST_KEYWORDS
        ):
            return None

        return RawItem(
            source=self.name,
            url=url_html,
            title=titulo,
            date=target,
            text=body_text,
        )

    def _fetch_html_text(self, url: str) -> str:
        """Descarga el HTML de un ítem BOE y extrae el texto plano."""
        from bs4 import BeautifulSoup

        resp = self._get_with_host_fallback(
            url, timeout=TIMEOUT_BODY, headers=self._default_headers(),
        )
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "lxml")
        # El contenido del BOE está en div#textoxslt o div.diari-boe
        content = (
            soup.find("div", id="textoxslt")
            or soup.find("div", class_="diari-boe")
            or soup.find("div", id="texto")
            or soup.body
        )
        return content.get_text(" ", strip=True) if content else ""
