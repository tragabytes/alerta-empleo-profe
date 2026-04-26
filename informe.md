# Mapa de fuentes para un bot de Telegram que cace empleo docente en Madrid

**El 80% del valor del bot se extrae con sólo cinco entradas: la API JSON del BOE, el RSS del BOCM, los canales de Telegram de ANPE/CSIF Madrid, la API oficial de InfoJobs y la API gratuita de Jooble.** Todo lo demás —portales de ATS de colegios privados, web del Instituto Cervantes, ayuntamientos del noroeste, plataformas ELE— son capas complementarias que cubren nichos específicos pero introducen costes técnicos crecientes (JavaScript dinámico, anti-bot, autenticación). El perfil descrito (Historia + máster + ELE + C1 inglés, sin búsqueda bilingüe) tiene tres mercados naturales: **oposiciones/interinidad pública de la especialidad 005 Geografía e Historia**, **colegios privados/concertados de la zona noroeste de Madrid** y **academias y universidades ELE**. Las tres requieren estrategias distintas y este informe las separa por categoría con URLs verificadas, viabilidad técnica de scraping, prioridad y notas de implementación. La conclusión transversal es clara: **sólo dos fuentes ofrecen API/RSS limpio (BOE y InfoJobs/Jooble); el resto exige scraping HTML** —en su mayoría sin protección agresiva si se respeta el rate limiting.

---

## Arquitectura recomendada por capas de polling

Antes de entrar en el catálogo, conviene fijar el modelo operativo. El bot debe organizarse en **cuatro capas con frecuencias distintas** según la latencia útil de cada tipo de oferta. Las convocatorias oficiales (BOE/BOCM) admiten polling diario porque sólo se publican una vez al día. Los canales de Telegram sindicales son tiempo real y conviene leerlos vía MTProto (Telethon o Pyrogram). Los ATS de colegios privados se mueven a ritmo de horas. Y los ayuntamientos cambian a ritmo semanal.

| Capa | Cadencia | Fuentes núcleo | Método |
|------|----------|----------------|--------|
| **L1 – Tiempo real** | continuo | Canales Telegram `@ANPEmadrid`, `@csifeducacionmadrid`, `@ugteducacionpublicamadrid`, `@educacion_ccoomadrid`, `@noticiasoposicionessecundaria`, `@bolsasdocentes`, `@opobusca` | MTProto / Bot API |
| **L2 – Diaria** | 1×/día (07:00) | BOE API JSON, BOCM RSS, comunidad.madrid (interinos), InfoJobs API, Jooble API, Indeed RSS, Colejobs, Colegios.es, sede Cervantes | HTTP + parsers |
| **L3 – Cada 6-12 h** | 2-4×/día | ATS de Inspired, SEK, Brains, Highlands, ANPE Madrid, CSIF Madrid, Hispanismo Cervantes, Profesoresdeele.org | HTTP + diff |
| **L4 – Semanal** | 1×/semana | Webs ayuntamientos (Tres Cantos, Las Rozas, Pozuelo, Majadahonda, Boadilla, etc.), universidades (Nebrija, UCM, UC3M), Lectorados AECID/MEFP/Fulbright | HTTP + hash diff |

El cuello de botella técnico no es el volumen de fuentes sino **distinguir señal de ruido**. Un regex maestro aplicado tras cada polling reduce ofertas en un 90%:

```regex
(?i)\b(geograf[ií]a\s+e\s+historia|profesor(?:ado|es)?\s+(?:de\s+)?(?:ense[ñn]anza\s+)?secundaria|cuerpo\s+0590|especialidad\s+005|interinidad|listas?\s+extraordinaria|bolsa\s+de\s+empleo.+docente|espa[ñn]ol\s+(?:para\s+extranjeros|como\s+lengua\s+extranjera)|\bELE\b|escuelas\s+oficiales\s+de\s+idiomas|0592|concurso\s+de\s+traslados.*docente|profesor\s+(?:de\s+)?adultos|educaci[oó]n\s+compensatoria|lectorad[oa]|auxiliar\s+conversaci[oó]n)
```

