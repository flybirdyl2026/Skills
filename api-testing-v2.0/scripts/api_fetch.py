"""
Apifox API 接口抓取工具
========================
从 Apifox 项目抓取全部接口定义，缓存到本地。

用法：
    python api_fetch.py fetch "https://xxx.apifox.cn"
    python api_fetch.py list "https://xxx.apifox.cn"
"""

import sys
import os
import re
import json
import time
import hashlib
import argparse
from pathlib import Path

try:
    import requests
except ImportError:
    print("ERROR: requests not installed. Run: pip install requests")
    sys.exit(1)

try:
    import yaml
except ImportError:
    print("ERROR: pyyaml not installed. Run: pip install pyyaml")
    sys.exit(1)


CACHE_DIR = Path.home() / ".qclaw" / "cache" / "apifox-api"
CACHE_DIR.mkdir(parents=True, exist_ok=True)

# workspace 缓存目录（可在运行时覆盖）
WORKSPACE_CACHE_DIR = None


def set_workspace_cache_dir(workspace_path):
    """设置 workspace 级别的缓存目录"""
    global WORKSPACE_CACHE_DIR
    if workspace_path:
        WORKSPACE_CACHE_DIR = Path(workspace_path) / "cache"
        WORKSPACE_CACHE_DIR.mkdir(parents=True, exist_ok=True)


# ── 工具 ────────────────────────────────────────────────────────────────────

def extract_base(url):
    """提取域名部分"""
    url = url.rstrip("/")
    m = re.match(r"^(https?://[^/]+)", url)
    return m.group(1) if m else url


def cache_key(apifox_url):
    """根据 apifox_url 生成缓存 key"""
    base = extract_base(apifox_url)
    return hashlib.md5(base.encode()).hexdigest()[:12]


def cache_path(apifox_url):
    key = cache_key(apifox_url)
    if WORKSPACE_CACHE_DIR:
        return WORKSPACE_CACHE_DIR / f"{key}.json"
    return CACHE_DIR / f"{key}.json"


def clean_text(s):
    if not isinstance(s, str):
        return s
    return re.sub(r"[\ufe00-\ufe0f\u200b-\u200f\u2028-\u202f\ufeff]", "", s)


def fetch_url(url, retries=3):
    for i in range(retries):
        try:
            r = requests.get(url, timeout=15,
                           headers={"User-Agent": "Mozilla/5.0 (apifox-skill/1.0)"})
            r.raise_for_status()
            return clean_text(r.text)
        except Exception as e:
            if i < retries - 1:
                time.sleep(2)
            else:
                raise e


# ── 解析 ─────────────────────────────────────────────────────────────────────

def extract_api_ids(text):
    """从 llms.txt 提取所有 API ID"""
    seen = set()
    results = []
    for m in re.finditer(r"/(\d{5,})e0\.md|api-(\d{5,})(?:[-.]|$)", text):
        aid = m.group(1) or m.group(2)
        if aid and aid not in seen:
            seen.add(aid)
            results.append(aid)
    return results


def extract_yaml_block(text):
    """从 Markdown 提取 YAML 代码块"""
    for pattern in [
        r"```yaml\s*\n(.*?)\n```",
        r"```\s*\n(.*?)\n```",
    ]:
        m = re.search(pattern, text, re.DOTALL)
        if m:
            return m.group(1).strip()
    return text.strip()


def resolve_ref(ref, schemas):
    if not isinstance(ref, dict):
        return ref
    ref_str = ref.get("$ref", "")
    if ref_str.startswith("#/components/schemas/"):
        name = ref_str.split("/")[-1]
        return resolve_ref(schemas.get(name, {}), schemas)
    result = dict(ref)
    for key in ["allOf", "anyOf", "oneOf"]:
        if key in result:
            result[key] = [resolve_ref(x, schemas) for x in result[key]]
    if "items" in result:
        result["items"] = resolve_ref(result["items"], schemas)
    if "properties" in result:
        result["properties"] = {k: resolve_ref(v, schemas)
                                for k, v in result["properties"].items()}
    return result


def parse_yaml(text):
    """解析 OpenAPI YAML，返回结构化 dict"""
    yaml_text = extract_yaml_block(text)
    try:
        data = yaml.safe_load(yaml_text)
    except Exception:
        return None

    if not data or "paths" not in data:
        return None

    schemas = data.get("components", {}).get("schemas", {})
    ops = []

    for path, methods in data.get("paths", {}).items():
        for method, op in methods.items():
            if method.upper() not in ("GET", "POST", "PUT", "DELETE", "PATCH", "HEAD", "OPTIONS"):
                continue

            o = {
                "method": method.upper(),
                "path": path,
                "summary": op.get("summary", ""),
                "description": op.get("description", ""),
                "deprecated": op.get("deprecated", False),
                "folder": op.get("x-apifox-folder", ""),
                "status": op.get("x-apifox-status", ""),
                "parameters": [],
                "requestBody": None,
                "responses": {}
            }

            for p in op.get("parameters", []):
                o["parameters"].append({
                    "name": p.get("name", ""),
                    "in": p.get("in", ""),
                    "required": p.get("required", False),
                    "description": p.get("description", ""),
                    "type": (p.get("schema") or {}).get("type", "any")
                })

            rb = op.get("requestBody") or {}
            if rb:
                content = rb.get("content", {})
                rb_data = {
                    "required": rb.get("required", False),
                    "contentTypes": list(content.keys()),
                    "schema": None
                }
                for ct, ct_val in content.items():
                    rb_data["schema"] = resolve_ref(ct_val.get("schema", {}), schemas)
                    break
                o["requestBody"] = rb_data

            for sc, resp in op.get("responses", {}).items():
                content = resp.get("content", {})
                o["responses"][sc] = {"description": resp.get("description", ""),
                                       "schema": None, "contentType": None}
                for ct, ct_val in content.items():
                    o["responses"][sc]["schema"] = resolve_ref(ct_val.get("schema", {}), schemas)
                    o["responses"][sc]["contentType"] = ct
                    break

            ops.append(o)

    return {"operations": ops, "folder": ops[0]["folder"] if ops else ""} if ops else None


