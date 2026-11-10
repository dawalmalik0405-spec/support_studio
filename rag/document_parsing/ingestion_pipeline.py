from rag.document_parsing.ingest import normalized_data, registry
from rag.chunking import DocumentChunker
from rag.managers.embeddings_manager import EmbeddingManager
from rag.managers.vector_store import VectorStoreManager


class IngestionPipeline:

    def __init__(self, embedding_manager=None, vector_store_manager=None):
        self.chunker = DocumentChunker()
        self._owns_embedding = embedding_manager is None
        self.embedding_manager = embedding_manager or EmbeddingManager()
        self.vector_store_manager = vector_store_manager

    def run(self):

        # Get only new or changed documents
        documents, deleted_documents = normalized_data()

        if not documents and not deleted_documents:
            print("No new or changed documents to ingest.")
            return {"indexed": 0, "deleted": 0}

        if self._owns_embedding and self.embedding_manager.process is None:
            self.embedding_manager.start()

        try:
            if self.vector_store_manager is None:
                self.vector_store_manager = VectorStoreManager(
                    self.embedding_manager
                )

            for document_id in deleted_documents:

                print(
                    f"\nDeleting document: {document_id}"
                )

                self.vector_store_manager.delete_document(
                    document_id
                )

                registry.delete_document(
                    document_id
                )

                print(
                    f"Successfully deleted: {document_id}"
                )

            for document in documents:

                document_id = document["document_id"]
                fingerprint = document["fingerprint"]
                file_path = document["file_path"]

                print(
                    f"\nIndexing document: {document_id}"
                )

                # Normalized data → chunks
                chunks = self.chunker.chunk(
                    document["data"]
                )

                # Synchronize chunks with Chroma
                self.vector_store_manager.sync_document(
                    chunks
                )

                # Only mark document as indexed
                # after Chroma succeeds
                registry.save_document(
                    document_id=document_id,
                    file_path=file_path,
                    fingerprint=fingerprint,
                    indexed_at=self._timestamp()
                )

                print(
                    f"Successfully indexed: {document_id}"
                )

            return {"indexed": len(documents), "deleted": len(deleted_documents)}

        finally:
            if self._owns_embedding:
                self.embedding_manager.stop()

    def _timestamp(self):
        from datetime import datetime, timezone

        return datetime.now(
            timezone.utc
        ).isoformat()


    
    def run_google_drive(
        self, credentials, selected_items, agent_id, known_versions=None
    ):
        from rag.document_parsing.google_drive_ingest import (
            normalized_drive_data,
        )

        documents, report = normalized_drive_data(
            credentials,
            selected_items,
            agent_id=agent_id,
            known_versions=known_versions,
        )

        if not documents:
            return {
                "indexed": 0,
                "skipped": report["skipped"],
                "errors": report["unsupported_or_inaccessible"],
                "files": report["files"],
                "root_sources": report["root_sources"],
                "unavailable_ids": report["unavailable_ids"],
            }

        if self._owns_embedding and self.embedding_manager.process is None:
            self.embedding_manager.start()

        try:
            if self.vector_store_manager is None:
                self.vector_store_manager = VectorStoreManager(
                    self.embedding_manager
                )

            indexed = 0

            for document in documents:
                document_id = document["document_id"]

                print(f"\nIndexing Google Drive document: {document_id}")

                chunks = self.chunker.chunk(document["data"])

                self.vector_store_manager.sync_document(chunks)

                # Register only after Chroma successfully synchronizes.
                registry.save_document(
                    document_id=document_id,
                    file_path=document["file_path"],
                    fingerprint=document["fingerprint"],
                    indexed_at=self._timestamp(),
                )

                indexed += 1

            return {
                "indexed": indexed,
                "skipped": report["skipped"],
                "errors": report["unsupported_or_inaccessible"],
                "files": report["files"],
                "root_sources": report["root_sources"],
                "unavailable_ids": report["unavailable_ids"],
            }

        finally:
            if self._owns_embedding:
                self.embedding_manager.stop()



    
