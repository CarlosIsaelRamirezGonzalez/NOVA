import os
import requests

# --- CONFIGURACIÓN DE XAI ---
XAI_API_KEY = "REDACTED" 
CHAT_API_URL = "https://api.x.ai/v1/chat/completions"
TTS_API_URL = "https://api.x.ai/v1/tts"
AUDIO_FILE = "respuesta_grok_rex.mp3"

headers = {
    "Authorization": f"Bearer {XAI_API_KEY}",
    "Content-Type": "application/json"
}

# --- INSTRUCCIONES PARA EL LLM (EL CEREBRO DEL CHATBOT) ---
# Aquí es donde ocurre la magia: le enseñamos a Grok a usar las etiquetas de voz.
system_prompt = {
    "role": "system",
    "content": (
        "Eres Rex, un asistente conversacional amigable y expresivo. "
        "Tus respuestas serán procesadas por un motor de Text-to-Speech avanzado, "
        "por lo que DEBES incluir etiquetas de emoción y ritmo de forma natural en tus frases.\n"
        "Usa las siguientes etiquetas según el contexto:\n"
        "- <whisper> texto </whisper>: Para secretos, misterio o hablar bajito.\n"
        "- <soft> texto </soft>: Para hablar con ternura, calma o empatía.\n"
        "- <slow> texto </slow>: Para enfatizar algo importante paso a paso.\n"
        "- [pause]: Para hacer una pausa dramática o respirar.\n"
        "- [laugh]: Para reírte cuando algo sea gracioso.\n"
        "- [sigh]: Para suspirar si estás cansado o aliviado.\n\n"
        "Ejemplo: '¡Hola! [laugh] Qué alegría verte. <soft> Estaba pensando que... </soft> [pause] <whisper> tengo un secreto para ti. </whisper>'\n"
        "Mantén tus respuestas relativamente breves y conversacionales."
    )
}

# Historial de conversación
mensajes = [system_prompt]

print("--- ¡Iniciando Chatbot de Voz Completo con Grok! ---")
print("Escribe 'salir' para terminar.\n")
    
while True:
    texto_usuario = input("\nTú: ")
    
    if texto_usuario.strip().lower() == 'salir':
        print("Saliendo del programa...")
        break
        
    if not texto_usuario.strip():
        continue

    # 1. Agregar lo que dijo el usuario al historial
    mensajes.append({"role": "user", "content": texto_usuario})

    try:
        # ==========================================
        # FASE 1: GENERACIÓN DE TEXTO CON GROK LLM
        # ==========================================
        print("Grok (Rex) está pensando su respuesta...")
        chat_payload = {
            "model": "grok-4.3", # O el modelo que prefieras de xAI
            "messages": mensajes,
            "temperature": 0.7 # Un poco de creatividad para que use bien las etiquetas
        }
        
        chat_response = requests.post(CHAT_API_URL, json=chat_payload, headers=headers)
        
        if chat_response.status_code != 200:
            print(f"Error en Chat API ({chat_response.status_code}): {chat_response.text}")
            continue
            
        respuesta_json = chat_response.json()
        texto_generado = respuesta_json["choices"][0]["message"]["content"]
        
        # Agregar la respuesta del asistente al historial para que tenga memoria
        mensajes.append({"role": "assistant", "content": texto_generado})
        
        print(f"\nRex (Texto): {texto_generado}\n")

        # ==========================================
        # FASE 2: GENERACIÓN DE AUDIO CON GROK TTS
        # ==========================================
        print("Convirtiendo a voz...")
        tts_payload = {
            "text": texto_generado,
            "voice_id": "rex",
            "language": "es",
            "output_format": {
                "container": "mp3"
            }
        }
        
        tts_response = requests.post(TTS_API_URL, json=tts_payload, headers=headers)
        
        if tts_response.status_code == 200:
            with open(AUDIO_FILE, "wb") as f:
                f.write(tts_response.content)
            
            # Reproducir el audio
            if os.name == 'posix': 
                os.system(f"afplay {AUDIO_FILE}" if os.uname().sysname == 'Darwin' else f"mpg123 {AUDIO_FILE} >/dev/null 2>&1")
            elif os.name == 'nt':   
                os.system(f"start /min \"\" {AUDIO_FILE}")
        else:
            print(f"Error en TTS API ({tts_response.status_code}): {tts_response.text}")

    except Exception as e:
        print(f"Ocurrió un error general: {e}")

print("Programa finalizado.")