from typing import Any, Dict, List
from fastembed import SparseTextEmbedding, TextEmbedding
from qdrant_client import AsyncQdrantClient, models
from src.config import settings
from src.schemas.corpus import LegalSectionDoc


class LegalVectorStore:

  def __init__(self):
    self.collection_name = "whatlawsays_legal_corpus"
    # Check if Qdrant URL is specified or fallback to local disk storage
    self.url = settings.QDRANT_URL
    self.client = None

    # Embedding models (lightweight, highly optimized via ONNX runtime)
    self.dense_model = TextEmbedding(model_name="BAAI/bge-small-en-v1.5")
    self.sparse_model = SparseTextEmbedding(model_name="Qdrant/bm25")

  async def setup_collection(self):
    """Initializes collection with both Dense and Sparse index configurations."""
    if self.client is None:
      import socket
      server_available = False
      if self.url.startswith("http"):
        try:
          # Extract host and port from URL
          from urllib.parse import urlparse
          parsed = urlparse(self.url)
          host = parsed.hostname or "localhost"
          port = parsed.port or 6333
          with socket.create_connection((host, port), timeout=0.3):
            server_available = True
        except Exception:
          server_available = False

      if server_available:
        try:
          self.client = AsyncQdrantClient(url=self.url, check_compatibility=False)
          print(f"[+] Connected to Qdrant Vector Server at [{self.url}]", flush=True)
        except Exception:
          server_available = False

      if not server_available or self.client is None:
        print("[+] Qdrant HTTP server not reachable. Initializing local embedded Qdrant database at ['./qdrant_db']...", flush=True)
        self.client = AsyncQdrantClient(path="./qdrant_db")

    collections = await self.client.get_collections()
    exists = any(c.name == self.collection_name for c in collections.collections)

    if not exists:
      await self.client.create_collection(
          collection_name=self.collection_name,
          vectors_config={
              "dense": models.VectorParams(
                  size=384,  # bge-small dimension
                  distance=models.Distance.COSINE,
              )
          },
          sparse_vectors_config={
              "sparse": models.SparseVectorParams(
                  index=models.SparseIndexParams(on_disk=False)
              )
          },
      )

  async def ensure_initialized(self):
    """Ensures that the Qdrant client connection and collection are initialized."""
    if self.client is None:
      await self.setup_collection()

  async def upsert_legal_documents(
      self, documents: List[LegalSectionDoc], batch_size: int = 100
  ):
    """Embeds documents into dense + sparse vectors and upserts into Qdrant in batches."""
    await self.ensure_initialized()
    total_docs = len(documents)
    print(f"[+] Total documents to embed and upsert: {total_docs}", flush=True)

    for i in range(0, total_docs, batch_size):
      batch_docs = documents[i : i + batch_size]
      texts = [doc.to_search_payload()["composite_text"] for doc in batch_docs]

      dense_embeddings = list(self.dense_model.embed(texts))
      sparse_embeddings = list(self.sparse_model.embed(texts))

      points = []
      for offset, (doc, dense_vec, sparse_vec) in enumerate(
          zip(batch_docs, dense_embeddings, sparse_embeddings)
      ):
        point_id = i + offset + 1
        points.append(
            models.PointStruct(
                id=point_id,
                vector={
                    "dense": dense_vec.tolist(),
                    "sparse": models.SparseVector(
                        indices=sparse_vec.indices.tolist(),
                        values=sparse_vec.values.tolist(),
                    ),
                },
                payload=doc.to_search_payload(),
            )
        )

      await self.client.upsert(
          collection_name=self.collection_name, points=points
      )
      print(f"  [+] Upserted batch {i // batch_size + 1}/{(total_docs + batch_size - 1) // batch_size} ({min(i + batch_size, total_docs)}/{total_docs} docs)...", flush=True)

  async def hybrid_search(
      self, query_text: str, limit: int = 5
  ) -> List[Dict[str, Any]]:
    """Runs parallel dense & sparse search and merges results via Reciprocal Rank Fusion."""
    await self.ensure_initialized()
    dense_query = list(self.dense_model.embed([query_text]))[0].tolist()
    sparse_query = list(self.sparse_model.embed([query_text]))[0]

    prefetch = [
        # Sparse BM25 Keyword Search
        models.Prefetch(
            query=models.SparseVector(
                indices=sparse_query.indices.tolist(),
                values=sparse_query.values.tolist(),
            ),
            using="sparse",
            limit=20,
        ),
        # Dense Semantic Search
        models.Prefetch(
            query=dense_query,
            using="dense",
            limit=20,
        ),
    ]

    # Qdrant native Reciprocal Rank Fusion (RRF)
    response = await self.client.query_points(
        collection_name=self.collection_name,
        prefetch=prefetch,
        query=models.FusionQuery(fusion=models.Fusion.RRF),
        limit=limit,
    )

    return [point.payload for point in response.points]


vector_store = LegalVectorStore()