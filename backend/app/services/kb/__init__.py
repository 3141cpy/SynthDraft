"""工程规范知识库（KB）服务层。

子模块：
- embedder：bge-m3 向量化（含 CPU 友好回退）
- qdrant_store：Qdrant 客户端封装
- indexer：从 Markdown 样本构建向量索引
- retriever：LlamaIndex 混合检索
"""

from __future__ import annotations
