"""arXiv PDF를 내려받아 텍스트를 뽑고 Intro/Methods/Results/Conclusion으로 나눈다.

arXiv 논문은 조판이 제각각(1단/2단, 로마숫자/아라비아 절 번호, 대문자/제목형
헤더)이라 단일 규칙으로는 다 잡히지 않는다. 그래서 3단계로 내려간다.

  1) 2단 조판 감지 후 컬럼 단위 텍스트 추출
  2) 섹션 헤더 정규식 매칭 → 4개 버킷에 배정        (parse_method="regex")
  3) 헤더를 못 찾으면 본문을 위치 기준으로 4등분    (parse_method="heuristic")
"""
from __future__ import annotations

import logging
import re
import statistics
from pathlib import Path

import pdfplumber
import requests

from config import PDF_CACHE_DIR
from core.models import Paper, PaperSections

log = logging.getLogger(__name__)

MAX_PAGES = 30              # 부록까지 다 읽을 필요는 없다
DOWNLOAD_TIMEOUT = 60
_UA = "ee-paper-trends/0.1 (arXiv summarizer; contact via local use)"


# ---------------------------------------------------------------- 다운로드
def download_pdf(paper: Paper, *, force: bool = False) -> Path:
    """PDF를 캐시에 내려받고 경로를 반환한다."""
    path = PDF_CACHE_DIR / f"{paper.arxiv_id}.pdf"
    if path.exists() and path.stat().st_size > 1024 and not force:
        log.info("PDF 캐시 적중: %s", path.name)
        return path

    url = paper.pdf_url
    log.info("PDF 다운로드: %s", url)
    resp = requests.get(url, timeout=DOWNLOAD_TIMEOUT, headers={"User-Agent": _UA})
    resp.raise_for_status()
    if not resp.content.startswith(b"%PDF"):
        raise ValueError(f"PDF가 아닌 응답을 받았습니다: {url}")

    path.write_bytes(resp.content)
    return path


# ---------------------------------------------------------------- 텍스트 추출
_NBINS = 120


def _column_split_x(page) -> float | None:
    """2단 조판이면 좌우를 가르는 x 좌표를, 아니면 None을 돌려준다.

    페이지 가로축을 잘게 나눠 각 구간을 지나는 단어 수를 세고, 한가운데
    부근에 '거의 비어 있는 골짜기'가 있으면 2단으로 판단한다. 전폭 그림이나
    제목이 가운데를 가로지르는 페이지도 있으므로 0이 아니라 중앙값 대비
    비율로 느슨하게 본다.
    """
    words = page.extract_words()
    if len(words) < 60:
        return None

    x0, x1 = page.bbox[0], page.bbox[2]
    width = x1 - x0
    if width <= 0:
        return None
    binw = width / _NBINS

    counts = [0] * _NBINS
    for w in words:
        a = max(0, min(_NBINS - 1, int((w["x0"] - x0) / binw)))
        b = max(0, min(_NBINS - 1, int((w["x1"] - x0) / binw)))
        for i in range(a, b + 1):
            counts[i] += 1

    nonzero = [c for c in counts if c > 0]
    if not nonzero:
        return None
    median = statistics.median(nonzero)

    lo, hi = int(_NBINS * 0.38), int(_NBINS * 0.62)
    central = counts[lo:hi]
    valley = min(central)
    if valley > max(2.0, median * 0.15):
        return None

    split = x0 + (lo + central.index(valley) + 0.5) * binw
    in_left = sum(1 for w in words if w["x1"] <= split)
    if min(in_left, len(words) - in_left) < len(words) * 0.30:
        return None       # 한쪽으로 쏠렸으면 2단이 아니다
    return split


def _page_text(page) -> str:
    split = _column_split_x(page)
    if split is None:
        return page.extract_text() or ""

    x0, top, x1, bottom = page.bbox
    chunks = []
    for box in ((x0, top, split, bottom), (split, top, x1, bottom)):
        try:
            chunks.append(page.crop(box, strict=False).extract_text() or "")
        except ValueError:  # 잘라낸 영역이 비면 pdfplumber가 예외를 던진다
            chunks.append("")
    return "\n".join(chunks)


