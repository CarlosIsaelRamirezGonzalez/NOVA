import json 

class LLMService:
    def __init__(self, api_key: str, api_url: str):
        self.headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        }
        self.api_url = api_url

    async def stream_response(self, session, payload: dict):
        async with session.post(
            self.api_url, json=payload, headers=self.headers
        ) as resp:
            if resp.status != 200:
                raise Exception(f"LLM Error {resp.status}: {await resp.text()}")

            async for line in resp.content:
                decoded = line.decode("utf-8").strip()
                if decoded.startswith("data: ") and decoded != "data: [DONE]":
                    yield self._extract_token(decoded)

    def _extract_token(self, sse_line: str) -> str:
        data = json.loads(sse_line[6:])
        return data["choices"][0]["delta"].get("content", "")
