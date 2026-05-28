"""
Apifox 通用接口调用客户端
==============================
依据从 Apifox 获取的接口定义，执行 API 调用。

Config (config.ini):
    base_url   = Actual API server base URL (required)
    apifox_url = Apifox project URL (for cache lookup, optional)
    app_code   = Application code (optional)
    timeout    = Request timeout in seconds (default: 30)

Usage:
    python api_call.py GET /user/fileInfo
    python api_call.py POST /server/fileInfo/page --body '{"current":1,"size":5}'
    python api_call.py --call 422011936 --params "fileId=xxx"
    python api_call.py GET /server/fileInfo/getById --api-url "http://192.168.200.96:15015/microvideo-file-center"
"""

import sys
import os
import re
import json
import hashlib
import configparser
import argparse
from pathlib import Path

try:
    import requests
except ImportError:
    print("ERROR: requests not installed. Run: pip install requests")
    sys.exit(1)


SKILL_DIR = Path(__file__).parent.parent
DEFAULT_CONFIG = SKILL_DIR / "config.ini"
CACHE_DIR = Path.home() / ".qclaw" / "cache" / "apifox-api"
WORKSPACE_CACHE_DIR = None


def set_workspace_cache_dir(workspace_path):
    """设置 workspace 级别的缓存目录"""
    global WORKSPACE_CACHE_DIR
    if workspace_path:
        WORKSPACE_CACHE_DIR = Path(workspace_path) / "cache"
        WORKSPACE_CACHE_DIR.mkdir(parents=True, exist_ok=True)


# ── Tools ────────────────────────────────────────────────────────────────────

def extract_base(url):
    url = url.rstrip("/")
    m = re.match(r"^(https?://[^/]+)", url)
    return m.group(1) if m else url


def cache_path(apifox_url):
    key = hashlib.md5(extract_base(apifox_url).encode()).hexdigest()[:12]
    if WORKSPACE_CACHE_DIR:
        return WORKSPACE_CACHE_DIR / f"{key}.json"
    return CACHE_DIR / f"{key}.json"


# ── Config ──────────────────────────────────────────────────────────────────

def load_config(config_path=None):
    cfg = configparser.ConfigParser()
    path = config_path or DEFAULT_CONFIG
    if path and Path(path).exists():
        cfg.read(Path(path), encoding="utf-8")
    return cfg


# ── Cache ───────────────────────────────────────────────────────────────────

def load_cache(apifox_url):
    path = cache_path(apifox_url)
    if path.exists():
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    return {}


def find_api_by_path(cache, path, method=None):
    for api in cache.get("apis", []):
        for op in api.get("operations", []):
            if op["path"] == path:
                if method is None or op["method"].upper() == method.upper():
                    return op
    return None


def find_api_by_id(cache, api_id):
    for api in cache.get("apis", []):
        if str(api.get("apiId")) == str(api_id):
            ops = api.get("operations", [])
            return ops[0] if ops else None
    return None


# ── Param helpers ────────────────────────────────────────────────────────────

def parse_kv(s):
    if "=" in s:
        k, v = s.split("=", 1)
        return k.strip(), v.strip()
    return s.strip(), ""


def parse_body(s):
    try:
        return json.loads(s)
    except json.JSONDecodeError as e:
        print(f"ERROR: Invalid JSON: {e}")
        sys.exit(1)


def apply_params_to_op(op, params_dict):
    """Fill URL path/query/body templates from params_dict"""
    path = op["path"]
    query = {}
    body = None

    defined_params = {p["name"]: p for p in op.get("parameters", [])}

    for name, val in params_dict.items():
        # Replace path params {name}
        path = path.replace(f"{{{name}}}", str(val))
        # Fill defined params
        if name in defined_params:
            p = defined_params[name]
            if p["in"] == "query":
                query[name] = val
            elif p["in"] == "path":
                path = path.replace(f"{{{name}}}", str(val))

    # Fill body from schema
    rb = op.get("requestBody")
    if rb:
        schema = rb.get("schema") or {}
        if schema.get("type") == "object" and "properties" in schema:
            body = {}
            for prop_name, prop_schema in schema["properties"].items():
                if prop_name in params_dict:
                    body[prop_name] = params_dict[prop_name]

    # Remove unreplaced placeholders
    path = re.sub(r"\{[^}]+\}", "", path)

    return path, query, body


