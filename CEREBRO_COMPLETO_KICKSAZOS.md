# DOSSIER TÉCNICO MAESTRO: PIPELINE AUTÓNOMO KICKSAZOS
**Versión de Arquitectura:** v4.1 (Híbrido Nube Gemini + 100% Local Offline Whisper/Ollama + Command Center)
**Destino:** Fuente de Conocimiento Experto para NotebookLM / Auditoría Técnica de Alto Nivel
**Repositorio Base:** `/home/bastiboy/clips_automation`
**Entorno Operativo:** Kubuntu Linux 64-bit | Kernel Linux 6.11 / 7.0 | Aceleración por Hardware VAAPI (`/dev/dri/renderD128`)

---

## 1. Resumen Ejecutivo, Hardware, Entorno y Árbol de Directorios

### 1.1 Resumen Ejecutivo
El **Pipeline Autónomo Kicksazos (v4.1)** es un sistema integral de ingeniería de software audiovisual e inteligencia artificial diseñado para la extracción, curaduría, renderizado vertical 9:16 y publicación automatizada de clips virales procedentes de streams y VODs de **Kick**, YouTube o Twitch, así como de archivos multimedia locales (`.mp4`, `.mkv`).

El pipeline opera bajo una arquitectura híbrida dual seleccionable:
- **Modo Nube (`gemini`):** Análisis multimodal directo con Google Gemini 3 Flash / Flash-Lite (`temperature=0.20`), segmentación paralela con `ThreadPoolExecutor(max_workers=3)` para audios largos (`> 1800 s`), reintentos con jitter y backoff, y renderizado en **2 pasadas con micro-alineación fonética** por clip (`_alinear_subtitulos_con_clip_renderizado`). Ante agotamiento total de cuotas Free Tier (`429`), conmuta automáticamente a motor local si `respaldo_local_auto=True`.
- **Modo Local 100% Offline (`local`):** Transcripción fonética local mediante `faster-whisper` (`medium`, `int8`, CPU) alimentada por buffer PCM float32 16 kHz directo, detección de picos vocales por energía acústica RMS (`>= 1.65x` mediana global), liberación inmediata de memoria RAM (`del model; gc.collect()`), curaduría viral mediante LLMs locales en **Ollama** (`qwen3:14b` por defecto, o `gemma3:12b` en `127.0.0.1:11434`), construcción de subtítulos dinámicos de 2–4 palabras desde los `word_timestamps` de Whisper, descarga de Ollama de RAM (`keep_alive=0`), y renderizado en **1 sola pasada directa** de FFmpeg sin requerir API externa ni archivos `raw_clip` intermedios.

### 1.2 Hardware del Host y Entorno Operativo
- **Sistema Operativo:** Kubuntu Linux 64-bit (base Ubuntu con entorno KDE Plasma / Wayland).
- **Procesador (CPU):** AMD Ryzen 5 7520U with Radeon Graphics (4 núcleos físicos, 8 subprocesos lógicos, frecuencia base 2.8 GHz / turbo 4.3 GHz).
- **Memoria RAM:** 16 GB LPDDR5-5500 MHz (14 GiB reconocidos por kernel, 8.0 GiB swap activa en SSD NVMe).
- **Aceleración por Hardware:** GPU integrada AMD Radeon 610M (`radeonsi`, driver Mesa Gallium 26.0.8, DRM 3.64). Dispositivo VAAPI en `/dev/dri/renderD128` verificado con `detectar_encoder_hardware()` mediante codificación nula de 1 frame.
- **Intérprete de Python:** `Python 3.14.4` en entorno virtual activo `/home/bastiboy/clips_automation/venv`.
- **Motor Multimedia FFmpeg:** `ffmpeg version 8.0.1-3ubuntu2` (GCC 15 Ubuntu) con filtros `libass` (`fontsdir=`), `subtitles`, `boxblur`, `scale`, `overlay`, `setsar` y telemetría de socket en `-progress pipe:1`.
- **Descargador yt-dlp:** `yt-dlp 2026.08.19` en sistema y `2026.10.26` en venv con soporte JavaScript vía Node.js y componentes remotos EJS.
- **Servidor Ollama:** Ollama v0.5+ activo en `127.0.0.1:11434`. Modelos verificados en disco: `qwen3:14b` (9.3 GB, 8k contexto) y `gemma3:12b` (8.2 GB).

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
faster-whisper>=1.1.0
```

### 1.4 Árbol de Directorios del Repositorio
```text
/home/bastiboy/clips_automation/
├── .env                              # [PROTEGIDO - ZERO-SECRETS] Variables de entorno (GEMINI_API_KEY, etc.)
├── .gitignore                         # Exclusiones de control de versiones Git
├── CEREBRO_COMPLETO_KICKSAZOS.md      # Dossier técnico maestro consolidado v4.1
├── CONTEXTO_PROYECTO_KICKSAZOS.md     # Base de conocimiento y contexto operativo unificado v4.1
├── Contexto y Objetivos del Proyecto Kicksazos.md # Documento histórico original
├── app_interfaz.py                    # Command Center web Gradio 6.31 (4 pestañas)
├── client_secret.json                 # [PROTEGIDO - ZERO-SECRETS] Credenciales cliente OAuth 2.0 YouTube
├── clips.json                         # Registro canónico del último lote de clips procesado
├── gradio.log                         # Bitácora de ejecución de la interfaz web
├── pipeline_viral_clips.py            # Motor principal de orquestación, curaduría híbrida y render
├── procesar_video_universal.py        # CLI de conveniencia para re-render de un único segmento
├── requirements.txt                   # Especificación de dependencias del entorno virtual
├── subidas_shorts.json                # Historial acumulativo de clips subidos a YouTube
├── subir_shorts.py                    # Módulo de autenticación OAuth 2.0 y subida a YouTube Shorts
├── token.json                         # [PROTEGIDO - ZERO-SECRETS] Token OAuth activo
├── token_cuenta_anterior.json         # [PROTEGIDO - ZERO-SECRETS] Token histórico
├── assets/
│   ├── fonts/
│   │   └── Montserrat-ExtraBold.ttf   # Tipografía oficial para subtítulos .ass
│   ├── watermark.png                  # Marca de agua oficial @Kicksazos (420px ancho)
│   └── Gemini_Generated_Image_...jpeg # Imagen de marca
├── clips_finales/                     # Directorio de salida con clips verticales 9:16 generados (.mp4)
├── jobs/                              # Directorios de trabajo temporales aislados por job (<job_id>/)
│   └── <job_id>/                      # Contexto de ejecución aislado
│       ├── temp_audio.mp3             # Pista de audio extraída (12 kHz mono 24 kbps)
│       ├── whisper_transcript.json    # Transcripción local Whisper en caché con timestamps y picos
│       ├── clips.json                 # Metadatos de clips seleccionados para el job
│       ├── subs_<id>.ass              # Subtítulos .ass generados por cada clip
│       └── raw_clip_<id>.mp4          # Corte preliminar sin subtítulos (sólo en modo nube 2 pasadas)
├── legacy/                            # Scripts históricos archivados
│   ├── analizar_stream.py
│   ├── recortar_clips.py
│   ├── subir_lote.py
│   └── clips_virales/
│       └── reporte_clips.json
├── tests/                             # Suite de pruebas automatizadas (64 tests / 100% OK)
│   ├── test_pipeline_v31.py           # 16 tests: Extracción audio, resiliencia, chunking y estilos ASS
│   ├── test_pipeline_v32.py           # 14 tests: Tipografía Montserrat, libass fontsdir y telemetría yt-dlp/ffmpeg
│   ├── test_pipeline_v40.py           # 19 tests: Audio ultraligero, Gemini paralelo, 2 pasadas, locks, limpieza y UI
│   └── test_pipeline_v41.py           # 15 tests: Safe zone v4.1, Whisper, Ollama, 1 pasada y fallback 429
└── venv/                              # Entorno virtual aislado Python 3.14.4
```

---

## 2. Esquema de Datos y Contratos Pydantic (`ClipViral` y `SegmentoSubtitulo`)

### 2.1 Código Literal de los Modelos de Datos
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


class ClipViralLocal(BaseModel):
    """Esquema estructurado de clip viral para curaduría local con Ollama (subtítulos provienen de Whisper)."""

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
        description="Resumen corto (2 líneas) con llamado a la acción (CTA) de suscripción y 3-5 hashtags estratégicos (#Shorts #Kicksazos)"
    )
    etiquetas: List[str] = Field(
        description="Lista de 8 a 12 tags SEO clave incluyendo nombres propios de involucrados y ecosistema streaming colombiano"
    )
    caption_tiktok: str = Field(
        description="Caption para TikTok de máximo 150 caracteres optimizado para SEO semántico y debate en comentarios."
    )
    hashtags_tiktok: List[str] = Field(
        description="Lista de 3 a 5 hashtags estratégicos para TikTok mezclando nicho y alcance."
    )
    gancho_visual_portada: str = Field(
        description="Titular visual de portada de 4 a 6 palabras, impactante, para retención inicial en TikTok."
    )


class ListaClipsLocal(BaseModel):
    """Contenedor raíz de respuesta JSON estructurada para Ollama."""

    clips: List[ClipViralLocal] = Field(default_factory=list)
```

