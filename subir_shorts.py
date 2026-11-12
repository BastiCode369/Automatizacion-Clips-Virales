#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import json
import os
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload

BASE_DIR = Path(__file__).resolve().parent

SCOPES = ["https://www.googleapis.com/auth/youtube.upload"]
CLIENT_SECRETS_FILE = BASE_DIR / "client_secret.json"
TOKEN_FILE = BASE_DIR / "token.json"
HISTORIAL_SUBIDAS_FILE = BASE_DIR / "subidas_shorts.json"


def autenticar_youtube(interactivo: bool = False):
    """Autentica con YouTube Data API v3 usando token.json y client_secret.json anclados a BASE_DIR."""
    creds = None
    if TOKEN_FILE.exists():
        creds = Credentials.from_authorized_user_file(str(TOKEN_FILE), SCOPES)
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            if not CLIENT_SECRETS_FILE.exists():
                raise FileNotFoundError(
                    f"Falta el archivo '{CLIENT_SECRETS_FILE}'. Descárgalo de Google Cloud Console."
                )
            if not interactivo:
                raise RuntimeError(
                    "Token de YouTube expirado o inexistente y modo no interactivo activo."
                )
            flow = InstalledAppFlow.from_client_secrets_file(str(CLIENT_SECRETS_FILE), SCOPES)
            creds = flow.run_local_server(port=0)
        with open(TOKEN_FILE, "w", encoding="utf-8") as token:
            token.write(creds.to_json())
    return build("youtube", "v3", credentials=creds)


def cargar_historial_subidas(
    ruta_json: str | Path = HISTORIAL_SUBIDAS_FILE,
) -> List[Dict[str, Any]]:
    """Carga el historial de subidas desde subidas_shorts.json."""
    ruta = Path(ruta_json)
    if not ruta.exists():
        return []
    try:
        with open(ruta, "r", encoding="utf-8") as f:
            datos = json.load(f)
            return datos if isinstance(datos, list) else []
    except Exception:
        return []


def registrar_subida(
    registro: Dict[str, Any],
    ruta_json: str | Path = HISTORIAL_SUBIDAS_FILE,
) -> List[Dict[str, Any]]:
    """Agrega o actualiza un registro de subida en subidas_shorts.json."""
    ruta = Path(ruta_json)
    historial = cargar_historial_subidas(ruta)
    video_id = registro.get("youtube_id")
    if video_id:
        historial = [item for item in historial if item.get("youtube_id") != video_id]
    historial.append(registro)
    with open(ruta, "w", encoding="utf-8") as f:
        json.dump(historial, f, indent=2, ensure_ascii=False)
    return historial


def subir_short(
    youtube,
    ruta_video: str | Path,
    titulo: str,
    descripcion: str,
    etiquetas: List[str],
    privacidad: str = "private",
    clip_id: Optional[int | str] = None,
    guardar_registro: bool = True,
) -> Dict[str, Any]:
    """Sube un video a YouTube Shorts en modo privado y registra la trazabilidad en subidas_shorts.json."""
    ruta_path = Path(ruta_video).resolve()
    if not ruta_path.exists():
        raise FileNotFoundError(f"No existe el archivo de video a subir: {ruta_path}")

    titulo_limpio = (titulo or "Clip Viral").strip()
    if "#shorts" not in titulo_limpio.lower():
        titulo_final = f"{titulo_limpio[:90]} #Shorts".strip()
    else:
        titulo_final = titulo_limpio[:100]

    desc_limpia = (descripcion or "").strip()
    if "#shorts" not in desc_limpia.lower():
        desc_final = f"{desc_limpia}\n\n#Shorts #Kicksazos #StreamColombia".strip()
    else:
        desc_final = desc_limpia

    tags_limpios = []
    for t in etiquetas or []:
        t_str = str(t).strip().lstrip("#")
        if t_str and t_str not in tags_limpios:
            tags_limpios.append(t_str)
    if not tags_limpios:
        tags_limpios = ["Shorts", "Kicksazos", "StreamColombia", "KickColombia", "IRL"]

    print(f"\n[YouTube Upload] Subiendo: {ruta_path.name}")
    print(f"  ├─ Título: {titulo_final}")
    print(f"  ├─ Visibilidad: {privacidad} | Categoría: 24 (Entretenimiento) | madeForKids: False")
    print(f"  └─ Etiquetas ({len(tags_limpios)}): {', '.join(tags_limpios[:8])}...")

    body = {
        "snippet": {
            "title": titulo_final[:100],
            "description": desc_final[:4900],
            "tags": tags_limpios[:25],
            "categoryId": "24",  # Entretenimiento
        },
        "status": {
            "privacyStatus": privacidad,
            "selfDeclaredMadeForKids": False,
            "madeForKids": False,
        },
    }

    media = MediaFileUpload(
        str(ruta_path),
        mimetype="video/mp4",
        resumable=True,
    )

    request = youtube.videos().insert(
        part="snippet,status",
        body=body,
        media_body=media,
    )

    response = None
    while response is None:
        status, response = request.next_chunk()
        if status:
            print(f"  Progreso de subida: {int(status.progress() * 100)}%")

    video_id = response["id"]
    url_short = f"https://youtube.com/shorts/{video_id}"
    print(f"✓ Video subido con éxito a YouTube Shorts: {url_short}")

    info_subida = {
        "clip_id": clip_id,
        "archivo": ruta_path.name,
        "ruta_archivo": str(ruta_path),
        "youtube_id": video_id,
        "url": url_short,
        "titulo": titulo_final[:100],
        "descripcion": desc_final,
        "etiquetas": tags_limpios,
        "privacidad": privacidad,
        "categoryId": "24",
        "madeForKids": False,
        "fecha_subida": datetime.now().isoformat(timespec="seconds"),
    }

    if guardar_registro:
        registrar_subida(info_subida)

    return info_subida


def main():
    if not CLIENT_SECRETS_FILE.exists():
        print(f"[ERROR] Coloca el archivo '{CLIENT_SECRETS_FILE}' en esta carpeta antes de continuar.")
        sys.exit(1)

    youtube = autenticar_youtube(interactivo=True)

    carpeta_clips = BASE_DIR / "clips_finales"
    if not carpeta_clips.exists() or not list(carpeta_clips.glob("*.mp4")):
        carpeta_clips = BASE_DIR / "legacy" / "clips_virales"

    archivos_mp4 = sorted(list(carpeta_clips.glob("*.mp4")))
    if not archivos_mp4:
        print(f"[ERROR] No se encontraron archivos .mp4 en {BASE_DIR / 'clips_finales'} ni en legacy/clips_virales/.")
        sys.exit(1)

    video_prueba = archivos_mp4[0]

    titulo_test = "¡Momento Épico en Vivo! 😂"
    descripcion_test = (
        "No te pierdas esta reacción brutal en pleno directo.\n"
        "¡Suscríbete al canal y activa la campanita para más clips diarios! #Shorts #Kicksazos #StreamColombia"
    )
    etiquetas_test = ["Shorts", "Kicksazos", "StreamColombia", "Kick", "Clips", "Humor", "Viral", "Colombia"]

    subir_short(
        youtube=youtube,
        ruta_video=video_prueba,
        titulo=titulo_test,
        descripcion=descripcion_test,
        etiquetas=etiquetas_test,
        privacidad="private",
    )


if __name__ == "__main__":
    main()
