from __future__ import annotations

import hashlib
import math
import re
import unicodedata
from collections import Counter


_TOKEN_RE = re.compile(r"[\u3400-\u9fff]+|[A-Za-z][A-Za-z0-9_+-]*|\d+(?:\.\d+)?")
_STOPWORDS = {
    "的",
    "了",
    "和",
    "是",
    "在",
    "与",
    "及",
    "或",
    "对",
    "从",
    "为",
    "中",
    "上",
    "下",
    "一个",
    "可以",
    "进行",
    "以及",
    "the",
    "and",
    "for",
    "with",
    "that",
    "this",
}


class HashEmbedding:
    """Deterministic local embedding with no model download requirement.

    It combines Chinese character n-grams and Latin word hashes into a fixed
    sparse-like dense vector. This keeps the demo runnable offline while the
    vector store remains Chroma-compatible.
    """

    def __init__(self, dimensions: int = 768) -> None:
        self.dimensions = dimensions

    def embed(self, texts: list[str]) -> list[list[float]]:
        return [self._embed_one(text) for text in texts]

    def _embed_one(self, text: str) -> list[float]:
        normalized = unicodedata.normalize("NFKC", text or "").lower()
        features: list[str] = []
        for match in _TOKEN_RE.findall(normalized):
            if not match or match in _STOPWORDS:
                continue
            if re.fullmatch(r"[\u3400-\u9fff]+", match):
                chars = list(match)
                features.extend(chars)
                features.extend(
                    "".join(chars[i : i + 2])
                    for i in range(max(0, len(chars) - 1))
                )
                if len(chars) >= 3:
                    features.extend(
                        "".join(chars[i : i + 3])
                        for i in range(len(chars) - 2)
                    )
            else:
                features.append(match)
                if len(match) > 4:
                    features.extend(
                        match[i : i + 3] for i in range(len(match) - 2)
                    )

        vector = [0.0] * self.dimensions
        counts = Counter(features)
        for token, count in counts.items():
            digest = hashlib.blake2b(
                token.encode("utf-8"), digest_size=8
            ).digest()
            raw = int.from_bytes(digest, "big")
            index = raw % self.dimensions
            sign = 1.0 if (raw >> 63) & 1 else -1.0
            weight = 1.0 + math.log(count)
            vector[index] += sign * weight

        norm = math.sqrt(sum(value * value for value in vector))
        if norm == 0:
            return vector
        return [value / norm for value in vector]
