# Monitor de afluencia · Bee's Pizza's

Revisa la afluencia **en vivo** de Google Maps y te manda notificaciones al celular:

- 🔥 **Pico de gente**: 70% o más en 2 lecturas seguidas, o sea unos 6 minutos.
- ✅ **Ya bajó la gente**: 45% o menos. Incluye cuánto duró el pico y su máximo.
- ⏰ **Se viene la hora fuerte**: aviso anticipado cuando, según la curva normal de Google, en la próxima hora se llena.
- ⭐ **Reseña nueva en Google Maps**: quién la escribió, cuántas estrellas y el texto (si escribió uno).
- ⚠️ **El monitor no puede leer Google**: se manda si falla durante unos 30 minutos (afluencia) o unas horas (reseñas).

Hay dos piezas:

| Pieza | Dónde vive | Qué hace |
|---|---|---|
| `monitor/monitor.py` | GitHub Actions (gratis, siempre encendido) | Cada hora revisa reseñas. Si la afluencia está activa, además toma 7 lecturas, una cada 3 min |
| `docs/` (página) | GitHub Pages (gratis) | App instalable en el celular: estado actual, gráfica del día y recepción de notificaciones |

Tu laptop solo se usa para probar y subir los archivos. No tiene que quedarse prendida.

---

## Paso 1 · Probar en tu laptop

Necesitas Python 3.10 o más reciente.

```
cd bees-afluencia
pip install -r requirements.txt
```

En `docs/config.json`, llena `direccion_google` con el nombre y la dirección **tal como salen en Google Maps**. Luego corre:

```
python monitor/monitor.py --una-vez
```

Debe imprimir algo como `En vivo: 42 | Normal: 55`. Si sale `En vivo: None`, en ese momento Google no está dando el dato en vivo (pasa en horas tranquilas). Prueba en un horario con movimiento.

Para probar la lógica de avisos sin internet: `python pruebas/test_monitor.py`

> **Afluencia en pausa (octubre 2026):** la librería gratuita dejó de funcionar y Google bloquea el inicio de sesión automatizado, así que `revisar_afluencia` está en `false` y `livepopulartimes` se quitó de `requirements.txt`. Para reactivarla habría que volver a instalarla (`pip install git+https://github.com/GrocerCheck/LivePopularTimes`) y encontrar una forma de lectura que funcione.
>
> La lectura usa una librería gratuita de terceros (LivePopularTimes) que lee la página pública de Google Maps. No es oficial, va contra los términos de uso de Google y puede dejar de funcionar si Google cambia su página. Si pasa, el monitor te avisa con ⚠️.

## Paso 1.5 · Activar el aviso de reseñas nuevas (opcional)

Para esto **sí existe una API oficial de Google** (a diferencia de la afluencia). Es gratis hasta cierto uso, pero para activarla Google pide dar de alta una tarjeta; con el uso de este monitor (una consulta por corrida, cada 20 minutos) te queda muy por debajo de la cuota gratuita mensual.

