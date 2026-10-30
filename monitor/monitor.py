"""
Monitor de afluencia de Bee's Pizza's (versión GitHub Actions)
---------------------------------------------------------------
Cada ejecución toma lecturas cada `cada_minutos` durante `duracion_minutos`
y cubre así el hueco entre corridas programadas de GitHub.

Avisa por notificación push (a la página instalada en tu celular) cuando:
  🔥 hay PICO             (afluencia en vivo >= umbral_pico, confirmado N lecturas)
  ✅ ya BAJÓ la gente     (afluencia en vivo <= umbral_baja)
  ⏰ en la próxima hora SUELE llenarse (curva habitual de Google)
  ⭐ hay una reseña NUEVA en Google Maps
  ⚠️ el monitor lleva rato sin poder leer Google

Uso:
    python monitor/monitor.py            -> ronda completa de lecturas
    python monitor/monitor.py --una-vez  -> una sola lectura (para probar en tu laptop)
    python monitor/monitor.py --prueba   -> solo manda una notificación de prueba

Secretos (variables de entorno, en GitHub: Settings > Secrets > Actions):
    VAPID_PRIVATE_KEY     llave privada que genera la página al activar notificaciones
    PUSH_SUBSCRIPTIONS    lista JSON con la suscripción de cada celular
    GOOGLE_PLACES_API_KEY llave de la API de Google Places (solo para reseñas; ver LEEME.md)
"""

import json
import os
import sys
import time
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import requests

RAIZ = Path(__file__).resolve().parent.parent
DOCS = RAIZ / "docs"
DATOS = DOCS / "data"
ARCHIVO_CONFIG = DOCS / "config.json"
ARCHIVO_ESTADO = DATOS / "estado.json"
ARCHIVO_HISTORIAL = DATOS / "historial.csv"

ZONA = ZoneInfo("America/Mexico_City")
DIAS_GOOGLE = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
FALLOS_PARA_AVISAR = 10  # ~30 min sin poder leer con lecturas cada 3 min
ESTRELLAS = {1: "⭐", 2: "⭐⭐", 3: "⭐⭐⭐", 4: "⭐⭐⭐⭐", 5: "⭐⭐⭐⭐⭐"}

ESTADO_INICIAL = {
    "en_pico": False,
    "lecturas_altas": 0,
    "inicio_pico": None,
    "maximo_pico": 0,
    "anticipado_enviado": None,
    "fallos_seguidos": 0,
    "aviso_fallo_enviado": False,
    "ultima_lectura": None,
    "curva_hoy": None,
    "fecha_curva": None,
    "ultima_resena_ts": None,      # ISO de la reseña más nueva ya vista
    "resenas_conocidas": [],       # ids ya avisados, para no repetir si el orden de Google se mueve
    "fallos_resenas_seguidos": 0,
    "aviso_fallo_resenas_enviado": False,
}


# ------------------------------------------------------------------ utilidades

def ahora():
    return datetime.now(ZONA)


def hhmm(t=None):
    return (t or ahora()).strftime("%H:%M")


