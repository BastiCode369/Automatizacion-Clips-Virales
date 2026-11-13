# DOSSIER TÉCNICO MAESTRO: PIPELINE AUTÓNOMO KICKSAZOS
**Versión de Arquitectura:** v3.2 (Tipografía Embebida de Alta Precisión & Telemetría Gráfica en Vivo)  
**Destino:** Fuente de Conocimiento Experto para NotebookLM / Auditoría Técnica de Alto Nivel  
**Repositorio Base:** `/home/bastiboy/clips_automation`  
**Entorno Operativo:** Kubuntu Linux 64-bit | Kernel Linux 7.0 | Aceleración por Hardware VAAPI (`/dev/dri/renderD128`)

---

## 1. Resumen Ejecutivo, Entorno y Stack Tecnológico

### 1.1 Resumen Ejecutivo
El **Pipeline Autónomo Kicksazos** es una plataforma end-to-end de automatización audiovisual e inteligencia artificial diseñada para monitorizar transmisiones en directo o grabaciones (VODs) de plataformas como Kick, Twitch y YouTube, detectar momentos con alto potencial viral, extraerlos en alta resolución sin descargar archivos pesados completos, formatearlos verticalmente (9:16) con desenfoque de fondo y marca de agua corporativa, generar subtítulos dinámicos de lectura rápida estilizados (`.ass`) con **tipografía local ExtraBold embebida (`Montserrat-ExtraBold.ttf` vía `:fontsdir=`)**, mayúsculas automáticas y animación pop-in, monitorear cada etapa mediante **telemetría estructurada en vivo** (velocidad MB/s, `%`, ETA, bloque IA, FPS/multiplicador `x` y encoder activo en Gradio HTML/CSS y CLI), y publicarlos o programarlos de manera autónoma en YouTube Shorts con metadatos SEO enriquecidos para YouTube y TikTok.

### 1.2 Entorno de Ejecución y Hardware
- **Sistema Operativo:** Kubuntu Linux (Ubuntu base con entorno KDE Plasma / Wayland).
- **Aceleración por Hardware:** GPU integrada AMD Radeon 610M (`radeonsi`, driver Mesa Gallium 26.0.8, DRM 3.64). Dispositivo VAAPI en `/dev/dri/renderD128`.
- **Intérprete de Python:** `Python 3.14.4` (entorno virtual activo en `~/clips_automation/venv`).
- **Motor Multimedia (FFmpeg):** `ffmpeg version 8.0.1-3ubuntu2` (soporte habilitado para decodificación/codificación VAAPI vía `h264_vaapi`, filtro `subtitles` con `fontsdir=` mediante `libass`, `boxblur`, `scale`, `overlay`, `setsar`, telemetría `-progress pipe:1`).
- **Extractor de Streams (yt-dlp):** `yt-dlp 2026.08.19` (con soporte para JavaScript runtimes vía Node.js, componentes remotos EJS y `--newline --progress` para streaming de telemetría).
- **Motor de Descarga Acelerada:** `aria2c` multi-hilo (16 conexiones simultáneas activadas selectivamente).

### 1.3 Contenido Literal de `requirements.txt`
```text
google-genai>=3.0.0
pydantic>=2.14
gradio>=6.31
google-api-python-client>=2.201
google-auth>=2.62
google-auth-oauthlib>=1.5
python-dotenv>=1.2
yt-dlp>=2026.10.26
```

### 1.4 Árbol de Directorios Actualizado
```text
/home/bastiboy/clips_automation/
├── .env                              # [PROTEGIDO - ZERO-SECRETS] Variables de entorno (GEMINI_API_KEY, etc.)
├── .gitignore                         # Exclusiones de Git (tokens, multimedia pesada, venv)
├── CEREBRO_COMPLETO_KICKSAZOS.md      # Dossier técnico maestro completo (actualizado v3.2)
├── CONTEXTO_PROYECTO_KICKSAZOS.md     # Base de conocimiento operativa del repositorio (v3.2)
├── app_interfaz.py                    # Interfaz web interactiva Gradio 6.x con panel de telemetría animado
├── assets/                            # Recursos estáticos del pipeline
│   ├── fonts/                         # Tipografía local embebida para libass (fontsdir=)
│   │   └── Montserrat-ExtraBold.ttf   # Fuente TrueType estática ExtraBold verificada con fc-scan
│   ├── watermark.png                  # Logotipo oficial Kicksazos para composición en video
│   └── Gemini_Generated_Image_...jpeg # Imagen conceptual / branding
├── client_secret.json                 # [PROTEGIDO - ZERO-SECRETS] Credenciales OAuth 2.0 Google Cloud
├── clips.json                         # Catálogo de clips virales del último stream analizado
├── clips_finales/                     # Directorio de renderizado de videos finales (.mp4 9:16)
│   ├── clip_1.mp4 ... clip_6.mp4      # Clips generados listos para consumo o distribución
├── gradio.log                         # Registro histórico de actividad de la interfaz gráfica
├── jobs/                              # Directorios aislados por ejecución (<timestamp>_<slug_url>/)
│   ├── <job_id>/                      # Contexto único del stream analizado
│   │   ├── clips.json                 # Metadatos de clips pertenecientes exclusivamente a ese job
│   │   ├── temp_audio.mp3             # Audio mono 16kHz del stream
│   │   └── subs_<id>.ass              # Subtítulos estilizados generados para cada clip
├── legacy/                            # Módulos previos a la refactorización unificada v3.1
│   ├── analizar_stream.py
│   ├── clips_virales/
│   ├── recortar_clips.py
│   └── subir_lote.py
├── pipeline_viral_clips.py            # Motor unificado v3.2 (curaduría IA, FFmpeg fontsdir, telemetría y CLI)
├── procesar_video_universal.py        # Wrapper CLI para corte individual rápido
├── requirements.txt                   # Especificación de dependencias del entorno de producción
├── subidas_shorts.json                # Base de datos local/historial de subidas a YouTube Shorts
├── subir_shorts.py                    # Módulo de integración OAuth 2.0 y subida con YouTube Data API v3
├── tests/                             # Suite de pruebas unitarias automatizadas
│   ├── test_pipeline_v31.py           # 16 tests unitarios v3.1 (offline + smoke FFmpeg)
│   └── test_pipeline_v32.py           # 14 tests unitarios v3.2 (fontsdir, libass real, telemetría, Gradio y CLI)
├── token.json                         # [PROTEGIDO - ZERO-SECRETS] Token OAuth 2.0 cuenta activa
├── token_cuenta_anterior.json         # [PROTEGIDO - ZERO-SECRETS] Token OAuth 2.0 cuenta previa
└── venv/                              # Entorno virtual de Python aislado
```

---

## 2. Esquema de Datos y Contratos Pydantic (`ClipViral` y `SegmentoSubtitulo`)

### 2.1 Código Literal de los Modelos Pydantic
Definidos en `pipeline_viral_clips.py`:

```python
class SegmentoSubtitulo(BaseModel):
    """Segmento individual de subtítulo dinámico sincronizado relativo al inicio del clip."""

    inicio_rel: float = Field(
        description="Segundo de inicio relativo al comienzo del clip (ej. 0.0)."
    )
    fin_rel: float = Field(
        description="Segundo de fin relativo al comienzo del clip (ej. 2.1)."
    )
    texto: str = Field(
        description="Transcripción literal en bloque de lectura rápida: 2 a 4 palabras, máximo 22 caracteres, sin emojis."
    )


class ClipViral(BaseModel):
    """Esquema estructurado de cada clip viral detectado por Gemini con SEO multiplataforma (YouTube Shorts + TikTok)."""

    id: int = Field(description="Identificador entero secuencial del clip (1, 2, 3...)")
    titulo: str = Field(
        description="Título magnético de alta tasa de clics (CTR), máximo 60 caracteres, en español coloquial/streamer."
    )
    inicio: str = Field(description="Timestamp exacto de inicio en formato HH:MM:SS")
    fin: str = Field(description="Timestamp exacto de fin en formato HH:MM:SS")
    gancho: str = Field(
        description="Primeras palabras textuales exactas del hook en los primeros 2 segundos"
    )
    razon_viral: str = Field(
        description="Explicación estratégica del gatillo de retención, polémica, tensión o clímax narrativo"
    )
    descripcion: str = Field(
        description="Resumen corto (2 líneas) con llamado a la acción (CTA) de suscripción y 3-5 hashtags estratégicos (ej. #Shorts #Kicksazos #StreamColombia)"
    )
    etiquetas: List[str] = Field(
        description="Lista de 8 a 12 tags SEO clave incluyendo nombres propios de involucrados y ecosistema streaming colombiano"
    )
    caption_tiktok: str = Field(
        description="Caption para TikTok de máximo 150 caracteres optimizado para SEO semántico y diseñado para detonar comentarios."
    )
    hashtags_tiktok: List[str] = Field(
        description="Lista de exactamente 3 a 5 hashtags estratégicos para TikTok mezclando nicho y alcance, sin spam."
    )
    gancho_visual_portada: str = Field(
        description="Titular visual de portada de 4 a 6 palabras, impactante, pensado para los primeros 2 segundos de retención en TikTok."
    )
    subtitulos: List[SegmentoSubtitulo] = Field(
        default_factory=list,
        description="Transcripción literal en bloques cortos (2 a 4 palabras, máximo 22 caracteres, sin emojis) sincronizados en segundos relativos desde 0.0 hasta la duración del clip.",
    )
```

### 2.2 Reglas de Validación y Normalización en el Pipeline

#### `_limpiar_y_parsear_json(texto, duracion_total=None, permitir_vacio=False)`
1. **Limpieza Regex de Bloques Markdown:** Elimina delimitadores ` ```json ` o ` ``` ` al inicio o final de la respuesta.
2. **Validación Estricta con Pydantic `TypeAdapter(List[ClipViral])`:** Intenta deserializar el JSON crudo. Si falla por texto decorativo alrededor, aplica búsqueda regex `\[.*\]` para extraer el arreglo interior.
3. **Manejo de Respuestas Clave-Valor:** Si el modelo entrega un objeto `{"clips": [...]}`, extrae la lista interna.
4. **Validación Temporal de Timestamps:**
   - Convierte `inicio` y `fin` mediante `hhmmss_a_segundos()`. Descarta clips con timestamps corruptos.
   - Si `duracion_total` es provista, descarta clips que inicien a menos de 2 segundos del final del audio (`ini_s >= duracion_total - 2`) y recorta `fin_s` para que no sobrepase `duracion_total`.
   - Exige una duración mínima de clip de 5 segundos (`duracion_clip = fin_s - ini_s >= 5`).
5. **Tratamiento de Longitudes y Defaults:**
   - Trunca `titulo` a máximo 60 caracteres (añadiendo elipsis `...`).
   - Inyecta llamada a la acción y `#Shorts #Kicksazos #StreamColombia` en la `descripcion` si no estaban presentes.
   - Pasa los campos por sus respectivos normalizadores (`_normalizar_etiquetas`, `_normalizar_caption_tiktok`, `_normalizar_hashtags_tiktok`, `_normalizar_gancho_portada`, `_normalizar_subtitulos`).
6. **Inyección de Metadatos Operativos:** Añade `duracion_segundos` redondeado al entero más cercano y renumera `id` secuencialmente (1, 2, ...).

#### `_normalizar_etiquetas(raw_tags)`
- Convierte strings separados por comas, saltos de línea o listas crudas en una lista de tags sin caracteres `#`.
- Elimina duplicados preservando el orden.
- Rellena automáticamente con tags predeterminados del ecosistema colombiano (`Shorts`, `Kicksazos`, `StreamColombia`, `KickColombia`, `ClipsVirales`, `IRLColombia`, `StreamersColombianos`, `PolémicaStream`, `WestCOL`, `YouTubeShorts`) si hay menos de 8 tags.
- Limita la lista final a exactamente entre 8 y 12 tags.