### 2.2 Validación y Sanitización Estricta en `_limpiar_y_parsear_json()`
La función `_limpiar_y_parsear_json()` procesa la respuesta textual del LLM y garantiza la total integridad del lote mediante las siguientes reglas:
1. **Limpieza de Bloques Think y Markdown:** Mediante `re.sub(r"<think>.*?</think>", "", texto, flags=re.IGNORECASE | re.DOTALL)` se remueven los pensamientos de razonamiento de modelos como Qwen 3 o DeepSeek-R1. Luego se eliminan delimitadores markdown.
2. **Extracción y Validación con `TypeAdapter`:** Emplea `_extraer_lista_json_con_esquema()` con `TypeAdapter(List[ClipViral])` para validar tipos nativos de Pydantic v2. Si el LLM devuelve un diccionario con clave raíz `clips`, extrae la lista interna.
3. **Validación Temporal de Coherencia:**
   - Convierte timestamps `inicio` y `fin` mediante `hhmmss_a_segundos()`.
   - Si `duracion_total` está definida, descarta clips cuyo inicio sea `>= duracion_total - 2` y acota `fin = min(fin, duracion_total)`.
   - Descarta clips con duración efectiva menor a 5 segundos (`duracion_clip < 5`).
4. **Normalización de Títulos y Metadatos:**
   - `titulo`: Trunca estrictamente a 60 caracteres (`titulo[:57].rstrip() + "..."`) garantizando que no sea cortado en la interfaz de YouTube Shorts.
   - `descripcion`: Si está vacía o carece de `#shorts`, inyecta el gancho y el llamado a la acción estándar (`#Shorts #Kicksazos #StreamColombia`).
   - `etiquetas`: Invoca `_normalizar_etiquetas()`, limpiando prefijos `#`, deduplicando y completando un lote SEO de 8 a 12 tags clave.
   - `caption_tiktok`: Invoca `_normalizar_caption_tiktok()`, limitando el texto a un máximo de 150 caracteres con llamado a debate.
   - `hashtags_tiktok`: Invoca `_normalizar_hashtags_tiktok()`, forzando entre 3 y 5 hashtags con `#` inicial.
   - `gancho_visual_portada`: Invoca `_normalizar_gancho_portada()`, forzando exactamente entre 4 y 6 palabras mayúsculas de alto impacto.
   - `subtitulos`: Invoca `_normalizar_subtitulos()`, eliminando emojis sin glifo (`_REGEX_EMOJIS_ASS`), ordenando cronológicamente, eliminando solapamientos temporales y llamando a `_dividir_segmento_subtitulo()` para asegurar que ningún bloque exceda 2 a 4 palabras (máximo 22 caracteres).