def extract_text(pdf_path: Path, max_pages: int = MAX_PAGES) -> tuple[str, list[str]]:
    """PDF 전체 텍스트와 경고 목록을 반환한다."""
    warnings: list[str] = []
    pages: list[str] = []

    with pdfplumber.open(pdf_path) as pdf:
        total = len(pdf.pages)
        if total > max_pages:
            warnings.append(f"{total}쪽 중 앞 {max_pages}쪽만 읽었습니다.")
        for page in pdf.pages[:max_pages]:
            try:
                pages.append(_page_text(page))
            except Exception as e:  # 개별 페이지 실패로 전체를 버리지 않는다
                warnings.append(f"{page.page_number}쪽 추출 실패: {e}")

    text = "\n".join(pages)
    # 줄 끝 하이픈 이음 복원: "semicon-\nductor" → "semiconductor"
    text = re.sub(r"(\w)-\n(\w)", r"\1\2", text)
    if len(text) < 500:
        warnings.append("추출된 텍스트가 너무 짧습니다 (스캔 이미지 PDF일 수 있음).")
    return text, warnings


# ---------------------------------------------------------------- 섹션 분할
# 앞에서부터 순서대로 검사한다. "Experimental Methods"처럼 두 버킷의 단어를
# 동시에 가진 헤더가 흔해서, 더 구체적인 쪽을 먼저 둔다.
_BUCKET_PATTERNS: list[tuple[str, str]] = [
    ("introduction", r"introduction|motivation|background|related\s+work|prior\s+work"),
    ("conclusion",   r"conclusion|concluding|summary\s+and|outlook|future\s+work|final\s+remarks"),
    ("methods",      r"method|methodolog|approach|proposed|design|architecture|"
                     r"implementation|fabrication|materials|framework|"
                     r"theor(?:y|etical)|formulation|preliminar|system\s+model|"
                     r"problem\s+(?:setup|formulation|statement)"),
    ("results",      r"result|evaluation|experiment|discussion|measurement|"
                     r"performance|simulation|ablation|benchmark|case\s+stud|validation"),
]

# 참고문헌·부록이 시작되면 본문은 끝이다 (여기서부터 통째로 버린다)
_HARD_END = r"references?|bibliograph|appendi|supplement(?:ary|al)?"
# 본문 중간에 끼어들 수 있어 해당 블록만 건너뛴다
_SOFT_END = (
    r"acknowledg|author\s+contribution|fundin|declaration|"
    r"conflict\s+of\s+interest|data\s+availability|competing\s+interest"
)
_END_PATTERN = rf"{_HARD_END}|{_SOFT_END}"

# "IV. RESULTS AND DISCUSSION" / "3.2 Proposed Method" / "Conclusion" 등을 모두 잡되
# 본문 중간 문장이 걸리지 않도록 짧은 줄만 대상으로 한다.
_NUM = r"(?:[IVXLC]{1,6}|\d{1,2}(?:\.\d{1,2})*)[\.\)]?[ \t]{1,3}"
_TITLE = r"([A-Za-z][A-Za-z0-9 \-&/,:'’]{2,70}?)"
_HEADER_RE_NUM = re.compile(rf"^[ \t]*{_NUM}{_TITLE}[ \t]*[:.]?[ \t]*$")
_HEADER_RE_ANY = re.compile(rf"^[ \t]*(?:{_NUM})?{_TITLE}[ \t]*[:.]?[ \t]*$")


def _classify(title: str) -> str | None:
    t = title.lower().strip()
    if re.search(_HARD_END, t):
        return "__HARD_END__"
    if re.search(_SOFT_END, t):
        return "__SOFT_END__"
    for bucket, pattern in _BUCKET_PATTERNS:
        if re.search(pattern, t):
            return bucket
    return None


