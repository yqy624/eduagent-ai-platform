"""向量存储"""
import hashlib
import os
import re
import shutil
from typing import Any, Dict, List, Optional, Tuple
from langchain_core.documents import Document

from ai.llm import get_embeddings


class VectorStoreManager:
    """向量存储管理器 — 优先使用 FAISS"""

    def __init__(self, persist_directory: Optional[str] = None):
        self.persist_directory = persist_directory or os.path.join(
            os.path.dirname(os.path.dirname(__file__)), "data", "vector_store"
        )
        os.makedirs(self.persist_directory, exist_ok=True)
        self._embeddings = None

    @property
    def embeddings(self):
        if self._embeddings is None:
            self._embeddings = get_embeddings()
        return self._embeddings

    def _get_faiss_index_path(self, collection_name: str) -> str:
        return os.path.join(self.persist_directory, f"{collection_name}.faiss")

    def add_documents(
        self, documents: List[Document], collection_name: str = "course_docs"
    ) -> int:
        """添加文档到向量库"""
        emb = self.embeddings
        if emb is None:
            raise RuntimeError("Embedding model is not configured; vector indexing is unavailable")

        from langchain_community.vectorstores import FAISS

        index_path = self._get_faiss_index_path(collection_name)
        try:
            store = FAISS.load_local(
                index_path, emb,
                allow_dangerous_deserialization=True,
            )
            store.add_documents(documents)
        except (FileNotFoundError, Exception):
            store = FAISS.from_documents(documents, emb)

        store.save_local(index_path)
        return len(documents)

    def get_store(self, collection_name: str = "course_docs") -> Any:
        """获取 FAISS 向量存储实例"""
        emb = self.embeddings
        if emb is None:
            raise RuntimeError("Embedding model is not configured; vector search is unavailable")

        from langchain_community.vectorstores import FAISS

        index_path = self._get_faiss_index_path(collection_name)
        if os.path.exists(index_path):
            return FAISS.load_local(
                index_path, emb,
                allow_dangerous_deserialization=True,
            )
        raise RuntimeError(f"Vector collection '{collection_name}' does not exist")

    def similarity_search(
        self,
        query: str,
        k: int = 5,
        collection_name: str = "course_docs",
        filter: Optional[Dict[str, Any]] = None,
    ) -> List[Tuple[Document, float]]:
        """相似度搜索"""
        store = self.get_store(collection_name)

        if filter:
            docs = store.similarity_search_with_score(query, k=k, filter=filter)
        else:
            docs = store.similarity_search_with_score(query, k=k)

        return docs

    def delete_collection(self, collection_name: str = "course_docs"):
        index_path = self._get_faiss_index_path(collection_name)
        if os.path.exists(index_path):
            if os.path.isdir(index_path):
                shutil.rmtree(index_path)
            else:
                os.remove(index_path)

    @staticmethod
    def compute_content_hash(content: str) -> str:
        return hashlib.md5(content.encode("utf-8")).hexdigest()

    @staticmethod
    def lexical_similarity(query: str, content: str) -> float:
        """Small local fallback for environments without an embedding service."""
        query = (query or "").strip().lower()
        content = (content or "").strip().lower()
        if not query or not content:
            return 0.0

        if query in content:
            return 0.95

        query_tokens = set(re.findall(r"[\w\u4e00-\u9fff]+", query))
        content_tokens = set(re.findall(r"[\w\u4e00-\u9fff]+", content))
        query_cjk = "".join(re.findall(r"[\u4e00-\u9fff]+", query))
        content_cjk = "".join(re.findall(r"[\u4e00-\u9fff]+", content))
        for size in (2, 3, 4):
            query_tokens.update(
                query_cjk[index:index + size]
                for index in range(max(len(query_cjk) - size + 1, 0))
            )
            content_tokens.update(
                content_cjk[index:index + size]
                for index in range(max(len(content_cjk) - size + 1, 0))
            )
        if not query_tokens or not content_tokens:
            return 0.0

        overlap = query_tokens & content_tokens
        coverage = len(overlap) / max(len(query_tokens), 1)
        jaccard = len(overlap) / max(len(query_tokens | content_tokens), 1)

        char_hits = sum(1 for ch in set(query) if ch.strip() and ch in content)
        char_score = char_hits / max(len(set(query)), 1)

        return round(min(1.0, coverage * 0.65 + jaccard * 0.2 + char_score * 0.15), 4)