#### `_normalizar_subtitulos(raw_subs, duracion_clip)`
- **Filtrado de Rango y Emojis:** Descarta segmentos donde `inicio_rel >= duracion_clip` o `fin_rel <= inicio_rel + 0.05`. Remueve emojis mediante la expresión regular `[𐀀-􏿿☀-➿️‍]+` para evitar caracteres rotos o rectángulos vacíos en libass.
- **Deduplicación y Solapamiento:** Ordena cronológicamente por `(inicio_rel, fin_rel)`. Si un segmento inicia antes de que termine el anterior (`seg.inicio_rel < prev.fin_rel`), recorta el final del anterior o ajusta el inicio del nuevo para garantizar una línea temporal continua sin superposición visual.
- **Auto-Partición de Bloques Largos (`_dividir_segmento_subtitulo`):** Si un subtítulo dura más de 0.6s y excede 5 palabras o 28 caracteres, lo subdivide matemáticamente en grupos de 2 a 4 palabras, distribuyendo la duración proporcionalmente a la cantidad de caracteres de cada fragmento con márgenes mínimos de 0.05s.

---

## 3. Motor de Curaduría IA, Resiliencia Free Tier y Chunking

### 3.1 Copia Literal Actual de `construir_prompt_viral()`
```python
def construir_prompt_viral(duracion_total: Optional[float] = None) -> str:
    """Construye el prompt multiplataforma (YouTube Shorts + TikTok 2026) con transcripción fonética forense y curaduría dinámica."""
    info_duracion = (
        f"\nDURACIÓN TOTAL DE ESTE AUDIO: {segundos_a_hhmmss(duracion_total)} "
        "(JAMÁS generes timestamps `inicio` o `fin` superiores a este límite)."
        if duracion_total
        else ""
    )
    return f"""Actúa como un Senior Growth Hacker, estratega de algoritmos de YouTube Shorts / TikTok (2026), transcriptor fonético forense y editor experto en el ecosistema de IRL y streaming de Colombia (WestCOL, MrStivenTC, Blessd, La Liendra, Yhap, eldomi, eventos IRL y polémicas).

Analiza el audio adjunto y extrae ÚNICAMENTE los segmentos con verdadero potencial de viralidad y alta retención de audiencia.{info_duracion}

### 1. CANTIDAD DINÁMICA DE CLIPS (CALIDAD Y RETENCIÓN PRIMERO):
- NO existe un número mínimo ni máximo de clips a extraer.
- Extrae tantos o tan pocos clips como justifique la calidad real del contenido (pueden ser 1, 4, 8 o los que realmente valgan la pena).
- Prohibido rellenar con clips aburridos o tiempos muertos: cada clip seleccionado debe tener un pico emocional, cómico, polémico o narrativo capaz de retener a la audiencia de principio a fin.

### 2. REGLA DEL PRIMER SEGUNDO Y DURACIÓN ESTRATÉGICA:
- Abre inmediatamente en el pico de tensión, confesión o curiosidad (0.0s de introducción muerta) para vencer la tasa de deslizamiento (swipe-away rate).
- Duración adaptada a retención: prioriza clips de 22-45 segundos (retención explosiva en Shorts) o de 60-75 segundos (arcos narrativos completos con clímax para TikTok Creator Rewards). Jamás cortes una frase o remate a la mitad.
- Estructura de Bucle (Seamless Loop): busca que el cierre del clip conecte de forma natural con la frase inicial.

### 3. PRECISIÓN FORENSE EN SUBTÍTULOS (CERO ALUCINACIONES):
- Transcribe LITERALMENTE lo que se escucha en el audio. Está ESTRICTAMENTE PROHIBIDO inventar frases, parafrasear, resumir o adivinar palabras que no se pronunciaron.
- Respeta la jerga colombiana real pronunciada en el audio (ej. "gonorrea", "parce", "chimba", "pirobo", "sisas", "nea", "marica") sin sustituirla por palabras neutras inventadas.
- Si hay ruido, música alta o voces superpuestas ininteligibles en un segundo específico, omite ese segundo en vez de alucinar texto.
- Divide el atributo `subtitulos` en bloques dinámicos de lectura rápida (ESTRICTAMENTE de 2 a 4 palabras por bloque, máximo 22 caracteres por segmento, SIN EMOJIS) con `inicio_rel` y `fin_rel` exactos en segundos respecto al inicio del clip (`0.0`), en orden cronológico y sin solapamientos.

### 4. METADATOS SEPARADOS Y OBLIGATORIOS POR CLIP:
- YouTube Shorts: `titulo` (máx 60 chars), `descripcion` (2 líneas con gancho + CTA + #Shorts), `etiquetas` (8-12 tags SEO).
- TikTok: `caption_tiktok` (máx 150 chars optimizado para SEO semántico y debate en comentarios), `hashtags_tiktok` (3 a 5 tags exactos mezclando nicho y alcance), `gancho_visual_portada` (titular impactante de 4-6 palabras).
- Común: `id` (entero secuencial), `inicio` y `fin` (`HH:MM:SS`), `gancho`, `razon_viral`, `subtitulos`."""
```

### 3.2 Modelos Candidatos y Configuración de Inferencia
- **Lista de Modelos (`MODELOS_CANDIDATOS`):**
  1. `gemini-3.8-flash` (Modelo principal de última generación)
  2. `gemini-3.7-flash` (Primer fallback de alto rendimiento multimodal)
  3. `gemini-3.5-flash-lite` (Fallback hiper-rápido y ultra-económico en consumo de cuota)
- **Configuración de `GenerateContentConfig`:**
  - `response_mime_type="application/json"`
  - `response_schema=list[ClipViral]` (Forzado mediante Structured Outputs nativos de la SDK `google-genai`)
  - `temperature=0.20` (Baja estocasticidad para evitar alucinaciones en subtítulos y marcas de tiempo)
  - `timeout=600000` ms (10 minutos por llamada HTTP para procesar audios de gran tamaño)

### 3.3 Cascada de Modelos y Resiliencia en Cuotas Free Tier
El pipeline implementa una máquina de estados para tolerar fallos en el Free Tier de Gemini:
1. **Detección Forense de Error 429:**
   - Distingue entre **límite de peticiones por minuto (RPM)** y **agotamiento de cuota diaria (RPD)** mediante `_es_error_cuota_diaria_free_tier()`.
   - Si el mensaje o detalle del error `429` contiene strings como `"free_tier_requests"`, `"perday"`, `"per day"` o `"limit: 20"`, el pipeline detecta que la cuota del día para ese modelo se agotó por completo.
   - **Salto Inmediato (0 segundos):** En caso de cuota diaria agotada, **NO duerme** ni ejecuta backoff inútil; descarta de inmediato el modelo actual y salta al siguiente de la lista en 0 segundos.
   - **Backoff Exponencial con Jitter:** Si el error 429 es transitorio (RPM) o un error `503` (sobrecarga temporal de Google), ejecuta hasta 4 reintentos aplicando `_esperar_con_jitter(intento, base=3.0, max_espera=30.0)` con aleatoriedad (`random.uniform`) para evitar tormentas de reintentos concurrentes.
2. **Subida y Ciclo de Vida en Gemini File API:**
   - Sube el archivo `.mp3` mediante `client.files.upload()`.
   - Sondea su estado activo cada 2.5 segundos con un timeout máximo de 300 segundos.
   - En el bloque `finally`, garantiza la eliminación del archivo temporal en los servidores de Google con `client.files.delete()` para mantener la cuota de almacenamiento limpia.

### 3.4 Segmentación de Audios Largos (*Audio Chunking*) y Offsets Absolutos
Para streams o podcasts de larga duración:
- **Umbral de Activación:** Streams con duración mayor a 55 minutos (`> 3300 segundos`).
- **Función `_segmentar_audio_en_chunks()`:**
  - Divide el audio en bloques de máximo 45 minutos (`2700 segundos`) con una ventana de solapamiento de 90 segundos entre bloques consecutivos.
  - Utiliza `ffmpeg -ss <offset> -t <duracion> -c copy` sin recodificar para una partición instantánea.
- **Compensación de Offsets Temporales:**
  - Los clips devueltos por Gemini dentro de cada bloque tienen marcas de tiempo relativas al chunk.
  - La función `analizar_con_gemini()` suma el `offset_seg` a `inicio` y `fin` convirtiéndolos en timestamps absolutos del stream completo.
  - **Importante:** Los `subtitulos` (`inicio_rel`, `fin_rel`) **NO** sufren desplazamiento de stream, ya que son relativos al segundo 0.0 del clip específico.
- **Deduplicación Inter-Chunk:**
  - En las zonas de 90s de solapamiento pueden detectarse clips duplicados.
  - La función `_clips_solapan()` calcula el índice de solapamiento temporal. Si dos clips de bloques consecutivos se solapan en más de un 50% de su duración, se conserva únicamente el de mayor longitud o mejor puntuación narrativa.

---

## 4. Pipeline Multimedia (Descarga de Audio, FFmpeg VAAPI y Subtítulos `.ass`)

### 4.1 Extracción de Audio (`extraer_audio()`) y Telemetría de Red
1. **Ruta y Aislamiento:** Todo el audio se extrae como mono a 16 kHz y 32 kbps (`-ac 1 -ar 16000 -b:a 32k`), formato óptimo para reconocimiento de voz en Gemini minimizando tamaño de transferencia.
2. **Intento Primario (yt-dlp Paralelo Agresivo con `--newline` y `Popen`):**
   - Parámetros: `--newline --progress --concurrent-fragments 16 --retries 10 --fragment-retries 10 --buffer-size 16K --http-chunk-size 10M --retry-sleep fragment:exp=1:10`.
   - Selector de formato: `ba/worst[height<=360]/worst/b[height<=360]/b` (prioriza audio-only o la pista de menor resolución).
   - Aceleración con `aria2c`: Si `aria2c` está instalado y la URL **NO** es un stream en vivo HLS (`.m3u8` de Kick o Twitch), inyecta `--downloader aria2c --downloader-args 'aria2c:-x 16 -s 16 -k 1M'`.
   - **Telemetría de Red en Vivo:** `_ejecutar_descarga_con_telemetria()` lee `stdout` línea por línea y `_parsear_linea_progreso_descarga()` extrae porcentaje, tamaño total, velocidad MB/s, `ETA` y fragmentos (`frag cur/tot`) tanto de `[download]` de `yt-dlp` como del formato `aria2c`, emitiendo hasta **3 actualizaciones/seg** (`min_intervalo=0.33s`, con cierre seguro de pipes vía `_cerrar_pipes_proceso()`).
   - Validación de Integridad: Si el archivo extraído no supera los 10 KB (`10_240 bytes`), se considera corrupto o bloqueado.
3. **Fallback Automático (Streaming Directo FFmpeg con `-progress pipe:1`):**
   - Si yt-dlp falla en la descarga completa, ejecuta `yt-dlp -g` para resolver la URL directa del stream CDN.
   - Pasa la URL HTTP/HTTPS directamente a FFmpeg con flags de reconexión de red (`-reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5 -rw_timeout 15000000`) y `-loglevel warning -progress pipe:1 -nostats` vía `_ejecutar_comando_con_captura()`.
   - Extrae el audio mono directamente por streaming sin descargar el video.

### 4.2 Subtítulos Estilizados con Tipografía Embebida (`generar_archivo_ass()`)
- **Tipografía ExtraBold Empaquetada (`assets/fonts/`):**
  - `_obtener_fuente_y_dir_subtitulos()` inspecciona `CARPETA_FUENTES = BASE_DIR / "assets" / "fonts"` buscando archivos `.ttf`/`.otf` locales (empaquetando **`Montserrat-ExtraBold.ttf`**).
  - Usa `fc-scan --format "%{fullname[0]}\n%{family}\n"` para extraer el nombre exacto de familia coincidente (`"Montserrat ExtraBold"`) y retorna `(nombre_familia, str(CARPETA_FUENTES))` para pasarlo al filtro `fontsdir=` de `libass`.
  - Si no hubiese fuentes locales en `assets/fonts/`, ejecuta el fallback `_detectar_fuente_subtitulos()` sobre `fc-list` (`Montserrat`, `Poppins`, `Impact`, `Liberation Sans`, `Ubuntu`, fallback `DejaVu Sans`) con `fonts_dir=None`.
