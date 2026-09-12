"""트렌드 추출 테스트.

API 키가 없으면 TF-IDF 폴백 경로만, 있으면 LLM 정규화까지 확인한다.
실행: python tests/test_trends.py
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from config import DEFAULT_CATEGORIES  # noqa: E402
from core.collector import collect_papers  # noqa: E402
from core.llm import api_key_available  # noqa: E402
from core.trends import compute_trends, extract_candidates  # noqa: E402


def main(days: int = 14, count: int = 60) -> None:
    print("=" * 78)
    print(f"최근 {days}일 논문 {count}건으로 트렌드를 계산합니다")
    print("=" * 78)

    papers = collect_papers("", DEFAULT_CATEGORIES, days=days, max_results=count)
    print(f"수집: {len(papers)}건\n")
    assert len(papers) >= 10, "트렌드 계산에 필요한 최소 논문 수를 못 채웠습니다"

    print("[1] TF-IDF 후보 (상위 20)")
    print("-" * 78)
    candidates = extract_candidates(papers)
    assert candidates, "후보가 비었습니다"
    for term, score, cnt in candidates[:20]:
        print(f"  {score:7.3f}  {cnt:3d}편  {term}")

    # 학술 상투어가 상위에 남아 있으면 불용어 처리가 실패한 것
    top_terms = {t for t, _, _ in candidates[:20]}
    leaked = top_terms & {"proposed method", "results show", "this paper", "we propose"}
    assert not leaked, f"불용어가 상위에 남았습니다: {leaked}"
    print("\n  학술 상투어 필터 OK")

    print("\n[2] 최종 트렌드 TOP 10")
    print("-" * 78)
    use_llm = api_key_available()
    print(f"  LLM 정규화: {'사용' if use_llm else '건너뜀 (API 키 없음)'}\n")

    trends, warnings = compute_trends(papers, use_llm=use_llm)
    assert trends, "트렌드가 비었습니다"

    for i, k in enumerate(trends, 1):
        line = f"  {i:2d}. {k.korean}"
        if k.korean != k.keyword:
            line += f"  [{k.keyword}]"
        print(f"{line}  — 점수 {k.score:.2f}, {k.paper_count}편")
        if k.note:
            print(f"      {k.note}")

    for w in warnings:
        print(f"\n  ! {w}")

    assert len(trends) <= 10
    assert all(k.paper_count >= 1 for k in trends), "등장 논문 수가 0인 항목이 있습니다"
    assert all(k.score > 0 for k in trends)

    print("\n" + "=" * 78)
    print("트렌드 테스트 통과")
    print("=" * 78)


if __name__ == "__main__":
    main()
