# DOSSIER TÉCNICO MAESTRO: PIPELINE AUTÓNOMO KICKSAZOS
**Versión de Arquitectura:** v4.0 (Turbo Paralelo + Sincronización Milimétrica + Command Center)  
**Destino:** Fuente de Conocimiento Experto para NotebookLM / Auditoría Técnica de Alto Nivel  
**Repositorio Base:** `/home/bastiboy/clips_automation`  
**Entorno Operativo:** Kubuntu Linux 64-bit | Kernel Linux 7.0 | Aceleración por Hardware VAAPI (`/dev/dri/renderD128`)

---

## 1. Resumen Ejecutivo, Entorno y Stack Tecnológico

### 1.1 Resumen Ejecutivo
El **Pipeline Autónomo Kicksazos (v4.0)** es una plataforma end-to-end de automatización audiovisual e inteligencia artificial diseñada para monitorizar transmisiones en directo o grabaciones (VODs) de plataformas como Kick, Twitch y YouTube, extraer audio ultraligero (**12 kHz / 24 kbps**), segmentar y analizar bloques en paralelo (`> 1800 s` en bloques de `1500 s` con `60 s` de solapamiento vía `ThreadPoolExecutor(max_workers=3)`), renderizar clips verticales (9:16) de forma concurrente (`max_workers=2` VAAPI/CPU) con **alineación fonética por clip en render de 2 pasadas** (`_alinear_subtitulos_con_clip_renderizado`) y subtítulos `.ass` centrados simétricamente (`MarginL=110`, `MarginR=110`, `Montserrat-ExtraBold.ttf` vía `:fontsdir=`), responder inmediatamente a `Ctrl+C` (`cola.get(timeout=0.5)`), auto-limpiar jobs antiguos (`_limpiar_jobs_antiguos(7)`), y operar desde un **Command Center de 4 pestañas** (`app_interfaz.py`) con telemetría multi-hilo en vivo y panel de **Estadísticas & Rendimiento** (`calcular_estadisticas_sistema()`).

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
├── CEREBRO_COMPLETO_KICKSAZOS.md      # Dossier técnico maestro completo (actualizado v4.0)
├── CONTEXTO_PROYECTO_KICKSAZOS.md     # Base de conocimiento operativa del repositorio (v4.0)
├── app_interfaz.py                    # Command Center Gradio 6.x (4 pestañas: Mando, Galería, Historial, Estadísticas)
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
├── jobs/                              # Directorios aislados por ejecución (auto-limpieza st_mtime > 7 días)
│   ├── <job_id>/                      # Contexto único del stream analizado
│   │   ├── clips.json                 # Metadatos de clips pertenecientes exclusivamente a ese job
│   │   ├── temp_audio.mp3             # Audio ultraligero mono 12 kHz / 24 kbps del stream
│   │   ├── raw_clip_<id>.mp4          # Clip crudo descargado en Pasada 1 (sin quemar subtítulos aún)
│   │   ├── clip_audio_<id>.mp3        # Audio mono 12 kHz/24k extraído del clip crudo para alineación fonética
│   │   └── subs_<id>.ass              # Subtítulos estilizados centrados (MarginL=110, MarginR=110)
├── legacy/                            # Módulos previos a la refactorización unificada v3.1
│   ├── analizar_stream.py
│   ├── clips_virales/
│   ├── recortar_clips.py
│   └── subir_lote.py
├── pipeline_viral_clips.py            # Motor unificado v4.0 (chunking paralelo, render 2 pasadas, alineación fonética, telemetría y CLI)
├── procesar_video_universal.py        # Wrapper CLI para corte individual rápido
├── requirements.txt                   # Especificación de dependencias del entorno de producción
├── subidas_shorts.json                # Base de datos local/historial de subidas a YouTube Shorts
├── subir_shorts.py                    # Módulo de integración OAuth 2.0 y subida con YouTube Data API v3
├── tests/                             # Suite de pruebas unitarias automatizadas
│   ├── test_pipeline_v31.py           # 16 tests unitarios v3.1 (offline + smoke FFmpeg)
│   ├── test_pipeline_v32.py           # 14 tests unitarios v3.2 (fontsdir, libass real, telemetría, Gradio y CLI)
│   └── test_pipeline_v40.py           # 19 tests unitarios v4.0 (audio 12kHz/24k, chunking paralelo, render 2 pasadas, alineación fonética)
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
1. **Ruta y Aislamiento:** Todo el audio se extrae como mono a 12 kHz y 24 kbps (`-ac 1 -ar 12000 -b:a 24k`), formato ultraligero óptimo para reconocimiento de voz en Gemini minimizando tamaño de transferencia y tiempo de subida.
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
- **Especificaciones del Formato ASS v4.0 (Resolución 1080x1920):**
  - `PlayResX: 1080`, `PlayResY: 1920`, **`WrapStyle: 2`** (evita saltos de línea automáticos indeseados al usar bloques ya segmentados a 2–4 palabras).
  - `Style: Default,<fuente>,54,&H00FFFFFF,&H0000FFFF,&H00000000,&HA0000000,-1,0,0,0,100,100,1.5,0,1,5.5,3.5,2,110,110,550,1`
  - **Parámetros Clave:**
    - `Fontsize: 54` y `Spacing: 1.5`: Alta presencia tipográfica y ligero tracking optimizado para lectura rápida móvil.
    - `PrimaryColour: &H00FFFFFF` (Blanco puro) y `SecondaryColour: &H0000FFFF` (Amarillo intenso).
    - `OutlineColour: &H00000000` (`Outline: 5.5`) y `BackColour: &HA0000000` (Sombra profunda con `Shadow: 3.5`).
    - `Alignment: 2` (Centrado horizontal, anclado a la base).
    - `MarginL: 110`, `MarginR: 110` (Márgenes simétricos centrados para evitar cortes laterales en Shorts/Reels/TikTok).
    - `MarginV: 550` (Tercio medio-inferior seguro, libre de UI inferior y sin cubrir el rostro).
    - **Alineación Fonética Post-Corte (`_alinear_subtitulos_con_clip_renderizado()`):** En v4.0, los subtítulos se realinean contra el audio exacto del clip cortado (`clip_audio_<id>.mp3`) para garantizar sincronización milimétrica.
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
8. **Arquitectura de Renderizado en 2 Pasadas y Orquestación Paralela (v4.0):**
   - **Pasada 1 (Corte Crudo + Audio):** `procesar_clip_ffmpeg()` descarga y recorta el segmento crudo (`raw_clip_<id>.mp4`) y extrae su pista de audio mono 12 kHz/24k (`clip_audio_<id>.mp3`).
   - **Alineación Fonética:** `_alinear_subtitulos_con_clip_renderizado()` envía `clip_audio_<id>.mp3` a Gemini para generar subtítulos sincronizados al milisegundo y construye `subs_<id>.ass`.
   - **Pasada 2 (Composición Final 9:16):** Aplica el `filter_complex` (fondo blur, marca de agua y quemado de `subs_<id>.ass` con `fontsdir=`) sobre `raw_clip_<id>.mp4` hacia `clips_finales/clip_<id>.mp4`.
   - **Orquestación y Limpieza:** `_orquestar_render_y_subida()` procesa hasta 2 clips en paralelo (`ThreadPoolExecutor(max_workers=2)`) y `_limpiar_jobs_antiguos()` purga directorios en `jobs/` con antigüedad superior a 7 días.

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
- [x] **Aislamiento por Jobs (`jobs/<job_id>`) y Auto-Limpieza:** Los streams no pisan temporales compartidos y `_limpiar_jobs_antiguos(dias_retencion=7, job_dir_actual=ctx.job_dir)` purga automáticamente carpetas con `st_mtime > 7` días.
- [x] **Audio Ultraligero & Chunking Paralelo (v4.0):** Pista mono `12 kHz / 24 kbps`; audios `> 1800 s` se dividen en bloques de `1500 s` (`25 min`) con `60 s` de solapamiento y se analizan en paralelo con `ThreadPoolExecutor(max_workers=3)`, desplazamiento de offsets y deduplicación `>50%`.
- [x] **Resiliencia en Free Tier de Gemini:** Máquina de estados que salta en 0s ante agotamiento diario de cuota y aplica backoff exponencial con jitter en errores transitorios.
- [x] **Alineación Fonética por Clip & Centrado Simétrico `.ass` (v4.0):** Render en 2 pasadas cuando hay subtítulos (`raw_clip_<id>.mp4` → `_alinear_subtitulos_con_clip_renderizado` con fallback seguro → `generar_archivo_ass` con `MarginL=110`, `MarginR=110`, `MarginV=550`, `Montserrat-ExtraBold.ttf` vía `:fontsdir=` → quemado `-c:a copy`).
- [x] **Orquestación Concurrente & Cancelación Inmediata (v4.0):** `_orquestar_render_y_subida` ejecuta renders con `ThreadPoolExecutor(max_workers=2)` (VAAPI/CPU), serializa cuota/subida bajo `yt_lock`, protege `clips.json` con `state_lock` y responde inmediatamente a `Ctrl+C` (`cola.get(timeout=0.5)`).
- [x] **Command Center de 4 Pestañas & Estadísticas (`app_interfaz.py` v4.0):** Stepper de 4 fases, workers concurrentes (`bloques_activos`, `clips_activos`), `gr.skip()` en ticks intermedios, sanitización XSS (`html.escape(..., quote=True)`) y pestaña **📊 4. Estadísticas & Rendimiento** (`calcular_estadisticas_sistema()`).
- [x] **Batería de Pruebas Unitarias (49 tests):** `test_pipeline_v31.py` (16) + `test_pipeline_v32.py` (14) + `test_pipeline_v40.py` (19) 100% offline con mocks y smoke tests reales de `ffmpeg`/`libass` + `:fontsdir=`.

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

