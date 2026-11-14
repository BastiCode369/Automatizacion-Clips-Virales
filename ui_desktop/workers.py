"""Workers QThread desacoplados para ejecución, re-render y sondeo sin congelar Qt."""

from __future__ import annotations

import os
import threading
from pathlib import Path
from typing import Any, Dict, Optional

from PySide6.QtCore import QThread, Signal

import pipeline_viral_clips as pvc
from ui_desktop import services


class PipelineWorker(QThread):
    """Ejecuta `ejecutar_pipeline_completo` en segundo plano emitiendo telemetría y logs."""

    telemetria_actualizada = Signal(dict)
    log_recibido = Signal(str)
    pipeline_finalizado = Signal(bool, str)

    def __init__(
        self,
        url: str,
        motor_ia: str = "gemini",
        modelo_preferido: Optional[str] = None,
        modelo_local: Optional[str] = None,
        solo_analisis: bool = False,
        subir_youtube: bool = False,
        respaldo_local_auto: bool = True,
        publish_at_inicio: Optional[str] = None,
        intervalo_horas: int = 0,
        job_dir: Optional[str] = None,
        api_key_override: Optional[str] = None,
        groq_api_key_override: Optional[str] = None,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self.url = (url or "").strip()
        self.motor_ia = (motor_ia or "gemini").strip().lower()
        self.modelo_preferido = modelo_preferido or pvc.MODELOS_CANDIDATOS[0]
        self.modelo_local = modelo_local
        self.solo_analisis = bool(solo_analisis)
        self.subir_youtube = bool(subir_youtube)
        self.respaldo_local_auto = bool(respaldo_local_auto)
        self.publish_at_inicio = publish_at_inicio
        self.intervalo_horas = int(intervalo_horas or 0)
        self.job_dir = job_dir
        self.api_key_override = (api_key_override or "").strip()
        self.groq_api_key_override = (groq_api_key_override or "").strip()
        self._cancel_event = threading.Event()

    def solicitar_detencion(self) -> int:
        """Marca cancelación y termina subprocesos activos (ffmpeg/yt-dlp) al instante."""
        self._cancel_event.set()
        self.log_recibido.emit("🛑 Solicitando detención inmediata y limpieza de subprocesos...")
        try:
            return int(pvc.terminar_procesos_activos())
        except Exception:
            return 0

    def run(self) -> None:
        gemini_prev = os.environ.get("GEMINI_API_KEY")
        groq_prev = os.environ.get("GROQ_API_KEY")
        if self.api_key_override:
            os.environ["GEMINI_API_KEY"] = self.api_key_override
        if self.groq_api_key_override:
            os.environ["GROQ_API_KEY"] = self.groq_api_key_override

        ultimo_estado: Dict[str, Any] = {}
        try:
            for estado in pvc.ejecutar_pipeline_completo(
                url=self.url,
                modelo_preferido=self.modelo_preferido,
                solo_analisis=self.solo_analisis,
                subir_youtube=self.subir_youtube,
                publish_at_inicio=self.publish_at_inicio,
                intervalo_horas=self.intervalo_horas,
                on_log=lambda msg: self.log_recibido.emit(str(msg)),
                on_telemetria=lambda est: self.telemetria_actualizada.emit(
                    services.normalizar_estado_telemetria(est)
                ),
                motor_ia=self.motor_ia,
                modelo_local=self.modelo_local,
                respaldo_local_auto=self.respaldo_local_auto,
                job_dir=self.job_dir,
            ):
                ultimo_estado = services.normalizar_estado_telemetria(estado)
                self.telemetria_actualizada.emit(ultimo_estado)
                if self._cancel_event.is_set() or self.isInterruptionRequested():
                    try:
                        pvc.terminar_procesos_activos()
                    except Exception:
                        pass
                    self.pipeline_finalizado.emit(
                        False, "Pipeline abortado por el usuario."
                    )
                    return

            if self._cancel_event.is_set():
                self.pipeline_finalizado.emit(False, "Pipeline abortado por el usuario.")
                return

            error = ultimo_estado.get("error")
            if error:
                self.pipeline_finalizado.emit(False, str(error))
            else:
                self.pipeline_finalizado.emit(
                    True,
                    str(ultimo_estado.get("mensaje") or "Pipeline finalizado con éxito."),
                )
        except Exception as exc:
            if self._cancel_event.is_set():
                self.pipeline_finalizado.emit(False, "Pipeline abortado por el usuario.")
            else:
                self.log_recibido.emit(f"[ERROR] {exc}")
                self.pipeline_finalizado.emit(False, str(exc))
        finally:
            if self.api_key_override:
                if gemini_prev is None:
                    os.environ.pop("GEMINI_API_KEY", None)
                else:
                    os.environ["GEMINI_API_KEY"] = gemini_prev
            if self.groq_api_key_override:
                if groq_prev is None:
                    os.environ.pop("GROQ_API_KEY", None)
                else:
                    os.environ["GROQ_API_KEY"] = groq_prev


class SingleClipWorker(QThread):
    """Worker para re-renderizar un clip individual o subirlo a YouTube Shorts."""

    progreso_actualizado = Signal(dict)
    log_recibido = Signal(str)
    operacion_finalizada = Signal(bool, str, dict)

    def __init__(
        self,
        modo: str,
        clip_data: Dict[str, Any],
        job_id: str = "",
        job_dir: str = "",
        source_url_override: str = "",
        ruta_video_actual: str = "",
        publish_at: Optional[str] = None,
        privacidad: str = "private",
        parent=None,
    ) -> None:
        super().__init__(parent)
        self.modo = modo
        self.clip_data = dict(clip_data)
        self.job_id = str(job_id or "")
        self.job_dir = str(job_dir or "")
        self.source_url_override = str(source_url_override or "").strip()
        self.ruta_video_actual = str(ruta_video_actual or "").strip()
        self.publish_at = publish_at
        self.privacidad = privacidad

    def _resolver_fuente_rerender(self) -> str:
        if self.source_url_override:
            return self.source_url_override
        if self.job_dir:
            job_path = services.validar_ruta_dentro_proyecto(
                self.job_dir, directorio_base=services.CARPETA_JOBS
            )
            local_source = job_path / "temp_source.mp4"
            if local_source.exists() and local_source.is_file():
                return str(local_source)
            meta = services._leer_json_seguro(job_path / "job_meta.json", {})
            if isinstance(meta, dict) and str(meta.get("source_url") or "").strip():
                return str(meta["source_url"]).strip()
        raise RuntimeError(
            "No se encontró la URL/archivo original en job_meta.json. "
            "Indica la fuente del stream o archivo local en el campo Origen para re-renderizar."
        )

    def _ejecutar_rerender(self) -> Dict[str, Any]:
        fuente = self._resolver_fuente_rerender()
        clip_id = self.clip_data.get("id") or 1
        inicio = str(self.clip_data.get("inicio") or "00:00:00")
        fin = str(self.clip_data.get("fin") or "00:00:30")
        dur_s = max(
            1.0,
            pvc.hhmmss_a_segundos(fin) - pvc.hhmmss_a_segundos(inicio),
        )
        subtitulos = self.clip_data.get("subtitulos") or []

        job_dir_path: Optional[Path] = None
        if self.job_dir:
            job_dir_path = services.validar_ruta_dentro_proyecto(
                self.job_dir, directorio_base=services.CARPETA_JOBS
            )
            if subtitulos:
                subs_norm = pvc._normalizar_subtitulos(subtitulos, duracion_clip=dur_s)
                if subs_norm:
                    ruta_ass = job_dir_path / f"sub_clip_{clip_id}.ass"
                    pvc.generar_archivo_ass(subs_norm, str(ruta_ass))
                    self.log_recibido.emit(f"✓ Subtítulos .ass regenerados: {ruta_ass.name}")

        self.log_recibido.emit(
            f"🎬 Re-renderizando Clip #{clip_id} ({inicio} -> {fin})..."
        )
        ruta_mp4 = pvc.procesar_clip_ffmpeg(
            url_o_archivo=fuente,
            inicio=inicio,
            fin=fin,
            id_clip=clip_id,
            job_id=self.job_id or None,
            subtitulos=subtitulos or None,
            job_dir=str(job_dir_path) if job_dir_path else None,
            on_telemetria=lambda est: self.progreso_actualizado.emit(
                services.normalizar_estado_telemetria(est)
            ),
            clip_indice=1,
            total_clips=1,
            on_log=lambda msg: self.log_recibido.emit(str(msg)),
            alinear_subtitulos=False,
        )

        self.clip_data["archivo_local"] = str(ruta_mp4)
        self.clip_data["render_status"] = "ok"
        self.clip_data["duracion_segundos"] = round(dur_s, 2)
        services.actualizar_y_guardar_clip(
            self.clip_data,
            job_dir=str(job_dir_path) if job_dir_path else None,
        )
        return {"archivo_mp4": str(ruta_mp4), "clip": self.clip_data}

    def run(self) -> None:
        try:
            if self.modo == "rerender":
                res = self._ejecutar_rerender()
                self.operacion_finalizada.emit(
                    True,
                    f"Clip re-renderizado en {Path(res['archivo_mp4']).name}",
                    res,
                )
                return

            if self.modo == "upload":
                ruta = self.ruta_video_actual or str(
                    self.clip_data.get("archivo_local") or ""
                )
                if not ruta:
                    raise FileNotFoundError(
                        "Este clip aún no tiene un archivo .mp4 renderizado."
                    )
                self.log_recibido.emit("📤 Iniciando subida individual a YouTube Shorts...")
                registro = services.subir_clip_individual(
                    clip=self.clip_data,
                    ruta_video=ruta,
                    privacidad=self.privacidad,
                    publish_at=self.publish_at,
                    on_log=lambda msg: self.log_recibido.emit(str(msg)),
                )
                self.operacion_finalizada.emit(
                    True,
                    f"Short subido: {registro.get('url') or registro.get('youtube_id')}",
                    {"youtube_info": registro},
                )
                return

            raise ValueError(f"Modo desconocido en SingleClipWorker: {self.modo}")
        except Exception as exc:
            self.log_recibido.emit(f"[ERROR] {exc}")
            self.operacion_finalizada.emit(False, str(exc), {})


class SystemProbeWorker(QThread):
    """Sondea cuota YouTube, Ollama local y encoder VAAPI/CPU sin bloquear la UI."""

    estado_detectado = Signal(dict)

    def run(self) -> None:
        try:
            estado = services.obtener_estado_sistema()
            self.estado_detectado.emit(estado)
        except Exception:
            pass
