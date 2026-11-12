#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from pathlib import Path
BASE_DIR = Path(__file__).resolve().parent

from dotenv import load_dotenv
load_dotenv(BASE_DIR / ".env")

import glob
import json
import os
import re
import sys
from datetime import datetime
from typing import Any, Dict, Generator, List, Optional, Tuple

import gradio as gr

from pipeline_viral_clips import (
    CARPETA_JOBS,
    CARPETA_SALIDA,
    MODELOS_CANDIDATOS,
    _guardar_y_sincronizar_clips,
    analizar_con_gemini,
    crear_contexto_job,
    descargar_video_fuente,
    extraer_audio,
    hhmmss_a_segundos,
    obtener_duracion_media,
    procesar_clip_ffmpeg,
    segundos_a_hhmmss,
)
from subir_shorts import (
    HISTORIAL_SUBIDAS_FILE,
    autenticar_youtube,
    cargar_historial_subidas,
    subir_short,
)

CUSTOM_CSS = """
:root, .dark, body, .gradio-container {
    --body-background-fill: #0f0f13 !important;
    --background-fill-primary: #14141b !important;
    --background-fill-secondary: #1b1b26 !important;
    --border-color-primary: #2a2a3c !important;
    --border-color-accent: #8b5cf6 !important;
    --color-accent: #8b5cf6 !important;
    --color-accent-soft: rgba(139, 92, 246, 0.18) !important;
    --body-text-color: #f3f4f6 !important;
    --body-text-color-subdued: #9ca3af !important;
    background-color: #0f0f13 !important;
    color: #f3f4f6 !important;
    font-family: 'Inter', 'Segoe UI', Roboto, system-ui, sans-serif !important;
}

.kicksazos-header {
    background: linear-gradient(135deg, #151521 0%, #1e1035 55%, #0e2215 100%);
    border: 1px solid #2e2e42;
    border-left: 5px solid #53fc18;
    border-radius: 14px;
    padding: 20px 26px;
    margin-bottom: 16px;
    box-shadow: 0 10px 30px rgba(0, 0, 0, 0.55);
}

.kicksazos-title {
    font-size: 1.85rem;
    font-weight: 800;
    letter-spacing: -0.02em;
    margin: 0 0 6px 0;
    background: linear-gradient(90deg, #53fc18 0%, #a855f7 55%, #ec4899 100%);
    -webkit-background-clip: text;
    -webkit-text-fill-color: transparent;
}

.kicksazos-subtitle {
    color: #d1d5db;
    font-size: 0.96rem;
    margin: 0;
}

.badge-row {
    display: flex;
    flex-wrap: wrap;
    gap: 10px;
    margin-top: 12px;
}

.k-badge {
    display: inline-flex;
    align-items: center;
    gap: 6px;
    padding: 4px 12px;
    border-radius: 999px;
    font-size: 0.78rem;
    font-weight: 700;
    text-transform: uppercase;
    letter-spacing: 0.04em;
}

.k-badge-kick {
    background: rgba(83, 252, 24, 0.14);
    color: #53fc18;
    border: 1px solid rgba(83, 252, 24, 0.45);
}

.k-badge-purple {
    background: rgba(139, 92, 246, 0.18);
    color: #c4b5fd;
    border: 1px solid rgba(139, 92, 246, 0.45);
}

.k-badge-yt {
    background: rgba(239, 68, 68, 0.16);
    color: #fca5a5;
    border: 1px solid rgba(239, 68, 68, 0.45);
}

.status-banner {
    border-radius: 12px;
    padding: 14px 18px;
    margin: 8px 0;
    font-size: 0.92rem;
    line-height: 1.5;
    border: 1px solid #2e2e42;
    background: #14141d;
}

.status-banner.ok {
    border-left: 4px solid #53fc18;
    background: linear-gradient(90deg, rgba(83, 252, 24, 0.10) 0%, #14141d 100%);
}

.status-banner.warn {
    border-left: 4px solid #f59e0b;
    background: linear-gradient(90deg, rgba(245, 158, 11, 0.12) 0%, #14141d 100%);
}

.status-banner.err {
    border-left: 4px solid #ef4444;
    background: linear-gradient(90deg, rgba(239, 68, 68, 0.14) 0%, #14141d 100%);
}

.status-banner.run {
    border-left: 4px solid #8b5cf6;
    background: linear-gradient(90deg, rgba(139, 92, 246, 0.16) 0%, #14141d 100%);
}

.clip-card {
    background: #14141d;
    border: 1px solid #2b2b3d;
    border-radius: 12px;
    padding: 16px;
    margin-bottom: 12px;
}

.clip-card h4 {
    margin: 0 0 8px 0;
    color: #53fc18;
    font-size: 1.08rem;
}

.clip-meta-grid {
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
    gap: 8px;
    margin: 10px 0;
}

.clip-meta-item {
    background: #1b1b28;
    border: 1px solid #2d2d42;
    border-radius: 8px;
    padding: 8px 12px;
    font-size: 0.84rem;
}

.tag-pill {
    display: inline-block;
    background: rgba(139, 92, 246, 0.16);
    color: #ddd6fe;
    border: 1px solid rgba(139, 92, 246, 0.35);
    border-radius: 6px;
    padding: 2px 8px;
    margin: 2px 4px 2px 0;
    font-size: 0.76rem;
}

button.primary {
    background: linear-gradient(90deg, #7c3aed 0%, #9333ea 100%) !important;
    border: 1px solid #a855f7 !important;
    color: #ffffff !important;
    font-weight: 700 !important;
    box-shadow: 0 4px 16px rgba(139, 92, 246, 0.35) !important;
}

button.primary:hover {
    background: linear-gradient(90deg, #53fc18 0%, #22c55e 100%) !important;
    color: #09090b !important;
    border-color: #53fc18 !important;
}
"""