```python
def _limpiar_y_parsear_json(
    texto: str, duracion_total: Optional[float] = None, permitir_vacio: bool = False
) -> List[dict]:
    """Limpia posibles bloques markdown y valida la respuesta mediante regex y esquema tipado estricto."""
    datos = _extraer_lista_json_con_esquema(
        texto,
        TypeAdapter(List[ClipViral]),
        clave_dict="clips",
    )
    if not datos:
        if permitir_vacio:
            return []
        raise ValueError("La respuesta JSON de Gemini no contiene una lista válida de clips.")

    clips_validos: List[dict] = []
    for idx, item in enumerate(datos, start=1):
        if not isinstance(item, dict):
            continue
        try:
            ini_s = hhmmss_a_segundos(item["inicio"])
            fin_s = hhmmss_a_segundos(item["fin"])
        except (KeyError, ValueError, TypeError):
            continue

        if duracion_total is not None:
            if ini_s >= duracion_total - 2:
                continue
            fin_s = min(fin_s, duracion_total)

        duracion_clip = fin_s - ini_s
        if duracion_clip < 5:
            continue

        titulo_raw = str(item.get("titulo") or f"Clip Viral #{idx}").strip()
        if len(titulo_raw) > 60:
            titulo_raw = titulo_raw[:57].rstrip() + "..."

        gancho_raw = str(item.get("gancho") or "").strip()
        razon_raw = str(item.get("razon_viral") or "").strip()

        desc_raw = str(item.get("descripcion") or "").strip()
        if not desc_raw:
            desc_raw = (
                f"{gancho_raw or titulo_raw}\n"
                "¡Suscríbete a Kicksazos para los mejores momentos del streaming colombiano! "
                "#Shorts #Kicksazos #StreamColombia #KickColombia"
            )
        elif "#shorts" not in desc_raw.lower():
            desc_raw = f"{desc_raw}\n#Shorts #Kicksazos #StreamColombia"

        etiquetas_norm = _normalizar_etiquetas(item.get("etiquetas"))
        caption_tiktok_norm = _normalizar_caption_tiktok(
            item.get("caption_tiktok"),
            gancho_fallback=gancho_raw,
            titulo_fallback=titulo_raw,
        )
        hashtags_tiktok_norm = _normalizar_hashtags_tiktok(
            item.get("hashtags_tiktok"),
            etiquetas_fallback=etiquetas_norm,
        )
        gancho_portada_norm = _normalizar_gancho_portada(
            item.get("gancho_visual_portada"),
            titulo_fallback=titulo_raw,
            gancho_fallback=gancho_raw,
        )
        subtitulos_norm = _normalizar_subtitulos(item.get("subtitulos"), duracion_clip)

        clip_validado = ClipViral(
            id=len(clips_validos) + 1,
            titulo=titulo_raw,
            inicio=segundos_a_hhmmss(ini_s),
            fin=segundos_a_hhmmss(fin_s),
            gancho=gancho_raw,
            razon_viral=razon_raw,
            descripcion=desc_raw,
            etiquetas=etiquetas_norm,
            caption_tiktok=caption_tiktok_norm,
            hashtags_tiktok=hashtags_tiktok_norm,
            gancho_visual_portada=gancho_portada_norm,
            subtitulos=subtitulos_norm,
        )
        clips_validos.append(
            {
                **clip_validado.model_dump(),
                "duracion_segundos": int(round(duracion_clip)),
            }
        )

    if not clips_validos:
        raise ValueError("Ningún clip del JSON superó la validación temporal.")
    return clips_validos
```

---

## 3. Motor Híbrido Dual de Curaduría IA (Nube Gemini + Local Offline Whisper & Ollama)

### 3.1 Prompts Especializados de Curaduría
#### Prompt Nube Multimodal (Gemini Audio Directo):
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

#### Prompt Curaduría Local (Ollama Transcripción Textual):
```python
def _construir_prompt_ollama(transcripcion_bloque: str, duracion_bloque: float) -> str:
    """Construye el prompt especializado en curaduría viral para modelos locales Ollama."""
    dur_str = segundos_a_hhmmss(duracion_bloque)
    if duracion_bloque < 90:
        rango_clips = "1 a 3 clips virales (respetando la duración real disponible)"
        min_seg = max(5, min(15, int(duracion_bloque * 0.45)))
    elif duracion_bloque < 420:
        rango_clips = "2 a 5 clips virales"
        min_seg = 15
    else:
        rango_clips = "3 a 6 clips virales"
        min_seg = 18

    return (
        "Eres el editor jefe viral del canal Kicksazos (YouTube Shorts y TikTok de Kick Colombia: "
        "WestCOL, Blessd, La Liendra, eldomi, Yhap, streamers colombianos).\n"
        f"Analiza esta transcripción cronológica del audio (duración del bloque: {dur_str}) y selecciona {rango_clips}.\n\n"
        "REGLAS ESTRICTAS DE CURADURÍA:\n"
        "1. PRIORIZA momentos marcados con [🔥 ALTA INTENSIDAD VOCAL] (gritos, risas explosivas, peleas, clímax emocionales), confesiones polémicas o remates con retención inmediata.\n"
        f"2. Cada clip debe durar entre {min_seg} y 58 segundos (ideal 20–50s) y usar timestamps EXACTOS presentes en esta transcripción en formato HH:MM:SS.\n"
        "3. `gancho`: primeras palabras literales habladas en los primeros 2 segundos del clip seleccionado.\n"
        "4. `titulo`: máximo 60 caracteres, estilo streamer colombiano con alto CTR.\n"
        "5. `caption_tiktok`: <= 150 caracteres con gancho de debate; `hashtags_tiktok`: 3 a 5 hashtags; `etiquetas`: 8 a 12 tags SEO relevantes.\n"
        "6. Responde EXCLUSIVAMENTE un objeto JSON válido con la clave raíz `clips` siguiendo el esquema solicitado. NO incluyas subtítulos ni explicaciones fuera del JSON.\n\n"
        f"TRANSCRIPCIÓN:\n{transcripcion_bloque}"
    )
```

