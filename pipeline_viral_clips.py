#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from pathlib import Path
BASE_DIR = Path(__file__).resolve().parent

from dotenv import load_dotenv
load_dotenv(BASE_DIR / ".env")

import argparse
import array
import atexit
import concurrent.futures
from datetime import datetime, timedelta, timezone
import gc
import glob
import inspect
import json
import math
import os
import queue
import random
import re
import shutil
import signal
import statistics
import subprocess
import sys
import tempfile
import threading
import time
from typing import Any, Callable, Dict, Generator, List, NamedTuple, Optional, Sequence, Set, Tuple
from urllib.parse import urlparse
import urllib.error
import urllib.request

from google import genai
from google.genai import types
from google.genai.errors import APIError, ServerError
from pydantic import BaseModel, Field, TypeAdapter

try:
    from faster_whisper import WhisperModel
except ImportError:
    WhisperModel = None  # type: ignore[assignment,misc]

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
    "gemini-3.7-flash",
    "gemini-3.5-flash-lite",
]
MODELOS_LOCALES_OLLAMA = ["qwen3:14b", "gemma3:12b", "qwen2.5:14b"]
OLLAMA_BASE_URL = os.environ.get("OLLAMA_HOST", "http://127.0.0.1:11434").rstrip("/")
WHISPER_MODEL_SIZE = "medium"
RUTA_MARCA_AGUA = BASE_DIR / "assets" / "watermark.png"
CARPETA_FUENTES = BASE_DIR / "assets" / "fonts"
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


class GeminiQuotaExhaustedError(RuntimeError):
    """Se lanza cuando toda la cascada Gemini falla por agotamiento de cuota / error 429."""


class JobContext(NamedTuple):
    job_id: str
    job_dir: Path


class StreamUrlCache:
    """Caché thread-safe en memoria por job_id para URLs directas de stream (video_url, audio_url) y dimensiones."""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._entries: Dict[str, Dict[str, Any]] = {}

    def obtener(self, job_id: str, url: str) -> Optional[Dict[str, Any]]:
        with self._lock:
            entrada = self._entries.get(job_id)
            if not entrada or entrada.get("source_url") != url:
                return None
            return dict(entrada)

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
        with self._lock:
            self._entries[job_id] = registro
            return dict(registro)

    def actualizar_dimensiones(
        self, job_id: str, url: str, dimensiones: Optional[Tuple[int, int]]
    ) -> None:
        with self._lock:
            entrada = self._entries.get(job_id)
            if entrada is not None and entrada.get("source_url") == url:
                entrada["dimensiones"] = dimensiones

    def invalidar(self, job_id: Optional[str] = None) -> None:
        with self._lock:
            if job_id is None:
                self._entries.clear()
            else:
                self._entries.pop(job_id, None)


STREAM_URL_CACHE = StreamUrlCache()
_STREAM_FETCH_LOCK = threading.Lock()
_STREAM_FETCH_LOCKS: Dict[str, threading.Lock] = {}

_CLIPS_JSON_LOCK = threading.RLock()
_PROCESOS_ACTIVOS_LOCK = threading.Lock()
_PROCESOS_ACTIVOS: Dict[int, Any] = {}


def _obtener_lock_stream_job(clave_cache: str) -> threading.Lock:
    """Devuelve un Lock por job_id para evitar llamadas yt-dlp -g duplicadas en paralelo."""
    with _STREAM_FETCH_LOCK:
        lock = _STREAM_FETCH_LOCKS.get(clave_cache)
        if lock is None:
            lock = threading.Lock()
            _STREAM_FETCH_LOCKS[clave_cache] = lock
        return lock


def _escribir_json_atomico(ruta: Path, datos: Any) -> None:
    """Escribe JSON de forma atómica usando archivo temporal y os.replace()."""
    ruta.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_path = tempfile.mkstemp(
        prefix=f".tmp_{ruta.stem}_", suffix=".json", dir=str(ruta.parent)
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(datos, f, indent=2, ensure_ascii=False)
        os.replace(tmp_path, ruta)
    except BaseException:
        if os.path.exists(tmp_path):
            try:
                os.remove(tmp_path)
            except OSError:
                pass
        raise


def _registrar_proceso_activo(proc: Any) -> None:
    """Registra un subproceso Popen activo para garantizar su limpieza ante cancelación."""
    if proc is None:
        return
    with _PROCESOS_ACTIVOS_LOCK:
        _PROCESOS_ACTIVOS[id(proc)] = proc


def _desregistrar_proceso_activo(proc: Any) -> None:
    """Elimina un subproceso Popen del registro de activos."""
    if proc is None:
        return
    with _PROCESOS_ACTIVOS_LOCK:
        _PROCESOS_ACTIVOS.pop(id(proc), None)


def _terminar_proceso_seguro(proc: Any) -> None:
    """Termina de forma limpia un subproceso Popen y su grupo de procesos si sigue vivo."""
    if proc is None:
        return
    try:
        esta_vivo = getattr(proc, "poll", lambda: 0)() is None
    except Exception:
        esta_vivo = False
    if not esta_vivo:
        return

    pid = getattr(proc, "pid", None)
    if os.name == "posix" and isinstance(pid, int) and pid > 0:
        try:
            pgid = os.getpgid(pid)
            os.killpg(pgid, signal.SIGTERM)
            try:
                proc.wait(timeout=1.5)
                return
            except subprocess.TimeoutExpired:
                os.killpg(pgid, signal.SIGKILL)
                proc.wait(timeout=2.0)
                return
        except (OSError, ProcessLookupError, subprocess.SubprocessError):
            pass

    try:
        proc.kill()
        proc.wait(timeout=2.0)
    except Exception:
        pass


def terminar_procesos_activos() -> int:
    """Finaliza todos los subprocesos FFmpeg/yt-dlp activos registrados (Ctrl+C o cierre UI)."""
    with _PROCESOS_ACTIVOS_LOCK:
        activos = list(_PROCESOS_ACTIVOS.values())
    terminados = 0
    for proc in activos:
        try:
            if getattr(proc, "poll", lambda: 0)() is None:
                _terminar_proceso_seguro(proc)
                terminados += 1
        finally:
            _cerrar_pipes_proceso(proc)
            _desregistrar_proceso_activo(proc)
    return terminados


atexit.register(terminar_procesos_activos)


def _cerrar_cliente_genai_seguro(client: Any) -> None:
    """Cierra el cliente google-genai y su pool HTTP/event loop interno sin propagar errores."""
    if client is None:
        return
    close_fn = getattr(client, "close", None)
    if callable(close_fn):
        try:
            close_fn()
        except Exception:
            pass


def _eliminar_archivo_gemini_seguro(client: Any, archivo_subido: Any) -> None:
    """Elimina un archivo remoto de Gemini File API de forma segura."""
    if client is None or archivo_subido is None:
        return
    nombre = getattr(archivo_subido, "name", None)
    if not nombre:
        return
    try:
        client.files.delete(name=nombre)
    except Exception:
        pass


class OllamaCircuitBreaker:
    """Circuit-breaker thread-safe para proteger al pipeline ante caídas del demonio Ollama."""

    def __init__(self, failure_threshold: int = 3, cooldown_seconds: float = 30.0) -> None:
        self._lock = threading.Lock()
        self.failure_threshold = max(1, int(failure_threshold))
        self.cooldown_seconds = max(1.0, float(cooldown_seconds))
        self._failures = 0
        self._opened_at: Optional[float] = None

    def estado(self) -> str:
        with self._lock:
            if self._opened_at is None:
                return "CLOSED"
            if (time.monotonic() - self._opened_at) >= self.cooldown_seconds:
                return "HALF_OPEN"
            return "OPEN"

    def permitir_peticion(self) -> bool:
        return self.estado() != "OPEN"

    def registrar_exito(self) -> None:
        with self._lock:
            self._failures = 0
            self._opened_at = None

    def registrar_fallo(self) -> str:
        with self._lock:
            self._failures += 1
            if self._failures >= self.failure_threshold:
                self._opened_at = time.monotonic()
                return "OPEN"
            return "CLOSED"

    def reiniciar(self) -> None:
        with self._lock:
            self._failures = 0
            self._opened_at = None


OLLAMA_CIRCUIT_BREAKER = OllamaCircuitBreaker(failure_threshold=3, cooldown_seconds=30.0)


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
        description="Transcripción literal en bloque de lectura rápida: 2 a 4 palabras, máximo 22 caracteres, sin emojis."
    )


class ClipViral(BaseModel):
    """Esquema estructurado de cada clip viral detectado por Gemini con SEO multiplataforma (YouTube Shorts + TikTok)."""

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
    caption_tiktok: str = Field(
        description="Caption para TikTok de máximo 150 caracteres optimizado para SEO semántico y diseñado para detonar comentarios."
    )
    hashtags_tiktok: List[str] = Field(
        description="Lista de exactamente 3 a 5 hashtags estratégicos para TikTok mezclando nicho y alcance, sin spam."
    )
    gancho_visual_portada: str = Field(
        description="Titular visual de portada de 4 a 6 palabras, impactante, pensado para los primeros 2 segundos de retención en TikTok."
    )
    subtitulos: List[SegmentoSubtitulo] = Field(
        default_factory=list,
        description="Transcripción literal en bloques cortos (2 a 4 palabras, máximo 22 caracteres, sin emojis) sincronizados en segundos relativos desde 0.0 hasta la duración del clip.",
    )


class ClipViralLocal(BaseModel):
    """Esquema estructurado de clip viral para curaduría local con Ollama (subtítulos provienen de Whisper)."""

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
        description="Resumen corto (2 líneas) con llamado a la acción (CTA) de suscripción y 3-5 hashtags estratégicos (#Shorts #Kicksazos)"
    )
    etiquetas: List[str] = Field(
        description="Lista de 8 a 12 tags SEO clave incluyendo nombres propios de involucrados y ecosistema streaming colombiano"
    )
    caption_tiktok: str = Field(
        description="Caption para TikTok de máximo 150 caracteres optimizado para SEO semántico y debate en comentarios."
    )
    hashtags_tiktok: List[str] = Field(
        description="Lista de 3 a 5 hashtags estratégicos para TikTok mezclando nicho y alcance."
    )
    gancho_visual_portada: str = Field(
        description="Titular visual de portada de 4 a 6 palabras, impactante, para retención inicial en TikTok."
    )


class ListaClipsLocal(BaseModel):
    """Contenedor raíz de respuesta JSON estructurada para Ollama."""

    clips: List[ClipViralLocal] = Field(default_factory=list)


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


def _normalizar_caption_tiktok(
    raw_caption: Any,
    gancho_fallback: str = "",
    titulo_fallback: str = "",
) -> str:
    """Garantiza un caption TikTok no vacío y <= 150 caracteres optimizado para comentarios."""
    caption = re.sub(r"\s+", " ", str(raw_caption or "")).strip()
    if not caption:
        base = re.sub(r"\s+", " ", str(gancho_fallback or titulo_fallback or "")).strip()
        if base:
            caption = f"{base} — ¿Tú qué opinas? 👇"
        else:
            caption = "Momento épico en stream colombiano 🔥 ¿Tú qué opinas? 👇"
    if len(caption) > 150:
        caption = caption[:147].rstrip() + "..."
    return caption


def _normalizar_hashtags_tiktok(
    raw_tags: Any,
    etiquetas_fallback: Optional[List[str]] = None,
) -> List[str]:
    """Garantiza una lista limpia de entre 3 y 5 hashtags con prefijo # para TikTok."""
    base_defaults = [
        "#Kicksazos",
        "#StreamColombia",
        "#KickColombia",
        "#IRLColombia",
        "#ClipsVirales",
    ]
    if isinstance(raw_tags, list):
        candidatos = raw_tags
    elif isinstance(raw_tags, str):
        candidatos = [t.strip() for t in re.split(r"[,;\s\n]+", raw_tags) if t.strip()]
    else:
        candidatos = []

    resultado: List[str] = []
    vistos = set()

    def _agregar(raw_tag: Any) -> None:
        cuerpo = re.sub(r"\s+", "", str(raw_tag or "").strip()).lstrip("#")
        if not cuerpo:
            return
        tag_fmt = f"#{cuerpo}"
        clave = tag_fmt.lower()
        if clave not in vistos:
            vistos.add(clave)
            resultado.append(tag_fmt)

    for tag in candidatos:
        _agregar(tag)

    if len(resultado) < 3 and etiquetas_fallback:
        for et in etiquetas_fallback:
            if len(resultado) >= 4:
                break
            cuerpo_et = re.sub(r"\s+", "", str(et or "").strip()).lstrip("#")
            if cuerpo_et.lower() in {"shorts", "youtubeshorts", "youtube"}:
                continue
            _agregar(cuerpo_et)

    for defecto in base_defaults:
        if len(resultado) >= 3:
            break
        _agregar(defecto)

    return resultado[:5]


def _normalizar_gancho_portada(
    raw_gancho: Any,
    titulo_fallback: str = "",
    gancho_fallback: str = "",
) -> str:
    """Garantiza un titular visual de portada de 4 a 6 palabras para TikTok."""
    texto = re.sub(r"\s+", " ", str(raw_gancho or "")).strip()
    palabras = texto.split()

    if not palabras:
        fuente = re.sub(
            r"[\U00010000-\U0010FFFF\u2600-\u27BF\uFE0F\u200D]+",
            "",
            str(titulo_fallback or gancho_fallback or ""),
        ).strip()
        palabras = [p for p in fuente.split() if any(ch.isalnum() for ch in p)]

    if len(palabras) > 6:
        palabras = palabras[:6]

    if len(palabras) < 4:
        if not palabras:
            palabras = ["ESTO", "PASÓ", "EN", "STREAM", "VIVO"]
        else:
            for extra in ("EN", "VIVO", "SIN", "FILTRO"):
                if len(palabras) >= 4:
                    break
                palabras.append(extra)

    return " ".join(palabras[:6])


_REGEX_EMOJIS_ASS = re.compile(r"[\U00010000-\U0010FFFF\u2600-\u27BF\uFE0F\u200D]+")
_ANIMACION_POPIN_ASS = r"{\fad(40,40)\t(0,70,\fscx105\fscy105)\t(70,140,\fscx100\fscy100)}"
_FUENTES_PRIORIDAD_SUBTITULOS = (
    "Montserrat ExtraBold",
    "Montserrat Black",
    "Montserrat",
    "Poppins ExtraBold",
    "Poppins Bold",
    "Poppins",
    "Impact",
    "Liberation Sans",
    "Ubuntu",
    "DejaVu Sans",
)


