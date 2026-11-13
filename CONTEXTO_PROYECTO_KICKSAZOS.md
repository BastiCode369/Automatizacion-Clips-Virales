# CONTEXTO_PROYECTO_KICKSAZOS.md — System Context (Base de Conocimiento Maestra)

> **Actualizado (v3.2 — Tipografía Embebida de Alta Precisión & Telemetría Gráfica en Vivo):** 2026-11-13 00:05 (-05:00) mediante empaquetado local de tipografía ExtraBold (`assets/fonts/Montserrat-ExtraBold.ttf` + `fontsdir=` en `libass`), refinamiento tipográfico `.ass` (`WrapStyle: 2`, mayúsculas automáticas, tracking `1.5`, `Fontsize=54`, `MarginV=550`), y telemetría estructurada en vivo (`yt-dlp --newline`, bloques Gemini y `ffmpeg -progress pipe:1`) renderizada con panel HTML/CSS animado en Gradio (`app_interfaz.py`) y barra visual en CLI (`RenderizadorProgresoCLI`).
> **Propósito:** que cualquier agente de IA entienda el código, el flujo de datos, los contratos y el estado real del sistema **sin explorar desde cero**.
> **Fuente de verdad:** el código fuente. El archivo previo `Contexto y Objetivos del Proyecto Kicksazos.md` contiene afirmaciones **que no coinciden con el código** (ver §6.4).
> **Seguridad:** todos los secretos aparecen como `<REDACTED>`. Nunca imprimir el contenido de `.env`, `client_secret.json`, `token.json` ni `token_cuenta_anterior.json`.

---

## Índice