Y un filtro de localización por la lista de municipios objetivo (Alcobendas, San Sebastián de los Reyes, Tres Cantos, Las Rozas, Majadahonda, Pozuelo, Boadilla, Torrelodones, Collado Villalba, Villanueva de la Cañada, Galapagar, Hoyo de Manzanares, Moraleja, Soto de Viñuelas, Ciudalcampo, Villafranca del Castillo). **Filtro de exclusión obligatorio**: descartar ofertas con `bilingüe.{0,30}inglés` cuando el rol completo se imparte en inglés.

---

## Empleo público y oposiciones: la columna vertebral del perfil

El BOE y el BOCM concentran el 100% de las convocatorias oficiales que pueden interesar al usuario, y son los únicos endpoints **completamente abiertos, con APIs limpias, sin captcha, sin Cloudflare y sin autenticación**.

### BOE — la fuente más limpia técnicamente

La API de datos abiertos del BOE devuelve sumarios diarios en JSON o XML según el header `Accept`. El endpoint `https://www.boe.es/datosabiertos/api/boe/sumario/AAAAMMDD` (con `Accept: application/json`) sirve el árbol completo del boletín diario; cada item trae `identificador`, `titulo`, `url_pdf`, `url_html`, `url_xml`. No hay rate limit documentado, no hay JS, no hay captcha. La sección **II.B (Oposiciones y concursos)** y los departamentos `MINISTERIO DE EDUCACIÓN, FORMACIÓN PROFESIONAL Y DEPORTES` y `COMUNIDAD DE MADRID` contienen lo relevante. Documentación oficial en `https://www.boe.es/datosabiertos/documentos/APIsumarioBOE.pdf`. **Prioridad máxima, scraping trivial con `requests`.**

### BOCM — la fuente más rica en convocatorias autonómicas

El Boletín Oficial de la Comunidad de Madrid es la **fuente de verdad** para todas las convocatorias docentes regionales (Cuerpo 0590, especialidad 005) y para los concursos de empleo de los ayuntamientos del noroeste. Tiene **tres feeds RSS oficiales**:
- `https://www.bocm.es/boletines.rss` (últimos 20 boletines)
- `https://www.bocm.es/sumarios.rss` (últimos 20 sumarios)
- `https://www.bocm.es/ultimo-boletin.xml` (anuncios detallados del día)

La búsqueda avanzada en `https://www.bocm.es/advanced-search` admite POST con texto libre y rango de fechas para buscar publicaciones antiguas. **Riesgo a vigilar**: el RSS sólo guarda 20 entradas; si el bot cae más de un día puede perderse publicaciones. Convocatorias docentes autonómicas aparecen siempre en Sección I.B → Consejería de Educación → Dirección General de Recursos Humanos.

### Portal de la Comunidad de Madrid: las bolsas en directo

Las bolsas de interinos viven en `https://www.comunidad.madrid/servicios/educacion/profesorado-interino` y las **listas extraordinarias permanentemente abiertas** (las que más se mueven para especialidades deficitarias) en `https://www.comunidad.madrid/servicios/educacion/listas-extraordinarias-permanentemente-abiertas-profesores-interinos`. La especialidad 005 *no suele estar deficitaria*, pero las bilingües 819/820/821 y a veces ELE sí. **El PADI (sustituciones diarias) requiere certificado digital del candidato y no es scrapeable**: el bot sólo puede recordar al usuario que entre. La sede electrónica `https://sede.comunidad.madrid/bolsa-empleo` carga listados con AJAX → conviene capturar el endpoint XHR JSON con DevTools antes de implementar, o caer a Playwright.

### Estado, SEPE y ayuntamientos del noroeste

`administracion.gob.es/pagFront/ofertasempleopublico/buscarConvocatoria.htm` con parámetros `tipoConvocatoria=2&_comunidadAutonoma=12` permite filtrar Madrid; es **HTML server-side, sin JS, scrapeable**. SEPE/Empléate es una SPA Vue que requiere Playwright o usar la versión `index_nojs.html?JAVASCRIPTSTATUS=NONE`. Los ayuntamientos del noroeste son donde aparecen plazas de **profesor de educación de adultos, educación compensatoria y profesores municipales de música/cultura** —relevantes ocasionalmente para el perfil. Tabla operativa:

