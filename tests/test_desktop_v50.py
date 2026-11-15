#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Pruebas dedicadas para Kicksazos Studio v5.0 (PySide6 Desktop + Gemini 3.5 + Groq + Seguridad)."""

import inspect
import io
import json
import os
import subprocess
import sys
import tempfile
import unittest
import urllib.error
from pathlib import Path
from unittest.mock import MagicMock, patch

ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

import app_interfaz  # noqa: E402
import pipeline_viral_clips as pvc  # noqa: E402
from ui_desktop import services as ui_services  # noqa: E402
from ui_desktop.workers import PipelineWorker, SingleClipWorker  # noqa: E402


class _FakeHTTPResp:
    def __init__(self, payload: dict) -> None:
        self._data = json.dumps(payload).encode("utf-8")

    def read(self) -> bytes:
        return self._data

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False


class TestV50Gemini35YGroqBackend(unittest.TestCase):
    def test_gemini_35_es_modelo_predeterminado_en_backend_y_cli(self):
        self.assertEqual(pvc.MODELOS_CANDIDATOS[0], "gemini-3.5-flash-lite")
        self.assertEqual(pvc.MODELO_GEMINI_PREDETERMINADO, "gemini-3.5-flash-lite")
        self.assertEqual(
            inspect.signature(pvc.analizar_con_gemini).parameters["modelo_preferido"].default,
            "gemini-3.5-flash-lite",
        )
        self.assertEqual(
            inspect.signature(pvc.ejecutar_pipeline_completo).parameters["modelo_preferido"].default,
            "gemini-3.5-flash-lite",
        )
        self.assertEqual(pvc._normalizar_modelo_gemini(None), "gemini-3.5-flash-lite")
        self.assertEqual(pvc._normalizar_modelo_gemini("Auto (Recomendado)"), "gemini-3.5-flash-lite")
        self.assertEqual(pvc._normalizar_modelo_gemini("gemini-3.8-flash"), "gemini-3.8-flash")

        # Verificar CLI defaults sin pasar --modelo
        capturado = {}

        def _fake_pipeline(**kwargs):
            capturado.update(kwargs)
            yield {"fase": "completado", "progreso": 1.0, "mensaje": "OK", "job_dir": "jobs/demo"}

        with patch.object(pvc, "ejecutar_pipeline_completo", side_effect=_fake_pipeline), patch.object(
            pvc, "terminar_procesos_activos"
        ), patch.object(sys, "argv", ["pipeline_viral_clips.py", "https://kick.com/eldomi/videos/1", "--solo-analisis"]):
            pvc.main()

        self.assertEqual(capturado["motor_ia"], "gemini")
        self.assertEqual(capturado["modelo_preferido"], "gemini-3.5-flash-lite")

    def test_motor_groq_exito_y_error_429(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_dir = Path(tmp)
            audio = tmp_dir / "temp_audio.mp3"
            audio.write_bytes(b"\xff\xfb" * 8000)

            transcripcion_mock = {
                "duracion_total": 120.0,
                "segmentos": [
                    {
                        "start": 10.0,
                        "end": 45.0,
                        "text": "Eso fue una locura en el directo",
                    }
                ],
                "palabras": [
                    {"start": 10.0, "end": 11.0, "word": "Eso"},
                    {"start": 11.0, "end": 12.0, "word": "locura"},
                ],
                "indices_picos": [0],
            }
            groq_clip_json = {
                "clips": [
                    {
                        "id": 1,
                        "titulo": "Locura en vivo!",
                        "inicio": "00:00:10",
                        "fin": "00:00:40",
                        "gancho": "Locura total",
                        "razon_viral": "Pico emocional",
                        "descripcion": "Momento increíble",
                        "etiquetas": ["kick", "viral"],
                        "caption_tiktok": "Mira esto!",
                        "hashtags_tiktok": ["#kick", "#viral"],
                        "gancho_visual_portada": "ESTO PASO EN VIVO",
                        "subtitulos": [],
                    }
                ]
            }
            fake_resp = _FakeHTTPResp(
                {"choices": [{"message": {"content": json.dumps(groq_clip_json)}}]}
            )

            with patch.dict(os.environ, {"GROQ_API_KEY": "fake_key_test"}, clear=False), patch.object(
                pvc, "_transcribir_audio_whisper_local", return_value=transcripcion_mock
            ), patch.object(urllib.request, "urlopen", return_value=fake_resp):
                clips = pvc.analizar_con_groq(
                    str(audio), duracion_total=120.0, job_dir=tmp_dir
                )

            self.assertEqual(len(clips), 1)
            self.assertEqual(clips[0]["modelo_ia"], pvc.MODELOS_GROQ[0])
            self.assertEqual(clips[0]["titulo"], "Locura en vivo!")
            self.assertGreaterEqual(len(clips[0]["subtitulos"]), 1)

            err_429 = urllib.error.HTTPError(
                url="https://api.groq.com/openai/v1/chat/completions",
                code=429,
                msg="Too Many Requests",
                hdrs=None,
                fp=io.BytesIO(b"rate limit exceeded"),
            )
            with patch.dict(os.environ, {"GROQ_API_KEY": "fake_key_test"}, clear=False), patch.object(
                pvc, "_transcribir_audio_whisper_local", return_value=transcripcion_mock
            ), patch.object(urllib.request, "urlopen", side_effect=err_429):
                with self.assertRaises(pvc.GeminiQuotaExhaustedError):
                    pvc.analizar_con_groq(str(audio), duracion_total=120.0, job_dir=tmp_dir)


class TestV50ServiciosYSeguridadDesktop(unittest.TestCase):
    def test_validacion_rutas_y_zero_secrets(self):
        for secreto in (".env", "client_secret.json", "token.json", "token_cuenta_anterior.json"):
            with self.assertRaises(PermissionError):
                ui_services.validar_ruta_dentro_proyecto(ui_services.PROYECTO_ROOT / secreto)

        with self.assertRaises(ValueError):
            ui_services.validar_ruta_dentro_proyecto("/etc/passwd")

        with tempfile.TemporaryDirectory() as tmp:
            tmp_jobs = Path(tmp) / "jobs"
            tmp_jobs.mkdir()
            fuera = Path(tmp) / "otro_dir"
            fuera.mkdir()
            with self.assertRaises(ValueError):
                ui_services.eliminar_job_seguro(fuera, carpeta_jobs=tmp_jobs)
            with self.assertRaises(ValueError):
                ui_services.eliminar_job_seguro(tmp_jobs, carpeta_jobs=tmp_jobs)

            job_ok = tmp_jobs / "20261114_010000_kick_com_test_abc123"
            job_ok.mkdir()
            (job_ok / "temp_audio.mp3").write_bytes(b"a" * 20000)
            self.assertTrue(ui_services.eliminar_job_seguro(job_ok, carpeta_jobs=tmp_jobs))
            self.assertFalse(job_ok.exists())

    def test_escanear_jobs_edicion_atomica_packs_y_export(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_root = Path(tmp)
            carpeta_jobs = tmp_root / "jobs"
            carpeta_salida = tmp_root / "clips_finales"
            carpeta_jobs.mkdir()
            carpeta_salida.mkdir()
            ruta_clips_raiz = tmp_root / "clips.json"
            ruta_subidas = tmp_root / "subidas_shorts.json"
            ruta_subidas.write_text("[]", encoding="utf-8")

            job_id = "20261114_020000_kick_com_eldomi_videos_112233"
            job_dir = carpeta_jobs / job_id
            job_dir.mkdir()
            (job_dir / "temp_audio.mp3").write_bytes(b"a" * 25000)
            (job_dir / "whisper_transcript.json").write_text(json.dumps({"segments": [1]}), encoding="utf-8")
            (job_dir / "job_meta.json").write_text(
                json.dumps({"job_id": job_id, "source_url": "https://kick.com/eldomi/videos/112233"}),
                encoding="utf-8",
            )
            mp4_clip = carpeta_salida / f"{job_id}_clip_1_demo.mp4"
            mp4_clip.write_bytes(b"mp4_bytes")
            clips_data = [
                {
                    "id": 1,
                    "titulo": "Título inicial",
                    "inicio": "00:00:10",
                    "fin": "00:00:45",
                    "descripcion": "Desc test",
                    "etiquetas": ["kick", "shorts"],
                    "caption_tiktok": "Caption test",
                    "hashtags_tiktok": ["#kick"],
                    "gancho_visual_portada": "BRUTAL MOMENTO",
                    "archivo_local": str(mp4_clip),
                }
            ]
            (job_dir / "clips.json").write_text(json.dumps(clips_data), encoding="utf-8")

            with patch.object(ui_services, "PROYECTO_ROOT", tmp_root), patch.object(
                ui_services, "CARPETA_JOBS", carpeta_jobs
            ), patch.object(ui_services, "CARPETA_SALIDA", carpeta_salida), patch.object(
                ui_services, "ARCHIVO_CLIPS", ruta_clips_raiz
            ), patch.object(ui_services, "ARCHIVO_SUBIDAS", ruta_subidas):
                jobs = ui_services.escanear_jobs()
                self.assertEqual(len(jobs), 1)
                self.assertTrue(jobs[0]["has_audio"])
                self.assertTrue(jobs[0]["has_whisper"])
                self.assertTrue(jobs[0]["has_clips"])
                self.assertEqual(jobs[0]["clips_renderizados"], 1)
                self.assertEqual(jobs[0]["source_url"], "https://kick.com/eldomi/videos/112233")

                editado = dict(clips_data[0])
                editado["titulo"] = "Título Editado v5"
                editado["fin"] = "00:00:55"
                ui_services.actualizar_y_guardar_clip(editado, job_dir=job_dir)
                cargado = ui_services.cargar_clips_json(job_dir / "clips.json")
                self.assertEqual(cargado[0]["titulo"], "Título Editado v5")
                self.assertEqual(cargado[0]["duracion_segundos"], 45.0)

                yt_pack = ui_services.formatear_pack_youtube(editado)
                tk_pack = ui_services.formatear_pack_tiktok(editado)
                self.assertIn("Título Editado v5", yt_pack)
                self.assertIn("BRUTAL MOMENTO", tk_pack)

                export_dst = tmp_root / "exports" / "copia.mp4"
                sal = ui_services.exportar_copia_clip(mp4_clip, export_dst)
                self.assertTrue(sal.exists())
                self.assertEqual(sal.read_bytes(), b"mp4_bytes")

    def test_single_clip_worker_rerender_y_upload(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_root = Path(tmp)
            carpeta_jobs = tmp_root / "jobs"
            carpeta_salida = tmp_root / "clips_finales"
            carpeta_jobs.mkdir()
            carpeta_salida.mkdir()
            ruta_clips_raiz = tmp_root / "clips.json"
            ruta_subidas = tmp_root / "subidas_shorts.json"
            ruta_subidas.write_text("[]", encoding="utf-8")

            job_id = "20261114_030000_kick_com_clip_test"
            job_dir = carpeta_jobs / job_id
            job_dir.mkdir()
            (job_dir / "job_meta.json").write_text(
                json.dumps({"job_id": job_id, "source_url": "https://kick.com/eldomi/videos/999"}),
                encoding="utf-8",
            )
            clip_dict = {
                "id": 1,
                "titulo": "Rerender Test",
                "inicio": "00:01:00",
                "fin": "00:01:30",
                "descripcion": "Desc",
                "etiquetas": ["kick"],
                "subtitulos": [{"inicio_rel": 1.0, "fin_rel": 3.0, "texto": "HOLA"}],
            }
            (job_dir / "clips.json").write_text(json.dumps([clip_dict]), encoding="utf-8")
            nuevo_mp4 = carpeta_salida / f"{job_id}_clip_1_nuevo.mp4"
            nuevo_mp4.write_bytes(b"nuevo_render")

            with patch.object(ui_services, "PROYECTO_ROOT", tmp_root), patch.object(
                ui_services, "CARPETA_JOBS", carpeta_jobs
            ), patch.object(ui_services, "CARPETA_SALIDA", carpeta_salida), patch.object(
                ui_services, "ARCHIVO_CLIPS", ruta_clips_raiz
            ), patch.object(ui_services, "ARCHIVO_SUBIDAS", ruta_subidas), patch.object(
                pvc, "generar_archivo_ass", return_value=str(job_dir / "sub_clip_1.ass")
            ) as mock_ass, patch.object(
                pvc, "procesar_clip_ffmpeg", return_value=str(nuevo_mp4)
            ) as mock_ffmpeg:
                worker_rr = SingleClipWorker(
                    modo="rerender",
                    clip_data=clip_dict,
                    job_id=job_id,
                    job_dir=str(job_dir),
                )
                eventos_rr = []
                worker_rr.operacion_finalizada.connect(lambda ok, msg, data: eventos_rr.append((ok, msg, data)))
                worker_rr.run()

                mock_ass.assert_called_once()
                mock_ffmpeg.assert_called_once()
                self.assertEqual(len(eventos_rr), 1)
                self.assertTrue(eventos_rr[0][0])
                self.assertEqual(eventos_rr[0][2]["archivo_mp4"], str(nuevo_mp4))

                with patch.object(ui_services, "autenticar_youtube", return_value="yt_client"), patch.object(
                    ui_services,
                    "subir_short",
                    return_value={"youtube_id": "abc123", "url": "https://youtube.com/shorts/abc123"},
                ) as mock_subir:
                    worker_up = SingleClipWorker(
                        modo="upload",
                        clip_data=clip_dict,
                        ruta_video_actual=str(nuevo_mp4),
                        privacidad="private",
                    )
                    eventos_up = []
                    worker_up.operacion_finalizada.connect(
                        lambda ok, msg, data: eventos_up.append((ok, msg, data))
                    )
                    worker_up.run()

                mock_subir.assert_called_once()
                self.assertTrue(eventos_up[0][0])
                self.assertEqual(eventos_up[0][2]["youtube_info"]["youtube_id"], "abc123")


class TestV50PySide6VentanaYFlujo(unittest.TestCase):
    def setUp(self) -> None:
        self.app = app_interfaz.crear_aplicacion([])
        self.ventana = app_interfaz.KicksazosMainWindow(auto_probe=False)

    def tearDown(self) -> None:
        self.ventana.close()
        self.app.processEvents()

    def test_topbar_navegacion_5_vistas_y_reanudar_job_desde_vista_3(self):
        self.assertEqual(self.ventana.windowTitle(), "Kicksazos Studio v5.0")
        self.assertEqual(self.ventana.stack_vistas.count(), 5)
        self.assertEqual(
            self.ventana.vista_command_center.combo_modelo.currentData(),
            "gemini-3.5-flash-lite",
        )

        # Simular actualización de estado superior (cuota, Ollama, VAAPI)
        self.ventana._on_estado_sistema_detectado(
            {
                "cuota": {"subidas_24h": 2, "limite": 6, "restantes": 4, "bloqueado": False},
                "ollama": {"online": True, "url": "http://127.0.0.1:11434", "modelos": ["qwen3:14b"]},
                "encoder": "h264_vaapi",
            }
        )
        self.assertIn("2/6", self.ventana.pill_cuota.text())
        self.assertIn("OK", self.ventana.pill_ollama.text())
        self.assertIn("AMD VAAPI", self.ventana.pill_encoder.text())

        # Cambiar por las 5 vistas
        for idx in range(5):
            self.ventana.sidebar_nav.setCurrentRow(idx)
            self.app.processEvents()
            self.assertEqual(self.ventana.stack_vistas.currentIndex(), idx)

        # Emitir reanudación desde Vista 3 -> cambia a Vista 1 y precarga datos
        job_demo = {
            "job_id": "20261114_demo_kick",
            "job_dir": str(ui_services.CARPETA_JOBS / "20261114_demo_kick"),
            "source_url": "https://kick.com/eldomi/videos/777",
            "clips_renderizados": 2,
            "total_clips": 5,
        }
        self.ventana.vista_jobs_manager.reanudar_job_solicitado.emit(job_demo)
        self.app.processEvents()
        self.assertEqual(self.ventana.stack_vistas.currentIndex(), 0)
        self.assertEqual(
            self.ventana.vista_command_center.input_url.text(),
            "https://kick.com/eldomi/videos/777",
        )
        self.assertEqual(
            self.ventana.vista_command_center._job_dir_reanudacion,
            job_demo["job_dir"],
        )


if __name__ == "__main__":
    unittest.main()