- **Especificaciones del Formato ASS v3.2 (Resolución 1080x1920):**
  - `PlayResX: 1080`, `PlayResY: 1920`, **`WrapStyle: 2`** (evita saltos de línea automáticos indeseados al usar bloques ya segmentados a 2–4 palabras).
  - `Style: Default,<fuente>,54,&H00FFFFFF,&H0000FFFF,&H00000000,&HA0000000,-1,0,0,0,100,100,1.5,0,1,5.5,3.5,2,65,210,550,1`
  - **Parámetros Clave:**
    - `Fontsize: 54` y `Spacing: 1.5`: Alta presencia tipográfica y ligero tracking optimizado para lectura rápida móvil.
    - `PrimaryColour: &H00FFFFFF` (Blanco puro) y `SecondaryColour: &H0000FFFF` (Amarillo intenso).
    - `OutlineColour: &H00000000` (`Outline: 5.5`) y `BackColour: &HA0000000` (Sombra profunda con `Shadow: 3.5`).
    - `Alignment: 2` (Centrado horizontal, anclado a la base).
    - `MarginL: 65`, `MarginR: 210` (Margen derecho optimizado para despejar la botonera vertical interactiva de TikTok y YouTube Shorts manteniendo centrado óptico).
    - `MarginV: 550` (Tercio medio-inferior seguro, libre de UI inferior y sin cubrir el rostro).
    - **Normalización ASS:** `_limpiar_texto_ass()` elimina emojis sin glifo, reemplaza `{`/`}` por `(`/`)`, convierte saltos a `\N` y transforma el texto a **MAYÚSCULAS (`texto.upper()`)**.
- **Efecto de Animación Pop-in:**
  - Cada diálogo se envuelve en: `{\fad(40,40)\t(0,70,\fscx105\fscy105)\t(70,140,\fscx100\fscy100)}`
  - Produce un micro-escalado al 105% en 70ms y retorno al 100% en 140ms, capturando la atención visual en cada cambio de palabra.

### 4.3 Procesamiento, Telemetría `-progress pipe:1` y Renderizado 9:16 (`procesar_clip_ffmpeg()`)
1. **Input Seeking Eficiente:** Emplea `-ss <inicio>` y `-t <duracion>` antes de `-i` para buscar por paquetes en el contenedor remoto, descargando exclusivamente los segundos requeridos para el clip.
2. **Caché en Memoria (`StreamUrlCache`):** Almacena las URLs directas de video y audio resueltas por `yt-dlp` por cada `job_id`, evitando múltiples llamadas redundantes a la API de Kick o YouTube.
3. **Manejo de Enlaces Expirados (HTTP 403 / 410):** Si el CDN de Kick/Cloudflare invalida los tokens de sesión durante un stream largo, FFmpeg captura el error `403 Forbidden`, invalida `STREAM_URL_CACHE`, resuelve nuevas URLs y reintenta la renderización sin abortar el trabajo.
4. **Composición del `filter_complex` con Inyección de `fontsdir=`:**
   ```text
   [0:v]split=2[bg][fg];
   [bg]scale=360:640:force_original_aspect_ratio=increase,crop=360:640,setsar=1,boxblur=10:2,scale=1080:1920:flags=bilinear[bg_blur];
   [fg]scale=1080:1920:force_original_aspect_ratio=decrease,setsar=1[fg_scaled];
   [bg_blur][fg_scaled]overlay=(W-w)/2:(H-h)/2[vid_comp];
   [1:v]scale=420:-1,format=rgba,colorchannelmixer=aa=0.92[wm];
   [vid_comp][wm]overlay=(W-w)/2:<y_wm>,subtitles='<ruta_ass>':fontsdir='<fonts_dir>',format=nv12,hwupload[outv]
   ```
5. **Telemetría FFmpeg en Tiempo Real (`-progress pipe:1`):**
   - `_construir_comando_render()` inyecta `-loglevel warning -progress pipe:1 -nostats` y `:fontsdir='<dir>'` si existe carpeta de fuentes locales.
   - `_ejecutar_comando_con_captura()` ejecuta FFmpeg mediante `subprocess.Popen` leyendo bloques `clave=valor` por `stdout` (usando `out_time_us / 1_000_000` ya que FFmpeg 8.0.1 reporta microsegundos tanto en `out_time_us` como en `out_time_ms`) y lee `stderr` en hilo dedicado para evitar deadlocks de pipe.
   - Emite `etapa="render"`, porcentaje real del clip (`out_sec / duracion_clip * 100`), `fps`, multiplicador de velocidad `velocidad_x` (ej. `2.95x`), `eta` calculada dinámicamente (`(duracion - out_sec) / speed_val`), `encoder` activo, `clip_id` y progreso `clip_indice/total_clips`.
6. **Cálculo Adaptativo de Marca de Agua:**
   - La función `_calcular_y_watermark()` evalúa la relación de aspecto del video original.
   - Si el video es horizontal (16:9), sitúa la marca de agua centrada horizontalmente y colocada verticalmente a 24 píxeles por encima del cuadro del video (`(H-h_fg)/2 - h - 24`), respetando siempre un límite de seguridad superior `y >= 200` para no superponerse a la cabecera de la aplicación móvil.
7. **Hardware Acceleration VAAPI vs Fallback CPU:**
   - Intento primario con `h264_vaapi`: Requiere inicialización con `-vaapi_device /dev/dri/renderD128` y conversión `format=nv12,hwupload[outv]` con `-qp 23`.
   - Fallback a CPU (`libx264`): Si la GPU falla o el nodo `/dev/dri/renderD128` arroja error de render, el pipeline conmuta automáticamente a codificación por software con `format=yuv420p[outv]`, `-c:v libx264 -preset veryfast -crf 22 -threads 0`.
   - Fallback de Subtítulos: Si el motor de renderizado falla por algún fallo en la sintaxis de libass, reintenta automáticamente el clip sin subtítulos para no perder el video.

---

## 5. Orquestación CLI, Interfaz Gradio (`app_interfaz.py`) y Publicación YouTube (`subir_shorts.py`)

### 5.1 Orquestador Unificado `ejecutar_pipeline_completo()` y Puente de Telemetría
Es una función generadora (`Generator[Dict[str, Any], None, None]`) que centraliza toda la ejecución tanto para la terminal como para la web, incluyendo siempre el diccionario `"telemetria"` en `_emitir_estado()`:
1. **Fase 0: Inicialización y Contexto:** Genera `JobContext(job_id, job_dir)` bajo `jobs/<timestamp>_<slug_url>/`. Valida `GEMINI_API_KEY` y formatos de fecha futuros.
2. **Puente Worker -> Generador (`_ejecutar_paso_con_telemetria`):** Ejecuta etapas bloqueantes (`extraer_audio`, `analizar_con_gemini`, `descargar_video_fuente`, `procesar_clip_ffmpeg`) en un hilo `daemon=True` con una `queue.Queue`, re-emitiendo cada evento `on_telemetria` al consumidor del generador en vivo sin bloquear la interfaz. Usa `_acepta_kwarg()` (compatible incluso con `unittest.mock` via `side_effect`) para mantener retrocompatibilidad con wrappers externos.
3. **Fase 1: Extracción de Audio (`etapa="descarga"`):** Invoca `extraer_audio()` con almacenamiento en `jobs/<job_id>/temp_audio.mp3` y telemetría de red MB/s en vivo.
4. **Fase 2: Curaduría IA (`etapa="gemini"`):** Ejecuta `analizar_con_gemini()` reportando bloque activo y modelo, y sincroniza `clips.json` en `job_dir` y raíz. Si `solo_analisis` está activo, finaliza aquí.
5. **Fase 3: Renderizado de Clips (`etapa="render"`):** Prepara fuente (`descargar_video_fuente` si <= 1 h o streaming HLS cacheado), genera `subs_<id_clip>.ass`, invoca `procesar_clip_ffmpeg()` emitiendo FPS, velocidad `x`, ETA y encoder, y almacena en `clips_finales/<job_id>_clip_<id>.mp4`.
6. **Fase 4: Publicación en YouTube Shorts (`etapa="youtube"`):**
   - Si `subir_youtube=True`, autentica contra YouTube Data API v3.
   - Aplica `verificar_cuota_diaria()` para no saturar la cuota de la API (límite configurado a 6 videos por día).
   - Calcula la fecha programada mediante `calcular_publish_at_utc(publish_at_inicio, indice, intervalo_horas)`.
   - Sube en privacidad `private` y registra el evento en `subidas_shorts.json`.

### 5.2 Flags del CLI (`pipeline_viral_clips.py`) y Barra Visual `RenderizadorProgresoCLI`
- `url`: (Obligatorio) URL del stream o video.
- `--solo-analisis`: Extrae audio y genera `clips.json` sin renderizar video ni gastar CPU/GPU.
- `--sin-subida`: Renderiza todos los clips en 9:16 pero no los sube a YouTube.
- `--modelo`: Define el modelo inicial preferido para Gemini (ej. `gemini-3.8-flash`).
- `--publish-at`: Fecha/hora de inicio en hora local de Colombia `-05:00` (ej. `2026-11-15 14:00`).
- `--intervalo-horas`: Espaciado en horas entre Shorts programados (ej. `2` horas).
- **Barra de Progreso Visual en Terminal:** `RenderizadorProgresoCLI` + `_formatear_barra_cli()` renderizan `[████████░░░░] 50.0% | ...` usando `\r\x1b[2K` en TTY reales (limpiando la barra antes de cada `.log()` para no mezclar texto) o líneas limpias por hitos `>=15%` / cambios de etapa fuera de TTY.

### 5.3 Interfaz Web Gradio (`app_interfaz.py`) y Panel de Telemetría Animado
- **Diseño Visual Kicksazos:** Tema oscuro con acentos violeta (`#8b5cf6`) y verde neón Kick (`#53fc18`).
- **Panel HTML/CSS Animado (`construir_panel_telemetria_html` + `telemetria_panel`):**
  - Muestra punto de pulso en vivo (`@keyframes kicksazos-pulse-dot`), barra animada de etapa activa (`@keyframes kicksazos-bar-shimmer`), barra de progreso global del job y grilla de 4 KPIs dinámicos: Velocidad (MB/s o `x • FPS`), ETA restante, Motor/Encoder (`yt-dlp 16 hilos`, modelo Gemini, `h264_vaapi` / `libx264`), y Bloque/Tamaño/Clip.
  - **Optimización de Ticks en Gradio (`ejecutar_pipeline_gradio`):** Emite **9 salidas** incluyendo `telemetria_panel`. En los ticks de telemetría de hasta 3×/seg sin cambios de hito/video/clips, devuelve `gr.skip()` para `galeria_videos`, `video_preview`, `clips_json_view`, `tarjetas_galeria_html`, `tabla_historial` y `resumen_historial_html`, evitando re-escanear `clips_finales/` con `ffprobe` o provocar parpadeos en el reproductor.
- **Seguridad Contra Inyecciones HTML (Sanitización Exhaustiva):**
  - Todo dato renderizado en pantalla —incluyendo telemetría en vivo (velocidad red, encoder, títulos, detalles), hooks, tags, URLs y nombres de archivos— pasa obligatoriamente por `html.escape(texto, quote=True)`.
  - Los hipervínculos externos se validan con `_sanitizar_url_href()` permitiendo exclusivamente los esquemas `http://` y `https://`, forzando `rel="noopener noreferrer"` y previniendo vectores de ataque como `javascript:`.
