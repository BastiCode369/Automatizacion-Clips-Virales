#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from pathlib import Path
BASE_DIR = Path(__file__).resolve().parent

from dotenv import load_dotenv
load_dotenv(BASE_DIR / ".env")

import argparse
from datetime import datetime
import glob
import json
import os
import re
import shutil
import subprocess
import sys
import time
from typing import Any, Dict, List, NamedTuple, Optional

from google import genai
from google.genai import types
from google.genai.errors import APIError, ServerError
from pydantic import BaseModel, Field, TypeAdapter

from subir_shorts import (
    HISTORIAL_SUBIDAS_FILE,
    autenticar_youtube,
    cargar_historial_subidas,
    subir_short,
)

GEMINI_TIMEOUT_MS = 600_000  # google-genai HttpOptions.timeout usa milisegundos (600_000 ms = 600.0s)
MODELOS_CANDIDATOS = [
    "gemini-3.8-flash",
    "gemini-3.5-flash-lite",
    "gemini-3.1-pro-preview",
    "gemini-3.7-flash",
    "gemini-2.5-flash",
    "gemini-2.5-pro",
]
RUTA_MARCA_AGUA = BASE_DIR / "assets" / "watermark.png"
CARPETA_SALIDA = BASE_DIR / "clips_finales"
CARPETA_JOBS = BASE_DIR / "jobs"
FORMATOS_VIDEO_RAPIDOS = (
    "bestvideo[height<=1080][protocol!=m3u8_native][ext=mp4]+bestaudio[protocol!=m3u8_native][ext=m4a]/"
    "bestvideo[height<=1080][ext=mp4]+bestaudio[ext=m4a]/"
    "best[height<=1080][ext=mp4]/"
    "best[height<=1080]/best"
)


class JobContext(NamedTuple):
    job_id: str
    job_dir: Path


def crear_contexto_job(url: str) -> JobContext:
    """Genera un job_id único YYYYMMDD_HHMMSS_<slug_url> y crea su directorio en BASE_DIR / 'jobs'."""
    slug_limpio = re.sub(r"^https?://(?:www\.)?", "", url.strip())
    slug_limpio = re.sub(r"[^a-zA-Z0-9]+", "_", slug_limpio).strip("_")
    slug_url = slug_limpio[:30].strip("_") or "stream"
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    job_id = f"{timestamp}_{slug_url}"
    job_dir = CARPETA_JOBS / job_id
    job_dir.mkdir(parents=True, exist_ok=True)
    return JobContext(job_id=job_id, job_dir=job_dir)


class ClipViral(BaseModel):
    """Esquema estructurado de cada clip viral detectado por Gemini con SEO completo para YouTube Shorts."""

    id: int = Field(description="Identificador entero secuencial del clip (1, 2, 3...)")
    titulo: str = Field(
        description="Título magnético de alta tasa de clics (CTR), máximo 60 caracteres, en español coloquial/streamer."
    )
    inicio: str = Field(description="Timestamp exacto de inicio en formato HH:MM:SS")
    fin: str = Field(description="Timestamp exacto de fin en formato HH:MM:SS")
    gancho: str = Field(
        description="Primeras palabras textuales exactas del hook en los primeros 2 segundos"
    )
    razon_viral: str = Field(
        description="Explicación estratégica del gatillo de retención, polémica, tensión o clímax narrativo"
    )
    descripcion: str = Field(
        description="Resumen corto (2 líneas) con llamado a la acción (CTA) de suscripción y 3-5 hashtags estratégicos (ej. #Shorts #Kicksazos #StreamColombia)"
    )
    etiquetas: List[str] = Field(
        description="Lista de 8 a 12 tags SEO clave incluyendo nombres propios de involucrados y ecosistema streaming colombiano"
    )


