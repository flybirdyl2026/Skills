#!/usr/bin/env python3
"""
apifox_to_interfaces.py
Convert raw Apifox MCP API list (as returned by apifox-mcp tools) into the
normalized interfaces.json format expected by run_tests.py.

Usage:
    python apifox_to_interfaces.py --input <apifox_raw.json> --output interfaces.json

The input is the JSON/dict returned by apifox-mcp `list_api_detail` or similar tools.
Supported raw shapes:
  1. Array of Apifox API objects  (items with .type == "apiDetail" or direct API dicts)
  2. Object with a .data.list or .items key containing an array

Each output interface object:
    {
        "name": "...",
        "method": "GET",
        "path": "/api/...",
        "headers": {},
        "query_params": {},
        "body": null,
        "body_type": "json"
    }
"""

import argparse
import json
import os
import sys
from typing import Any, Dict, List, Optional


def extract_api_list(raw: Any) -> List[Dict]:
    """Try to extract a flat list of API objects from various Apifox MCP response shapes."""
    if isinstance(raw, list):
        return raw
    if isinstance(raw, dict):
        # Try common wrapper keys
        for key in ("data", "result", "apis", "items"):
            if key in raw:
                inner = raw[key]
                if isinstance(inner, list):
                    return inner
                if isinstance(inner, dict):
                    for subkey in ("list", "items", "apis"):
                        if subkey in inner and isinstance(inner[subkey], list):
                            return inner[subkey]
    return []


def extract_query_params(parameters: Optional[List]) -> Dict[str, str]:
    if not parameters:
        return {}
    return {
        p.get("name", ""): p.get("example", p.get("default", ""))
        for p in parameters
        if p.get("in") == "query" and p.get("name")
    }


def extract_headers(parameters: Optional[List]) -> Dict[str, str]:
    if not parameters:
        return {}
    return {
        p.get("name", ""): p.get("example", p.get("default", ""))
        for p in parameters
        if p.get("in") == "header" and p.get("name")
    }


def extract_body(request_body: Optional[Dict]) -> tuple:
    """Returns (body_dict_or_none, body_type_str)."""
    if not request_body:
        return None, "json"
    content = request_body.get("content") or {}
    if "application/json" in content:
        schema = content["application/json"].get("schema") or {}
        example = content["application/json"].get("example")
        body = example if example is not None else schema.get("example")
        return body, "json"
    if "application/x-www-form-urlencoded" in content:
        return None, "form"
    if "multipart/form-data" in content:
        return None, "form"
    return None, "json"


def normalize_api(api: Dict) -> Optional[Dict]:
    """Normalize a single Apifox API object into run_tests.py format."""
    # Apifox MCP may wrap objects under 'api' key
    if "api" in api and isinstance(api["api"], dict):
        api = api["api"]

    method = (api.get("method") or api.get("httpMethod") or "GET").upper()
    path = api.get("path") or api.get("url") or api.get("uri") or "/"
    name = api.get("name") or api.get("title") or api.get("summary") or path

    parameters: List = api.get("parameters") or api.get("params") or []
    request_body = api.get("requestBody") or api.get("request_body") or api.get("body")

    query_params = extract_query_params(parameters)
    headers = extract_headers(parameters)
    body, body_type = extract_body(request_body if isinstance(request_body, dict) else None)

    return {
        "name": name,
        "method": method,
        "path": path,
        "headers": headers,
        "query_params": query_params,
        "body": body,
        "body_type": body_type,
    }


def convert(input_path: str, output_path: str):
    with open(input_path, "r", encoding="utf-8") as f:
        raw = json.load(f)

    api_list = extract_api_list(raw)
    if not api_list:
        print(f"WARNING: No API items found in {input_path}. Check the JSON structure.")

    interfaces = []
    for item in api_list:
        normalized = normalize_api(item)
        if normalized:
            interfaces.append(normalized)

    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(interfaces, f, ensure_ascii=False, indent=2)

    print(f"Converted {len(interfaces)} interfaces -> {output_path}")


def main():
    parser = argparse.ArgumentParser(description="Convert Apifox MCP output to interfaces.json")
    parser.add_argument("--input", required=True, help="Raw Apifox MCP JSON file")
    parser.add_argument("--output", default="interfaces.json", help="Output interfaces file")
    args = parser.parse_args()

    if not os.path.exists(args.input):
        print(f"ERROR: Input file not found: {args.input}")
        sys.exit(1)

    convert(args.input, args.output)


if __name__ == "__main__":
    main()
