"""상단 트렌드 영역 — TOP 10 차트와 워드클라우드."""
from __future__ import annotations

import matplotlib.pyplot as plt
import plotly.graph_objects as go
import streamlit as st
from wordcloud import WordCloud

from core.models import Paper, TrendKeyword


def _bar_chart(trends: list[TrendKeyword]) -> go.Figure:
    # 가로 막대는 위에서 아래로 그려지므로 뒤집어 1위가 맨 위에 오게 한다
    items = list(reversed(trends))
    labels = [
        k.korean if k.korean == k.keyword else f"{k.korean}<br><sub>{k.keyword}</sub>"
        for k in items
    ]
    hover = [
        f"<b>{k.keyword}</b><br>{k.paper_count}편<br>{k.note or ''}<extra></extra>"
        for k in items
    ]

    fig = go.Figure(
        go.Bar(
            x=[k.score for k in items],
            y=labels,
            orientation="h",
            text=[f"{k.paper_count}편" for k in items],
            textposition="outside",
            hovertemplate=hover,
            marker=dict(
                color=[k.score for k in items],
                colorscale="Teal",
                showscale=False,
            ),
        )
    )
    fig.update_layout(
        height=max(360, 38 * len(items)),
        margin=dict(l=10, r=40, t=10, b=10),
        xaxis_title="TF-IDF 합산 점수",
        yaxis_title=None,
        plot_bgcolor="rgba(0,0,0,0)",
    )
    fig.update_xaxes(showgrid=True, gridcolor="rgba(128,128,128,0.2)")
    return fig


def _wordcloud(trends: list[TrendKeyword]):
    # 한글 라벨은 기본 폰트에서 네모로 깨지므로 영문 표기를 쓴다
    freqs = {k.keyword: k.score for k in trends if k.score > 0}
    if not freqs:
        return None
    cloud = WordCloud(
        width=1000, height=450,
        background_color=None, mode="RGBA",
        colormap="viridis", prefer_horizontal=0.9,
        relative_scaling=0.5,
    ).generate_from_frequencies(freqs)

    fig, ax = plt.subplots(figsize=(10, 4.5))
    ax.imshow(cloud, interpolation="bilinear")
    ax.axis("off")
    fig.patch.set_alpha(0)
    fig.tight_layout(pad=0)
    return fig


def render_trends(
    trends: list[TrendKeyword], papers: list[Paper], warnings: list[str], days: int
) -> None:
    st.subheader(f"최근 {days}일간 가장 많이 언급된 주제 TOP {len(trends)}")

    for w in warnings:
        st.warning(w, icon="⚠️")

    if not trends:
        st.info("트렌드를 계산할 만큼 논문이 모이지 않았습니다. 기간이나 카테고리를 넓혀보세요.")
        return

    a, b, c = st.columns(3)
    a.metric("수집 논문", f"{len(papers)}편")
    b.metric("추출 주제", f"{len(trends)}개")
    c.metric("1위 주제", trends[0].korean)

    tab_chart, tab_cloud, tab_table = st.tabs(["차트", "워드클라우드", "표"])

    with tab_chart:
        st.plotly_chart(_bar_chart(trends), width="stretch")
        st.caption(
            "막대 길이는 초록에서 계산한 TF-IDF 합산 점수, 막대 끝 숫자는 그 주제가 등장한 논문 수입니다."
        )

    with tab_cloud:
        fig = _wordcloud(trends)
        if fig is None:
            st.info("워드클라우드를 만들 키워드가 없습니다.")
        else:
            st.pyplot(fig, width="stretch")
            plt.close(fig)
            st.caption("글자 크기는 TF-IDF 점수에 비례합니다. (한글 폰트 문제로 영문 표기를 씁니다)")

    with tab_table:
        st.dataframe(
            [
                {
                    "순위": i,
                    "주제": k.korean,
                    "원문": k.keyword,
                    "점수": round(k.score, 3),
                    "논문 수": k.paper_count,
                    "설명": k.note,
                }
                for i, k in enumerate(trends, 1)
            ],
            width="stretch",
            hide_index=True,
        )