def obtener_duracion_media(ruta_archivo: str | Path) -> Optional[float]:
    """Obtiene la duración en segundos de un archivo multimedia usando ffprobe."""
    try:
        res = subprocess.run(
            [
                "ffprobe",
                "-v",
                "error",
                "-show_entries",
                "format=duration",
                "-of",
                "default=noprint_wrappers=1:nokey=1",
                str(ruta_archivo),
            ],
            capture_output=True,
            text=True,
            check=True,
        )
        return float(res.stdout.strip())
    except Exception:
        return None


def segundos_a_hhmmss(segundos: float) -> str:
    """Convierte segundos a formato HH:MM:SS."""
    total = max(0, int(round(segundos)))
    horas, resto = divmod(total, 3600)
    minutos, segs = divmod(resto, 60)
    return f"{horas:02d}:{minutos:02d}:{segs:02d}"


def hhmmss_a_segundos(timestamp: str) -> float:
    """Convierte un timestamp HH:MM:SS o MM:SS a segundos."""
    limpio = str(timestamp).strip().split(".")[0]
    partes = [int(p) for p in limpio.split(":")]
    if len(partes) == 3:
        return partes[0] * 3600 + partes[1] * 60 + partes[2]
    if len(partes) == 2:
        return partes[0] * 60 + partes[1]
    if len(partes) == 1:
        return float(partes[0])
    raise ValueError(f"Formato de timestamp inválido: {timestamp}")


def _obtener_estado_archivo(archivo) -> str:
    estado = getattr(archivo, "state", None)
    if estado is None:
        return "STATE_UNSPECIFIED"
    return estado.name if hasattr(estado, "name") else str(estado)


def _normalizar_etiquetas(raw_tags: Any) -> List[str]:
    """Garantiza una lista limpia de entre 8 y 12 tags SEO."""
    base_defaults = [
        "Shorts",
        "Kicksazos",
        "StreamColombia",
        "KickColombia",
        "ClipsVirales",
        "IRLColombia",
        "StreamersColombianos",
        "PolémicaStream",
        "WestCOL",
        "YouTubeShorts",
    ]
    resultado: List[str] = []
    if isinstance(raw_tags, list):
        candidatos = raw_tags
    elif isinstance(raw_tags, str):
        candidatos = [t.strip() for t in re.split(r"[,;\n]+", raw_tags) if t.strip()]
    else:
        candidatos = []

    for tag in candidatos:
        limpio = str(tag).strip().lstrip("#")
        if limpio and limpio not in resultado:
            resultado.append(limpio)

    for defecto in base_defaults:
        if len(resultado) >= 8:
            break
        if defecto not in resultado:
            resultado.append(defecto)

    return resultado[:12]


