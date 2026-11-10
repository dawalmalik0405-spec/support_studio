class RAGPipeline:

    def __init__(
        self,
        retriever,
        prompt_manager,
        llm_manager
    ):
        self.retriever = retriever
        self.prompt_manager = prompt_manager
        self.llm_manager = llm_manager

    def build_context(self, documents):
        context_parts = []

        for index, document in enumerate(
            documents,
            start=1
        ):
            metadata = document.metadata

            source_file = metadata.get(
                "source_file",
                "Unknown"
            )

            page = metadata.get("page")

            if page is not None:
                source = f"{source_file}, Page {page}"
            else:
                source = source_file

            context_parts.append(
                f"[Source {index}]\n"
                f"Document: {source}\n\n"
                f"{document.page_content}"
            )

        return "\n\n".join(context_parts)

    def build_sources(self, documents):
        sources = []

        for index, document in enumerate(
            documents,
            start=1
        ):
            metadata = document.metadata

            sources.append({
                "source_id": index,
                "document_id": metadata.get(
                    "document_id"
                ),
                "source_file": metadata.get(
                    "source_file"
                ),
                "page": metadata.get(
                    "page"
                ),
                "file_type": metadata.get(
                    "file_type"
                ),
            })

        return sources

    def ask(
        self,
        question,
        k=8,
        enable_thinking=False,
        yield_events=False,
        agent_instructions=None,
        agent_tone=None,
        max_tokens=1500,
    ):

        documents = self.retriever.retrieve(
            question,
            k=k
        )

        context = self.build_context(
            documents
        )

        sources = self.build_sources(
            documents
        )

        system_prompt = self.prompt_manager.build_rag_system_prompt(
            "rag_answer.md"
        )
        user_prompt = (
            f"Retrieved context:\n\n{context or '(No relevant documents were retrieved.)'}"
            f"\n\nUser question:\n{question}"
        )
        if agent_tone or agent_instructions:
            system_prompt += "\n\nSupport agent configuration:\n"
            if agent_tone:
                system_prompt += f"Respond in a {agent_tone} tone.\n"
            if agent_instructions:
                system_prompt += f"Follow these agent instructions:\n{agent_instructions}\n"

        answer_stream = self.llm_manager.generate(
            user_prompt,
            max_tokens=max_tokens,
            system_prompt=system_prompt,
            enable_thinking=enable_thinking,
            yield_events=yield_events
        )

        return {
            "answer": answer_stream,
            "sources": sources
        }
