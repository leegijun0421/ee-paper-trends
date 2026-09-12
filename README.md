# EE Paper Trends

**What is electrical engineering research talking about this week, and can a first-year student read any of it?**

A Streamlit app that pulls recent arXiv papers in EE-adjacent categories, extracts the topics that keep recurring, and then explains any single paper at the level of a **first-year undergraduate** — section summaries, why the paper matters, and the six to eight terms you need to know before you can read it.

> Built by a first-year EE student at Korea University, for first-year EE students. I am the primary user; every feature exists because an earlier version got in my way.

한국어 문서는 [README.ko.md](README.ko.md)에 있습니다.

---

## Why it exists

Reading research as a first-year is a filtering problem before it is a comprehension problem. The papers that matter are findable; the cost of *deciding* whether one is relevant is nearly the cost of reading it, and abstracts are written to impress rather than to be triaged.

Two questions, then, and the app answers them in that order:

1. **What is the field doing?** — TF-IDF over recent abstracts produces candidate keywords, and Claude merges them into actual topics. Raw TF-IDF gives you `design` and `quantum`; the normalization step is what turns those into topics a person can act on.
2. **Can I read this specific paper?** — download the PDF, split it into Introduction / Methods / Results / Conclusion, summarize each in 3–5 sentences, state why the paper matters and how it differs from prior work, and define its jargon without equations.

## Features

| | |
|---|---|
| **Collection** | arXiv API, last N days, title / abstract / authors / date / PDF link |
| **Categories** | `cond-mat.mes-hall`, `eess.SY`, `physics.app-ph`, `cs.AR` (selectable) |
| **Trends** | TF-IDF candidates → Claude topic merge → top-10 chart, word cloud, table |
| **Section summaries** | PDF split into Intro / Methods / Results / Conclusion, 3–5 sentences each |
| **Why it matters** | One paragraph on significance, one on how it differs from prior work |
| **Glossary** | 6–8 technical terms explained at first-year level — no equations, everyday analogies |

## Architecture

```
arXiv API ──▶ collector.py      query assembly, collection, 30-min search cache
                   │
                   ├──▶ trends.py      TF-IDF candidates ──▶ Claude topic normalization
                   │
                   └──▶ pdf_parser.py  PDF download ──▶ two-column handling ──▶ section split
                              │
                              ▼
                         llm.py         Claude structured output + response cache
                              │
                              ▼
                      Streamlit UI      trend view · paper list · paper detail
```

```
.
├── app.py                # Streamlit entry point (search → trends → list/detail routing)
├── config.py             # categories, model, cache paths
├── core/
│   ├── models.py         # Paper / PaperSections / PaperAnalysis data structures
│   ├── collector.py      # arXiv query assembly, collection, search cache
│   ├── pdf_parser.py     # PDF download → two-column handling → section split
│   ├── trends.py         # TF-IDF candidate extraction + LLM normalization
│   └── llm.py            # Claude calls (structured output) + response cache
├── ui/
│   ├── sidebar.py        # search parameters
│   ├── trend_view.py     # top-10 chart / word cloud / table
│   └── paper_view.py     # paper cards + detail view
└── tests/                # each module runnable standalone
```

`core/` (logic) and `ui/` (presentation) are separate, so every module runs standalone without Streamlit:

```bash
python tests/test_collector.py    # arXiv collection
python tests/test_pdf_parser.py   # PDF parsing + section split
python tests/test_trends.py       # trend extraction
python tests/test_llm.py          # prompts / schema / cache (real call if a key is present)
```

## Design decisions

**Structured output over free-form summaries.** Claude is asked for a fixed set of fields rather than "summarize this paper." Comparable output across 30 papers is what makes a stack of them scannable, and giving the model an explicit place to say *not stated in the source* is what made invented method descriptions mostly disappear.

**Cache the LLM response, not just the PDF.** Streamlit re-runs the whole script on every widget interaction. Without `cache/llm/`, expanding a paper card twice bills you twice. This is the single most important thing I learned about building a *product* on an LLM API rather than a script.

**TF-IDF first, model second.** Keyword extraction is a solved statistical problem and costs nothing; topic merging is a judgment problem and costs a call. One API call per search, one per paper analyzed — the split is deliberate.

**Degrade without a key.** Collection and the TF-IDF chart work with no API key at all. You lose topic merging and the explanations, not the app.

**Three-tier section splitting.** arXiv typesetting is inconsistent, so section detection falls back numbering → keyword → position, and the detail view reports which path it took (`regex` / `heuristic` / `abstract-only`) instead of hiding it. A parser that silently mislabels is worse than one that tells you it guessed.

## Quick start

Python 3.10+.

```bash
git clone https://github.com/leegijun0421/ee-paper-trends.git
cd ee-paper-trends
pip install -r requirements.txt

cp .env.example .env     # then add your Anthropic API key
streamlit run app.py     # opens http://localhost:8501
```

Get a key at [console.anthropic.com](https://console.anthropic.com/settings/keys). `.env` is git-ignored; never put a key in the source.

**How to use it**: set keywords (optional), period, categories and a paper cap in the sidebar → **collect** → read the top-10 trend chart → open a paper card and hit **detail** to download the PDF and generate the summary and glossary. Keywords are comma-separated (`VLSI, semiconductor device`), and multi-word keywords are automatically quoted into phrase searches.

## Cost

One API call per search (trend normalization), one per paper analyzed (sections + significance + glossary in a single call). Responses are cached in `cache/llm/`, so reopening a paper costs nothing. To spend less, change the model in `.env`:

```dotenv
CLAUDE_MODEL=claude-sonnet-5
CLAUDE_EFFORT=low
```

## Known limitations

- **Section splitting** — six of six measured papers were structured correctly, but a section heading mangled during extraction can misfile a conclusion under Results. The detail view shows which split path was used.
- **Scanned PDFs** — no text layer, no parse; the app falls back to abstract-only analysis.
- **arXiv rate limits** — repeated queries return 429. Identical searches are cached for 30 minutes.
- **Word cloud** — the default font has no Hangul glyphs, so labels are romanized.
- **Category display** — arXiv papers carry several categories, and the primary one may sit outside your selection (`math.OC` primary with `eess.SY` secondary, say).

## Roadmap

- [ ] Hosted deployment so other students can use it without cloning
- [ ] Saved reading lists and note export
- [ ] Sources beyond arXiv (IEEE Xplore metadata)
- [ ] Prerequisite graph across a paper set — read them in dependency order

## Built with Claude

Developed with **Claude Code**; runs on the **Claude API**. Two things I would tell anyone starting a similar project: ask for a schema rather than a summary, and iterate on the prompt against the papers you actually need to read this week — a prompt that scores well on a toy example and badly on your real backlog is a prompt you will keep rewriting.

## License

MIT — see [LICENSE](LICENSE).
