"""
ContextGC: archive of retired turns, with lexical recall.

When the compiler retires a turn it is not discarded -- it is moved here so a
later question can bring it back. Retrieval is **lexical** (token overlap,
subword matching, phrase bonus), not semantic.

This module previously advertised "768-dim embeddings" and a ClickHouse
``ivfflat`` index. Both were untrue: the vectors were SHA-256 hashes of words,
the DDL constant was referenced nowhere in the codebase, and the search was
~80% lexical with the fake cosine contributing 40% of the weight. Rather than
keep a decorative vector attached to a string-matching search, this is now
named and documented for what it is. If you want true semantic recall, plug a
real embedder in behind :meth:`RetiredTurnArchive.search` -- the interface is
one method.
"""

import re
from typing import Any, Dict, List

#: Words too common to carry retrieval signal.
_STOPWORDS = frozenset({
    "the", "a", "an", "is", "in", "to", "for", "of", "and", "or", "it", "at",
    "what", "was", "were", "are", "be", "been", "this", "that", "there", "here",
})

_TOKEN_RE = re.compile(r"[a-z0-9]+")


class RetiredTurnArchive:
    """
    Append-only store of retired turns plus a lexical recall function.

    Deliberately simple and inspectable: every stored row is the original text
    plus the reason it was retired, so a recall result can always be traced back
    to the exact turn it came from.
    """

    def __init__(self, session_id: str = "contextgc"):
        self.session_id = session_id
        self.rows: List[Dict[str, Any]] = []
        self.retire_log: List[str] = []

    # -- writing ------------------------------------------------------------

    def archive_turn(self, turn_index: int, role: str, content: str, reason: str) -> Dict[str, Any]:
        """Move a retired turn into the archive and return the stored record."""
        record = {
            "session_id": self.session_id,
            "turn_index": turn_index,
            "role": role,
            "raw_content": content,
            "compact_summary": content[:160] + "..." if len(content) > 160 else content,
            "retired_reason": reason,
        }
        self.rows.append(record)
        self.retire_log.append(f"turn {turn_index} ({role}) retired: {reason}")
        return record

    # -- reading ------------------------------------------------------------

    def search(self, query: str, top_k: int = 2, min_score: float = 0.2) -> List[Dict[str, Any]]:
        """
        Rank archived turns against ``query`` by lexical overlap.

        Scoring, in descending weight:
          * phrase containment of the whole query      (0.50)
          * exact token overlap on non-stopword terms (0.35 each)
          * subword containment, e.g. "rain" in "rainfall" (0.20 each)

        Returns at most ``top_k`` hits with score >= ``min_score``. A query with
        no lexical relationship to a row scores 0 and is never returned, so a
        nonsense query returns nothing rather than an arbitrary row.
        """
        if not self.rows or not query.strip():
            return []

        q_text = query.lower().strip()
        q_all = set(_TOKEN_RE.findall(q_text))
        q_terms = q_all - _STOPWORDS or q_all

        scored: List[Dict[str, Any]] = []
        for row in self.rows:
            r_text = row["raw_content"].lower()
            r_terms = set(_TOKEN_RE.findall(r_text))

            phrase = 0.5 if q_text and q_text in r_text else 0.0
            exact = 0.35 * len(q_terms & r_terms)

            subword = 0.0
            for term in q_terms:
                if len(term) >= 4 and any(term != other and term in other for other in r_terms):
                    subword += 0.20

            score = phrase + exact + subword
            if score >= min_score:
                hit = dict(row)
                hit["score"] = round(score, 4)
                hit["matched_terms"] = sorted(q_terms & r_terms)
                scored.append(hit)

        scored.sort(key=lambda r: (-r["score"], r["turn_index"]))
        return scored[:top_k]

    def __len__(self) -> int:
        return len(self.rows)


#: Backwards-compatible alias. The old name promised a vector store.
VectorMemoryTier = RetiredTurnArchive
