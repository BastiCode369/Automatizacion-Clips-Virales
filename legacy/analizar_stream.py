import os
import time
from google import genai
from google.genai import types
from google.genai.errors import ServerError

api_key = os.environ.get("GEMINI_API_KEY")
if not api_key:
    raise ValueError("Falta la variable GEMINI_API_KEY.")

client = genai.Client(api_key=api_key)

file_name = "files/qqucn2awgp39"
print(f"1. Conectando al archivo existente: {file_name}...")
audio_file = client.files.get(name=file_name)

print("2. Analizando momentos virales con gemini-3.8-flash...")
prompt = """
Actúa como un editor profesional de clips virales para TikTok, Shorts y Reels.
Analiza este stream de Kick de 3 horas.
Identifica entre 5 y 8 de los mejores momentos para clips cortos (reacciones, jugadas, risas, anécdotas o momentos tensos).

Requisitos indispensables:
- Duración por clip: Entre 30 y 60 segundos.
- Indica el timestamp exacto de inicio y de fin (formato HH:MM:SS).
- Responde ÚNICAMENTE un array JSON válido con esta estructura exacta:
[
  {
    "id": 1,
    "titulo": "Título corto y llamativo",
    "inicio": "00:15:30",
    "fin": "00:16:15",
    "gancho": "Frase que engancha en los primeros 3 segundos"
  }
]
"""

# Reintentos automáticos si el modelo está en pico de demanda (503)
intentos = 5
for i in range(1, intentos + 1):
    try:
        response = client.models.generate_content(
            model="gemini-3.8-flash",
            contents=[audio_file, prompt],
            config=types.GenerateContentConfig(
                response_mime_type="application/json"
            )
        )
        with open("clips.json", "w", encoding="utf-8") as f:
            f.write(response.text)
        print("¡Listo! Las marcas de tiempo se guardaron en 'clips.json'.")
        break
    except ServerError as e:
        print(f"Pico de demanda en el servidor (intento {i}/{intentos}). Esperando 10 segundos...")
        time.sleep(10)
    except Exception as e:
        print(f"Error inesperado: {e}")
        raise
