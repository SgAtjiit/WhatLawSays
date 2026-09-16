from typing import Any, Dict, List
from src.config import settings
from src.core.logger import pipeline_logger


class LegalCrossEncoderReranker:

    def __init__(self):
        self.model_name = settings.CROSS_ENCODER_MODEL
        self._reranker = None

    def _get_reranker(self):
        if self._reranker is None:
            try:
                from fastembed.rerank.cross_encoder import TextCrossEncoder

                self._reranker = TextCrossEncoder(model_name=self.model_name)
            except Exception as e:
                pipeline_logger.log_step(
                    "LEGAL RERANKER",
                    f"Cross-encoder unavailable ({type(e).__name__}) -> RRF score ranking fallback",
                    status="WARNING",
                )
                self._reranker = False
        return self._reranker if self._reranker is not False else None

    @property
    def is_available(self) -> bool:
        """True when the cross-encoder loaded; False once it has fallen back."""
        return self._get_reranker() is not None

    async def rerank(
        self, query: str, candidate_chunks: List[Dict[str, Any]], top_k: int = 10
    ) -> List[Dict[str, Any]]:
        """Reranks top N candidate chunks down to top K (e.g., 8-12) using Cross-Encoder or RRF fallback."""
        if not candidate_chunks:
            return []

        reranker = self._get_reranker()

        if reranker:
            try:
                documents = [
                    f"{c.get('act', '')} | {c.get('section_number', '')}: {c.get('title', '')}\n"
                    f"{c.get('content', '')}"
                    for c in candidate_chunks
                ]
                scores = list(reranker.rerank(query, documents))
                scored_candidates = list(zip(scores, candidate_chunks))
                scored_candidates.sort(key=lambda x: x[0], reverse=True)

                reranked_results = []
                for score, doc in scored_candidates[:top_k]:
                    doc_copy = dict(doc)
                    doc_copy["rerank_score"] = float(score)
                    # Cross-encoder scores are unbounded logits; tag the scale so
                    # downstream consumers normalize them correctly.
                    doc_copy["rerank_mode"] = "cross_encoder"
                    reranked_results.append(doc_copy)

                pipeline_logger.log_step(
                    "LEGAL RERANKER",
                    f"Cross-Encoder Reranked {len(candidate_chunks)} candidates -> Selected Top {len(reranked_results)} provisions",
                    status="SUCCESS",
                )
                return reranked_results
            except Exception as e:
                pipeline_logger.log_step(
                    "LEGAL RERANKER",
                    f"Cross-encoder execution error ({e}) -> RRF score ranking fallback",
                    status="WARNING",
                )

        # Fallback RRF selection. Rank position tells us ordering, not relevance
        # quality, so derive a rank-normalized score in [0, 1] rather than the
        # previous constant 1.0 -- which made every chunk look perfectly relevant.
        top_results = [dict(d) for d in candidate_chunks[:top_k]]
        span = max(len(top_results), 1)
        for position, d in enumerate(top_results):
            rank = d.get("rrf_rank")
            rank = position if rank is None else int(rank)
            d["rerank_score"] = max(0.0, 1.0 - (rank / span))
            d["rerank_mode"] = "rrf_fallback"

        pipeline_logger.log_step(
            "LEGAL RERANKER",
            f"RRF Fallback Selection: Selected top {len(top_results)} candidate provisions from RRF scores.",
            status="SUCCESS",
        )
        return top_results


reranker = LegalCrossEncoderReranker()