| Ayuntamiento | URL crítica | Tecnología | Observación |
|--------------|-------------|------------|-------------|
| **Alcobendas** | `alcobendas.org/es/ayuntamiento/empleo-publico` + `alcobendas.convoca.online/` | Convoca = SPA Vue (necesita Playwright) | OEP 2024 incluyó **7 plazas docentes ESO/adultos** |
| **Tres Cantos** | `web.trescantos.es/transparencia/convocatorias-de-empleo-publico/` | WordPress estático | El más fácil de scrapear; estructura predecible |
| **Las Rozas** | `lasrozas.es/el-ayuntamiento/Convocatorias-en-plazo` | Drupal | HTML scrapeable |
| **Majadahonda** | `majadahonda.org/empleo-publico` + `majadahonda.convoca.online/` | Mixto | Convocan profesor pintura/música/cerámica |
| **Pozuelo** | `pozuelodealarcon.org/tu-ayuntamiento/empleo-publico/ofertas-de-empleo-publico` | HTML server-side | Patronato Cultura saca plazas de música |
| **Boadilla** | `silbo.aytoboadilla.org/` | eAdmin estándar | Scrapeable HTTP |
| **San Sebastián de los Reyes** | `ssreyes.org/oferta-de-empleo-p%C3%BAblico` | Liferay | Scrapeable |
| **Torrelodones** | `torrelodones.es/ayuntamiento/avisos-y-bandos/54-menus/empleo/` | Joomla | Baja actividad docente |
| **Villanueva de la Cañada** | `ayto-villacanada.es/economia-y-empleo/empleo-publico/procesos-selectivos/` | WordPress | Scrapeable |
| **Hoyo de Manzanares** | `hoyodemanzanares.sedelectronica.es/info.0` | sedelectronica.es Espublico | Estructura común replicable a otros |
| **Galapagar** | `sede.galapagar.es/eAdmin/Tablon.do?action=verAnuncios` | eAdmin | Scrapeable |
| **Collado Villalba** | `colladovillalba.es/empleo` | Joomla | Suelen redirigir a BOCM |

**Atajo importante**: como casi todas estas convocatorias se publican primero en el BOCM, **monitorizar el RSS del BOCM con un regex que incluya el nombre del ayuntamiento es más eficiente** que polling individual. Reservar el polling municipal para detectar bases de bolsas de trabajo no publicadas en BOCM.

---

## Colegios privados y concertados de la zona objetivo

El sector privado madrileño se ha consolidado alrededor de **cuatro grandes ATS** y un conjunto de webs propias con formularios de candidatura. Identificar el ATS subyacente es lo que determina la viabilidad del scraping.

### Los cuatro ATS dominantes en la zona noroeste

**Inspired Education Group** (`https://jobs.inspirededu.com/?locale=es_ES`) es el portal con mejor ROI: agrupa Mirabal (Boadilla), Kensington School (Pozuelo), King's College (Soto de Viñuelas/Tres Cantos), Colegio San Patricio (La Moraleja/El Soto) y Everest. Listado server-side, paginación estable, anti-bot bajo. **Prioridad muy alta** —concentra cinco colegios objetivo en una sola URL. Para Geografía e Historia y ELE aparecen vacantes con regularidad.

**SEK Education Group** (`https://empleo.sek.es/`) usa Teamtailor y publica plazas IB de Geography & History y de ELE. Cubre SEK El Castillo, SEK Ciudalcampo (San Sebastián de los Reyes/Soto de Viñuelas) y la Universidad Camilo José Cela (Villanueva de la Cañada). Teamtailor expone HTML estático con URLs estables `/jobs/[id]-[slug]`; scraping HTTP simple sin captcha.

**Brains International Schools** (`https://brainsinternationalschool.factorial.es/`) usa el ATS Factorial; HTML server-side, sin protección notable. Cubre el centro de La Moraleja (Alcobendas), zona prioritaria.

**Colegios RC / Highlands** (`https://jobs.lcred.net/colegiosrc/`) usa SAP SuccessFactors. Cubre Highlands Los Fresnos (Boadilla), Highlands El Encinar y Everest Monteclaro (Pozuelo). HTML estable pero **rate-limita en exceso** —respetar 4-6 segundos entre peticiones.

