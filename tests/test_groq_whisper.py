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


if __name__ == "__main__":
    unittest.main()