### 3.2 Configuración del Modo Nube (`gemini`)
- **Cascada de Modelos:** `MODELOS_CANDIDATOS = ['gemini-3.8-flash', 'gemini-3.7-flash', 'gemini-3.5-flash-lite']`.
- **Parámetros de Inferencia:** `temperature=0.20`, `HttpOptions.timeout = 600_000` ms (10 minutos).
- **Chunking Paralelo:** Si el audio supera los 30 minutos (`> 1800 s`), `_segmentar_audio_en_chunks()` divide el archivo con `ffmpeg -c copy` en bloques de 25 minutos (`1500 s`) con `60 s` de solapamiento. Los bloques se procesan concurrentemente en un `ThreadPoolExecutor(max_workers=3)`.
- **Deduplicación de Solapamientos:** `_deduplicar_clips_solapados()` detecta solapamientos `> 50%` entre clips de bloques adyacentes y resuelve la colisión mediante `_puntaje_calidad_clip()`, preservando el segmento con mayor duración, conteo de subtítulos y riqueza semántica.
- **Salto Inmediato ante Cuota Diaria (429):** La función `_es_error_cuota_diaria_free_tier()` detecta códigos `429` / `RESOURCE_EXHAUSTED`. Si se agota la cuota en un modelo, salta en `0.00 s` al siguiente sin esperas inútiles. Si se agota toda la cascada y `respaldo_local_auto=True`, activa `_correr_analisis_local()`.

### 3.3 Configuración del Modo Local 100% Offline (`local`)
- **Motor Whisper:** `faster-whisper` (`WHISPER_MODEL_SIZE = "medium"`, `compute_type = "int8"`, `device = "cpu"`, hilos = `cpu_count() - 2`).
- **Decodificación PCM Directa (`_decodificar_audio_pcm_16k`):** Decodifica el audio hacia un buffer float32 mono a 16.000 Hz mediante `ffmpeg -f f32le -ac 1 -ar 16000 -` y lo entrega a Whisper como un array NumPy zero-copy. Esto elimina por completo los bloqueos y fallos de segmentación de PyAV >= 19.
- **Detección de Picos Vocales RMS (`_calcular_energia_segmentos_audio`):** Extrae muestras PCM s16le a 12 kHz, calcula el valor RMS por segmento de habla y clasifica como pico de alta intensidad (`[🔥 ALTA INTENSIDAD VOCAL]`) cualquier segmento con energía `>= 1.65x` la mediana global.
- **Caché Persistente en Disco:** Almacena la transcripción con timestamps por palabra y picos vocales en `jobs/<job_id>/whisper_transcript.json`. Si el job se reinicia o re-ejecuta, la transcripción se carga instantáneamente sin recomputar.
- **Higiene de RAM:** Tras completar la transcripción, destruye la instancia de Whisper y ejecuta recolección de basura (`del model; gc.collect()`).
- **Inferencia con Ollama (`qwen3:14b`):** Envía la transcripción formateada al endpoint `/api/chat` en modo streaming con `temperature=0.25`, `num_ctx=8192` y esquema estructurado `ListaClipsLocal`. Para modelos pensantes como Qwen 3 o DeepSeek-R1, envía `think=False` o tolera fallback en caso de 400.
- **Subtítulos Directos desde Whisper:** `_construir_subtitulos_desde_whisper()` ensambla bloques de 2 a 4 palabras sincronizados a partir de los `word_timestamps` reales del audio para cada clip seleccionado por Ollama.
- **Descarga Forzada de RAM (`_descargar_modelo_ollama_ram`):** Ejecuta un POST a `/api/generate` con `{"keep_alive": 0}` para vaciar el modelo LLM de la memoria RAM del sistema antes de iniciar la renderización de video en FFmpeg.

---

## 4. Pipeline Multimedia (Descarga de Audio, FFmpeg VAAPI y Subtítulos `.ass`)

### 4.1 Ingesta de Audio y Resiliencia de Red
- **Extracción de Audio Ultraligero:** Genera un archivo MP3 mono a 12 kHz / 24 kbps (`temp_audio.mp3`) que reduce un stream de 4 horas a menos de 45 MB, acelerando la subida a Gemini y la lectura de Whisper.
- **Descarga Paralela:** Utiliza `yt-dlp` con `--concurrent-fragments 16`, `--newline` y `aria2c` en streams no-HLS.
- **Fallback por Streaming:** Si el archivo resultante es menor a 10 KB, extrae la URL directa con `yt-dlp -g` y descarga en streaming continuo mediante `ffmpeg -reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5 -rw_timeout 15000000`.
- **Entradas Locales:** Si el parámetro de entrada es un archivo existente en el sistema de archivos, omite `yt-dlp` y extrae directamente con FFmpeg sin alterar ni borrar el archivo original.

### 4.2 Renderizado Vertical 9:16 y Aceleración VAAPI
- **Encoder Hardware:** Detecta `/dev/dri/renderD128`. Si la prueba de codificación es exitosa, utiliza `h264_vaapi` con `-qp 23`. Si falla o surgen errores durante la codificación, conmuta automáticamente a CPU `libx264` con `-preset veryfast -crf 20`.
- **Composición de Video 9:16:** Divide la señal en dos ramas (`split=2[bg][fg]`). El fondo se escala y recorta a 360x640 con desenfoque bilineal (`boxblur=10:2`) reescalado a 1080x1920. El primer plano se escala proporcionalmente a 1080x1920 y se superpone centrado.
- **Posicionamiento Adaptativo de Marca de Agua:** Para videos 16:9 con barras negras, calcula `y = max(200, (H - h_fg)/2 - h - 24)`, posicionando el logo exactamente en el espacio desenfocado superior sin tapar el rostro del streamer ni colisionar con la interfaz de Shorts (`y >= 200`). Para videos nativos verticales, fija `y = 200`.
- **Caché e Invalidación de URLs:** `StreamUrlCache` almacena URLs directas con TTL de 4 horas e invalida automáticamente ante errores HTTP `403 Forbidden` o `410 Gone`, re-extrayendo los enlaces sin detener el pipeline.

### 4.3 Especificación del Archivo de Subtítulos `.ass` (v4.1 Safe Zone Centrada)
- **Resolución:** `PlayResX: 1080`, `PlayResY: 1920`.
- **Ajuste y Márgenes:** `WrapStyle: 0` (ajuste inteligente de línea superior larga / inferior corta).
- **Márgenes de Safe Zone:** `MarginL=80`, `MarginR=170` (compensa 90 px por la botonera derecha de YouTube Shorts), `MarginV=550` (eleva los subtítulos 550 px sobre la base, evitando la barra de título, canal y sonido).
- **Tipografía y Estilo:** `Montserrat ExtraBold`, tamaño `Fontsize=50`, espaciado `Spacing=1.2`, borde negro `Outline=5.0`, sombra `Shadow=3.0`, color blanco con rebote amarillo `PrimaryColour=&H00FFFFFF`, `SecondaryColour=&H0000FFFF`.
- **Efecto de Animación Pop-in:** `{\\fad(40,40)\\t(0,70,\\fscx105\\fscy105)\\t(70,140,\\fscx100\\fscy100)}` aplicado a cada línea.
- **Localización de Fuente:** Emplea `:fontsdir='<assets/fonts>'` en el filtro `subtitles` de FFmpeg para forzar la carga de `Montserrat-ExtraBold.ttf` sin requerir instalación global en `/usr/share/fonts`.

