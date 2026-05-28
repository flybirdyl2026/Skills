#!/usr/bin/env python3
"""
apifox-api-tester: Run all API interfaces from Apifox project using requests library.

Usage:
    python run_tests.py --interfaces <json_file> [--base-url <base_url>] [--output <output_file>]
                        [--timeout <seconds>] [--token <bearer_token>] [--env <env_json>]

Arguments:
    --interfaces   Path to a JSON file containing the list of API interfaces (exported from Apifox MCP)
    --base-url     Base URL to override all interface hosts (e.g. https://api.example.com)
    --output       Output file path for the test report (default: api_test_report.json)
    --timeout      Request timeout in seconds (default: 15)
    --token        Bearer token for Authorization header (optional)
    --env          Path to a JSON file with environment variables for placeholder replacement

The interfaces JSON file must be an array of objects, each with at least:
    {
        "name": "Interface name",
        "method": "GET|POST|PUT|DELETE|PATCH",
        "path": "/api/v1/resource",
        "headers": {...},           (optional)
        "query_params": {...},      (optional)
        "body": {...},              (optional, for POST/PUT/PATCH)
        "body_type": "json|form|raw" (optional, default: json)
    }
"""

import argparse
import json
import os
import re
import sys
import time
from datetime import datetime
from typing import Any, Dict, List, Optional

# ── Windows encoding fix ──────────────────────────────────────
# On Windows, stdout/stderr default to GBK, which cannot encode
# Unicode emoji (✅ ❌ ⚠️) used in the summary output.
# This must be done before any print() calls.
if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except AttributeError:
        # Python < 3.7 fallback
        import io
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
        sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")
# ─────────────────────────────────────────────────────────────

try:
    import requests
    from requests.exceptions import RequestException
except ImportError:
    print("ERROR: 'requests' library is not installed. Run: pip install requests")
    sys.exit(1)


# ─────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────

def replace_placeholders(value: Any, env: Dict[str, str]) -> Any:
    """Recursively replace {{variable}} placeholders in strings/dicts/lists."""
    if isinstance(value, str):
        for k, v in env.items():
            value = value.replace(f"{{{{{k}}}}}", str(v))
        return value
    if isinstance(value, dict):
        return {k: replace_placeholders(v, env) for k, v in value.items()}
    if isinstance(value, list):
        return [replace_placeholders(item, env) for item in value]
    return value


def build_url(base_url: Optional[str], path: str) -> str:
    """Combine base URL with path, handling trailing/leading slashes."""
    if not base_url:
        return path
    return base_url.rstrip("/") + "/" + path.lstrip("/")


def sanitize_body(body: Any, body_type: str):
    """Return (json_payload, data_payload, raw_payload) depending on body_type."""
    if not body:
        return None, None, None
    body_type = (body_type or "json").lower()
    if body_type == "json":
        return body, None, None
    if body_type == "form":
        return None, body, None
    # raw / text
    return None, None, body


def run_single(interface: Dict, base_url: Optional[str], timeout: int,
               default_headers: Dict[str, str], env: Dict[str, str]) -> Dict:
    """Execute a single API interface and return a result dict."""
    name = interface.get("name", "Unnamed")
    method = (interface.get("method") or "GET").upper()
    path = interface.get("path", "/")
    headers = dict(default_headers)
    headers.update(interface.get("headers") or {})
    query_params = interface.get("query_params") or {}
    body = interface.get("body")
    body_type = interface.get("body_type", "json")

    # Apply env substitution
    path = replace_placeholders(path, env)
    headers = replace_placeholders(headers, env)
    query_params = replace_placeholders(query_params, env)
    body = replace_placeholders(body, env)

    url = build_url(base_url, path)
    json_payload, data_payload, raw_payload = sanitize_body(body, body_type)

    result: Dict = {
        "name": name,
        "method": method,
        "url": url,
        "request": {
            "headers": headers,
            "query_params": query_params,
            "body": body,
            "body_type": body_type,
        },
        "status": "unknown",
        "http_status": None,
        "response_time_ms": None,
        "response_headers": None,
        "response_body": None,
        "error": None,
    }

    start = time.monotonic()
    try:
        resp = requests.request(
            method=method,
            url=url,
            headers=headers,
            params=query_params if query_params else None,
            json=json_payload,
            data=data_payload if data_payload else (raw_payload if raw_payload else None),
            timeout=timeout,
            allow_redirects=True,
        )
        elapsed_ms = round((time.monotonic() - start) * 1000, 2)
        result["http_status"] = resp.status_code
        result["response_time_ms"] = elapsed_ms
        result["response_headers"] = dict(resp.headers)
        # Try to parse body as JSON; fall back to text
        try:
            result["response_body"] = resp.json()
        except Exception:
            result["response_body"] = resp.text[:5000]  # cap at 5000 chars
        result["status"] = "success" if resp.ok else "http_error"
    except RequestException as exc:
        elapsed_ms = round((time.monotonic() - start) * 1000, 2)
        result["response_time_ms"] = elapsed_ms
        result["status"] = "error"
        result["error"] = str(exc)

    return result


