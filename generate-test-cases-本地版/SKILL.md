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
   pip install -r requirements.txt
   ```
2. 确认 `scripts/config.ini` 中已填入有效的 API Key：
   ```ini
   [openai-chat]
   api_key = <你的 API Key>
   ```
   若未配置，脚本会自动创建模板并退出，需用户手动填入 Key 后重新运行。

## 操作步骤

1. 向用户确认以下两个路径（若未提供则使用默认路径）：
   - 需求文档路径：默认放在 `input/` 目录下（如 `input/需求文档.docx`）
   - 输出测试用例路径：默认输出到 `output/` 目录下（如 `output/测试用例.xlsx`）

2. 执行脚本：
   ```bash
   python scripts/generate_cases.py --requirements_file \"<需求文档路径>\" --output_file \"<输出路径>\"
   ```

3. 监控脚本输出日志，确认运行状态。

4. 运行完成后，向用户报告输出文件路径。

## 注意事项

- 脚本使用 SiliconFlow API（模型：`deepseek-ai/DeepSeek-V3.1`），需要网络连接。
- 需求文档内容通过正则 `业务规则(.*?)原型界面` 提取功能点，文档结构需包含