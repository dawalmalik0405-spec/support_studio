from langchain_core.documents import Document

from rag.managers.embeddings_manager import EmbeddingManager
from rag.managers.vector_store import VectorStoreManager
from rag.managers.llm_manager import LLMManager
from rag.prompt_manager import PromptManager

from rag.retriever import Retriever
from rag.rag_pipeline import RAGPipeline
from rag.query_router import QueryRouter


class RAGService:

    def __init__(self):
        self.embedding_manager = EmbeddingManager()
        self.vector_store_manager = None
        self.llm_manager = LLMManager()

        self.retriever = None
        self.agent_retrievers = {}
        self.prompt_manager = PromptManager()
        self.rag_pipeline = None
        self.router = None

    def start(self):

        self.embedding_manager.start()

        self.vector_store_manager = VectorStoreManager(
            self.embedding_manager
        )

        # Automatically detect and sync documents from uploads/ on startup
        from rag.document_parsing.ingestion_pipeline import IngestionPipeline
        ingestion = IngestionPipeline(
            embedding_manager=self.embedding_manager,
            vector_store_manager=self.vector_store_manager
        )
        ingestion.run()

        documents = self._load_documents()

        self.retriever = Retriever(
            self.vector_store_manager.vector_store,
            self.embedding_manager,
            documents
        )

        self.llm_manager.start()

        self.rag_pipeline = RAGPipeline(
            retriever=self.retriever,
            prompt_manager=self.prompt_manager,
            llm_manager=self.llm_manager
        )

        # The interactive RAG path does not need a separate query router.

    def _load_documents(self, agent_id=None):
        options = {"include": ["documents", "metadatas"]}
        if agent_id is not None:
            options["where"] = {"agent_id": str(agent_id)}
        data = self.vector_store_manager.vector_store._collection.get(**options)

        documents = []

        for text, metadata in zip(
            data["documents"],
            data["metadatas"]
        ):
            documents.append(
                Document(
                    page_content=text,
                    metadata=metadata
                )
            )

        return documents

    def refresh_agent_retriever(self, agent_id):
        if not self.vector_store_manager or not self.embedding_manager:
            raise RuntimeError("RAGService has not been started.")
        agent_id = str(agent_id)
        self.agent_retrievers[agent_id] = Retriever(
            self.vector_store_manager.vector_store,
            self.embedding_manager,
            self._load_documents(agent_id),
            agent_id=agent_id,
        )

    def index_google_drive(self, agent_id, credentials, selected_items, known_versions=None):
        if not self.vector_store_manager or not self.embedding_manager:
            raise RuntimeError("RAGService has not been started.")

        from rag.document_parsing.ingestion_pipeline import IngestionPipeline
        ingestion = IngestionPipeline(
            embedding_manager=self.embedding_manager,
            vector_store_manager=self.vector_store_manager,
        )
        try:
            return ingestion.run_google_drive(
                credentials,
                selected_items,
                agent_id=str(agent_id),
                known_versions=known_versions,
            )
        finally:
            self.refresh_agent_retriever(agent_id)

    def remove_agent_document(self, agent_id, drive_file_id):
        if not self.vector_store_manager:
            raise RuntimeError("RAGService has not been started.")
        document_id = f"{agent_id}:gdrive:{drive_file_id}"
        self.vector_store_manager.delete_document(document_id)
        from rag.document_parsing.ingest import registry
        registry.delete_document(document_id)
        self.refresh_agent_retriever(agent_id)

    def has_agent_document(self, agent_id, drive_file_id):
        if not self.vector_store_manager:
            raise RuntimeError("RAGService has not been started.")
        document_id = f"{agent_id}:gdrive:{drive_file_id}"
        return self.vector_store_manager.has_document(document_id)

    def delete_agent(self, agent_id):
        if not self.vector_store_manager:
            raise RuntimeError("RAGService has not been started.")
        agent_id = str(agent_id)
        deleted_chunks = self.vector_store_manager.delete_agent_documents(agent_id)
        from rag.document_parsing.ingest import registry
        for record in registry.get_all_documents():
            if record["document_id"].startswith(f"{agent_id}:gdrive:"):
                registry.delete_document(record["document_id"])
        self.agent_retrievers.pop(agent_id, None)
        return deleted_chunks

    def ask_agent(
        self,
        agent_id,
        question,
        k=8,
        enable_thinking=False,
        yield_events=False,
        agent_instructions=None,
        agent_tone=None,
        max_tokens=1500,
    ):
        agent_id = str(agent_id)
        if agent_id not in self.agent_retrievers:
            self.refresh_agent_retriever(agent_id)
        pipeline = RAGPipeline(
            retriever=self.agent_retrievers[agent_id],
            prompt_manager=self.prompt_manager,
            llm_manager=self.llm_manager,
        )
        return pipeline.ask(
            question,
            k=k,
            enable_thinking=enable_thinking,
            yield_events=yield_events,
            agent_instructions=agent_instructions,
            agent_tone=agent_tone,
            max_tokens=max_tokens,
        )

    def ask(self, question, k=8, enable_thinking=False, yield_events=False):

        if self.rag_pipeline is None:
            raise RuntimeError(
                "RAGService has not been started."
            )

        return self.rag_pipeline.ask(
            question,
            k=k,
            enable_thinking=enable_thinking,
            yield_events=yield_events
        )

    def route_query(self, question):

        if self.router is None:
            return "RAG"
        return self.router.route(question)

    def sync_documents(self):
        if not self.vector_store_manager or not self.embedding_manager:
            raise RuntimeError("RAGService has not been started.")

        from rag.document_parsing.ingestion_pipeline import IngestionPipeline
        ingestion = IngestionPipeline(
            embedding_manager=self.embedding_manager,
            vector_store_manager=self.vector_store_manager
        )
        stats = ingestion.run()

        # Reload documents and refresh Retriever & Pipeline
        documents = self._load_documents()
        self.retriever = Retriever(
            self.vector_store_manager.vector_store,
            self.embedding_manager,
            documents
        )
        if self.rag_pipeline:
            self.rag_pipeline.retriever = self.retriever

        return stats or {"indexed": 0, "deleted": 0}

    def get_documents_metadata_summary(self):
        if not self.retriever or not self.retriever.documents:
            return "No documents are currently indexed."

        files = {}
        for doc in self.retriever.documents:
            meta = doc.metadata
            source = meta.get("source_file") or meta.get("document_id") or "Unknown"
            if source not in files:
                files[source] = {
                    "file_type": meta.get("file_type", "document"),
                    "chunks": 0,
                    "pages": set(),
                }
            files[source]["chunks"] += 1
            page = meta.get("page")
            if page is not None:
                files[source]["pages"].add(page)

        summary_lines = [
            f"Total files: {len(files)}, Total chunks in database: {len(self.retriever.documents)}",
            "Files in database:"
        ]

        for idx, (filename, info) in enumerate(files.items(), 1):
            page_text = f", Pages: {len(info['pages'])}" if info["pages"] else ""
            summary_lines.append(
                f"- Document {idx}: {filename} (Type: {info['file_type']}{page_text}, Indexed Chunks: {info['chunks']})"
            )

        return "\n".join(summary_lines)

    def overview(self, question):
        if self.llm_manager is None or self.prompt_manager is None:
            raise RuntimeError(
                "RAGService has not been started."
            )

        docs_metadata = self.get_documents_metadata_summary()
        prompt_template = self.prompt_manager.load_prompt("corpus_overview.md")
        prompt = prompt_template.replace("{{question}}", question.strip())
        prompt = prompt.replace("{{documents_metadata}}", docs_metadata)

        return self.llm_manager.generate(prompt, max_tokens=1500, stream=True)

    def stop(self):
        if self.llm_manager:
            self.llm_manager.stop()
        if self.embedding_manager:
            self.embedding_manager.stop()