# ── Core call ────────────────────────────────────────────────────────────────

def do_call(method, path, base_url, app_code=None,
            query_params=None, headers=None, body_str=None,
            file_path=None, body_file=None,
            output_path=None, silent=False, raw=False,
            timeout=30):
    headers = dict(headers) if headers else {}

    # Auto-inject appCode
    if app_code:
        if path.startswith("/server/") or path.startswith("/wpsOnline/"):
            headers["appCode"] = app_code
        elif path.startswith("/user/") or "?" in path:
            if query_params is None:
                query_params = {}
            query_params["appCode"] = app_code

    # File upload
    files = None
    data = None
    body = None

    if file_path:
        if not os.path.exists(file_path):
            print(f"ERROR: File not found: {file_path}")
            return 1
        file_name = os.path.basename(file_path)
        files = {
            "fileContent": (file_name, open(file_path, "rb"),
                            "application/octet-stream")
        }
    else:
        if body_file:
            with open(body_file, "r", encoding="utf-8-sig") as f:
                body = json.load(f)
        elif body_str:
            body = parse_body(body_str)

        if body:
            data = json.dumps(body, ensure_ascii=False)
            headers["Content-Type"] = "application/json"

    # Build URL
    url = base_url.rstrip("/") + path
    if query_params:
        sep = "&" if "?" in path else "?"
        url += sep + "&".join(f"{k}={requests.utils.quote(str(v))}"
                               for k, v in query_params.items())

    # Print request info
    safe_h = {k: ("***" if k.lower() in ("token", "authorization", "appcode") else v)
              for k, v in headers.items()}
    print(f"\n[CALL] {method.upper()} {url}")
    if safe_h:
        print(f"       Headers: {safe_h}")
    if body and not silent:
        body_preview = json.dumps(body, ensure_ascii=False)[:200]
        print(f"       Body: {body_preview}")

    # Execute request
    try:
        resp = requests.request(
            method.upper(), url=url, headers=headers,
            files=files, data=data, timeout=timeout
        )
    except requests.exceptions.RequestException as e:
        print(f"ERROR: {e}")
        return 1

    print(f"[HTTP] {resp.status_code}  ({resp.elapsed.total_seconds():.2f}s)")

    # File stream response
    ct = resp.headers.get("Content-Type", "")
    if "json" not in ct and resp.content:
        disp = resp.headers.get("Content-Disposition", "")
        fname_m = re.search(r'filename[*]?=["\']?([^"\']+)', disp)
        fname = fname_m.group(1) if fname_m else "download"
        out = output_path or fname
        with open(out, "wb") as f:
            f.write(resp.content)
        print(f"[SAVE] File saved: {out} ({len(resp.content)} bytes)")
        return 0 if resp.ok else 1

    # JSON response
    try:
        resp_data = resp.json()
    except json.JSONDecodeError:
        print(f"[RAW]  {resp.text[:300]}")
        return 0 if resp.ok else 1

    if output_path:
        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(resp_data, f, ensure_ascii=False, indent=2)
        print(f"[SAVE] Response saved: {output_path}")

    if raw:
        print(json.dumps(resp_data, ensure_ascii=False, indent=2))
    elif silent:
        print(json.dumps(resp_data.get("data", resp_data),
                        ensure_ascii=False, indent=2))
    else:
        print(json.dumps(resp_data, ensure_ascii=False, indent=2))

    code = resp_data.get("code")
    if code == 200 or code == "200":
        return 0
    if resp_data.get("success") is False:
        print(f"[WARN] {resp_data.get('msg', '')}")
        return 1
    return 0 if resp.ok else 1


