"""Pruebas unitarias para la delegación de transcripción de audio a Groq (whisper-large-v3-turbo)."""

from __future__ import annotations

import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
import urllib.error
from unittest.mock import MagicMock, patch

BASE_DIR = Path(__file__).resolve().parent.parent
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

import pipeline_viral_clips as pvc
from ui_desktop import services as ui_services


class _FakeHTTPResponse:
    """Respuesta HTTP simulada para urllib.request.urlopen."""

    def __init__(self, data: bytes | dict | str, code: int = 200) -> None:
        if isinstance(data, dict):
            self._bytes = json.dumps(data).encode("utf-8")
        elif isinstance(data, str):
            self._bytes = data.encode("utf-8")
        else:
            self._bytes = data
        self.code = code

    def read(self) -> bytes:
        return self._bytes

    def __iter__(self):
        return iter(self._bytes.splitlines(keepends=True))

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False


class TestGroqWhisper(unittest.TestCase):
    """Validación exhaustiva de la transcripción en nube con Groq Whisper."""

    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.job_dir = Path(self.temp_dir.name)
        self.fake_audio = self.job_dir / "temp_audio.mp3"
        self.fake_audio.write_bytes(b"ID3" + b"\x00" * 2048)

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def test_peticion_multipart_parametros_y_headers(self) -> None:
        """Valida model=whisper-large-v3-turbo, response_format=verbose_json y timestamp_granularities[]."""
        mock_resp = {
            "text": "Hola mundo parce",
            "language": "es",
            "duration": 5.0,
            "segments": [
                {"id": 0, "start": 0.0, "end": 2.5, "text": "Hola mundo parce"}
            ],
            "words": [
                {"word": "Hola", "start": 0.0, "end": 0.8},
                {"word": "mundo", "start": 0.9, "end": 1.6},
                {"word": "parce", "start": 1.7, "end": 2.4},
            ],
        }

        with patch("urllib.request.urlopen", return_value=_FakeHTTPResponse(mock_resp)) as mock_urlopen:
            resp = pvc._peticion_multipart_groq_whisper(
                url=pvc.GROQ_AUDIO_URL,
                api_key="gsk_test123",
                ruta_archivo=self.fake_audio,
                modelo="whisper-large-v3-turbo",
            )
            self.assertEqual(resp["language"], "es")
            self.assertEqual(len(resp["segments"]), 1)
            self.assertEqual(len(resp["words"]), 3)

            mock_urlopen.assert_called_once()
            req = mock_urlopen.call_args[0][0]
            self.assertIn("Authorization", req.headers)
            self.assertEqual(req.headers["Authorization"], "Bearer gsk_test123")
            self.assertEqual(req.headers["User-agent"], "Mozilla/5.0 (X11; Linux x86_64) KicksazosStudio/5.0")
            self.assertIn("multipart/form-data; boundary=", req.headers["Content-type"])

            body_bytes = req.data
            self.assertIn(b'name="model"\r\n\r\nwhisper-large-v3-turbo', body_bytes)
            self.assertIn(b'name="response_format"\r\n\r\nverbose_json', body_bytes)
            self.assertIn(b'name="timestamp_granularities[]"\r\n\r\nword', body_bytes)
            self.assertIn(b'name="timestamp_granularities[]"\r\n\r\nsegment', body_bytes)
            self.assertIn(b'name="temperature"\r\n\r\n0.0', body_bytes)
            self.assertIn(b"Stream en vivo en Kick Colombia con jerga colombiana", body_bytes)

    def test_transcribir_audio_groq_cache_y_picos_rms(self) -> None:
        """Verifica guardado y reutilización de whisper_transcript.json, e inyección de pico_vocal."""
        mock_resp = {
            "text": "Primer segmento de prueba. Segundo segmento con mas energia.",
            "language": "es",
            "duration": 6.0,
            "segments": [
                {"start": 0.0, "end": 3.0, "text": "Primer segmento de prueba."},
                {"start": 3.1, "end": 6.0, "text": "Segundo segmento con mas energia."},
            ],
            "words": [
                {"word": "Primer", "start": 0.0, "end": 0.5},
                {"word": "segmento", "start": 0.6, "end": 1.2},
                {"word": "Segundo", "start": 3.1, "end": 3.6},
            ],
        }

        logs = []
        telemetrias = []

        with patch.object(pvc, "_peticion_multipart_groq_whisper", return_value=mock_resp), \
             patch.object(pvc, "obtener_duracion_media", return_value=6.0), \
             patch.object(pvc, "_calcular_energia_segmentos_audio", return_value={1}):

            res = pvc._transcribir_audio_groq(
                self.fake_audio,
                groq_api_key="gsk_fake",
                job_dir=self.job_dir,
                on_log=logs.append,
                on_telemetria=telemetrias.append,
            )

            cache_file = self.job_dir / "whisper_transcript.json"
            self.assertTrue(cache_file.is_file())
            cached_data = json.loads(cache_file.read_text(encoding="utf-8"))
            self.assertEqual(cached_data["duracion"], 6.0)
            self.assertEqual(len(cached_data["segmentos"]), 2)
            self.assertFalse(cached_data["segmentos"][0]["pico_vocal"])
            self.assertTrue(cached_data["segmentos"][1]["pico_vocal"])
            self.assertIn(1, cached_data["indices_picos"])

            # Segunda llamada: debe reutilizar caché sin llamar a Groq API
            with patch.object(pvc, "_peticion_multipart_groq_whisper") as mock_api_2:
                res2 = pvc._transcribir_audio_groq(
                    self.fake_audio,
                    groq_api_key="gsk_fake",
                    job_dir=self.job_dir,
                    on_log=logs.append,
                    on_telemetria=telemetrias.append,
                )
                mock_api_2.assert_not_called()
                self.assertEqual(res2["duracion"], 6.0)
                self.assertTrue(any("Reutilizando transcripción" in lg for lg in logs))

    def test_dividir_audio_por_tamano_groq_y_suma_offsets(self) -> None:
        """Valida que si supera 24 MB se divida con ffmpeg -segment_time 3600 y los offsets se sumen con precisión."""
        # Creamos partes simuladas
        p1 = self.job_dir / "groq_audio_part_00.mp3"
        p2 = self.job_dir / "groq_audio_part_01.mp3"
        p1.write_bytes(b"1" * 100)
        p2.write_bytes(b"2" * 100)

        def fake_ffmpeg(cmd, **kwargs):
            return subprocess.CompletedProcess(cmd, 0)

        def fake_dur(p):
            if "00" in str(p):
                return 3600.0
            return 1200.0

        with patch("subprocess.run", side_effect=fake_ffmpeg), \
             patch.object(pvc, "obtener_duracion_media", side_effect=fake_dur):
            # Forzamos max_bytes menor al tamaño del fake_audio
            partes, offsets, es_temp = pvc._dividir_audio_por_tamano_groq(
                self.fake_audio,
                job_dir=self.job_dir,
                max_bytes=100,  # forzar corte
            )
            self.assertTrue(es_temp)
            self.assertEqual(len(partes), 2)
            self.assertEqual(offsets, [0.0, 3600.0])

        # Ahora probamos _transcribir_audio_groq procesando esas 2 partes simuladas
        def fake_peticion(url, api_key, ruta_archivo, **kwargs):
            if "00" in str(ruta_archivo):
                return {
                    "language": "es",
                    "segments": [{"start": 10.0, "end": 20.0, "text": "Parte 1"}],
                    "words": [{"word": "Parte", "start": 10.0, "end": 15.0}],
                }
            else:
                return {
                    "language": "es",
                    "segments": [{"start": 5.0, "end": 15.0, "text": "Parte 2"}],
                    "words": [{"word": "Parte", "start": 5.0, "end": 10.0}],
                }

        # Borramos caché previo si quedó
        cache_prev = self.job_dir / "whisper_transcript.json"
        if cache_prev.exists():
            cache_prev.unlink()

        with patch.object(pvc, "_dividir_audio_por_tamano_groq", return_value=([p1, p2], [0.0, 3600.0], True)), \
             patch.object(pvc, "_peticion_multipart_groq_whisper", side_effect=fake_peticion), \
             patch.object(pvc, "obtener_duracion_media", return_value=4800.0), \
             patch.object(pvc, "_calcular_energia_segmentos_audio", return_value=set()):

            res = pvc._transcribir_audio_groq(
                self.fake_audio,
                groq_api_key="gsk_fake",
                job_dir=self.job_dir,
            )

            # Verificar que parte 2 sumó el offset 3600.0
            self.assertEqual(len(res["segmentos"]), 2)
            self.assertEqual(res["segmentos"][0]["start"], 10.0)
            self.assertEqual(res["segmentos"][0]["end"], 20.0)
            self.assertEqual(res["segmentos"][1]["start"], 3605.0)
            self.assertEqual(res["segmentos"][1]["end"], 3615.0)

            self.assertEqual(len(res["palabras"]), 2)
            self.assertEqual(res["palabras"][1]["start"], 3605.0)
            self.assertEqual(res["palabras"][1]["end"], 3610.0)

            # Verificar limpieza de partes temporales en el bloque finally
            self.assertFalse(p1.exists())
            self.assertFalse(p2.exists())

    def test_analizar_con_groq_flujo_completo_1_sola_pasada(self) -> None:
        """Valida que analizar_con_groq produzca clips con subtitulos_origen='whisper_word_timestamps' y motor_ia='groq'."""
        mock_transcript = {
            "duracion": 20.0,
            "duracion_total": 20.0,
            "idioma": "es",
            "segmentos": [
                {"start": 0.0, "end": 10.0, "text": "Clip viral del streamer en kick.", "pico_vocal": True}
            ],
            "palabras": [
                {"word": "Clip", "start": 0.0, "end": 1.0},
                {"word": "viral", "start": 1.1, "end": 2.0},
                {"word": "streamer", "start": 2.1, "end": 4.0},
            ],
            "indices_picos": [0],
        }

        mock_curaduria_json = json.dumps({
            "clips": [
                {
                    "inicio": "00:00:00",
                    "fin": "00:00:08",
                    "titulo": "Momento Épico Kick",
                    "justificacion": "Alta energía al inicio",
                    "hook": "Mira esto",
                    "score_viral": 95,
                }
            ]
        })

        with patch.object(pvc, "_transcribir_audio_groq", return_value=mock_transcript), \
             patch.object(pvc, "_llamar_groq_chat", return_value=mock_curaduria_json):

            clips = pvc.analizar_con_groq(
                str(self.fake_audio),
                modelo_preferido="llama-3.3-70b-versatile",
                job_dir=self.job_dir,
                groq_api_key="gsk_test",
            )

            self.assertEqual(len(clips), 1)
            clip = clips[0]
            self.assertEqual(clip["motor_ia"], "groq")
            self.assertEqual(clip["subtitulos_origen"], "whisper_word_timestamps")
            self.assertTrue(len(clip["subtitulos"]) > 0)
            # En procesar_clip_ffmpeg, al tener subtitulos_origen == whisper_word_timestamps,
            # kwargs_render["alinear_subtitulos"] se vuelve False, activando la pasada única directa.

    def test_fallback_a_whisper_local_ante_error_429_audio(self) -> None:
        """Valida fallback a _transcribir_audio_whisper_local() ante error 429 de Groq cuando respaldo_local_auto=True."""
        err_429 = urllib.error.HTTPError(
            url=pvc.GROQ_AUDIO_URL,
            code=429,
            msg="Too Many Requests",
            hdrs=MagicMock(),
            fp=io.BytesIO(b'{"error": {"message": "Rate limit reached for model whisper-large-v3-turbo"}}'),
        )

        mock_transcript_local = {
            "duracion": 15.0,
            "duracion_total": 15.0,
            "idioma": "es",
            "segmentos": [{"start": 0.0, "end": 10.0, "text": "Texto transcrito localmente"}],
            "palabras": [{"word": "Texto", "start": 0.0, "end": 1.0}],
            "indices_picos": [0],
        }

        mock_curaduria_json = json.dumps({
            "clips": [
                {
                    "inicio": "00:00:00",
                    "fin": "00:00:08",
                    "titulo": "Fallback Clip",
                    "hook": "Hook",
                    "score_viral": 90,
                }
            ]
        })

        logs = []
        with patch.object(pvc, "_transcribir_audio_groq", side_effect=err_429), \
             patch.object(pvc, "_transcribir_audio_whisper_local", return_value=mock_transcript_local) as mock_local_whisper, \
             patch.object(pvc, "_llamar_groq_chat", return_value=mock_curaduria_json):

            clips = pvc.analizar_con_groq(
                str(self.fake_audio),
                modelo_preferido="llama-3.3-70b-versatile",
                job_dir=self.job_dir,
                groq_api_key="gsk_test",
                respaldo_local_auto=True,
                on_log=logs.append,
            )

            mock_local_whisper.assert_called_once()
            self.assertEqual(len(clips), 1)
            self.assertTrue(any("Falló transcripción en Groq Whisper" in l for l in logs))

        # Y si respaldo_local_auto=False, debe relanzar el error 429
        with patch.object(pvc, "_transcribir_audio_groq", side_effect=err_429):
            with self.assertRaises(pvc.GeminiQuotaExhaustedError):
                pvc.analizar_con_groq(
                    str(self.fake_audio),
                    job_dir=self.job_dir,
                    groq_api_key="gsk_test",
                    respaldo_local_auto=False,
                )

    def test_telemetria_etapa_groq_whisper_mapeo_ui(self) -> None:
        """Verifica que la etapa 'groq_whisper' se mapee correctamente en ui_desktop/services.py."""
        estado_tele = {
            "fase": "groq_whisper",
            "telemetria": {
                "etapa": "groq_whisper",
                "titulo_etapa": "Transcripción Nube (Groq Whisper)",
                "porcentaje": 45.0,
                "velocidad_red": "API Groq",
                "tamano_total": "Parte 1/2",
                "detalle": "Transcribiendo parte 1...",
            },
        }
        res_ui = ui_services.normalizar_estado_telemetria(estado_tele)
        self.assertEqual(res_ui["etapa_num"], 2)
        self.assertEqual(res_ui["etapa_nombre"], "Transcripción Nube (Groq Whisper)")
        self.assertEqual(res_ui["progreso"], 45.0)

        # Verificar formateo de barra CLI
        linea_cli = pvc._formatear_barra_cli(estado_tele)
        self.assertIn("Groq Whisper", linea_cli)
        self.assertIn("Parte 1/2", linea_cli)

    def test_cascada_modelos_groq_y_user_agent_chat(self) -> None:
        """Valida la cascada openai/gpt-oss-120b -> qwen/qwen3.8-27b ante error 404/429, User-Agent y limpieza <think>."""
        mock_transcript = {
            "duracion": 20.0,
            "duracion_total": 20.0,
            "idioma": "es",
            "segmentos": [
                {"start": 0.0, "end": 10.0, "text": "Clip de streaming en Kick", "pico_vocal": True}
            ],
            "palabras": [
                {"word": "Clip", "start": 0.0, "end": 1.0},
                {"word": "streaming", "start": 1.1, "end": 3.0},
            ],
            "indices_picos": [0],
        }

        # Simular que openai/gpt-oss-120b falla con 404 (model_not_found)
        err_404 = urllib.error.HTTPError(
            url="https://api.groq.com/openai/v1/chat/completions",
            code=404,
            msg="Not Found",
            hdrs=MagicMock(),
            fp=io.BytesIO(b'{"error": {"message": "model_not_found: openai/gpt-oss-120b"}}'),
        )

        # qwen/qwen3.8-27b responde con bloque <think>
        mock_curaduria_qwen = (
            "<think>Razonamiento interno del modelo Qwen3...</think>\n"
            + json.dumps({
                "clips": [
                    {
                        "inicio": "00:00:00",
                        "fin": "00:00:08",
                        "titulo": "Cascada Exitosa Qwen3",
                        "justificacion": "Alta energía detectada tras fallback",
                        "hook": "Mira esto",
                        "score_viral": 92,
                    }
                ]
            })
        )

        modelos_llamados = []
        headers_capturados = []

        def fake_llamar_chat(api_key, modelo, prompt):
            modelos_llamados.append(modelo)
            if modelo == "openai/gpt-oss-120b":
                raise err_404
            return mock_curaduria_qwen

        logs = []
        with patch.object(pvc, "_transcribir_audio_groq", return_value=mock_transcript), \
             patch.object(pvc, "_llamar_groq_chat", side_effect=fake_llamar_chat), \
             patch.object(pvc, "GROQ_MODELOS_CANDIDATOS", ["openai/gpt-oss-120b", "qwen/qwen3.8-27b", "openai/gpt-oss-20b"]):

            clips = pvc.analizar_con_groq(
                str(self.fake_audio),
                modelo_preferido="openai/gpt-oss-120b",
                job_dir=self.job_dir,
                groq_api_key="gsk_test",
                on_log=logs.append,
            )

            # Debe haber intentado gpt-oss-120b, saltado por 404, y tenido éxito con qwen3.8-27b
            self.assertEqual(modelos_llamados, ["openai/gpt-oss-120b", "qwen/qwen3.8-27b"])
            self.assertEqual(len(clips), 1)
            self.assertEqual(clips[0]["modelo_ia"], "qwen/qwen3.8-27b")
            self.assertEqual(clips[0]["titulo"], "Cascada Exitosa Qwen3")
            self.assertTrue(any("conmutando a siguiente modelo candidato" in l for l in logs))

        # Test directo de _llamar_groq_chat para verificar el header User-Agent en peticiones a api.groq.com
        chat_mock_resp = {
            "choices": [
                {"message": {"content": '{"clips": []}'}}
            ]
        }
        with patch("urllib.request.urlopen", return_value=_FakeHTTPResponse(chat_mock_resp)) as mock_urlopen:
            pvc._llamar_groq_chat(
                api_key="gsk_test456",
                modelo_groq="openai/gpt-oss-120b",
                prompt="test prompt",
            )
            req = mock_urlopen.call_args[0][0]
            self.assertIn("User-agent", req.headers)
            self.assertEqual(req.headers["User-agent"], "Mozilla/5.0 (X11; Linux x86_64) KicksazosStudio/5.0")
            self.assertEqual(req.headers["Authorization"], "Bearer gsk_test456")

    def test_analizar_con_groq_bloque_vacio_y_fallido_continua_sin_abortar(self) -> None:
        """Bloque 1/3 vacío ([]) y bloque 2/3 con JSON inválido no abortan el job; continúa a 3/3 y guarda checkpoint."""
        transcripcion_mock = {
            "duracion": 1800.0,
            "segmentos": [{"inicio": 0.0, "fin": 10.0, "texto": "Intro del stream"}],
            "palabras": [],
            "indices_picos": [],
        }
        bloques_mock = [
            {"offset_seg": 0.0, "duracion_bloque": 600.0, "texto": "Bloque 1"},
            {"offset_seg": 600.0, "duracion_bloque": 600.0, "texto": "Bloque 2"},
            {"offset_seg": 1200.0, "duracion_bloque": 600.0, "texto": "Bloque 3"},
        ]
        respuestas = iter(
            [
                "[]",  # Bloque 1/3 vacío
                "NO_ES_JSON_VALIDO{{{",  # Bloque 2/3 corrupto
                json.dumps(
                    [
                        {
                            "titulo": "Clip Bloque 3",
                            "inicio": "00:00:10",
                            "fin": "00:00:35",
                            "gancho": "Qué locura parce",
                            "razon_viral": "Clímax",
                        }
                    ]
                ),
            ]
        )
        logs: list[str] = []

        with (
            patch.object(pvc, "_transcribir_audio_groq", return_value=transcripcion_mock),
            patch.object(pvc, "_segmentar_transcripcion_para_ollama", return_value=bloques_mock),
            patch.object(pvc, "_llamar_groq_chat", side_effect=lambda *_a, **_kw: next(respuestas)),
        ):
            clips = pvc.analizar_con_groq(
                ruta_audio=str(self.fake_audio),
                modelo_preferido="openai/gpt-oss-120b",
                duracion_total=1800.0,
                job_dir=self.job_dir,
                groq_api_key="gsk_test_ok",
                on_log=logs.append,
            )

        self.assertEqual(len(clips), 1)
        self.assertEqual(clips[0]["titulo"], "Clip Bloque 3")
        # Bloque 3 tiene offset_seg=1200 -> 00:20:10 a 00:20:35
        self.assertEqual(clips[0]["inicio"], "00:20:10")
        self.assertEqual(clips[0]["fin"], "00:20:35")
        self.assertTrue(any("bloque 2/3 omitido por error" in l for l in logs))
        ckpt = self.job_dir / "groq_checkpoint.json"
        self.assertTrue(ckpt.exists())
        ckpt_data = json.loads(ckpt.read_text(encoding="utf-8"))
        self.assertEqual(len(ckpt_data), 1)

    def test_analizar_con_groq_timestamps_absolutos_y_relativos(self) -> None:
        """Acepta timestamps absolutos dentro de [offset_seg, offset_fin + 5] y los valida contra duracion_total_stream."""
        transcripcion_mock = {
            "duracion": 1500.0,
            "segmentos": [{"inicio": 600.0, "fin": 650.0, "texto": "Momento épico"}],
            "palabras": [],
            "indices_picos": [],
        }
        bloques_mock = [
            {"offset_seg": 600.0, "duracion_bloque": 600.0, "texto": "Bloque 2 absoluto"},
        ]
        resp_abs = json.dumps(
            [
                {
                    "titulo": "Clip Absoluto",
                    "inicio": "00:11:10",  # 670s (absoluto dentro de [600, 1205])
                    "fin": "00:11:40",     # 700s
                    "gancho": "Parce mire esto",
                    "razon_viral": "Reacción",
                }
            ]
        )

        with (
            patch.object(pvc, "_transcribir_audio_groq", return_value=transcripcion_mock),
            patch.object(pvc, "_segmentar_transcripcion_para_ollama", return_value=bloques_mock),
            patch.object(pvc, "_llamar_groq_chat", return_value=resp_abs),
        ):
            clips = pvc.analizar_con_groq(
                ruta_audio=str(self.fake_audio),
                modelo_preferido="qwen/qwen3.8-27b",
                duracion_total=1500.0,
                job_dir=self.job_dir,
                groq_api_key="gsk_test_abs",
            )

        self.assertEqual(len(clips), 1)
        self.assertEqual(clips[0]["inicio"], "00:11:10")
        self.assertEqual(clips[0]["fin"], "00:11:40")
        self.assertEqual(clips[0]["duracion_segundos"], 30)

    def test_groq_429_espera_dinamica_y_reintento_mismo_bloque(self) -> None:
        """Verifica parsing de 'Please try again in 8.16s' en HTTP 429 con espera y reintento en el mismo bloque."""
        transcripcion_mock = {
            "duracion": 300.0,
            "segmentos": [{"start": 0.0, "end": 10.0, "text": "Clip uno"}],
            "palabras": [],
            "indices_picos": [],
        }
        bloques_mock = [{"offset_seg": 0.0, "duracion_bloque": 300.0, "texto": "[00:00:00] Clip uno"}]
        resp_ok = json.dumps({
            "clips": [{"inicio": "00:00:05", "fin": "00:00:25", "titulo": "Clip 429 OK"}]
        })
        err_429 = urllib.error.HTTPError(
            url="https://api.groq.com/openai/v1/chat/completions",
            code=429,
            msg="Too Many Requests",
            hdrs=None,
            fp=io.BytesIO(b'{"error":{"message":"Rate limit reached. Please try again in 8.16s"}}'),
        )

        with (
            patch.object(pvc, "_transcribir_audio_groq", return_value=transcripcion_mock),
            patch.object(pvc, "_segmentar_transcripcion_para_ollama", return_value=bloques_mock),
            patch.object(pvc, "_llamar_groq_chat", side_effect=[err_429, resp_ok]) as mock_chat,
            patch("time.sleep") as mock_sleep,
        ):
            clips = pvc.analizar_con_groq(
                ruta_audio=str(self.fake_audio),
                duracion_total=300.0,
                job_dir=self.job_dir,
                groq_api_key="gsk_test_429",
                pausa_entre_bloques=0.0,
            )

        self.assertEqual(len(clips), 1)
        self.assertEqual(mock_chat.call_count, 2)
        self.assertEqual(mock_chat.call_args_list[0][0][1], mock_chat.call_args_list[1][0][1])
        mock_sleep.assert_called_once()
        self.assertAlmostEqual(mock_sleep.call_args[0][0], 9.66, places=2)

    def test_groq_continuidad_por_bloque_y_checkpoint(self) -> None:
        """Verifica continuidad exacta desde idx_bloque sin reiniciar en bloque 1 y persistencia en groq_checkpoint.json."""
        transcripcion_mock = {
            "duracion": 720.0,
            "segmentos": [{"start": 0.0, "end": 10.0, "text": "Texto"}],
            "palabras": [],
            "indices_picos": [],
        }
        bloques_mock = [
            {"offset_seg": 0.0, "duracion_bloque": 360.0, "texto": "[00:00:00] Bloque 1"},
            {"offset_seg": 335.0, "duracion_bloque": 360.0, "texto": "[00:00:00] Bloque 2"},
        ]
        resp_b1 = json.dumps({"clips": [{"inicio": "00:00:10", "fin": "00:00:30", "titulo": "Clip B1"}]})
        resp_b2 = json.dumps({"clips": [{"inicio": "00:00:15", "fin": "00:00:35", "titulo": "Clip B2"}]})
        err_404 = urllib.error.HTTPError(
            url="https://api.groq.com/openai/v1/chat/completions",
            code=404,
            msg="Not Found",
            hdrs=None,
            fp=io.BytesIO(b'{"error":{"message":"model_not_found"}}'),
        )

        llamadas = []

        def fake_chat(api_key, modelo, prompt):
            llamadas.append(modelo)
            if len(llamadas) == 1:
                return resp_b1
            if len(llamadas) == 2:
                raise err_404
            return resp_b2

        with (
            patch.object(pvc, "_transcribir_audio_groq", return_value=transcripcion_mock),
            patch.object(pvc, "_segmentar_transcripcion_para_ollama", return_value=bloques_mock),
            patch.object(pvc, "_llamar_groq_chat", side_effect=fake_chat),
        ):
            clips = pvc.analizar_con_groq(
                ruta_audio=str(self.fake_audio),
                duracion_total=720.0,
                job_dir=self.job_dir,
                groq_api_key="gsk_test_cont",
                pausa_entre_bloques=0.0,
            )

        # Solo 3 llamadas: B1 con modelo 1, B2 falla con modelo 1, B2 con modelo 2 (no reinicia B1)
        self.assertEqual(len(llamadas), 3)
        self.assertEqual(llamadas[0], pvc.GROQ_MODELOS_CANDIDATOS[0])
        self.assertEqual(llamadas[1], pvc.GROQ_MODELOS_CANDIDATOS[0])
        self.assertEqual(llamadas[2], pvc.GROQ_MODELOS_CANDIDATOS[1])
        self.assertEqual(len(clips), 2)

        ckpt_path = self.job_dir / "groq_checkpoint.json"
        self.assertTrue(ckpt_path.exists())
        ckpt = json.loads(ckpt_path.read_text(encoding="utf-8"))
        self.assertIsInstance(ckpt, list)
        self.assertEqual(len(ckpt), 2)

    def test_groq_validacion_temporal_dual_y_bloque_vacio(self) -> None:
        """Verifica aceptación de timestamps relativos/absolutos y manejo limpio de bloques vacíos ([])."""
        transcripcion_mock = {
            "duracion": 1000.0,
            "segmentos": [{"start": 0.0, "end": 10.0, "text": "Intro"}],
            "palabras": [],
            "indices_picos": [],
        }
        bloques_mock = [
            {"offset_seg": 0.0, "duracion_bloque": 360.0, "texto": "[00:00:00] Intro tranquila"},
            {"offset_seg": 335.0, "duracion_bloque": 360.0, "texto": "[00:00:00] Climax"},
        ]
        resp_vacio = json.dumps({"clips": []})
        resp_dual = json.dumps({
            "clips": [
                {"inicio": "00:00:10", "fin": "00:00:30", "titulo": "Relativo"},
                {"inicio": "00:07:00", "fin": "00:07:20", "titulo": "Absoluto"},
            ]
        })
        logs = []

        with (
            patch.object(pvc, "_transcribir_audio_groq", return_value=transcripcion_mock),
            patch.object(pvc, "_segmentar_transcripcion_para_ollama", return_value=bloques_mock),
            patch.object(pvc, "_llamar_groq_chat", side_effect=[resp_vacio, resp_dual]),
        ):
            clips = pvc.analizar_con_groq(
                ruta_audio=str(self.fake_audio),
                duracion_total=1000.0,
                job_dir=self.job_dir,
                groq_api_key="gsk_test_dual",
                pausa_entre_bloques=0.0,
                on_log=logs.append,
            )

        self.assertTrue(any("Bloque 1/2 sin momentos virales detectados" in m for m in logs))
        self.assertEqual(len(clips), 2)
        self.assertEqual(clips[0]["inicio"], "00:05:45")  # 335 + 10 = 345s
        self.assertEqual(clips[1]["inicio"], "00:07:00")  # 420s absoluto

    def test_groq_sin_response_format_y_salto_http_400(self) -> None:
        """Verifica ausencia de response_format en payload Groq y salto limpio ante HTTP 400."""
        fake_resp = _FakeHTTPResponse({"choices": [{"message": {"content": '{"clips": []}'}}]})
        with patch("urllib.request.urlopen", return_value=fake_resp) as mock_urlopen:
            pvc._llamar_groq_chat("gsk_key", "openai/gpt-oss-20b", "hola")
            req = mock_urlopen.call_args[0][0]
            payload = json.loads(req.data.decode("utf-8"))
            self.assertNotIn("response_format", payload)
            self.assertEqual(req.headers["User-agent"], "Mozilla/5.0 (X11; Linux x86_64) KicksazosStudio/5.0")

        transcripcion_mock = {
            "duracion": 120.0,
            "segmentos": [{"start": 0.0, "end": 10.0, "text": "Clip"}],
            "palabras": [],
            "indices_picos": [],
        }
        bloques_mock = [{"offset_seg": 0.0, "duracion_bloque": 120.0, "texto": "[00:00:00] Clip"}]
        err_400 = urllib.error.HTTPError(
            url="https://api.groq.com/openai/v1/chat/completions",
            code=400,
            msg="Bad Request",
            hdrs=None,
            fp=io.BytesIO(b'{"error":{"code":"json_validate_failed"}}'),
        )
        resp_ok = json.dumps({"clips": [{"inicio": "00:00:05", "fin": "00:00:25", "titulo": "OK"}]})

        with (
            patch.object(pvc, "_transcribir_audio_groq", return_value=transcripcion_mock),
            patch.object(pvc, "_segmentar_transcripcion_para_ollama", return_value=bloques_mock),
            patch.object(pvc, "_llamar_groq_chat", side_effect=[err_400, resp_ok]),
        ):
            clips = pvc.analizar_con_groq(
                ruta_audio=str(self.fake_audio),
                duracion_total=120.0,
                job_dir=self.job_dir,
                groq_api_key="gsk_test_400",
                pausa_entre_bloques=0.0,
            )
        self.assertEqual(len(clips), 1)

    def test_ollama_respaldo_ligero_y_timeout_300s(self) -> None:
        """Verifica modelo local ligero qwen3:8b por defecto y timeout de 300s en Ollama."""
        self.assertEqual(pvc.MODELOS_LOCALES_OLLAMA[0], "gemma3:12b")
        fake_resp = _FakeHTTPResponse(b'{"message":{"content":"{\\"clips\\":[]}"},"done":true}\n')
        with patch("urllib.request.urlopen", return_value=fake_resp) as mock_urlopen:
            pvc._llamar_ollama_chat("qwen3:8b", "hola")
            self.assertEqual(mock_urlopen.call_args[1]["timeout"], 300.0)


if __name__ == "__main__":
    unittest.main()