def _limpiar_y_parsear_json(
    texto: str, duracion_total: Optional[float] = None
) -> List[dict]:
    """Limpia posibles bloques markdown y valida la respuesta mediante regex y esquema tipado estricto."""
    limpio = texto.strip()
    limpio = re.sub(r"^```(?:json)?\s*", "", limpio, flags=re.IGNORECASE)
    limpio = re.sub(r"\s*```$", "", limpio)
    limpio = limpio.strip()

    adapter = TypeAdapter(List[ClipViral])
    datos = None
    try:
        clips_objetos = adapter.validate_json(limpio)
        datos = [c.model_dump() for c in clips_objetos]
    except Exception:
        coincidencia = re.search(r"\[.*\]", limpio, flags=re.DOTALL)
        if coincidencia:
            bloque_json = coincidencia.group(0)
            try:
                clips_objetos = adapter.validate_json(bloque_json)
                datos = [c.model_dump() for c in clips_objetos]
            except Exception:
                datos = json.loads(bloque_json)
        else:
            datos = json.loads(limpio)

    if isinstance(datos, dict):
        datos = datos.get("clips", [])
    if not isinstance(datos, list) or not datos:
        raise ValueError("La respuesta JSON de Gemini no contiene una lista válida de clips.")

    clips_validos: List[dict] = []
    for idx, item in enumerate(datos, start=1):
        if not isinstance(item, dict):
            continue
        try:
            ini_s = hhmmss_a_segundos(item["inicio"])
            fin_s = hhmmss_a_segundos(item["fin"])
        except (KeyError, ValueError, TypeError):
            continue

        if duracion_total is not None:
            if ini_s >= duracion_total - 2:
                continue
            fin_s = min(fin_s, duracion_total)

        duracion_clip = fin_s - ini_s
        if duracion_clip < 5:
            continue

        titulo_raw = str(item.get("titulo") or f"Clip Viral #{idx}").strip()
        if len(titulo_raw) > 60:
            titulo_raw = titulo_raw[:57].rstrip() + "..."

        gancho_raw = str(item.get("gancho") or "").strip()
        razon_raw = str(item.get("razon_viral") or "").strip()

        desc_raw = str(item.get("descripcion") or "").strip()
        if not desc_raw:
            desc_raw = (
                f"{gancho_raw or titulo_raw}\n"
                "¡Suscríbete a Kicksazos para los mejores momentos del streaming colombiano! "
                "#Shorts #Kicksazos #StreamColombia #KickColombia"
            )
        elif "#shorts" not in desc_raw.lower():
            desc_raw = f"{desc_raw}\n#Shorts #Kicksazos #StreamColombia"

        etiquetas_norm = _normalizar_etiquetas(item.get("etiquetas"))

        clip_validado = ClipViral(
            id=len(clips_validos) + 1,
            titulo=titulo_raw,
            inicio=segundos_a_hhmmss(ini_s),
            fin=segundos_a_hhmmss(fin_s),
            gancho=gancho_raw,
            razon_viral=razon_raw,
            descripcion=desc_raw,
            etiquetas=etiquetas_norm,
        )
        clips_validos.append(
            {
                **clip_validado.model_dump(),
                "duracion_segundos": int(round(duracion_clip)),
            }
        )

    if not clips_validos:
        raise ValueError("Ningún clip del JSON superó la validación temporal.")
    return clips_validos


def extraer_audio(url: str, job_dir: Optional[Path | str] = None) -> str:
    """Descarga y convierte el audio del video fuente a MP3 ligero usando yt-dlp dentro de su job_dir."""
    print("\n[1/4] Extrayendo audio para análisis con IA...")
    directorio = Path(job_dir).resolve() if job_dir else BASE_DIR
    directorio.mkdir(parents=True, exist_ok=True)

    audio_salida = directorio / "temp_audio.mp3"
    patron_viejo = str(directorio / "temp_audio.*")
    for viejo in glob.glob(patron_viejo):
        try:
            os.remove(viejo)
        except OSError:
            pass

    salida_template = str(directorio / "temp_audio.%(ext)s")
    comando = [
        sys.executable,
        "-m",
        "yt_dlp",
        "--js-runtimes",
        "node",
        "--remote-components",
        "ejs:github",
        "--no-playlist",
        "--force-overwrites",
        "--concurrent-fragments",
        "4",
        "--retries",
        "5",
        "--fragment-retries",
        "5",
        "-f",
        "ba/b[height<=360]/b/worst",
        "-x",
        "--audio-format",
        "mp3",
        "--postprocessor-args",
        "ffmpeg:-ac 1 -ar 16000 -b:a 32k",
        "-o",
        salida_template,
        url,
    ]
    subprocess.run(comando, check=True)
    if not audio_salida.exists():
        raise FileNotFoundError(f"No se generó el archivo de audio esperado: {audio_salida}")
    return str(audio_salida.resolve())