def _banner_html(titulo: str, detalle: str, nivel: str = "run") -> str:
    iconos = {
        "ok": "✅",
        "warn": "⚠️",
        "err": "❌",
        "run": "⚡",
    }
    icono = iconos.get(nivel, "⚡")
    return (
        f'<div class="status-banner {nivel}">'
        f"<strong>{icono} {titulo}</strong><br/>"
        f"<span>{detalle}</span>"
        f"</div>"
    )


def _cargar_clips_actuales() -> List[Dict[str, Any]]:
    ruta = BASE_DIR / "clips.json"
    if ruta.exists():
        try:
            with open(ruta, "r", encoding="utf-8") as f:
                data = json.load(f)
                if isinstance(data, list):
                    return data
        except Exception:
            pass
    return []


def _indexar_subidas_por_archivo() -> Dict[str, Dict[str, Any]]:
    historial = cargar_historial_subidas(HISTORIAL_SUBIDAS_FILE)
    mapa: Dict[str, Dict[str, Any]] = {}
    for item in historial:
        nombre = item.get("archivo")
        if nombre:
            mapa[nombre] = item
    return mapa


def construir_tarjetas_galeria_html(clips: List[Dict[str, Any]]) -> str:
    """Construye el panel visual HTML con los metadatos, gancho, duración y enlace a YouTube de cada clip."""
    mapa_subidas = _indexar_subidas_por_archivo()
    if not clips:
        archivos = sorted(CARPETA_SALIDA.glob("*.mp4"))
        if not archivos:
            return _banner_html(
                "Sin clips renderizados aún",
                "Ejecuta el pipeline en la pestaña 'Extractor & Pipeline' para generar clips 9:16.",
                "warn",
            )
        tarjetas = []
        for ruta in archivos:
            nombre = ruta.name
            dur = obtener_duracion_media(ruta)
            dur_str = f"{int(round(dur))}s" if dur else "N/D"
            subida = mapa_subidas.get(nombre)
            if subida and subida.get("url"):
                yt_badge = (
                    f'<a href="{subida["url"]}" target="_blank" '
                    f'style="color:#53fc18;font-weight:700;text-decoration:underline;">'
                    f'🔒 Subido en Privado ({subida.get("youtube_id")})</a>'
                )
            else:
                yt_badge = '<span style="color:#9ca3af;">Local (Sin registro de subida)</span>'
            tarjetas.append(
                f'<div class="clip-card">'
                f"<h4>🎬 {nombre}</h4>"
                f'<div class="clip-meta-grid">'
                f'<div class="clip-meta-item"><strong>Duración:</strong> {dur_str}</div>'
                f'<div class="clip-meta-item"><strong>Estado YouTube:</strong> {yt_badge}</div>'
                f"</div></div>"
            )
        return "".join(tarjetas)

    tarjetas = []
    for clip in clips:
        cid = clip.get("id", "?")
        titulo = clip.get("titulo", f"Clip #{cid}")
        inicio = clip.get("inicio", "00:00:00")
        fin = clip.get("fin", "00:00:00")
        try:
            dur_s = int(round(hhmmss_a_segundos(fin) - hhmmss_a_segundos(inicio)))
        except Exception:
            dur_s = clip.get("duracion_segundos", 0)

        gancho = clip.get("gancho", "—")
        razon = clip.get("razon_viral", "—")
        descripcion = clip.get("descripcion", "—")
        etiquetas = clip.get("etiquetas") or []

        ruta_local = clip.get("archivo_local")
        if ruta_local:
            nombre_archivo = Path(ruta_local).name
        else:
            candidatos = list(CARPETA_SALIDA.glob(f"*clip_{cid}.mp4"))
            nombre_archivo = candidatos[0].name if candidatos else f"clip_{cid}.mp4"

        subida = mapa_subidas.get(nombre_archivo)

        yt_url = clip.get("youtube_url") or (subida.get("url") if subida else None)
        yt_status = clip.get("youtube_status") or (
            "Subido (Privado)" if yt_url else "Renderizado Localmente"
        )

        if yt_url:
            yt_html = (
                f'<span class="k-badge k-badge-kick">🔒 {yt_status}</span> '
                f'<a href="{yt_url}" target="_blank" '
                f'style="color:#53fc18;font-weight:700;margin-left:8px;text-decoration:underline;">'
                f"Abrir en YouTube Shorts ↗</a>"
            )
        else:
            yt_html = f'<span class="k-badge k-badge-purple">{yt_status}</span>'

        pills_html = "".join(f'<span class="tag-pill">#{t}</span>' for t in etiquetas)

        tarjetas.append(
            f'<div class="clip-card">'
            f"<h4>🔥 Clip #{cid}: {titulo}</h4>"
            f'<div style="margin-bottom:8px;">{yt_html}</div>'
            f'<div class="clip-meta-grid">'
            f'<div class="clip-meta-item">⏱️ <strong>Timestamps:</strong> {inicio} ➔ {fin} ({dur_s}s)</div>'
            f'<div class="clip-meta-item">📁 <strong>Archivo:</strong> <code>{nombre_archivo}</code></div>'
            f"</div>"
            f'<p style="margin:6px 0;">🎯 <strong>Hook (2s):</strong> <em>"{gancho}"</em></p>'
            f'<p style="margin:6px 0;color:#d1d5db;">🧠 <strong>Gatillo Viral:</strong> {razon}</p>'
            f'<p style="margin:6px 0;color:#9ca3af;font-size:0.86rem;">📝 <strong>Descripción SEO:</strong> {descripcion}</p>'
            f'<div style="margin-top:8px;">{pills_html}</div>'
            f"</div>"
        )
    return "".join(tarjetas)


