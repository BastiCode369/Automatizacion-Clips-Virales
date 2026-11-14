#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import json
import sys
import tempfile
import threading
import unittest
import urllib.error
from pathlib import Path
from unittest import mock

BASE_DIR = Path(__file__).resolve().parent.parent
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

import app_interfaz
import pipeline_viral_clips as pvc
import subir_shorts


class TestEstabilidadYConcurrenciaV43(unittest.TestCase):
    def test_escritura_atomica_clips_y_subidas_concurrentes(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_dir = Path(tmp)
            ruta_subidas = tmp_dir / "subidas_shorts.json"
            job_dir = tmp_dir / "job_conc"
            job_dir.mkdir(parents=True, exist_ok=True)
            ruta_raiz = tmp_dir / "clips_raiz.json"

            errores = []

            def _worker_subida(idx: int) -> None:
                try:
                    subir_shorts.registrar_subida(
                        {
                            "clip_id": idx,
                            "youtube_id": f"yt_{idx}",
                            "fecha_subida": "2026-11-13T12:00:00",
                        },
                        ruta_json=ruta_subidas,
                    )
                except BaseException as exc:
                    errores.append(exc)

            hilos = [threading.Thread(target=_worker_subida, args=(i,)) for i in range(12)]
            for h in hilos:
                h.start()
            for h in hilos:
                h.join()

            self.assertEqual(errores, [])
            datos = subir_shorts.cargar_historial_subidas(ruta_subidas)
            self.assertEqual(len(datos), 12)

            with mock.patch.object(pvc, "BASE_DIR", tmp_dir):
                def _worker_clips(idx: int) -> None:
                    try:
                        pvc._guardar_y_sincronizar_clips(
                            [{"id": idx, "titulo": f"Clip {idx}"}],
                            job_dir=job_dir,
                        )
                    except BaseException as exc:
                        errores.append(exc)

                hilos_c = [threading.Thread(target=_worker_clips, args=(i,)) for i in range(10)]
                for h in hilos_c:
                    h.start()
                for h in hilos_c:
                    h.join()

            self.assertEqual(errores, [])
            job_clips = json.loads((job_dir / "clips.json").read_text(encoding="utf-8"))
            raiz_clips = json.loads((tmp_dir / "clips.json").read_text(encoding="utf-8"))
            self.assertEqual(len(job_clips), 1)
            self.assertEqual(len(raiz_clips), 1)
            self.assertFalse(ruta_raiz.exists())

    def test_reparacion_json_truncado_y_think_sin_cerrar(self):
        raw_truncado = (
            "<think>razonamiento interno sin cerrar\n"
            "```json\n"
            '[{"id": 1, "titulo": "Clip Recuperado", "inicio": "00:00:05", "fin": "00:00:30", '
            '"gancho": "Qué pasa", "razon_viral": "Pico", "descripcion": "Desc #Shorts", '
            '"etiquetas": ["Shorts"], "caption_tiktok": "Cap", "hashtags_tiktok": ["#Kicksazos"], '
            '"gancho_visual_portada": "ESTO PASO EN VIVO", '
            '"subtitulos": [{"inicio_rel": 0.0, "fin_rel": 1.2, "texto": "Qué pasa"}]}, '
            '{"id": 2, "titulo": "Clip Truncado", "inicio": "00:01:00'
        )
        clips = pvc._limpiar_y_parsear_json(raw_truncado, duracion_total=120.0)
        self.assertEqual(len(clips), 1)
        self.assertEqual(clips[0]["titulo"], "Clip Recuperado")
        self.assertEqual(clips[0]["inicio"], "00:00:05")
        self.assertEqual(clips[0]["fin"], "00:00:30")

    def test_ollama_circuit_breaker_abre_tras_fallos_consecutivos(self):
        cb = pvc.OllamaCircuitBreaker(failure_threshold=2, cooldown_seconds=30.0)
        self.assertEqual(cb.estado(), "CLOSED")
        self.assertTrue(cb.permitir_peticion())

        self.assertEqual(cb.registrar_fallo(), "CLOSED")
        self.assertTrue(cb.permitir_peticion())

        self.assertEqual(cb.registrar_fallo(), "OPEN")
        self.assertEqual(cb.estado(), "OPEN")
        self.assertFalse(cb.permitir_peticion())

        cb.registrar_exito()
        self.assertEqual(cb.estado(), "CLOSED")
        self.assertTrue(cb.permitir_peticion())

    def test_analizar_con_ollama_dispara_circuit_breaker_en_caida_demonio(self):
        pvc.OLLAMA_CIRCUIT_BREAKER.reiniciar()
        try:
            with tempfile.TemporaryDirectory() as tmp:
                audio = Path(tmp) / "temp_audio.mp3"
                audio.write_bytes(b"ID3" + b"\x00" * 12000)
                transcripcion_fake = {
                    "duracion_total": 60.0,
                    "idioma": "es",
                    "segmentos": [{"start": 0.0, "end": 10.0, "text": "Hola parce"}],
                    "palabras": [{"start": 0.0, "end": 0.5, "word": "Hola"}],
                    "indices_picos": [0],
                }
                breaker_test = pvc.OllamaCircuitBreaker(
                    failure_threshold=2, cooldown_seconds=30.0
                )
                with (
                    mock.patch.object(pvc, "OLLAMA_CIRCUIT_BREAKER", breaker_test),
                    mock.patch.object(pvc, "_asegurar_modelo_ollama"),
                    mock.patch.object(
                        pvc, "_transcribir_audio_whisper_local", return_value=transcripcion_fake
                    ),
                    mock.patch.object(
                        pvc,
                        "_llamar_ollama_chat",
                        side_effect=urllib.error.URLError("Connection refused"),
                    ),
                    mock.patch.object(pvc, "_esperar_con_jitter"),
                    mock.patch.object(pvc, "_descargar_modelo_ollama_ram"),
                ):
                    with self.assertRaises(RuntimeError) as ctx:
                        pvc.analizar_con_ollama(
                            str(audio),
                            modelo_local="qwen3:14b",
                            duracion_total=60.0,
                            job_dir=tmp,
                        )
                    self.assertIn("Circuit-breaker", str(ctx.exception))
        finally:
            pvc.OLLAMA_CIRCUIT_BREAKER.reiniciar()

    def test_terminar_procesos_activos_limpia_subprocesos_colgados(self):
        fake_proc = mock.MagicMock()
        fake_proc.pid = -1
        fake_proc.poll.return_value = None
        fake_proc.stdout = mock.MagicMock()
        fake_proc.stderr = mock.MagicMock()

        pvc._registrar_proceso_activo(fake_proc)
        cantidad = pvc.terminar_procesos_activos()

        self.assertGreaterEqual(cantidad, 1)
        fake_proc.kill.assert_called_once()
        fake_proc.stdout.close.assert_called_once()
        fake_proc.stderr.close.assert_called_once()

    def test_cascada_gemini_no_espera_en_ultimo_intento_y_cierra_cliente(self):
        fake_client = mock.MagicMock()
        fake_client.models.generate_content_stream.side_effect = ValueError("stream vacio")
        with mock.patch.object(pvc, "_esperar_con_jitter") as mock_wait:
            with self.assertRaises(RuntimeError):
                pvc._ejecutar_cascada_modelos_gemini(
                    client=fake_client,
                    archivo_subido=mock.MagicMock(),
                    prompt="test",
                    response_schema=list[pvc.ClipViral],
                    temperature=0.2,
                    parsear_fn=lambda x: [],
                    modelo_preferido="gemini-3.8-flash",
                )
            # 3 modelos * (4 intentos - 1 último intento sin espera) = 9 esperas, no 12
            self.assertEqual(mock_wait.call_count, 9)

        pvc._cerrar_cliente_genai_seguro(fake_client)
        fake_client.close.assert_called_once()

    def test_reanudacion_job_dir_reutiliza_audio_clips_y_omite_render_completo(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_dir = Path(tmp)
            job_dir = tmp_dir / "20261113_220000_kick_test"
            job_dir.mkdir(parents=True, exist_ok=True)
            audio_cache = job_dir / "temp_audio.mp3"
            audio_cache.write_bytes(b"ID3" + b"\x00" * 20_000)

            clip_renderizado = tmp_dir / "clip_1.mp4"
            clip_renderizado.write_bytes(b"\x00\x00\x00\x18ftypmp42")

            clips_guardados = [
                {
                    "id": 1,
                    "titulo": "Clip En Cache",
                    "inicio": "00:00:00",
                    "fin": "00:00:15",
                    "gancho": "Hola",
                    "razon_viral": "Pico",
                    "descripcion": "Desc #Shorts",
                    "etiquetas": ["Shorts"],
                    "caption_tiktok": "Cap",
                    "hashtags_tiktok": ["#Kicksazos"],
                    "gancho_visual_portada": "ESTO PASO EN VIVO",
                    "subtitulos": [],
                    "render_status": "OK",
                    "archivo_local": str(clip_renderizado),
                    "youtube_url": "https://youtube.com/shorts/abc123",
                    "youtube_id": "abc123",
                }
            ]
            (job_dir / "clips.json").write_text(
                json.dumps(clips_guardados), encoding="utf-8"
            )

            with (
                mock.patch.object(pvc, "BASE_DIR", tmp_dir),
                mock.patch.object(pvc, "CARPETA_JOBS", tmp_dir),
                mock.patch.object(pvc, "extraer_audio") as mock_extraer,
                mock.patch.object(pvc, "analizar_con_gemini") as mock_gem,
                mock.patch.object(pvc, "analizar_con_ollama") as mock_ol,
                mock.patch.object(pvc, "procesar_clip_ffmpeg") as mock_ffmpeg,
                mock.patch.object(pvc, "autenticar_youtube", return_value=mock.MagicMock()),
                mock.patch.object(pvc, "subir_short") as mock_yt,
                mock.patch.object(pvc, "obtener_duracion_media", return_value=30.0),
            ):
                estados = list(
                    pvc.ejecutar_pipeline_completo(
                        url="https://kick.com/eldomi/videos/test",
                        motor_ia="local",
                        subir_youtube=True,
                        job_dir=job_dir,
                    )
                )

            mock_extraer.assert_not_called()
            mock_gem.assert_not_called()
            mock_ol.assert_not_called()
            mock_ffmpeg.assert_not_called()
            mock_yt.assert_not_called()
            self.assertEqual(estados[-1]["fase"], "completado")

    def test_cerrar_interfaz_seguro_gradio_sin_error(self):
        fake_demo = mock.MagicMock()
        app_interfaz.cerrar_interfaz_seguro(fake_demo)
        fake_demo.close.assert_called_once()


if __name__ == "__main__":
    unittest.main()
