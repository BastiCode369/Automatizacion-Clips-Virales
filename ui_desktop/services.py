"""Servicios puros y seguros para la aplicación de escritorio Kicksazos Studio v5.0."""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import urllib.request
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

import pipeline_viral_clips as pvc
from subir_shorts import (
    HISTORIAL_SUBIDAS_FILE,
    autenticar_youtube,
    cargar_historial_subidas,
    subir_short,
    verificar_cuota_diaria,
)

PROYECTO_ROOT: Path = Path(pvc.BASE_DIR).resolve()
CARPETA_JOBS: Path = Path(pvc.CARPETA_JOBS)
CARPETA_SALIDA: Path = Path(pvc.CARPETA_SALIDA)
ARCHIVO_CLIPS: Path = PROYECTO_ROOT / "clips.json"
ARCHIVO_SUBIDAS: Path = Path(HISTORIAL_SUBIDAS_FILE)

ARCHIVOS_SECRETOS_PROHIBIDOS = frozenset(
    {
        ".env",
        "client_secret.json",
        "token.json",
        "token_cuenta_anterior.json",
    }
)


def validar_ruta_dentro_proyecto(
    ruta: str | Path,
    directorio_base: Optional[str | Path] = None,
) -> Path:
    """Valida que una ruta resuelva estrictamente dentro del proyecto/directorio base."""
    if ruta is None or not str(ruta).strip():
        raise ValueError("La ruta proporcionada está vacía.")

    base = Path(directorio_base).resolve() if directorio_base is not None else PROYECTO_ROOT
    candidata = Path(ruta)
    if not candidata.is_absolute():
        candidata = base / candidata
    resuelta = candidata.resolve(strict=False)

    if resuelta.name in ARCHIVOS_SECRETOS_PROHIBIDOS:
        raise PermissionError(f"Acceso denegado a archivo sensible: {resuelta.name}")

    if not resuelta.is_relative_to(base):
        raise ValueError(
            f"Ruta fuera del directorio permitido ({base}): {resuelta}"
        )
    return resuelta


def _leer_json_seguro(ruta: Path, defecto: Any) -> Any:
    if not ruta.exists() or not ruta.is_file():
        return defecto
    try:
        with ruta.open("r", encoding="utf-8") as fh:
            return json.load(fh)
    except Exception:
        return defecto


def _calcular_tamano_directorio_bytes(ruta_dir: Path) -> int:
    total = 0
    try:
        for entrada in ruta_dir.rglob("*"):
            if entrada.is_file() and not entrada.is_symlink():
                try:
                    total += entrada.stat().st_size
                except OSError:
                    pass
    except OSError:
        pass
    return total


def _inferir_fuente_desde_job_id(job_id: str) -> str:
    """Infiere un texto legible de origen para jobs antiguos sin job_meta.json."""
    limpio = re.sub(r"^\d{8}_\d{6}_", "", str(job_id or ""))
    limpio = re.sub(r"_[0-9a-f]{6,10}$", "", limpio)
    if not limpio:
        return "Origen local / sin metadatos"
    if limpio.startswith("kick_com_"):
        resto = limpio[len("kick_com_") :].replace("_", "/")
        return f"kick.com/{resto} (inferido)"
    if limpio.startswith(("youtube_com_", "youtu_be_")):
        return f"{limpio.replace('_', '/')} (inferido)"
    return f"{limpio.replace('_', ' ')} (inferido)"