### 4.4 Renderizado en 1 Pasada Directa vs 2 Pasadas con Alineación
- **Modo Local (1 Pasada Directa):** Dado que los subtítulos provienen de los `word_timestamps` milimétricos de Whisper, se queman directamente en el corte 9:16 en una única pasada de codificación (`alinear_subtitulos=False`), reduciendo a la mitad el tiempo de render y el consumo de CPU.
- **Modo Nube (2 Pasadas con Micro-Alineación Fonética):**
  - **Paso 1:** Corta y compone el video en `raw_clip_<id>.mp4` sin subtítulos.
  - **Paso 2a:** Extrae el audio del clip recortado y lo envía a Gemini File API con `_construir_prompt_alineacion_subtitulos()` para corregir desviaciones fonéticas y obtener centisegundos exactos.
  - **Paso 2b:** Genera `subs_<id>.ass` y lo quema sobre `raw_clip` reutilizando el audio sin re-codificar (`-c:a copy`).

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
```

---

## 5. Orquestación Concurrente, Command Center Gradio y Publicación en YouTube Shorts

### 5.1 Orquestación Paralela y Seguridad Concurrente (`_orquestar_render_y_subida`)
La orquestación coordina la preparación de la fuente de video, el renderizado concurrente y la subida controlada mediante las siguientes garantías:
- **Renderizado Concurrente:** `ThreadPoolExecutor(max_workers=2)` procesa dos clips simultáneamente aprovechando la GPU VAAPI o multihilo en CPU.
- **Control de Estado Atómico (`state_lock`):** Protege las actualizaciones sobre la lista `clips` y sincroniza las escrituras en `jobs/<job_id>/clips.json` y `clips.json` en la raíz.
- **Exclusión Mutua en Subidas (`yt_lock`):** Serializa las peticiones hacia la API de YouTube para prevenir condiciones de carrera en el token OAuth y el conteo de cuota diaria.
- **Descarga Única de Video Fuente:** Para streams remotos de duración menor o igual a 1 hora, descarga la fuente completa en 1080p una sola vez (`descargar_video_fuente()`), permitiendo que los workers recorten localmente a máxima velocidad sin descargas fragmentadas redundantes.
- **Limpieza Automática de Jobs Antiguos (`_limpiar_jobs_antiguos`):** Al inicio de cada ejecución, escanea `CARPETA_JOBS` y elimina directorios temporales cuya fecha de modificación supere los 7 días (`dias_retencion=7`), preservando el job en curso.

### 5.2 Command Center Gradio v4.1 (`app_interfaz.py`)
La interfaz web opera en el puerto `7860` con un diseño broadcast oscuro (`#0b0e14`, `#121824`, verde neón Kick `#53fc18` y rojo YouTube `#ff0000`), estructurada en 4 pestañas operativas:
1. **⚡ 1. Centro de Mando:**
   - Selector de motor IA: Radio button interactivo `☁️ Gemini (Nube)` vs `💻 Local Offline (Whisper + Ollama)` que conmuta dinámicamente la visibilidad de los dropdowns de modelos sin recargar la página (`_alternar_motor_ui`).
   - Dropdown dinámico de modelos locales poblado en tiempo real desde `listar_modelos_ollama_disponibles()` (`127.0.0.1:11434`).
   - Checkbox de respaldo automático `respaldo_local_auto`.
   - Parámetros de publicación programada (`publishAt` en hora local Colombia `-05:00` con intervalo en horas).
   - **Panel Broadcast de Telemetría Multi-Hilo:** Renderizado en HTML/CSS con stepper iluminado de 4 fases (`1. Red & Audio`, `2. IA Paralela`, `3. Render VAAPI`, `4. YouTube Shorts`), pills de workers activos concurrentes con FPS y porcentaje, barra de etapa y barra global del job.
2. **🎬 2. Galería & Metadatos Duales:**
   - Tarjetas responsivas con reproductor de video de los clips generados.
   - Bloque **🔴 YouTube Shorts:** Título (máx 60 chars), Descripción con CTA y Etiquetas SEO en píldoras copiables con un solo clic.
   - Bloque **🎵 TikTok:** Gancho Visual de Portada (4–6 palabras), Caption optimizado para comentarios (máx 150 chars) y Hashtags de nicho.
   - Botones interactivos con JavaScript nativo (`navigator.clipboard`) que cambian visualmente a `✓ Copiado` durante 1.4 segundos.
3. **📜 3. Historial & Cuota YouTube:**
   - Medidor de cuota diaria en vivo con barra de progreso (límite 6 subidas en 24 horas móviles).
   - Tabla de auditoría con enlaces directos a YouTube Shorts (`https://youtube.com/shorts/<id>`), estado de privacidad y fecha de subida.
4. **📊 4. Estadísticas & Rendimiento (`calcular_estadisticas_sistema()`):**
   - Cálculo 100% offline a partir de `subidas_shorts.json` y los `clips.json` de todos los jobs históricos.
   - Métricas clave: Total de jobs procesados, clips virales curados, clips renderizados en 9:16, total subidos a YouTube, minutos totales de contenido analizado, modelo IA más utilizado y tasa de éxito global.

