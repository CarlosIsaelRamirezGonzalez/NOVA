import asyncio
import aiohttp
import json
import re
import io
import time
import pygame

# --- CONFIGURACIÓN DE XAI ---
XAI_API_KEY = "REDACTED"
CHAT_API_URL = "https://api.x.ai/v1/chat/completions"
TTS_API_URL = "https://api.x.ai/v1/tts"

headers = {
    "Authorization": f"Bearer {XAI_API_KEY}",
    "Content-Type": "application/json"
}

system_prompt = {
    "role": "system",
    "content": (
        "Eres Rex, un asistente conversacional amigable. "
        "Usa las siguientes etiquetas de forma natural en tus frases:\n"
        "<whisper> texto </whisper>, <soft> texto </soft>, <slow> texto </slow>, "
        "[pause], [laugh], [sigh].\n"
        "Mantén tus respuestas breves y conversacionales. Usa puntuación clara."
    )
}

mensajes = [system_prompt]

pygame.mixer.init()

# * Delimitadores para cortar frases largas. Se agregó la coma y un límite
# * de palabras para bajar el "time to first audio" del primer fragmento.
delimitadores = r'([,.!?]|\n|</whisper>|</soft>|</slow>|\[pause\]|\[laugh\]|\[sigh\])'
MAX_PALABRAS_PRIMER_CHUNK = 6  # * fuerza un corte temprano aunque no haya puntuación


async def procesar_tts(session, text_chunk, indice, resultados, evento_listo, t_inicio):
    """Genera el audio de un fragmento y lo guarda en 'resultados[indice]' en memoria.
    NO decide el orden de reproducción — eso lo controla el reproductor."""
    payload = {
        "text": text_chunk,
        "voice_id": "rex",
        "language": "es",
        "output_format": {"container": "mp3"}
    }

    t0 = time.perf_counter()
    try:
        async with session.post(TTS_API_URL, json=payload, headers=headers) as resp:
            if resp.status == 200:
                audio_bytes = await resp.read()
                resultados[indice] = io.BytesIO(audio_bytes)
                print(f"\n[TTS chunk {indice} listo en {time.perf_counter()-t0:.2f}s "
                      f"| +{time.perf_counter()-t_inicio:.2f}s desde inicio]")
            else:
                error_txt = await resp.text()
                print(f"\n[Error TTS {resp.status}: {error_txt}]")
                resultados[indice] = None
    except Exception as e:
        print(f"\n[Error TTS Excepción: {e}]")
        resultados[indice] = None
    finally:
        evento_listo.set()


async def reproductor_audio(resultados, total_chunks, eventos):
    """Reproduce los fragmentos EN ORDEN, esperando a que cada índice esté listo
    aunque los TTS hayan terminado en otro orden. Reproduce en memoria (sin disco)."""
    for i in range(total_chunks):
        await eventos[i].wait()
        audio_io = resultados.get(i)
        if audio_io is None:
            continue
        try:
            sonido = pygame.mixer.Sound(audio_io)
            canal = sonido.play()
            while canal.get_busy():
                await asyncio.sleep(0.03)
        except Exception as e:
            print(f"\n[Error de reproducción chunk {i}: {e}]")


async def chatear_con_rex():
    print("--- ¡Iniciando Chat de Voz Ultra-Fluido con Rex! ---")
    print("Escribe 'salir' para terminar.\n")

    # * Sesión persistente reutilizada en TODO el programa (no solo por turno)
    # * para no pagar el handshake TLS en cada mensaje.
    async with aiohttp.ClientSession() as session:
        while True:
            texto_usuario = await asyncio.to_thread(input, "\nTú: ")

            if texto_usuario.strip().lower() == 'salir':
                break
            if not texto_usuario.strip():
                continue

            mensajes.append({"role": "user", "content": texto_usuario})

            chat_payload = {
                "model": "grok-4.3",
                "messages": mensajes,
                "temperature": 0.7,
                "stream": True
            }

            t_inicio = time.perf_counter()
            t_primer_token = None

            resultados = {}
            eventos = []
            tareas_tts = []
            indice_chunk = 0

            print("Rex (Pensando/Hablando): ", end="", flush=True)
            respuesta_completa = ""
            buffer_frase = ""
            palabras_buffer = 0

            def lanzar_chunk(texto):
                nonlocal indice_chunk
                ev = asyncio.Event()
                eventos.append(ev)
                tarea = asyncio.create_task(
                    procesar_tts(session, texto, indice_chunk, resultados, ev, t_inicio)
                )
                tareas_tts.append(tarea)
                indice_chunk += 1

            try:
                async with session.post(a, json=chat_payload, headers=headers) as resp:
                    if resp.status != 200:
                        error_text = await resp.text()
                        print(f"\n[Error de Grok LLM ({resp.status}): {error_text}]")
                        continue

                    async for linea in resp.content:
                        linea_decodificada = linea.decode('utf-8').strip()

                        if linea_decodificada.startswith("data: ") and linea_decodificada != "data: [DONE]":
                            try:
                                datos = json.loads(linea_decodificada[6:])
                                token = datos['choices'][0]['delta'].get('content', '')

                                if token:
                                    if t_primer_token is None:
                                        t_primer_token = time.perf_counter()
                                        print(f"\n[Primer token del LLM en {t_primer_token - t_inicio:.2f}s]")
                                        print("Rex: ", end="", flush=True)

                                    print(token, end="", flush=True)
                                    respuesta_completa += token
                                    buffer_frase += token
                                    palabras_buffer = len(buffer_frase.split())

                                    # * Corte normal por puntuación/etiquetas
                                    if re.search(delimitadores, buffer_frase):
                                        texto_limpio = buffer_frase.strip()
                                        if texto_limpio:
                                            lanzar_chunk(texto_limpio)
                                        buffer_frase = ""
                                        palabras_buffer = 0

                                    # * Corte forzado SOLO para el primer chunk, si aún
                                    # * no hay puntuación pero ya hay suficientes palabras.
                                    # * Esto es lo que baja el "time to first audio".
                                    elif indice_chunk == 0 and palabras_buffer >= MAX_PALABRAS_PRIMER_CHUNK:
                                        texto_limpio = buffer_frase.strip()
                                        if texto_limpio:
                                            lanzar_chunk(texto_limpio)
                                        buffer_frase = ""
                                        palabras_buffer = 0

                            except json.JSONDecodeError:
                                pass

                if buffer_frase.strip():
                    lanzar_chunk(buffer_frase.strip())

                # * Arrancamos el reproductor YA con el total de chunks conocido,
                # * reproduce en orden aunque los TTS terminen desordenados.
                tarea_reproductor = asyncio.create_task(
                    reproductor_audio(resultados, len(eventos), eventos)
                )

                await asyncio.gather(*tareas_tts)
                await tarea_reproductor

                mensajes.append({"role": "assistant", "content": respuesta_completa})
                print(f"\n[Turno completo en {time.perf_counter()-t_inicio:.2f}s]\n")

            except Exception as e:
                print(f"\nOcurrió un error en la conexión: {e}")


if __name__ == "__main__":
    asyncio.run(chatear_con_rex())