- **Componentes:**
  - Pestaña de Control: `estado_banner`, `telemetria_panel`, entrada de URL, selector de modelo IA, switches de solo análisis o subida a YouTube, selectores de fecha de programación, logs, preview de video y JSON colapsable.
  - Visor de Clips: Galería 9:16, reproductor y tarjetas interactivas con botones de copiado rápido (`📋 Copiar`) para títulos, descripciones, hashtags y captions de TikTok.
  - Monitor de Historial y Cuota: Visualización del estado de subidas en las últimas 24 horas y cupos restantes.

### 5.4 Publicación en YouTube (`subir_shorts.py`)
- **Autenticación OAuth 2.0 y `token.json`:**
  - Usa los alcances `https://www.googleapis.com/auth/youtube.upload`.
  - Si el token expira pero posee `refresh_token`, se refresca silenciosamente en memoria y actualiza el archivo en disco.
- **Función `obtener_hash_cuenta()` (Trazabilidad Zero-Secrets):**
  - Genera un hash SHA-256 truncado a 12 caracteres derivado de la semilla de credenciales (`rt:<refresh_token>` o `cid:<client_id>`).
  - Permite identificar de forma única en `subidas_shorts.json` qué cuenta subió el clip sin exponer jamás llaves ni tokens privados.
- **Normalización de `publishAt` (UTC vs Colombia -05:00):**
  - La API de YouTube exige la propiedad `publishAt` en formato ISO 8601 estricto con sufijo `Z` (`YYYY-MM-DDTHH:MM:SSZ`).
  - La función `_normalizar_publish_at_futuro()` convierte la hora local de Colombia a UTC y verifica que la fecha sea estrictamente futura. Si la fecha ya expiró, sube el video como privado inmediato.
- **Resiliencia de Red en Subida por Chunks:**
  - Emplea `MediaFileUpload(resumable=True)` con `request.next_chunk()`.
  - Captura `HttpError` reintentables (`500`, `502`, `503`, `504`) y errores transitorios de socket (`ConnectionError`, `ssl.SSLError`, `socket.timeout`) ejecutando reintentos con backoff y jitter de hasta 4 intentos.

---

## 6. Historial Operativo y Datos Reales (`subidas_shorts.json` y `clips.json`)

### 6.1 Resumen Estadístico de Subidas
- **Total de Subidas Registradas:** 7 videos.
- **Categoría YouTube:** `24` (Entretenimiento).
- **Parámetro `madeForKids`:** `False` en el 100% de las subidas.
- **Visibilidad:** `private` en el 100% de las subidas.
- **Distribución de Cuentas:** 6 subidas realizadas en la cuenta principal (`63810c9535bf`), 1 subida manual de prueba (`desconocida`).

### 6.2 Tabla de Registros en `subidas_shorts.json`
| Fecha de Subida | Archivo | ID YouTube | Título | Privacidad | Cuenta ID |
| :--- | :--- | :--- | :--- | :--- | :--- |
| 2026-11-11 00:20:13 | `clip_1.mp4` | `LQIcG8bjKNQ` | ¡LO TIENEN ACORRALADO EN PLENO IRL! 😂👀 #Shorts | private | `63810c9535bf` |
| 2026-11-11 00:44:20 | `clip_1.mp4` | `omzV0U7F9RQ` | ¿CUÁNTO LE REBAJAMOS AL CAMARÓGRAFO? 😡📉 #Shorts | private | `63810c9535bf` |
| 2026-11-11 00:45:25 | `clip_2.mp4` | `W-ybt9xaGvU` | ¿PINTARME DE AZUL COMO BLESSD? NUNCA 🔵🧢 #Shorts | private | `63810c9535bf` |
| 2026-11-11 00:46:48 | `clip_3.mp4` | `KZB9ToKaeaU` | LA VERDAD DE CUÁNTO PAGA KICK EN COLOMBIA 💸🇨🇴 #Shorts | private | `63810c9535bf` |
| 2026-11-11 00:47:41 | `clip_4.mp4` | `-Hd7i3Y4IUg` | ¡NUNCA SE METAN CON UN GOTA A GOTA! ⚠️💀 #Shorts | private | `63810c9535bf` |
| 2026-11-11 00:48:43 | `clip_5.mp4` | `H-fGRr_ySXo` | ¡CASI NOS MATAN EN PROVENZA EN PATINETA! 🛴😱 #Shorts | private | `63810c9535bf` |
| 2026-11-11 20:49:06 | `clip_1.mp4` | `FJnV_odrhC4` | ¡Momento Épico en Vivo! 😂 #Shorts | private | `desconocida` |

### 6.3 Resumen de Clips en `clips.json` Actual
- **Modelo IA Utilizado:** `gemini-3.5-flash-lite`
- **Clip 1:**
  - **Título:** *¡SE ENTERÓ EN VIVO! La reacción que paralizó el stream 🚨*
  - **Timestamps:** `00:07:07` -> `00:07:45` (38 segundos)
  - **Gancho:** *"Oye, qué rico"*
  - **Razón Viral:** Genera intriga inmediata y capta la atención del espectador con un saludo casual que evoluciona rápidamente a una interacción de chat caliente y directa sobre el mundo del streaming colombiano.
- **Clip 2:**
  - **Título:** *¡MILLONES EN JUEGO! La verdad oculta del streaming 💸*
  - **Timestamps:** `00:10:07` -> `00:10:55` (48 segundos)
  - **Gancho:** *"Por qué tanto me ignoras"*
  - **Razón Viral:** Toca fibras sensibles con una queja de atención que resuena fuertemente con la dinámica de la comunidad y los chats intensos de las plataformas de streaming.
- **Clip 3:**
  - **Título:** *¡SE PICÓ! Le cantó la tabla sin miedo a nada 🔥*
  - **Timestamps:** `00:13:00` -> `00:13:42` (42 segundos)
  - **Gancho:** *"Para mí es un placer conocerte"*
  - **Razón Viral:** El tono de coqueteo y confrontación directa engancha al instante por el morbo de saber cómo reaccionará la otra persona ante semejante propuesta.

---

## 7. Deuda Técnica Actual, Limitaciones Conocidas y Roadmap de Escalamiento

### 7.1 Estado de Resolución (Lo que ya funciona robustamente)
- [x] **Aislamiento por Jobs (`jobs/<job_id>`):** Los streams ya no pisan archivos temporales compartidos en la raíz.
- [x] **Resiliencia en Free Tier de Gemini:** Máquina de estados que salta en 0s ante agotamiento diario de cuota y aplica backoff exponencial con jitter en errores transitorios.
- [x] **Audio Chunking:** Segmentación limpia de audios mayores a 55 minutos con solapamiento de 90s y compensación matemática de offsets.
- [x] **Protección Contra Enlaces Expirados:** Recuperación automática contra errores HTTP 403/410 de Kick/Cloudflare mediante invalidación de caché.
- [x] **Seguridad XSS y Zero-Secrets:** Sanitización completa en Gradio (`html.escape()` en banners, telemetría en vivo y tarjetas, validación de esquemas URL) y cero exposición de tokens en logs y hashes.
- [x] **Tipografía Profesional Embebida (`fontsdir=`):** Fuente estática `assets/fonts/Montserrat-ExtraBold.ttf` cargada explícitamente en FFmpeg (`libass`) sin caída al fallback del sistema, con `WrapStyle: 2` y texto en MAYÚSCULAS.
- [x] **Telemetría Gráfica y Terminal en Vivo:** Streaming throttled (`<= 3 Hz`) de descarga (`yt-dlp --newline` + `aria2c`), bloques Gemini y FFmpeg `-progress pipe:1` (`out_time_us`, FPS, velocidad `x`, ETA, encoder), renderizado con panel HTML/CSS animado (`gr.skip()`) en Gradio y `RenderizadorProgresoCLI` en terminal.
- [x] **Batería de Pruebas Unitarias:** **30 tests unitarios automatizados** (`test_pipeline_v31.py` + `test_pipeline_v32.py`) con mocks offline, verificación de `gr.skip()`/XSS y smoke tests reales de `ffmpeg`/`libass` + `:fontsdir=`.

### 7.2 Limitaciones Conocidas y Deuda Técnica Pendiente
1. **Caducidad de Tokens OAuth en Modo Testing (7 Días):**
   - La aplicación en Google Cloud Console se encuentra en estado de publicación "Testing".
   - Por políticas de Google, los tokens de aplicaciones en modo de prueba que no han pasado por el proceso de verificación expiran a los 7 días calendario, obligando a reautenticar manualmente en un navegador.
   - *Solución:* Pasar la aplicación en Google Cloud Console a estado "In Production" (Producción) para que el `refresh_token` sea permanente.
2. **Políticas de "Contenido Reutilizado" (YouTube YPP y TikTok Creator Rewards):**
   - Subir clips de transmisiones ajenas sin valor agregado significativo puede activar flags de desmonetización en el YouTube Partner Program o provocar supresión de alcance en TikTok.
   - *Mitigación en Pipeline:* El desenfoque de fondo dinámico, el reencuadre 9:16, la marca de agua adaptativa y la quema de subtítulos animados modifican la firma espectral y visual del video, pero se recomienda enriquecer los clips con intros narrativas o comentarios de voz sintética.
3. **[RESUELTO en v3.2] Dependencia de Fuentes del Sistema:**
   - Anteriormente, si un sistema Linux no poseía instaladas tipografías como `Montserrat` o `Poppins`, `fc-list` conmutaba a `DejaVu Sans`.
   - *Solución Implementada (v3.2):* `assets/fonts/Montserrat-ExtraBold.ttf` viene empaquetada localmente y `_obtener_fuente_y_dir_subtitulos()` pasa su familia exacta (`Montserrat ExtraBold`) junto con `:fontsdir=` directamente al filtro `subtitles` de `libass`.

### 7.3 Roadmap de Escalamiento
1. **Detección Automática de Caras (Auto-Tracking Facial 9:16):** Integrar MediaPipe o YOLO para recortar dinámicamente la cámara del streamer en streams 16:9 en lugar de forzar letterboxing con fondo desenfocado.
2. **Publicación Nativa en TikTok e Instagram Reels:** Integrar las APIs oficiales de TikTok for Developers y Meta Graph API para distribución omnicanal con un solo clic.
3. **B-Rolls y Memes Dinámicos:** Conectar con librerías de memes y sonidos en picos de silencio o remates cómicos detectados por Gemini.

---

## 8. Apéndice de Código Crítico de Referencia (v3.2)

A continuación se incluyen los bloques de código fuente verificados (v3.2) de las rutinas núcleo de `pipeline_viral_clips.py`:

