# -*- coding: utf-8 -*-
"""
通用接口测试执行骨架
====================
从 cases/*.json 读取用例定义，逐条执行并输出 test_results/JSON。

用法:
    python run_test.py --workspace workspaces/{项目名}/
    python run_test.py --cases cases/single_cases.json --config config.ini

用例 JSON 格式见 docs/case-design.md 或 cases/example.json。
"""
import sys
import io
import os
import json
import time
import copy
import shutil
import uuid as uuidlib
import argparse
import configparser
from datetime import datetime
from pathlib import Path

import requests

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

SKILL_DIR = Path(__file__).resolve().parent.parent
DEFAULT_RESULTS_DIR = SKILL_DIR / "test_results"


# ── HTTP 调用 ───────────────────────────────────────────────────────────────

def do_call(method, path, *, base_url, headers=None, params=None, body=None,
            timeout=30, mobile=None):
    """执行 HTTP 调用，返回 (http_status, biz_code, msg, data, raw_text)。"""
    url = base_url + path
    if headers is None:
        headers = {}
    if mobile and "mobile" not in headers:
        headers["mobile"] = str(mobile)
    if "Content-Type" not in headers and body is not None:
        headers["Content-Type"] = "application/json"
    try:
        if method == "GET":
            r = requests.get(url, params=params, headers=headers, timeout=timeout)
        elif method == "POST":
            data_bytes = json.dumps(body, ensure_ascii=False).encode("utf-8") if body else None
            r = requests.post(url, data=data_bytes, headers=headers, params=params, timeout=timeout)
        elif method == "DELETE":
            r = requests.delete(url, params=params, headers=headers, timeout=timeout)
        elif method == "PUT":
            data_bytes = json.dumps(body, ensure_ascii=False).encode("utf-8") if body else None
            r = requests.put(url, data=data_bytes, headers=headers, params=params, timeout=timeout)
        else:
            return 0, -1, f"method not supported: {method}", None, ""
        txt = r.text
        try:
            j = r.json()
            biz_code = j.get("code")
            msg = j.get("msg", "")
            data = j.get("data")
        except Exception:
            biz_code = None
            msg = ""
            data = None
        return r.status_code, biz_code, msg, data, txt
    except requests.RequestException as e:
        return 0, -1, f"NETWORK_ERR:{e}", None, str(e)


# ── 期望结果匹配器 ──────────────────────────────────────────────────────────

def exp_ok(http, biz, msg):
    if http == 200 and biz == 200:
        return True, "OK"
    return False, f"期望HTTP200/biz200, 实际HTTP{http}/biz{biz}"

def exp_biz_fail(http, biz, msg):
    if http == 200 and biz is not None and biz != 200:
        return True, f"业务错误已返回 biz={biz}"
    return False, f"期望业务失败, 实际HTTP{http}/biz{biz}"

def exp_biz_fail_or_http_4xx5xx(http, biz, msg):
    if http == 200 and biz == 200:
        return False, f"期望失败但业务成功(HTTP{http}/biz{biz})"
    return True, f"已返回异常(HTTP{http}/biz{biz})"

def exp_ok_or_empty_data(http, biz, msg):
    if http == 200:
        return True, f"HTTP200(biz={biz})"
    return False, f"HTTP{http}"

def exp_contains(keyword):
    """工厂函数：返回检查 msg 是否包含关键字的判定函数（支持 expect_fn: "exp_contains:keyword"）"""
    def _check(http, biz, msg):
        if http == 200 and biz != 200 and keyword in (msg or ""):
            return True, f"已返回预期业务错误，包含'{keyword}'"
        if http == 200 and biz == 200 and keyword in (msg or ""):
            return True, f"成功且响应包含'{keyword}'"
        if http == 200 and biz != 200:
            return False, f"期望包含'{keyword}'，实际msg='{msg[:50]}'"
        return False, f"期望HTTP200&包含'{keyword}'，实际HTTP{http}/biz{biz}"
    return _check

# 预注册的 exp_contains 工厂（也可通过 "exp_contains:keyword" 动态调用）
EXPECT_FNS = {
    "exp_ok": exp_ok,
    "exp_biz_fail": exp_biz_fail,
    "exp_biz_fail_or_http_4xx5xx": exp_biz_fail_or_http_4xx5xx,
    "exp_ok_or_empty_data": exp_ok_or_empty_data,
}