### Bolsas privadas estructuradas y semi-estructuradas

| Fuente | URL | Frecuencia | Scraping | Notas |
|--------|-----|------------|----------|-------|
| **Colejobs.es** | `colejobs.es/ofertas-trabajo/madrid/` | 60-70 ofertas activas en pico | HTTP simple, paginación `?page=N` | Probablemente **fuente número uno** para colegios privados, alta densidad de Geografía/Historia y ELE |
| **Colegios.es** | `colegios.es/empleoprofesores/historia/` y `/empleoprofesores/trabajo/ofertas-de-empleo/` | Diaria | WordPress, probar `/feed/` | Categoría dedicada a Historia |
| **Talento ECM (Escuelas Católicas Madrid)** | `talentoecm.es/login.aspx` | Bolsa inversa | **No scrapeable** | Crítico para Salesianos/Maristas/Escolapios/Marianistas/Pilar; obliga a registro manual del usuario |
| **Edutalent** | `edutalent.es/empleo/ofertas-docente-de-greografia-e-historia/` | Diaria | Detalles tras login | Útil como segunda fuente |
| **Magisnet** | `magisnet.com` | RSS WordPress (`/feed/`) | Trivial | Noticias de OEP, no ofertas directas |
| **Empleo.magister.com** | `empleo.magister.com` | Requiere login | Bloqueado | Descartar para automatización |

### Colegios singulares sin ATS (estrategia diff)

Para los colegios que sólo tienen un formulario de "trabaja con nosotros" sin listado de vacantes, la única estrategia automática es **monitorizar el hash del bloque relevante** y alertar cuando cambie: Logos International (Las Rozas), Liceo Europeo (Moraleja), Los Sauces (Moraleja/Torrelodones), Engage y Thames British School (Majadahonda), Zola, Balder y GSD (Las Rozas), Schoenstatt, Alarcón, San José de Cluny y Veritas (Pozuelo). El grupo **Attendis NO opera en Madrid** (sólo Andalucía y Extremadura), descartable. **ACADE y CECE** no tienen bolsa pública activa.

---

## Plataformas ELE: dispersión alta, automatización media

El sector ELE no tiene un BOE: la información se distribuye entre la sede electrónica del Instituto Cervantes, dos blogs de referencia (TodoELE y ProfesoresdeELE), una lista de correo histórica (FORMESPA), las webs propias de academias y los programas oficiales de lectorados. **El bot debe combinar scraping HTML con parsing de email** para cubrirlo bien.

### Núcleo institucional

**Instituto Cervantes** publica todas sus convocatorias en su sede electrónica, `https://cervantes.sede.gob.es/categoria?idCat=100296`. La convocatoria pública de profesores (referencia `CVA-PROF-PUB-XX/XX`) se abre aproximadamente una vez al año y nutre la bolsa para centros en el extranjero. **No hay convocatoria periódica de profesores ELE en la sede de Madrid**; sólo becas de formación anuales (38+1 plazas, última publicada en julio 2025). HTML server-rendered con URLs estables, **sin RSS pero scrapeable**. Complementariamente, `https://hispanismo.cervantes.es/convocatorias-y-empleo/ofertas-empleo` agrega 942+ ofertas históricas de hispanismo internacional —prioridad alta para perfil académico/lectorados.

**TodoELE** (`https://todoele.net/ofertas-trabajo`) es el referente mundial en bolsa ELE, con 47 ofertas activas en abril 2026 y filtros por país, tipo de centro y duración. Drupal con tabla HTML regular, scrapeable trivialmente con BeautifulSoup. **Sin RSS**, pero la URL `?page=N` permite recorrer paginación de forma estable.

**ProfesoresdeELE.org** (`https://profesoresdeele.org/category/ofertas-de-trabajo/`) es WordPress puro: el feed `/category/ofertas-de-trabajo/feed/` debería existir y resolver el problema con un `feedparser` de cuatro líneas. Frecuencia alta de ofertas Madrid/España.