### 8.1 Extracción de Audio y Telemetría de Red (`_emitir_telemetria`, `_ejecutar_descarga_con_telemetria`, `extraer_audio`)
```python
def _emitir_telemetria(
    on_telemetria: Optional[Callable[[Dict[str, Any]], None]],
    ultimo_ts_ref: List[float],
    datos: Dict[str, Any],
    forzar: bool = False,
    min_intervalo: float = 0.33,
) -> None:
    """Invoca callback de telemetría respetando el límite de ~3 actualizaciones/seg salvo hitos forzados."""
    if on_telemetria is None:
        return
    ahora = time.monotonic()
    if not forzar and (ahora - ultimo_ts_ref[0]) < min_intervalo:
        return
    ultimo_ts_ref[0] = ahora
    try:
        on_telemetria(dict(datos))
    except Exception:
        pass


def _cerrar_pipes_proceso(proc: Any) -> None:
    """Cierra los pipes stdout/stderr de Popen de forma segura para evitar ResourceWarning."""
    for attr in ("stdout", "stderr"):
        stream = getattr(proc, attr, None)
        if stream is not None:
            try:
                stream.close()
            except Exception:
                pass


def _ejecutar_descarga_con_telemetria(
    comando: List[str],
    on_telemetria: Optional[Callable[[Dict[str, Any]], None]],
    etapa: str,
    titulo_etapa: str,
    detalle_default: str,
) -> str:
    """Ejecuta yt-dlp con Popen leyendo línea a línea y emitiendo telemetría en vivo."""
    proc = subprocess.Popen(
        comando,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,
    )
    ultimas_lineas: List[str] = []
    ultimo_ts = [0.0]

    try:
        if proc.stdout is not None:
            for linea_raw in iter(proc.stdout.readline, ""):
                linea = linea_raw.rstrip("\r\n")
                if linea:
                    ultimas_lineas.append(linea)
                    if len(ultimas_lineas) > 60:
                        ultimas_lineas.pop(0)
                    if on_telemetria is None:
                        print(linea)

                parsed = _parsear_linea_progreso_descarga(linea)
                if parsed and on_telemetria is not None:
                    frag_cur = parsed.get("frag_cur")
                    frag_tot = parsed.get("frag_tot")
                    detalle = (
                        f"Fragmentos {frag_cur}/{frag_tot}"
                        if frag_cur and frag_tot
                        else detalle_default
                    )
                    pct = float(parsed["porcentaje"])
                    _emitir_telemetria(
                        on_telemetria,
                        ultimo_ts,
                        {
                            "etapa": etapa,
                            "titulo_etapa": titulo_etapa,
                            "porcentaje": pct,
                            "velocidad_red": parsed["velocidad_red"],
                            "tamano_total": parsed["tamano_total"],
                            "eta": parsed["eta"],
                            "detalle": detalle,
                        },
                        forzar=(pct >= 100.0),
                    )

        returncode = proc.wait()
    finally:
        if getattr(proc, "poll", lambda: 0)() is None:
            try:
                proc.kill()
                proc.wait(timeout=2.0)
            except Exception:
                pass
        _cerrar_pipes_proceso(proc)

    salida_txt = "\n".join(ultimas_lineas)
    if returncode != 0:
        raise subprocess.CalledProcessError(returncode, comando, output=salida_txt, stderr=salida_txt)
    return salida_txt


def extraer_audio(
    url: str,
    job_dir: Optional[Path | str] = None,
    on_telemetria: Optional[Callable[[Dict[str, Any]], None]] = None,
    on_log: Optional[Callable[[str], None]] = None,
) -> str:
    """Extrae audio mono 16kHz/32k mediante descarga paralela yt-dlp (--newline) y fallback FFmpeg streaming."""
    def _log(msg: str) -> None:
        if on_log is not None:
            on_log(msg)
        else:
            print(msg)

    _log("\n[1/4] Extrayendo audio para análisis con IA...")
    directorio = Path(job_dir).resolve() if job_dir else BASE_DIR
    directorio.mkdir(parents=True, exist_ok=True)

    audio_salida = directorio / "temp_audio.mp3"
    for patron in (str(directorio / "temp_audio.*"), str(directorio / "temp_audio_chunk_*.mp3")):
        for viejo in glob.glob(patron):
            try:
                os.remove(viejo)
            except OSError:
                pass

    # Intento primario: descarga paralela agresiva con yt-dlp (--concurrent-fragments 16 y aria2c opcional)
    salida_template = str(directorio / "temp_audio.%(ext)s")
    comando_primario = [
        sys.executable,
        "-m",
        "yt_dlp",
        "--newline",
        "--progress",
        "--js-runtimes",
        "node",
        "--remote-components",
        "ejs:github",
        "--no-playlist",
        "--force-overwrites",
        "--concurrent-fragments",
        "16",
        "--retries",
        "10",
        "--fragment-retries",
        "10",
        "--retry-sleep",
        "fragment:exp=1:10",
        "--socket-timeout",
        "15",
        "--buffer-size",
        "16K",
        "--http-chunk-size",
        "10M",
    ]
    if shutil.which("aria2c") and not _es_stream_hls_kick_o_twitch(url):
        comando_primario.extend(
            [
                "--downloader",
                "aria2c",
                "--downloader-args",
                "aria2c:-x 16 -s 16 -k 1M",
            ]
        )
    comando_primario.extend(
        [
            "-f",
            FORMATOS_AUDIO_DIRECTO,
            "-x",
            "--audio-format",
            "mp3",
            "--postprocessor-args",
            "ffmpeg:-vn -ac 1 -ar 16000 -b:a 32k",
            "-o",
            salida_template,
            url,
        ]
    )

    try:
        _log("Descargando y extrayendo audio en paralelo con yt-dlp (16 hilos)...")
        _emitir_telemetria(
            on_telemetria,
            [0.0],
            {
                "etapa": "descarga",
                "titulo_etapa": "Descargando Audio del Stream (16 Hilos)",
                "porcentaje": 0.0,
                "velocidad_red": "--",
                "tamano_total": "--",
                "eta": "--:--",
                "detalle": "Conectando con servidor fuente...",
            },
            forzar=True,
        )
        _ejecutar_descarga_con_telemetria(
            comando_primario,
            on_telemetria=on_telemetria,
            etapa="descarga",
            titulo_etapa="Descargando Audio del Stream (16 Hilos)",
            detalle_default="Descarga paralela activa",
        )
        if audio_salida.exists() and audio_salida.stat().st_size > 10_240:
            _emitir_telemetria(
                on_telemetria,
                [0.0],
                {
                    "etapa": "descarga",
                    "titulo_etapa": "Audio Extraído con Éxito",
                    "porcentaje": 100.0,
                    "velocidad_red": "Completado",
                    "tamano_total": f"{audio_salida.stat().st_size / (1024 * 1024):.2f}MiB",
                    "eta": "00:00",
                    "detalle": "Pista de audio lista para IA",
                },
                forzar=True,
            )
            return str(audio_salida.resolve())
        tam = audio_salida.stat().st_size if audio_salida.exists() else 0
        raise RuntimeError(
            f"El archivo generado por yt-dlp es demasiado pequeño o inválido ({tam} bytes <= 10 KB)."
        )
    except Exception as e:
        _log(
            f"[AVISO] Extracción paralela con yt-dlp falló ({e}); "
            "activando fallback automático con streaming directo FFmpeg..."
        )
        for resto in glob.glob(str(directorio / "temp_audio.*")):
            try:
                os.remove(resto)
            except OSError:
                pass

    # Fallback automático: streaming directo FFmpeg con reconexión
    _log("Consultando URL directa de audio/menor resolución con yt-dlp -g...")
    stream_url = _obtener_url_audio_directo(url)
    comando_ffmpeg = [
        "ffmpeg",
        "-hide_banner",
        "-loglevel",
        "warning",
        "-progress",
        "pipe:1",
        "-nostats",
        "-y",
    ]
    if stream_url.startswith(("http://", "https://")):
        comando_ffmpeg.extend(
            [
                "-reconnect",
                "1",
                "-reconnect_streamed",
                "1",
                "-reconnect_delay_max",
                "5",
                "-rw_timeout",
                "15000000",
            ]
        )
    comando_ffmpeg.extend(
        [
            "-i",
            stream_url,
            "-vn",
            "-ac",
            "1",
            "-ar",
            "16000",
            "-b:a",
            "32k",
            str(audio_salida),
        ]
    )
    _log("Extrayendo pista de audio directa por streaming con FFmpeg...")

    def _on_prog_ffmpeg_audio(prog: Dict[str, Any]) -> None:
        if on_telemetria is None:
            return
        on_telemetria(
            {
                "etapa": "descarga",
                "titulo_etapa": "Extrayendo Audio (Fallback FFmpeg Streaming)",
                "porcentaje": prog["porcentaje"],
                "velocidad_red": prog["speed_str"],
                "tamano_total": prog.get("size_str", "--"),
                "eta": prog["eta_str"],
                "velocidad_x": prog["speed_str"],
                "detalle": f"Streaming directo FFmpeg • t={prog['out_time_str']}",
            }
        )

    _ejecutar_comando_con_captura(
        comando_ffmpeg,
        duracion_objetivo=None,
        on_progreso=_on_prog_ffmpeg_audio if on_telemetria is not None else None,
    )
    if not audio_salida.exists() or audio_salida.stat().st_size <= 0:
        raise FileNotFoundError(f"No se generó el archivo de audio esperado: {audio_salida}")
    return str(audio_salida.resolve())
```