### 5.3 Publicación Automatizada en YouTube Shorts (`subir_shorts.py`)
- **Flujo OAuth 2.0 Headless:** Genera credenciales locales en `token.json` utilizando `InstalledAppFlow` con el scope estricto `https://www.googleapis.com/auth/youtube.upload`.
- **Trazabilidad por Hash de Cuenta (`obtener_hash_cuenta`):** Genera un hash SHA-256 corto a partir del refresh token o client ID para etiquetar cada subida en `subidas_shorts.json` sin almacenar credenciales en texto plano.
- **Auditoría de Cuota de 24 Horas Móviles (`verificar_cuota_diaria`):** Comprueba el número de subidas registradas en las 24 horas precedentes. Si `subidas_24h >= limite_diario (6)`, detiene nuevas peticiones y marca los clips restantes como `Pendiente por cuota diaria (6/24h)` para no quemar la cuota de la cuota del proyecto en Google Cloud Console.
- **Subida Reanudable con Backoff y Jitter:** Realiza subidas resumables (`MediaFileUpload(chunksize=1024*1024, resumable=True)`) con 5 intentos de reintento exponencial aleatorizado ante errores de red `5xx`.
- **Programación Futura (`publishAt`):** Soporta subidas en estado `private` programadas con fecha ISO 8601 UTC en el futuro, validadas con `_normalizar_publish_at_futuro()`.

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
    alinear_subtitulos: bool = True,
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
        es_archivo_local = False
        try:
            es_archivo_local = bool(str(url or "").strip()) and Path(url).is_file()
        except OSError:
            es_archivo_local = False

        # Para videos <= 1h descargar una sola vez evita múltiples conexiones HTTP/HLS lentas
        if es_archivo_local:
            _log(f"✓ Usando archivo multimedia local directo para render: {url}")
        elif duracion_total is None or duracion_total <= 3600:
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
        acepta_alinear_subs = _acepta_kwarg(procesar_clip_ffmpeg, "alinear_subtitulos")

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
                if acepta_alinear_subs:
                    kwargs_render["alinear_subtitulos"] = (
                        bool(alinear_subtitulos)
                        and clip.get("subtitulos_origen") != "whisper_word_timestamps"
                    )

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
```

---

## 6. Historial Operativo y Datos Reales del Repositorio

### 6.1 Historial Acumulado de Subidas (`subidas_shorts.json`)
El archivo `subidas_shorts.json` registra a la fecha **13 publicaciones exitosas** en YouTube Shorts, distribuidas en las siguientes sesiones operativas:
- **Sesión 2026-11-11 (Job Kick eldomi - Clips 1 a 5 + Prueba):**
  1. `LQIcG8bjKNQ` | `¡LO TIENEN ACORRALADO EN PLENO IRL! 😂👀 #Shorts` | 2026-11-11T00:20:13
  2. `omzV0U7F9RQ` | `¿CUÁNTO LE REBAJAMOS AL CAMARÓGRAFO? 😡📉` | 2026-11-11T00:44:20
  3. `W-ybt9xaGvU` | `¿PINTARME DE AZUL COMO BLESSD? NUNCA 🔵🧢` | 2026-11-11T00:45:25
  4. `KZB9ToKaeaU` | `LA VERDAD DE CUÁNTO PAGA KICK EN COLOMBIA 💸🇨🇴` | 2026-11-11T00:46:48
  5. `-Hd7i3Y4IUg` | `¡NUNCA SE METAN CON UN GOTA A GOTA! ⚠️💀` | 2026-11-11T00:47:41
  6. `H-fGRr_ySXo` | `¡CASI NOS MATAN EN PROVENZA EN PATINETA! 🛹💥` | 2026-11-11T00:48:43
  7. `FJnV_odrhC4` | `¡Momento Épico en Vivo! 😂 #Shorts` | 2026-11-11T20:49:06
- **Sesión 2026-11-13 (Job Kick eldomi v4.0 - Clips 1 a 6):**
  8. `eTHSeLRoIls` | `¡LA VERDAD DEL BANEO DE YHAP EN KICK! 🚨👀` | 2026-11-13T01:01:48
  9. `3OioPNyhfJM` | `¡CASI LO BANEAN EN VIVO POR ESTA PALABRA! 😳🚨` | 2026-11-13T01:02:25
  10. `3SDwOW9WwdY` | `¡ME ECHAN DE MI APARTAMENTO Y LA VOY A GRABAR! 😡🏠` | 2026-11-13T01:03:14
  11. `9SPg-zIO5jA` | `¡Se descontrolan todas en pleno stream! 😱🔥` | 2026-11-13T01:03:44
  12. `cpchsnUi0vs` | `El domi se desahoga y expone la dura realidad de la calle 💔` | 2026-11-13T01:04:19
  13. `iL_QH1Cw2XU` | `¡El domi se la tiró directo a Amilkar! 🥊👀` | 2026-11-13T01:04:57

### 6.2 Registro Canónico Actual (`clips.json`)
El archivo `clips.json` en la raíz contiene el último lote procesado (**8 clips virales**, renderizados en estado `OK` y marcados como `Pendiente por cuota diaria (6/24h)` para respetar el límite de YouTube):
1. **Clip #1 (00:01:58 -> 00:02:18, 20s):** `NINA DRAMA BANEA A HATER EN VIVO Y SE DESCONTROLA` | Archivo: `20261113_164425_kick_com_ninadrama_videos_01a1_clip_1.mp4` (8.6 MB)
2. **Clip #2 (00:06:23 -> 00:06:36, 13s):** `DAN IGE HACE RETUMBAR EL ARENA CON ESTE CANTICO` | Archivo: `20261113_164425_kick_com_ninadrama_videos_01a1_clip_2.mp4` (11 MB)
3. **Clip #3 (00:09:18 -> 00:09:44, 26s):** `¡LA DECLARACIÓN MÁS SALVAJE EN LA RUEDA DE PRENSA UFC!` | Archivo: `20261113_164425_kick_com_ninadrama_videos_01a1_clip_3.mp4` (19 MB)
4. **Clip #4 (00:25:03 -> 00:25:24, 21s):** `¡LOS PIELES CLARAS SÍ SABEN PELEAR! 🥊🔥 #UFC` | Archivo: `20261113_164425_kick_com_ninadrama_videos_01a1_clip_4.mp4` (14 MB)
5. **Clip #5 (00:31:28 -> 00:32:04, 36s):** `¡TE GANO EN CUALQUIER DEPORTE! 🏀♟️ #UFC` | Archivo: `20261113_164425_kick_com_ninadrama_videos_01a1_clip_5.mp4` (22 MB)
6. **Clip #6 (00:39:35 -> 00:40:35, 60s):** `NINA DRAMA REVELA SITUACIÓN EN ABU DHABI 🇦🇪⚠️` | Archivo: `20261113_164425_kick_com_ninadrama_videos_01a1_clip_6.mp4` (61 MB)
7. **Clip #7 (00:50:46 -> 00:51:06, 20s):** `¿POR QUÉ ARRESTARON A MERAB EN ABU DHABI? 🚨 NINA LO REVELA` | Archivo: `20261113_164425_kick_com_ninadrama_videos_01a1_clip_7.mp4` (9.5 MB)
8. **Clip #8 (00:57:10 -> 00:57:42, 32s):** `¿BBL O GIMNASIO? 🍑 NINA DRAMA CONFIESA SU PLAN A LOS 38 AÑOS` | Archivo: `20261113_164425_kick_com_ninadrama_videos_01a1_clip_8.mp4` (19 MB)

