"""Pruebas de la lógica de avisos con lecturas simuladas (no se conecta a Google).
Correr:  python pruebas/test_monitor.py"""
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "monitor"))
import monitor as m

CFG = {"nombre_local": "Bee's", "umbral_pico": 70, "umbral_baja": 45,
       "lecturas_para_confirmar": 2, "aviso_anticipado": True}
CURVA = [0] * 12 + [20, 35, 50, 55, 45, 50, 60, 80, 95, 85, 55, 20]  # pico habitual 19-21 h


def t(h, mi=0):
    return datetime(2026, 9, 26, h, mi, tzinfo=m.ZONA)


def nuevo():
    return dict(m.ESTADO_INICIAL)


def test_pico_y_bajada():
    e = nuevo()
    serie = [(19, 0, 50), (19, 3, 75), (19, 6, 60), (19, 9, 72), (19, 12, 80), (19, 15, 90),
             (19, 18, 65), (19, 21, 50), (19, 24, 40), (19, 27, 72), (19, 30, 74)]
    tipos = []
    for h, mi, v in serie:
        for titulo, *_ in m.evaluar(e, v, CURVA, CFG, t(h, mi)):
            tipos.append((f"{h}:{mi:02d}", titulo))
    assert tipos == [("19:12", "🔥 ¡Pico de gente!"), ("19:24", "✅ Ya bajó la gente"),
                     ("19:30", "🔥 ¡Pico de gente!")], tipos


def test_anticipado_una_sola_vez():
    e = nuevo()
    avisos = []
    for mi in range(0, 60, 3):  # toda la hora 18 (la 19 es la primera >= 70)
        avisos += [a[0] for a in m.evaluar(e, 40, CURVA, CFG, t(18, mi))]
    assert avisos == ["⏰ Se viene la hora fuerte"], avisos
    # a las 19 y 20 ya no se repite (no es borde de subida)
    assert m.evaluar(e, 40, CURVA, CFG, t(19, 0)) == []
    assert m.evaluar(e, 40, CURVA, CFG, t(20, 0)) == []


def test_sin_dato_en_vivo_no_rompe():
    e = nuevo()
    assert m.evaluar(e, None, None, CFG, t(15)) == []


def test_aviso_de_falla():
    e = nuevo()
    avisos = []
    for _ in range(m.FALLOS_PARA_AVISAR + 5):
        avisos += m.registrar_fallo(e, CFG, "bloqueado")
    assert len(avisos) == 1


def test_una_lectura_escribe_archivos(tmp):
    m.ARCHIVO_HISTORIAL = tmp / "historial.csv"
    e = nuevo()
    m.una_lectura(CFG, e, lector=lambda cfg: (66, CURVA))
    assert e["ultima_lectura"]["en_vivo"] == 66
    assert m.ARCHIVO_HISTORIAL.read_text().startswith("fecha,hora,en_vivo,normal\n")


CFG_RESENAS = {**CFG, "revisar_resenas": True, "google_place_id": "places/demo123"}


def test_resenas_primera_vez_no_avisa():
    """La primera corrida debe 'aprender' las reseñas que ya existían, sin mandar 5 avisos de golpe."""
    e = nuevo()
    existentes = [
        {"id": "r1", "autor": "Ana", "calificacion": 5, "texto": "Rica pizza", "publicada": "2026-09-20T10:00:00Z"},
        {"id": "r2", "autor": "Luis", "calificacion": 4, "texto": "Buen servicio", "publicada": "2026-09-22T12:00:00Z"},
    ]
    m.leer_resenas = lambda cfg: existentes
    avisos = m.revisar_resenas(e, CFG_RESENAS)
    assert avisos == [], avisos
    assert set(e["resenas_conocidas"]) == {"r1", "r2"}
    assert e["ultima_resena_ts"] == "2026-09-22T12:00:00Z"


def test_resena_nueva_si_avisa():
    e = nuevo()
    e["resenas_conocidas"] = ["r1", "r2"]
    e["ultima_resena_ts"] = "2026-09-22T12:00:00Z"
    m.leer_resenas = lambda cfg: [
        {"id": "r1", "autor": "Ana", "calificacion": 5, "texto": "Rica pizza", "publicada": "2026-09-20T10:00:00Z"},
        {"id": "r2", "autor": "Luis", "calificacion": 4, "texto": "Buen servicio", "publicada": "2026-09-22T12:00:00Z"},
        {"id": "r3", "autor": "Marta", "calificacion": 2, "texto": "Tardó mucho", "publicada": "2026-09-27T19:00:00Z"},
    ]
    avisos = m.revisar_resenas(e, CFG_RESENAS)
    assert len(avisos) == 1, avisos
    assert "Marta" in avisos[0][1] and "⭐⭐" in avisos[0][1]
    assert "r3" in e["resenas_conocidas"]


def test_resena_repetida_no_vuelve_a_avisar():
    e = nuevo()
    e["resenas_conocidas"] = ["r1", "r2", "r3"]
    e["ultima_resena_ts"] = "2026-09-27T19:00:00Z"
    m.leer_resenas = lambda cfg: [
        {"id": "r3", "autor": "Marta", "calificacion": 2, "texto": "Tardó mucho", "publicada": "2026-09-27T19:00:00Z"},
    ]
    assert m.revisar_resenas(e, CFG_RESENAS) == []


def test_resenas_sin_configurar_no_hace_nada():
    e = nuevo()
    assert m.revisar_resenas(e, CFG) == []  # CFG no tiene google_place_id


def test_resenas_fallo_avisa_tras_varios_intentos():
    e = nuevo()

    def falla(cfg):
        raise RuntimeError("sin conexión")
    m.leer_resenas = falla
    avisos = []
    for _ in range(4):
        avisos += m.revisar_resenas(e, CFG_RESENAS)
    assert len(avisos) == 1
    assert avisos[0][2] == "falla-resenas"


def test_afluencia_en_pausa_no_lee_google(tmp):
    """Con revisar_afluencia = false, main() revisa reseñas y termina sin tomar lecturas."""
    import json
    m.ARCHIVO_CONFIG = tmp / "config.json"
    m.ARCHIVO_CONFIG.write_text(json.dumps({**CFG_RESENAS, "revisar_afluencia": False}), encoding="utf-8")
    m.ARCHIVO_ESTADO = tmp / "estado.json"
    m.ARCHIVO_HISTORIAL = tmp / "historial_pausa.csv"
    m.leer_resenas = lambda cfg: []
    sys.argv = ["monitor.py", "--una-vez"]
    m.main()
    assert not m.ARCHIVO_HISTORIAL.exists()
    estado = json.loads(m.ARCHIVO_ESTADO.read_text(encoding="utf-8"))
    assert estado["fallos_seguidos"] == 0 and estado["fallos_resenas_seguidos"] == 0


if __name__ == "__main__":
    import tempfile
    test_pico_y_bajada(); test_anticipado_una_sola_vez(); test_sin_dato_en_vivo_no_rompe(); test_aviso_de_falla()
    with tempfile.TemporaryDirectory() as d:
        test_una_lectura_escribe_archivos(Path(d))
    test_resenas_primera_vez_no_avisa(); test_resena_nueva_si_avisa()
    test_resena_repetida_no_vuelve_a_avisar(); test_resenas_sin_configurar_no_hace_nada()
    test_resenas_fallo_avisa_tras_varios_intentos()
    with tempfile.TemporaryDirectory() as d:
        test_afluencia_en_pausa_no_lee_google(Path(d))
    print("Todas las pruebas pasaron ✔")