### 8.2 Curaduría y Análisis IA con Gemini (`analizar_con_gemini`)
```python
def analizar_con_gemini(
    ruta_audio: str | Path,
    duracion_total: Optional[float] = None,
    modelo_preferido: Optional[str] = None,
    job_dir: Optional[Path | str] = None,
    on_log: Optional[Callable[[str], None]] = None,
    on_telemetria: Optional[Callable[[Dict[str, Any]], None]] = None,
) -> List[dict]:
    """Segmenta audios largos (>55 min) si aplica, sube a Gemini File API, consolida offsets y guarda clips.json."""
    def _log(msg: str) -> None:
        if on_log is not None:
            on_log(msg)
        else:
            print(msg)

    _log("\n[2/4] Subiendo audio a Gemini y ejecutando análisis viral con IA...")
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        raise RuntimeError("Falta la variable de entorno GEMINI_API_KEY.")

    client = genai.Client(
        api_key=api_key,
        http_options={"timeout": GEMINI_TIMEOUT_MS},
    )

    duracion_efectiva: Optional[float] = (
        float(duracion_total)
        if duracion_total is not None
        else obtener_duracion_media(ruta_audio)
    )

    modelo_label = (modelo_preferido or MODELOS_CANDIDATOS[0]).strip()
    _emitir_telemetria(
        on_telemetria,
        [0.0],
        {
            "etapa": "gemini",
            "titulo_etapa": f"Preparando Análisis IA ({modelo_label})",
            "porcentaje": 0.0,
            "bloque_actual": 1,
            "total_bloques": 1,
            "modelo_ia": modelo_label,
            "eta": "--:--",
            "detalle": "Evaluando duración de pista para segmentación...",
        },
        forzar=True,
    )

    chunks_temporales: List[str] = []
    try:
        if duracion_efectiva is not None:
            chunks = _segmentar_audio_en_chunks(ruta_audio, duracion_efectiva)
        else:
            chunks = [(str(ruta_audio), 0.0, None)]

        chunks_temporales = [
            ruta_c
            for ruta_c, _, _ in chunks
            if str(ruta_c) != str(ruta_audio) and Path(ruta_c).name.startswith("temp_audio_chunk_")
        ]

        if len(chunks) > 1 and duracion_efectiva is not None:
            _log(
                f"Audio de {segundos_a_hhmmss(duracion_efectiva)} (> 55 min): "
                f"segmentando en {len(chunks)} bloques de hasta 45 min con 90s de solapamiento..."
            )

        clips_acumulados: List[dict] = []
        ultimo_error: Optional[Exception] = None
        total_bloques = len(chunks)
        acepta_tele = _acepta_kwarg(_analizar_archivo_audio_gemini, "on_telemetria")

        for idx_chunk, (ruta_chunk, offset_seg, dur_chunk) in enumerate(chunks, start=1):
            if len(chunks) > 1 and dur_chunk is not None:
                _log(
                    f"Analizando bloque {idx_chunk}/{total_bloques} "
                    f"[{segundos_a_hhmmss(offset_seg)} -> {segundos_a_hhmmss(offset_seg + dur_chunk)}]..."
                )
            _emitir_telemetria(
                on_telemetria,
                [0.0],
                {
                    "etapa": "gemini",
                    "titulo_etapa": f"Analizando Narrativa Viral ({modelo_label})",
                    "porcentaje": round(((idx_chunk - 1) / max(1, total_bloques)) * 100.0, 1),
                    "bloque_actual": idx_chunk,
                    "total_bloques": total_bloques,
                    "modelo_ia": modelo_label,
                    "eta": "--:--",
                    "detalle": (
                        f"Bloque {idx_chunk}/{total_bloques}"
                        + (
                            f" [{segundos_a_hhmmss(offset_seg)} → {segundos_a_hhmmss(offset_seg + dur_chunk)}]"
                            if dur_chunk is not None
                            else ""
                        )
                    ),
                },
                forzar=True,
            )
            try:
                if acepta_tele:
                    clips_chunk = _analizar_archivo_audio_gemini(
                        client,
                        ruta_chunk,
                        dur_chunk,
                        modelo_preferido,
                        _log,
                        on_telemetria=on_telemetria,
                        bloque_actual=idx_chunk,
                        total_bloques=total_bloques,
                    )
                else:
                    clips_chunk = _analizar_archivo_audio_gemini(
                        client,
                        ruta_chunk,
                        dur_chunk,
                        modelo_preferido,
                        _log,
                    )
            except Exception as e_chunk:
                ultimo_error = e_chunk
                if len(chunks) == 1:
                    raise
                _log(f"[AVISO] Falló análisis del bloque {idx_chunk}/{total_bloques}: {e_chunk}")
                continue

            if not acepta_tele:
                _emitir_telemetria(
                    on_telemetria,
                    [0.0],
                    {
                        "etapa": "gemini",
                        "titulo_etapa": f"Analizando Narrativa Viral ({modelo_label})",
                        "porcentaje": round((idx_chunk / max(1, total_bloques)) * 100.0, 1),
                        "bloque_actual": idx_chunk,
                        "total_bloques": total_bloques,
                        "modelo_ia": modelo_label,
                        "eta": "--:--",
                        "detalle": f"Bloque {idx_chunk}/{total_bloques} completado ({len(clips_chunk)} clips)",
                    },
                    forzar=True,
                )

            for clip in clips_chunk:
                try:
                    ini_abs = max(0.0, hhmmss_a_segundos(clip["inicio"]) + offset_seg)
                    fin_abs = max(0.0, hhmmss_a_segundos(clip["fin"]) + offset_seg)
                except (KeyError, ValueError, TypeError):
                    continue

                if duracion_efectiva is not None:
                    if ini_abs >= duracion_efectiva - 2:
                        continue
                    fin_abs = min(fin_abs, duracion_efectiva)

                dur_clip_abs = fin_abs - ini_abs
                if dur_clip_abs < 5:
                    continue

                clip_ajustado = dict(clip)
                clip_ajustado["inicio"] = segundos_a_hhmmss(ini_abs)
                clip_ajustado["fin"] = segundos_a_hhmmss(fin_abs)
                dur_normalizada = max(
                    0.0,
                    hhmmss_a_segundos(clip_ajustado["fin"]) - hhmmss_a_segundos(clip_ajustado["inicio"]),
                )
                clip_ajustado["duracion_segundos"] = int(round(dur_normalizada))
                # Subtítulos usan inicio_rel/fin_rel respecto al clip; NO sumar offset_seg del stream
                subs_validados = _normalizar_subtitulos(
                    clip_ajustado.get("subtitulos"), dur_normalizada
                )
                clip_ajustado["subtitulos"] = [s.model_dump() for s in subs_validados]
                clips_acumulados.append(clip_ajustado)

        clips_finales = _deduplicar_clips_solapados(clips_acumulados)
        if not clips_finales:
            if ultimo_error is not None:
                raise ultimo_error
            raise RuntimeError("No se detectaron clips virales válidos en ninguno de los bloques del audio.")

        _guardar_y_sincronizar_clips(clips_finales, job_dir=job_dir)
        _log(f"✓ Se detectaron {len(clips_finales)} momentos virales con SEO completo y se guardaron en clips.json")
        return clips_finales
    finally:
        for ruta_c in chunks_temporales:
            try:
                if os.path.exists(ruta_c):
                    os.remove(ruta_c)
            except OSError:
                pass
        carpeta_audio = Path(ruta_audio).resolve().parent
        for resto_chunk in glob.glob(str(carpeta_audio / "temp_audio_chunk_*.mp3")):
            if str(resto_chunk) != str(Path(ruta_audio).resolve()):
                try:
                    os.remove(resto_chunk)
                except OSError:
                    pass
```

### 8.3 Tipografía Embebida y Subtítulos ASS (`_limpiar_texto_ass`, `_obtener_fuente_y_dir_subtitulos`, `generar_archivo_ass`)
```python
def _limpiar_texto_ass(texto: str) -> str:
    """Normaliza texto en MAYÚSCULAS para Dialogue ASS evitando llaves, saltos crudos y emojis sin glifo."""
    limpio = _REGEX_EMOJIS_ASS.sub("", str(texto or ""))
    limpio = re.sub(r"\r\n|\r|\n", r"\\N", limpio)
    limpio = re.sub(r"[ \t\f\v]+", " ", limpio).strip()
    limpio = limpio.replace("{", "(").replace("}", ")")
    return limpio.upper()


def _inferir_nombre_fuente_por_archivo(ruta_fuente: Path) -> str:
    """Infiere un nombre legible de familia a partir del nombre de archivo .ttf/.otf."""
    stem = re.sub(r"\[.*?\]", "", ruta_fuente.stem)
    limpio = re.sub(r"[-_]+", " ", stem).strip()
    return limpio or "Montserrat ExtraBold"


def _obtener_fuente_y_dir_subtitulos() -> Tuple[str, Optional[str]]:
    """Obtiene (nombre_familia_libass, fonts_dir) desde assets/fonts/ o fallback del sistema."""
    try:
        if CARPETA_FUENTES.exists() and CARPETA_FUENTES.is_dir():
            candidatos = [
                p
                for p in CARPETA_FUENTES.iterdir()
                if p.is_file() and p.suffix.lower() in (".ttf", ".otf") and p.stat().st_size > 0
            ]
            if candidatos:
                candidatos.sort(
                    key=lambda p: (
                        0
                        if "extrabold" in p.name.lower()
                        else (1 if "black" in p.name.lower() else (2 if "bold" in p.name.lower() else 3)),
                        p.name.lower(),
                    )
                )
                ruta_elegida = candidatos[0]
                nombre_familia: Optional[str] = None
                if shutil.which("fc-scan"):
                    try:
                        res = subprocess.run(
                            ["fc-scan", "--format", "%{fullname[0]}\n%{family}\n", str(ruta_elegida)],
                            capture_output=True,
                            text=True,
                            check=True,
                            timeout=5,
                        )
                        lineas = [ln.strip() for ln in res.stdout.splitlines() if ln.strip()]
                        fullname = lineas[0] if len(lineas) >= 1 else ""
                        familias = (
                            [f.strip() for f in lineas[1].split(",") if f.strip()]
                            if len(lineas) >= 2
                            else []
                        )
                        if fullname and fullname in familias:
                            nombre_familia = fullname
                        else:
                            for fam in familias:
                                if any(tag in fam.lower() for tag in ("extrabold", "black", "bold")):
                                    nombre_familia = fam
                                    break
                            if not nombre_familia and familias:
                                nombre_familia = familias[0]
                            elif not nombre_familia and fullname:
                                nombre_familia = fullname
                    except Exception:
                        nombre_familia = None

                if not nombre_familia:
                    nombre_familia = _inferir_nombre_fuente_por_archivo(ruta_elegida)
                return nombre_familia, str(CARPETA_FUENTES.resolve())
    except Exception:
        pass
    return _detectar_fuente_subtitulos(), None


def generar_archivo_ass(
    subtitulos: List[Any],
    ruta_ass: str | Path,
) -> str:
    """Genera un archivo .ass v3.2 estilizado en tercio medio-inferior (1080x1920) y devuelve su ruta absoluta."""
    ruta = Path(ruta_ass).resolve()
    ruta.parent.mkdir(parents=True, exist_ok=True)
    fuente_sub, _ = _obtener_fuente_y_dir_subtitulos()

    encabezado = "\n".join(
        [
            "[Script Info]",
            "Title: Kicksazos Shorts Subtitles",
            "ScriptType: v4.00+",
            "WrapStyle: 2",
            "ScaledBorderAndShadow: yes",
            "YCbCr Matrix: TV.709",
            "PlayResX: 1080",
            "PlayResY: 1920",
            "",
            "[V4+ Styles]",
            "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding",
            f"Style: Default,{fuente_sub},54,&H00FFFFFF,&H0000FFFF,&H00000000,&HA0000000,-1,0,0,0,100,100,1.5,0,1,5.5,3.5,2,65,210,550,1",
            "",
            "[Events]",
            "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text",
        ]
    )

    lineas_eventos: List[str] = []
    for seg in subtitulos or []:
        if isinstance(seg, SegmentoSubtitulo):
            ini_raw, fin_raw, txt_raw = seg.inicio_rel, seg.fin_rel, seg.texto
        elif isinstance(seg, dict):
            ini_raw = seg.get("inicio_rel")
            fin_raw = seg.get("fin_rel")
            txt_raw = seg.get("texto")
        else:
            continue

        try:
            ini = max(0.0, float(ini_raw))
            fin = float(fin_raw)
        except (TypeError, ValueError):
            continue

        texto_ass = _limpiar_texto_ass(str(txt_raw or ""))
        if not texto_ass or fin <= ini + 0.02:
            continue

        t_ini = _segundos_a_ass_time(ini)
        t_fin = _segundos_a_ass_time(fin)
        lineas_eventos.append(
            f"Dialogue: 0,{t_ini},{t_fin},Default,,0,0,0,,{_ANIMACION_POPIN_ASS}{texto_ass}"
        )

    contenido = encabezado + ("\n" + "\n".join(lineas_eventos) if lineas_eventos else "") + "\n"
    ruta.write_text(contenido, encoding="utf-8")
    return str(ruta)
```

### 8.4 Renderizado 9:16 y Telemetría FFmpeg (`_construir_comando_render`, `procesar_clip_ffmpeg`)

El comando FFmpeg inyecta `-progress pipe:1 -nostats` (capturado y parseado línea a línea por `_ejecutar_comando_con_captura()` y `_parsear_tiempo_ffmpeg()` usando `out_time_us`, `frame`, `fps`, `speed`, `total_size` y ETA throttled a ≤ 3 Hz con `_cerrar_pipes_proceso()` en `finally`) además de `:fontsdir='...'` en el filtro `subtitles`.

