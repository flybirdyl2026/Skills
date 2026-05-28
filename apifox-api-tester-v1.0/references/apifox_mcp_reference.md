# Apifox REST API 参考

> **重要说明（2026-04 验证）**：
> - `apifox-mcp@1.0.0` npm 包只有 224 字节，是一个空占位包，无可执行文件，`npx -y apifox-mcp@latest` 必然失败。
> - `apifox-mcp-server@latest` 需要启动时指定 `--project=<id>`，且不提供 `get_project_list` 等工具。
> - **正确做法**：直接调用 Apifox Open REST API（见下文）。

---

## Apifox Open REST API

### Base URL

```
https://api.apifox.com
```

### 鉴权方式

所有请求必须携带：

```
Authorization: Bearer <APIFOX_ACCESS_TOKEN>
X-Apifox-Api-Version: 2024-01-20
Content-Type: application/json
```

Access Token 存储位置：`~/.workbuddy/mcp.json` → `mcpServers.apifox.env.APIFOX_ACCESS_TOKEN`

---

## 核心接口

### 导出项目全量接口（OpenAPI 3.0）

**最重要的接口，一次性获取所有路径。**

```
POST /api/v1/projects/{projectId}/export-openapi
```

Request Body:
```json
{
  "version": "3.0",
  "excludeExtension": true
}
```

Python 示例：
```python
import urllib.request, json

TOKEN = "afxp_xxxxx"
PROJECT_ID = "4261089"

url = f"https://api.apifox.com/api/v1/projects/{PROJECT_ID}/export-openapi"
data = json.dumps({"version": "3.0", "excludeExtension": True}).encode("utf-8")
req = urllib.request.Request(
    url, data=data, method="POST",
    headers={
        "Authorization": f"Bearer {TOKEN}",
        "X-Apifox-Api-Version": "2024-01-20",
        "Content-Type": "application/json"
    }
)
resp = urllib.request.urlopen(req, timeout=30)
spec = json.loads(resp.read().decode("utf-8"))
# spec 是标准 OpenAPI 3.0 对象，包含 spec["paths"]
```

返回值：标准 OpenAPI 3.0 JSON，包含：
- `spec["info"]` — 项目信息
- `spec["tags"]` — 接口分组标签
- `spec["paths"]` — 所有接口路径（key: path, value: {method: operation}）
- `spec["components"]["schemas"]` — 数据模型（用于 $ref 解析）

---

## OpenAPI 3.0 接口结构

```json
{
  "paths": {
    "/blancedata": {
      "post": {
        "summary": "对账数据接口",
        "tags": [],
        "parameters": [
          { "in": "header", "name": "token", "example": "Jsrg@def789" }
        ],
        "requestBody": {
          "content": {
            "application/json": {
              "schema": { "$ref": "#/components/schemas/BlanceDataVo" },
              "example": { "processTime": "", "laneId": 0 }
            }
          }
        }
      }
    }
  },
  "components": {
    "schemas": {
      "BlanceDataVo": {
        "type": "object",
        "properties": {
          "processTime": { "type": "string", "example": "" },
          "laneId":      { "type": "integer", "example": 0 },
          "stationId":   { "type": "string", "example": "" },
          "flux":        { "type": "integer", "example": 0 },
          "exitMoney":   { "type": "integer", "example": 0 }
        }
      }
    }
  }
}
```

### $ref 解析规则

当 `requestBody.content.application/json.schema` 中含有 `$ref` 时，需递归解析：

```python
def resolve_ref(ref, schemas):
    # ref 格式: "#/components/schemas/XxxVo"
    parts = ref.lstrip("#/").split("/")
    # parts = ["components", "schemas", "XxxVo"]
    if len(parts) == 3 and parts[0] == "components" and parts[1] == "schemas":
        return schemas.get(parts[2], {})
    return {}
```

解析顺序：先取 `example`，再 fallback 到 schema `properties` 逐字段提取。

---

## interfaces.json 格式（run_tests.py 期望格式）

```json
[
  {
    "name": "对账数据接口",
    "method": "POST",
    "path": "/blancedata",
    "headers": { "token": "Jsrg@def789" },
    "query_params": {},
    "body": {
      "processTime": "",
      "laneId": 0,
      "stationId": "",
      "flux": 0,
      "exitMoney": 0
    },
    "body_type": "json"
  }
]
```

字段说明：
- `headers`：从 OpenAPI `parameters[in=header]` 提取，key=name, value=example
- `query_params`：从 OpenAPI `parameters[in=query]` 提取
- `body`：优先取 `requestBody.content.application/json.example`，否则递归展开 schema properties
- `body_type`：`json`（默认）或 `form`（application/x-www-form-urlencoded）

---

## 环境变量文件格式（env.json）

用于替换接口 path/body/headers 中的 `{{variable}}` 占位符：

```json
{
  "base_url": "https://api.example.com",
  "user_id": "12345",
  "api_key": "abc-xyz"
}
```

---

## 如何获取项目 ID

1. 打开 Apifox，进入目标项目
2. 左侧侧边栏 → 项目设置 → 基本设置
3. 页面上即显示项目 ID（纯数字，如 `4261089`）
