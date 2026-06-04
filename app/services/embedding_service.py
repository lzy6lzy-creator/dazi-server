from __future__ import annotations

"""Embedding 服务 — bge-base-zh-v1.5 模型加载与文本编码

使用固定大小线程池（max_workers=2）限制并发推理数量，
避免并发请求同时跑模型导致内存问题。
对外暴露 async 方法，调用方无需手动 asyncio.to_thread。
"""
import asyncio
import logging
import os
from concurrent.futures import ThreadPoolExecutor

from app.core.config import settings
from app.services.location_normalizer import align_city_from_catalog, standard_city_names

# 国内服务器使用 HuggingFace 镜像
os.environ.setdefault("HF_ENDPOINT", "https://hf-mirror.com")

logger = logging.getLogger(__name__)


class EmbeddingService:
    """单例 embedding 服务，懒加载模型，线程池串行化推理"""

    def __init__(self):
        self._model = None
        self._city_embeddings = None
        # 固定线程池：限制并发推理数量，避免内存问题
        self._executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix="embedding")

    def _load_model(self):
        if self._model is None:
            from sentence_transformers import SentenceTransformer
            logger.info(f"Loading embedding model: {settings.EMBEDDING_MODEL}")
            self._model = SentenceTransformer(settings.EMBEDDING_MODEL)
            logger.info("Embedding model loaded")
        return self._model

    def _encode_sync(self, text: str) -> list[float]:
        """同步编码单条文本（在线程池内调用）"""
        model = self._load_model()
        vec = model.encode(text, normalize_embeddings=True)
        return vec.tolist()

    def _encode_batch_sync(self, texts: list[str]) -> list[list[float]]:
        """同步批量编码（在线程池内调用）"""
        model = self._load_model()
        vecs = model.encode(texts, normalize_embeddings=True, batch_size=32)
        return [v.tolist() for v in vecs]

    def _align_city_sync(self, city_raw: str | None) -> str:
        """同步城市对齐（在线程池内调用）"""
        if not city_raw or not city_raw.strip():
            return "unknown"

        catalog_city = align_city_from_catalog(city_raw)
        if catalog_city:
            return catalog_city

        if self._city_embeddings is None:
            self._init_city_embeddings()

        city_vec = self._encode_sync(city_raw.strip())
        import numpy as np
        city_vec = np.array(city_vec)

        best_city = "unknown"
        best_sim = -1.0
        for std_city, std_vec in self._city_embeddings.items():
            sim = float(np.dot(city_vec, std_vec))
            if sim > best_sim:
                best_sim = sim
                best_city = std_city

        # 相似度阈值：低于 0.5 视为未知城市
        if best_sim < 0.5:
            return city_raw.strip()

        return best_city

    async def encode(self, text: str) -> list[float]:
        """异步编码单条文本，通过线程池串行化"""
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(self._executor, self._encode_sync, text)

    async def encode_batch(self, texts: list[str]) -> list[list[float]]:
        """异步批量编码，通过线程池串行化"""
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(self._executor, self._encode_batch_sync, texts)

    async def align_city(self, city_raw: str | None) -> str:
        """异步城市对齐，通过线程池串行化"""
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(self._executor, self._align_city_sync, city_raw)

    @staticmethod
    def build_event_text(title: str, activity_type: str,
                         city: str | None = None,
                         location: str | None = None,
                         preferences: list[str] | None = None,
                         constraints: list[str] | None = None) -> str:
        """将事件关键信息拼成文本用于向量化（含城市）"""
        parts = [title, activity_type]
        if city:
            parts.append(city)
        if location:
            parts.append(location)
        if preferences:
            parts.extend(preferences)
        if constraints:
            parts.extend(constraints)
        return " ".join(parts)

    def _init_city_embeddings(self):
        """预计算标准城市列表的 embeddings（在线程池内调用）"""
        import numpy as np
        STANDARD_CITIES = list(standard_city_names())
        logger.info(f"Initializing city embeddings for {len(STANDARD_CITIES)} cities")
        vecs = self._encode_batch_sync(STANDARD_CITIES)
        self._city_embeddings = {
            city: np.array(vec) for city, vec in zip(STANDARD_CITIES, vecs)
        }
        logger.info("City embeddings initialized")

    async def close(self):
        """关闭线程池，应在 lifespan 关闭阶段调用"""
        self._executor.shutdown(wait=False)
        logger.info("Embedding thread pool shut down.")


embedding_service = EmbeddingService()
