from pathlib import Path


class PromptManager:

    def __init__(self):
        BASE_DIR = Path(__file__).parent
        self.PROMPT_DIR = BASE_DIR / "prompts"

    def load_prompt(self, prompt_name):
        prompt_path = self.PROMPT_DIR / prompt_name

        if not prompt_path.exists():
            raise FileNotFoundError(
                f"Prompt file not found: {prompt_path}"
            )

        return prompt_path.read_text(encoding="utf-8")

    def build_rag_prompt(self, prompt, context, question):

        prompt = self.load_prompt(prompt)

        prompt = prompt.replace(
            "{{context}}",
            context
        )

        prompt = prompt.replace(
            "{{question}}",
            question
        )

        return prompt

    def build_rag_system_prompt(self, prompt_name="rag_answer.md"):
        """Load the shared RAG instructions as a dedicated system message."""
        prompt = self.load_prompt(prompt_name)
        for placeholder in ("{{context}}", "{{question}}"):
            prompt = prompt.replace(placeholder, "")
        return prompt