def _dividir_segmento_subtitulo(seg: SegmentoSubtitulo) -> List[SegmentoSubtitulo]:
    """Divide segmentos largos (>5 palabras o >28 chars y >=0.6s) en bloques de 2 a 4 palabras."""
    texto = seg.texto
    palabras = texto.split()
    duracion = seg.fin_rel - seg.inicio_rel
    if duracion < 0.6 or (len(palabras) <= 5 and len(texto) <= 28):
        return [seg]

    n = len(palabras)
    if n < 4:
        return [seg]

    k_min = max(2, math.ceil(n / 4))
    k_max = max(k_min, min(n // 2, max(2, int(duracion / 0.10))))
    grupos_palabras: List[List[str]] = []
    for k in range(k_min, k_max + 1):
        base, extra = divmod(n, k)
        candidatos_grupos: List[List[str]] = []
        idx = 0
        for j in range(k):
            tam = base + (1 if j < extra else 0)
            candidatos_grupos.append(palabras[idx : idx + tam])
            idx += tam
        grupos_palabras = candidatos_grupos
        if all(len(" ".join(g)) <= 28 for g in candidatos_grupos):
            break

    fragmentos = [" ".join(g) for g in grupos_palabras if g]
    if len(fragmentos) <= 1:
        return [seg]

    pesos = [max(1, len(frag)) for frag in fragmentos]
    total_pesos = sum(pesos)
    ini = round(seg.inicio_rel, 2)
    fin = round(seg.fin_rel, 2)
    span = fin - ini

    resultado: List[SegmentoSubtitulo] = []
    cursor = ini
    peso_acum = 0
    num_frags = len(fragmentos)
    for j, (frag, peso) in enumerate(zip(fragmentos, pesos)):
        if j == num_frags - 1:
            seg_fin = fin
        else:
            peso_acum += peso
            prop_fin = round(ini + span * (peso_acum / total_pesos), 2)
            min_fin = round(cursor + 0.05, 2)
            max_fin = round(fin - 0.05 * (num_frags - 1 - j), 2)
            seg_fin = max(min_fin, min(max_fin, prop_fin))
        if seg_fin <= cursor + 0.02:
            continue
        resultado.append(
            SegmentoSubtitulo(
                inicio_rel=round(cursor, 2),
                fin_rel=round(seg_fin, 2),
                texto=frag,
            )
        )
        cursor = round(seg_fin, 2)

    return resultado or [seg]


def _normalizar_subtitulos(
    raw_subs: Any, duracion_clip: float
) -> List[SegmentoSubtitulo]:
    """Limpia, valida, ordena, auto-divide bloques largos y elimina solapamientos dentro de [0, duracion_clip]."""
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

        texto_sin_emojis = _REGEX_EMOJIS_ASS.sub("", str(txt_raw or ""))
        texto = re.sub(r"\s+", " ", texto_sin_emojis).strip()
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

    divididos: List[SegmentoSubtitulo] = []
    for seg in sin_solape:
        divididos.extend(_dividir_segmento_subtitulo(seg))
    return divididos


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
    """Normaliza texto en MAYÚSCULAS para Dialogue ASS evitando llaves, saltos crudos y emojis sin glifo."""
    limpio = _REGEX_EMOJIS_ASS.sub("", str(texto or ""))
    limpio = re.sub(r"\r\n|\r|\n", r"\\N", limpio)
    limpio = re.sub(r"[ \t\f\v]+", " ", limpio).strip()
    limpio = limpio.replace("{", "(").replace("}", ")")
    return limpio.upper()


def _detectar_fuente_subtitulos() -> str:
    """Detecta vía fc-list la primera tipografía instalada en orden de prioridad para clips virales."""
    try:
        res = subprocess.run(
            ["fc-list", ":", "family"],
            capture_output=True,
            text=True,
            check=True,
            timeout=5,
        )
        familias: Dict[str, str] = {}
        for linea in res.stdout.splitlines():
            for fam in linea.split(","):
                limpia = fam.strip()
                if limpia:
                    familias.setdefault(limpia.lower(), limpia)
        for candidata in _FUENTES_PRIORIDAD_SUBTITULOS:
            match = familias.get(candidata.lower())
            if match:
                return match
    except Exception:
        pass
    return "DejaVu Sans"


def _inferir_nombre_fuente_por_archivo(ruta_fuente: Path) -> str:
    """Infiere un nombre legible de familia a partir del nombre de archivo .ttf/.otf."""
    stem = re.sub(r"\[.*?\]", "", ruta_fuente.stem)
    limpio = re.sub(r"[-_]+", " ", stem).strip()
    return limpio or "Montserrat ExtraBold"


def _obtener_fuente_y_dir_subtitulos() -> Tuple[str, Optional[str]]:
    """Obtiene (nombre_familia_libass, fonts_dir) desde assets/fonts/ o fallback del sistema."""
    try:
        if CARPETA_FUENTES.exists() and CARPETA_FUENTES.is_dir():
            candidatos = [
                p
                for p in CARPETA_FUENTES.iterdir()
                if p.is_file() and p.suffix.lower() in (".ttf", ".otf") and p.stat().st_size > 0
            ]
            if candidatos:
                candidatos.sort(
                    key=lambda p: (
                        0
                        if "extrabold" in p.name.lower()
                        else (1 if "black" in p.name.lower() else (2 if "bold" in p.name.lower() else 3)),
                        p.name.lower(),
                    )
                )
                ruta_elegida = candidatos[0]
                nombre_familia: Optional[str] = None
                if shutil.which("fc-scan"):
                    try:
                        res = subprocess.run(
                            ["fc-scan", "--format", "%{fullname[0]}\n%{family}\n", str(ruta_elegida)],
                            capture_output=True,
                            text=True,
                            check=True,
                            timeout=5,
                        )
                        lineas = [ln.strip() for ln in res.stdout.splitlines() if ln.strip()]
                        fullname = lineas[0] if len(lineas) >= 1 else ""
                        familias = (
                            [f.strip() for f in lineas[1].split(",") if f.strip()]
                            if len(lineas) >= 2
                            else []
                        )
                        if fullname and fullname in familias:
                            nombre_familia = fullname
                        else:
                            for fam in familias:
                                if any(tag in fam.lower() for tag in ("extrabold", "black", "bold")):
                                    nombre_familia = fam
                                    break
                            if not nombre_familia and familias:
                                nombre_familia = familias[0]
                            elif not nombre_familia and fullname:
                                nombre_familia = fullname
                    except Exception:
                        nombre_familia = None

                if not nombre_familia:
                    nombre_familia = _inferir_nombre_fuente_por_archivo(ruta_elegida)
                return nombre_familia, str(CARPETA_FUENTES.resolve())
    except Exception:
        pass
    return _detectar_fuente_subtitulos(), None


def generar_archivo_ass(
    subtitulos: List[Any],
    ruta_ass: str | Path,
) -> str:
    """Genera un archivo .ass v4.1 ópticamente centrado en Safe Zone 9:16 (WrapStyle: 0, Fontsize=50, MarginL=120, MarginR=120, MarginV=450)."""
    ruta = Path(ruta_ass).resolve()
    ruta.parent.mkdir(parents=True, exist_ok=True)
    fuente_sub, _ = _obtener_fuente_y_dir_subtitulos()

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
            f"Style: Default,{fuente_sub},50,&H00FFFFFF,&H0000FFFF,&H00000000,&HA0000000,-1,0,0,0,100,100,1.2,0,1,5.0,3.0,2,120,120,450,1",
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
            f"Dialogue: 0,{t_ini},{t_fin},Default,,0,0,0,,{_ANIMACION_POPIN_ASS}{texto_ass}"
        )

    contenido = encabezado + ("\n" + "\n".join(lineas_eventos) if lineas_eventos else "") + "\n"
    ruta.write_text(contenido, encoding="utf-8")
    return str(ruta)


def _reparar_json_lista_truncada(limpio: str) -> Optional[list]:
    """Extrae objetos JSON completos de un array truncado (ej. por max_tokens) usando JSONDecoder.raw_decode."""
    idx_inicio = limpio.find("[")
    if idx_inicio == -1:
        return None
    dec = json.JSONDecoder()
    pos = idx_inicio + 1
    n = len(limpio)
    objetos: list = []
    while pos < n:
        while pos < n and limpio[pos] in " \t\r\n,":
            pos += 1
        if pos >= n or limpio[pos] == "]":
            break
        if limpio[pos] != "{":
            break
        try:
            obj, end_pos = dec.raw_decode(limpio, pos)
            if isinstance(obj, dict):
                objetos.append(obj)
            pos = end_pos
        except json.JSONDecodeError:
            break
    return objetos if objetos else None


def _extraer_lista_json_con_esquema(
    texto: str,
    adapter: TypeAdapter[Any],
    clave_dict: str,
) -> list:
    """Limpia bloques think/markdown, recupera arrays JSON truncados y valida con TypeAdapter."""
    limpio = re.sub(r"<think>.*?</think>", "", str(texto or ""), flags=re.IGNORECASE | re.DOTALL).strip()
    if "<think>" in limpio.lower():
        limpio = re.sub(r"<think>.*?(?=\{|\[|$)", "", limpio, flags=re.IGNORECASE | re.DOTALL).strip()
    limpio = re.sub(r"^```(?:json)?\s*", "", limpio, flags=re.IGNORECASE)
    limpio = re.sub(r"\s*```$", "", limpio)
    limpio = limpio.strip()

    datos = None
    try:
        objetos = adapter.validate_json(limpio)
        datos = [c.model_dump() for c in objetos]
    except Exception:
        try:
            datos = json.loads(limpio)
        except Exception:
            coincidencia = re.search(r"\[.*\]", limpio, flags=re.DOTALL)
            if coincidencia:
                bloque_json = coincidencia.group(0)
                try:
                    objetos = adapter.validate_json(bloque_json)
                    datos = [c.model_dump() for c in objetos]
                except Exception:
                    try:
                        datos = json.loads(bloque_json)
                    except Exception:
                        datos = _reparar_json_lista_truncada(limpio)
            else:
                datos = _reparar_json_lista_truncada(limpio)

            if datos is None:
                datos = json.loads(limpio)

    if isinstance(datos, dict):
        datos = datos.get(clave_dict, [])
    if not isinstance(datos, list):
        raise ValueError(f"La respuesta JSON de IA no contiene una lista válida de '{clave_dict}'.")
    return datos


def _parsear_subtitulos_json(texto: str, duracion_clip: float) -> List[SegmentoSubtitulo]:
    """Parsea y normaliza la respuesta JSON de alineación fonética (list[SegmentoSubtitulo])."""
    datos = _extraer_lista_json_con_esquema(
        texto,
        TypeAdapter(List[SegmentoSubtitulo]),
        clave_dict="subtitulos",
    )
    subs = _normalizar_subtitulos(datos, duracion_clip)
    if not subs:
        raise ValueError("La respuesta JSON de alineación fonética no contiene subtítulos válidos.")
    return subs


def _limpiar_y_parsear_json(
    texto: str, duracion_total: Optional[float] = None, permitir_vacio: bool = False
) -> List[dict]:
    """Limpia posibles bloques markdown y valida la respuesta mediante regex y esquema tipado estricto."""
    datos = _extraer_lista_json_con_esquema(
        texto,
        TypeAdapter(List[ClipViral]),
        clave_dict="clips",
    )
    if not datos:
        if permitir_vacio:
            return []
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
        caption_tiktok_norm = _normalizar_caption_tiktok(
            item.get("caption_tiktok"),
            gancho_fallback=gancho_raw,
            titulo_fallback=titulo_raw,
        )
        hashtags_tiktok_norm = _normalizar_hashtags_tiktok(
            item.get("hashtags_tiktok"),
            etiquetas_fallback=etiquetas_norm,
        )
        gancho_portada_norm = _normalizar_gancho_portada(
            item.get("gancho_visual_portada"),
            titulo_fallback=titulo_raw,
            gancho_fallback=gancho_raw,
        )
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
            caption_tiktok=caption_tiktok_norm,
            hashtags_tiktok=hashtags_tiktok_norm,
            gancho_visual_portada=gancho_portada_norm,
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
    res = subprocess.run(comando, capture_output=True, text=True, check=True, timeout=60)
    urls = [linea.strip() for linea in res.stdout.splitlines() if linea.strip()]
    if not urls:
        raise RuntimeError("yt-dlp -g no devolvió URL directa para extracción de audio.")
    return urls[0]


def _es_stream_hls_kick_o_twitch(url: str) -> bool:
    """Detecta si la URL corresponde a un stream HLS (.m3u8) o a los dominios de Kick/Twitch."""
    url_limpia = (url or "").strip().lower()
    if ".m3u8" in url_limpia:
        return True
    host = urlparse(url_limpia).hostname or ""
    return (
        host == "kick.com"
        or host.endswith(".kick.com")
        or host == "twitch.tv"
        or host.endswith(".twitch.tv")
    )


_REGEX_YTDLP_PROGRESO = re.compile(
    r"\[download\]\s+(?P<pct>\d+(?:\.\d+)?)%\s+of\s+~?\s*(?P<total>\S+)\s+"
    r"(?:at\s+(?P<vel>Unknown\s+B/s|\S+)(?:\s+ETA\s+(?P<eta>\S+))?"
    r"|in\s+\S+\s+at\s+(?P<vel_fin>\S+))"
)
_REGEX_YTDLP_FRAG = re.compile(r"\(frag\s+(?P<frag_cur>\d+)/(?P<frag_tot>\d+)\)")
_REGEX_ARIA2_PROGRESO = re.compile(
    r"\[\S+\s+\S+/(?P<total>[^(\s]+)\((?P<pct>\d+(?:\.\d+)?)%\).*?DL:(?P<vel>\S+)(?:.*?ETA:(?P<eta>[^\s\]]+))?"
)


def _emitir_telemetria(
    on_telemetria: Optional[Callable[[Dict[str, Any]], None]],
    ultimo_ts_ref: List[float],
    datos: Dict[str, Any],
    forzar: bool = False,
    min_intervalo: float = 0.33,
) -> None:
    """Invoca callback de telemetría respetando el límite de ~3 actualizaciones/seg salvo hitos forzados."""
    if on_telemetria is None:
        return
    ahora = time.monotonic()
    if not forzar and (ahora - ultimo_ts_ref[0]) < min_intervalo:
        return
    ultimo_ts_ref[0] = ahora
    try:
        on_telemetria(dict(datos))
    except Exception:
        pass


def _parsear_linea_progreso_descarga(linea: str) -> Optional[Dict[str, Any]]:
    """Extrae porcentaje, tamaño, velocidad de red, ETA y fragmentos de líneas yt-dlp o aria2c."""
    if not linea:
        return None

    m_yt = _REGEX_YTDLP_PROGRESO.search(linea)
    if m_yt:
        pct = max(0.0, min(100.0, float(m_yt.group("pct"))))
        total = m_yt.group("total") or "--"
        vel = (m_yt.group("vel") or m_yt.group("vel_fin") or "--").strip()
        eta = (m_yt.group("eta") or ("00:00" if pct >= 100.0 else "--:--")).strip()
        m_frag = _REGEX_YTDLP_FRAG.search(linea)
        frag_cur = int(m_frag.group("frag_cur")) if m_frag else None
        frag_tot = int(m_frag.group("frag_tot")) if m_frag else None
        return {
            "porcentaje": round(pct, 1),
            "tamano_total": total,
            "velocidad_red": vel,
            "eta": eta,
            "frag_cur": frag_cur,
            "frag_tot": frag_tot,
        }

    m_ar = _REGEX_ARIA2_PROGRESO.search(linea)
    if m_ar:
        pct = max(0.0, min(100.0, float(m_ar.group("pct"))))
        total = (m_ar.group("total") or "--").strip()
        vel = (m_ar.group("vel") or "--").strip()
        if vel != "--" and not vel.endswith("/s"):
            vel = f"{vel}/s"
        eta = (m_ar.group("eta") or ("0s" if pct >= 100.0 else "--:--")).strip()
        return {
            "porcentaje": round(pct, 1),
            "tamano_total": total,
            "velocidad_red": vel,
            "eta": eta,
            "frag_cur": None,
            "frag_tot": None,
        }

    return None


def _cerrar_pipes_proceso(proc: Any) -> None:
    """Cierra los pipes stdout/stderr de Popen de forma segura para evitar ResourceWarning."""
    for attr in ("stdout", "stderr"):
        stream = getattr(proc, attr, None)
        if stream is not None:
            try:
                stream.close()
            except Exception:
                pass


def _ejecutar_descarga_con_telemetria(
    comando: List[str],
    on_telemetria: Optional[Callable[[Dict[str, Any]], None]],
    etapa: str,
    titulo_etapa: str,
    detalle_default: str,
) -> str:
    """Ejecuta yt-dlp con Popen leyendo línea a línea y emitiendo telemetría en vivo."""
    popen_kwargs: Dict[str, Any] = {
        "stdin": subprocess.DEVNULL,
        "stdout": subprocess.PIPE,
        "stderr": subprocess.STDOUT,
        "text": True,
        "bufsize": 1,
    }
    if os.name == "posix":
        popen_kwargs["start_new_session"] = True
    proc = subprocess.Popen(comando, **popen_kwargs)
    _registrar_proceso_activo(proc)
    ultimas_lineas: List[str] = []
    ultimo_ts = [0.0]

    try:
        if proc.stdout is not None:
            for linea_raw in iter(proc.stdout.readline, ""):
                linea = linea_raw.rstrip("\r\n")
                if linea:
                    ultimas_lineas.append(linea)
                    if len(ultimas_lineas) > 60:
                        ultimas_lineas.pop(0)
                    if on_telemetria is None:
                        print(linea)

                parsed = _parsear_linea_progreso_descarga(linea)
                if parsed and on_telemetria is not None:
                    frag_cur = parsed.get("frag_cur")
                    frag_tot = parsed.get("frag_tot")
                    detalle = (
                        f"Fragmentos {frag_cur}/{frag_tot}"
                        if frag_cur and frag_tot
                        else detalle_default
                    )
                    pct = float(parsed["porcentaje"])
                    _emitir_telemetria(
                        on_telemetria,
                        ultimo_ts,
                        {
                            "etapa": etapa,
                            "titulo_etapa": titulo_etapa,
                            "porcentaje": pct,
                            "velocidad_red": parsed["velocidad_red"],
                            "tamano_total": parsed["tamano_total"],
                            "eta": parsed["eta"],
                            "detalle": detalle,
                        },
                        forzar=(pct >= 100.0),
                    )

        returncode = proc.wait()
    finally:
        _terminar_proceso_seguro(proc)
        _cerrar_pipes_proceso(proc)
        _desregistrar_proceso_activo(proc)

    salida_txt = "\n".join(ultimas_lineas)
    if returncode != 0:
        raise subprocess.CalledProcessError(returncode, comando, output=salida_txt, stderr=salida_txt)
    return salida_txt


def extraer_audio(
    url: str,
    job_dir: Optional[Path | str] = None,
    on_telemetria: Optional[Callable[[Dict[str, Any]], None]] = None,
    on_log: Optional[Callable[[str], None]] = None,
) -> str:
    """Extrae audio mono 12kHz/24k mediante descarga paralela yt-dlp (--newline) y fallback FFmpeg streaming."""
    def _log(msg: str) -> None:
        if on_log is not None:
            on_log(msg)
        else:
            print(msg)

    _log("\n[1/4] Extrayendo audio para análisis con IA...")
    directorio = Path(job_dir).resolve() if job_dir else BASE_DIR
    directorio.mkdir(parents=True, exist_ok=True)

    ruta_local_entrada = Path(url)
    try:
        es_archivo_local = bool(str(url or "").strip()) and ruta_local_entrada.is_file()
    except OSError:
        es_archivo_local = False

    audio_salida = directorio / "temp_audio.mp3"
    for patron in (str(directorio / "temp_audio.*"), str(directorio / "temp_audio_chunk_*.mp3")):
        for viejo in glob.glob(patron):
            try:
                if es_archivo_local and Path(viejo).resolve() == ruta_local_entrada.resolve():
                    continue
                os.remove(viejo)
            except OSError:
                pass

    if es_archivo_local:
        ruta_local_res = ruta_local_entrada.resolve()
        _log(f"Extrayendo audio local desde archivo fuente: {ruta_local_entrada.name}")
        _emitir_telemetria(
            on_telemetria,
            [0.0],
            {
                "etapa": "descarga",
                "titulo_etapa": "Extrayendo Audio Local",
                "porcentaje": 0.0,
                "velocidad_red": "Local",
                "tamano_total": "--",
                "eta": "00:00",
                "detalle": ruta_local_entrada.name,
            },
            forzar=True,
        )
        if ruta_local_res != audio_salida.resolve():
            comando_local = [
                "ffmpeg",
                "-y",
                "-hide_banner",
                "-loglevel",
                "error",
                "-i",
                str(ruta_local_res),
                "-vn",
                "-ac",
                "1",
                "-ar",
                "12000",
                "-b:a",
                "24k",
                str(audio_salida),
            ]
            _ejecutar_comando_con_captura(comando_local)
        if audio_salida.exists() and audio_salida.stat().st_size > 0:
            _emitir_telemetria(
                on_telemetria,
                [0.0],
                {
                    "etapa": "descarga",
                    "titulo_etapa": "Audio Extraído con Éxito",
                    "porcentaje": 100.0,
                    "velocidad_red": "Completado",
                    "tamano_total": f"{audio_salida.stat().st_size / (1024 * 1024):.2f}MiB",
                    "eta": "00:00",
                    "detalle": "Pista de audio local lista para IA",
                },
                forzar=True,
            )
            return str(audio_salida.resolve())
        raise RuntimeError(f"No se pudo extraer audio desde archivo local: {ruta_local_entrada}")

    # Intento primario: descarga paralela agresiva con yt-dlp (--concurrent-fragments 16 y aria2c opcional)
    salida_template = str(directorio / "temp_audio.%(ext)s")
    comando_primario = [
        sys.executable,
        "-m",
        "yt_dlp",
        "--newline",
        "--progress",
        "--js-runtimes",
        "node",
        "--remote-components",
        "ejs:github",
        "--no-playlist",
        "--force-overwrites",
        "--concurrent-fragments",
        "16",
        "--retries",
        "10",
        "--fragment-retries",
        "10",
        "--retry-sleep",
        "fragment:exp=1:10",
        "--socket-timeout",
        "15",
        "--buffer-size",
        "16K",
        "--http-chunk-size",
        "10M",
    ]
    if shutil.which("aria2c") and not _es_stream_hls_kick_o_twitch(url):
        comando_primario.extend(
            [
                "--downloader",
                "aria2c",
                "--downloader-args",
                "aria2c:-x 16 -s 16 -k 1M",
            ]
        )
    comando_primario.extend(
        [
            "-f",
            FORMATOS_AUDIO_DIRECTO,
            "-x",
            "--audio-format",
            "mp3",
            "--postprocessor-args",
            "ffmpeg:-vn -ac 1 -ar 12000 -b:a 24k",
            "-o",
            salida_template,
            url,
        ]
    )

    try:
        _log("Descargando y extrayendo audio en paralelo con yt-dlp (16 hilos)...")
        _emitir_telemetria(
            on_telemetria,
            [0.0],
            {
                "etapa": "descarga",
                "titulo_etapa": "Descargando Audio del Stream (16 Hilos)",
                "porcentaje": 0.0,
                "velocidad_red": "--",
                "tamano_total": "--",
                "eta": "--:--",
                "detalle": "Conectando con servidor fuente...",
            },
            forzar=True,
        )
        _ejecutar_descarga_con_telemetria(
            comando_primario,
            on_telemetria=on_telemetria,
            etapa="descarga",
            titulo_etapa="Descargando Audio del Stream (16 Hilos)",
            detalle_default="Descarga paralela activa",
        )
        if audio_salida.exists() and audio_salida.stat().st_size > 10_240:
            _emitir_telemetria(
                on_telemetria,
                [0.0],
                {
                    "etapa": "descarga",
                    "titulo_etapa": "Audio Extraído con Éxito",
                    "porcentaje": 100.0,
                    "velocidad_red": "Completado",
                    "tamano_total": f"{audio_salida.stat().st_size / (1024 * 1024):.2f}MiB",
                    "eta": "00:00",
                    "detalle": "Pista de audio lista para IA",
                },
                forzar=True,
            )
            return str(audio_salida.resolve())
        tam = audio_salida.stat().st_size if audio_salida.exists() else 0
        raise RuntimeError(
            f"El archivo generado por yt-dlp es demasiado pequeño o inválido ({tam} bytes <= 10 KB)."
        )
    except Exception as e:
        _log(
            f"[AVISO] Extracción paralela con yt-dlp falló ({e}); "
            "activando fallback automático con streaming directo FFmpeg..."
        )
        for resto in glob.glob(str(directorio / "temp_audio.*")):
            try:
                os.remove(resto)
            except OSError:
                pass

    # Fallback automático: streaming directo FFmpeg con reconexión
    _log("Consultando URL directa de audio/menor resolución con yt-dlp -g...")
    stream_url = _obtener_url_audio_directo(url)
    comando_ffmpeg = [
        "ffmpeg",
        "-hide_banner",
        "-loglevel",
        "warning",
        "-progress",
        "pipe:1",
        "-nostats",
        "-y",
    ]
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
            "12000",
            "-b:a",
            "24k",
            str(audio_salida),
        ]
    )
    _log("Extrayendo pista de audio directa por streaming con FFmpeg...")

    def _on_prog_ffmpeg_audio(prog: Dict[str, Any]) -> None:
        if on_telemetria is None:
            return
        on_telemetria(
            {
                "etapa": "descarga",
                "titulo_etapa": "Extrayendo Audio (Fallback FFmpeg Streaming)",
                "porcentaje": prog["porcentaje"],
                "velocidad_red": prog["speed_str"],
                "tamano_total": prog.get("size_str", "--"),
                "eta": prog["eta_str"],
                "velocidad_x": prog["speed_str"],
                "detalle": f"Streaming directo FFmpeg • t={prog['out_time_str']}",
            }
        )

    _ejecutar_comando_con_captura(
        comando_ffmpeg,
        duracion_objetivo=None,
        on_progreso=_on_prog_ffmpeg_audio if on_telemetria is not None else None,
    )
    if not audio_salida.exists() or audio_salida.stat().st_size <= 0:
        raise FileNotFoundError(f"No se generó el archivo de audio esperado: {audio_salida}")
    return str(audio_salida.resolve())


