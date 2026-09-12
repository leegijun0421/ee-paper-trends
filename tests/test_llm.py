"""Claude 연동 테스트.

API 키가 없어도 프롬프트 조립 · JSON 스키마 · 캐시 왕복까지는 검증한다.
키가 있으면 실제 호출까지 이어서 확인한다.

실행: python tests/test_llm.py
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from config import CLAUDE_MODEL, MAX_SECTION_CHARS  # noqa: E402
from core import llm  # noqa: E402
from core.collector import collect_papers  # noqa: E402
from core.models import PaperAnalysis, PaperSections, TermExplanation  # noqa: E402
from core.pdf_parser import parse_sections  # noqa: E402
from config import DEFAULT_CATEGORIES  # noqa: E402


def check_schema(name: str, schema: dict) -> None:
    """structured outputs가 요구하는 형태인지 재귀적으로 확인한다."""
    if schema.get("type") == "object":
        assert schema.get("additionalProperties") is False, f"{name}: additionalProperties 누락"
        props = schema.get("properties", {})
        required = set(schema.get("required", []))
        assert required == set(props), f"{name}: required가 properties와 불일치 ({required} vs {set(props)})"
        for key, sub in props.items():
            check_schema(f"{name}.{key}", sub)
    elif schema.get("type") == "array":
        check_schema(f"{name}[]", schema["items"])


def test_schemas() -> None:
    print("=" * 78)
    print("[1] JSON 스키마 검증")
    print("=" * 78)
    check_schema("analysis", llm._ANALYSIS_SCHEMA)
    check_schema("trends", llm._TRENDS_SCHEMA)
    print("  두 스키마 모두 structured outputs 요구사항 충족 (재귀 검사)\n")


def test_prompt(paper, sections) -> None:
    print("=" * 78)
    print("[2] 프롬프트 조립")
    print("=" * 78)
    prompt = llm._build_analysis_prompt(paper, sections)

    for marker in ["# 제목", "# 초록", "# Introduction 원문", "# Conclusion 원문"]:
        assert marker in prompt, f"프롬프트에 {marker}가 없습니다"
    print(f"  프롬프트 길이: {len(prompt):,}자")
    print(f"  섹션당 상한 {MAX_SECTION_CHARS:,}자 → 전체 상한 약 {MAX_SECTION_CHARS * 4 + 4000:,}자")
    assert len(prompt) < MAX_SECTION_CHARS * 4 + 8000, "길이 제한이 걸리지 않았습니다"

    empty = PaperSections(arxiv_id="x", parse_method="abstract-only")
    fallback_prompt = llm._build_analysis_prompt(paper, empty)
    assert "(원문에서 찾지 못함)" in fallback_prompt
    assert "초록만 제공됩니다" in fallback_prompt
    print("  빈 섹션 → '찾지 못함' 표기 + 초록 전용 안내 OK\n")


def test_cache() -> None:
    print("=" * 78)
    print("[3] 캐시 왕복")
    print("=" * 78)
    original = PaperAnalysis(
        arxiv_id="0000.00000",
        one_liner="테스트 한 줄 요약",
        section_summaries={"introduction": "가", "methods": "나", "results": "다", "conclusion": "라"},
        significance="중요성",
        novelty="차별점",
        terms=[TermExplanation("FinFET", "핀펫", "설명", "비유")],
        parse_method="regex",
    )
    llm._cache_save("test", "roundtrip-key", original.to_dict())
    loaded = PaperAnalysis.from_dict(llm._cache_load("test", "roundtrip-key"))

    assert loaded.one_liner == original.one_liner
    assert loaded.section_summaries == original.section_summaries
    assert loaded.terms[0].korean == "핀펫"
    assert llm._cache_load("test", "없는-키") is None
    print("  저장 → 로드 → 필드 일치 OK (한글 포함)")
    llm._cache_path("test", "roundtrip-key").unlink(missing_ok=True)
    print("  임시 캐시 파일 정리 완료\n")


def test_live_call(paper, sections) -> None:
    print("=" * 78)
    print(f"[4] 실제 호출 ({CLAUDE_MODEL})")
    print("=" * 78)
    if not llm.api_key_available():
        print("  ANTHROPIC_API_KEY가 없어 건너뜁니다.")
        print("  .env에 키를 넣고 다시 실행하면 이 단계까지 검증됩니다.\n")
        return

    analysis = llm.analyze_paper(paper, sections)
    print(f"  한 줄 요약: {analysis.one_liner}\n")
    for label, key in [("Introduction", "introduction"), ("Methods", "methods"),
                       ("Results", "results"), ("Conclusion", "conclusion")]:
        body = analysis.section_summaries.get(key, "")
        print(f"  [{label}] {body[:180]}{'…' if len(body) > 180 else ''}\n")
    print(f"  중요성: {analysis.significance[:200]}…\n")
    print(f"  차별점: {analysis.novelty[:200]}…\n")
    print(f"  용어 {len(analysis.terms)}개:")
    for t in analysis.terms:
        print(f"    - {t.term} ({t.korean}): {t.explanation[:90]}…")
        print(f"      비유: {t.analogy[:90]}")

    assert analysis.one_liner and analysis.significance and analysis.novelty
    assert len(analysis.terms) >= 3, "용어가 너무 적습니다"
    assert sum(1 for v in analysis.section_summaries.values() if v.strip()) >= 3
    print("\n  필드 검증 OK")

    # 두 번째 호출은 캐시에서 나와야 한다
    again = llm.analyze_paper(paper, sections)
    assert again.one_liner == analysis.one_liner
    print("  캐시 재사용 OK\n")


if __name__ == "__main__":
    test_schemas()
    test_cache()

    papers = collect_papers("", DEFAULT_CATEGORIES, days=7, max_results=1)
    assert papers, "테스트할 논문을 가져오지 못했습니다"
    paper = papers[0]
    print(f"대상 논문: {paper.arxiv_id} — {paper.title[:60]}\n")
    sections = parse_sections(paper)

    test_prompt(paper, sections)
    test_live_call(paper, sections)

    print("=" * 78)
    print("4단계 테스트 완료")
    print("=" * 78)
