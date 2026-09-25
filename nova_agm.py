import textwrap
import time
import io
import asyncio
import aiohttp
from audio_manager import AudioManager
from config import Config
import re
import traceback
from nova.prompts.nova_prompts import NOVA_SYSTEM_PROMPT
import json

from dotenv import load_dotenv

class Nova:
    def __init__(self):
        self.config = Config()
        self.headers = {
            "Authorization": f"Bearer {self.config.XAI_API_KEY}",
            "Content-Type": "application/json",
        }
        self.MAX_PALABRAS_PRIMER_CHUNK = (
            6  # * fuerza un corte temprano aunque no haya puntuación
        )
        self.audio_manager = AudioManager(self.config)
        self.system_prompt = {
            "role": "system",
            "content": NOVA_SYSTEM_PROMPT
        }
        self.delimiters = r"([,.!?]|\n|</whisper>|</soft>|</slow>|\[pause\]|\[laugh\]|\[sigh\]|\[long-pause\]|\[chuckle\]|\[giggle\]|\[cry\]|\[breath\]|\[inhale\]|\[exhale\]|\[tsk\]|\[tongue-click\]|\[lip-smack\])"
        self.messages = [self.system_prompt]
        self.chat_payload = {
            "model": "grok-4.3",
            "messages": self.messages,
            "temperature": 0.7,
            "stream": True,
        }

    async def tts_process(
        self, session, text_chunk, index, results, ready_event, start_time
    ):
        """Generates audio for a text chunk and saves it in 'results[index]' in memory.
        Does NOT decide playback order — that is controlled by the player."""
        payload = {
            "text": text_chunk,
            "voice_id": "iris",
            "language": "es",
            "output_format": {"container": "mp3"},
        }

        t0 = time.perf_counter()
        try:
            async with session.post(
                self.config.TTS_API_URL, json=payload, headers=self.headers
            ) as resp:
                if resp.status == 200:
                    audio_bytes = await resp.read()
                    results[index] = io.BytesIO(audio_bytes)
                    print(
                        f"\n[TTS chunk {index} ready in {time.perf_counter()-t0:.2f}s "
                        f"| +{time.perf_counter()-start_time:.2f}s since start]"
                    )
                else:
                    error_txt = await resp.text()
                    print(f"\n[TTS Error {resp.status}: {error_txt}]")
                    results[index] = None
        except Exception as e:
            print(f"\n[TTS Exception: {e}]")
            results[index] = None

        finally:
            ready_event.set()

    async def talk_with_nova(self):
            """Método principal para gestionar la conversación en tiempo real con NOVA."""
            print("Start talking with NOVA...")
            
            # Abre una sesión HTTP (aiohttp) que permite hacer muchas peticiones rápidas y asíncronas
            async with aiohttp.ClientSession() as session:
                while True:
                    # 1. CAPTURA DE ENTRADA: Espera a que el usuario escriba en consola.
                    # asyncio.to_thread evita que el 'input' (que es síncrono) congele el resto del programa.
                    user_text = await asyncio.to_thread(input, "\nYou: ")
                    
                    # Guarda el texto del usuario en el historial para que Grok tenga contexto
                    self.messages.append({"role": "user", "content": user_text})
                    
                    # Inicializa temporizadores y estructuras para medir el rendimiento (latencia)
                    beggining_time = time.perf_counter()
                    beggining_time_token = None
                    
                    # Diccionario donde se guardarán los audios finales en memoria: {0: audio0, 1: audio1...}
                    results = {}
                    # Lista de eventos para avisar al reproductor qué audio ya terminó de convertirse
                    events = []
                    # Lista de tareas asíncronas (las "10 peticiones a la API" en paralelo que mencionabas)
                    tts_tasks = []
                    # Contador para saber en qué fragmento (chunk) de texto vamos
                    index_chunk = 0

                    whole_answer = ""    # Guardará la respuesta completa en texto de Grok
                    phrase_buffer = ""   # Acumulador temporal de texto antes de mandarlo a TTS
                    buffer_words = 0     # Contador de palabras acumuladas en el buffer temporal

                    # FUNCIÓN INTERNA: Crea una tarea para convertir texto a audio sin esperar el resultado inmediatamente
                    def throw_chunk(text):
                        nonlocal index_chunk
                        event = asyncio.Event()  # Evento que se activará cuando ESTE fragmento esté listo
                        events.append(event)
                        
                        # Crea la tarea asíncrona (Petición TTS) y la lanza a ejecutarse en segundo plano
                        task = asyncio.create_task(
                            self.tts_process(
                                session, text, index_chunk, results, event, beggining_time
                            )
                        )
                        tts_tasks.append(task) # La guarda para rastrearla después
                        index_chunk += 1       # Incrementa el índice para el siguiente pedazo de texto

                    try:
                        # 2. PETICIÓN A GROK: Conexión con la API de LLM (Chat)
                        async with session.post(
                            self.config.CHAT_API_URL,
                            json=self.chat_payload,
                            headers=self.headers,
                        ) as resp:
                            if resp.status != 200:
                                error_text = await resp.text()
                                print(f"\n[Grok LLM Error ({resp.status}): {error_text}]")
                                continue
                            
                            # 3. PROCESAMIENTO DEL STREAM: Lee la respuesta de Grok conforme va llegando (línea por línea)
                            async for line in resp.content:
                                decoded_line = line.decode("utf-8").strip()
                                
                                # Filtra el formato Server-Sent Events (SSE) estándar de las IA ("data: {...}")
                                if (
                                    decoded_line.startswith("data: ")
                                    and decoded_line != "data: [DONE]"
                                ):
                                    try:
                                        data = json.loads(decoded_line[6:])
                                        # Extrae el nuevo fragmento de texto (token) que envió Grok
                                        token = data["choices"][0]["delta"].get(
                                            "content", ""
                                        )
                                        if token:
                                            # Si es el primer token de todos, calcula cuánto tardó en empezar a responder
                                            if beggining_time_token is None:
                                                beggining_time_token = time.perf_counter()
                                                print(
                                                    f"\n[First LLM token in {beggining_time_token - beggining_time:.2f}s]"
                                                )
                                                print("NOVA: ", end="", flush=True)

                                            # Imprime el token en consola en tiempo real
                                            print(token, end="", flush=True)
                                            whole_answer += token    # Lo suma al texto total
                                            phrase_buffer += token   # Lo acumula en el buffer de la frase actual
                                            buffer_words += len(token.split())

                                            # ESTRATEGIA A: Si detecta comas, puntos o etiquetas TTS en el buffer...
                                            if re.search(self.delimiters, phrase_buffer):
                                                clean_text = phrase_buffer.strip()
                                                if clean_text:
                                                    throw_chunk(clean_text) # Dispara petición de audio en paralelo
                                                phrase_buffer = ""          # Limpia el buffer
                                                buffer_words = 0

                                            # ESTRATEGIA B: Si es la primera frase y ya llegó a 6 palabras (sin puntos aún),
                                            # corta forzadamente para reducir la latencia inicial del audio.
                                            elif (
                                                index_chunk == 0
                                                and buffer_words
                                                >= self.MAX_PALABRAS_PRIMER_CHUNK
                                            ):
                                                clean_text = phrase_buffer.strip()
                                                if clean_text:
                                                    throw_chunk(clean_text) # Dispara petición de audio en paralelo
                                                phrase_buffer = ""
                                                buffer_words = 0

                                    except json.JSONDecodeError:
                                        pass
                                        
                        # Al salir del stream, si quedó texto restante en el buffer, genera su audio
                        if phrase_buffer.strip():
                            throw_chunk(phrase_buffer.strip())

                        # 4. REPRODUCCIÓN: Inicia el proceso de reproducción de audio.
                        # Se le pasan los 'events' para intentar que reproduzca en orden (0, 1, 2...)
                        reproductor_task = asyncio.create_task(
                            self.audio_manager.audio_player(results, len(events), events)
                        )
                        
                        # 5. ESPERA SÍNCRONA DE TAREAS: Aquí el código finalmente se detiene a esperar
                        # que todas las peticiones de audio (TTS) y el reproductor terminen su trabajo.
                        await asyncio.gather(*tts_tasks)
                        await reproductor_task

                        # Guarda la respuesta completa de la IA en el historial
                        self.messages.append({"role": "assistant", "content": whole_answer})
                        print(
                            f"\n[Turn completed in {time.perf_counter()-beggining_time:.2f}s]\n"
                        )
                    except Exception as e:
                        traceback.print_exc()
                        print(f"\n[Error: {e}]")
                        continue

if __name__ == "__main__":
    load_dotenv()  # Carga las variables de entorno desde el archivo .env
    import os

    nova = Nova()

    asyncio.run(nova.talk_with_nova())