def construir_prompt_viral(duracion_total: Optional[float] = None) -> str:
    """Construye el prompt multiplataforma (YouTube Shorts + TikTok 2026) con transcripción fonética forense y curaduría dinámica."""
    info_duracion = (
        f"\nDURACIÓN TOTAL DE ESTE AUDIO: {segundos_a_hhmmss(duracion_total)} "
        "(JAMÁS generes timestamps `inicio` o `fin` superiores a este límite)."
        if duracion_total
        else ""
    )
    return f"""Actúa como un Senior Growth Hacker, estratega de algoritmos de YouTube Shorts / TikTok (2026), transcriptor fonético forense y editor experto en el ecosistema de IRL y streaming de Colombia (WestCOL, MrStivenTC, Blessd, La Liendra, Yhap, eldomi, eventos IRL y polémicas).

Analiza el audio adjunto y extrae ÚNICAMENTE los segmentos con verdadero potencial de viralidad y alta retención de audiencia.{info_duracion}

### 1. CANTIDAD DINÁMICA DE CLIPS (CALIDAD Y RETENCIÓN PRIMERO):
- NO existe un número mínimo ni máximo de clips a extraer.
- Extrae tantos o tan pocos clips como justifique la calidad real del contenido (pueden ser 1, 4, 8 o los que realmente valgan la pena).
- Prohibido rellenar con clips aburridos o tiempos muertos: cada clip seleccionado debe tener un pico emocional, cómico, polémico o narrativo capaz de retener a la audiencia de principio a fin.

### 2. REGLA DEL PRIMER SEGUNDO Y DURACIÓN ESTRATÉGICA:
- Abre inmediatamente en el pico de tensión, confesión o curiosidad (0.0s de introducción muerta) para vencer la tasa de deslizamiento (swipe-away rate).
- Duración adaptada a retención: prioriza clips de 22-45 segundos (retención explosiva en Shorts) o de 60-75 segundos (arcos narrativos completos con clímax para TikTok Creator Rewards). Jamás cortes una frase o remate a la mitad.
- Estructura de Bucle (Seamless Loop): busca que el cierre del clip conecte de forma natural con la frase inicial.

### 3. PRECISIÓN FORENSE EN SUBTÍTULOS (CERO ALUCINACIONES):
- Transcribe LITERALMENTE lo que se escucha en el audio. Está ESTRICTAMENTE PROHIBIDO inventar frases, parafrasear, resumir o adivinar palabras que no se pronunciaron.
- Respeta la jerga colombiana real pronunciada en el audio (ej. "gonorrea", "parce", "chimba", "pirobo", "sisas", "nea", "marica") sin sustituirla por palabras neutras inventadas.
- Si hay ruido, música alta o voces superpuestas ininteligibles en un segundo específico, omite ese segundo en vez de alucinar texto.
- Divide el atributo `subtitulos` en bloques dinámicos de lectura rápida (ESTRICTAMENTE de 2 a 4 palabras por bloque, máximo 22 caracteres por segmento, SIN EMOJIS) con `inicio_rel` y `fin_rel` exactos en segundos respecto al inicio del clip (`0.0`), en orden cronológico y sin solapamientos.

### 4. METADATOS SEPARADOS Y OBLIGATORIOS POR CLIP:
- YouTube Shorts: `titulo` (máx 60 chars), `descripcion` (2 líneas con gancho + CTA + #Shorts), `etiquetas` (8-12 tags SEO).
- TikTok: `caption_tiktok` (máx 150 chars optimizado para SEO semántico y debate en comentarios), `hashtags_tiktok` (3 a 5 tags exactos mezclando nicho y alcance), `gancho_visual_portada` (titular impactante de 4-6 palabras).
- Común: `id` (entero secuencial), `inicio` y `fin` (`HH:MM:SS`), `gancho`, `razon_viral`, `subtitulos`."""


def _guardar_y_sincronizar_clips(clips: List[dict], job_dir: Optional[Path | str] = None):
    """Guarda clips.json en el job_dir (si aplica) y mantiene sincronizado BASE_DIR / 'clips.json' de forma atómica."""
    with _CLIPS_JSON_LOCK:
        if job_dir:
            jdir = Path(job_dir).resolve()
            jdir.mkdir(parents=True, exist_ok=True)
            _escribir_json_atomico(jdir / "clips.json", clips)

        _escribir_json_atomico(BASE_DIR / "clips.json", clips)


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


def _es_error_cuota_diaria_free_tier(error: APIError) -> bool:
    """Detecta si un APIError 429 corresponde a agotamiento de cuota diaria gratuita (Free Tier)."""
    codigo = getattr(error, "code", None)
    if str(codigo) != "429":
        return False
    texto = f"{error} {getattr(error, 'message', '') or ''}"
    texto_lower = texto.lower()
    if any(ind in texto_lower for ind in ("free_tier_requests", "perday", "per day")):
        return True
    return bool(re.search(r"limit:\s*20(?!\d)", texto_lower))


def _segmentar_audio_en_chunks(
    ruta_audio: str | Path,
    duracion_total: float,
    max_duracion_chunk: int = 1500,
    solapamiento: int = 60,
) -> List[Tuple[str, float, float]]:
    """Divide audios mayores a 30 min (>1800s) en bloques de 25 min con 60s de solapamiento usando ffmpeg -c copy."""
    ruta_src = Path(ruta_audio)
    if duracion_total <= 1800:
        return [(str(ruta_src), 0.0, float(duracion_total))]

    carpeta = ruta_src.resolve().parent
    paso = max(1, int(max_duracion_chunk) - int(solapamiento))
    chunks: List[Tuple[str, float, float]] = []
    offset = 0.0
    idx = 0

    while offset < duracion_total:
        dur_bloque = min(float(max_duracion_chunk), float(duracion_total) - offset)
        if dur_bloque <= 0:
            break
        ruta_chunk = carpeta / f"temp_audio_chunk_{idx:02d}.mp3"
        comando = [
            "ffmpeg",
            "-hide_banner",
            "-loglevel",
            "error",
            "-y",
            "-ss",
            f"{offset:.3f}",
            "-t",
            f"{dur_bloque:.3f}",
            "-i",
            str(ruta_src),
            "-c",
            "copy",
            str(ruta_chunk),
        ]
        subprocess.run(comando, check=True)
        chunks.append((str(ruta_chunk), float(offset), float(dur_bloque)))
        if offset + dur_bloque >= duracion_total - 0.5:
            break
        offset += paso
        idx += 1

    return chunks


def _acepta_kwarg(fn: Callable[..., Any], nombre: str) -> bool:
    """Verifica de forma segura si un callable acepta cierto argumento por nombre."""
    objetivo = fn
    side_effect = getattr(fn, "side_effect", None)
    if callable(side_effect) and not (isinstance(side_effect, type) and issubclass(side_effect, BaseException)):
        objetivo = side_effect
    try:
        sig = inspect.signature(objetivo)
    except (ValueError, TypeError):
        return False
    for param in sig.parameters.values():
        if param.kind == inspect.Parameter.VAR_KEYWORD or param.name == nombre:
            return True
    return False


def _subir_archivo_gemini_activo(
    client: genai.Client,
    ruta_archivo: str | Path,
    on_log: Optional[Callable[[str], None]] = None,
    on_estado: Optional[Callable[[float, str], None]] = None,
) -> Any:
    """Sube un archivo a Gemini File API con reintentos y espera hasta estado ACTIVE."""
    def _log(msg: str) -> None:
        if on_log is not None:
            on_log(msg)
        else:
            print(msg)

    archivo_subido = None
    for intento_up in range(1, 5):
        try:
            archivo_subido = client.files.upload(file=str(ruta_archivo))
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
        if on_estado is not None:
            on_estado(0.18, f"Procesando audio en File API ({estado})...")
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
                if on_estado is not None:
                    on_estado(
                        min(0.30, 0.18 + intentos_estado * 0.01),
                        f"Esperando File API ({estado})...",
                    )
            except Exception as e_get:
                _log(f"[AVISO] Error transitorio consultando estado del archivo: {e_get}")
        _log("✓ Archivo de audio listo y activo para inferencia.")
        return archivo_subido
    except BaseException:
        _eliminar_archivo_gemini_seguro(client, archivo_subido)
        raise


def _ejecutar_cascada_modelos_gemini(
    client: genai.Client,
    archivo_subido: Any,
    prompt: str,
    response_schema: Any,
    temperature: float,
    parsear_fn: Callable[[str], Any],
    modelo_preferido: Optional[str] = None,
    on_log: Optional[Callable[[str], None]] = None,
    on_modelo_inicio: Optional[Callable[[str], None]] = None,
    on_chunk_texto: Optional[Callable[[str, int], None]] = None,
) -> Tuple[Any, str]:
    """Ejecuta inferencia streaming sobre la cascada MODELOS_CANDIDATOS con salto 0s ante cuota diaria 429."""
    def _log(msg: str) -> None:
        if on_log is not None:
            on_log(msg)
        else:
            print(msg)

    orden_modelos = list(MODELOS_CANDIDATOS)
    if modelo_preferido and modelo_preferido.strip():
        pref = modelo_preferido.strip()
        orden_modelos = [pref] + [m for m in orden_modelos if m != pref]

    resultado = None
    modelo_usado: Optional[str] = None
    max_intentos = 4
    vio_error_429 = False

    for modelo in orden_modelos:
        _log(f"Probando análisis en streaming con: {modelo}...")
        if on_modelo_inicio is not None:
            on_modelo_inicio(modelo)
        for intento in range(1, max_intentos + 1):
            accion_siguiente = (
                "reintentar" if intento < max_intentos else "saltar al siguiente modelo"
            )
            try:
                partes_texto: List[str] = []
                chars_recibidos = 0
                stream = client.models.generate_content_stream(
                    model=modelo,
                    contents=[archivo_subido, prompt],
                    config=types.GenerateContentConfig(
                        response_mime_type="application/json",
                        response_schema=response_schema,
                        temperature=temperature,
                    ),
                )
                for chunk in stream:
                    txt_chunk = getattr(chunk, "text", None)
                    if txt_chunk:
                        partes_texto.append(txt_chunk)
                        chars_recibidos += len(txt_chunk)
                        if on_chunk_texto is not None:
                            on_chunk_texto(modelo, chars_recibidos)

                texto_respuesta = "".join(partes_texto).strip()
                if not texto_respuesta:
                    raise ValueError("Respuesta vacía recibida desde el stream de Gemini.")

                resultado = parsear_fn(texto_respuesta)
                modelo_usado = modelo
                break
            except ServerError as e:
                codigo_err = getattr(e, "code", None) or 503
                msg_srv = (
                    f"[AVISO] Modelo {modelo} falló (código {codigo_err}, "
                    f"intento {intento}/{max_intentos}) antes de {accion_siguiente}: {e}"
                )
                if intento < max_intentos:
                    _esperar_con_jitter(
                        intento,
                        base=4.0,
                        max_espera=25.0,
                        on_log=on_log,
                        contexto=msg_srv,
                    )
                else:
                    _log(msg_srv)
            except APIError as e:
                codigo_err = getattr(e, "code", None) or "APIError"
                detalle_err = getattr(e, "message", None) or str(e)
                if (
                    codigo_err == 429
                    or _es_error_cuota_diaria_free_tier(e)
                    or "RESOURCE_EXHAUSTED" in str(detalle_err).upper()
                ):
                    vio_error_429 = True
                if _es_error_cuota_diaria_free_tier(e):
                    _log(
                        f"[AVISO] Cuota diaria gratuita agotada para {modelo} (código 429, "
                        f"espera 0.00s): saltando inmediatamente al siguiente modelo. Detalle: {detalle_err}"
                    )
                    break
                if codigo_err in (400, 404):
                    _log(
                        f"[AVISO] Modelo {modelo} falló (código {codigo_err}, espera 0.00s "
                        f"antes de saltar al siguiente modelo): {detalle_err}"
                    )
                    break
                if codigo_err in (429, 503):
                    msg_api = (
                        f"[AVISO] Modelo {modelo} falló (código {codigo_err}, "
                        f"intento {intento}/{max_intentos}) antes de {accion_siguiente}: {detalle_err}"
                    )
                    if intento < max_intentos:
                        _esperar_con_jitter(
                            intento,
                            base=4.0,
                            max_espera=25.0,
                            on_log=on_log,
                            contexto=msg_api,
                        )
                    else:
                        _log(msg_api)
                else:
                    _log(
                        f"[AVISO] Modelo {modelo} falló (código {codigo_err}, espera 0.00s "
                        f"antes de saltar al siguiente modelo): {detalle_err}"
                    )
                    break
            except Exception as e:
                codigo_err = type(e).__name__
                msg_err = str(e)
                if "429" in msg_err or "RESOURCE_EXHAUSTED" in msg_err.upper():
                    vio_error_429 = True
                msg_gen = (
                    f"[AVISO] Modelo {modelo} falló (error {codigo_err}, "
                    f"intento {intento}/{max_intentos}) antes de {accion_siguiente}: {e}"
                )
                if intento < max_intentos:
                    _esperar_con_jitter(
                        intento,
                        base=4.0,
                        max_espera=25.0,
                        on_log=on_log,
                        contexto=msg_gen,
                    )
                else:
                    _log(msg_gen)
        if resultado is not None:
            break

    if resultado is None or modelo_usado is None:
        if vio_error_429:
            raise GeminiQuotaExhaustedError(
                "Cuota diaria / límites 429 de Gemini agotados en todos los modelos candidatos."
            )
        raise RuntimeError("No se pudo obtener una respuesta JSON válida de los modelos disponibles.")
    return resultado, modelo_usado


def _analizar_archivo_audio_gemini(
    client: genai.Client,
    ruta_archivo: str | Path,
    duracion_bloque: Optional[float],
    modelo_preferido: Optional[str] = None,
    on_log: Optional[Callable[[str], None]] = None,
    on_telemetria: Optional[Callable[[Dict[str, Any]], None]] = None,
    bloque_actual: int = 1,
    total_bloques: int = 1,
) -> List[dict]:
    """Sube un archivo/chunk a Gemini File API, espera ACTIVE, ejecuta cascada de modelos y limpia el remoto."""
    def _log(msg: str) -> None:
        if on_log is not None:
            on_log(msg)
        else:
            print(msg)

    ultimo_ts_tele = [0.0]
    total_b = max(1, int(total_bloques or 1))
    bloque_i = max(1, min(total_b, int(bloque_actual or 1)))
    base_pct = ((bloque_i - 1) / total_b) * 100.0
    span_pct = 100.0 / total_b

    def _emitir_gem(frac_bloque: float, modelo_act: str, detalle: str, forzar: bool = False) -> None:
        pct = round(min(100.0, max(0.0, base_pct + span_pct * max(0.0, min(1.0, frac_bloque)))), 1)
        _emitir_telemetria(
            on_telemetria,
            ultimo_ts_tele,
            {
                "etapa": "gemini",
                "titulo_etapa": f"Analizando Narrativa Viral ({modelo_act})",
                "porcentaje": pct,
                "bloque_actual": bloque_i,
                "total_bloques": total_b,
                "modelo_ia": modelo_act,
                "eta": "--:--",
                "detalle": f"Bloque {bloque_i}/{total_b} • {detalle}",
            },
            forzar=forzar,
        )

    modelo_inicial = (modelo_preferido or MODELOS_CANDIDATOS[0]).strip()
    _emitir_gem(0.05, modelo_inicial, "Subiendo audio a Gemini File API...", forzar=True)

    archivo_subido = _subir_archivo_gemini_activo(
        client,
        ruta_archivo,
        on_log=on_log,
        on_estado=lambda frac, det: _emitir_gem(frac, modelo_inicial, det, forzar=(frac <= 0.2)),
    )

    try:
        prompt = construir_prompt_viral(duracion_bloque)
        clips, modelo_usado = _ejecutar_cascada_modelos_gemini(
            client=client,
            archivo_subido=archivo_subido,
            prompt=prompt,
            response_schema=list[ClipViral],
            temperature=0.20,
            parsear_fn=lambda txt: _limpiar_y_parsear_json(
                txt,
                duracion_total=duracion_bloque,
                permitir_vacio=True,
            ),
            modelo_preferido=modelo_preferido,
            on_log=on_log,
            on_modelo_inicio=lambda mod: _emitir_gem(
                0.35, mod, f"Iniciando inferencia streaming ({mod})...", forzar=True
            ),
            on_chunk_texto=lambda mod, chars: _emitir_gem(
                min(0.92, 0.40 + (chars / 8000.0) * 0.52),
                mod,
                f"Recibiendo respuesta JSON ({chars} chars)...",
            ),
        )
        _log(f"✓ Análisis generado con éxito usando {modelo_usado} ({len(clips)} clips)")
        _emitir_gem(1.0, modelo_usado, f"Completado con {modelo_usado} ({len(clips)} clips)", forzar=True)

        for c in clips:
            c["modelo_ia"] = modelo_usado
        return clips
    finally:
        _eliminar_archivo_gemini_seguro(client, archivo_subido)


def _puntaje_calidad_clip(clip: dict, duracion: float) -> Tuple[float, int, int]:
    """Calcula un puntaje determinista para resolver solapamientos priorizando duración y completitud."""
    subs = len(clip.get("subtitulos") or [])
    texto_meta = len(str(clip.get("razon_viral") or "")) + len(str(clip.get("gancho") or ""))
    return (round(duracion, 3), subs, texto_meta)


def _deduplicar_clips_solapados(clips: List[dict]) -> List[dict]:
    """Fusiona/deduplica clips que se solapan >50% tras analizar chunks contiguos y reasigna IDs secuenciales."""
    if not clips:
        return []

    con_rango: List[Tuple[float, float, dict]] = []
    for clip in clips:
        try:
            ini_s = hhmmss_a_segundos(clip["inicio"])
            fin_s = hhmmss_a_segundos(clip["fin"])
        except (KeyError, ValueError, TypeError):
            continue
        if fin_s - ini_s < 5:
            continue
        con_rango.append((ini_s, fin_s, dict(clip)))

    con_rango.sort(key=lambda item: (item[0], item[1]))

    aceptados: List[Tuple[float, float, dict]] = []
    for ini_cand, fin_cand, cand in con_rango:
        dur_cand = fin_cand - ini_cand
        reemplazado = False
        descartar = False

        for idx_prev in range(len(aceptados) - 1, -1, -1):
            ini_prev, fin_prev, prev = aceptados[idx_prev]
            if fin_prev <= ini_cand:
                break
            interseccion = max(0.0, min(fin_prev, fin_cand) - max(ini_prev, ini_cand))
            dur_prev = fin_prev - ini_prev
            min_dur = min(dur_prev, dur_cand)
            if min_dur > 0 and (interseccion / min_dur) > 0.5:
                if _puntaje_calidad_clip(cand, dur_cand) > _puntaje_calidad_clip(prev, dur_prev):
                    aceptados[idx_prev] = (ini_cand, fin_cand, cand)
                    reemplazado = True
                else:
                    descartar = True
                break

        if not reemplazado and not descartar:
            aceptados.append((ini_cand, fin_cand, cand))

    aceptados.sort(key=lambda item: (item[0], item[1]))
    resultado: List[dict] = []
    for idx_nuevo, (_, _, clip_final) in enumerate(aceptados, start=1):
        clip_final["id"] = idx_nuevo
        resultado.append(clip_final)
    return resultado