def construir_prompt_viral(duracion_total: Optional[float] = None) -> str:
    """Construye el prompt especializado en retención de Shorts y ecosistema streaming colombiano."""
    info_duracion = (
        f"\nDURACIÓN TOTAL DEL AUDIO: {segundos_a_hhmmss(duracion_total)} (jamás generes timestamps superiores a este límite).\n"
        if duracion_total
        else ""
    )
    return f"""
Actúa como un Senior Growth Hacker, estratega de retención de algoritmo de YouTube Shorts / TikTok y editor experto en el ecosistema de IRL y streaming de Latinoamérica (específicamente Colombia).

Tu misión es analizar el audio adjunto y detectar los segmentos con mayor potencial de viralidad explosiva y retención (watch time > 100%).
{info_duracion}
### 1. MENTALIDAD DE INFERENCIA Y ALGORITMO DE SHORTS:
- **Hook Explosivo (Primeros 2 segundos):** El clip DEBE abrir de golpe en medio de una frase picante, confesión, grito, cifra escandalosa, pregunta incisiva o momento de alta tensión. Cero introducciones lentas ni saludos.
- **Ritmo Dinámico:** Evita segmentos con silencios muertos o divagaciones sin rumbo.
- **Arco Narrativo Completo:** Todo clip debe tener apertura fuerte (hook), desarrollo rápido, clímax narrativo y una resolución o remate contundente (punchline/reacción final).

### 2. CONTEXTO CULTURAL Y ECOSISTEMA STREAMING COLOMBIANO:
Presta máxima atención y prioriza cualquier mención directa, indirecta, tiradera o anécdota sobre:
- **Personalidades y Streamers:** WestCOL, Blessd (El Bendito), JH de la Cruz, MrStiven (Stiven Tangarife), Daiky Gamboa, La Liendra, Kris R, Ryan Castro, Pelicanger, Barbossa, Cossio, Aida Victoria, streamers de Kick/Twitch Colombia y escena urbana de Medellín, Cali y Bogotá.
- **Gatillos Virales de Alta Retención:**
  * Cifras de dinero, apuestas, deudas, compras o gastos extravagantes.
  * Discusiones en vivo, tiraderas, reclamos, filtraciones o peleas.
  * Confesiones íntimas, anécdotas callejeras, momentos incómodos en IRL o revelaciones personales.
  * Humor negro contextual, jerga colombiana auténtica (gonorrea, nea, parce, visaje, etc.) y opiniones controversiales sobre figuras públicas o eventos.

### 3. DURACIÓN DINÁMICA E INTELIGENTE (SIN CORTES RÍGIDOS):
- NO apliques una restricción rígida de corte fijo (nunca cortes a los 30s exactos si la historia sigue).
- La duración debe adaptarse de forma natural e inteligente a la unidad narrativa completa (típicamente entre **25 y 75 segundos**; o proporcional si el video fuente completo es un clip corto).
- Asegúrate de que el timestamp `inicio` abra exactamente en el gancho y el timestamp `fin` cierre después del remate, sin dejar palabras ni ideas cortadas a la mitad.

### 4. METADATOS SEO OBLIGATORIOS POR CADA CLIP:
Por cada clip seleccionado (extrae entre 3 y 6 de los mejores momentos, o los mejores disponibles según la longitud del audio), devuelve en el JSON:
- `id`: Entero secuencial (1, 2, 3...).
- `titulo`: Título magnético de alto CTR, **máximo 60 caracteres**, en español coloquial/streamer (usa mayúsculas estratégicas o emojis puntuales).
- `inicio`: Timestamp exacto `HH:MM:SS`.
- `fin`: Timestamp exacto `HH:MM:SS`.
- `gancho`: Transcripción textual de las primeras palabras que abren el clip.
- `razon_viral`: Explicación concisa del gatillo psicológico/viral y por qué retendrá a la audiencia.
- `descripcion`: Resumen corto de **2 líneas** que enganche al espectador + llamado a la acción (CTA) claro de suscripción al canal Kicksazos + 3 a 5 hashtags estratégicos (ej. `#Shorts #Kicksazos #StreamColombia #KickColombia`).
- `etiquetas`: Lista de **8 a 12 tags SEO** clave (incluyendo nombres propios de los involucrados, nicho IRL, streaming Colombia, etc.).

Devuelve EXCLUSIVAMENTE un arreglo JSON válido con esta estructura exacta:
[
  {{
    "id": 1,
    "titulo": " Título magnético máx 60 chars",
    "inicio": "HH:MM:SS",
    "fin": "HH:MM:SS",
    "gancho": "Primeras palabras textuales del hook",
    "razon_viral": "Explicación del gatillo de retención",
    "descripcion": "Línea 1 de contexto viral.\\nLínea 2 con CTA: ¡Suscríbete a Kicksazos para más clips! #Shorts #Kicksazos #StreamColombia #KickColombia",
    "etiquetas": ["Shorts", "Kicksazos", "StreamColombia", "WestCOL", "KickColombia", "IRLColombia", "ClipsVirales", "Polémica"]
  }}
]
"""


