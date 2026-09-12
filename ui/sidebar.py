"""사이드바 — 검색 조건 입력."""
from __future__ import annotations

from dataclasses import dataclass

import streamlit as st

from config import DEFAULT_CATEGORIES, DEFAULT_DAYS, EE_CATEGORIES
from core.llm import api_key_available

EXAMPLE_KEYWORDS = ["VLSI", "semiconductor device", "ASIC design", "power electronics"]


@dataclass
class SearchParams:
    keywords: str
    days: int
    categories: list[str]
    max_results: int
    use_llm: bool
    submitted: bool


def render_sidebar() -> SearchParams:
    st.sidebar.title("검색 조건")

    keywords = st.sidebar.text_input(
        "검색 키워드",
        value=st.session_state.get("keywords", ""),
        placeholder="VLSI, semiconductor device",
        help="쉼표로 구분해 여러 개를 넣을 수 있습니다. 비워두면 카테고리 전체를 봅니다.",
        key="keywords",
    )

    st.sidebar.caption("예시 키워드")
    cols = st.sidebar.columns(2)
    for i, example in enumerate(EXAMPLE_KEYWORDS):
        if cols[i % 2].button(example, width="stretch", key=f"ex_{i}"):
            # 위젯 값을 코드로 바꾸려면 세션 상태를 고치고 즉시 다시 그려야 한다
            st.session_state["keywords"] = example
            st.rerun()

    st.sidebar.divider()

    days = st.sidebar.slider(
        "기간 (최근 N일)", min_value=1, max_value=30, value=DEFAULT_DAYS,
        help="arXiv에 처음 제출된 날짜 기준입니다.",
    )

    categories = st.sidebar.multiselect(
        "카테고리",
        options=list(EE_CATEGORIES),
        default=DEFAULT_CATEGORIES,
        format_func=lambda c: f"{c} — {EE_CATEGORIES[c]}",
    )

    max_results = st.sidebar.slider(
        "최대 수집 편수", min_value=10, max_value=150, value=60, step=10,
        help="트렌드 분석은 30편 이상일 때 쓸 만해집니다.",
    )

    st.sidebar.divider()

    has_key = api_key_available()
    if has_key:
        use_llm = st.sidebar.toggle(
            "트렌드 키워드 LLM 정규화", value=True,
            help="TF-IDF 후보를 Claude가 주제 단위로 합치고 우리말 라벨을 붙입니다. 검색당 1회 호출.",
        )
        st.sidebar.success("Claude API 키 연결됨", icon="✅")
    else:
        use_llm = False
        st.sidebar.warning(
            "ANTHROPIC_API_KEY가 없어 요약·용어 설명을 쓸 수 없습니다. "
            "프로젝트 폴더의 `.env`에 키를 넣어주세요.",
            icon="⚠️",
        )

    submitted = st.sidebar.button(
        "논문 수집", type="primary", width="stretch", disabled=not categories
    )
    if not categories:
        st.sidebar.error("카테고리를 하나 이상 선택해주세요.")

    return SearchParams(
        keywords=keywords,
        days=days,
        categories=categories,
        max_results=max_results,
        use_llm=use_llm,
        submitted=submitted,
    )
