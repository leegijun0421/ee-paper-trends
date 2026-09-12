"""arXiv API로 최근 논문을 수집한다."""
from __future__ import annotations

import hashlib
import json
import logging
import re
import time
from datetime import datetime, timedelta, timezone

import arxiv

from config import (
    ARXIV_DELAY_SECONDS,
    ARXIV_PAGE_SIZE,
    DEFAULT_MAX_RESULTS,
    SEARCH_CACHE_DIR,
    SEARCH_CACHE_TTL,
)
from core.models import Paper

log = logging.getLogger(__name__)


class CollectorError(RuntimeError):
    """UI에 그대로 보여줄 수 있는 수집 실패 사유."""


_client = arxiv.Client(
    page_size=ARXIV_PAGE_SIZE,
    delay_seconds=ARXIV_DELAY_SECONDS,
    num_retries=3,
)


def parse_keywords(raw: str) -> list[str]:
    """사용자 입력을 키워드 리스트로. 콤마 구분, 빈 항목 제거."""
    if not raw:
        return []
    return [k.strip() for k in re.split(r"[,\n]", raw) if k.strip()]


def _quote(keyword: str) -> str:
    """arXiv 검색은 여러 단어를 따옴표로 묶지 않으면 OR 로 흩어진다.

    'semiconductor device' → '"semiconductor device"' (구문 검색)
    이미 따옴표가 있으면 그대로 둔다.
    """
    kw = keyword.strip()
    if kw.startswith('"') and kw.endswith('"'):
        return kw
    if " " in kw:
        return f'"{kw}"'
    return kw


def build_query(
    keywords: list[str],
    categories: list[str],
    days: int | None = None,
    *,
    use_date_filter: bool = True,
) -> str:
    """arXiv search_query 문자열을 조립한다."""
    parts: list[str] = []

    if categories:
        cat_clause = " OR ".join(f"cat:{c}" for c in categories)
        parts.append(f"({cat_clause})")

    if keywords:
        kw_clause = " OR ".join(f"all:{_quote(k)}" for k in keywords)
        parts.append(f"({kw_clause})")

    if use_date_filter and days:
        end = datetime.now(timezone.utc)
        start = end - timedelta(days=days)
        # arXiv 날짜 범위 문법: submittedDate:[YYYYMMDDHHMM TO YYYYMMDDHHMM]
        parts.append(
            f"submittedDate:[{start.strftime('%Y%m%d%H%M')} "
            f"TO {end.strftime('%Y%m%d%H%M')}]"
        )

    if not parts:
        raise ValueError("카테고리와 키워드 중 최소 하나는 지정해야 합니다.")

    return " AND ".join(parts)


def _fetch(query: str, max_results: int) -> list[Paper]:
    search = arxiv.Search(
        query=query,
        max_results=max_results,
        sort_by=arxiv.SortCriterion.SubmittedDate,
        sort_order=arxiv.SortOrder.Descending,
    )
    try:
        return [Paper.from_arxiv_result(r) for r in _client.results(search)]
    except arxiv.HTTPError as e:
        if e.status == 429:
            raise CollectorError(
                "arXiv가 요청 제한(429)을 걸었습니다. 잠시(수 분) 후 다시 시도해주세요. "
                "같은 조건이라면 캐시된 결과가 재사용됩니다."
            ) from e
        raise CollectorError(f"arXiv 요청 실패 (HTTP {e.status}). 잠시 후 다시 시도해주세요.") from e
    except arxiv.UnexpectedEmptyPageError as e:
        raise CollectorError("arXiv가 빈 응답을 돌려주었습니다. 잠시 후 다시 시도해주세요.") from e


# ---------------------------------------------------------------- 캐시
def _cache_path(query: str, max_results: int):
    digest = hashlib.sha256(f"{query}|{max_results}".encode("utf-8")).hexdigest()[:16]
    return SEARCH_CACHE_DIR / f"search_{digest}.json"


def _cache_load(query: str, max_results: int) -> list[Paper] | None:
    path = _cache_path(query, max_results)
    if not path.exists():
        return None
    if time.time() - path.stat().st_mtime > SEARCH_CACHE_TTL:
        return None
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
        return [Paper.from_dict(d) for d in raw]
    except (json.JSONDecodeError, OSError, KeyError, TypeError):
        return None


def _cache_save(query: str, max_results: int, papers: list[Paper]) -> None:
    try:
        _cache_path(query, max_results).write_text(
            json.dumps([p.to_dict() for p in papers], ensure_ascii=False),
            encoding="utf-8",
        )
    except OSError as e:
        log.warning("검색 캐시 저장 실패: %s", e)


def _fetch_cached(query: str, max_results: int) -> list[Paper]:
    """같은 쿼리를 짧은 시간 안에 반복 호출하지 않도록 디스크 캐시를 거친다."""
    cached = _cache_load(query, max_results)
    if cached is not None:
        log.info("검색 캐시 적중 (%d건)", len(cached))
        return cached
    papers = _fetch(query, max_results)
    _cache_save(query, max_results, papers)
    return papers


def collect_papers(
    keywords: str | list[str],
    categories: list[str],
    days: int = 7,
    max_results: int = DEFAULT_MAX_RESULTS,
) -> list[Paper]:
    """최근 `days`일 내 제출된 논문을 수집한다.

    1차로 arXiv 서버측 날짜 필터를 쓰고, 결과가 비면 날짜 절 없이 다시 조회한
    뒤 클라이언트에서 걸러낸다. (날짜 범위 문법은 arXiv 쪽 사정으로 간헐적으로
    빈 결과를 돌려주는 사례가 보고돼 있어 폴백을 둔다.)
    """
    kws = parse_keywords(keywords) if isinstance(keywords, str) else list(keywords)

    query = build_query(kws, categories, days, use_date_filter=True)
    log.info("arXiv query: %s", query)
    papers = _fetch_cached(query, max_results)

    if not papers:
        fallback = build_query(kws, categories, days, use_date_filter=False)
        log.warning("날짜 필터 결과 0건 → 폴백 조회: %s", fallback)
        # 최신순 정렬이므로 넉넉히 받아 클라이언트에서 자른다
        papers = _fetch_cached(fallback, max(max_results * 4, 200))

    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    papers = [p for p in papers if p.published >= cutoff]

    # 카테고리 OR 조건상 같은 논문이 중복될 수 있다
    seen: set[str] = set()
    unique: list[Paper] = []
    for p in papers:
        if p.arxiv_id in seen:
            continue
        seen.add(p.arxiv_id)
        unique.append(p)

    unique.sort(key=lambda p: p.published, reverse=True)
    return unique[:max_results]
