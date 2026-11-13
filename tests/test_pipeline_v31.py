#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Suite de pruebas unitarias offline (sin red ni gasto de cuota) para Kicksazos v3.1."""

import io
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from google.genai.errors import APIError, ServerError  # noqa: E402

import pipeline_viral_clips as pvc  # noqa: E402


def _hacer_clip_raw(
    clip_id: int,
    inicio: str,
    fin: str,
    titulo: str = "Momento épico en Kick",
    subtitulos=None,
) -> dict:
    return {
        "id": clip_id,
        "titulo": titulo,
        "inicio": inicio,
        "fin": fin,
        "gancho": "Parce mire lo que pasó",
        "razon_viral": "Alta tensión narrativa y polémica en vivo.",
        "descripcion": "Momento increíble en stream\n¡Suscríbete a Kicksazos! #Shorts #Kicksazos",
        "etiquetas": ["Kicksazos", "WestCOL", "KickColombia", "Shorts", "StreamColombia", "IRL", "Medellin", "Viral"],
        "caption_tiktok": "¿Ustedes qué opinan de esto en vivo?",
        "hashtags_tiktok": ["#Kicksazos", "#KickColombia", "#StreamColombia"],
        "gancho_visual_portada": "ESTO PASÓ EN VIVO",
        "subtitulos": subtitulos
        if subtitulos is not None
        else [
            {"inicio_rel": 0.0, "fin_rel": 1.2, "texto": "Parce mire esto"},
            {"inicio_rel": 1.2, "fin_rel": 2.5, "texto": "Qué gonorrea hermano"},
        ],
    }


def _hacer_fake_popen(stdout_text: str = "", stderr_text: str = "", returncode: int = 0):
    return SimpleNamespace(
        stdout=io.StringIO(stdout_text),
        stderr=io.StringIO(stderr_text),
        poll=lambda: returncode,
        wait=lambda timeout=None: returncode,
        kill=lambda: None,
    )


