---
name: apifox-api-tester
description: >
  This skill automates API testing by fetching all interface definitions from an
  Apifox project via the Apifox Open REST API, executing each interface using Python's
  requests library, and generating a complete test report with status codes, response
  times, and response bodies. Use this skill when the user asks to: test all APIs in an
  Apifox project, run batch API requests from Apifox, check interface health,
  execute Apifox接口批量测试, 接口自动化测试, 跑接口, 测试所有接口, API批量请求,
  接口联调, 接口健康检查, apifox接口执行, 获取apifox项目接口并执行,
  运行对账数据接口, 运行接口测试, 跑测试, 测试接口.
---

# Apifox API Tester Skill

## Purpose

Fetch all API interface definitions from an Apifox project via the **Apifox Open REST API**
(not apifox-mcp tools, which may be unavailable), execute each interface using Python `requests`,
and produce a comprehensive test report with HTML visualization.

## Prerequisites

- Python with `requests` installed (`pip install requests`).
- An **Apifox Personal Access Token** (configured in `~/.workbuddy/mcp.json` under
  `env.APIFOX_ACCESS_TOKEN`, or ask the user to provide it).
- The user must provide a **project ID** and a **base URL** to run against.

> ⚠️ **DO NOT rely on apifox-mcp MCP tools** (`get_project_list`, `export_openapi_data`, etc.)
> in this skill. The configured npm package `apifox-mcp@latest` is a stub (224 bytes) with no
> executable, and `apifox-mcp-server@latest` requires a pre-configured project ID and does not
> expose these tools at runtime. Always use the **Apifox Open REST API** directly instead.

## Workflow

### Phase 0 — Gather Required Info

Before starting, collect (or infer from context):

| Item | How to get |
|---|---|
| **Access Token** | Read from `~/.workbuddy/mcp.json` → `mcpServers.apifox.env.APIFOX_ACCESS_TOKEN` |
| **Project ID** | Read from `~/.workbuddy/mcp.json` → `mcpServers.apifox.args` (e.g. `--project-id=4261089`) |
| **Base URL** | **Auto-fetch from Apifox environment config** (see below) |
| **Filter keyword** | Optional. If user mentions a specific module (e.g. "对账"), filter by name |

If the access token is not found in mcp.json, ask the user to provide it.

#### Base URL Auto-Resolution (MUST follow this order)

**Step 1**: Call the Apifox environments API to fetch all configured environments:

```python
import urllib.request, json

TOKEN = "<APIFOX_ACCESS_TOKEN>"
PROJECT_ID = "<project_id>"

url = f"https://api.apifox.com/api/v1/projects/{PROJECT_ID}/environments"
req = urllib.request.Request(
    url, method="GET",
    headers={
        "Authorization": f"Bearer {TOKEN}",
        "X-Apifox-Api-Version": "2024-01-20",
    }
)
resp = urllib.request.urlopen(req, timeout=15)
envs = json.loads(resp.read().decode("utf-8")).get("data", [])
```

**Step 2**: Select Base URL by priority:

```python
def select_base_url(envs):
    # Only consider type="normal" envs with a non-empty baseUrl
    normal = [e for e in envs if e.get("type") == "normal" and e.get("baseUrl", "").strip()]

    # Priority keywords (case-insensitive match on env name)
    TEST_KEYWORDS  = ["测试", "test", "staging", "uat", "dev", "开发", "联调"]
    PROD_KEYWORDS  = ["正式", "生产", "prod", "production", "线上", "release"]

    test_envs = [e for e in normal if any(k in e["name"] for k in TEST_KEYWORDS)]
    prod_envs = [e for e in normal if any(k in e["name"] for k in PROD_KEYWORDS)]

    if test_envs:
        return test_envs[0]["baseUrl"].rstrip("/"), test_envs[0]["name"]
    if prod_envs:
        return prod_envs[0]["baseUrl"].rstrip("/"), prod_envs[0]["name"]
    if normal:
        return normal[0]["baseUrl"].rstrip("/"), normal[0]["name"]
    return None, None

base_url, env_name = select_base_url(envs)
```

**Step 3**: Fallback — if no valid Base URL is found from Apifox environments, **then** ask the user to provide one manually.

**Step 4**: Inform the user which environment is being used (e.g. "已自动选择测试环境：http://192.168.200.39"), then proceed **without asking for confirmation**.

### Phase 1 — Export Interfaces via Apifox REST API

Call the Apifox Open REST API directly using Python — **not** via npx or MCP tools.

```python
import urllib.request, json

TOKEN = "<APIFOX_ACCESS_TOKEN>"
PROJECT_ID = "<project_id>"

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
```

Save the raw response to `apifox_raw.json` in the workspace.

Print all paths and summaries so the user can confirm which interfaces to test.

### Phase 2 — Convert OpenAPI → interfaces.json

Use `scripts/convert_openapi.py` to convert the saved spec:

```bash
python scripts/convert_openapi.py --input apifox_raw.json --output interfaces.json
```

If the user wants to test only a subset (e.g. "对账数据接口"), also generate a filtered file:

```bash
python scripts/convert_openapi.py --input apifox_raw.json --output interfaces_filtered.json --filter "对账"
```

The script resolves `$ref` schema references to populate `body` examples automatically.

### Phase 3 — Execute Tests

Run the test script with `PYTHONUTF8=1` (critical on Windows to avoid GBK encoding errors):

