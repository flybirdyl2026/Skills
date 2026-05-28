---
name: generate-test-cases
description: 根据需求文档（.docx）自动生成测试用例并输出为 Excel 文件。当用户提到生成测试用例、处理需求文档、执行 generate_cases.py 脚本时使用。
---

# 生成测试用例

根据需求文档，调用 `scripts/generate_cases.py` 脚本，自动生成测试用例并输出为 `.xlsx` 文件。

## 使用时机

- 用户需要根据需求文档生成测试用例
- 用户提到运行或执行测试用例生成脚本
- 用户提供了 `.docx` 格式的需求文档并要求产出测试用例

## 前置条件

1. 确认已安装依赖：
   ```
   pip install -r scripts/requirements.txt
   ```
2. **模型自动选择**（无需手动配置）：
   - 优先使用 OpenClaw 本地模型（`http://127.0.0.1:19000/proxy/llm`，模型ID：`modelroute`）
   - 若本地模型不可用，自动回退到 `scripts/config.ini` 中配置的备用 API
   - 若均不可用，脚本会报错退出并提示
3. **备用模型配置**（`scripts/config.ini`，三行填满即可）：

   ```ini
   [openai-chat]
   api_key   = 你的API密钥
   base_url  = API地址（如 https://api.openai.com/v1）
   model     = 模型名（如 gpt-4o）
   ```

   | 厂商 | base_url 示例 | model 示例 |
   |------|---------------|------------|
   | SiliconFlow | `https://api.siliconflow.cn/v1` | `deepseek-ai/DeepSeek-V3.1` |
   | OpenAI | `https://api.openai.com/v1` | `gpt-4o` |
   | Azure OpenAI | `https://xxx.openai.azure.com/v1` | `gpt-4o` |

## 操作步骤

1. 从需求文档文件名中提取项目名称（去掉"需求分析说明书"、"需求文档"等后缀）

2. 拼接输出路径：
   - 输出目录：`output/`
   - 文件命名规则：**`{项目名}测试用例.xlsx`**
   - 示例：`xxx需求分析说明书.docx` → `xxx测试用例.xlsx`

3. 执行脚本：
   ```bash
   python scripts/generate_cases.py --requirements_file "<需求文档路径>" --output_file "output/{项目名}测试用例.xlsx"
   ```

4. 监控脚本输出日志，确认运行状态。

5. 运行完成后，向用户报告输出文件路径。

## 命名规则

| 项目 | 规则 | 示例 |
|------|------|------|
| 输出文件名 | `{项目名}测试用例.xlsx` | `广东省交通基础设施数字化转型管理系统测试用例.xlsx` |
| 项目名提取 | 去掉文档名中的"需求分析说明书"、"需求文档"等后缀 | `xxx需求分析说明书.docx` → 项目名=`xxx` |
| 输出目录 | `output/`（skill目录下） | `output/广东省交通基础设施数字化转型管理系统测试用例.xlsx` |

## 与 req quality-scorer 联动

当 `req quality-scorer` skill 完成需求评估后，可根据评分等级决定是否生成测试用例：

| 评估等级 | 评分 | 联动动作 |
|----------|------|----------|
| A/B | >=75 | 直接生成测试用例 |
| C | 60-74 | 提示用户先修复警告问题，用户确认后可生成 |
| D/E | <60 | 提示用户必须先补充P0阻塞问题，不建议生成 |

联动时额外传递：
- 评估摘要（各维度得分 + 问题清单）
- 重点关注项（评估中发现的边界条件、异常场景缺陷），作为测试用例补充提示

## 注意事项

- 脚本使用6种测试设计方法：等价类划分、边界值分析、判定表驱动、场景法、错误猜测法、状态迁移法。
- 并发生成（默认20线程），大量功能点时耗时约1-3分钟。

## 目录结构

```
generate-test-cases/
├── SKILL.md                 # 本文件
├── scripts/
│   ├── generate_cases.py    # 核心生成脚本
│   ├── config.ini           # 备用模型配置
│   ├── requirements.txt     # Python 依赖
│   └── diag_numbering.py    # 文档编号解析
├── input/                   # 需求文档输入目录
└── output/                  # 测试用例输出目录
```
