#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from pathlib import Path
BASE_DIR = Path(__file__).resolve().parent

from dotenv import load_dotenv
load_dotenv(BASE_DIR / ".env")

import argparse
from datetime import datetime, timedelta, timezone
import glob
import json
import os
import random
import re
import shutil
import subprocess
import sys
import time
from typing import Any, Callable, Dict, Generator, List, NamedTuple, Optional, Tuple

from google import genai
from google.genai import types
from google.genai.errors import APIError, ServerError
from pydantic import BaseModel, Field, TypeAdapter

from subir_shorts import (
    HISTORIAL_SUBIDAS_FILE,
    autenticar_youtube,
    cargar_historial_subidas,
    subir_short,
    verificar_cuota_diaria,
)

GEMINI_TIMEOUT_MS = 600_000  # google-genai HttpOptions.timeout usa milisegundos (600_000 ms = 600.0s)
ZONA_HORARIA_LOCAL = timezone(timedelta(hours=-5))  # Hora local Colombia (-05:00)
LIMITE_CUOTA_DIARIA_SHORTS = 6
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
VAAPI_DEVICE = "/dev/dri/renderD128"
FORMATOS_AUDIO_DIRECTO = "ba/worst[height<=360]/worst/b[height<=360]/b"
FORMATOS_VIDEO_RAPIDOS = (
    "bestvideo[height<=1080][protocol!=m3u8_native][ext=mp4]+bestaudio[protocol!=m3u8_native][ext=m4a]/"
    "bestvideo[height<=1080][ext=mp4]+bestaudio[ext=m4a]/"
    "best[height<=1080][ext=mp4]/"
    "best[height<=1080]/best"
)


class JobContext(NamedTuple):
    job_id: str
    job_dir: Path


class StreamUrlCache:
    """Caché en memoria por job_id para URLs directas de stream (video_url, audio_url) y dimensiones."""

    def __init__(self) -> None:
        self._entries: Dict[str, Dict[str, Any]] = {}

    def obtener(self, job_id: str, url: str) -> Optional[Dict[str, Any]]:
        entrada = self._entries.get(job_id)
        if not entrada or entrada.get("source_url") != url:
            return None
        return entrada

    def guardar(
        self,
        job_id: str,
        url: str,
        urls: List[str],
        dimensiones: Optional[Tuple[int, int]] = None,
    ) -> Dict[str, Any]:
        video_url = urls[0] if len(urls) >= 1 else None
        audio_url = urls[1] if len(urls) >= 2 else None
        registro = {
            "source_url": url,
            "video_url": video_url,
            "audio_url": audio_url,
            "dimensiones": dimensiones,
        }
        self._entries[job_id] = registro
        return registro

    def actualizar_dimensiones(
        self, job_id: str, url: str, dimensiones: Optional[Tuple[int, int]]
    ) -> None:
        entrada = self.obtener(job_id, url)
        if entrada is not None:
            entrada["dimensiones"] = dimensiones

    def invalidar(self, job_id: Optional[str] = None) -> None:
        if job_id is None:
            self._entries.clear()
        else:
            self._entries.pop(job_id, None)


STREAM_URL_CACHE = StreamUrlCache()


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


