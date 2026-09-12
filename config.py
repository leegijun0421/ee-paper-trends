"""프로젝트 전역 설정 및 상수."""
from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent

# 경로를 명시한다. 상위 폴더에서 `streamlit run EEResearch/app.py` 로 실행하면
# 작업 디렉터리가 프로젝트 밖이 되어, 인자 없는 load_dotenv()는 .env를 놓칠 수 있다.
load_dotenv(BASE_DIR / ".env")
CACHE_DIR = BASE_DIR / "cache"
PDF_CACHE_DIR = CACHE_DIR / "pdfs"
LLM_CACHE_DIR = CACHE_DIR / "llm"
SEARCH_CACHE_DIR = CACHE_DIR / "search"

for _d in (PDF_CACHE_DIR, LLM_CACHE_DIR, SEARCH_CACHE_DIR):
    _d.mkdir(parents=True, exist_ok=True)

# 같은 검색을 30분 안에 반복하면 arXiv를 다시 부르지 않는다 (429 방지)
SEARCH_CACHE_TTL = 30 * 60

# ---------------------------------------------------------------- arXiv
# 전자공학 관련 arXiv 카테고리. key = arXiv 카테고리 코드, value = 화면 표시용 라벨
EE_CATEGORIES: dict[str, str] = {
    "cond-mat.mes-hall": "메조스코픽·나노 물리 (소자 물리)",
    "eess.SY": "시스템·제어 (Systems and Control)",
    "physics.app-ph": "응용물리 (Applied Physics)",
    "cs.AR": "컴퓨터 구조 (Hardware Architecture)",
}

DEFAULT_CATEGORIES: list[str] = list(EE_CATEGORIES)
DEFAULT_DAYS = 7
DEFAULT_MAX_RESULTS = 60

# arXiv API 예의: 요청 간 최소 3초 간격 권장
ARXIV_DELAY_SECONDS = 3.0
ARXIV_PAGE_SIZE = 100

# ---------------------------------------------------------------- Claude
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")
# 비용을 낮추고 싶으면 .env 에서 CLAUDE_MODEL=claude-sonnet-5 로 바꾸면 된다
CLAUDE_MODEL = os.getenv("CLAUDE_MODEL", "claude-opus-5")
# 논문 한 편 분석은 섹션 요약 4개 + 용어 6~8개라 넉넉히 잡는다
CLAUDE_MAX_TOKENS = 8000
# low | medium | high | xhigh | max — 요약·설명은 medium으로 충분하다
CLAUDE_EFFORT = os.getenv("CLAUDE_EFFORT", "medium")

# LLM에 넘기기 전 섹션별로 잘라낼 최대 글자 수 (토큰 비용 방어)
MAX_SECTION_CHARS = 7000

# 학부생 눈높이 설명의 기준이 되는 페르소나
AUDIENCE = "고려대학교 전기전자공학부 1학년 학부생"

# ---------------------------------------------------------------- 트렌드
TOP_K_KEYWORDS = 10
# TF-IDF 후보를 넉넉히 뽑아 LLM 정규화 단계에서 병합·정리한다
TFIDF_CANDIDATE_K = 40
