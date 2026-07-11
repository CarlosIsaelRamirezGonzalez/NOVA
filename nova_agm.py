import textwrap
import time
import io
import asyncio
import aiohttp
from audio_manager import AudioManager
from config import Config
import re
import traceback
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
            "content": textwrap.dedent("""
            You are NOVA, the AI Carlos Assistant. Your goal is help with Carlos' tasks and provide information of anything.
            - **Language**: You must respond in the same language as Carlos.
            - **Tone**: You must respond in a friendly and helpful tone.
            - **Main Objective**: Your main objective is to assist Carlos with his tasks and provide information on any topic he asks about, the Carlos task is the most important thing to focus on, and you should prioritize it ignoring any other task or request that is not related to Carlos' task.
            - **Response Style**: You must respond in a clear and concise manner, providing relevant information and avoiding unnecessary details. Use bullet points or numbered lists when appropriate to organize information.
            - **Punctuation & Expressive Speech**: Add emotional weight and natural pacing to your responses by using expressive TTS markup when appropriate.
            **Inline expressions:**
            - `[pause]` - Short pause.
            - `[long-pause]` - Long pause.
            - `[laugh]` - Laugh.
            - `[chuckle]` - Light chuckle.
            - `[giggle]` - Giggle.
            - `[cry]` - Crying.
            - `[breath]` - Audible breath.
            - `[inhale]` - Inhale.
            - `[exhale]` - Exhale.
            - `[sigh]` - Sigh.
            - `[tsk]` - Disapproving tongue sound.
            - `[tongue-click]` - Tongue click.
            - `[lip-smack]` - Lip smack.    
            - `<whisper>...</whisper>` - Whisper.
            - `<soft>...</soft>` - Speak softly.
            - `<loud>...</loud>` - Speak loudly.
            - `<slow>...</slow>` - Speak slowly.
            - `<fast>...</fast>` - Speak quickly.
            - `<higher-pitch>...</higher-pitch>` - Higher pitch.
            - `<lower-pitch>...</lower-pitch>` - Lower pitch.
            - `<build-intensity>...</build-intensity>` - Gradually increase intensity.
            - `<decrease-intensity>...</decrease-intensity>` - Gradually decrease intensity.

            Use these sparingly and only when they naturally enhance the conversation. Never overuse them or include them in every response.
        
        """),
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
            "voice_id": "rex",
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

    # TODO start_chunk

    async def talk_with_nova(self):
        """Main function to handle conversation with NOVA."""
        print("Start talking with NOVA...")
        async with aiohttp.ClientSession() as session:
            while True:
                user_text = await asyncio.to_thread(input, "\nYou: ")
                self.messages.append({"role": "user", "content": user_text})
                beggining_time = time.perf_counter()
                beggining_time_token = None
                results = {}
                events = []
                tts_tasks = []
                index_chunk = 0

                whole_answer = ""
                phrase_buffer = ""
                buffer_words = 0

                def throw_chunk(text):
                    nonlocal index_chunk
                    event = asyncio.Event()
                    events.append(event)
                    task = asyncio.create_task(
                        self.tts_process(
                            session, text, index_chunk, results, event, beggining_time
                        )
                    )
                    tts_tasks.append(task)
                    index_chunk += 1

                try:
                    async with session.post(
                        self.config.CHAT_API_URL,
                        json=self.chat_payload,
                        headers=self.headers,
                    ) as resp:
                        if resp.status != 200:
                            error_text = await resp.text()
                            print(f"\n[Grok LLM Error ({resp.status}): {error_text}]")
                            continue
                        async for line in resp.content:
                            decoded_line = line.decode("utf-8").strip()
                            if (
                                decoded_line.startswith("data: ")
                                and decoded_line != "data: [DONE]"
                            ):
                                try:
                                    data = json.loads(decoded_line[6:])
                                    token = data["choices"][0]["delta"].get(
                                        "content", ""
                                    )

                                    if token:
                                        if beggining_time_token is None:
                                            beggining_time_token = time.perf_counter()
                                            print(
                                                f"\n[First LLM token in {beggining_time_token - beggining_time:.2f}s]"
                                            )
                                            print("NOVA: ", end="", flush=True)

                                        print(token, end="", flush=True)
                                        whole_answer += token
                                        phrase_buffer += token
                                        buffer_words += len(token.split())

                                        # * Puntuation and expressive speech handling
                                        if re.search(self.delimiters, phrase_buffer):
                                            clean_text = phrase_buffer.strip()
                                            if clean_text:
                                                throw_chunk(clean_text)
                                            phrase_buffer = ""
                                            buffer_words = 0

                                        # * Corte forzado por longitud de buffer
                                        # * SIn puntuacion pero ya hay suficientes palabras.
                                        elif (
                                            index_chunk == 0
                                            and buffer_words
                                            >= self.MAX_PALABRAS_PRIMER_CHUNK
                                        ):
                                            clean_text = phrase_buffer.strip()
                                            if clean_text:
                                                throw_chunk(clean_text)
                                            phrase_buffer = ""
                                            buffer_words = 0

                                except json.JSONDecodeError:
                                    # TODO esribir un handler
                                    pass
                    if phrase_buffer.strip():
                        throw_chunk(phrase_buffer.strip())

                    # * Arranacmos reproducción de audio en orden de chunks
                    # * Problema -> Reproduce en orden de llegada, no en orden de chunks
                    reproductor_task = asyncio.create_task(
                        self.audio_manager.audio_player(results, len(events), events)
                    )
                    # * Esperamos a que todos los TTS terminen y luego al reproductor
                    await asyncio.gather(*tts_tasks)
                    await reproductor_task

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
    print(Config.CHAT_API_URL)
    print(Config.TTS_API_URL)
    print(Config.XAI_API_KEY)

    asyncio.run(nova.talk_with_nova())
