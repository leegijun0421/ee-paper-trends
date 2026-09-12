"""전자공학 논문 트렌드 분석 & 요약 — Streamlit 진입점.

실행: streamlit run app.py
"""
from __future__ import annotations

import logging

import streamlit as st

st.set_page_config(
    page_title="전자공학 논문 트렌드",
    page_icon="📡",
    layout="wide",
    initial_sidebar_state="expanded",
)

from core.collector import CollectorError, collect_papers  # noqa: E402
from core.trends import compute_trends  # noqa: E402
from ui.paper_view import render_paper_detail, render_paper_list  # noqa: E402
from ui.sidebar import render_sidebar  # noqa: E402
from ui.trend_view import render_trends  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")


def _init_state() -> None:
    st.session_state.setdefault("papers", [])
    st.session_state.setdefault("trends", [])
    st.session_state.setdefault("trend_warnings", [])
    st.session_state.setdefault("selected", None)
    st.session_state.setdefault("last_days", 7)
    st.session_state.setdefault("searched", False)


def _run_search(params) -> None:
    st.session_state["selected"] = None

    with st.spinner("arXiv에서 논문을 가져오는 중…"):
        try:
            papers = collect_papers(
                params.keywords, params.categories, params.days, params.max_results
            )
        except CollectorError as e:
            st.error(str(e), icon="🚫")
            return

    st.session_state["papers"] = papers
    st.session_state["last_days"] = params.days
    st.session_state["searched"] = True

    if not papers:
        st.session_state["trends"] = []
        st.session_state["trend_warnings"] = []
        return

    with st.spinner("초록에서 트렌드 키워드를 뽑는 중…"):
        trends, warnings = compute_trends(papers, use_llm=params.use_llm)

    st.session_state["trends"] = trends
    st.session_state["trend_warnings"] = warnings


def main() -> None:
    _init_state()
    params = render_sidebar()

    if params.submitted:
        _run_search(params)

    papers = st.session_state["papers"]
    selected_id = st.session_state["selected"]

    # 상세 화면은 목록/트렌드를 대체한다
    if selected_id:
        paper = next((p for p in papers if p.arxiv_id == selected_id), None)
        if paper is not None:
            render_paper_detail(paper)
            return
        st.session_state["selected"] = None

    st.title("📡 전자공학 논문 트렌드 분석")
    st.caption(
        "arXiv의 최신 전자공학 논문을 모아 트렌드를 뽑고, 논문 한 편을 "
        "학부 1학년 눈높이로 풀어 설명합니다."
    )

    if not st.session_state["searched"]:
        st.info(
            "왼쪽 사이드바에서 조건을 정하고 **논문 수집**을 눌러주세요.\n\n"
            "- 키워드를 비워두면 선택한 카테고리 전체의 최신 논문을 봅니다.\n"
            "- 트렌드 분석은 30편 이상 모였을 때 쓸 만해집니다.",
            icon="👈",
        )
        return

    render_trends(
        st.session_state["trends"],
        papers,
        st.session_state["trend_warnings"],
        st.session_state["last_days"],
    )
    st.divider()
    render_paper_list(papers)


if __name__ == "__main__":
    main()
