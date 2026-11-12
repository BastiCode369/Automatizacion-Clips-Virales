# CONTEXTO_PROYECTO_KICKSAZOS.md — System Context (Base de Conocimiento Maestra)

> **Generado:** 2026-11-11 21:13 (-05:00) mediante auditoría completa de `~/clips_automation`.
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

1. Recibe una URL (VOD/stream/video de **Kick**, YouTube o Twitch).
2. Extrae una pista de **audio mono 16 kHz / 32 kbps** con `yt-dlp`.
3. Sube el audio a la **Gemini File API** y pide a un modelo Gemini (cascada con fallback) que detecte 3–6 momentos virales, devolviendo **timestamps + metadatos SEO** en JSON estructurado (`clips.json`).
4. Renderiza cada momento en **vertical 9:16 (1080×1920)** con FFmpeg: fondo desenfocado + video centrado sin recorte + marca de agua `assets/watermark.png`.
5. Sube cada clip a **YouTube Shorts en privado** (YouTube Data API v3, OAuth instalado) y registra la trazabilidad en `subidas_shorts.json`.

**Nicho objetivo:** clips IRL / streaming colombiano (Kick Colombia: WestCOL, Blessd, La Liendra, Yhap, eldomi, etc.). Canal destino: **Kicksazos**. Idioma: español coloquial colombiano.

**Puntos de entrada:**

| Entrada | Comando | Uso |
|---|---|---|
| CLI E2E | `venv/bin/python pipeline_viral_clips.py "<URL>" [--solo-analisis] [--sin-subida] [--modelo <id>]` | Pipeline completo headless |
| GUI Gradio | `venv/bin/python app_interfaz.py` → `http://127.0.0.1:7860` | Mismo pipeline con progreso, galería e historial |
| Render manual de 1 clip | `venv/bin/python procesar_video_universal.py <URL\|archivo> <HH:MM:SS> <HH:MM:SS> <ID>` | Re-render puntual |
| Upload de prueba | `venv/bin/python subir_shorts.py` | OAuth interactivo + sube el 1er `.mp4` de `clips_finales/` con metadatos de prueba |

### 1.1 Diagrama de arquitectura (ASCII)

