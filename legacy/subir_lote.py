#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import json
from pathlib import Path
from subir_shorts import autenticar_youtube, subir_short

def subir_lote():
    carpeta = Path("clips_virales")
    reporte = carpeta / "reporte_clips.json"
    
    if not reporte.exists():
        print("[ERROR] No se encontró clips_virales/reporte_clips.json")
        return

    with open(reporte, "r", encoding="utf-8") as f:
        metadatos = json.load(f)

    # Límite seguro diario para YouTube Data API (máx 5-6 por día)
    limite = 5
    clips_a_subir = metadatos[:limite]

    print(f"Iniciando autenticación en YouTube...")
    youtube = autenticar_youtube()

    archivos_mp4 = list(carpeta.glob("*.mp4"))

    for item in clips_a_subir:
        cid = item.get("id")
        titulo = item.get("titulo", f"Clip {cid}")
        gancho = item.get("gancho", "")
        
        # Buscar el archivo correspondiente por prefijo de id
        prefijo = f"clip_{cid:02d}_"
        coincidencias = [f for f in archivos_mp4 if f.name.startswith(prefijo)]
        
        if not coincidencias:
            print(f"[AVISO] No se encontró archivo local para el clip #{cid} con prefijo '{prefijo}'")
            continue
            
        archivo_video = coincidencias[0]
        descripcion = f"{gancho}\n\nMomento viral de stream.\nSuscríbete para más clips diarios."
        tags = ["Shorts", "Kick", "KickClips", "Viral", "Humor", "Stream"]

        try:
            subir_short(
                youtube=youtube,
                ruta_video=archivo_video,
                titulo=titulo,
                descripcion=descripcion,
                etiquetas=tags,
                privacidad="private"
            )
        except Exception as e:
            print(f"[ERROR] Falló la subida de {archivo_video.name}: {e}")
            break

if __name__ == "__main__":
    subir_lote()