def _find_headers(lines: list[str], *, require_numbering: bool) -> list[tuple[int, str, str]]:
    """(줄 번호, 버킷, 헤더 원문) 목록."""
    pattern = _HEADER_RE_NUM if require_numbering else _HEADER_RE_ANY
    found: list[tuple[int, str, str]] = []

    for i, line in enumerate(lines):
        stripped = line.strip()
        if not (3 <= len(stripped) <= 75):
            continue
        if stripped.endswith((",", ";")) or stripped.count(" ") > 7:
            continue
        m = pattern.match(line)
        if not m:
            continue
        title = m.group(1).strip()
        words = [w for w in title.split() if w]
        if not words:
            continue
        # 헤더는 보통 전부 대문자이거나 각 단어가 대문자로 시작한다
        if sum(1 for w in words if w[:1].isupper()) / len(words) < 0.6:
            continue
        bucket = _classify(title)
        if bucket:
            found.append((i, bucket, stripped))

    return _drop_front_matter(found)


def _drop_front_matter(headers: list[tuple[int, str, str]]) -> list[tuple[int, str, str]]:
    """논문 제목·표 캡션이 첫 절 앞에서 헤더로 오인되는 경우를 잘라낸다.

    (예: 'The Benefits of an Integrated Approach ...' 라는 제목이 'approach'
    때문에 methods로 분류되고, 그 아래 저자·소속 블록을 통째로 삼킨다.)
    """
    for idx, (_, bucket, _) in enumerate(headers):
        if bucket == "introduction":
            return headers[idx:]
    return headers


def _is_caps_line(line: str) -> bool:
    s = line.strip()
    letters = [c for c in s if c.isalpha()]
    return bool(letters) and 2 <= len(s) <= 60 and not any(c.islower() for c in letters)


def _content_start(lines: list[str], header_line: int) -> int:
    """대문자 절 제목이 두 줄로 접힌 경우 이어지는 줄까지 건너뛴다.

    'II. MECHANICAL TOPOLOGICAL' / 'INSULATOR AND DISPERSION RELATION' 처럼
    제목이 줄바꿈되면 뒷줄이 본문 첫 문장으로 딸려 들어간다.
    """
    start = header_line + 1
    if not _is_caps_line(lines[header_line]):
        return start
    for _ in range(2):
        if start < len(lines) and _is_caps_line(lines[start]):
            start += 1
        else:
            break
    return start


def _assemble(lines: list[str], headers: list[tuple[int, str, str]]) -> tuple[dict[str, str], list[str]]:
    buckets: dict[str, list[str]] = {
        "introduction": [], "methods": [], "results": [], "conclusion": []
    }
    labels: list[str] = []

    for idx, (line_no, bucket, raw) in enumerate(headers):
        if bucket == "__HARD_END__":
            break
        end = headers[idx + 1][0] if idx + 1 < len(headers) else len(lines)
        if bucket == "__SOFT_END__":
            continue          # 감사의 글 같은 블록은 건너뛰고 계속 스캔한다
        body = "\n".join(lines[_content_start(lines, line_no) : end]).strip()
        if body:
            buckets[bucket].append(body)
            labels.append(raw)

    return {k: "\n\n".join(v).strip() for k, v in buckets.items()}, labels


def _score(buckets: dict[str, str]) -> int:
    return sum(1 for v in buckets.values() if len(v.strip()) > 200)


# ---- 구조 기반 탐색 -------------------------------------------------------
# 물리 계열 논문은 절 제목을 'II. MULTI-STATE QUANTUM GEOMETRY'처럼 내용으로
# 붙여서, 키워드만으로는 Conclusion 말고는 아무것도 안 걸린다. 그래서 번호
# 체계로 절 구조를 먼저 복원하고, 키워드는 '보정'에만 쓴다.
_ROMAN_VALUES = {"I": 1, "V": 5, "X": 10, "L": 50, "C": 100}
_STRUCT_RE = re.compile(
    r"^[ \t]*([IVXLC]{1,6}|\d{1,2})[\.\)]?[ \t]{1,3}"
    r"([A-Za-z][A-Za-z0-9 \-&/,:'’]{2,70}?)[ \t]*[:.]?[ \t]*$"
)
_BUCKET_ORDER = ["introduction", "methods", "results", "conclusion"]


