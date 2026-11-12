#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import hashlib
import http.client
import json
import os
import random
import socket
import ssl
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

import httplib2
from google.auth.exceptions import TransportError
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from googleapiclient.http import MediaFileUpload

BASE_DIR = Path(__file__).resolve().parent

SCOPES = ["https://www.googleapis.com/auth/youtube.upload"]
CLIENT_SECRETS_FILE = BASE_DIR / "client_secret.json"
TOKEN_FILE = BASE_DIR / "token.json"
HISTORIAL_SUBIDAS_FILE = BASE_DIR / "subidas_shorts.json"

CODIGOS_HTTP_REINTENTABLES = {500, 502, 503, 504}
ERRORES_RED_TRANSITORIOS = (
    httplib2.HttpLib2Error,
    TransportError,
    http.client.HTTPException,
    TimeoutError,
    ConnectionError,
    ssl.SSLError,
    socket.timeout,
    socket.error,
)


def obtener_hash_cuenta(creds: Any) -> str:
    """Genera un identificador corto SHA-256 de la cuenta/canal OAuth sin exponer secretos."""
    if creds is None:
        return "desconocida"

    if isinstance(creds, dict):
        refresh_token = creds.get("refresh_token")
        client_id = creds.get("client_id")
        token = creds.get("token")
    else:
        refresh_token = getattr(creds, "refresh_token", None)
        client_id = getattr(creds, "client_id", None)
        token = getattr(creds, "token", None)

    if refresh_token:
        semilla = f"rt:{refresh_token}"
    elif client_id or token:
        prefijo_token = str(token or "")[:16]
        semilla = f"cid:{client_id or ''}:tok:{prefijo_token}"
    else:
        return "desconocida"

    return hashlib.sha256(semilla.encode("utf-8")).hexdigest()[:12]


def _resolver_cuenta_id(youtube: Any, cuenta_id: Optional[str] = None) -> str:
    """Resuelve el cuenta_id desde parámetro explícito, cliente autenticado o credenciales locales."""
    if cuenta_id:
        return str(cuenta_id)
    attr_id = getattr(youtube, "_kicksazos_cuenta_id", None)
    if attr_id:
        return str(attr_id)
    creds = getattr(getattr(youtube, "_http", None), "credentials", None)
    if creds is not None:
        return obtener_hash_cuenta(creds)
    return "desconocida"


def _esperar_con_jitter_subida(
    intento: int,
    base: float = 2.0,
    max_espera: float = 32.0,
    log_fn: Optional[Callable[[str], None]] = None,
    contexto: str = "",
) -> float:
    """Espera usando backoff exponencial con jitter aleatorio para reintentos de subida."""
    techo = min(max_espera, base * (2 ** max(0, intento - 1)))
    espera = round(random.uniform(max(0.5, techo * 0.5), techo), 2)
    if contexto:
        msg = f"{contexto} | Reintentando en {espera:.2f}s..."
        if log_fn is not None:
            log_fn(msg)
        else:
            print(msg)
    time.sleep(espera)
    return espera


def _normalizar_publish_at_futuro(
    publish_at: Optional[str],
    log_fn: Optional[Callable[[str], None]] = None,
) -> Optional[str]:
    """Valida que publish_at sea una fecha futura válida y la normaliza a ISO 8601 UTC (Z)."""
    if not publish_at or not str(publish_at).strip():
        return None
    texto = str(publish_at).strip()
    try:
        dt = datetime.fromisoformat(texto.replace("Z", "+00:00"))
    except ValueError:
        msg = f"[AVISO] Formato inválido en publish_at '{texto}'; se omitirá programación."
        if log_fn is not None:
            log_fn(msg)
        else:
            print(msg)
        return None

    if dt.tzinfo is None:
        dt_utc = dt.replace(tzinfo=timezone.utc)
    else:
        dt_utc = dt.astimezone(timezone.utc)

    if dt_utc <= datetime.now(timezone.utc):
        msg = (
            f"[AVISO] La fecha publish_at '{dt_utc.strftime('%Y-%m-%dT%H:%M:%SZ')}' "
            "no es futura; se subirá en privado inmediato sin programación."
        )
        if log_fn is not None:
            log_fn(msg)
        else:
            print(msg)
        return None

    return dt_utc.strftime("%Y-%m-%dT%H:%M:%SZ")


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
    youtube = build("youtube", "v3", credentials=creds)
    setattr(youtube, "_kicksazos_cuenta_id", obtener_hash_cuenta(creds))
    return youtube


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