def _guardar_y_sincronizar_clips(clips: List[dict], job_dir: Optional[Path | str] = None):
    """Guarda clips.json en el job_dir (si aplica) y mantiene sincronizado BASE_DIR / 'clips.json'."""
    if job_dir:
        jdir = Path(job_dir).resolve()
        jdir.mkdir(parents=True, exist_ok=True)
        ruta_job_json = jdir / "clips.json"
        with open(ruta_job_json, "w", encoding="utf-8") as f:
            json.dump(clips, f, indent=2, ensure_ascii=False)

    ruta_raiz_json = BASE_DIR / "clips.json"
    with open(ruta_raiz_json, "w", encoding="utf-8") as f:
        json.dump(clips, f, indent=2, ensure_ascii=False)


def analizar_con_gemini(
    ruta_audio: str | Path,
    duracion_total: Optional[float] = None,
    modelo_preferido: Optional[str] = None,
    job_dir: Optional[Path | str] = None,
) -> List[dict]:
    """Sube el audio a Gemini File API, espera estado ACTIVE e infiere vía streaming con cascada de modelos."""
    print("\n[2/4] Subiendo audio a Gemini y ejecutando análisis viral con IA...")
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        print("[ERROR] Falta GEMINI_API_KEY.")
        sys.exit(1)

    client = genai.Client(
        api_key=api_key,
        http_options={"timeout": GEMINI_TIMEOUT_MS},
    )

    archivo_subido = None
    for intento_up in range(1, 5):
        try:
            archivo_subido = client.files.upload(file=str(ruta_audio))
            break
        except Exception as e:
            if intento_up == 4:
                raise
            print(f"[AVISO] Reintentando subida a File API ({intento_up}/4) tras error de red: {e}")
            time.sleep(3 * intento_up)

    try:
        estado = _obtener_estado_archivo(archivo_subido)
        print(f"Subido con ID {archivo_subido.name}. Estado inicial: {estado}. Esperando procesamiento...")
        intentos_estado = 0
        while estado != "ACTIVE":
            if estado == "FAILED":
                raise RuntimeError(f"Fallo al procesar archivo en Gemini: {estado}")
            intentos_estado += 1
            if intentos_estado > 150:
                raise TimeoutError("Tiempo de espera agotado esperando estado ACTIVE en File API.")
            time.sleep(4)
            try:
                archivo_subido = client.files.get(name=archivo_subido.name)
                estado = _obtener_estado_archivo(archivo_subido)
                print(f"Estado actual del archivo: {estado}")
            except Exception as e_get:
                print(f"[AVISO] Error transitorio consultando estado del archivo: {e_get}")
        print("✓ Archivo de audio listo y activo para inferencia.")

        prompt = construir_prompt_viral(duracion_total)

        orden_modelos = list(MODELOS_CANDIDATOS)
        if modelo_preferido and modelo_preferido.strip():
            pref = modelo_preferido.strip()
            orden_modelos = [pref] + [m for m in orden_modelos if m != pref]

        clips: Optional[List[dict]] = None
        modelo_usado: Optional[str] = None

        for modelo in orden_modelos:
            print(f"Probando análisis en streaming con: {modelo}...")
            for intento in range(1, 3):
                try:
                    partes_texto: List[str] = []
                    stream = client.models.generate_content_stream(
                        model=modelo,
                        contents=[archivo_subido, prompt],
                        config=types.GenerateContentConfig(
                            response_mime_type="application/json",
                            response_schema=list[ClipViral],
                            temperature=0.35,
                        ),
                    )
                    for chunk in stream:
                        if getattr(chunk, "text", None):
                            partes_texto.append(chunk.text)

                    texto_respuesta = "".join(partes_texto).strip()
                    if not texto_respuesta:
                        raise ValueError("Respuesta vacía recibida desde el stream de Gemini.")

                    clips = _limpiar_y_parsear_json(texto_respuesta, duracion_total=duracion_total)
                    modelo_usado = modelo
                    print(f"✓ Análisis generado con éxito usando {modelo}")
                    break
                except ServerError as e:
                    print(f"Servidor ocupado (503) en intento {intento}/2 con {modelo}: {e}")
                    time.sleep(5)
                except APIError as e:
                    if e.code in (400, 404):
                        print(f"Modelo {modelo} no disponible ({e.code}): {e.message}")
                        break
                    if e.code in (429, 503):
                        print(f"Límite temporal ({e.code}) en intento {intento}/2 con {modelo}. Esperando 5s...")
                        time.sleep(5)
                    else:
                        print(f"Error de API con {modelo}: {e}")
                        break
                except Exception as e:
                    print(f"Aviso en intento {intento}/2 con {modelo}: {e}")
                    time.sleep(2)
            if clips:
                break

        if not clips:
            raise RuntimeError("No se pudo obtener una respuesta JSON válida de los modelos disponibles.")

        for c in clips:
            c["modelo_ia"] = modelo_usado

        _guardar_y_sincronizar_clips(clips, job_dir=job_dir)
        print(f"✓ Se detectaron {len(clips)} momentos virales con SEO completo y se guardaron en clips.json")
        return clips
    finally:
        try:
            client.files.delete(name=archivo_subido.name)
        except Exception:
            pass