**FORMESPA** es una lista de correo de RedIRIS (>2.200 suscriptores en 33 países), moderada por TodoELE desde 2023. Suscripción enviando email a `LISTSERV@LISTSERV.REDIRIS.ES` con cuerpo `subscribe FORMESPA Nombre Apellidos`. Para integrarla con el bot, **configurar un buzón IMAP que reenvíe los mensajes parseados a Telegram**.

### Lectorados y programas oficiales (alertas calendarizadas)

Cinco programas marcan el calendario anual del usuario y deberían disparar alertas por fecha:

- **MAEC-AECID Lectorados** (`https://www.aecid.es/lectorados-para-espanoles-maec-aecid`): convocatoria anual, ~150 plazas en 70 países; vacantes nuevas 13-30 enero, renovaciones jul-oct también en enero, renovaciones dic-ene en abril. Edad máxima 37 años. **Encaja perfecto en el perfil** (acepta Máster ELE oficial).
- **Auxiliares de Conversación MEFP** (Profex 2): convocatoria octubre-enero, programa Europa/América/Oceanía.
- **Profesorado Visitante en EE.UU. y Canadá**: requiere experiencia previa en sistema español ≥1 curso —barrera potencial para recién graduado.
- **Fulbright FLTA** (`https://fulbright.es/programas-y-becas/convocatorias/lectorados-de-espanol/`): 13 plazas anuales, abre septiembre, cierra mediados octubre. Requiere TOEFL ≥90 (el C1 inglés del usuario es suficiente).
- **Escuelas Europeas / Consejería en el exterior**: programas paralelos del MAEUEC.

### Academias y universidades de Madrid

| Centro | URL clave | Frecuencia | Notas |
|--------|-----------|------------|-------|
| **AIL Madrid** | LinkedIn `linkedin.com/company/ail-espanol` | Alto volumen (~200 profesores) | No tiene página de empleo estructurada; advertir al usuario sobre polémicas laborales documentadas |
| **International House Madrid** | `ihmadrid.com/profesores-espanol` + LinkedIn | Frecuente | "No tenemos bolsa formal" pero contratan tras formación interna |
| **Estudio Sampere** | LinkedIn + `infojobs.net/estudio-sampere/...` | Esporádica | Publican vacantes en LinkedIn |
| **Don Quijote / Enforex** | `donquijote.org/jobs/`, `enforex.com/espanol/trabajo-web.html` | CV abierto | Mismo grupo Ideal Education, reputación cuestionada |
| **Tandem Madrid** | `tandemmadrid.com/es/trabaja-en-tandem-madrid/` | CV abierto | Pocas vacantes específicas |
| **Inhispania Madrid** | Publica en TodoELE y profesoresdeele.org | Frecuente | No requiere monitorización propia |
| **Universidad Nebrija — CEHI** | `nebrija.es/rrhh/seleccion/portal/inscripcion.php` | Vacantes ELE periódicas | **La universidad más activa** del segmento |
| **UCM Centro Complutense para la Enseñanza del Español** | `ucm.es/empleo-ucm` | Esporádica | PDI estándar |
| **UC3M Centro de Idiomas** | `uc3m.es/conocenos/empleo-universidad` | Esporádica | Máster ELE online |
| **Comillas, CEU, URJC, UCJC, UFV, UEM** | Webs institucionales | Esporádica | Prioridad media-baja |
| **EOI Madrid (Español para Extranjeros)** | Vía BOCM (especialidad 008) | Convocatoria anual marzo-abril | Funcionarios A1 |

### Plataformas online de tutoría

italki, Preply, Verbling y Lingoda **no son fuentes de ofertas** sino marketplaces o academias online donde el usuario se registra como tutor. No procede scraping continuo: bastan recordatorios al usuario para crear y mantener perfil. **Lingoda** sí tiene un proceso de selección estructurado en `https://www.lingoda.com/en/become-a-teacher/` (exige C2 nativo + título + 2-3 años + cert. ELE; tarifa modesta ~8,50 €/h). Open English no contrata profesores ELE.

---

## Sindicatos y comunidades: la ventaja informativa de horas

Los sindicatos publican **antes que las webs oficiales** los acuerdos de mesa sectorial, distribuciones de plazas y aperturas de bolsas extraordinarias. Para un opositor es la diferencia entre llegar a tiempo a una lista o quedarse fuera.