# ── 用例记录 ────────────────────────────────────────────────────────────────

def record_case(results, case_id, api_name, method, path, case_type, desc,
                req_params_str, expected_desc, http, biz, actual_msg,
                expect_match_fn=None, expect_fn_str=None):
    passed = False
    reason = ""
    if expect_match_fn:
        try:
            passed, reason = expect_match_fn(http, biz, actual_msg)
        except Exception as e:
            passed, reason = False, f"eval_err:{e}"
    else:
        passed = (http == 200 and biz == 200)
        reason = "默认判定"
    results.append({
        "case_id": case_id,
        "api_name": api_name,
        "method": method,
        "path": path,
        "case_type": case_type,
        "desc": desc,
        "request_params": req_params_str,
        "expected": expected_desc,
        "expect_fn": expect_fn_str or "",
        "http_status": http,
        "biz_code": biz,
        "actual_msg": (actual_msg or "")[:200],
        "result": "PASS" if passed else "FAIL",
        "reason": reason,
    })
    status_flag = "✓" if passed else "✗"
    print(f"[{status_flag}] {case_id:>6} {api_name}/{case_type}: {desc[:40]} -> HTTP {http} biz {biz}")


# ── 从 JSON 执行单条用例 ───────────────────────────────────────────────────

def execute_single_case(c, results, tc_idx, base_url, mobile, timeout,
                        setup_uuid=None, setup_file_id=None):
    """
    执行一条用例（从 cases JSON），自动填充 TC 编号。
    c: dict，含 method/path/case_type/desc/params/expect/expect_fn/...
    """
    tc_idx[0] += 1
    case_id = c.get("case_id") or f"TC{tc_idx[0]:03d}"
    method = c["method"]
    path = c["path"]
    api_name = c.get("api_name", "")
    case_type = c.get("case_type", "")
    desc = c.get("desc", "")
    expected_desc = c.get("expected_desc", "")

    # 构造参数（替换 $uuid / $fileId 上下文变量）
    params = None
    body = None
    req_params_str = ""
    raw_params = c.get("params") or {}
    # 支持 $uuid / $fileId 占位符（单接口用例也适用）
    for k, v in list(raw_params.items()):
        if isinstance(v, str) and v == "$uuid":
            raw_params[k] = setup_uuid or ""
        elif isinstance(v, str) and v == "$fileId":
            raw_params[k] = setup_file_id or ""

    if method == "GET":
        params = raw_params
        req_params_str = ", ".join(f"{k}={v}" for k, v in raw_params.items())
    elif method in ("POST", "PUT"):
        body = raw_params
        req_params_str = json.dumps(raw_params, ensure_ascii=False)[:200] if raw_params else ""
    elif method == "DELETE":
        params = raw_params
        req_params_str = ", ".join(f"{k}={v}" for k, v in raw_params.items())

    # 替换 path 中的 {uuid} / {fileId} 等占位符
    if isinstance(path, str):
        path = path.replace("{uuid}", str(raw_params.get("uuid", setup_uuid or "")))
        path = path.replace("{fileId}", str(raw_params.get("fileId", setup_file_id or "")))

    # 执行
    http, biz, msg, data, _ = do_call(
        method, path, base_url=base_url, params=params, body=body,
        timeout=timeout, mobile=mobile
    )

    # 期望匹配函数（支持 "exp_contains:keyword" 参数化格式）
    expect_fn_name = c.get("expect_fn")
    expect_match_fn = None
    if expect_fn_name:
        if expect_fn_name in EXPECT_FNS:
            expect_match_fn = EXPECT_FNS[expect_fn_name]
        elif expect_fn_name.startswith("exp_contains:"):
            keyword = expect_fn_name.split(":", 1)[1]
            expect_match_fn = exp_contains(keyword)

    record_case(results, case_id, api_name, method, path, case_type, desc,
                req_params_str, expected_desc, http, biz, msg, expect_match_fn,
                expect_fn_str=expect_fn_name)