class TestFase1ExtraccionAudio(unittest.TestCase):
    def test_extraer_audio_primario_youtube_con_aria2c(self):
        with tempfile.TemporaryDirectory() as tmp:
            job_dir = Path(tmp)
            comandos_ejecutados = []

            def fake_popen(cmd, **kwargs):
                comandos_ejecutados.append(cmd)
                # Simula creación de temp_audio.mp3 > 10 KB
                (job_dir / "temp_audio.mp3").write_bytes(b"ID3" + b"\x00" * 15000)
                return _hacer_fake_popen("[download] 100.0% of 10.00MiB at 15.00MiB/s ETA 00:00\n")

            with patch.object(pvc.shutil, "which", return_value="/usr/bin/aria2c"), patch.object(
                pvc.subprocess, "Popen", side_effect=fake_popen
            ):
                salida = pvc.extraer_audio("https://www.youtube.com/watch?v=abc123", job_dir=job_dir)

            self.assertEqual(Path(salida), (job_dir / "temp_audio.mp3").resolve())
            self.assertEqual(len(comandos_ejecutados), 1)
            cmd = comandos_ejecutados[0]
            self.assertIn("yt_dlp", cmd)
            self.assertIn("--newline", cmd)
            self.assertIn("--concurrent-fragments", cmd)
            self.assertEqual(cmd[cmd.index("--concurrent-fragments") + 1], "16")
            self.assertEqual(cmd[cmd.index("--retries") + 1], "10")
            self.assertEqual(cmd[cmd.index("--fragment-retries") + 1], "10")
            self.assertEqual(cmd[cmd.index("--retry-sleep") + 1], "fragment:exp=1:10")
            self.assertEqual(cmd[cmd.index("--socket-timeout") + 1], "15")
            self.assertEqual(cmd[cmd.index("--buffer-size") + 1], "16K")
            self.assertEqual(cmd[cmd.index("--http-chunk-size") + 1], "10M")
            self.assertIn("--downloader", cmd)
            self.assertEqual(cmd[cmd.index("--downloader") + 1], "aria2c")
            self.assertEqual(cmd[cmd.index("--downloader-args") + 1], "aria2c:-x 16 -s 16 -k 1M")
            self.assertEqual(cmd[cmd.index("-f") + 1], pvc.FORMATOS_AUDIO_DIRECTO)
            self.assertEqual(cmd[cmd.index("--postprocessor-args") + 1], "ffmpeg:-vn -ac 1 -ar 12000 -b:a 24k")

    def test_extraer_audio_sin_aria2c_en_kick_twitch_m3u8(self):
        for url in (
            "https://kick.com/eldomi/videos/01a1b385",
            "https://www.twitch.tv/videos/987654",
            "https://cdn.example.com/stream/master.m3u8?sig=xyz",
        ):
            with tempfile.TemporaryDirectory() as tmp:
                job_dir = Path(tmp)
                comandos_ejecutados = []

                def fake_popen(cmd, **kwargs):
                    comandos_ejecutados.append(cmd)
                    (job_dir / "temp_audio.mp3").write_bytes(b"ID3" + b"\x00" * 12000)
                    return _hacer_fake_popen("[download] 100.0% of 8.00MiB at 10.00MiB/s ETA 00:00\n")

                with patch.object(pvc.shutil, "which", return_value="/usr/bin/aria2c"), patch.object(
                    pvc.subprocess, "Popen", side_effect=fake_popen
                ):
                    pvc.extraer_audio(url, job_dir=job_dir)

                self.assertNotIn("--downloader", comandos_ejecutados[0], f"No debía usar aria2c en {url}")

    def test_extraer_audio_fallback_si_archivo_menor_10kb(self):
        with tempfile.TemporaryDirectory() as tmp:
            job_dir = Path(tmp)
            comandos_ejecutados = []

            def fake_popen(cmd, **kwargs):
                comandos_ejecutados.append(cmd)
                if "yt_dlp" in cmd:
                    # Primario genera archivo inválido < 10 KB
                    (job_dir / "temp_audio.mp3").write_bytes(b"tiny" * 100)
                    return _hacer_fake_popen("[download] 100.0% of 0.01MiB at 1.00MiB/s ETA 00:00\n")
                if cmd[0] == "ffmpeg":
                    (job_dir / "temp_audio.mp3").write_bytes(b"ID3" + b"\x00" * 20480)
                    return _hacer_fake_popen("out_time_us=1000000\nprogress=end\n", "")
                return _hacer_fake_popen()

            with patch.object(pvc.shutil, "which", return_value=None), patch.object(
                pvc, "_obtener_url_audio_directo", return_value="https://cdn.kick.com/audio/stream.m3u8"
            ), patch.object(pvc.subprocess, "Popen", side_effect=fake_popen):
                salida = pvc.extraer_audio("https://kick.com/yhap/videos/1", job_dir=job_dir)

            self.assertTrue(Path(salida).exists())
            self.assertEqual(len(comandos_ejecutados), 2)
            ffmpeg_cmd = comandos_ejecutados[1]
            self.assertEqual(ffmpeg_cmd[0], "ffmpeg")
            self.assertIn("-reconnect", ffmpeg_cmd)
            self.assertIn("-reconnect_streamed", ffmpeg_cmd)
            self.assertIn("-reconnect_delay_max", ffmpeg_cmd)
            self.assertIn("-rw_timeout", ffmpeg_cmd)
            self.assertIn("https://cdn.kick.com/audio/stream.m3u8", ffmpeg_cmd)