### 6.3 Inventario de Clips Finales en Disco (`clips_finales/`)
En `clips_finales/` residen actualmente 24 archivos de video MP4 procesados en 1080x1920 con marca de agua y subtítulos dinámicos quemados, listos para difusión o re-subida programada.

---

## 7. Suite de Pruebas Automatizadas (64 Tests / 100% Cobertura Operativa)

### 7.1 Resultado de Ejecución Oficial
Comando: `venv/bin/python -m unittest discover -s tests -v`
Resultado: **Ran 64 tests in 10.865s — OK (0 fallos, 0 errores)**.

### 7.2 Desglose por Módulo de Pruebas

#### 1. `tests/test_pipeline_v31.py` (16 Tests)
- `TestFase1ExtraccionAudio`:
  - `test_extraer_audio_primario_youtube_con_aria2c`: Descarga paralela 16 hilos con aria2c en URLs de YouTube.
  - `test_extraer_audio_fallback_si_archivo_menor_10kb`: Detección de salida corrupta <= 10 KB y conmutación a streaming directo FFmpeg.
  - `test_extraer_audio_stream_kick_directo_sin_aria2c`: Exclusión de aria2c en transmisiones HLS de Kick/Twitch.
- `TestFase2ResilienciaYChunking`:
  - `test_analizar_con_gemini_error_429_salto_inmediato`: Salto en 0s al siguiente modelo ante cuota agotada Free Tier.
  - `test_segmentar_audio_en_chunks_umbral_y_solape`: Segmentación de audios largos con solapamiento temporal.
  - `test_deduplicar_clips_solapados_fusion_y_prioridad`: Deduplicación determinista de clips solapados > 50%.
- `TestFase3PromptYCuraduriaDinamica`:
  - `test_prompt_curaduria_dinamica_sin_forzar_limites`: Validación del prompt de crecimiento y retención.
- `TestFase4SubtitulosYEstilosASS`:
  - `test_normalizar_subtitulos_auto_particion_bloques`: Auto-partición de frases largas en bloques de 2 a 4 palabras.
  - `test_generar_archivo_ass_estilos_y_popin`: Generación de cabecera ASS con animación pop-in y centisegundos.

#### 2. `tests/test_pipeline_v32.py` (14 Tests)
- `TestFase1TipografiaEmbebeYASS`:
  - `test_obtener_fuente_y_dir_subtitulos_prioriza_montserrat`: Detección de `Montserrat-ExtraBold.ttf` en `assets/fonts/`.
  - `test_generar_archivo_ass_safe_zone_y_mayusculas`: Verificación de `MarginV=550`, `MarginR=170` y MAYÚSCULAS.
  - `test_smoke_ffmpeg_libass_fontsdir_real`: Smoke test real de quemado FFmpeg con `:fontsdir=` local.
- `TestFase2TelemetriaDescargaYFFmpeg`:
  - `test_parsear_linea_progreso_descarga_ytdlp_y_aria2`: Parseo de regex de velocidad, porcentaje y ETA.
  - `test_ejecutar_comando_con_captura_parsea_progress_pipe1`: Captura y emisión de telemetría desde `-progress pipe:1`.
- `TestFase2Y3OrquestadorCLIYGradio`:
  - `test_renderizador_progreso_cli_tty_y_no_tty`: Barra visual CLI sin parpadeos y logs formateados.
  - `test_construir_panel_telemetria_html_sanitizacion`: Prevención de vulnerabilidades XSS en la interfaz web.

#### 3. `tests/test_pipeline_v40.py` (19 Tests)
- `TestTarea1AudioUltraLigero`:
  - `test_extraer_audio_ultraligero_12k_mono_24k`: Validación de parámetros `-vn -ac 1 -ar 12000 -b:a 24k`.
- `TestTarea2ChunkingYGeminiParalelo`:
  - `test_segmentar_audio_en_chunks_umbral_1800_y_bloques_1500_solape_60`: Validación de bloques de 25 min para audios > 30 min.
  - `test_analizar_con_gemini_paralelo_telemetria_bloques_activos_y_porcentaje`: Monitoreo de bloques activos en concurrencia.
- `TestTarea3AlineacionYRenderDosPasos`:
  - `test_alinear_subtitulos_exito_cascada_429_y_limpieza`: Micro-alineación fonética por Gemini File API sobre `raw_clip`.
  - `test_procesar_clip_ffmpeg_dos_pasos_con_subtitulos_y_limpieza_raw`: Render en 2 pasos y eliminación segura de `raw_clip`.
- `TestTarea4OrquestacionParalela`:
  - `test_orquestar_render_y_subida_paralelo_clips_activos_y_locks`: Render de 2 clips concurrentes con `state_lock` y `yt_lock`.
- `TestTarea5CancelacionYLimpieza`:
  - `test_ejecutar_paso_con_telemetria_timeout_polling_y_keyboard_interrupt`: Cancelación instantánea con Ctrl+C sin procesos huérfanos.
  - `test_limpiar_jobs_antiguos_retencion_y_exclusion_job_actual`: Poda de directorios con más de 7 días de antigüedad.
- `TestTarea6InterfazCommandCenterYEstadisticas`:
  - `test_calcular_estadisticas_sistema_y_panel_html_offline`: Métricas agregadas del panel de rendimiento sin red.
  - `test_integracion_telemetria_v40_a_gradio_sin_keyerror_y_cierre_limpio`: Estabilidad de la interfaz Gradio ante eventos de cierre.

