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

## 注意事项

保留英文原说明中的命令和输入输出约定。

## 命令与配置参考

以下命令、路径和配置键保持原样，复制时请以实际环境为准。

```bash
pip install pymupdf openai
```

```bash
cp .env.example .env
```

```bash
python main.py
```
