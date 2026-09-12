"""Claude API 연동 — 용어 설명, 섹션 요약, 트렌드 키워드 정규화.

호출은 전부 structured outputs(`output_config.format`)를 써서 JSON 스키마를
강제한다. 응답을 정규식으로 긁어 파싱하다 깨지는 일이 없다.

같은 논문을 다시 열 때 API를 또 부르지 않도록 결과를 디스크에 캐싱한다.
Streamlit은 위젯을 건드릴 때마다 스크립트를 처음부터 다시 실행하므로,
캐시가 없으면 카드를 한 번 펼칠 때마다 요금이 나간다.
"""
from __future__ import annotations

import hashlib
import json
import logging
from pathlib import Path

import anthropic

from config import (
    ANTHROPIC_API_KEY,
    AUDIENCE,
    CLAUDE_EFFORT,
    CLAUDE_MAX_TOKENS,
    CLAUDE_MODEL,
    LLM_CACHE_DIR,
    MAX_SECTION_CHARS,
    TOP_K_KEYWORDS,
)
from core.models import Paper, PaperAnalysis, PaperSections, TermExplanation

log = logging.getLogger(__name__)


class LLMError(RuntimeError):
    """호출자(UI)가 사용자에게 그대로 보여줄 수 있는 오류 메시지."""


# ---------------------------------------------------------------- 클라이언트
_client: anthropic.Anthropic | None = None


def get_client() -> anthropic.Anthropic:
    global _client
    if _client is None:
        if not ANTHROPIC_API_KEY:
            raise LLMError(
                "ANTHROPIC_API_KEY가 없습니다. 프로젝트 폴더에 .env 파일을 만들고 "
                "ANTHROPIC_API_KEY=sk-ant-... 한 줄을 넣어주세요."
            )
        _client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
    return _client


def api_key_available() -> bool:
    return bool(ANTHROPIC_API_KEY)


# ---------------------------------------------------------------- 캐시
def _prompt_version(system: str) -> str:
    """시스템 프롬프트를 고치면 캐시가 자동으로 무효화되도록 지문을 만든다."""
    return hashlib.sha256(system.encode("utf-8")).hexdigest()[:8]


def _cache_path(kind: str, key: str) -> Path:
    digest = hashlib.sha256(key.encode("utf-8")).hexdigest()[:16]
    return LLM_CACHE_DIR / f"{kind}_{digest}.json"


def _cache_load(kind: str, key: str) -> dict | None:
    path = _cache_path(kind, key)
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None


def _cache_save(kind: str, key: str, value: dict) -> None:
    try:
        _cache_path(kind, key).write_text(
            json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8"
        )
    except OSError as e:
        log.warning("LLM 캐시 저장 실패: %s", e)


# ---------------------------------------------------------------- 호출 래퍼
def _call_json(system: str, user: str, schema: dict) -> dict:
    """JSON 스키마를 강제해 한 번 호출하고 파싱된 dict를 돌려준다."""
    client = get_client()
    try:
        response = client.messages.create(
            model=CLAUDE_MODEL,
            max_tokens=CLAUDE_MAX_TOKENS,
            system=system,
            output_config={
                "effort": CLAUDE_EFFORT,
                "format": {"type": "json_schema", "schema": schema},
            },
            messages=[{"role": "user", "content": user}],
        )
    except anthropic.AuthenticationError:
        raise LLMError("API 키가 올바르지 않습니다. .env의 ANTHROPIC_API_KEY를 확인해주세요.")
    except anthropic.NotFoundError:
        raise LLMError(f"모델 '{CLAUDE_MODEL}'을 찾을 수 없습니다. .env의 CLAUDE_MODEL을 확인해주세요.")
    except anthropic.RateLimitError:
        raise LLMError("요청이 몰렸습니다(429). 잠시 후 다시 시도해주세요.")
    except anthropic.APIStatusError as e:
        raise LLMError(f"Claude API 오류 ({e.status_code}): {e.message}")
    except anthropic.APIConnectionError:
        raise LLMError("네트워크 오류로 Claude API에 연결하지 못했습니다.")

    # 안전 분류기가 요청을 거절하면 content가 비어 있을 수 있다
    if response.stop_reason == "refusal":
        raise LLMError("모델이 이 요청에 대한 응답을 거절했습니다.")
    if response.stop_reason == "max_tokens":
        raise LLMError(
            "응답이 max_tokens에서 잘렸습니다. config.py의 CLAUDE_MAX_TOKENS를 늘려주세요."
        )

    text = next((b.text for b in response.content if b.type == "text"), "")
    if not text:
        raise LLMError("모델이 빈 응답을 돌려주었습니다.")
    return json.loads(text)


