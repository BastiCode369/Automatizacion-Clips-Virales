#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from pathlib import Path
BASE_DIR = Path(__file__).resolve().parent

from dotenv import load_dotenv
load_dotenv(BASE_DIR / ".env")

import argparse
from datetime import datetime, timedelta, timezone
import glob
import inspect
import json
import math
import os
import queue
import random
import re
import shutil
import subprocess
import sys
import threading
import time
from typing import Any, Callable, Dict, Generator, List, NamedTuple, Optional, Tuple
from urllib.parse import urlparse

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
    "gemini-3.7-flash",
    "gemini-3.5-flash-lite",
]
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
    """Genera un archivo .ass v3.2 estilizado en tercio medio-inferior (1080x1920) y devuelve su ruta absoluta."""
    ruta = Path(ruta_ass).resolve()
    ruta.parent.mkdir(parents=True, exist_ok=True)
    fuente_sub, _ = _obtener_fuente_y_dir_subtitulos()

    encabezado = "\n".join(
        [
            "[Script Info]",
            "Title: Kicksazos Shorts Subtitles",
            "ScriptType: v4.00+",
            "WrapStyle: 2",
            "ScaledBorderAndShadow: yes",
            "YCbCr Matrix: TV.709",
            "PlayResX: 1080",
            "PlayResY: 1920",
            "",
            "[V4+ Styles]",
            "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding",
            f"Style: Default,{fuente_sub},54,&H00FFFFFF,&H0000FFFF,&H00000000,&HA0000000,-1,0,0,0,100,100,1.5,0,1,5.5,3.5,2,65,210,550,1",
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


def _limpiar_y_parsear_json(
    texto: str, duracion_total: Optional[float] = None, permitir_vacio: bool = False
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
    if not isinstance(datos, list):
        raise ValueError("La respuesta JSON de Gemini no contiene una lista válida de clips.")
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
    res = subprocess.run(comando, capture_output=True, text=True, check=True)
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
    proc = subprocess.Popen(
        comando,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,
    )
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
        if getattr(proc, "poll", lambda: 0)() is None:
            try:
                proc.kill()
                proc.wait(timeout=2.0)
            except Exception:
                pass
        _cerrar_pipes_proceso(proc)

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
    """Extrae audio mono 16kHz/32k mediante descarga paralela yt-dlp (--newline) y fallback FFmpeg streaming."""
    def _log(msg: str) -> None:
        if on_log is not None:
            on_log(msg)
        else:
            print(msg)

    _log("\n[1/4] Extrayendo audio para análisis con IA...")
    directorio = Path(job_dir).resolve() if job_dir else BASE_DIR
    directorio.mkdir(parents=True, exist_ok=True)

    audio_salida = directorio / "temp_audio.mp3"
    for patron in (str(directorio / "temp_audio.*"), str(directorio / "temp_audio_chunk_*.mp3")):
        for viejo in glob.glob(patron):
            try:
                os.remove(viejo)
            except OSError:
                pass

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
            "ffmpeg:-vn -ac 1 -ar 16000 -b:a 32k",
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
            "16000",
            "-b:a",
            "32k",
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
    max_duracion_chunk: int = 2700,
    solapamiento: int = 90,
) -> List[Tuple[str, float, float]]:
    """Divide audios mayores a 55 min (>3300s) en bloques de 45 min con 90s de solapamiento usando ffmpeg -c copy."""
    ruta_src = Path(ruta_audio)
    if duracion_total <= 3300:
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
        _emitir_gem(0.18, modelo_inicial, f"Procesando audio en File API ({estado})...", forzar=True)
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
                _emitir_gem(
                    min(0.30, 0.18 + intentos_estado * 0.01),
                    modelo_inicial,
                    f"Esperando File API ({estado})...",
                )
            except Exception as e_get:
                _log(f"[AVISO] Error transitorio consultando estado del archivo: {e_get}")
        _log("✓ Archivo de audio listo y activo para inferencia.")

        prompt = construir_prompt_viral(duracion_bloque)

        orden_modelos = list(MODELOS_CANDIDATOS)
        if modelo_preferido and modelo_preferido.strip():
            pref = modelo_preferido.strip()
            orden_modelos = [pref] + [m for m in orden_modelos if m != pref]

        clips: Optional[List[dict]] = None
        modelo_usado: Optional[str] = None
        max_intentos = 4

        for modelo in orden_modelos:
            _log(f"Probando análisis en streaming con: {modelo}...")
            _emitir_gem(0.35, modelo, f"Iniciando inferencia streaming ({modelo})...", forzar=True)
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
                            response_schema=list[ClipViral],
                            temperature=0.20,
                        ),
                    )
                    for chunk in stream:
                        txt_chunk = getattr(chunk, "text", None)
                        if txt_chunk:
                            partes_texto.append(txt_chunk)
                            chars_recibidos += len(txt_chunk)
                            frac_stream = min(0.92, 0.40 + (chars_recibidos / 8000.0) * 0.52)
                            _emitir_gem(
                                frac_stream,
                                modelo,
                                f"Recibiendo respuesta JSON ({chars_recibidos} chars)...",
                            )

                    texto_respuesta = "".join(partes_texto).strip()
                    if not texto_respuesta:
                        raise ValueError("Respuesta vacía recibida desde el stream de Gemini.")

                    clips = _limpiar_y_parsear_json(
                        texto_respuesta,
                        duracion_total=duracion_bloque,
                        permitir_vacio=True,
                    )
                    modelo_usado = modelo
                    _log(f"✓ Análisis generado con éxito usando {modelo} ({len(clips)} clips)")
                    _emitir_gem(1.0, modelo, f"Completado con {modelo} ({len(clips)} clips)", forzar=True)
                    break
                except ServerError as e:
                    codigo_err = getattr(e, "code", None) or 503
                    _esperar_con_jitter(
                        intento,
                        base=4.0,
                        max_espera=25.0,
                        on_log=on_log,
                        contexto=(
                            f"[AVISO] Modelo {modelo} falló (código {codigo_err}, "
                            f"intento {intento}/{max_intentos}) antes de {accion_siguiente}: {e}"
                        ),
                    )
                except APIError as e:
                    codigo_err = getattr(e, "code", None) or "APIError"
                    detalle_err = getattr(e, "message", None) or str(e)
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
                        _esperar_con_jitter(
                            intento,
                            base=4.0,
                            max_espera=25.0,
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
                        base=4.0,
                        max_espera=25.0,
                        on_log=on_log,
                        contexto=(
                            f"[AVISO] Modelo {modelo} falló (error {codigo_err}, "
                            f"intento {intento}/{max_intentos}) antes de {accion_siguiente}: {e}"
                        ),
                    )
            if clips is not None:
                break

        if clips is None:
            raise RuntimeError("No se pudo obtener una respuesta JSON válida de los modelos disponibles.")

        for c in clips:
            c["modelo_ia"] = modelo_usado
        return clips
    finally:
        if archivo_subido is not None and getattr(archivo_subido, "name", None):
            try:
                client.files.delete(name=archivo_subido.name)
            except Exception:
                pass


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
    """Segmenta audios largos (>55 min) si aplica, sube a Gemini File API, consolida offsets y guarda clips.json."""
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
            "total_bloques": 1,
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
                f"Audio de {segundos_a_hhmmss(duracion_efectiva)} (> 55 min): "
                f"segmentando en {len(chunks)} bloques de hasta 45 min con 90s de solapamiento..."
            )

        clips_acumulados: List[dict] = []
        ultimo_error: Optional[Exception] = None
        total_bloques = len(chunks)
        acepta_tele = _acepta_kwarg(_analizar_archivo_audio_gemini, "on_telemetria")

        for idx_chunk, (ruta_chunk, offset_seg, dur_chunk) in enumerate(chunks, start=1):
            if len(chunks) > 1 and dur_chunk is not None:
                _log(
                    f"Analizando bloque {idx_chunk}/{total_bloques} "
                    f"[{segundos_a_hhmmss(offset_seg)} -> {segundos_a_hhmmss(offset_seg + dur_chunk)}]..."
                )
            _emitir_telemetria(
                on_telemetria,
                [0.0],
                {
                    "etapa": "gemini",
                    "titulo_etapa": f"Analizando Narrativa Viral ({modelo_label})",
                    "porcentaje": round(((idx_chunk - 1) / max(1, total_bloques)) * 100.0, 1),
                    "bloque_actual": idx_chunk,
                    "total_bloques": total_bloques,
                    "modelo_ia": modelo_label,
                    "eta": "--:--",
                    "detalle": (
                        f"Bloque {idx_chunk}/{total_bloques}"
                        + (
                            f" [{segundos_a_hhmmss(offset_seg)} → {segundos_a_hhmmss(offset_seg + dur_chunk)}]"
                            if dur_chunk is not None
                            else ""
                        )
                    ),
                },
                forzar=True,
            )
            try:
                if acepta_tele:
                    clips_chunk = _analizar_archivo_audio_gemini(
                        client,
                        ruta_chunk,
                        dur_chunk,
                        modelo_preferido,
                        _log,
                        on_telemetria=on_telemetria,
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
                ultimo_error = e_chunk
                if len(chunks) == 1:
                    raise
                _log(f"[AVISO] Falló análisis del bloque {idx_chunk}/{total_bloques}: {e_chunk}")
                continue

            if not acepta_tele:
                _emitir_telemetria(
                    on_telemetria,
                    [0.0],
                    {
                        "etapa": "gemini",
                        "titulo_etapa": f"Analizando Narrativa Viral ({modelo_label})",
                        "porcentaje": round((idx_chunk / max(1, total_bloques)) * 100.0, 1),
                        "bloque_actual": idx_chunk,
                        "total_bloques": total_bloques,
                        "modelo_ia": modelo_label,
                        "eta": "--:--",
                        "detalle": f"Bloque {idx_chunk}/{total_bloques} completado ({len(clips_chunk)} clips)",
                    },
                    forzar=True,
                )

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
                clips_acumulados.append(clip_ajustado)

        clips_finales = _deduplicar_clips_solapados(clips_acumulados)
        if not clips_finales:
            if ultimo_error is not None:
                raise ultimo_error
            raise RuntimeError("No se detectaron clips virales válidos en ninguno de los bloques del audio.")

        _guardar_y_sincronizar_clips(clips_finales, job_dir=job_dir)
        _log(f"✓ Se detectaron {len(clips_finales)} momentos virales con SEO completo y se guardaron en clips.json")
        return clips_finales
    finally:
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
        "-f",
        FORMATOS_VIDEO_RAPIDOS,
        "--merge-output-format",
        "mp4",
        "-o",
        str(ruta_destino),
        url,
    ]
    _ejecutar_descarga_con_telemetria(
        comando,
        on_telemetria=on_telemetria,
        etapa="descarga_video",
        titulo_etapa="Descargando Video Fuente (1080p)",
        detalle_default="Descarga 1080p activa",
    )
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
        proc = subprocess.Popen(
            comando,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            errors="replace",
            bufsize=1,
        )
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
            if getattr(proc, "poll", lambda: 0)() is None:
                try:
                    proc.kill()
                    proc.wait(timeout=2.0)
                except Exception:
                    pass
            hilo_err.join(timeout=2.0)
            _cerrar_pipes_proceso(proc)

        salida_txt = "".join(stderr_chunks)
        if returncode != 0:
            raise subprocess.CalledProcessError(returncode, comando, output=salida_txt, stderr=salida_txt)
        return salida_txt

    proc = subprocess.Popen(
        comando,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
    )
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
        if getattr(proc, "poll", lambda: 0)() is None:
            try:
                proc.kill()
                proc.wait(timeout=2.0)
            except Exception:
                pass
        _cerrar_pipes_proceso(proc)

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
        ruta_esc = _escapar_ruta_ffmpeg_filtro(ruta_ass)
        if fonts_dir:
            fonts_esc = _escapar_ruta_ffmpeg_filtro(fonts_dir)
            cadena_final.append(f"subtitles='{ruta_esc}':fontsdir='{fonts_esc}'")
        else:
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
    on_telemetria: Optional[Callable[[Dict[str, Any]], None]] = None,
    clip_indice: Optional[int] = None,
    total_clips: Optional[int] = None,
    on_log: Optional[Callable[[str], None]] = None,
) -> str:
    """Extrae el clip con input seek (-ss) y corte exacto (-t), renderiza 9:16 por VAAPI/CPU, watermark adaptativa y .ass con telemetría."""
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

    _log(
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
    fuente_sub, fonts_dir_sub = _obtener_fuente_y_dir_subtitulos()
    if ruta_ass:
        _log(
            f"✓ Subtítulos dinámicos generados en: {ruta_ass} "
            f"[fuente={fuente_sub}, fontsdir={fonts_dir_sub or 'sistema'}]"
        )

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
    etiqueta_clip = f"Renderizando Clip #{id_clip}" + (
        f" ({clip_indice}/{total_clips})" if clip_indice and total_clips else ""
    )

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
            fonts_dir=fonts_dir_sub if ruta_ass_activa else None,
        )
        _log(
            f"Renderizando composición 9:16 con FFmpeg [encoder={encoder_activo}, "
            f"wm_y={y_watermark}, subs={'sí' if ruta_ass_activa else 'no'}]..."
        )
        _emitir_telemetria(
            on_telemetria,
            [0.0],
            {
                "etapa": "render",
                "titulo_etapa": etiqueta_clip,
                "porcentaje": 0.0,
                "fps": "--",
                "velocidad_x": "--",
                "eta": "--:--",
                "encoder": encoder_activo,
                "clip_id": str(id_clip),
                "clip_indice": clip_indice,
                "total_clips": total_clips,
                "frame": 0,
                "out_time": "00:00:00",
                "duracion_clip": duracion_clip,
                "detalle": f"Iniciando render {encoder_activo}...",
            },
            forzar=True,
        )

        def _on_prog_ffmpeg(prog: Dict[str, Any]) -> None:
            if on_telemetria is None:
                return
            on_telemetria(
                {
                    "etapa": "render",
                    "titulo_etapa": etiqueta_clip,
                    "porcentaje": prog["porcentaje"],
                    "fps": prog["fps_str"],
                    "velocidad_x": prog["speed_str"],
                    "eta": prog["eta_str"],
                    "encoder": encoder_activo,
                    "clip_id": str(id_clip),
                    "clip_indice": clip_indice,
                    "total_clips": total_clips,
                    "frame": prog["frame"],
                    "out_time": prog["out_time_str"],
                    "duracion_clip": duracion_clip,
                    "detalle": (
                        f"Encoder {encoder_activo} • {prog['fps_str']} fps • "
                        f"{prog['speed_str']} • ETA {prog['eta_str']}"
                    ),
                }
            )

        try:
            _ejecutar_comando_con_captura(
                comando_ffmpeg,
                duracion_objetivo=duracion_clip,
                on_progreso=_on_prog_ffmpeg if on_telemetria is not None else None,
            )
            break
        except subprocess.CalledProcessError as err:
            if archivo_salida.exists():
                try:
                    archivo_salida.unlink()
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

            if ruta_ass_activa and re.search(
                r"Parsed_subtitles|subtitles|libass|\.ass", stderr_txt, re.IGNORECASE
            ):
                _log(
                    "[AVISO] El filtro de subtítulos .ass falló; "
                    "reintentando render del clip sin subtítulos..."
                )
                ruta_ass_activa = None
                continue

            if encoder_activo == "h264_vaapi":
                _log(
                    "[AVISO] Renderizado VAAPI falló en ejecución; "
                    "reintentando automáticamente con CPU (libx264)..."
                )
                encoder_activo = "libx264"
                continue

            if ruta_ass_activa:
                _log(
                    "[AVISO] Renderizado falló con subtítulos activos; "
                    "reintentando sin subtítulos..."
                )
                ruta_ass_activa = None
                continue

            raise

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
    """Ejecuta una etapa bloqueante en hilo worker re-emitiendo su telemetría en vivo por el generador."""
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
    while True:
        tipo, payload = cola.get()
        if tipo == "tele":
            yield construir_estado(payload)
        elif tipo == "ok":
            hilo.join(timeout=1.0)
            return payload
        elif tipo == "err":
            hilo.join(timeout=1.0)
            raise payload


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
) -> Generator[Dict[str, Any], None, None]:
    """Orquestador compartido de Fase 3+4 con tolerancia a fallos por clip, telemetría en vivo y control de cuota."""
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
        # Para videos <= 1h descargar una sola vez evita múltiples conexiones HTTP/HLS lentas
        if duracion_total is None or duracion_total <= 3600:
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
        subidos_en_lote = 0

        for idx, clip in enumerate(clips, start=1):
            cid = clip.get("id", idx)
            frac_inicio = 0.60 + (0.35 * (idx - 1) / max(1, total_clips))
            frac_span = 0.35 / max(1, total_clips)
            _log(
                f"Procesando Clip #{cid}/{total_clips} ({clip.get('inicio')} -> {clip.get('fin')})..."
            )
            tele_render_init = {
                "etapa": "render",
                "titulo_etapa": f"Renderizando Clip #{cid} ({idx}/{total_clips})",
                "porcentaje": 0.0,
                "fps": "--",
                "velocidad_x": "--",
                "eta": "--:--",
                "encoder": "detectando...",
                "clip_id": str(cid),
                "clip_indice": idx,
                "total_clips": total_clips,
                "detalle": f"Preparando composición 9:16 del Clip #{cid}",
            }
            if on_telemetria is not None:
                on_telemetria(dict(tele_render_init))
            yield _emitir_estado(
                fase="render",
                progreso=frac_inicio,
                mensaje=f"Renderizando Clip #{cid}/{total_clips}: {clip.get('titulo', '')}",
                clips=clips,
                ultimo_video=ultimo_video,
                job_dir=job_dir_str,
                telemetria=tele_render_init,
            )

            try:
                kwargs_render: Dict[str, Any] = {
                    "job_id": job_id,
                    "subtitulos": clip.get("subtitulos"),
                    "job_dir": job_dir,
                }
                if _acepta_kwarg(procesar_clip_ffmpeg, "clip_indice"):
                    kwargs_render["clip_indice"] = idx
                if _acepta_kwarg(procesar_clip_ffmpeg, "total_clips"):
                    kwargs_render["total_clips"] = total_clips
                if _acepta_kwarg(procesar_clip_ffmpeg, "on_log"):
                    kwargs_render["on_log"] = _log

                salida = yield from _ejecutar_paso_con_telemetria(
                    procesar_clip_ffmpeg,
                    entrada_render,
                    clip.get("inicio"),
                    clip.get("fin"),
                    str(cid),
                    construir_estado=lambda tele, fi=frac_inicio, fs=frac_span, c_id=cid, t_c=total_clips, c_tit=clip.get("titulo", ""): _emitir_estado(
                        fase="render",
                        progreso=min(0.95, fi + fs * (float(tele.get("porcentaje", 0.0)) / 100.0)),
                        mensaje=(
                            f"Renderizando Clip #{c_id}/{t_c}: {c_tit} "
                            f"[{tele.get('porcentaje', 0):.1f}% • {tele.get('encoder', '')}]"
                        ),
                        clips=clips,
                        ultimo_video=ultimo_video,
                        job_dir=job_dir_str,
                        telemetria=tele,
                    ),
                    on_telemetria_externa=on_telemetria,
                    **kwargs_render,
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
                        if on_telemetria is not None:
                            on_telemetria(dict(tele_yt))
                        yield _emitir_estado(
                            fase="youtube",
                            progreso=min(0.98, frac_inicio + (0.15 / max(1, total_clips))),
                            mensaje=msg_yt,
                            clips=clips,
                            ultimo_video=ultimo_video,
                            job_dir=job_dir_str,
                            telemetria=tele_yt,
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
    on_telemetria: Optional[Callable[[Dict[str, Any]], None]] = None,
) -> Generator[Dict[str, Any], None, None]:
    """Orquestador único (CLI y GUI) que ejecuta el pipeline completo y emite diccionarios de estado con telemetría."""
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

        modelo_label = (modelo_preferido or MODELOS_CANDIDATOS[0]).strip()
        tele_gemini_init = {
            "etapa": "gemini",
            "titulo_etapa": f"Analizando Narrativa Viral ({modelo_label})",
            "porcentaje": 0.0,
            "bloque_actual": 1,
            "total_bloques": 1,
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
            on_telemetria=on_telemetria,
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
        vel_x = tele.get("velocidad_x") or "--"
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
        ):
            ultimo_estado = estado
            cli_ui.actualizar(estado)
    finally:
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
