# 전자공학 논문 트렌드 분석 & 요약

arXiv의 최신 전자공학 논문을 모아 **최근 자주 등장하는 주제**를 뽑고, 논문 한 편을
**고려대 전기전자공학부 1학년 눈높이**로 풀어 설명하는 Streamlit 웹앱입니다.

## 기능

| 기능 | 내용 |
|---|---|
| 논문 수집 | arXiv API로 최근 N일 내 제출된 논문 수집 (제목·초록·저자·게재일·PDF 링크) |
| 대상 카테고리 | `cond-mat.mes-hall`, `eess.SY`, `physics.app-ph`, `cs.AR` (선택 가능) |
| 트렌드 분석 | 초록 TF-IDF로 후보를 뽑고 Claude가 주제 단위로 병합 → TOP 10 차트 · 워드클라우드 |
| 섹션별 요약 | PDF를 내려받아 Introduction / Methods / Results / Conclusion으로 나눠 각 3~5문장 요약 |
| 왜 중요한가 | "이 논문이 왜 중요한지", "기존 연구 대비 무엇이 다른지"를 각각 한 문단 |
| 용어 설명 | 전문 용어 6~8개를 골라 학부 1학년 수준으로 설명 (수식 없이, 일상 비유 포함) |

## 설치

Python 3.10 이상이 필요합니다.

```bash
pip install -r requirements.txt
```

## API 키 설정

요약·용어 설명·트렌드 정규화에는 Anthropic API 키가 필요합니다.

1. [console.anthropic.com](https://console.anthropic.com/settings/keys)에서 키를 발급받습니다.
2. `.env.example`을 `.env`로 복사하고 키를 채웁니다.

```bash
cp .env.example .env
```

```dotenv
ANTHROPIC_API_KEY=sk-ant-...
```

`.env`는 `.gitignore`에 들어 있어 커밋되지 않습니다. 키를 코드에 직접 적지 마세요.

**키가 없어도** 논문 수집과 TF-IDF 트렌드 차트는 동작합니다. 다만 트렌드 키워드가
`design`, `quantum` 같은 단어 단위로 나오고, 요약·용어 설명은 쓸 수 없습니다.

## 실행

```bash
streamlit run app.py
```

브라우저에서 http://localhost:8501 이 열립니다.

**사용 순서**

1. 왼쪽 사이드바에서 키워드(선택), 기간, 카테고리, 최대 수집 편수를 정하고 **논문 수집**
2. 상단에서 트렌드 TOP 10 차트 / 워드클라우드 / 표를 확인
3. 아래 논문 카드에서 **상세 분석**을 누르면 PDF를 내려받아 요약·용어 설명을 생성

키워드는 쉼표로 여러 개를 넣을 수 있고(`VLSI, semiconductor device`), 여러 단어로 된
키워드는 자동으로 따옴표로 묶여 구문 검색이 됩니다.

## 프로젝트 구조

```
.
├── app.py                # Streamlit 진입점 (검색 → 트렌드 → 목록/상세 라우팅)
├── config.py             # 카테고리·모델·캐시 경로 등 상수
├── core/
│   ├── models.py         # Paper / PaperSections / PaperAnalysis 등 데이터 구조
│   ├── collector.py      # arXiv 쿼리 조립 + 수집 + 검색 캐시
│   ├── pdf_parser.py     # PDF 다운로드 → 2단 조판 처리 → 섹션 분할
│   ├── trends.py         # TF-IDF 후보 추출 + LLM 정규화
│   └── llm.py            # Claude 호출 (structured outputs) + 결과 캐시
├── ui/
│   ├── sidebar.py        # 검색 조건 입력
│   ├── trend_view.py     # TOP 10 차트 / 워드클라우드 / 표
│   └── paper_view.py     # 논문 카드 목록 + 상세 화면
├── tests/                # 각 모듈 단독 실행 테스트
└── cache/                # 런타임 생성 (검색 결과 / PDF / LLM 응답)
```

`core/`(로직)와 `ui/`(화면)가 분리돼 있어 Streamlit 없이도 각 모듈을 단독 실행할 수 있습니다.

```bash
python tests/test_collector.py    # arXiv 수집
python tests/test_pdf_parser.py   # PDF 파싱 + 섹션 분할
python tests/test_trends.py       # 트렌드 추출
python tests/test_llm.py          # 프롬프트/스키마/캐시 (+키가 있으면 실제 호출)
```

## 비용

- 트렌드 정규화: **검색 1회당 API 호출 1회**
- 논문 분석: **논문 1편당 API 호출 1회** (섹션 요약 + 중요성 + 용어 설명을 한 번에)

결과는 `cache/llm/`에 저장되어 같은 논문을 다시 열면 호출하지 않습니다. Streamlit은
위젯을 건드릴 때마다 스크립트를 처음부터 다시 실행하기 때문에, 이 캐시가 없으면
카드를 펼칠 때마다 요금이 나갑니다.

비용을 더 줄이려면 `.env`에서 모델을 바꾸세요.

```dotenv
CLAUDE_MODEL=claude-sonnet-5
CLAUDE_EFFORT=low
```

## 알려진 한계

- **섹션 분할**: arXiv 논문은 조판이 제각각이라 번호 체계·키워드·위치 기반의 3단 폴백을
  씁니다. 실측 6편 중 6편이 구조 인식에 성공했지만, 절 제목이 추출 과정에서 깨지면
  결론이 Results 쪽에 섞이는 등 라벨이 어긋날 수 있습니다. 상세 화면의 "분석 진단 정보"에
  어떤 경로로 나눴는지(`regex` / `heuristic` / `abstract-only`) 표시됩니다.
- **스캔 이미지 PDF**: 텍스트 레이어가 없으면 파싱되지 않습니다. 이 경우 초록만으로 요약합니다.
- **arXiv 요청 제한**: 짧은 시간에 반복 조회하면 429가 납니다. 같은 조건의 검색 결과를
  30분간 `cache/search/`에 캐싱해 완화했습니다.
- **워드클라우드**: 기본 폰트에 한글 글리프가 없어 영문 표기를 씁니다.
- **분야 표시**: arXiv는 논문마다 여러 카테고리를 다는데, 대표 카테고리가 선택한 목록
  밖일 수 있습니다(예: `math.OC`가 대표이고 `eess.SY`가 부카테고리).
