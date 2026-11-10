import subprocess
import time
from pathlib import Path

import requests
from langchain_openai import OpenAIEmbeddings


class EmbeddingManager:

    def __init__(self):
        BASE_DIR = Path(__file__).parent.parent

        self.LLAMA_SERVER = BASE_DIR / "runtime" / "llama-server.exe"
        self.MODEL = BASE_DIR / "models" / "Qwen3-Embedding-0.6B-Q8_0.gguf"

        self.SERVER_URL = "http://127.0.0.1:8081"

        self.process = None

        self.embeddings = OpenAIEmbeddings(
            model="Qwen3-Embedding-0.6B-Q8_0.gguf",
            api_key="local",
            base_url=f"{self.SERVER_URL}/v1",
        )

    def start(self):

        self.process = subprocess.Popen(
            [
                str(self.LLAMA_SERVER),
                "-m", str(self.MODEL),
                "--embedding",
                "--pooling", "last",
                "--host", "127.0.0.1",
                "--port", "8081",
            ],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )

        print("Starting Qwen3 embedding model...")

        for _ in range(60):

            try:
                health = requests.get(
                    f"{self.SERVER_URL}/health",
                    timeout=1
                )

                if health.status_code == 200:
                    print("Embedding model is ready.")
                    return

            except requests.RequestException:
                pass

            time.sleep(1)

        self.process.terminate()
        self.process = None

        raise RuntimeError(
            "Embedding llama-server failed to start."
        )





    def embed_documents(self, texts):
        return self.embeddings.embed_documents(texts)

    def embed_query(self, query):
        instructed_query = (
            "Instruct: Given a query, retrieve relevant passages that "
            "answer the query\n"
            f"Query: {query}"
        )

        return self.embeddings.embed_query(instructed_query)




    def stop(self):
        if self.process is not None:
            self.process.terminate()
            self.process.wait()
            self.process = None