def _fix_flow_api_names(cases: list):
    """检测并自我修复：若同一流程所有步骤 api_name 相同（说明填错了），
    则用各步骤 path 末段作为 api_name。"""
    names = [c.get("api_name", "") for c in cases]
    if len(set(names)) == 1 and names[0] != "":
        print(f"[AUTO-FIX] 业务流程所有步骤 api_name 均为「{names[0]}」，"
              "已自动修复为各步骤实际接口名")
        for c in cases:
            seg = c.get("path", "").strip("/").split("/")[-1]
            c["api_name"] = seg
    return cases


def execute_flow(cases, results, tc_idx, base_url, mobile, timeout,
                 setup_uuid=None, setup_file_id=None):
    """
    执行一批业务流程用例（按 step 顺序），前置失败则后续 SKIP。
    cases: list of dict，每条含 step/depends/...
    """
    cases = _fix_flow_api_names(cases)

    flow_ctx = {"uuid": setup_uuid, "fileId": setup_file_id}
    for c in cases:
        tc_idx[0] += 1
        case_id = c.get("case_id") or f"TC{tc_idx[0]:03d}"
        method = c["method"]
        path = c["path"]
        api_name = c.get("api_name", "")
        case_type = c.get("case_type", "")
        desc = c.get("desc", "")
        expected_desc = c.get("expected_desc", "")

        # 替换上下文变量
        raw_params = {}
        for k, v in (c.get("params") or {}).items():
            if isinstance(v, str) and v.startswith("$"):
                raw_params[k] = flow_ctx.get(v[1:], v)
            else:
                raw_params[k] = v

        params = None
        body = None
        req_params_str = ""
        if method == "GET":
            params = raw_params
            req_params_str = ", ".join(f"{k}={v}" for k, v in raw_params.items())
        elif method in ("POST", "PUT"):
            body = raw_params
            req_params_str = json.dumps(raw_params, ensure_ascii=False)[:200] if raw_params else ""
        elif method == "DELETE":
            params = raw_params
            req_params_str = ", ".join(f"{k}={v}" for k, v in raw_params.items())

        # 替换 path 占位符
        if isinstance(path, str):
            for k, v in raw_params.items():
                path = path.replace("{" + k + "}", str(v))

        # 执行
        http, biz, msg, data, _ = do_call(
            method, path, base_url=base_url, params=params, body=body,
            timeout=timeout, mobile=mobile
        )

        # 保存上下文（提取 uuid 等）
        if data and isinstance(data, dict):
            if "uuid" in data:
                flow_ctx["uuid"] = data["uuid"]
            if "fileIdList" in data and isinstance(data["fileIdList"], list):
                if data["fileIdList"]:
                    flow_ctx["fileId"] = data["fileIdList"][0]

        expect_fn_name = c.get("expect_fn")
        expect_match_fn = None
        if expect_fn_name:
            if expect_fn_name in EXPECT_FNS:
                expect_match_fn = EXPECT_FNS[expect_fn_name]
            elif expect_fn_name.startswith("exp_contains:"):
                keyword = expect_fn_name.split(":", 1)[1]
                expect_match_fn = exp_contains(keyword)

        record_case(results, case_id, api_name, method, path, case_type, desc,
                    req_params_str, expected_desc, http, biz, msg, expect_match_fn,
                    expect_fn_str=expect_fn_name)