def _to_int(token: str) -> int | None:
    if token.isdigit():
        return int(token)
    total = prev = 0
    for ch in reversed(token.upper()):
        v = _ROMAN_VALUES.get(ch)
        if v is None:
            return None
        total += -v if v < prev else v
        prev = max(prev, v)
    return total or None


def _find_structural_headers(lines: list[str]) -> list[tuple[int, int, str, str]]:
    """(줄 번호, 절 번호, 제목, 원문) — 번호가 붙은 최상위 절만."""
    out: list[tuple[int, int, str, str]] = []
    for i, line in enumerate(lines):
        stripped = line.strip()
        if not (5 <= len(stripped) <= 75) or stripped.count(" ") > 7:
            continue
        m = _STRUCT_RE.match(line)
        if not m:
            continue
        num = _to_int(m.group(1))
        if num is None or not (1 <= num <= 30):
            continue
        title = m.group(2).strip()
        words = title.split()
        if sum(1 for w in words if w[:1].isupper()) / len(words) < 0.6:
            continue
        out.append((i, num, title, stripped))
    return _longest_increasing(out)


def _longest_increasing(cands: list[tuple[int, int, str, str]]) -> list[tuple[int, int, str, str]]:
    """절 번호가 증가하는 가장 긴 부분열만 남긴다.

    본문 중간의 우연한 매칭이나 표 캡션을 걸러내고, 헤더 하나가 추출에서
    깨져 빠지더라도(1이 없고 2부터 시작해도) 나머지를 살린다.
    """
    if len(cands) < 2:
        return cands
    n = len(cands)
    best = [1] * n
    prev = [-1] * n
    for i in range(n):
        for j in range(i):
            if cands[j][1] < cands[i][1] and best[j] + 1 > best[i]:
                best[i], prev[i] = best[j] + 1, j
    end = max(range(n), key=lambda i: best[i])
    chain = []
    while end != -1:
        chain.append(cands[end])
        end = prev[end]
    return list(reversed(chain))