def leer_json(ruta, defecto):
    try:
        with open(ruta, encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return defecto


def guardar_json(ruta, datos):
    ruta.parent.mkdir(parents=True, exist_ok=True)
    with open(ruta, "w", encoding="utf-8") as f:
        json.dump(datos, f, ensure_ascii=False, indent=2)


def dentro_de_horario(cfg, t):
    inicio, fin = cfg.get("horario", ["00:00", "23:59"])
    return inicio <= hhmm(t) <= fin


# ------------------------------------------------------------------ lectura de Google

def leer_google(cfg):
    """Devuelve (en_vivo, curva_de_hoy). curva_de_hoy = 24 valores 0-100 o None."""
    import livepopulartimes

    datos = livepopulartimes.get_populartimes_by_address(cfg["direccion_google"]) or {}
    en_vivo = datos.get("current_popularity")
    curva = None
    dia_hoy = DIAS_GOOGLE[ahora().weekday()]
    for dia in datos.get("populartimes") or []:
        if dia.get("name") == dia_hoy and len(dia.get("data") or []) == 24:
            curva = dia["data"]
    return en_vivo, curva


# ------------------------------------------------------------------ reseñas (API oficial de Google)

def leer_resenas(cfg):
    """Trae hasta 5 reseñas del local vía la API oficial Places API (New).
    Devuelve una lista de dicts {id, autor, calificacion, texto, publicada} o [] si no hay place_id/llave."""
    place_id = (cfg.get("google_place_id") or "").strip()
    llave = os.environ.get("GOOGLE_PLACES_API_KEY", "").strip()
    if not place_id or not llave:
        print(f"[{hhmm()}] Reseñas: falta la llave GOOGLE_PLACES_API_KEY; no se revisaron.")
        return []

    r = requests.get(
        f"https://places.googleapis.com/v1/places/{place_id}",
        params={"languageCode": "es"},
        headers={"X-Goog-Api-Key": llave, "X-Goog-FieldMask": "reviews"},
        timeout=30,
    )
    r.raise_for_status()
    crudas = r.json().get("reviews") or []

    resenas = []
    for res in crudas:
        resenas.append({
            "id": res.get("name", ""),  # ej. places/XXX/reviews/YYY, único por reseña
            "autor": (res.get("authorAttribution") or {}).get("displayName", "Alguien"),
            "calificacion": res.get("rating"),
            "texto": (res.get("text") or {}).get("text", "").strip(),
            "publicada": res.get("publishTime"),  # ISO 8601, ej. 2026-09-27T18:04:00Z
        })
    return resenas


def revisar_resenas(estado, cfg):
    """Compara las reseñas actuales contra las ya vistas y arma los avisos de las nuevas."""
    if not cfg.get("revisar_resenas", True):
        return []
    if not (cfg.get("google_place_id") or "").strip():
        return []  # no configurado: no es un error, simplemente no se activó

    try:
        resenas = leer_resenas(cfg)
    except Exception as e:
        estado["fallos_resenas_seguidos"] += 1
        print(f"[{hhmm()}] Error leyendo reseñas ({estado['fallos_resenas_seguidos']} seguidos): {e}")
        if estado["fallos_resenas_seguidos"] >= 3 and not estado["aviso_fallo_resenas_enviado"]:
            estado["aviso_fallo_resenas_enviado"] = True
            return [("⚠️ No se pudieron revisar las reseñas",
                     "Revisa la llave GOOGLE_PLACES_API_KEY y el google_place_id en la configuración.",
                     "falla-resenas")]
        return []

    estado["fallos_resenas_seguidos"] = 0
    estado["aviso_fallo_resenas_enviado"] = False
    print(f"[{hhmm()}] Reseñas revisadas: {len(resenas)} leídas de Google.")
    if not resenas:
        return []

    conocidas = set(estado.get("resenas_conocidas") or [])
    primera_vez = estado.get("ultima_resena_ts") is None
    nuevas = [r for r in resenas if r["id"] and r["id"] not in conocidas]

    # se guardan siempre las vistas, para no repetir un aviso si Google reordena la lista
    estado["resenas_conocidas"] = list({r["id"] for r in resenas} | conocidas)[-50:]
    marcas = [r["publicada"] for r in resenas if r["publicada"]]
    if marcas:
        estado["ultima_resena_ts"] = max(marcas + ([estado["ultima_resena_ts"]] if estado.get("ultima_resena_ts") else []))

    if primera_vez or not nuevas:
        return []  # la primera corrida solo "aprende" las reseñas existentes, no las anuncia todas

    avisos = []
    for r in sorted(nuevas, key=lambda r: r["publicada"] or ""):
        estrellas = ESTRELLAS.get(r["calificacion"], f"{r['calificacion']}★" if r["calificacion"] else "")
        fragmento = (r["texto"][:180] + "…") if len(r["texto"]) > 180 else r["texto"]
        cuerpo = f"{r['autor']} · {estrellas}" + (f'\n"{fragmento}"' if fragmento else " (sin comentario escrito)")
        avisos.append(("⭐ Nueva reseña en Google Maps", cuerpo, "resena"))
    return avisos


# ------------------------------------------------------------------ notificaciones push

def enviar_push(cfg, titulo, cuerpo, etiqueta):
    print(f"[{hhmm()}] AVISO -> {titulo}: {cuerpo}")
    llave = os.environ.get("VAPID_PRIVATE_KEY", "").strip()
    try:
        subs = json.loads(os.environ.get("PUSH_SUBSCRIPTIONS") or "[]")
    except json.JSONDecodeError:
        print("  PUSH_SUBSCRIPTIONS no es JSON válido; revisa el secreto.")
        return
    if isinstance(subs, dict):
        subs = [subs]
    if not llave or not subs:
        print("  (sin VAPID_PRIVATE_KEY o PUSH_SUBSCRIPTIONS: no se manda push)")
        return

    from pywebpush import WebPushException, webpush

    datos = json.dumps({"titulo": titulo, "cuerpo": cuerpo, "etiqueta": etiqueta}, ensure_ascii=False)
    for i, sub in enumerate(subs, 1):
        try:
            webpush(
                subscription_info=sub,
                data=datos,
                vapid_private_key=llave,
                vapid_claims={"sub": cfg.get("contacto_vapid", "mailto:admin@example.com")},
                ttl=1800,  # si el celular está sin señal, el aviso espera hasta 30 min
            )
            print(f"  push enviado al celular {i}")
        except WebPushException as e:
            codigo = getattr(e.response, "status_code", "?")
            nota = " (suscripción vencida: vuelve a activar notificaciones)" if codigo in (404, 410) else ""
            print(f"  error enviando al celular {i}: {codigo}{nota}")


# ------------------------------------------------------------------ lógica de avisos

def evaluar(estado, en_vivo, curva, cfg, t):
    """Actualiza el estado y devuelve la lista de avisos (titulo, cuerpo, etiqueta)."""
    avisos = []
    nombre = cfg["nombre_local"]
    pico, baja = cfg["umbral_pico"], cfg["umbral_baja"]
    normal = curva[t.hour] if curva else None
    extra = f" Lo normal a esta hora: {normal}%." if normal is not None else ""

    # 1) Aviso anticipado: en la curva habitual, la PRÓXIMA hora cruza el umbral y esta no.
    if cfg.get("aviso_anticipado", True) and curva and t.hour < 23 and not estado["en_pico"]:
        sig = curva[t.hour + 1]
        clave = f"{t:%Y-%m-%d}-{t.hour + 1}"
        if sig >= pico and curva[t.hour] < pico and estado.get("anticipado_enviado") != clave:
            estado["anticipado_enviado"] = clave
            avisos.append((
                "⏰ Se viene la hora fuerte",
                f"En {nombre} normalmente se llena a partir de las {t.hour + 1}:00 ({sig}% de su máximo). "
                f"Ahorita va en {en_vivo if en_vivo is not None else '—'}%.",
                "anticipado",
            ))

    if en_vivo is None:
        return avisos

    # 2) Pico / bajada con histéresis
    if not estado["en_pico"]:
        estado["lecturas_altas"] = estado["lecturas_altas"] + 1 if en_vivo >= pico else 0
        if estado["lecturas_altas"] >= cfg.get("lecturas_para_confirmar", 2):
            estado.update(en_pico=True, inicio_pico=hhmm(t), maximo_pico=en_vivo, lecturas_altas=0)
            avisos.append((
                "🔥 ¡Pico de gente!",
                f"{nombre} está al {en_vivo}% de su máximo.{extra} Es buen momento para ir a apoyar.",
                "pico",
            ))
    else:
        estado["maximo_pico"] = max(estado["maximo_pico"], en_vivo)
        if en_vivo <= baja:
            avisos.append((
                "✅ Ya bajó la gente",
                f"{nombre} bajó a {en_vivo}%.{extra} El pico fue de {estado['inicio_pico']} a {hhmm(t)} "
                f"(máximo {estado['maximo_pico']}%).",
                "pico",
            ))
            estado.update(en_pico=False, inicio_pico=None, maximo_pico=0)
    return avisos


def registrar_fallo(estado, cfg, error):
    estado["fallos_seguidos"] += 1
    print(f"[{hhmm()}] Error leyendo Google ({estado['fallos_seguidos']} seguidos): {error}")
    if estado["fallos_seguidos"] >= FALLOS_PARA_AVISAR and not estado["aviso_fallo_enviado"]:
        estado["aviso_fallo_enviado"] = True
        return [("⚠️ El monitor no puede leer Google",
                 "Lleva un rato sin poder leer la afluencia. Revisa los registros en GitHub Actions.",
                 "falla")]
    return []


def guardar_historial(t, en_vivo, normal):
    nuevo = not ARCHIVO_HISTORIAL.exists()
    ARCHIVO_HISTORIAL.parent.mkdir(parents=True, exist_ok=True)
    with open(ARCHIVO_HISTORIAL, "a", encoding="utf-8") as f:
        if nuevo:
            f.write("fecha,hora,en_vivo,normal\n")
        vivo = "" if en_vivo is None else en_vivo
        norm = "" if normal is None else normal
        f.write(f"{t:%Y-%m-%d},{hhmm(t)},{vivo},{norm}\n")


# ------------------------------------------------------------------ una lectura

def una_lectura(cfg, estado, lector=leer_google):
    t = ahora()
    try:
        en_vivo, curva = lector(cfg)
    except Exception as e:  # Google cambió su página, sin internet, bloqueo, etc.
        return registrar_fallo(estado, cfg, e)

    estado["fallos_seguidos"] = 0
    estado["aviso_fallo_enviado"] = False
    if curva:
        estado["curva_hoy"], estado["fecha_curva"] = curva, f"{t:%Y-%m-%d}"
    normal = curva[t.hour] if curva else None

    guardar_historial(t, en_vivo, normal)
    estado["ultima_lectura"] = {"momento": t.isoformat(timespec="minutes"), "en_vivo": en_vivo, "normal": normal}
    print(f"[{hhmm(t)}] En vivo: {en_vivo} | Normal: {normal} | En pico: {estado['en_pico']}")
    return evaluar(estado, en_vivo, curva, cfg, t)


# ------------------------------------------------------------------ main

def main():
    cfg = leer_json(ARCHIVO_CONFIG, None)
    if not cfg:
        sys.exit(f"No encuentro {ARCHIVO_CONFIG}")
    estado = {**ESTADO_INICIAL, **leer_json(ARCHIVO_ESTADO, {})}

    if "--prueba" in sys.argv:
        enviar_push(cfg, "👋 Prueba", f"Las notificaciones de {cfg['nombre_local']} funcionan.", "prueba")
        return

    if "--una-vez" not in sys.argv and not dentro_de_horario(cfg, ahora()):
        print(f"Fuera de horario ({hhmm()}); no se hacen lecturas.")
        return

    # Las reseñas se revisan una sola vez por corrida (no cada 3 min): no cambian tan seguido
    # y así se gasta menos cuota de la API de Google.
    for titulo, cuerpo, etiqueta in revisar_resenas(estado, cfg):
        enviar_push(cfg, titulo, cuerpo, etiqueta)
    guardar_json(ARCHIVO_ESTADO, estado)

    # La afluencia en vivo se puede pausar (p. ej. si Google bloquea la lectura) sin apagar las reseñas.
    if not cfg.get("revisar_afluencia", True):
        print("Afluencia en pausa (revisar_afluencia = false); solo se revisaron reseñas.")
        return

    intervalo = cfg.get("cada_minutos", 3)
    lecturas = 1 if "--una-vez" in sys.argv else cfg.get("duracion_minutos", 18) // intervalo + 1

    for i in range(lecturas):
        for titulo, cuerpo, etiqueta in una_lectura(cfg, estado):
            enviar_push(cfg, titulo, cuerpo, etiqueta)
        # se guarda en cada vuelta para no perder el estado si la corrida se corta
        estado["umbrales"] = {"pico": cfg["umbral_pico"], "baja": cfg["umbral_baja"]}
        guardar_json(ARCHIVO_ESTADO, estado)
        if i < lecturas - 1:
            if not dentro_de_horario(cfg, ahora()):
                break
            time.sleep(intervalo * 60)


if __name__ == "__main__":
    main()
