# 规则配置目录

本目录存放接口测试用例生成的通用规则配置，与具体项目无关，可复用到任何项目。

## 文件说明

| 文件 | 用途 |
|------|------|
| `api_classification.json` | 接口分类规则 - 识别接口类型（列表、详情、统计等） |
| `flow_patterns.json` | 业务流程模式 - 定义通用业务流程模板 |
| `case_templates.json` | 用例生成模板 - 定义各类测试用例的生成规则 |

## api_classification.json

定义如何根据接口的 path 和 summary 识别接口类型：

```json
{
  "classifications": {
    "list_api": {
      "keywords": {
        "path": ["/page", "/list"],
        "summary": ["列表", "分页"]
      },
      "method": ["GET"]
    }
  }
}
```

## flow_patterns.json

定义通用业务流程模式：

```json
{
  "patterns": [
    {
      "name": "列表详情流程",
      "steps": [
        {"role": "list", "action": "查询数据列表"},
        {"role": "detail", "action": "根据ID查询详情"}
      ]
    }
  ]
}
```

## case_templates.json

定义单接口用例的生成模板：

```json
{
  "templates": {
    "positive": {
      "expect_fn": "exp_ok",
      "ratio": 0.25
    },
    "negative": {
      "expect_fn": "exp_biz_fail",
      "ratio": 0.40
    }
  }
}
```

## 扩展规则

如需针对特定项目添加专属规则，可在项目目录下创建 `rules/` 子目录覆盖默认规则。

目录查找顺序：
1. `项目目录/rules/` - 项目专属规则
2. `技能包目录/rules/` - 默认通用规则