```
                ┌──────────────────────────────────────────────────────────────┐
                │           ENTRADA: URL (Kick / YouTube / Twitch)             │
                │   CLI: pipeline_viral_clips.py main()                        │
                │   GUI: app_interfaz.py ejecutar_pipeline_gradio()            │
                └───────────────────────────────┬──────────────────────────────┘
                                                │
        [1/4] extraer_audio(url)                ▼
        subprocess: python -m yt_dlp -f "ba/b[height<=360]/b/worst" -x mp3
        ffmpeg pp: -ac 1 -ar 16000 -b:a 32k  ──►  ./temp_audio.mp3
                                                │
        obtener_duracion_media() (ffprobe) ──►  duracion_total (float s)
                                                │
        [2/4] analizar_con_gemini()             ▼
        ┌───────────────────────────────────────────────────────────────┐
        │ genai.Client(timeout=600 000 ms)                              │
        │ files.upload (4 reintentos, backoff 3s·n)                     │
        │ polling files.get cada 4 s hasta ACTIVE (máx 150 → ~10 min)   │
        │ CASCADA: [preferido] + MODELOS_CANDIDATOS (2 intentos c/u)    │
        │ generate_content_stream(response_schema=list[ClipViral],      │
        │                         mime=application/json, temp=0.35)     │
        │ _limpiar_y_parsear_json() → validación temporal + SEO         │
        │ finally: files.delete (remoto)                                │
        └───────────────────────────────┬───────────────────────────────┘
                                        ▼
                               ./clips.json  (v1: análisis)
                                        │
        [3/4] Render                    ▼
        ¿duracion_total ≤ 3600 s? ── sí ─► descargar_video_fuente() → ./temp_source.mp4 (≤1080p)
                 │ no / fallo                                         │
                 ▼                                                    │
        obtener_urls_stream() (yt-dlp -g) → URL(s) HLS/MP4 remotas    │
                 └──────────────────────┬─────────────────────────────┘
                                        ▼
        procesar_clip_ffmpeg() por clip: -ss/-to (input seek) + filter_complex 9:16
        + overlay watermark  ──►  ./clips_finales/clip_<id>.mp4  (1080x1920 H.264/AAC)
                                        │
        [4/4] Upload (si habilitado)    ▼
        autenticar_youtube(interactivo=False) → token.json (refresh auto)
        subir_short() → videos.insert(part=snippet,status, resumable)
                  privacy=private, categoryId=24, madeForKids=False
                                        │
                ┌───────────────────────┴───────────────────────┐
                ▼                                               ▼
     ./subidas_shorts.json (append/dedupe por youtube_id)   ./clips.json (v2: + archivo_local,
                                                             youtube_id, youtube_url, youtube_status)
        Limpieza (finally): borra temp_audio.mp3 y temp_source.mp4
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
├── app_interfaz.py                          # [ACTIVO] GUI Gradio (860+ líneas) con soporte de jobs y BASE_DIR
├── pipeline_viral_clips.py                  # [ACTIVO] Núcleo del pipeline + CLI + crear_contexto_job
├── subir_shorts.py                          # [ACTIVO] OAuth + upload YouTube + historial anclado a BASE_DIR
├── procesar_video_universal.py              # [ACTIVO] Wrapper CLI de render con BASE_DIR y soporte de job_id
├── client_secret.json                       # OAuth client (<REDACTED>)
├── token.json                               # OAuth token activo (<REDACTED>)
├── token_cuenta_anterior.json               # Backup token cuenta anterior (<REDACTED>)
├── clips.json                               # Estado: último análisis sincronizado
├── subidas_shorts.json                      # Estado: historial acumulado de subidas (7 registros)
├── gradio.log                               # Log local previo (ignorado por git)
├── Contexto y Objetivos del Proyecto Kicksazos.md   # Doc previo
├── CONTEXTO_PROYECTO_KICKSAZOS.md           # ESTE documento (actualizado Fase 1)
├── assets/
│   ├── watermark.png                        # 946×262 RGBA (marca de agua @Kicksazos)
│   └── Gemini_Generated_Image_qk0ar5qk0ar5qk0a.jpeg  # Arte de marca
├── clips_finales/                           # Salida del pipeline ACTIVO: <job_id>_clip_<id>.mp4
│   ├── clip_1.mp4 … clip_5.mp4              # 1080x1920 @60fps (runs históricos)
│   └── clip_6.mp4                           # 1080x1920 @23.976fps
├── jobs/                                    # [NUEVO] Aislamiento de ejecuciones por job_id (ignorado en git)
│   └── <job_id>/                            # YYYYMMDD_HHMMSS_<slug>/ con temp_audio.mp3, temp_source.mp4, clips.json
└── legacy/                                  # [NUEVO] Scripts y artefactos obsoletos archivados
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
| `MODELOS_CANDIDATOS` | `["gemini-3.8-flash", "gemini-3.5-flash-lite", "gemini-3.1-pro-preview", "gemini-3.7-flash", "gemini-2.5-flash", "gemini-2.5-pro"]` | Orden de la cascada y opciones del dropdown Gradio |
| `RUTA_MARCA_AGUA` | `abspath("assets/watermark.png")` | Resuelta **al importar** (depende del CWD) |
| `CARPETA_SALIDA` | `abspath("clips_finales")` | Salida de renders |
| `FORMATOS_VIDEO_RAPIDOS` | ver §4.1 | Selector `-f` de yt-dlp para video |

**Funciones:**

| Función | Firma | Responsabilidad | Efectos laterales |
|---|---|---|---|
| `ClipViral` | `BaseModel` | Esquema estricto de un clip (id, titulo, inicio, fin, gancho, razon_viral, descripcion, etiquetas) | Se pasa como `response_schema=list[ClipViral]` a Gemini |
| `obtener_duracion_media` | `(ruta) -> float\|None` | `ffprobe -v error -show_entries format=duration -of default=noprint_wrappers=1:nokey=1` | Ninguno; devuelve `None` ante cualquier error |
| `segundos_a_hhmmss` | `(float) -> str` | Redondeo a entero, `HH:MM:SS` | — |
| `hhmmss_a_segundos` | `(str) -> float` | Acepta `HH:MM:SS`, `MM:SS`, `SS`; **descarta fracciones** (`split(".")[0]`) | `ValueError` si >3 partes |
| `_obtener_estado_archivo` | `(file) -> str` | Normaliza `file.state` (enum o str) | — |
| `_normalizar_etiquetas` | `(Any) -> List[str]` | Acepta lista o string separado por `,;\n`; quita `#`; dedup; rellena con defaults hasta 8; corta a 12 | — |
| `_limpiar_y_parsear_json` | `(texto, duracion_total) -> List[dict]` | Quita fences markdown, valida con pydantic (3 niveles de fallback), validación temporal y enriquecimiento SEO | `ValueError` si no queda ningún clip |
| `extraer_audio` | `(url) -> "temp_audio.mp3"` | yt-dlp → MP3 mono 16 kHz 32 kbps | **Borra `temp_audio.*`** previos del CWD; crea `temp_audio.mp3` |
| `construir_prompt_viral` | `(duracion_total) -> str` | Prompt de curaduría (texto íntegro en §4.2) | — |
| `analizar_con_gemini` | `(ruta_audio, duracion_total, modelo_preferido) -> List[dict]` | Upload File API, polling, cascada de modelos en streaming, parseo | **Escribe `clips.json`**; borra el archivo remoto; `sys.exit(1)` si falta API key |
| `descargar_video_fuente` | `(url, destino="temp_source.mp4") -> str` | Descarga completa ≤1080p MP4 | Crea `temp_source.mp4` (lo borra si existía) |
| `obtener_urls_stream` | `(url) -> List[str]` | `yt-dlp -g` (máx 2 URLs: video y audio) | — |
| `procesar_clip_ffmpeg` | `(url_o_archivo, inicio, fin, id_clip) -> str` | Render 9:16 + watermark. Si el argumento existe como archivo → local; si no → `obtener_urls_stream` (remoto) | Crea/sobrescribe `clips_finales/clip_<id>.mp4`; `FileNotFoundError` si falta watermark |
| `renderizar_y_subir_clips` | `(url, clips, duracion_total, subir_youtube=True) -> List[str]` | Orquesta fase 3+4 en CLI | Reescribe `clips.json` (v2); append en `subidas_shorts.json`; borra `temp_source.mp4` |
| `renderizar_clips` | alias | Compatibilidad: `renderizar_y_subir_clips(..., subir_youtube=True)` | — |
| `main` | argparse | CLI: `url`, `--solo-analisis`, `--sin-subida`, `--modelo` | Borra `temp_audio.mp3` en `finally` |

#### `app_interfaz.py` — GUI Gradio (ACTIVO)

| Función | Responsabilidad |
|---|---|
| `CUSTOM_CSS` | Tema oscuro (fondo `#0f0f13`, acento violeta `#8b5cf6`, verde Kick `#53fc18`), clases `.kicksazos-header`, `.status-banner.{ok,warn,err,run}`, `.clip-card`, `.tag-pill` |
| `_banner_html(titulo, detalle, nivel)` | HTML de estado con iconos ✅⚠️❌⚡ (**sin escape HTML** de `detalle`) |
| `_cargar_clips_actuales()` | Lee `clips.json` (lista o `[]`) |
| `_indexar_subidas_por_archivo()` | Dict `archivo → registro` desde `subidas_shorts.json` (el último registro con el mismo nombre gana) |
| `construir_tarjetas_galeria_html(clips)` | Tarjetas con timestamps, hook, gatillo, descripción SEO, tags y link a YouTube. Si `clips` vacío: tarjetas por `.mp4` en `clips_finales/` |
| `obtener_datos_galeria()` | → `(items_galeria[(ruta, leyenda)], primer_video, html_tarjetas, clips)`. Prioriza `clip_<id>.mp4` del último `clips.json`; si no, todos los mp4 por mtime desc |
| `obtener_tabla_historial()` | → `(filas Dataframe, html resumen)` desde `subidas_shorts.json` en orden inverso |
| `ejecutar_pipeline_gradio(url, modelo_preferido, subir_auto_yt, solo_analisis, gemini_key, progress)` | **Generador** que replica el pipeline CLI paso a paso emitiendo 8 outputs por `yield` (ver §4.5) |
| `seleccionar_clip_galeria(evt: gr.SelectData)` | Extrae `path` del item seleccionado para el reproductor |
| `obtener_tema_oscuro()` | `gr.themes.Soft(primary_hue="violet", secondary_hue="emerald", neutral_hue="slate")` + overrides |
| `construir_interfaz()` | Construye `gr.Blocks` con 3 pestañas y conecta eventos |
| `__main__` | `demo.launch(server_name="127.0.0.1", server_port=7860, inbrowser=False, allowed_paths=[clips_finales, assets], theme=..., css=...)` |

