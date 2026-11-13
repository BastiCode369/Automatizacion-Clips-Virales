import asyncio
import gc
import json
import os
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import gradio as gr

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

import app_interfaz
import pipeline_viral_clips as pvc


def _cerrar_loops_gradio(*demos: object) -> None:
    """Cierra instancias gr.Blocks y event loops asyncio huérfanos para evitar ResourceWarning."""
    for demo_obj in (*demos, getattr(app_interfaz, "demo", None)):
        if demo_obj is not None:
            try:
                demo_obj.close()
            except Exception:
                pass

    try:
        asyncio.set_event_loop(None)
    except Exception:
        pass

    for obj in list(gc.get_objects()):
        try:
            if isinstance(obj, asyncio.AbstractEventLoop) and not obj.is_closed() and not obj.is_running():
                obj.close()
        except Exception:
            pass
    gc.collect()


def _crear_mp4_sintetico(carpeta: Path, nombre: str = "sample.mp4") -> Path:
    """Genera un MP4 H.264 + AAC corto para smoke tests reales de FFmpeg."""
    video_path = carpeta / nombre
    subprocess.run(
        [
            "ffmpeg",
            "-hide_banner",
            "-loglevel",
            "error",
            "-y",
            "-f",
            "lavfi",
            "-i",
            "color=c=navy:s=1080x1920:d=0.6:r=24",
            "-f",
            "lavfi",
            "-i",
            "sine=frequency=440:sample_rate=44100:duration=0.6",
            "-c:v",
            "libx264",
            "-pix_fmt",
            "yuv420p",
            "-c:a",
            "aac",
            "-shortest",
            str(video_path),
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    return video_path


class TestTarea1AudioUltraLigero(unittest.TestCase):
    def test_extraer_audio_fallback_ffmpeg_usa_12000hz_24k(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_dir = Path(tmp)
            comandos = []

            def fake_descarga(cmd, **kwargs):
                comandos.append(cmd)
                # Simula fallo de yt-dlp para disparar fallback directo FFmpeg
                raise subprocess.CalledProcessError(1, cmd, stderr="ytdlp err")

            def fake_ffmpeg(cmd, **kwargs):
                comandos.append(cmd)
                Path(cmd[-1]).write_bytes(b"MP3" * 5000)

            with patch.object(pvc, "_ejecutar_descarga_con_telemetria", side_effect=fake_descarga), patch.object(
                pvc, "_obtener_url_audio_directo", return_value="https://stream.example.com/audio.m3u8"
            ), patch.object(pvc, "_ejecutar_comando_con_captura", side_effect=fake_ffmpeg):
                salida = pvc.extraer_audio(
                    "https://kick.com/streamer/videos/123",
                    job_dir=tmp_dir,
                    on_log=lambda _: None,
                )

            self.assertTrue(Path(salida).exists())
            self.assertEqual(len(comandos), 2)
            cmd_ytdlp, cmd_ffmpeg = comandos
            self.assertEqual(cmd_ytdlp[cmd_ytdlp.index("--postprocessor-args") + 1], "ffmpeg:-vn -ac 1 -ar 12000 -b:a 24k")
            self.assertEqual(cmd_ffmpeg[0], "ffmpeg")
            self.assertEqual(cmd_ffmpeg[cmd_ffmpeg.index("-ac") + 1], "1")
            self.assertEqual(cmd_ffmpeg[cmd_ffmpeg.index("-ar") + 1], "12000")
            self.assertEqual(cmd_ffmpeg[cmd_ffmpeg.index("-b:a") + 1], "24k")


class TestTarea2ChunkingYGeminiParalelo(unittest.TestCase):
    def test_analizar_con_gemini_paralelo_telemetria_bloques_activos_y_porcentaje(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_dir = Path(tmp)
            audio = tmp_dir / "temp_audio.mp3"
            audio.write_bytes(b"ORIG")

            def fake_ffmpeg(cmd, **kwargs):
                Path(cmd[-1]).write_bytes(b"CHUNK")
                return SimpleNamespace(returncode=0)

            lock_estado = threading.Lock()
            activos_now = {"count": 0, "max_concurrent": 0}
            telemetrias = []

            respuestas = {
                "temp_audio_chunk_00.mp3": [
                    {
                        "id": 1,
                        "titulo": "Clip 1",
                        "inicio": "00:01:00",
                        "fin": "00:01:40",
                        "duracion_segundos": 40,
                        "razon_viral": "Buen clip",
                        "gancho_texto": "Ey",
                        "descripcion": "Desc",
                        "etiquetas": ["shorts"],
                        "subtitulos": [{"inicio_rel": 0.0, "fin_rel": 1.2, "texto": "Hola parcero"}],
                    }
                ],
                "temp_audio_chunk_01.mp3": [
                    {
                        "id": 1,
                        "titulo": "Clip 2",
                        "inicio": "00:02:00",
                        "fin": "00:02:45",
                        "duracion_segundos": 45,
                        "razon_viral": "Otro clip",
                        "gancho_texto": "Mira",
                        "descripcion": "Desc",
                        "etiquetas": ["shorts"],
                        "subtitulos": [{"inicio_rel": 0.5, "fin_rel": 2.0, "texto": "Qué locura"}],
                    }
                ],
                "temp_audio_chunk_02.mp3": [
                    {
                        "id": 1,
                        "titulo": "Clip 3",
                        "inicio": "00:00:30",
                        "fin": "00:01:05",
                        "duracion_segundos": 35,
                        "razon_viral": "Cierre",
                        "gancho_texto": "Brutal",
                        "descripcion": "Desc",
                        "etiquetas": ["shorts"],
                        "subtitulos": [{"inicio_rel": 0.0, "fin_rel": 1.5, "texto": "Tremendo cierre"}],
                    }
                ],
            }

            def fake_analizar_chunk(client, ruta_archivo, duracion_bloque, modelo_preferido, on_log, **kwargs):
                with lock_estado:
                    activos_now["count"] += 1
                    activos_now["max_concurrent"] = max(activos_now["max_concurrent"], activos_now["count"])
                try:
                    time.sleep(0.08)
                    return respuestas[Path(ruta_archivo).name]
                finally:
                    with lock_estado:
                        activos_now["count"] -= 1

            with patch.dict(pvc.os.environ, {"GEMINI_API_KEY": "test_key"}), patch.object(
                pvc, "BASE_DIR", tmp_dir
            ), patch.object(
                pvc.genai, "Client", return_value=MagicMock()
            ), patch.object(pvc.subprocess, "run", side_effect=fake_ffmpeg), patch.object(
                pvc, "_analizar_archivo_audio_gemini", side_effect=fake_analizar_chunk
            ):
                resultado = pvc.analizar_con_gemini(
                    audio,
                    duracion_total=3300.0,
                    job_dir=tmp_dir,
                    on_log=lambda _: None,
                    on_telemetria=lambda d: telemetrias.append(dict(d)),
                )

            self.assertEqual([c["id"] for c in resultado], [1, 2, 3])
            # Con max_workers=3 y 3 chunks de 80ms deben traslaparse en ejecución paralela
            self.assertGreaterEqual(activos_now["max_concurrent"], 2)

            eventos_gemini = [t for t in telemetrias if t.get("etapa") == "gemini"]
            self.assertTrue(any("Bloque 1/3" in (t.get("bloques_activos") or []) for t in eventos_gemini))
            self.assertTrue(any(t.get("total_bloques") == 3 for t in eventos_gemini))
            completados_vistos = [t.get("bloques_completados") for t in eventos_gemini if "bloques_completados" in t]
            self.assertIn(3, completados_vistos)
            ultimo = eventos_gemini[-1]
            self.assertEqual(ultimo["bloques_completados"], 3)
            self.assertEqual(ultimo["total_bloques"], 3)
            self.assertEqual(ultimo["bloques_activos"], [])
            self.assertEqual(ultimo["porcentaje"], 100.0)
            self.assertEqual(list(tmp_dir.glob("temp_audio_chunk_*.mp3")), [])

    def test_analizar_con_gemini_chunk_fallido_aislado_no_aborta_otros_bloques(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_dir = Path(tmp)
            audio = tmp_dir / "temp_audio.mp3"
            audio.write_bytes(b"ORIG")

            def fake_ffmpeg(cmd, **kwargs):
                Path(cmd[-1]).write_bytes(b"CHUNK")
                return SimpleNamespace(returncode=0)

            def fake_analizar_chunk(client, ruta_archivo, duracion_bloque, modelo_preferido, on_log, **kwargs):
                nombre = Path(ruta_archivo).name
                if nombre == "temp_audio_chunk_01.mp3":
                    raise RuntimeError("Error transitorio bloque 2")
                return [
                    {
                        "id": 1,
                        "titulo": f"Ok {nombre}",
                        "inicio": "00:01:00",
                        "fin": "00:01:30",
                        "duracion_segundos": 30,
                        "razon_viral": "Bueno",
                        "gancho_texto": "Ey",
                        "descripcion": "Desc",
                        "etiquetas": ["shorts"],
                        "subtitulos": [],
                    }
                ]

            with patch.dict(pvc.os.environ, {"GEMINI_API_KEY": "test_key"}), patch.object(
                pvc, "BASE_DIR", tmp_dir
            ), patch.object(
                pvc.genai, "Client", return_value=MagicMock()
            ), patch.object(pvc.subprocess, "run", side_effect=fake_ffmpeg), patch.object(
                pvc, "_analizar_archivo_audio_gemini", side_effect=fake_analizar_chunk
            ):
                resultado = pvc.analizar_con_gemini(
                    audio, duracion_total=3300.0, job_dir=tmp_dir, on_log=lambda _: None
                )

            self.assertEqual(len(resultado), 2)
            self.assertEqual([c["id"] for c in resultado], [1, 2])

    def test_segmentar_audio_en_chunks_umbral_1800_y_bloques_1500_solape_60(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_dir = Path(tmp)
            audio = tmp_dir / "temp_audio.mp3"
            audio.write_bytes(b"AUDIO")

            with patch.object(pvc.subprocess, "run") as mock_run_corto:
                un_bloque = pvc._segmentar_audio_en_chunks(audio, duracion_total=1800.0)
            mock_run_corto.assert_not_called()
            self.assertEqual(un_bloque, [(str(audio), 0.0, 1800.0)])

            comandos_vistos = []

            def fake_ffmpeg(cmd, **kwargs):
                comandos_vistos.append(list(cmd))
                Path(cmd[-1]).write_bytes(b"CHUNK")
                return SimpleNamespace(returncode=0)

            with patch.object(pvc.subprocess, "run", side_effect=fake_ffmpeg):
                bloques = pvc._segmentar_audio_en_chunks(
                    audio,
                    duracion_total=3300.0,
                    max_duracion_chunk=1500,
                    solapamiento=60,
                )

            self.assertEqual(len(bloques), 3)
            self.assertEqual(len(comandos_vistos), 3)
            offsets_y_durs = [(Path(r).name, off, dur) for r, off, dur in bloques]
            self.assertEqual(
                offsets_y_durs,
                [
                    ("temp_audio_chunk_00.mp3", 0.0, 1500.0),
                    ("temp_audio_chunk_01.mp3", 1440.0, 1500.0),
                    ("temp_audio_chunk_02.mp3", 2880.0, 420.0),
                ],
            )
            self.assertIn("-ss", comandos_vistos[1])
            self.assertEqual(comandos_vistos[1][comandos_vistos[1].index("-ss") + 1], "1440.000")
            self.assertEqual(comandos_vistos[1][comandos_vistos[1].index("-t") + 1], "1500.000")

    def test_analizar_con_gemini_desplaza_offsets_y_deduplica_solapamientos(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_dir = Path(tmp)
            audio = tmp_dir / "temp_audio.mp3"
            audio.write_bytes(b"AUDIO")

            def fake_ffmpeg(cmd, **kwargs):
                Path(cmd[-1]).write_bytes(b"CHUNK")
                return SimpleNamespace(returncode=0)

            respuestas = {
                "temp_audio_chunk_00.mp3": [
                    {
                        "id": 1,
                        "titulo": "Inicio Stream",
                        "inicio": "00:01:00",
                        "fin": "00:01:30",
                        "duracion_segundos": 30,
                        "razon_viral": "Intro",
                        "gancho_texto": "Arrancamos",
                        "descripcion": "Desc",
                        "etiquetas": ["shorts"],
                        "subtitulos": [{"inicio_rel": 0.0, "fin_rel": 1.2, "texto": "Hola"}],
                    },
                    {
                        "id": 2,
                        "titulo": "Solapado Corto",
                        "inicio": "00:24:10",
                        "fin": "00:24:45",
                        "duracion_segundos": 35,
                        "razon_viral": "Casi igual",
                        "gancho_texto": "Ey",
                        "descripcion": "Desc",
                        "etiquetas": ["shorts"],
                        "subtitulos": [{"inicio_rel": 0.0, "fin_rel": 1.0, "texto": "Corto"}],
                    },
                ],
                "temp_audio_chunk_01.mp3": [
                    {
                        "id": 1,
                        "titulo": "Solapado Ganador",
                        "inicio": "00:00:08",
                        "fin": "00:00:50",
                        "duracion_segundos": 42,
                        "razon_viral": "Mejor encuadre completo del remate",
                        "gancho_texto": "No te lo crees",
                        "descripcion": "Desc",
                        "etiquetas": ["shorts"],
                        "subtitulos": [
                            {"inicio_rel": 0.2, "fin_rel": 1.4, "texto": "Mira esto"},
                            {"inicio_rel": 1.4, "fin_rel": 2.8, "texto": "Qué locura"},
                        ],
                    },
                    {
                        "id": 2,
                        "titulo": "Segundo Bloque",
                        "inicio": "00:02:00",
                        "fin": "00:02:35",
                        "duracion_segundos": 35,
                        "razon_viral": "Clímax",
                        "gancho_texto": "Golazo",
                        "descripcion": "Desc",
                        "etiquetas": ["shorts"],
                        "subtitulos": [],
                    },
                ],
            }

            with patch.dict(pvc.os.environ, {"GEMINI_API_KEY": "test_key"}), patch.object(
                pvc, "BASE_DIR", tmp_dir
            ), patch.object(
                pvc.genai, "Client", return_value=MagicMock()
            ), patch.object(pvc.subprocess, "run", side_effect=fake_ffmpeg), patch.object(
                pvc,
                "_analizar_archivo_audio_gemini",
                side_effect=lambda client, ruta_archivo, *a, **kw: respuestas[Path(ruta_archivo).name],
            ):
                resultado = pvc.analizar_con_gemini(
                    audio, duracion_total=2100.0, job_dir=tmp_dir, on_log=lambda _: None
                )

            # Offset chunk 1 = +1440s (24m): [00:08..00:50] -> [24:08..24:50] reemplaza a [24:10..24:45]
            self.assertEqual(len(resultado), 3)
            self.assertEqual([c["id"] for c in resultado], [1, 2, 3])
            self.assertEqual([c["titulo"] for c in resultado], ["Inicio Stream", "Solapado Ganador", "Segundo Bloque"])
            self.assertEqual(resultado[1]["inicio"], "00:24:08")
            self.assertEqual(resultado[1]["fin"], "00:24:50")
            self.assertEqual(resultado[1]["subtitulos"][0]["inicio_rel"], 0.2)
            self.assertEqual(resultado[2]["inicio"], "00:26:00")
            self.assertEqual(resultado[2]["fin"], "00:26:35")


class TestTarea3AlineacionYRenderDosPasos(unittest.TestCase):
    def test_generar_archivo_ass_centrado_optico_v41(self):
        with tempfile.TemporaryDirectory() as tmp:
            ruta_ass = Path(tmp) / "subtitulo_simetrico.ass"
            subs = [
                pvc.SegmentoSubtitulo(inicio_rel=0.0, fin_rel=1.4, texto="Qué {locura} hermano"),
                {"inicio_rel": 1.4, "fin_rel": 2.9, "texto": "Clip viral centrado"},
            ]

            with patch.object(pvc, "_obtener_fuente_y_dir_subtitulos", return_value=("Montserrat ExtraBold", None)):
                salida = pvc.generar_archivo_ass(subs, ruta_ass)

            self.assertEqual(Path(salida).resolve(), ruta_ass.resolve())
            contenido = ruta_ass.read_text(encoding="utf-8")
            self.assertIn("PlayResX: 1080", contenido)
            self.assertIn("PlayResY: 1920", contenido)
            self.assertIn("WrapStyle: 0", contenido)
            linea_estilo = next(l for l in contenido.splitlines() if l.startswith("Style: Default,"))
            campos = linea_estilo.split(",")
            # Format: ...,Fontsize(2),...,Spacing(13),...,Outline(16),Shadow(17),Alignment(18),MarginL(19),MarginR(20),MarginV(21),Encoding(22)
            self.assertEqual(campos[2], "50")
            self.assertEqual(campos[13], "1.2")
            self.assertEqual(campos[16], "5.0")
            self.assertEqual(campos[17], "3.0")
            self.assertEqual(campos[18], "2")
            self.assertEqual(campos[19], "80")
            self.assertEqual(campos[20], "170")
            self.assertEqual(campos[21], "550")
            self.assertIn("QUÉ (LOCURA) HERMANO", contenido)
            self.assertIn("CLIP VIRAL CENTRADO", contenido)

    def test_alinear_subtitulos_guardas_tempranas(self):
        subs = [pvc.SegmentoSubtitulo(inicio_rel=0.0, fin_rel=1.0, texto="Hola parcero")]
        with tempfile.TemporaryDirectory() as tmp:
            tmp_dir = Path(tmp)
            raw_ok = tmp_dir / "raw_clip_1.mp4"
            raw_ok.write_bytes(b"RAW")

            with patch.object(pvc.subprocess, "run") as mock_run:
                # 1. Sin subtítulos
                self.assertEqual(
                    pvc._alinear_subtitulos_con_clip_renderizado(str(raw_ok), [], tmp_dir, 1, 10.0),
                    [],
                )
                # 2. Sin GEMINI_API_KEY
                with patch.dict(pvc.os.environ, {}, clear=True):
                    res_no_key = pvc._alinear_subtitulos_con_clip_renderizado(
                        str(raw_ok), subs, tmp_dir, 1, 10.0
                    )
                    self.assertEqual(res_no_key, subs)
                # 3. Archivo raw inexistente
                with patch.dict(pvc.os.environ, {"GEMINI_API_KEY": "k"}):
                    res_no_file = pvc._alinear_subtitulos_con_clip_renderizado(
                        str(tmp_dir / "no_existe.mp4"), subs, tmp_dir, 1, 10.0
                    )
                    self.assertEqual(res_no_file, subs)
            mock_run.assert_not_called()

    def test_alinear_subtitulos_exito_cascada_429_y_limpieza(self):
        subs_in = [pvc.SegmentoSubtitulo(inicio_rel=0.0, fin_rel=1.2, texto="Hola parcero")]
        with tempfile.TemporaryDirectory() as tmp:
            tmp_dir = Path(tmp)
            raw = tmp_dir / "raw_clip_7.mp4"
            raw.write_bytes(b"RAWVIDEO")
            comandos_ffmpeg = []

            def fake_run(cmd, **kwargs):
                comandos_ffmpeg.append(cmd)
                Path(cmd[-1]).write_bytes(b"MP3AUDIO")
                return SimpleNamespace(returncode=0)

            cliente = MagicMock()
            archivo_remoto = SimpleNamespace(name="files/clip_audio_7", state=SimpleNamespace(name="ACTIVE"))
            cliente.files.upload.return_value = archivo_remoto
            cliente.files.get.return_value = archivo_remoto

            configs_usados = []
            modelos_llamados = []

            def fake_generate_stream(model, contents, config):
                modelos_llamados.append(model)
                configs_usados.append(config)
                if len(modelos_llamados) == 1:
                    raise pvc.APIError(
                        429,
                        {
                            "error": {
                                "code": 429,
                                "status": "RESOURCE_EXHAUSTED",
                                "message": "Quota exceeded for metric: GenerateRequestsPerDayPerProjectPerModel-FreeTier",
                            }
                        },
                    )
                return [
                    SimpleNamespace(
                        text=json.dumps(
                            [
                                {"inicio_rel": 0.42, "fin_rel": 1.35, "texto": "hola parcero"},
                                {"inicio_rel": 1.40, "fin_rel": 2.90, "texto": "qué hubo pues parcero hoy acá"},
                            ]
                        )
                    )
                ]

            cliente.models.generate_content_stream.side_effect = fake_generate_stream

            with patch.dict(pvc.os.environ, {"GEMINI_API_KEY": "secret_test"}), patch.object(
                pvc.subprocess, "run", side_effect=fake_run
            ), patch.object(pvc.genai, "Client", return_value=cliente), patch.object(
                pvc.time, "sleep"
            ) as mock_sleep:
                res = pvc._alinear_subtitulos_con_clip_renderizado(
                    str(raw), subs_in, tmp_dir, 7, 15.0, on_log=lambda _: None
                )

            # FFmpeg extrajo audio con parámetros ultra-ligeros exactos
            self.assertEqual(len(comandos_ffmpeg), 1)
            cmd = comandos_ffmpeg[0]
            self.assertEqual(cmd[:7], ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-i", str(raw)])
            self.assertIn("-vn", cmd)
            self.assertEqual(cmd[cmd.index("-ac") + 1], "1")
            self.assertEqual(cmd[cmd.index("-ar") + 1], "12000")
            self.assertEqual(cmd[cmd.index("-b:a") + 1], "24k")
            self.assertTrue(cmd[-1].endswith("clip_audio_7.mp3"))

            # Salto 0s en 429 Free Tier (no duerme backoff) y reutiliza MODELOS_CANDIDATOS
            mock_sleep.assert_not_called()
            self.assertEqual(modelos_llamados, [pvc.MODELOS_CANDIDATOS[0], pvc.MODELOS_CANDIDATOS[1]])
            self.assertEqual(configs_usados[-1].temperature, 0.1)
            self.assertEqual(configs_usados[-1].response_mime_type, "application/json")
            self.assertEqual(configs_usados[-1].response_schema, list[pvc.SegmentoSubtitulo])

            # Subtítulos normalizados (el de 6 palabras se parte en bloques <= 4 palabras)
            self.assertEqual(len(res), 3)
            self.assertAlmostEqual(res[0].inicio_rel, 0.42, places=2)
            for seg in res:
                self.assertLessEqual(len(seg.texto.split()), 4)

            # Cleanup local y remoto garantizado
            cliente.files.delete.assert_called_once_with(name="files/clip_audio_7")
            self.assertFalse((tmp_dir / "clip_audio_7.mp3").exists())

    def test_alinear_subtitulos_fallback_seguro_en_error(self):
        subs_in = [pvc.SegmentoSubtitulo(inicio_rel=0.2, fin_rel=1.4, texto="Texto original")]
        logs = []
        with tempfile.TemporaryDirectory() as tmp:
            tmp_dir = Path(tmp)
            raw = tmp_dir / "raw_clip_9.mp4"
            raw.write_bytes(b"RAW")

            def fake_run(cmd, **kwargs):
                Path(cmd[-1]).write_bytes(b"MP3")
                return SimpleNamespace(returncode=0)

            cliente = MagicMock()
            archivo_remoto = SimpleNamespace(name="files/clip_audio_9", state=SimpleNamespace(name="ACTIVE"))
            cliente.files.upload.return_value = archivo_remoto
            cliente.files.get.return_value = archivo_remoto
            cliente.models.generate_content_stream.side_effect = RuntimeError("Timeout API")

            with patch.dict(pvc.os.environ, {"GEMINI_API_KEY": "k"}), patch.object(
                pvc.subprocess, "run", side_effect=fake_run
            ), patch.object(pvc.genai, "Client", return_value=cliente), patch.object(pvc.time, "sleep"):
                res = pvc._alinear_subtitulos_con_clip_renderizado(
                    str(raw), subs_in, tmp_dir, 9, 12.0, on_log=logs.append
                )

            self.assertEqual(res, subs_in)
            self.assertTrue(any("fallback seguro" in m.lower() for m in logs))
            cliente.files.delete.assert_called_once_with(name="files/clip_audio_9")
            self.assertFalse((tmp_dir / "clip_audio_9.mp3").exists())

    def test_procesar_clip_ffmpeg_dos_pasos_con_subtitulos_y_limpieza_raw(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_dir = Path(tmp)
            carpeta_salida = tmp_dir / "salida"
            job_dir = tmp_dir / "job"
            job_dir.mkdir(parents=True)
            fuente = tmp_dir / "temp_source.mp4"
            fuente.write_bytes(b"VIDEO")
            wm = tmp_dir / "watermark.png"
            wm.write_bytes(b"PNG")

            comandos_ejecutados = []
            estado_raw_durante_alineacion = {}

            def fake_alinear(ruta_raw, subs, jdir, cid, dur, on_log=None):
                estado_raw_durante_alineacion["existe"] = Path(ruta_raw).exists()
                estado_raw_durante_alineacion["nombre"] = Path(ruta_raw).name
                return [pvc.SegmentoSubtitulo(inicio_rel=0.5, fin_rel=1.8, texto="Sub alineado")]

            def fake_captura(cmd, duracion_objetivo=None, on_progreso=None):
                comandos_ejecutados.append(list(cmd))
                Path(cmd[-1]).write_bytes(b"MP4DATA")
                if on_progreso is not None:
                    on_progreso(
                        {
                            "porcentaje": 100.0,
                            "fps_str": "60.0",
                            "speed_str": "2.0x",
                            "eta_str": "00:00",
                            "frame": 120,
                            "out_time_str": "00:00:05",
                        }
                    )

            with patch.object(pvc, "CARPETA_SALIDA", carpeta_salida), patch.object(
                pvc, "RUTA_MARCA_AGUA", wm
            ), patch.object(pvc, "obtener_dimensiones_video", return_value=(1920, 1080)), patch.object(
                pvc, "detectar_encoder_hardware", return_value="libx264"
            ), patch.object(
                pvc, "_alinear_subtitulos_con_clip_renderizado", side_effect=fake_alinear
            ), patch.object(
                pvc, "_ejecutar_comando_con_captura", side_effect=fake_captura
            ):
                salida = pvc.procesar_clip_ffmpeg(
                    str(fuente),
                    "00:00:10",
                    "00:00:15",
                    id_clip=3,
                    job_id="job_test",
                    subtitulos=[{"inicio_rel": 0.0, "fin_rel": 1.0, "texto": "Sub original"}],
                    job_dir=job_dir,
                    on_log=lambda _: None,
                )

            self.assertEqual(len(comandos_ejecutados), 2)
            cmd_p1, cmd_p2 = comandos_ejecutados
            # Paso 1: render limpio sin subtitles hacia raw_clip_3.mp4
            self.assertTrue(cmd_p1[-1].endswith("raw_clip_3.mp4"))
            self.assertNotIn("subtitles=", " ".join(cmd_p1))
            # Alineación recibió el raw_clip_3.mp4 ya renderizado
            self.assertTrue(estado_raw_durante_alineacion.get("existe"))
            self.assertEqual(estado_raw_durante_alineacion.get("nombre"), "raw_clip_3.mp4")
            # Paso 2: lee raw_clip_3.mp4, quema .ass, copia audio (-c:a copy) hacia archivo final
            self.assertEqual(cmd_p2[cmd_p2.index("-i") + 1], str((job_dir / "raw_clip_3.mp4").resolve()))
            self.assertIn("subtitles=", cmd_p2[cmd_p2.index("-vf") + 1])
            self.assertEqual(cmd_p2[cmd_p2.index("-c:a") + 1], "copy")
            self.assertEqual(Path(cmd_p2[-1]).resolve(), Path(salida).resolve())
            self.assertTrue(Path(salida).exists())
            # El archivo ASS contiene los márgenes ópticos Safe Zone 80,170 y el texto alineado
            ass_texto = (job_dir / "subs_3.ass").read_text(encoding="utf-8")
            self.assertIn(",80,170,550,1", ass_texto)
            self.assertIn("SUB ALINEADO", ass_texto)
            # Cleanup del raw_clip_3.mp4 en finally
            self.assertFalse((job_dir / "raw_clip_3.mp4").exists())

    def test_procesar_clip_ffmpeg_un_paso_sin_subtitulos(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_dir = Path(tmp)
            carpeta_salida = tmp_dir / "salida"
            job_dir = tmp_dir / "job"
            job_dir.mkdir(parents=True)
            fuente = tmp_dir / "temp_source.mp4"
            fuente.write_bytes(b"VIDEO")
            wm = tmp_dir / "watermark.png"
            wm.write_bytes(b"PNG")
            comandos = []

            def fake_captura(cmd, duracion_objetivo=None, on_progreso=None):
                comandos.append(list(cmd))
                Path(cmd[-1]).write_bytes(b"MP4DATA")

            with patch.object(pvc, "CARPETA_SALIDA", carpeta_salida), patch.object(
                pvc, "RUTA_MARCA_AGUA", wm
            ), patch.object(pvc, "obtener_dimensiones_video", return_value=(1920, 1080)), patch.object(
                pvc, "detectar_encoder_hardware", return_value="libx264"
            ), patch.object(
                pvc, "_alinear_subtitulos_con_clip_renderizado"
            ) as mock_alinear, patch.object(
                pvc, "_ejecutar_comando_con_captura", side_effect=fake_captura
            ):
                salida = pvc.procesar_clip_ffmpeg(
                    str(fuente),
                    "00:00:10",
                    "00:00:15",
                    id_clip=1,
                    job_id="job_nosub",
                    subtitulos=[],
                    job_dir=job_dir,
                    on_log=lambda _: None,
                )

            mock_alinear.assert_not_called()
            self.assertEqual(len(comandos), 1)
            self.assertEqual(Path(comandos[0][-1]).resolve(), Path(salida).resolve())
            self.assertFalse((job_dir / "raw_clip_1.mp4").exists())
            self.assertFalse((job_dir / "subs_1.ass").exists())

    def test_smoke_ffmpeg_quemar_ass_paso2_real(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_dir = Path(tmp)
            raw_mp4 = _crear_mp4_sintetico(tmp_dir, "raw_clip_1.mp4")
            subs = [pvc.SegmentoSubtitulo(inicio_rel=0.05, fin_rel=0.55, texto="PRUEBA MILIMETRICA")]
            ruta_ass = pvc.generar_archivo_ass(subs, tmp_dir / "subs_1.ass")
            _, fonts_dir = pvc._obtener_fuente_y_dir_subtitulos()

            # Smoke test 1: CPU libx264 real
            out_cpu = tmp_dir / "final_cpu.mp4"
            cmd_cpu = pvc._construir_comando_quemar_ass(
                ruta_video_raw=raw_mp4,
                archivo_salida=out_cpu,
                ruta_ass=ruta_ass,
                encoder="libx264",
                fonts_dir=fonts_dir,
            )
            pvc._ejecutar_comando_con_captura(cmd_cpu, duracion_objetivo=0.6)
            self.assertTrue(out_cpu.exists())
            self.assertGreater(out_cpu.stat().st_size, 1000)
            probe = subprocess.run(
                [
                    "ffprobe",
                    "-v",
                    "error",
                    "-show_entries",
                    "stream=codec_type",
                    "-of",
                    "default=noprint_wrappers=1:nokey=1",
                    str(out_cpu),
                ],
                check=True,
                capture_output=True,
                text=True,
            )
            self.assertIn("video", probe.stdout)
            self.assertIn("audio", probe.stdout)

            # Smoke test 2: VAAPI GPU real si el dispositivo está activo en esta máquina
            if pvc.detectar_encoder_hardware() == "h264_vaapi":
                out_vaapi = tmp_dir / "final_vaapi.mp4"
                cmd_vaapi = pvc._construir_comando_quemar_ass(
                    ruta_video_raw=raw_mp4,
                    archivo_salida=out_vaapi,
                    ruta_ass=ruta_ass,
                    encoder="h264_vaapi",
                    fonts_dir=fonts_dir,
                )
                pvc._ejecutar_comando_con_captura(cmd_vaapi, duracion_objetivo=0.6)
                self.assertTrue(out_vaapi.exists())
                self.assertGreater(out_vaapi.stat().st_size, 1000)


class TestTarea4OrquestacionParalela(unittest.TestCase):
    def test_orquestar_render_y_subida_paralelo_clips_activos_y_locks(self):
        with tempfile.TemporaryDirectory() as tmp:
            job_dir = Path(tmp) / "job_p"
            job_dir.mkdir(parents=True)
            clips = [
                {
                    "id": 1,
                    "titulo": "Clip 1",
                    "inicio": "00:00:10",
                    "fin": "00:00:25",
                    "descripcion": "d1",
                    "etiquetas": ["shorts"],
                    "subtitulos": [],
                },
                {
                    "id": 2,
                    "titulo": "Clip 2",
                    "inicio": "00:01:10",
                    "fin": "00:01:25",
                    "descripcion": "d2",
                    "etiquetas": ["shorts"],
                    "subtitulos": [],
                },
                {
                    "id": 3,
                    "titulo": "Clip 3",
                    "inicio": "00:02:10",
                    "fin": "00:02:25",
                    "descripcion": "d3",
                    "etiquetas": ["shorts"],
                    "subtitulos": [],
                },
            ]

            lock_track = threading.Lock()
            render_track = {"activos": 0, "max_activos": 0}
            yt_track = {"activos": 0, "max_activos": 0, "orden": []}
            publish_ats_vistos = []

            def fake_render(url_o_archivo, inicio, fin, id_clip, job_id=None, subtitulos=None, job_dir=None, on_telemetria=None, clip_indice=None, total_clips=None, on_log=None):
                with lock_track:
                    render_track["activos"] += 1
                    render_track["max_activos"] = max(render_track["max_activos"], render_track["activos"])
                try:
                    if on_telemetria:
                        on_telemetria(
                            {
                                "etapa": "render",
                                "porcentaje": 50.0,
                                "fps": "90.0",
                                "velocidad_x": "3.0x",
                                "encoder": "h264_vaapi",
                                "clip_id": str(id_clip),
                                "clip_indice": clip_indice,
                                "total_clips": total_clips,
                            }
                        )
                    time.sleep(0.08)
                    out = Path(job_dir) / f"out_{id_clip}.mp4"
                    out.write_bytes(b"MP4")
                    return str(out)
                finally:
                    with lock_track:
                        render_track["activos"] -= 1

            def fake_subir(**kwargs):
                with lock_track:
                    yt_track["activos"] += 1
                    yt_track["max_activos"] = max(yt_track["max_activos"], yt_track["activos"])
                try:
                    publish_ats_vistos.append(kwargs.get("publish_at"))
                    yt_track["orden"].append(kwargs["clip_id"])
                    time.sleep(0.02)
                    cid = kwargs["clip_id"]
                    return {
                        "youtube_id": f"yt_{cid}",
                        "url": f"https://youtu.be/yt_{cid}",
                        "publish_at": kwargs.get("publish_at"),
                    }
                finally:
                    with lock_track:
                        yt_track["activos"] -= 1

            tele_externa = []
            with patch.object(pvc, "BASE_DIR", Path(tmp)), patch.object(
                pvc, "descargar_video_fuente", side_effect=RuntimeError("skip")
            ), patch.object(
                pvc, "autenticar_youtube", return_value=MagicMock()
            ), patch.object(pvc, "procesar_clip_ffmpeg", side_effect=fake_render), patch.object(
                pvc,
                "verificar_cuota_diaria",
                side_effect=[
                    {"permitido": True, "subidas_24h": 0, "limite": 6},
                    {"permitido": True, "subidas_24h": 1, "limite": 6},
                    {"permitido": False, "subidas_24h": 6, "limite": 6},
                ],
            ), patch.object(pvc, "subir_short", side_effect=fake_subir):
                estados = list(
                    pvc._orquestar_render_y_subida(
                        url="https://kick.com/u/videos/1",
                        clips=clips,
                        duracion_total=600.0,
                        subir_youtube=True,
                        job_id="job_par",
                        job_dir=job_dir,
                        publish_at_inicio="2026-12-01 10:00",
                        intervalo_horas=2,
                        on_log=lambda _: None,
                        on_telemetria=lambda d: tele_externa.append(d),
                    )
                )

            # Renderizado paralelo real con max_workers=2
            self.assertEqual(render_track["max_activos"], 2)
            # Subida YouTube estrictamente serializada bajo yt_lock
            self.assertEqual(yt_track["max_activos"], 1)
            # Solo 2 subidas antes del límite diario; 3ro marcado por cuota
            self.assertEqual(len(yt_track["orden"]), 2)
            self.assertEqual(publish_ats_vistos, ["2026-12-01T15:00:00Z", "2026-12-01T17:00:00Z"])
            self.assertEqual(sum(1 for c in clips if "Pendiente por cuota diaria" in c.get("youtube_status", "")), 1)
            self.assertTrue(all(c.get("render_status") == "OK" for c in clips))
            # Telemetría reporta clips_activos paralelos
            self.assertTrue(any(len(e.get("telemetria", {}).get("clips_activos", [])) >= 2 for e in estados))
            # Persistencia thread-safe en job_dir/clips.json y raíz
            guardado = json.loads((job_dir / "clips.json").read_text(encoding="utf-8"))
            self.assertEqual(len(guardado), 3)


class TestTarea5CancelacionYLimpieza(unittest.TestCase):
    def test_ejecutar_paso_con_telemetria_timeout_polling_y_keyboard_interrupt(self):
        # 1. Verifica que timeout=0.5s permite continuar iterando tras queue.Empty hasta completar
        def paso_lento(on_telemetria=None):
            time.sleep(0.65)
            if on_telemetria:
                on_telemetria({"porcentaje": 100.0})
            return "LISTO"

        gen = pvc._ejecutar_paso_con_telemetria(
            paso_lento,
            construir_estado=lambda t: {"tele": t},
        )
        estados = []
        try:
            while True:
                estados.append(next(gen))
        except StopIteration as stop:
            retorno = stop.value

        self.assertEqual(retorno, "LISTO")
        self.assertEqual(estados, [{"tele": {"porcentaje": 100.0}}])

        # 2. Verifica propagación inmediata de KeyboardInterrupt
        def paso_interrumpido():
            raise KeyboardInterrupt()

        gen_int = pvc._ejecutar_paso_con_telemetria(
            paso_interrumpido,
            construir_estado=lambda t: t,
        )
        with self.assertRaises(KeyboardInterrupt):
            next(gen_int)

    def test_limpiar_jobs_antiguos_retencion_y_exclusion_job_actual(self):
        with tempfile.TemporaryDirectory() as tmp:
            jobs_root = Path(tmp) / "jobs"
            jobs_root.mkdir()
            ahora = time.time()

            old_dir = jobs_root / "job_viejo"
            old_dir.mkdir()
            (old_dir / "archivo.txt").write_text("old", encoding="utf-8")
            os.utime(old_dir, (ahora - 8 * 86400, ahora - 8 * 86400))

            recent_dir = jobs_root / "job_reciente"
            recent_dir.mkdir()
            os.utime(recent_dir, (ahora - 2 * 86400, ahora - 2 * 86400))

            current_dir = jobs_root / "job_actual"
            current_dir.mkdir()
            os.utime(current_dir, (ahora - 15 * 86400, ahora - 15 * 86400))

            stray_file = jobs_root / "nota.txt"
            stray_file.write_text("conservar", encoding="utf-8")
            os.utime(stray_file, (ahora - 15 * 86400, ahora - 15 * 86400))

            target_ext = Path(tmp) / "externo"
            target_ext.mkdir()
            symlink_dir = jobs_root / "enlace"
            symlink_dir.symlink_to(target_ext)

            with patch.object(pvc, "CARPETA_JOBS", jobs_root):
                eliminados = pvc._limpiar_jobs_antiguos(dias_retencion=7, job_dir_actual=current_dir)

            self.assertEqual(eliminados, 1)
            self.assertFalse(old_dir.exists())
            self.assertTrue(recent_dir.exists())
            self.assertTrue(current_dir.exists())
            self.assertTrue(stray_file.exists())
            self.assertTrue(symlink_dir.is_symlink())
            self.assertTrue(target_ext.exists())

    def test_ejecutar_pipeline_completo_invoca_limpiar_jobs_antiguos(self):
        with tempfile.TemporaryDirectory() as tmp:
            job_dir = Path(tmp) / "job_actual"
            job_dir.mkdir()
            ctx_mock = SimpleNamespace(job_id="job_actual", job_dir=job_dir)

            with patch.dict(pvc.os.environ, {"GEMINI_API_KEY": "k"}), patch.object(
                pvc, "crear_contexto_job", return_value=ctx_mock
            ), patch.object(pvc, "_limpiar_jobs_antiguos", return_value=2) as mock_limpiar, patch.object(
                pvc, "obtener_duracion_media", return_value=60.0
            ), patch.object(
                pvc, "extraer_audio", return_value=str(job_dir / "temp_audio.mp3")
            ), patch.object(
                pvc,
                "analizar_con_gemini",
                return_value=[{"id": 1, "titulo": "Clip", "inicio": "00:00:10", "fin": "00:00:25"}],
            ):
                list(
                    pvc.ejecutar_pipeline_completo(
                        "https://kick.com/u/videos/1",
                        solo_analisis=True,
                        on_log=lambda _: None,
                    )
                )

            mock_limpiar.assert_called_once_with(dias_retencion=7, job_dir_actual=job_dir)


class TestTarea6InterfazCommandCenterYEstadisticas(unittest.TestCase):
    def setUp(self):
        self._demos_creados = []

    def tearDown(self):
        _cerrar_loops_gradio(*self._demos_creados)
        self._demos_creados.clear()

    @classmethod
    def tearDownClass(cls):
        _cerrar_loops_gradio()

    def test_calcular_estadisticas_sistema_y_panel_html_offline(self):
        from datetime import datetime, timedelta

        ahora = datetime.now().astimezone()
        hace_2h = (ahora - timedelta(hours=2)).isoformat()
        hace_3d = (ahora - timedelta(days=3)).isoformat()

        with tempfile.TemporaryDirectory() as tmp:
            tmp_dir = Path(tmp)
            carpeta_jobs = tmp_dir / "jobs"
            carpeta_jobs.mkdir()
            ruta_clips_raiz = tmp_dir / "clips.json"
            ruta_subidas = tmp_dir / "subidas_shorts.json"

            job1_clips = [
                {
                    "id": 1,
                    "titulo": "Clip Óptimo Shorts",
                    "inicio": "00:01:00",
                    "fin": "00:01:30",
                    "duracion_segundos": 30,
                    "render_status": "OK",
                    "archivo_local": "clip_1.mp4",
                    "youtube_id": "yt_1",
                },
                {
                    "id": 2,
                    "titulo": "Clip Corto Sin Campo Duracion",
                    "inicio": "00:02:10",
                    "fin": "00:02:25",
                },
            ]
            job2_clips = [
                {
                    "id": 1,
                    "titulo": "Arco TikTok",
                    "inicio": "00:05:00",
                    "fin": "00:06:00",
                    "duracion_segundos": 60,
                    "render_status": "OK",
                },
                {
                    "id": 2,
                    "titulo": "Clip Largo",
                    "inicio": "00:10:00",
                    "fin": "00:11:30",
                    "duracion_segundos": 90,
                },
            ]

            job1_dir = carpeta_jobs / "20260401_120000_kick_com_westcol_abc"
            job1_dir.mkdir()
            (job1_dir / "clips.json").write_text(json.dumps(job1_clips), encoding="utf-8")

            job2_dir = carpeta_jobs / "20260402_180000_twitch_tv_elxokas_xyz"
            job2_dir.mkdir()
            (job2_dir / "clips.json").write_text(json.dumps(job2_clips), encoding="utf-8")

            # Carpeta sin clips.json debe contarse en total_carpetas_jobs pero no en total_jobs
            (carpeta_jobs / "20260403_000000_youtube_com_sin_clips").mkdir()

            # Mirror raíz duplicado de job1 NO debe inflar el conteo total
            ruta_clips_raiz.write_text(json.dumps(job1_clips), encoding="utf-8")

            subidas_mock = [
                {
                    "youtube_id": "yt_1",
                    "url": "https://youtube.com/shorts/yt_1",
                    "fecha_subida": hace_2h,
                    "publish_at": "2026-11-15T18:00:00Z",
                },
                {
                    "youtube_id": "yt_2",
                    "url": "https://youtube.com/shorts/yt_2",
                    "fecha_subida": hace_2h,
                },
                {
                    "youtube_id": "yt_old",
                    "url": "https://youtube.com/shorts/yt_old",
                    "fecha_subida": hace_3d,
                },
            ]
            ruta_subidas.write_text(json.dumps(subidas_mock), encoding="utf-8")

            with patch.object(app_interfaz, "CARPETA_JOBS", carpeta_jobs), patch.object(
                app_interfaz, "ARCHIVO_CLIPS", ruta_clips_raiz
            ), patch.object(app_interfaz, "ARCHIVO_SUBIDAS", ruta_subidas):
                stats = app_interfaz.calcular_estadisticas_sistema()

            self.assertEqual(stats["total_jobs"], 2)
            self.assertEqual(stats["total_carpetas_jobs"], 3)
            self.assertEqual(stats["total_clips"], 4)
            self.assertEqual(stats["total_subidos_youtube"], 3)
            self.assertEqual(stats["total_programados_youtube"], 1)
            self.assertEqual(stats["duracion_promedio_s"], 48.8)
            self.assertEqual(stats["clips_optimos_shorts"], 1)
            self.assertEqual(stats["cuota_usada_24h"], 2)
            self.assertEqual(stats["cuota_limite_24h"], 6)
            self.assertEqual(stats["cupo_disponible_24h"], 4)
            self.assertEqual(
                stats["distribucion_duracion"],
                {
                    "cortos_lt_22": 1,
                    "shorts_optimo_22_45": 1,
                    "arcos_tiktok_46_75": 1,
                    "largos_gt_75": 1,
                },
            )
            origenes = [item["origen"] for item in stats["actividad_reciente"]]
            self.assertIn("Kick · westcol", origenes)
            self.assertIn("Twitch · elxokas", origenes)

            stats_xss = dict(stats)
            stats_xss["actividad_reciente"] = [
                {
                    "job_id": "xss_job",
                    "fecha": "<script>alert(1)</script>",
                    "origen": '"><img src=x onerror=alert(1)>',
                    "clips": 2,
                    "renderizados": 2,
                    "subidos": 1,
                    "duracion_promedio_s": 30.0,
                }
            ]
            html_stats = app_interfaz.construir_panel_estadisticas_html(stats_xss)
            self.assertNotIn("<script>alert(1)</script>", html_stats)
            self.assertNotIn("<img src=x", html_stats)
            self.assertIn("&lt;script&gt;alert(1)&lt;/script&gt;", html_stats)
            self.assertIn("&quot;&gt;&lt;img src=x onerror=alert(1)&gt;", html_stats)
            self.assertIn("48.8s", html_stats)
            self.assertIn("Shorts Óptimo (22–45s)", html_stats)

    def test_construir_panel_telemetria_html_stepper_workers_y_xss(self):
        html_idle = app_interfaz.construir_panel_telemetria_html(None)
        for paso in ("1. Red &amp; Audio", "2. IA Paralela", "3. Render VAAPI", "4. YouTube Shorts"):
            self.assertIn(paso, html_idle)

        estado_gemini = {
            "fase": "gemini",
            "progreso": 0.40,
            "mensaje": "Curando bloques paralelos",
            "modelo": "gemini-2.5-flash",
            "telemetria": {
                "etapa": "gemini",
                "porcentaje": 33.3,
                "bloques_completados": 1,
                "total_bloques": 3,
                "bloques_activos": ["Bloque 2/3", "Bloque 3/3"],
                "clips_activos": [],
                "velocidad_red": "--",
                "fps": "--",
                "velocidad_render": "--",
                "eta": "00:42",
                "encoder": "Gemini File API",
                "modelo_ia": "gemini-2.5-flash",
                "detalle": "Procesando bloques concurrentes",
            },
        }
        html_gemini = app_interfaz.construir_panel_telemetria_html(estado_gemini)
        self.assertIn("Bloques: 1/3", html_gemini)
        self.assertIn("Bloque 2/3", html_gemini)
        self.assertIn("Bloque 3/3", html_gemini)
        self.assertIn("IA Paralela", html_gemini)
        self.assertIn("33.3%", html_gemini)

        estado_render = {
            "fase": "render",
            "progreso": 0.72,
            "mensaje": "Renderizando clips concurrentes",
            "telemetria": {
                "etapa": "render",
                "porcentaje": 62.5,
                "bloques_completados": 3,
                "total_bloques": 3,
                "bloques_activos": [],
                "clips_activos": [
                    {"clip_id": 1, "porcentaje": 62.5, "fps": "95.0", "velocidad_render": "3.2x"},
                    {"clip_id": 2, "porcentaje": 40.0, "fps": "88.0", "velocidad_x": "2.9x"},
                ],
                "velocidad_red": "--",
                "fps": "95.0",
                "velocidad_render": "3.2x",
                "eta": "00:14",
                "encoder": "h264_vaapi",
                "clip_indice": 1,
                "total_clips": 2,
                "clip_id": 1,
                "detalle": "Quemando subtítulos ASS",
            },
        }
        html_render = app_interfaz.construir_panel_telemetria_html(estado_render)
        self.assertIn("Clip #1 (62% • 3.2x • 95.0 FPS)", html_render)
        self.assertIn("Clip #2 (40% • 2.9x • 88.0 FPS)", html_render)
        self.assertIn("AMD VAAPI", html_render)
        self.assertIn("95.0 FPS", html_render)
        self.assertIn("3.2x", html_render)
        self.assertIn("00:14", html_render)

        estado_xss = {
            "fase": "render",
            "progreso": 0.5,
            "mensaje": '<script>alert("msg")</script>',
            "telemetria": {
                "etapa": "render",
                "porcentaje": 50.0,
                "bloques_completados": 1,
                "total_bloques": 2,
                "bloques_activos": ['<img src=x onerror=alert("b")>'],
                "clips_activos": [{"clip_id": '<script>c</script>', "estado": '"><svg onload=alert(1)>'}],
                "velocidad_red": '<script>net</script>',
                "fps": '<script>fps</script>',
                "velocidad_render": '<script>vel</script>',
                "eta": '"><script>eta</script>',
                "encoder": '<script>enc</script>',
                "modelo_ia": '<script>mod</script>',
                "detalle": '<img src=x onerror=alert("det")>',
            },
        }
        html_xss = app_interfaz.construir_panel_telemetria_html(estado_xss)
        for peligro in ("<script>", "<img src=x", "<svg onload"):
            self.assertNotIn(peligro, html_xss)
        self.assertIn("&lt;script&gt;alert(&quot;msg&quot;)&lt;/script&gt;", html_xss)
        self.assertIn("&lt;img src=x onerror=alert(&quot;det&quot;)&gt;", html_xss)

    def test_integracion_telemetria_v40_a_gradio_sin_keyerror_y_cierre_limpio(self):
        estados_v40 = [
            {
                "fase": "audio",
                "progreso": 0.12,
                "mensaje": "Descargando audio 12 kHz",
                "telemetria": {
                    "etapa": "descarga",
                    "bloques_completados": 0,
                    "total_bloques": 0,
                    "bloques_activos": [],
                    "clips_activos": [],
                    "porcentaje": 45.0,
                    "velocidad_red": "14.2MiB/s",
                    "fps": "--",
                    "velocidad_render": "--",
                    "velocidad_x": "--",
                    "eta": "00:12",
                    "encoder": "yt-dlp",
                },
            },
            {
                "fase": "gemini",
                "progreso": 0.35,
                "mensaje": "IA Paralela v4.0",
                "telemetria": {
                    "etapa": "gemini",
                    "bloques_completados": 2,
                    "total_bloques": 3,
                    "bloques_activos": ["Bloque 3/3"],
                    "clips_activos": [],
                    "porcentaje": 66.7,
                    "velocidad_red": "--",
                    "fps": "--",
                    "velocidad_render": "--",
                    "velocidad_x": "--",
                    "eta": "00:25",
                    "encoder": "Gemini File API",
                    "modelo_ia": "gemini-2.5-flash",
                },
            },
            {
                "fase": "render",
                "progreso": 0.78,
                "mensaje": "Render concurrente max_workers=2",
                "telemetria": {
                    "etapa": "render",
                    "bloques_completados": 3,
                    "total_bloques": 3,
                    "bloques_activos": [],
                    "clips_activos": [
                        {"clip_id": 1, "porcentaje": 80.0, "fps": "104.2", "velocidad_render": "3.5x"}
                    ],
                    "porcentaje": 80.0,
                    "velocidad_red": "--",
                    "fps": "104.2",
                    "velocidad_render": "3.5x",
                    "velocidad_x": "3.5x",
                    "eta": "00:09",
                    "encoder": "h264_vaapi",
                    "clip_id": 1,
                    "clip_indice": 1,
                    "total_clips": 2,
                },
            },
            {
                "fase": "completado",
                "progreso": 1.0,
                "mensaje": "Pipeline v4.0 finalizado",
                "clips": [],
                "ultimo_video": None,
                "telemetria": {
                    "etapa": "completado",
                    "bloques_completados": 3,
                    "total_bloques": 3,
                    "bloques_activos": [],
                    "clips_activos": [],
                    "porcentaje": 100.0,
                    "velocidad_red": "--",
                    "fps": "--",
                    "velocidad_render": "--",
                    "velocidad_x": "--",
                    "eta": "00:00",
                    "encoder": "h264_vaapi",
                    "detalle": "Completado",
                },
            },
        ]

        with patch.object(app_interfaz, "ejecutar_pipeline_completo", return_value=iter(estados_v40)), patch.object(
            app_interfaz, "obtener_datos_galeria", return_value=([], None, "<div>ok</div>", [])
        ), patch.object(app_interfaz, "obtener_tabla_historial", return_value=([], "<div>hist</div>")):
            salidas = list(
                app_interfaz.ejecutar_pipeline_gradio(
                    url="https://kick.com/westcol/videos/999",
                    modelo_preferido="Auto (Recomendado)",
                    subir_auto_yt=False,
                    solo_analisis=False,
                    gemini_key="",
                    progress=None,
                )
            )

        self.assertEqual(len(salidas), 4)
        for fila in salidas:
            self.assertEqual(len(fila), 9)
        self.assertIn("14.2MiB/s", salidas[0][1])
        self.assertIn("Bloques: 2/3", salidas[1][1])
        self.assertIn("Bloque 3/3", salidas[1][1])
        self.assertIn("Clip #1 (80% • 3.5x • 104.2 FPS)", salidas[2][1])
        self.assertIn("00:09", salidas[2][1])
        self.assertIn("AMD VAAPI", salidas[2][1])

        skip_marker = gr.skip()
        self.assertEqual(salidas[0][6], "<div>ok</div>")
        self.assertEqual(salidas[0][8], "<div>hist</div>")
        for idx_tick in (1, 2):
            for idx_col in range(3, 9):
                self.assertEqual(salidas[idx_tick][idx_col], skip_marker)
        self.assertEqual(salidas[3][6], "<div>ok</div>")
        self.assertEqual(salidas[3][8], "<div>hist</div>")

        demo = app_interfaz.construir_interfaz()
        self._demos_creados.append(demo)
        self.assertIsInstance(demo, gr.Blocks)
        tabs = [
            comp.label
            for comp in demo.blocks.values()
            if isinstance(comp, gr.Tab)
        ]
        self.assertEqual(len(tabs), 4)
        self.assertIn("⚡ 1. Centro de Mando", tabs)
        self.assertIn("📊 4. Estadísticas & Rendimiento", tabs)


if __name__ == "__main__":
    unittest.main()
