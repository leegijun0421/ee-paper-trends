"""초록에서 최근 자주 등장하는 주제를 뽑는다.

TF-IDF로 후보를 넉넉히 뽑고(무료·즉시), Claude가 그 후보를 연구 주제 단위로
합쳐 준다(호출 1회). TF-IDF만 쓰면 'finfet'과 'fin fet'이 따로 세어지고
'proposed method' 같은 잡음이 상위에 올라오는데, 그 마무리만 LLM에 맡기는
구조다. LLM 호출이 실패하면 TF-IDF 결과를 그대로 쓴다.
"""
from __future__ import annotations

import logging
import re

from sklearn.feature_extraction.text import TfidfVectorizer

from config import TFIDF_CANDIDATE_K, TOP_K_KEYWORDS
from core.models import Paper, TrendKeyword

log = logging.getLogger(__name__)

# 논문이라면 어디에나 나오는 단어들. 이걸 빼지 않으면 상위 10개가 전부 이런 말로 찬다.
ACADEMIC_STOPWORDS = {
    "paper", "papers", "study", "studies", "work", "works", "approach", "approaches",
    "method", "methods", "result", "results", "show", "shows", "shown", "propose",
    "proposed", "proposes", "present", "presents", "presented", "using", "used", "use",
    "based", "novel", "new", "recent", "recently", "demonstrate", "demonstrates",
    "demonstrated", "provide", "provides", "obtain", "obtained", "consider",
    "considered", "investigate", "investigated", "analysis", "analyze", "analyzed",
    "case", "cases", "also", "however", "thus", "therefore", "moreover", "furthermore",
    "respectively", "et", "al", "e.g", "i.e", "via", "within", "large", "small",
    "high", "low", "good", "better", "best", "significant", "significantly",
    "important", "well", "first", "second", "given", "different", "various",
    "several", "many", "much", "one", "two", "three", "number", "numbers",
    "value", "values", "effect", "effects", "furthermore", "additionally",
    "framework", "problem", "problems", "model", "models", "data", "set", "sets",
}


def _corpus(papers: list[Paper]) -> list[str]:
    """제목은 주제를 더 잘 드러내므로 두 번 넣어 가중치를 준다."""
    docs = []
    for p in papers:
        text = f"{p.title}. {p.title}. {p.abstract}"
        # LaTeX 잔재와 숫자 토큰 제거
        text = re.sub(r"\$[^$]*\$", " ", text)
        text = re.sub(r"\\[a-zA-Z]+", " ", text)
        docs.append(text.lower())
    return docs


def extract_candidates(
    papers: list[Paper], top_k: int = TFIDF_CANDIDATE_K
) -> list[tuple[str, float, int]]:
    """(키워드, TF-IDF 합산 점수, 등장 논문 수) 목록을 점수 내림차순으로."""
    if len(papers) < 2:
        return []       # 문서가 하나면 IDF가 의미를 잃는다

    docs = _corpus(papers)
    stop_words = list(ACADEMIC_STOPWORDS)

    vectorizer = TfidfVectorizer(
        ngram_range=(1, 3),
        stop_words="english",
        # 3분의 1이 넘는 논문에 나오는 말은 '트렌드'가 아니라 분야 그 자체다
        # ('systems', 'design' 같은 단어가 상위를 독차지하는 것을 막는다)
        max_df=0.35,
        min_df=max(2, len(papers) // 25),
        sublinear_tf=True,
        token_pattern=r"(?u)\b[a-z][a-z\-]{2,}\b",   # 순수 숫자 토큰 배제
    )
    try:
        matrix = vectorizer.fit_transform(docs)
    except ValueError:       # 문서가 너무 적거나 전부 불용어인 경우
        log.warning("TF-IDF 후보를 추출하지 못했습니다.")
        return []

    terms = vectorizer.get_feature_names_out()
    scores = matrix.sum(axis=0).A1
    doc_counts = (matrix > 0).sum(axis=0).A1

    rows = []
    for term, score, count in zip(terms, scores, doc_counts):
        words = term.split()
        # n-gram 안에 학술 상투어가 섞이면 통째로 버린다
        if any(w in ACADEMIC_STOPWORDS for w in words):
            continue
        # 'quantum hall effect'가 'hall'보다 주제를 잘 나타내는데, 짧은 단어일수록
        # 자주 나와 TF-IDF 점수가 높다. 길이에 비례한 가중치로 이를 상쇄한다.
        weighted = float(score) * (1.0 + 0.6 * (len(words) - 1))
        rows.append((term, weighted, int(count)))

    rows.sort(key=lambda r: r[1], reverse=True)
    return rows[:top_k]


def _fallback(candidates: list[tuple[str, float, int]]) -> list[TrendKeyword]:
    return [
        TrendKeyword(keyword=t, korean=t, score=s, paper_count=c)
        for t, s, c in candidates[:TOP_K_KEYWORDS]
    ]


def compute_trends(
    papers: list[Paper], *, use_llm: bool = True
) -> tuple[list[TrendKeyword], list[str]]:
    """상위 주제 목록과 경고 메시지를 함께 돌려준다."""
    warnings: list[str] = []
    candidates = extract_candidates(papers)

    if not candidates:
        return [], ["키워드를 뽑기에 논문 수가 너무 적습니다. 기간이나 카테고리를 넓혀보세요."]

    if not use_llm:
        return _fallback(candidates), warnings

    # LLM 실패는 치명적이지 않다 — TF-IDF 결과로 화면을 채우고 사유만 알린다
    try:
        from core.llm import LLMError, normalize_keywords

        merged = normalize_keywords(
            [(t, s) for t, s, _ in candidates],
            [p.title for p in papers],
        )
    except LLMError as e:
        warnings.append(f"LLM 정규화를 건너뛰고 TF-IDF 원본을 보여줍니다 — {e}")
        return _fallback(candidates), warnings
    except Exception as e:  # 예상 못 한 오류로 화면 전체가 죽지 않도록
        log.exception("트렌드 정규화 실패")
        warnings.append(f"LLM 정규화 중 오류가 발생해 TF-IDF 원본을 보여줍니다 — {e}")
        return _fallback(candidates), warnings

    if not merged:
        return _fallback(candidates), warnings

    by_term = {t: (s, c) for t, s, c in candidates}
    docs = _corpus(papers)

    results: list[TrendKeyword] = []
    for item in merged:
        sources = item.get("merged_from") or [item.get("keyword", "")]
        known = [s.lower() for s in sources if s.lower() in by_term]
        if not known:
            continue
        score = sum(by_term[s][0] for s in known)
        # 합쳐진 표기 중 하나라도 들어 있으면 그 논문 1편으로 센다.
        # 단어 경계를 걸지 않으면 'network'가 'networks'·'networking'까지 잡아
        # 등장 편수가 크게 부풀려진다.
        patterns = [re.compile(rf"\b{re.escape(s)}\b") for s in known]
        paper_count = sum(1 for d in docs if any(p.search(d) for p in patterns))
        results.append(
            TrendKeyword(
                keyword=item.get("keyword", known[0]),
                korean=item.get("korean") or item.get("keyword", known[0]),
                score=score,
                paper_count=paper_count,
                note=item.get("note", ""),
            )
        )

    if not results:
        return _fallback(candidates), warnings

    results.sort(key=lambda k: k.score, reverse=True)
    return results[:TOP_K_KEYWORDS], warnings
