# -*- coding: utf-8 -*-
"""
通用接口测试执行骨架
====================
从 cases/*.json 读取用例定义，逐条执行并输出 test_results/JSON。
支持断点续跑：中断后可从断点继续执行。

用法:
    python run_test.py --output D:/test-output/{项目名}/
    python run_test.py --output D:/test-output/{项目名}/ --resume    # 继续上次中断的测试
    python run_test.py --output D:/test-output/{项目名}/ --discard   # 放弃进度，重新开始

用例 JSON 格式见 references/case-design.md。
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
            timeout=30, mobile=None, token=None, app_code=None):
    """执行 HTTP 调用，返回 (http_status, biz_code, msg, data, raw_text)。"""
    url = base_url + path
    if headers is None:
        headers = {}
    if mobile and "mobile" not in headers:
        headers["mobile"] = str(mobile)
    if token and "Authorization" not in headers:
        headers["Authorization"] = f"Bearer {token}"
    if app_code and "appCode" not in headers:
        headers["appCode"] = str(app_code)
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

def exp_param_validation(http, biz, msg):
    """期望系统正确处理参数校验：返回明确的参数错误提示，而非内部异常(biz 500)"""
    # 内部异常 biz=500 直接判定失败
    if biz == 500:
        return False, f"系统未校验参数，异常穿透返回biz=500（msg='{(msg or '')[:60]}'）"
    # HTTP 非200 也是失败
    if http != 200:
        return False, f"HTTP{http}，期望参数校验错误"
    # 检查 msg 是否包含参数校验关键词
    validation_keywords = ["参数", "长度", "格式", "不能", "超限", "非法", "无效", "不合法", "限制", "超过", "为空", "必填", "不能为空", "请输入", "请选择", "长度不能", "格式不正确"]
    msg_text = msg or ""
    has_validation_hint = any(kw in msg_text for kw in validation_keywords)
    if biz != 200 and has_validation_hint:
        return True, f"系统已校验参数，返回明确提示：{msg_text[:50]}"
    if biz != 200 and not has_validation_hint:
        return False, f"biz={biz}但无明确参数提示（msg='{msg_text[:50]}'）"
    # biz=200 也算通过（某些系统可能用返回数据中的字段表示错误）
    if biz == 200 and has_validation_hint:
        return True, f"系统已校验参数（msg包含提示）"
    return False, f"系统未返回明确的参数校验错误（biz={biz}, msg='{msg_text[:50]}'）"

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
    "exp_param_validation": exp_param_validation,
}


# ── 学习模式：自动识别假失败并生成覆盖规则 ────────────────────────────────────

def learn_expect_overrides(results, ws):
    """
    分析测试结果，识别假失败模式，生成期望覆盖规则。

    识别两种假失败：
    1. 假通过（False Pass）：expect_fn 太宽松，导致 biz!=200 也显示 PASS
       - 正向测试用例返回 biz 500 但使用 exp_ok_or_empty_data
       - 应该改为 exp_ok，让真正的错误暴露出来

    2. 假失败（False Fail）：expect_fn 太严格，导致 biz=200 也显示 FAIL
       - 期望业务失败但实际成功了（可能是正常业务逻辑）
       - 例如：删除不存在的资源返回200是幂等的正常行为
    """
    false_passes = []  # 假通过：expect_fn 太宽松
    false_fails = []   # 假失败：expect_fn 太严格
    system_bugs = []   # 真正的系统bug（不要掩盖）

    for case in results:
        http = case["http_status"]
        biz = case["biz_code"]
        msg = case.get("actual_msg", "")
        expect_fn = case.get("expect_fn", "")
        api_name = case.get("api_name", "")
        case_type = case.get("case_type", "")
        desc = case.get("desc", "")
        result = case.get("result", "")
        req_params = case.get("request_params", "")

        # ── 假通过检测：biz!=200 但显示 PASS ─────────────────────────────
        # 这是最严重的问题：真正的错误被掩盖了
        if http == 200 and biz != 200 and result == "PASS":
            # 正向测试用例用 exp_ok_or_empty_data 是错误的
            if "正向测试" in case_type and "exp_ok_or_empty_data" in expect_fn:
                false_passes.append({
                    "api_name": api_name,
                    "case_type": case_type,
                    "desc": desc,
                    "biz": biz,
                    "msg": msg[:80],
                    "suggested_fn": "exp_ok",
                    "reason": f"正向测试期望业务成功(biz=200)，但返回 biz={biz}。"
                               "biz!=200 说明系统存在问题，不应被 exp_ok_or_empty_data 掩盖。"
                })
            # 边界/安全测试用 exp_ok_or_empty_data 也可能掩盖问题
            elif ("边界测试" in case_type or "安全测试" in case_type) and "exp_ok_or_empty_data" in expect_fn:
                # 如果是 biz=500（数据库/系统异常），这是系统bug，不是假失败
                if biz == 500:
                    system_bugs.append({
                        "api_name": api_name,
                        "case_type": case_type,
                        "desc": desc,
                        "biz": biz,
                        "msg": msg[:80],
                        "reason": "biz=500 通常是系统内部错误，可能是真实的bug"
                    })
                else:
                    false_passes.append({
                        "api_name": api_name,
                        "case_type": case_type,
                        "desc": desc,
                        "biz": biz,
                        "msg": msg[:80],
                        "suggested_fn": "exp_ok",
                        "reason": f"用例返回 biz={biz}，应用 exp_ok 替代 exp_ok_or_empty_data"
                    })

        # ── 假失败检测：期望失败但实际成功了 ─────────────────────────────
        if result == "FAIL" and expect_fn == "exp_biz_fail" and http == 200 and biz == 200:
            # 删除不存在资源的操作返回200是正常幂等行为
            if "删除" in api_name and ("不存在" in desc or "不存在" in req_params):
                false_fails.append({
                    "api_name": api_name,
                    "case_type": case_type,
                    "desc": desc,
                    "suggested_fn": "exp_ok",
                    "reason": "删除不存在的资源返回200是正常RESTful幂等设计"
                })
            # 某些详情查询接口对不存在的uuid返回空数据是正常行为
            elif "不存在" in desc and biz == 200:
                false_fails.append({
                    "api_name": api_name,
                    "case_type": case_type,
                    "desc": desc,
                    "suggested_fn": "exp_ok_or_empty_data",
                    "reason": "查询接口对不存在的uuid返回空数据是正常业务逻辑"
                })

    # 输出分析结果
    print("\n" + "=" * 60)
    print("[LEARN] 测试结果分析报告")
    print("=" * 60)

    if system_bugs:
        print(f"\n⚠️  发现 {len(system_bugs)} 个可能的系统 bug（不要掩盖！）:")
        for i, bug in enumerate(system_bugs, 1):
            print(f"  {i}. [{bug['api_name']}/{bug['case_type']}] {bug['desc'][:40]}")
            print(f"     biz={bug['biz']} | msg={bug['msg'][:50]}")

    if false_passes:
        print(f"\n✗ 发现 {len(false_passes)} 个假通过（expect_fn 太宽松，掩盖了真实错误）:")
        for i, fp in enumerate(false_passes, 1):
            print(f"  {i}. [{fp['api_name']}/{fp['case_type']}] {fp['desc'][:40]}")
            print(f"     当前: exp_ok_or_empty_data -> 建议: {fp['suggested_fn']}")
            print(f"     原因: {fp['reason']}")

    if false_fails:
        print(f"\n✗ 发现 {len(false_fails)} 个假失败（expect_fn 太严格，正常行为被判失败）:")
        for i, ff in enumerate(false_fails, 1):
            print(f"  {i}. [{ff['api_name']}/{ff['case_type']}] {ff['desc'][:40]}")
            print(f"     当前: exp_biz_fail -> 建议: {ff['suggested_fn']}")
            print(f"     原因: {ff['reason']}")

    # 只修复假失败（expect_fn 太严格导致正常行为被判失败）
    # 不修复假通过（expect_fn 太宽松），因为那会掩盖真正的系统问题
    overrides = []
    seen_patterns = set()

    for ff in false_fails:
        pattern = (ff["suggested_fn"], ff["api_name"], ff["case_type"])
        if pattern not in seen_patterns:
            seen_patterns.add(pattern)
            overrides.append({
                "api_name_pattern": ff["api_name"],
                "case_type_pattern": ff["case_type"],
                "desc_patterns": ["不存在"],
                "override": {
                    "expect_fn": ff["suggested_fn"],
                    "reason": ff["reason"]
                }
            })

    if not overrides:
        print("\n[LEARN] 未发现需要调整的假失败模式")
        if false_passes:
            print("       （注：发现假通过用例，但 biz!=200 可能是真实系统问题，不建议掩盖）")
        return None

    # 生成规则文件
    rules_dir = ws / "rules"
    rules_dir.mkdir(exist_ok=True)
    override_file = rules_dir / "expect_fn_overrides.json"

    rule_content = {
        "version": "1.0",
        "description": "期望函数覆盖规则 - 由 --learn 模式自动生成（仅修复假失败，不掩盖真实错误）",
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "overrides": overrides
    }

    with open(override_file, "w", encoding="utf-8") as f:
        json.dump(rule_content, f, ensure_ascii=False, indent=2)

    print(f"\n[LEARN] 已生成覆盖规则: {override_file}")
    print(f"       仅修复 {len(overrides)} 个假失败（不掩盖系统bug）")

    return override_file


# ── 断点续跑进度管理 ─────────────────────────────────────────────────────────

PROGRESS_FILE = "progress.json"


def load_progress(results_dir):
    """加载进度文件，返回 None 如果不存在或不匹配"""
    progress_path = results_dir / PROGRESS_FILE
    if not progress_path.exists():
        return None
    try:
        with open(progress_path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def save_progress(results_dir, session_id, total, completed, next_index):
    """保存进度"""
    progress_path = results_dir / PROGRESS_FILE
    progress = {
        "session_id": session_id,
        "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "total": total,
        "completed": completed,
        "next_index": next_index,
    }
    try:
        with open(progress_path, "w", encoding="utf-8") as f:
            json.dump(progress, f, ensure_ascii=False, indent=2)
    except Exception:
        pass


def remove_progress(results_dir):
    """删除进度文件"""
    progress_path = results_dir / PROGRESS_FILE
    if progress_path.exists():
        try:
            progress_path.unlink()
        except Exception:
            pass


def build_case_key(case):
    """生成用例唯一标识（用于判断是否已执行）"""
    path = case.get("path", "")
    method = case.get("method", "")
    desc = case.get("desc", "")
    return f"{method}:{path}:{desc[:30]}"


def check_resume(completed, case):
    """检查用例是否已执行过"""
    key = build_case_key(case)
    for item in completed:
        if item.get("key") == key:
            return True, item.get("result")
    return False, None


# ── 用例记录 ────────────────────────────────────────────────────────────────

def record_case(results, case_id, api_name, method, path, case_type, desc,
                req_params_str, expected_desc, http, biz, actual_msg,
                expect_match_fn=None, expect_fn_str=None, raw_txt=None):
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

    # 当 biz != 200 且 msg 为空时，尝试从 raw_txt 提取原因
    display_msg = actual_msg
    if not display_msg and biz != 200 and raw_txt:
        try:
            import json as _json
            j = _json.loads(raw_txt)
            # 尝试从响应体中提取有意义的字段
            for field in ("msg", "message", "error", "reason", "data"):
                if field in j and j[field]:
                    display_msg = str(j[field])[:200]
                    break
            if not display_msg:
                display_msg = raw_txt[:200].strip()
        except Exception:
            display_msg = (raw_txt or "")[:200].strip()

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
        "actual_msg": (display_msg or "")[:200],
        "result": "PASS" if passed else "FAIL",
        "reason": reason,
    })
    status_flag = "✓" if passed else "✗"
    print(f"[{status_flag}] {case_id:>6} {api_name}/{case_type}: {desc[:40]} -> HTTP {http} biz {biz} {('| ' + display_msg[:50]) if display_msg and biz != 200 else ''}")


# ── 从 JSON 执行单条用例 ───────────────────────────────────────────────────

def execute_single_case(c, results, tc_idx, base_url, mobile, timeout, token=None, app_code=None,
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
    http, biz, msg, data, txt = do_call(
        method, path, base_url=base_url, params=params, body=body,
        timeout=timeout, mobile=mobile, token=token, app_code=app_code
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
                expect_fn_str=expect_fn_name, raw_txt=txt)

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


def execute_flow(cases, results, tc_idx, base_url, mobile, timeout, token=None, app_code=None,
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
        http, biz, msg, data, txt = do_call(
            method, path, base_url=base_url, params=params, body=body,
            timeout=timeout, mobile=mobile, token=token, app_code=app_code
        )

        # 保存上下文（提取 uuid 等，支持多种常见 ID 字段名）
        if data and isinstance(data, dict):
            # 提取 uuid（支持多种常见字段名）
            for id_field in ["uuid", "id", "contractUuid", "preauditId"]:
                if id_field in data and data[id_field]:
                    flow_ctx["uuid"] = str(data[id_field])
                    # 同时设置 id 别名以便不同命名习惯的 API
                    flow_ctx["id"] = str(data[id_field])
                    break
            # 提取 fileIdList
            if "fileIdList" in data and isinstance(data["fileIdList"], list):
                if data["fileIdList"]:
                    flow_ctx["fileId"] = data["fileIdList"][0]
            # 也从 fileIds 提取
            if "fileIds" in data and isinstance(data["fileIds"], list):
                if data["fileIds"]:
                    flow_ctx["fileId"] = data["fileIds"][0]
            # 从 data 字段递归提取（有些接口返回 {success, code, msg, data: {uuid: xxx}}）
            if "data" in data and isinstance(data["data"], dict):
                inner = data["data"]
                for id_field in ["uuid", "id", "contractUuid", "preauditId"]:
                    if id_field in inner and inner[id_field]:
                        flow_ctx["uuid"] = str(inner[id_field])
                        flow_ctx["id"] = str(inner[id_field])
                        break

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
                    expect_fn_str=expect_fn_name, raw_txt=txt)


# ── 主入口 ──────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Generic API test runner")
    parser.add_argument("--output", dest="output_dir", default=None,
                        help="项目目录 (必需)，示例: --output D:/test-output/项目名/")
    parser.add_argument("--config", dest="config_path", default=None,
                        help="Path to config.ini (default: 项目目录/config.ini)")
    parser.add_argument("--cases", dest="cases_json", action="append", default=None,
                        help="Path to cases JSON (can repeat, default: workspace/cases/*.json)")
    parser.add_argument("--resume", action="store_true",
                        help="继续上次中断的测试（从断点继续）")
    parser.add_argument("--discard", action="store_true",
                        help="放弃进度，重新开始测试")
    parser.add_argument("--learn", action="store_true",
                        help="学习失败模式，生成期望函数覆盖规则（用于消除假失败）")
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
    token = cfg.get("auth", "token", fallback=None)
    app_code = cfg.get("auth", "app_code", fallback=None)
    timeout = int(cfg.get("options", "timeout", fallback="30") or 30)

    if not base_url:
        print("[ERR] config.ini 中未配置 api.base_url")
        sys.exit(1)

    # 解析 results 目录（与 gen_report.py 保持一致，直接输出到 ws）
    if ws:
        results_dir = ws / "test_results"
    else:
        results_dir = DEFAULT_RESULTS_DIR
    # 创建 test_results 和 reports 目录
    if ws:
        reports_dir = ws / "reports"
        reports_dir.mkdir(parents=True, exist_ok=True)
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

    # ── 断点续跑逻辑 ──────────────────────────────────────────────────────────
    resume_mode = False
    if args.discard:
        remove_progress(results_dir)
        print("[INFO] 已放弃上次进度，重新开始测试")
    elif args.resume:
        progress = load_progress(results_dir)
        if progress:
            print(f"[RESUME] 检测到上次进度: {progress.get('timestamp')}")
            print(f"         已完成: {len(progress.get('completed', []))}/{progress.get('total', 0)} 条")
            resume_mode = True
        else:
            print("[WARN] 未检测到进度文件，将重新开始测试")
    else:
        progress = load_progress(results_dir)
        if progress:
            print(f"[INFO] 检测到上次进度: {progress.get('timestamp')}")
            print(f"       已完成: {len(progress.get('completed', []))}/{progress.get('total', 0)} 条")
            print("       继续执行请使用 --resume，放弃进度请使用 --discard")
            print("       (5秒后继续执行，Ctrl+C 中断)")
            try:
                import time
                time.sleep(5)
            except KeyboardInterrupt:
                print("\n[ABORT] 已取消执行")
                sys.exit(0)
            resume_mode = True

    # 执行
    start_ts = datetime.now()
    print(f"=== 开始测试 {project_name} @ {start_ts.strftime('%Y-%m-%d %H:%M:%S')} ===")
    print(f"服务地址: {base_url}")
    print(f"用例文件: {', '.join(str(f.name) for f in case_files)}")

    # Setup: 尝试获取真实 uuid（通用兜底）
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
                                           mobile=mobile, token=token, app_code=app_code, timeout=timeout)
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

    # 方式2：如果查询不到，尝试常见的创建接口路径（通用）
    if not real_uuid:
        print("[SETUP] 分页无数据，尝试创建测试数据...")
        for path_hint in ["/save", "/create", "/add"]:
            http, biz, msg, data, _ = do_call("POST", path_hint,
                                               base_url=base_url,
                                               params=None,
                                               body={"name": "SETUP自动创建测试数据", "title": "测试标题"},
                                               mobile=mobile, token=token, app_code=app_code, timeout=timeout)
            if http == 200 and biz == 200 and data:
                if isinstance(data, dict) and data.get("uuid"):
                    real_uuid = data["uuid"]
                    print(f"[SETUP] 通过 POST {path_hint} 创建测试数据获取 uuid={real_uuid}")
                    break
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
    session_id = datetime.now().strftime("%Y%m%d_%H%M%S")

    # 断点续跑：加载已完成的用例结果
    completed_cases = {}  # key -> result dict
    total_planned = 0
    if resume_mode:
        progress = load_progress(results_dir)
        if progress:
            for item in progress.get("completed", []):
                key = item.get("key")
                if key:
                    completed_cases[key] = item
            total_planned = progress.get("total", 0)
            # 从已完成的results中恢复
            for item in progress.get("completed", []):
                if "result_obj" in item:
                    results.append(item["result_obj"])
                    tc_idx[0] = max(tc_idx[0], int(item.get("tc_idx", 0)))
            print(f"[RESUME] 已加载 {len(completed_cases)} 条已完成的用例结果")

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
                case_key = build_case_key(c)
                if resume_mode and case_key in completed_cases:
                    item = completed_cases[case_key]
                    tc_idx[0] += 1
                    results.append(item["result_obj"])
                    print(f"[SKIP] TC{tc_idx[0]:03d} {c.get('api_name','')}/{c.get('case_type','')}: {c.get('desc','')[:40]} -> (已跳过)")
                    continue
                execute_single_case(c, results, tc_idx, base_url, mobile, timeout,
                                    token=token, app_code=app_code,
                                    setup_uuid=real_uuid, setup_file_id=real_file_id)
                # 保存进度
                if resume_mode:
                    key = build_case_key(c)
                    last_result = results[-1]
                    completed_cases[key] = {
                        "key": key,
                        "result": last_result["result"],
                        "tc_idx": tc_idx[0],
                        "result_obj": last_result,
                    }
                    save_progress(results_dir, session_id, len(case_data), list(completed_cases.values()), tc_idx[0])

            for flow_cases in flows:
                # 校验业务流程 api_name：同一流程内各 step 应填写各自实际调用的接口名
                api_names = [c.get("api_name", "") for c in flow_cases]
                if len(set(api_names)) == 1 and api_names[0] != "":
                    print(f"[WARN] {case_file.name} 某条业务流程所有步骤 api_name 均相同（{api_names[0]}），"
                          "请确认每个步骤是否填写了各自调用的实际接口名称，而非整条流程名称。"
                          "正确示例：Step1=用户登录, Step2=创建订单, Step3=查询订单")
                # 业务流程整体判断是否跳过
                flow_key = build_case_key(flow_cases[0]) if flow_cases else ""
                if resume_mode and flow_key in completed_cases:
                    item = completed_cases[flow_key]
                    for fc in flow_cases:
                        tc_idx[0] += 1
                        results.append(item["result_obj"])
                        print(f"[SKIP] TC{tc_idx[0]:03d} {fc.get('api_name','')}/{fc.get('case_type','')}: {fc.get('desc','')[:40]} -> (流程已跳过)")
                    continue
                execute_flow(flow_cases, results, tc_idx, base_url, mobile, timeout,
                             token=token, app_code=app_code,
                             setup_uuid=real_uuid, setup_file_id=real_file_id)
                # 保存进度（流程整体算一个完成单元）
                if resume_mode:
                    last_result = results[-1]
                    completed_cases[flow_key] = {
                        "key": flow_key,
                        "result": last_result["result"],
                        "tc_idx": tc_idx[0],
                        "result_obj": last_result,
                    }
                    save_progress(results_dir, session_id, len(case_data), list(completed_cases.values()), tc_idx[0])

        elif isinstance(case_data, dict):
            # { "single": [...], "flows": [[...], [...]] }
            singles = case_data.get("single", [])
            flows = case_data.get("flows", [])

            print(f"\n[LOAD] {case_file.name}: {len(singles)} 单接口用例, {len(flows)} 条业务流程")

            for c in singles:
                case_key = build_case_key(c)
                if resume_mode and case_key in completed_cases:
                    item = completed_cases[case_key]
                    tc_idx[0] += 1
                    results.append(item["result_obj"])
                    print(f"[SKIP] TC{tc_idx[0]:03d} {c.get('api_name','')}/{c.get('case_type','')}: {c.get('desc','')[:40]} -> (已跳过)")
                    continue
                execute_single_case(c, results, tc_idx, base_url, mobile, timeout,
                                    token=token, app_code=app_code,
                                    setup_uuid=real_uuid, setup_file_id=real_file_id)

            for flow in flows:
                execute_flow(flow, results, tc_idx, base_url, mobile, timeout,
                             token=token, app_code=app_code,
                             setup_uuid=real_uuid, setup_file_id=real_file_id)

    # 清除进度文件
    remove_progress(results_dir)

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

    # 学习模式：分析失败用例，生成期望覆盖规则
    if args.learn and ws:
        learned_file = learn_expect_overrides(results, ws)
        if learned_file:
            print(f"[LEARN] 期望覆盖规则已生成: {learned_file}")
            print("       下次生成用例时会自动应用这些规则，消除假失败")

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
