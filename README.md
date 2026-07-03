# tg-generator

<!-- bilingual-readme:start -->

## 双语说明 / Bilingual Documentation

> 本节提供整篇 README 的中英双语维护说明；下方保留原始详细说明、命令、路径和配置示例。
> This section provides bilingual maintenance notes for the full README; the original detailed notes, commands, paths, and configuration examples are preserved below.

### 中文

**概览**：51Talk 教师指南生成器，用 LLM 从学生课件 PDF 自动生成带注释的 ESL Teacher Guide。

**主要能力**：
- 读取 51Talk student-slide PDF。
- 生成教师授课说明和注释。
- 面向 TG 文档自动化生产。

**使用方式**：按下方脚本说明准备 PDF、API 配置和输出目录后运行。

**状态**：该仓库仍按当前 README 的说明维护或使用。

**注意事项**：保留英文原说明中的命令和输入输出约定。

### English

**Overview**: 51Talk Teacher Guide generator that uses an LLM to create annotated ESL TGs from student-slide PDFs.

**Key capabilities**:
- Reads 51Talk student-slide PDFs.
- Generates teacher-facing instructions and annotations.
- Targets automated TG document production.

**Usage**: Prepare PDFs, API configuration, and output paths as described below, then run the scripts.

**Status**: This repository is maintained or used according to the current README notes.

**Notes**: The original command and input/output conventions are retained below.

<!-- bilingual-readme:end -->

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