def descargar_video_fuente(url: str, destino: Optional[Path | str] = None) -> str:
    """Descarga el video fuente completo una sola vez priorizando MP4 directo (sin HLS lento)."""
    ruta_destino = Path(destino).resolve() if destino else BASE_DIR / "temp_source.mp4"
    if ruta_destino.exists():
        ruta_destino.unlink()

    print("Descargando video fuente en 1080p para corte rápido local...")
    comando = [
        sys.executable,
        "-m",
        "yt_dlp",
        "--js-runtimes",
        "node",
        "--remote-components",
        "ejs:github",
        "--no-playlist",
        "--force-overwrites",
        "-f",
        FORMATOS_VIDEO_RAPIDOS,
        "--merge-output-format",
        "mp4",
        "-o",
        str(ruta_destino),
        url,
    ]
    subprocess.run(comando, check=True)
    if not ruta_destino.exists():
        raise FileNotFoundError(f"No se generó el video fuente: {ruta_destino}")
    return str(ruta_destino)


def obtener_urls_stream(url: str) -> List[str]:
    """Obtiene URLs directas del stream con yt-dlp -g para seek remoto sin descarga completa."""
    comando = [
        sys.executable,
        "-m",
        "yt_dlp",
        "--js-runtimes",
        "node",
        "--remote-components",
        "ejs:github",
        "--no-playlist",
        "-f",
        FORMATOS_VIDEO_RAPIDOS,
        "-g",
        url,
    ]
    res = subprocess.run(comando, capture_output=True, text=True, check=True)
    urls = [linea.strip() for linea in res.stdout.splitlines() if linea.strip()]
    if not urls:
        raise RuntimeError("yt-dlp no devolvió URLs de stream válidas.")
    return urls[:2]