## 8. Apéndice de Código Crítico de Referencia (v4.0)

A continuación se incluyen los bloques de código fuente verificados (**v4.0**) de las rutinas núcleo de `pipeline_viral_clips.py`:

### 8.1 Extracción de Audio 12 kHz / 24 kbps (`extraer_audio`)
```python
def extraer_audio(
    url: str,
    job_dir: Optional[Path | str] = None,
    on_telemetria: Optional[Callable[[Dict[str, Any]], None]] = None,
    on_log: Optional[Callable[[str], None]] = None,
) -> str:
    """Extrae audio mono 12kHz/24k mediante descarga paralela yt-dlp (--newline) y fallback FFmpeg streaming."""
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
            "ffmpeg:-vn -ac 1 -ar 12000 -b:a 24k",
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
            "12000",
            "-b:a",
            "24k",
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

### 8.2 Curaduría IA con Chunking Paralelo (`analizar_con_gemini`)
```python
def analizar_con_gemini(
    ruta_audio: str | Path,
    duracion_total: Optional[float] = None,
    modelo_preferido: Optional[str] = None,
    job_dir: Optional[Path | str] = None,
    on_log: Optional[Callable[[str], None]] = None,
    on_telemetria: Optional[Callable[[Dict[str, Any]], None]] = None,
) -> List[dict]:
    """Segmenta audios largos (>30 min), analiza bloques en paralelo con Gemini File API y guarda clips.json."""
    log_lock = threading.Lock()

    def _log(msg: str) -> None:
        with log_lock:
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
            "bloques_completados": 0,
            "total_bloques": 1,
            "bloques_activos": [],
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
                f"Audio de {segundos_a_hhmmss(duracion_efectiva)} (> 30 min): "
                f"segmentando en {len(chunks)} bloques de hasta 25 min con 60s de solapamiento (máx. 3 en paralelo)..."
            )

        total_bloques = len(chunks)
        acepta_tele = _acepta_kwarg(_analizar_archivo_audio_gemini, "on_telemetria")
        tele_lock = threading.Lock()
        ultimo_ts_tele = [0.0]
        bloques_completados = 0
        bloques_activos_map: Dict[int, str] = {}
        clips_acumulados: List[dict] = []
        errores_por_bloque: List[Tuple[int, Exception]] = []

        def _construir_estado_telemetria(
            idx_ref: int,
            modelo_act: str,
            detalle: str,
        ) -> Dict[str, Any]:
            activos = [bloques_activos_map[k] for k in sorted(bloques_activos_map)]
            pct = round(min(100.0, max(0.0, (bloques_completados / max(1, total_bloques)) * 100.0)), 1)
            return {
                "etapa": "gemini",
                "titulo_etapa": f"Analizando Narrativa Viral ({modelo_act})",
                "porcentaje": pct,
                "bloque_actual": idx_ref,
                "bloques_completados": bloques_completados,
                "total_bloques": total_bloques,
                "bloques_activos": activos,
                "modelo_ia": modelo_act,
                "eta": "--:--",
                "detalle": detalle,
            }

        def _emitir_bloque_seguro(
            idx_ref: int,
            modelo_act: str,
            detalle: str,
            forzar: bool = False,
        ) -> None:
            if on_telemetria is None:
                return
            with tele_lock:
                datos = _construir_estado_telemetria(idx_ref, modelo_act, detalle)
                _emitir_telemetria(on_telemetria, ultimo_ts_tele, datos, forzar=forzar)

        def _procesar_bloque(
            idx_chunk: int,
            ruta_chunk: str,
            offset_seg: float,
            dur_chunk: Optional[float],
        ) -> None:
            nonlocal bloques_completados
            etiqueta_bloque = f"Bloque {idx_chunk}/{total_bloques}"
            if len(chunks) > 1 and dur_chunk is not None:
                _log(
                    f"Analizando bloque {idx_chunk}/{total_bloques} "
                    f"[{segundos_a_hhmmss(offset_seg)} -> {segundos_a_hhmmss(offset_seg + dur_chunk)}]..."
                )

            with tele_lock:
                bloques_activos_map[idx_chunk] = etiqueta_bloque
                activos_txt = ", ".join(bloques_activos_map[k] for k in sorted(bloques_activos_map))
                rango_txt = (
                    f" [{segundos_a_hhmmss(offset_seg)} → {segundos_a_hhmmss(offset_seg + dur_chunk)}]"
                    if dur_chunk is not None
                    else ""
                )
                datos_ini = _construir_estado_telemetria(
                    idx_chunk,
                    modelo_label,
                    f"En curso: {activos_txt}{rango_txt}",
                )
                _emitir_telemetria(on_telemetria, ultimo_ts_tele, datos_ini, forzar=True)

            def _on_tele_worker(datos_sub: Dict[str, Any]) -> None:
                mod_sub = str(datos_sub.get("modelo_ia") or modelo_label)
                det_sub = str(datos_sub.get("detalle") or etiqueta_bloque)
                _emitir_bloque_seguro(idx_chunk, mod_sub, det_sub, forzar=False)

            clips_chunk: List[dict] = []
            try:
                if acepta_tele:
                    clips_chunk = _analizar_archivo_audio_gemini(
                        client,
                        ruta_chunk,
                        dur_chunk,
                        modelo_preferido,
                        _log,
                        on_telemetria=_on_tele_worker,
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
                with tele_lock:
                    errores_por_bloque.append((idx_chunk, e_chunk))
                    bloques_activos_map.pop(idx_chunk, None)
                    bloques_completados += 1
                    datos_err = _construir_estado_telemetria(
                        idx_chunk,
                        modelo_label,
                        f"{etiqueta_bloque} falló ({type(e_chunk).__name__})",
                    )
                    _emitir_telemetria(on_telemetria, ultimo_ts_tele, datos_err, forzar=True)
                if len(chunks) > 1:
                    _log(f"[AVISO] Falló análisis del {etiqueta_bloque}: {e_chunk}")
                return

            clips_bloque_ajustados: List[dict] = []
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
                clips_bloque_ajustados.append(clip_ajustado)

            with tele_lock:
                clips_acumulados.extend(clips_bloque_ajustados)
                bloques_activos_map.pop(idx_chunk, None)
                bloques_completados += 1
                activos_rest = [bloques_activos_map[k] for k in sorted(bloques_activos_map)]
                sufijo = f" • Activos: {', '.join(activos_rest)}" if activos_rest else ""
                datos_fin = _construir_estado_telemetria(
                    idx_chunk,
                    modelo_label,
                    f"{etiqueta_bloque} completado ({len(clips_chunk)} clips){sufijo}",
                )
                _emitir_telemetria(on_telemetria, ultimo_ts_tele, datos_fin, forzar=True)

        with concurrent.futures.ThreadPoolExecutor(max_workers=3) as executor:
            futuros = [
                executor.submit(_procesar_bloque, idx_c, ruta_c, off_c, dur_c)
                for idx_c, (ruta_c, off_c, dur_c) in enumerate(chunks, start=1)
            ]
            for fut in futuros:
                fut.result()

        if len(chunks) == 1 and errores_por_bloque:
            raise errores_por_bloque[0][1]

        clips_finales = _deduplicar_clips_solapados(clips_acumulados)
        if not clips_finales:
            if errores_por_bloque:
                raise errores_por_bloque[-1][1]
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

### 8.3 Subtítulos ASS Centrados y Alineación Fonética (`generar_archivo_ass`, `_alinear_subtitulos_con_clip_renderizado`)
```python
def generar_archivo_ass(
    subtitulos: List[Any],
    ruta_ass: str | Path,
) -> str:
    """Genera un archivo .ass v4.0 centrado (1080x1920, MarginL/R=110) y devuelve su ruta absoluta."""
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
            f"Style: Default,{fuente_sub},54,&H00FFFFFF,&H0000FFFF,&H00000000,&HA0000000,-1,0,0,0,100,100,1.5,0,1,5.5,3.5,2,110,110,550,1",
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


def _alinear_subtitulos_con_clip_renderizado(
    ruta_video_raw: str,
    subtitulos: List[SegmentoSubtitulo],
    job_dir: Path,
    id_clip: int,
    duracion_clip: float,
    on_log: Optional[Callable[[str], None]] = None,
) -> List[SegmentoSubtitulo]:
    """Re-sincroniza subtítulos contra el audio exacto de raw_clip_<id>.mp4 usando Gemini File API."""
    def _log(msg: str) -> None:
        if on_log is not None:
            on_log(msg)
        else:
            print(msg)

    api_key = os.environ.get("GEMINI_API_KEY")
    if (
        not subtitulos
        or duracion_clip <= 0
        or not api_key
        or not ruta_video_raw
        or not Path(ruta_video_raw).is_file()
    ):
        return subtitulos

    carpeta_job = Path(job_dir).resolve()
    carpeta_job.mkdir(parents=True, exist_ok=True)
    ruta_audio_clip = carpeta_job / f"clip_audio_{id_clip}.mp3"

    client: Optional[genai.Client] = None
    archivo_subido: Any = None
    try:
        comando_audio = [
            "ffmpeg",
            "-hide_banner",
            "-loglevel",
            "error",
            "-y",
            "-i",
            str(ruta_video_raw),
            "-vn",
            "-ac",
            "1",
            "-ar",
            "12000",
            "-b:a",
            "24k",
            str(ruta_audio_clip),
        ]
        subprocess.run(comando_audio, check=True, capture_output=True, text=True)
        if not ruta_audio_clip.is_file() or ruta_audio_clip.stat().st_size <= 0:
            raise RuntimeError("El audio extraído del clip raw está vacío.")

        client = genai.Client(
            api_key=api_key,
            http_options={"timeout": GEMINI_TIMEOUT_MS},
        )
        archivo_subido = _subir_archivo_gemini_activo(
            client,
            ruta_audio_clip,
            on_log=on_log,
        )
        prompt = _construir_prompt_alineacion_subtitulos(duracion_clip, subtitulos)
        subs_alineados, modelo_usado = _ejecutar_cascada_modelos_gemini(
            client=client,
            archivo_subido=archivo_subido,
            prompt=prompt,
            response_schema=list[SegmentoSubtitulo],
            temperature=0.1,
            parsear_fn=lambda txt: _parsear_subtitulos_json(txt, duracion_clip),
            on_log=on_log,
        )
        _log(
            f"✓ Subtítulos del Clip #{id_clip} alineados fonéticamente con {modelo_usado} "
            f"({len(subs_alineados)} segmentos)"
        )
        return subs_alineados
    except Exception as exc:
        _log(
            f"[AVISO] Falló micro-pasada de alineación fonética para Clip #{id_clip} ({exc}); "
            "usando subtítulos originales como fallback seguro."
        )
        return subtitulos
    finally:
        if client is not None and archivo_subido is not None and getattr(archivo_subido, "name", None):
            try:
                client.files.delete(name=archivo_subido.name)
            except Exception:
                pass
        if ruta_audio_clip.exists():
            try:
                os.remove(ruta_audio_clip)
            except OSError:
                pass
```

### 8.4 Renderizado 9:16 en 2 Pasadas (`procesar_clip_ffmpeg`)
```python
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
    """Renderiza el clip 9:16 (2 pasos con alineación fonética si tiene subtítulos, o 1 paso directo si no)."""
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

    if job_dir:
        carpeta_job = Path(job_dir).resolve()
    elif job_id:
        carpeta_job = (CARPETA_JOBS / job_id).resolve()
    else:
        carpeta_job = (CARPETA_JOBS / "standalone").resolve()
    carpeta_job.mkdir(parents=True, exist_ok=True)

    _log(
        f"\n--- Procesando Clip {id_clip} ({inicio} -> {fin}, t={duracion_str}s) "
        f"[Salida: {nombre_clip}] ---"
    )

    subs_norm = _normalizar_subtitulos(subtitulos, duracion_clip)
    tiene_subs = bool(subs_norm)

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
    url_refrescada = False
    etiqueta_clip = f"Renderizando Clip #{id_clip}" + (
        f" ({clip_indice}/{total_clips})" if clip_indice and total_clips else ""
    )

    def _emitir_render_tele(
        pct: float,
        fps: str = "--",
        velocidad_x: str = "--",
        eta: str = "--:--",
        frame: int = 0,
        out_time: str = "00:00:00",
        detalle: str = "",
        forzar: bool = False,
    ) -> None:
        if on_telemetria is None:
            return
        payload = {
            "etapa": "render",
            "titulo_etapa": etiqueta_clip,
            "porcentaje": round(min(100.0, max(0.0, float(pct))), 1),
            "fps": fps,
            "velocidad_x": velocidad_x,
            "velocidad_render": velocidad_x,
            "eta": eta,
            "encoder": encoder_activo,
            "clip_id": str(id_clip),
            "clip_indice": clip_indice,
            "total_clips": total_clips,
            "frame": frame,
            "out_time": out_time,
            "duracion_clip": duracion_clip,
            "detalle": detalle,
        }
        if forzar:
            _emitir_telemetria(on_telemetria, [0.0], payload, forzar=True)
        else:
            on_telemetria(payload)

    def _ejecutar_paso_1(destino_paso1: Path, escala_pct: float = 1.0, etiqueta_paso: str = "") -> None:
        nonlocal entradas_media, dimensiones, y_watermark, encoder_activo, url_refrescada
        while True:
            comando_ffmpeg = _construir_comando_render(
                entradas_media=entradas_media,
                es_remoto=es_remoto,
                inicio=inicio,
                duracion_str=duracion_str,
                archivo_salida=destino_paso1,
                y_watermark=y_watermark,
                encoder=encoder_activo,
                ruta_ass=None,
                fonts_dir=None,
            )
            sufijo_paso = f" [{etiqueta_paso}]" if etiqueta_paso else ""
            _log(
                f"Renderizando composición 9:16 con FFmpeg{sufijo_paso} "
                f"[encoder={encoder_activo}, wm_y={y_watermark}, subs=no]..."
            )
            _emitir_render_tele(
                0.0,
                detalle=f"Iniciando render {encoder_activo}{' • ' + etiqueta_paso if etiqueta_paso else ''}...",
                forzar=True,
            )

            def _on_prog_p1(prog: Dict[str, Any]) -> None:
                _emitir_render_tele(
                    prog["porcentaje"] * escala_pct,
                    fps=prog["fps_str"],
                    velocidad_x=prog["speed_str"],
                    eta=prog["eta_str"],
                    frame=prog["frame"],
                    out_time=prog["out_time_str"],
                    detalle=(
                        f"Encoder {encoder_activo}"
                        f"{' (' + etiqueta_paso + ')' if etiqueta_paso else ''} • "
                        f"{prog['fps_str']} fps • {prog['speed_str']} • ETA {prog['eta_str']}"
                    ),
                )

            try:
                _ejecutar_comando_con_captura(
                    comando_ffmpeg,
                    duracion_objetivo=duracion_clip,
                    on_progreso=_on_prog_p1 if on_telemetria is not None else None,
                )
                break
            except subprocess.CalledProcessError as err:
                if destino_paso1.exists():
                    try:
                        destino_paso1.unlink()
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

                if encoder_activo == "h264_vaapi":
                    _log(
                        "[AVISO] Renderizado VAAPI falló en ejecución; "
                        "reintentando automáticamente con CPU (libx264)..."
                    )
                    encoder_activo = "libx264"
                    continue

                raise

    if not tiene_subs:
        _ejecutar_paso_1(archivo_salida, escala_pct=1.0)
        _log(f"✓ Clip {id_clip} guardado con éxito en: {archivo_salida}")
        return str(archivo_salida.resolve())

    raw_clip = carpeta_job / f"raw_clip_{id_clip}.mp4"
    try:
        # Paso 1: corte y composición 9:16 limpia (sin subtítulos) hacia raw_clip_<id>.mp4
        _ejecutar_paso_1(raw_clip, escala_pct=0.50, etiqueta_paso="Paso 1/2: corte 9:16")

        # Paso 2a: micro-pasada de alineación fonética sobre el audio exacto de raw_clip
        _emitir_render_tele(
            52.0,
            detalle="Alineando subtítulos fonéticamente al audio exacto...",
            forzar=True,
        )
        id_clip_arg: Any = int(id_clip) if str(id_clip).isdigit() else id_clip
        subs_alineados = _alinear_subtitulos_con_clip_renderizado(
            str(raw_clip),
            subs_norm,
            carpeta_job,
            id_clip_arg,
            duracion_clip,
            on_log=on_log,
        )
        subs_finales = _normalizar_subtitulos(subs_alineados, duracion_clip) or subs_norm
        ruta_ass = generar_archivo_ass(subs_finales, carpeta_job / f"subs_{id_clip}.ass")
        fuente_sub, fonts_dir_sub = _obtener_fuente_y_dir_subtitulos()
        _log(
            f"✓ Subtítulos dinámicos alineados en: {ruta_ass} "
            f"[fuente={fuente_sub}, fontsdir={fonts_dir_sub or 'sistema'}]"
        )

        # Paso 2b: quemado rápido de subtítulos .ass sobre raw_clip con -c:a copy
        while True:
            comando_pass2 = _construir_comando_quemar_ass(
                ruta_video_raw=raw_clip,
                archivo_salida=archivo_salida,
                ruta_ass=ruta_ass,
                encoder=encoder_activo,
                fonts_dir=fonts_dir_sub,
            )
            _log(
                f"Quemando subtítulos .ass sobre raw_clip [Paso 2/2, encoder={encoder_activo}]..."
            )
            _emitir_render_tele(
                55.0,
                detalle=f"Paso 2/2: quemando subtítulos ({encoder_activo})...",
                forzar=True,
            )

            def _on_prog_p2(prog: Dict[str, Any]) -> None:
                _emitir_render_tele(
                    55.0 + prog["porcentaje"] * 0.45,
                    fps=prog["fps_str"],
                    velocidad_x=prog["speed_str"],
                    eta=prog["eta_str"],
                    frame=prog["frame"],
                    out_time=prog["out_time_str"],
                    detalle=(
                        f"Paso 2/2 ({encoder_activo}) • {prog['fps_str']} fps • "
                        f"{prog['speed_str']} • ETA {prog['eta_str']}"
                    ),
                )

            try:
                _ejecutar_comando_con_captura(
                    comando_pass2,
                    duracion_objetivo=duracion_clip,
                    on_progreso=_on_prog_p2 if on_telemetria is not None else None,
                )
                break
            except subprocess.CalledProcessError as err:
                if archivo_salida.exists():
                    try:
                        archivo_salida.unlink()
                    except OSError:
                        pass

                stderr_txt = err.stderr or err.output or ""

                if re.search(r"Parsed_subtitles|subtitles|libass|\.ass", stderr_txt, re.IGNORECASE):
                    _log(
                        "[AVISO] El filtro de subtítulos .ass falló en Paso 2; "
                        "guardando clip sin subtítulos desde raw_clip..."
                    )
                    shutil.copy2(raw_clip, archivo_salida)
                    break

                if encoder_activo == "h264_vaapi":
                    _log(
                        "[AVISO] Quemado .ass con VAAPI falló en Paso 2; "
                        "reintentando automáticamente con CPU (libx264)..."
                    )
                    encoder_activo = "libx264"
                    continue

                _log(
                    "[AVISO] Paso 2 falló con subtítulos activos; "
                    "guardando clip limpio sin subtítulos desde raw_clip..."
                )
                shutil.copy2(raw_clip, archivo_salida)
                break
    finally:
        if raw_clip.exists():
            try:
                raw_clip.unlink()
            except OSError:
                pass

    _log(f"✓ Clip {id_clip} guardado con éxito en: {archivo_salida}")
    return str(archivo_salida.resolve())
```

### 8.5 Orquestación Paralela y Auto-Limpieza de Jobs (`_orquestar_render_y_subida`, `_limpiar_jobs_antiguos`)
```python
def _orquestar_render_y_subida(
    url: str,
    clips: List[dict],
    duracion_total: Optional[float] = None,
    subir_youtube: bool = True,
    job_id: Optional[str] = None,
    job_dir: Optional[Path | str] = None,
    publish_at_inicio: Optional[str] = None,
    intervalo_horas: int | float = 0,
    on_log: Optional[Callable[[str], None]] = None,
    on_telemetria: Optional[Callable[[Dict[str, Any]], None]] = None,
) -> Generator[Dict[str, Any], None, None]:
    """Orquestador compartido de Fase 3+4 con renderizado paralelo (max_workers=2) y locks thread-safe."""
    log_lock = threading.Lock()

    def _log(msg: str) -> None:
        with log_lock:
            if on_log is not None:
                on_log(msg)
            else:
                print(msg)

    job_dir_str = str(Path(job_dir).resolve()) if job_dir else None
    fuente_local: Optional[str] = None
    youtube_client = None
    ultimo_video: Optional[str] = None

    _log("\n[3/4] Renderizando clips con formato 9:16 y marca de agua @Kicksazos...")
    tele_fuente_init = {
        "etapa": "descarga_video",
        "titulo_etapa": "Preparando Fuente de Video (1080p)",
        "porcentaje": 0.0,
        "velocidad_red": "--",
        "tamano_total": "--",
        "eta": "--:--",
        "detalle": "Evaluando estrategia de lectura de stream...",
    }
    if on_telemetria is not None:
        on_telemetria(dict(tele_fuente_init))
    yield _emitir_estado(
        fase="fuente",
        progreso=0.55,
        mensaje="Fase 3/4: Preparando fuente de video en 1080p...",
        clips=clips,
        ultimo_video=ultimo_video,
        job_dir=job_dir_str,
        telemetria=tele_fuente_init,
    )

    try:
        # Para videos <= 1h descargar una sola vez evita múltiples conexiones HTTP/HLS lentas
        if duracion_total is None or duracion_total <= 3600:
            try:
                destino_fuente = (
                    Path(job_dir) / "temp_source.mp4"
                    if job_dir
                    else BASE_DIR / "temp_source.mp4"
                )
                kwargs_dl: Dict[str, Any] = {"destino": destino_fuente}
                if _acepta_kwarg(descargar_video_fuente, "on_log"):
                    kwargs_dl["on_log"] = _log
                fuente_local = yield from _ejecutar_paso_con_telemetria(
                    descargar_video_fuente,
                    url,
                    construir_estado=lambda tele: _emitir_estado(
                        fase="fuente",
                        progreso=0.55 + 0.05 * (float(tele.get("porcentaje", 0.0)) / 100.0),
                        mensaje=f"Fase 3/4: {tele.get('titulo_etapa', 'Descargando fuente 1080p')} ({tele.get('porcentaje', 0):.1f}%)",
                        clips=clips,
                        ultimo_video=ultimo_video,
                        job_dir=job_dir_str,
                        telemetria=tele,
                    ),
                    on_telemetria_externa=on_telemetria,
                    **kwargs_dl,
                )
                _log(f"✓ Video fuente descargado en {fuente_local}")
            except Exception as e:
                _log(f"[AVISO] Descarga local completa omitida ({e}); usando seek directo en stream...")
                fuente_local = None

        if subir_youtube:
            _log("\n[4/4] Preparando cliente de YouTube Data API v3 para subida automática...")
            try:
                youtube_client = autenticar_youtube(interactivo=False)
                _log("✓ Cliente de YouTube autenticado correctamente.")
            except Exception as e:
                _log(
                    f"[AVISO] No se pudo inicializar YouTube Data API ({e}). "
                    "Los clips se renderizarán localmente sin interrumpir el flujo."
                )
                youtube_client = None

        entrada_render = fuente_local or url
        total_clips = len(clips)
        if total_clips == 0:
            return

        subidos_en_lote = 0
        state_lock = threading.Lock()
        yt_lock = threading.Lock()
        cola_estados: queue.Queue[Tuple[str, Dict[str, Any]]] = queue.Queue()
        progreso_clip: Dict[int, float] = {idx: 0.0 for idx in range(1, total_clips + 1)}
        clips_activos_map: Dict[int, Dict[str, Any]] = {}
        acepta_clip_idx = _acepta_kwarg(procesar_clip_ffmpeg, "clip_indice")
        acepta_total_clips = _acepta_kwarg(procesar_clip_ffmpeg, "total_clips")
        acepta_on_log = _acepta_kwarg(procesar_clip_ffmpeg, "on_log")
        acepta_on_tele = _acepta_kwarg(procesar_clip_ffmpeg, "on_telemetria")

        def _emitir_en_cola_seguro(
            fase: str,
            mensaje: str,
            tele_payload: Dict[str, Any],
            progreso_override: Optional[float] = None,
        ) -> None:
            with state_lock:
                activos_snapshot = [dict(clips_activos_map[k]) for k in sorted(clips_activos_map)]
                tele_envio = dict(tele_payload)
                tele_envio["clips_activos"] = activos_snapshot
                if progreso_override is not None:
                    prog_global = progreso_override
                else:
                    prog_global = min(
                        0.95,
                        0.60 + 0.35 * (sum(progreso_clip.values()) / max(1, total_clips)),
                    )
                if on_telemetria is not None:
                    try:
                        on_telemetria(dict(tele_envio))
                    except Exception:
                        pass
                estado = _emitir_estado(
                    fase=fase,
                    progreso=prog_global,
                    mensaje=mensaje,
                    clips=[dict(c) for c in clips],
                    ultimo_video=ultimo_video,
                    job_dir=job_dir_str,
                    telemetria=tele_envio,
                )
            cola_estados.put(("estado", estado))

        def _procesar_un_clip(idx: int, clip: dict) -> None:
            nonlocal ultimo_video, subidos_en_lote
            cid = clip.get("id", idx)
            c_tit = clip.get("titulo", "")
            _log(
                f"Procesando Clip #{cid}/{total_clips} ({clip.get('inicio')} -> {clip.get('fin')})..."
            )
            with state_lock:
                clips_activos_map[idx] = {
                    "clip_id": str(cid),
                    "clip_indice": idx,
                    "estado": "renderizando",
                    "porcentaje": 0.0,
                    "encoder": "detectando...",
                    "fps": "--",
                    "velocidad_x": "--",
                    "velocidad_render": "--",
                }

            tele_render_init = {
                "etapa": "render",
                "titulo_etapa": f"Renderizando Clip #{cid} ({idx}/{total_clips})",
                "porcentaje": 0.0,
                "fps": "--",
                "velocidad_x": "--",
                "velocidad_render": "--",
                "eta": "--:--",
                "encoder": "detectando...",
                "clip_id": str(cid),
                "clip_indice": idx,
                "total_clips": total_clips,
                "detalle": f"Preparando composición 9:16 del Clip #{cid}",
            }
            _emitir_en_cola_seguro(
                fase="render",
                mensaje=f"Renderizando Clip #{cid}/{total_clips}: {c_tit}",
                tele_payload=tele_render_init,
            )

            def _on_tele_clip(datos: Dict[str, Any]) -> None:
                copia = dict(datos or {})
                pct_clip = float(copia.get("porcentaje", 0.0))
                vel_clip = str(copia.get("velocidad_x") or copia.get("velocidad_render") or "--")
                with state_lock:
                    progreso_clip[idx] = max(
                        progreso_clip.get(idx, 0.0),
                        min(1.0, max(0.0, pct_clip / 100.0)),
                    )
                    clips_activos_map[idx] = {
                        "clip_id": str(copia.get("clip_id") or cid),
                        "clip_indice": idx,
                        "estado": "renderizando",
                        "porcentaje": round(pct_clip, 1),
                        "encoder": str(copia.get("encoder") or ""),
                        "fps": str(copia.get("fps") or "--"),
                        "velocidad_x": vel_clip,
                        "velocidad_render": vel_clip,
                    }
                _emitir_en_cola_seguro(
                    fase="render",
                    mensaje=(
                        f"Renderizando Clip #{cid}/{total_clips}: {c_tit} "
                        f"[{pct_clip:.1f}% • {copia.get('encoder', '')}]"
                    ),
                    tele_payload=copia,
                )

            try:
                kwargs_render: Dict[str, Any] = {
                    "job_id": job_id,
                    "subtitulos": clip.get("subtitulos"),
                    "job_dir": job_dir,
                }
                if acepta_clip_idx:
                    kwargs_render["clip_indice"] = idx
                if acepta_total_clips:
                    kwargs_render["total_clips"] = total_clips
                if acepta_on_log:
                    kwargs_render["on_log"] = _log
                if acepta_on_tele:
                    kwargs_render["on_telemetria"] = _on_tele_clip

                salida = procesar_clip_ffmpeg(
                    entrada_render,
                    clip.get("inicio"),
                    clip.get("fin"),
                    str(cid),
                    **kwargs_render,
                )
                with state_lock:
                    clip["archivo_local"] = salida
                    clip["render_status"] = "OK"
                    ultimo_video = salida
                    progreso_clip[idx] = 1.0
                _log(f"✓ Clip #{cid} renderizado en: {salida}")

                if not subir_youtube:
                    with state_lock:
                        clip["youtube_status"] = "Subida omitida (--sin-subida)"
                elif youtube_client is None:
                    with state_lock:
                        clip["youtube_status"] = "Pendiente de subida (Sin credenciales activas)"
                else:
                    with yt_lock:
                        cuota = verificar_cuota_diaria(limite_diario=LIMITE_CUOTA_DIARIA_SHORTS)
                        if not cuota["permitido"]:
                            with state_lock:
                                clip["youtube_status"] = (
                                    f"Pendiente por cuota diaria ({cuota['limite']}/24h)"
                                )
                            _log(
                                f"[AVISO] Cuota diaria alcanzada ({cuota['subidas_24h']}/{cuota['limite']} "
                                f"en últimas 24h). Clip #{cid} marcado como '{clip['youtube_status']}'."
                            )
                        else:
                            publish_at_clip = None
                            if publish_at_inicio and str(publish_at_inicio).strip():
                                publish_at_clip = calcular_publish_at_utc(
                                    publish_at_inicio,
                                    indice_clip=subidos_en_lote,
                                    intervalo_horas=intervalo_horas,
                                )

                            msg_yt = f"Subiendo Clip #{cid} a YouTube Shorts"
                            if publish_at_clip:
                                msg_yt += f" (Programado UTC: {publish_at_clip})"
                            else:
                                msg_yt += " (Privado)"
                            _log(msg_yt)

                            with state_lock:
                                clips_activos_map[idx] = {
                                    "clip_id": str(cid),
                                    "clip_indice": idx,
                                    "estado": "subiendo_youtube",
                                    "porcentaje": 100.0,
                                    "encoder": "youtube_api",
                                    "fps": "--",
                                    "velocidad_x": "--",
                                }
                                prog_actual = min(
                                    0.98,
                                    0.60
                                    + 0.35 * (sum(progreso_clip.values()) / max(1, total_clips))
                                    + (0.15 / max(1, total_clips)),
                                )

                            tele_yt = {
                                "etapa": "youtube",
                                "titulo_etapa": f"Subiendo Clip #{cid} a YouTube Shorts",
                                "porcentaje": round((idx / max(1, total_clips)) * 100.0, 1),
                                "eta": "--:--",
                                "clip_id": str(cid),
                                "clip_indice": idx,
                                "total_clips": total_clips,
                                "detalle": msg_yt,
                            }
                            _emitir_en_cola_seguro(
                                fase="youtube",
                                mensaje=msg_yt,
                                tele_payload=tele_yt,
                                progreso_override=prog_actual,
                            )

                            try:
                                info_yt = subir_short(
                                    youtube=youtube_client,
                                    ruta_video=salida,
                                    titulo=clip.get("titulo", f"Clip {cid}"),
                                    descripcion=clip.get("descripcion", ""),
                                    etiquetas=clip.get("etiquetas", []),
                                    privacidad="private",
                                    clip_id=clip.get("id"),
                                    guardar_registro=True,
                                    publish_at=publish_at_clip,
                                    on_log=_log,
                                )
                                with state_lock:
                                    clip["youtube_id"] = info_yt["youtube_id"]
                                    clip["youtube_url"] = info_yt["url"]
                                    if info_yt.get("publish_at"):
                                        clip["youtube_publish_at"] = info_yt["publish_at"]
                                        clip["youtube_status"] = f"Programado ({info_yt['publish_at']})"
                                    else:
                                        clip["youtube_status"] = "Subido (Privado)"
                                subidos_en_lote += 1
                            except Exception as e_yt:
                                _log(f"[AVISO] Error al subir Clip #{cid} a YouTube: {e_yt}")
                                with state_lock:
                                    clip["youtube_status"] = f"Error subida ({str(e_yt)[:80]})"
            except Exception as e_clip:
                err_txt = str(e_clip)
                with state_lock:
                    clip["render_status"] = f"Error render ({err_txt[:120]})"
                    clip["youtube_status"] = f"No renderizado ({err_txt[:80]})"
                    progreso_clip[idx] = 1.0
                _log(f"[ERROR] Falló procesamiento del Clip #{cid}: {err_txt}")
            finally:
                # Persistencia incremental thread-safe tras cada clip sin abortar el lote
                with state_lock:
                    clips_activos_map.pop(idx, None)
                    _guardar_y_sincronizar_clips(clips, job_dir=job_dir)

        executor = concurrent.futures.ThreadPoolExecutor(max_workers=2)
        try:
            futuros = [
                executor.submit(_procesar_un_clip, idx, clip)
                for idx, clip in enumerate(clips, start=1)
            ]
            while True:
                try:
                    tipo, payload = cola_estados.get(timeout=0.5)
                    if tipo == "estado":
                        yield payload
                except queue.Empty:
                    if all(f.done() for f in futuros) and cola_estados.empty():
                        break

            while not cola_estados.empty():
                tipo, payload = cola_estados.get_nowait()
                if tipo == "estado":
                    yield payload

            for fut in futuros:
                fut.result()
        except BaseException:
            executor.shutdown(wait=False, cancel_futures=True)
            raise
        else:
            executor.shutdown(wait=True)
    finally:
        if job_id:
            STREAM_URL_CACHE.invalidar(job_id)
        if fuente_local and os.path.exists(fuente_local):
            try:
                os.remove(fuente_local)
            except OSError:
                pass


def _limpiar_jobs_antiguos(
    dias_retencion: int = 7,
    job_dir_actual: Optional[Path] = None,
) -> int:
    """Elimina de CARPETA_JOBS los subdirectorios cuya st_mtime supere dias_retencion días (ignorando job_dir_actual)."""
    if not CARPETA_JOBS.exists() or not CARPETA_JOBS.is_dir():
        return 0

    actual_resuelto = Path(job_dir_actual).resolve() if job_dir_actual is not None else None
    limite_ts = time.time() - (max(0.0, float(dias_retencion)) * 86400.0)
    eliminados = 0

    try:
        entradas = list(CARPETA_JOBS.iterdir())
    except OSError:
        return 0

    for entrada in entradas:
        try:
            if not entrada.is_dir() or entrada.is_symlink():
                continue
            if actual_resuelto is not None and entrada.resolve() == actual_resuelto:
                continue
            if entrada.stat().st_mtime < limite_ts:
                shutil.rmtree(entrada, ignore_errors=True)
                eliminados += 1
        except OSError:
            continue

    return eliminados
```
