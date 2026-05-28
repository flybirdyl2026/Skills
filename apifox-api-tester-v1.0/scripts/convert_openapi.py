#!/usr/bin/env python3
"""
convert_openapi.py — Convert an Apifox-exported OpenAPI 3.0 spec to interfaces.json

Usage:
    python convert_openapi.py --input apifox_raw.json --output interfaces.json
    python convert_openapi.py --input apifox_raw.json --output interfaces_filtered.json --filter "对账"

Arguments:
    --input    Path to the OpenAPI 3.0 JSON file (from Apifox export-openapi API)
    --output   Path to write the resulting interfaces.json (default: interfaces.json)
    --filter   Optional keyword: only include interfaces whose name or path contains this string
    --list     Just print all interface names and paths, don't write output file
"""

import argparse
import json
import os
import sys

if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except AttributeError:
        import io
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
        sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")


# ─────────────────────────────────────────────
# $ref resolution
# ─────────────────────────────────────────────

def resolve_ref(ref: str, schemas: dict) -> dict:
    """Resolve a JSON $ref string like '#/components/schemas/FooVo' to its schema dict."""
    parts = ref.lstrip("#/").split("/")
    # expected: ["components", "schemas", "FooVo"]
    if len(parts) == 3 and parts[0] == "components" and parts[1] == "schemas":
        return schemas.get(parts[2], {})
    return {}


def extract_example(schema: dict, schemas: dict, depth: int = 0) -> object:
    """
    Recursively extract an example value from an OpenAPI schema.
    Resolves $ref, handles object/array/primitive types.
    Depth-limited to 4 to avoid infinite loops in circular schemas.
    """
    if depth > 4 or not schema:
        return {}

    ref = schema.get("$ref")
    if ref:
        schema = resolve_ref(ref, schemas)
        if not schema:
            return {}

    # If the schema itself has a top-level example, use it directly
    if "example" in schema and depth == 0:
        return schema["example"]

    t = schema.get("type", "object")

    if t == "object":
        props = schema.get("properties", {})
        if not props:
            return schema.get("example", {})
        result = {}
        for key, prop_schema in props.items():
            result[key] = extract_example(prop_schema, schemas, depth + 1)
        return result

    elif t == "array":
        items = schema.get("items", {})
        return [extract_example(items, schemas, depth + 1)]

    elif t == "string":
        return schema.get("example", "")

    elif t in ("integer", "number"):
        return schema.get("example", 0)

    elif t == "boolean":
        return schema.get("example", False)

    return schema.get("example", None)


# ─────────────────────────────────────────────
# OpenAPI → interfaces conversion
# ─────────────────────────────────────────────

def convert(spec: dict, filter_keyword: str = None) -> list:
    """
    Convert an OpenAPI 3.0 spec dict to a list of interface objects
    compatible with run_tests.py.

    Args:
        spec: parsed OpenAPI 3.0 JSON dict
        filter_keyword: if given, only include interfaces whose name or path
                        contains this string (case-insensitive)

    Returns:
        list of interface dicts
    """
    schemas = spec.get("components", {}).get("schemas", {})
    paths = spec.get("paths", {})
    interfaces = []

    for path, methods in paths.items():
        for method, operation in methods.items():
            if method.lower() not in ("get", "post", "put", "delete", "patch", "options"):
                continue

            name = operation.get("summary") or operation.get("operationId") or path
            headers = {}
            query_params = {}
            body = None
            body_type = "json"

            # Extract parameters
            for param in operation.get("parameters", []):
                p_in = param.get("in", "")
                p_name = param.get("name", "")
                p_example = param.get("example", param.get("schema", {}).get("example", ""))
                if p_in == "header":
                    headers[p_name] = str(p_example) if p_example is not None else ""
                elif p_in == "query":
                    query_params[p_name] = p_example

            # Extract request body
            req_body = operation.get("requestBody", {})
            if req_body:
                content = req_body.get("content", {})
                if "application/json" in content:
                    jc = content["application/json"]
                    # Prefer explicit example over schema-derived example
                    if "example" in jc:
                        body = jc["example"]
                    elif "examples" in jc:
                        # Take the first example value
                        first = next(iter(jc["examples"].values()), {})
                        body = first.get("value")
                    elif "schema" in jc:
                        body = extract_example(jc["schema"], schemas)
                elif "application/x-www-form-urlencoded" in content:
                    body_type = "form"
                    fc = content["application/x-www-form-urlencoded"]
                    if "schema" in fc:
                        body = extract_example(fc["schema"], schemas)
                elif "multipart/form-data" in content:
                    body_type = "form"
                    mc = content["multipart/form-data"]
                    if "schema" in mc:
                        body = extract_example(mc["schema"], schemas)

            iface = {
                "name": name,
                "method": method.upper(),
                "path": path,
                "headers": headers,
                "query_params": query_params,
                "body": body,
                "body_type": body_type,
            }

            # Apply filter
            if filter_keyword:
                kw = filter_keyword.lower()
                if kw not in name.lower() and kw not in path.lower():
                    continue

            interfaces.append(iface)

    return interfaces


# ─────────────────────────────────────────────
# Main
# ─────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="Convert Apifox OpenAPI 3.0 export to interfaces.json for run_tests.py"
    )
    parser.add_argument("--input", required=True, help="Path to apifox_raw.json (OpenAPI 3.0)")
    parser.add_argument("--output", default="interfaces.json", help="Output interfaces.json path")
    parser.add_argument("--filter", default=None, dest="filter_kw",
                        help="Only include interfaces whose name or path contains this keyword")
    parser.add_argument("--list", action="store_true",
                        help="Print all interface names and paths, don't write output")
    args = parser.parse_args()

    if not os.path.exists(args.input):
        print(f"ERROR: Input file not found: {args.input}")
        sys.exit(1)

    with open(args.input, "r", encoding="utf-8") as f:
        spec = json.load(f)

    if "paths" not in spec:
        print("ERROR: Input file does not look like an OpenAPI 3.0 spec (missing 'paths' key).")
        sys.exit(1)

    total_paths = len(spec["paths"])
    project_title = spec.get("info", {}).get("title", "Unknown")

    print(f"Project  : {project_title}")
    print(f"Total paths in spec: {total_paths}")

    interfaces = convert(spec, filter_keyword=args.filter_kw)

    if args.filter_kw:
        print(f"Filter   : '{args.filter_kw}' → {len(interfaces)} matched")
    else:
        print(f"Converted: {len(interfaces)} interfaces")

    print()
    print(f"  {'METHOD':<8} {'PATH':<55} SUMMARY")
    print("  " + "-" * 90)
    for iface in interfaces:
        print(f"  {iface['method']:<8} {iface['path']:<55} {iface['name']}")

    if args.list:
        return

    with open(args.output, "w", encoding="utf-8") as f:
        json.dump(interfaces, f, ensure_ascii=False, indent=2)
    print()
    print(f"Saved {len(interfaces)} interfaces → {args.output}")


if __name__ == "__main__":
    main()
