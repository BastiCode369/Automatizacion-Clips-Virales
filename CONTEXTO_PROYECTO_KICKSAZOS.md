# CONTEXTO TÉCNICO Y OPERATIVO DEL PROYECTO KICKSAZOS (v4.1)

> **Documento de Referencia Rápida y System Context Maestro (v4.1)**
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

**Kicksazos (v4.1)** es un pipeline audiovisual end-to-end diseñado para el ecosistema de streaming e IRL de Colombia (Kick Colombia: WestCOL, Blessd, La Liendra, eldomi, Yhap, peleas, eventos y anécdotas callejeras), optimizado para producir **YouTube Shorts** y clips de **TikTok** con retención algorítmica superior.

El sistema opera mediante un **motor híbrido dual de curaduría audiovisual**:
- **Modo Nube (`gemini`):** Envía el audio extraído (12 kHz mono 24 kbps) a la File API de Google Gemini (familia Gemini 3: `gemini-3.8-flash`, `gemini-3.7-flash`, `gemini-3.5-flash-lite`). Procesa audios largos mediante chunking paralelo (`ThreadPoolExecutor(max_workers=3)`) y realiza un renderizado en **2 pasadas con micro-alineación fonética** por clip (`_alinear_subtitulos_con_clip_renderizado`). Si la cuota diaria Free Tier (`429`) se agota en toda la cascada y `respaldo_local_auto=True`, conmuta automáticamente al motor local sin abortar el job.
- **Modo Local 100% Offline (`local`):** Transcribe el audio sin conexión externa mediante `faster-whisper` (`medium`, `int8`, CPU) asistido por decodificación directa en buffer float32 PCM (`_decodificar_audio_pcm_16k`), detecta picos vocales por energía RMS (`>= 1.65x` mediana global), libera la memoria RAM de Whisper, envía la transcripción estructurada a **Ollama** (`qwen3:14b` por defecto o `gemma3:12b` en `127.0.0.1:11434`), descarga Ollama de la RAM (`keep_alive=0`), genera bloques dinámicos de 2 a 4 palabras sincronizados desde los `word_timestamps` de Whisper y ejecuta el renderizado 9:16 en **1 sola pasada directa** con FFmpeg.
- **Aceleración y Composición Multimedia:** Detecta GPU integrada AMD Radeon 610M (`h264_vaapi` en `/dev/dri/renderD128`) con conmutación transparente a CPU (`libx264 veryfast`), aplica fondo desenfocado (`boxblur=10:2`), encuadre adaptativo de marca de agua (`y=200` o `max(200, (H-h_fg)/2-h-24)`) y subtítulos `.ass` ópticamente centrados (`WrapStyle: 0`, `Fontsize=50`, `MarginL=80`, `MarginR=170`, `MarginV=550`) utilizando la tipografía embebida `assets/fonts/Montserrat-ExtraBold.ttf` (`:fontsdir=`).
- **Publicación Segura y Command Center:** Sube clips a YouTube Shorts bajo exclusión mutua (`yt_lock`), respeta el límite de cuota (6 subidas/24h) y se administra desde la interfaz web Gradio 6.31 (`app_interfaz.py`) de 4 pestañas interactivas con telemetría multi-hilo en vivo.

---

## 2. Entorno, Stack y Credenciales

### 2.1 Hardware y Sistema Operativo
- **SO:** Kubuntu Linux 64-bit (kernel 6.11 / 7.0).
- **Procesador:** AMD Ryzen 5 7520U with Radeon Graphics (4C / 8T).
- **Memoria:** 16 GB LPDDR5-5500 MHz (14 GiB RAM utilizable + 8 GiB Swap en NVMe).
- **GPU:** AMD Radeon 610M (Mesa Gallium 26.0.8, VAAPI `/dev/dri/renderD128`).

