from langchain_core.documents import Document
from langchain_text_splitters import RecursiveCharacterTextSplitter


class DocumentChunker:

    def __init__(self):
        self.splitter = RecursiveCharacterTextSplitter(
            chunk_size=1000,
            chunk_overlap=200
        )

    def chunk(self, normalized_data):

        documents = []

        for item in normalized_data:
            documents.append(
                Document(
                    page_content=item["text"],
                    metadata=item["metadata"]
                )
            )

        chunks = self.splitter.split_documents(documents)

        return chunks