### Telegram: el canal nativo del bot

La estrategia óptima es **integrar el bot con Telegram MTProto (Telethon o Pyrogram)** para leer estos canales públicos en tiempo real:

- `@ANPEmadrid` — ANPE Madrid oficial, **el más rápido en alertas de bolsas extraordinarias**
- `@csifeducacionmadrid` — CSIF Educación Madrid (publican "CSIF INFORMA" con resoluciones BOCM en directo)
- `@ugteducacionpublicamadrid` — UGT Servicios Públicos Madrid
- `@educacion_ccoomadrid` — CCOO Madrid (también difunden PDFs con circulares)
- `@noticiasoposicionessecundaria` — agregador multi-CCAA con subgrupos por especialidad
- `@bolsasdocentes` — bolsas docentes nacional
- `@opobusca` — buscador automatizado, mensajes estructurados ideales para parsing
- `@forodocentescsif` — foro abierto

Como **fallback sin API key** funciona el HTML preview público en `https://t.me/s/{canal}`, scrapeable con `requests` + BeautifulSoup.

### Webs sindicales (cuando Telegram no basta)

**ANPE Madrid** (`https://anpemadrid.es/mas-noticias` y `/etiqueta1/Convocatoria`) usa CMS propio sin RSS estándar. Las URLs `notices/{ID}/{slug}` permiten deduplicación por ID numérico incremental. **Polling cada 15-30 minutos en horario laboral** L-V; en semanas de convocatorias activas, cada 10 minutos. Sin captcha, sin Cloudflare, sin login. ANPE nacional (`anpe.es/web/38/Bolsas-de-trabajo`) complementa con info de otras CCAA y exterior.

**CSIF Madrid** (`csif.es/comunidad-de-madrid/educacion`, `/oposiciones`) corre sobre el CMS propietario "Lansoft", también sin RSS. Estructura de URLs `articulo/.../{ID}` predecible. **FeSP-UGT Madrid** (`fespugtmadrid.es/category/general/ensenanza-publica/`) y **CCOO Madrid** (`feccoo-madrid.org/Pública`) son scrapeables; el primero es WordPress estándar (probar `/feed/` con alta probabilidad de éxito), el segundo usa CMS propio con estructura `noticia:{ID}--{slug}` y muchos PDFs adjuntos que requieren `pdfplumber` para extraer texto.

**STES/STEM Madrid** (`stemstes.org`, `stes.es/category/territorios/madrid/`) son WordPress; los feeds `/feed/` y `/category/territorios/madrid/feed/` deberían funcionar.

### El caso especial de la concertada

**FSIE Madrid** es el único cauce estructurado para empleo en concertada, pero su bolsa (`fsiemadrid.es/bolsa-de-empleo/`) **es exclusiva de afiliados** y no es scrapeable: el bot sólo puede notificar las noticias y comunicados públicos. Para entrar a la bolsa real **el usuario debe afiliarse** y subir CV + autorización RGPD. **FEUSO Madrid** (`feusomadrid.net`) cubre sector concertada/privada pero rara vez publica vacantes específicas.

### Preparadores de oposiciones

Los preparadores son útiles porque **mantienen tablas comparadas de OEP por CCAA** que se actualizan antes de la publicación oficial. El más útil es **CEN** (`https://www.cen.edu/oposiciones-secundaria/convocatorias-2026-2027/`) con tabla viva por CCAA. Le siguen **MAD Editorial** (`mad.es/oposiciones/educacion/profesores-de-secundaria/geografia-e-historia/`) y los blogs de preparadores específicos de Geografía e Historia: Rafael Montes, Manuel Vida, David Molina, Opogeo, Aula de Historia. Todos son WordPress: el bot puede consumir sus `/feed/` automáticamente. Magister tiene noticias en `web.magister.com/noticias/`.

### Foros y otras redes

`buscaoposiciones.com/foro/` mantiene una sección activa de "Educacion-Secundaria-Geografia-e-Historia" con hilos del propio Rafael Montes. `reddit.com/r/opositores` accesible vía JSON API (`/r/opositores.json` con User-Agent), prioridad baja por bajo volumen específico. **Facebook está prácticamente vetado** desde 2024 (Graph API ya no permite leer grupos sin ser admin). **Twitter/X requiere API de pago** (~$100/mes); como Telegram cubre el mismo contenido, descartable.