def verificar_cuota_diaria(
    limite_diario: int = 6,
    ruta_json: str | Path = HISTORIAL_SUBIDAS_FILE,
    ahora: Optional[datetime] = None,
) -> Dict[str, Any]:
    """Cuenta subidas exitosas en las últimas 24 horas en subidas_shorts.json y valida cuota diaria."""
    historial = cargar_historial_subidas(ruta_json)
    tz_local = datetime.now().astimezone().tzinfo or timezone(timedelta(hours=-5))
    ref_ahora = ahora if ahora is not None else datetime.now(tz_local)
    if ref_ahora.tzinfo is None:
        ref_ahora = ref_ahora.replace(tzinfo=tz_local)

    ventana = timedelta(hours=24)
    subidas_24h = 0
    for item in historial:
        if not isinstance(item, dict) or not item.get("youtube_id"):
            continue
        fecha_raw = item.get("fecha_subida")
        if not fecha_raw or not isinstance(fecha_raw, str):
            continue
        try:
            dt = datetime.fromisoformat(fecha_raw.strip().replace("Z", "+00:00"))
        except ValueError:
            continue
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=ref_ahora.tzinfo)
        delta = ref_ahora - dt
        if timedelta(0) <= delta <= ventana:
            subidas_24h += 1

    limite = max(0, int(limite_diario))
    return {
        "permitido": subidas_24h < limite,
        "subidas_24h": subidas_24h,
        "limite": limite,
        "restantes": max(0, limite - subidas_24h),
    }


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
    publish_at: Optional[str] = None,
    cuenta_id: Optional[str] = None,
    on_log: Optional[Callable[[str], None]] = None,
) -> Dict[str, Any]:
    """Sube un video a YouTube Shorts (privado o programado con publishAt) y registra en subidas_shorts.json."""
    def _log(msg: str) -> None:
        if on_log is not None:
            on_log(msg)
        else:
            print(msg)

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

    publish_at_utc = _normalizar_publish_at_futuro(publish_at, log_fn=_log)
    privacidad_efectiva = "private" if publish_at_utc else privacidad
    cuenta_id_resuelta = _resolver_cuenta_id(youtube, cuenta_id=cuenta_id)

    _log(f"\n[YouTube Upload] Subiendo: {ruta_path.name}")
    _log(f"  ├─ Título: {titulo_final}")
    _log(
        f"  ├─ Visibilidad: {privacidad_efectiva} | Categoría: 24 (Entretenimiento) | "
        f"madeForKids: False | Cuenta: {cuenta_id_resuelta}"
    )
    if publish_at_utc:
        _log(f"  ├─ Programado (publishAt UTC): {publish_at_utc}")
    _log(f"  └─ Etiquetas ({len(tags_limpios)}): {', '.join(tags_limpios[:8])}...")

    status_body: Dict[str, Any] = {
        "privacyStatus": privacidad_efectiva,
        "selfDeclaredMadeForKids": False,
        "madeForKids": False,
    }
    if publish_at_utc:
        status_body["publishAt"] = publish_at_utc

    body = {
        "snippet": {
            "title": titulo_final[:100],
            "description": desc_final[:4900],
            "tags": tags_limpios[:25],
            "categoryId": "24",  # Entretenimiento
        },
        "status": status_body,
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
    reintentos_consecutivos = 0
    max_reintentos = 4
    while response is None:
        try:
            status, response = request.next_chunk()
            reintentos_consecutivos = 0
            if status:
                print(f"  Progreso de subida: {int(status.progress() * 100)}%")
        except HttpError as err:
            codigo = getattr(err, "status_code", None) or getattr(
                getattr(err, "resp", None), "status", None
            )
            if codigo in CODIGOS_HTTP_REINTENTABLES and reintentos_consecutivos < max_reintentos:
                reintentos_consecutivos += 1
                _esperar_con_jitter_subida(
                    reintentos_consecutivos,
                    log_fn=_log,
                    contexto=(
                        f"[AVISO] Error HTTP {codigo} en next_chunk() "
                        f"(intento {reintentos_consecutivos}/{max_reintentos})"
                    ),
                )
                continue
            raise
        except ERRORES_RED_TRANSITORIOS as err:
            if reintentos_consecutivos < max_reintentos:
                reintentos_consecutivos += 1
                _esperar_con_jitter_subida(
                    reintentos_consecutivos,
                    log_fn=_log,
                    contexto=(
                        f"[AVISO] Error transitorio de red en next_chunk() "
                        f"({type(err).__name__}: {err}) "
                        f"(intento {reintentos_consecutivos}/{max_reintentos})"
                    ),
                )
                continue
            raise

    video_id = response["id"]
    url_short = f"https://youtube.com/shorts/{video_id}"
    _log(f"✓ Video subido con éxito a YouTube Shorts: {url_short}")

    info_subida = {
        "clip_id": clip_id,
        "archivo": ruta_path.name,
        "ruta_archivo": str(ruta_path),
        "youtube_id": video_id,
        "url": url_short,
        "titulo": titulo_final[:100],
        "descripcion": desc_final,
        "etiquetas": tags_limpios,
        "privacidad": privacidad_efectiva,
        "publish_at": publish_at_utc,
        "cuenta_id": cuenta_id_resuelta,
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