def obtener_datos_galeria() -> Tuple[List[Tuple[str, str]], Optional[str], str, List[Dict[str, Any]]]:
    """Obtiene los videos en clips_finales/ y arma la galería junto con sus metadatos."""
    clips = _cargar_clips_actuales()
    mapa_clips = {str(c.get("id")): c for c in clips}
    mapa_subidas = _indexar_subidas_por_archivo()

    items_galeria: List[Tuple[str, str]] = []
    CARPETA_SALIDA.mkdir(parents=True, exist_ok=True)
    archivos_mp4 = sorted(
        list(CARPETA_SALIDA.glob("*.mp4")),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )

    # Priorizar los clips del último análisis referenciados en clips.json
    archivos_recientes: List[Path] = []
    for c in clips:
        ruta_c = c.get("archivo_local")
        if ruta_c and Path(ruta_c).exists():
            archivos_recientes.append(Path(ruta_c).resolve())
        else:
            candidatos = list(CARPETA_SALIDA.glob(f"*clip_{c.get('id')}.mp4"))
            if candidatos:
                archivos_recientes.append(candidatos[0].resolve())

    lista_final = [str(p) for p in archivos_recientes] if archivos_recientes else [str(p) for p in archivos_mp4]

    for ruta in lista_final:
        nombre = Path(ruta).name
        match = re.search(r"(?:^|_)clip_(\d+)\.mp4$", nombre)
        cid_match = match.group(1) if match else None

        info_clip = mapa_clips.get(cid_match) if cid_match else None
        subida = mapa_subidas.get(nombre)

        if info_clip:
            dur = info_clip.get("duracion_segundos")
            if not dur:
                try:
                    dur = int(
                        round(
                            hhmmss_a_segundos(info_clip["fin"])
                            - hhmmss_a_segundos(info_clip["inicio"])
                        )
                    )
                except Exception:
                    dur = 0
            estado_yt = "🔒 YT Privado" if (info_clip.get("youtube_url") or subida) else "💾 Local"
            leyenda = f"#{cid_match} {info_clip.get('titulo')} ({dur}s) | {estado_yt}"
        else:
            dur_f = obtener_duracion_media(ruta)
            dur_txt = f"{int(round(dur_f))}s" if dur_f else ""
            estado_yt = "🔒 YT Privado" if subida else "💾 Local"
            leyenda = f"{nombre} {dur_txt} | {estado_yt}".strip()

        items_galeria.append((ruta, leyenda))

    primer_video = lista_final[0] if lista_final else None
    html_tarjetas = construir_tarjetas_galeria_html(clips)
    return items_galeria, primer_video, html_tarjetas, clips


