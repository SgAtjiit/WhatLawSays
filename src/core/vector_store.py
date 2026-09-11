import uuid
from typing import Any, Dict, List, Optional
from fastembed import SparseTextEmbedding, TextEmbedding
from qdrant_client import AsyncQdrantClient, models
from src.config import settings
from src.schemas.corpus import LegalSectionDoc

# Canonical `act` payload values, exactly as indexed in the collection.
ACT_BNS = "Bharatiya Nyaya Sanhita, 2023 (BNS)"
ACT_BNSS = "Bharatiya Nagarik Suraksha Sanhita, 2023 (BNSS)"
ACT_BSA = "Bharatiya Sakshya Adhiniyam, 2023 (BSA)"
ACT_CONSTITUTION = "Constitution of India"

# Only the BNS creates offences. Searching it alongside the other three left the
# substantive penal law outnumbered roughly 3:1 in every candidate pool, so
# procedural and constitutional provisions crowded out the sections an offence
# analysis actually needs.
ACT_IT = "The Information Technology Act, 2000 (IT Act)"
ACT_POSH = (
    "The Sexual Harassment of Women at Workplace "
    "(Prevention, Prohibition and Redressal) Act, 2013 (POSH Act)"
)

# The IT Act (ss. 65-74) and the POSH Act (s. 26) both create offences, so they
# join the BNS in the offence-identification pass. Their procedural and
# definitional sections are filtered out downstream by title, exactly as the
# BNS's own preliminary provisions already are.
SUBSTANTIVE_ACTS = [ACT_BNS, ACT_IT, ACT_POSH]
PROCEDURAL_ACTS = [ACT_BNSS, ACT_BSA, ACT_CONSTITUTION]

# Namespace for deterministic point ids (see _point_id).
_POINT_NAMESPACE = uuid.UUID("6f9619ff-8b86-d011-b42d-00c04fc964ff")


def _point_id(doc: LegalSectionDoc) -> str:
    """Stable id derived from the act and section.

    The previous scheme numbered points by their position in the batch, so
    ingesting one Act on its own would silently overwrite the first N points of
    whatever was already indexed. Deriving the id from the document's identity
    makes ingestion idempotent and safely incremental.
    """
    return str(uuid.uuid5(_POINT_NAMESPACE, f"{doc.act}|{doc.section_number}"))


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

  async def recreate_collection(self):
    """Drops and rebuilds the collection, for a full corpus rebuild."""
    await self.ensure_initialized()
    await self.client.delete_collection(collection_name=self.collection_name)
    await self.setup_collection()
    await self._ensure_act_index()

  async def ensure_initialized(self):
    """Ensures that the Qdrant client connection and collection are initialized."""
    if self.client is None:
      await self.setup_collection()
      await self._ensure_act_index()

  async def _ensure_act_index(self):
    """Index the `act` payload field so act-scoped retrieval filters efficiently.

    Idempotent: re-creating an existing index is a no-op error we can ignore, so
    this also upgrades collections that were indexed before scoping existed.
    """
    try:
      await self.client.create_payload_index(
          collection_name=self.collection_name,
          field_name="act",
          field_schema=models.PayloadSchemaType.KEYWORD,
      )
    except Exception:
      pass

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
      for doc, dense_vec, sparse_vec in zip(
          batch_docs, dense_embeddings, sparse_embeddings
      ):
        point_id = _point_id(doc)
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
      self, query_text: str, limit: int = 5, acts: Optional[List[str]] = None
  ) -> List[Dict[str, Any]]:
    """Runs parallel dense & sparse search and merges results via Reciprocal Rank Fusion.

    `acts` restricts the search to those statutes (see SUBSTANTIVE_ACTS /
    PROCEDURAL_ACTS). The filter is applied to each prefetch so the restriction
    shapes candidate generation rather than merely trimming the fused result.
    """
    await self.ensure_initialized()
    dense_query = list(self.dense_model.embed([query_text]))[0].tolist()
    sparse_query = list(self.sparse_model.embed([query_text]))[0]

    act_filter = (
        models.Filter(
            must=[models.FieldCondition(key="act", match=models.MatchAny(any=acts))]
        )
        if acts
        else None
    )

    prefetch = [
        # Sparse BM25 Keyword Search
        models.Prefetch(
            query=models.SparseVector(
                indices=sparse_query.indices.tolist(),
                values=sparse_query.values.tolist(),
            ),
            using="sparse",
            limit=20,
            filter=act_filter,
        ),
        # Dense Semantic Search
        models.Prefetch(
            query=dense_query,
            using="dense",
            limit=20,
            filter=act_filter,
        ),
    ]

    # Qdrant native Reciprocal Rank Fusion (RRF)
    response = await self.client.query_points(
        collection_name=self.collection_name,
        prefetch=prefetch,
        query=models.FusionQuery(fusion=models.Fusion.RRF),
        limit=limit,
    )

    # Carry the fusion score and rank onto the payload: the reranker fallback and
    # the confidence estimator both need a retrieval signal, and payload-only
    # returns discarded it.
    results = []
    for rank, point in enumerate(response.points):
        payload = dict(point.payload or {})
        payload["rrf_score"] = float(point.score) if point.score is not None else None
        payload["rrf_rank"] = rank
        results.append(payload)
    return results


vector_store = LegalVectorStore()