#### 4. `tests/test_pipeline_v41.py` (15 Tests)
- `TestFase1SubtitulosOpticosV41`:
  - `test_generar_archivo_ass_wrap_y_safe_zone_v41`: Validación de `WrapStyle: 0`, `Fontsize=50`, `MarginL=80`, `MarginR=170`, `MarginV=550`.
  - `test_smoke_ffmpeg_smart_wrap_optico_real`: Comprobación de renderizado real FFmpeg con ajuste de línea óptico.
- `TestFase2MotorLocalWhisperYOllama`:
  - `test_decodificar_audio_pcm_16k_salida_float32`: Decodificación directa mono float32 16 kHz evitando PyAV.
  - `test_transcribir_audio_whisper_local_cache_telemetria_y_gc`: Transcripción local Whisper, caché y recolección de RAM.
  - `test_calcular_energia_segmentos_audio_picos_vocales_reales`: Detección de picos vocales >= 1.65x mediana global.
  - `test_analizar_con_ollama_secuencial_y_descarga_ram`: Consulta estructurada a Ollama y descarga de RAM con `keep_alive=0`.
  - `test_construir_subtitulos_desde_whisper_bloques_2_a_4_palabras`: Construcción de subtítulos desde `word_timestamps`.
  - `test_listar_modelos_ollama_prioriza_y_maneja_offline`: Listado tolerante ante servidor Ollama activo u offline.
  - `test_asegurar_modelo_ollama_error_offline_y_pull_auto`: Verificación y descarga automática de modelos faltantes.
- `TestFase3RenderPasadaUnicaHibrida`:
  - `test_procesar_clip_ffmpeg_pasada_unica_local_omite_raw_clip`: Render en 1 sola pasada directa sin `raw_clip` en modo local.
  - `test_smoke_ffmpeg_pasada_unica_real_con_marca_de_agua_y_ass`: Smoke test real de 1 pasada con marca de agua y subtítulos.
  - `test_orquestar_render_y_subida_archivo_local_no_se_borra`: Preservación intacta de archivos fuente locales en disco.
- `TestFase4OrquestadorCLIGradioV41`:
  - `test_ejecutar_pipeline_completo_local_sin_gemini_api_key`: Ejecución completa offline sin variable `GEMINI_API_KEY`.
  - `test_ejecutar_pipeline_completo_respaldo_auto_429`: Conmutación automática a motor local ante error 429 de Gemini.
  - `test_gradio_ui_v41_selector_hibrido_y_telemetria`: Verificación de componentes interactivos de la interfaz Gradio v4.1.
  - `test_cli_main_flags_local_y_formateo_barra`: Compatibilidad de argumentos CLI (`--motor`, `--modelo-local`).

---

## 8. Deuda Técnica Resuelta, Limitaciones Conocidas y Roadmap

### 8.1 Deuda Técnica Resuelta al 100%
1. **Desacoplamiento Total de APIs Propietarias:** Soporte 100% offline mediante Whisper medium int8 y Ollama, eliminando bloqueos por cuota 429 en Gemini Free Tier.
2. **Eliminación del Bug de PyAV >= 19:** Decodificación FFmpeg float32 directa que erradica cuelgues de audio en faster-whisper.
3. **Aceleración de Renderizado Local:** Reducción del tiempo de renderizado a la mitad en modo local mediante pasada única directa (sin `raw_clip` intermedio).
4. **Optimización de Memoria RAM (16 GB):** Secuenciamiento estricto con descarga de Whisper (`del model; gc.collect()`) y descarga de Ollama (`keep_alive=0`) antes de invocar los encoders FFmpeg.
5. **Centrado Óptico y Safe Zone de Subtítulos (v4.1):** `WrapStyle: 0`, `MarginL=80`, `MarginR=170` y `MarginV=550`, garantizando legibilidad total sin solapamiento con botones de YouTube Shorts ni TikTok.
6. **Aislamiento Multi-Job y Cero Residuos:** Contextos independientes en `jobs/<job_id>/` y poda automática de jobs con antigüedad superior a 7 días.
7. **Seguridad Absoluta contra XSS:** Sanitización exhaustiva con `html.escape()` en todos los componentes dinámicos de Gradio.
8. **Tolerancia a Fallos de Red en VODs:** Re-intento automático con invalidación de caché ante errores HTTP 403/410 de URLs firmadas.

### 8.2 Limitaciones Conocidas
- **Cuota de YouTube Data API v3:** La cuota por defecto del proyecto en Google Cloud (~10.000 unidades diarias) restringe las subidas a ~6 videos cada 24 horas móviles.
- **Tiempo de Inferencia CPU en Whisper Medium:** En procesadores de 4 núcleos (como el Ryzen 5 7520U), transcribir un stream de 2 horas en CPU toma aproximadamente 8 a 12 minutos (alrededor de 10x-15x tiempo real).
- **VODs de Kick con Segmentos Privados:** Si el streamer silencia o elimina fragmentos por copyright, `yt-dlp` puede reportar advertencias en fragmentos específicos que FFmpeg descarta automáticamente.

### 8.3 Guía de Comandos Rápidos para Operadores y Agentes
```bash
# Activar entorno de trabajo
cd /home/bastiboy/clips_automation
source venv/bin/activate

# Ejecución de suite de pruebas unitarias completa (64 tests)
venv/bin/python -m unittest discover -s tests -v

# Pipeline en Modo Nube Gemini (Análisis + Render + Subida Privada a YouTube)
venv/bin/python pipeline_viral_clips.py "https://kick.com/eldomi/videos/<uuid>"

# Pipeline en Modo 100% Local Offline (Whisper + Ollama qwen3:14b, sin GEMINI_API_KEY)
venv/bin/python pipeline_viral_clips.py "https://kick.com/eldomi/videos/<uuid>" --motor local --modelo-local qwen3:14b

# Procesamiento de archivo de video local sin subida (sólo clips locales 9:16)
venv/bin/python pipeline_viral_clips.py "/ruta/a/mi_video.mp4" --motor local --sin-subida

# Iniciar Command Center Web (Gradio Studio v4.1)
venv/bin/python app_interfaz.py
# Acceder vía navegador local en http://127.0.0.1:7860

# Re-renderizar un clip específico manualmente
venv/bin/python procesar_video_universal.py "<URL|archivo.mp4>" 00:15:20 00:15:55 1
```