### 2.2 Dependencias de Software Clave
- **Python:** 3.14.4 en `/home/bastiboy/clips_automation/venv`.
- **FFmpeg:** 8.0.1 (soporte VAAPI, libass con fontsdir, progress pipe:1).
- **yt-dlp:** 2026.10.26 (soporte Node.js runtime para JavaScript de YouTube y Kick).
- **Ollama:** Servidor local en `http://127.0.0.1:11434` con modelos `qwen3:14b` (9.3 GB) y `gemma3:12b` (8.2 GB).
- **Bibliotecas Python:** `google-genai>=3.0.0`, `pydantic>=2.14`, `gradio>=6.31`, `faster-whisper>=1.1.0`, `google-api-python-client>=2.201`, `google-auth>=2.62`, `python-dotenv>=1.2`.

### 2.3 Seguridad y Credenciales (Zero-Secrets)
- `.env`: Contiene `GEMINI_API_KEY=<REDACTED>` y parámetros del canal.
- `client_secret.json`: Credenciales de la aplicación OAuth 2.0 (`installed`) de Google Cloud Platform (`<REDACTED>`).
- `token.json`: Token de acceso y refresh token activo para subidas a YouTube (`<REDACTED>`).
- `token_cuenta_anterior.json`: Token OAuth archivado (`<REDACTED>`).

---

## 3. Mapa de Archivos y Módulos

- **`pipeline_viral_clips.py`:** Módulo maestro (5.162 líneas). Contiene la lógica de extracción de audio, curaduría híbrida (Gemini multimodal y Whisper + Ollama local), composición de video FFmpeg 9:16 (1 pasada y 2 pasadas), generación de subtítulos ASS v4.1, orquestación paralela con locks e interfaz de línea de comandos (`RenderizadorProgresoCLI`).
- **`app_interfaz.py`:** Interfaz web de broadcast (2.651 líneas) construida sobre Gradio 6.31. Expone 4 pestañas: Centro de Mando con alternancia de motores, Galería de Clips con metadatos duales para YouTube Shorts y TikTok, Historial con medidor de cuota de 24 horas y Panel de Rendimiento y Estadísticas del Sistema.
- **`subir_shorts.py`:** Módulo de subida y auditoría (428 líneas). Maneja el flujo OAuth 2.0, hash identificador de cuenta (`obtener_hash_cuenta`), control de cuota diaria (máx 6 subidas en 24h móviles), subidas resumables con backoff y persistencia en `subidas_shorts.json`.
- **`procesar_video_universal.py`:** Script auxiliar de conveniencia (22 líneas) para re-procesar o re-renderizar un corte específico con timestamps exactos.
- **`assets/fonts/Montserrat-ExtraBold.ttf`:** Tipografía oficial que libass embebe automáticamente en los subtítulos mediante `:fontsdir=`.
- **`assets/watermark.png`:** Logotipo oficial de Kicksazos escalado a 420 px con canal alfa del 92%.
- **`tests/`:** 4 suites automatizadas con 64 pruebas unitarias (`test_pipeline_v31.py`, `test_pipeline_v32.py`, `test_pipeline_v40.py`, `test_pipeline_v41.py`) con cobertura 100% exitosa.

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
7. **Sanitización HTML Total:** Prevención de inyección XSS mediante `html.escape()` en todos los componentes de la interfaz de usuario.

---

## 7. Estado Actual, Limitaciones Conocidas y Roadmap

### 7.1 Estado Actual del Sistema
- **Estabilidad:** 100% de la suite de pruebas unitarias superada (64/64 tests OK).
- **Operaciones Registradas:** 13 shorts publicados exitosamente en YouTube y 24 clips renderizados en alta definición vertical en disco.
- **Disponibilidad:** Servidor web activo en puerto 7860 y CLI listo para procesamiento autónomo.

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

# Ejecutar suite de pruebas completa
venv/bin/python -m unittest discover -s tests -v

# Ejecutar pipeline completo en modo Nube (Gemini)
venv/bin/python pipeline_viral_clips.py "https://kick.com/eldomi/videos/<uuid>"

# Ejecutar pipeline en modo 100% Local Offline (Whisper + Ollama)
venv/bin/python pipeline_viral_clips.py "https://kick.com/eldomi/videos/<uuid>" --motor local --modelo-local qwen3:14b

# Procesar video local sin subida a YouTube
venv/bin/python pipeline_viral_clips.py "/ruta/al/video.mp4" --motor local --sin-subida

# Iniciar Command Center Web (Gradio 6.31)
venv/bin/python app_interfaz.py
```
