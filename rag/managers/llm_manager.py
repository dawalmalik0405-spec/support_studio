import subprocess
import time
import requests
from pathlib import Path
import json

class LLMManager:

    def __init__(self):
      BASE_DIR = Path(__file__).parent.parent

      self.LLAMA_SERVER = BASE_DIR / "runtime" / "llama-server.exe"
      self.MODEL = BASE_DIR / "models" / "Qwen3-4B-Q4_K_M.gguf"

      self.SERVER_URL = "http://127.0.0.1:8080"

      self.process = None

   

    def start(self):

      self.process = subprocess.Popen(
            [
                str(self.LLAMA_SERVER),
                "-m", str(self.MODEL),
                "-c", "8192",
                "--reasoning", "auto",
                "--host", "127.0.0.1",
                "--port", "8080",
            ],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )

       #--------------------------------------------------
          # Wait until llama-server is ready
          # --------------------------------------------------

      print("Starting Qwen3 model...")

      for _ in range(60):
          try:
              health = requests.get(
                  f"{self.SERVER_URL}/health",
                  timeout=1
              )

              if health.status_code == 200:
                  print("Qwen3 model is ready.")
                  break

          except requests.RequestException:
              pass

          time.sleep(1)

      else:
          self.process.terminate()
          self.process = None 
          raise RuntimeError("llama-server failed to start.")

        
        

    def generate(self, prompt, max_tokens=1500, stream=True, enable_thinking=False, yield_events=False, system_prompt=None):

        messages = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": prompt})

        response = requests.post(
                f"{self.SERVER_URL}/v1/chat/completions",
                json={
                    "messages": messages,
                    "chat_template_kwargs": {
                        "enable_thinking": enable_thinking
                    },
                    "max_tokens": max_tokens,
                    "stream": stream,
                },
                stream=stream,
                timeout=120,
            )
        
        response.raise_for_status()

        if not stream:
            data = response.json()
            message = data["choices"][0]["message"]
            if yield_events:
                if message.get("reasoning_content"):
                    yield ("thinking", message["reasoning_content"])
                yield ("token", message.get("content", ""))
            else:
                yield message.get("content", "")
            return

        for line in response.iter_lines():
            if not line:
                continue

            if isinstance(line, bytes):
                line = line.decode("utf-8", errors="replace")
            line = line.strip()

            # SSE permits comments and metadata fields between data events.
            if not line or line.startswith((':', "event:", "id:", "retry:")):
                continue
            if line.startswith("data:"):
                line = line[5:].strip()
            elif not line.startswith("{"):
                # Ignore other SSE fields and transport noise, but do not try
                # to parse them as JSON payloads.
                continue

            if not line:
                continue

            if line == "[DONE]":
                break

            try:
                data = json.loads(line)
            except json.JSONDecodeError as exc:
                raise RuntimeError(
                    "llama-server returned a malformed streaming response. "
                    f"Payload began with: {line[:160]!r}"
                ) from exc

            if data.get("error"):
                raise RuntimeError(f"llama-server error: {data['error']}")

            choices = data.get("choices", [])
            if not choices:
                continue

            delta = choices[0].get("delta", {})
            reasoning = delta.get("reasoning_content")
            if reasoning and yield_events:
                yield ("thinking", reasoning)

            content = delta.get("content")
            if content:
                if yield_events:
                    yield ("token", content)
                else:
                    yield content
       

    def stop(self):
      if self.process is not None:
          self.process.terminate()
          self.process.wait()
          self.process = None