# ── CLI ──────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Apifox API Client")
    parser.add_argument("method", nargs="?", help="HTTP method (GET/POST/PUT/DELETE)")
    parser.add_argument("path", nargs="?", help="API path (e.g. /user/fileInfo)")

    g = parser.add_argument_group("Call modes")
    g.add_argument("--call", dest="api_id", help="Call by API ID (auto-match path/method)")
    g.add_argument("--params", dest="params_str", help="Params k=v,k2=v2 (for --call)")

    g = parser.add_argument_group("Workspace")
    g.add_argument("--workspace", dest="workspace", default=None,
                   help="Path to workspace directory (overrides config + cache paths)")

    g = parser.add_argument_group("URL")
    g.add_argument("--api-url", dest="api_url",
                   help="Actual API server base URL (required if not in config)")
    g.add_argument("--apifox-url", dest="apifox_url",
                   help="Apifox project URL (for cache lookup)")

    g = parser.add_argument_group("Request")
    g.add_argument("--app-code", dest="app_code")
    g.add_argument("--query", dest="query", action="append")
    g.add_argument("--header", dest="headers", action="append")
    g.add_argument("--body", dest="body")
    g.add_argument("--body-file", dest="body_file")
    g.add_argument("--file", dest="file_path")
    g.add_argument("--output", dest="output_path")
    g.add_argument("--config", dest="config_path")
    g.add_argument("--no-cache", dest="no_cache", action="store_true")
    g.add_argument("--silent", action="store_true")
    g.add_argument("--raw", action="store_true")
    g.add_argument("--timeout", type=int, default=30)

    args = parser.parse_args()

    # Resolve workspace: if --workspace given, use its config
    workspace = Path(args.workspace) if args.workspace else None

    # 设置 workspace 缓存目录（确保在 load_cache 之前调用）
    if workspace:
        set_workspace_cache_dir(str(workspace))

    # Load config: workspace config.ini > --config > skill-level default
    if workspace and (workspace / "config.ini").exists():
        cfg = load_config(str(workspace / "config.ini"))
    else:
        cfg = load_config(args.config_path)

    api_url = (
        args.api_url
        or cfg.get("api", "base_url", fallback=None)
        or cfg.get("apifox", "base_url", fallback=None)
        or cfg.get("DEFAULT", "base_url", fallback=None)
    )
    if not api_url:
        print("ERROR: No API URL. Set base_url in config.ini or use --api-url")
        sys.exit(1)

    apifox_url = (
        args.apifox_url
        or cfg.get("api", "apifox_url", fallback=None)
        or cfg.get("apifox", "apifox_url", fallback=None)
        or api_url
    )

    app_code = (
        args.app_code
        or cfg.get("api", "app_code", fallback=None)
        or cfg.get("apifox", "app_code", fallback=None)
        or cfg.get("auth", "app_code", fallback=None)
    )

    mobile = (
        cfg.get("auth", "mobile", fallback=None)
    )

    timeout = args.timeout or int(
        cfg.get("api", "timeout", fallback=None)
        or cfg.get("apifox", "timeout", fallback="30")
    ) or 30

    # Parse query/headers
    query_params = None
    if args.query:
        query_params = {}
        for q in args.query:
            k, v = parse_kv(q)
            query_params[k] = v

    headers = None
    if args.headers:
        headers = {}
        for h in args.headers:
            k, v = parse_kv(h)
            headers[k] = v

    call_params = {}
    if args.params_str:
        for p in args.params_str.split(","):
            k, v = parse_kv(p)
            call_params[k] = v

    # Determine method + path
    method = None
    path = None
    cache = {}

    if not args.no_cache:
        cache = load_cache(apifox_url)
        if not cache:
            print(f"[INFO] No cache for: {apifox_url}")
            print(f"       Run: python api_fetch.py fetch \"{apifox_url}\"")
            print(f"       Continuing without cache...")

    if args.api_id:
        op = find_api_by_id(cache, args.api_id) if cache else None
        if not op:
            print(f"[WARN] API ID not found in cache: {args.api_id}")
            sys.exit(1)
        method = op["method"]
        path, q, body = apply_params_to_op(op, call_params)
        if q:
            query_params = {**(query_params or {}), **q}
        if body:
            args.body = json.dumps(body, ensure_ascii=False)
        print(f"[INFO] API {args.api_id}: {method} {path}")

    elif args.method and args.path:
        method = args.method.upper()
        path = args.path
    else:
        parser.print_help()
        sys.exit(1)

    # Execute
    exit_code = do_call(
        method=method, path=path, base_url=api_url,
        app_code=app_code, query_params=query_params,
        headers=headers, body_str=args.body,
        file_path=args.file_path, body_file=args.body_file,
        output_path=args.output_path, silent=args.silent,
        raw=args.raw, timeout=timeout
    )
    sys.exit(exit_code)


if __name__ == "__main__":
    main()