1. [Resumen Ejecutivo y Propósito del Sistema](#1-resumen-ejecutivo-y-propósito-del-sistema)
2. [Entorno, Dependencias y Credenciales](#2-entorno-dependencias-y-credenciales)
3. [Mapa de Archivos y Arquitectura Modular](#3-mapa-de-archivos-y-arquitectura-modular)
4. [Lógica Interna Detallada (Core Logic)](#4-lógica-interna-detallada-core-logic)
5. [Contratos de Datos y Esquemas JSON](#5-contratos-de-datos-y-esquemas-json)
6. [Historial de Decisiones Técnicas y Problemas Resueltos](#6-historial-de-decisiones-técnicas-y-problemas-resueltos)
7. [Estado Actual, Limitaciones Conocidas y Roadmap](#7-estado-actual-limitaciones-conocidas-y-roadmap)
8. [Apéndice: Referencia Rápida para Agentes](#8-apéndice-referencia-rápida-para-agentes)

---

## 1. Resumen Ejecutivo y Propósito del Sistema

**Kicksazos** es un pipeline autónomo en Python que:

1. Recibe una URL (VOD/stream/video de **Kick**, YouTube o Twitch) y crea un contexto aislado en `jobs/<job_id>/`.
2. Extrae una pista de **audio mono 16 kHz / 32 kbps** mediante descarga paralela agresiva con `yt-dlp --newline` (`--concurrent-fragments 16`, reintentos con backoff y `aria2c` opcional fuera de Kick/Twitch/HLS `.m3u8`), emitiendo telemetría en vivo (MB/s, %, ETA, fragmentos) con fallback automático a `yt-dlp -g` + `ffmpeg -vn -reconnect* -progress pipe:1`.
3. Si el audio supera **55 min (`> 3300 s`)**, lo segmenta sin re-codificar (`ffmpeg -c copy`) en bloques de **45 min (`2700 s`)** con **90 s de solapamiento** (`temp_audio_chunk_*.mp3`); sube cada bloque a la **Gemini File API** y pide a la cascada de modelos (con salto `0s` ante cuota diaria Free Tier `429`, `temperature=0.20`, telemetría por bloque/modelo y cantidad 100% dinámica según calidad) **timestamps + metadatos SEO multiplataforma + transcripción fonética forense en `subtitulos`**, ajustando offsets y deduplicando solapamientos antes de guardar `clips.json`.
4. Renderiza cada momento en **vertical 9:16 (1080×1920)** con FFmpeg + `-progress pipe:1` (telemetría en vivo de FPS, velocidad `x`, ETA y encoder activo; acelerado por hardware **VAAPI** `h264_vaapi` en `/dev/dri/renderD128` con fallback automático a CPU `libx264`): fondo desenfocado + video centrado sin recorte + marca de agua adaptativa `assets/watermark.png` + subtítulos dinámicos quemados con **tipografía local embebida** (`assets/fonts/Montserrat-ExtraBold.ttf` inyectada vía `:fontsdir=`, `WrapStyle: 2`, tamaño `54`, `Outline=5.5`, `Shadow=3.5`, `Spacing=1.5`, `BackColour=&HA0000000`, `MarginL=65`, `MarginR=210`, `MarginV=550`, mayúsculas automáticas, auto-partición 2–4 palabras y efecto *pop-in*).
5. Sube cada clip a **YouTube Shorts** (privado inmediato o programado con `publishAt` ISO 8601 UTC, con control de cuota diaria ~6 uploads/24h, hash de canal/cuenta `cuenta_id` y reintentos resumables) y registra la trazabilidad en `subidas_shorts.json`.

**Nicho objetivo:** clips IRL / streaming colombiano (Kick Colombia: WestCOL, Blessd, La Liendra, Yhap, eldomi, etc.). Canal destino: **Kicksazos**. Idioma: español coloquial colombiano.

**Puntos de entrada:**

| Entrada | Comando | Uso |
|---|---|---|
| CLI E2E | `venv/bin/python pipeline_viral_clips.py "<URL>" [--solo-analisis] [--sin-subida] [--modelo <id>] [--publish-at "YYYY-MM-DD HH:MM"] [--intervalo-horas <N>]` | Pipeline completo headless consumiendo el orquestador unificado |
| GUI Gradio | `venv/bin/python app_interfaz.py` → `http://127.0.0.1:7860` | Mismo generador central con progreso en tiempo real, programación, galería e historial sanitizados |
| Render manual de 1 clip | `venv/bin/python procesar_video_universal.py <URL\|archivo> <HH:MM:SS> <HH:MM:SS> <ID> [JOB_ID]` | Re-render puntual |
| Upload de prueba | `venv/bin/python subir_shorts.py` | OAuth interactivo + sube el 1er `.mp4` de `clips_finales/` con metadatos de prueba |

### 1.1 Diagrama de arquitectura (ASCII)

```
                ┌──────────────────────────────────────────────────────────────┐
                │           ENTRADA: URL (Kick / YouTube / Twitch)             │
                │   CLI: pipeline_viral_clips.py main()                        │
                │   GUI: app_interfaz.py ejecutar_pipeline_gradio()            │
                └───────────────────────────────┬──────────────────────────────┘
                                                │
        [1/4] extraer_audio(url, job_dir)       ▼
        1) Primario: yt-dlp --concurrent-fragments 16 (+ aria2c si no HLS/Kick/Twitch)
           -f ba/worst[height<=360] -x mp3 (-vn -ac 1 -ar 16000 -b:a 32k), valida >10 KB
        2) Fallback: yt-dlp -g → ffmpeg (-reconnect* -vn -ac 1 -ar 16000 -b:a 32k)
           ──► jobs/<job_id>/temp_audio.mp3
                                                │
        obtener_duracion_media() (ffprobe) ──►  duracion_total (float s)
                                                │
        [2/4] analizar_con_gemini()             ▼
        ┌───────────────────────────────────────────────────────────────┐
        │ _segmentar_audio_en_chunks (>3300s → bloques 2700s, ovlp 90s) │
        │ genai.Client(timeout=600 000 ms)                              │
        │ Por cada chunk (_analizar_archivo_audio_gemini):              │
        │   files.upload (4 reintentos) + polling ACTIVE                │
        │   CASCADA: [preferido] + MODELOS_CANDIDATOS (4 intentos c/u)  │
        │   - 429 cuota diaria Free Tier → break 0.00s inmediato        │
        │   - 429 RPM/TPM o 503 → backoff con jitter (4s..25s)          │
        │   generate_content_stream(schema=list[ClipViral], temp=0.20)  │
        │   _limpiar_y_parsear_json(permitir_vacio=True) + auto-split   │
        │   finally: files.delete (remoto)                              │
        │ Ajuste +offset_seg en inicio/fin + _deduplicar_clips_solapados│
        │ Reasignación secuencial de id (1..N) + limpieza chunks .mp3   │
        └───────────────────────────────┬───────────────────────────────┘
                                        ▼
                jobs/<job_id>/clips.json + ./clips.json (v3.1: cantidad dinámica + subs 2-4p)
                                        │
        [3/4] Render                    ▼
        ¿duracion_total ≤ 3600 s? ── sí ─► descargar_video_fuente() → jobs/<job_id>/temp_source.mp4
                 │ no / fallo                                         │
                 ▼                                                    │
        obtener_urls_stream(url, job_id) + STREAM_URL_CACHE           │
        (invalidación y reintento ante HTTP 403/410)                  │
                 └──────────────────────┬─────────────────────────────┘
                                        ▼
        procesar_clip_ffmpeg() por clip:
        ├─ ffprobe dimensiones → watermark adaptativa (y dinámica o y=60 en 9:16)
        ├─ generar_archivo_ass() → jobs/<job_id>/subs_<id>.ass (si hay subtítulos)
        ├─ -ss <inicio> -t <duracion> (corte exacto) + filter_complex 9:16 + subtitles=
        └─ detectar_encoder_hardware(): h264_vaapi (/dev/dri/renderD128, nv12,hwupload, -qp 23)
           con fallback automático a libx264 (-preset veryfast -crf 22) y fallback sin subs
           ──►  ./clips_finales/<job_id>_clip_<id>.mp4  (1080x1920 H.264/AAC)
                                        │
        [4/4] Upload (si habilitado)    ▼
        autenticar_youtube(interactivo=False) → token.json (refresh auto)
        subir_short() → videos.insert(part=snippet,status, resumable)
                  privacy=private, categoryId=24, madeForKids=False
                                        │
                ┌───────────────────────┴───────────────────────┐
                ▼                                               ▼
     ./subidas_shorts.json (append/dedupe por youtube_id)   clips.json (v2: + archivo_local,
                                                             youtube_id, youtube_url, youtube_status)
        Limpieza (finally): invalida STREAM_URL_CACHE[job_id], borra temp_audio.mp3 y temp_source.mp4
```

---

## 2. Entorno, Dependencias y Credenciales

### 2.1 Sistema

| Componente | Versión detectada | Notas |
|---|---|---|
| SO | Kubuntu Linux | Directorio raíz: `/home/bastiboy/clips_automation` |
| Python (sistema y `venv/`) | **3.14.4** | Usa sintaxis `str \| int` (PEP 604) → requiere ≥3.10 |
| FFmpeg / ffprobe | **8.0.1-3ubuntu2** (`/usr/bin/ffmpeg`) | libx264 + aac nativos |
| yt-dlp | **2026.10.26** (pip en venv **y** `/usr/local/bin/yt-dlp`) | Invocado vía **`sys.executable -m yt_dlp`** con aislamiento por job |
| Node.js | **v22.22.1** (`/usr/bin/node`) | Requerido por `--js-runtimes node --remote-components ejs:github` (resolución de firmas JS de YouTube) |
| Git | **Inicializado** (`.git/` presente) | Protegido con `.gitignore` estricto (credenciales, artefactos, temporales) |
| `requirements.txt` | **Creado en la raíz** | Contiene dependencias fijas y actualizadas del proyecto |

### 2.2 Librerías clave del `venv/` (pip list)

| Paquete | Versión | Uso en el código |
|---|---|---|
| `google-genai` | 3.0.0 | `from google import genai`, `types`, `errors.APIError/ServerError` |
| `pydantic` / `pydantic_core` | 2.14.3 / 2.50.4 | `ClipViral`, `TypeAdapter(List[ClipViral])` |
| `gradio` (+ `gradio_client`) | 6.31.0 (2.7.2) | `app_interfaz.py` |
| `google-api-python-client` | 2.201.0 | `googleapiclient.discovery.build`, `MediaFileUpload` |
| `google-auth` / `google-auth-oauthlib` / `google-auth-httplib2` | 2.62.1 / 1.5.0 / 0.4.4 | OAuth `InstalledAppFlow`, `Credentials`, `Request` |
| `python-dotenv` | 1.2.4 | `load_dotenv(BASE_DIR / ".env")` |
| `yt-dlp` | 2026.10.26 | Ejecutado como módulo vía subprocess con soporte de jobs |
| `fastapi` / `uvicorn` / `httpx` | 0.162.2 / 0.54.0 / 0.28.1 | Transitivas de Gradio / genai |
| `av` (PyAV) | **Desinstalado** | Eliminado en la Fase 1 para limpieza de entorno |
| `faster-whisper` / `openai-whisper` | **Desinstalados** | Eliminados en la Fase 1 para liberar espacio y dependencias innecesarias |

**`requirements.txt` activo en la raíz:**
```
google-genai>=3.0.0
pydantic>=2.14
gradio>=6.31
google-api-python-client>=2.201
google-auth>=2.62
google-auth-oauthlib>=1.5
python-dotenv>=1.2
yt-dlp>=2026.10.26
```

### 2.3 Variables de entorno

| Variable | Requerida | Dónde se lee | Notas |
|---|---|---|---|
| `GEMINI_API_KEY` | **Sí** | `.env` (vía `load_dotenv()`), `os.environ` | Valor: `<REDACTED>`. La GUI permite sobrescribirla en runtime (campo password → `os.environ["GEMINI_API_KEY"]`, persiste en el proceso) |
| `GEMINI_MODEL` | No | Solo en `pipeline_viral_clips.py.bak` (legacy) | Ya no se usa; ahora es `--modelo` / dropdown |

`.env` contiene **una única variable**: `GEMINI_API_KEY=<REDACTED>`.

> ⚠️ `analizar_stream.py` **no** llama a `load_dotenv()`: requiere `export GEMINI_API_KEY=...` en la shell.

### 2.4 Credenciales OAuth (YouTube Data API v3)

| Archivo | Contenido (estructura) | Rol |
|---|---|---|
| `client_secret.json` | `{"installed": {"client_id": <REDACTED>, "project_id": "kick-clips-auto-514009", "auth_uri", "token_uri", "auth_provider_x509_cert_url", "client_secret": <REDACTED>, "redirect_uris": ["http://localhost"]}}` | Cliente OAuth tipo **Desktop/Installed App** del proyecto GCP `kick-clips-auto-514009` |
| `token.json` | `{"token": <REDACTED>, "refresh_token": <REDACTED>, "token_uri", "client_id", "client_secret", "scopes": ["https://www.googleapis.com/auth/youtube.upload"], "universe_domain": "googleapis.com", "account": "", "expiry": "2026-11-12T02:48:58Z"}` | Token **activo** (cuenta/canal NUEVO). Generado/reescrito 2026-11-11 20:48 |
| `token_cuenta_anterior.json` | Misma estructura, `expiry 2026-11-12T02:47:52Z` | Respaldo manual del token de la **cuenta anterior** (no lo lee ningún script) |

- **Scope único:** `https://www.googleapis.com/auth/youtube.upload` (no permite listar/editar videos, playlists ni thumbnails).
- Constantes en `subir_shorts.py`: `CLIENT_SECRETS_FILE = BASE_DIR / "client_secret.json"`, `TOKEN_FILE = BASE_DIR / "token.json"`, `HISTORIAL_SUBIDAS_FILE = BASE_DIR / "subidas_shorts.json"` — **rutas absolutas ancladas a `BASE_DIR`**.

> 🔐 Repositorio Git inicializado y protegido por `.gitignore`: excluye `.env`, `client_secret.json`, `token*.json`, `venv/`, `jobs/`, `clips_finales/*.mp4`, `clips_virales/`, `temp_*`, `*.part`, `*.ytdl` y `gradio.log`.

---

## 3. Mapa de Archivos y Arquitectura Modular

### 3.1 Árbol (excluye `venv/`, `__pycache__/`, `jobs/`; medios pesados resumidos)

```
~/clips_automation/                          (≈300 MB sin venv ni jobs)
├── .env                                     # GEMINI_API_KEY=<REDACTED>
├── .gitignore                               # Reglas de exclusión de credenciales, temporales y medios
├── requirements.txt                         # Dependencias activas del proyecto
├── app_interfaz.py                          # [ACTIVO] GUI Gradio (1350+ líneas) con panel de telemetría animado e historial
├── pipeline_viral_clips.py                  # [ACTIVO] Núcleo v3.2 + telemetría en vivo + CLI RenderizadorProgresoCLI
├── subir_shorts.py                          # [ACTIVO] OAuth + upload YouTube + historial anclado a BASE_DIR
├── procesar_video_universal.py              # [ACTIVO] Wrapper CLI de render con BASE_DIR y soporte de job_id
├── client_secret.json                       # OAuth client (<REDACTED>)
├── token.json                               # OAuth token activo (<REDACTED>)
├── token_cuenta_anterior.json               # Backup token cuenta anterior (<REDACTED>)
├── clips.json                               # Estado: último análisis sincronizado
├── subidas_shorts.json                      # Estado: historial acumulado de subidas (7 registros)
├── gradio.log                               # Log local previo (ignorado por git)
├── Contexto y Objetivos del Proyecto Kicksazos.md   # Doc previo
├── CONTEXTO_PROYECTO_KICKSAZOS.md           # ESTE documento (actualizado v3.2)
├── CEREBRO_COMPLETO_KICKSAZOS.md            # Dossier técnico maestro completo (actualizado v3.2)
├── assets/
│   ├── fonts/
│   │   └── Montserrat-ExtraBold.ttf         # Tipografía ExtraBold embebida (inyectada vía fontsdir= en libass)
│   ├── watermark.png                        # 946×262 RGBA (marca de agua @Kicksazos)
│   └── Gemini_Generated_Image_qk0ar5qk0ar5qk0a.jpeg  # Arte de marca
├── tests/
│   ├── test_pipeline_v31.py                 # Suite unitaria v3.1 (16 tests offline + smoke FFmpeg/libass)
│   └── test_pipeline_v32.py                 # Suite unitaria v3.2 (14 tests tipografía fontsdir, telemetría y Gradio)
├── clips_finales/                           # Salida del pipeline ACTIVO: <job_id>_clip_<id>.mp4
│   ├── clip_1.mp4 … clip_5.mp4              # 1080x1920 @60fps (runs históricos)
│   └── clip_6.mp4                           # 1080x1920 @23.976fps
├── jobs/                                    # Aislamiento de ejecuciones por job_id (ignorado en git)
│   └── <job_id>/                            # YYYYMMDD_HHMMSS_<slug>/ con temp_audio.mp3, temp_source.mp4, clips.json
└── legacy/                                  # Scripts y artefactos obsoletos archivados
    ├── pipeline_viral_clips.py.bak          # Pipeline v1
    ├── analizar_stream.py                   # Prototipo Gemini hardcodeado
    ├── recortar_clips.py                    # Prototipo render hardcodeado
    ├── subir_lote.py                        # Upload legacy
    └── clips_virales/                       # Salida del pipeline legacy
```

### 3.2 Grafo de dependencias internas

```
app_interfaz.py ──imports──► pipeline_viral_clips.py ──imports──► subir_shorts.py
       │                              ▲
       └──────────imports─────────────┼──────────────────────────► subir_shorts.py
procesar_video_universal.py ──────────┘ (procesar_clip_ffmpeg)
legacy/subir_lote.py ──────────────────────────────────────────► subir_shorts.py
legacy/{analizar_stream.py, recortar_clips.py, pipeline_viral_clips.py.bak} : autónomos archivados
```

> ⚠️ Importar `app_interfaz.py` construye la interfaz a nivel de módulo (`demo = construir_interfaz()`), leyendo `clips.json` y `subidas_shorts.json` anclados a `BASE_DIR`. Todos los scripts activos utilizan `BASE_DIR = Path(__file__).resolve().parent`.

### 3.3 Desglose por archivo

#### `pipeline_viral_clips.py` — Núcleo (ACTIVO)

**Constantes globales:**

| Constante | Valor | Uso |
|---|---|---|
| `GEMINI_TIMEOUT_MS` | `600_000` | `http_options={"timeout": ...}` (milisegundos = 600 s) |
| `MODELOS_CANDIDATOS` | `["gemini-3.8-flash", "gemini-3.7-flash", "gemini-3.5-flash-lite"]` | Orden de la cascada y opciones del dropdown Gradio |
| `RUTA_MARCA_AGUA` | `BASE_DIR / "assets/watermark.png"` | Ruta absoluta anclada a `BASE_DIR` |
| `CARPETA_FUENTES` | `BASE_DIR / "assets/fonts"` | Carpeta local de tipografía ExtraBold embebida para `libass` (`fontsdir=`) |
| `CARPETA_SALIDA` | `BASE_DIR / "clips_finales"` | Salida de renders |
| `CARPETA_JOBS` | `BASE_DIR / "jobs"` | Directorios aislados por `job_id` |
| `VAAPI_DEVICE` | `"/dev/dri/renderD128"` | Dispositivo DRM/VAAPI para aceleración por GPU |
| `FORMATOS_AUDIO_DIRECTO` | `"ba/worst[height<=360]/worst/b[height<=360]/b"` | Selector `-f` prioritario audio-only o menor resolución para `yt-dlp -g` |
| `FORMATOS_VIDEO_RAPIDOS` | ver §4.1 | Selector `-f` de yt-dlp para video |
| `STREAM_URL_CACHE` | `StreamUrlCache()` | Caché en memoria de `video_url`, `audio_url` y dimensiones por `job_id` |

**Funciones:**

| Función | Firma | Responsabilidad | Efectos laterales |
|---|---|---|---|
| `StreamUrlCache` | clase | Caché en memoria por `job_id` (`obtener`, `guardar`, `actualizar_dimensiones`, `invalidar`) | Mantiene URLs firmadas durante el job |
| `SegmentoSubtitulo` | `BaseModel` | Segmento de subtítulo (`inicio_rel`, `fin_rel`, `texto`) | Anidado en `ClipViral.subtitulos` |
| `ClipViral` | `BaseModel` | Esquema estricto de un clip (`id`, `titulo`, `inicio`, `fin`, `gancho`, `razon_viral`, `descripcion`, `etiquetas`, `subtitulos`) | Se pasa como `response_schema=list[ClipViral]` a Gemini |
| `obtener_duracion_media` | `(ruta) -> float\|None` | `ffprobe -v error -show_entries format=duration -of default=noprint_wrappers=1:nokey=1` | Ninguno; devuelve `None` ante cualquier error |
| `segundos_a_hhmmss` | `(float) -> str` | Redondeo a entero, `HH:MM:SS` | — |
| `hhmmss_a_segundos` | `(str) -> float` | Acepta `HH:MM:SS`, `MM:SS`, `SS` con decimales opcionales | `ValueError` si >3 partes |
| `_obtener_estado_archivo` | `(file) -> str` | Normaliza `file.state` (enum o str) | — |
| `_normalizar_etiquetas` | `(Any) -> List[str]` | Acepta lista o string separado por `,;\n`; quita `#`; dedup; rellena con defaults hasta 8; corta a 12 | — |
| `_normalizar_subtitulos` | `(Any, float) -> List[SegmentoSubtitulo]` | Limpia emojis, clamp a `[0, duracion_clip]`, elimina solapes y auto-divide bloques (`>5` palabras o `>28` chars, `>=0.6s`) en segmentos de 2–4 palabras proporcionales | — |
| `_limpiar_texto_ass` | `(str) -> str` | Elimina emojis/caracteres no permitidos, escapa `{}` a `()`, saltos `\N` y convierte texto a **MAYÚSCULAS** | — |
| `_detectar_fuente_subtitulos` | `() -> str` | Fallback: consulta `fc-list : family` y elige la primera tipografía instalada (`Montserrat`, `Poppins`, `Impact`, `Liberation Sans`, `Ubuntu`, fallback `DejaVu Sans`) | — |
| `_obtener_fuente_y_dir_subtitulos` | `() -> Tuple[str, Optional[str]]` | Prioriza `.ttf`/`.otf` en `CARPETA_FUENTES` resolviendo `%{fullname[0]}` / `%{family}` vía `fc-scan` (p. ej. `Montserrat ExtraBold`) para `fontsdir=`; fallback a `_detectar_fuente_subtitulos()` con `None` | — |
| `generar_archivo_ass` | `(subtitulos, ruta_ass) -> str` | Genera `.ass` (`WrapStyle: 2`, tercio medio-inferior 1080×1920, fuente embebida, tamaño `54` Bold, `Spacing=1.5`, `BackColour=&HA0000000`, `Outline=5.5`, `Shadow=3.5`, `Alignment=2`, `MarginL=65`, `MarginR=210`, `MarginV=550`, mayúsculas, animación *pop-in*) | Crea/sobrescribe `.ass` en disco |
| `_limpiar_y_parsear_json` | `(texto, duracion_total, permitir_vacio=False) -> List[dict]` | Quita fences markdown, valida con pydantic (3 niveles de fallback), soporta `[]` en chunks muertos (`permitir_vacio=True`), validación temporal, SEO y `subtitulos` | `ValueError` si es inválido o vacío no permitido |
| `_es_stream_hls_kick_o_twitch` | `(url) -> bool` | Detecta URLs HLS (`.m3u8`) o dominios `kick.com` / `twitch.tv` para omitir `aria2c` | — |
| `_emitir_telemetria` | `(on_telemetria, ultimo_ts_ref, datos, forzar=False, min_intervalo=0.33)` | Throttling de eventos en vivo (`<= ~3 updates/s`, siempre pasa si `forzar=True`) | — |
| `_parsear_linea_progreso_descarga` | `(linea) -> Optional[dict]` | Parsea progreso en tiempo real de `yt-dlp --newline` (`%`, tamaño, MB/s, `ETA`, `(frag cur/tot)`) y `aria2c` | — |
| `_ejecutar_descarga_con_telemetria` | `(comando, on_telemetria, ...) -> str` | Ejecuta `yt-dlp` con `Popen` línea a línea, cierra pipes en `try...finally` y emite telemetría `descarga` / `descarga_video` | Lanza `CalledProcessError` si falla |
| `extraer_audio` | `(url, job_dir=None, on_telemetria=None, on_log=None) -> str` | Primario: `yt-dlp --newline --concurrent-fragments 16` (+ `aria2c` fuera de Kick/Twitch/HLS) con telemetría en vivo y validación `>10 KB`; fallback automático `yt-dlp -g` + `ffmpeg -vn -progress pipe:1 -reconnect*` | **Borra `temp_audio.*` y `temp_audio_chunk_*.mp3`** previos; crea `temp_audio.mp3` |
| `construir_prompt_viral` | `(duracion_total) -> str` | Prompt v3.1/v3.2 de curaduría dinámica (sin mínimo/máximo fijo) y transcripción fonética literal anti-alucinaciones | — |
| `_esperar_con_jitter` | `(intento, base=3.0, max_espera=30.0, ...) -> float` | Backoff exponencial con jitter (`random.uniform`) y registro de modelo, código de error y espera | Bloquea el hilo durante el tiempo calculado |
| `_es_error_cuota_diaria_free_tier` | `(APIError) -> bool` | Detecta `429` con indicadores de cuota diaria (`free_tier_requests`, `PerDay`, `per day`, `limit: 20`) para salto `0s` | — |
| `_segmentar_audio_en_chunks` | `(ruta_audio, duracion_total, max_duracion_chunk=2700, solapamiento=90)` | Si `duracion_total > 3300 s`, divide con `ffmpeg -c copy` en bloques de 45 min con 90 s de solape | Crea `temp_audio_chunk_NN.mp3` |
| `_analizar_archivo_audio_gemini` | `(client, ruta_archivo, duracion_bloque, modelo_preferido, on_log, on_telemetria=None, ...)` | Upload File API, polling `ACTIVE`, cascada (`temperature=0.20`), salto `0s` en cuota diaria `429`, telemetría Gemini y limpieza remota `files.delete` | Sube/borra archivo temporal remoto |
| `_deduplicar_clips_solapados` | `(clips) -> List[dict]` | Fusiona clips de chunks contiguos con solape `>50%` priorizando duración/calidad y reasigna `id` (`1..N`) | — |
| `analizar_con_gemini` | `(ruta_audio, duracion_total, modelo_preferido, job_dir=None, on_log=None, on_telemetria=None) -> List[dict]` | Segmenta audios `>55 min`, emite telemetría por bloque/modelo, suma `offset_seg`, deduplica y limpia `temp_audio_chunk_*.mp3` | **Escribe `clips.json`** en `job_dir` y raíz; limpia chunks |
| `descargar_video_fuente` | `(url, destino=None, on_telemetria=None, on_log=None) -> str` | Descarga completa ≤1080p MP4 con telemetría de red en vivo (`--newline`) | Crea `temp_source.mp4` en `job_dir` (lo borra si existía) |
| `obtener_urls_stream` | `(url, job_id=None, forzar_recarga=False) -> List[str]` | `yt-dlp -g` con caché en memoria por `job_id` | Pobla `STREAM_URL_CACHE` |
| `detectar_encoder_hardware` | `(device_path=VAAPI_DEVICE) -> str` | Verifica `/dev/dri/renderD128` y prueba codificación nula de 1 frame `h264_vaapi` con `lavfi` | Devuelve `"h264_vaapi"` o `"libx264"` sin lanzar excepciones |
| `obtener_dimensiones_video` | `(fuente) -> Tuple[int,int]\|None` | Consulta `ffprobe` (ancho, alto, SAR, rotación) | — |
| `_ejecutar_comando_con_captura` | `(comando, duracion_objetivo=None, on_progreso=None) -> str` | Ejecuta FFmpeg con `Popen`; si lleva `-progress pipe:1`, lee `out_time_us`, `fps`, `speed`, `frame`, `total_size` calculando `%` y `ETA`, cerrando pipes limpiamente | Captura `stderr` para diagnóstico |
| `_construir_comando_render` | `(..., ruta_ass=None, fonts_dir=None) -> List[str]` | Arma comando FFmpeg con `-progress pipe:1 -nostats -loglevel warning` e inyecta `subtitles='<ass>':fontsdir='<dir>'` cuando aplica | — |
| `procesar_clip_ffmpeg` | `(url_o_archivo, inicio, fin, id_clip, job_id=None, subtitulos=None, job_dir=None, on_telemetria=None, clip_indice=None, total_clips=None, on_log=None) -> str` | Render 9:16 VAAPI/CPU, corte exacto `-t`, watermark adaptativa, `.ass` + `fontsdir`, telemetría en vivo (FPS, velocidad `x`, ETA, encoder), refresh 403/410 y fallbacks | Crea `clips_finales/<job_id>_clip_<id>.mp4` y `job_dir/subs_<id>.ass` |
| `calcular_publish_at_utc` | `(publish_at_inicio, indice_clip=0, intervalo_horas=0) -> str\|None` | Convierte fecha local Colombia (-05:00) o ISO sumando intervalo a UTC ISO 8601 (`YYYY-MM-DDTHH:MM:SSZ`) | — |
| `_ejecutar_paso_con_telemetria` | `(fn, *args, q_builder=..., on_log=None, **kwargs)` | Ejecuta paso bloqueante en hilo worker reenviando en streaming dicts de telemetría vía `queue.Queue` al generador | Puente síncrono → generador |
| `ejecutar_pipeline_completo` | `(url, modelo_preferido, solo_analisis, subir_youtube, publish_at_inicio, intervalo_horas, on_log, on_telemetria=None)` | **Orquestador único generador** que emite diccionarios de estado (`fase`, `progreso`, `mensaje`, `clips`, `ultimo_video`, `job_dir`, `error`, **`telemetria`**) con tolerancia a fallos por clip | Orquesta todo el pipeline CLI/GUI |
| `renderizar_y_subir_clips` | `(url, clips, ...) -> List[str]` | Wrapper compatible que delega en el orquestador unificado con persistencia incremental | Reescribe `clips.json` incrementalmente |
| `renderizar_clips` | alias | Compatibilidad: `renderizar_y_subir_clips(..., subir_youtube=True, ...)` | — |
| `_formatear_barra_cli` / `RenderizadorProgresoCLI` | helpers CLI | Barra visual sincronizada (`\r\x1b[2K` en TTY o saltos `>=15%` fuera de TTY) intercalando logs sin romper la línea activa | Escribe en terminal |
| `main` | argparse | CLI: `url`, `--solo-analisis`, `--sin-subida`, `--modelo`, `--publish-at`, `--intervalo-horas` | Consume `ejecutar_pipeline_completo` y `RenderizadorProgresoCLI` |

#### `app_interfaz.py` — GUI Gradio (ACTIVO)

| Función | Responsabilidad |
|---|---|
| `CUSTOM_CSS` | Tema oscuro (`#0f0f13`, acento `#8b5cf6`, verde Kick `#53fc18`) + animaciones CSS `.telemetry-card`, `.telemetry-bar-fill`, `@keyframes kicksazos-bar-shimmer` y `@keyframes kicksazos-pulse-dot` |
| `_sanitizar_url_href(url)` | Valida esquema http(s) y escapa URLs para atributos `href` seguros |
| `_banner_html(titulo, detalle, nivel)` | HTML de estado con iconos ✅⚠️❌⚡ sanitizado con `html.escape()` |
| `construir_panel_telemetria_html(estado)` | Panel HTML/CSS animado con barra de etapa, barra global, 4 KPIs dinámicos (Velocidad MB/s o `x`+FPS, ETA, Motor/Encoder/IA, Bloque/Tamaño) y detalle con `html.escape()` estricto |
| `_cargar_clips_actuales()` | Lee `clips.json` (lista o `[]`) |
| `_indexar_subidas_por_archivo()` | Dict `archivo → registro` desde `subidas_shorts.json` |
| `construir_tarjetas_galeria_html(clips)` | Tarjetas con timestamps, hook, gatillo, descripción SEO, tags y link a YouTube con sanitización estricta (`html.escape()`) |
| `obtener_datos_galeria()` | → `(items_galeria[(ruta, leyenda)], primer_video, html_tarjetas, clips)` |
| `obtener_tabla_historial()` | → `(filas Dataframe, html resumen)` desde `subidas_shorts.json` con escape HTML y estado de cuota 24h |
| `ejecutar_pipeline_gradio(...)` | **Generador adaptador (9 salidas)** que consume `ejecutar_pipeline_completo()`, actualiza `telemetria_panel` hasta 3×/seg y usa **`gr.skip()`** en galería/reproductor/historial durante ticks intermedios para no re-escanear disco con `ffprobe` |
| `seleccionar_clip_galeria(evt: gr.SelectData)` | Extrae `path` del item seleccionado para el reproductor |
| `obtener_tema_oscuro()` | `gr.themes.Soft(primary_hue="violet", secondary_hue="emerald", neutral_hue="slate")` + overrides |
| `construir_interfaz()` | Construye `gr.Blocks` con `estado_banner`, `telemetria_panel` (`gr.HTML`), accordion de programación (`publish_at_input`, `intervalo_horas_input`), 3 pestañas y eventos |
| `__main__` | `demo.launch(server_name="127.0.0.1", server_port=7860, inbrowser=False, ...)` |

#### `subir_shorts.py` — YouTube (ACTIVO)

| Función | Responsabilidad |
|---|---|
| `autenticar_youtube(interactivo=False)` | Autentica con OAuth, refresca si expiró y asocia `_kicksazos_cuenta_id` al Resource |
| `obtener_hash_cuenta(creds)` | Genera identificador seguro SHA-256 corto (`[:12]`) de la cuenta/canal a partir de tokens/clientId |
| `verificar_cuota_diaria(limite_diario=6)` | Lee `subidas_shorts.json`, filtra subidas de las últimas 24h y valida si se alcanzó el límite diario |
| `cargar_historial_subidas(ruta)` | Lee `subidas_shorts.json` → lista |
| `registrar_subida(registro, ruta)` | Deduplica por `youtube_id`, append y reescribe JSON |
| `subir_short(...)` | Sube resumable con hasta 4 reintentos ante HTTP 5xx / red usando backoff con jitter, soporta programación `publishAt` (ISO 8601 UTC) y registra `cuenta_id` y `publish_at` |
| `main()` | CLI interactivo de upload de prueba |

#### `procesar_video_universal.py` (ACTIVO, wrapper)
`procesar_clip(url, inicio, fin, id_clip)` → `procesar_clip_ffmpeg(...)`. CLI: `python procesar_video_universal.py <URL|archivo> <INICIO> <FIN> <ID>`. No sube ni modifica JSON.

#### Archivos LEGACY (no usados por el flujo actual; conservar como referencia)

| Archivo | Qué hace | Diferencias clave vs actual |
|---|---|---|
| `pipeline_viral_clips.py.bak` | Pipeline v1: `verificar_entorno()` (`which yt-dlp ffmpeg`), audio con binario `yt-dlp --user-agent <Chrome 131>`, `obtener_url_stream_m3u8` (`-f best -g`), Gemini **no streaming** con `response_schema=ColeccionClips` (`{"clips":[...]}`), 5 intentos con backoff `10s·n`, render remoto directo a `clips_virales/clip_{id:02d}_{slug}.mp4`, reporte `clips_virales/reporte_clips.json` | Sin SEO, sin watermark, sin upload, clips de 15–45 s, `PRIMARY_MODEL=env GEMINI_MODEL or gemini-3.8-flash`, fallback `[gemini-3.8-flash, gemini-3.5-flash, gemini-3.1-flash-lite]`, filtro `boxblur=20:5` a 1080×1920 |
| `analizar_stream.py` | Reusa un archivo ya subido (`files/qqucn2awgp39`, hardcodeado, probablemente expirado — la File API retiene ~48 h) y pide 5–8 clips de 30–60 s a `gemini-3.8-flash`; 5 reintentos ante `ServerError` con espera 10 s; escribe `response.text` crudo en `clips.json` | **Sobrescribe `clips.json`** con esquema reducido; sin `load_dotenv` |
| `recortar_clips.py` | Lee `clips.json`, obtiene URL de `https://kick.com/eldomi/videos/01a1b385-...` (hardcodeada) con `yt-dlp --user-agent ... -f best -g`, renderiza a `clips_finales/clip_{id}_{titulo}.mp4` | Filtro sin watermark, `boxblur=20:5`, `-user_agent` en ffmpeg, sin `check=True` |
| `subir_lote.py` | Lee `clips_virales/reporte_clips.json`, sube los primeros 5 (límite "seguro" de cuota) buscando archivos `clip_{id:02d}_*`, descripción `"{gancho}\n\nMomento viral de stream.\nSuscríbete para más clips diarios."`, tags fijos | Llama `autenticar_youtube()` con `interactivo=False` por defecto → falla si no hay token válido; se detiene (`break`) al primer error; no pasa `clip_id` |

---

## 4. Lógica Interna Detallada (Core Logic)

### 4.1 Ingesta y extracción de audio/video (`yt-dlp` multihilo + fallback streaming FFmpeg)

Todas las invocaciones de `yt-dlp` usan el intérprete del venv: `[sys.executable, "-m", "yt_dlp", ...]`.

**Flags comunes de `yt-dlp`:**
- `--js-runtimes node` + `--remote-components ejs:github` → usa Node para resolver los desafíos JS (n-sig/firmas) de YouTube con el componente EJS descargado de GitHub.
- `--no-playlist` → nunca expande listas.
- `--force-overwrites` (solo descargas).

**A) Audio para IA — `extraer_audio(url, job_dir=None, on_telemetria=None, on_log=None)` (v3.2)**
1. **Intento primario (descarga paralela agresiva con `yt-dlp --newline` y telemetría en vivo):**
   - Limpia `temp_audio.*` y `temp_audio_chunk_*.mp3` previos en `job_dir`.
   - Invoca `sys.executable -m yt_dlp --newline --progress` mediante `_ejecutar_descarga_con_telemetria()` (`subprocess.Popen` leyendo `stdout` línea por línea):
     - `--concurrent-fragments 16 --retries 10 --fragment-retries 10 --retry-sleep fragment:exp=1:10 --socket-timeout 15 --buffer-size 16K --http-chunk-size 10M`
     - Si `shutil.which("aria2c")` existe y `_es_stream_hls_kick_o_twitch(url)` es `False` (p. ej. YouTube), agrega `--downloader aria2c --downloader-args "aria2c:-x 16 -s 16 -k 1M"`.
     - Selector `-f "ba/worst[height<=360]/worst/b[height<=360]/b"`, extracción `-x --audio-format mp3 --postprocessor-args "ffmpeg:-vn -ac 1 -ar 16000 -b:a 32k"`.
   - `_parsear_linea_progreso_descarga()` parsea líneas `[download]` y `[#id ... DL:... ETA:...]` de `aria2c`, emitiendo hasta **3 actualizaciones/seg** (`min_intervalo=0.33s`, siempre forzando `0%` y `100%`) con `etapa="descarga"`, `porcentaje`, `velocidad_red`, `tamano_total`, `eta` y `Fragmentos X/Y`.
   - Valida que `temp_audio.mp3` exista y supere **10 KB (`> 10_240` bytes)**.
2. **Fallback automático (streaming directo FFmpeg con reconexión y `-progress pipe:1`):**
   - Si el intento primario falla o genera un archivo `<= 10 KB`, limpia restos parciales, obtiene la URL directa vía `_obtener_url_audio_directo` (`yt-dlp -g`) y ejecuta mediante `_ejecutar_comando_con_captura()`:
     ```bash
     ffmpeg -hide_banner -loglevel warning -progress pipe:1 -nostats -y \
       -reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5 -rw_timeout 15000000 \
       -i "<STREAM_URL>" -vn -ac 1 -ar 16000 -b:a 32k "<job_dir>/temp_audio.mp3"
     ```
- Resultado: `jobs/<job_id>/temp_audio.mp3` (mono, 16 kHz, 32 kbps ≈ 14 MB/h).

**B) Video fuente completo — `descargar_video_fuente(url, destino=None, on_telemetria=None, on_log=None)`** (solo si `duracion_total ≤ 3600 s` o desconocida)
```bash
python -m yt_dlp --newline --progress --js-runtimes node --remote-components ejs:github \
  --no-playlist --force-overwrites \
  -f "bestvideo[height<=1080][protocol!=m3u8_native][ext=mp4]+bestaudio[protocol!=m3u8_native][ext=m4a]/bestvideo[height<=1080][ext=mp4]+bestaudio[ext=m4a]/best[height<=1080][ext=mp4]/best[height<=1080]/best" \
  --merge-output-format mp4 \
  -o "<job_dir>/temp_source.mp4" "<URL>"
```
- Emite telemetría en vivo con `etapa="descarga_video"` (`porcentaje`, `velocidad_red`, `tamano_total`, `eta`).
- `FORMATOS_VIDEO_RAPIDOS` prioriza DASH/HTTPS directo (evita HLS `m3u8_native`, más lento) y cae a HLS/muxed si no hay alternativa.
- Si falla → aviso y se usa seek remoto.

**C) URLs directas con caché en memoria — `obtener_urls_stream(url, job_id=None, forzar_recarga=False)`**
```bash
python -m yt_dlp --js-runtimes node --remote-components ejs:github \
  --no-playlist -f "<FORMATOS_VIDEO_RAPIDOS>" -g "<URL>"
```
- Devuelve 1 URL (muxed, p. ej. manifest HLS de Kick en CloudFront) o 2 URLs (video + audio separados). Se toman `urls[:2]`.
- `STREAM_URL_CACHE` (`StreamUrlCache`) almacena `{source_url, video_url, audio_url, dimensiones}` indexado por `job_id` en la primera consulta para evitar repetir `yt-dlp -g` y `ffprobe` en cada clip de VODs largos (>1 h).
- **Invalidación automática (HTTP 403/410):** si `procesar_clip_ffmpeg` detecta `HTTP error 403/410` o `403 Forbidden / 410 Gone` por expiración de firma temporal, limpia la entrada de `STREAM_URL_CACHE` para ese `job_id`, ejecuta `obtener_urls_stream(..., forzar_recarga=True)` una vez y reintenta el render del clip. La caché del job se limpia en `finally` al finalizar la ejecución.

**Manejo de secciones:** no se usa `--download-sections`; el corte se hace en FFmpeg con *input seek* (`-ss <inicio>` antes de `-i`) + duración exacta (`-t <duracion_clip>` calculada desde `fin - inicio`), tanto en entrada como en salida.

### 4.2 Motor de curaduría con IA (Gemini)

#### 4.2.1 Flujo de `analizar_con_gemini` (v3.1 con Chunking y Consolidación)
1. Valida `os.environ.get("GEMINI_API_KEY")` (lanza `RuntimeError` si falta) e inicializa `genai.Client(api_key=..., http_options={"timeout": 600_000})`.
2. **Segmentación automática (`_segmentar_audio_en_chunks`):**
   - Si `duracion_total <= 3300 s` (55 min), analiza el archivo íntegro sin dividir `[(ruta_audio, 0.0, duracion_total)]`.
   - Si `duracion_total > 3300 s`, divide el MP3 con `ffmpeg -hide_banner -loglevel error -y -ss <offset> -t <duracion_bloque> -i <ruta_audio> -c copy <job_dir>/temp_audio_chunk_<idx:02d>.mp3` en bloques de **45 min (`2700 s`)** con **90 s de solapamiento** entre bloques consecutivos.
3. **Por cada chunk (`_analizar_archivo_audio_gemini`):**
   - **Upload** `client.files.upload` con hasta **4 intentos** y backoff con jitter (`base=3.0s`, `max=30.0s`).
   - **Polling**: `sleep(4)` + `files.get` hasta `ACTIVE` (máx 150 iteraciones).
   - **Prompt**: `construir_prompt_viral(duracion_bloque)` (sin límites artificiales de cantidad y con reglas fonéticas literales).
   - **Cascada de modelos**: `[modelo_preferido] + MODELOS_CANDIDATOS` (4 intentos c/u) con `generate_content_stream(..., config=GenerateContentConfig(response_mime_type="application/json", response_schema=list[ClipViral], temperature=0.20))`.
   - Parseo con `_limpiar_y_parsear_json(..., duracion_total=duracion_bloque, permitir_vacio=True)`: permite que bloques silenciosos/muertos retornen `[]` sin abortar el job.
   - `finally`: elimina el archivo remoto en Gemini (`client.files.delete`).
4. **Consolidación y offsets:**
   - Desplaza `inicio` y `fin` de cada clip sumando `offset_seg` (haciendo clamp a `duracion_total`). Los `subtitulos` conservan sus tiempos `inicio_rel`/`fin_rel` relativos al clip (**no** se suma `offset_seg`) y se validan contra la duración del clip.
   - `_deduplicar_clips_solapados`: si dos clips de chunks contiguos se solapan en `> 50%` de su duración (`interseccion / min(dur_a, dur_b) > 0.5`), conserva el de mayor duración/calidad y reasigna los `id` secuencialmente (`1..N`).
   - Si tras procesar todos los chunks el total global de clips es 0, lanza `RuntimeError`.
   - Escribe `clips.json` en `job_dir` y raíz.
5. `finally`: elimina todos los archivos temporales locales `temp_audio_chunk_*.mp3`.

#### 4.2.2 Matriz de manejo de errores (por intento)

| Excepción | Condición | Acción |
|---|---|---|
| `ServerError` (5xx, p. ej. 503 overloaded) | — | Backoff con jitter (`base=4.0s`, `max_espera=25.0s`), reintenta hasta 4 veces antes de saltar al siguiente modelo |
| `APIError` | `code == 429` y cuota diaria Free Tier (`"free_tier_requests"`, `"PerDay"`, `"per day"`, `"limit: 20"`) | Cuota diaria agotada → aviso en log, espera **0.00s** (sin `_esperar_con_jitter`) y **salta al siguiente modelo inmediatamente (`break`)** |
| `APIError` | `code in (400, 404)` | Modelo no disponible/inválido → espera **0.00s** y **salta al siguiente modelo inmediatamente** |
| `APIError` | `code in (429, 503)` transitorio (RPM/TPM/saturación) | Backoff con jitter (`base=4.0s`, `max_espera=25.0s`), reintenta hasta 4 veces |
| `APIError` | otro código | Log y **salta al siguiente modelo** |
| `Exception` genérica | fallos de red (`ConnectError`), DNS, stream vacío, JSON inválido | Backoff con jitter (`base=4.0s`, `max_espera=25.0s`), reintenta hasta 4 veces |
| Todos los modelos agotados | `clips` es `None` en el chunk / 0 clips globales | `RuntimeError` descriptivo |

> El backoff exponencial con jitter (`_esperar_con_jitter`) utiliza `base=4.0` s y `max_espera=25.0` s para absorver picos transitorios de RPM/TPM, 503 y micro-cortes DNS, mientras que las cuotas diarias Free Tier (`limit: 20` / `PerDay`) rotan en **0.00 s**.

#### 4.2.3 Prompt de producción v3.1 (resumen, `construir_prompt_viral`)

```text
Actúa como un Senior Growth Hacker, estratega de algoritmos de YouTube Shorts / TikTok (2026), transcriptor fonético forense y editor experto en el ecosistema de IRL y streaming de Colombia (WestCOL, MrStivenTC, Blessd, La Liendra, Yhap, eldomi, eventos IRL y polémicas).

Analiza el audio adjunto y extrae ÚNICAMENTE los segmentos con verdadero potencial de viralidad y alta retención de audiencia.
[Si hay duración:] DURACIÓN TOTAL DE ESTE AUDIO: {info_duracion} (JAMÁS generes timestamps `inicio` o `fin` superiores a este límite).

### 1. CANTIDAD DINÁMICA DE CLIPS (CALIDAD Y RETENCIÓN PRIMERO):
- Sin mínimo ni máximo artificial (pueden ser 1, 4, 8 o [] si el segmento está muerto); prohibido rellenar con tiempos muertos.

### 2. REGLA DEL PRIMER SEGUNDO Y DURACIÓN ESTRATÉGICA:
- Apertura en 0.0s sin introducción muerta, rangos 22-45s (Shorts) o 60-75s (TikTok Creator Rewards) y Seamless Loop.

### 3. PRECISIÓN FORENSE EN SUBTÍTULOS (CERO ALUCINACIONES):
- Transcripción LITERAL del audio respetando jerga colombiana real ("gonorrea", "parce", "chimba", "pirobo", "sisas", "nea", "marica"); omitir segundos ininteligibles sin inventar texto.
- Bloques dinámicos de lectura rápida: ESTRICTAMENTE 2 a 4 palabras por bloque, máximo 22 caracteres por segmento, SIN EMOJIS, `inicio_rel`/`fin_rel` cronológicos sin solapamientos.

### 4. METADATOS SEPARADOS Y OBLIGATORIOS POR CLIP:
- YouTube Shorts: `titulo` (máx 60 chars), `descripcion` (2 líneas + CTA + #Shorts), `etiquetas` (8-12 tags SEO).
- TikTok: `caption_tiktok` (máx 150 chars SEO semántico), `hashtags_tiktok` (3 a 5 tags), `gancho_visual_portada` (4-6 palabras).
- Común: `id`, `inicio`/`fin` (`HH:MM:SS`), `gancho`, `razon_viral`, `subtitulos`.
```
*(El texto literal completo está en `construir_prompt_viral` dentro de [pipeline_viral_clips.py](file:///home/bastiboy/clips_automation/pipeline_viral_clips.py).)*

> Nota: Gemini recibe `response_schema=list[ClipViral]`, `response_mime_type="application/json"` y `temperature=0.20` para máxima precisión fonética y temporal.

#### 4.2.4 Parsing y validación — `_limpiar_y_parsear_json(texto, duracion_total, permitir_vacio=False)`
1. Quita los fences markdown iniciales/finales (triple backtick con o sin `json`) mediante regex.
2. Intenta `TypeAdapter(List[ClipViral]).validate_json(texto)`.
3. Si falla (incluyendo archivos `clips.json` v1/v2 sin campos TikTok): regex `\[.*\]` (DOTALL) → `validate_json(bloque)` → si falla, `json.loads(bloque)`. Sin coincidencia: `json.loads(texto)`.
4. Si es `dict` → toma `datos["clips"]`. Si la lista está vacía y `permitir_vacio=True`, retorna `[]`.
5. Por cada item:
   - Convierte `inicio`/`fin` a segundos (si falla → descarta).
   - Si `ini ≥ duracion_total − 2` → descarta; `fin = min(fin, duracion_total)`.
   - Si `fin − ini < 5 s` → descarta.
   - `titulo` > 60 chars → recorta a 57 + `"..."`; vacío → `"Clip Viral #n"`.
   - `descripcion` vacía → plantilla `"{gancho|titulo}\n¡Suscríbete a Kicksazos ...! #Shorts #Kicksazos #StreamColombia #KickColombia"`; si no contiene `#shorts` → añade `"\n#Shorts #Kicksazos #StreamColombia"`.
   - `etiquetas` → `_normalizar_etiquetas` (8–12 tags sin `#`).
   - `caption_tiktok` → `_normalizar_caption_tiktok` (≤150 chars; autogenera fallback con `gancho`/`titulo` + CTA de comentarios si falta).
   - `hashtags_tiktok` → `_normalizar_hashtags_tiktok` (3–5 hashtags con `#`; si faltan en v1/v2 reutiliza tags relevantes de `etiquetas` + defaults TikTok).
   - `gancho_visual_portada` → `_normalizar_gancho_portada` (4–6 palabras; autogenera fallback desde `titulo`/`gancho` si falta).
   - `subtitulos` → `_normalizar_subtitulos(..., duracion_clip)`: limpia emojis, hace clamp a `[0.0, duracion_clip]`, ordena cronológicamente, elimina solapamientos y auto-divide segmentos de `>5` palabras o `>28` chars (con duración `>= 0.6s`) en sub-segmentos de **2 a 4 palabras** repartiendo el intervalo proporcionalmente al número de caracteres (redondeado a 2 decimales).
   - **Re-numera `id` secuencialmente** (1..N tras descartes) y añade `duracion_segundos`.
6. Lista vacía tras validación temporal → `ValueError`.

### 4.3 Pipeline de renderizado FFmpeg (9:16), VAAPI y Subtítulos `.ass`

#### 4.3.1 Detección de hardware, telemetría `-progress pipe:1` y comando completo (`procesar_clip_ffmpeg`)
- `detectar_encoder_hardware()` comprueba si existe `/dev/dri/renderD128` y ejecuta una prueba nula de 1 frame con `lavfi` (`color=c=black:s=256x256:d=0.1` → `format=nv12,hwupload` → `-c:v h264_vaapi -qp 23 -f null -`). Devuelve `"h264_vaapi"` (activo en GPU AMD Radeon 610M de Kubuntu) o `"libx264"` sin lanzar excepciones.
- **Modo VAAPI (`h264_vaapi`):** antepone `-vaapi_device /dev/dri/renderD128`, agrega `format=nv12,hwupload` al final del `filter_complex` y codifica con `-c:v h264_vaapi -qp 23`.
- **Fallback automático a CPU (`libx264`):** si VAAPI no está disponible o falla en tiempo de ejecución, captura el `CalledProcessError` y reintenta automáticamente con `-c:v libx264 -preset veryfast -crf 22 -threads 0`.
- **Telemetría FFmpeg en vivo (`-progress pipe:1`):** `_construir_comando_render()` añade `-loglevel warning -progress pipe:1 -nostats` y `_ejecutar_comando_con_captura()` lee pares clave=valor por `stdout` (`out_time_us`, `fps`, `speed`, `frame`, `total_size`, `progress=continue|end`) calculando porcentaje real del clip (`out_sec / duracion_objetivo`) y `ETA`, emitiendo hasta ~3 updates/seg (`etapa="render"`, `encoder`, `fps`, `velocidad_x`, `clip_id`, `clip_indice/total_clips`).

Entrada **local** (`temp_source.mp4`):
```bash
ffmpeg -hide_banner -loglevel warning -progress pipe:1 -nostats -y [-vaapi_device /dev/dri/renderD128] \
  -ss <INICIO> -t <DURACION_CLIP> -i <temp_source.mp4> \
  -i <abs>/assets/watermark.png \
  -filter_complex "<FILTRO>" \
  -map "[outv]" -map "0:a?" -t <DURACION_CLIP> \
  [-c:v h264_vaapi -qp 23 | -c:v libx264 -preset veryfast -crf 22 -threads 0] \
  -c:a aac -b:a 128k -movflags +faststart \
  <abs>/clips_finales/<job_id>_clip_<ID>.mp4
```
Entrada **remota** (por cada URL en caché o `yt-dlp -g`, se antepone):
```bash
-rw_timeout 15000000 -reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5 -ss <INICIO> -t <DURACION_CLIP> -i <URL_n>
```
- Con 2 URLs (video+audio separados): video = input 0, audio = `-map 1:a?`, watermark = input 2.
- Con 1 URL o archivo local: audio = `-map 0:a?`, watermark = input 1.
- **Precisión de corte:** `-ss <INICIO>` como opción de entrada para *fast seek* en red, combinado con `-t <DURACION_CLIP>` calculada exactamente desde `(fin - inicio)` para evitar desfases de cierre por keyframes.

#### 4.3.2 `filter_complex`, watermark adaptativa y subtítulos `.ass` con `fontsdir=`
```
[0:v]split=2[bg][fg];
[bg]scale=360:640:force_original_aspect_ratio=increase,crop=360:640,setsar=1,boxblur=10:2,scale=1080:1920:flags=bilinear[bg_blur];
[fg]scale=1080:1920:force_original_aspect_ratio=decrease,setsar=1[fg_scaled];
[bg_blur][fg_scaled]overlay=(W-w)/2:(H-h)/2[vid_comp];
[<idx_wm>:v]scale=420:-1,format=rgba,colorchannelmixer=aa=0.92[wm];
[vid_comp][wm]overlay=(W-w)/2:<y_wm>[,subtitles='<ruta_ass_escapada>':fontsdir='<fonts_dir_escapada>'],<format=nv12,hwupload | format=yuv420p>[outv]
```

| Etapa | Qué hace | Por qué |
|---|---|---|
| `split=2` | Duplica el video en capa fondo `bg` y capa frente `fg` | Una sola decodificación |
| Fondo `scale 360:640 increase` + `crop 360:640` | Rellena un lienzo 9:16 pequeño recortando laterales | Blur a 360p es ~9× más barato que a 1080p |
| `boxblur=10:2` | Radio 10, 2 pasadas (≈ gaussiano) | Desenfoque del fondo |
| `scale=1080:1920:flags=bilinear` | Sube el fondo borroso a 1080×1920 | Upscale barato (el blur oculta artefactos) |
| Frente `scale=1080:1920 decrease` | Encaja la fuente sin recorte (respetando aspecto) | Contenido íntegro, centrado |
| `overlay=(W-w)/2:(H-h)/2` | Centra el frente vertical y horizontalmente | Layout clásico "blur bars" |
| Watermark adaptativa (`_calcular_y_watermark`) | `ffprobe` obtiene `(w, h)` efectivos (incl. SAR/rotación). Si la fuente ya es vertical 9:16 (`w/h ≤ 9/16 + 0.03`), fija `y = 200`; si hay barras desenfocadas, usa `y = max(200, (H - h_fg)/2 - h - 24)` | Libra las cabeceras/menús superiores de Shorts (192 px) y TikTok (154 px) sin invadir cuadros 16:9/4:3/1:1 |
| Subtítulos dinámicos `.ass` (`generar_archivo_ass` + `fontsdir=`) | Si `clip.subtitulos` tiene segmentos válidos, normaliza/auto-parte en 2–4 palabras y genera `jobs/<job_id>/subs_<id_clip>.ass` (`WrapStyle: 2`, lienzo `1080×1920`, tipografía vía `_obtener_fuente_y_dir_subtitulos()` desde `assets/fonts/Montserrat-ExtraBold.ttf` resolviendo `Montserrat ExtraBold`, tamaño `54`, Bold `-1`, blanco `&H00FFFFFF`, `SecondaryColour=&H0000FFFF`, `OutlineColour=&H00000000`, `BackColour=&HA0000000`, `Spacing=1.5`, `Outline=5.5`, `Shadow=3.5`, `Alignment=2`, `MarginL=65`, `MarginR=210`, `MarginV=550`, texto `.upper()` y *pop-in* `{\fad(40,40)\t(0,70,\fscx105\fscy105)\t(70,140,\fscx100\fscy100)}`), inyectando `subtitles='<ass>':fontsdir='<CARPETA_FUENTES>'` en FFmpeg | Garantiza tipografía ExtraBold consistente sin depender de las fuentes instaladas del SO ni caer en `DejaVu Sans`; posiciona el texto en el tercio medio-inferior (`Y=1370`) despejando botones/descripciones y evita saltos automáticos de línea no deseados (`WrapStyle: 2`) |
| Salida `format=nv12,hwupload` / `format=yuv420p` | Superficie NV12 para `h264_vaapi` o YUV420P para `libx264` | Compatibilidad HW/SW y reproducción universal |

- Codificación: `h264_vaapi -qp 23` (GPU) o `libx264 -preset veryfast -crf 22` (CPU), AAC 128 kbps, `+faststart`.
- La imagen PNG es una entrada de 1 frame; `overlay` repite el último frame (`eof_action=repeat` por defecto).

#### 4.3.3 Safe Zones Multiplataforma 9:16 (YouTube Shorts + TikTok) — Calibración v3.2

Sobre el lienzo vertical estándar **`1080 × 1920` (`PlayResX=1080`, `PlayResY=1920`)**, el backend aplica márgenes combinados (intersección segura de las interfaces de YouTube Shorts y TikTok):

| Elemento | Parámetro / Coordenada | Dimensión Exacta | Objetivo de Safe Zone |
|---|---|---|---|
| **Marca de agua (`assets/watermark.png`)** | `y` en `overlay=(W-w)/2:<y_wm>` | `y = 200` px (fuente 9:16) / `max(200, (H-h_fg)/2 - h - 24)` (horizontal/mixta) | Supera la barra superior de estado y menús (192 px en YouTube Shorts y 154 px en TikTok). |
| **Subtítulos `.ass` (Tercio medio-inferior)** | `MarginV` | `550` px desde el borde inferior (`Y = 1370` px, `Alignment=2`) | Despeja el bloque inferior de descripción/audio/progreso (540–672 px) sin invadir el rostro del streamer. |
| **Subtítulos `.ass` (Margen derecho)** | `MarginR` | `210` px desde el borde derecho | Evita colisión con la botonera vertical derecha (like, comentarios, guardar, compartir) en TikTok y Shorts. |
| **Subtítulos `.ass` (Margen izquierdo)** | `MarginL` | `65` px desde el borde izquierdo | Centra ópticamente el texto en el área útil libre manteniendo respiración lateral. |
| **Tipografía & Efecto `.ass`** | `Fontname`, `Fontsize`, `WrapStyle`, `Outline`, `Shadow`, `Spacing`, animación | Embebida `Montserrat ExtraBold` via `:fontsdir=assets/fonts` (fallback `fc-list`), `WrapStyle: 2`, `54`, Bold `-1`, `Spacing=1.5`, `Outline=5.5`, `Shadow=3.5`, `BackColour=&HA0000000`, `.upper()`, *pop-in* `\fad`+`\fscx` | Máxima legibilidad e impacto viral estilo Hormozi/OpusClip en bloques de 2–4 palabras en MAYÚSCULAS sin saltos de línea rotos ni dependencia de fuentes del SO. |

### 4.4 Integración con YouTube Data API v3

#### 4.4.1 Autenticación OAuth 2.0 (Installed App)
```
autenticar_youtube(interactivo)
 ├─ token.json existe → Credentials.from_authorized_user_file(token.json, SCOPES)
 ├─ ¿válido? → build("youtube","v3")
 ├─ ¿expirado + refresh_token? → creds.refresh(Request()) → reescribe token.json
 └─ sin token válido:
      ├─ falta client_secret.json → FileNotFoundError
      ├─ interactivo=False (pipeline CLI y GUI) → RuntimeError  → el pipeline continúa sin subir
      └─ interactivo=True (subir_shorts.py main) → InstalledAppFlow.run_local_server(port=0)
           (abre navegador, callback en http://localhost:<puerto aleatorio>) → guarda token.json
```
**Bootstrap / cambio de cuenta:** borrar o renombrar `token.json` y ejecutar `venv/bin/python subir_shorts.py` (⚠️ esto también **sube un video de prueba**). Si el proyecto OAuth está en modo "Testing" en GCP, los refresh tokens caducan a los 7 días y la cuenta debe estar en *Test users*.

#### 4.4.2 Normalización de metadatos (`subir_short`)
- **Título:** si no contiene `#shorts` → `titulo[:90] + " #Shorts"`; si lo contiene → `titulo[:100]`. Enviado: `[:100]`.
- **Descripción:** si no contiene `#shorts` → `+ "\n\n#Shorts #Kicksazos #StreamColombia"`. Enviada: `[:4900]`.
- **Tags:** sin `#`, deduplicados, máx **25**; vacíos → `["Shorts","Kicksazos","StreamColombia","KickColombia","IRL"]`. (YouTube limita a ~500 caracteres totales; no se valida.)

#### 4.4.3 Request
```python
youtube.videos().insert(
    part="snippet,status",
    body={
        "snippet": {"title": ..., "description": ..., "tags": [...], "categoryId": "24"},  # 24 = Entertainment
        "status":  {"privacyStatus": "private", "selfDeclaredMadeForKids": False, "madeForKids": False},
    },
    media_body=MediaFileUpload(path, mimetype="video/mp4", resumable=True),
)
# bucle: status, response = request.next_chunk()  → imprime % de progreso
```
- URL resultante: `https://youtube.com/shorts/<videoId>` (YouTube clasifica como Short por ser vertical y ≤3 min).
- **Cuota:** `videos.insert` cuesta **~1600 unidades** de las 10 000 diarias por defecto → **≈6 subidas/día** por proyecto GCP (de ahí el `limite = 5` de `subir_lote.py`). El pipeline activo **no** tiene límite: un run con 6 clips puede agotar la cuota y los siguientes fallan con `quotaExceeded` (403), capturado como "No subido (...)".
- No hay reintento en `next_chunk()` ante errores HTTP 5xx.

#### 4.4.4 Registro
`registrar_subida(info_subida)` → elimina entradas con el mismo `youtube_id`, append, reescribe `subidas_shorts.json` (esquema §5.2). En el pipeline, además se actualiza el clip en `clips.json` con `youtube_id`, `youtube_url`, `youtube_status`.

### 4.5 Interfaz gráfica (Gradio 6.31)

**Lanzamiento:** `127.0.0.1:7860`, sin `share`, `allowed_paths=[clips_finales/, assets/]`, tema Soft violeta/esmeralda + `CUSTOM_CSS`. Título de pestaña: *"Kicksazos Studio | AI Viral Shorts Suite"*. Header con badges "Kick / Twitch / YouTube IRL", "Gemini 3.8 Flash + Cascada Resiliente", "Auto-Upload YouTube Shorts (Private)".

**Pestañas y componentes:**

| Pestaña | Componentes |
|---|---|
| **🚀 1. Extractor & Pipeline** | `estado_banner` (HTML) · **`telemetria_panel`** (HTML/CSS animado v3.2 con `construir_panel_telemetria_html`: barra de etapa, barra global, 4 KPIs y detalle en vivo) · `url_input` (Textbox) · `modelo_dropdown` (choices=`MODELOS_CANDIDATOS`, default `Auto (Recomendado)`) · `subir_yt_chk` (Checkbox, default **True**) · `solo_analisis_chk` (default False) · `api_key_input` (password, opcional) · `btn_ejecutar` (primary, lg) · `salida_logs` (Textbox 14–20 líneas, read-only) · `video_preview` (Video, h=420) · Accordion → `clips_json_view` (JSON) |
| **🎬 2. Galería de Clips (9:16)** | `btn_refrescar_galeria` · `galeria_videos` (Gallery, 3 columnas, h=520, contain) · `reproductor_galeria` (Video, h=520) · `tarjetas_galeria_html` (HTML escapado con `html.escape`, bloques diferenciados copiables para **YouTube Shorts** y **TikTok** vía `js_on_load`) |
| **📈 3. Historial de Subidas** | `btn_refrescar_historial` · `resumen_historial_html` · `tabla_historial` (Dataframe: Fecha Subida, Archivo Local, Título SEO, ID YouTube, URL Directa Short, Privacidad, Tags Clave[≤6]) |

**Eventos:**

| Disparador | Función | Inputs | Outputs |
|---|---|---|---|
| `btn_ejecutar.click` | `ejecutar_pipeline_gradio` (generador) | url, modelo, subir_yt, solo_analisis, api_key, publish_at, intervalo_horas | `estado_banner, telemetria_panel, salida_logs, video_preview, clips_json_view, galeria_videos, tarjetas_galeria_html, tabla_historial, resumen_historial_html` (**9**) |
| `galeria_videos.select` | `seleccionar_clip_galeria` | `gr.SelectData` | `reproductor_galeria` |
| `btn_refrescar_galeria.click` | `obtener_datos_galeria` | — | `galeria_videos, reproductor_galeria, tarjetas_galeria_html, clips_json_view` |
| `btn_refrescar_historial.click` | `obtener_tabla_historial` | — | `tabla_historial, resumen_historial_html` |

**Máquina de estados y streaming de telemetría (`ejecutar_pipeline_gradio` ← `ejecutar_pipeline_completo`):**

| Progreso | Fase | Acción y Telemetría Emitida (`estado["telemetria"]`) |
|---|---|---|
| — | Validación | URL vacía → banner err; key del campo → `os.environ`; sin key → banner err |
| 0.08 | 1/4 Audio | `extraer_audio(..., on_telemetria)` vía `_ejecutar_paso_con_telemetria` → ticks en vivo `etapa="descarga"` (`porcentaje`, `velocidad_red`, `tamano_total`, `eta`, `Fragmentos cur/tot`) + `obtener_duracion_media` |
| 0.30 | 2/4 Gemini | `analizar_con_gemini(..., on_telemetria)` → ticks `etapa="gemini"` (`bloque_actual`, `total_bloques`, `modelo_ia`). Si `solo_analisis` → 1.0 y fin |
| 0.55 | 3/4 Fuente | `descargar_video_fuente(..., on_telemetria)` si ≤3600 s (`etapa="descarga_video"`); si no, seek remoto |
| — | Auth YT | `autenticar_youtube(False)` si `subir_auto_yt` |
| 0.60→0.95 | 3/4 Render + 4/4 Upload por clip | `procesar_clip_ffmpeg(..., on_telemetria)` vía `_ejecutar_paso_con_telemetria` → ticks en vivo `etapa="render"` (`porcentaje`, `fps`, `velocidad_x`, `eta`, `encoder`, `clip_id`, `clip_indice/total_clips`) → `subir_short` (`etapa="youtube"`). En ticks de telemetría intermedios (sin hito/video nuevo), Gradio retorna `gr.skip()` para galería/video/historial evitando re-escaneo de disco |
| 1.0 | Fin | Reescribe `clips.json`, refresca galería/historial, `telemetria_panel` al 100% y banner con nº renderizados/subidos |
| — | `except Exception` | Banner err con `str(e)`; refresca galería/historial |
| — | `finally` | Borra `temp_audio.mp3`, `temp_source.mp4` y limpia `STREAM_URL_CACHE` |

**Estado:** la GUI no usa `gr.State`; todo el estado vive en disco (`clips.json`, `subidas_shorts.json`, `clips_finales/`). Los logs se acumulan en una lista local por ejecución (y se imprimen en stdout).

---

## 5. Contratos de Datos y Esquemas JSON

### 5.1 `clips.json` (sincronizado entre `jobs/<job_id>/clips.json` y la raíz del proyecto)

Ciclo de vida: generado por `analizar_con_gemini` (en `job_dir` y sincronizado en raíz) → actualizado tras render/subida (CLI y GUI). Cada ejecución mantiene su versión histórica inmutable dentro de `jobs/<job_id>/clips.json`, mientras que `BASE_DIR / "clips.json"` actúa como puntero al último estado generado.

#### Esquema Multiplataforma v3 (Shorts + TikTok)

El modelo Pydantic `ClipViral` en [pipeline_viral_clips.py](file:///home/bastiboy/clips_automation/pipeline_viral_clips.py) exige metadatos diferenciados para **YouTube Shorts** y **TikTok** manteniendo retrocompatibilidad con archivos `clips.json` v1/v2 y `subidas_shorts.json`:

| Campo | Plataforma | Tipo | Regla / Normalización en `_limpiar_y_parsear_json` |
|---|---|---|---|
| `id` | Común | `int` | Secuencial `1..N` tras validación temporal |
| `inicio` / `fin` | Común | `str` | Formato `HH:MM:SS`, `fin - inicio >= 5s`, `fin <= duracion_total` |
| `gancho` | Común | `str` | Frase literal de apertura (primeros 2 segundos) |
| `razon_viral` | Común | `str` | Gatillo psicológico/narrativo de retención |
| `titulo` | YouTube Shorts | `str` | ≤ 60 caracteres (recorte a 57 + `"..."`) |
| `descripcion` | YouTube Shorts | `str` | 2 líneas + CTA + `#Shorts` garantizado |
| `etiquetas` | YouTube Shorts | `List[str]` | 8 a 12 tags SEO sin prefijo `#` (`_normalizar_etiquetas`) |
| `caption_tiktok` | TikTok (v3) | `str` | ≤ 150 caracteres para SEO semántico y comentarios; fallback autogenerado desde `gancho`/`titulo` si falta |
| `hashtags_tiktok` | TikTok (v3) | `List[str]` | Exactamente 3 a 5 hashtags con prefijo `#`; si falta en v1/v2 reutiliza tags relevantes de `etiquetas` + defaults TikTok |
| `gancho_visual_portada` | TikTok (v3) | `str` | Titular visual de 4 a 6 palabras para portada/primeros 2s; fallback autogenerado desde `titulo`/`gancho` si falta |
| `subtitulos` | Común | `List[SegmentoSubtitulo]` | Segmentos `{inicio_rel, fin_rel, texto}` (2–4 palabras, máx 22 chars, sin emojis, sin solapes; auto-divididos si exceden 5 palabras o 28 chars) |

```jsonc
[
  {
    "id": 1,                              // int, secuencial 1..N (re-numerado tras validación y deduplicación)
    "titulo": "string ≤60",               // YouTube Shorts: recortado a 57+"..." si excede
    "inicio": "HH:MM:SS",                 // normalizado (+offset_seg si vino de chunking >55 min)
    "fin": "HH:MM:SS",                    // ≤ duracion_total
    "gancho": "string",
    "razon_viral": "string",
    "descripcion": "string con \\n y #Shorts",
    "etiquetas": ["8..12 strings sin #"],
    "caption_tiktok": "string ≤150",      // TikTok v3: SEO semántico + detonador de comentarios
    "hashtags_tiktok": ["#tag1", "#tag2", "#tag3"], // TikTok v3: exactamente 3..5 hashtags con #
    "gancho_visual_portada": "TITULAR DE 4 A 6 PALABRAS", // TikTok v3: portada / primeros 2s
    "subtitulos": [                       // opcional (default []), segmentos relativos al clip
      {
        "inicio_rel": 0.0,                // float segundos >= 0.0 (no se suma offset_seg)
        "fin_rel": 1.8,                   // float segundos <= duracion_clip
        "texto": "¡NO PUEDE SER!"         // bloque corto (2-4 palabras, máx 22 chars, sin emojis)
      }
    ],
    "duracion_segundos": 51,              // int (fin-inicio)
    "modelo_ia": "gemini-3.8-flash",      // modelo que respondió con éxito
    // --- añadidos en fase render/subida ---
    "archivo_local": "/home/bastiboy/clips_automation/clips_finales/<job_id>_clip_1.mp4",
    "youtube_id": "omzV0U7F9RQ",          // solo si se subió
    "youtube_url": "https://youtube.com/shorts/omzV0U7F9RQ",
    "youtube_status": "Subido (Privado)"  // ver valores posibles abajo
  }
]
```
**Valores de `youtube_status`:** CLI → `"Subido (Privado)"`, `"No subido (<err[:80]>)"`, `"Subida omitida (--sin-subida)"`, `"Pendiente de subida (Sin credenciales activas)"`. GUI → `"Subido (Privado)"`, `"Error subida (<err[:60]>)"`, `"Subida desactivada por usuario"`, `"Local (Sin token activo)"`.

**Ejemplo real (estado actual, 5 clips, VOD de Kick de ~2 h 06 min, streamer "Yhap"):**
```json
{
  "id": 1,
  "titulo": "¿CUÁNTO LE REBAJAMOS AL CAMARÓGRAFO? 😡📉",
  "inicio": "00:11:43",
  "fin": "00:12:34",
  "gancho": "Vea cómo nos tocó transmitir hoy",
  "razon_viral": "Tensión y comedia involuntaria al exponer un fallo técnico en vivo. Apela a la cultura streamer de WestCOL con el tema de rebajar el sueldo a los trabajadores por 'strikes'.",
  "descripcion": "Yhap se enfurece con su camarógrafo por no configurar el PC y le pide al chat fijar la multa.\n¡Suscríbete a Kicksazos para ver lo mejor del streaming colombiano! #Shorts #Kicksazos #WestCOL #KickColombia #StreamColombia",
  "etiquetas": ["WestCOL","Kicksazos","StreamColombia","KickColombia","Yhap","Pasto","Medellín","ClipsKick","IRLColombia","HumorPaisa"],
  "duracion_segundos": 51,
  "modelo_ia": "gemini-3.8-flash",
  "archivo_local": "/home/bastiboy/clips_automation/clips_finales/clip_1.mp4",
  "youtube_id": "omzV0U7F9RQ",
  "youtube_url": "https://youtube.com/shorts/omzV0U7F9RQ",
  "youtube_status": "Subido (Privado)"
}
```
Resumen del resto: id2 `00:20:58→00:21:48` (50 s, W-ybt9xaGvU) · id3 `00:55:54→00:57:05` (71 s, KZB9ToKaeaU) · id4 `01:04:01→01:04:52` (51 s, -Hd7i3Y4IUg) · id5 `01:23:44→01:24:28` (44 s, H-fGRr_ySXo). Todos `gemini-3.8-flash`, "Subido (Privado)".

### 5.2 `subidas_shorts.json` (raíz; historial acumulativo, nunca se trunca)

```jsonc
[
  {
    "clip_id": 1,                 // int | null (null en subidas manuales vía subir_shorts.py main / subir_lote.py)
    "archivo": "clip_1.mp4",      // basename — CLAVE de cruce con la galería (no es única entre runs)
    "ruta_archivo": "/home/bastiboy/clips_automation/clips_finales/clip_1.mp4",
    "youtube_id": "LQIcG8bjKNQ",  // clave de deduplicación
    "url": "https://youtube.com/shorts/LQIcG8bjKNQ",
    "titulo": "¡LO TIENEN ACORRALADO EN PLENO IRL! 😂👀 #Shorts",
    "descripcion": "...\n¡Suscríbete a Kicksazos ...! #Shorts #Kicksazos #StreamColombia #KickColombia",
    "etiquetas": ["Kicksazos","StreamColombia","..."],
    "privacidad": "private",
    "publish_at": "2026-11-12T23:00:00Z", // null o string ISO 8601 UTC si fue programado
    "cuenta_id": "d4a8f9c21b3e",          // hash SHA-256 corto del refresh_token/client_id (sin exponer secretos)
    "categoryId": "24",
    "madeForKids": false,
    "fecha_subida": "2026-11-11T00:20:13"   // ISO local, sin zona horaria
  }
]
```
**Contenido actual (7 registros históricos + nuevos registros enriquecidos):**

| # | clip_id | archivo | youtube_id | fecha_subida | Observación |
|---|---|---|---|---|---|
| 1 | 1 | clip_1.mp4 | LQIcG8bjKNQ | 2026-11-11T00:20:13 | Run previo (cuenta anterior) |
| 2 | 1 | clip_1.mp4 | omzV0U7F9RQ | 2026-11-11T00:44:20 | Run actual de `clips.json` (cuenta anterior) |
| 3–6 | 2–5 | clip_2..5.mp4 | W-ybt9xaGvU, KZB9ToKaeaU, -Hd7i3Y4IUg, H-fGRr_ySXo | 00:45–00:48 | Cuenta anterior |
| 7 | null | clip_1.mp4 | FJnV_odrhC4 | 2026-11-11T20:49:06 | **Prueba de la cuenta NUEVA** vía `subir_shorts.py` (título "¡Momento Épico en Vivo! 😂 #Shorts") |

> ✅ Desde la **Fase 3**, cada nuevo registro guarda `"cuenta_id"` (hash seguro SHA-256 de 12 chars derivado de las credenciales OAuth activas) y `"publish_at"` para distinguir analíticas entre canales y rastrear publicaciones diferidas. Además, `verificar_cuota_diaria()` inspecciona dinámicamente este archivo para no superar el límite de 6 subidas por ventana de 24h.

### 5.3 `clips_virales/reporte_clips.json` (LEGACY)
```json
[{"id": 1, "titulo": "Casi nos chocamos en la calle", "inicio": "00:12:48", "fin": "00:13:08",
  "gancho": "No, pues es que bro, ¿cómo", "razon_viral": "Un momento de peligro inminente ..."}]
```
7 clips, sin campos SEO. Consumido solo por `subir_lote.py`.

### 5.4 Archivos temporales y de proceso

| Archivo | Creado por | Eliminado por | Notas |
|---|---|---|---|
| `temp_audio.mp3` | `extraer_audio` | `ejecutar_pipeline_completo` `finally` | Aislado en `jobs/<job_id>/` |
| `temp_audio_chunk_<idx:02d>.mp3` | `_segmentar_audio_en_chunks` | `analizar_con_gemini` `finally` | Solo audios `>55 min` (`>3300 s`); corte `-c copy` |
| `temp_audio.*` (`.mp4`, `.part`, `.ytdl`, `.webm`) | yt-dlp (intermedios) | Siguiente `extraer_audio` / fallback (glob) | Limpieza por `job_dir` |
| `temp_source.mp4` | `descargar_video_fuente` | `_orquestar_render_y_subida` `finally` | Solo VOD ≤1 h |
| Archivo remoto Gemini `files/<id>` | `client.files.upload` | `_analizar_archivo_audio_gemini` `finally` | Expira solo a las ~48 h si no se borra |
| `clips_finales/<job_id>_clip_<id>.mp4` | `procesar_clip_ffmpeg` | **Nunca** (aislado por `job_id`) | Renders finales 1080×1920 |

---

## 6. Historial de Decisiones Técnicas y Problemas Resueltos

Reconstruido a partir del código actual, el `.bak`, los scripts legacy, timestamps de archivos y `gradio.log`.

### 6.1 Cronología

| Fecha (2026-11) | Hito | Evidencia |
|---|---|---|
| 07 ~00:28–01:55 | Creación del venv; prototipos `analizar_stream.py` (Gemini sobre file ID ya subido, VOD Kick de 3 h) y `recortar_clips.py` (render remoto VOD `kick.com/eldomi`) | mtimes |
| 07 ~04:17–04:58 | Pipeline v1 (`.bak`): audio → Gemini (schema `ColeccionClips`) → render a `clips_virales/`; OAuth (`client_secret.json`); `subir_lote.py` | mtimes, 33 mp4 en `clips_virales/` |
| 07 18:34 | Último run legacy (`reporte_clips.json`) | mtime |
| 10 ~19:56–22:25 | Pipeline v2: `.env` + dotenv, salida `clips_finales/clip_<id>.mp4`, wrapper `procesar_video_universal.py`, doc previo | `clip_6.mp4` (23.976 fps, fuente distinta) |
| 11 00:14–00:48 | SEO completo en `ClipViral`, subida automática privada integrada en pipeline y GUI; run E2E (VOD Kick 2 h 06 min) con 5 clips subidos | `gradio.log`, `subidas_shorts.json` |
| 11 17:21–17:23 | Ajustes finales en `pipeline_viral_clips.py`; re-render de `clip_1.mp4` | mtimes |
| 11 20:36 | Nuevo `assets/watermark.png` (946×262; antes 500×120) | `file`, `gradio.log` |
| 11 20:47–20:49 | **Cambio de cuenta OAuth**: token anterior respaldado en `token_cuenta_anterior.json`, nuevo `token.json`, upload de prueba `FJnV_odrhC4` | mtimes, registro #7 |
| 12 01:31–01:35 | Evolución v3: esquema multiplataforma YouTube Shorts + TikTok, curaduría 2026, Safe Zones y tarjetas duales Gradio | `pipeline_viral_clips.py`, `app_interfaz.py` |
| 12 20:55 | **Actualización v3.1**: `extraer_audio` paralelo 16x (+ `aria2c`), chunking >55 min con offsets/deduplicación, salto 0s Free Tier `429`, curaduría dinámica sin límites fijos, `temperature=0.20`, subtítulos `.ass` rediseñados con `fc-list` + auto-partición + *pop-in* y suite unitaria offline | `pipeline_viral_clips.py`, `tests/test_pipeline_v31.py` |
| 13 00:05 | **Actualización v3.2**: Tipografía ExtraBold local embebida (`assets/fonts/Montserrat-ExtraBold.ttf` + `:fontsdir=` en `libass`, `WrapStyle: 2`, mayúsculas automáticas, `Fontsize=54`, `MarginV=550`, `MarginR=210`), telemetría en vivo (`yt-dlp --newline`, bloques Gemini, `ffmpeg -progress pipe:1`, `_ejecutar_paso_con_telemetria`), panel HTML/CSS animado en Gradio (`telemetria_panel` + `gr.skip()`), barra visual `RenderizadorProgresoCLI` y suite `test_pipeline_v32.py` | `assets/fonts/`, `pipeline_viral_clips.py`, `app_interfaz.py`, `tests/test_pipeline_v32.py` |

### 6.2 Decisiones arquitectónicas (v1 → v2 → v3.2)

| Tema | v1 (`.bak`) | v3 / v3.2 (actual) | Motivo |
|---|---|---|---|
| Invocación yt-dlp | Binario `yt-dlp` + `--user-agent` Chrome | `sys.executable -m yt_dlp --newline --progress` + `--js-runtimes node --remote-components ejs:github` | Garantizar versión del venv, soporte JS de YouTube y líneas limpias para telemetría MB/s en vivo |
| Extracción de audio | Secuencial / un solo hilo | Primario `yt-dlp --concurrent-fragments 16` (+ `aria2c` en YouTube) con telemetría `Popen` + fallback `yt-dlp -g` + `ffmpeg -reconnect* -progress pipe:1` | Saturar ancho de banda, emitir MB/s + ETA en tiempo real y evitar fallos HLS |
| Audios > 55 min | Envío monolítico en una petición | Chunking automático `ffmpeg -c copy` en bloques de 45 min con 90 s de solape, ajuste de offsets y telemetría por bloque/modelo | Evitar rechazo >250k tokens en Free Tier y truncamiento en VODs de 2.5–4 h |
| Fuente de render | Siempre URL HLS remota (`-f best -g`) | Descarga local si ≤1 h (con telemetría MB/s); remoto con flags `-reconnect*` si no | Muchas conexiones HLS por clip eran lentas/inestables |
| Formatos | `best` | `FORMATOS_VIDEO_RAPIDOS` (≤1080p, evita `m3u8_native`) | Velocidad de descarga/seek |
| Llamada Gemini | `generate_content` (bloqueante) | `generate_content_stream` + timeout 600 s + `temperature=0.20` | Evitar timeouts y maximizar precisión fonética literal sin alucinaciones |
| Schema | `ColeccionClips {clips: [...]}` | `list[ClipViral]` directo + parser tolerante (3 niveles, `permitir_vacio`) | Respuestas más simples, soporte TikTok v3 y tolerancia a chunks muertos |
| Reintentos | 5 intentos/modelo, backoff lineal 10 s·n | 4 intentos/modelo con jitter (`4..25s`) en 503/RPM; **salto 0s (`break`) en 429 cuota diaria Free Tier** y 400/404 | No perder tiempo reintentando cuotas diarias agotadas (`limit: 20` / `PerDay`) |
| Modelos | 3.8-flash → 3.5-flash → 3.1-flash-lite | Terna activa `MODELOS_CANDIDATOS` (`3.8-flash`, `3.7-flash`, `3.5-flash-lite`) + preferido elegible | IDs inexistentes daban 404; resiliencia ante 503/429 |
| Cantidad y duración | 15–45 s estricta | 100% dinámica guiada por calidad/retención (22–45 s Shorts / 60–75 s TikTok) | Eliminar relleno artificial y cortes abruptos |
| Metadatos | titulo ≤6 palabras, gancho, razón | + descripción con CTA, 8–12 etiquetas YT + `caption_tiktok`, `hashtags_tiktok`, `gancho_visual_portada` | Habilitar publicación multiplataforma YouTube Shorts + TikTok |
| Validación temporal | Ninguna | Clamp a duración real, mín 5 s, descarte fuera de rango, deduplicación `>50%` solape | Evitar alucinaciones de timestamps y duplicados en bordes de chunks |
| Subtítulos `.ass` | Sin subtítulos | **Tipografía local embebida (`Montserrat ExtraBold` via `:fontsdir=assets/fonts`)**, `WrapStyle: 2`, tamaño `54`, `Spacing=1.5`, `Outline=5.5`, `Shadow=3.5`, `BackColour=&HA0000000`, `MarginL=65`, `MarginR=210`, `MarginV=550`, `.upper()`, auto-partición 2–4 palabras y *pop-in* | Elimina caída a `DejaVu Sans` / `Noto Sans` en Linux, evita saltos de línea no deseados e incrementa contraste y retención móvil |
| Telemetría de ejecución | `subprocess.run` silencioso / solo spinner Gradio | Streaming `on_telemetria` (`<= 3 Hz`), puente worker `_ejecutar_paso_con_telemetria`, `ffmpeg -progress pipe:1` (`out_time_us`, FPS, `x`, ETA, encoder), panel HTML/CSS animado (`gr.skip()`) y `RenderizadorProgresoCLI` | Visibilidad completa en vivo (MB/s, ETA, bloque IA, FPS/VAAPI) sin bloquear el generador ni saturar UI |
| Filtro 9:16 | Blur `boxblur=20:5` a 1080×1920 | Blur a 360×640 `boxblur=10:2` + upscale bilinear; watermark adaptativa | Rendimiento y branding |
| Salida | `clips_virales/clip_NN_<slug>.mp4` | `clips_finales/<job_id>_clip_<id>.mp4` | Aislamiento por job y cruce determinista con `clips.json`/historial |
| Upload | Script separado (`subir_lote.py`) | Integrado por clip, cuota 6/24h, programación `publishAt`, nunca bloquea render | E2E autónomo |

### 6.3 Problemas resueltos

1. **Errores 503/404/429 de Gemini** → cascada de modelos + matriz de errores (§4.2.2). 400/404 y **429 cuota diaria Free Tier (`free_tier_requests` / `PerDay` / `per day` / `limit: 20`)** ejecutan salto inmediato (`0.00s`).
2. **JSON malformado / envuelto en markdown** → `response_schema` + limpieza de fences + regex `\[.*\]` + pydantic (`permitir_vacio=True` para chunks sin eventos).
3. **Timestamps fuera de rango** → `duracion_total` inyectada en el prompt + clamp en post-proceso.
4. **Archivo de audio no listo** (`PROCESSING`) → polling hasta `ACTIVE` con timeout.
5. **Audio pesado y límite de tokens en streams de varias horas (>55 min)** → mono 16 kHz 32 kbps (≈14 MB/h) + `_segmentar_audio_en_chunks` (bloques de 45 min con 90 s de solapamiento vía `ffmpeg -c copy`), ajuste de offsets `+offset_seg` en `inicio`/`fin` (conservando `subtitulos` relativos) y `_deduplicar_clips_solapados` (`>50%` overlap).
6. **Eliminación de dependencias pesadas (`PyAV` / `Whisper`)**: todo el procesamiento multimedia es vía `subprocess` a `ffmpeg`/`ffprobe`/`yt-dlp`, y la transcripción fonética forense proviene directamente del audio en Gemini con `temperature=0.20` + auto-partición en `_normalizar_subtitulos`.
7. **Token OAuth en modo no interactivo** → el pipeline nunca abre navegador; si falla la auth, renderiza localmente y marca el estado.
8. **Cambio de cuenta OAuth** (11-nov 20:47) → respaldo del token anterior y re-autorización interactiva con `subir_shorts.py`; `client_secret.json` (proyecto `kick-clips-auto-514009`) se mantuvo.
9. **Cuello de botella en descarga secuencial HLS/DASH** → resuelto en v3.1 invirtiendo `extraer_audio`: primario con `yt-dlp --concurrent-fragments 16 --retries 10 --fragment-retries 10 --retry-sleep fragment:exp=1:10 --socket-timeout 15 --buffer-size 16K --http-chunk-size 10M` (+ `aria2c -x 16 -s 16 -k 1M` si no es Kick/Twitch/HLS `.m3u8`), validando archivo `>10 KB`, con fallback automático a `yt-dlp -g` + streaming directo `ffmpeg -reconnect*`.
10. **Purga de modelos Gemini obsoletos (404) y resiliencia ante 503 / micro-cortes DNS** → terna activa (`gemini-3.8-flash`, `gemini-3.7-flash`, `gemini-3.5-flash-lite`), 4 intentos/modelo y backoff con jitter (`base=4.0` s, `max_espera=25.0` s) para fallos transitorios.
11. **Subtítulos desbordados y caída a fuente fallback del sistema (`DejaVu Sans` / `Noto Sans`)** → resuelto entre v3.1 y **v3.2**: fuente local empaquetada `assets/fonts/Montserrat-ExtraBold.ttf`, resolución exacta de `fullname` vía `fc-scan` (`Montserrat ExtraBold`), inyección explícita `subtitles='<ass>':fontsdir='<dir>'` en FFmpeg, `WrapStyle: 2`, estilo ampliado (`Fontsize=54`, `Spacing=1.5`, `Outline=5.5`, `Shadow=3.5`, `BackColour=&HA0000000`, `MarginL=65`, `MarginR=210`, `MarginV=550`) y texto en **MAYÚSCULAS**.
12. **Falta de visibilidad en vivo durante descargas y renders largos** → resuelto en **v3.2** mediante parsing en tiempo real de `yt-dlp --newline` + `aria2c` (`MB/s`, `%`, `ETA`, fragmentos), `ffmpeg -progress pipe:1` (`out_time_us` en microsegundos, FPS, velocidad `x`, ETA real y encoder activo), throttling `<= 3 Hz`, cierre seguro de pipes `_cerrar_pipes_proceso`, puente por cola `_ejecutar_paso_con_telemetria`, panel HTML/CSS animado con `gr.skip()` en Gradio y `RenderizadorProgresoCLI` en terminal.

### 6.4 Discrepancias del doc previo (`Contexto y Objetivos del Proyecto Kicksazos.md`) vs. código real

| Afirmación del doc previo | Realidad en el código |
|---|---|
| "Exponential backoff con jitter" | Implementado con jitter aleatorio real (`_esperar_con_jitter`) con base 4.0 s y techo 25.0 s para 503/429 transitorios/red, y salto `0s` en 429 cuota diaria |
| "Máscara de recorte previa para subtítulos incrustados" | No existe ningún filtro de máscara/crop de subtítulos |
| "PyAV sustituido por subprocess con pipes asíncronos" | `subprocess.Popen` con lectura en streaming de progreso (`yt-dlp --newline` y `ffmpeg -progress pipe:1`) |
| GUI: selector de nº de clips, tabla editable de timestamps, controles de blur/watermark/aspect, botón de descarga | No existen; la GUI tiene URL, modelo, 2 checkboxes, API key, programación `publishAt`, banner, **panel animado de telemetría en vivo**, logs, preview, galería e historial |
| Clips de 30–60 s | Curaduría 100% dinámica sin límites artificiales (prioriza 22–45 s Shorts / 60–75 s TikTok) |
| Python 3.10+, Ubuntu 22.04/Debian/WSL2, FFmpeg 5+ | Kubuntu, Python 3.14.4, FFmpeg 8.0.1 |
| Subida a YouTube como "objetivo futuro" | **Ya implementada** (privado y programado) |
| Metadatos SEO por IA como "futuro" | **Ya implementados** (YouTube Shorts + TikTok) |

---

## 7. Estado Actual, Limitaciones Conocidas y Roadmap

### 7.1 Qué funciona (verificado con artefactos y pruebas)

- ✅ Control de versiones activo con Git y `.gitignore` estricto (credenciales, artefactos multimedia, temporales y caché).
- ✅ Entorno limpio con `requirements.txt` explícito y dependencias residuales desinstaladas (`openai-whisper`, `faster-whisper`, `av`).
- ✅ Rutas absolutas ancladas a `BASE_DIR = Path(__file__).resolve().parent` en todos los módulos activos (`pipeline_viral_clips.py`, `subir_shorts.py`, `app_interfaz.py`, `procesar_video_universal.py`).
- ✅ Aislamiento por jobs (`jobs/<job_id>/`) con temporales locales (`temp_audio.mp3`, `temp_audio_chunk_*.mp3`, `temp_source.mp4`, `subs_<id>.ass`, `clips.json`) y prefijo único en renders (`<job_id>_clip_<id>.mp4`).
- ✅ Código y artefactos obsoletos archivados en `legacy/`.
- ✅ Extracción de audio y descarga de video fuente con `yt-dlp --newline --concurrent-fragments 16` (+ `aria2c` fuera de Kick/Twitch/HLS), telemetría MB/s + ETA en vivo y fallback automático `yt-dlp -g` + `ffmpeg -vn -progress pipe:1 -reconnect*`.
- ✅ Chunking automático de audios `>55 min` (`>3300 s`) en bloques de 45 min con 90 s de solapamiento, desplazamiento de offsets, tolerancia a chunks vacíos (`[]`), deduplicación `>50%` y telemetría por bloque/modelo.
- ✅ Cascada de modelos Gemini (`gemini-3.8-flash`, `gemini-3.7-flash`, `gemini-3.5-flash-lite`) con `temperature=0.20`, salto `0.00s` en cuota diaria Free Tier `429` y curaduría de cantidad 100% dinámica.
- ✅ Caché en memoria (`STREAM_URL_CACHE`) por `job_id` con invalidación y reintento ante errores HTTP 403/410.
- ✅ Renderizado acelerado por hardware **VAAPI** (`h264_vaapi -qp 23` en `/dev/dri/renderD128` para GPU AMD Radeon 610M) con fallback automático a CPU (`libx264 -preset veryfast -crf 22`) y telemetría `-progress pipe:1` (FPS, `x`, ETA, encoder).
- ✅ Watermark adaptativa (`ffprobe` + expresión dinámica según aspecto / 9:16), corte exacto `-t <duracion>` y quemado de subtítulos `.ass` **v3.2** con **fuente local embebida** (`assets/fonts/Montserrat-ExtraBold.ttf` vía `:fontsdir=`), `WrapStyle: 2`, tamaño `54`, `Spacing=1.5`, `Outline=5.5`, `Shadow=3.5`, `BackColour=&HA0000000`, `MarginL=65`, `MarginR=210`, `MarginV=550`, MAYÚSCULAS, auto-partición 2–4 palabras, *pop-in* y filtro anti-emojis.
- ✅ Subida privada y programada (`publishAt`) a YouTube Shorts con registro en `subidas_shorts.json`.
- ✅ Suite unitaria automatizada (`tests/test_pipeline_v31.py` + `tests/test_pipeline_v32.py`, 30 tests totales aprobados offline + validación real de `ffmpeg`/`libass` con `fontsdir=Montserrat-ExtraBold` y compilación `py_compile`).
- ✅ GUI Gradio operativa con panel animado de telemetría en vivo (`telemetria_panel`), `gr.skip()` en ticks intermedios, soporte para jobs, resolución dinámica de `archivo_local`, galería y CLI con `RenderizadorProgresoCLI`.

### 7.2 Limitaciones y puntos frágiles

**Concurrencia / estado global**
1. [RESUELTO - FASE 1] Aislamiento de ejecuciones mediante `crear_contexto_job(url)`: cada job tiene su directorio en `jobs/<job_id>` con sus propios temporales y `clips.json`.
2. [RESUELTO - FASE 1] Rutas relativas al CWD eliminadas: todos los scripts resuelven rutas respecto a `BASE_DIR`.
3. [RESUELTO - FASE 1] Sobrescritura de clips: renders nombrados como `<job_id>_clip_<id>.mp4` en `clips_finales/`.
4. `GEMINI_API_KEY` ingresada en la GUI muta `os.environ` de forma persistente para el proceso.

**Robustez**
5. [RESUELTO - FASE 3] Tolerancia a fallos por clip: si un clip individual falla en renderizado o subida, se captura en su propio bloque `try/except`, se actualizan `render_status` y `youtube_status`, se sincroniza `clips.json` incrementalmente y el lote continúa.
6. [RESUELTO - FASE 3] Límite de cuota YouTube mitigado: `verificar_cuota_diaria(limite_diario=6)` omite subidas adicionales marcando `"Pendiente por cuota diaria (6/24h)"` antes de invocar la API. `next_chunk()` ahora tiene hasta 4 reintentos con backoff exponencial y jitter ante HTTP 5xx o errores de transporte.
7. [RESUELTO - FASE 2] `obtener_urls_stream` y dimensiones de stream ahora se cachean en memoria por `job_id` en `STREAM_URL_CACHE`, con invalidación automática y reintento ante HTTP 403/410.
8. [RESUELTO - v3.1/v3.2] `extraer_audio` prioriza descarga paralela `yt-dlp --newline --concurrent-fragments 16` (+ `aria2c` en YouTube/no-HLS) con telemetría en vivo y fallback automático a streaming directo FFmpeg `-vn -progress pipe:1 -reconnect*`.
9. [RESUELTO - v3.1] Audios largos (`>55 min`) se segmentan automáticamente con `ffmpeg -c copy` en bloques de 45 min con 90 s de solapamiento, ajuste de offsets y deduplicación, evitando rechazos de cuota/tokens (>250k) en Free Tier.
10. [RESUELTO - v3.1/v3.2] Cuota diaria Free Tier (`429`) rota instantáneamente en `0.00s` al siguiente modelo; subtítulos `.ass` usan fuente local `Montserrat-ExtraBold.ttf` (`fontsdir=`), `WrapStyle: 2`, MAYÚSCULAS y Safe Zone `MarginV=550`, `MarginR=210`.
11. [RESUELTO - FASE 2] `hhmmss_a_segundos` conserva fracciones decimales y `procesar_clip_ffmpeg` usa `-ss <inicio>` + `-t <duracion_clip>` para evitar desfases de cierre.
12. [RESUELTO - FASE 2] Watermark posicionada dinámicamente con `ffprobe` (`y=200` en vertical 9:16 o `max(200, (H-h_fg)/2-h-24)` con barras desenfocadas).
13. [RESUELTO - FASE 3] `analizar_con_gemini` ya no utiliza `sys.exit(1)`; lanza excepciones descriptivas (`RuntimeError`) para integración segura como librería y orquestador.
14. [RESUELTO - FASE 3] Sanitización HTML completa: `_banner_html`, `construir_panel_telemetria_html`, `construir_tarjetas_galeria_html` y `obtener_tabla_historial` aplican `html.escape()` sobre todos los textos dinámicos de entrada y salida, eliminando riesgos XSS.
15. Los IDs de modelo de `MODELOS_CANDIDATOS` deben mantenerse al día.
16. [RESUELTO - FASE 3/v3.2] Unificación de orquestación con streaming de telemetría: `ejecutar_pipeline_completo()` (`_ejecutar_paso_con_telemetria`) emite diccionarios `"telemetria"` consumidos en vivo tanto por CLI (`RenderizadorProgresoCLI`) como por Gradio (`ejecutar_pipeline_gradio()` + `construir_panel_telemetria_html()`).
17. El refresh token puede caducar (7 días si la app OAuth está en modo Testing).

**Higiene del repo**
18. [RESUELTO - FASE 1] Git inicializado con `.gitignore` exhaustivo y `requirements.txt`.
19. [RESUELTO - FASE 1] Paquetes residuales pesados desinstalados del venv (`openai-whisper`, `faster-whisper`, `av`).
20. [RESUELTO - FASE 1] Scripts legacy archivados de forma segura en `legacy/`.

### 7.3 Roadmap de Siguientes Fases

| Prioridad | Fase / Tarea | Detalle |
|---|---|---|
| ✅ Hecho | **Fase 1: Higiene, Seguridad, Rutas y Jobs** | Git, `.gitignore`, `requirements.txt`, `BASE_DIR`, `crear_contexto_job()`, `legacy/` |
| ✅ Hecho | **Fase 2: Red, VAAPI, Precisión y Subtítulos `.ass`** | Caché de URLs + invalidación 403/410, `h264_vaapi` + fallback `libx264`, watermark adaptativa + `-t` exacto, `SegmentoSubtitulo` + `.ass` |
| ✅ Hecho | **Fase 3: Orquestación Unificada, Cuota y Seguridad** | `ejecutar_pipeline_completo()`, tolerancia por clip, `verificar_cuota_diaria()`, `cuenta_id`, `publishAt`, sanitización HTML |
| ✅ Hecho | **v3.1: Performance, Chunking & Subtítulos de Alta Precisión** | Descarga paralela 16x (+ `aria2c`), chunking `>55 min` con offsets/dedupe, salto `0s` en 429 Free Tier, curaduría dinámica, `temperature=0.20`, `.ass` estilizado + auto-partición + *pop-in* |
| ✅ Hecho | **v3.2: Tipografía Embebida & Telemetría Gráfica en Vivo** | `assets/fonts/Montserrat-ExtraBold.ttf` + `fontsdir=` en `libass`, `WrapStyle: 2`, MAYÚSCULAS, `.ass` ampliado, `yt-dlp --newline`, `ffmpeg -progress pipe:1`, `_ejecutar_paso_con_telemetria`, panel HTML/CSS animado en Gradio (`gr.skip()`), `RenderizadorProgresoCLI` |
| ✅ Hecho | **Suites de pruebas automatizadas (`unittest`)** | `tests/test_pipeline_v31.py` (16 tests) + `tests/test_pipeline_v32.py` (14 tests) offline + smoke real `ffmpeg`/`libass` + `fontsdir=` |
| P2 | **Acelerador opcional en SO / Cola de Jobs** | Instalar `aria2` en Kubuntu para maximizar descargas DASH en YouTube; evaluar cola secuencial multi-URL sin bloqueo UI |

---

## 8. Apéndice: Referencia Rápida para Agentes

```bash
cd ~/clips_automation && source venv/bin/activate

# Validación de sintaxis y suites unitarias completas (v3.1 + v3.2)
/home/bastiboy/clips_automation/venv/bin/python -m py_compile pipeline_viral_clips.py app_interfaz.py subir_shorts.py procesar_video_universal.py
/home/bastiboy/clips_automation/venv/bin/python -m unittest discover -s tests -v

# Pipeline completo (análisis + render + subida privada) con barra de progreso en vivo
/home/bastiboy/clips_automation/venv/bin/python pipeline_viral_clips.py "https://kick.com/<canal>/videos/<uuid>"
/home/bastiboy/clips_automation/venv/bin/python pipeline_viral_clips.py "<URL>" --solo-analisis            # solo clips.json
/home/bastiboy/clips_automation/venv/bin/python pipeline_viral_clips.py "<URL>" --sin-subida --modelo gemini-3.8-flash

# GUI Gradio (incluye panel HTML/CSS animado de telemetría en vivo)
/home/bastiboy/clips_automation/venv/bin/python app_interfaz.py            # http://127.0.0.1:7860

# Re-render de un clip puntual (usa assets/watermark.png → clips_finales/clip_<ID>.mp4)
/home/bastiboy/clips_automation/venv/bin/python procesar_video_universal.py "<URL|archivo.mp4>" 00:11:43 00:12:34 1

# (Re)autorizar YouTube / cambiar de cuenta  ⚠ sube un video de prueba privado
mv token.json token_backup.json && /home/bastiboy/clips_automation/venv/bin/python subir_shorts.py
```

**Reglas para agentes que modifiquen el sistema:**
- No exponer ni imprimir `.env`, `client_secret.json`, `token*.json`.
- No modificar `subir_shorts.py` ni sus scopes OAuth (`youtube.upload`) ni `verificar_cuota_diaria(limite_diario=6)` salvo instrucción explícita.
- Ejecutar usando el entorno `/home/bastiboy/clips_automation/venv/bin/python` (todas las rutas activas usan `BASE_DIR` y temporales aislados en `jobs/<job_id>/`).
- Si ejecutas CLI y GUI simultáneamente, `BASE_DIR / "clips.json"` reflejará el último job completado; cada job conserva su propio `jobs/<job_id>/clips.json`.
- Cambios en la orquestación o telemetría → aplicarlos en `pipeline_viral_clips.ejecutar_pipeline_completo` (consumido por CLI `RenderizadorProgresoCLI` y `app_interfaz.ejecutar_pipeline_gradio` / `construir_panel_telemetria_html`).
- Cambios en `ClipViral` / `SegmentoSubtitulo` → revisar `_limpiar_y_parsear_json`, `construir_prompt_viral`, `_normalizar_subtitulos`, `generar_archivo_ass`, `construir_tarjetas_galeria_html`, `obtener_datos_galeria` y `subir_short`.
- Respetar la cuota de YouTube (~6 subidas/día/proyecto).
