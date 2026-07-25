"""向量存储"""
import hashlib
import os
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
            # 无 embedding 模型可用，写入空索引标记
            return 0

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
            return None

        from langchain_community.vectorstores import FAISS

        index_path = self._get_faiss_index_path(collection_name)
        if os.path.exists(index_path):
            return FAISS.load_local(
                index_path, emb,
                allow_dangerous_deserialization=True,
            )
        return None

    def similarity_search(
        self,
        query: str,
        k: int = 5,
        collection_name: str = "course_docs",
        filter: Optional[Dict[str, Any]] = None,
    ) -> List[Tuple[Document, float]]:
        """相似度搜索"""
        store = self.get_store(collection_name)
        if store is None:
            return []

        if filter:
            docs = store.similarity_search_with_score(query, k=k, filter=filter)
        else:
            docs = store.similarity_search_with_score(query, k=k)

        return docs

    def delete_collection(self, collection_name: str = "course_docs"):
        index_path = self._get_faiss_index_path(collection_name)
        if os.path.exists(index_path):
            os.remove(index_path)

    @staticmethod
    def compute_content_hash(content: str) -> str:
        return hashlib.md5(content.encode("utf-8")).hexdigest()
