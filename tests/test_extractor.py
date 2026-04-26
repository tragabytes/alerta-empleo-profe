"""
Pruebas del extractor con casos representativos del perfil docente.

Cubre:
  - matches fuertes (Geografía e Historia, ELE, lectorados, EOI...)
  - matches débiles (convocatoria + profesor en ventana)
  - falsos positivos (cuerpo 0597, PDI universitario, roles bilingües)
"""
from datetime import date

from vigia.extractor import extract
from vigia.sources.base import RawItem


def _raw(title: str, text: str = "", source: str = "test") -> RawItem:
    return RawItem(source=source, url=f"http://x/{abs(hash(title))}",
                   title=title, date=date(2026, 4, 1), text=text)


# ---------------------------------------------------------------------------
# Matches fuertes
# ---------------------------------------------------------------------------

def test_geografia_historia_directo_matches():
    item = extract(_raw("Convocatoria oposición Geografía e Historia 2026"))
    assert item is not None
    assert item.categoria in ("oposicion", "otro")


def test_cuerpo_0590_matches():
    item = extract(_raw(
        "Resolución por la que se publican las plazas del Cuerpo 0590"
    ))
    assert item is not None


def test_especialidad_005_matches():
    item = extract(_raw("Plazas para la especialidad 005 de Secundaria"))
    assert item is not None


def test_eoi_espanol_extranjeros_matches():
    item = extract(_raw(
        "Convocatoria EOI - profesores de español para extranjeros"
    ))
    assert item is not None


def test_lectorado_aecid_matches():
    item = extract(_raw(
        "Convocatoria de Lectorados MAEC-AECID en universidades extranjeras"
    ))
    assert item is not None
    assert item.categoria == "lectorado"


def test_auxiliar_conversacion_matches():
    item = extract(_raw("Auxiliares de conversación en EE.UU. y Canadá"))
    assert item is not None
    assert item.categoria == "lectorado"


def test_bolsa_interinidad_matches():
    item = extract(_raw(
        "Apertura de listas extraordinarias de profesorado interino"
    ))
    assert item is not None
    assert item.categoria == "bolsa"


def test_concurso_traslados_docente_matches():
    item = extract(_raw(
        "Concurso de traslados del profesorado de cuerpos docentes"
    ))
    assert item is not None
    assert item.categoria == "traslado"


def test_match_via_body_text():
    """El título es genérico pero el cuerpo tiene 'Geografía e Historia'."""
    item = extract(_raw(
        "Resolución de proceso selectivo",
        text="Especialidad 005 Geografía e Historia, 80 plazas en Madrid",
    ))
    assert item is not None


# ---------------------------------------------------------------------------
# Matches débiles
# ---------------------------------------------------------------------------

def test_weak_convocatoria_profesor():
    """'Convocatoria' es weak; necesita 'profesor' cerca para matchear."""
    item = extract(_raw(
        "Convocatoria de profesores para el centro municipal de adultos"
    ))
    assert item is not None


def test_weak_consejeria_educacion_docente():
    item = extract(_raw(
        "Consejería de Educación: nueva bolsa de docentes para ESO"
    ))
    assert item is not None


# ---------------------------------------------------------------------------
# Falsos positivos
# ---------------------------------------------------------------------------

def test_maestros_primaria_descartado():
    item = extract(_raw(
        "Convocatoria del Cuerpo 0597 Maestros, especialidad infantil"
    ))
    assert item is None


def test_pdi_universitario_descartado():
    item = extract(_raw(
        "Plazas PDI Profesor Ayudante Doctor en la Universidad Complutense"
    ))
    assert item is None


def test_profesor_titular_descartado():
    item = extract(_raw(
        "Concurso de Profesor Titular de Universidad - área de Historia"
    ))
    assert item is None


def test_rol_bilingue_ingles_descartado():
    item = extract(_raw(
        "Profesor de secundaria bilingüe en inglés - colegio Madrid"
    ))
    assert item is None


def test_clases_en_ingles_descartado():
    item = extract(_raw(
        "Profesor para impartir clases en inglés en King's College"
    ))
    assert item is None


def test_oferta_no_relevante_no_matchea():
    item = extract(_raw(
        "Resolución sobre tasas universitarias del curso 2026/27"
    ))
    assert item is None


def test_oferta_completamente_inconexa_no_matchea():
    item = extract(_raw(
        "Convenio de colaboración con la Fundación X para becas tecnológicas"
    ))
    assert item is None