---

## Portales generalistas: dos APIs limpias y un RSS que sobrevive

Aquí la conclusión es contraintuitiva: **InfoJobs y Jooble tienen APIs oficiales gratuitas que la mayoría de scrapers ignoran**, y son la mejor base sobre la que construir el bot.

### InfoJobs API (gratis, oficial, sin captcha)

`https://api.infojobs.net/api/9/offer` con HTTP Basic Auth (`client_id`/`client_secret` registrados gratis en `https://developer.infojobs.net/`) devuelve JSON o XML según el header `Accept`. Parámetros: `q`, `province=Madrid`, `category`, `page`, `maxResults`. **Sin OAuth de usuario para búsqueda de ofertas**; rate limit no documentado pero generoso. Como complemento existe RSS por búsqueda en `https://www.infojobs.net/trabajos.feed/{filtro}` —generar suscribiéndose desde cualquier búsqueda. Volumen: ~90 ofertas activas en consultas tipo "profesor + Madrid". **Esto debe ser el corazón del bot para mercado privado.**

### Jooble API (agregador gratuito)

`POST https://jooble.org/api/{API_KEY}` con body `{"keywords":"profesor historia","location":"Madrid","page":"1"}` devuelve JSON limpio agregando InfoJobs, Indeed, LinkedIn y decenas de portales más. Registro en `https://jooble.org/api/about`. **Es la mejor opción para cobertura amplia con un único request limpio**: 1.300+ ofertas indexadas para "profesor + Madrid". Documentación oficial en `help.jooble.org`.

### Indeed: el RSS no oficial que sigue funcionando

Indeed cerró su Publisher API y deja a los scrapers contra Cloudflare + Turnstile. Pero el **truco RSS sigue activo**: `https://rss.indeed.com/rss?q=profesor+historia&l=Madrid&sort=date` devuelve un feed XML estable. Sin documentación oficial, **funciona por inercia** y puede caer en cualquier momento; conviene tener fallback con Playwright + IP residencial.

### LinkedIn Guest API: el truco semioficial

El endpoint `https://www.linkedin.com/jobs-guest/jobs/api/seeMoreJobPostings/search` acepta `keywords`, `location`, `geoId=105646813` (Comunidad de Madrid), `f_TPR=r604800` (semana), `sortBy=DD`, `start=0|25|50…` y devuelve **HTML fragment** parseable con BeautifulSoup. Máximo 1.000 resultados por búsqueda. **Tolerado de facto**, sin captcha si se respeta cadencia (1 consulta cada 5-10 min por keyword) y se rotan headers Chrome realistas. No requiere JavaScript, no requiere login. **La API oficial de LinkedIn es inviable** (sólo partners corporativos con pricing privado).

### Resto del ecosistema

| Portal | Mejor método | Comentario |
|--------|--------------|------------|
| **Trabajos.com / Laboris** | Scraping HTTP simple | Volumen modesto; mismo grupo (Schibsted) que InfoJobs |
| **Computrabajo.es** | Scraping con Cloudflare suave | Más relevante en LATAM |
| **Talent.com** | Scraping con Cloudflare | Agregador grande |
| **Adecco / Randstad / Manpower** | Scraping HTTP, categoría educación | ETT con vacantes docentes reales pero bajo volumen |
| **Hays / Michael Page / Page Personnel** | — | Perfiles ejecutivos, no docencia operativa |
| **JobToday / JobandTalent** | — | Hostelería/operario, no aplica |
| **Empléate (SEPE)** | Playwright o `index_nojs.html?JAVASCRIPTSTATUS=NONE` | SPA Vue; útil para interinidades agregadas |
| **Google for Jobs** | Sólo vía SerpAPI (~50 €/mes) | Redundante si ya tienes InfoJobs/Jooble/LinkedIn |
| **Tusclasesparticulares / Superprof / Classgap** | Registro como profesor | No son fuentes de ofertas, sino marketplaces |

---

## Plan de implementación priorizado