> La GUI **no** llama a `renderizar_y_subir_clips`; reimplementa el bucle de render/subida inline para poder emitir progreso. Cualquier cambio en la lógica de orquestación debe replicarse en **ambos** lugares.

#### `subir_shorts.py` — YouTube (ACTIVO)

| Función | Responsabilidad |
|---|---|
| `autenticar_youtube(interactivo=False)` | Carga `token.json` → refresca si expiró y hay `refresh_token` → si no hay token válido: con `interactivo=True` abre `InstalledAppFlow.run_local_server(port=0)`; con `False` lanza `RuntimeError`. Persiste el token y devuelve `build("youtube","v3")` |
| `cargar_historial_subidas(ruta)` | Lee `subidas_shorts.json` → lista (o `[]` ante error) |
| `registrar_subida(registro, ruta)` | Elimina registros con el mismo `youtube_id`, hace append y reescribe el JSON |
| `subir_short(youtube, ruta_video, titulo, descripcion, etiquetas, privacidad="private", clip_id=None, guardar_registro=True)` | Normaliza metadatos, `videos().insert` resumable con `next_chunk()`, devuelve y registra `info_subida` |
| `main()` | Exige `client_secret.json`, autentica **interactivo**, sube el primer `.mp4` (orden alfabético) de `clips_finales/` (o `clips_virales/`) con título/descripción/tags **de prueba** |

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

### 4.1 Ingesta y extracción de audio/video (`yt-dlp`)

Todas las invocaciones activas usan el intérprete del venv: `[sys.executable, "-m", "yt_dlp", ...]` con `subprocess.run(..., check=True)` (stdout/stderr heredados → aparecen en la consola / `gradio.log`).

**Flags comunes:**
- `--js-runtimes node` + `--remote-components ejs:github` → usa Node para resolver los desafíos JS (n-sig/firmas) de YouTube con el componente EJS descargado de GitHub.
- `--no-playlist` → nunca expande listas.
- `--force-overwrites` (solo descargas).

**A) Audio para IA — `extraer_audio(url)`**
```bash
python -m yt_dlp --js-runtimes node --remote-components ejs:github \
  --no-playlist --force-overwrites \
  --concurrent-fragments 4 --retries 5 --fragment-retries 5 \
  -f "ba/b[height<=360]/b/worst" \
  -x --audio-format mp3 \
  --postprocessor-args "ffmpeg:-ac 1 -ar 16000 -b:a 32k" \
  -o "temp_audio.%(ext)s" "<URL>"
```
- Selector: mejor audio-only → si no existe (caso **Kick HLS**, que no ofrece audio separado) mejor muxed ≤360p → mejor → peor.
- Descarga paralela y resiliencia de red: se incorporan `--concurrent-fragments 4`, `--retries 5` y `--fragment-retries 5` para saturar el ancho de banda descargando fragmentos concurrentemente, evitando los valles de inactividad (caídas a 0 B/s entre peticiones HTTP sucesivas) causados por la latencia en entornos remotos.
- Resultado: `temp_audio.mp3` (mono, 16 kHz, 32 kbps ≈ 14 MB/h). Antes se borran todos los `temp_audio.*` del CWD.
- En Kick se descarga primero el contenedor muxed (`temp_audio.mp4`, por fragmentos HLS → aparecen `temp_audio.mp4.part` / `.ytdl`) y luego FFmpegExtractAudio lo convierte. Para VODs de 2 h esto son ~600 MB (observado en `gradio.log`: 613 fragmentos, ~625 MiB).

**B) Video fuente completo — `descargar_video_fuente(url)`** (solo si `duracion_total ≤ 3600 s` o desconocida)
```bash
python -m yt_dlp --js-runtimes node --remote-components ejs:github \
  --no-playlist --force-overwrites \
  -f "bestvideo[height<=1080][protocol!=m3u8_native][ext=mp4]+bestaudio[protocol!=m3u8_native][ext=m4a]/bestvideo[height<=1080][ext=mp4]+bestaudio[ext=m4a]/best[height<=1080][ext=mp4]/best[height<=1080]/best" \
  --merge-output-format mp4 \
  -o "<abs>/temp_source.mp4" "<URL>"
```
- `FORMATOS_VIDEO_RAPIDOS` prioriza DASH/HTTPS directo (evita HLS `m3u8_native`, más lento) y cae a HLS/muxed si no hay alternativa.
- Si falla → aviso y se usa seek remoto.

**C) URLs directas para seek remoto — `obtener_urls_stream(url)`** (VOD > 1 h o descarga fallida)
```bash
python -m yt_dlp --js-runtimes node --remote-components ejs:github \
  --no-playlist -f "<FORMATOS_VIDEO_RAPIDOS>" -g "<URL>"
```
- Devuelve 1 URL (muxed, p. ej. manifest HLS de Kick en CloudFront) o 2 URLs (video + audio separados). Se toman `urls[:2]`.
- ⚠️ Se llama **una vez por clip** (no se cachea) → N invocaciones de yt-dlp por run remoto.

**Manejo de secciones:** no se usa `--download-sections`; el corte se hace en FFmpeg con *input seek* (`-ss`/`-to` antes de `-i`), tanto local como remoto (FFmpeg solo pide los segmentos HLS/rangos HTTP necesarios).

### 4.2 Motor de curaduría con IA (Gemini)

#### 4.2.1 Flujo de `analizar_con_gemini`
1. `api_key = os.environ["GEMINI_API_KEY"]` → si falta: `print` + `sys.exit(1)` (⚠️ `SystemExit` no es capturado por `except Exception` en la GUI; la GUI valida la key antes para evitarlo).
2. `client = genai.Client(api_key=..., http_options={"timeout": 600_000})`.
3. **Upload** `client.files.upload(file=ruta_audio)` con hasta **4 intentos**, espera `3·n` s (3, 6, 9).
4. **Polling**: mientras `state != "ACTIVE"`: si `FAILED` → `RuntimeError`; `sleep(4)` + `files.get`; máx **150 iteraciones (~600 s)** → `TimeoutError`. Errores transitorios de `files.get` se registran y se reintenta.
5. **Prompt**: `construir_prompt_viral(duracion_total)`.
6. **Cascada de modelos**: `orden = [modelo_preferido] + MODELOS_CANDIDATOS sin duplicado`.
7. Por modelo, **2 intentos** con `client.models.generate_content_stream(model, contents=[archivo_subido, prompt], config=GenerateContentConfig(response_mime_type="application/json", response_schema=list[ClipViral], temperature=0.35))`; concatena `chunk.text`.
8. Parseo con `_limpiar_y_parsear_json`; se añade `modelo_ia` a cada clip; se escribe `clips.json`.
9. `finally`: `client.files.delete(name=...)` (errores silenciados).

