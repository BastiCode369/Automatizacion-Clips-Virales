#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from pathlib import Path
BASE_DIR = Path(__file__).resolve().parent

from dotenv import load_dotenv
load_dotenv(BASE_DIR / ".env")

import html
import json
import os
import re
from datetime import datetime
from typing import Any, Dict, Generator, List, Optional, Tuple

import gradio as gr

from pipeline_viral_clips import (
    CARPETA_JOBS,
    CARPETA_SALIDA,
    MODELOS_CANDIDATOS,
    ejecutar_pipeline_completo,
    hhmmss_a_segundos,
    obtener_duracion_media,
)
from subir_shorts import (
    HISTORIAL_SUBIDAS_FILE,
    cargar_historial_subidas,
    verificar_cuota_diaria,
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

.tag-pill-tt {
    display: inline-block;
    background: rgba(0, 242, 234, 0.12);
    color: #67e8f9;
    border: 1px solid rgba(0, 242, 234, 0.35);
    border-radius: 6px;
    padding: 2px 8px;
    margin: 2px 4px 2px 0;
    font-size: 0.76rem;
}

.platform-grid {
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(280px, 1fr));
    gap: 12px;
    margin-top: 12px;
}

.platform-box {
    background: #181824;
    border: 1px solid #2d2d42;
    border-radius: 10px;
    padding: 12px;
}

.platform-box.yt-box {
    border-top: 3px solid #ef4444;
}

.platform-box.tt-box {
    border-top: 3px solid #00f2ea;
}

.platform-title {
    margin: 0 0 10px 0;
    font-size: 0.94rem;
    font-weight: 700;
    color: #f3f4f6;
}

.copy-field {
    margin-bottom: 10px;
}

.copy-field:last-child {
    margin-bottom: 0;
}

.copy-header {
    display: flex;
    justify-content: space-between;
    align-items: center;
    margin-bottom: 4px;
    font-size: 0.78rem;
    color: #9ca3af;
    font-weight: 600;
}

.copy-btn {
    background: #252538;
    color: #e5e7eb;
    border: 1px solid #3b3b54;
    border-radius: 6px;
    padding: 2px 8px;
    font-size: 0.72rem;
    font-weight: 600;
    cursor: pointer;
}

.copy-btn:hover {
    background: #53fc18;
    color: #09090b;
    border-color: #53fc18;
}