def normalizar_estado_telemetria(estado: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """Normaliza cualquier payload de progreso del pipeline (anidado o plano) a un esquema uniforme."""
    datos = dict(estado or {})
    tele = dict(datos.get("telemetria") or {}) if isinstance(datos.get("telemetria"), dict) else {}
    fase = str(datos.get("fase") or tele.get("etapa") or "esperando").strip().lower()

    mapa_etapa = {
        "esperando": (0, "En espera"),
        "preparacion": (1, "Red & Audio"),
        "audio": (1, "Red & Audio"),
        "descarga": (1, "Red & Audio"),
        "analisis": (2, "Análisis IA"),
        "gemini": (2, "Análisis IA (Gemini)"),
        "groq": (2, "Análisis IA (Groq)"),
        "groq_whisper": (2, "Transcripción Nube (Groq Whisper)"),
        "local_whisper": (2, "Whisper Local"),
        "local_ollama": (2, "Ollama Local"),
        "ia": (2, "Análisis IA"),
        "transcripcion": (2, "Análisis IA"),
        "render": (3, "Render 9:16"),
        "subida": (4, "YouTube Shorts"),
        "youtube": (4, "YouTube Shorts"),
        "completado": (4, "Completado"),
        "error": (int(datos.get("etapa_num") or 1), "Error"),
    }
    etapa_default, nombre_default = mapa_etapa.get(fase, (1, fase.capitalize()))

    progreso_raw = tele.get("porcentaje")
    if progreso_raw is None:
        progreso_raw = datos.get("porcentaje")
    if progreso_raw is not None:
        progreso = max(0.0, min(100.0, float(progreso_raw)))
    else:
        p_val = float(datos.get("progreso") or 0.0)
        progreso = max(0.0, min(100.0, p_val * 100.0 if 0.0 < p_val <= 1.0 else p_val))

    if datos.get("progreso_global") is not None:
        progreso_global = max(0.0, min(100.0, float(datos["progreso_global"])))
    elif datos.get("progreso") is not None and 0.0 <= float(datos["progreso"]) <= 1.0:
        progreso_global = max(0.0, min(100.0, float(datos["progreso"]) * 100.0))
    else:
        total_etapas = max(1, int(datos.get("total_etapas") or 4))
        idx_etapa = max(0, int(datos.get("etapa_num") or etapa_default))
        if fase == "completado" or datos.get("completado"):
            progreso_global = 100.0
        elif idx_etapa <= 0:
            progreso_global = 0.0
        else:
            progreso_global = min(
                100.0,
                ((idx_etapa - 1) * (100.0 / total_etapas))
                + (progreso / total_etapas),
            )

    workers_norm: List[Dict[str, Any]] = []
    workers_crudos = datos.get("workers") or []
    if isinstance(workers_crudos, list):
        for w in workers_crudos:
            if isinstance(w, dict):
                workers_norm.append(
                    {
                        "id": str(w.get("id") or w.get("worker_id") or "worker"),
                        "etiqueta": str(
                            w.get("etiqueta")
                            or w.get("label")
                            or w.get("nombre")
                            or "Worker activo"
                        ),
                        "estado": str(w.get("estado") or "ejecutando"),
                        "progreso": max(
                            0.0, min(100.0, float(w.get("progreso") or 0.0))
                        ),
                        "fps": w.get("fps") or "—",
                        "velocidad": w.get("velocidad") or w.get("speed") or "—",
                        "eta": w.get("eta") or "—",
                    }
                )

    for c in tele.get("clips_activos") or []:
        if isinstance(c, dict):
            vel_c = c.get("velocidad_render") or c.get("velocidad_x") or "—"
            workers_norm.append(
                {
                    "id": f"clip_{c.get('clip_id', 'x')}",
                    "etiqueta": f"🎬 Clip #{c.get('clip_id', '?')}",
                    "estado": str(c.get("estado") or "renderizando"),
                    "progreso": max(
                        0.0, min(100.0, float(c.get("porcentaje") or 0.0))
                    ),
                    "fps": str(c.get("fps") or "—"),
                    "velocidad": str(vel_c),
                    "eta": str(c.get("eta") or tele.get("eta") or "—"),
                }
            )

    for b in tele.get("bloques_activos") or []:
        workers_norm.append(
            {
                "id": f"bloque_{b}",
                "etiqueta": f"🧠 {b}",
                "estado": "analizando",
                "progreso": progreso,
                "fps": "—",
                "velocidad": "Paralelo",
                "eta": str(tele.get("eta") or "—"),
            }
        )

    def _primer_valido(*candidatos: Any) -> str:
        for cand in candidatos:
            txt = str(cand or "").strip()
            if txt and txt not in ("--", "—", "None"):
                return txt
        return "—"

    vel = _primer_valido(
        datos.get("velocidad"),
        tele.get("velocidad_render"),
        tele.get("velocidad_x"),
        tele.get("velocidad_red"),
    )
    fps_val = _primer_valido(datos.get("fps"), tele.get("fps"))
    eta_val = _primer_valido(datos.get("eta"), tele.get("eta"))

    modelo_val = str(
        datos.get("modelo_activo")
        or datos.get("modelo")
        or tele.get("modelo_ia")
        or pvc.MODELOS_CANDIDATOS[0]
    )
    encoder_val = str(datos.get("encoder") or tele.get("encoder") or "auto")
    clips_lista = datos.get("clips") if isinstance(datos.get("clips"), list) else []
    clips_detectados = int(
        datos.get("clips_detectados") or len(clips_lista) or tele.get("total_clips") or 0
    )

    return {
        "fase": fase,
        "etapa_num": int(datos.get("etapa_num") or etapa_default),
        "total_etapas": int(datos.get("total_etapas") or 4),
        "etapa_nombre": str(
            datos.get("etapa_nombre") or tele.get("titulo_etapa") or nombre_default
        ),
        "progreso": round(progreso, 1),
        "progreso_global": round(progreso_global, 1),
        "fps": fps_val,
        "velocidad": str(vel),
        "eta": eta_val,
        "detalle": str(datos.get("detalle") or tele.get("detalle") or ""),
        "mensaje": str(datos.get("mensaje") or "Listo para iniciar"),
        "modelo_activo": modelo_val,
        "encoder": encoder_val,
        "motor_ia": str(datos.get("motor_ia") or "gemini"),
        "workers": workers_norm,
        "chunks_total": int(
            datos.get("chunks_total") or tele.get("total_bloques") or 0
        ),
        "chunks_completados": int(
            datos.get("chunks_completados") or tele.get("bloques_completados") or 0
        ),
        "clips_detectados": clips_detectados,
        "clips_renderizados": int(datos.get("clips_renderizados") or 0),
        "clips_subidos": int(datos.get("clips_subidos") or 0),
        "job_id": str(datos.get("job_id") or ""),
        "job_dir": str(datos.get("job_dir") or ""),
        "error": datos.get("error"),
        "completado": bool(datos.get("completado") or fase == "completado"),
    }


def consultar_cuota_diaria(ruta_subidas: Optional[Path | str] = None) -> Dict[str, Any]:
    """Consulta la cuota móvil de 24 horas para YouTube Shorts sin escribir secretos."""
    archivo = Path(ruta_subidas) if ruta_subidas is not None else ARCHIVO_SUBIDAS
    return verificar_cuota_diaria(
        limite_diario=pvc.LIMITE_CUOTA_DIARIA_SHORTS,
        ruta_json=archivo,
    )


def verificar_estado_ollama(timeout: float = 0.8) -> Dict[str, Any]:
    """Verifica si el demonio local Ollama responde y devuelve sus modelos instalados."""
    url_base = str(getattr(pvc, "OLLAMA_BASE_URL", "http://127.0.0.1:11434")).rstrip("/")
    req = urllib.request.Request(f"{url_base}/api/tags", method="GET")
    online = False
    modelos: List[str] = []
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            if getattr(resp, "status", 200) < 400:
                online = True
                raw = json.loads(resp.read().decode("utf-8", errors="ignore") or "{}")
                for item in raw.get("models") or []:
                    nombre = str(item.get("name") or "").strip()
                    if nombre:
                        modelos.append(nombre)
    except Exception:
        online = False

    if online and not modelos:
        try:
            modelos = list(pvc.listar_modelos_ollama_disponibles())
        except Exception:
            modelos = list(pvc.MODELOS_LOCALES_OLLAMA)

    return {
        "online": online,
        "url": url_base,
        "modelos": modelos or list(pvc.MODELOS_LOCALES_OLLAMA),
    }


def obtener_estado_sistema() -> Dict[str, Any]:
    """Recopila cuota YouTube, estado Ollama y encoder de hardware detectado."""
    try:
        cuota = consultar_cuota_diaria()
    except Exception:
        cuota = {
            "subidas_24h": 0,
            "limite": pvc.LIMITE_CUOTA_DIARIA_SHORTS,
            "restantes": pvc.LIMITE_CUOTA_DIARIA_SHORTS,
            "bloqueado": False,
        }
    ollama = verificar_estado_ollama()
    try:
        encoder = pvc.detectar_encoder_hardware()
    except Exception:
        encoder = "libx264"
    return {
        "cuota": cuota,
        "ollama": ollama,
        "encoder": encoder,
    }


def _resolver_archivo_mp4_clip(
    clip: Dict[str, Any],
    indice_fallback: int,
    job_id: str,
    carpeta_salida: Path,
) -> Optional[Path]:
    """Busca el archivo .mp4 renderizado correspondiente a un clip en clips_finales/."""
    ruta_cruda = clip.get("archivo_local") or clip.get("ruta_archivo") or ""
    if ruta_cruda:
        cand = Path(ruta_cruda)
        if not cand.is_absolute():
            cand = PROYECTO_ROOT / cand
        cand_res = cand.resolve(strict=False)
        if (
            cand_res.exists()
            and cand_res.is_file()
            and cand_res.is_relative_to(PROYECTO_ROOT)
        ):
            return cand_res

    clip_id = clip.get("id") or indice_fallback
    if carpeta_salida.exists():
        patrones: List[str] = []
        if job_id:
            patrones.append(f"{job_id}_clip_{clip_id}_*.mp4")
            patrones.append(f"{job_id}_clip_{indice_fallback}_*.mp4")
        patrones.append(f"clip_{clip_id}_*.mp4")
        for patron in patrones:
            coincidencias = sorted(carpeta_salida.glob(patron))
            if coincidencias:
                return coincidencias[0].resolve()
    return None


def _segundos_seguros(valor: Any) -> float:
    try:
        return max(0.0, float(pvc.hhmmss_a_segundos(valor)))
    except Exception:
        return 0.0


def cargar_clips_json(ruta_clips: Optional[Path | str] = None) -> List[Dict[str, Any]]:
    """Lee un archivo clips.json validando la ruta dentro del proyecto."""
    destino = validar_ruta_dentro_proyecto(ruta_clips or ARCHIVO_CLIPS)
    data = _leer_json_seguro(destino, [])
    return data if isinstance(data, list) else []


def guardar_clips_json(
    clips: List[Dict[str, Any]],
    job_dir: Optional[Path | str] = None,
) -> Tuple[Path, Optional[Path]]:
    """Guarda atómicamente clips.json raíz y el del job especificado usando _CLIPS_JSON_LOCK."""
    if not isinstance(clips, list):
        raise ValueError("clips debe ser una lista de diccionarios.")

    raiz_val = validar_ruta_dentro_proyecto(ARCHIVO_CLIPS)
    job_clips_val: Optional[Path] = None
    if job_dir is not None and str(job_dir).strip():
        job_dir_val = validar_ruta_dentro_proyecto(job_dir, directorio_base=CARPETA_JOBS)
        job_dir_val.mkdir(parents=True, exist_ok=True)
        job_clips_val = validar_ruta_dentro_proyecto(
            job_dir_val / "clips.json", directorio_base=CARPETA_JOBS
        )

    with pvc._CLIPS_JSON_LOCK:
        if job_clips_val is not None:
            pvc._escribir_json_atomico(job_clips_val, clips)
        pvc._escribir_json_atomico(raiz_val, clips)

    return raiz_val, job_clips_val


def actualizar_y_guardar_clip(
    clip_actualizado: Dict[str, Any],
    job_dir: Optional[Path | str] = None,
    ruta_clips: Optional[Path | str] = None,
) -> List[Dict[str, Any]]:
    """Actualiza un clip dentro del clips.json del job (y raíz) de forma atómica."""
    target_path: Optional[Path] = None
    if job_dir:
        job_dir_val = validar_ruta_dentro_proyecto(job_dir, directorio_base=CARPETA_JOBS)
        target_path = job_dir_val / "clips.json"
    elif ruta_clips:
        target_path = validar_ruta_dentro_proyecto(ruta_clips)
    else:
        target_path = validar_ruta_dentro_proyecto(ARCHIVO_CLIPS)

    clips = cargar_clips_json(target_path)
    clip_id_obj = clip_actualizado.get("id")
    inicio_s = _segundos_seguros(clip_actualizado.get("inicio"))
    fin_s = _segundos_seguros(clip_actualizado.get("fin"))
    duracion_s = round(max(0.0, fin_s - inicio_s), 2)

    nuevo_clip = dict(clip_actualizado)
    if duracion_s > 0:
        nuevo_clip["duracion_segundos"] = duracion_s

    reemplazado = False
    for idx, item in enumerate(clips):
        if clip_id_obj is not None and item.get("id") == clip_id_obj:
            merged = dict(item)
            merged.update(nuevo_clip)
            clips[idx] = merged
            reemplazado = True
            break

    if not reemplazado:
        clips.append(nuevo_clip)

    guardar_clips_json(clips, job_dir=job_dir if job_dir else None)
    return clips


def escanear_jobs(
    carpeta_jobs: Optional[Path | str] = None,
    carpeta_salida: Optional[Path | str] = None,
) -> List[Dict[str, Any]]:
    """Escanea jobs/ ordenados del más reciente al más antiguo con estado de checkpoints."""
    base_jobs = Path(carpeta_jobs) if carpeta_jobs is not None else CARPETA_JOBS
    base_salida = Path(carpeta_salida) if carpeta_salida is not None else CARPETA_SALIDA

    if not base_jobs.exists() or not base_jobs.is_dir():
        return []

    resultados: List[Dict[str, Any]] = []
    entradas = [p for p in base_jobs.iterdir() if p.is_dir() and not p.is_symlink()]
    entradas.sort(key=lambda p: (p.name, p.stat().st_mtime), reverse=True)

    for carpeta in entradas:
        job_id = carpeta.name
        meta = _leer_json_seguro(carpeta / "job_meta.json", {})
        if not isinstance(meta, dict):
            meta = {}

        audio_path = carpeta / "temp_audio.mp3"
        has_audio = audio_path.exists() and audio_path.stat().st_size > 10 * 1024

        whisper_path = carpeta / "whisper_transcript.json"
        has_whisper = whisper_path.exists() and whisper_path.stat().st_size > 2

        source_file = carpeta / "temp_source.mp4"
        has_source_video = source_file.exists() and source_file.stat().st_size > 50 * 1024

        clips_path = carpeta / "clips.json"
        clips = _leer_json_seguro(clips_path, [])
        if not isinstance(clips, list):
            clips = []
        total_clips = len(clips)

        renderizados = 0
        for idx, clip in enumerate(clips, start=1):
            if _resolver_archivo_mp4_clip(clip, idx, job_id, base_salida) is not None:
                renderizados += 1

        if total_clips == 0 and base_salida.exists():
            renderizados = len(list(base_salida.glob(f"{job_id}_clip_*.mp4")))

        tam_bytes = _calcular_tamano_directorio_bytes(carpeta)
        tam_mb = round(tam_bytes / (1024 * 1024), 2)

        if total_clips > 0 and renderizados >= total_clips:
            estado = "Completado"
        elif total_clips > 0 and renderizados == 0:
            estado = "Solo Análisis / Interrumpido"
        elif total_clips > 0 and renderizados < total_clips:
            estado = "Parcial / Reanudable"
        elif has_audio or has_whisper or has_source_video:
            estado = "Interrumpido / Incompleto"
        else:
            estado = "Vacío / Inicial"

        source_url = str(meta.get("source_url") or "").strip()
        fuente_display = (
            source_url
            if source_url
            else _inferir_fuente_desde_job_id(job_id)
        )

        fecha_str = str(meta.get("created_at") or "").strip()
        if not fecha_str:
            m = re.match(r"^(\d{4})(\d{2})(\d{2})_(\d{2})(\d{2})(\d{2})", job_id)
            if m:
                fecha_str = (
                    f"{m.group(1)}-{m.group(2)}-{m.group(3)} "
                    f"{m.group(4)}:{m.group(5)}:{m.group(6)}"
                )
            else:
                fecha_str = "Fecha desconocida"

        resultados.append(
            {
                "job_id": job_id,
                "job_dir": str(carpeta),
                "fecha": fecha_str,
                "source_url": source_url,
                "fuente_display": fuente_display,
                "motor_ia": str(meta.get("motor_ia") or "—"),
                "modelo_preferido": str(meta.get("modelo_preferido") or "—"),
                "has_audio": has_audio,
                "has_whisper": has_whisper,
                "has_clips": clips_path.exists() and total_clips > 0,
                "has_source_video": has_source_video,
                "total_clips": total_clips,
                "clips_renderizados": renderizados,
                "tamano_bytes": tam_bytes,
                "tamano_mb": tam_mb,
                "estado": estado,
                "completado": estado == "Completado",
            }
        )

    return resultados


def eliminar_job_seguro(
    job_dir: str | Path,
    carpeta_jobs: Optional[Path | str] = None,
) -> bool:
    """Elimina de forma segura un subdirectorio específico dentro de jobs/."""
    base_jobs = Path(carpeta_jobs).resolve() if carpeta_jobs is not None else CARPETA_JOBS.resolve()
    objetivo = validar_ruta_dentro_proyecto(job_dir, directorio_base=base_jobs)

    if objetivo == base_jobs:
        raise ValueError("No está permitido eliminar la carpeta raíz de jobs/.")
    if objetivo.parent != base_jobs:
        raise ValueError("Solo se pueden eliminar carpetas directas dentro de jobs/.")
    if not objetivo.exists() or not objetivo.is_dir():
        return False

    shutil.rmtree(objetivo)
    return True


def _indice_subidas_youtube(
    ruta_subidas: Optional[Path | str] = None,
) -> Dict[str, Dict[str, Any]]:
    archivo = Path(ruta_subidas) if ruta_subidas is not None else ARCHIVO_SUBIDAS
    historial = cargar_historial_subidas(ruta_json=archivo)
    por_ruta: Dict[str, Dict[str, Any]] = {}
    for entry in historial:
        ruta_arch = str(entry.get("ruta_archivo") or "")
        archivo_nombre = str(entry.get("archivo") or "")
        if ruta_arch:
            por_ruta[ruta_arch] = entry
        if archivo_nombre:
            por_ruta[archivo_nombre] = entry
    return por_ruta


def listar_clips_estudio(
    filtro_job: str = "TODOS",
    carpeta_jobs: Optional[Path | str] = None,
    carpeta_salida: Optional[Path | str] = None,
    ruta_subidas: Optional[Path | str] = None,
    archivo_clips_raiz: Optional[Path | str] = None,
) -> List[Dict[str, Any]]:
    """Lista los clips de todos los jobs / clips_finales enriquecidos para el Estudio."""
    base_jobs = Path(carpeta_jobs) if carpeta_jobs is not None else CARPETA_JOBS
    base_salida = Path(carpeta_salida) if carpeta_salida is not None else CARPETA_SALIDA
    raiz_clips = Path(archivo_clips_raiz) if archivo_clips_raiz is not None else ARCHIVO_CLIPS
    subidas_idx = _indice_subidas_youtube(ruta_subidas)

    items: List[Dict[str, Any]] = []
    archivos_vistos: set[str] = set()

    jobs = escanear_jobs(carpeta_jobs=base_jobs, carpeta_salida=base_salida)
    for job in jobs:
        job_id = job["job_id"]
        if filtro_job not in ("TODOS", "CLIPS_FINALES", job_id):
            continue

        job_dir_path = Path(job["job_dir"])
        clips = _leer_json_seguro(job_dir_path / "clips.json", [])
        if not isinstance(clips, list):
            continue

        for idx, clip in enumerate(clips, start=1):
            mp4 = _resolver_archivo_mp4_clip(clip, idx, job_id, base_salida)
            if mp4 is not None:
                archivos_vistos.add(str(mp4.resolve()))
            yt_entry = None
            if mp4 is not None:
                yt_entry = subidas_idx.get(str(mp4)) or subidas_idx.get(mp4.name)

            dur = clip.get("duracion_segundos")
            if not dur:
                dur = round(
                    max(
                        0.0,
                        _segundos_seguros(clip.get("fin"))
                        - _segundos_seguros(clip.get("inicio")),
                    ),
                    1,
                )

            if yt_entry:
                estado = "Subido YT"
            elif mp4 is not None:
                estado = "Renderizado OK"
            else:
                estado = "Pendiente"

            items.append(
                {
                    "job_id": job_id,
                    "job_dir": str(job_dir_path),
                    "source_url": job.get("source_url") or "",
                    "fuente_display": job.get("fuente_display") or job_id,
                    "clip_index": idx,
                    "clip_data": dict(clip),
                    "id": clip.get("id", idx),
                    "titulo": str(clip.get("titulo") or f"Clip #{clip.get('id', idx)}"),
                    "gancho": str(clip.get("gancho") or ""),
                    "gancho_visual_portada": str(clip.get("gancho_visual_portada") or ""),
                    "caption_tiktok": str(clip.get("caption_tiktok") or ""),
                    "descripcion": str(clip.get("descripcion") or ""),
                    "etiquetas": list(clip.get("etiquetas") or []),
                    "hashtags_tiktok": list(clip.get("hashtags_tiktok") or []),
                    "inicio": str(clip.get("inicio") or "00:00:00"),
                    "fin": str(clip.get("fin") or "00:00:30"),
                    "duracion_segundos": float(dur or 0.0),
                    "puntaje_viral": clip.get("puntaje_viral") or clip.get("score") or "—",
                    "archivo_mp4": str(mp4) if mp4 else "",
                    "estado": estado,
                    "youtube_info": yt_entry,
                }
            )

    if not items and raiz_clips.exists() and filtro_job in ("TODOS", "RAIZ"):
        clips_raiz = _leer_json_seguro(raiz_clips, [])
        if isinstance(clips_raiz, list):
            for idx, clip in enumerate(clips_raiz, start=1):
                mp4 = _resolver_archivo_mp4_clip(clip, idx, "", base_salida)
                if mp4 is not None:
                    archivos_vistos.add(str(mp4.resolve()))
                yt_entry = (
                    subidas_idx.get(str(mp4)) or subidas_idx.get(mp4.name)
                    if mp4
                    else None
                )
                dur = clip.get("duracion_segundos") or round(
                    max(
                        0.0,
                        _segundos_seguros(clip.get("fin"))
                        - _segundos_seguros(clip.get("inicio")),
                    ),
                    1,
                )
                estado = (
                    "Subido YT"
                    if yt_entry
                    else ("Renderizado OK" if mp4 else "Pendiente")
                )
                items.append(
                    {
                        "job_id": "raiz",
                        "job_dir": "",
                        "source_url": "",
                        "fuente_display": "clips.json raíz",
                        "clip_index": idx,
                        "clip_data": dict(clip),
                        "id": clip.get("id", idx),
                        "titulo": str(clip.get("titulo") or f"Clip #{idx}"),
                        "gancho": str(clip.get("gancho") or ""),
                        "gancho_visual_portada": str(clip.get("gancho_visual_portada") or ""),
                        "caption_tiktok": str(clip.get("caption_tiktok") or ""),
                        "descripcion": str(clip.get("descripcion") or ""),
                        "etiquetas": list(clip.get("etiquetas") or []),
                        "hashtags_tiktok": list(clip.get("hashtags_tiktok") or []),
                        "inicio": str(clip.get("inicio") or "00:00:00"),
                        "fin": str(clip.get("fin") or "00:00:30"),
                        "duracion_segundos": float(dur or 0.0),
                        "puntaje_viral": clip.get("puntaje_viral") or "—",
                        "archivo_mp4": str(mp4) if mp4 else "",
                        "estado": estado,
                        "youtube_info": yt_entry,
                    }
                )

    if filtro_job in ("TODOS", "CLIPS_FINALES") and base_salida.exists():
        for mp4 in sorted(base_salida.glob("*.mp4"), key=lambda p: p.stat().st_mtime, reverse=True):
            res = str(mp4.resolve())
            if res in archivos_vistos:
                continue
            yt_entry = subidas_idx.get(res) or subidas_idx.get(mp4.name)
            items.append(
                {
                    "job_id": "clips_finales",
                    "job_dir": "",
                    "source_url": "",
                    "fuente_display": "clips_finales/",
                    "clip_index": 0,
                    "clip_data": {"titulo": mp4.stem},
                    "id": mp4.stem,
                    "titulo": mp4.stem,
                    "gancho": "",
                    "gancho_visual_portada": "",
                    "caption_tiktok": "",
                    "descripcion": "",
                    "etiquetas": [],
                    "hashtags_tiktok": [],
                    "inicio": "00:00:00",
                    "fin": "00:00:30",
                    "duracion_segundos": 0.0,
                    "puntaje_viral": "—",
                    "archivo_mp4": res,
                    "estado": "Subido YT" if yt_entry else "Renderizado OK",
                    "youtube_info": yt_entry,
                }
            )

    return items


def formatear_pack_youtube(clip: Dict[str, Any]) -> str:
    """Genera texto listo para copiar con título, descripción y etiquetas de YouTube Shorts."""
    titulo = str(clip.get("titulo") or "").strip()
    descripcion = str(clip.get("descripcion") or "").strip()
    etiquetas = clip.get("etiquetas") or []
    if isinstance(etiquetas, str):
        tags_list = [t.strip() for t in etiquetas.split(",") if t.strip()]
    else:
        tags_list = [str(t).strip() for t in etiquetas if str(t).strip()]
    tags_str = ", ".join(tags_list)
    partes = [f"TÍTULO:\n{titulo}"]
    if descripcion:
        partes.append(f"DESCRIPCIÓN:\n{descripcion}")
    if tags_str:
        partes.append(f"ETIQUETAS:\n{tags_str}")
    return "\n\n".join(partes).strip()


def formatear_pack_tiktok(clip: Dict[str, Any]) -> str:
    """Genera texto listo para copiar con texto de portada, caption y hashtags de TikTok."""
    portada = str(clip.get("gancho_visual_portada") or "").strip()
    caption = str(clip.get("caption_tiktok") or "").strip()
    hashtags = clip.get("hashtags_tiktok") or clip.get("etiquetas") or []
    if isinstance(hashtags, str):
        lista = [h.strip() for h in re.split(r"[\s,]+", hashtags) if h.strip()]
    else:
        lista = [str(h).strip() for h in hashtags if str(h).strip()]
    hashes = " ".join(h if h.startswith("#") else f"#{h}" for h in lista)
    partes = []
    if portada:
        partes.append(f"PORTADA TIKTOK:\n{portada}")
    if caption:
        partes.append(f"CAPTION:\n{caption}")
    if hashes:
        partes.append(f"HASHTAGS:\n{hashes}")
    return "\n\n".join(partes).strip()


def exportar_copia_clip(ruta_origen: str | Path, ruta_destino: str | Path) -> Path:
    """Exporta de forma segura una copia del clip .mp4 validando el origen dentro del proyecto."""
    origen = validar_ruta_dentro_proyecto(ruta_origen)
    if not origen.exists() or not origen.is_file():
        raise FileNotFoundError(f"No existe el video origen: {origen}")
    destino = Path(ruta_destino).expanduser().resolve(strict=False)
    if destino.name in ARCHIVOS_SECRETOS_PROHIBIDOS:
        raise PermissionError("Destino inválido.")
    destino.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(origen, destino)
    return destino


def abrir_en_sistema(ruta_o_url: str | Path) -> bool:
    """Abre un archivo, carpeta o URL http(s) con xdg-open de forma desacoplada."""
    texto = str(ruta_o_url or "").strip()
    if not texto:
        return False
    if texto.startswith(("http://", "https://")):
        objetivo = texto
    else:
        ruta = Path(texto).resolve(strict=False)
        if ruta.name in ARCHIVOS_SECRETOS_PROHIBIDOS or not ruta.exists():
            return False
        objetivo = str(ruta)
    try:
        subprocess.Popen(
            ["xdg-open", objetivo],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
        return True
    except Exception:
        return False


def subir_clip_individual(
    clip: Dict[str, Any],
    ruta_video: str | Path,
    privacidad: str = "private",
    publish_at: Optional[str] = None,
    on_log: Optional[Callable[[str], None]] = None,
) -> Dict[str, Any]:
    """Sube un único clip validado a YouTube Shorts respetando la cuota de 24h."""
    video_val = validar_ruta_dentro_proyecto(ruta_video)
    if not video_val.exists() or not video_val.is_file():
        raise FileNotFoundError(f"No se encontró el archivo renderizado: {video_val}")

    cuota = consultar_cuota_diaria()
    if cuota.get("bloqueado"):
        raise RuntimeError(
            f"Cuota diaria agotada ({cuota.get('subidas_24h')}/{cuota.get('limite')} en las últimas 24h)."
        )

    publish_at_utc: Optional[str] = None
    if publish_at and str(publish_at).strip():
        txt = str(publish_at).strip()
        if "T" in txt and txt.endswith("Z"):
            publish_at_utc = txt
        else:
            publish_at_utc = pvc.calcular_publish_at_utc(txt, indice_clip=0, intervalo_horas=0)

    etiquetas = clip.get("etiquetas") or []
    if isinstance(etiquetas, str):
        etiquetas = [e.strip() for e in etiquetas.split(",") if e.strip()]

    youtube = autenticar_youtube(interactivo=False)
    return subir_short(
        youtube=youtube,
        ruta_video=video_val,
        titulo=str(clip.get("titulo") or video_val.stem),
        descripcion=str(clip.get("descripcion") or ""),
        etiquetas=etiquetas,
        privacidad="private" if publish_at_utc else privacidad,
        clip_id=clip.get("id"),
        guardar_registro=True,
        publish_at=publish_at_utc,
        on_log=on_log,
    )


def obtener_historial_subidas(
    filtro: str = "",
    ruta_json: Optional[Path | str] = None,
) -> List[Dict[str, Any]]:
    """Devuelve el historial de subidas ordenado de más reciente a más antiguo."""
    archivo = Path(ruta_json) if ruta_json is not None else ARCHIVO_SUBIDAS
    historial = cargar_historial_subidas(ruta_json=archivo)
    q = str(filtro or "").strip().lower()
    ordenadas = list(reversed(historial))
    if not q:
        return ordenadas
    return [
        item
        for item in ordenadas
        if q in str(item.get("titulo") or "").lower()
        or q in str(item.get("youtube_id") or "").lower()
        or q in str(item.get("archivo") or "").lower()
        or q in str(item.get("privacidad") or "").lower()
    ]


def calcular_estadisticas_sistema(
    carpeta_jobs: Optional[Path | str] = None,
    carpeta_salida: Optional[Path | str] = None,
    ruta_subidas: Optional[Path | str] = None,
    archivo_clips_raiz: Optional[Path | str] = None,
) -> Dict[str, Any]:
    """Calcula métricas 100% offline leyendo jobs/*/clips.json, clips_finales/ y subidas_shorts.json."""
    base_jobs = Path(carpeta_jobs) if carpeta_jobs is not None else CARPETA_JOBS
    base_salida = Path(carpeta_salida) if carpeta_salida is not None else CARPETA_SALIDA
    archivo_subidas = Path(ruta_subidas) if ruta_subidas is not None else ARCHIVO_SUBIDAS
    raiz_clips = Path(archivo_clips_raiz) if archivo_clips_raiz is not None else ARCHIVO_CLIPS

    jobs = escanear_jobs(carpeta_jobs=base_jobs, carpeta_salida=base_salida)
    total_jobs = len(jobs)
    jobs_completados = sum(1 for j in jobs if j.get("completado"))
    jobs_incompletos = total_jobs - jobs_completados

    clips_curados = 0
    duraciones: List[float] = []
    distribucion = {"<22s": 0, "22-45s": 0, "46-75s": 0, ">75s": 0}

    fuentes_clips: List[List[Dict[str, Any]]] = []
    for j in jobs:
        lista = _leer_json_seguro(Path(j["job_dir"]) / "clips.json", [])
        if isinstance(lista, list) and lista:
            fuentes_clips.append(lista)

    if not fuentes_clips and raiz_clips.exists():
        lista_raiz = _leer_json_seguro(raiz_clips, [])
        if isinstance(lista_raiz, list) and lista_raiz:
            fuentes_clips.append(lista_raiz)

    for lista in fuentes_clips:
        clips_curados += len(lista)
        for clip in lista:
            dur = clip.get("duracion_segundos")
            if not dur:
                dur = max(
                    0.0,
                    _segundos_seguros(clip.get("fin"))
                    - _segundos_seguros(clip.get("inicio")),
                )
            try:
                dur_f = float(dur)
            except Exception:
                dur_f = 0.0
            if dur_f > 0:
                duraciones.append(dur_f)
                if dur_f < 22.0:
                    distribucion["<22s"] += 1
                elif dur_f <= 45.0:
                    distribucion["22-45s"] += 1
                elif dur_f <= 75.0:
                    distribucion["46-75s"] += 1
                else:
                    distribucion[">75s"] += 1

    clips_renderizados = (
        len(list(base_salida.glob("*.mp4"))) if base_salida.exists() else 0
    )
    historial = cargar_historial_subidas(ruta_json=archivo_subidas)
    shorts_subidos = len(historial)

    duracion_promedio_s = (
        round(sum(duraciones) / len(duraciones), 1) if duraciones else 0.0
    )
    tasa_exito_pct = (
        round((jobs_completados / total_jobs) * 100.0, 1)
        if total_jobs > 0
        else (100.0 if clips_renderizados > 0 else 0.0)
    )

    return {
        "total_jobs": total_jobs,
        "jobs_completados": jobs_completados,
        "jobs_incompletos": jobs_incompletos,
        "clips_curados": clips_curados,
        "clips_renderizados": clips_renderizados,
        "shorts_subidos": shorts_subidos,
        "duracion_promedio_s": duracion_promedio_s,
        "tasa_exito_pct": tasa_exito_pct,
        "distribucion_duracion": distribucion,
        "ultimos_jobs": jobs[:12],
    }