class SegmentoSubtitulo(BaseModel):
    """Segmento individual de subtítulo dinámico sincronizado relativo al inicio del clip."""

    inicio_rel: float = Field(
        description="Segundo de inicio relativo al comienzo del clip (ej. 0.0)."
    )
    fin_rel: float = Field(
        description="Segundo de fin relativo al comienzo del clip (ej. 2.1)."
    )
    texto: str = Field(
        description="Frase corta y contundente de máximo 4 a 6 palabras."
    )


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
    subtitulos: List[SegmentoSubtitulo] = Field(
        default_factory=list,
        description="Frases clave cortas (máximo 4-6 palabras) sincronizadas en segundos relativos desde 0.0 hasta la duración del clip.",
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
    """Convierte un timestamp HH:MM:SS, MM:SS o SS (con decimales opcionales) a segundos."""
    limpio = str(timestamp).strip()
    trozos = limpio.split(":")
    if len(trozos) == 3:
        return int(trozos[0]) * 3600 + int(trozos[1]) * 60 + float(trozos[2])
    if len(trozos) == 2:
        return int(trozos[0]) * 60 + float(trozos[1])
    if len(trozos) == 1:
        return float(trozos[0])
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


def _normalizar_subtitulos(
    raw_subs: Any, duracion_clip: float
) -> List[SegmentoSubtitulo]:
    """Limpia, valida y ordena segmentos de subtítulos relativos dentro de [0, duracion_clip]."""
    if not isinstance(raw_subs, list) or duracion_clip <= 0:
        return []

    candidatos: List[SegmentoSubtitulo] = []
    for seg in raw_subs:
        if isinstance(seg, SegmentoSubtitulo):
            ini_raw, fin_raw, txt_raw = seg.inicio_rel, seg.fin_rel, seg.texto
        elif isinstance(seg, dict):
            ini_raw = seg.get("inicio_rel")
            fin_raw = seg.get("fin_rel")
            txt_raw = seg.get("texto")
        else:
            continue

        try:
            ini = max(0.0, float(ini_raw))
            fin = min(float(duracion_clip), float(fin_raw))
        except (TypeError, ValueError):
            continue

        texto = re.sub(r"\s+", " ", str(txt_raw or "")).strip()
        if not texto or ini >= duracion_clip or fin <= ini + 0.05:
            continue

        candidatos.append(
            SegmentoSubtitulo(
                inicio_rel=round(ini, 2),
                fin_rel=round(fin, 2),
                texto=texto,
            )
        )

    candidatos.sort(key=lambda s: (s.inicio_rel, s.fin_rel))

    sin_solape: List[SegmentoSubtitulo] = []
    for seg in candidatos:
        if sin_solape and seg.inicio_rel < sin_solape[-1].fin_rel:
            prev = sin_solape[-1]
            nuevo_fin_prev = round(seg.inicio_rel, 2)
            if nuevo_fin_prev >= prev.inicio_rel + 0.05:
                sin_solape[-1] = SegmentoSubtitulo(
                    inicio_rel=prev.inicio_rel,
                    fin_rel=nuevo_fin_prev,
                    texto=prev.texto,
                )
            else:
                # Si el segmento anterior queda demasiado corto, ajusta inicio del nuevo
                nuevo_ini = round(prev.fin_rel, 2)
                if seg.fin_rel <= nuevo_ini + 0.05:
                    continue
                seg = SegmentoSubtitulo(
                    inicio_rel=nuevo_ini,
                    fin_rel=seg.fin_rel,
                    texto=seg.texto,
                )
        sin_solape.append(seg)

    return sin_solape


def _segundos_a_ass_time(segundos: float) -> str:
    """Convierte segundos decimales al formato ASS H:MM:SS.cc (centisegundos)."""
    total_cs = max(0, int(round(float(segundos) * 100)))
    cs = total_cs % 100
    total_s = total_cs // 100
    s = total_s % 60
    total_m = total_s // 60
    m = total_m % 60
    h = total_m // 60
    return f"{h}:{m:02d}:{s:02d}.{cs:02d}"


def _limpiar_texto_ass(texto: str) -> str:
    """Normaliza texto para eventos Dialogue ASS evitando llaves, saltos crudos y emojis sin glifo."""
    limpio = re.sub(r"[\U00010000-\U0010FFFF\u2600-\u27BF\uFE0F\u200D]+", "", str(texto or ""))
    limpio = re.sub(r"\s+", " ", limpio).strip()
    limpio = re.sub(r"\r\n|\r|\n", r"\\N", limpio)
    limpio = limpio.replace("{", "(").replace("}", ")")
    return limpio


def generar_archivo_ass(
    subtitulos: List[Any],
    ruta_ass: str | Path,
) -> str:
    """Genera un archivo .ass estilizado para YouTube Shorts (1080x1920) y devuelve su ruta absoluta."""
    ruta = Path(ruta_ass).resolve()
    ruta.parent.mkdir(parents=True, exist_ok=True)

    encabezado = "\n".join(
        [
            "[Script Info]",
            "Title: Kicksazos Shorts Subtitles",
            "ScriptType: v4.00+",
            "WrapStyle: 0",
            "ScaledBorderAndShadow: yes",
            "YCbCr Matrix: TV.709",
            "PlayResX: 1080",
            "PlayResY: 1920",
            "",
            "[V4+ Styles]",
            "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding",
            "Style: Default,DejaVu Sans,58,&H00FFFFFF,&H0000FFFF,&H00000000,&H80000000,-1,0,0,0,100,100,0,0,1,4,2,2,60,60,480,1",
            "",
            "[Events]",
            "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text",
        ]
    )

    lineas_eventos: List[str] = []
    for seg in subtitulos or []:
        if isinstance(seg, SegmentoSubtitulo):
            ini_raw, fin_raw, txt_raw = seg.inicio_rel, seg.fin_rel, seg.texto
        elif isinstance(seg, dict):
            ini_raw = seg.get("inicio_rel")
            fin_raw = seg.get("fin_rel")
            txt_raw = seg.get("texto")
        else:
            continue

        try:
            ini = max(0.0, float(ini_raw))
            fin = float(fin_raw)
        except (TypeError, ValueError):
            continue

        texto_ass = _limpiar_texto_ass(str(txt_raw or ""))
        if not texto_ass or fin <= ini + 0.02:
            continue

        t_ini = _segundos_a_ass_time(ini)
        t_fin = _segundos_a_ass_time(fin)
        lineas_eventos.append(
            f"Dialogue: 0,{t_ini},{t_fin},Default,,0,0,0,,{texto_ass}"
        )

    contenido = encabezado + ("\n" + "\n".join(lineas_eventos) if lineas_eventos else "") + "\n"
    ruta.write_text(contenido, encoding="utf-8")
    return str(ruta)


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
        subtitulos_norm = _normalizar_subtitulos(item.get("subtitulos"), duracion_clip)

        clip_validado = ClipViral(
            id=len(clips_validos) + 1,
            titulo=titulo_raw,
            inicio=segundos_a_hhmmss(ini_s),
            fin=segundos_a_hhmmss(fin_s),
            gancho=gancho_raw,
            razon_viral=razon_raw,
            descripcion=desc_raw,
            etiquetas=etiquetas_norm,
            subtitulos=subtitulos_norm,
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


def _obtener_url_audio_directo(url: str) -> str:
    """Obtiene vía yt-dlp -g la URL directa de audio-only o la variante de menor resolución."""
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
        FORMATOS_AUDIO_DIRECTO,
        "-g",
        url,
    ]
    res = subprocess.run(comando, capture_output=True, text=True, check=True)
    urls = [linea.strip() for linea in res.stdout.splitlines() if linea.strip()]
    if not urls:
        raise RuntimeError("yt-dlp -g no devolvió URL directa para extracción de audio.")
    return urls[0]


def extraer_audio(url: str, job_dir: Optional[Path | str] = None) -> str:
    """Extrae audio mono 16kHz/32k directo desde stream HLS/remoto con FFmpeg y usa yt-dlp como fallback."""
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

    # Intento rápido: extraer audio directo desde la URL del manifiesto con FFmpeg (sin bajar video completo)
    try:
        print("Consultando URL directa de audio/menor resolución con yt-dlp -g...")
        stream_url = _obtener_url_audio_directo(url)
        comando_ffmpeg = ["ffmpeg", "-hide_banner", "-loglevel", "warning", "-stats", "-y"]
        if stream_url.startswith(("http://", "https://")):
            comando_ffmpeg.extend(
                [
                    "-reconnect",
                    "1",
                    "-reconnect_streamed",
                    "1",
                    "-reconnect_delay_max",
                    "5",
                    "-rw_timeout",
                    "15000000",
                ]
            )
        comando_ffmpeg.extend(
            [
                "-i",
                stream_url,
                "-vn",
                "-ac",
                "1",
                "-ar",
                "16000",
                "-b:a",
                "32k",
                str(audio_salida),
            ]
        )
        print("Extrayendo pista de audio directa por streaming con FFmpeg...")
        subprocess.run(comando_ffmpeg, check=True)
        if audio_salida.exists() and audio_salida.stat().st_size > 0:
            return str(audio_salida.resolve())
        raise RuntimeError("FFmpeg finalizó sin generar un temp_audio.mp3 válido.")
    except Exception as e:
        print(
            f"[AVISO] Extracción directa con FFmpeg falló ({e}); "
            "activando fallback automático con descarga yt-dlp..."
        )
        if audio_salida.exists():
            try:
                audio_salida.unlink()
            except OSError:
                pass

    # Fallback automático con descarga tradicional de yt-dlp
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

### 4. METADATOS SEO Y SUBTÍTULOS DINÁMICOS OBLIGATORIOS POR CLIP:
Por cada clip seleccionado (extrae entre 3 y 6 de los mejores momentos, o los mejores disponibles según la longitud del audio), devuelve en el JSON:
- `id`: Entero secuencial (1, 2, 3...).
- `titulo`: Título magnético de alto CTR, **máximo 60 caracteres**, en español coloquial/streamer (usa mayúsculas estratégicas o emojis puntuales).
- `inicio`: Timestamp exacto `HH:MM:SS`.
- `fin`: Timestamp exacto `HH:MM:SS`.
- `gancho`: Transcripción textual de las primeras palabras que abren el clip.
- `razon_viral`: Explicación concisa del gatillo psicológico/viral y por qué retendrá a la audiencia.
- `descripcion`: Resumen corto de **2 líneas** que enganche al espectador + llamado a la acción (CTA) claro de suscripción al canal Kicksazos + 3 a 5 hashtags estratégicos (ej. `#Shorts #Kicksazos #StreamColombia #KickColombia`).
- `etiquetas`: Lista de **8 a 12 tags SEO** clave (incluyendo nombres propios de los involucrados, nicho IRL, streaming Colombia, etc.).
- `subtitulos`: Lista cronológica de frases cortas e impactantes (máximo **4 a 6 palabras** por segmento, texto limpio sin emojis) transcribiendo fielmente lo hablado en el clip, sincronizadas en segundos relativos (`inicio_rel`, `fin_rel` como decimales desde `0.0` hasta la duración exacta `fin - inicio`), sin solaparse entre sí.

Devuelve EXCLUSIVAMENTE un arreglo JSON válido con esta estructura exacta:
[
  {{
    "id": 1,
    "titulo": "Título magnético máx 60 chars",
    "inicio": "HH:MM:SS",
    "fin": "HH:MM:SS",
    "gancho": "Primeras palabras textuales del hook",
    "razon_viral": "Explicación del gatillo de retención",
    "descripcion": "Línea 1 de contexto viral.\\nLínea 2 con CTA: ¡Suscríbete a Kicksazos para más clips! #Shorts #Kicksazos #StreamColombia #KickColombia",
    "etiquetas": ["Shorts", "Kicksazos", "StreamColombia", "WestCOL", "KickColombia", "IRLColombia", "ClipsVirales", "Polémica"],
    "subtitulos": [
      {{"inicio_rel": 0.0, "fin_rel": 1.8, "texto": "¡NO PUEDE SER ESTO!"}},
      {{"inicio_rel": 1.9, "fin_rel": 4.2, "texto": "Mira lo que dijo en vivo"}}
    ]
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


def _esperar_con_jitter(
    intento: int,
    base: float = 3.0,
    max_espera: float = 30.0,
    on_log: Optional[Callable[[str], None]] = None,
    contexto: str = "",
) -> float:
    """Ejecuta backoff exponencial con jitter aleatorio usando random.uniform y retorna los segundos esperados."""
    techo = min(max_espera, base * (2 ** max(0, intento - 1)))
    piso = min(techo, max(0.5, techo * 0.5))
    espera = round(random.uniform(piso, techo), 2)
    if contexto:
        msg = f"{contexto} | Espera: {espera:.2f}s"
        if on_log is not None:
            on_log(msg)
        else:
            print(msg)
    time.sleep(espera)
    return espera


def analizar_con_gemini(
    ruta_audio: str | Path,
    duracion_total: Optional[float] = None,
    modelo_preferido: Optional[str] = None,
    job_dir: Optional[Path | str] = None,
    on_log: Optional[Callable[[str], None]] = None,
) -> List[dict]:
    """Sube el audio a Gemini File API, espera estado ACTIVE e infiere vía streaming con cascada de modelos."""
    def _log(msg: str) -> None:
        if on_log is not None:
            on_log(msg)
        else:
            print(msg)

    _log("\n[2/4] Subiendo audio a Gemini y ejecutando análisis viral con IA...")
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        raise RuntimeError("Falta la variable de entorno GEMINI_API_KEY.")

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
            _esperar_con_jitter(
                intento_up,
                base=3.0,
                max_espera=30.0,
                on_log=on_log,
                contexto=(
                    f"[AVISO] Error de red subiendo audio a File API ({type(e).__name__}, "
                    f"intento {intento_up}/4) antes de reintentar: {e}"
                ),
            )

    try:
        estado = _obtener_estado_archivo(archivo_subido)
        _log(f"Subido con ID {archivo_subido.name}. Estado inicial: {estado}. Esperando procesamiento...")
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
                _log(f"Estado actual del archivo: {estado}")
            except Exception as e_get:
                _log(f"[AVISO] Error transitorio consultando estado del archivo: {e_get}")
        _log("✓ Archivo de audio listo y activo para inferencia.")

        prompt = construir_prompt_viral(duracion_total)

        orden_modelos = list(MODELOS_CANDIDATOS)
        if modelo_preferido and modelo_preferido.strip():
            pref = modelo_preferido.strip()
            orden_modelos = [pref] + [m for m in orden_modelos if m != pref]

        clips: Optional[List[dict]] = None
        modelo_usado: Optional[str] = None
        max_intentos = 2

        for modelo in orden_modelos:
            _log(f"Probando análisis en streaming con: {modelo}...")
            for intento in range(1, max_intentos + 1):
                accion_siguiente = (
                    "reintentar" if intento < max_intentos else "saltar al siguiente modelo"
                )
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
                    _log(f"✓ Análisis generado con éxito usando {modelo}")
                    break
                except ServerError as e:
                    codigo_err = getattr(e, "code", None) or 503
                    _esperar_con_jitter(
                        intento,
                        base=3.0,
                        max_espera=30.0,
                        on_log=on_log,
                        contexto=(
                            f"[AVISO] Modelo {modelo} falló (código {codigo_err}, "
                            f"intento {intento}/{max_intentos}) antes de {accion_siguiente}: {e}"
                        ),
                    )
                except APIError as e:
                    codigo_err = getattr(e, "code", None) or "APIError"
                    detalle_err = getattr(e, "message", None) or str(e)
                    if codigo_err in (400, 404):
                        _log(
                            f"[AVISO] Modelo {modelo} falló (código {codigo_err}, espera 0.00s "
                            f"antes de saltar al siguiente modelo): {detalle_err}"
                        )
                        break
                    if codigo_err in (429, 503):
                        _esperar_con_jitter(
                            intento,
                            base=3.0,
                            max_espera=30.0,
                            on_log=on_log,
                            contexto=(
                                f"[AVISO] Modelo {modelo} falló (código {codigo_err}, "
                                f"intento {intento}/{max_intentos}) antes de {accion_siguiente}: {detalle_err}"
                            ),
                        )
                    else:
                        _log(
                            f"[AVISO] Modelo {modelo} falló (código {codigo_err}, espera 0.00s "
                            f"antes de saltar al siguiente modelo): {detalle_err}"
                        )
                        break
                except Exception as e:
                    codigo_err = type(e).__name__
                    _esperar_con_jitter(
                        intento,
                        base=2.0,
                        max_espera=15.0,
                        on_log=on_log,
                        contexto=(
                            f"[AVISO] Modelo {modelo} falló (error {codigo_err}, "
                            f"intento {intento}/{max_intentos}) antes de {accion_siguiente}: {e}"
                        ),
                    )
            if clips:
                break

        if not clips:
            raise RuntimeError("No se pudo obtener una respuesta JSON válida de los modelos disponibles.")

        for c in clips:
            c["modelo_ia"] = modelo_usado

        _guardar_y_sincronizar_clips(clips, job_dir=job_dir)
        _log(f"✓ Se detectaron {len(clips)} momentos virales con SEO completo y se guardaron en clips.json")
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


def obtener_urls_stream(
    url: str,
    job_id: Optional[str] = None,
    forzar_recarga: bool = False,
) -> List[str]:
    """Obtiene URLs directas del stream con yt-dlp -g usando caché en memoria por job_id."""
    clave_cache = job_id or f"anon:{url}"
    if not forzar_recarga:
        entrada = STREAM_URL_CACHE.obtener(clave_cache, url)
        if entrada:
            urls_cacheadas = [
                u for u in (entrada.get("video_url"), entrada.get("audio_url")) if u
            ]
            if urls_cacheadas:
                print(f"Usando URLs de stream en caché para job '{clave_cache}'.")
                return urls_cacheadas

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
    urls_finales = urls[:2]
    STREAM_URL_CACHE.guardar(clave_cache, url, urls_finales)
    return urls_finales


def detectar_encoder_hardware(device_path: str = VAAPI_DEVICE) -> str:
    """Verifica /dev/dri/renderD128 y prueba codificación nula de 1 frame con h264_vaapi; retorna 'h264_vaapi' o 'libx264'."""
    try:
        if not Path(device_path).exists():
            return "libx264"
        comando = [
            "ffmpeg",
            "-hide_banner",
            "-loglevel",
            "error",
            "-vaapi_device",
            device_path,
            "-f",
            "lavfi",
            "-i",
            "color=c=black:s=256x256:d=0.1",
            "-vf",
            "format=nv12,hwupload",
            "-frames:v",
            "1",
            "-c:v",
            "h264_vaapi",
            "-qp",
            "23",
            "-f",
            "null",
            "-",
        ]
        res = subprocess.run(comando, capture_output=True, text=True, timeout=10)
        if res.returncode == 0:
            return "h264_vaapi"
    except Exception:
        pass
    return "libx264"


def obtener_dimensiones_video(fuente: str) -> Optional[Tuple[int, int]]:
    """Obtiene (ancho, alto) efectivos del stream de video usando ffprobe."""
    comando = [
        "ffprobe",
        "-v",
        "error",
        "-select_streams",
        "v:0",
        "-show_entries",
        "stream=width,height,sample_aspect_ratio:stream_side_data=rotation",
        "-of",
        "json",
    ]
    if fuente.startswith(("http://", "https://")):
        comando.extend(["-rw_timeout", "10000000"])
    comando.append(fuente)

    try:
        res = subprocess.run(comando, capture_output=True, text=True, check=True, timeout=15)
        data = json.loads(res.stdout or "{}")
        streams = data.get("streams") or []
        if not streams:
            return None
        stream = streams[0]
        w = int(stream.get("width") or 0)
        h = int(stream.get("height") or 0)
        if w <= 0 or h <= 0:
            return None

        sar = str(stream.get("sample_aspect_ratio") or "")
        if ":" in sar:
            try:
                num, den = (int(x) for x in sar.split(":", 1))
                if num > 0 and den > 0 and num != den:
                    w = int(round(w * num / den))
            except ValueError:
                pass

        for sd in stream.get("side_data_list") or []:
            rot = sd.get("rotation")
            if rot is not None and abs(int(round(float(rot)))) in (90, 270):
                w, h = h, w
                break

        return (w, h)
    except Exception:
        return None


def _calcular_y_watermark(dimensiones: Optional[Tuple[int, int]]) -> str:
    """Calcula la expresión Y adaptativa para centrar la marca de agua sin invadir el video."""
    if dimensiones and dimensiones[0] > 0 and dimensiones[1] > 0:
        w, h = dimensiones
        aspecto = w / h
        if aspecto <= (9.0 / 16.0) + 0.03:
            return "60"
        h_fg = min(1920, int(round(1080 * h / w)))
    else:
        h_fg = 608
    return f"max(40\\,(H-{h_fg})/2-h-24)"


def _escapar_ruta_ffmpeg_filtro(ruta: str | Path) -> str:
    """Escapa una ruta absoluta para usarla en subtitles='<ruta>' dentro de -filter_complex."""
    raw = str(Path(ruta).resolve())
    lv1 = raw.replace("\\", "\\\\").replace(":", "\\:").replace("'", "\\'")
    return lv1.replace("'", "'\\''")


def _es_error_http_expiracion(stderr_txt: str) -> bool:
    """Detecta errores HTTP 403/410 en la salida de FFmpeg por expiración de firma temporal."""
    if not stderr_txt:
        return False
    return bool(
        re.search(
            r"(?:HTTP\s+error\s+(?:403|410)|Server\s+returned\s+(?:403|410)|403\s+Forbidden|410\s+Gone)",
            stderr_txt,
            re.IGNORECASE,
        )
    )


def _ejecutar_comando_con_captura(comando: List[str]) -> str:
    """Ejecuta un comando mostrando su salida en consola y capturando stderr para diagnóstico."""
    proc = subprocess.Popen(
        comando,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
    )
    assert proc.stdout is not None
    chunks: List[bytes] = []
    fd = proc.stdout.fileno()
    while True:
        data = os.read(fd, 4096)
        if not data:
            break
        chunks.append(data)
        try:
            sys.stderr.buffer.write(data)
            sys.stderr.buffer.flush()
        except Exception:
            try:
                sys.stderr.write(data.decode("utf-8", errors="replace"))
                sys.stderr.flush()
            except Exception:
                pass
    returncode = proc.wait()
    salida_txt = b"".join(chunks).decode("utf-8", errors="replace")
    if returncode != 0:
        raise subprocess.CalledProcessError(returncode, comando, output=salida_txt, stderr=salida_txt)
    return salida_txt


def _preparar_archivo_ass_clip(
    subtitulos: Optional[List[Any]],
    id_clip: str | int,
    duracion_clip: float,
    job_id: Optional[str] = None,
    job_dir: Optional[Path | str] = None,
) -> Optional[str]:
    """Si hay subtítulos válidos para el clip, genera subs_<id_clip>.ass en job_dir."""
    subs_norm = _normalizar_subtitulos(subtitulos, duracion_clip)
    if not subs_norm:
        return None
    if job_dir:
        carpeta = Path(job_dir).resolve()
    elif job_id:
        carpeta = CARPETA_JOBS / job_id
    else:
        carpeta = CARPETA_JOBS / "standalone"
    carpeta.mkdir(parents=True, exist_ok=True)
    return generar_archivo_ass(subs_norm, carpeta / f"subs_{id_clip}.ass")


def _construir_comando_render(
    entradas_media: List[str],
    es_remoto: bool,
    inicio: str,
    duracion_str: str,
    archivo_salida: Path,
    y_watermark: str,
    encoder: str,
    ruta_ass: Optional[str] = None,
) -> List[str]:
    """Construye el comando FFmpeg 9:16 con encoder VAAPI o CPU, watermark adaptativa y subtítulos .ass."""
    comando = ["ffmpeg", "-hide_banner", "-stats", "-y"]
    if encoder == "h264_vaapi":
        comando.extend(["-vaapi_device", VAAPI_DEVICE])

    for media in entradas_media:
        if es_remoto:
            comando.extend(
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
        comando.extend(["-ss", inicio, "-t", duracion_str, "-i", media])

    idx_watermark = len(entradas_media)
    idx_audio = "1:a?" if len(entradas_media) > 1 else "0:a?"
    comando.extend(["-i", str(RUTA_MARCA_AGUA)])

    partes_filtro = [
        "[0:v]split=2[bg][fg]",
        "[bg]scale=360:640:force_original_aspect_ratio=increase,crop=360:640,setsar=1,boxblur=10:2,scale=1080:1920:flags=bilinear[bg_blur]",
        "[fg]scale=1080:1920:force_original_aspect_ratio=decrease,setsar=1[fg_scaled]",
        "[bg_blur][fg_scaled]overlay=(W-w)/2:(H-h)/2[vid_comp]",
        f"[{idx_watermark}:v]scale=420:-1,format=rgba,colorchannelmixer=aa=0.92[wm]",
    ]

    cadena_final = [f"[vid_comp][wm]overlay=(W-w)/2:{y_watermark}"]
    if ruta_ass:
        ruta_esc = _escapar_ruta_ffmpeg_filtro(ruta_ass)
        cadena_final.append(f"subtitles='{ruta_esc}'")
    if encoder == "h264_vaapi":
        cadena_final.append("format=nv12,hwupload[outv]")
    else:
        cadena_final.append("format=yuv420p[outv]")
    partes_filtro.append(",".join(cadena_final))
    filtro = ";".join(partes_filtro)

    comando.extend(
        [
            "-filter_complex",
            filtro,
            "-map",
            "[outv]",
            "-map",
            idx_audio,
            "-t",
            duracion_str,
        ]
    )

    if encoder == "h264_vaapi":
        comando.extend(["-c:v", "h264_vaapi", "-qp", "23"])
    else:
        comando.extend(
            [
                "-c:v",
                "libx264",
                "-preset",
                "veryfast",
                "-crf",
                "22",
                "-threads",
                "0",
            ]
        )

    comando.extend(
        [
            "-c:a",
            "aac",
            "-b:a",
            "128k",
            "-movflags",
            "+faststart",
            str(archivo_salida),
        ]
    )
    return comando


def procesar_clip_ffmpeg(
    url_o_archivo: str,
    inicio: str,
    fin: str,
    id_clip: str | int,
    job_id: Optional[str] = None,
    subtitulos: Optional[List[Any]] = None,
    job_dir: Optional[Path | str] = None,
) -> str:
    """Extrae el clip con input seek (-ss) y corte exacto (-t), renderiza 9:16 por VAAPI/CPU, watermark adaptativa y .ass."""
    if not RUTA_MARCA_AGUA.exists():
        raise FileNotFoundError(f"No se encontró la marca de agua en {RUTA_MARCA_AGUA}")

    duracion_clip = hhmmss_a_segundos(fin) - hhmmss_a_segundos(inicio)
    if duracion_clip <= 0:
        raise ValueError(f"Duración de clip inválida ({inicio} -> {fin}).")
    duracion_str = f"{duracion_clip:.3f}"

    CARPETA_SALIDA.mkdir(parents=True, exist_ok=True)
    nombre_clip = f"{job_id}_clip_{id_clip}.mp4" if job_id else f"clip_{id_clip}.mp4"
    archivo_salida = CARPETA_SALIDA / nombre_clip

    print(
        f"\n--- Procesando Clip {id_clip} ({inicio} -> {fin}, t={duracion_str}s) "
        f"[Salida: {nombre_clip}] ---"
    )

    ruta_ass = _preparar_archivo_ass_clip(
        subtitulos=subtitulos,
        id_clip=id_clip,
        duracion_clip=duracion_clip,
        job_id=job_id,
        job_dir=job_dir,
    )
    if ruta_ass:
        print(f"✓ Subtítulos dinámicos generados en: {ruta_ass}")

    clave_cache = job_id or f"anon:{url_o_archivo}"
    if os.path.exists(url_o_archivo):
        entradas_media = [str(Path(url_o_archivo).resolve())]
        es_remoto = False
        dimensiones = obtener_dimensiones_video(entradas_media[0])
    else:
        entradas_media = obtener_urls_stream(url_o_archivo, job_id=job_id)
        es_remoto = True
        entrada_cache = STREAM_URL_CACHE.obtener(clave_cache, url_o_archivo)
        dimensiones = entrada_cache.get("dimensiones") if entrada_cache else None
        if dimensiones is None:
            dimensiones = obtener_dimensiones_video(entradas_media[0])
            STREAM_URL_CACHE.actualizar_dimensiones(clave_cache, url_o_archivo, dimensiones)

    y_watermark = _calcular_y_watermark(dimensiones)
    encoder_activo = detectar_encoder_hardware()
    ruta_ass_activa = ruta_ass
    url_refrescada = False

    while True:
        comando_ffmpeg = _construir_comando_render(
            entradas_media=entradas_media,
            es_remoto=es_remoto,
            inicio=inicio,
            duracion_str=duracion_str,
            archivo_salida=archivo_salida,
            y_watermark=y_watermark,
            encoder=encoder_activo,
            ruta_ass=ruta_ass_activa,
        )
        print(
            f"Renderizando composición 9:16 con FFmpeg [encoder={encoder_activo}, "
            f"wm_y={y_watermark}, subs={'sí' if ruta_ass_activa else 'no'}]..."
        )
        try:
            _ejecutar_comando_con_captura(comando_ffmpeg)
            break
        except subprocess.CalledProcessError as err:
            if archivo_salida.exists():
                try:
                    archivo_salida.unlink()
                except OSError:
                    pass

            stderr_txt = err.stderr or err.output or ""

            if es_remoto and not url_refrescada and _es_error_http_expiracion(stderr_txt):
                print(
                    "[AVISO] Error HTTP 403/410 detectado en stream; "
                    "invalidando caché y re-obteniendo URLs..."
                )
                STREAM_URL_CACHE.invalidar(clave_cache)
                entradas_media = obtener_urls_stream(
                    url_o_archivo, job_id=job_id, forzar_recarga=True
                )
                dimensiones = obtener_dimensiones_video(entradas_media[0])
                STREAM_URL_CACHE.actualizar_dimensiones(clave_cache, url_o_archivo, dimensiones)
                y_watermark = _calcular_y_watermark(dimensiones)
                url_refrescada = True
                continue

            if ruta_ass_activa and re.search(
                r"Parsed_subtitles|subtitles|libass|\.ass", stderr_txt, re.IGNORECASE
            ):
                print(
                    "[AVISO] El filtro de subtítulos .ass falló; "
                    "reintentando render del clip sin subtítulos..."
                )
                ruta_ass_activa = None
                continue

            if encoder_activo == "h264_vaapi":
                print(
                    "[AVISO] Renderizado VAAPI falló en ejecución; "
                    "reintentando automáticamente con CPU (libx264)..."
                )
                encoder_activo = "libx264"
                continue

            if ruta_ass_activa:
                print(
                    "[AVISO] Renderizado falló con subtítulos activos; "
                    "reintentando sin subtítulos..."
                )
                ruta_ass_activa = None
                continue

            raise

    print(f"✓ Clip {id_clip} guardado con éxito en: {archivo_salida}")
    return str(archivo_salida.resolve())


def calcular_publish_at_utc(
    publish_at_inicio: Optional[str],
    indice_clip: int = 0,
    intervalo_horas: int | float = 0,
) -> Optional[str]:
    """Convierte fecha/hora local (-05:00) o ISO y suma intervalo_horas * indice_clip a ISO 8601 UTC (Z)."""
    if not publish_at_inicio or not str(publish_at_inicio).strip():
        return None
    texto = str(publish_at_inicio).strip()
    try:
        dt = datetime.fromisoformat(texto.replace("Z", "+00:00"))
    except ValueError as err:
        raise ValueError(
            f"Formato de fecha inválido '{texto}'. Usa 'YYYY-MM-DD HH:MM' (hora local Colombia -05:00) o ISO 8601."
        ) from err

    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=ZONA_HORARIA_LOCAL)

    horas_extra = max(0.0, float(intervalo_horas or 0)) * max(0, int(indice_clip))
    dt_objetivo = dt + timedelta(hours=horas_extra)
    return dt_objetivo.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _emitir_estado(
    fase: str,
    progreso: float,
    mensaje: str,
    clips: Optional[List[dict]] = None,
    ultimo_video: Optional[str] = None,
    job_dir: Optional[str] = None,
    error: Optional[str] = None,
) -> Dict[str, Any]:
    return {
        "fase": fase,
        "progreso": round(float(progreso), 4),
        "mensaje": mensaje,
        "clips": clips if clips is not None else [],
        "ultimo_video": ultimo_video,
        "job_dir": job_dir,
        "error": error,
    }


def _orquestar_render_y_subida(
    url: str,
    clips: List[dict],
    duracion_total: Optional[float] = None,
    subir_youtube: bool = True,
    job_id: Optional[str] = None,
    job_dir: Optional[Path | str] = None,
    publish_at_inicio: Optional[str] = None,
    intervalo_horas: int | float = 0,
    on_log: Optional[Callable[[str], None]] = None,
) -> Generator[Dict[str, Any], None, None]:
    """Orquestador compartido de Fase 3+4 con tolerancia a fallos por clip y control de cuota."""
    def _log(msg: str) -> None:
        if on_log is not None:
            on_log(msg)
        else:
            print(msg)

    job_dir_str = str(Path(job_dir).resolve()) if job_dir else None
    fuente_local: Optional[str] = None
    youtube_client = None
    ultimo_video: Optional[str] = None

    _log("\n[3/4] Renderizando clips con formato 9:16 y marca de agua @Kicksazos...")
    yield _emitir_estado(
        fase="fuente",
        progreso=0.55,
        mensaje="Fase 3/4: Preparando fuente de video en 1080p...",
        clips=clips,
        ultimo_video=ultimo_video,
        job_dir=job_dir_str,
    )

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
                _log(f"✓ Video fuente descargado en {fuente_local}")
            except Exception as e:
                _log(f"[AVISO] Descarga local completa omitida ({e}); usando seek directo en stream...")
                fuente_local = None

        if subir_youtube:
            _log("\n[4/4] Preparando cliente de YouTube Data API v3 para subida automática...")
            try:
                youtube_client = autenticar_youtube(interactivo=False)
                _log("✓ Cliente de YouTube autenticado correctamente.")
            except Exception as e:
                _log(
                    f"[AVISO] No se pudo inicializar YouTube Data API ({e}). "
                    "Los clips se renderizarán localmente sin interrumpir el flujo."
                )
                youtube_client = None

        entrada_render = fuente_local or url
        total_clips = len(clips)
        subidos_en_lote = 0

        for idx, clip in enumerate(clips, start=1):
            cid = clip.get("id", idx)
            frac = 0.60 + (0.35 * (idx - 1) / max(1, total_clips))
            _log(
                f"Procesando Clip #{cid}/{total_clips} ({clip.get('inicio')} -> {clip.get('fin')})..."
            )
            yield _emitir_estado(
                fase="render",
                progreso=frac,
                mensaje=f"Renderizando Clip #{cid}/{total_clips}: {clip.get('titulo', '')}",
                clips=clips,
                ultimo_video=ultimo_video,
                job_dir=job_dir_str,
            )

            try:
                salida = procesar_clip_ffmpeg(
                    entrada_render,
                    clip.get("inicio"),
                    clip.get("fin"),
                    str(cid),
                    job_id=job_id,
                    subtitulos=clip.get("subtitulos"),
                    job_dir=job_dir,
                )
                clip["archivo_local"] = salida
                clip["render_status"] = "OK"
                ultimo_video = salida
                _log(f"✓ Clip #{cid} renderizado en: {salida}")

                if not subir_youtube:
                    clip["youtube_status"] = "Subida omitida (--sin-subida)"
                elif youtube_client is None:
                    clip["youtube_status"] = "Pendiente de subida (Sin credenciales activas)"
                else:
                    cuota = verificar_cuota_diaria(limite_diario=LIMITE_CUOTA_DIARIA_SHORTS)
                    if not cuota["permitido"]:
                        clip["youtube_status"] = (
                            f"Pendiente por cuota diaria ({cuota['limite']}/24h)"
                        )
                        _log(
                            f"[AVISO] Cuota diaria alcanzada ({cuota['subidas_24h']}/{cuota['limite']} "
                            f"en últimas 24h). Clip #{cid} marcado como '{clip['youtube_status']}'."
                        )
                    else:
                        publish_at_clip = None
                        if publish_at_inicio and str(publish_at_inicio).strip():
                            publish_at_clip = calcular_publish_at_utc(
                                publish_at_inicio,
                                indice_clip=subidos_en_lote,
                                intervalo_horas=intervalo_horas,
                            )

                        msg_yt = f"Subiendo Clip #{cid} a YouTube Shorts"
                        if publish_at_clip:
                            msg_yt += f" (Programado UTC: {publish_at_clip})"
                        else:
                            msg_yt += " (Privado)"
                        _log(msg_yt)
                        yield _emitir_estado(
                            fase="youtube",
                            progreso=min(0.98, frac + (0.15 / max(1, total_clips))),
                            mensaje=msg_yt,
                            clips=clips,
                            ultimo_video=ultimo_video,
                            job_dir=job_dir_str,
                        )

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
                                publish_at=publish_at_clip,
                                on_log=_log,
                            )
                            clip["youtube_id"] = info_yt["youtube_id"]
                            clip["youtube_url"] = info_yt["url"]
                            if info_yt.get("publish_at"):
                                clip["youtube_publish_at"] = info_yt["publish_at"]
                                clip["youtube_status"] = f"Programado ({info_yt['publish_at']})"
                            else:
                                clip["youtube_status"] = "Subido (Privado)"
                            subidos_en_lote += 1
                        except Exception as e_yt:
                            _log(f"[AVISO] Error al subir Clip #{cid} a YouTube: {e_yt}")
                            clip["youtube_status"] = f"Error subida ({str(e_yt)[:80]})"
            except Exception as e_clip:
                err_txt = str(e_clip)
                clip["render_status"] = f"Error render ({err_txt[:120]})"
                clip["youtube_status"] = f"No renderizado ({err_txt[:80]})"
                _log(f"[ERROR] Falló procesamiento del Clip #{cid}: {err_txt}")
            finally:
                # Persistencia incremental tras cada clip sin abortar el lote
                _guardar_y_sincronizar_clips(clips, job_dir=job_dir)
    finally:
        if job_id:
            STREAM_URL_CACHE.invalidar(job_id)
        if fuente_local and os.path.exists(fuente_local):
            try:
                os.remove(fuente_local)
            except OSError:
                pass


def ejecutar_pipeline_completo(
    url: str,
    modelo_preferido: Optional[str] = None,
    solo_analisis: bool = False,
    subir_youtube: bool = True,
    publish_at_inicio: Optional[str] = None,
    intervalo_horas: int | float = 0,
    on_log: Optional[Callable[[str], None]] = None,
) -> Generator[Dict[str, Any], None, None]:
    """Orquestador único (CLI y GUI) que ejecuta el pipeline completo y emite diccionarios de estado."""
    def _log(msg: str) -> None:
        if on_log is not None:
            on_log(msg)
        else:
            print(msg)

    url_limpia = (url or "").strip()
    if not url_limpia:
        msg = "Por favor ingresa una URL válida de Kick, YouTube o Twitch."
        _log(f"[ERROR] {msg}")
        yield _emitir_estado("error", 0.0, msg, error=msg)
        return

    if not os.environ.get("GEMINI_API_KEY"):
        msg = "Falta GEMINI_API_KEY en el archivo .env o en las variables de entorno."
        _log(f"[ERROR] {msg}")
        yield _emitir_estado("error", 0.0, msg, error=msg)
        return

    if subir_youtube and not solo_analisis and publish_at_inicio and str(publish_at_inicio).strip():
        try:
            calcular_publish_at_utc(
                publish_at_inicio,
                indice_clip=0,
                intervalo_horas=intervalo_horas,
            )
        except ValueError as e_fecha:
            msg = str(e_fecha)
            _log(f"[ERROR] {msg}")
            yield _emitir_estado("error", 0.0, msg, error=msg)
            return

    ctx = crear_contexto_job(url_limpia)
    job_dir_str = str(ctx.job_dir)
    _log(f"Iniciando Job {ctx.job_id} en {ctx.job_dir}")

    audio_temp: Optional[str] = None
    clips: List[dict] = []
    ultimo_video: Optional[str] = None

    try:
        _log(f"Fase 1/4: Extrayendo pista de audio desde {url_limpia}...")
        yield _emitir_estado(
            fase="audio",
            progreso=0.08,
            mensaje=f"Fase 1/4: Extrayendo audio ligero en jobs/{ctx.job_id}...",
            clips=clips,
            ultimo_video=ultimo_video,
            job_dir=job_dir_str,
        )
        audio_temp = extraer_audio(url_limpia, job_dir=ctx.job_dir)
        duracion = obtener_duracion_media(audio_temp)
        dur_str = segundos_a_hhmmss(duracion) if duracion else "Desconocida"
        _log(f"✓ Audio extraído correctamente ({audio_temp}) | Duración: {dur_str}")

        modelo_label = (modelo_preferido or MODELOS_CANDIDATOS[0]).strip()
        yield _emitir_estado(
            fase="gemini",
            progreso=0.30,
            mensaje=f"Fase 2/4: Analizando narrativa viral con {modelo_label}...",
            clips=clips,
            ultimo_video=ultimo_video,
            job_dir=job_dir_str,
        )
        clips = analizar_con_gemini(
            audio_temp,
            duracion_total=duracion,
            modelo_preferido=modelo_preferido,
            job_dir=ctx.job_dir,
            on_log=_log,
        )
        for c in clips:
            _log(
                f"  • Clip #{c['id']}: {c['titulo']} [{c['inicio']} -> {c['fin']}] | "
                f"Hook: {str(c.get('gancho', ''))[:45]}..."
            )

        if solo_analisis:
            msg_fin = (
                f"Análisis viral completado ({len(clips)} clips) en jobs/{ctx.job_id}/clips.json y clips.json."
            )
            _log(f"✓ {msg_fin}")
            yield _emitir_estado(
                fase="completado",
                progreso=1.0,
                mensaje=msg_fin,
                clips=clips,
                ultimo_video=None,
                job_dir=job_dir_str,
            )
            return

        for estado_lote in _orquestar_render_y_subida(
            url=url_limpia,
            clips=clips,
            duracion_total=duracion,
            subir_youtube=subir_youtube,
            job_id=ctx.job_id,
            job_dir=ctx.job_dir,
            publish_at_inicio=publish_at_inicio,
            intervalo_horas=intervalo_horas,
            on_log=_log,
        ):
            if estado_lote.get("ultimo_video"):
                ultimo_video = estado_lote["ultimo_video"]
            yield estado_lote

        render_ok = sum(1 for c in clips if c.get("render_status") == "OK")
        render_err = len(clips) - render_ok
        subidos_ok = sum(1 for c in clips if c.get("youtube_url"))
        msg_final = (
            f"Job {ctx.job_id}: {render_ok}/{len(clips)} clips renderizados en 9:16 "
            f"({subidos_ok} subidos a YouTube Shorts"
            + (f", {render_err} con error de render" if render_err else "")
            + ")."
        )
        _log(f"✓ {msg_final}")
        yield _emitir_estado(
            fase="completado",
            progreso=1.0,
            mensaje=msg_final,
            clips=clips,
            ultimo_video=ultimo_video,
            job_dir=job_dir_str,
        )
    except Exception as e:
        err_msg = str(e)
        _log(f"[ERROR] {err_msg}")
        yield _emitir_estado(
            fase="error",
            progreso=0.0,
            mensaje=f"Error en pipeline: {err_msg}",
            clips=clips,
            ultimo_video=ultimo_video,
            job_dir=job_dir_str,
            error=err_msg,
        )
    finally:
        STREAM_URL_CACHE.invalidar(ctx.job_id)
        if audio_temp and os.path.exists(audio_temp):
            try:
                os.remove(audio_temp)
            except OSError:
                pass


def renderizar_y_subir_clips(
    url: str,
    clips: List[dict],
    duracion_total: Optional[float] = None,
    subir_youtube: bool = True,
    job_id: Optional[str] = None,
    job_dir: Optional[Path | str] = None,
    publish_at_inicio: Optional[str] = None,
    intervalo_horas: int | float = 0,
) -> List[str]:
    """Wrapper compatible que delega en _orquestar_render_y_subida y retorna rutas locales exitosas."""
    for _ in _orquestar_render_y_subida(
        url=url,
        clips=clips,
        duracion_total=duracion_total,
        subir_youtube=subir_youtube,
        job_id=job_id,
        job_dir=job_dir,
        publish_at_inicio=publish_at_inicio,
        intervalo_horas=intervalo_horas,
    ):
        pass
    return [c["archivo_local"] for c in clips if c.get("archivo_local")]


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
    parser.add_argument(
        "--publish-at",
        default=None,
        help="Fecha/hora inicio programación (YYYY-MM-DD HH:MM hora Colombia -05:00)",
    )
    parser.add_argument(
        "--intervalo-horas",
        type=int,
        default=0,
        help="Intervalo en horas entre Shorts programados (0-24)",
    )
    args = parser.parse_args()

    ultimo_estado: Optional[Dict[str, Any]] = None
    for estado in ejecutar_pipeline_completo(
        url=args.url,
        modelo_preferido=args.modelo,
        solo_analisis=args.solo_analisis,
        subir_youtube=not args.sin_subida,
        publish_at_inicio=args.publish_at,
        intervalo_horas=args.intervalo_horas,
        on_log=print,
    ):
        ultimo_estado = estado

    if not ultimo_estado or ultimo_estado.get("error"):
        err = (ultimo_estado or {}).get("error") or "Error desconocido en el pipeline."
        print(f"\n[ERROR] Pipeline falló: {err}")
        sys.exit(1)

    job_dir_final = ultimo_estado.get("job_dir") or str(CARPETA_JOBS)
    print(f"\n✓ ¡Pipeline completado con éxito! ({ultimo_estado.get('mensaje')})")
    print(f"Revisa {CARPETA_SALIDA}, {job_dir_final} y {HISTORIAL_SUBIDAS_FILE}")


if __name__ == "__main__":
    main()
