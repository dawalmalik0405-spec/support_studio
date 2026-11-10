from rank_bm25 import BM25Okapi
import re



# Common English stopwords that add noise to BM25 scoring
STOPWORDS = frozenset({
    "a", "an", "the", "is", "are", "was", "were", "be", "been",
    "am", "do", "does", "did", "will", "would", "shall", "should",
    "can", "could", "may", "might", "must", "have", "has", "had",
    "i", "me", "my", "we", "our", "you", "your", "he", "she",
    "it", "its", "they", "them", "their", "this", "that", "these",
    "those", "what", "which", "who", "whom", "how", "when", "where",
    "why", "if", "then", "so", "but", "and", "or", "not", "no",
    "in", "on", "at", "to", "for", "of", "with", "by", "from",
    "as", "into", "about", "between", "through", "after", "before",
    "tell", "give", "show", "file", "document",
})


class Retriever:

    def __init__(self, vector_store, embedding_manager, documents, agent_id=None):
        self.vector_store = vector_store
        self.embedding_manager = embedding_manager
        self.documents = documents
        self.agent_id = str(agent_id) if agent_id is not None else None

        self.bm25 = self.build_bm25_index()


    def tokenize(self, text):
        """Tokenize with stopword removal for better BM25 precision."""
        tokens = re.findall(r"\b\w+\b", text.lower())
        filtered = [t for t in tokens if t not in STOPWORDS]
        # Fall back to all tokens if filtering removes everything
        return filtered if filtered else tokens

    def _build_bm25_text(self, document):
        """Build enriched text for BM25 that includes the filename.

        Repeating the human-readable filename ensures that queries
        referencing a document by name (e.g. "weekly work update")
        score highly even when the body text doesn't contain those
        exact words.
        """
        source_file = document.metadata.get("source_file", "")
        document_id = document.metadata.get("document_id", "")
        # Turn underscores / dots / hyphens into spaces
        clean_name = re.sub(r"[_.\-/]", " ", source_file)
        clean_id = re.sub(r"[_.\-/]", " ", document_id)
        return (
            f"{source_file} {clean_name} {clean_name} "
            f"{clean_id} {document.page_content}"
        )

    def build_bm25_index(self):
        tokenized = [
            self.tokenize(self._build_bm25_text(doc))
            for doc in self.documents
        ]

        return BM25Okapi(tokenized) if tokenized else None

    def rebuild_bm25_index(self):
        """Rebuild the BM25 index after documents have changed."""
        self.bm25 = self.build_bm25_index()


    def reciprocal_rank_fusion(self, dense_results, bm25_results):
        scores = {}
        documents = {}

        result_sets = [
            (dense_results, 0.4),
            (bm25_results, 0.6)
        ]

        for results, weight in result_sets:
            for rank, document in enumerate(results):
                document_id = (
                    document.metadata.get("source_file"),
                    document.metadata.get("page"),
                    document.metadata.get("item_index"),
                    document.page_content
                )

                if document_id not in scores:
                    scores[document_id] = 0
                    documents[document_id] = document

                scores[document_id] += (
                    weight / (60 + rank + 1)
                )

        ranked_documents = sorted(
            scores,
            key=scores.get,
            reverse=True
        )

        return [
            documents[document_id]
            for document_id in ranked_documents
        ]



    def retrieve(self, query, k=8):
        if not self.documents:
            return []

        candidate_k = 30

        # Dense search
        query_vector = self.embedding_manager.embed_query(query)

        search_options = {"k": candidate_k}
        if self.agent_id:
            search_options["filter"] = {"agent_id": self.agent_id}
        dense_results = self.vector_store.similarity_search_by_vector(
            query_vector,
            **search_options,
        )

        # BM25 search
        if self.bm25 is None:
            bm25_results = []
        else:
            query_tokens = self.tokenize(query)

            bm25_scores = self.bm25.get_scores(query_tokens)

            ranked_indexes = sorted(
                range(len(bm25_scores)),
                key=lambda i: bm25_scores[i],
                reverse=True
            )[:candidate_k]

            bm25_results = [
                self.documents[i]
                for i in ranked_indexes
            ]


        final_results = self.reciprocal_rank_fusion(
            dense_results,
            bm25_results
        )

        return final_results[:k]
