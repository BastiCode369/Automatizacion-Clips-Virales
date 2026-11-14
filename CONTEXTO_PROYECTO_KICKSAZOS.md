# CONTEXTO TÉCNICO Y OPERATIVO DEL PROYECTO KICKSAZOS (v5.0)

> **Documento de Referencia Rápida y System Context Maestro (v5.0 Desktop Qt6)**
> **Propósito:** Brindar a cualquier agente de inteligencia artificial o desarrollador el entendimiento unificado del flujo de datos, arquitectura modular, contratos Pydantic y estado operativo sin necesidad de explorar el repositorio desde cero.
> **Regla Crítica de Seguridad (Zero-Secrets):** Ningún secreto, API Key ni credencial OAuth debe exponerse. Variables de entorno sensibles y tokens se identifican estrictamente como `<REDACTED>`.

---

## Índice General

1. [Resumen Ejecutivo y Arquitectura Híbrida](#1-resumen-ejecutivo-y-arquitectura-híbrida)
2. [Entorno, Stack y Credenciales](#2-entorno-stack-y-credenciales)
3. [Mapa de Archivos y Módulos](#3-mapa-de-archivos-y-módulos)
4. [Lógica Interna del Pipeline (Core Workflow)](#4-lógica-interna-del-pipeline-core-workflow)
5. [Contratos de Datos y Esquemas JSON](#5-contratos-de-datos-y-esquemas-json)
6. [Historial Operativo y Decisiones Técnicas Clave](#6-historial-operativo-y-decisiones-técnicas-clave)
7. [Estado Actual, Limitaciones Conocidas y Roadmap](#7-estado-actual-limitaciones-conocidas-y-roadmap)
8. [Referencia Rápida de Comandos para Agentes](#8-referencia-rápida-de-comandos-para-agentes)

---

## 1. Resumen Ejecutivo y Arquitectura Híbrida

**Kicksazos Studio (v5.0)** es una aplicación de escritorio nativa (PySide6 / Qt6) y pipeline audiovisual end-to-end diseñado para el ecosistema de streaming e IRL de Colombia, optimizado para producir **YouTube Shorts** y clips de **TikTok** con retención algorítmica superior.

El sistema opera mediante una **arquitectura multimotor de curaduría viral**:
- **Modo Nube Gemini (`gemini`, predeterminado):** Envía el audio extraído (12 kHz mono 24 kbps) a Google Gemini tomando **Gemini 3.5 (`gemini-3.5-flash-lite`) como modelo predeterminado oficial** (primero en `MODELOS_CANDIDATOS = ['gemini-3.5-flash-lite', 'gemini-3.8-flash', 'gemini-3.7-flash']`, CLI `--modelo` y selector UI), con cascada automática ante errores `429`, chunking paralelo (`ThreadPoolExecutor(max_workers=3)`) y renderizado en **2 pasadas con micro-alineación fonética** por clip (`_alinear_subtitulos_con_clip_renderizado`). Si se agota la cuota y `respaldo_local_auto=True`, conmuta al motor local sin abortar el job.
- **Modo Groq Nube (`groq`):** Delega la transcripción completa a Groq Cloud con `whisper-large-v3-turbo` (con timestamps por palabra y segmento, división automática sin recodificar si > 24 MB, picos vocales RMS y caché `whisper_transcript.json`), ejecuta la curaduría viral en Groq Cloud (`llama-3.3-70b-versatile` / modelos Groq) y renderiza en **1 sola pasada directa** con subtítulos sincronizados, con fallback automático a `faster-whisper` local ante error de red o cuota `429` cuando `respaldo_local_auto=True`.
- **Modo Local 100% Offline (`local`):** Transcribe el audio sin conexión externa mediante `faster-whisper` (`medium`, `int8`, CPU) asistido por decodificación directa en buffer float32 PCM (`_decodificar_audio_pcm_16k`), detecta picos vocales por energía RMS (`>= 1.65x` mediana global), libera la memoria RAM de Whisper, envía la transcripción estructurada a **Ollama** (`qwen3:14b` por defecto o `gemma3:12b` en `127.0.0.1:11434`), descarga Ollama de la RAM (`keep_alive=0`), genera bloques dinámicos de 2 a 4 palabras sincronizados desde los `word_timestamps` de Whisper y ejecuta el renderizado 9:16 en **1 sola pasada directa** con FFmpeg.
- **Aceleración y Composición Multimedia:** Detecta GPU integrada AMD Radeon 610M (`h264_vaapi` en `/dev/dri/renderD128`) con conmutación transparente a CPU (`libx264 veryfast`), aplica fondo desenfocado (`boxblur=10:2`), encuadre adaptativo de marca de agua (`y=200` o `max(200, (H-h_fg)/2-h-24)`) y subtítulos `.ass` ópticamente centrados (`WrapStyle: 0`, `Fontsize=50`, `MarginL=80`, `MarginR=170`, `MarginV=550`) utilizando la tipografía embebida `assets/fonts/Montserrat-ExtraBold.ttf` (`:fontsdir=`).
- **Aplicación de Escritorio Nativa (PySide6 / Qt6):** Sustituye por completo la interfaz web Gradio con `app_interfaz.py` + paquete modular `ui_desktop/` en estilo **Dark Studio**, barra de estado en tiempo real (Cuota YouTube `X/6`, Ollama `127.0.0.1:11434`, Encoder VAAPI/CPU) y 5 vistas integradas: Centro de Mando, Estudio de Clips con reproductor vertical 9:16 y editor rápido, Gestor de Jobs/Reanudación (`jobs/` + `job_meta.json`), Historial & Cuota YouTube y Estadísticas offline.

---

## 2. Entorno, Stack y Credenciales

### 2.1 Hardware y Sistema Operativo
- **SO:** Kubuntu Linux 64-bit (KDE Plasma / Wayland).
- **Procesador:** AMD Ryzen 5 7520U with Radeon Graphics (4C / 8T).
- **Memoria:** 16 GB LPDDR5-5500 MHz (14 GiB RAM utilizable + 8 GiB Swap en NVMe).
- **GPU:** AMD Radeon 610M (Mesa Gallium 26.0.8, VAAPI `/dev/dri/renderD128`).

### 2.2 Dependencias de Software Clave
- **Python:** 3.14.4 en `/home/bastiboy/clips_automation/venv`.
- **FFmpeg:** 8.0.1 (soporte VAAPI, libass con fontsdir, progress pipe:1).
- **yt-dlp:** 2026.10.26 (soporte Node.js runtime para JavaScript de YouTube y Kick).
- **Ollama:** Servidor local en `http://127.0.0.1:11434` con detección dinámica de modelos (`qwen3:14b`, `gemma3:12b`).
- **Bibliotecas Python:** `google-genai>=3.0.0`, `pydantic>=2.14`, `PySide6>=6.8.0` (`6.12.0` instalado), `faster-whisper>=1.1.0`, `google-api-python-client>=2.201`, `google-auth>=2.62`, `python-dotenv>=1.2`.

### 2.3 Seguridad y Credenciales (Zero-Secrets)
- `.env`: Contiene `GEMINI_API_KEY=<REDACTED>` (y opcionalmente `GROQ_API_KEY=<REDACTED>`).
- `client_secret.json`: Credenciales de la aplicación OAuth 2.0 (`installed`) de Google Cloud Platform (`<REDACTED>`).
- `token.json`: Token de acceso y refresh token activo para subidas a YouTube (`<REDACTED>`).
- `token_cuenta_anterior.json`: Token OAuth archivado (`<REDACTED>`).

---

## 3. Mapa de Archivos y Módulos

- **`pipeline_viral_clips.py`:** Módulo maestro backend. Extracción de audio, curaduría multi-motor (Gemini 3.5 predeterminado, Groq nube, Whisper + Ollama local), `job_meta.json`, FFmpeg 9:16, subtítulos `.ass` v4.1, locks e interfaz CLI (`RenderizadorProgresoCLI`).
- **`app_interfaz.py`:** Punto de entrada de la aplicación de escritorio **Kicksazos Studio v5.0** (`KicksazosMainWindow(QMainWindow)` con barra lateral, barra superior de estado y `QStackedWidget` de 5 vistas).
- **`ui_desktop/`:** Paquete modular de la capa de presentación Qt6:
  - `ui_desktop/theme.py`: Tema QSS Dark Studio (`#0b0e14`, `#131822`, `#232b3a`, `#53fc18`, `#8b5cf6`, `#ff2a2a`).
  - `ui_desktop/services.py`: Servicios puros y seguros con validación anti-path-traversal (`validar_ruta_dentro_proyecto`), escaneo de `jobs/`, edición atómica de `clips.json`, packs YouTube/TikTok, exportación, historial, cuota 24h y estadísticas offline.
  - `ui_desktop/workers.py`: Hilos `QThread` (`PipelineWorker` con cancelación instantánea vía `terminar_procesos_activos()`, `SingleClipWorker` para re-renderizar o subir un único clip, y `SystemProbeWorker`).
  - `ui_desktop/widgets/`: `command_center.py`, `clips_studio.py`, `video_player.py` (`QMediaPlayer` + `QVideoWidget` + `QAudioOutput` + `xdg-open`), `jobs_manager.py`, `history_quota.py`, `stats_dashboard.py`.
- **`subir_shorts.py`:** Módulo de subida OAuth 2.0, auditoría de cuota móvil 24h (6/día) y registro en `subidas_shorts.json`.
- **`procesar_video_universal.py`:** Script auxiliar CLI para re-procesar o re-renderizar un corte específico.
- **`assets/`:** `fonts/Montserrat-ExtraBold.ttf` y `watermark.png`.
- **`tests/`:** 6 suites automatizadas (`test_pipeline_v31.py`, `test_pipeline_v32.py`, `test_pipeline_v40.py`, `test_pipeline_v41.py`, `test_pipeline_v43.py`, `test_desktop_v50.py` y `test_groq_whisper.py`) ejecutables bajo `QT_QPA_PLATFORM=offscreen`.

---

## 4. Lógica Interna del Pipeline (Core Workflow)

```
                     [ Entrada: URL Kick/YT o Video Local ]
                                      │
           ┌──────────────────────────┴──────────────────────────┐
           ▼                                                     ▼
  [ Archivo Local ]                                       [ URL Remota ]
  FFmpeg directo mono 12k/24k                             yt-dlp 16 hilos (fallback stream FFmpeg)
           │                                                     │
           └──────────────────────────┬──────────────────────────┘
                                      ▼
                       temp_audio.mp3 (mono 12kHz 24kbps)
                                      │
         ┌────────────────────────────┴────────────────────────────┐
         ▼                                                         ▼
 [ Modo Nube: Gemini ]                                    [ Modo Local Offline ]
 - Segmentación > 30 min (chunks 25 min)                  - faster-whisper medium (CPU int8)
 - ThreadPoolExecutor(3) paralelo                         - PCM float32 16k sin PyAV
 - Cascada 3.8 -> 3.7 -> 3.5                              - Picos vocales RMS >= 1.65x mediana
 - Deduplicación de solapes > 50%                         - Caché whisper_transcript.json
 - Fallback 429 auto a local si agotado                   - del model; gc.collect()
                                                          - Ollama qwen3:14b / gemma3:12b
                                                          - keep_alive=0 RAM liberada
                                                          - Subs directos de word_timestamps
         │                                                         │
         ▼                                                         ▼
 [ Render 2 Pasadas ]                                     [ Render 1 Pasada Directa ]
 1. raw_clip_<id>.mp4 (sin subs)                          1. Corte 9:16 + watermark +
 2. Micro-alineación fonética Gemini                         subs_<id>.ass directo en FFmpeg
 3. Quemado rápido subs .ass (-c:a copy)                     (Sin raw_clip, 2x más veloz)
         │                                                         │
         └────────────────────────────┬────────────────────────────┘
                                      ▼
                 ThreadPoolExecutor(max_workers=2) VAAPI/CPU
                                      │
                                      ▼
                    Clips Finales 1080x1920 en clips_finales/
                                      │
                                      ▼
           Subida YouTube Shorts (Serializada yt_lock, máx 6/24h)
```

---

## 5. Contratos de Datos y Esquemas JSON

### 5.1 Esquema `ClipViral` (Pydantic v2)
- `id`: Entero secuencial del clip (1, 2, 3...).
- `titulo`: Título magnético CTR streamer (máximo 60 caracteres).
- `inicio` y `fin`: Timestamps exactos en formato `HH:MM:SS`.
- `gancho`: Hook de los primeros 2 segundos.
- `razon_viral`: Justificación del gatillo emocional o retención.
- `descripcion`: 2 líneas con resumen, CTA y hashtags #Shorts.
- `etiquetas`: Lista de 8 a 12 tags SEO normalizados.
- `caption_tiktok`: Texto para TikTok <= 150 caracteres para debate.
- `hashtags_tiktok`: 3 a 5 hashtags con `#`.
- `gancho_visual_portada`: Titular visual de 4 a 6 palabras en mayúsculas.
- `subtitulos`: Lista de `SegmentoSubtitulo`.

### 5.2 Esquema `SegmentoSubtitulo`
- `inicio_rel`: Segundo decimal de inicio relativo al clip (ej. 0.00).
- `fin_rel`: Segundo decimal de fin relativo al clip (ej. 1.85).
- `texto`: Transcripción de 2 a 4 palabras (máx 22 caracteres, sin emojis).

### 5.3 Contrato de Subidas (`subidas_shorts.json`)
Cada entrada contiene: `clip_id`, `archivo`, `ruta_archivo`, `youtube_id`, `url` (`https://youtube.com/shorts/<id>`), `titulo`, `descripcion`, `etiquetas`, `privacidad` (`private`), `categoryId` (`24`), `madeForKids` (`false`), `fecha_subida` (ISO 8601 local) y `cuenta_id` (SHA-256 corto).

---

## 6. Historial Operativo y Decisiones Técnicas Clave

1. **Conmutación Inmediata de Cuotas (429):** Eliminación de esperas inútiles ante códigos 429 de Gemini Free Tier; rotación instantánea de modelos y opción de respaldo automático hacia Whisper + Ollama.
2. **Solución Definitiva a PyAV >= 19:** Decodificación FFmpeg float32 directa que evita caídas del intérprete en `faster-whisper`.
3. **Renderizado en Pasada Única:** Aceleración del 50% en el tiempo de codificación durante el modo local quemando subtítulos directamente sobre el corte base.
4. **Ajuste Óptico de Subtítulos v4.1:** Establecimiento de `WrapStyle: 0`, `MarginL=80`, `MarginR=170` (margen derecho ampliado para evitar la barra de acciones de Shorts) y `MarginV=550` (elevación sobre el área de interfaz inferior).
5. **Gestión de Memoria RAM:** Descarga programada de Whisper y LLMs locales (`keep_alive=0`) antes del proceso de video, permitiendo ejecutar modelos de 14B parámetros en 16 GB de RAM.
6. **Tolerancia a Streams HLS:** Soporte para enlaces dinámicos de Kick y Twitch con reintentos e invalidación de caché ante respuestas HTTP 403 o 410.
7. **Sanitización y Protección de Rutas:** Validación estricta contra path traversal (`validar_ruta_dentro_proyecto`) y bloqueo de lectura/exposición de archivos de secretos (`.env`, `client_secret.json`, `token.json`, `token_cuenta_anterior.json`).
8. **Blindaje de Producción v4.3 + Escritorio Nativo v5.0 (PySide6 / Qt6):**
   - Escrituras atómicas thread-safe (`os.replace` + `_CLIPS_JSON_LOCK` / `_HISTORIAL_LOCK`) en `clips.json` y `subidas_shorts.json`.
   - Registro global de subprocesos (`_PROCESOS_ACTIVOS` + `start_new_session` + `os.killpg`) y `terminar_procesos_activos()` ante `Ctrl+C` o botón **Detener / Abortar** desde `PipelineWorker`.
   - Cierre explícito de `genai.Client` (`_cerrar_cliente_genai_seguro`) y liberación ordenada de `QThread` y `VerticalVideoPlayerWidget` en `KicksazosMainWindow.closeEvent()`.
   - Sustitución total de Gradio por `app_interfaz.py` + paquete modular `ui_desktop/` en tema **Dark Studio** y **Gemini 3.5** (`gemini-3.5-flash-lite`) como modelo predeterminado oficial en backend, CLI y UI.

---

## 7. Estado Actual, Limitaciones Conocidas y Roadmap

### 7.1 Estado Actual del Sistema
- **Estabilidad:** Suite automatizada de 77 tests (`unittest` bajo `QT_QPA_PLATFORM=offscreen`) incluyendo `tests/test_desktop_v50.py` cubriendo Gemini 3.5, Groq, seguridad de rutas, Estudio de Clips, Gestor de Jobs y cierre limpio Qt6.
- **Operaciones Registradas:** Historial persistido localmente en `subidas_shorts.json` y checkpoints de jobs en `jobs/<job_id>/job_meta.json`.
- **Disponibilidad:** Aplicación nativa de escritorio (`app_interfaz.py`) y CLI (`pipeline_viral_clips.py`) operativas en Kubuntu KDE/Wayland.

### 7.2 Limitaciones Conocidas
- **Cuota Diaria de YouTube:** Límite impuesto de 6 publicaciones cada 24 horas para evitar agotar las unidades gratuitas de API.
- **Velocidad de Whisper en CPU:** El modelo `medium` requiere entre 8 y 12 minutos para transcribir streams de 2 horas en procesadores de 4 núcleos.

### 7.3 Roadmap de Evolución
- [ ] Incorporación de aceleración Vulkan / ROCm para inferencia de Whisper en GPUs integradas AMD.
- [ ] Cola de trabajos persistente SQLite para encolado secuencial de múltiples URLs.
- [ ] Conector directo con la API de TikTok para publicación automatizada de borradores.

---

## 8. Referencia Rápida de Comandos para Agentes

```bash
# Directorio base y entorno virtual
cd /home/bastiboy/clips_automation && source venv/bin/activate

# Ejecutar suite de pruebas completa (modo offscreen Qt6)
QT_QPA_PLATFORM=offscreen venv/bin/python -m unittest discover -s tests -v

# Ejecutar pipeline completo en modo Nube (Gemini 3.5 predeterminado)
venv/bin/python pipeline_viral_clips.py "https://kick.com/eldomi/videos/<uuid>"

# Ejecutar pipeline en modo Groq Nube o 100% Local Offline (Whisper + Ollama)
venv/bin/python pipeline_viral_clips.py "https://kick.com/eldomi/videos/<uuid>" --motor groq
venv/bin/python pipeline_viral_clips.py "https://kick.com/eldomi/videos/<uuid>" --motor local --modelo-local qwen3:14b

# Reanudar un job interrumpido desde checkpoints (--job-dir)
venv/bin/python pipeline_viral_clips.py "https://kick.com/eldomi/videos/<uuid>" --job-dir jobs/<job_id>

# Procesar video local sin subida a YouTube
venv/bin/python pipeline_viral_clips.py "/ruta/al/video.mp4" --motor local --sin-subida

# Iniciar aplicación de escritorio nativa Kicksazos Studio v5.0 (PySide6 / Qt6)
venv/bin/python app_interfaz.py
```
