from pathlib import Path

from langchain_chroma import Chroma
import hashlib


class VectorStoreManager:

    def __init__(self, embedding_manager):

        BASE_DIR = Path(__file__).parent.parent

        self.PERSIST_DIRECTORY = BASE_DIR / "data" / "chroma"

        self.vector_store = Chroma(
            collection_name="rag_documents",
            embedding_function=embedding_manager.embeddings,
            persist_directory=str(self.PERSIST_DIRECTORY),
        )
        print("Existing Chroma documents:", self.vector_store._collection.count()) 


    def create_chunk_id(self, chunk):
        metadata = chunk.metadata

        raw_id = (
            f"{metadata.get('document_id')}|"
            f"{metadata.get('source_file')}|"
            f"{metadata.get('page')}|"
            f"{metadata.get('item_index')}|"
            f"{chunk.page_content}"
        )

        return hashlib.sha256(raw_id.encode("utf-8")).hexdigest()

    def sync_document(self, chunks):
        if not chunks:
            return

        document_id = chunks[0].metadata.get("document_id")

        if not document_id:
            raise ValueError("Chunks are missing document_id")

        # Create IDs for the new version of the document
        new_ids = [
            self.create_chunk_id(chunk)
            for chunk in chunks
        ]

        # Get existing chunks belonging to this document
        existing = self.vector_store._collection.get(
            where={"document_id": document_id},
            include=["metadatas"]
        )

        existing_ids = existing.get("ids", [])

        # IDs that no longer exist in the updated document
        ids_to_delete = [
            chunk_id
            for chunk_id in existing_ids
            if chunk_id not in new_ids
        ]

        # Delete stale chunks
        if ids_to_delete:
            self.vector_store.delete(ids=ids_to_delete)

        # Add only chunks that don't already exist
        existing_id_set = set(existing_ids)

        new_chunks = []
        new_chunk_ids = []

        for chunk, chunk_id in zip(chunks, new_ids):
            if chunk_id not in existing_id_set:
                new_chunks.append(chunk)
                new_chunk_ids.append(chunk_id)

        if new_chunks:
            self.vector_store.add_documents(
                documents=new_chunks,
                ids=new_chunk_ids
            )

        print(f"Document: {document_id}")
        print(f"Existing chunks: {len(existing_ids)}")
        print(f"New chunks: {len(new_chunks)}")
        print(f"Deleted chunks: {len(ids_to_delete)}")




    def delete_document(self, document_id):
        existing = self.vector_store._collection.get(
            where={"document_id": document_id},
            include=["metadatas"]
        )

        existing_ids = existing.get("ids", [])

        if existing_ids:
            self.vector_store.delete(ids=existing_ids)

        print(f"Deleted document from Chroma: {document_id}")
        print(f"Deleted chunks: {len(existing_ids)}")

    def has_document(self, document_id):
        existing = self.vector_store._collection.get(
            where={"document_id": document_id},
            include=["metadatas"],
        )
        return bool(existing.get("ids"))

    def delete_agent_documents(self, agent_id):
        existing = self.vector_store._collection.get(
            where={"agent_id": str(agent_id)},
            include=["metadatas"],
        )
        ids = existing.get("ids", [])
        if ids:
            self.vector_store.delete(ids=ids)
        return len(ids)
