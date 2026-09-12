"""Lexical search over the clauses of one contract.

Contract Q&A retrieves from the uploaded document, not from the statutory
corpus, and a contract is 10-120 clauses rather than 2,336 sections. At that
size BM25 in process beats a vector store on every axis that matters here: no
per-contract collection to create and tear down, no embedding cost per question,
no model to be unavailable, and a result that is identical every time the same
question is asked.

It is also the honest tool for the job. Most questions people ask of their own
contract name the thing they are asking about -- "what is my notice period",
"how much is the deposit", "can they fire me without reason" -- and that is
exactly the case lexical matching handles well.
"""

import math
import re
from dataclasses import dataclass
from typing import Any, Dict, List, Sequence

# Words that carry no discriminating signal in a contract, where "agreement",
# "party" and "shall" appear in nearly every clause.
_STOPWORDS = frozenset("""
a an the this that these those and or but if then than of in on at to for with
by from as is are was were be been being shall will may must can could would
should do does did not no nor so such other any all each every both either
neither i you he she it we they me him her us them my your his its our their
what which who whom whose when where why how there here
agreement party parties clause section hereby herein hereof hereto hereunder
said aforesaid whatsoever thereof therein
under upon within without between during after before against into over per
""".split())

_TOKEN = re.compile(r"[a-z0-9]+")

# Standard BM25 parameters. k1 controls term-frequency saturation, b how much
# clause length is normalized away.
_K1 = 1.5
_B = 0.75


# Suffixes stripped so that a question and a clause meet on the stem: the
# evaluation set showed "can I join a competitor" failing to reach a clause that
# says "competing business", and "leaving" failing to reach "leave". Order
# matters -- longer suffixes first -- and a stem is never cut below 3 letters.
_SUFFIXES = ("ations", "ation", "ments", "ment", "ities", "ity", "ness", "ing",
             "ers", "ors", "ies", "ed", "es", "er", "or", "ly", "s")


# After suffix stripping, longer stems are truncated so that word families meet:
# "competitor" -> "competit" and "competing" -> "compet" only agree at six
# letters. Within a single contract the vocabulary is small enough that the false
# merges this causes ("employ" for employee/employer/employment) help recall
# more than they hurt it.
_STEM_LENGTH = 6


def stem(token: str) -> str:
    """A light Porter-style stem, tuned on what people ask of contracts.

    The audit showed a base form and its inflections meeting nowhere: "notice"
    stayed "notice" while "notices" became "notic"; "leave" stayed while
    "leaves" and "leaving" became "leav"; "bonus" lost its s. Each pair now
    lands on one stem, so a question about notices reaches the notice clause.
    """
    if len(token) <= 3:
        return token
    for suffix in _SUFFIXES:
        if token.endswith(suffix) and len(token) - len(suffix) >= 3:
            if suffix == "s" and token[-2] in "us":
                break  # bonus, status, address: the s is part of the word
            if suffix == "ies":
                token = token[:-3] + "i"  # salaries -> salari, to meet salary
            else:
                token = token[: -len(suffix)]
            break
    if len(token) >= 4:
        if token.endswith("y") and token[-2] not in "aeiou":
            # salary -> salari (meets salaries); but employ, pay, day keep their y,
            # or "employer" and "employee" would stem apart.
            token = token[:-1] + "i"
        elif token.endswith("e"):
            token = token[:-1]  # notice -> notic, leave -> leav, fire -> fir
    return token[:_STEM_LENGTH] if len(token) > _STEM_LENGTH else token


def tokenize(text: str) -> List[str]:
    return [
        stem(token)
        for token in _TOKEN.findall((text or "").lower())
        if token not in _STOPWORDS and len(token) > 1
    ]


@dataclass
class ClauseHit:
    clause_index: int
    score: float
    matched_terms: List[str]


class ClauseIndex:
    """A BM25 index over one contract's clauses."""

    def __init__(self, clauses: Sequence[Any]):
        self.clauses = list(clauses)
        self._docs: Dict[int, List[str]] = {}
        self._freqs: Dict[int, Dict[str, int]] = {}
        self._doc_freq: Dict[str, int] = {}

        for clause in self.clauses:
            index = getattr(clause, "index", None)
            if index is None:
                continue
            heading = getattr(clause, "heading", "") or ""
            category = str(getattr(clause, "category", "")).replace("_", " ")
            # The heading and category name the clause's subject, and a question
            # usually names that subject rather than quoting the body, so they
            # are weighted by repetition rather than by a separate field score.
            tokens = (
                tokenize(getattr(clause, "text", ""))
                + tokenize(heading) * 3
                + tokenize(category) * 2
            )
            self._docs[index] = tokens
            counts: Dict[str, int] = {}
            for token in tokens:
                counts[token] = counts.get(token, 0) + 1
            self._freqs[index] = counts
            for token in counts:
                self._doc_freq[token] = self._doc_freq.get(token, 0) + 1

        lengths = [len(tokens) for tokens in self._docs.values()]
        self._avg_len = (sum(lengths) / len(lengths)) if lengths else 1.0
        self._count = max(len(self._docs), 1)

    def _idf(self, term: str) -> float:
        freq = self._doc_freq.get(term, 0)
        if freq == 0:
            return 0.0
        return math.log(1 + (self._count - freq + 0.5) / (freq + 0.5))

    def search(self, query: str, limit: int = 5, min_score: float = 0.1) -> List[ClauseHit]:
        terms = tokenize(query)
        if not terms:
            return []

        hits: List[ClauseHit] = []
        for index, tokens in self._docs.items():
            counts = self._freqs[index]
            length = len(tokens) or 1
            score = 0.0
            matched = []
            for term in set(terms):
                frequency = counts.get(term, 0)
                if not frequency:
                    continue
                matched.append(term)
                idf = self._idf(term)
                numerator = frequency * (_K1 + 1)
                denominator = frequency + _K1 * (1 - _B + _B * length / self._avg_len)
                score += idf * numerator / denominator
            if score > min_score:
                hits.append(ClauseHit(index, score, sorted(matched)))

        hits.sort(key=lambda h: (-h.score, h.clause_index))
        return hits[:limit]


def search_clauses(clauses: Sequence[Any], query: str, limit: int = 5) -> List[ClauseHit]:
    return ClauseIndex(clauses).search(query, limit=limit)