def analizar_con_gemini(
    ruta_audio: str | Path,
    duracion_total: Optional[float] = None,
    modelo_preferido: Optional[str] = None,
    job_dir: Optional[Path | str] = None,
    on_log: Optional[Callable[[str], None]] = None,
    on_telemetria: Optional[Callable[[Dict[str, Any]], None]] = None,
) -> List[dict]:
    """Segmenta audios largos (>30 min), analiza bloques en paralelo con Gemini File API y guarda clips.json."""
    log_lock = threading.Lock()

    def _log(msg: str) -> None:
        with log_lock:
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

    duracion_efectiva: Optional[float] = (
        float(duracion_total)
        if duracion_total is not None
        else obtener_duracion_media(ruta_audio)
    )

    modelo_label = (modelo_preferido or MODELOS_CANDIDATOS[0]).strip()
    _emitir_telemetria(
        on_telemetria,
        [0.0],
        {
            "etapa": "gemini",
            "titulo_etapa": f"Preparando Análisis IA ({modelo_label})",
            "porcentaje": 0.0,
            "bloque_actual": 1,
            "bloques_completados": 0,
            "total_bloques": 1,
            "bloques_activos": [],
            "modelo_ia": modelo_label,
            "eta": "--:--",
            "detalle": "Evaluando duración de pista para segmentación...",
        },
        forzar=True,
    )

    chunks_temporales: List[str] = []
    try:
        if duracion_efectiva is not None:
            chunks = _segmentar_audio_en_chunks(ruta_audio, duracion_efectiva)
        else:
            chunks = [(str(ruta_audio), 0.0, None)]

        chunks_temporales = [
            ruta_c
            for ruta_c, _, _ in chunks
            if str(ruta_c) != str(ruta_audio) and Path(ruta_c).name.startswith("temp_audio_chunk_")
        ]

        if len(chunks) > 1 and duracion_efectiva is not None:
            _log(
                f"Audio de {segundos_a_hhmmss(duracion_efectiva)} (> 30 min): "
                f"segmentando en {len(chunks)} bloques de hasta 25 min con 60s de solapamiento (máx. 3 en paralelo)..."
            )

        total_bloques = len(chunks)
        acepta_tele = _acepta_kwarg(_analizar_archivo_audio_gemini, "on_telemetria")
        tele_lock = threading.Lock()
        ultimo_ts_tele = [0.0]
        bloques_completados = 0
        bloques_activos_map: Dict[int, str] = {}
        clips_acumulados: List[dict] = []
        errores_por_bloque: List[Tuple[int, Exception]] = []

        def _construir_estado_telemetria(
            idx_ref: int,
            modelo_act: str,
            detalle: str,
        ) -> Dict[str, Any]:
            activos = [bloques_activos_map[k] for k in sorted(bloques_activos_map)]
            pct = round(min(100.0, max(0.0, (bloques_completados / max(1, total_bloques)) * 100.0)), 1)
            return {
                "etapa": "gemini",
                "titulo_etapa": f"Analizando Narrativa Viral ({modelo_act})",
                "porcentaje": pct,
                "bloque_actual": idx_ref,
                "bloques_completados": bloques_completados,
                "total_bloques": total_bloques,
                "bloques_activos": activos,
                "modelo_ia": modelo_act,
                "eta": "--:--",
                "detalle": detalle,
            }

        def _emitir_bloque_seguro(
            idx_ref: int,
            modelo_act: str,
            detalle: str,
            forzar: bool = False,
        ) -> None:
            if on_telemetria is None:
                return
            with tele_lock:
                datos = _construir_estado_telemetria(idx_ref, modelo_act, detalle)
                _emitir_telemetria(on_telemetria, ultimo_ts_tele, datos, forzar=forzar)

        def _procesar_bloque(
            idx_chunk: int,
            ruta_chunk: str,
            offset_seg: float,
            dur_chunk: Optional[float],
        ) -> None:
            nonlocal bloques_completados
            etiqueta_bloque = f"Bloque {idx_chunk}/{total_bloques}"
            if len(chunks) > 1 and dur_chunk is not None:
                _log(
                    f"Analizando bloque {idx_chunk}/{total_bloques} "
                    f"[{segundos_a_hhmmss(offset_seg)} -> {segundos_a_hhmmss(offset_seg + dur_chunk)}]..."
                )

            with tele_lock:
                bloques_activos_map[idx_chunk] = etiqueta_bloque
                activos_txt = ", ".join(bloques_activos_map[k] for k in sorted(bloques_activos_map))
                rango_txt = (
                    f" [{segundos_a_hhmmss(offset_seg)} → {segundos_a_hhmmss(offset_seg + dur_chunk)}]"
                    if dur_chunk is not None
                    else ""
                )
                datos_ini = _construir_estado_telemetria(
                    idx_chunk,
                    modelo_label,
                    f"En curso: {activos_txt}{rango_txt}",
                )
                _emitir_telemetria(on_telemetria, ultimo_ts_tele, datos_ini, forzar=True)

            def _on_tele_worker(datos_sub: Dict[str, Any]) -> None:
                mod_sub = str(datos_sub.get("modelo_ia") or modelo_label)
                det_sub = str(datos_sub.get("detalle") or etiqueta_bloque)
                _emitir_bloque_seguro(idx_chunk, mod_sub, det_sub, forzar=False)

            clips_chunk: List[dict] = []
            try:
                if acepta_tele:
                    clips_chunk = _analizar_archivo_audio_gemini(
                        client,
                        ruta_chunk,
                        dur_chunk,
                        modelo_preferido,
                        _log,
                        on_telemetria=_on_tele_worker,
                        bloque_actual=idx_chunk,
                        total_bloques=total_bloques,
                    )
                else:
                    clips_chunk = _analizar_archivo_audio_gemini(
                        client,
                        ruta_chunk,
                        dur_chunk,
                        modelo_preferido,
                        _log,
                    )
            except Exception as e_chunk:
                with tele_lock:
                    errores_por_bloque.append((idx_chunk, e_chunk))
                    bloques_activos_map.pop(idx_chunk, None)
                    bloques_completados += 1
                    datos_err = _construir_estado_telemetria(
                        idx_chunk,
                        modelo_label,
                        f"{etiqueta_bloque} falló ({type(e_chunk).__name__})",
                    )
                    _emitir_telemetria(on_telemetria, ultimo_ts_tele, datos_err, forzar=True)
                if len(chunks) > 1:
                    _log(f"[AVISO] Falló análisis del {etiqueta_bloque}: {e_chunk}")
                return

            clips_bloque_ajustados: List[dict] = []
            for clip in clips_chunk:
                try:
                    ini_abs = max(0.0, hhmmss_a_segundos(clip["inicio"]) + offset_seg)
                    fin_abs = max(0.0, hhmmss_a_segundos(clip["fin"]) + offset_seg)
                except (KeyError, ValueError, TypeError):
                    continue

                if duracion_efectiva is not None:
                    if ini_abs >= duracion_efectiva - 2:
                        continue
                    fin_abs = min(fin_abs, duracion_efectiva)

                dur_clip_abs = fin_abs - ini_abs
                if dur_clip_abs < 5:
                    continue

                clip_ajustado = dict(clip)
                clip_ajustado["inicio"] = segundos_a_hhmmss(ini_abs)
                clip_ajustado["fin"] = segundos_a_hhmmss(fin_abs)
                dur_normalizada = max(
                    0.0,
                    hhmmss_a_segundos(clip_ajustado["fin"]) - hhmmss_a_segundos(clip_ajustado["inicio"]),
                )
                clip_ajustado["duracion_segundos"] = int(round(dur_normalizada))
                # Subtítulos usan inicio_rel/fin_rel respecto al clip; NO sumar offset_seg del stream
                subs_validados = _normalizar_subtitulos(
                    clip_ajustado.get("subtitulos"), dur_normalizada
                )
                clip_ajustado["subtitulos"] = [s.model_dump() for s in subs_validados]
                clips_bloque_ajustados.append(clip_ajustado)

            with tele_lock:
                clips_acumulados.extend(clips_bloque_ajustados)
                bloques_activos_map.pop(idx_chunk, None)
                bloques_completados += 1
                activos_rest = [bloques_activos_map[k] for k in sorted(bloques_activos_map)]
                sufijo = f" • Activos: {', '.join(activos_rest)}" if activos_rest else ""
                datos_fin = _construir_estado_telemetria(
                    idx_chunk,
                    modelo_label,
                    f"{etiqueta_bloque} completado ({len(clips_chunk)} clips){sufijo}",
                )
                _emitir_telemetria(on_telemetria, ultimo_ts_tele, datos_fin, forzar=True)

        with concurrent.futures.ThreadPoolExecutor(max_workers=3) as executor:
            futuros = [
                executor.submit(_procesar_bloque, idx_c, ruta_c, off_c, dur_c)
                for idx_c, (ruta_c, off_c, dur_c) in enumerate(chunks, start=1)
            ]
            for fut in futuros:
                fut.result()

        if len(chunks) == 1 and errores_por_bloque:
            raise errores_por_bloque[0][1]

        clips_finales = _deduplicar_clips_solapados(clips_acumulados)
        if not clips_finales:
            if errores_por_bloque:
                raise errores_por_bloque[-1][1]
            raise RuntimeError("No se detectaron clips virales válidos en ninguno de los bloques del audio.")

        _guardar_y_sincronizar_clips(clips_finales, job_dir=job_dir)
        _log(f"✓ Se detectaron {len(clips_finales)} momentos virales con SEO completo y se guardaron en clips.json")
        return clips_finales
    finally:
        _cerrar_cliente_genai_seguro(client)
        for ruta_c in chunks_temporales:
            try:
                if os.path.exists(ruta_c):
                    os.remove(ruta_c)
            except OSError:
                pass
        carpeta_audio = Path(ruta_audio).resolve().parent
        for resto_chunk in glob.glob(str(carpeta_audio / "temp_audio_chunk_*.mp3")):
            if str(resto_chunk) != str(Path(ruta_audio).resolve()):
                try:
                    os.remove(resto_chunk)
                except OSError:
                    pass


def _resolver_ollama_url() -> str:
    """Resuelve la URL base de Ollama respetando OLLAMA_HOST o OLLAMA_BASE_URL."""
    raw = (os.environ.get("OLLAMA_HOST") or OLLAMA_BASE_URL or "http://127.0.0.1:11434").strip()
    if "://" not in raw:
        raw = f"http://{raw}"
    return raw.rstrip("/")


def _normalizar_modelo_ollama(nombre: Optional[str]) -> str:
    """Devuelve un nombre de modelo Ollama válido priorizando el valor por defecto v4.1."""
    limpio = str(nombre or "").strip()
    return limpio or MODELOS_LOCALES_OLLAMA[0]


def _modelo_instalado_en_ollama(modelo: str, instalados: Sequence[str]) -> bool:
    """Comprueba coincidencia exacta o con sufijo ':latest' dentro de los tags instalados."""
    objetivo = modelo.strip()
    conjunto = {str(m).strip() for m in instalados if str(m).strip()}
    if objetivo in conjunto:
        return True
    if f"{objetivo}:latest" in conjunto:
        return True
    if objetivo.endswith(":latest") and objetivo[:-7] in conjunto:
        return True
    return False


def listar_modelos_ollama_disponibles() -> List[str]:
    """Lista los modelos instalados en Ollama priorizando MODELOS_LOCALES_OLLAMA sin lanzar excepciones."""
    url = f"{_resolver_ollama_url()}/api/tags"
    try:
        req = urllib.request.Request(url, method="GET")
        with urllib.request.urlopen(req, timeout=2.0) as resp:
            payload = json.loads(resp.read().decode("utf-8", errors="replace"))
    except Exception:
        return list(MODELOS_LOCALES_OLLAMA)

    crudos: List[str] = []
    for item in payload.get("models", []) if isinstance(payload, dict) else []:
        if not isinstance(item, dict):
            continue
        nombre = str(item.get("name") or item.get("model") or "").strip()
        if nombre and nombre not in crudos:
            crudos.append(nombre)

    if not crudos:
        return list(MODELOS_LOCALES_OLLAMA)

    ordenados: List[str] = []
    for pref in MODELOS_LOCALES_OLLAMA:
        for candidato in crudos:
            if candidato == pref or candidato == f"{pref}:latest":
                if candidato not in ordenados:
                    ordenados.append(candidato)
                break
    for restante in crudos:
        if "embed" in restante.lower():
            continue
        if restante not in ordenados:
            ordenados.append(restante)
    return ordenados or list(MODELOS_LOCALES_OLLAMA)