def obtener_tabla_historial() -> Tuple[List[List[Any]], str]:
    """Lee subidas_shorts.json y devuelve filas para gr.Dataframe y un resumen HTML."""
    historial = cargar_historial_subidas(HISTORIAL_SUBIDAS_FILE)
    if not historial:
        html = _banner_html(
            "Historial de subidas vacío",
            f"Aún no se registran videos en {HISTORIAL_SUBIDAS_FILE.name}. Se poblará automáticamente tras el pipeline o subida manual.",
            "warn",
        )
        return [], html

    filas: List[List[Any]] = []
    for item in reversed(historial):
        filas.append(
            [
                item.get("fecha_subida", "—"),
                item.get("archivo", "—"),
                item.get("titulo", "—"),
                item.get("youtube_id", "—"),
                item.get("url", "—"),
                item.get("privacidad", "private"),
                ", ".join((item.get("etiquetas") or [])[:6]),
            ]
        )

    html = _banner_html(
        f"Registro de Subidas Activo ({len(historial)} Shorts en Privado)",
        "Todos los videos fueron cargados con <code>privacyStatus='private'</code>, <code>categoryId='24'</code> y <code>madeForKids=False</code> listos para programación estratégica.",
        "ok",
    )
    return filas, html


def ejecutar_pipeline_gradio(
    url: str,
    modelo_preferido: str,
    subir_auto_yt: bool,
    solo_analisis: bool,
    gemini_key: str,
    progress=gr.Progress(track_tqdm=False),
) -> Generator[Tuple[str, str, Optional[str], Any, List[Tuple[str, str]], str, List[List[Any]], str], None, None]:
    """Ejecuta el pipeline paso a paso actualizando barra de progreso, logs en tiempo real, galería e historial."""
    logs: List[str] = []

    def log(msg: str):
        marca = datetime.now().strftime("%H:%M:%S")
        linea = f"[{marca}] {msg}"
        print(linea)
        logs.append(linea)
        return "\n".join(logs)

    url_limpia = (url or "").strip()
    gal_items, vid_prev, gal_html, clips_prev = obtener_datos_galeria()
    hist_filas, hist_html = obtener_tabla_historial()

    if not url_limpia:
        banner = _banner_html(
            "URL Requerida",
            "Por favor ingresa una URL válida de YouTube, Kick o Twitch antes de iniciar el pipeline.",
            "err",
        )
        yield banner, log("ERROR: URL vacía."), vid_prev, clips_prev, gal_items, gal_html, hist_filas, hist_html
        return

    if gemini_key and gemini_key.strip():
        os.environ["GEMINI_API_KEY"] = gemini_key.strip()

    if not os.environ.get("GEMINI_API_KEY"):
        banner = _banner_html(
            "Falta GEMINI_API_KEY",
            "Configura GEMINI_API_KEY en el archivo .env o ingrésala en el campo opcional.",
            "err",
        )
        yield banner, log("ERROR: GEMINI_API_KEY no encontrada."), vid_prev, clips_prev, gal_items, gal_html, hist_filas, hist_html
        return

    ctx = crear_contexto_job(url_limpia)
    log(f"Iniciando Job {ctx.job_id} en {ctx.job_dir}")

    audio_temp = None
    fuente_local = None

    try:
        # FASE 1: Extracción de audio en su job_dir
        progress(0.08, desc="Fase 1/4: Extrayendo pista de audio ligera con yt-dlp...")
        banner = _banner_html(
            "Fase 1/4 en ejecución: Extracción de Audio",
            f"Descargando y comprimiendo audio mono 16kHz desde: <code>{url_limpia}</code> en <code>jobs/{ctx.job_id}</code>",
            "run",
        )
        yield banner, log(f"Iniciando extracción de audio para job {ctx.job_id} desde: {url_limpia}"), vid_prev, clips_prev, gal_items, gal_html, hist_filas, hist_html

        audio_temp = extraer_audio(url_limpia, job_dir=ctx.job_dir)
        duracion = obtener_duracion_media(audio_temp)
        dur_str = segundos_a_hhmmss(duracion) if duracion else "Desconocida"
        log(f"✓ Audio extraído correctamente ({audio_temp}) | Duración: {dur_str}")

        # FASE 2: Inferencia con Gemini
        progress(0.30, desc=f"Fase 2/4: Analizando narrativa viral con {modelo_preferido}...")
        banner = _banner_html(
            "Fase 2/4 en ejecución: Análisis Viral con Gemini IA",
            f"Subiendo audio a File API (polling hasta ACTIVE) y detectando hooks/polémica colombiana con cascada liderada por <code>{modelo_preferido}</code>...",
            "run",
        )
        yield banner, "\n".join(logs), vid_prev, clips_prev, gal_items, gal_html, hist_filas, hist_html

        clips = analizar_con_gemini(
            audio_temp,
            duracion_total=duracion,
            modelo_preferido=modelo_preferido,
            job_dir=ctx.job_dir,
        )
        log(f"✓ Gemini detectó {len(clips)} clips virales con metadatos SEO completos.")
        for c in clips:
            log(
                f"  • Clip #{c['id']}: {c['titulo']} [{c['inicio']} -> {c['fin']}] | Hook: {c['gancho'][:45]}..."
            )

        if solo_analisis:
            progress(1.0, desc="¡Análisis completado!")
            gal_items, vid_prev, gal_html, _ = obtener_datos_galeria()
            banner = _banner_html(
                "Análisis Viral Completado (Modo Solo Análisis)",
                f"Se generaron {len(clips)} propuestas con SEO en <code>jobs/{ctx.job_id}/clips.json</code> y <code>clips.json</code>.",
                "ok",
            )
            yield banner, "\n".join(logs), vid_prev, clips, gal_items, gal_html, hist_filas, hist_html
            return

        # FASE 3: Descarga base y Renderizado FFmpeg 9:16
        progress(0.55, desc="Fase 3/4: Preparando fuente de video en 1080p...")
        banner = _banner_html(
            "Fase 3/4 en ejecución: Renderizado Vertical 9:16 con FFmpeg",
            "Aplicando fast-seek (-ss antes de -i), fondo 360p con boxblur, encuadre central y marca de agua @Kicksazos...",
            "run",
        )
        yield banner, log("Preparando fuente de video para corte local rápido..."), vid_prev, clips, gal_items, gal_html, hist_filas, hist_html

        if duracion is None or duracion <= 3600:
            try:
                destino_fuente = ctx.job_dir / "temp_source.mp4"
                fuente_local = descargar_video_fuente(url_limpia, destino=destino_fuente)
                log(f"✓ Video fuente descargado en {fuente_local}")
            except Exception as e:
                log(f"[AVISO] Se usará seek remoto directo ({e})")
                fuente_local = None

        entrada_render = fuente_local or url_limpia

        youtube_client = None
        if subir_auto_yt:
            log("Autenticando cliente de YouTube Data API v3 (token.json)...")
            try:
                youtube_client = autenticar_youtube(interactivo=False)
                log("✓ Autenticación con YouTube exitosa.")
            except Exception as e:
                log(f"[AVISO] No se pudo autenticar YouTube ({e}). Se continuará con renderizado local.")
                youtube_client = None

        total_clips = len(clips)
        for idx, clip in enumerate(clips, start=1):
            cid = clip.get("id")
            frac = 0.60 + (0.35 * (idx - 1) / max(1, total_clips))
            progress(frac, desc=f"Renderizando Clip #{cid}/{total_clips}: {clip.get('titulo')}...")
            yield banner, log(
                f"Renderizando Clip #{cid} ({clip.get('inicio')} -> {clip.get('fin')})..."
            ), vid_prev, clips, gal_items, gal_html, hist_filas, hist_html

            ruta_clip = procesar_clip_ffmpeg(
                entrada_render,
                clip.get("inicio"),
                clip.get("fin"),
                cid,
                job_id=ctx.job_id,
            )
            clip["archivo_local"] = ruta_clip
            log(f"✓ Clip #{cid} renderizado en: {ruta_clip}")

            if subir_auto_yt and youtube_client is not None:
                progress(
                    frac + (0.15 / max(1, total_clips)),
                    desc=f"Subiendo Clip #{cid} a YouTube Shorts (Privado)...",
                )
                yield _banner_html(
                    f"Fase 4/4: Subiendo Clip #{cid} a YouTube Shorts (Privado)",
                    f"Inyectando SEO: <strong>{clip.get('titulo')}</strong> | Categoría 24 | madeForKids=False",
                    "run",
                ), log(f"Subiendo {os.path.basename(ruta_clip)} a YouTube en privado..."), ruta_clip, clips, gal_items, gal_html, hist_filas, hist_html

                try:
                    info_yt = subir_short(
                        youtube=youtube_client,
                        ruta_video=ruta_clip,
                        titulo=clip.get("titulo", f"Clip {cid}"),
                        descripcion=clip.get("descripcion", ""),
                        etiquetas=clip.get("etiquetas", []),
                        privacidad="private",
                        clip_id=cid,
                        guardar_registro=True,
                    )
                    clip["youtube_id"] = info_yt["youtube_id"]
                    clip["youtube_url"] = info_yt["url"]
                    clip["youtube_status"] = "Subido (Privado)"
                    log(f"✓ Subido a YouTube Shorts: {info_yt['url']}")
                except Exception as e:
                    clip["youtube_status"] = f"Error subida ({str(e)[:60]})"
                    log(f"[AVISO] Falló subida a YouTube para Clip #{cid}: {e}")
            elif not subir_auto_yt:
                clip["youtube_status"] = "Subida desactivada por usuario"
            else:
                clip["youtube_status"] = "Local (Sin token activo)"

        _guardar_y_sincronizar_clips(clips, job_dir=ctx.job_dir)

        progress(1.0, desc="¡Pipeline E2E completado con éxito!")
        gal_items, vid_prev, gal_html, _ = obtener_datos_galeria()
        hist_filas, hist_html = obtener_tabla_historial()

        subidos_ok = sum(1 for c in clips if c.get("youtube_url"))
        banner_final = _banner_html(
            "¡Pipeline Kicksazos Completado con Éxito!",
            f"Job: <code>{ctx.job_id}</code>. Se renderizaron <strong>{len(clips)} clips verticales 9:16</strong> en <code>clips_finales/</code> "
            f"y se subieron <strong>{subidos_ok} videos en privado</strong> a YouTube Shorts.",
            "ok",
        )
        yield banner_final, log(f"✓ Flujo E2E finalizado sin errores para job {ctx.job_id}."), vid_prev, clips, gal_items, gal_html, hist_filas, hist_html

    except Exception as e:
        gal_items, vid_prev, gal_html, clips_prev = obtener_datos_galeria()
        hist_filas, hist_html = obtener_tabla_historial()
        banner_err = _banner_html(
            "Alerta de Ejecución en el Pipeline",
            f"Se produjo una excepción controlada: <code>{str(e)}</code>",
            "err",
        )
        yield banner_err, log(f"[ERROR] {str(e)}"), vid_prev, clips_prev, gal_items, gal_html, hist_filas, hist_html
    finally:
        if audio_temp and os.path.exists(audio_temp):
            try:
                os.remove(audio_temp)
            except OSError:
                pass
        if fuente_local and os.path.exists(fuente_local):
            try:
                os.remove(fuente_local)
            except OSError:
                pass


