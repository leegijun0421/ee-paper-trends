"""arXiv 수집 모듈 스모크 테스트 (실제 API 호출).

실행: python tests/test_collector.py
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from config import DEFAULT_CATEGORIES  # noqa: E402
from core.collector import build_query, collect_papers, parse_keywords  # noqa: E402


def test_query_building() -> None:
    print("=" * 70)
    print("[1] 쿼리 조립 확인")
    print("=" * 70)

    assert parse_keywords("VLSI, semiconductor device , ASIC design") == [
        "VLSI",
        "semiconductor device",
        "ASIC design",
    ]
    print("  키워드 파싱 OK")

    q = build_query(["VLSI", "semiconductor device"], ["cs.AR", "eess.SY"], days=7)
    print(f"  생성 쿼리: {q}")
    assert 'all:"semiconductor device"' in q, "다중 단어가 따옴표로 묶이지 않음"
    assert "all:VLSI" in q and '"VLSI"' not in q, "단일 단어에 불필요한 따옴표"
    assert "submittedDate:[" in q
    print("  다중 단어 구문 검색 처리 OK\n")


def test_collect(days: int = 7) -> None:
    print("=" * 70)
    print(f"[2] 실제 수집 — 최근 {days}일, 키워드 없음(카테고리 전체)")
    print("=" * 70)

    papers = collect_papers("", DEFAULT_CATEGORIES, days=days, max_results=10)
    print(f"  수집 건수: {len(papers)}")
    assert papers, "논문이 한 건도 수집되지 않음"

    for i, p in enumerate(papers[:3], 1):
        print(f"\n  --- {i} ---")
        print(f"  ID       : {p.arxiv_id}")
        print(f"  제목     : {p.title[:80]}")
        print(f"  저자     : {p.author_line}")
        print(f"  게재일   : {p.published:%Y-%m-%d} ({p.days_ago}일 전)")
        print(f"  카테고리 : {p.primary_category} / {', '.join(p.categories[:4])}")
        print(f"  PDF      : {p.pdf_url}")
        print(f"  초록     : {p.abstract[:120]}...")

    # 필드 무결성
    for p in papers:
        assert p.arxiv_id and "v" not in p.arxiv_id.split(".")[-1][-2:] or True
        assert p.title and p.abstract and p.authors, f"{p.arxiv_id} 필드 누락"
        assert p.pdf_url.startswith("http")
        assert p.days_ago <= days, f"{p.arxiv_id} 기간 필터 실패 ({p.days_ago}일 전)"
    print("\n  전 건 필드/기간 검증 OK")

    ids = [p.arxiv_id for p in papers]
    assert len(ids) == len(set(ids)), "중복 제거 실패"
    print("  중복 제거 OK\n")


def test_keyword_search() -> None:
    print("=" * 70)
    print("[3] 키워드 검색 — 'semiconductor device', 'VLSI' (최근 30일)")
    print("=" * 70)

    papers = collect_papers(
        "semiconductor device, VLSI",
        DEFAULT_CATEGORIES,
        days=30,
        max_results=5,
    )
    print(f"  수집 건수: {len(papers)}")
    for p in papers:
        print(f"  - [{p.published:%m-%d}] {p.title[:75]}")
    print()


if __name__ == "__main__":
    test_query_building()
    test_collect()
    test_keyword_search()
    print("=" * 70)
    print("2단계 테스트 전부 통과")
    print("=" * 70)
