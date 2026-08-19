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
                from fastembed.rerank.cross_encoder import TextReRanker

                self._reranker = TextReRanker(model_name=self.model_name)
            except Exception as e:
                pipeline_logger.log_step(
                    "LEGAL RERANKER",
                    f"Cross-encoder unavailable ({type(e).__name__}) -> RRF score ranking fallback",
                    status="WARNING",
                )
                self._reranker = False
        return self._reranker if self._reranker is not False else None

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

        # Fallback RRF selection
        top_results = candidate_chunks[:top_k]
        for d in top_results:
            d["rerank_score"] = d.get("score", 1.0)

        pipeline_logger.log_step(
            "LEGAL RERANKER",
            f"RRF Fallback Selection: Selected top {len(top_results)} candidate provisions from RRF scores.",
            status="SUCCESS",
        )
        return top_results


reranker = LegalCrossEncoderReranker()