def seleccionar_clip_galeria(evt: gr.SelectData) -> Optional[str]:
    """Al hacer clic en un elemento de la galería, lo carga en el reproductor principal."""
    try:
        val = evt.value
        if isinstance(val, dict):
            video_info = val.get("video") or val.get("image") or val
            if isinstance(video_info, dict) and "path" in video_info:
                return video_info["path"]
        if isinstance(val, (list, tuple)) and val:
            return str(val[0])
    except Exception:
        pass
    return None


def obtener_tema_oscuro():
    return gr.themes.Soft(
        primary_hue="violet",
        secondary_hue="emerald",
        neutral_hue="slate",
    ).set(
        body_background_fill="#0f0f13",
        body_background_fill_dark="#0f0f13",
        block_background_fill="#14141d",
        block_background_fill_dark="#14141d",
        block_border_color="#2a2a3c",
        block_border_color_dark="#2a2a3c",
        input_background_fill="#1b1b28",
        input_background_fill_dark="#1b1b28",
        button_primary_background_fill="#8b5cf6",
        button_primary_background_fill_hover="#7c3aed",
        button_primary_text_color="#ffffff",
    )


def construir_interfaz() -> gr.Blocks:
    items_iniciales, primer_video, html_inicial, clips_iniciales = obtener_datos_galeria()
    filas_historial_init, html_historial_init = obtener_tabla_historial()

    with gr.Blocks(title="Kicksazos Studio | AI Viral Shorts Suite") as demo:
        # Header Corporativo
        gr.HTML(
            """
            <div class="kicksazos-header">
                <div style="display:flex; justify-content:space-between; align-items:flex-start; flex-wrap:wrap; gap:12px;">
                    <div>
                        <h1 class="kicksazos-title">⚡ KICKSAZOS STUDIO</h1>
                        <p class="kicksazos-subtitle">Suite autónoma de IA para curaduría, renderizado vertical 9:16 y auto-upload de clips virales colombianos.</p>
                    </div>
                </div>
                <div class="badge-row">
                    <span class="k-badge k-badge-kick">🟢 Kick / Twitch / YouTube IRL</span>
                    <span class="k-badge k-badge-purple">🤖 Gemini 3.8 Flash + Cascada Resiliente</span>
                    <span class="k-badge k-badge-yt">🔴 Auto-Upload YouTube Shorts (Private)</span>
                </div>
            </div>
            """
        )

        with gr.Tabs():
            # PESTAÑA 1: PIPELINE E2E
            with gr.Tab("🚀 1. Extractor & Pipeline"):
                estado_banner = gr.HTML(
                    _banner_html(
                        "Sistema Listo",
                        "Ingresa una URL de Kick o YouTube para extraer los mejores momentos con IA y renderizarlos en 9:16.",
                        "ok",
                    )
                )

                with gr.Row():
                    with gr.Column(scale=5):
                        url_input = gr.Textbox(
                            label="URL del Stream o VOD (Kick, YouTube, Twitch)",
                            placeholder="https://kick.com/video/... o https://youtube.com/watch?v=...",
                            lines=1,
                        )
                    with gr.Column(scale=3):
                        modelo_dropdown = gr.Dropdown(
                            label="Modelo Gemini Principal (Cascada con Fallback)",
                            choices=MODELOS_CANDIDATOS,
                            value=MODELOS_CANDIDATOS[0],
                        )

                with gr.Row():
                    with gr.Column(scale=2):
                        subir_yt_chk = gr.Checkbox(
                            label="Subir automáticamente a YouTube Shorts (Privado)",
                            value=True,
                            info="Usa OAuth instalado para publicar en modo 'private' con SEO completo",
                        )
                    with gr.Column(scale=2):
                        solo_analisis_chk = gr.Checkbox(
                            label="Solo Análisis (clips.json)",
                            value=False,
                            info="Detecta timestamps y hooks sin renderizar videos",
                        )
                    with gr.Column(scale=4):
                        api_key_input = gr.Textbox(
                            label="GEMINI_API_KEY (Opcional si ya está en .env)",
                            placeholder="Sobrescribir API Key en runtime...",
                            type="password",
                        )

                btn_ejecutar = gr.Button(
                    "⚡ EJECUTAR PIPELINE COMPLETO (AUDIO ➔ GEMINI ➔ FFMPEG 9:16 ➔ YOUTUBE)",
                    variant="primary",
                    size="lg",
                )

                with gr.Row():
                    with gr.Column(scale=5):
                        salida_logs = gr.Textbox(
                            label="Consola de Ejecución en Tiempo Real",
                            lines=16,
                            max_lines=24,
                            interactive=False,
                        )
                    with gr.Column(scale=3):
                        video_preview = gr.Video(
                            label="Último Short Renderizado",
                            value=primer_video,
                            interactive=False,
                            height=420,
                        )

                with gr.Accordion("Ver JSON Estructurado Generado (clips.json)", open=False):
                    clips_json_view = gr.JSON(
                        value=clips_iniciales,
                        label="Esquema Validado Pydantic",
                    )

            # PESTAÑA 2: GALERÍA DE CLIPS (9:16)
            with gr.Tab("🎬 2. Galería de Clips (9:16)"):
                with gr.Row():
                    btn_refrescar_galeria = gr.Button("🔄 Refrescar Galería y Metadatos", size="sm")

                with gr.Row():
                    with gr.Column(scale=5):
                        galeria_videos = gr.Gallery(
                            label="Shorts Disponibles en clips_finales/",
                            value=items_iniciales,
                            columns=[3],
                            rows=[2],
                            object_fit="contain",
                            height=520,
                            allow_preview=False,
                        )
                    with gr.Column(scale=3):
                        reproductor_galeria = gr.Video(
                            label="Reproductor Vertical 9:16",
                            value=primer_video,
                            height=520,
                        )

                tarjetas_galeria_html = gr.HTML(html_inicial)

            # PESTAÑA 3: HISTORIAL DE SUBIDAS A YOUTUBE
            with gr.Tab("📈 3. Historial de Subidas"):
                with gr.Row():
                    btn_refrescar_historial = gr.Button("🔄 Recargar Historial de Subidas", size="sm")

                resumen_historial_html = gr.HTML(html_historial_init)

                tabla_historial = gr.Dataframe(
                    headers=[
                        "Fecha Subida",
                        "Archivo Local",
                        "Título SEO",
                        "ID YouTube",
                        "URL Directa Short",
                        "Privacidad",
                        "Tags Clave (Extracto)",
                    ],
                    datatype=["str", "str", "str", "str", "str", "str", "str"],
                    value=filas_historial_init,
                    interactive=False,
                    wrap=True,
                )

        # Eventos principales
        btn_ejecutar.click(
            fn=ejecutar_pipeline_gradio,
            inputs=[
                url_input,
                modelo_dropdown,
                subir_yt_chk,
                solo_analisis_chk,
                api_key_input,
            ],
            outputs=[
                estado_banner,
                salida_logs,
                video_preview,
                clips_json_view,
                galeria_videos,
                tarjetas_galeria_html,
                tabla_historial,
                resumen_historial_html,
            ],
        )

        galeria_videos.select(
            fn=seleccionar_clip_galeria,
            inputs=None,
            outputs=[reproductor_galeria],
        )

        btn_refrescar_galeria.click(
            fn=obtener_datos_galeria,
            inputs=None,
            outputs=[
                galeria_videos,
                reproductor_galeria,
                tarjetas_galeria_html,
                clips_json_view,
            ],
        )

        btn_refrescar_historial.click(
            fn=obtener_tabla_historial,
            inputs=None,
            outputs=[tabla_historial, resumen_historial_html],
        )

    return demo


demo = construir_interfaz()

if __name__ == "__main__":
    CARPETA_SALIDA.mkdir(parents=True, exist_ok=True)
    demo.launch(
        server_name="127.0.0.1",
        server_port=7860,
        inbrowser=False,
        allowed_paths=[str(CARPETA_SALIDA), str(BASE_DIR / "assets"), str(CARPETA_JOBS)],
        theme=obtener_tema_oscuro(),
        css=CUSTOM_CSS,
    )
