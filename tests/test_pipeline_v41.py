import asyncio
import gc
import io
import json
import os
import subprocess
import sys
import tempfile
import unittest
import urllib.error
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

BASE_DIR = Path(__file__).resolve().parent.parent
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

import app_interfaz  # noqa: E402
import pipeline_viral_clips as pvc  # noqa: E402
from ui_desktop import services as ui_services  # noqa: E402


class _FakeHTTPResponse:
    """Respuesta HTTP mínima compatible con context manager urlopen (JSON o NDJSON)."""

    def __init__(self, body_bytes: bytes) -> None:
        self._bytes = body_bytes
        self._lines = body_bytes.splitlines(keepends=True)

    def read(self) -> bytes:
        return self._bytes

    def __iter__(self):
        return iter(self._lines)

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False


class TestFase1SubtitulosOpticosV41(unittest.TestCase):
    def test_generar_archivo_ass_wrap_y_safe_zone_v41(self):
        with tempfile.TemporaryDirectory() as tmp:
            ruta_ass = Path(tmp) / "optico_v41.ass"
            subs = [
                pvc.SegmentoSubtitulo(
                    inicio_rel=0.0,
                    fin_rel=1.8,
                    texto="Esto es una frase larga para probar salto inteligente",
                )
            ]
            with patch.object(
                pvc, "_obtener_fuente_y_dir_subtitulos", return_value=("Montserrat ExtraBold", "/tmp")
            ):
                pvc.generar_archivo_ass(subs, ruta_ass)

            contenido = ruta_ass.read_text(encoding="utf-8")
            self.assertIn("WrapStyle: 0", contenido)
            self.assertIn(
                "Style: Default,Montserrat ExtraBold,50,&H00FFFFFF,&H0000FFFF,&H00000000,&HA0000000,-1,0,0,0,100,100,1.2,0,1,5.0,3.0,2,120,120,450,1",
                contenido,
            )

    def test_smoke_ffmpeg_smart_wrap_optico_real(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_dir = Path(tmp)
            ruta_ass = pvc.generar_archivo_ass(
                [
                    pvc.SegmentoSubtitulo(
                        inicio_rel=0.0,
                        fin_rel=0.9,
                        texto="Prueba real Safe Zone centrado óptico",
                    )
                ],
                tmp_dir / "wrap.ass",
            )
            esc = pvc._escapar_ruta_ffmpeg_filtro(ruta_ass)
            _, fonts_dir = pvc._obtener_fuente_y_dir_subtitulos()
            vf = f"subtitles='{esc}':fontsdir='{pvc._escapar_ruta_ffmpeg_filtro(fonts_dir)}'" if fonts_dir else f"subtitles='{esc}'"
            out_mp4 = tmp_dir / "wrap.mp4"
            res = subprocess.run(
                [
                    "ffmpeg",
                    "-hide_banner",
                    "-loglevel",
                    "error",
                    "-y",
                    "-f",
                    "lavfi",
                    "-i",
                    "color=c=black:s=1080x1920:d=1",
                    "-vf",
                    vf,
                    "-c:v",
                    "libx264",
                    "-preset",
                    "ultrafast",
                    "-t",
                    "1",
                    str(out_mp4),
                ],
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(res.returncode, 0, msg=res.stderr)
            self.assertTrue(out_mp4.exists() and out_mp4.stat().st_size > 1000)


class TestFase2MotorLocalWhisperYOllama(unittest.TestCase):
    def test_listar_modelos_ollama_prioriza_y_maneja_offline(self):
        tags_json = json.dumps(
            {
                "models": [
                    {"name": "nomic-embed-text:latest"},
                    {"name": "gemma3:12b"},
                    {"name": "qwen3:14b"},
                    {"name": "llama3.1:8b"},
                ]
            }
        ).encode("utf-8")

        with patch.object(pvc.urllib.request, "urlopen", return_value=_FakeHTTPResponse(tags_json)):
            modelos = pvc.listar_modelos_ollama_disponibles()
        self.assertEqual(modelos[:3], ["gemma3:12b", "qwen3:14b", "llama3.1:8b"])
        self.assertNotIn("nomic-embed-text:latest", modelos)

        with patch.object(
            pvc.urllib.request, "urlopen", side_effect=urllib.error.URLError("Connection refused")
        ):
            fallback = pvc.listar_modelos_ollama_disponibles()
        self.assertEqual(fallback, list(pvc.MODELOS_LOCALES_OLLAMA))

    def test_asegurar_modelo_ollama_error_offline_y_pull_auto(self):
        with patch.object(
            pvc.urllib.request, "urlopen", side_effect=OSError("Connection refused")
        ):
            with self.assertRaises(RuntimeError) as ctx:
                pvc._asegurar_modelo_ollama("qwen3:14b")
            self.assertIn("127.0.0.1:11434", str(ctx.exception))

        tags_vacios = json.dumps({"models": [{"name": "gemma3:12b"}]}).encode("utf-8")
        pull_stream = (
            b'{"status":"pulling manifest"}\n'
            b'{"status":"downloading","total":100,"completed":50}\n'
            b'{"status":"success"}\n'
        )
        urls_llamadas = []

        def fake_urlopen(req, timeout=None):
            urls_llamadas.append(req.full_url)
            if req.full_url.endswith("/api/tags"):
                return _FakeHTTPResponse(tags_vacios)
            return _FakeHTTPResponse(pull_stream)

        logs = []
        with patch.object(pvc.urllib.request, "urlopen", side_effect=fake_urlopen):
            pvc._asegurar_modelo_ollama("qwen3:14b", on_log=logs.append)

        self.assertTrue(any(u.endswith("/api/pull") for u in urls_llamadas))
        self.assertTrue(any("50%" in l for l in logs))

    def test_calcular_energia_segmentos_audio_picos_vocales_reales(self):
        with tempfile.TemporaryDirectory() as tmp:
            wav_path = Path(tmp) / "test_peaks.wav"
            # Tramo 0 (0-2s): tono suave (0.08), Tramo 1 (2-4s): pico fuerte (0.90), Tramo 2 (4-6s): tono suave (0.08)
            res = subprocess.run(
                [
                    "ffmpeg",
                    "-hide_banner",
                    "-loglevel",
                    "error",
                    "-y",
                    "-f",
                    "lavfi",
                    "-i",
                    "sine=frequency=440:duration=2,volume=0.08",
                    "-f",
                    "lavfi",
                    "-i",
                    "sine=frequency=440:duration=2,volume=0.90",
                    "-f",
                    "lavfi",
                    "-i",
                    "sine=frequency=440:duration=2,volume=0.08",
                    "-filter_complex",
                    "[0:a][1:a][2:a]concat=n=3:v=0:a=1[outa]",
                    "-map",
                    "[outa]",
                    str(wav_path),
                ],
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(res.returncode, 0, msg=res.stderr)

            segmentos = [
                {"start": 0.1, "end": 1.9, "text": "hablando normal"},
                {"start": 2.1, "end": 3.9, "text": "grito eufórico"},
                {"start": 4.1, "end": 5.9, "text": "vuelve calma"},
            ]
            picos = pvc._calcular_energia_segmentos_audio(str(wav_path), segmentos)
            self.assertEqual(picos, {1})

            pcm = pvc._decodificar_audio_pcm_16k(str(wav_path))
            self.assertEqual(getattr(pcm, "dtype", None).name, "float32")
            self.assertGreater(len(pcm), 80000)

    def test_transcribir_audio_whisper_local_cache_telemetria_y_gc(self):
        with tempfile.TemporaryDirectory() as tmp:
            job_dir = Path(tmp) / "job"
            job_dir.mkdir(parents=True)
            audio_fake = job_dir / "temp_audio.mp3"
            audio_fake.write_bytes(b"MP3")

            fake_words = [
                SimpleNamespace(start=0.0, end=0.4, word="Qué"),
                SimpleNamespace(start=0.4, end=0.9, word="chimba"),
                SimpleNamespace(start=0.9, end=1.4, word="parce"),
            ]
            fake_seg = SimpleNamespace(start=0.0, end=1.4, text="Qué chimba parce", words=fake_words)
            fake_model = MagicMock()
            fake_model.transcribe.return_value = ([fake_seg], SimpleNamespace(duration=12.0, language="es"))
            fake_cls = MagicMock(return_value=fake_model)
            tele_eventos = []

            with patch.object(pvc, "WhisperModel", fake_cls), patch.object(
                pvc, "_calcular_energia_segmentos_audio", return_value={0}
            ), patch.object(pvc.gc, "collect", wraps=gc.collect) as spy_gc:
                res1 = pvc._transcribir_audio_whisper_local(
                    str(audio_fake),
                    job_dir=job_dir,
                    on_telemetria=tele_eventos.append,
                )
                self.assertEqual(fake_cls.call_count, 1)
                self.assertGreaterEqual(spy_gc.call_count, 1)
                self.assertTrue((job_dir / "whisper_transcript.json").exists())
                self.assertEqual(res1["indices_picos"], [0])
                self.assertEqual(len(res1["palabras"]), 3)
                self.assertTrue(any(e.get("etapa") == "local_whisper" for e in tele_eventos))
                self.assertEqual(tele_eventos[-1]["porcentaje"], 100.0)

                # Segunda llamada debe leer desde whisper_transcript.json sin instanciar WhisperModel
                res2 = pvc._transcribir_audio_whisper_local(str(audio_fake), job_dir=job_dir)
                self.assertEqual(fake_cls.call_count, 1)
                self.assertEqual(res2["palabras"], res1["palabras"])

            with patch.object(pvc, "WhisperModel", None):
                job_sin_cache = Path(tmp) / "sin_cache"
                with self.assertRaises(RuntimeError):
                    pvc._transcribir_audio_whisper_local(str(audio_fake), job_dir=job_sin_cache)

    def test_construir_subtitulos_desde_whisper_bloques_2_a_4_palabras(self):
        palabras = [
            {"start": 10.0, "end": 10.3, "word": "Parce"},
            {"start": 10.3, "end": 10.6, "word": "qué"},
            {"start": 10.6, "end": 11.0, "word": "locura."},
            {"start": 11.8, "end": 12.1, "word": "No"},
            {"start": 12.1, "end": 12.4, "word": "me"},
            {"start": 12.4, "end": 12.8, "word": "lo"},
            {"start": 12.8, "end": 13.2, "word": "creo"},
            {"start": 13.2, "end": 13.5, "word": "hermanito"},
        ]
        subs = pvc._construir_subtitulos_desde_whisper(palabras, inicio_seg=10.0, fin_seg=15.0)
        self.assertGreaterEqual(len(subs), 2)
        self.assertEqual(subs[0]["texto"], "Parce qué locura.")
        for s in subs:
            self.assertLessEqual(len(s["texto"].split()), 4)
            self.assertGreater(s["fin_rel"], s["inicio_rel"])
            self.assertLessEqual(s["fin_rel"], 5.0)

    def test_analizar_con_ollama_secuencial_y_descarga_ram(self):
        with tempfile.TemporaryDirectory() as tmp:
            job_dir = Path(tmp) / "job_ol"
            job_dir.mkdir(parents=True)
            audio_fake = job_dir / "temp_audio.mp3"
            audio_fake.write_bytes(b"MP3")

            fake_transcript = {
                "duracion_total": 45.0,
                "idioma": "es",
                "segmentos": [
                    {"start": 0.0, "end": 2.5, "text": "Arrancamos el stream parche"},
                    {"start": 2.5, "end": 8.0, "text": "NO PUEDE SER QUÉ GOLAZO"},
                    {"start": 8.0, "end": 28.0, "text": "La gente está vuelta loca en el chat"},
                ],
                "palabras": [
                    {"start": 2.5, "end": 3.0, "word": "NO"},
                    {"start": 3.0, "end": 3.5, "word": "PUEDE"},
                    {"start": 3.5, "end": 4.0, "word": "SER"},
                    {"start": 4.0, "end": 4.8, "word": "GOLAZO"},
                ],
                "indices_picos": [1],
            }

            ollama_json = {
                "clips": [
                    {
                        "id": 1,
                        "titulo": "NO PUEDE SER ESTE GOLAZO EN VIVO",
                        "inicio": "00:00:02",
                        "fin": "00:00:26",
                        "gancho": "NO PUEDE SER",
                        "razon_viral": "Grito explosivo de euforia",
                        "descripcion": "Clímax total en Kick",
                        "etiquetas": ["Kicksazos", "KickColombia"],
                        "caption_tiktok": "Reacción brutal en vivo 🔥",
                        "hashtags_tiktok": ["#Shorts", "#Kicksazos", "#Colombia"],
                        "gancho_visual_portada": "REACCIÓN BRUTAL EN VIVO",
                    }
                ]
            }
            ndjson_chat = (
                json.dumps({"message": {"thinking": "pensando...", "content": ""}, "done": False}).encode("utf-8")
                + b"\n"
                + json.dumps({"message": {"content": json.dumps(ollama_json)}, "done": True}).encode("utf-8")
                + b"\n"
            )

            peticiones = []

            def fake_urlopen(req, timeout=None):
                body = req.data.decode("utf-8") if req.data else ""
                peticiones.append((req.full_url, body))
                if req.full_url.endswith("/api/tags"):
                    return _FakeHTTPResponse(json.dumps({"models": [{"name": "qwen3:14b"}]}).encode("utf-8"))
                if req.full_url.endswith("/api/chat"):
                    # Verificar que se envió prompt con etiqueta de pico vocal
                    parsed_req = json.loads(body)
                    self.assertIn("[🔥 ALTA INTENSIDAD VOCAL]", parsed_req["messages"][0]["content"])
                    return _FakeHTTPResponse(ndjson_chat)
                if req.full_url.endswith("/api/generate"):
                    return _FakeHTTPResponse(b'{"done":true}\n')
                raise AssertionError(f"URL inesperada: {req.full_url}")

            tele_hist = []
            with patch.object(pvc, "_transcribir_audio_whisper_local", return_value=fake_transcript), patch.object(
                pvc.urllib.request, "urlopen", side_effect=fake_urlopen
            ), patch.object(pvc, "_guardar_y_sincronizar_clips") as spy_save:
                clips = pvc.analizar_con_ollama(
                    str(audio_fake),
                    modelo_local="qwen3:14b",
                    job_dir=job_dir,
                    on_telemetria=tele_hist.append,
                )

            self.assertEqual(len(clips), 1)
            self.assertEqual(clips[0]["subtitulos_origen"], "whisper_word_timestamps")
            self.assertEqual(clips[0]["motor_ia"], "local")
            self.assertEqual(clips[0]["modelo_ia"], "qwen3:14b")
            self.assertTrue(len(clips[0]["subtitulos"]) >= 1)
            spy_save.assert_called_once()
            # Debe descargar memoria RAM explícitamente con keep_alive=0 al finalizar
            self.assertTrue(
                any(u.endswith("/api/generate") and '"keep_alive": 0' in b for u, b in peticiones)
            )
            self.assertTrue(any(e.get("etapa") == "local_ollama" for e in tele_hist))


class TestFase3RenderPasadaUnicaHibrida(unittest.TestCase):
    def test_procesar_clip_ffmpeg_pasada_unica_local_omite_raw_clip(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_dir = Path(tmp)
            carpeta_salida = tmp_dir / "salida"
            job_dir = tmp_dir / "job"
            job_dir.mkdir(parents=True)
            fuente = tmp_dir / "fuente.mp4"
            fuente.write_bytes(b"VID")
            wm = tmp_dir / "watermark.png"
            wm.write_bytes(b"PNG")

            comandos = []

            def fake_cap(cmd, **kwargs):
                comandos.append(list(cmd))
                Path(cmd[-1]).write_bytes(b"OUT1PASS")
                return "ok"

            with patch.object(pvc, "CARPETA_SALIDA", carpeta_salida), patch.object(
                pvc, "RUTA_MARCA_AGUA", wm
            ), patch.object(pvc, "obtener_dimensiones_video", return_value=(1920, 1080)), patch.object(
                pvc, "detectar_encoder_hardware", return_value="libx264"
            ), patch.object(
                pvc, "_obtener_fuente_y_dir_subtitulos", return_value=("Montserrat ExtraBold", None)
            ), patch.object(
                pvc, "_alinear_subtitulos_con_clip_renderizado", side_effect=AssertionError("NO debe ejecutar paso 2 en local")
            ), patch.object(pvc, "_ejecutar_comando_con_captura", side_effect=fake_cap):
                salida = pvc.procesar_clip_ffmpeg(
                    str(fuente),
                    "00:00:00",
                    "00:00:08",
                    1,
                    job_id="job1pass",
                    job_dir=job_dir,
                    subtitulos=[{"inicio_rel": 0.2, "fin_rel": 2.0, "texto": "Hola mundo"}],
                    alinear_subtitulos=False,
                )

            self.assertEqual(len(comandos), 1)
            cmd_str = " ".join(comandos[0])
            self.assertIn("subtitles=", cmd_str)
            self.assertIn("subs_1.ass", cmd_str)
            self.assertFalse((job_dir / "raw_clip_1.mp4").exists())
            self.assertTrue(Path(salida).exists())

    def test_smoke_ffmpeg_pasada_unica_real_con_marca_de_agua_y_ass(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_dir = Path(tmp)
            carpeta_salida = tmp_dir / "salida"
            job_dir = tmp_dir / "job"
            job_dir.mkdir(parents=True)
            fuente = tmp_dir / "fuente_16_9.mp4"

            res_src = subprocess.run(
                [
                    "ffmpeg",
                    "-hide_banner",
                    "-loglevel",
                    "error",
                    "-y",
                    "-f",
                    "lavfi",
                    "-i",
                    "testsrc=size=1280x720:rate=24:duration=2",
                    "-f",
                    "lavfi",
                    "-i",
                    "sine=frequency=440:duration=2",
                    "-c:v",
                    "libx264",
                    "-preset",
                    "ultrafast",
                    "-c:a",
                    "aac",
                    str(fuente),
                ],
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(res_src.returncode, 0, msg=res_src.stderr)

            with patch.object(pvc, "CARPETA_SALIDA", carpeta_salida), patch.object(
                pvc, "detectar_encoder_hardware", return_value="libx264"
            ):
                out_path = pvc.procesar_clip_ffmpeg(
                    str(fuente),
                    "00:00:00",
                    "00:00:02",
                    "smoke1p",
                    job_id="smk",
                    job_dir=job_dir,
                    subtitulos=[{"inicio_rel": 0.1, "fin_rel": 1.8, "texto": "Subtítulo directo en una pasada"}],
                    alinear_subtitulos=False,
                )

            self.assertTrue(Path(out_path).exists())
            self.assertFalse((job_dir / "raw_clip_smoke1p.mp4").exists())
            dims = pvc.obtener_dimensiones_video(out_path)
            self.assertEqual(dims, (1080, 1920))

    def test_orquestar_render_y_subida_archivo_local_no_se_borra(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_dir = Path(tmp)
            local_mp4 = tmp_dir / "entrada_local.mp4"
            local_mp4.write_bytes(b"MP4LOCAL")
            job_dir = tmp_dir / "job"
            job_dir.mkdir()
            clips = [
                {
                    "id": 1,
                    "titulo": "Local test",
                    "inicio": "00:00:00",
                    "fin": "00:00:10",
                    "subtitulos": [{"inicio_rel": 0.0, "fin_rel": 1.0, "texto": "Uno dos"}],
                    "subtitulos_origen": "whisper_word_timestamps",
                }
            ]
            recibidos = {}

            def fake_render(url_in, ini, fin, cid, **kwargs):
                recibidos["url_in"] = url_in
                recibidos["alinear"] = kwargs.get("alinear_subtitulos")
                return str(tmp_dir / "out.mp4")

            with patch.object(pvc, "procesar_clip_ffmpeg", side_effect=fake_render), patch.object(
                pvc, "descargar_video_fuente", side_effect=AssertionError("No debe descargar archivo local")
            ), patch.object(pvc, "_guardar_y_sincronizar_clips"):
                list(
                    pvc._orquestar_render_y_subida(
                        url=str(local_mp4),
                        clips=clips,
                        duracion_total=10.0,
                        subir_youtube=False,
                        job_id="jloc",
                        job_dir=job_dir,
                        alinear_subtitulos=True,
                    )
                )

            self.assertEqual(recibidos["url_in"], str(local_mp4))
            self.assertFalse(recibidos["alinear"])
            self.assertTrue(local_mp4.exists())


class TestFase4OrquestadorCLIGradioV41(unittest.TestCase):
    def test_ejecutar_pipeline_completo_local_sin_gemini_api_key(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_dir = Path(tmp)
            fake_audio = tmp_dir / "temp_audio.mp3"
            fake_audio.write_bytes(b"AUDIO")
            ctx = pvc.JobContext(
                job_id="job_loc_1",
                job_dir=tmp_dir / "job_loc_1",
            )
            ctx.job_dir.mkdir(parents=True)
            clips_mock = [
                {
                    "id": 1,
                    "titulo": "Clip Local",
                    "inicio": "00:00:00",
                    "fin": "00:00:15",
                    "gancho": "Hola",
                    "subtitulos": [],
                    "subtitulos_origen": "whisper_word_timestamps",
                }
            ]

            with patch.dict(os.environ, {"GEMINI_API_KEY": ""}, clear=False), patch.object(
                pvc, "crear_contexto_job", return_value=ctx
            ), patch.object(pvc, "_limpiar_jobs_antiguos", return_value=0), patch.object(
                pvc, "extraer_audio", return_value=str(fake_audio)
            ), patch.object(pvc, "obtener_duracion_media", return_value=30.0), patch.object(
                pvc, "analizar_con_ollama", return_value=clips_mock
            ) as spy_ol, patch.object(
                pvc, "analizar_con_gemini", side_effect=AssertionError("No debe llamar Gemini en modo local")
            ):
                estados = list(
                    pvc.ejecutar_pipeline_completo(
                        url="https://kick.com/eldomi/videos/test",
                        motor_ia="local",
                        modelo_local="gemma3:12b",
                        solo_analisis=True,
                        subir_youtube=False,
                    )
                )

            spy_ol.assert_called_once()
            self.assertEqual(spy_ol.call_args.kwargs.get("modelo_local"), "gemma3:12b")
            self.assertEqual(estados[-1]["fase"], "completado")
            self.assertIsNone(estados[-1].get("error"))

    def test_ejecutar_pipeline_completo_respaldo_auto_429(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_dir = Path(tmp)
            fake_audio = tmp_dir / "temp_audio.mp3"
            fake_audio.write_bytes(b"AUDIO")
            ctx = pvc.JobContext(
                job_id="job_fb_429",
                job_dir=tmp_dir / "job_fb_429",
            )
            ctx.job_dir.mkdir(parents=True)
            clips_mock = [
                {
                    "id": 1,
                    "titulo": "Fallback Local",
                    "inicio": "00:00:00",
                    "fin": "00:00:12",
                    "gancho": "Parce",
                    "subtitulos": [],
                    "subtitulos_origen": "whisper_word_timestamps",
                }
            ]

            def fake_orq(**kwargs):
                yield {
                    "fase": "render",
                    "progreso": 0.9,
                    "mensaje": "Render OK",
                    "clips": kwargs["clips"],
                    "alinear_recibido": kwargs.get("alinear_subtitulos"),
                    "telemetria": {"etapa": "render", "porcentaje": 100.0},
                }

            with patch.dict(os.environ, {"GEMINI_API_KEY": "fake-key"}, clear=False), patch.object(
                pvc, "crear_contexto_job", return_value=ctx
            ), patch.object(pvc, "_limpiar_jobs_antiguos", return_value=0), patch.object(
                pvc, "extraer_audio", return_value=str(fake_audio)
            ), patch.object(pvc, "obtener_duracion_media", return_value=30.0), patch.object(
                pvc, "analizar_con_gemini", side_effect=pvc.GeminiQuotaExhaustedError("429 quota")
            ), patch.object(
                pvc, "analizar_con_ollama", return_value=clips_mock
            ) as spy_ol, patch.object(
                pvc, "_orquestar_render_y_subida", side_effect=fake_orq
            ) as spy_orq:
                estados = list(
                    pvc.ejecutar_pipeline_completo(
                        url="https://kick.com/eldomi/videos/429",
                        motor_ia="gemini",
                        modelo_local="qwen3:14b",
                        respaldo_local_auto=True,
                        subir_youtube=False,
                    )
                )

            spy_ol.assert_called_once()
            self.assertFalse(spy_orq.call_args.kwargs.get("alinear_subtitulos"))
            self.assertEqual(estados[-1]["fase"], "completado")

    def test_cli_main_flags_local_y_formateo_barra(self):
        linea_w = pvc._formatear_barra_cli(
            {"telemetria": {"etapa": "local_whisper", "porcentaje": 50.0, "velocidad_red": "CPU int8", "tamano_total": "10 segs", "detalle": "Transcrito"}}
        )
        linea_o = pvc._formatear_barra_cli(
            {"telemetria": {"etapa": "local_ollama", "porcentaje": 75.0, "modelo_ia": "qwen3:14b", "tamano_total": "Bloque 1/1", "detalle": "JSON"}}
        )
        self.assertIn("Whisper (CPU int8)", linea_w)
        self.assertIn("Ollama qwen3:14b", linea_o)

        capturado = {}

        def fake_pipe(**kwargs):
            capturado.update(kwargs)
            yield {"fase": "completado", "progreso": 1.0, "mensaje": "OK", "job_dir": "/tmp/j", "telemetria": {"etapa": "completado", "porcentaje": 100.0}}

        with patch.object(pvc, "ejecutar_pipeline_completo", side_effect=fake_pipe), patch.object(
            sys,
            "argv",
            ["pipeline_viral_clips.py", "/tmp/video.mp4", "--motor", "local", "--modelo-local", "gemma3:12b", "--sin-respaldo-local", "--sin-subida"],
        ), patch("sys.stdout", new_callable=io.StringIO):
            pvc.main()

        self.assertEqual(capturado["motor_ia"], "local")
        self.assertEqual(capturado["modelo_local"], "gemma3:12b")
        self.assertFalse(capturado["respaldo_local_auto"])
        self.assertFalse(capturado["subir_youtube"])

    def test_desktop_ui_v50_selector_hibrido_y_telemetria(self):
        norm = ui_services.normalizar_estado_telemetria(
            {
                "fase": "local_whisper",
                "progreso": 0.4,
                "mensaje": "Transcribiendo localmente",
                "telemetria": {
                    "etapa": "local_whisper",
                    "titulo_etapa": "Transcripción Local (Whisper Medium)",
                    "porcentaje": 60.0,
                    "velocidad_red": "CPU int8",
                    "eta": "00:18",
                    "detalle": "Procesando",
                },
            }
        )
        self.assertEqual(norm["etapa_num"], 2)
        self.assertEqual(norm["progreso"], 60.0)
        self.assertEqual(norm["velocidad"], "CPU int8")

        app = app_interfaz.crear_aplicacion([])
        ventana = app_interfaz.KicksazosMainWindow(auto_probe=False)
        try:
            cc = ventana.vista_command_center
            self.assertEqual(cc.combo_motor.count(), 3)
            self.assertEqual(cc.combo_motor.currentData(), "gemini")
            self.assertEqual(cc.combo_modelo.currentData(), pvc.MODELOS_CANDIDATOS[0])

            cc.actualizar_modelos_ollama(["qwen3:14b", "gemma3:12b"])
            idx_local = cc.combo_motor.findData("local")
            cc.combo_motor.setCurrentIndex(idx_local)
            modelos_ui = [
                cc.combo_modelo.itemData(i) for i in range(cc.combo_modelo.count())
            ]
            self.assertEqual(modelos_ui, ["qwen3:14b", "gemma3:12b"])

            cc.actualizar_telemetria(norm)
            self.assertEqual(cc.bar_etapa.value(), 60)
            self.assertEqual(cc.kpi_velocidad.lbl_valor.text(), "CPU int8")
        finally:
            ventana.close()
            app.processEvents()


if __name__ == "__main__":
    unittest.main()
