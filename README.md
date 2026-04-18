# tg-generator

Auto-generate annotated ESL Teacher Guides (TG) from 51talk student-slide PDFs using an LLM API.

## Setup

```bash
pip install pymupdf openai
```

Copy `.env.example` to `.env` and fill in your API key:

```bash
cp .env.example .env
```

## Usage

Place student-slide PDFs in `tg_input/`, then run:

```bash
python main.py
```

Generated TG drafts are saved to `tg_output/pdf/`.

## Structure

| File | Purpose |
|------|---------|
| `main.py` | Pipeline: PDF → images → LLM → annotated PDF |
| `api_config.py` | API settings, prompts, and JSON schema |
| `prompts/` | Prompt templates per level (A2, B2) |

## Prompts

- `prompts/A2(L4-L6).txt` — A2 level (L4–L6)
- `prompts/B2(L10-12).txt` — B2 level (L10–L12)