def procesar_clip_ffmpeg(
    url_o_archivo: str,
    inicio: str,
    fin: str,
    id_clip: str | int,
    job_id: Optional[str] = None,
) -> str:
    """Extrae el clip con input seek (-ss/-to antes de -i) y renderiza 9:16 optimizado."""
    if not RUTA_MARCA_AGUA.exists():
        raise FileNotFoundError(f"No se encontró la marca de agua en {RUTA_MARCA_AGUA}")

    CARPETA_SALIDA.mkdir(parents=True, exist_ok=True)
    nombre_clip = f"{job_id}_clip_{id_clip}.mp4" if job_id else f"clip_{id_clip}.mp4"
    archivo_salida = CARPETA_SALIDA / nombre_clip

    print(f"\n--- Procesando Clip {id_clip} ({inicio} -> {fin}) [Salida: {nombre_clip}] ---")

    if os.path.exists(url_o_archivo):
        entradas_media = [str(Path(url_o_archivo).resolve())]
        es_remoto = False
    else:
        entradas_media = obtener_urls_stream(url_o_archivo)
        es_remoto = True

    comando_ffmpeg = ["ffmpeg", "-hide_banner", "-stats", "-y"]
    for media in entradas_media:
        if es_remoto:
            comando_ffmpeg.extend(
                [
                    "-rw_timeout",
                    "15000000",
                    "-reconnect",
                    "1",
                    "-reconnect_streamed",
                    "1",
                    "-reconnect_delay_max",
                    "5",
                ]
            )
        comando_ffmpeg.extend(["-ss", inicio, "-to", fin, "-i", media])

    idx_watermark = len(entradas_media)
    idx_audio = "1:a?" if len(entradas_media) > 1 else "0:a?"
    comando_ffmpeg.extend(["-i", str(RUTA_MARCA_AGUA)])

    filtro = (
        "[0:v]split=2[bg][fg];"
        "[bg]scale=360:640:force_original_aspect_ratio=increase,crop=360:640,setsar=1,boxblur=10:2,scale=1080:1920:flags=bilinear[bg_blur];"
        "[fg]scale=1080:1920:force_original_aspect_ratio=decrease,setsar=1[fg_scaled];"
        "[bg_blur][fg_scaled]overlay=(W-w)/2:(H-h)/2[vid_comp];"
        f"[{idx_watermark}:v]scale=420:-1,format=rgba,colorchannelmixer=aa=0.92[wm];"
        "[vid_comp][wm]overlay=(W-w)/2:520,format=yuv420p[outv]"
    )

    comando_ffmpeg.extend(
        [
            "-filter_complex",
            filtro,
            "-map",
            "[outv]",
            "-map",
            idx_audio,
            "-c:v",
            "libx264",
            "-preset",
            "veryfast",
            "-crf",
            "22",
            "-threads",
            "0",
            "-c:a",
            "aac",
            "-b:a",
            "128k",
            "-movflags",
            "+faststart",
            str(archivo_salida),
        ]
    )

    print("Renderizando composición vertical 9:16 con FFmpeg...")
    subprocess.run(comando_ffmpeg, check=True)
    print(f"✓ Clip {id_clip} guardado con éxito en: {archivo_salida}")
    return str(archivo_salida.resolve())