class TestFase2ResilienciaYChunking(unittest.TestCase):
    def _mock_client_para_stream(self, stream_fn):
        client = MagicMock()
        client.files.upload.return_value = SimpleNamespace(name="files/audio_test_1", state="ACTIVE")
        client.files.get.return_value = SimpleNamespace(name="files/audio_test_1", state="ACTIVE")
        client.models.generate_content_stream.side_effect = stream_fn
        return client

    def test_salto_inmediato_0s_en_429_cuota_diaria_free_tier(self):
        for indicador in ("free_tier_requests", "PerDay", "per day", "limit: 20"):
            modelos_invocados = []
            temperaturas = []

            def fake_stream(*, model, contents, config):
                modelos_invocados.append(model)
                temperaturas.append(config.temperature)
                if model == pvc.MODELOS_CANDIDATOS[0]:
                    raise APIError(
                        429,
                        {
                            "error": {
                                "code": 429,
                                "status": "RESOURCE_EXHAUSTED",
                                "message": f"Quota exceeded for metric: {indicador}",
                            }
                        },
                    )
                payload = json.dumps([_hacer_clip_raw(1, "00:01:00", "00:01:35")])
                return [SimpleNamespace(text=payload)]

            client = self._mock_client_para_stream(fake_stream)
            logs = []

            with patch.object(pvc, "_esperar_con_jitter") as mock_wait:
                clips = pvc._analizar_archivo_audio_gemini(
                    client,
                    ruta_archivo="dummy.mp3",
                    duracion_bloque=600.0,
                    modelo_preferido=None,
                    on_log=logs.append,
                )

            mock_wait.assert_not_called()
            self.assertEqual(modelos_invocados, [pvc.MODELOS_CANDIDATOS[0], pvc.MODELOS_CANDIDATOS[1]])
            self.assertEqual(temperaturas, [0.20, 0.20])
            self.assertEqual(len(clips), 1)
            self.assertEqual(clips[0]["modelo_ia"], pvc.MODELOS_CANDIDATOS[1])
            self.assertTrue(any("0.00s" in m and "Cuota diaria" in m for m in logs))
            client.files.delete.assert_called_once_with(name="files/audio_test_1")

    def test_salto_inmediato_0s_en_429_con_details_anidados_google_genai(self):
        modelos_invocados = []

        def fake_stream(*, model, contents, config):
            modelos_invocados.append(model)
            if model == pvc.MODELOS_CANDIDATOS[0]:
                raise APIError(
                    429,
                    {
                        "error": {
                            "code": 429,
                            "message": "Resource has been exhausted.",
                            "status": "RESOURCE_EXHAUSTED",
                            "details": [
                                {
                                    "violations": [
                                        {
                                            "quotaMetric": "generativelanguage.googleapis.com/generate_content_free_tier_requests",
                                            "quotaId": "GenerateRequestsPerDayPerProjectPerModel-FreeTier",
                                            "quotaValue": "20",
                                        }
                                    ]
                                }
                            ],
                        }
                    },
                )
            return [SimpleNamespace(text=json.dumps([_hacer_clip_raw(1, "00:00:05", "00:00:35")]))]

        client = self._mock_client_para_stream(fake_stream)
        with patch.object(pvc, "_esperar_con_jitter") as mock_wait:
            clips = pvc._analizar_archivo_audio_gemini(
                client,
                ruta_archivo="dummy.mp3",
                duracion_bloque=120.0,
                modelo_preferido=None,
                on_log=lambda _: None,
            )

        mock_wait.assert_not_called()
        self.assertEqual(modelos_invocados, [pvc.MODELOS_CANDIDATOS[0], pvc.MODELOS_CANDIDATOS[1]])
        self.assertEqual(len(clips), 1)

    def test_deduplicar_conserva_clips_con_solape_menor_o_igual_50_porciento(self):
        # Clip 1: 00:00:00 -> 00:00:40 (40s)
        # Clip 2: 00:00:25 -> 00:01:05 (40s), solape = 15s (37.5% <= 50%) -> deben conservarse ambos
        clips = [
            _hacer_clip_raw(7, "00:00:00", "00:00:40", titulo="Clip 1"),
            _hacer_clip_raw(9, "00:00:25", "00:01:05", titulo="Clip 2"),
        ]
        res = pvc._deduplicar_clips_solapados(clips)
        self.assertEqual(len(res), 2)
        self.assertEqual([c["id"] for c in res], [1, 2])

    def test_backoff_en_429_transitorio_rpm_y_503(self):
        intentos_m1 = {"count": 0}

        def fake_stream_rpm(*, model, contents, config):
            intentos_m1["count"] += 1
            if intentos_m1["count"] == 1:
                raise APIError(
                    429,
                    {
                        "error": {
                            "code": 429,
                            "status": "RESOURCE_EXHAUSTED",
                            "message": "Rate limit exceeded per minute (RPM limit: 15)",
                        }
                    },
                )
            if intentos_m1["count"] == 2:
                raise ServerError(
                    503,
                    {"error": {"code": 503, "status": "UNAVAILABLE", "message": "Model overloaded"}},
                )
            payload = json.dumps([_hacer_clip_raw(1, "00:00:10", "00:00:40")])
            return [SimpleNamespace(text=payload)]

        client = self._mock_client_para_stream(fake_stream_rpm)
        with patch.object(pvc, "_esperar_con_jitter", return_value=4.0) as mock_wait:
            clips = pvc._analizar_archivo_audio_gemini(
                client,
                ruta_archivo="dummy.mp3",
                duracion_bloque=300.0,
                modelo_preferido=None,
                on_log=lambda _: None,
            )

        self.assertEqual(mock_wait.call_count, 2)
        self.assertEqual(len(clips), 1)
        self.assertEqual(clips[0]["modelo_ia"], pvc.MODELOS_CANDIDATOS[0])

    def test_segmentar_audio_en_chunks_umbrales_y_solapamiento(self):
        with tempfile.TemporaryDirectory() as tmp:
            audio = Path(tmp) / "temp_audio.mp3"
            audio.write_bytes(b"MP3")

            with patch.object(pvc.subprocess, "run") as mock_run:
                corto = pvc._segmentar_audio_en_chunks(str(audio), 1800.0)
            mock_run.assert_not_called()
            self.assertEqual(corto, [(str(audio), 0.0, 1800.0)])

            comandos = []

            def fake_ffmpeg(cmd, **kwargs):
                comandos.append(cmd)
                Path(cmd[-1]).write_bytes(b"CHUNK")
                return SimpleNamespace(returncode=0)

            with patch.object(pvc.subprocess, "run", side_effect=fake_ffmpeg):
                largos = pvc._segmentar_audio_en_chunks(str(audio), 3300.0)

            self.assertEqual(len(largos), 3)
            self.assertEqual(largos[0][1:], (0.0, 1500.0))
            self.assertEqual(largos[1][1:], (1440.0, 1500.0))
            self.assertEqual(largos[2][1:], (2880.0, 420.0))
            self.assertTrue(largos[0][0].endswith("temp_audio_chunk_00.mp3"))
            self.assertTrue(largos[1][0].endswith("temp_audio_chunk_01.mp3"))
            self.assertTrue(largos[2][0].endswith("temp_audio_chunk_02.mp3"))
            for cmd in comandos:
                self.assertIn("-c", cmd)
                self.assertEqual(cmd[cmd.index("-c") + 1], "copy")

    def test_analizar_con_gemini_offsets_deduplicacion_chunk_vacio_y_limpieza(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_dir = Path(tmp)
            audio = tmp_dir / "temp_audio.mp3"
            audio.write_bytes(b"ORIG")

            def fake_ffmpeg(cmd, **kwargs):
                Path(cmd[-1]).write_bytes(b"CHUNK")
                return SimpleNamespace(returncode=0)

            # Simula 3 chunks (threshold > 1800s, bloques de 1500s, solapamiento 60s):
            # - chunk 0 (offset 0): clip 1 [00:10:00 -> 00:10:40] (40s) + clip solapado corto [00:24:20 -> 00:25:00] (40s = 1460..1500)
            # - chunk 1 (offset 1440): clip solapado completo [00:00:20 -> 00:01:15] -> abs [1460..1515] = [00:24:20 -> 00:25:15] (55s)
            # - chunk 2 (offset 2880): [] (chunk silencioso/muerto)
            respuestas_por_nombre = {
                "temp_audio_chunk_00.mp3": [
                    _hacer_clip_raw(
                        1,
                        "00:10:00",
                        "00:10:40",
                        titulo="Clip Chunk 0",
                        subtitulos=[{"inicio_rel": 0.0, "fin_rel": 1.5, "texto": "Inicio clip cero"}],
                    ),
                    _hacer_clip_raw(
                        2,
                        "00:24:20",
                        "00:25:00",
                        titulo="Clip Cortado Borde",
                        subtitulos=[{"inicio_rel": 0.0, "fin_rel": 1.0, "texto": "Borde corto"}],
                    ),
                ],
                "temp_audio_chunk_01.mp3": [
                    _hacer_clip_raw(
                        1,
                        "00:00:20",
                        "00:01:15",
                        titulo="Clip Completo Solapado",
                        subtitulos=[
                            {"inicio_rel": 0.0, "fin_rel": 1.5, "texto": "Inicio completo"},
                            {"inicio_rel": 1.5, "fin_rel": 3.0, "texto": "Remate brutal"},
                        ],
                    )
                ],
                "temp_audio_chunk_02.mp3": [],
            }

            def fake_analizar_chunk(client, ruta_archivo, duracion_bloque, modelo_preferido, on_log=None, *args, **kwargs):
                ruta = Path(ruta_archivo)
                # Asegura que el chunk temporal exista durante el análisis
                self.assertTrue(ruta.exists())
                return respuestas_por_nombre[ruta.name]

            guardado = {}

            def fake_guardar(clips, job_dir=None):
                guardado["clips"] = clips
                guardado["job_dir"] = job_dir

            with patch.dict(pvc.os.environ, {"GEMINI_API_KEY": "test_key"}), patch.object(
                pvc.genai, "Client", return_value=MagicMock()
            ), patch.object(pvc.subprocess, "run", side_effect=fake_ffmpeg), patch.object(
                pvc, "_analizar_archivo_audio_gemini", side_effect=fake_analizar_chunk
            ), patch.object(
                pvc, "_guardar_y_sincronizar_clips", side_effect=fake_guardar
            ):
                resultado = pvc.analizar_con_gemini(
                    audio, duracion_total=3300.0, job_dir=tmp_dir, on_log=lambda _: None
                )

            self.assertEqual(len(resultado), 2)
            self.assertEqual([c["id"] for c in resultado], [1, 2])
            self.assertEqual(resultado[0]["inicio"], "00:10:00")
            self.assertEqual(resultado[0]["fin"], "00:10:40")
            # Clip 2 ganó la deduplicación (55s vs 40s) y desplazó su timestamp +1440s
            self.assertEqual(resultado[1]["titulo"], "Clip Completo Solapado")
            self.assertEqual(resultado[1]["inicio"], "00:24:20")
            self.assertEqual(resultado[1]["fin"], "00:25:15")
            self.assertEqual(resultado[1]["duracion_segundos"], 55)
            # Los subtítulos siguen siendo relativos al clip (no se les sumó 1440s)
            self.assertEqual(resultado[1]["subtitulos"][0]["inicio_rel"], 0.0)
            self.assertEqual(resultado[1]["subtitulos"][0]["fin_rel"], 1.5)
            # Todos los chunks temporales fueron borrados y el audio original permanece intacto
            self.assertTrue(audio.exists())
            self.assertEqual(list(tmp_dir.glob("temp_audio_chunk_*.mp3")), [])
            self.assertEqual(guardado["clips"], resultado)

    def test_analizar_con_gemini_error_si_todos_los_chunks_devuelven_vacio(self):
        with tempfile.TemporaryDirectory() as tmp:
            audio = Path(tmp) / "temp_audio.mp3"
            audio.write_bytes(b"ORIG")

            with patch.dict(pvc.os.environ, {"GEMINI_API_KEY": "test_key"}), patch.object(
                pvc.genai, "Client", return_value=MagicMock()
            ), patch.object(
                pvc, "_analizar_archivo_audio_gemini", return_value=[]
            ), patch.object(
                pvc, "_guardar_y_sincronizar_clips"
            ):
                with self.assertRaises(RuntimeError):
                    pvc.analizar_con_gemini(audio, duracion_total=1200.0, on_log=lambda _: None)


class TestFase3PromptYCuraduriaDinamica(unittest.TestCase):
    def test_prompt_v31_sin_limites_artificiales(self):
        prompt = pvc.construir_prompt_viral(3600.0)
        self.assertIn("01:00:00", prompt)
        self.assertIn("NO existe un número mínimo ni máximo de clips", prompt)
        self.assertNotIn("3 a 6", prompt)
        self.assertIn("2 a 4 palabras", prompt)
        self.assertIn("máximo 22 caracteres", prompt)
        self.assertIn("SIN EMOJIS", prompt)
        self.assertIn("Transcribe LITERALMENTE", prompt)

    def test_parseo_dinamico_1_u_8_clips_y_vacio_opcional(self):
        self.assertEqual(pvc._limpiar_y_parsear_json("[]", permitir_vacio=True), [])
        with self.assertRaises(ValueError):
            pvc._limpiar_y_parsear_json("[]", permitir_vacio=False)

        uno = pvc._limpiar_y_parsear_json(
            json.dumps([_hacer_clip_raw(9, "00:00:10", "00:00:40")]), duracion_total=300.0
        )
        self.assertEqual(len(uno), 1)
        self.assertEqual(uno[0]["id"], 1)

        ocho_raw = [
            _hacer_clip_raw(i + 1, pvc.segundos_a_hhmmss(i * 60), pvc.segundos_a_hhmmss(i * 60 + 30))
            for i in range(8)
        ]
        ocho = pvc._limpiar_y_parsear_json(json.dumps(ocho_raw), duracion_total=600.0)
        self.assertEqual(len(ocho), 8)
        self.assertEqual([c["id"] for c in ocho], list(range(1, 9)))


class TestFase4SubtitulosYEstilosASS(unittest.TestCase):
    def test_auto_particion_segmentos_largos_por_palabras_y_caracteres(self):
        raw = [
            {
                "inicio_rel": 0.0,
                "fin_rel": 4.0,
                "texto": "Esta gente no tiene vergüenza ninguna hermano mío",  # 8 palabras
            },
            {
                "inicio_rel": 4.0,
                "fin_rel": 6.0,
                "texto": "Extraordinariamente impresionante hermano querido",  # 4 palabras, 49 chars (>28)
            },
            {
                "inicio_rel": 6.0,
                "fin_rel": 6.4,
                "texto": "Uno dos tres cuatro cinco seis",  # < 0.6s, no se divide
            },
        ]
        subs = pvc._normalizar_subtitulos(raw, duracion_clip=10.0)

        # Los dos primeros deben haberse dividido en bloques de 2 a 4 palabras
        primeros = [s for s in subs if s.fin_rel <= 4.01]
        self.assertGreaterEqual(len(primeros), 2)
        for s in primeros:
            self.assertGreaterEqual(len(s.texto.split()), 2)
            self.assertLessEqual(len(s.texto.split()), 4)
        self.assertEqual(primeros[0].inicio_rel, 0.0)
        self.assertEqual(primeros[-1].fin_rel, 4.0)

        segundos = [s for s in subs if s.inicio_rel >= 4.0 and s.fin_rel <= 6.01]
        self.assertEqual(len(segundos), 2)
        for s in segundos:
            self.assertEqual(len(s.texto.split()), 2)
        self.assertEqual(segundos[0].inicio_rel, 4.0)
        self.assertEqual(segundos[-1].fin_rel, 6.0)

        tercero = [s for s in subs if s.inicio_rel >= 6.0]
        self.assertEqual(len(tercero), 1)
        self.assertEqual(tercero[0].texto, "Uno dos tres cuatro cinco seis")

        # Cero solapamientos en toda la lista y sin emojis
        for i in range(1, len(subs)):
            self.assertLessEqual(subs[i - 1].fin_rel, subs[i].inicio_rel)

        # Idempotencia
        self.assertEqual(pvc._normalizar_subtitulos(subs, duracion_clip=10.0), subs)

    def test_detectar_fuente_subtitulos_prioridad_y_fallback(self):
        fake_fclist = SimpleNamespace(
            stdout="DejaVu Sans\nUbuntu\nImpact\nLiberation Sans\nMontserrat,Montserrat ExtraBold\n"
        )
        with patch.object(pvc.subprocess, "run", return_value=fake_fclist):
            self.assertEqual(pvc._detectar_fuente_subtitulos(), "Montserrat ExtraBold")

        fake_poppins = SimpleNamespace(stdout="DejaVu Sans\nPoppins,Poppins Bold\nImpact\n")
        with patch.object(pvc.subprocess, "run", return_value=fake_poppins):
            self.assertEqual(pvc._detectar_fuente_subtitulos(), "Poppins Bold")

        fake_liberation = SimpleNamespace(stdout="Ubuntu\nLiberation Sans\nDejaVu Sans\n")
        with patch.object(pvc.subprocess, "run", return_value=fake_liberation):
            self.assertEqual(pvc._detectar_fuente_subtitulos(), "Liberation Sans")

        with patch.object(pvc.subprocess, "run", side_effect=FileNotFoundError("no fc-list")):
            self.assertEqual(pvc._detectar_fuente_subtitulos(), "DejaVu Sans")

    def test_generar_archivo_ass_estilos_popin_y_anti_emojis(self):
        with tempfile.TemporaryDirectory() as tmp:
            ruta_ass = Path(tmp) / "subs_test.ass"
            subs = [
                pvc.SegmentoSubtitulo(inicio_rel=0.0, fin_rel=1.5, texto="¡Qué chimba parce! 🔥😂"),
                pvc.SegmentoSubtitulo(inicio_rel=1.5, fin_rel=3.0, texto="Texto con {llaves} 💀"),
            ]
            with patch.object(pvc, "_obtener_fuente_y_dir_subtitulos", return_value=("Montserrat ExtraBold", "/tmp/fonts")):
                salida = pvc.generar_archivo_ass(subs, ruta_ass)

            contenido = Path(salida).read_text(encoding="utf-8")
            self.assertIn("WrapStyle: 0", contenido)
            self.assertIn(
                "Style: Default,Montserrat ExtraBold,50,&H00FFFFFF,&H0000FFFF,&H00000000,&HA0000000,-1,0,0,0,100,100,1.2,0,1,5.0,3.0,2,80,170,550,1",
                contenido,
            )
            popin = r"{\fad(40,40)\t(0,70,\fscx105\fscy105)\t(70,140,\fscx100\fscy100)}"
            self.assertIn(f"Dialogue: 0,0:00:00.00,0:00:01.50,Default,,0,0,0,,{popin}¡QUÉ CHIMBA PARCE!", contenido)
            self.assertIn(f"Dialogue: 0,0:00:01.50,0:00:03.00,Default,,0,0,0,,{popin}TEXTO CON (LLAVES)", contenido)
            self.assertNotIn("🔥", contenido)
            self.assertNotIn("😂", contenido)
            self.assertNotIn("💀", contenido)

    def test_smoke_ffmpeg_chunking_y_quemado_ass_reales(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_dir = Path(tmp)
            # 1) Smoke test ASS con libass real sobre video sintético de 1 segundo
            ruta_ass = tmp_dir / "smoke.ass"
            subs = pvc._normalizar_subtitulos(
                [{"inicio_rel": 0.0, "fin_rel": 0.9, "texto": "Prueba real de subtítulo viral en FFmpeg"}],
                duracion_clip=1.0,
            )
            pvc.generar_archivo_ass(subs, ruta_ass)
            esc = pvc._escapar_ruta_ffmpeg_filtro(ruta_ass)
            out_mp4 = tmp_dir / "smoke.mp4"
            res_ass = subprocess.run(
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
                    f"subtitles='{esc}'",
                    "-c:v",
                    "libx264",
                    "-preset",
                    "ultrafast",
                    str(out_mp4),
                ],
                capture_output=True,
                text=True,
            )
            self.assertEqual(res_ass.returncode, 0, res_ass.stderr)
            self.assertTrue(out_mp4.exists() and out_mp4.stat().st_size > 1000)

            # 2) Smoke test segmentación real -c copy en MP3 sintético
            audio_test = tmp_dir / "test_audio.mp3"
            res_mp3 = subprocess.run(
                [
                    "ffmpeg",
                    "-hide_banner",
                    "-loglevel",
                    "error",
                    "-y",
                    "-f",
                    "lavfi",
                    "-i",
                    "anullsrc=r=16000:cl=mono",
                    "-t",
                    "12",
                    "-c:a",
                    "libmp3lame",
                    "-b:a",
                    "32k",
                    str(audio_test),
                ],
                capture_output=True,
                text=True,
            )
            self.assertEqual(res_mp3.returncode, 0, res_mp3.stderr)
            # Valida corte manual con parámetros de _segmentar_audio_en_chunks usando max_duracion_chunk=6, solapamiento=2
            # (simula audio > 3300 llamando al comando ffmpeg directamente en umbral pequeño con patch o dur>3300)
            chunk_out = tmp_dir / "chunk_test.mp3"
            res_cut = subprocess.run(
                [
                    "ffmpeg",
                    "-hide_banner",
                    "-loglevel",
                    "error",
                    "-y",
                    "-ss",
                    "4.000",
                    "-t",
                    "6.000",
                    "-i",
                    str(audio_test),
                    "-c",
                    "copy",
                    str(chunk_out),
                ],
                capture_output=True,
                text=True,
            )
            self.assertEqual(res_cut.returncode, 0, res_cut.stderr)
            dur_chunk = pvc.obtener_duracion_media(chunk_out)
            self.assertIsNotNone(dur_chunk)
            self.assertAlmostEqual(dur_chunk, 6.0, delta=0.5)


if __name__ == "__main__":
    unittest.main(verbosity=2)
