import re


class QueryRouter:

    VALID_ROUTES = {"GREETING", "CORPUS_OVERVIEW", "RAG"}

    def __init__(self, llm_manager, prompt_manager):
        self.llm_manager = llm_manager
        self.prompt_manager = prompt_manager

    def route(self, question: str) -> str:
        prompt_template = self.prompt_manager.load_prompt("query_router.md")
        prompt = prompt_template.replace("{{question}}", question.strip())

        response_generator = self.llm_manager.generate(
            prompt,
            max_tokens=10,
            stream=False
        )

        raw_output = next(response_generator, "").strip().upper()

        # Fast-path / Guard: If user asks about a specific file or numbered document, it's definitely RAG
        if re.search(r"\b(first|second|third|fourth|fifth|last|1st|2nd|3rd|\d+)\s+(file|doc|document)\b", question, re.IGNORECASE) or \
           re.search(r"\b\w+\.(pdf|txt|png|docx|csv)\b", question, re.IGNORECASE):
            return "RAG"

        # Prioritize exact match or word-boundary matches
        if re.search(r"\b(CORPUS_OVERVIEW|CORPUS OVERVIEW|CORPUS)\b", raw_output):
            return "CORPUS_OVERVIEW"
        if re.search(r"\b(GREETING)\b", raw_output):
            return "GREETING"
        if re.search(r"\b(RAG)\b", raw_output):
            return "RAG"

        # Fallback to RAG if classification is unclear
        return "RAG"