# ─────────────────────────────────────────────
# Report generation
# ─────────────────────────────────────────────

def generate_report(results: List[Dict], start_time: str, end_time: str) -> Dict:
    total = len(results)
    success = sum(1 for r in results if r["status"] == "success")
    http_error = sum(1 for r in results if r["status"] == "http_error")
    error = sum(1 for r in results if r["status"] == "error")

    return {
        "summary": {
            "start_time": start_time,
            "end_time": end_time,
            "total_interfaces": total,
            "success": success,
            "http_error": http_error,
            "connection_error": error,
            "pass_rate": f"{round(success / total * 100, 1)}%" if total else "N/A",
        },
        "results": results,
    }


def print_summary(report: Dict):
    s = report["summary"]
    print("\n" + "=" * 60)
    print("  Apifox API Test Report")
    print("=" * 60)
    print(f"  Start Time   : {s['start_time']}")
    print(f"  End Time     : {s['end_time']}")
    print(f"  Total        : {s['total_interfaces']}")
    print(f"  ✅ Success   : {s['success']}")
    print(f"  ⚠️  HTTP Err  : {s['http_error']}")
    print(f"  ❌ Conn Err  : {s['connection_error']}")
    print(f"  Pass Rate    : {s['pass_rate']}")
    print("=" * 60)
    print("\nDetailed Results:")
    for r in report["results"]:
        icon = {"success": "✅", "http_error": "⚠️ ", "error": "❌"}.get(r["status"], "❓")
        http = f"HTTP {r['http_status']}" if r["http_status"] else "N/A"
        ms = f"{r['response_time_ms']}ms" if r["response_time_ms"] is not None else "N/A"
        print(f"  {icon} [{r['method']:6}] {r['name'][:45]:<45} {http:10} {ms}")
        if r["error"]:
            print(f"       Error: {r['error']}")
    print()


# ─────────────────────────────────────────────
# Main
# ─────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Run all Apifox interfaces via requests")
    parser.add_argument("--interfaces", required=True, help="Path to interfaces JSON file")
    parser.add_argument("--base-url", default=None, help="Base URL override")
    parser.add_argument("--output", default="api_test_report.json", help="Output report file path")
    parser.add_argument("--timeout", type=int, default=15, help="Request timeout (seconds)")
    parser.add_argument("--token", default=None, help="Bearer token for Authorization header")
    parser.add_argument("--env", default=None, help="Path to environment variables JSON file")
    args = parser.parse_args()

    # Load interfaces
    if not os.path.exists(args.interfaces):
        print(f"ERROR: Interfaces file not found: {args.interfaces}")
        sys.exit(1)
    with open(args.interfaces, "r", encoding="utf-8") as f:
        interfaces = json.load(f)
    if not isinstance(interfaces, list):
        print("ERROR: Interfaces JSON must be a top-level array.")
        sys.exit(1)
    print(f"Loaded {len(interfaces)} interfaces from: {args.interfaces}")

    # Load env
    env: Dict[str, str] = {}
    if args.env:
        if not os.path.exists(args.env):
            print(f"WARNING: Env file not found: {args.env}. Continuing without env.")
        else:
            with open(args.env, "r", encoding="utf-8") as f:
                env = json.load(f)
            print(f"Loaded {len(env)} env variables.")

    # Default headers
    default_headers: Dict[str, str] = {}
    if args.token:
        default_headers["Authorization"] = f"Bearer {args.token}"

    # Run all interfaces
    start_time = datetime.now().isoformat(timespec="seconds")
    results: List[Dict] = []
    for idx, iface in enumerate(interfaces, 1):
        name = iface.get("name", f"Interface #{idx}")
        print(f"  [{idx:3}/{len(interfaces)}] Running: {name[:60]}")
        res = run_single(iface, args.base_url, args.timeout, default_headers, env)
        results.append(res)

    end_time = datetime.now().isoformat(timespec="seconds")

    # Generate and save report
    report = generate_report(results, start_time, end_time)
    with open(args.output, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)
    print(f"\nReport saved to: {args.output}")

    print_summary(report)


if __name__ == "__main__":
    main()