def _clip(text: str, limit: int = MAX_SECTION_CHARS) -> str:
    text = " ".join((text or "").split())
    if len(text) <= limit:
        return text
    return text[:limit] + " …(이하 생략)"


# ---------------------------------------------------------------- 논문 분석
_ANALYSIS_SCHEMA = {
    "type": "object",
    "properties": {
        "one_liner": {"type": "string", "description": "논문 전체를 한 문장으로 요약(한국어)"},
        "sections": {
            "type": "object",
            "properties": {
                "introduction": {"type": "string"},
                "methods": {"type": "string"},
                "results": {"type": "string"},
                "conclusion": {"type": "string"},
            },
            "required": ["introduction", "methods", "results", "conclusion"],
            "additionalProperties": False,
        },
        "significance": {"type": "string", "description": "이 논문이 왜 중요한지 한 문단"},
        "novelty": {"type": "string", "description": "기존 연구 대비 무엇이 다른지 한 문단"},
        "terms": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "term": {"type": "string", "description": "논문에 등장한 원문 용어"},
                    "korean": {"type": "string", "description": "우리말 표기"},
                    "explanation": {"type": "string", "description": "2~3문장 설명"},
                    "analogy": {"type": "string", "description": "일상적인 비유 한 문장"},
                },
                "required": ["term", "korean", "explanation", "analogy"],
                "additionalProperties": False,
            },
        },
    },
    "required": ["one_liner", "sections", "significance", "novelty", "terms"],
    "additionalProperties": False,
}

_ANALYSIS_SYSTEM = f"""당신은 전자공학 논문을 학부 저학년에게 풀어 설명하는 조교입니다.
독자는 {AUDIENCE}입니다. 미적분과 일반물리는 배웠지만 반도체 소자, VLSI,
제어이론, 양자역학 같은 전공 과목은 아직 듣지 않았다고 가정하세요.

작성 규칙:
- 모든 출력은 한국어로 작성합니다. 단, 정착된 전문 용어는 "핀펫(FinFET)"처럼
  우리말과 원문을 함께 적습니다.
- 수식은 쓰지 않습니다. 꼭 필요하면 말로 풀어 설명합니다.
- 각 섹션 요약은 3~5문장입니다. 원문에 없는 내용을 지어내지 않습니다.
- 어떤 섹션의 원문이 제공되지 않았다면, 그 자리에 "원문에서 이 섹션을 찾지
  못했습니다."라고만 적습니다. 다른 섹션 내용으로 채우지 않습니다.
- terms에는 이 논문을 읽는 데 꼭 필요한 전문 용어를 6~8개 고릅니다. 학부
  1학년이 이미 아는 단어(전압, 저항 등)는 제외합니다. analogy는 비전공자도
  떠올릴 수 있는 일상 사물에 빗댄 한 문장으로 씁니다.
- significance는 "그래서 이게 왜 중요한가"를, novelty는 "기존 연구는 이렇게
  했는데 이 논문은 이렇게 다르다"를 각각 한 문단으로 씁니다."""


def _build_analysis_prompt(paper: Paper, sections: PaperSections) -> str:
    parts = [
        f"# 제목\n{paper.title}",
        f"\n# 저자\n{', '.join(paper.authors[:10])}",
        f"\n# 카테고리\n{paper.primary_category} ({', '.join(paper.categories[:5])})",
        f"\n# 초록\n{_clip(paper.abstract, 4000)}",
    ]
    for label, body in sections.as_mapping().items():
        text = _clip(body)
        parts.append(f"\n# {label} 원문\n{text if text else '(원문에서 찾지 못함)'}")

    if sections.parse_method == "heuristic":
        parts.append(
            "\n※ 참고: 섹션 제목을 인식하지 못해 본문을 위치 기준으로 나눴습니다. "
            "섹션 경계가 정확하지 않을 수 있으니, 각 덩어리의 실제 내용에 맞춰 요약하세요."
        )
    elif sections.parse_method == "abstract-only":
        parts.append(
            "\n※ 참고: 본문을 가져오지 못해 초록만 제공됩니다. 초록에서 알 수 있는 "
            "범위로만 작성하고, 근거가 없는 섹션은 찾지 못했다고 적으세요."
        )
    return "\n".join(parts)


