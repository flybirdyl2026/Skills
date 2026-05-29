---
name: api-testing
description: 接口测试技能。从 Apifox 抓取接口定义、设计用例、执行测试、生成 Excel 用例和 Word 报告。支持两段式地址（Apifox 文档站 + 实际 API 服务分离）、按路径/API ID 调用、自动注入 appCode 或 mobile 鉴权头、自动解析请求体模板、自动识别文件上传、按接口分组统计、单接口测试 + 业务流程（多接口串联）测试。触发场景：调用接口、测试接口、抓取 Apifox、API 测试、接口调试、生成接口测试报告、接口测试用例生成、业务流程测试。详细规范见 references/。
---

> ### ⚠️ 发起 API 测试前，请提供以下 4 项信息
>
> | # | 配置项 | 说明 | 示例 |
> |---|--------|------|------|
> | 1 | **API 服务地址** | 实际接口的后端服务 URL（内网/服务器地址） | `http://192.168.x.x:8003/项目名` |
> | 2 | **Apifox 文档站地址** | 公开的 Apifox 项目分享链接 | `https://xxx.apifox.cn/` |
> | 3 | **鉴权信息** | appCode / mobile 手机号 / token，由后端确认 | `test` 或 `15251506890` 或 `无token` |
> | 4 | **项目名称** | 用于报告命名（可选，默认从 URL 提取） | `CRM系统` |
>
> **示例**："帮我测试这个项目：服务地址 `http://xxx:8080/myproject`，Apifox `https://xxx.apifox.cn/`，appCode `xxx`"
>
> **需求文档（可选）**：若 `input/` 目录下放置了 `*.docx` / `*.md` 需求文档，会被用于识别业务流程设计（多接口串联用例）。

# 接口测试技能

## ① 核心概念

### 两段式地址

Apifox 文档站域名（如 `xxx.apifox.cn`）**不是**实际 API 服务地址。调用真实接口需要配置真实后端地址。

```
Apifox 文档站 → https://xxx.apifox.cn     （抓接口用）
实际 API 服务 → https://api.real-server.com （调用用）
```

### workspace 概念

