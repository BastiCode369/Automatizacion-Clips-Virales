# **Documento de Contexto Técnico: Proyecto Kicksazos**

Este documento contiene la especificación completa del estado actual, arquitectura, soluciones implementadas y hoja de ruta del sistema de automatización de video para el canal **Kicksazos**. Está diseñado para servir como base de conocimiento para nuevos ciclos de desarrollo e integración con modelos de IA.

---

# **1\. Proyecto Actual (Overview y Objetivos)**

El proyecto **Kicksazos** es una plataforma automatizada de procesamiento de video diseñada para transformar contenido audiovisual en formato horizontal (16:9) a clips verticales optimizados para formato corto (9:16), como YouTube Shorts, TikTok y Instagram Reels.

## **Objetivos Principales**

* **Extracción Automatizada:** Descarga eficiente de videos fuente en alta resolución a partir de URLs o términos de búsqueda.  
* **Reencuadre Inteligente:** Conversión de 16:9 a 9:16 manteniendo el enfoque principal, añadiendo un fondo desenfocado (*background blur*) y aplicando marcas de agua personalizadas.  
* **Análisis de Contenido mediante IA:** Integración de modelos del lenguaje avanzados para segmentación, identificación de momentos clave y selección de *timestamps* óptimos.  
* **Procesamiento Eficiente:** Generación de piezas finales de video sin degradación de calidad y con tiempos de renderizado reducidos.

---

# **2\. Stack Tecnológico**

El entorno del sistema está configurado para garantizar compatibilidad multiplataforma y un procesamiento multimedia de alto rendimiento.

| Componente | Tecnología / Herramienta | Función Principal |
| :---- | :---- | :---- |
| **Sistema Operativo** | Linux (Ubuntu 22.04 LTS / Debian 12\) / Windows WSL2 | Entorno de ejecución y procesamiento paralelo |
| **Lenguaje Base** | Python 3.10+ | Lógica de la aplicación y scripts de automatización |
| **Motor de Video** | FFmpeg (v5.0+) | Procesamiento de video, filtros compositivos y renderizado |
| **Descarga de Medios** | `yt-dlp` | Extracción de streams de video y audio desde plataformas externas |
| **Modelo de IA** | Gemini 3.8 Flash API | Análisis de transcripciones, segmentación temporal y contextual |
| **Interfaz de Usuario** | Gradio | Dashboard web interactivo para control del pipeline |

---

# **3\. Estructura del Pipeline**

El pipeline de procesamiento ejecuta un flujo secuencial automatizado desde el ingreso del enlace fuente hasta la exportación del archivo final.

```
[URL Fuente] ➔ [yt-dlp (Descarga)] ➔ [Gemini 3.8 Flash (Análisis/Timestamps)] 
                                                │
[Video Final (9:16)] ⬅ [FFmpeg (Filtros & Marca de Agua)] ↵
```

## **Paso a Paso del Flujo de Trabajo**

1. **Ingreso e Ingesta:**  
   * La URL del video es capturada e ingerida a través de la interfaz Gradio o línea de comandos.  
   * `yt-dlp` extrae el stream de mayor calidad disponible (limitado a 1080p para optimizar tiempos de render).  
2. **Análisis de Contenido y Segmentación (Gemini 3.8 Flash):**  
   * Se extrae la pista de audio o el archivo de subtítulos/transcripción.  
   * El texto extraído se procesa mediante el modelo **Gemini 3.8 Flash** utilizando un prompt especializado que identifica:  
     * Puntos de enganche (*hooks*) narrativos.  
     * Marcas de tiempo de inicio y fin (*timestamps*) para clips de 30 a 60 segundos.  
     * Títulos conceptuales para cada segmento.  
3. **Reencuadre y Edición de Video (FFmpeg):**  
   * El clip seleccionado se procesa mediante una cadena de filtros complejos (`filter_complex`) en **FFmpeg**:  
     * **Capa Trasera (Fondo):** El video original de 16:9 se escala para cubrir el lienzo vertical de `1080x1920` y se le aplica un desenfoque gaussiano significativo (`boxblur` / `gblur`).  
     * **Capa Frontal (Contenido Principal):** El video original se escala manteniendo su relación de aspecto original para encajar en el centro de la pantalla.  
     * **Superposición de Marca de Agua:** Se aplica una capa PNG transparente con el logo/marca de *Kicksazos* posicionada estratégicamente (usualmente en la zona superior o inferior del marco central).

---

# **4\. Problemas Resueltos y Desafíos Técnicos**

Durante el desarrollo del sistema se identificaron y solucionaron diversos cuellos de botella técnicos:

## **A. Gestión de Errores de API (503 / 404\)**

* **Problema:** Fallos intermitentes en la API de Gemini (código 503 por sobrecarga del servicio) y errores 404 al consultar endpoints no existentes o recursos eliminados.  
* **Solución:** Implementación de un patrón de reintentos (*exponential backoff*) con *jitter* para las llamadas de la API de Gemini, junto con un sistema de *fallback* que conmuta a modelos alternativos si persiste el error 503\.

## **B. Remoción e Inserción Limpia de Subtítulos**

* **Problema:** Los videos originales a menudo contenían subtítulos incrustados (*hardcoded*) que chocaban visualmente con el fondo desenfocado y el nuevo encuadre.  
* **Solución:** Se implementó una máscara de recorte previa en FFmpeg para aislar la zona libre de texto fuente antes de aplicar la escala y el desenfoque del fondo.

## **C. Conflictos de Dependencias con PyAV**

* **Problema:** Incompatibilidades de binding entre Python, las librerías `PyAV` y la instalación del sistema de FFmpeg, lo que provocaba cierres inesperados (*segmentation faults*) durante la decodificación de cuadros.  
* **Solución:** Se sustituyó la decodificación directa por `PyAV` invocando directamente el binario compilado de `FFmpeg` a través del módulo `subprocess` de Python con manejo asíncrono de pipes de entrada/salida.

---

# **5\. Interfaz Gráfica (Gradio Dashboard)**

El control del sistema se realiza a través de un panel web desarrollado en **Gradio**, diseñado para minimizar la intervención manual.

## **Componentes de la Interfaz**

* **Panel de Ingesta:** Campo de texto para la URL fuente y selector del número deseado de clips a generar.  
* **Visor de Timestamps:** Tabla interactiva que muestra los clips propuestos por Gemini 3.8 Flash, permitiendo ajustar manualmente los puntos de inicio/fin si es necesario.  
* **Controles de Estilo:** Selectores para activar/desactivar la marca de agua, ajustar el nivel de desenfoque del fondo (*blur intensity*) y seleccionar presets de relación de aspecto.  
* **Previsualización y Exportación:** Reproductor de video integrado para revisar los clips 9:16 generados y botón de descarga directa del archivo final.

---

# **6\. Objetivos Futuros**

La siguiente fase de desarrollo se centrará en la automatización de extremo a extremo (*end-to-end*).

* **Subida Automatizada a YouTube Shorts:** Integración directa con la **YouTube Data API v3** para programar y publicar los clips generados automáticamente.  
* **Generación de Metadatos por IA:** Utilizar Gemini para crear automáticamente:  
  * Títulos optimizados para SEO y clickbait moderado.  
  * Descripciones enriquecidas con marcadores de tiempo.  
  * Etiquetas (*hashtags*) de alta tendencia según la temática del video.  
* **Generación de Subtítulos Dinámicos (Burned-in Captions):** Integración de Whisper para transcripción precisa y renderizado de texto animado estilo *Karaoke* sobre el video final.