```python
def _construir_comando_render(
    entradas_media: List[str],
    es_remoto: bool,
    inicio: str,
    duracion_str: str,
    archivo_salida: Path,
    y_watermark: str,
    encoder: str,
    ruta_ass: Optional[str] = None,
    fonts_dir: Optional[str] = None,
) -> List[str]:
    """Construye el comando FFmpeg 9:16 con encoder VAAPI/CPU, watermark adaptativa, fontsdir y -progress pipe:1."""
    comando = [
        "ffmpeg",
        "-hide_banner",
        "-loglevel",
        "warning",
        "-progress",
        "pipe:1",
        "-nostats",
        "-y",
    ]
    if encoder == "h264_vaapi":
        comando.extend(["-vaapi_device", VAAPI_DEVICE])

    for media in entradas_media:
        if es_remoto:
            comando.extend(
                [
                    "-rw_timeout",
                    "15000000",
                    "-reconnect",
                    "1",
                    "-reconnect_streamed",
                    "1",
                    "-reconnect_delay_max",
                    "5",
                ]
            )
        comando.extend(["-ss", inicio, "-t", duracion_str, "-i", media])

    idx_watermark = len(entradas_media)
    idx_audio = "1:a?" if len(entradas_media) > 1 else "0:a?"
    comando.extend(["-i", str(RUTA_MARCA_AGUA)])

    partes_filtro = [
        "[0:v]split=2[bg][fg]",
        "[bg]scale=360:640:force_original_aspect_ratio=increase,crop=360:640,setsar=1,boxblur=10:2,scale=1080:1920:flags=bilinear[bg_blur]",
        "[fg]scale=1080:1920:force_original_aspect_ratio=decrease,setsar=1[fg_scaled]",
        "[bg_blur][fg_scaled]overlay=(W-w)/2:(H-h)/2[vid_comp]",
        f"[{idx_watermark}:v]scale=420:-1,format=rgba,colorchannelmixer=aa=0.92[wm]",
    ]

    cadena_final = [f"[vid_comp][wm]overlay=(W-w)/2:{y_watermark}"]
    if ruta_ass:
        ruta_esc = _escapar_ruta_ffmpeg_filtro(ruta_ass)
        if fonts_dir:
            fonts_esc = _escapar_ruta_ffmpeg_filtro(fonts_dir)
            cadena_final.append(f"subtitles='{ruta_esc}':fontsdir='{fonts_esc}'")
        else:
            cadena_final.append(f"subtitles='{ruta_esc}'")
    if encoder == "h264_vaapi":
        cadena_final.append("format=nv12,hwupload[outv]")
    else:
        cadena_final.append("format=yuv420p[outv]")
    partes_filtro.append(",".join(cadena_final))
    filtro = ";".join(partes_filtro)

    comando.extend(
        [
            "-filter_complex",
            filtro,
            "-map",
            "[outv]",
            "-map",
            idx_audio,
            "-t",
            duracion_str,
        ]
    )

    if encoder == "h264_vaapi":
        comando.extend(["-c:v", "h264_vaapi", "-qp", "23"])
    else:
        comando.extend(
            [
                "-c:v",
                "libx264",
                "-preset",
                "veryfast",
                "-crf",
                "22",
                "-threads",
                "0",
            ]
        )

    comando.extend(
        [
            "-c:a",
            "aac",
            "-b:a",
            "128k",
            "-movflags",
            "+faststart",
            str(archivo_salida),
        ]
    )
    return comando


def procesar_clip_ffmpeg(
    url_o_archivo: str,
    inicio: str,
    fin: str,
    id_clip: str | int,
    job_id: Optional[str] = None,
    subtitulos: Optional[List[Any]] = None,
    job_dir: Optional[Path | str] = None,
    on_telemetria: Optional[Callable[[Dict[str, Any]], None]] = None,
    clip_indice: Optional[int] = None,
    total_clips: Optional[int] = None,
    on_log: Optional[Callable[[str], None]] = None,
) -> str:
    """Extrae el clip con input seek (-ss) y corte exacto (-t), renderiza 9:16 por VAAPI/CPU, watermark adaptativa y .ass con telemetría."""
    def _log(msg: str) -> None:
        if on_log is not None:
            on_log(msg)
        else:
            print(msg)

    if not RUTA_MARCA_AGUA.exists():
        raise FileNotFoundError(f"No se encontró la marca de agua en {RUTA_MARCA_AGUA}")

    duracion_clip = hhmmss_a_segundos(fin) - hhmmss_a_segundos(inicio)
    if duracion_clip <= 0:
        raise ValueError(f"Duración de clip inválida ({inicio} -> {fin}).")
    duracion_str = f"{duracion_clip:.3f}"

    CARPETA_SALIDA.mkdir(parents=True, exist_ok=True)
    nombre_clip = f"{job_id}_clip_{id_clip}.mp4" if job_id else f"clip_{id_clip}.mp4"
    archivo_salida = CARPETA_SALIDA / nombre_clip

    _log(
        f"\n--- Procesando Clip {id_clip} ({inicio} -> {fin}, t={duracion_str}s) "
        f"[Salida: {nombre_clip}] ---"
    )

    ruta_ass = _preparar_archivo_ass_clip(
        subtitulos=subtitulos,
        id_clip=id_clip,
        duracion_clip=duracion_clip,
        job_id=job_id,
        job_dir=job_dir,
    )
    fuente_sub, fonts_dir_sub = _obtener_fuente_y_dir_subtitulos()
    if ruta_ass:
        _log(
            f"✓ Subtítulos dinámicos generados en: {ruta_ass} "
            f"[fuente={fuente_sub}, fontsdir={fonts_dir_sub or 'sistema'}]"
        )

    clave_cache = job_id or f"anon:{url_o_archivo}"
    if os.path.exists(url_o_archivo):
        entradas_media = [str(Path(url_o_archivo).resolve())]
        es_remoto = False
        dimensiones = obtener_dimensiones_video(entradas_media[0])
    else:
        entradas_media = obtener_urls_stream(url_o_archivo, job_id=job_id)
        es_remoto = True
        entrada_cache = STREAM_URL_CACHE.obtener(clave_cache, url_o_archivo)
        dimensiones = entrada_cache.get("dimensiones") if entrada_cache else None
        if dimensiones is None:
            dimensiones = obtener_dimensiones_video(entradas_media[0])
            STREAM_URL_CACHE.actualizar_dimensiones(clave_cache, url_o_archivo, dimensiones)

    y_watermark = _calcular_y_watermark(dimensiones)
    encoder_activo = detectar_encoder_hardware()
    ruta_ass_activa = ruta_ass
    url_refrescada = False
    etiqueta_clip = f"Renderizando Clip #{id_clip}" + (
        f" ({clip_indice}/{total_clips})" if clip_indice and total_clips else ""
    )

    while True:
        comando_ffmpeg = _construir_comando_render(
            entradas_media=entradas_media,
            es_remoto=es_remoto,
            inicio=inicio,
            duracion_str=duracion_str,
            archivo_salida=archivo_salida,
            y_watermark=y_watermark,
            encoder=encoder_activo,
            ruta_ass=ruta_ass_activa,
            fonts_dir=fonts_dir_sub if ruta_ass_activa else None,
        )
        _log(
            f"Renderizando composición 9:16 con FFmpeg [encoder={encoder_activo}, "
            f"wm_y={y_watermark}, subs={'sí' if ruta_ass_activa else 'no'}]..."
        )
        _emitir_telemetria(
            on_telemetria,
            [0.0],
            {
                "etapa": "render",
                "titulo_etapa": etiqueta_clip,
                "porcentaje": 0.0,
                "fps": "--",
                "velocidad_x": "--",
                "eta": "--:--",
                "encoder": encoder_activo,
                "clip_id": str(id_clip),
                "clip_indice": clip_indice,
                "total_clips": total_clips,
                "frame": 0,
                "out_time": "00:00:00",
                "duracion_clip": duracion_clip,
                "detalle": f"Iniciando render {encoder_activo}...",
            },
            forzar=True,
        )

        def _on_prog_ffmpeg(prog: Dict[str, Any]) -> None:
            if on_telemetria is None:
                return
            on_telemetria(
                {
                    "etapa": "render",
                    "titulo_etapa": etiqueta_clip,
                    "porcentaje": prog["porcentaje"],
                    "fps": prog["fps_str"],
                    "velocidad_x": prog["speed_str"],
                    "eta": prog["eta_str"],
                    "encoder": encoder_activo,
                    "clip_id": str(id_clip),
                    "clip_indice": clip_indice,
                    "total_clips": total_clips,
                    "frame": prog["frame"],
                    "out_time": prog["out_time_str"],
                    "duracion_clip": duracion_clip,
                    "detalle": (
                        f"Encoder {encoder_activo} • {prog['fps_str']} fps • "
                        f"{prog['speed_str']} • ETA {prog['eta_str']}"
                    ),
                }
            )

        try:
            _ejecutar_comando_con_captura(
                comando_ffmpeg,
                duracion_objetivo=duracion_clip,
                on_progreso=_on_prog_ffmpeg if on_telemetria is not None else None,
            )
            break
        except subprocess.CalledProcessError as err:
            if archivo_salida.exists():
                try:
                    archivo_salida.unlink()
                except OSError:
                    pass

            stderr_txt = err.stderr or err.output or ""

            if es_remoto and not url_refrescada and _es_error_http_expiracion(stderr_txt):
                _log(
                    "[AVISO] Error HTTP 403/410 detectado en stream; "
                    "invalidando caché y re-obteniendo URLs..."
                )
                STREAM_URL_CACHE.invalidar(clave_cache)
                entradas_media = obtener_urls_stream(
                    url_o_archivo, job_id=job_id, forzar_recarga=True
                )
                dimensiones = obtener_dimensiones_video(entradas_media[0])
                STREAM_URL_CACHE.actualizar_dimensiones(clave_cache, url_o_archivo, dimensiones)
                y_watermark = _calcular_y_watermark(dimensiones)
                url_refrescada = True
                continue

            if ruta_ass_activa and re.search(
                r"Parsed_subtitles|subtitles|libass|\.ass", stderr_txt, re.IGNORECASE
            ):
                _log(
                    "[AVISO] El filtro de subtítulos .ass falló; "
                    "reintentando render del clip sin subtítulos..."
                )
                ruta_ass_activa = None
                continue

            if encoder_activo == "h264_vaapi":
                _log(
                    "[AVISO] Renderizado VAAPI falló en ejecución; "
                    "reintentando automáticamente con CPU (libx264)..."
                )
                encoder_activo = "libx264"
                continue

            if ruta_ass_activa:
                _log(
                    "[AVISO] Renderizado falló con subtítulos activos; "
                    "reintentando sin subtítulos..."
                )
                ruta_ass_activa = None
                continue

            raise

    _log(f"✓ Clip {id_clip} guardado con éxito en: {archivo_salida}")
    return str(archivo_salida.resolve())
```