# ── 命令 ─────────────────────────────────────────────────────────────────────

def cmd_fetch(apifox_url, force=False):
    base = extract_base(apifox_url)
    llms_url = f"{base}/llms.txt"

    print(f"Fetching API list: {llms_url}")
    try:
        llms_text = fetch_url(llms_url)
    except Exception as e:
        print(f"ERROR: Cannot access {llms_url}")
        print(f"  Reason: {e}")
        print("Hint: Make sure the Apifox project is set to 'Public' in project settings.")
        sys.exit(1)

    api_ids = extract_api_ids(llms_text)
    if not api_ids:
        print("ERROR: No API IDs found in llms.txt. Check the URL.")
        sys.exit(1)

    print(f"Found {len(api_ids)} APIs, fetching details...")

    results = []
    errors = []
    total = len(api_ids)

    for i, api_id in enumerate(api_ids, 1):
        detail_url = f"{base}/{api_id}e0.md"
        try:
            text = fetch_url(detail_url)
            parsed = parse_yaml(text)
            if parsed:
                parsed["apiId"] = api_id
                results.append(parsed)
            else:
                errors.append(api_id)
        except Exception as e:
            errors.append(f"{api_id}({e})")

        if i % 20 == 0 or i == total:
            print(f"  Progress: {i}/{total}  ({len(results)} OK, {len(errors)} errors)")

        time.sleep(0.15)

    cache_data = {
        "apifoxUrl": base,
        "fetchedAt": time.strftime("%Y-%m-%d %H:%M:%S"),
        "total": len(results),
        "apis": results,
        "errors": errors
    }
    path = cache_path(apifox_url)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(cache_data, f, ensure_ascii=False, indent=2)
    print(f"Cache saved: {path}")

    pct = len(results) / total * 100
    print(f"\nDone! {len(results)}/{total} fetched ({pct:.0f}%)")
    if errors:
        errs = ", ".join(str(e) for e in errors[:5])
        if len(errors) > 5:
            errs += f" ... +{len(errors)-5} more"
        print(f"WARNING: {len(errors)} failed: {errs}")


def cmd_list(apifox_url, filter_text=None, folder=None):
    path = cache_path(apifox_url)
    if not path.exists():
        print(f"No cache found for: {apifox_url}")
        print(f"Run: python api_fetch.py fetch \"{apifox_url}\"")
        sys.exit(1)

    with open(path, "r", encoding="utf-8") as f:
        cache = json.load(f)

    print(f"Apifox: {cache.get('apifoxUrl', apifox_url)}")
    print(f"Cached: {cache.get('fetchedAt', 'unknown')}  |  {len(cache.get('apis', []))} APIs\n")

    for api in cache.get("apis", []):
        for op in api.get("operations", []):
            if filter_text:
                searchable = (op["summary"] + op["path"] + op.get("description", "")).lower()
                if filter_text.lower() not in searchable:
                    continue
            if folder and op.get("folder") != folder:
                continue

            tag = "[DEPRECATED] " if op.get("deprecated") else ""
            print(f"[{op['method']:7}] {op['path']}  {tag}{op['summary']}")
            if op.get("folder"):
                print(f"           Folder: {op['folder']}")
            print()


# ── CLI ──────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_fetch = sub.add_parser("fetch", help="Fetch API definitions")
    p_fetch.add_argument("apifox_url", help="Apifox project URL (e.g. https://xxx.apifox.cn)")
    p_fetch.add_argument("--force", action="store_true", help="Force refresh cache")
    p_fetch.add_argument("--workspace", help="Workspace directory for cache storage")

    p_list = sub.add_parser("list", help="List cached APIs")
    p_list.add_argument("apifox_url", help="Apifox project URL")
    p_list.add_argument("--filter", dest="filter_text", help="Keyword filter")
    p_list.add_argument("--folder", help="Filter by folder")
    p_list.add_argument("--workspace", help="Workspace directory for cache lookup")

    args = parser.parse_args()

    # 设置 workspace 缓存目录
    if hasattr(args, 'workspace') and args.workspace:
        set_workspace_cache_dir(args.workspace)

    if args.cmd == "fetch":
        cmd_fetch(args.apifox_url, args.force)
    elif args.cmd == "list":
        cmd_list(args.apifox_url, args.filter_text, args.folder)


if __name__ == "__main__":
    main()
