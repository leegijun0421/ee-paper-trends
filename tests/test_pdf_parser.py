"""PDF 다운로드 + 섹션 분할 테스트 (실제 arXiv PDF 사용).

실행: python tests/test_pdf_parser.py [건수]
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from config import DEFAULT_CATEGORIES  # noqa: E402
from core.collector import collect_papers  # noqa: E402
from core.pdf_parser import download_pdf, extract_text, parse_sections  # noqa: E402


def preview(label: str, text: str, n: int = 160) -> None:
    body = " ".join(text.split())
    mark = "OK " if body else "-- "
    print(f"    {mark}{label:<14} {len(text):>7,}자  {body[:n]}{'...' if len(body) > n else ''}")


def main(count: int = 3) -> None:
    print("=" * 78)
    print(f"최근 논문 {count}건을 받아 섹션 분할을 검증합니다")
    print("=" * 78)

    papers = collect_papers("", DEFAULT_CATEGORIES, days=7, max_results=count)
    assert papers, "테스트할 논문이 없습니다"

    stats = {"regex": 0, "heuristic": 0, "abstract-only": 0}

    for i, p in enumerate(papers, 1):
        print(f"\n[{i}/{len(papers)}] {p.arxiv_id} — {p.title[:64]}")
        print(f"  카테고리: {p.primary_category}")

        path = download_pdf(p)
        size_kb = path.stat().st_size / 1024
        print(f"  PDF: {path.name} ({size_kb:,.0f} KB)")
        assert path.exists() and size_kb > 10, "PDF 다운로드 실패"

        raw, warns = extract_text(path)
        print(f"  본문 추출: {len(raw):,}자")
        assert len(raw) > 1000, "본문이 너무 짧음"

        sec = parse_sections(p, path)
        stats[sec.parse_method] = stats.get(sec.parse_method, 0) + 1
        print(f"  분할 방식: {sec.parse_method}  /  채워진 섹션: {sec.found_sections}")
        for label, key in [
            ("Introduction", sec.introduction),
            ("Methods", sec.methods),
            ("Results", sec.results),
            ("Conclusion", sec.conclusion),
        ]:
            preview(label, key)
        for w in sec.warnings:
            print(f"    ! {w[:150]}")

        assert sec.found_sections, "섹션이 하나도 채워지지 않음"

    # 캐시 동작 확인
    print("\n" + "-" * 78)
    p = papers[0]
    before = download_pdf(p)
    after = download_pdf(p)
    assert before == after and after.exists()
    print(f"PDF 캐시 재사용 OK ({after.name})")

    print("-" * 78)
    print(f"분할 방식 분포: {stats}")
    print("=" * 78)
    print("3단계 테스트 통과")
    print("=" * 78)


if __name__ == "__main__":
    main(int(sys.argv[1]) if len(sys.argv) > 1 else 3)