每个测试项目的数据（配置、用例、输入文档、缓存、输出报告）全部在 `D:\test-output\{项目名}\` 下统一管理。

> ⚠️ **参数规则（重要）**：
> - `api_fetch.py`、`generate_cases.py` → 用 `--workspace D:/test-output/{项目名}/`
> - `run_test.py` → 用 `--output D:/test-output/{项目名}/`
>
> 混淆会导致项目目录创建错误。

### 输出目录（可选）

通过 `--output` 参数可将项目输出到指定目录（如 `D:\test-output\{项目名}\`），用于统一管理测试结果。首次运行时会自动从原 workspace 复制 `config.ini` 和 `cases/` 到新目录。

## ② 功能概览

1. **自动抓取** — 给定 Apifox 项目地址，自动获取全部接口（利用 `/llms.txt` 端点）
2. **本地缓存** — 抓取后缓存到 `~/.qclaw/cache/apifox-api/`（按 Apifox URL 哈希分键，跨项目复用）
3. **两段式地址** — 区分 Apifox 文档地址（抓接口用）和实际 API 服务地址（调用用）
4. **通用调用** — 支持任意 HTTP 方法、任意参数组合、Header/Query/Path/Body 全覆盖
5. **智能解析** — 自动识别文件上传、JSON Body、Query 参数
6. **两级测试设计**
   - **单接口用例**：规则生成，正向25% / 逆向40% / 边界20% / 安全15%
   - **业务流程用例**：AI 生成（需需求文档）或规则生成（接口关联分析）
   - 业务流程用例格式：`api_name`填**每个步骤各自调用的接口中文名**（如"用户登录"、"创建订单"、"查询订单"），`case_type`填`业务流程`，`desc`填`StepX: 操作描述`，步骤间用`$变量名`传参（如`$uuid`）
     > ⚠️ **常见错误**：把整条流程的名称填到每个步骤的 `api_name` 里，导致 Excel 报告"接口名称"列所有步骤都一样。脚本会自动用 path 末段修复，无需手动改 JSON。
   - 智能判定：可通过`expect_fn`字段配置`exp_contains:关键字`等判定函数，实现按响应消息精确匹配
7. **AI 增强** — 支持用 LLM 生成业务流程用例，自动适配 Claude Code / OpenAI 兼容环境
8. **自动报告** — 测试完成后自动生成 Excel 测试用例（2 Sheet：单接口/业务流程，各 10 列）和 Word 测试报告（6 章节），无需手动调用

## ③ 目录结构

> ⚠️ 所有路径均相对于本技能目录（`api-testing/`），便于整个目录拷贝迁移。

```
api-testing/                ← 整个目录可拷贝到任意电脑使用
├── SKILL.md                # 本文件，技能入口和工作流
├── references/                   # 规范文档（按需引用，不参与执行）
│   ├── case-design.md          用例设计规范（命名/字段/缺陷等级/预期结果/业务流程）
│   ├── excel-template.md       Excel 模板（10 列 / 样式 / 文件命名）
│   ├── report-template.md      Word 报告模板（6 章节 / 样式 / 文件命名）
│   └── auth-and-troubleshooting.md  鉴权方式 / appCode 路由 / 常见问题
├── scripts/
│   ├── api_fetch.py            抓取接口定义（通用，所有项目复用）
│   ├── generate_cases.py       自动生成测试用例（单接口+业务流程）
│   ├── api_call.py             调用单个 API（通用，支持 --workspace）
│   ├── run_test.py             通用测试执行骨架（从 cases/*.json 读用例）
│   ├── gen_excel.py            Excel 生成器（通用，支持 --workspace）
│   └── gen_report.py           Word 报告生成器（通用，支持 --workspace）
└── D:\test-output\{项目名}\   # ✅ 项目文件夹统一存放位置
    ├── config.ini           该项目的 API 地址、鉴权等配置
    ├── cases/               用例数据 JSON（从 cases/*.json 读用例）
    ├── cache/               抓取的接口定义缓存
    ├── reports/              生成的 Excel 和 Word 报告
    └── test_results/         生成的 JSON 测试结果
└── D:\test-input\{项目名}\input/  # ✅ 需求文档目录（.docx / .md），可放置在此
```

## ④ 配置说明

每个项目的配置在其 `D:\test-output\{项目名}\config.ini` 中：

```ini
[project]
name        = MyProject                              ; 项目名（用于报告命名）
description = MyProject 接口测试

[api]
base_url    = http://localhost:8080                  ; 实际 API 地址（必填）
apifox_url  = https://xxx.apifox.cn                ; Apifox 文档站（抓接口用）

[auth]
auth_type   = mobile                                 ; 鉴权方式：appcode / mobile / token / none
mobile      = 15251506890                            ; mobile 鉴权时填
app_code    =                                        ; appCode 鉴权时填

[options]
timeout     = 30                                     ; 请求超时秒数
```

> 鉴权方式选择和 appCode 路由规则详见 [references/auth-and-troubleshooting.md](references/auth-and-troubleshooting.md)。

## ⑤ 标准工作流

> ### ⚠️ 硬性执行顺序：步骤一二三四五必须按顺序执行，不得跳过任何步骤
> - 步骤三（需求文档）是步骤四（用例设计）的前置条件，未完成步骤三不得进入步骤四
> - 步骤四是步骤五（执行测试）的前置条件，未完成有效用例设计不得进入步骤五
> - 违反此顺序将导致测试结果无效（通过率低、报告无参考价值）

### 步骤一：配置项目

创建项目目录，放入 `config.ini`：

```bash
mkdir -p D:/test-output/{项目名}
# 将上面的 config.ini 模板填入 config.ini，修改 base_url、apifox_url、auth 配置
```

### 步骤二：抓取接口

```bash
python scripts/api_fetch.py fetch "https://xxx.apifox.cn" --workspace D:/test-output/{项目名}/
```
> ⚠️ 注意：此处用 `--workspace`，不是 `--output`

抓取结果保存到 `D:/test-output/{项目名}/cache/`（按 Apifox URL 哈希分键）。

### 步骤三：阅读需求文档，设计业务流程用例

> ### ⚠️ 强制要求：此步骤不得跳过
> **必须**在执行步骤四之前完成需求文档阅读和分析。跳过此步骤将导致：
> - 业务流程用例不符合业务逻辑
> - 单接口用例缺少必要参数（如GET详情uuid为空）
> - 期望结果设计错误（安全测试用错expect_fn）
> - 测试通过率极低，报告无参考价值
>
> **需求文档会被 `generate_cases.py` 自动读取**，用于解析业务流程和生成符合业务逻辑的用例参数。

**检查需求文档：**
1. 先检查 `D:\test-input\{项目名}\input\` 下是否有需求文档（`.docx` / `.md`）
2. 如果是 `.docx` 格式，先用 `python scripts/docx_to_md.py "<文档路径>"` 转换为 `.md`
3. 读取并分析需求文档中的业务流程章节

**从需求文档中提取：**
- 业务模块划分（哪些模块需要测试）
- 核心业务流程（创建→审批→执行→关闭的链路）
- 每个接口的必填字段（设计正向测试参数）
- 业务规则和约束（设计逆向/边界测试）

**业务流程用例设计规范（必须遵守）：**
| 用例类型 | 期望函数 | 参数要求 | 示例 |
|---------|---------|---------|------|
| 正向测试 | 不填（默认exp_ok） | 完整必填参数 | 正常参数查询，期望成功 |
| 逆向测试 | `exp_biz_fail` | 缺参/空参 | 缺少必填uuid，期望被拦截 |
| 边界测试 | 不填（默认exp_ok） | 超长/极端值 | pageNum超长 |
| 安全测试 | `exp_biz_fail` | SQL注入/XSS | 期望攻击被拦截 |

> 详细规范见 [references/case-design.md](references/case-design.md)。

### 步骤四：自动生成测试用例

```bash
# 自动生成测试用例（单接口+业务流程，AI 自动检测）
python scripts/generate_cases.py --workspace D:/test-output/{项目名}/

# 强制使用 AI 生成业务流程
python scripts/generate_cases.py --workspace D:/test-output/{项目名}/ --use-ai

# 禁用 AI，仅使用规则生成
python scripts/generate_cases.py --workspace D:/test-output/{项目名}/ --no-ai
```

**生成逻辑：**
- **单接口用例**：规则生成（正向25%/逆向40%/边界20%/安全15%）
- **业务流程用例**：
  1. 有需求文档 → AI 生成优先，规则兜底
  2. 无需求文档 → 规则检测接口关联

脚本会自动：
- 查找 `D:/test-input/{项目名}/input/` 目录下的需求文档（.md 格式）
- 从需求文档中解析业务流程，生成**业务流程用例**
- 分析接口定义，生成**单接口用例**
- 根据需求文档中的业务字段填充正向测试参数

> **AI 配置**：脚本自动检测 Claude Code / OpenAI 兼容环境，无需额外配置。

### 步骤五：执行测试（自动生成报告）

```bash
# 执行测试并自动生成 Excel + Word 报告
python scripts/run_test.py --output D:/test-output/{项目名}/

# 测试中断后可从断点继续
python scripts/run_test.py --output D:/test-output/{项目名}/ --resume

# 放弃进度，重新开始
python scripts/run_test.py --output D:/test-output/{项目名}/ --discard
```

> ⚠️ **重要**：单接口用例 + 业务流程用例必须**一次跑完**，不得分开跑两次。分开跑会导致流程数据断裂、报告不一致。

自动完成：执行测试 → 生成 JSON → 生成 Excel → 生成 Word，三件套时间戳一致。

**断点续跑**：测试中断后使用 `--resume` 可从断点继续，已完成的用例会被跳过。

---

## ⑥ 执行测试（自动生成报告）

```bash
# 完整流程示例
python scripts/api_fetch.py fetch "https://xxx.apifox.cn" --workspace D:/test-output/{项目名}/
python scripts/generate_cases.py --workspace D:/test-output/{项目名}/
python scripts/run_test.py --output D:/test-output/{项目名}/
```

## ⑦ 规范文档索引

| 文档 | 触发场景 |
|------|---------|
| [references/case-design.md](references/case-design.md) | 写用例时（命名、字段、缺陷等级、预期结果、业务流程模式） |
| [references/excel-template.md](references/excel-template.md) | 校对 Excel 格式 / 理解文件结构时（10 列定义、样式、命名格式） |
| [references/report-template.md](references/report-template.md) | 校对 Word 报告时（6 章节结构、问题分类、修复建议聚合） |
| [references/auth-and-troubleshooting.md](references/auth-and-troubleshooting.md) | 配 `[auth]` 段、调通鉴权、排查响应异常时 |

## ⑧ 规则文件说明

规则文件位于 `rules/` 目录，**每个项目可独立配置**：

### 规则文件位置（优先级从高到低）

| 位置 | 说明 |
|------|------|
| `D:/test-output/{项目名}/rules/` | 项目专用规则（优先加载） |
| `api-testing/rules/` | 通用默认规则 |

### 规则文件列表

| 文件 | 说明 | 关键配置项 |
|------|------|-----------|
| `api_classification.json` | 接口分类规则 | path关键词、summary关键词、method、system_fields |
| `flow_patterns.json` | 业务流程模式 | steps、role、action、extract_field |
| `case_templates.json` | 用例生成模板 | positive/negative/boundary/security比例、biz_key_fields |

### 新项目配置示例

```bash
# 为新项目创建规则目录
mkdir -p D:/test-output/{新项目名}/rules/

# 复制通用规则作为起点
cp api-testing/rules/*.json D:/test-output/{新项目名}/rules/

# 根据项目业务修改规则...
```

### 规则文件说明

**api_classification.json** - 定义接口类型识别规则：
```json
{
  "detail_api": {
    "keywords": {
      "path": ["/getById", "/detail"],  // URL路径关键词
      "summary": ["详情", "明细"]         // 接口描述关键词
    },
    "method": ["GET"],                     // HTTP方法
    "id_params": ["id", "uuid"]           // 详情接口的ID参数名
  }
}
```

**flow_patterns.json** - 定义业务流程模板：
```json
{
  "patterns": [{
    "name": "列表详情流程",
    "steps": [
      {"role": "list_api", "action": "查询列表", "extract_field": "uuid"},
      {"role": "detail_api", "action": "查看详情", "depends_on": "list_api"}
    ]
  }]
}
```

**case_templates.json** - 定义用例生成比例和测试数据：
```json
{
  "templates": {
    "positive": {"ratio": 0.25},          // 正向用例占比
    "negative": {"ratio": 0.40},         // 逆向用例占比
    "boundary": {"ratio": 0.20},          // 边界用例占比
    "security": {"ratio": 0.15}           // 安全用例占比
  }
}
```
