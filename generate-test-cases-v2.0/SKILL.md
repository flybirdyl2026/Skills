---
name: generate-test-cases
description: 根据需求文档（.docx）自动生成测试用例并输出为 Excel 文件。
keywords: [测试用例, 需求文档, Excel生成]
author: yangl
version: 2.0
date: 2026-06-01
---

> **使用前提**：已安装 Python 依赖 `pip install -r ../requirements.txt`

# 一、功能简介

根据需求文档（.docx），自动生成测试用例并输出为 Excel 文件。

# 二、目录结构

```
generate-test-cases/
├── SKILL.md
├── references/
│   └── case-format.md
├── scripts/
│   ├── core/
│   │   ├── generate_cases.py
│   │   └── prompt.py
│   └── tools/
│       └── doc_diag.py
```

# 三、输入输出路径

| 类型 | 路径 |
|------|------|
| 输入 | `D:\test-input\{项目名}\input\` |
| 输出 | `D:\test-output\{项目名}\output\` |

# 四、执行命令

```bash
cd scripts/core
python generate_cases.py --project "项目名称"
```

# 五、参数说明

| 参数 | 说明 |
|------|------|
| `--project` | 项目名称 |
| `--requirements_file` | 需求文档路径；不传则自动从 `input/` 取最新 .docx |
| `--output_file` | 输出 .xlsx 路径 |
| `--summary` | 可接入 req-quality-scorer 评估摘要，在"备注"列标注 P0/P1 问题 |
| `--force` | 强制生成（即使评估等级为 D/E） |

# 六、模型配置

## 6.1 优先级

1. OpenClaw 本地模型（`http://127.0.0.1:19000/proxy/llm`）
2. llm-config 配置（`../llm-config/llm_config.ini`）

## 6.2 llm_config.ini

```ini
[llm]
api_key = your_api_key_here
base_url = https://api.example.com/v1
model = your-model-name
```

# 七、输出格式

| 列 | 字段 |
|----|------|
| A | 需求编号 |
| B | 用例编号 |
| C | 用例等级 |
| D | 用例标题 |
| E | 预置条件 |
| F | 操作步骤 |
| G | 预期结果 |
| H | 执行结果 |
| I | 备注 |

# 八、更新日志

| 版本 | 日期 | 说明 |
|------|------|------|
| 2.0 | 2026-06-01 | 修复需求编号提取逻辑 |
| 1.0 | 2026-05-28 | 初始版本 |
