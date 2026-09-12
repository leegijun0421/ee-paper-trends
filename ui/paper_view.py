"""하단 논문 리스트(카드)와 상세 화면(용어 설명 + 섹션별 요약)."""
from __future__ import annotations

import streamlit as st

from config import EE_CATEGORIES
from core.llm import LLMError, analyze_paper, api_key_available
from core.models import Paper, PaperAnalysis
from core.pdf_parser import parse_sections

_PARSE_LABELS = {
    "regex": ("섹션 제목을 인식해 나눴습니다", "✅"),
    "heuristic": ("섹션 제목을 찾지 못해 본문을 위치 기준으로 4등분했습니다. 섹션 경계가 정확하지 않을 수 있습니다", "⚠️"),
    "abstract-only": ("본문을 가져오지 못해 초록만으로 요약했습니다", "⚠️"),
}


def _select(arxiv_id: str) -> None:
    st.session_state["selected"] = arxiv_id


def _clear_selection() -> None:
    st.session_state["selected"] = None


# ---------------------------------------------------------------- 리스트
def render_paper_list(papers: list[Paper]) -> None:
    st.subheader(f"논문 목록 ({len(papers)}편)")
    if not papers:
        st.info("조건에 맞는 논문이 없습니다. 키워드를 줄이거나 기간을 늘려보세요.")
        return

    st.caption("카드의 '상세 분석'을 누르면 용어 설명과 섹션별 요약을 볼 수 있습니다.")

    for paper in papers:
        with st.container(border=True):
            left, right = st.columns([5, 1])

            with left:
                st.markdown(f"**{paper.title}**")
                st.caption(
                    f"{paper.author_line}  ·  {paper.published:%Y-%m-%d} "
                    f"({paper.days_ago}일 전)  ·  `{paper.primary_category}`"
                )
                preview = paper.abstract[:280]
                if len(paper.abstract) > 280:
                    preview += "…"
                st.write(preview)

            with right:
                st.button(
                    "상세 분석",
                    key=f"detail_{paper.arxiv_id}",
                    on_click=_select,
                    args=(paper.arxiv_id,),
                    width="stretch",
                    type="primary",
                )
                st.link_button("PDF", paper.pdf_url, width="stretch")
                st.link_button("arXiv", paper.entry_url, width="stretch")


# ---------------------------------------------------------------- 상세
def _run_analysis(paper: Paper) -> PaperAnalysis | None:
    """PDF 내려받기 → 섹션 분할 → Claude 분석. 실패하면 화면에 사유를 남긴다."""
    key = f"analysis_{paper.arxiv_id}"
    if key in st.session_state:
        return st.session_state[key]

    with st.status("논문을 분석하는 중…", expanded=True) as status:
        st.write("PDF를 내려받고 섹션을 나누는 중…")
        sections = parse_sections(paper)
        st.write(f"인식한 섹션: {', '.join(sections.found_sections) or '없음'}")

        st.write("Claude가 요약과 용어 설명을 만드는 중… (30초~1분)")
        try:
            analysis = analyze_paper(paper, sections)
        except LLMError as e:
            status.update(label="분석 실패", state="error")
            st.error(str(e))
            return None

        status.update(label="분석 완료", state="complete", expanded=False)

    st.session_state[key] = analysis
    return analysis


def _render_terms(analysis: PaperAnalysis) -> None:
    if not analysis.terms:
        st.info("추출된 전문 용어가 없습니다.")
        return
    for term in analysis.terms:
        label = f"**{term.term}**" + (f" — {term.korean}" if term.korean else "")
        with st.expander(label):
            st.write(term.explanation)
            if term.analogy:
                st.info(f"비유: {term.analogy}", icon="💡")


def _render_summaries(analysis: PaperAnalysis) -> None:
    labels = [
        ("Introduction", "introduction", "서론 — 무엇을 왜 하려 했는가"),
        ("Methods", "methods", "본론 — 어떻게 했는가"),
        ("Results", "results", "결과 — 무엇을 얻었는가"),
        ("Conclusion", "conclusion", "결론 — 무엇을 주장하는가"),
    ]
    for title, key, subtitle in labels:
        body = analysis.section_summaries.get(key, "").strip()
        with st.container(border=True):
            st.markdown(f"##### {title}")
            st.caption(subtitle)
            st.write(body or "_요약 없음_")


def render_paper_detail(paper: Paper) -> None:
    st.button("← 목록으로", on_click=_clear_selection)

    st.title(paper.title)
    st.caption(
        f"{', '.join(paper.authors)}  ·  {paper.published:%Y-%m-%d}  ·  "
        f"`{paper.primary_category}` ({EE_CATEGORIES.get(paper.primary_category, '기타')})"
    )
    a, b = st.columns(2)
    a.link_button("PDF 원문", paper.pdf_url, width="stretch")
    b.link_button("arXiv 페이지", paper.entry_url, width="stretch")

    with st.expander("원문 초록 보기"):
        st.write(paper.abstract)

    st.divider()

    if not api_key_available():
        st.error(
            "요약과 용어 설명에는 Claude API 키가 필요합니다. 프로젝트 폴더에 `.env` 파일을 만들고 "
            "`ANTHROPIC_API_KEY=sk-ant-...` 를 넣은 뒤 앱을 다시 실행해주세요.",
            icon="🔑",
        )
        return

    analysis = _run_analysis(paper)
    if analysis is None:
        return

    if analysis.one_liner:
        st.success(f"**한 줄 요약** — {analysis.one_liner}", icon="📌")

    note = _PARSE_LABELS.get(analysis.parse_method)
    if note and analysis.parse_method != "regex":
        st.warning(note[0], icon=note[1])

    tab_summary, tab_terms, tab_why = st.tabs(
        ["섹션별 요약", f"용어 설명 ({len(analysis.terms)})", "왜 중요한가"]
    )

    with tab_summary:
        _render_summaries(analysis)

    with tab_terms:
        st.caption("고려대 전기전자공학부 1학년 눈높이로 풀어 쓴 설명입니다.")
        _render_terms(analysis)

    with tab_why:
        st.markdown("##### 이 논문이 왜 중요한가")
        st.write(analysis.significance or "_내용 없음_")
        st.markdown("##### 기존 연구 대비 무엇이 다른가")
        st.write(analysis.novelty or "_내용 없음_")

    with st.expander("분석 진단 정보"):
        st.write(f"섹션 분할 방식: `{analysis.parse_method}`")
        for w in analysis.warnings:
            st.text(f"• {w[:300]}")
