"""앱 전체에서 주고받는 데이터 구조."""
from __future__ import annotations

import re
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone


def _clean(text: str) -> str:
    """arXiv 초록은 줄바꿈이 원문 그대로 들어있어 그대로 쓰면 읽기 어렵다."""
    return re.sub(r"\s+", " ", (text or "")).strip()


@dataclass
class Paper:
    arxiv_id: str          # 버전 표기를 뗀 순수 ID (예: 2508.01234)
    title: str
    abstract: str
    authors: list[str]
    published: datetime    # 최초 제출일 (UTC)
    updated: datetime      # 최종 수정일 (UTC)
    pdf_url: str
    entry_url: str         # arXiv 초록 페이지
    primary_category: str
    categories: list[str] = field(default_factory=list)
    comment: str = ""

    @classmethod
    def from_arxiv_result(cls, r) -> "Paper":
        # r.entry_id = "http://arxiv.org/abs/2508.01234v2" → "2508.01234"
        raw_id = r.entry_id.rsplit("/", 1)[-1]
        arxiv_id = re.sub(r"v\d+$", "", raw_id)
        return cls(
            arxiv_id=arxiv_id,
            title=_clean(r.title),
            abstract=_clean(r.summary),
            authors=[a.name for a in r.authors],
            published=r.published,
            updated=r.updated,
            pdf_url=r.pdf_url or f"https://arxiv.org/pdf/{arxiv_id}",
            entry_url=r.entry_id,
            primary_category=r.primary_category,
            categories=list(r.categories),
            comment=_clean(r.comment or ""),
        )

    @property
    def author_line(self) -> str:
        """카드에 한 줄로 표시할 저자 문자열."""
        if len(self.authors) <= 3:
            return ", ".join(self.authors)
        return f"{', '.join(self.authors[:3])} 외 {len(self.authors) - 3}명"

    @property
    def days_ago(self) -> int:
        return (datetime.now(timezone.utc) - self.published).days

    def to_dict(self) -> dict:
        d = asdict(self)
        d["published"] = self.published.isoformat()
        d["updated"] = self.updated.isoformat()
        return d

    @classmethod
    def from_dict(cls, d: dict) -> "Paper":
        d = dict(d)
        d["published"] = datetime.fromisoformat(d["published"])
        d["updated"] = datetime.fromisoformat(d["updated"])
        return cls(**d)


@dataclass
class PaperSections:
    """PDF에서 뽑아낸 섹션별 원문."""
    arxiv_id: str
    introduction: str = ""
    methods: str = ""
    results: str = ""
    conclusion: str = ""
    full_text: str = ""
    parse_method: str = ""   # "regex" | "heuristic" | "abstract-only"
    warnings: list[str] = field(default_factory=list)

    def as_mapping(self) -> dict[str, str]:
        return {
            "Introduction": self.introduction,
            "Methods": self.methods,
            "Results": self.results,
            "Conclusion": self.conclusion,
        }

    @property
    def found_sections(self) -> list[str]:
        return [k for k, v in self.as_mapping().items() if v.strip()]


@dataclass
class TermExplanation:
    """학부 1학년 눈높이로 풀어 쓴 전문 용어 한 건."""
    term: str            # 원문 용어 (예: "FinFET")
    korean: str          # 우리말 표기 (예: "핀펫")
    explanation: str     # 2~3문장 설명
    analogy: str         # 일상 비유

    @classmethod
    def from_dict(cls, d: dict) -> "TermExplanation":
        return cls(
            term=d.get("term", ""),
            korean=d.get("korean", ""),
            explanation=d.get("explanation", ""),
            analogy=d.get("analogy", ""),
        )


@dataclass
class PaperAnalysis:
    """Claude가 돌려준 논문 한 편의 분석 결과."""
    arxiv_id: str
    one_liner: str = ""                       # 한 줄 요약
    section_summaries: dict[str, str] = field(default_factory=dict)
    significance: str = ""                    # 왜 중요한가
    novelty: str = ""                         # 기존 연구 대비 무엇이 다른가
    terms: list[TermExplanation] = field(default_factory=list)
    parse_method: str = ""                    # 어떤 경로로 섹션을 나눴는지
    warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "arxiv_id": self.arxiv_id,
            "one_liner": self.one_liner,
            "section_summaries": self.section_summaries,
            "significance": self.significance,
            "novelty": self.novelty,
            "terms": [asdict(t) for t in self.terms],
            "parse_method": self.parse_method,
            "warnings": self.warnings,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "PaperAnalysis":
        return cls(
            arxiv_id=d["arxiv_id"],
            one_liner=d.get("one_liner", ""),
            section_summaries=d.get("section_summaries", {}),
            significance=d.get("significance", ""),
            novelty=d.get("novelty", ""),
            terms=[TermExplanation.from_dict(t) for t in d.get("terms", [])],
            parse_method=d.get("parse_method", ""),
            warnings=d.get("warnings", []),
        )


@dataclass
class TrendKeyword:
    keyword: str          # 정규화된 영문 키워드
    korean: str           # 우리말 라벨
    score: float          # TF-IDF 합산 점수
    paper_count: int      # 이 주제를 다룬 논문 수
    note: str = ""        # 한 줄 설명

    @classmethod
    def from_dict(cls, d: dict) -> "TrendKeyword":
        return cls(
            keyword=d.get("keyword", ""),
            korean=d.get("korean", ""),
            score=float(d.get("score", 0.0)),
            paper_count=int(d.get("paper_count", 0)),
            note=d.get("note", ""),
        )
