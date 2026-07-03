# tg-generator

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Python](https://img.shields.io/badge/Python-3.x-blue.svg)](https://www.python.org/)

[English](README.md) | 中文

## 概览

51Talk 教师指南生成器，用 LLM 从学生课件 PDF 自动生成带注释的 ESL Teacher Guide。

## 主要能力

- 读取 51Talk student-slide PDF。
- 生成教师授课说明和注释。
- 面向 TG 文档自动化生产。

## 使用方式

按下方脚本说明准备 PDF、API 配置和输出目录后运行。

## 状态

该仓库仍按当前 README 的说明维护或使用。

## 注意事项

保留英文原说明中的命令和输入输出约定。

## 命令与配置参考

以下代码块从主 README 保留；命令、路径和配置键不翻译，复制时请以实际环境为准。

```bash
pip install pymupdf openai
```

```bash
cp .env.example .env
```

```bash
python main.py
```

## 详细技术说明

主 README 保留了原始技术细节、历史说明、完整命令和文件结构。本文件作为中文版本维护核心说明；需要逐项核对命令时，请参照主 README 的代码块和路径。