### 8.5 Orquestador Completo, Puente de Telemetría y Barra CLI (`_ejecutar_paso_con_telemetria`, `ejecutar_pipeline_completo`, `RenderizadorProgresoCLI`)
```python
def _ejecutar_paso_con_telemetria(
    fn: Callable[..., Any],
    *args: Any,
    construir_estado: Callable[[Dict[str, Any]], Dict[str, Any]],
    on_telemetria_externa: Optional[Callable[[Dict[str, Any]], None]] = None,
    **kwargs: Any,
) -> Generator[Dict[str, Any], None, Any]:
    """Ejecuta una etapa bloqueante en hilo worker re-emitiendo su telemetría en vivo por el generador."""
    cola: queue.Queue[Tuple[str, Any]] = queue.Queue()
    acepta_tele = _acepta_kwarg(fn, "on_telemetria")

    def _cb_tele(datos: Dict[str, Any]) -> None:
        copia = dict(datos or {})
        if on_telemetria_externa is not None:
            try:
                on_telemetria_externa(copia)
            except Exception:
                pass
        cola.put(("tele", copia))

    def _worker() -> None:
        try:
            call_kwargs = dict(kwargs)
            if acepta_tele:
                call_kwargs["on_telemetria"] = _cb_tele
            res = fn(*args, **call_kwargs)
            cola.put(("ok", res))
        except BaseException as exc:
            cola.put(("err", exc))

    hilo = threading.Thread(target=_worker, daemon=True)
    hilo.start()
    while True:
        tipo, payload = cola.get()
        if tipo == "tele":
            yield construir_estado(payload)
        elif tipo == "ok":
            hilo.join(timeout=1.0)
            return payload
        elif tipo == "err":
            hilo.join(timeout=1.0)
            raise payload


def ejecutar_pipeline_completo(
    url: str,
    modelo_preferido: Optional[str] = None,
    solo_analisis: bool = False,
    subir_youtube: bool = True,
    publish_at_inicio: Optional[str] = None,
    intervalo_horas: int | float = 0,
    on_log: Optional[Callable[[str], None]] = None,
    on_telemetria: Optional[Callable[[Dict[str, Any]], None]] = None,
) -> Generator[Dict[str, Any], None, None]:
    """Orquestador único (CLI y GUI) que ejecuta el pipeline completo y emite diccionarios de estado con telemetría."""
    def _log(msg: str) -> None:
        if on_log is not None:
            on_log(msg)
        else:
            print(msg)

    url_limpia = (url or "").strip()
    if not url_limpia:
        msg = "Por favor ingresa una URL válida de Kick, YouTube o Twitch."
        _log(f"[ERROR] {msg}")
        yield _emitir_estado("error", 0.0, msg, error=msg)
        return

    if not os.environ.get("GEMINI_API_KEY"):
        msg = "Falta GEMINI_API_KEY en el archivo .env o en las variables de entorno."
        _log(f"[ERROR] {msg}")
        yield _emitir_estado("error", 0.0, msg, error=msg)
        return

    if subir_youtube and not solo_analisis and publish_at_inicio and str(publish_at_inicio).strip():
        try:
            calcular_publish_at_utc(
                publish_at_inicio,
                indice_clip=0,
                intervalo_horas=intervalo_horas,
            )
        except ValueError as e_fecha:
            msg = str(e_fecha)
            _log(f"[ERROR] {msg}")
            yield _emitir_estado("error", 0.0, msg, error=msg)
            return

    ctx = crear_contexto_job(url_limpia)
    job_dir_str = str(ctx.job_dir)
    _log(f"Iniciando Job {ctx.job_id} en {ctx.job_dir}")

    audio_temp: Optional[str] = None
    clips: List[dict] = []
    ultimo_video: Optional[str] = None

    try:
        _log(f"Fase 1/4: Extrayendo pista de audio desde {url_limpia}...")
        tele_audio_init = {
            "etapa": "descarga",
            "titulo_etapa": "Descargando Audio del Stream (16 Hilos)",
            "porcentaje": 0.0,
            "velocidad_red": "--",
            "tamano_total": "--",
            "eta": "--:--",
            "detalle": f"Preparando extracción en jobs/{ctx.job_id}",
        }
        if on_telemetria is not None:
            on_telemetria(dict(tele_audio_init))
        yield _emitir_estado(
            fase="audio",
            progreso=0.05,
            mensaje=f"Fase 1/4: Extrayendo audio ligero en jobs/{ctx.job_id}...",
            clips=clips,
            ultimo_video=ultimo_video,
            job_dir=job_dir_str,
            telemetria=tele_audio_init,
        )
        kwargs_audio: Dict[str, Any] = {"job_dir": ctx.job_dir}
        if _acepta_kwarg(extraer_audio, "on_log"):
            kwargs_audio["on_log"] = _log
        audio_temp = yield from _ejecutar_paso_con_telemetria(
            extraer_audio,
            url_limpia,
            construir_estado=lambda tele: _emitir_estado(
                fase="audio",
                progreso=0.05 + 0.23 * (float(tele.get("porcentaje", 0.0)) / 100.0),
                mensaje=(
                    f"Fase 1/4: {tele.get('titulo_etapa', 'Extrayendo audio')} "
                    f"({tele.get('porcentaje', 0):.1f}% • {tele.get('velocidad_red', '--')})"
                ),
                clips=clips,
                ultimo_video=ultimo_video,
                job_dir=job_dir_str,
                telemetria=tele,
            ),
            on_telemetria_externa=on_telemetria,
            **kwargs_audio,
        )
        duracion = obtener_duracion_media(audio_temp)
        dur_str = segundos_a_hhmmss(duracion) if duracion else "Desconocida"
        _log(f"✓ Audio extraído correctamente ({audio_temp}) | Duración: {dur_str}")

        modelo_label = (modelo_preferido or MODELOS_CANDIDATOS[0]).strip()
        tele_gemini_init = {
            "etapa": "gemini",
            "titulo_etapa": f"Analizando Narrativa Viral ({modelo_label})",
            "porcentaje": 0.0,
            "bloque_actual": 1,
            "total_bloques": 1,
            "modelo_ia": modelo_label,
            "eta": "--:--",
            "detalle": "Iniciando análisis de momentos virales...",
        }
        if on_telemetria is not None:
            on_telemetria(dict(tele_gemini_init))
        yield _emitir_estado(
            fase="gemini",
            progreso=0.30,
            mensaje=f"Fase 2/4: Analizando narrativa viral con {modelo_label}...",
            clips=clips,
            ultimo_video=ultimo_video,
            job_dir=job_dir_str,
            telemetria=tele_gemini_init,
        )
        clips = yield from _ejecutar_paso_con_telemetria(
            analizar_con_gemini,
            audio_temp,
            construir_estado=lambda tele: _emitir_estado(
                fase="gemini",
                progreso=0.30 + 0.24 * (float(tele.get("porcentaje", 0.0)) / 100.0),
                mensaje=(
                    f"Fase 2/4: {tele.get('titulo_etapa', 'Análisis Gemini')} "
                    f"[{tele.get('detalle', '')}]"
                ),
                clips=clips,
                ultimo_video=ultimo_video,
                job_dir=job_dir_str,
                telemetria=tele,
            ),
            on_telemetria_externa=on_telemetria,
            duracion_total=duracion,
            modelo_preferido=modelo_preferido,
            job_dir=ctx.job_dir,
            on_log=_log,
        )
        for c in clips:
            _log(
                f"  • Clip #{c['id']}: {c['titulo']} [{c['inicio']} -> {c['fin']}] | "
                f"Hook: {str(c.get('gancho', ''))[:45]}..."
            )

        if solo_analisis:
            msg_fin = (
                f"Análisis viral completado ({len(clips)} clips) en jobs/{ctx.job_id}/clips.json y clips.json."
            )
            _log(f"✓ {msg_fin}")
            tele_fin = {
                "etapa": "completado",
                "titulo_etapa": "Análisis Viral Completado",
                "porcentaje": 100.0,
                "eta": "00:00",
                "detalle": msg_fin,
            }
            if on_telemetria is not None:
                on_telemetria(dict(tele_fin))
            yield _emitir_estado(
                fase="completado",
                progreso=1.0,
                mensaje=msg_fin,
                clips=clips,
                ultimo_video=None,
                job_dir=job_dir_str,
                telemetria=tele_fin,
            )
            return

        # Fases 3 y 4: descarga fuente/render paralelo con telemetría + subida a YouTube Shorts
        for estado_lote in _orquestar_render_y_subida(
            url=url_limpia,
            clips=clips,
            duracion_total=duracion,
            subir_youtube=subir_youtube,
            job_id=ctx.job_id,
            job_dir=ctx.job_dir,
            publish_at_inicio=publish_at_inicio,
            intervalo_horas=intervalo_horas,
            on_log=_log,
            on_telemetria=on_telemetria,
        ):
            if estado_lote.get("ultimo_video"):
                ultimo_video = estado_lote["ultimo_video"]
            yield estado_lote

        render_ok = sum(1 for c in clips if c.get("render_status") == "OK")
        render_err = len(clips) - render_ok
        subidos_ok = sum(1 for c in clips if c.get("youtube_url"))
        msg_final = (
            f"Job {ctx.job_id}: {render_ok}/{len(clips)} clips renderizados en 9:16 "
            f"({subidos_ok} subidos a YouTube Shorts"
            + (f", {render_err} con error de render" if render_err else "")
            + ")."
        )
        _log(f"✓ {msg_final}")
        tele_done = {
            "etapa": "completado",
            "titulo_etapa": "Pipeline Completado",
            "porcentaje": 100.0,
            "eta": "00:00",
            "detalle": msg_final,
        }
        if on_telemetria is not None:
            on_telemetria(dict(tele_done))
        yield _emitir_estado(
            fase="completado",
            progreso=1.0,
            mensaje=msg_final,
            clips=clips,
            ultimo_video=ultimo_video,
            job_dir=job_dir_str,
            telemetria=tele_done,
        )
    except Exception as e:
        err_msg = str(e)
        _log(f"[ERROR] {err_msg}")
        tele_err = {
            "etapa": "error",
            "titulo_etapa": "Error en Ejecución",
            "porcentaje": 0.0,
            "eta": "--:--",
            "detalle": err_msg,
        }
        if on_telemetria is not None:
            on_telemetria(dict(tele_err))
        yield _emitir_estado(
            fase="error",
            progreso=0.0,
            mensaje=f"Error en pipeline: {err_msg}",
            clips=clips,
            ultimo_video=ultimo_video,
            job_dir=job_dir_str,
            error=err_msg,
            telemetria=tele_err,
        )
    finally:
        STREAM_URL_CACHE.invalidar(ctx.job_id)
        if audio_temp and os.path.exists(audio_temp):
            try:
                os.remove(audio_temp)
            except OSError:
                pass


def _formatear_barra_cli(estado: Dict[str, Any], ancho_barra: int = 24) -> str:
    """Genera una línea de barra de progreso visual compacta para CLI a partir de estado/telemetría."""
    tele = estado.get("telemetria") or {}
    pct_raw = tele.get("porcentaje")
    if pct_raw is None:
        pct_raw = float(estado.get("progreso", 0.0)) * 100.0
    pct = max(0.0, min(100.0, float(pct_raw)))
    llenos = int(round((pct / 100.0) * ancho_barra))
    barra = "█" * llenos + "░" * max(0, ancho_barra - llenos)

    etapa = str(tele.get("etapa") or estado.get("fase") or "run").lower()
    partes = [f"[{barra}] {pct:5.1f}%"]

    if etapa in ("descarga", "descarga_video"):
        vel = tele.get("velocidad_red") or "--"
        tam = tele.get("tamano_total") or "--"
        eta = tele.get("eta") or "--:--"
        partes.extend([f"↓ {vel}", str(tam), f"ETA {eta}"])
    elif etapa == "gemini":
        modelo = tele.get("modelo_ia") or "Gemini"
        b_act = tele.get("bloque_actual")
        b_tot = tele.get("total_bloques")
        if b_act and b_tot:
            partes.append(f"Bloque {b_act}/{b_tot}")
        partes.append(str(modelo))
    elif etapa == "render":
        encoder = tele.get("encoder") or "ffmpeg"
        fps = tele.get("fps") or "--"
        vel_x = tele.get("velocidad_x") or "--"
        eta = tele.get("eta") or "--:--"
        partes.extend([str(encoder), f"{fps} fps", str(vel_x), f"ETA {eta}"])
    elif etapa == "youtube":
        cid = tele.get("clip_id")
        partes.append(f"YouTube Shorts #{cid}" if cid else "YouTube Shorts")

    detalle = str(tele.get("detalle") or "").strip()
    if detalle and etapa not in ("render",):
        partes.append(detalle[:48])

    return " | ".join(partes)


class RenderizadorProgresoCLI:
    """Administra la impresión sincronizada de logs y barra de progreso visual en terminal."""

    def __init__(self, stream=None, es_tty: Optional[bool] = None) -> None:
        self.stream = stream if stream is not None else sys.stdout
        self.es_tty = bool(self.stream.isatty()) if es_tty is None else bool(es_tty)
        self._barra_activa = False
        self._ultima_etapa = ""
        self._ultimo_pct_no_tty = -10.0

    def log(self, mensaje: str) -> None:
        if self._barra_activa and self.es_tty:
            self.stream.write("\r\x1b[2K")
            self._barra_activa = False
        self.stream.write(f"{mensaje}\n")
        self.stream.flush()

    def actualizar(self, estado: Dict[str, Any]) -> None:
        tele = estado.get("telemetria") or {}
        if not tele:
            return
        etapa = str(tele.get("etapa") or estado.get("fase") or "")
        pct = float(tele.get("porcentaje", 0.0))
        linea = _formatear_barra_cli(estado)

        if self.es_tty:
            self.stream.write(f"\r\x1b[2K{linea}")
            self.stream.flush()
            self._barra_activa = True
            if pct >= 100.0 or etapa in ("completado", "error"):
                self.stream.write("\n")
                self.stream.flush()
                self._barra_activa = False
        else:
            cambio_etapa = etapa != self._ultima_etapa
            salto_pct = abs(pct - self._ultimo_pct_no_tty) >= 15.0 or pct >= 100.0
            if cambio_etapa or salto_pct:
                self.stream.write(f"{linea}\n")
                self.stream.flush()
                self._ultima_etapa = etapa
                self._ultimo_pct_no_tty = pct

    def finalizar(self) -> None:
        if self._barra_activa and self.es_tty:
            self.stream.write("\n")
            self.stream.flush()
            self._barra_activa = False
```
