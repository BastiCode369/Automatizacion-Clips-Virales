import json
import subprocess
import os

vod_url = "https://kick.com/eldomi/videos/01a1b385-3148-7af6-8f11-713594ed57a5"
user_agent = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36"

print("1. Obteniendo URL de stream directo en alta calidad con yt-dlp...")
cmd_url = [
    "yt-dlp",
    "--user-agent", user_agent,
    "-f", "best",
    "-g",
    vod_url
]
res = subprocess.run(cmd_url, capture_output=True, text=True)
stream_url = res.stdout.strip()

if not stream_url:
    print("Error al obtener la URL del stream:", res.stderr)
    exit(1)

print(f"URL de stream obtenida correctamente.")

with open("clips.json", "r", encoding="utf-8") as f:
    clips = json.load(f)

# Filtro complejo para 9:16 con fondo desenfocado
# [0:v] split [fondo][frente]
# fondo: escala a 1080x1920 recortando bordes y aplica boxblur
# frente: escala manteniendo aspecto a ancho 1080
# overlay: monta frente en el centro de fondo
filter_complex = (
    "[0:v]split=2[bg][fg];"
    "[bg]scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920,boxblur=20:5[bg_blurred];"
    "[fg]scale=1080:-1[fg_scaled];"
    "[bg_blurred][fg_scaled]overlay=(W-w)/2:(H-h)/2[v]"
)

print(f"2. Procesando {len(clips)} clips...")

for clip in clips:
    c_id = clip["id"]
    titulo_limpio = "".join(c for c in clip["titulo"] if c.isalnum() or c in (" ", "_", "-")).rstrip()
    output_path = f"clips_finales/clip_{c_id}_{titulo_limpio.replace(' ', '_')}.mp4"
    
    inicio = clip["inicio"]
    fin = clip["fin"]
    
    print(f"\nGenerando Clip {c_id}: {clip['titulo']} ({inicio} -> {fin})")
    
    cmd_ffmpeg = [
        "ffmpeg", "-y",
        "-user_agent", user_agent,
        "-ss", inicio,
        "-to", fin,
        "-i", stream_url,
        "-filter_complex", filter_complex,
        "-map", "[v]",
        "-map", "0:a?",
        "-c:v", "libx264",
        "-preset", "veryfast",
        "-crf", "22",
        "-c:a", "aac",
        "-b:a", "128k",
        output_path
    ]
    
    subprocess.run(cmd_ffmpeg)

print("\n¡Todos los clips verticales fueron generados en la carpeta 'clips_finales/'!")