1. Entra a [console.cloud.google.com](https://console.cloud.google.com), crea un proyecto (o usa uno existente).
2. En el buscador de la consola escribe **"Places API (New)"** y actívala para ese proyecto.
3. Ve a **APIs y servicios → Credenciales → Crear credenciales → Clave de API**. Copia la llave.
   *Recomendado:* edítala y en "Restricciones de API" limítala a "Places API (New)", para que no sirva para nada más si se filtra.
4. Consigue el **Place ID** de tu local: abre la herramienta [Place ID Finder de Google](https://developers.google.com/maps/documentation/places/web-service/place-id) (o busca "google place id finder"), localiza Bee's Pizza's y copia el ID (empieza como `ChIJ...`).
5. En `docs/config.json` pon ese valor en `"google_place_id"`.
6. Esa llave (`GOOGLE_PLACES_API_KEY`) va como **secreto de GitHub** en el Paso 3, igual que la llave privada de las notificaciones — nunca en `config.json`, porque el repositorio es público.

Si no quieres esta función, deja `"google_place_id": ""` y el monitor la ignora sin errores. También puedes desactivarla poniendo `"revisar_resenas": false`.

> **Limitación real:** la API solo entrega las 5 reseñas que Google considera más relevantes para ese local, no necesariamente las 5 más nuevas. En un local con pocas reseñas casi siempre coincide, pero si tienen cientos, una reseña nueva con pocas interacciones podría no aparecer en esas 5 y el aviso se retrasaría hasta que sí aparezca.

## Paso 2 · Subir a GitHub

1. Crea un repositorio **público** en github.com, por ejemplo `bees-afluencia`, con la rama `main`.
   *Tiene que ser público porque, siendo público, GitHub Actions y Pages son gratis sin límite. Lo único visible es el porcentaje de afluencia y la dirección del local. Las llaves y suscripciones van en secretos, que nadie ve.*
2. Sube todo el contenido de esta carpeta, incluyendo la carpeta oculta `.github`:
   ```
   git init && git add . && git commit -m "Monitor de afluencia"
   git branch -M main
   git remote add origin https://github.com/TU_USUARIO/bees-afluencia.git
   git push -u origin main
   ```
3. En el repo, ve a **Settings → Pages**. En *Source* elige **Deploy from a branch**, con la rama `main` y la carpeta `/docs`. Guarda.
   En 1 o 2 minutos tu página queda en `https://TU_USUARIO.github.io/bees-afluencia/`.

## Paso 3 · Instalar la app en el celular y activar notificaciones

1. Abre esa dirección en el celular.
   - **Android (Chrome):** menú ⋮ → **Instalar app**.
   - **iPhone (iOS 16.4 o más reciente):** Compartir → **Agregar a pantalla de inicio**, y ábrela **desde el ícono**. En iPhone las notificaciones solo funcionan así.
2. Toca **Activar notificaciones en este celular** y acepta el permiso.
3. La primera vez la página te muestra 3 datos para copiar:
   - **Llave privada** → en GitHub: **Settings → Secrets and variables → Actions → New repository secret**, con el nombre `VAPID_PRIVATE_KEY`.
   - **Llave pública** → edita `docs/config.json` en GitHub y pégala en `"vapid_public"`. Aprovecha para poner tu correo en `"contacto_vapid"` (`mailto:tucorreo@...`). Es obligatorio para los servicios de notificaciones, pero no se muestra en ningún lado.
   - **Suscripción** → nuevo secreto `PUSH_SUBSCRIPTIONS`.
4. Si activaste el Paso 1.5, agrega un secreto más: `GOOGLE_PLACES_API_KEY` con la llave de Google Cloud.

**¿Más celulares?** Cuando ya esté la llave pública en `config.json`, abre la página en el otro celular y toca Activar. Solo te dará su suscripción. Junta todas en el mismo secreto:
`[ {"endpoint":"…celular 1…"}, {"endpoint":"…celular 2…"} ]`

## Paso 4 · Probar desde GitHub

En el repo: **Actions → Monitor de afluencia → Run workflow**.

1. Elige `prueba`. Te debe llegar "👋 Prueba" al celular.
2. Elige `normal` en horario de servicio. Revisa en el registro que lea Google. Esto confirma que Google no bloquea a los servidores de GitHub.

A partir de ahí corre solo cada hora dentro del `horario`.

---

## Ajustes (`docs/config.json`)

| Campo | Qué hace |
|---|---|
| `umbral_pico` / `umbral_baja` | % del máximo del local para avisar pico o bajada. 100 = lo más lleno que suele estar |
| `lecturas_para_confirmar` | Lecturas seguidas arriba del umbral antes de avisar. Evita falsas alarmas |
| `aviso_anticipado` | `true`/`false` para el aviso ⏰ |
| `cada_minutos`, `duracion_minutos` | Frecuencia de lecturas dentro de cada corrida |
| `horario` | Solo monitorea dentro de este horario (hora de CDMX) |
| `revisar_afluencia` | `true`/`false` para leer la afluencia en vivo (🔥 ✅ ⏰). Hoy está en `false`: ver la nota de abajo |
| `revisar_resenas` | `true`/`false` para el aviso ⭐ |
| `google_place_id` | Place ID del local (ver Paso 1.5). Vacío = desactivado |

El historial queda en `docs/data/historial.csv`. Con unas semanas de datos puedes afinar los umbrales.

## A tener en cuenta

- Google da un **porcentaje respecto al pico del propio local**, no un número de personas.
- Las corridas programadas de GitHub pueden retrasarse unos minutos en horas de mucha carga. Por eso cada corrida toma varias lecturas.
- Si el repo pasa 60 días sin actividad, GitHub puede pausar las tareas programadas y te avisa por correo. Se reactivan con un clic en la pestaña Actions.
- Si una notificación deja de llegar a un celular (por ejemplo, porque borraste la app), vuelve a activar las notificaciones en ese celular y actualiza su suscripción en el secreto.