def _assign_buckets(headers: list[tuple[int, int, str, str]]) -> list[tuple[int, str, str]]:
    """절 순서를 이용해 각 절을 4개 버킷에 배정한다.

    키워드로 분류되면 그대로 따르고, 이름만 봐선 알 수 없는 절은 직전 절을
    이어받되 뒤로 되돌아가지는 않는다. 첫 절 다음부터는 기본값을 methods로
    올려, 서론이 논문 전체를 삼키는 일을 막는다.
    """
    assigned: list[tuple[int, str, str]] = []
    inherited: list[int] = []      # 키워드 없이 이어받기만 한 절의 위치
    explicit_results = False
    current = "introduction"

    for idx, (line_no, _num, title, raw) in enumerate(headers):
        bucket = _classify(title)
        if bucket in ("__HARD_END__", "__SOFT_END__"):
            assigned.append((line_no, bucket, raw))
            continue
        if bucket is None:
            if idx > 0 and current == "introduction":
                current = "methods"
            bucket = current
            if bucket == "methods":
                inherited.append(len(assigned))
        else:
            # 키워드가 명시적으로 앞 단계를 지목하면 그대로 존중한다
            current = bucket
            explicit_results = explicit_results or bucket == "results"
        assigned.append((line_no, bucket, raw))

    # 'IV. GEOMETRY OF SHIFT CURRENT' 처럼 절 제목이 전부 내용어라 results로
    # 분류된 절이 하나도 없으면, 이어받은 중간 절들의 뒤쪽 절반을 results로 본다.
    if not explicit_results and len(inherited) >= 2:
        for pos in inherited[len(inherited) // 2:]:
            line_no, _b, raw = assigned[pos]
            assigned[pos] = (line_no, "results", raw)

    return assigned


def _split_by_headers(text: str) -> tuple[dict[str, str], list[str]]:
    """세 가지 전략을 모두 시도하고 가장 많은 섹션을 채운 결과를 쓴다."""
    lines = text.split("\n")
    candidates: list[tuple[dict[str, str], list[str]]] = []

    struct = _find_structural_headers(lines)
    if struct:
        candidates.append(_assemble(lines, _assign_buckets(struct)))

    for require_numbering in (True, False):
        headers = _find_headers(lines, require_numbering=require_numbering)
        if headers:
            candidates.append(_assemble(lines, headers))

    if not candidates:
        return {}, []
    return max(candidates, key=lambda c: _score(c[0]))


def _cut_references(text: str) -> str:
    """참고문헌 이후를 잘라낸다. 헤더 줄과 '[1] ' 형태의 목록 시작을 모두 본다."""
    cut = len(text)
    floor = int(len(text) * 0.3)   # 앞부분의 우연한 매칭으로 본문을 날리지 않도록

    for m in re.finditer(
        rf"(?m)^[ \t]*(?:[IVXLC0-9]{{1,6}}[\.\)]?[ \t]*)?(?:{_END_PATTERN})\b.{{0,30}}$",
        text,
        re.IGNORECASE,
    ):
        if m.start() > floor:
            cut = m.start()
            break

    # 헤더가 안 잡혀도 참고문헌 목록 자체는 [1] 로 시작하는 경우가 많다
    b = re.search(r"(?m)^[ \t]*\[1\][ \t]+[A-Z]", text[floor:])
    if b:
        cut = min(cut, floor + b.start())

    return text[:cut].rstrip()


def _split_by_position(text: str) -> dict[str, str]:
    """헤더를 못 찾았을 때: 본문을 20/40/25/15 비율로 잘라 네 덩이로 만든다."""
    body = text
    m = re.search(r"(?m)^[ \t]*(?:I\.?[ \t]*)?INTRODUCTION[ \t]*$", text, re.IGNORECASE)
    if m:
        body = text[m.end():]
    body = _cut_references(body)

    n = len(body)
    if n < 400:
        return {}
    cuts = [0, int(n * 0.20), int(n * 0.60), int(n * 0.85), n]
    keys = ["introduction", "methods", "results", "conclusion"]
    return {k: body[cuts[i] : cuts[i + 1]].strip() for i, k in enumerate(keys)}


def parse_sections(paper: Paper, pdf_path: Path | None = None) -> PaperSections:
    """PDF를 읽어 섹션별 원문을 담은 PaperSections를 만든다."""
    sections = PaperSections(arxiv_id=paper.arxiv_id)

    try:
        path = pdf_path or download_pdf(paper)
    except Exception as e:
        sections.warnings.append(f"PDF 다운로드 실패: {e}")
        sections.parse_method = "abstract-only"
        sections.full_text = paper.abstract
        sections.introduction = paper.abstract
        return sections

    try:
        text, warnings = extract_text(path)
    except Exception as e:
        sections.warnings.append(f"PDF 파싱 실패: {e}")
        sections.parse_method = "abstract-only"
        sections.full_text = paper.abstract
        sections.introduction = paper.abstract
        return sections

    sections.full_text = text
    sections.warnings.extend(warnings)

    buckets, labels = _split_by_headers(text)
    filled = sum(1 for v in buckets.values() if len(v.strip()) > 200)

    if filled >= 2:
        sections.parse_method = "regex"
        if labels:
            sections.warnings.append("인식한 섹션 헤더: " + " | ".join(labels[:12]))
    else:
        buckets = _split_by_position(text)
        sections.parse_method = "heuristic" if buckets else "abstract-only"
        if buckets:
            sections.warnings.append(
                "섹션 헤더를 찾지 못해 본문을 위치 기준으로 4등분했습니다."
            )
        else:
            buckets = {"introduction": paper.abstract}
            sections.warnings.append("본문 추출 실패 → 초록만 사용합니다.")

    sections.introduction = buckets.get("introduction", "")
    sections.methods = buckets.get("methods", "")
    # 마지막 절 뒤에 참고문헌이 딸려오는 경우가 흔하다
    sections.results = _cut_references(buckets.get("results", ""))
    sections.conclusion = _cut_references(buckets.get("conclusion", ""))
    return sections