Si el desarrollo se ataca por orden de ROI, la secuencia óptima es:

**Sprint 1 — núcleo público:** API JSON del BOE + RSS del BOCM con regex maestro y filtro de municipios. Ya cubre el 60% del valor para oposiciones e interinidad.

**Sprint 2 — núcleo privado:** API InfoJobs + API Jooble con keywords "profesor historia", "profesor secundaria", "profesor español extranjeros", "profesor ELE", filtro provincia Madrid. Añade el 70% del mercado privado en dos integraciones limpias.

**Sprint 3 — Telegram en tiempo real:** integración MTProto con los siete canales sindicales clave. El usuario ganará horas frente a la competencia en bolsas extraordinarias.

**Sprint 4 — ATS de colegios privados:** scrapers para Inspired, SEK Teamtailor, Brains Factorial y Colegios RC (con pausa de 4-6 segundos). Añade la red noroeste de Madrid.

**Sprint 5 — bolsas docentes especializadas:** Colejobs, Colegios.es, ProfesoresdeELE (RSS WordPress), TodoELE, sede Cervantes, Hispanismo Cervantes, Universidad Nebrija. Cubre el segmento ELE.

**Sprint 6 — capa LinkedIn + Indeed:** guest API de LinkedIn y RSS no oficial de Indeed con IP residencial y cache agresivo.

**Sprint 7 — capa municipal y universitaria:** scraping semanal de los 12 ayuntamientos de la zona y de las webs de empleo de UCM, UC3M, Comillas, CEU, URJC, UCJC, UFV, UEM.

**Sprint 8 — alertas calendario:** disparar avisos en septiembre (Fulbright FLTA, Auxiliares MEFP), enero (AECID lectorados, Profesores Visitantes), marzo-abril (oposiciones EOI Madrid), mayo-julio (becas Cervantes).

**Sprint 9 — recordatorios de registro manual:** el bot debe avisar al usuario para mantener vivos los perfiles en Talento ECM, Tusclasesparticulares, Superprof, Lingoda, italki, Preply y Verbling, que no se pueden automatizar.

### Stack técnico mínimo recomendado

Python con `httpx` async para el grueso de fuentes HTTP, `feedparser` para los RSS de WordPress, `beautifulsoup4` o `selectolax` para HTML, `pdfplumber` para los comunicados de CCOO, `Telethon` o `Pyrogram` para los canales de Telegram, y `python-telegram-bot` para envío al usuario. Headers obligatorios en todos los requests: `User-Agent` Chrome realista, `Accept-Language: es-ES,es;q=0.9,en;q=0.8`. Deduplicación con hash SHA-256 sobre `(título + URL)` en Redis con TTL de 30 días. **Playwright sólo cuando es estrictamente imprescindible** (sede.comunidad.madrid, alcobendas.convoca.online, majadahonda.convoca.online, empleate.gob.es) porque dispara coste de CPU y latencia.

## Conclusión: dónde vive el dinero del proyecto

La paradoja del catálogo es que **las dos fuentes con APIs gratuitas legales (BOE e InfoJobs+Jooble) cubren más superficie útil que las treinta integraciones siguientes juntas**. El error típico al diseñar un bot de empleo es perseguir el agregador perfecto (LinkedIn, Indeed, Google Jobs) y descuidar la fontanería oficial. Para este perfil concreto —Historia + ELE, Madrid noroeste— el ranking de impacto está clarísimo: **convocatorias autonómicas** (BOCM + sindicatos en Telegram) priman sobre todo lo demás, **ATS de Inspired y SEK** son la mejor entrada al privado, y **lectorados oficiales** son la mejor opción ELE para alguien que aún está construyendo experiencia. El segundo aprendizaje es que **PADI, Talento ECM, FSIE Madrid y los marketplaces P2P (italki/Preply/Verbling)** no son automatizables: el bot tiene que asumir su rol como sistema de recordatorios y delegar la acción al usuario. Y el tercero es que **Indeed y LinkedIn no merecen el coste técnico** que reclaman si InfoJobs API + Jooble API ya están en marcha; sólo añadirlos cuando el resto del bot esté maduro y con presupuesto para proxies residenciales.