def analyze_paper(
    paper: Paper, sections: PaperSections, *, use_cache: bool = True
) -> PaperAnalysis:
    """논문 한 편의 섹션 요약 + 중요성 + 용어 설명을 한 번의 호출로 받아온다."""
    cache_key = (
        f"{paper.arxiv_id}|{CLAUDE_MODEL}|{sections.parse_method}"
        f"|{_prompt_version(_ANALYSIS_SYSTEM)}"
    )

    if use_cache:
        cached = _cache_load("analysis", cache_key)
        if cached:
            log.info("분석 캐시 적중: %s", paper.arxiv_id)
            return PaperAnalysis.from_dict(cached)

    data = _call_json(
        _ANALYSIS_SYSTEM,
        _build_analysis_prompt(paper, sections),
        _ANALYSIS_SCHEMA,
    )

    analysis = PaperAnalysis(
        arxiv_id=paper.arxiv_id,
        one_liner=data.get("one_liner", ""),
        section_summaries=data.get("sections", {}),
        significance=data.get("significance", ""),
        novelty=data.get("novelty", ""),
        terms=[TermExplanation.from_dict(t) for t in data.get("terms", [])],
        parse_method=sections.parse_method,
        warnings=list(sections.warnings),
    )
    _cache_save("analysis", cache_key, analysis.to_dict())
    return analysis


# ---------------------------------------------------------------- 트렌드 정규화
_TRENDS_SCHEMA = {
    "type": "object",
    "properties": {
        "keywords": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "keyword": {"type": "string", "description": "대표 영문 표기"},
                    "korean": {"type": "string", "description": "우리말 라벨"},
                    "merged_from": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "이 주제로 합쳐진 후보 키워드들",
                    },
                    "note": {"type": "string", "description": "한 줄 설명"},
                },
                "required": ["keyword", "korean", "merged_from", "note"],
                "additionalProperties": False,
            },
        }
    },
    "required": ["keywords"],
    "additionalProperties": False,
}

_TRENDS_SYSTEM = f"""당신은 전자공학 논문 동향을 정리하는 조교입니다.
TF-IDF로 뽑은 후보 키워드 목록을 받아 실제 '연구 주제' 단위로 정리하세요.

규칙:
- 같은 개념의 표기 흔들림(예: "finfet"/"fin fet", "neural network"/"neural networks")은
  하나로 합치고, 합친 후보들을 merged_from에 모두 적습니다.
- merged_from에는 **같은 개념의 표기 변형만** 넣습니다. "quantum", "hall",
  "transport"처럼 여러 주제에 두루 쓰이는 상위어를 특정 주제 밑으로 끌어오지
  마세요. merged_from에 넣은 단어의 등장 편수가 곧 그 주제의 편수로 집계되므로,
  넓게 묶을수록 수치가 부풀려집니다.
- 논문 어디에나 나오는 일반어(예: "proposed method", "results show", "using",
  "paper", "approach")는 결과에서 제외합니다.
- 남은 것 중 연구 주제로서 의미 있는 상위 {TOP_K_KEYWORDS}개만 고릅니다.
- korean은 {AUDIENCE}가 알아볼 수 있는 우리말 라벨입니다. 정착된 번역이
  없으면 원문을 그대로 쓰고 괄호로 짧게 풀어줍니다.
- note는 "이게 무슨 주제인지" 한 줄 설명입니다.
- 후보에 없는 키워드를 새로 만들지 마세요."""


def normalize_keywords(
    candidates: list[tuple[str, float]],
    sample_titles: list[str],
    *,
    use_cache: bool = True,
) -> list[dict]:
    """TF-IDF 후보를 주제 단위로 병합·정리한다. 실패해도 예외를 올리지 않는다.

    반환: [{keyword, korean, merged_from, note}, ...] — 실패 시 빈 리스트.
    """
    if not candidates:
        return []

    cache_key = (
        f"{CLAUDE_MODEL}|{_prompt_version(_TRENDS_SYSTEM)}|"
        + "|".join(f"{k}:{v:.3f}" for k, v in candidates)
    )
    if use_cache:
        cached = _cache_load("trends", cache_key)
        if cached:
            log.info("트렌드 캐시 적중")
            return cached.get("keywords", [])

    listing = "\n".join(f"- {k} (점수 {v:.3f})" for k, v in candidates)
    titles = "\n".join(f"- {t}" for t in sample_titles[:20])
    user = (
        f"# TF-IDF 후보 키워드\n{listing}\n\n"
        f"# 참고용 논문 제목 일부\n{titles}\n\n"
        "위 후보를 연구 주제 단위로 정리해주세요."
    )

    data = _call_json(_TRENDS_SYSTEM, user, _TRENDS_SCHEMA)
    _cache_save("trends", cache_key, data)
    return data.get("keywords", [])
