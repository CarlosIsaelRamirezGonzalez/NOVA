import aiohttp
import asyncio


class AgentManager:
    def __init__(self, conversation, llm, tts, chunking, player):
        self.conversation = conversation
        self.llm = llm
        self.tts = tts
        self.chunking = chunking
        self.player = player

    async def run_turn(self, user_input: str):
        """Ejecuta un turno completo: user -> LLM -> chunking -> TTS -> playback."""
        # 1. Agregar mensaje de usuario
        self.conversation.add_user_message(user_input)

        # 2. Obtener payload
        payload = self.conversation.get_payload(model="grok-4.3")

        # 3. Stream del LLM y chunking en vivo
        results = {}
        events = []
        tts_tasks = []
        chunk_index = 0
        full_response = ""

        async with aiohttp.ClientSession() as session:
            # 3.1 Escuchar el stream
            async for token in self.llm.stream_response(session, payload):
                full_response += token
                chunks = self.chunking.add_token(token)

                for chunk_text in chunks:
                    event = asyncio.Event()
                    events.append(event)
                    task = asyncio.create_task(
                        self._tts_and_store(
                            session, chunk_text, chunk_index, results, event
                        )
                    )
                    tts_tasks.append(task)
                    chunk_index += 1

            # 3.2 Fragmento final
            final_chunk = self.chunking.flush()
            if final_chunk:
                event = asyncio.Event()
                events.append(event)
                task = asyncio.create_task(
                    self._tts_and_store(
                        session, final_chunk, chunk_index, results, event
                    )
                )
                tts_tasks.append(task)

            # 4. Reproducir
            await asyncio.gather(*tts_tasks)
            await self.player.play_in_order(results, len(events), events)

        # 5. Guardar en historial
        self.conversation.add_assistant_message(full_response)
        return full_response

    async def _tts_and_store(self, session, text, index, results, event):
        """Wrapper para TTS y guardado en results."""
        idx, audio_bytes = await self.tts.text_to_audio(session, text, index)
        results[idx] = audio_bytes
        event.set()