# ── 主入口 ──────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Generic API test runner")
    parser.add_argument("--output", dest="output_dir", default=None,
                        help="项目目录 (必需)，示例: --output D:/test-output/项目名/")
    parser.add_argument("--config", dest="config_path", default=None,
                        help="Path to config.ini (default: 项目目录/config.ini)")
    parser.add_argument("--cases", dest="cases_json", action="append", default=None,
                        help="Path to cases JSON (can repeat, default: workspace/cases/*.json)")
    args = parser.parse_args()

    # 确定项目目录
    if not args.output_dir:
        print("[ERR] 请使用 --output 参数指定项目目录")
        print("       示例: python run_test.py --output D:/test-output/项目名/")
        sys.exit(1)

    ws = Path(args.output_dir)
    if not ws.exists():
        print(f"[ERR] 目录不存在: {ws}")
        sys.exit(1)

    # 加载 config
    cfg = configparser.ConfigParser()
    config_path = args.config_path or (ws / "config.ini" if ws else None)
    if config_path and Path(config_path).exists():
        cfg.read(Path(config_path), encoding="utf-8")

    project_name = cfg.get("project", "name", fallback="接口测试")
    base_url = cfg.get("api", "base_url", fallback="")
    mobile = cfg.get("auth", "mobile", fallback=None)
    timeout = int(cfg.get("options", "timeout", fallback="30") or 30)

    if not base_url:
        print("[ERR] config.ini 中未配置 api.base_url")
        sys.exit(1)

    # 解析 results 目录
    if ws:
        results_dir = ws / "test_results"
    else:
        results_dir = DEFAULT_RESULTS_DIR
    results_dir.mkdir(parents=True, exist_ok=True)

    # 加载用例文件
    if args.cases_json:
        case_files = [Path(p) for p in args.cases_json]
    else:
        cases_dir = ws / "cases" if ws else Path("cases")
        case_files = sorted(cases_dir.glob("*.json")) if cases_dir.exists() else []

    if not case_files:
        print("[ERR] 未找到用例文件，请指定 --cases 或在 workspace/cases/ 下放置 *.json")
        sys.exit(1)

    # 执行
    start_ts = datetime.now()
    print(f"=== 开始测试 {project_name} @ {start_ts.strftime('%Y-%m-%d %H:%M:%S')} ===")
    print(f"服务地址: {base_url}")
    print(f"用例文件: {', '.join(str(f.name) for f in case_files)}")

    # Setup: 尝试获取真实 uuid（通用兜底，找不到则尝试创建测试数据）
    print("\n[SETUP] 尝试获取真实 uuid 以便后续用例复用...")
    real_uuid = None
    real_file_id = None

    # 方式1：从分页查询获取
    for path_hint, params_hint in [
        ("/page", {"pageNum": 1, "pageSize": 5}),
        ("/list", {"pageNum": 1, "pageSize": 5}),
        ("/query", {"pageNum": 1, "pageSize": 5}),
    ]:
        http, biz, msg, data, _ = do_call("GET", path_hint,
                                           base_url=base_url, params=params_hint,
                                           mobile=mobile, timeout=timeout)
        if isinstance(data, dict):
            records = data.get("records") or []
            for rec in records:
                if rec.get("uuid"):
                    real_uuid = rec["uuid"]
                    break
            if not real_uuid:
                for rec in records:
                    fl = rec.get("fileIdList") or []
                    if fl:
                        real_file_id = fl[0] if isinstance(fl[0], str) else None
                        if real_file_id:
                            break
            if real_uuid or real_file_id:
                print(f"[SETUP] 从 {path_hint} 获取到数据")
                break

    # 方式2：如果查询不到 uuid，尝试创建一条测试数据
    if not real_uuid:
        print("[SETUP] 分页无数据，尝试创建测试数据获取 uuid...")
        # 尝试常见的创建接口
        for path_hint in ["/saveContractPreAudit", "/create", "/add"]:
            http, biz, msg, data, _ = do_call("POST", path_hint,
                                               base_url=base_url,
                                               params=None,
                                               body={"purchaseContractName": "SETUP自动创建测试合同", "contractBudgetAmount": 10000},
                                               mobile=mobile, timeout=timeout)
            if http == 200 and biz == 200 and data:
                if isinstance(data, dict) and data.get("uuid"):
                    real_uuid = data["uuid"]
                    print(f"[SETUP] 通过 POST {path_hint} 创建测试数据获取 uuid={real_uuid}")
                    break
                # 也可能在 data.data 或其他层级
                for key in ["data", "result"]:
                    if isinstance(data.get(key), dict) and data[key].get("uuid"):
                        real_uuid = data[key]["uuid"]
                        print(f"[SETUP] 通过 POST {path_hint} 创建测试数据获取 uuid={real_uuid}")
                        break
            if real_uuid:
                break

    print(f"[SETUP] real_uuid={real_uuid}, real_file_id={real_file_id}")

    results = []
    tc_idx = [0]

    for case_file in case_files:
        with open(case_file, "r", encoding="utf-8") as f:
            case_data = json.load(f)

        # 支持两种格式：
        # 1. 直接是列表：[{case}, {case}, ...]
        # 2. 带 flow 标记：{ "single": [...], "flows": [ [...], [...] ] }
        if isinstance(case_data, list):
            # 识别业务流程（case_type == "业务流程"）
            singles = [c for c in case_data if c.get("case_type", "") != "业务流程"]
            flows = []
            current_flow = []
            for c in case_data:
                if c.get("case_type", "") == "业务流程":
                    # 遇到 Step1 说明是新车流程开始，保存旧的
                    if current_flow and "Step1:" in c.get("desc", ""):
                        flows.append(current_flow)
                        current_flow = []
                    current_flow.append(c)
                else:
                    if current_flow:
                        flows.append(current_flow)
                        current_flow = []
            if current_flow:
                flows.append(current_flow)

            print(f"\n[LOAD] {case_file.name}: {len(singles)} 单接口用例, {len(flows)} 条业务流程")

            for c in singles:
                execute_single_case(c, results, tc_idx, base_url, mobile, timeout,
                                    real_uuid, real_file_id)

            for flow_cases in flows:
                # 校验业务流程 api_name：同一流程内各 step 应填写各自实际调用的接口名
                api_names = [c.get("api_name", "") for c in flow_cases]
                if len(set(api_names)) == 1 and api_names[0] != "":
                    print(f"[WARN] {case_file.name} 某条业务流程所有步骤 api_name 均相同（{api_names[0]}），"
                          "请确认每个步骤是否填写了各自调用的实际接口名称，而非整条流程名称。"
                          "正确示例：Step1=用户登录, Step2=创建订单, Step3=查询订单")
                execute_flow(flow_cases, results, tc_idx, base_url, mobile, timeout,
                             real_uuid, real_file_id)

        elif isinstance(case_data, dict):
            # { "single": [...], "flows": [[...], [...]] }
            singles = case_data.get("single", [])
            flows = case_data.get("flows", [])

            print(f"\n[LOAD] {case_file.name}: {len(singles)} 单接口用例, {len(flows)} 条业务流程")

            for c in singles:
                execute_single_case(c, results, tc_idx, base_url, mobile, timeout,
                                    real_uuid, real_file_id)

            for flow in flows:
                execute_flow(flow, results, tc_idx, base_url, mobile, timeout,
                             real_uuid, real_file_id)

    total = len(results)
    passed = sum(1 for c in results if c["result"] == "PASS")
    failed = total - passed
    print(f"\n\n====== 结果汇总 ======")
    print(f"共 {total} 条用例：PASS={passed}, FAIL={failed}, 通过率 {passed/total*100:.1f}%")

    end_ts = datetime.now()
    ts = end_ts.strftime("%Y%m%d_%H%M%S")
    out = {
        "project": project_name,
        "base_url": base_url,
        "start_time": start_ts.strftime("%Y-%m-%d %H:%M:%S"),
        "end_time": end_ts.strftime("%Y-%m-%d %H:%M:%S"),
        "duration_seconds": round((end_ts - start_ts).total_seconds(), 1),
        "cases": results,
    }
    result_file = results_dir / f"{project_name}测试结果_{ts}.json"
    with open(result_file, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=2)
    latest = results_dir / "latest_results.json"
    with open(latest, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=2)
    print(f"\n[OK] 结果已写入: {result_file}")
    print(f"[OK] 副本: {latest}")

    # 自动生成 Excel 和 Word 报告（仅在有明确 workspace 时）
    if ws:
        import subprocess
        scripts_dir = Path(__file__).parent
        for script_name in ("gen_excel.py", "gen_report.py"):
            script_path = scripts_dir / script_name
            if script_path.exists():
                try:
                    r = subprocess.run(
                        [sys.executable, str(script_path), "--output", str(ws)],
                        capture_output=True, text=True, encoding="utf-8", errors="replace"
                    )
                    if r.returncode == 0:
                        out = (r.stdout or "").strip().split("\n")
                        print(out[-1] if out else f"[OK] {script_name} 已完成")
                    else:
                        print(f"[WARN] {script_name} 生成失败: {(r.stderr or '').strip()}")
                except Exception as e:
                    print(f"[WARN] {script_name} 生成异常: {e}")
            else:
                print(f"[WARN] {script_path} 不存在，跳过")


if __name__ == "__main__":
    main()