#### 4.2.2 Matriz de manejo de errores (por intento)

| Excepción | Condición | Acción |
|---|---|---|
| `ServerError` (5xx, p. ej. 503 overloaded) | — | Log "Servidor ocupado (503)", `sleep(5)`, siguiente intento (tras 2 → siguiente modelo) |
| `APIError` | `code in (400, 404)` | Modelo no disponible/inválido → **salta al siguiente modelo inmediatamente** |
| `APIError` | `code in (429, 503)` | Cuota/saturación → `sleep(5)`, reintenta |
| `APIError` | otro código | Log y **salta al siguiente modelo** |
| `Exception` genérica | stream vacío, JSON inválido, validación temporal sin clips, red | `sleep(2)`, reintenta |
| Todos los modelos agotados | `clips` vacío | `RuntimeError("No se pudo obtener una respuesta JSON válida de los modelos disponibles.")` |

> No hay *exponential backoff con jitter* (a pesar de lo que dice el doc previo): las esperas son fijas (5 s / 2 s). Peor caso ≈ 6 modelos × 2 intentos × (latencia + 5 s).

#### 4.2.3 Prompt de producción (íntegro, `construir_prompt_viral`)

```text
Actúa como un Senior Growth Hacker, estratega de retención de algoritmo de YouTube Shorts / TikTok y editor experto en el ecosistema de IRL y streaming de Latinoamérica (específicamente Colombia).

Tu misión es analizar el audio adjunto y detectar los segmentos con mayor potencial de viralidad explosiva y retención (watch time > 100%).
[Si hay duración:] DURACIÓN TOTAL DEL AUDIO: HH:MM:SS (jamás generes timestamps superiores a este límite).

### 1. MENTALIDAD DE INFERENCIA Y ALGORITMO DE SHORTS:
- **Hook Explosivo (Primeros 2 segundos):** El clip DEBE abrir de golpe en medio de una frase picante, confesión, grito, cifra escandalosa, pregunta incisiva o momento de alta tensión. Cero introducciones lentas ni saludos.
- **Ritmo Dinámico:** Evita segmentos con silencios muertos o divagaciones sin rumbo.
- **Arco Narrativo Completo:** Todo clip debe tener apertura fuerte (hook), desarrollo rápido, clímax narrativo y una resolución o remate contundente (punchline/reacción final).

### 2. CONTEXTO CULTURAL Y ECOSISTEMA STREAMING COLOMBIANO:
Presta máxima atención y prioriza cualquier mención directa, indirecta, tiradera o anécdota sobre:
- **Personalidades y Streamers:** WestCOL, Blessd (El Bendito), JH de la Cruz, MrStiven (Stiven Tangarife), Daiky Gamboa, La Liendra, Kris R, Ryan Castro, Pelicanger, Barbossa, Cossio, Aida Victoria, streamers de Kick/Twitch Colombia y escena urbana de Medellín, Cali y Bogotá.
- **Gatillos Virales de Alta Retención:**
  * Cifras de dinero, apuestas, deudas, compras o gastos extravagantes.
  * Discusiones en vivo, tiraderas, reclamos, filtraciones o peleas.
  * Confesiones íntimas, anécdotas callejeras, momentos incómodos en IRL o revelaciones personales.
  * Humor negro contextual, jerga colombiana auténtica (gonorrea, nea, parce, visaje, etc.) y opiniones controversiales sobre figuras públicas o eventos.

### 3. DURACIÓN DINÁMICA E INTELIGENTE (SIN CORTES RÍGIDOS):
- NO apliques una restricción rígida de corte fijo (nunca cortes a los 30s exactos si la historia sigue).
- La duración debe adaptarse de forma natural e inteligente a la unidad narrativa completa (típicamente entre **25 y 75 segundos**; o proporcional si el video fuente completo es un clip corto).
- Asegúrate de que el timestamp `inicio` abra exactamente en el gancho y el timestamp `fin` cierre después del remate, sin dejar palabras ni ideas cortadas a la mitad.

### 4. METADATOS SEO OBLIGATORIOS POR CADA CLIP:
Por cada clip seleccionado (extrae entre 3 y 6 de los mejores momentos, o los mejores disponibles según la longitud del audio), devuelve en el JSON:
- `id`, `titulo` (máx 60 caracteres, mayúsculas estratégicas/emojis), `inicio`/`fin` (HH:MM:SS), `gancho` (transcripción textual),
  `razon_viral`, `descripcion` (2 líneas + CTA de suscripción a Kicksazos + 3–5 hashtags), `etiquetas` (8–12 tags SEO).

Devuelve EXCLUSIVAMENTE un arreglo JSON válido con esta estructura exacta: [ { "id": 1, "titulo": ..., "inicio": "HH:MM:SS", ... } ]
```
*(La sección 4 está resumida aquí; el texto literal completo está en [pipeline_viral_clips.py L283-L338](file:///home/bastiboy/clips_automation/pipeline_viral_clips.py#L283-L338).)*

> Nota: los clips de YouTube Shorts admiten hasta 3 min, pero el prompt sugiere 25–75 s. Las restricciones (máx 60 chars, 8–12 tags, 3–6 clips) **no** se imponen vía JSON Schema; se corrigen en post-proceso.

#### 4.2.4 Parsing y validación — `_limpiar_y_parsear_json(texto, duracion_total)`
1. Quita los fences markdown iniciales/finales (triple backtick con o sin `json`) mediante regex.
2. Intenta `TypeAdapter(List[ClipViral]).validate_json(texto)`.
3. Si falla: regex `\[.*\]` (DOTALL) → `validate_json(bloque)` → si falla, `json.loads(bloque)` (sin validación de tipos). Sin coincidencia: `json.loads(texto)`.
4. Si es `dict` → toma `datos["clips"]`.
5. Por cada item:
   - Convierte `inicio`/`fin` a segundos (si falla → descarta).
   - Si `ini ≥ duracion_total − 2` → descarta; `fin = min(fin, duracion_total)`.
   - Si `fin − ini < 5 s` → descarta.
   - `titulo` > 60 chars → recorta a 57 + `"..."`; vacío → `"Clip Viral #n"`.
   - `descripcion` vacía → plantilla `"{gancho|titulo}\n¡Suscríbete a Kicksazos ...! #Shorts #Kicksazos #StreamColombia #KickColombia"`; si no contiene `#shorts` → añade `"\n#Shorts #Kicksazos #StreamColombia"`.
   - `etiquetas` → `_normalizar_etiquetas` (defaults: `Shorts, Kicksazos, StreamColombia, KickColombia, ClipsVirales, IRLColombia, StreamersColombianos, PolémicaStream, WestCOL, YouTubeShorts`).
   - **Re-numera `id` secuencialmente** (1..N tras descartes) y añade `duracion_segundos`.
6. Lista vacía → `ValueError`.

### 4.3 Pipeline de renderizado FFmpeg (9:16)

#### 4.3.1 Comando completo (`procesar_clip_ffmpeg`)

Entrada **local** (`temp_source.mp4`):
```bash
ffmpeg -hide_banner -stats -y \
  -ss <INICIO> -to <FIN> -i <temp_source.mp4> \
  -i <abs>/assets/watermark.png \
  -filter_complex "<FILTRO>" \
  -map "[outv]" -map "0:a?" \
  -c:v libx264 -preset veryfast -crf 22 -threads 0 \
  -c:a aac -b:a 128k -movflags +faststart \
  <abs>/clips_finales/clip_<ID>.mp4
```
Entrada **remota** (por cada URL devuelta por `yt-dlp -g`, se antepone):
```bash
-rw_timeout 15000000 -reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5 -ss <INICIO> -to <FIN> -i <URL_n>
```
- Con 2 URLs (video+audio separados): video = input 0, audio = `-map 1:a?`, watermark = input 2.
- Con 1 URL o archivo local: audio = `-map 0:a?`, watermark = input 1.
- `-ss`/`-to` **como opciones de entrada** → *fast seek* (salta al keyframe sin decodificar desde 0; `-to` relativo a la posición absoluta del input). Precisión de corte: ±1 GOP en algunos contenedores.

#### 4.3.2 `filter_complex` (desglose)
```
[0:v]split=2[bg][fg];
[bg]scale=360:640:force_original_aspect_ratio=increase,crop=360:640,setsar=1,boxblur=10:2,scale=1080:1920:flags=bilinear[bg_blur];
[fg]scale=1080:1920:force_original_aspect_ratio=decrease,setsar=1[fg_scaled];
[bg_blur][fg_scaled]overlay=(W-w)/2:(H-h)/2[vid_comp];
[<idx_wm>:v]scale=420:-1,format=rgba,colorchannelmixer=aa=0.92[wm];
[vid_comp][wm]overlay=(W-w)/2:520,format=yuv420p[outv]
```

| Etapa | Qué hace | Por qué |
|---|---|---|
| `split=2` | Duplica el video en capa fondo `bg` y capa frente `fg` | Una sola decodificación |
| Fondo `scale 360:640 increase` + `crop 360:640` | Rellena un lienzo 9:16 pequeño recortando laterales | Blur a 360p es ~9× más barato que a 1080p |
| `boxblur=10:2` | Radio 10, 2 pasadas (≈ gaussiano) | Desenfoque del fondo |
| `scale=1080:1920:flags=bilinear` | Sube el fondo borroso a 1080×1920 | Upscale barato (el blur oculta artefactos) |
| Frente `scale=1080:1920 decrease` | Encaja 16:9 sin recorte → 1080×608 para fuente 1920×1080 | Contenido íntegro, centrado |
| `overlay=(W-w)/2:(H-h)/2` | Centra el frente (y≈656–1264) | Layout clásico "blur bars" |
| Watermark `scale=420:-1`, `format=rgba`, `colorchannelmixer=aa=0.92` | 420 px de ancho, alfa al 92 % | Marca @Kicksazos semitransparente |
| `overlay=(W-w)/2:520` | Centrada horizontalmente, **y=520 fijo** | Con `watermark.png` 946×262 → 420×116 → ocupa y≈520–636, justo **encima** del video central (fuentes 16:9) |
| `format=yuv420p` | Compatibilidad universal (YouTube/móviles) | — |

- Codificación: `libx264 veryfast CRF 22`, AAC 128 kbps, `+faststart` (moov al inicio). FPS heredado de la fuente (Kick 1080p60 → clips de 60 fps; ~2.0–4.4 Mbps observados).
- La imagen PNG es una entrada de 1 frame; `overlay` repite el último frame (`eof_action=repeat` por defecto), por lo que no hace falta `-loop 1`.
- Rendimiento observado en `gradio.log` (HLS remoto Kick 1080p60): **0.8×–1.2× tiempo real**.
- Si la fuente ya es vertical, el frente ocupa todo el lienzo y el watermark queda encima del contenido.

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
| **🚀 1. Extractor & Pipeline** | `estado_banner` (HTML) · `url_input` (Textbox) · `modelo_dropdown` (choices=`MODELOS_CANDIDATOS`, default `gemini-3.8-flash`) · `subir_yt_chk` (Checkbox, default **True**) · `solo_analisis_chk` (default False) · `api_key_input` (password, opcional) · `btn_ejecutar` (primary, lg) · `salida_logs` (Textbox 14–20 líneas, read-only) · `video_preview` (Video, h=420) · Accordion → `clips_json_view` (JSON) |
| **🎬 2. Galería de Clips (9:16)** | `btn_refrescar_galeria` · `galeria_videos` (Gallery, 3 columnas, h=520, contain) · `reproductor_galeria` (Video, h=520) · `tarjetas_galeria_html` (HTML) |
| **📈 3. Historial de Subidas** | `btn_refrescar_historial` · `resumen_historial_html` · `tabla_historial` (Dataframe: Fecha Subida, Archivo Local, Título SEO, ID YouTube, URL Directa Short, Privacidad, Tags Clave[≤6]) |

**Eventos:**

| Disparador | Función | Inputs | Outputs |
|---|---|---|---|
| `btn_ejecutar.click` | `ejecutar_pipeline_gradio` (generador) | url, modelo, subir_yt, solo_analisis, api_key | `estado_banner, salida_logs, video_preview, clips_json_view, galeria_videos, tarjetas_galeria_html, tabla_historial, resumen_historial_html` (8) |
| `galeria_videos.select` | `seleccionar_clip_galeria` | `gr.SelectData` | `reproductor_galeria` |
| `btn_refrescar_galeria.click` | `obtener_datos_galeria` | — | `galeria_videos, reproductor_galeria, tarjetas_galeria_html, clips_json_view` |
| `btn_refrescar_historial.click` | `obtener_tabla_historial` | — | `tabla_historial, resumen_historial_html` |

**Máquina de estados de `ejecutar_pipeline_gradio`** (barra `gr.Progress`):

| Progreso | Fase | Acción |
|---|---|---|
| — | Validación | URL vacía → banner err; key del campo → `os.environ`; sin key → banner err |
| 0.08 | 1/4 Audio | `extraer_audio` + `obtener_duracion_media` |
| 0.30 | 2/4 Gemini | `analizar_con_gemini(..., modelo_preferido)` → log de cada clip. Si `solo_analisis` → 1.0 y fin |
| 0.55 | 3/4 Fuente | `descargar_video_fuente` si ≤3600 s; si no, seek remoto |
| — | Auth YT | `autenticar_youtube(False)` si `subir_auto_yt` |
| 0.60→0.95 | 3/4 Render + 4/4 Upload por clip | `procesar_clip_ffmpeg` → `subir_short` (privado) → actualiza `youtube_status` (`"Subido (Privado)"`, `"Error subida (...)"`, `"Subida desactivada por usuario"`, `"Local (Sin token activo)"`) |
| 1.0 | Fin | Reescribe `clips.json`, refresca galería/historial, banner con nº renderizados/subidos |
| — | `except Exception` | Banner err con `str(e)`; refresca galería/historial |
| — | `finally` | Borra `temp_audio.mp3` y `temp_source.mp4` |

**Estado:** la GUI no usa `gr.State`; todo el estado vive en disco (`clips.json`, `subidas_shorts.json`, `clips_finales/`). Los logs se acumulan en una lista local por ejecución (y se imprimen en stdout).

---

## 5. Contratos de Datos y Esquemas JSON

### 5.1 `clips.json` (sincronizado entre `jobs/<job_id>/clips.json` y la raíz del proyecto)

Ciclo de vida: **v1** escrito por `analizar_con_gemini` (en `job_dir` y sincronizado en raíz) → **v2** reescrito tras render/subida (CLI y GUI). Cada ejecución mantiene su versión histórica inmutable dentro de `jobs/<job_id>/clips.json`, mientras que `BASE_DIR / "clips.json"` actúa como puntero al último estado generado.

**Esquema (v2):**
```jsonc
[
  {
    "id": 1,                              // int, secuencial 1..N (re-numerado tras validación)
    "titulo": "string ≤60",               // recortado a 57+"..." si excede
    "inicio": "HH:MM:SS",                 // normalizado
    "fin": "HH:MM:SS",                    // ≤ duracion_total
    "gancho": "string",
    "razon_viral": "string",
    "descripcion": "string con \\n y #Shorts",
    "etiquetas": ["8..12 strings sin #"],
    "duracion_segundos": 51,              // int (fin-inicio)
    "modelo_ia": "gemini-3.8-flash",      // modelo que respondió con éxito
    // --- añadidos en fase render/subida (v2) ---
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
    "categoryId": "24",
    "madeForKids": false,
    "fecha_subida": "2026-11-11T00:20:13"   // ISO local, sin zona horaria
  }
]
```
**Contenido actual (7 registros):**

| # | clip_id | archivo | youtube_id | fecha_subida | Observación |
|---|---|---|---|---|---|
| 1 | 1 | clip_1.mp4 | LQIcG8bjKNQ | 2026-11-11T00:20:13 | Run previo (cuenta anterior) |
| 2 | 1 | clip_1.mp4 | omzV0U7F9RQ | 2026-11-11T00:44:20 | Run actual de `clips.json` (cuenta anterior) |
| 3–6 | 2–5 | clip_2..5.mp4 | W-ybt9xaGvU, KZB9ToKaeaU, -Hd7i3Y4IUg, H-fGRr_ySXo | 00:45–00:48 | Cuenta anterior |
| 7 | null | clip_1.mp4 | FJnV_odrhC4 | 2026-11-11T20:49:06 | **Prueba de la cuenta NUEVA** vía `subir_shorts.py` (título "¡Momento Épico en Vivo! 😂 #Shorts") |

> ⚠️ El registro no guarda la cuenta/canal; tras el cambio OAuth, los IDs 1–6 pertenecen al canal anterior y el 7 al nuevo.

### 5.3 `clips_virales/reporte_clips.json` (LEGACY)
```json
[{"id": 1, "titulo": "Casi nos chocamos en la calle", "inicio": "00:12:48", "fin": "00:13:08",
  "gancho": "No, pues es que bro, ¿cómo", "razon_viral": "Un momento de peligro inminente ..."}]
```
7 clips, sin campos SEO. Consumido solo por `subir_lote.py`.

### 5.4 Archivos temporales y de proceso

| Archivo | Creado por | Eliminado por | Notas |
|---|---|---|---|
| `temp_audio.mp3` | `extraer_audio` | `main()` / GUI `finally` | Nombre fijo en CWD |
| `temp_audio.*` (`.mp4`, `.part`, `.ytdl`, `.webm`) | yt-dlp (intermedios) | Siguiente `extraer_audio` (glob) | Quedan huérfanos si el proceso muere |
| `temp_source.mp4` | `descargar_video_fuente` | `renderizar_y_subir_clips` / GUI `finally` | Solo VOD ≤1 h |
| Archivo remoto Gemini `files/<id>` | `client.files.upload` | `client.files.delete` en `finally` | Expira solo a las ~48 h si no se borra |
| `clips_finales/clip_<id>.mp4` | `procesar_clip_ffmpeg` | **Nunca** (se sobrescribe por id) | Clips de runs anteriores con id > N persisten (p. ej. `clip_6.mp4`) |

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
| 11 ~20:28→ | GUI en ejecución (PID 15943) con un nuevo run en fase 1 (descarga de audio) | `ps`, `temp_audio.mp4.part` |

### 6.2 Decisiones arquitectónicas (v1 → v2)

| Tema | v1 (`.bak`) | v2 (actual) | Motivo |
|---|---|---|---|
| Invocación yt-dlp | Binario `yt-dlp` + `--user-agent` Chrome | `sys.executable -m yt_dlp` + `--js-runtimes node --remote-components ejs:github` | Garantizar versión del venv; soporte de desafíos JS de YouTube |
| Fuente de render | Siempre URL HLS remota (`-f best -g`) | Descarga local si ≤1 h; remoto con flags `-reconnect*` si no | Muchas conexiones HLS por clip eran lentas/inestables |
| Formatos | `best` | `FORMATOS_VIDEO_RAPIDOS` (≤1080p, evita `m3u8_native`) | Velocidad de descarga/seek |
| Llamada Gemini | `generate_content` (bloqueante) | `generate_content_stream` + timeout 600 s | Evitar timeouts en respuestas largas con audios de horas |
| Schema | `ColeccionClips {clips: [...]}` | `list[ClipViral]` directo + parser tolerante (3 niveles) | Respuestas más simples y robustas |
| Reintentos | 5 intentos/modelo, backoff lineal 10 s·n | 2 intentos/modelo, espera fija 5 s, salto inmediato en 400/404 | Fallar rápido y rotar de modelo (cuotas por modelo) |
| Modelos | 3.8-flash → 3.5-flash → 3.1-flash-lite | 6 modelos (3.8-flash, 3.5-flash-lite, 3.1-pro-preview, 3.7-flash, 2.5-flash, 2.5-pro) + preferido elegible | IDs inexistentes daban 404; resiliencia ante 503/429 |
| Duración clips | 15–45 s estricta | 25–75 s dinámica por arco narrativo | Clips cortados a mitad de idea |
| Metadatos | titulo ≤6 palabras, gancho, razón | + descripción con CTA, 8–12 etiquetas, título ≤60 chars | Habilitar upload automático con SEO |
| Validación temporal | Ninguna | Clamp a duración real, mín 5 s, descarte fuera de rango | Gemini alucinaba timestamps > duración |
| Filtro 9:16 | Blur `boxblur=20:5` a 1080×1920 | Blur a 360×640 `boxblur=10:2` + upscale bilinear; watermark | ~Rendimiento; branding |
| Salida | `clips_virales/clip_NN_<slug>.mp4` | `clips_finales/clip_<id>.mp4` | Cruce determinista con `clips.json`/historial |
| Upload | Script separado (`subir_lote.py`) | Integrado por clip, nunca bloquea el render si falla auth/upload | E2E autónomo |

### 6.3 Problemas resueltos

1. **Errores 503/404/429 de Gemini** → cascada de modelos + matriz de errores (§4.2.2). 400/404 = modelo inexistente para la key → salto inmediato.
2. **JSON malformado / envuelto en markdown** → `response_schema` + limpieza de fences + regex `\[.*\]` + pydantic.
3. **Timestamps fuera de rango** → `duracion_total` inyectada en el prompt + clamp en post-proceso.
4. **Archivo de audio no listo** (`PROCESSING`) → polling hasta `ACTIVE` con timeout.
5. **Audio pesado** → mono 16 kHz 32 kbps (≈14 MB/h) para upload rápido y bajo costo de tokens.
6. **Eliminación de subtítulos / PyAV / Whisper**: se exploró transcripción con Whisper (`openai-whisper`, `faster-whisper`) y decodificación con PyAV (`av`); se abandonaron (crashes/incompatibilidades de bindings PyAV ↔ FFmpeg del sistema, y la transcripción ya no es necesaria porque Gemini analiza el audio directamente). Hoy **todo** el procesamiento multimedia es vía `subprocess` a los binarios `ffmpeg`/`ffprobe`/`yt-dlp`. Los paquetes siguen instalados en el venv pero **no se importan** (candidatos a desinstalar).
7. **Token OAuth en modo no interactivo** → el pipeline nunca abre navegador; si falla la auth, renderiza localmente y marca el estado.
8. **Cambio de cuenta OAuth** (11-nov 20:47) → respaldo del token anterior y re-autorización interactiva con `subir_shorts.py`; `client_secret.json` (proyecto `kick-clips-auto-514009`) se mantuvo.
9. **Cuello de botella en descarga secuencial HLS** → mitigado implementando concurrencia de fragmentos (`--concurrent-fragments 4`) y tolerancia a fallos (`--retries 5`, `--fragment-retries 5`) en yt-dlp para la extracción de audio, estabilizando la fluctuación de red y eliminando los valles de inactividad a 0 B/s.

### 6.4 Discrepancias del doc previo (`Contexto y Objetivos del Proyecto Kicksazos.md`) vs. código real

| Afirmación del doc previo | Realidad en el código |
|---|---|
| "Exponential backoff con jitter" | Esperas fijas (5 s / 2 s); backoff lineal solo en el upload a File API (3 s·n) |
| "Máscara de recorte previa para subtítulos incrustados" | No existe ningún filtro de máscara/crop de subtítulos |
| "PyAV sustituido por subprocess con pipes asíncronos" | `subprocess.run` síncrono, sin pipes |
| GUI: selector de nº de clips, tabla editable de timestamps, controles de blur/watermark/aspect, botón de descarga | No existen; la GUI tiene URL, modelo, 2 checkboxes, API key, logs, preview, galería e historial |
| Clips de 30–60 s | Prompt pide 25–75 s |
| Python 3.10+, Ubuntu 22.04/Debian/WSL2, FFmpeg 5+ | Kubuntu, Python 3.14.4, FFmpeg 8.0.1 |
| Subida a YouTube como "objetivo futuro" | **Ya implementada** (privado) |
| Metadatos SEO por IA como "futuro" | **Ya implementados** |

---

## 7. Estado Actual, Limitaciones Conocidas y Roadmap

### 7.1 Qué funciona (verificado con artefactos)

- ✅ Control de versiones activo con Git y `.gitignore` estricto (credenciales, artefactos multimedia, temporales y caché).
- ✅ Entorno limpio con `requirements.txt` explícito y dependencias residuales desinstaladas (`openai-whisper`, `faster-whisper`, `av`).
- ✅ Rutas absolutas ancladas a `BASE_DIR = Path(__file__).resolve().parent` en todos los módulos activos (`pipeline_viral_clips.py`, `subir_shorts.py`, `app_interfaz.py`, `procesar_video_universal.py`).
- ✅ Aislamiento por jobs (`jobs/<job_id>/`) con temporales locales (`temp_audio.mp3`, `temp_source.mp4`, `clips.json`) y prefijo único en renders (`<job_id>_clip_<id>.mp4`).
- ✅ Código y artefactos obsoletos archivados en `legacy/`.
- ✅ Extracción de audio desde Kick VOD (HLS) y YouTube.
- ✅ Análisis con `gemini-3.8-flash` → 5 clips válidos con SEO.
- ✅ Render 9:16 1080×1920 H.264/AAC con blur + watermark.
- ✅ Seek remoto en VOD de >1 h (2 h 06 min) a ~0.8–1.2× tiempo real.
- ✅ Subida privada a YouTube Shorts (6 en cuenta anterior + 1 prueba en cuenta nueva) con registro en `subidas_shorts.json`.
- ✅ GUI Gradio operativa con soporte para jobs, resolución dinámica de `archivo_local` y galería sincronizada.

### 7.2 Limitaciones y puntos frágiles

**Concurrencia / estado global**
1. [RESUELTO - FASE 1] Aislamiento de ejecuciones mediante `crear_contexto_job(url)`: cada job tiene su directorio en `jobs/<job_id>` con sus propios temporales y `clips.json`.
2. [RESUELTO - FASE 1] Rutas relativas al CWD eliminadas: todos los scripts resuelven rutas respecto a `BASE_DIR`.
3. [RESUELTO - FASE 1] Sobrescritura de clips: renders nombrados como `<job_id>_clip_<id>.mp4` en `clips_finales/`.
4. `GEMINI_API_KEY` ingresada en la GUI muta `os.environ` de forma persistente para el proceso.

**Robustez**
5. Si **un** render FFmpeg falla (`CalledProcessError`), se aborta el bucle completo y `clips.json` v2 **no** se escribe (las subidas ya hechas sí quedan en `subidas_shorts.json`).
6. Sin límite de cuota YouTube en el pipeline activo (~6 uploads/día por proyecto). Sin reintentos en `next_chunk()`.
7. `obtener_urls_stream` se invoca por clip (URLs firmadas pueden expirar entre clips, pero también es overhead redundante).
8. Para VODs largos de Kick, la extracción de audio descarga el stream muxed ≤360p completo. Con `--concurrent-fragments 4` el flujo es más rápido y ahora queda encapsulado en su `job_dir`.
9. `hhmmss_a_segundos` ignora fracciones; *input seek* puede desfasar ±1 GOP.
10. Watermark en `y=520` fijo: correcto para fuentes 16:9; tapa contenido en fuentes verticales/4:3.
11. `analizar_con_gemini` usa `sys.exit(1)` (no apto para uso como librería).
12. `_banner_html` interpola `str(e)` y metadatos sin escape HTML (riesgo menor de XSS local).
13. Los IDs de modelo de `MODELOS_CANDIDATOS` deben mantenerse al día.
14. La GUI duplica la lógica de orquestación de `renderizar_y_subir_clips` (candidato a unificación en Fase 2).
15. El refresh token puede caducar (7 días si la app OAuth está en modo Testing).

**Higiene del repo**
16. [RESUELTO - FASE 1] Git inicializado con `.gitignore` exhaustivo y `requirements.txt`.
17. [RESUELTO - FASE 1] Paquetes residuales pesados desinstalados del venv (`openai-whisper`, `faster-whisper`, `av`).
18. [RESUELTO - FASE 1] Scripts legacy archivados de forma segura en `legacy/`.

### 7.3 Roadmap de Siguientes Fases

| Prioridad | Fase / Tarea | Detalle |
|---|---|---|
| ✅ Hecho | **Fase 1: Higiene, Seguridad, Rutas y Jobs** | Git, `.gitignore`, `requirements.txt`, `BASE_DIR`, `crear_contexto_job()`, `legacy/` |
| P1 | **Fase 2: Unificación de orquestación** | GUI y CLI llaman a un único motor/generador con callbacks de progreso |
| P1 | **Fase 2: Tolerancia a fallos por clip** | `try/except` por render individual; persistencia incremental de `clips.json` |
| P1 | **Fase 2: Gestor de cuota YouTube** | Contador diario en `subidas_shorts.json`; cola de pendientes; reintentos con backoff |
| P2 | **Fase 3: Optimización de stream Kick** | Extracción directa de audio HLS con ffmpeg sin bajar video muxed intermedio |
| P2 | **Fase 3: Watermark adaptativo** | Ajuste dinámico de escala y coordenada `y` según aspecto de la fuente |
| P3 | **Fase 4: Subtítulos dinámicos** | Transcripción de palabras con Gemini → ASS → render FFmpeg |
| P3 | **Fase 4: Tests unitarios** | Cobertura para parsing JSON, validaciones de tiempo y contratos de jobs |

---

## 8. Apéndice: Referencia Rápida para Agentes

```bash
cd ~/clips_automation && source venv/bin/activate

# Pipeline completo (análisis + render + subida privada)
python pipeline_viral_clips.py "https://kick.com/<canal>/videos/<uuid>"
python pipeline_viral_clips.py "<URL>" --solo-analisis            # solo clips.json
python pipeline_viral_clips.py "<URL>" --sin-subida --modelo gemini-2.5-pro

# GUI
python app_interfaz.py            # http://127.0.0.1:7860

# Re-render de un clip puntual (usa assets/watermark.png → clips_finales/clip_<ID>.mp4)
python procesar_video_universal.py "<URL|archivo.mp4>" 00:11:43 00:12:34 1

# (Re)autorizar YouTube / cambiar de cuenta  ⚠ sube un video de prueba privado
mv token.json token_backup.json && python subir_shorts.py
```

**Reglas para agentes que modifiquen el sistema:**
- No exponer ni imprimir `.env`, `client_secret.json`, `token*.json`.
- Ejecutar siempre desde `~/clips_automation` (rutas relativas al CWD).
- No lanzar un run CLI mientras la GUI está procesando (colisión de temporales).
- Cambios en la orquestación → aplicarlos en `pipeline_viral_clips.renderizar_y_subir_clips` **y** en `app_interfaz.ejecutar_pipeline_gradio`.
- Cambios en `ClipViral` → revisar `_limpiar_y_parsear_json`, `construir_prompt_viral`, `construir_tarjetas_galeria_html`, `obtener_datos_galeria` y `subir_short`.
- Respetar la cuota de YouTube (~6 subidas/día/proyecto).