.copy-value {
    background: #101018;
    border: 1px solid #262638;
    border-radius: 6px;
    padding: 8px 10px;
    font-size: 0.83rem;
    color: #f3f4f6;
    white-space: pre-wrap;
    word-break: break-word;
    user-select: all;
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


def _sanitizar_url_href(url: Any) -> str:
    """Valida que una URL sea http(s) y la escapa para atributos href."""
    url_str = str(url or "").strip()
    if url_str.startswith(("https://", "http://")):
        return html.escape(url_str, quote=True)
    return "#"


def _banner_html(titulo: str, detalle: str, nivel: str = "run") -> str:
    iconos = {
        "ok": "✅",
        "warn": "⚠️",
        "err": "❌",
        "run": "⚡",
    }
    nivel_seguro = nivel if nivel in iconos else "run"
    icono = iconos[nivel_seguro]
    titulo_seguro = html.escape(str(titulo), quote=True)
    detalle_seguro = html.escape(str(detalle), quote=True)
    return (
        f'<div class="status-banner {nivel_seguro}">'
        f"<strong>{icono} {titulo_seguro}</strong><br/>"
        f"<span>{detalle_seguro}</span>"
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


def _campo_copiable_html(etiqueta: str, valor_escapado: str, extra_html: str = "") -> str:
    """Renderiza un campo de metadatos listo para copiar al portapapeles con contenido ya escapado."""
    etiqueta_esc = html.escape(etiqueta, quote=True)
    return (
        f'<div class="copy-field">'
        f'<div class="copy-header"><span>{etiqueta_esc}</span>'
        f'<button type="button" class="copy-btn">📋 Copiar</button></div>'
        f'<div class="copy-value">{valor_escapado}</div>'
        f"{extra_html}"
        f"</div>"
    )


def construir_tarjetas_galeria_html(clips: List[Dict[str, Any]]) -> str:
    """Construye el panel visual HTML escapado con bloques diferenciados para YouTube Shorts y TikTok."""
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
            nombre_esc = html.escape(ruta.name, quote=True)
            dur = obtener_duracion_media(ruta)
            dur_str = html.escape(f"{int(round(dur))}s" if dur else "N/D", quote=True)
            subida = mapa_subidas.get(ruta.name)
            if subida and subida.get("url"):
                href_seguro = _sanitizar_url_href(subida["url"])
                yt_id_esc = html.escape(str(subida.get("youtube_id", "")), quote=True)
                yt_badge = (
                    f'<a href="{href_seguro}" target="_blank" rel="noopener noreferrer" '
                    f'style="color:#53fc18;font-weight:700;text-decoration:underline;">'
                    f"🔒 Subido en Privado ({yt_id_esc})</a>"
                )
            else:
                yt_badge = '<span style="color:#9ca3af;">Local (Sin registro de subida)</span>'
            tarjetas.append(
                f'<div class="clip-card">'
                f"<h4>🎬 {nombre_esc}</h4>"
                f'<div class="clip-meta-grid">'
                f'<div class="clip-meta-item"><strong>Duración:</strong> {dur_str}</div>'
                f'<div class="clip-meta-item"><strong>Estado YouTube:</strong> {yt_badge}</div>'
                f"</div></div>"
            )
        return "".join(tarjetas)

    tarjetas = []
    for clip in clips:
        cid = clip.get("id", "?")
        cid_esc = html.escape(str(cid), quote=True)
        titulo_raw = str(clip.get("titulo") or f"Clip #{cid}")
        titulo_esc = html.escape(titulo_raw, quote=True)
        inicio = clip.get("inicio", "00:00:00")
        fin = clip.get("fin", "00:00:00")
        try:
            dur_s = int(round(hhmmss_a_segundos(fin) - hhmmss_a_segundos(inicio)))
        except Exception:
            dur_s = clip.get("duracion_segundos", 0)

        inicio_esc = html.escape(str(inicio), quote=True)
        fin_esc = html.escape(str(fin), quote=True)
        dur_esc = html.escape(str(dur_s), quote=True)

        gancho_esc = html.escape(str(clip.get("gancho") or "—"), quote=True)
        razon_esc = html.escape(str(clip.get("razon_viral") or "—"), quote=True)
        descripcion_esc = html.escape(str(clip.get("descripcion") or "—"), quote=True)
        etiquetas = clip.get("etiquetas") or []
        etiquetas_csv = ", ".join(str(t).strip() for t in etiquetas if str(t).strip())
        etiquetas_csv_esc = html.escape(etiquetas_csv or "—", quote=True)

        gancho_portada_esc = html.escape(str(clip.get("gancho_visual_portada") or "—"), quote=True)
        caption_tt_esc = html.escape(str(clip.get("caption_tiktok") or "—"), quote=True)
        hashtags_tt_raw = clip.get("hashtags_tiktok") or []
        hashtags_tt_norm = [
            (str(t).strip() if str(t).strip().startswith("#") else f"#{str(t).strip()}")
            for t in hashtags_tt_raw
            if str(t).strip()
        ]
        hashtags_tt_esc = html.escape(" ".join(hashtags_tt_norm) or "—", quote=True)

        ruta_local = clip.get("archivo_local")
        if ruta_local:
            nombre_archivo = Path(ruta_local).name
        else:
            candidatos = list(CARPETA_SALIDA.glob(f"*clip_{cid}.mp4"))
            nombre_archivo = candidatos[0].name if candidatos else f"clip_{cid}.mp4"
        nombre_archivo_esc = html.escape(str(nombre_archivo), quote=True)

        subida = mapa_subidas.get(nombre_archivo)

        yt_url = clip.get("youtube_url") or (subida.get("url") if subida else None)
        yt_status = clip.get("youtube_status") or (
            "Subido (Privado)" if yt_url else "Renderizado Localmente"
        )
        yt_status_esc = html.escape(str(yt_status), quote=True)

        if yt_url:
            href_seguro = _sanitizar_url_href(yt_url)
            yt_html = (
                f'<span class="k-badge k-badge-kick">🔒 {yt_status_esc}</span> '
                f'<a href="{href_seguro}" target="_blank" rel="noopener noreferrer" '
                f'style="color:#53fc18;font-weight:700;margin-left:8px;text-decoration:underline;">'
                f"Abrir en YouTube Shorts ↗</a>"
            )
        else:
            clase_badge = "k-badge-yt" if "error" in str(yt_status).lower() or "no renderizado" in str(yt_status).lower() else "k-badge-purple"
            yt_html = f'<span class="k-badge {clase_badge}">{yt_status_esc}</span>'

        pills_yt_html = (
            '<div style="margin-top:6px;">'
            + "".join(
                f'<span class="tag-pill">#{html.escape(str(t).lstrip("#"), quote=True)}</span>'
                for t in etiquetas
                if str(t).strip()
            )
            + "</div>"
        )
        pills_tt_html = (
            '<div style="margin-top:6px;">'
            + "".join(
                f'<span class="tag-pill-tt">{html.escape(t, quote=True)}</span>'
                for t in hashtags_tt_norm
            )
            + "</div>"
        )

        bloque_youtube = (
            f'<div class="platform-box yt-box">'
            f'<div class="platform-title">🔴 YouTube Shorts</div>'
            + _campo_copiable_html("Título", titulo_esc)
            + _campo_copiable_html("Descripción", descripcion_esc)
            + _campo_copiable_html("Etiquetas", etiquetas_csv_esc, pills_yt_html)
            + "</div>"
        )
        bloque_tiktok = (
            f'<div class="platform-box tt-box">'
            f'<div class="platform-title">🎵 TikTok</div>'
            + _campo_copiable_html("Gancho Visual de Portada", gancho_portada_esc)
            + _campo_copiable_html("Caption TikTok", caption_tt_esc)
            + _campo_copiable_html("Hashtags TikTok", hashtags_tt_esc, pills_tt_html)
            + "</div>"
        )

        tarjetas.append(
            f'<div class="clip-card">'
            f"<h4>🔥 Clip #{cid_esc}: {titulo_esc}</h4>"
            f'<div style="margin-bottom:8px;">{yt_html}</div>'
            f'<div class="clip-meta-grid">'
            f'<div class="clip-meta-item">⏱️ <strong>Timestamps:</strong> {inicio_esc} ➔ {fin_esc} ({dur_esc}s)</div>'
            f'<div class="clip-meta-item">📁 <strong>Archivo:</strong> <code>{nombre_archivo_esc}</code></div>'
            f"</div>"
            f'<p style="margin:6px 0;">🎯 <strong>Hook (2s):</strong> <em>"{gancho_esc}"</em></p>'
            f'<p style="margin:6px 0;color:#d1d5db;">🧠 <strong>Gatillo Viral:</strong> {razon_esc}</p>'
            f'<div class="platform-grid">{bloque_youtube}{bloque_tiktok}</div>'
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
    """Lee subidas_shorts.json y devuelve filas escapadas para gr.Dataframe y un resumen HTML seguro."""
    historial = cargar_historial_subidas(HISTORIAL_SUBIDAS_FILE)
    cuota = verificar_cuota_diaria()
    if not historial:
        resumen_html = _banner_html(
            "Historial de subidas vacío",
            f"Aún no se registran videos en {HISTORIAL_SUBIDAS_FILE.name}. "
            f"Cuota últimas 24h: {cuota['subidas_24h']}/{cuota['limite']}.",
            "warn",
        )
        return [], resumen_html

    filas: List[List[Any]] = []
    for item in reversed(historial):
        tags_str = ", ".join(str(t) for t in (item.get("etiquetas") or [])[:6])
        filas.append(
            [
                html.escape(str(item.get("fecha_subida") or "—"), quote=True),
                html.escape(str(item.get("archivo") or "—"), quote=True),
                html.escape(str(item.get("titulo") or "—"), quote=True),
                html.escape(str(item.get("youtube_id") or "—"), quote=True),
                html.escape(str(item.get("url") or "—"), quote=True),
                html.escape(str(item.get("privacidad") or "private"), quote=True),
                html.escape(str(item.get("publish_at") or "Inmediato"), quote=True),
                html.escape(str(item.get("cuenta_id") or "—"), quote=True),
                html.escape(tags_str or "—", quote=True),
            ]
        )

    nivel_cuota = "ok" if cuota["permitido"] else "warn"
    resumen_html = _banner_html(
        f"Registro de Subidas Activo ({len(historial)} Shorts | Cuota 24h: {cuota['subidas_24h']}/{cuota['limite']})",
        "Todos los videos se cargan con privacyStatus='private', categoryId='24' y madeForKids=False. "
        f"Cupos disponibles en las últimas 24h: {cuota['restantes']}.",
        nivel_cuota,
    )
    return filas, resumen_html


def ejecutar_pipeline_gradio(
    url: str,
    modelo_preferido: str,
    subir_auto_yt: bool,
    solo_analisis: bool,
    gemini_key: str,
    publish_at_inicio: str = "",
    intervalo_horas: int | float = 0,
    progress=gr.Progress(track_tqdm=False),
) -> Generator[Tuple[str, str, Optional[str], Any, List[Tuple[str, str]], str, List[List[Any]], str], None, None]:
    """Consume el orquestador único ejecutar_pipeline_completo() y actualiza Gradio en tiempo real."""
    logs: List[str] = []

    def registrar_log(msg: str) -> None:
        marca = datetime.now().strftime("%H:%M:%S")
        for linea_raw in str(msg).splitlines() or [""]:
            if linea_raw.strip():
                linea = f"[{marca}] {linea_raw}"
                print(linea)
                logs.append(linea)

    def _reportar_progreso(valor: float, desc: str) -> None:
        if progress is not None:
            try:
                progress(valor, desc=desc)
            except Exception:
                pass

    if gemini_key and gemini_key.strip():
        os.environ["GEMINI_API_KEY"] = gemini_key.strip()

    gal_items, vid_prev, gal_html, clips_prev = obtener_datos_galeria()
    hist_filas, hist_html = obtener_tabla_historial()

    titulos_fase = {
        "audio": "Fase 1/4 en ejecución: Extracción de Audio",
        "gemini": "Fase 2/4 en ejecución: Análisis Viral con Gemini IA",
        "fuente": "Fase 3/4 en ejecución: Preparación de Fuente de Video",
        "render": "Fase 3/4 en ejecución: Renderizado Vertical 9:16 con FFmpeg",
        "youtube": "Fase 4/4 en ejecución: Subida a YouTube Shorts",
        "completado": "¡Pipeline Kicksazos Completado con Éxito!",
        "error": "Alerta de Ejecución en el Pipeline",
    }

    for estado in ejecutar_pipeline_completo(
        url=url,
        modelo_preferido=modelo_preferido,
        solo_analisis=solo_analisis,
        subir_youtube=subir_auto_yt,
        publish_at_inicio=(publish_at_inicio or "").strip() or None,
        intervalo_horas=intervalo_horas or 0,
        on_log=registrar_log,
    ):
        fase = estado.get("fase", "run")
        progreso = float(estado.get("progreso", 0.0))
        mensaje = str(estado.get("mensaje", ""))
        clips_estado = estado.get("clips") or clips_prev
        ultimo_video = estado.get("ultimo_video")

        _reportar_progreso(progreso, mensaje)

        if fase in ("gemini", "youtube", "completado", "error") or ultimo_video:
            gal_items, vid_gal, gal_html, _ = obtener_datos_galeria()
            hist_filas, hist_html = obtener_tabla_historial()
            if ultimo_video:
                vid_prev = ultimo_video
            elif vid_gal:
                vid_prev = vid_gal

        nivel = "err" if fase == "error" else ("ok" if fase == "completado" else "run")
        titulo_banner = titulos_fase.get(fase, "Pipeline en Ejecución")
        banner = _banner_html(titulo_banner, mensaje, nivel)

        yield (
            banner,
            "\n".join(logs),
            vid_prev,
            clips_estado,
            gal_items,
            gal_html,
            hist_filas,
            hist_html,
        )


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

                with gr.Accordion("📅 Programación de Publicación (Opcional)", open=False):
                    with gr.Row():
                        with gr.Column(scale=3):
                            publish_at_input = gr.Textbox(
                                label="Fecha y Hora Inicial (Hora Local Colombia -05:00)",
                                placeholder="YYYY-MM-DD HH:MM (Hora local Colombia, vacío = privado inmediato)",
                                lines=1,
                            )
                        with gr.Column(scale=2):
                            intervalo_horas_input = gr.Slider(
                                minimum=0,
                                maximum=24,
                                step=1,
                                value=0,
                                label="Intervalo entre Shorts (horas)",
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

                tarjetas_galeria_html = gr.HTML(
                    html_inicial,
                    js_on_load="""
                    element.addEventListener('click', function(e) {
                        const btn = e.target.closest('.copy-btn');
                        if (!btn) return;
                        const field = btn.closest('.copy-field');
                        const valEl = field ? field.querySelector('.copy-value') : null;
                        if (!valEl) return;
                        const texto = (valEl.textContent || '').trim();
                        const marcarCopiado = () => {
                            const prev = btn.textContent;
                            btn.textContent = '✓ Copiado';
                            setTimeout(() => { btn.textContent = prev; }, 1400);
                        };
                        if (navigator.clipboard && navigator.clipboard.writeText) {
                            navigator.clipboard.writeText(texto).then(marcarCopiado).catch(() => {});
                        } else {
                            const ta = document.createElement('textarea');
                            ta.value = texto;
                            ta.style.position = 'fixed';
                            ta.style.opacity = '0';
                            document.body.appendChild(ta);
                            ta.select();
                            try { document.execCommand('copy'); marcarCopiado(); } catch (_) {}
                            document.body.removeChild(ta);
                        }
                    });
                    """,
                )

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
                        "Programado (UTC)",
                        "Cuenta ID",
                        "Tags Clave (Extracto)",
                    ],
                    datatype=["html"] * 9,
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
                publish_at_input,
                intervalo_horas_input,
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