def _asegurar_modelo_ollama(
    modelo_local: str,
    on_log: Optional[Callable[[str], None]] = None,
) -> None:
    """Verifica conexión con Ollama y descarga automáticamente el modelo si aún no está en disco."""
    def _log(msg: str) -> None:
        if on_log is not None:
            on_log(msg)
        else:
            print(msg)

    modelo = _normalizar_modelo_ollama(modelo_local)
    base_url = _resolver_ollama_url()
    tags_url = f"{base_url}/api/tags"
    try:
        req = urllib.request.Request(tags_url, method="GET")
        with urllib.request.urlopen(req, timeout=3.0) as resp:
            payload = json.loads(resp.read().decode("utf-8", errors="replace"))
    except Exception as e:
        raise RuntimeError(
            "Ollama no está activo en 127.0.0.1:11434. Inícialo con 'ollama serve' o 'systemctl start ollama'."
        ) from e

    instalados = [
        str(m.get("name") or m.get("model") or "").strip()
        for m in (payload.get("models", []) if isinstance(payload, dict) else [])
        if isinstance(m, dict)
    ]
    if _modelo_instalado_en_ollama(modelo, instalados):
        return

    _log(f"Modelo Ollama '{modelo}' no encontrado en disco. Ejecutando descarga automática (/api/pull)...")
    pull_req = urllib.request.Request(
        f"{base_url}/api/pull",
        data=json.dumps({"name": modelo, "stream": True}).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    ultimo_pct_log = -10
    ultimo_estado = ""
    with urllib.request.urlopen(pull_req, timeout=1800.0) as resp:
        for raw_line in resp:
            linea = raw_line.decode("utf-8", errors="replace").strip()
            if not linea:
                continue
            try:
                evento = json.loads(linea)
            except json.JSONDecodeError:
                continue
            if evento.get("error"):
                raise RuntimeError(f"Error descargando modelo Ollama '{modelo}': {evento['error']}")
            estado = str(evento.get("status") or "").strip()
            total_b = evento.get("total")
            comp_b = evento.get("completed")
            if isinstance(total_b, (int, float)) and total_b > 0 and isinstance(comp_b, (int, float)):
                pct = int(round((comp_b / total_b) * 100))
                if pct >= ultimo_pct_log + 10 or pct >= 100:
                    ultimo_pct_log = pct
                    _log(f"  Descargando {modelo}: {pct}% ({estado})")
            elif estado and estado != ultimo_estado:
                ultimo_estado = estado
                _log(f"  Ollama pull {modelo}: {estado}")
    _log(f"✓ Modelo Ollama '{modelo}' descargado y listo.")


def _descargar_modelo_ollama_ram(
    modelo_local: str,
    on_log: Optional[Callable[[str], None]] = None,
) -> None:
    """Fuerza la descarga de RAM del modelo Ollama mediante keep_alive=0 antes de lanzar FFmpeg."""
    modelo = _normalizar_modelo_ollama(modelo_local)
    base_url = _resolver_ollama_url()
    try:
        req = urllib.request.Request(
            f"{base_url}/api/generate",
            data=json.dumps(
                {"model": modelo, "prompt": "", "keep_alive": 0, "stream": False}
            ).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=10.0) as resp:
            resp.read()
        msg = f"Memoria RAM de Ollama liberada tras análisis ({modelo}, keep_alive=0)."
        if on_log is not None:
            on_log(msg)
        else:
            print(msg)
    except Exception:
        pass
    finally:
        gc.collect()


def _calcular_energia_segmentos_audio(
    ruta_audio: str,
    segmentos: List[Dict[str, Any]],
) -> Set[int]:
    """Calcula RMS PCM mono 12kHz por segmento y detecta picos vocales >= 1.65x mediana global."""
    if not segmentos or not ruta_audio:
        return set()

    sr = 12000
    comando = [
        "ffmpeg",
        "-hide_banner",
        "-loglevel",
        "error",
        "-i",
        str(ruta_audio),
        "-f",
        "s16le",
        "-ac",
        "1",
        "-ar",
        str(sr),
        "-",
    ]
    try:
        proc = subprocess.run(comando, capture_output=True, check=False, timeout=300)
    except (OSError, subprocess.SubprocessError):
        return set()

    if proc.returncode != 0 or not proc.stdout:
        return set()

    n_bytes = len(proc.stdout) - (len(proc.stdout) % 2)
    if n_bytes < 2:
        return set()

    muestras = array.array("h")
    muestras.frombytes(proc.stdout[:n_bytes])
    del proc
    if sys.byteorder != "little":
        muestras.byteswap()

    total_muestras = len(muestras)
    rms_por_seg: List[float] = []
    for seg in segmentos:
        try:
            ini = float(seg.get("start", 0.0) or 0.0)
            fin = float(seg.get("end", ini) or ini)
        except (TypeError, ValueError):
            rms_por_seg.append(0.0)
            continue
        i0 = max(0, min(total_muestras, int(ini * sr)))
        i1 = max(i0, min(total_muestras, int(fin * sr)))
        n = i1 - i0
        if n <= 0:
            rms_por_seg.append(0.0)
            continue
        tramo = muestras[i0:i1]
        energia = sum(map(int.__mul__, tramo, tramo)) / n
        rms_por_seg.append(math.sqrt(energia))
    del muestras

    positivos = [r for r in rms_por_seg if r > 0.0]
    if not positivos:
        return set()

    mediana_global = statistics.median(positivos)
    if mediana_global <= 0.0:
        return set()

    umbral = mediana_global * 1.65
    return {idx for idx, rms in enumerate(rms_por_seg) if rms >= umbral and rms > 0.0}


def _decodificar_audio_pcm_16k(ruta_audio: str) -> Any:
    """Decodifica audio a mono float32 16 kHz vía FFmpeg para evitar bugs de PyAV >= 19 en faster-whisper."""
    try:
        ruta_obj = Path(ruta_audio)
        if not ruta_obj.is_file() or ruta_obj.stat().st_size < 64:
            return ruta_audio
        import numpy as np  # dependencia transitiva de faster-whisper
    except (OSError, ImportError):
        return ruta_audio

    try:
        proc = subprocess.run(
            [
                "ffmpeg",
                "-hide_banner",
                "-loglevel",
                "error",
                "-i",
                str(ruta_obj),
                "-f",
                "f32le",
                "-ac",
                "1",
                "-ar",
                "16000",
                "-",
            ],
            capture_output=True,
            check=False,
            timeout=900,
        )
        n_samples = len(proc.stdout) // 4 if proc.stdout else 0
        if proc.returncode == 0 and n_samples >= 1:
            return np.frombuffer(proc.stdout, dtype=np.float32, count=n_samples)
    except (OSError, subprocess.SubprocessError):
        pass
    return ruta_audio


def _transcribir_audio_whisper_local(
    ruta_audio: str,
    job_dir: Optional[Path] = None,
    on_log: Optional[Callable[[str], None]] = None,
    on_telemetria: Optional[Callable[[Dict[str, Any]], None]] = None,
) -> Dict[str, Any]:
    """Transcribe audio offline con faster-whisper medium int8 y timestamps por palabra + cache."""
    def _log(msg: str) -> None:
        if on_log is not None:
            on_log(msg)
        else:
            print(msg)

    cache_path = (Path(job_dir).resolve() / "whisper_transcript.json") if job_dir else None
    ultimo_ts = [0.0]

    if cache_path and cache_path.is_file():
        try:
            cached = json.loads(cache_path.read_text(encoding="utf-8"))
            if (
                isinstance(cached, dict)
                and isinstance(cached.get("segmentos"), list)
                and cached["segmentos"]
                and isinstance(cached.get("palabras"), list)
            ):
                if "indices_picos" not in cached or cached["indices_picos"] is None:
                    cached["indices_picos"] = sorted(
                        _calcular_energia_segmentos_audio(ruta_audio, cached["segmentos"])
                    )
                _log(f"✓ Reutilizando transcripción local en caché: {cache_path.name}")
                _emitir_telemetria(
                    on_telemetria,
                    ultimo_ts,
                    {
                        "etapa": "local_whisper",
                        "titulo_etapa": "Transcripción Local (Whisper Medium)",
                        "porcentaje": 100.0,
                        "velocidad_red": "Cache Local",
                        "tamano_total": f"{len(cached['segmentos'])} segs",
                        "eta": "00:00",
                        "detalle": "Transcripción local cargada desde disco",
                    },
                    forzar=True,
                )
                return cached
        except (OSError, json.JSONDecodeError, TypeError):
            pass

    if WhisperModel is None:
        raise RuntimeError("faster-whisper no está instalado en el entorno virtual.")

    _log(f"Iniciando transcripción local Whisper ({WHISPER_MODEL_SIZE}, int8, CPU)...")
    _emitir_telemetria(
        on_telemetria,
        ultimo_ts,
        {
            "etapa": "local_whisper",
            "titulo_etapa": "Transcripción Local (Whisper Medium)",
            "porcentaje": 5.0,
            "velocidad_red": "CPU int8",
            "tamano_total": "--",
            "eta": "--:--",
            "detalle": f"Cargando modelo Whisper {WHISPER_MODEL_SIZE} (int8)...",
        },
        forzar=True,
    )

    cpu_threads = max(4, (os.cpu_count() or 8) - 2)
    model = WhisperModel(
        WHISPER_MODEL_SIZE,
        device="cpu",
        compute_type="int8",
        cpu_threads=cpu_threads,
    )

    segmentos: List[Dict[str, Any]] = []
    palabras: List[Dict[str, Any]] = []
    duracion_total = 0.0
    idioma = "es"
    entrada_whisper: Any = None
    try:
        entrada_whisper = _decodificar_audio_pcm_16k(ruta_audio)
        segments, info = model.transcribe(
            entrada_whisper,
            language="es",
            beam_size=5,
            vad_filter=True,
            vad_parameters={"min_silence_duration_ms": 600, "speech_pad_ms": 250},
            word_timestamps=True,
            condition_on_previous_text=False,
            initial_prompt="Stream en vivo en Kick Colombia con jerga colombiana: parce, gonorrea, chimba, nea, sisas, marica, pirobo, WestCOL, Blessd, La Liendra, eldomi, Yhap.",
        )
        duracion_total = float(getattr(info, "duration", 0.0) or 0.0)
        idioma = str(getattr(info, "language", "es") or "es")
        if duracion_total <= 0.0:
            duracion_total = float(obtener_duracion_media(ruta_audio) or 0.0)

        for seg in segments:
            texto_seg = str(getattr(seg, "text", "") or "").strip()
            if not texto_seg:
                continue
            ini_s = float(getattr(seg, "start", 0.0) or 0.0)
            fin_s = float(getattr(seg, "end", ini_s) or ini_s)
            segmentos.append({"start": ini_s, "end": fin_s, "text": texto_seg})
            for w in (getattr(seg, "words", None) or []):
                w_txt = str(getattr(w, "word", "") or "").strip()
                if w_txt:
                    palabras.append(
                        {
                            "start": float(getattr(w, "start", ini_s) or ini_s),
                            "end": float(getattr(w, "end", fin_s) or fin_s),
                            "word": w_txt,
                        }
                    )

            pct_est = (
                min(92.0, max(8.0, 8.0 + (fin_s / duracion_total) * 84.0))
                if duracion_total > 0.0
                else min(90.0, 10.0 + len(segmentos) * 1.5)
            )
            _emitir_telemetria(
                on_telemetria,
                ultimo_ts,
                {
                    "etapa": "local_whisper",
                    "titulo_etapa": "Transcripción Local (Whisper Medium)",
                    "porcentaje": round(pct_est, 1),
                    "velocidad_red": "CPU int8",
                    "tamano_total": f"{len(segmentos)} segs",
                    "eta": "--:--",
                    "detalle": f"Transcrito hasta {segundos_a_hhmmss(fin_s)} ({len(palabras)} palabras)",
                },
                forzar=False,
            )
    finally:
        entrada_whisper = None
        del model
        gc.collect()

    if not segmentos:
        raise RuntimeError("Whisper local no detectó segmentos de habla válidos en el audio.")

    if duracion_total <= 0.0:
        duracion_total = max(float(s["end"]) for s in segmentos)

    indices_picos = sorted(_calcular_energia_segmentos_audio(ruta_audio, segmentos))
    _log(
        f"✓ Whisper completado: {len(segmentos)} segmentos, {len(palabras)} palabras, "
        f"{len(indices_picos)} picos vocales detectados. RAM liberada."
    )

    resultado = {
        "duracion_total": round(duracion_total, 3),
        "idioma": idioma,
        "segmentos": segmentos,
        "palabras": palabras,
        "indices_picos": indices_picos,
    }
    if cache_path is not None:
        try:
            cache_path.parent.mkdir(parents=True, exist_ok=True)
            cache_path.write_text(
                json.dumps(resultado, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
        except OSError:
            pass

    _emitir_telemetria(
        on_telemetria,
        ultimo_ts,
        {
            "etapa": "local_whisper",
            "titulo_etapa": "Transcripción Local (Whisper Medium)",
            "porcentaje": 100.0,
            "velocidad_red": "CPU int8",
            "tamano_total": f"{len(segmentos)} segs",
            "eta": "00:00",
            "detalle": f"Listo ({len(palabras)} palabras, {len(indices_picos)} picos vocales)",
        },
        forzar=True,
    )
    return resultado


def _construir_subtitulos_desde_whisper(
    palabras: Sequence[Dict[str, Any]],
    inicio_seg: float,
    fin_seg: float,
    segmentos: Optional[Sequence[Dict[str, Any]]] = None,
) -> List[Dict[str, Any]]:
    """Construye bloques de 2 a 4 palabras sincronizados al milímetro desde word_timestamps de Whisper."""
    duracion_clip = max(0.2, float(fin_seg) - float(inicio_seg))
    palabras_clip: List[Dict[str, Any]] = []

    for w in palabras or []:
        if not isinstance(w, dict):
            continue
        txt = str(w.get("word") or "").strip()
        if not txt:
            continue
        try:
            w_ini = float(w.get("start", 0.0) or 0.0)
            w_fin = float(w.get("end", w_ini + 0.1) or (w_ini + 0.1))
        except (TypeError, ValueError):
            continue
        if w_fin < inicio_seg - 0.15 or w_ini > fin_seg + 0.15:
            continue
        ini_rel = max(0.0, min(duracion_clip - 0.08, w_ini - inicio_seg))
        fin_rel = max(ini_rel + 0.08, min(duracion_clip, w_fin - inicio_seg))
        palabras_clip.append({"start": ini_rel, "end": fin_rel, "word": txt})

    bloques_raw: List[Dict[str, Any]] = []
    if palabras_clip:
        buf: List[Dict[str, Any]] = []

        def _volcar_buffer() -> None:
            if not buf:
                return
            t_ini = buf[0]["start"]
            t_fin = max(t_ini + 0.15, buf[-1]["end"])
            if bloques_raw and t_ini < bloques_raw[-1]["fin_rel"]:
                t_ini = min(duracion_clip - 0.08, bloques_raw[-1]["fin_rel"])
                t_fin = max(t_ini + 0.08, min(duracion_clip, t_fin))
            texto_bloque = " ".join(p["word"] for p in buf).strip()
            if texto_bloque:
                bloques_raw.append(
                    {
                        "inicio_rel": round(t_ini, 3),
                        "fin_rel": round(min(duracion_clip, t_fin), 3),
                        "texto": texto_bloque,
                    }
                )
            buf.clear()

        for idx, pw in enumerate(palabras_clip):
            buf.append(pw)
            texto_actual = " ".join(p["word"] for p in buf)
            siguiente = palabras_clip[idx + 1] if idx + 1 < len(palabras_clip) else None
            pausa_sig = (siguiente["start"] - pw["end"]) if siguiente else 0.0
            termina_puntuacion = pw["word"].endswith((".", "!", "?", ";", ":"))
            largo_siguiente = (
                len(texto_actual) + 1 + len(siguiente["word"]) if siguiente else 0
            )
            if (
                siguiente is None
                or len(buf) >= 4
                or pausa_sig >= 0.65
                or (len(buf) >= 2 and (termina_puntuacion or largo_siguiente > 26))
            ):
                _volcar_buffer()
    elif segmentos:
        for seg in segmentos:
            if not isinstance(seg, dict):
                continue
            txt = str(seg.get("text") or "").strip()
            if not txt:
                continue
            s_ini = float(seg.get("start", 0.0) or 0.0)
            s_fin = float(seg.get("end", s_ini) or s_ini)
            if s_fin <= inicio_seg or s_ini >= fin_seg:
                continue
            ini_rel = max(0.0, s_ini - inicio_seg)
            fin_rel = min(duracion_clip, s_fin - inicio_seg)
            if fin_rel > ini_rel + 0.1:
                bloques_raw.append(
                    {"inicio_rel": round(ini_rel, 3), "fin_rel": round(fin_rel, 3), "texto": txt}
                )

    if not bloques_raw:
        return []
    subs_norm = _normalizar_subtitulos(bloques_raw, duracion_clip)
    return [s.model_dump() for s in subs_norm]


def _segmentar_transcripcion_para_ollama(
    segmentos: Sequence[Dict[str, Any]],
    indices_picos: Set[int],
    duracion_total: float,
    max_duracion_bloque: float = 900.0,
    solapamiento: float = 60.0,
    max_segmentos_bloque: int = 180,
) -> List[Dict[str, Any]]:
    """Divide transcripciones largas en bloques temporales manejables para RAM local (16 GB)."""
    segs_indexados = [(idx, seg) for idx, seg in enumerate(segmentos)]
    if not segs_indexados:
        return []

    dur_eff = max(float(duracion_total or 0.0), max(float(s["end"]) for _, s in segs_indexados))

    def _formatear_bloque(
        subset: List[Tuple[int, Dict[str, Any]]],
        offset: float,
        dur_b: float,
    ) -> Dict[str, Any]:
        lineas: List[str] = []
        for idx_orig, s in subset:
            ini_r = max(0.0, float(s.get("start", 0.0)) - offset)
            fin_r = max(ini_r, float(s.get("end", ini_r)) - offset)
            marca_pico = " [🔥 ALTA INTENSIDAD VOCAL]" if idx_orig in indices_picos else ""
            txt = str(s.get("text") or "").strip()
            lineas.append(f"[{segundos_a_hhmmss(ini_r)} - {segundos_a_hhmmss(fin_r)}]{marca_pico} {txt}")
        return {
            "offset_seg": offset,
            "duracion_bloque": max(5.0, dur_b),
            "texto": "\n".join(lineas),
            "num_segmentos": len(subset),
        }

    if dur_eff <= 1200.0 and len(segs_indexados) <= max_segmentos_bloque:
        return [_formatear_bloque(segs_indexados, 0.0, dur_eff)]

    bloques: List[Dict[str, Any]] = []
    paso = max(120.0, max_duracion_bloque - solapamiento)
    inicio_w = 0.0
    while inicio_w < dur_eff - 1.0:
        fin_w = min(dur_eff, inicio_w + max_duracion_bloque)
        subset = [
            (idx_o, s)
            for idx_o, s in segs_indexados
            if float(s.get("end", 0.0)) > inicio_w and float(s.get("start", 0.0)) < fin_w
        ]
        if subset:
            if len(subset) > max_segmentos_bloque:
                for pos in range(0, len(subset), max_segmentos_bloque):
                    sub_recorte = subset[pos : pos + max_segmentos_bloque]
                    sub_off = max(0.0, float(sub_recorte[0][1].get("start", 0.0)))
                    sub_fin = max(sub_off + 5.0, float(sub_recorte[-1][1].get("end", sub_off + 5.0)))
                    bloques.append(_formatear_bloque(sub_recorte, sub_off, sub_fin - sub_off))
            else:
                bloques.append(_formatear_bloque(subset, inicio_w, fin_w - inicio_w))
        if fin_w >= dur_eff:
            break
        inicio_w += paso
    return bloques


def _construir_prompt_ollama(transcripcion_bloque: str, duracion_bloque: float) -> str:
    """Construye el prompt especializado en curaduría viral para modelos locales Ollama."""
    dur_str = segundos_a_hhmmss(duracion_bloque)
    if duracion_bloque < 90:
        rango_clips = "1 a 3 clips virales (respetando la duración real disponible)"
        min_seg = max(5, min(15, int(duracion_bloque * 0.45)))
    elif duracion_bloque < 420:
        rango_clips = "2 a 5 clips virales"
        min_seg = 15
    else:
        rango_clips = "3 a 6 clips virales"
        min_seg = 18

    return (
        "Eres el editor jefe viral del canal Kicksazos (YouTube Shorts y TikTok de Kick Colombia: "
        "WestCOL, Blessd, La Liendra, eldomi, Yhap, streamers colombianos).\n"
        f"Analiza esta transcripción cronológica del audio (duración del bloque: {dur_str}) y selecciona {rango_clips}.\n\n"
        "REGLAS ESTRICTAS DE CURADURÍA:\n"
        "1. PRIORIZA momentos marcados con [🔥 ALTA INTENSIDAD VOCAL] (gritos, risas explosivas, peleas, clímax emocionales), confesiones polémicas o remates con retención inmediata.\n"
        f"2. Cada clip debe durar entre {min_seg} y 58 segundos (ideal 20–50s) y usar timestamps EXACTOS presentes en esta transcripción en formato HH:MM:SS.\n"
        "3. `gancho`: primeras palabras literales habladas en los primeros 2 segundos del clip seleccionado.\n"
        "4. `titulo`: máximo 60 caracteres, estilo streamer colombiano con alto CTR.\n"
        "5. `caption_tiktok`: <= 150 caracteres con gancho de debate; `hashtags_tiktok`: 3 a 5 hashtags; `etiquetas`: 8 a 12 tags SEO relevantes.\n"
        "6. Responde EXCLUSIVAMENTE un objeto JSON válido con la clave raíz `clips` siguiendo el esquema solicitado. NO incluyas subtítulos ni explicaciones fuera del JSON.\n\n"
        f"TRANSCRIPCIÓN:\n{transcripcion_bloque}"
    )


def _llamar_ollama_chat(
    modelo_local: str,
    prompt: str,
    num_ctx: int = 8192,
    on_chunk_texto: Optional[Callable[[int], None]] = None,
) -> str:
    """Ejecuta POST /api/chat en modo streaming evitando timeout y limpiando bloques think."""
    base_url = _resolver_ollama_url()
    chat_url = f"{base_url}/api/chat"
    schema = ListaClipsLocal.model_json_schema()
    es_thinking = any(
        pref in modelo_local.lower() for pref in ("qwen3", "deepseek-r1", "qwq")
    )

    def _hacer_peticion(incluir_think_false: bool) -> str:
        payload: Dict[str, Any] = {
            "model": modelo_local,
            "messages": [{"role": "user", "content": prompt}],
            "stream": True,
            "format": schema,
            "keep_alive": "3m",
            "options": {"temperature": 0.25, "num_ctx": num_ctx},
        }
        if incluir_think_false:
            payload["think"] = False

        req = urllib.request.Request(
            chat_url,
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        partes_contenido: List[str] = []
        chars = 0
        with urllib.request.urlopen(req, timeout=600.0) as resp:
            for raw_line in resp:
                linea = raw_line.decode("utf-8", errors="replace").strip()
                if not linea:
                    continue
                try:
                    evento = json.loads(linea)
                except json.JSONDecodeError:
                    continue
                if evento.get("error"):
                    raise RuntimeError(f"Ollama error ({modelo_local}): {evento['error']}")
                msg = evento.get("message") or {}
                txt = msg.get("content") or ""
                if txt:
                    partes_contenido.append(txt)
                    chars += len(txt)
                    if on_chunk_texto is not None:
                        on_chunk_texto(chars)
                if evento.get("done") is True:
                    break
        return "".join(partes_contenido).strip()

    try:
        return _hacer_peticion(incluir_think_false=es_thinking)
    except urllib.error.HTTPError as e:
        detalle = ""
        try:
            detalle = e.read().decode("utf-8", errors="replace")
        except Exception:
            detalle = str(e)
        if e.code == 400 and es_thinking and "think" in detalle.lower():
            return _hacer_peticion(incluir_think_false=False)
        raise RuntimeError(f"Ollama HTTP {e.code} ({modelo_local}): {detalle}") from e


def analizar_con_ollama(
    ruta_audio: str,
    modelo_local: Optional[str] = None,
    duracion_total: Optional[float] = None,
    job_dir: Optional[Path | str] = None,
    on_log: Optional[Callable[[str], None]] = None,
    on_telemetria: Optional[Callable[[Dict[str, Any]], None]] = None,
) -> List[dict]:
    """Analiza un audio 100% offline usando Whisper medium + Ollama secuencial con gestión estricta de RAM."""
    def _log(msg: str) -> None:
        if on_log is not None:
            on_log(msg)
        else:
            print(msg)

    modelo_elegido = _normalizar_modelo_ollama(modelo_local)
    _asegurar_modelo_ollama(modelo_elegido, on_log=_log)

    dir_job = Path(job_dir).resolve() if job_dir else BASE_DIR
    transcripcion = _transcribir_audio_whisper_local(
        ruta_audio,
        job_dir=dir_job,
        on_log=_log,
        on_telemetria=on_telemetria,
    )

    duracion_efectiva = float(
        duracion_total
        or transcripcion.get("duracion_total")
        or obtener_duracion_media(ruta_audio)
        or 0.0
    )
    segmentos = transcripcion.get("segmentos") or []
    palabras = transcripcion.get("palabras") or []
    indices_picos = set(int(i) for i in (transcripcion.get("indices_picos") or []))

    bloques = _segmentar_transcripcion_para_ollama(
        segmentos=segmentos,
        indices_picos=indices_picos,
        duracion_total=duracion_efectiva,
    )
    if not bloques:
        raise RuntimeError("No hay contenido transcrito suficiente para analizar con Ollama.")

    _log(
        f"\n[2/4] Curaduría viral local con Ollama ({modelo_elegido}) en {len(bloques)} bloque(s) secuenciales..."
    )
    ultimo_ts = [0.0]
    clips_acumulados: List[dict] = []

    try:
        total_b = len(bloques)
        for idx_b, bloque in enumerate(bloques, start=1):
            offset_seg = float(bloque["offset_seg"])
            dur_bloque = float(bloque["duracion_bloque"])
            prompt = _construir_prompt_ollama(bloque["texto"], dur_bloque)
            num_ctx = 12288 if len(prompt) > 12000 else 8192

            _emitir_telemetria(
                on_telemetria,
                ultimo_ts,
                {
                    "etapa": "local_ollama",
                    "titulo_etapa": f"Curaduría Viral Local ({modelo_elegido})",
                    "porcentaje": round(((idx_b - 1) / total_b) * 100.0, 1),
                    "velocidad_red": modelo_elegido,
                    "tamano_total": f"Bloque {idx_b}/{total_b}",
                    "eta": "--:--",
                    "detalle": f"Analizando bloque {idx_b}/{total_b} en Ollama...",
                },
                forzar=True,
            )

            def _on_chunk_local(chars_rx: int, b_idx: int = idx_b, b_tot: int = total_b) -> None:
                base_pct = ((b_idx - 1) / b_tot) * 100.0
                pct_avance = min(98.0, base_pct + min(0.95, chars_rx / 2500.0) * (100.0 / b_tot))
                _emitir_telemetria(
                    on_telemetria,
                    ultimo_ts,
                    {
                        "etapa": "local_ollama",
                        "titulo_etapa": f"Curaduría Viral Local ({modelo_elegido})",
                        "porcentaje": round(pct_avance, 1),
                        "velocidad_red": modelo_elegido,
                        "tamano_total": f"{chars_rx} chars",
                        "eta": "--:--",
                        "detalle": f"Bloque {b_idx}/{b_tot}: generando JSON ({chars_rx} chars)",
                    },
                    forzar=False,
                )

            clips_bloque: List[dict] = []
            ultimo_error: Optional[Exception] = None
            for intento in range(1, 3):
                if not OLLAMA_CIRCUIT_BREAKER.permitir_peticion():
                    raise RuntimeError(
                        f"Circuit-breaker de Ollama abierto tras fallos consecutivos ({modelo_elegido}). "
                        "Verifica que 'ollama serve' esté activo."
                    )
                try:
                    texto_resp = _llamar_ollama_chat(
                        modelo_elegido,
                        prompt,
                        num_ctx=num_ctx,
                        on_chunk_texto=_on_chunk_local,
                    )
                    OLLAMA_CIRCUIT_BREAKER.registrar_exito()
                    clips_bloque = _limpiar_y_parsear_json(
                        texto_resp,
                        duracion_total=dur_bloque,
                        permitir_vacio=(total_b > 1 and intento == 2),
                    )
                    if clips_bloque or total_b > 1:
                        break
                    raise ValueError("Ollama devolvió una lista de clips vacía.")
                except (urllib.error.URLError, TimeoutError, ConnectionError, OSError) as err_red_ol:
                    ultimo_error = err_red_ol
                    estado_cb = OLLAMA_CIRCUIT_BREAKER.registrar_fallo()
                    msg_ol = (
                        f"[AVISO] Ollama ({modelo_elegido}) bloque {idx_b}/{total_b} "
                        f"fallo de conexión/demonio ({type(err_red_ol).__name__}, circuito={estado_cb}): {err_red_ol}"
                    )
                    if estado_cb == "OPEN":
                        _log(msg_ol)
                        raise RuntimeError(
                            f"Circuit-breaker de Ollama abierto tras fallos de conexión ({modelo_elegido}): {err_red_ol}"
                        ) from err_red_ol
                    if intento < 2:
                        _esperar_con_jitter(
                            intento,
                            base=2.0,
                            max_espera=8.0,
                            on_log=_log,
                            contexto=msg_ol,
                        )
                    else:
                        _log(msg_ol)
                except Exception as err_ol:
                    ultimo_error = err_ol
                    _log(
                        f"[AVISO] Ollama ({modelo_elegido}) bloque {idx_b}/{total_b} intento {intento}/2: {err_ol}"
                    )
                    if intento < 2:
                        _esperar_con_jitter(
                            intento,
                            base=1.5,
                            max_espera=5.0,
                            on_log=_log,
                        )

            if not clips_bloque and total_b == 1 and ultimo_error is not None:
                raise ultimo_error

            for clip in clips_bloque:
                try:
                    ini_abs = max(0.0, hhmmss_a_segundos(clip["inicio"]) + offset_seg)
                    fin_abs = max(0.0, hhmmss_a_segundos(clip["fin"]) + offset_seg)
                except (KeyError, ValueError, TypeError):
                    continue
                if duracion_efectiva > 0.0:
                    if ini_abs >= duracion_efectiva - 2.0:
                        continue
                    fin_abs = min(fin_abs, duracion_efectiva)
                dur_clip_abs = fin_abs - ini_abs
                if dur_clip_abs < 5.0:
                    continue

                subs_whisper = _construir_subtitulos_desde_whisper(
                    palabras,
                    ini_abs,
                    fin_abs,
                    segmentos=segmentos,
                )
                clip_enriquecido = dict(clip)
                clip_enriquecido["inicio"] = segundos_a_hhmmss(ini_abs)
                clip_enriquecido["fin"] = segundos_a_hhmmss(fin_abs)
                clip_enriquecido["duracion_segundos"] = int(round(dur_clip_abs))
                clip_enriquecido["subtitulos"] = subs_whisper
                clip_enriquecido["subtitulos_origen"] = "whisper_word_timestamps"
                clip_enriquecido["motor_ia"] = "local"
                clip_enriquecido["modelo_ia"] = modelo_elegido
                clips_acumulados.append(clip_enriquecido)
    finally:
        _descargar_modelo_ollama_ram(modelo_elegido, on_log=_log)

    clips_finales = _deduplicar_clips_solapados(clips_acumulados)
    if not clips_finales:
        raise RuntimeError(
            f"Ollama ({modelo_elegido}) no detectó momentos virales válidos en la transcripción."
        )

    for idx_f, clip_f in enumerate(clips_finales, start=1):
        clip_f["id"] = idx_f

    _guardar_y_sincronizar_clips(clips_finales, job_dir=job_dir)
    _log(
        f"✓ Análisis local completado ({modelo_elegido}): {len(clips_finales)} clips con word_timestamps guardados en clips.json"
    )
    _emitir_telemetria(
        on_telemetria,
        ultimo_ts,
        {
            "etapa": "local_ollama",
            "titulo_etapa": f"Curaduría Viral Local ({modelo_elegido})",
            "porcentaje": 100.0,
            "velocidad_red": modelo_elegido,
            "tamano_total": f"{len(clips_finales)} clips",
            "eta": "00:00",
            "detalle": f"Listo: {len(clips_finales)} clips seleccionados • RAM Ollama liberada",
        },
        forzar=True,
    )
    return clips_finales


def descargar_video_fuente(
    url: str,
    destino: Optional[Path | str] = None,
    on_telemetria: Optional[Callable[[Dict[str, Any]], None]] = None,
    on_log: Optional[Callable[[str], None]] = None,
) -> str:
    """Descarga el video fuente completo una sola vez priorizando MP4 directo (sin HLS lento) con telemetría."""
    def _log(msg: str) -> None:
        if on_log is not None:
            on_log(msg)
        else:
            print(msg)

    ruta_destino = Path(destino).resolve() if destino else BASE_DIR / "temp_source.mp4"
    if ruta_destino.exists():
        ruta_destino.unlink()

    _log("Descargando video fuente en 1080p para corte rápido local...")
    _emitir_telemetria(
        on_telemetria,
        [0.0],
        {
            "etapa": "descarga_video",
            "titulo_etapa": "Descargando Video Fuente (1080p)",
            "porcentaje": 0.0,
            "velocidad_red": "--",
            "tamano_total": "--",
            "eta": "--:--",
            "detalle": "Preparando descarga de video fuente...",
        },
        forzar=True,
    )
    comando = [
        sys.executable,
        "-m",
        "yt_dlp",
        "--newline",
        "--progress",
        "--js-runtimes",
        "node",
        "--remote-components",
        "ejs:github",
        "--no-playlist",
        "--force-overwrites",
        "--concurrent-fragments",
        "16",
        "--retries",
        "10",
        "--fragment-retries",
        "10",
        "--retry-sleep",
        "fragment:exp=1:10",
        "--socket-timeout",
        "15",
        "-f",
        FORMATOS_VIDEO_RAPIDOS,
        "--merge-output-format",
        "mp4",
        "-o",
        str(ruta_destino),
        url,
    ]
    try:
        _ejecutar_descarga_con_telemetria(
            comando,
            on_telemetria=on_telemetria,
            etapa="descarga_video",
            titulo_etapa="Descargando Video Fuente (1080p)",
            detalle_default="Descarga 1080p activa",
        )
    except BaseException:
        for resto_part in glob.glob(f"{ruta_destino}.*"):
            try:
                os.remove(resto_part)
            except OSError:
                pass
        raise
    if not ruta_destino.exists():
        raise FileNotFoundError(f"No se generó el video fuente: {ruta_destino}")
    _emitir_telemetria(
        on_telemetria,
        [0.0],
        {
            "etapa": "descarga_video",
            "titulo_etapa": "Video Fuente Listo (1080p)",
            "porcentaje": 100.0,
            "velocidad_red": "Completado",
            "tamano_total": f"{ruta_destino.stat().st_size / (1024 * 1024):.1f}MiB",
            "eta": "00:00",
            "detalle": "Video fuente listo para recorte local",
        },
        forzar=True,
    )
    return str(ruta_destino)


def obtener_urls_stream(
    url: str,
    job_id: Optional[str] = None,
    forzar_recarga: bool = False,
) -> List[str]:
    """Obtiene URLs directas del stream con yt-dlp -g usando caché thread-safe y lock por job_id."""
    clave_cache = job_id or f"anon:{url}"
    lock_job = _obtener_lock_stream_job(clave_cache)
    with lock_job:
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
        res = subprocess.run(comando, capture_output=True, text=True, check=True, timeout=60)
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
    """Calcula la expresión Y adaptativa para centrar la marca de agua respetando la Safe Zone superior (y>=200)."""
    if dimensiones and dimensiones[0] > 0 and dimensiones[1] > 0:
        w, h = dimensiones
        aspecto = w / h
        if aspecto <= (9.0 / 16.0) + 0.03:
            return "200"
        h_fg = min(1920, int(round(1080 * h / w)))
    else:
        h_fg = 608
    return f"max(200\\,(H-{h_fg})/2-h-24)"


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


def _formatear_eta_segundos(segundos: float) -> str:
    """Formatea segundos restantes a MM:SS o HH:MM:SS para ETA."""
    total = max(0, int(round(segundos)))
    h = total // 3600
    m = (total % 3600) // 60
    s = total % 60
    if h > 0:
        return f"{h:02d}:{m:02d}:{s:02d}"
    return f"{m:02d}:{s:02d}"


def _parsear_tiempo_ffmpeg(out_time_us: str, out_time_str: str) -> float:
    """Convierte out_time_us (microsegundos) o out_time (HH:MM:SS.xx) a segundos."""
    if out_time_us and out_time_us.strip().lstrip("-").isdigit():
        return max(0.0, int(out_time_us.strip()) / 1_000_000.0)
    if out_time_str and out_time_str.strip() not in ("N/A", ""):
        partes = out_time_str.strip().split(":")
        try:
            if len(partes) == 3:
                return max(0.0, int(partes[0]) * 3600 + int(partes[1]) * 60 + float(partes[2]))
        except ValueError:
            pass
    return 0.0


def _ejecutar_comando_con_captura(
    comando: List[str],
    duracion_objetivo: Optional[float] = None,
    on_progreso: Optional[Callable[[Dict[str, Any]], None]] = None,
) -> str:
    """Ejecuta un comando capturando stderr y parseando -progress pipe:1 cuando está habilitado."""
    usa_progress = "-progress" in comando
    if usa_progress:
        popen_kwargs: Dict[str, Any] = {
            "stdin": subprocess.DEVNULL,
            "stdout": subprocess.PIPE,
            "stderr": subprocess.PIPE,
            "text": True,
            "errors": "replace",
            "bufsize": 1,
        }
        if os.name == "posix":
            popen_kwargs["start_new_session"] = True
        proc = subprocess.Popen(comando, **popen_kwargs)
        _registrar_proceso_activo(proc)
        stderr_chunks: List[str] = []

        def _leer_stderr() -> None:
            if proc.stderr is None:
                return
            try:
                for chunk in iter(lambda: proc.stderr.read(4096), ""):
                    stderr_chunks.append(chunk)
                    if on_progreso is None:
                        try:
                            sys.stderr.write(chunk)
                            sys.stderr.flush()
                        except Exception:
                            pass
            except ValueError:
                pass

        hilo_err = threading.Thread(target=_leer_stderr, daemon=True)
        hilo_err.start()

        ultimo_ts = [0.0]
        bloque: Dict[str, str] = {}
        try:
            if proc.stdout is not None:
                for linea_raw in iter(proc.stdout.readline, ""):
                    linea = linea_raw.strip()
                    if not linea or "=" not in linea:
                        continue
                    k, _, v = linea.partition("=")
                    k = k.strip()
                    v = v.strip()
                    bloque[k] = v
                    if k == "progress":
                        es_fin = v == "end"
                        out_sec = _parsear_tiempo_ffmpeg(
                            bloque.get("out_time_us", ""),
                            bloque.get("out_time", ""),
                        )
                        if duracion_objetivo and duracion_objetivo > 0:
                            out_sec = min(out_sec, float(duracion_objetivo))
                            pct = 100.0 if es_fin else round(min(99.9, max(0.0, (out_sec / duracion_objetivo) * 100.0)), 1)
                        else:
                            pct = 100.0 if es_fin else 0.0

                        try:
                            frame_int = int(bloque.get("frame", "0") or 0)
                        except ValueError:
                            frame_int = 0

                        try:
                            fps_val = float(bloque.get("fps", "0") or 0.0)
                        except ValueError:
                            fps_val = 0.0
                        fps_str = f"{fps_val:.1f}" if fps_val > 0 else "--"

                        raw_speed = bloque.get("speed", "").strip()
                        speed_val: Optional[float] = None
                        if raw_speed and raw_speed != "N/A":
                            try:
                                speed_val = float(raw_speed.rstrip("xX"))
                            except ValueError:
                                speed_val = None
                        speed_str = f"{speed_val:.2f}x" if speed_val is not None and speed_val > 0 else (raw_speed or "--")

                        if es_fin:
                            eta_str = "00:00"
                        elif duracion_objetivo and duracion_objetivo > 0 and speed_val and speed_val > 0:
                            rem = max(0.0, (float(duracion_objetivo) - out_sec) / speed_val)
                            eta_str = _formatear_eta_segundos(rem)
                        else:
                            eta_str = "--:--"

                        raw_size = bloque.get("total_size", "")
                        if raw_size.isdigit():
                            size_str = f"{int(raw_size) / (1024 * 1024):.2f}MiB"
                        else:
                            size_str = "--"

                        _emitir_telemetria(
                            on_progreso,
                            ultimo_ts,
                            {
                                "porcentaje": pct,
                                "frame": frame_int,
                                "fps": fps_val,
                                "fps_str": fps_str,
                                "speed_val": speed_val,
                                "speed_str": speed_str,
                                "eta_str": eta_str,
                                "out_sec": out_sec,
                                "out_time_str": segundos_a_hhmmss(out_sec),
                                "size_str": size_str,
                                "progress": v,
                            },
                            forzar=es_fin,
                        )
                        bloque.clear()

            returncode = proc.wait()
        finally:
            _terminar_proceso_seguro(proc)
            hilo_err.join(timeout=2.0)
            _cerrar_pipes_proceso(proc)
            _desregistrar_proceso_activo(proc)

        salida_txt = "".join(stderr_chunks)
        if returncode != 0:
            raise subprocess.CalledProcessError(returncode, comando, output=salida_txt, stderr=salida_txt)
        return salida_txt

    popen_kwargs_raw: Dict[str, Any] = {
        "stdin": subprocess.DEVNULL,
        "stdout": subprocess.PIPE,
        "stderr": subprocess.STDOUT,
    }
    if os.name == "posix":
        popen_kwargs_raw["start_new_session"] = True
    proc = subprocess.Popen(comando, **popen_kwargs_raw)
    _registrar_proceso_activo(proc)
    chunks: List[bytes] = []
    try:
        assert proc.stdout is not None
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
    finally:
        _terminar_proceso_seguro(proc)
        _cerrar_pipes_proceso(proc)
        _desregistrar_proceso_activo(proc)

    salida_txt = b"".join(chunks).decode("utf-8", errors="replace")
    if returncode != 0:
        raise subprocess.CalledProcessError(returncode, comando, output=salida_txt, stderr=salida_txt)
    return salida_txt


def _construir_prompt_alineacion_subtitulos(
    duracion_clip: float,
    subtitulos: List[SegmentoSubtitulo],
) -> str:
    """Construye el prompt de micro-pasada para sincronizar subtítulos exactamente al audio del clip cortado."""
    guia_texto = " ".join(s.texto for s in subtitulos if getattr(s, "texto", "")).strip()
    bloque_guia = (
        f'\nGUÍA ORTOGRÁFICA OPCIONAL (únicamente como apoyo de nombres propios/jerga si realmente se pronuncian; '
        f'PROHIBIDO copiar frases ausentes o reutilizar tiempos viejos): "{guia_texto[:600]}"'
        if guia_texto
        else ""
    )
    return (
        f"Eres un transcriptor fonético forense experto en streaming y jerga colombiana.\n"
        f"Sincroniza y transcribe LITERALMENTE lo que se escucha en el audio adjunto de este clip "
        f"(duración total exacta: {duracion_clip:.2f} segundos).\n"
        f"REGLAS ESTRICTAS:\n"
        f"- Timestamps `inicio_rel` y `fin_rel` en segundos decimales exactos desde 0.00 hasta {duracion_clip:.2f} "
        f"(precisión de centésimas, en orden cronológico y sin solapamientos).\n"
        f"- Bloques dinámicos de lectura rápida de 2 a 4 palabras por segmento (máximo 22 caracteres), SIN EMOJIS.\n"
        f"- Respeta literalmente el español coloquial colombiano pronunciado (incluyendo jerga real, sin parafrasear ni inventar).\n"
        f"- Si un tramo tiene silencio o ruido ininteligible, omítelo.{bloque_guia}"
    )


def _alinear_subtitulos_con_clip_renderizado(
    ruta_video_raw: str,
    subtitulos: List[SegmentoSubtitulo],
    job_dir: Path,
    id_clip: int,
    duracion_clip: float,
    on_log: Optional[Callable[[str], None]] = None,
) -> List[SegmentoSubtitulo]:
    """Re-sincroniza subtítulos contra el audio exacto de raw_clip_<id>.mp4 usando Gemini File API."""
    def _log(msg: str) -> None:
        if on_log is not None:
            on_log(msg)
        else:
            print(msg)

    api_key = os.environ.get("GEMINI_API_KEY")
    if (
        not subtitulos
        or duracion_clip <= 0
        or not api_key
        or not ruta_video_raw
        or not Path(ruta_video_raw).is_file()
    ):
        return subtitulos

    carpeta_job = Path(job_dir).resolve()
    carpeta_job.mkdir(parents=True, exist_ok=True)
    ruta_audio_clip = carpeta_job / f"clip_audio_{id_clip}.mp3"

    client: Optional[genai.Client] = None
    archivo_subido: Any = None
    try:
        comando_audio = [
            "ffmpeg",
            "-hide_banner",
            "-loglevel",
            "error",
            "-y",
            "-i",
            str(ruta_video_raw),
            "-vn",
            "-ac",
            "1",
            "-ar",
            "12000",
            "-b:a",
            "24k",
            str(ruta_audio_clip),
        ]
        subprocess.run(comando_audio, check=True, capture_output=True, text=True)
        if not ruta_audio_clip.is_file() or ruta_audio_clip.stat().st_size <= 0:
            raise RuntimeError("El audio extraído del clip raw está vacío.")

        client = genai.Client(
            api_key=api_key,
            http_options={"timeout": GEMINI_TIMEOUT_MS},
        )
        archivo_subido = _subir_archivo_gemini_activo(
            client,
            ruta_audio_clip,
            on_log=on_log,
        )
        prompt = _construir_prompt_alineacion_subtitulos(duracion_clip, subtitulos)
        subs_alineados, modelo_usado = _ejecutar_cascada_modelos_gemini(
            client=client,
            archivo_subido=archivo_subido,
            prompt=prompt,
            response_schema=list[SegmentoSubtitulo],
            temperature=0.1,
            parsear_fn=lambda txt: _parsear_subtitulos_json(txt, duracion_clip),
            on_log=on_log,
        )
        _log(
            f"✓ Subtítulos del Clip #{id_clip} alineados fonéticamente con {modelo_usado} "
            f"({len(subs_alineados)} segmentos)"
        )
        return subs_alineados
    except Exception as exc:
        _log(
            f"[AVISO] Falló micro-pasada de alineación fonética para Clip #{id_clip} ({exc}); "
            "usando subtítulos originales como fallback seguro."
        )
        return subtitulos
    finally:
        _eliminar_archivo_gemini_seguro(client, archivo_subido)
        _cerrar_cliente_genai_seguro(client)
        if ruta_audio_clip.exists():
            try:
                os.remove(ruta_audio_clip)
            except OSError:
                pass


def _construir_filtro_subtitulos(
    ruta_ass: str | Path, fonts_dir: Optional[str | Path] = None
) -> str:
    """Construye el filtro libass subtitles='<ruta>'[:fontsdir='<dir>'] escapado para FFmpeg."""
    ruta_esc = _escapar_ruta_ffmpeg_filtro(ruta_ass)
    if fonts_dir:
        fonts_esc = _escapar_ruta_ffmpeg_filtro(fonts_dir)
        return f"subtitles='{ruta_esc}':fontsdir='{fonts_esc}'"
    return f"subtitles='{ruta_esc}'"


def _args_codec_video(encoder: str) -> Tuple[str, List[str]]:
    """Devuelve (filtro_formato_salida, args_codec_ffmpeg) para h264_vaapi o libx264."""
    if encoder == "h264_vaapi":
        return "format=nv12,hwupload", ["-c:v", "h264_vaapi", "-qp", "23"]
    return "format=yuv420p", [
        "-c:v",
        "libx264",
        "-preset",
        "veryfast",
        "-crf",
        "22",
        "-threads",
        "0",
    ]


def _construir_comando_quemar_ass(
    ruta_video_raw: str | Path,
    archivo_salida: Path,
    ruta_ass: str | Path,
    encoder: str,
    fonts_dir: Optional[str] = None,
) -> List[str]:
    """Construye la segunda pasada rápida de FFmpeg sobre raw_clip con -vf subtitles y -c:a copy."""
    comando = [
        "ffmpeg",
        "-hide_banner",
        "-loglevel",
        "warning",
        "-progress",
        "pipe:1",
        "-nostats",
        "-y",
    ]
    if encoder == "h264_vaapi":
        comando.extend(["-vaapi_device", VAAPI_DEVICE])

    comando.extend(["-i", str(ruta_video_raw)])

    filtro_subs = _construir_filtro_subtitulos(ruta_ass, fonts_dir)
    fmt_salida, codec_args = _args_codec_video(encoder)
    vf = f"{filtro_subs},{fmt_salida}"

    comando.extend(
        [
            "-vf",
            vf,
            *codec_args,
            "-c:a",
            "copy",
            "-movflags",
            "+faststart",
            str(archivo_salida),
        ]
    )
    return comando


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
    fonts_dir: Optional[str] = None,
) -> List[str]:
    """Construye el comando FFmpeg 9:16 con encoder VAAPI/CPU, watermark adaptativa, fontsdir y -progress pipe:1."""
    comando = [
        "ffmpeg",
        "-hide_banner",
        "-loglevel",
        "warning",
        "-progress",
        "pipe:1",
        "-nostats",
        "-y",
    ]
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
        cadena_final.append(_construir_filtro_subtitulos(ruta_ass, fonts_dir))
    fmt_salida, codec_args = _args_codec_video(encoder)
    cadena_final.append(f"{fmt_salida}[outv]")
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
            *codec_args,
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
    on_telemetria: Optional[Callable[[Dict[str, Any]], None]] = None,
    clip_indice: Optional[int] = None,
    total_clips: Optional[int] = None,
    on_log: Optional[Callable[[str], None]] = None,
    alinear_subtitulos: bool = True,
) -> str:
    """Renderiza el clip 9:16 (1 pasada directa si alinear_subtitulos=False o sin subs; 2 pasos con alineación fonética si alinear_subtitulos=True)."""
    def _log(msg: str) -> None:
        if on_log is not None:
            on_log(msg)
        else:
            print(msg)

    if not RUTA_MARCA_AGUA.exists():
        raise FileNotFoundError(f"No se encontró la marca de agua en {RUTA_MARCA_AGUA}")

    duracion_clip = hhmmss_a_segundos(fin) - hhmmss_a_segundos(inicio)
    if duracion_clip <= 0:
        raise ValueError(f"Duración de clip inválida ({inicio} -> {fin}).")
    duracion_str = f"{duracion_clip:.3f}"

    CARPETA_SALIDA.mkdir(parents=True, exist_ok=True)
    nombre_clip = f"{job_id}_clip_{id_clip}.mp4" if job_id else f"clip_{id_clip}.mp4"
    archivo_salida = CARPETA_SALIDA / nombre_clip

    if job_dir:
        carpeta_job = Path(job_dir).resolve()
    elif job_id:
        carpeta_job = (CARPETA_JOBS / job_id).resolve()
    else:
        carpeta_job = (CARPETA_JOBS / "standalone").resolve()
    carpeta_job.mkdir(parents=True, exist_ok=True)

    _log(
        f"\n--- Procesando Clip {id_clip} ({inicio} -> {fin}, t={duracion_str}s) "
        f"[Salida: {nombre_clip}] ---"
    )

    subs_norm = _normalizar_subtitulos(subtitulos, duracion_clip)
    tiene_subs = bool(subs_norm)

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
    url_refrescada = False
    etiqueta_clip = f"Renderizando Clip #{id_clip}" + (
        f" ({clip_indice}/{total_clips})" if clip_indice and total_clips else ""
    )

    def _emitir_render_tele(
        pct: float,
        fps: str = "--",
        velocidad_x: str = "--",
        eta: str = "--:--",
        frame: int = 0,
        out_time: str = "00:00:00",
        detalle: str = "",
        forzar: bool = False,
    ) -> None:
        if on_telemetria is None:
            return
        payload = {
            "etapa": "render",
            "titulo_etapa": etiqueta_clip,
            "porcentaje": round(min(100.0, max(0.0, float(pct))), 1),
            "fps": fps,
            "velocidad_x": velocidad_x,
            "velocidad_render": velocidad_x,
            "eta": eta,
            "encoder": encoder_activo,
            "clip_id": str(id_clip),
            "clip_indice": clip_indice,
            "total_clips": total_clips,
            "frame": frame,
            "out_time": out_time,
            "duracion_clip": duracion_clip,
            "detalle": detalle,
        }
        if forzar:
            _emitir_telemetria(on_telemetria, [0.0], payload, forzar=True)
        else:
            on_telemetria(payload)

    def _ejecutar_paso_1(
        destino_paso1: Path,
        escala_pct: float = 1.0,
        etiqueta_paso: str = "",
        ruta_ass: Optional[str | Path] = None,
        fonts_dir: Optional[str | Path] = None,
    ) -> None:
        nonlocal entradas_media, dimensiones, y_watermark, encoder_activo, url_refrescada
        ass_actual = ruta_ass
        fonts_actual = fonts_dir
        while True:
            comando_ffmpeg = _construir_comando_render(
                entradas_media=entradas_media,
                es_remoto=es_remoto,
                inicio=inicio,
                duracion_str=duracion_str,
                archivo_salida=destino_paso1,
                y_watermark=y_watermark,
                encoder=encoder_activo,
                ruta_ass=ass_actual,
                fonts_dir=fonts_actual,
            )
            sufijo_paso = f" [{etiqueta_paso}]" if etiqueta_paso else ""
            _log(
                f"Renderizando composición 9:16 con FFmpeg{sufijo_paso} "
                f"[encoder={encoder_activo}, wm_y={y_watermark}, subs={'directo' if ass_actual else 'no'}]..."
            )
            _emitir_render_tele(
                0.0,
                detalle=f"Iniciando render {encoder_activo}{' • ' + etiqueta_paso if etiqueta_paso else ''}...",
                forzar=True,
            )

            def _on_prog_p1(prog: Dict[str, Any]) -> None:
                _emitir_render_tele(
                    prog["porcentaje"] * escala_pct,
                    fps=prog["fps_str"],
                    velocidad_x=prog["speed_str"],
                    eta=prog["eta_str"],
                    frame=prog["frame"],
                    out_time=prog["out_time_str"],
                    detalle=(
                        f"Encoder {encoder_activo}"
                        f"{' (' + etiqueta_paso + ')' if etiqueta_paso else ''} • "
                        f"{prog['fps_str']} fps • {prog['speed_str']} • ETA {prog['eta_str']}"
                    ),
                )

            try:
                _ejecutar_comando_con_captura(
                    comando_ffmpeg,
                    duracion_objetivo=duracion_clip,
                    on_progreso=_on_prog_p1 if on_telemetria is not None else None,
                )
                break
            except subprocess.CalledProcessError as err:
                if destino_paso1.exists():
                    try:
                        destino_paso1.unlink()
                    except OSError:
                        pass

                stderr_txt = err.stderr or err.output or ""

                if es_remoto and not url_refrescada and _es_error_http_expiracion(stderr_txt):
                    _log(
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

                if ass_actual is not None and re.search(
                    r"Parsed_subtitles|subtitles|libass|\.ass", stderr_txt, re.IGNORECASE
                ):
                    _log(
                        "[AVISO] El filtro libass falló en pasada directa; "
                        "reintentando render limpio sin subtítulos..."
                    )
                    ass_actual = None
                    fonts_actual = None
                    continue

                if encoder_activo == "h264_vaapi":
                    _log(
                        "[AVISO] Renderizado VAAPI falló en ejecución; "
                        "reintentando automáticamente con CPU (libx264)..."
                    )
                    encoder_activo = "libx264"
                    continue

                raise

    if not tiene_subs:
        _ejecutar_paso_1(archivo_salida, escala_pct=1.0)
        _log(f"✓ Clip {id_clip} guardado con éxito en: {archivo_salida}")
        return str(archivo_salida.resolve())

    if not alinear_subtitulos:
        ruta_ass = generar_archivo_ass(subs_norm, carpeta_job / f"subs_{id_clip}.ass")
        fuente_sub, fonts_dir_sub = _obtener_fuente_y_dir_subtitulos()
        _log(
            f"✓ Subtítulos Whisper listos para 1 pasada directa: {ruta_ass} "
            f"[fuente={fuente_sub}, fontsdir={fonts_dir_sub or 'sistema'}]"
        )
        _ejecutar_paso_1(
            archivo_salida,
            escala_pct=1.0,
            etiqueta_paso="Pasada única 9:16 + .ass",
            ruta_ass=ruta_ass,
            fonts_dir=fonts_dir_sub,
        )
        _log(f"✓ Clip {id_clip} guardado con éxito en: {archivo_salida}")
        return str(archivo_salida.resolve())

    raw_clip = carpeta_job / f"raw_clip_{id_clip}.mp4"
    try:
        # Paso 1: corte y composición 9:16 limpia (sin subtítulos) hacia raw_clip_<id>.mp4
        _ejecutar_paso_1(raw_clip, escala_pct=0.50, etiqueta_paso="Paso 1/2: corte 9:16")

        # Paso 2a: micro-pasada de alineación fonética sobre el audio exacto de raw_clip
        _emitir_render_tele(
            52.0,
            detalle="Alineando subtítulos fonéticamente al audio exacto...",
            forzar=True,
        )
        id_clip_arg: Any = int(id_clip) if str(id_clip).isdigit() else id_clip
        subs_alineados = _alinear_subtitulos_con_clip_renderizado(
            str(raw_clip),
            subs_norm,
            carpeta_job,
            id_clip_arg,
            duracion_clip,
            on_log=on_log,
        )
        subs_finales = _normalizar_subtitulos(subs_alineados, duracion_clip) or subs_norm
        ruta_ass = generar_archivo_ass(subs_finales, carpeta_job / f"subs_{id_clip}.ass")
        fuente_sub, fonts_dir_sub = _obtener_fuente_y_dir_subtitulos()
        _log(
            f"✓ Subtítulos dinámicos alineados en: {ruta_ass} "
            f"[fuente={fuente_sub}, fontsdir={fonts_dir_sub or 'sistema'}]"
        )

        # Paso 2b: quemado rápido de subtítulos .ass sobre raw_clip con -c:a copy
        while True:
            comando_pass2 = _construir_comando_quemar_ass(
                ruta_video_raw=raw_clip,
                archivo_salida=archivo_salida,
                ruta_ass=ruta_ass,
                encoder=encoder_activo,
                fonts_dir=fonts_dir_sub,
            )
            _log(
                f"Quemando subtítulos .ass sobre raw_clip [Paso 2/2, encoder={encoder_activo}]..."
            )
            _emitir_render_tele(
                55.0,
                detalle=f"Paso 2/2: quemando subtítulos ({encoder_activo})...",
                forzar=True,
            )

            def _on_prog_p2(prog: Dict[str, Any]) -> None:
                _emitir_render_tele(
                    55.0 + prog["porcentaje"] * 0.45,
                    fps=prog["fps_str"],
                    velocidad_x=prog["speed_str"],
                    eta=prog["eta_str"],
                    frame=prog["frame"],
                    out_time=prog["out_time_str"],
                    detalle=(
                        f"Paso 2/2 ({encoder_activo}) • {prog['fps_str']} fps • "
                        f"{prog['speed_str']} • ETA {prog['eta_str']}"
                    ),
                )

            try:
                _ejecutar_comando_con_captura(
                    comando_pass2,
                    duracion_objetivo=duracion_clip,
                    on_progreso=_on_prog_p2 if on_telemetria is not None else None,
                )
                break
            except subprocess.CalledProcessError as err:
                if archivo_salida.exists():
                    try:
                        archivo_salida.unlink()
                    except OSError:
                        pass

                stderr_txt = err.stderr or err.output or ""

                if re.search(r"Parsed_subtitles|subtitles|libass|\.ass", stderr_txt, re.IGNORECASE):
                    _log(
                        "[AVISO] El filtro de subtítulos .ass falló en Paso 2; "
                        "guardando clip sin subtítulos desde raw_clip..."
                    )
                    shutil.copy2(raw_clip, archivo_salida)
                    break

                if encoder_activo == "h264_vaapi":
                    _log(
                        "[AVISO] Quemado .ass con VAAPI falló en Paso 2; "
                        "reintentando automáticamente con CPU (libx264)..."
                    )
                    encoder_activo = "libx264"
                    continue

                _log(
                    "[AVISO] Paso 2 falló con subtítulos activos; "
                    "guardando clip limpio sin subtítulos desde raw_clip..."
                )
                shutil.copy2(raw_clip, archivo_salida)
                break
    finally:
        if raw_clip.exists():
            try:
                raw_clip.unlink()
            except OSError:
                pass

    _log(f"✓ Clip {id_clip} guardado con éxito en: {archivo_salida}")
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
    telemetria: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    return {
        "fase": fase,
        "progreso": round(float(progreso), 4),
        "mensaje": mensaje,
        "clips": clips if clips is not None else [],
        "ultimo_video": ultimo_video,
        "job_dir": job_dir,
        "error": error,
        "telemetria": telemetria if telemetria is not None else {},
    }


def _ejecutar_paso_con_telemetria(
    fn: Callable[..., Any],
    *args: Any,
    construir_estado: Callable[[Dict[str, Any]], Dict[str, Any]],
    on_telemetria_externa: Optional[Callable[[Dict[str, Any]], None]] = None,
    **kwargs: Any,
) -> Generator[Dict[str, Any], None, Any]:
    """Ejecuta una etapa bloqueante en hilo worker re-emitiendo su telemetría en vivo con cancelación Ctrl+C inmediata."""
    cola: queue.Queue[Tuple[str, Any]] = queue.Queue()
    acepta_tele = _acepta_kwarg(fn, "on_telemetria")

    def _cb_tele(datos: Dict[str, Any]) -> None:
        copia = dict(datos or {})
        if on_telemetria_externa is not None:
            try:
                on_telemetria_externa(copia)
            except Exception:
                pass
        cola.put(("tele", copia))

    def _worker() -> None:
        try:
            call_kwargs = dict(kwargs)
            if acepta_tele:
                call_kwargs["on_telemetria"] = _cb_tele
            res = fn(*args, **call_kwargs)
            cola.put(("ok", res))
        except BaseException as exc:
            cola.put(("err", exc))

    hilo = threading.Thread(target=_worker, daemon=True)
    hilo.start()
    try:
        while True:
            try:
                tipo, payload = cola.get(timeout=0.5)
            except queue.Empty:
                if not hilo.is_alive() and cola.empty():
                    raise RuntimeError(
                        f"El hilo worker de '{getattr(fn, '__name__', 'etapa')}' finalizó sin resultado."
                    )
                continue

            if tipo == "tele":
                yield construir_estado(payload)
            elif tipo == "ok":
                hilo.join(timeout=1.0)
                return payload
            elif tipo == "err":
                hilo.join(timeout=1.0)
                raise payload
    except (KeyboardInterrupt, GeneratorExit):
        terminar_procesos_activos()
        raise


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
    on_telemetria: Optional[Callable[[Dict[str, Any]], None]] = None,
    alinear_subtitulos: bool = True,
) -> Generator[Dict[str, Any], None, None]:
    """Orquestador compartido de Fase 3+4 con renderizado paralelo (max_workers=2) y locks thread-safe."""
    log_lock = threading.Lock()

    def _log(msg: str) -> None:
        with log_lock:
            if on_log is not None:
                on_log(msg)
            else:
                print(msg)

    job_dir_str = str(Path(job_dir).resolve()) if job_dir else None
    fuente_local: Optional[str] = None
    youtube_client = None
    ultimo_video: Optional[str] = None

    _log("\n[3/4] Renderizando clips con formato 9:16 y marca de agua @Kicksazos...")
    tele_fuente_init = {
        "etapa": "descarga_video",
        "titulo_etapa": "Preparando Fuente de Video (1080p)",
        "porcentaje": 0.0,
        "velocidad_red": "--",
        "tamano_total": "--",
        "eta": "--:--",
        "detalle": "Evaluando estrategia de lectura de stream...",
    }
    if on_telemetria is not None:
        on_telemetria(dict(tele_fuente_init))
    yield _emitir_estado(
        fase="fuente",
        progreso=0.55,
        mensaje="Fase 3/4: Preparando fuente de video en 1080p...",
        clips=clips,
        ultimo_video=ultimo_video,
        job_dir=job_dir_str,
        telemetria=tele_fuente_init,
    )

    try:
        es_archivo_local = False
        try:
            es_archivo_local = bool(str(url or "").strip()) and Path(url).is_file()
        except OSError:
            es_archivo_local = False

        # Para videos <= 1h descargar una sola vez evita múltiples conexiones HTTP/HLS lentas
        if es_archivo_local:
            _log(f"✓ Usando archivo multimedia local directo para render: {url}")
        elif duracion_total is None or duracion_total <= 3600:
            try:
                destino_fuente = (
                    Path(job_dir) / "temp_source.mp4"
                    if job_dir
                    else BASE_DIR / "temp_source.mp4"
                )
                kwargs_dl: Dict[str, Any] = {"destino": destino_fuente}
                if _acepta_kwarg(descargar_video_fuente, "on_log"):
                    kwargs_dl["on_log"] = _log
                fuente_local = yield from _ejecutar_paso_con_telemetria(
                    descargar_video_fuente,
                    url,
                    construir_estado=lambda tele: _emitir_estado(
                        fase="fuente",
                        progreso=0.55 + 0.05 * (float(tele.get("porcentaje", 0.0)) / 100.0),
                        mensaje=f"Fase 3/4: {tele.get('titulo_etapa', 'Descargando fuente 1080p')} ({tele.get('porcentaje', 0):.1f}%)",
                        clips=clips,
                        ultimo_video=ultimo_video,
                        job_dir=job_dir_str,
                        telemetria=tele,
                    ),
                    on_telemetria_externa=on_telemetria,
                    **kwargs_dl,
                )
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
        if total_clips == 0:
            return

        subidos_en_lote = 0
        state_lock = threading.Lock()
        yt_lock = threading.Lock()
        cola_estados: queue.Queue[Tuple[str, Dict[str, Any]]] = queue.Queue()
        progreso_clip: Dict[int, float] = {idx: 0.0 for idx in range(1, total_clips + 1)}
        clips_activos_map: Dict[int, Dict[str, Any]] = {}
        acepta_clip_idx = _acepta_kwarg(procesar_clip_ffmpeg, "clip_indice")
        acepta_total_clips = _acepta_kwarg(procesar_clip_ffmpeg, "total_clips")
        acepta_on_log = _acepta_kwarg(procesar_clip_ffmpeg, "on_log")
        acepta_on_tele = _acepta_kwarg(procesar_clip_ffmpeg, "on_telemetria")
        acepta_alinear_subs = _acepta_kwarg(procesar_clip_ffmpeg, "alinear_subtitulos")

        def _emitir_en_cola_seguro(
            fase: str,
            mensaje: str,
            tele_payload: Dict[str, Any],
            progreso_override: Optional[float] = None,
        ) -> None:
            with state_lock:
                activos_snapshot = [dict(clips_activos_map[k]) for k in sorted(clips_activos_map)]
                tele_envio = dict(tele_payload)
                tele_envio["clips_activos"] = activos_snapshot
                if progreso_override is not None:
                    prog_global = progreso_override
                else:
                    prog_global = min(
                        0.95,
                        0.60 + 0.35 * (sum(progreso_clip.values()) / max(1, total_clips)),
                    )
                if on_telemetria is not None:
                    try:
                        on_telemetria(dict(tele_envio))
                    except Exception:
                        pass
                estado = _emitir_estado(
                    fase=fase,
                    progreso=prog_global,
                    mensaje=mensaje,
                    clips=[dict(c) for c in clips],
                    ultimo_video=ultimo_video,
                    job_dir=job_dir_str,
                    telemetria=tele_envio,
                )
            cola_estados.put(("estado", estado))

        def _procesar_un_clip(idx: int, clip: dict) -> None:
            nonlocal ultimo_video, subidos_en_lote
            cid = clip.get("id", idx)
            c_tit = clip.get("titulo", "")
            _log(
                f"Procesando Clip #{cid}/{total_clips} ({clip.get('inicio')} -> {clip.get('fin')})..."
            )
            with state_lock:
                clips_activos_map[idx] = {
                    "clip_id": str(cid),
                    "clip_indice": idx,
                    "estado": "renderizando",
                    "porcentaje": 0.0,
                    "encoder": "detectando...",
                    "fps": "--",
                    "velocidad_x": "--",
                    "velocidad_render": "--",
                }

            tele_render_init = {
                "etapa": "render",
                "titulo_etapa": f"Renderizando Clip #{cid} ({idx}/{total_clips})",
                "porcentaje": 0.0,
                "fps": "--",
                "velocidad_x": "--",
                "velocidad_render": "--",
                "eta": "--:--",
                "encoder": "detectando...",
                "clip_id": str(cid),
                "clip_indice": idx,
                "total_clips": total_clips,
                "detalle": f"Preparando composición 9:16 del Clip #{cid}",
            }
            _emitir_en_cola_seguro(
                fase="render",
                mensaje=f"Renderizando Clip #{cid}/{total_clips}: {c_tit}",
                tele_payload=tele_render_init,
            )

            def _on_tele_clip(datos: Dict[str, Any]) -> None:
                copia = dict(datos or {})
                pct_clip = float(copia.get("porcentaje", 0.0))
                vel_clip = str(copia.get("velocidad_x") or copia.get("velocidad_render") or "--")
                with state_lock:
                    progreso_clip[idx] = max(
                        progreso_clip.get(idx, 0.0),
                        min(1.0, max(0.0, pct_clip / 100.0)),
                    )
                    clips_activos_map[idx] = {
                        "clip_id": str(copia.get("clip_id") or cid),
                        "clip_indice": idx,
                        "estado": "renderizando",
                        "porcentaje": round(pct_clip, 1),
                        "encoder": str(copia.get("encoder") or ""),
                        "fps": str(copia.get("fps") or "--"),
                        "velocidad_x": vel_clip,
                        "velocidad_render": vel_clip,
                    }
                _emitir_en_cola_seguro(
                    fase="render",
                    mensaje=(
                        f"Renderizando Clip #{cid}/{total_clips}: {c_tit} "
                        f"[{pct_clip:.1f}% • {copia.get('encoder', '')}]"
                    ),
                    tele_payload=copia,
                )

            try:
                ruta_existente = clip.get("archivo_local")
                if (
                    clip.get("render_status") == "OK"
                    and ruta_existente
                    and os.path.isfile(str(ruta_existente))
                    and os.path.getsize(str(ruta_existente)) > 0
                ):
                    salida = str(Path(str(ruta_existente)).resolve())
                    with state_lock:
                        clip["archivo_local"] = salida
                        ultimo_video = salida
                        progreso_clip[idx] = 1.0
                    _log(f"✓ Reutilizando Clip #{cid} ya renderizado en caché: {salida}")
                else:
                    kwargs_render: Dict[str, Any] = {
                        "job_id": job_id,
                        "subtitulos": clip.get("subtitulos"),
                        "job_dir": job_dir,
                    }
                    if acepta_clip_idx:
                        kwargs_render["clip_indice"] = idx
                    if acepta_total_clips:
                        kwargs_render["total_clips"] = total_clips
                    if acepta_on_log:
                        kwargs_render["on_log"] = _log
                    if acepta_on_tele:
                        kwargs_render["on_telemetria"] = _on_tele_clip
                    if acepta_alinear_subs:
                        kwargs_render["alinear_subtitulos"] = (
                            bool(alinear_subtitulos)
                            and clip.get("subtitulos_origen") != "whisper_word_timestamps"
                        )

                    salida = procesar_clip_ffmpeg(
                        entrada_render,
                        clip.get("inicio"),
                        clip.get("fin"),
                        str(cid),
                        **kwargs_render,
                    )
                    with state_lock:
                        clip["archivo_local"] = salida
                        clip["render_status"] = "OK"
                        ultimo_video = salida
                        progreso_clip[idx] = 1.0
                    _log(f"✓ Clip #{cid} renderizado en: {salida}")

                if clip.get("youtube_url") or clip.get("youtube_id"):
                    _log(f"✓ Clip #{cid} ya registrado en YouTube ({clip.get('youtube_url') or clip.get('youtube_id')}); omitiendo re-subida.")
                elif not subir_youtube:
                    with state_lock:
                        clip["youtube_status"] = "Subida omitida (--sin-subida)"
                elif youtube_client is None:
                    with state_lock:
                        clip["youtube_status"] = "Pendiente de subida (Sin credenciales activas)"
                else:
                    with yt_lock:
                        cuota = verificar_cuota_diaria(limite_diario=LIMITE_CUOTA_DIARIA_SHORTS)
                        if not cuota["permitido"]:
                            with state_lock:
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

                            with state_lock:
                                clips_activos_map[idx] = {
                                    "clip_id": str(cid),
                                    "clip_indice": idx,
                                    "estado": "subiendo_youtube",
                                    "porcentaje": 100.0,
                                    "encoder": "youtube_api",
                                    "fps": "--",
                                    "velocidad_x": "--",
                                }
                                prog_actual = min(
                                    0.98,
                                    0.60
                                    + 0.35 * (sum(progreso_clip.values()) / max(1, total_clips))
                                    + (0.15 / max(1, total_clips)),
                                )

                            tele_yt = {
                                "etapa": "youtube",
                                "titulo_etapa": f"Subiendo Clip #{cid} a YouTube Shorts",
                                "porcentaje": round((idx / max(1, total_clips)) * 100.0, 1),
                                "eta": "--:--",
                                "clip_id": str(cid),
                                "clip_indice": idx,
                                "total_clips": total_clips,
                                "detalle": msg_yt,
                            }
                            _emitir_en_cola_seguro(
                                fase="youtube",
                                mensaje=msg_yt,
                                tele_payload=tele_yt,
                                progreso_override=prog_actual,
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
                                with state_lock:
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
                                with state_lock:
                                    clip["youtube_status"] = f"Error subida ({str(e_yt)[:80]})"
            except Exception as e_clip:
                err_txt = str(e_clip)
                with state_lock:
                    clip["render_status"] = f"Error render ({err_txt[:120]})"
                    clip["youtube_status"] = f"No renderizado ({err_txt[:80]})"
                    progreso_clip[idx] = 1.0
                _log(f"[ERROR] Falló procesamiento del Clip #{cid}: {err_txt}")
            finally:
                # Persistencia incremental thread-safe tras cada clip sin abortar el lote
                with state_lock:
                    clips_activos_map.pop(idx, None)
                    _guardar_y_sincronizar_clips(clips, job_dir=job_dir)

        executor = concurrent.futures.ThreadPoolExecutor(max_workers=2)
        try:
            futuros = [
                executor.submit(_procesar_un_clip, idx, clip)
                for idx, clip in enumerate(clips, start=1)
            ]
            while True:
                try:
                    tipo, payload = cola_estados.get(timeout=0.5)
                    if tipo == "estado":
                        yield payload
                except queue.Empty:
                    if all(f.done() for f in futuros) and cola_estados.empty():
                        break

            while not cola_estados.empty():
                tipo, payload = cola_estados.get_nowait()
                if tipo == "estado":
                    yield payload

            for fut in futuros:
                fut.result()
        except BaseException:
            terminar_procesos_activos()
            executor.shutdown(wait=False, cancel_futures=True)
            raise
        else:
            executor.shutdown(wait=True)
    finally:
        if job_id:
            STREAM_URL_CACHE.invalidar(job_id)
        if fuente_local and os.path.exists(fuente_local):
            try:
                os.remove(fuente_local)
            except OSError:
                pass


def _limpiar_jobs_antiguos(
    dias_retencion: int = 7,
    job_dir_actual: Optional[Path] = None,
) -> int:
    """Elimina de CARPETA_JOBS los subdirectorios cuya st_mtime supere dias_retencion días (ignorando job_dir_actual)."""
    if not CARPETA_JOBS.exists() or not CARPETA_JOBS.is_dir():
        return 0

    actual_resuelto = Path(job_dir_actual).resolve() if job_dir_actual is not None else None
    limite_ts = time.time() - (max(0.0, float(dias_retencion)) * 86400.0)
    eliminados = 0

    try:
        entradas = list(CARPETA_JOBS.iterdir())
    except OSError:
        return 0

    for entrada in entradas:
        try:
            if not entrada.is_dir() or entrada.is_symlink():
                continue
            if actual_resuelto is not None and entrada.resolve() == actual_resuelto:
                continue
            if entrada.stat().st_mtime < limite_ts:
                shutil.rmtree(entrada, ignore_errors=True)
                eliminados += 1
        except OSError:
            continue

    return eliminados


def ejecutar_pipeline_completo(
    url: str,
    modelo_preferido: Optional[str] = None,
    solo_analisis: bool = False,
    subir_youtube: bool = True,
    publish_at_inicio: Optional[str] = None,
    intervalo_horas: int | float = 0,
    on_log: Optional[Callable[[str], None]] = None,
    on_telemetria: Optional[Callable[[Dict[str, Any]], None]] = None,
    motor_ia: str = "gemini",
    modelo_local: Optional[str] = None,
    respaldo_local_auto: bool = True,
    job_dir: Optional[Path | str] = None,
) -> Generator[Dict[str, Any], None, None]:
    """Orquestador único (CLI y GUI) que ejecuta el pipeline híbrido (Gemini/Local) con telemetría y reanudación."""
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

    motor_normalizado = str(motor_ia or "gemini").strip().lower()
    if motor_normalizado not in ("gemini", "local"):
        motor_normalizado = "gemini"

    if motor_normalizado != "local" and not os.environ.get("GEMINI_API_KEY"):
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

    reanudando = False
    if job_dir:
        ruta_jdir = Path(job_dir).resolve()
        reanudando = ruta_jdir.exists()
        ruta_jdir.mkdir(parents=True, exist_ok=True)
        ctx = JobContext(job_id=ruta_jdir.name, job_dir=ruta_jdir)
    else:
        ctx = crear_contexto_job(url_limpia)

    try:
        eliminados = _limpiar_jobs_antiguos(dias_retencion=7, job_dir_actual=ctx.job_dir)
        if eliminados:
            _log(
                f"Limpieza automática: {eliminados} carpeta(s) antigua(s) (>7 días) "
                f"eliminada(s) de {CARPETA_JOBS}"
            )
    except OSError:
        pass
    job_dir_str = str(ctx.job_dir)
    _log(f"{'Reanudando' if reanudando else 'Iniciando'} Job {ctx.job_id} en {ctx.job_dir}")

    audio_temp: Optional[str] = None
    clips: List[dict] = []
    ultimo_video: Optional[str] = None
    pipeline_completado = False

    try:
        audio_cache = ctx.job_dir / "temp_audio.mp3"
        clips_cache = ctx.job_dir / "clips.json"
        if reanudando and clips_cache.is_file():
            try:
                datos_cache = json.loads(clips_cache.read_text(encoding="utf-8"))
                if isinstance(datos_cache, list) and datos_cache:
                    clips = [c for c in datos_cache if isinstance(c, dict)]
            except (OSError, json.JSONDecodeError, ValueError):
                clips = []

        if reanudando and audio_cache.is_file() and audio_cache.stat().st_size > 10_240:
            audio_temp = str(audio_cache.resolve())
            duracion = obtener_duracion_media(audio_temp)
            dur_str = segundos_a_hhmmss(duracion) if duracion else "Desconocida"
            _log(f"✓ Reutilizando audio en caché ({audio_temp}) | Duración: {dur_str}")
        else:
            _log(f"Fase 1/4: Extrayendo pista de audio desde {url_limpia}...")
            tele_audio_init = {
                "etapa": "descarga",
                "titulo_etapa": "Descargando Audio del Stream (16 Hilos)",
                "porcentaje": 0.0,
                "velocidad_red": "--",
                "tamano_total": "--",
                "eta": "--:--",
                "detalle": f"Preparando extracción en jobs/{ctx.job_id}",
            }
            if on_telemetria is not None:
                on_telemetria(dict(tele_audio_init))
            yield _emitir_estado(
                fase="audio",
                progreso=0.05,
                mensaje=f"Fase 1/4: Extrayendo audio ligero en jobs/{ctx.job_id}...",
                clips=clips,
                ultimo_video=ultimo_video,
                job_dir=job_dir_str,
                telemetria=tele_audio_init,
            )
            kwargs_audio: Dict[str, Any] = {"job_dir": ctx.job_dir}
            if _acepta_kwarg(extraer_audio, "on_log"):
                kwargs_audio["on_log"] = _log
            audio_temp = yield from _ejecutar_paso_con_telemetria(
                extraer_audio,
                url_limpia,
                construir_estado=lambda tele: _emitir_estado(
                    fase="audio",
                    progreso=0.05 + 0.23 * (float(tele.get("porcentaje", 0.0)) / 100.0),
                    mensaje=(
                        f"Fase 1/4: {tele.get('titulo_etapa', 'Extrayendo audio')} "
                        f"({tele.get('porcentaje', 0):.1f}% • {tele.get('velocidad_red', '--')})"
                    ),
                    clips=clips,
                    ultimo_video=ultimo_video,
                    job_dir=job_dir_str,
                    telemetria=tele,
                ),
                on_telemetria_externa=on_telemetria,
                **kwargs_audio,
            )
            duracion = obtener_duracion_media(audio_temp)
            dur_str = segundos_a_hhmmss(duracion) if duracion else "Desconocida"
            _log(f"✓ Audio extraído correctamente ({audio_temp}) | Duración: {dur_str}")

        modelo_local_efectivo = _normalizar_modelo_ollama(modelo_local)
        motor_efectivo = motor_normalizado

        def _correr_analisis_local(modelo_loc: str) -> Generator[Dict[str, Any], None, List[dict]]:
            tele_local_init = {
                "etapa": "local_whisper",
                "titulo_etapa": "Transcripción Local (Whisper Medium)",
                "porcentaje": 0.0,
                "velocidad_red": "CPU int8",
                "tamano_total": "--",
                "eta": "--:--",
                "modelo_ia": modelo_loc,
                "detalle": f"Preparando análisis 100% offline (Whisper + {modelo_loc})...",
            }
            if on_telemetria is not None:
                on_telemetria(dict(tele_local_init))
            yield _emitir_estado(
                fase="local_whisper",
                progreso=0.30,
                mensaje=f"Fase 2/4: Transcribiendo offline con Whisper + {modelo_loc}...",
                clips=clips,
                ultimo_video=ultimo_video,
                job_dir=job_dir_str,
                telemetria=tele_local_init,
            )
            kwargs_local: Dict[str, Any] = {}
            if _acepta_kwarg(analizar_con_ollama, "modelo_local"):
                kwargs_local["modelo_local"] = modelo_loc
            if _acepta_kwarg(analizar_con_ollama, "duracion_total"):
                kwargs_local["duracion_total"] = duracion
            if _acepta_kwarg(analizar_con_ollama, "job_dir"):
                kwargs_local["job_dir"] = ctx.job_dir
            if _acepta_kwarg(analizar_con_ollama, "on_log"):
                kwargs_local["on_log"] = _log
            res_local = yield from _ejecutar_paso_con_telemetria(
                analizar_con_ollama,
                audio_temp,
                construir_estado=lambda tele: _emitir_estado(
                    fase=str(tele.get("etapa") or "local_ollama"),
                    progreso=0.30 + 0.24 * (float(tele.get("porcentaje", 0.0)) / 100.0),
                    mensaje=(
                        f"Fase 2/4: {tele.get('titulo_etapa', 'Análisis Local')} "
                        f"[{tele.get('detalle', '')}]"
                    ),
                    clips=clips,
                    ultimo_video=ultimo_video,
                    job_dir=job_dir_str,
                    telemetria=tele,
                ),
                on_telemetria_externa=on_telemetria,
                **kwargs_local,
            )
            return res_local

        if clips:
            _log(f"✓ Reutilizando {len(clips)} clip(s) desde caché de reanudación ({ctx.job_dir / 'clips.json'})")
            if any(c.get("motor_ia") == "local" or c.get("subtitulos_origen") == "whisper_word_timestamps" for c in clips):
                motor_efectivo = "local"
        elif motor_normalizado == "local":
            clips = yield from _correr_analisis_local(modelo_local_efectivo)
        else:
            modelo_label = (modelo_preferido or MODELOS_CANDIDATOS[0]).strip()
            tele_gemini_init = {
                "etapa": "gemini",
                "titulo_etapa": f"Analizando Narrativa Viral ({modelo_label})",
                "porcentaje": 0.0,
                "bloque_actual": 1,
                "bloques_completados": 0,
                "total_bloques": 1,
                "bloques_activos": [],
                "modelo_ia": modelo_label,
                "eta": "--:--",
                "detalle": "Iniciando análisis de momentos virales...",
            }
            if on_telemetria is not None:
                on_telemetria(dict(tele_gemini_init))
            yield _emitir_estado(
                fase="gemini",
                progreso=0.30,
                mensaje=f"Fase 2/4: Analizando narrativa viral con {modelo_label}...",
                clips=clips,
                ultimo_video=ultimo_video,
                job_dir=job_dir_str,
                telemetria=tele_gemini_init,
            )
            try:
                clips = yield from _ejecutar_paso_con_telemetria(
                    analizar_con_gemini,
                    audio_temp,
                    construir_estado=lambda tele: _emitir_estado(
                        fase="gemini",
                        progreso=0.30 + 0.24 * (float(tele.get("porcentaje", 0.0)) / 100.0),
                        mensaje=(
                            f"Fase 2/4: {tele.get('titulo_etapa', 'Análisis Gemini')} "
                            f"[{tele.get('detalle', '')}]"
                        ),
                        clips=clips,
                        ultimo_video=ultimo_video,
                        job_dir=job_dir_str,
                        telemetria=tele,
                    ),
                    on_telemetria_externa=on_telemetria,
                    duracion_total=duracion,
                    modelo_preferido=modelo_preferido,
                    job_dir=ctx.job_dir,
                    on_log=_log,
                )
            except Exception as err_gem:
                es_cuota_429 = isinstance(err_gem, GeminiQuotaExhaustedError) or (
                    "429" in str(err_gem)
                    or "RESOURCE_EXHAUSTED" in str(err_gem).upper()
                )
                if respaldo_local_auto and es_cuota_429:
                    _log(
                        f"[RESPALDO LOCAL] Cuotas Gemini 429 agotadas ({err_gem}); "
                        f"conmutando automáticamente a motor local (Whisper + {modelo_local_efectivo})..."
                    )
                    motor_efectivo = "local"
                    clips = yield from _correr_analisis_local(modelo_local_efectivo)
                else:
                    raise

        for c in clips:
            _log(
                f"  • Clip #{c['id']}: {c['titulo']} [{c['inicio']} -> {c['fin']}] | "
                f"Hook: {str(c.get('gancho', ''))[:45]}..."
            )

        if solo_analisis:
            pipeline_completado = True
            msg_fin = (
                f"Análisis viral completado ({len(clips)} clips) en jobs/{ctx.job_id}/clips.json y clips.json."
            )
            _log(f"✓ {msg_fin}")
            tele_fin = {
                "etapa": "completado",
                "titulo_etapa": "Análisis Viral Completado",
                "porcentaje": 100.0,
                "eta": "00:00",
                "detalle": msg_fin,
            }
            if on_telemetria is not None:
                on_telemetria(dict(tele_fin))
            yield _emitir_estado(
                fase="completado",
                progreso=1.0,
                mensaje=msg_fin,
                clips=clips,
                ultimo_video=None,
                job_dir=job_dir_str,
                telemetria=tele_fin,
            )
            return

        kwargs_orq: Dict[str, Any] = {
            "url": url_limpia,
            "clips": clips,
            "duracion_total": duracion,
            "subir_youtube": subir_youtube,
            "job_id": ctx.job_id,
            "job_dir": ctx.job_dir,
            "publish_at_inicio": publish_at_inicio,
            "intervalo_horas": intervalo_horas,
            "on_log": _log,
            "on_telemetria": on_telemetria,
        }
        if _acepta_kwarg(_orquestar_render_y_subida, "alinear_subtitulos"):
            kwargs_orq["alinear_subtitulos"] = motor_efectivo != "local"

        for estado_lote in _orquestar_render_y_subida(**kwargs_orq):
            if estado_lote.get("ultimo_video"):
                ultimo_video = estado_lote["ultimo_video"]
            yield estado_lote

        pipeline_completado = True
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
        tele_done = {
            "etapa": "completado",
            "titulo_etapa": "Pipeline Completado",
            "porcentaje": 100.0,
            "eta": "00:00",
            "detalle": msg_final,
        }
        if on_telemetria is not None:
            on_telemetria(dict(tele_done))
        yield _emitir_estado(
            fase="completado",
            progreso=1.0,
            mensaje=msg_final,
            clips=clips,
            ultimo_video=ultimo_video,
            job_dir=job_dir_str,
            telemetria=tele_done,
        )
    except Exception as e:
        err_msg = str(e)
        _log(f"[ERROR] {err_msg}")
        tele_err = {
            "etapa": "error",
            "titulo_etapa": "Error en Ejecución",
            "porcentaje": 0.0,
            "eta": "--:--",
            "detalle": err_msg,
        }
        if on_telemetria is not None:
            on_telemetria(dict(tele_err))
        yield _emitir_estado(
            fase="error",
            progreso=0.0,
            mensaje=f"Error en pipeline: {err_msg}",
            clips=clips,
            ultimo_video=ultimo_video,
            job_dir=job_dir_str,
            error=err_msg,
            telemetria=tele_err,
        )
    finally:
        STREAM_URL_CACHE.invalidar(ctx.job_id)
        if pipeline_completado and audio_temp and os.path.exists(audio_temp):
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


def _formatear_barra_cli(estado: Dict[str, Any], ancho_barra: int = 24) -> str:
    """Genera una línea de barra de progreso visual compacta para CLI a partir de estado/telemetría."""
    tele = estado.get("telemetria") or {}
    pct_raw = tele.get("porcentaje")
    if pct_raw is None:
        pct_raw = float(estado.get("progreso", 0.0)) * 100.0
    pct = max(0.0, min(100.0, float(pct_raw)))
    llenos = int(round((pct / 100.0) * ancho_barra))
    barra = "█" * llenos + "░" * max(0, ancho_barra - llenos)

    etapa = str(tele.get("etapa") or estado.get("fase") or "run").lower()
    partes = [f"[{barra}] {pct:5.1f}%"]

    if etapa in ("descarga", "descarga_video"):
        vel = tele.get("velocidad_red") or "--"
        tam = tele.get("tamano_total") or "--"
        eta = tele.get("eta") or "--:--"
        partes.extend([f"↓ {vel}", str(tam), f"ETA {eta}"])
    elif etapa == "local_whisper":
        vel = tele.get("velocidad_red") or "CPU int8"
        tam = tele.get("tamano_total") or "--"
        partes.extend([f"Whisper ({vel})", str(tam)])
    elif etapa == "local_ollama":
        modelo = tele.get("modelo_ia") or tele.get("velocidad_red") or MODELOS_LOCALES_OLLAMA[0]
        tam = tele.get("tamano_total") or "--"
        partes.extend([f"Ollama {modelo}", str(tam)])
    elif etapa == "gemini":
        modelo = tele.get("modelo_ia") or "Gemini"
        b_act = tele.get("bloque_actual")
        b_tot = tele.get("total_bloques")
        if b_act and b_tot:
            partes.append(f"Bloque {b_act}/{b_tot}")
        partes.append(str(modelo))
    elif etapa == "render":
        encoder = tele.get("encoder") or "ffmpeg"
        fps = tele.get("fps") or "--"
        vel_x = tele.get("velocidad_x") or tele.get("velocidad_render") or "--"
        eta = tele.get("eta") or "--:--"
        partes.extend([str(encoder), f"{fps} fps", str(vel_x), f"ETA {eta}"])
    elif etapa == "youtube":
        cid = tele.get("clip_id")
        partes.append(f"YouTube Shorts #{cid}" if cid else "YouTube Shorts")

    detalle = str(tele.get("detalle") or "").strip()
    if detalle and etapa not in ("render",):
        partes.append(detalle[:48])

    return " | ".join(partes)


class RenderizadorProgresoCLI:
    """Administra la impresión sincronizada de logs y barra de progreso visual en terminal."""

    def __init__(self, stream=None, es_tty: Optional[bool] = None) -> None:
        self.stream = stream if stream is not None else sys.stdout
        self.es_tty = bool(self.stream.isatty()) if es_tty is None else bool(es_tty)
        self._barra_activa = False
        self._ultima_etapa = ""
        self._ultimo_pct_no_tty = -10.0

    def log(self, mensaje: str) -> None:
        if self._barra_activa and self.es_tty:
            self.stream.write("\r\x1b[2K")
            self._barra_activa = False
        self.stream.write(f"{mensaje}\n")
        self.stream.flush()

    def actualizar(self, estado: Dict[str, Any]) -> None:
        tele = estado.get("telemetria") or {}
        if not tele:
            return
        etapa = str(tele.get("etapa") or estado.get("fase") or "")
        pct = float(tele.get("porcentaje", 0.0))
        linea = _formatear_barra_cli(estado)

        if self.es_tty:
            self.stream.write(f"\r\x1b[2K{linea}")
            self.stream.flush()
            self._barra_activa = True
            if pct >= 100.0 or etapa in ("completado", "error"):
                self.stream.write("\n")
                self.stream.flush()
                self._barra_activa = False
        else:
            cambio_etapa = etapa != self._ultima_etapa
            salto_pct = abs(pct - self._ultimo_pct_no_tty) >= 15.0 or pct >= 100.0
            if cambio_etapa or salto_pct:
                self.stream.write(f"{linea}\n")
                self.stream.flush()
                self._ultima_etapa = etapa
                self._ultimo_pct_no_tty = pct

    def finalizar(self) -> None:
        if self._barra_activa and self.es_tty:
            self.stream.write("\n")
            self.stream.flush()
            self._barra_activa = False


def main():
    parser = argparse.ArgumentParser(
        description="Pipeline híbrido v4.1 de clips virales Kicksazos (Gemini Cloud o 100% Local)"
    )
    parser.add_argument("url", help="URL del stream/VOD o ruta a un archivo de video local")
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
        "--motor",
        choices=["gemini", "local"],
        default="gemini",
        help="Motor de análisis viral: 'gemini' (nube) o 'local' (Whisper + Ollama 100%% offline)",
    )
    parser.add_argument(
        "--modelo",
        default=None,
        help="Modelo Gemini preferido para iniciar la cascada de inferencia en modo nube",
    )
    parser.add_argument(
        "--modelo-local",
        default=None,
        help=f"Modelo Ollama para análisis local (ej: {', '.join(MODELOS_LOCALES_OLLAMA)})",
    )
    parser.add_argument(
        "--sin-respaldo-local",
        action="store_true",
        help="Desactiva el cambio automático a motor local si Gemini agota todas sus cuotas 429",
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
    parser.add_argument(
        "--job-dir",
        default=None,
        help="Directorio de job existente (jobs/<id>) para reanudar desde checkpoints",
    )
    args = parser.parse_args()

    cli_ui = RenderizadorProgresoCLI()
    ultimo_estado: Optional[Dict[str, Any]] = None
    try:
        for estado in ejecutar_pipeline_completo(
            url=args.url,
            modelo_preferido=args.modelo,
            solo_analisis=args.solo_analisis,
            subir_youtube=not args.sin_subida,
            publish_at_inicio=args.publish_at,
            intervalo_horas=args.intervalo_horas,
            on_log=cli_ui.log,
            motor_ia=args.motor,
            modelo_local=args.modelo_local,
            respaldo_local_auto=not args.sin_respaldo_local,
            job_dir=args.job_dir,
        ):
            ultimo_estado = estado
            cli_ui.actualizar(estado)
    finally:
        terminar_procesos_activos()
        cli_ui.finalizar()

    if not ultimo_estado or ultimo_estado.get("error"):
        err = (ultimo_estado or {}).get("error") or "Error desconocido en el pipeline."
        print(f"\n[ERROR] Pipeline falló: {err}")
        sys.exit(1)

    job_dir_final = ultimo_estado.get("job_dir") or str(CARPETA_JOBS)
    print(f"\n✓ ¡Pipeline completado con éxito! ({ultimo_estado.get('mensaje')})")
    print(f"Revisa {CARPETA_SALIDA}, {job_dir_final} y {HISTORIAL_SUBIDAS_FILE}")


if __name__ == "__main__":
    main()
