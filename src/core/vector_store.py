from typing import Any, Dict, List
from fastembed import SparseTextEmbedding, TextEmbedding
from qdrant_client import AsyncQdrantClient, models
from src.config import settings
from src.schemas.corpus import LegalSectionDoc


class LegalVectorStore:

  def __init__(self):
    self.client = AsyncQdrantClient(url=settings.QDRANT_URL)
    self.collection_name = "whatlawsays_legal_corpus"

    # Embedding models (lightweight, highly optimized via ONNX runtime)
    self.dense_model = TextEmbedding(model_name="BAAI/bge-small-en-v1.5")
    self.sparse_model = SparseTextEmbedding(model_name="Qdrant/bm25")

  async def setup_collection(self):
    """Initializes collection with both Dense and Sparse index configurations."""
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

  async def upsert_legal_documents(self, documents: List[LegalSectionDoc]):
    """Embeds documents into dense + sparse vectors and upserts into Qdrant."""
    texts = [doc.to_search_payload()["composite_text"] for doc in documents]

    # Generate dense embeddings (returns generator -> cast to list)
    dense_embeddings = list(self.dense_model.embed(texts))
    # Generate sparse BM25 vectors
    sparse_embeddings = list(self.sparse_model.embed(texts))

    points = []
    for idx, (doc, dense_vec, sparse_vec) in enumerate(
        zip(documents, dense_embeddings, sparse_embeddings)
    ):
      points.append(
          models.PointStruct(
              id=idx + 1,
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

  async def hybrid_search(
      self, query_text: str, limit: int = 5
  ) -> List[Dict[str, Any]]:
    """Runs parallel dense & sparse search and merges results via Reciprocal Rank Fusion."""
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