def renderizar_y_subir_clips(
    url: str,
    clips: List[dict],
    duracion_total: Optional[float] = None,
    subir_youtube: bool = True,
    job_id: Optional[str] = None,
    job_dir: Optional[Path | str] = None,
) -> List[str]:
    """Renderiza en 9:16 todos los clips detectados y los sube automáticamente a YouTube Shorts en privado."""
    print("\n[3/4] Renderizando clips con formato 9:16 y marca de agua @Kicksazos...")
    fuente_local = None
    youtube_client = None

    if subir_youtube:
        print("\n[4/4] Preparando cliente de YouTube Data API v3 para subida automática en privado...")
        try:
            youtube_client = autenticar_youtube(interactivo=False)
            print("✓ Cliente de YouTube autenticado correctamente.")
        except Exception as e:
            print(
                f"[AVISO] No se pudo inicializar YouTube Data API ({e}). "
                "Los clips se renderizarán localmente sin interrumpir el flujo."
            )
            youtube_client = None

    try:
        # Para videos <= 1h descargar una sola vez evita múltiples conexiones HTTP/HLS lentas
        if duracion_total is None or duracion_total <= 3600:
            try:
                destino_fuente = (
                    Path(job_dir) / "temp_source.mp4"
                    if job_dir
                    else BASE_DIR / "temp_source.mp4"
                )
                fuente_local = descargar_video_fuente(url, destino=destino_fuente)
            except Exception as e:
                print(f"[AVISO] Descarga local completa omitida ({e}); usando seek directo en stream...")
                fuente_local = None

        entrada_render = fuente_local or url
        salidas = []
        for clip in clips:
            cid = str(clip.get("id"))
            inicio = clip.get("inicio")
            fin = clip.get("fin")
            salida = procesar_clip_ffmpeg(
                entrada_render, inicio, fin, cid, job_id=job_id
            )
            salidas.append(salida)
            clip["archivo_local"] = salida

            if subir_youtube and youtube_client is not None:
                try:
                    info_yt = subir_short(
                        youtube=youtube_client,
                        ruta_video=salida,
                        titulo=clip.get("titulo", f"Clip {cid}"),
                        descripcion=clip.get("descripcion", ""),
                        etiquetas=clip.get("etiquetas", []),
                        privacidad="private",
                        clip_id=clip.get("id"),
                        guardar_registro=True,
                    )
                    clip["youtube_id"] = info_yt["youtube_id"]
                    clip["youtube_url"] = info_yt["url"]
                    clip["youtube_status"] = "Subido (Privado)"
                except Exception as e:
                    print(f"[AVISO] Error al subir {os.path.basename(salida)} a YouTube: {e}")
                    clip["youtube_status"] = f"No subido ({str(e)[:80]})"
            elif not subir_youtube:
                clip["youtube_status"] = "Subida omitida (--sin-subida)"
            else:
                clip["youtube_status"] = "Pendiente de subida (Sin credenciales activas)"

        _guardar_y_sincronizar_clips(clips, job_dir=job_dir)
        return salidas
    finally:
        if fuente_local and os.path.exists(fuente_local):
            try:
                os.remove(fuente_local)
            except OSError:
                pass


def renderizar_clips(
    url: str,
    clips: List[dict],
    duracion_total: Optional[float] = None,
    job_id: Optional[str] = None,
    job_dir: Optional[Path | str] = None,
) -> List[str]:
    """Alias compatible hacia atrás que renderiza y sube los clips."""
    return renderizar_y_subir_clips(
        url=url,
        clips=clips,
        duracion_total=duracion_total,
        subir_youtube=True,
        job_id=job_id,
        job_dir=job_dir,
    )


def main():
    parser = argparse.ArgumentParser(
        description="Pipeline de automatización de clips virales Kicksazos"
    )
    parser.add_argument("url", help="URL del video o stream fuente")
    parser.add_argument(
        "--solo-analisis",
        action="store_true",
        help="Solo genera clips.json sin renderizar los videos finales",
    )
    parser.add_argument(
        "--sin-subida",
        action="store_true",
        help="Renderiza los clips localmente sin subirlos a YouTube",
    )
    parser.add_argument(
        "--modelo",
        default=None,
        help="Modelo Gemini preferido para iniciar la cascada de inferencia",
    )
    args = parser.parse_args()

    ctx = crear_contexto_job(args.url)
    print(f"Iniciando Job {ctx.job_id} en {ctx.job_dir}")

    audio = extraer_audio(args.url, job_dir=ctx.job_dir)
    try:
        duracion = obtener_duracion_media(audio)
        clips = analizar_con_gemini(
            audio,
            duracion_total=duracion,
            modelo_preferido=args.modelo,
            job_dir=ctx.job_dir,
        )
        if not args.solo_analisis:
            renderizar_y_subir_clips(
                args.url,
                clips,
                duracion_total=duracion,
                subir_youtube=not args.sin_subida,
                job_id=ctx.job_id,
                job_dir=ctx.job_dir,
            )
    finally:
        if os.path.exists(audio):
            try:
                os.remove(audio)
            except OSError:
                pass

    print(f"\n✓ ¡Pipeline completado con éxito para job {ctx.job_id}!")
    print(f"Revisa {CARPETA_SALIDA}, {ctx.job_dir} y {HISTORIAL_SUBIDAS_FILE}")


if __name__ == "__main__":
    main()
