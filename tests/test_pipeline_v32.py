#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Suite de pruebas unitarias e integración local para Kicksazos v3.2 (tipografía + telemetría)."""

import io
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import gradio as gr

ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

import app_interfaz  # noqa: E402
import pipeline_viral_clips as pvc  # noqa: E402


def _fake_popen(stdout_text: str = "", stderr_text: str = "", returncode: int = 0):
    return SimpleNamespace(
        stdout=io.StringIO(stdout_text),
        stderr=io.StringIO(stderr_text),
        poll=lambda: returncode,
        wait=lambda timeout=None: returncode,
        kill=lambda: None,
    )


class TestFase1TipografiaEmbebeYASS(unittest.TestCase):
    def test_obtener_fuente_y_dir_embebida_real(self):
        fuente, fonts_dir = pvc._obtener_fuente_y_dir_subtitulos()
        self.assertEqual(fonts_dir, str(pvc.CARPETA_FUENTES))
        self.assertTrue((pvc.CARPETA_FUENTES / "Montserrat-ExtraBold.ttf").is_file())
        self.assertEqual(fuente, "Montserrat ExtraBold")

    def test_obtener_fuente_fallback_y_inferencia_nombre(self):
        self.assertEqual(
            pvc._inferir_nombre_fuente_por_archivo(Path("/tmp/Montserrat-ExtraBold.ttf")),
            "Montserrat ExtraBold",
        )
        self.assertEqual(
            pvc._inferir_nombre_fuente_por_archivo(Path("/tmp/Kicksazos-Bold.ttf")),
            "Kicksazos Bold",
        )
        with tempfile.TemporaryDirectory() as tmp:
            vacia = Path(tmp) / "fonts_vacia"
            vacia.mkdir()
            with patch.object(pvc, "CARPETA_FUENTES", vacia), patch.object(
                pvc, "_detectar_fuente_subtitulos", return_value="DejaVu Sans"
            ):
                fuente, fonts_dir = pvc._obtener_fuente_y_dir_subtitulos()
            self.assertEqual(fuente, "DejaVu Sans")
            self.assertIsNone(fonts_dir)

    def test_limpiar_texto_ass_mayusculas_y_llaves(self):
        limpio = pvc._limpiar_texto_ass("  ¡Qué {locura}\nparce! 🔥😂  ")
        self.assertEqual(limpio, r"¡QUÉ (LOCURA)\NPARCE!")

    def test_construir_comando_render_inyecta_fontsdir_y_progress(self):
        cmd = pvc._construir_comando_render(
            entradas_media=["in.mp4"],
            es_remoto=False,
            inicio="00:00:00",
            duracion_str="10.000",
            archivo_salida=Path("/tmp/out.mp4"),
            y_watermark="(H-h)/2",
            encoder="libx264",
            ruta_ass="/tmp/dir's/subs_1.ass",
            fonts_dir="/tmp/assets/fonts",
        )
        self.assertIn("-progress", cmd)
        self.assertEqual(cmd[cmd.index("-progress") + 1], "pipe:1")
        self.assertIn("-nostats", cmd)
        vf = cmd[cmd.index("-filter_complex") + 1]
        self.assertIn("subtitles='", vf)
        self.assertIn(":fontsdir='/tmp/assets/fonts'", vf)

        cmd_sin_dir = pvc._construir_comando_render(
            entradas_media=["in.mp4"],
            es_remoto=False,
            inicio="00:00:00",
            duracion_str="10.000",
            archivo_salida=Path("/tmp/out.mp4"),
            y_watermark="(H-h)/2",
            encoder="libx264",
            ruta_ass="/tmp/subs_1.ass",
            fonts_dir=None,
        )
        vf_sin_dir = cmd_sin_dir[cmd_sin_dir.index("-filter_complex") + 1]
        self.assertNotIn("fontsdir=", vf_sin_dir)

    def test_smoke_ffmpeg_libass_usa_montserrat_extrabold(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_dir = Path(tmp)
            ruta_ass = pvc.generar_archivo_ass(
                [pvc.SegmentoSubtitulo(inicio_rel=0.0, fin_rel=1.0, texto="Prueba tipografía viral")],
                tmp_dir / "subs_smoke.ass",
            )
            ass_text = Path(ruta_ass).read_text(encoding="utf-8")
            self.assertIn("WrapStyle: 2", ass_text)
            self.assertIn("PRUEBA TIPOGRAFÍA VIRAL", ass_text)

            _, fonts_dir = pvc._obtener_fuente_y_dir_subtitulos()
            self.assertIsNotNone(fonts_dir)
            vf = (
                f"subtitles='{pvc._escapar_ruta_ffmpeg_filtro(ruta_ass)}'"
                f":fontsdir='{pvc._escapar_ruta_ffmpeg_filtro(fonts_dir)}'"
            )
            out_mp4 = tmp_dir / "burn.mp4"
            res = subprocess.run(
                [
                    "ffmpeg",
                    "-y",
                    "-v",
                    "verbose",
                    "-f",
                    "lavfi",
                    "-i",
                    "color=c=black:s=720x1280:d=1:r=24",
                    "-vf",
                    vf,
                    "-c:v",
                    "libx264",
                    "-preset",
                    "ultrafast",
                    str(out_mp4),
                ],
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(res.returncode, 0, msg=res.stderr)
            self.assertTrue(out_mp4.is_file() and out_mp4.stat().st_size > 1024)
            self.assertIn("Montserrat-ExtraBold", res.stderr)


class TestFase2TelemetriaDescargaYFFmpeg(unittest.TestCase):
    def test_parsear_linea_progreso_ytdlp_y_aria2(self):
        yt = pvc._parsear_linea_progreso_descarga(
            "[download]  42.5% of ~ 120.50MiB at  14.82MiB/s ETA 00:05 (frag 12/40)"
        )
        self.assertIsNotNone(yt)
        self.assertAlmostEqual(yt["porcentaje"], 42.5)
        self.assertEqual(yt["tamano_total"], "120.50MiB")
        self.assertEqual(yt["velocidad_red"], "14.82MiB/s")
        self.assertEqual(yt["eta"], "00:05")
        self.assertEqual(yt["frag_cur"], 12)
        self.assertEqual(yt["frag_tot"], 40)

        ar = pvc._parsear_linea_progreso_descarga(
            "[#a1b2c3 18MiB/40MiB(45%) CN:16 DL:12.4MiB ETA:02s]"
        )
        self.assertIsNotNone(ar)
        self.assertEqual(ar["porcentaje"], 45.0)
        self.assertEqual(ar["tamano_total"], "40MiB")
        self.assertEqual(ar["velocidad_red"], "12.4MiB/s")
        self.assertEqual(ar["eta"], "02s")

    def test_extraer_audio_emite_telemetria_throttle_y_100(self):
        with tempfile.TemporaryDirectory() as tmp:
            job_dir = Path(tmp)
            stdout_lines = "\n".join(
                [
                    "[download]  10.0% of 40.00MiB at 10.00MiB/s ETA 00:04 (frag 1/10)",
                    "[download]  20.0% of 40.00MiB at 11.00MiB/s ETA 00:03 (frag 2/10)",
                    "[download]  50.0% of 40.00MiB at 14.00MiB/s ETA 00:02 (frag 5/10)",
                    "[download]  60.0% of 40.00MiB at 14.50MiB/s ETA 00:01 (frag 6/10)",
                    "[download] 100.0% of 40.00MiB at 16.00MiB/s ETA 00:00 (frag 10/10)",
                ]
            ) + "\n"

            def fake_popen(cmd, **kwargs):
                (job_dir / "temp_audio.mp3").write_bytes(b"ID3" + b"\x00" * 15000)
                return _fake_popen(stdout_lines)

            eventos = []
            ticks = iter([10.0, 10.50, 10.55, 10.95, 11.00, 11.05, 11.10])
            fake_time = SimpleNamespace(monotonic=lambda: next(ticks, 11.10), sleep=lambda _: None)
            with patch.object(pvc.shutil, "which", return_value=None), patch.object(
                pvc.subprocess, "Popen", side_effect=fake_popen
            ), patch.object(pvc, "time", fake_time):
                pvc.extraer_audio(
                    "https://www.youtube.com/watch?v=test",
                    job_dir=job_dir,
                    on_telemetria=eventos.append,
                    on_log=lambda _: None,
                )

            pcts = [e["porcentaje"] for e in eventos]
            self.assertEqual(pcts[0], 0.0)
            self.assertIn(10.0, pcts)
            self.assertNotIn(20.0, pcts)
            self.assertIn(50.0, pcts)
            self.assertNotIn(60.0, pcts)
            self.assertEqual(pcts[-1], 100.0)
            self.assertEqual(eventos[-2]["etapa"], "descarga")
            self.assertEqual(eventos[-2]["velocidad_red"], "16.00MiB/s")
            self.assertEqual(eventos[-2]["detalle"], "Fragmentos 10/10")

    def test_ejecutar_comando_con_captura_parsea_ffmpeg_progress_y_eta(self):
        progress_txt = (
            "frame=150\nfps=60.0\nout_time_us=5000000\nspeed=2.00x\ntotal_size=524288\nprogress=continue\n"
            "frame=300\nfps=60.0\nout_time_us=10000000\nspeed=2.00x\ntotal_size=1048576\nprogress=end\n"
        )
        eventos = []
        ticks = iter([100.0, 100.5])
        fake_time = SimpleNamespace(monotonic=lambda: next(ticks, 101.0), sleep=lambda _: None)
        with patch.object(
            pvc.subprocess, "Popen", return_value=_fake_popen(progress_txt, "")
        ), patch.object(pvc, "time", fake_time):
            pvc._ejecutar_comando_con_captura(
                ["ffmpeg", "-progress", "pipe:1", "-nostats", "-i", "a.mp4", "b.mp4"],
                duracion_objetivo=10.0,
                on_progreso=eventos.append,
            )

        self.assertEqual(len(eventos), 2)
        self.assertEqual(eventos[0]["porcentaje"], 50.0)
        self.assertEqual(eventos[0]["fps_str"], "60.0")
        self.assertEqual(eventos[0]["speed_str"], "2.00x")
        self.assertEqual(eventos[0]["eta_str"], "00:02")
        self.assertEqual(eventos[1]["porcentaje"], 100.0)
        self.assertEqual(eventos[1]["eta_str"], "00:00")
        self.assertEqual(eventos[1]["size_str"], "1.00MiB")

    def test_procesar_clip_ffmpeg_telemetria_y_fallback_cpu(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_dir = Path(tmp)
            fuente = tmp_dir / "src.mp4"
            fuente.write_bytes(b"\x00" * 2048)
            watermark = tmp_dir / "wm.png"
            watermark.write_bytes(b"PNG" + b"\x00" * 128)
            salida_dir = tmp_dir / "clips_finales"

            encoders_llamados = []

            def fake_captura(cmd, duracion_objetivo=None, on_progreso=None):
                cv = cmd[cmd.index("-c:v") + 1]
                encoders_llamados.append(cv)
                if cv == "h264_vaapi":
                    raise subprocess.CalledProcessError(1, cmd, output="vaapi error", stderr="vaapi error")
                if on_progreso is not None:
                    on_progreso(
                        {
                            "porcentaje": 75.0,
                            "frame": 225,
                            "fps_str": "88.5",
                            "speed_str": "2.95x",
                            "eta_str": "00:02",
                            "size_str": "1.20MiB",
                            "out_time_str": "00:00:07",
                        }
                    )
                ruta_salida = Path(cmd[-1])
                ruta_salida.write_bytes(b"MP4" + b"\x00" * 16000)
                return ""

            eventos = []
            with patch.object(pvc, "CARPETA_SALIDA", salida_dir), patch.object(
                pvc, "RUTA_MARCA_AGUA", watermark
            ), patch.object(pvc, "detectar_encoder_hardware", return_value="h264_vaapi"), patch.object(
                pvc, "obtener_dimensiones_video", return_value=(1920, 1080)
            ), patch.object(pvc, "obtener_duracion_media", return_value=20.0), patch.object(
                pvc, "_ejecutar_comando_con_captura", side_effect=fake_captura
            ):
                clip_out = pvc.procesar_clip_ffmpeg(
                    url_o_archivo=str(fuente),
                    inicio="00:00:00",
                    fin="00:00:10",
                    id_clip=7,
                    job_dir=tmp_dir,
                    on_telemetria=eventos.append,
                    clip_indice=2,
                    total_clips=4,
                    on_log=lambda _: None,
                )

            self.assertTrue(Path(clip_out).is_file())
            self.assertEqual(encoders_llamados, ["h264_vaapi", "libx264"])
            render_eventos = [e for e in eventos if e.get("etapa") == "render" and e.get("porcentaje") == 75.0]
            self.assertEqual(len(render_eventos), 1)
            ev = render_eventos[0]
            self.assertEqual(ev["encoder"], "libx264")
            self.assertEqual(ev["fps"], "88.5")
            self.assertEqual(ev["velocidad_x"], "2.95x")
            self.assertEqual(ev["clip_id"], "7")
            self.assertEqual(ev["clip_indice"], 2)
            self.assertEqual(ev["total_clips"], 4)

    def test_analizar_con_gemini_emite_telemetria_bloques(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_dir = Path(tmp)
            audio = tmp_dir / "temp_audio.mp3"
            audio.write_bytes(b"ID3" + b"\x00" * 5000)
            chunk1 = tmp_dir / "temp_audio_chunk_01.mp3"
            chunk2 = tmp_dir / "temp_audio_chunk_02.mp3"
            chunk1.write_bytes(b"ID3" + b"\x00" * 1000)
            chunk2.write_bytes(b"ID3" + b"\x00" * 1000)

            def fake_chunk(client, ruta_archivo, duracion_bloque, modelo_preferido, on_log, **kwargs):
                return [
                    {
                        "id": 1,
                        "titulo": "Momento viral",
                        "inicio": "00:00:10",
                        "fin": "00:00:30",
                        "subtitulos": [],
                    }
                ]

            eventos = []
            with patch.dict(os.environ, {"GEMINI_API_KEY": "fake-test-key"}), patch.object(
                pvc, "BASE_DIR", tmp_dir
            ), patch.object(
                pvc.genai, "Client", return_value=MagicMock()
            ), patch.object(
                pvc, "_segmentar_audio_en_chunks", return_value=[(str(chunk1), 0.0, 2700.0), (str(chunk2), 2610.0, 2700.0)]
            ), patch.object(pvc, "_analizar_archivo_audio_gemini", side_effect=fake_chunk):
                res = pvc.analizar_con_gemini(
                    audio,
                    duracion_total=5310.0,
                    modelo_preferido="gemini-2.5-flash",
                    job_dir=tmp_dir,
                    on_log=lambda _: None,
                    on_telemetria=eventos.append,
                )

            self.assertGreaterEqual(len(res), 1)
            bloques = [(e.get("bloque_actual"), e.get("total_bloques"), e.get("modelo_ia")) for e in eventos]
            self.assertIn((1, 2, "gemini-2.5-flash"), bloques)
            self.assertIn((2, 2, "gemini-2.5-flash"), bloques)


class TestFase2Y3OrquestadorCLIYGradio(unittest.TestCase):
    def test_ejecutar_pipeline_completo_streaming_telemetria_worker(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_root = Path(tmp)
            job_dir = tmp_root / "jobs" / "job_test"
            clips_dir = tmp_root / "clips_finales"
            job_dir.mkdir(parents=True)
            clips_dir.mkdir(parents=True)
            (job_dir / "video_fuente.mp4").write_bytes(b"MP4" + b"\x00" * 2048)
            ctx = pvc.JobContext(job_id="job_test", job_dir=job_dir)

            def fake_extraer_audio(url, job_dir=None, on_telemetria=None, on_log=None):
                if on_telemetria:
                    on_telemetria(
                        {
                            "etapa": "descarga",
                            "titulo_etapa": "Descargando Audio del Stream (16 Hilos)",
                            "porcentaje": 55.5,
                            "velocidad_red": "22.10MiB/s",
                            "tamano_total": "40.00MiB",
                            "eta": "00:02",
                            "detalle": "Fragmentos 5/9",
                        }
                    )
                ruta = Path(job_dir) / "temp_audio.mp3"
                ruta.write_bytes(b"ID3" + b"\x00" * 12000)
                return str(ruta)

            clips_mock = [
                {
                    "id": 1,
                    "titulo": "Clip Viral",
                    "inicio": "00:00:05",
                    "fin": "00:00:25",
                    "razon_viral": "Pico emocional",
                    "subtitulos": [{"inicio_rel": 0.0, "fin_rel": 1.5, "texto": "Hola gente"}],
                }
            ]

            def fake_render(fuente, ini, fin, id_c, **kwargs):
                on_t = kwargs.get("on_telemetria")
                if on_t:
                    on_t(
                        {
                            "etapa": "render",
                            "titulo_etapa": "Renderizando Clip #1 (1/1)",
                            "porcentaje": 60.0,
                            "fps": "75.0",
                            "velocidad_x": "2.50x",
                            "eta": "00:03",
                            "encoder": "h264_vaapi",
                            "clip_id": 1,
                            "clip_indice": 1,
                            "total_clips": 1,
                            "detalle": "Codificando",
                        }
                    )
                out = clips_dir / "job_test_clip_1.mp4"
                out.write_bytes(b"MP4" + b"\x00" * 16000)
                return str(out)

            with patch.dict(os.environ, {"GEMINI_API_KEY": "fake-test-key"}), patch.object(
                pvc, "BASE_DIR", tmp_root
            ), patch.object(pvc, "CARPETA_JOBS", tmp_root / "jobs"), patch.object(
                pvc, "CARPETA_SALIDA", clips_dir
            ), patch.object(
                pvc, "crear_contexto_job", return_value=ctx
            ), patch.object(pvc, "extraer_audio", side_effect=fake_extraer_audio), patch.object(
                pvc, "obtener_duracion_media", return_value=120.0
            ), patch.object(pvc, "analizar_con_gemini", return_value=clips_mock), patch.object(
                pvc, "descargar_video_fuente", return_value=str(job_dir / "video_fuente.mp4")
            ), patch.object(pvc, "procesar_clip_ffmpeg", side_effect=fake_render):
                estados = list(
                    pvc.ejecutar_pipeline_completo(
                        url="https://www.youtube.com/watch?v=test",
                        subir_youtube=False,
                        on_log=lambda _: None,
                    )
                )

            descarga_ticks = [e for e in estados if (e.get("telemetria") or {}).get("velocidad_red") == "22.10MiB/s"]
            render_ticks = [e for e in estados if (e.get("telemetria") or {}).get("encoder") == "h264_vaapi"]
            self.assertEqual(len(descarga_ticks), 1)
            self.assertEqual(descarga_ticks[0]["telemetria"]["porcentaje"], 55.5)
            self.assertEqual(len(render_ticks), 1)
            self.assertEqual(estados[-1]["fase"], "completado")
            self.assertEqual(estados[-1]["telemetria"]["porcentaje"], 100.0)

    def test_formatear_barra_cli_y_renderizador_tty_y_no_tty(self):
        linea_dl = pvc._formatear_barra_cli(
            {
                "fase": "audio",
                "progreso": 0.12,
                "telemetria": {
                    "etapa": "descarga",
                    "porcentaje": 50.0,
                    "velocidad_red": "14.82MiB/s",
                    "tamano_total": "42.10MiB",
                    "eta": "00:03",
                    "detalle": "Fragmentos 5/10",
                },
            },
            ancho_barra=10,
        )
        self.assertIn("█████░░░░░", linea_dl)
        self.assertIn("50.0%", linea_dl)
        self.assertIn("↓ 14.82MiB/s", linea_dl)
        self.assertIn("ETA 00:03", linea_dl)

        buf_tty = io.StringIO()
        cli_tty = pvc.RenderizadorProgresoCLI(stream=buf_tty, es_tty=True)
        cli_tty.actualizar({"fase": "render", "progreso": 0.5, "telemetria": {"etapa": "render", "porcentaje": 50.0, "encoder": "h264_vaapi", "fps": "90.0", "velocidad_x": "3.00x", "eta": "00:04"}})
        cli_tty.log("Mensaje limpio")
        cli_tty.actualizar({"fase": "render", "progreso": 0.8, "telemetria": {"etapa": "render", "porcentaje": 100.0, "encoder": "h264_vaapi", "fps": "90.0", "velocidad_x": "3.00x", "eta": "00:00"}})
        tty_out = buf_tty.getvalue()
        self.assertIn("\r\x1b[2K", tty_out)
        self.assertIn("Mensaje limpio\n", tty_out)
        self.assertIn("h264_vaapi", tty_out)

        buf_plain = io.StringIO()
        cli_plain = pvc.RenderizadorProgresoCLI(stream=buf_plain, es_tty=False)
        cli_plain.actualizar({"fase": "audio", "telemetria": {"etapa": "descarga", "porcentaje": 10.0, "velocidad_red": "5MiB/s"}})
        cli_plain.actualizar({"fase": "audio", "telemetria": {"etapa": "descarga", "porcentaje": 14.0, "velocidad_red": "5MiB/s"}})
        cli_plain.actualizar({"fase": "audio", "telemetria": {"etapa": "descarga", "porcentaje": 35.0, "velocidad_red": "8MiB/s"}})
        lineas_plain = [ln for ln in buf_plain.getvalue().splitlines() if ln.strip()]
        self.assertEqual(len(lineas_plain), 2)

    def test_panel_telemetria_gradio_estados_y_escape_xss(self):
        idle_html = app_interfaz.construir_panel_telemetria_html(None)
        self.assertIn("En espera", idle_html)

        xss_html = app_interfaz.construir_panel_telemetria_html(
            {
                "fase": "audio",
                "progreso": 0.15,
                "mensaje": "<script>alert(1)</script>",
                "telemetria": {
                    "etapa": "descarga",
                    "titulo_etapa": "<img src=x onerror=alert(1)>",
                    "porcentaje": 42.5,
                    "velocidad_red": "<script>99MiB/s</script>",
                    "tamano_total": "50MiB",
                    "eta": "00:04",
                    "detalle": "<b>det</b>",
                },
            }
        )
        self.assertNotIn("<script>", xss_html)
        self.assertIn("&lt;script&gt;", xss_html)
        self.assertIn("42.5%", xss_html)
        self.assertIn("50MiB", xss_html)

        render_html = app_interfaz.construir_panel_telemetria_html(
            {
                "fase": "render",
                "progreso": 0.72,
                "telemetria": {
                    "etapa": "render",
                    "titulo_etapa": "Renderizado 9:16",
                    "porcentaje": 80.0,
                    "fps": "95.2",
                    "velocidad_x": "3.17x",
                    "eta": "00:02",
                    "encoder": "h264_vaapi",
                    "clip_id": 3,
                    "clip_indice": 1,
                    "total_clips": 2,
                },
            }
        )
        self.assertIn("h264_vaapi", render_html)
        self.assertIn("3.17x • 95.2 FPS", render_html)
        self.assertIn("Clip #3 (1/2)", render_html)

    def test_ejecutar_pipeline_gradio_9_tuplas_y_skip_y_construccion_ui(self):
        estados_mock = [
            {
                "fase": "audio",
                "progreso": 0.05,
                "mensaje": "Iniciando audio",
                "telemetria": {"etapa": "descarga", "porcentaje": 10.0, "velocidad_red": "5MiB/s"},
            },
            {
                "fase": "render",
                "progreso": 0.70,
                "mensaje": "Render 50%",
                "telemetria": {"etapa": "render", "porcentaje": 50.0, "encoder": "h264_vaapi", "fps": "90.0", "velocidad_x": "3.0x", "eta": "00:04"},
            },
            {
                "fase": "completado",
                "progreso": 1.0,
                "mensaje": "Todo listo",
                "clips": [],
                "ultimo_video": None,
                "telemetria": {"etapa": "completado", "porcentaje": 100.0, "eta": "00:00", "detalle": "Fin"},
            },
        ]

        with patch.object(app_interfaz, "ejecutar_pipeline_completo", return_value=iter(estados_mock)), patch.object(
            app_interfaz, "obtener_datos_galeria", return_value=([], None, "<div></div>", [])
        ), patch.object(app_interfaz, "obtener_tabla_historial", return_value=([], "<div></div>")):
            salidas = list(
                app_interfaz.ejecutar_pipeline_gradio(
                    url="https://www.youtube.com/watch?v=test",
                    modelo_preferido="Auto (Recomendado)",
                    subir_auto_yt=False,
                    solo_analisis=False,
                    gemini_key="",
                    progress=None,
                )
            )

        self.assertEqual(len(salidas), 3)
        for fila in salidas:
            self.assertEqual(len(fila), 9)
        self.assertIn("5MiB/s", salidas[0][1])
        self.assertIn("h264_vaapi", salidas[1][1])
        # Tick intermedio usa gr.skip() en galería, player e historial para evitar re-escaneo 3x/s
        skip_marker = gr.skip()
        self.assertEqual(salidas[1][3], skip_marker)
        self.assertEqual(salidas[1][4], skip_marker)
        self.assertEqual(salidas[1][6], skip_marker)
        self.assertIn("100.0%", salidas[2][1])

        demo = app_interfaz.construir_interfaz()
        self.assertIsInstance(demo, gr.Blocks)


if __name__ == "__main__":
    unittest.main()