**Windows (PowerShell):**
```powershell
$env:PYTHONUTF8=1
python scripts/run_tests.py `
  --interfaces interfaces_filtered.json `
  --base-url <BASE_URL> `
  --output api_test_report.json `
  --timeout 15
```

**Linux / macOS:**
```bash
PYTHONUTF8=1 python scripts/run_tests.py \
  --interfaces interfaces_filtered.json \
  --base-url <BASE_URL> \
  --output api_test_report.json \
  --timeout 15
```

> ⚠️ **Windows encoding**: Always set `PYTHONUTF8=1` (or `$env:PYTHONUTF8=1` in PowerShell)
> before running `run_tests.py`. Without it, printing Unicode emoji (✅ ❌ ⚠️) to the Windows
> console will raise `UnicodeEncodeError: 'gbk' codec can't encode character`.

### Phase 4 — Generate HTML Report & Present Results

After tests complete, generate a self-contained HTML report:

```python
# Build HTML from api_test_report.json and open it
# See scripts/generate_html_report.py or inline the HTML generation
```

Then start a local HTTP server and preview:

```powershell
Start-Process python -ArgumentList "-m http.server 7789 --directory <workspace>" -NoNewWindow
# Then preview http://localhost:7789/api_test_report.html
```

The HTML report must include:
- Summary cards: total / success / HTTP errors / connection errors / pass rate
- Per-interface table: method, name, URL, status badge, HTTP code, response time
- Request detail block (headers + body sent)
- Error message block for failed interfaces
- Fault diagnosis section for connection errors

### Phase 5 — Diagnose Failures

| Failure Type | Likely Cause | Suggestion |
|---|---|---|
| `ConnectTimeoutError` | Current machine not on same LAN as server | Run from a machine in the same intranet, or use VPN |
| `ConnectionRefusedError` | Service not running on target host/port | Check if the server process is up |
| HTTP 401 / 403 | Auth token missing or expired | Verify `token` header value in interfaces.json |
| HTTP 404 | Wrong base URL or path | Confirm base URL and path prefix |
| HTTP 5xx | Server-side error | Check application logs on the server |

## Key Files

| File | Purpose |
|---|---|
| `scripts/run_tests.py` | Main test runner — executes all interfaces via requests |
| `scripts/convert_openapi.py` | Converts OpenAPI 3.0 spec → interfaces.json (with $ref resolution + filter) |
| `scripts/apifox_to_interfaces.py` | Converts Apifox native JSON to interfaces.json format (legacy fallback) |
| `references/apifox_mcp_reference.md` | Apifox REST API endpoints and data formats reference |

## Output Format

`api_test_report.json` structure:
```json
{
  "summary": {
    "start_time": "2026-04-24T09:00:00",
    "end_time":   "2026-04-24T09:00:10",
    "total_interfaces": 20,
    "success": 18,
    "http_error": 1,
    "connection_error": 1,
    "pass_rate": "90.0%"
  },
  "results": [
    {
      "name": "对账数据接口",
      "method": "POST",
      "url": "http://192.168.1.100:8080/blancedata",
      "status": "error",
      "http_status": null,
      "response_time_ms": 15000.0,
      "response_body": null,
      "error": "Connection to 192.168.1.100 timed out."
    }
  ]
}
```

## Accumulated Lessons (踩坑经验)

- **apifox-mcp npm package**: `apifox-mcp@1.0.0` is a 224-byte stub with no executable binary.
  `npx -y apifox-mcp@latest` always fails with "could not determine executable to run".
  Use the Apifox Open REST API directly instead.
- **apifox-mcp-server**: Requires `--project=<id>` arg at startup and does NOT expose
  `get_project_list` / `export_openapi_data` tools at runtime. Cannot be used for dynamic
  project listing.
- **Apifox export endpoint**: `POST https://api.apifox.com/api/v1/projects/{projectId}/export-openapi`
  with body `{"version":"3.0","excludeExtension":true}` and headers
  `Authorization: Bearer <token>` + `X-Apifox-Api-Version: 2024-01-20`. Returns full OpenAPI 3.0 JSON.
- **Windows GBK encoding**: `run_tests.py` uses emoji (✅ ❌) in print statements.
  On Windows, stdout defaults to GBK, causing `UnicodeEncodeError`. Fix: always set
  `$env:PYTHONUTF8=1` before running, or add `sys.stdout.reconfigure(encoding='utf-8')` at
  the top of the script.
- **$ref resolution in OpenAPI**: Apifox-exported specs use `$ref: "#/components/schemas/XxxVo"`
  for request bodies. Must resolve refs recursively to extract field-level examples for body.
- **ConnectTimeoutError on 192.168.x.x**: Internal IP addresses are only reachable from the
  same LAN. When WorkBuddy is running on the user's laptop, it may not be on the same subnet
  as the test server. Report the error clearly and instruct the user to run from an intranet host.
- **Base URL 自动获取**: 通过 `GET https://api.apifox.com/api/v1/projects/{id}/environments` 获取环境列表；
  优先选 type=normal 且名称含"测试/test/staging"的环境，其次选"正式/prod"，再次选第一个 normal 环境；
  baseUrl 末尾要 rstrip("/") 避免路径重复斜杠；找不到时才让用户手动输入。
- **Project ID 自动获取**: 从 `~/.workbuddy/mcp.json` 的 `mcpServers.apifox.args` 中解析
  `--project-id=XXXX` 获得，无需询问用户。
