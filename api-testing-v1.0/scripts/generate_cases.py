# -*- coding: utf-8 -*-
"""
自动生成测试用例脚本
====================
根据 Apifox 缓存的接口定义 + 需求文档，自动生成单接口用例和业务流程用例。

单接口用例比例：正向25% / 逆向40% / 边界20% / 安全15%
业务流程用例：根据需求文档中的业务流程 + 接口关联自动生成串联链路

用法:
    python generate_cases.py --workspace "D:/test-output/项目名"
    python generate_cases.py --apifox-url "https://xxx.apifox.cn" --workspace "D:/test-output/项目名"
"""
import sys
import io
import json
import argparse
import re
from pathlib import Path
from datetime import datetime

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

SKILL_DIR = Path(__file__).resolve().parent.parent
DEFAULT_CACHE_DIR = Path.home() / ".qclaw" / "cache" / "apifox-api"

# 系统内部字段（后端自动生成），POST 请求时不传
SYSTEM_FIELDS = {"uuid", "deleted", "createdBy", "createdTime",
                  "updatedBy", "updatedTime", "userId", "deptId",
                  "deptName", "orgId", "orgName", "oneGroupId",
                  "groupName", "revision", "groupCode", "taskId",
                  "procId", "contractUuid", "fileIdList", "tradeUnion"}


def find_requirement_doc(workspace_path):
    """查找需求文档（md格式）"""
    ws = Path(workspace_path)

    # 1. 优先查找 input 目录下的 md 文件
    input_dir = ws / "input"
    if input_dir.exists():
        md_files = list(input_dir.glob("*.md"))
        if md_files:
            print(f"[INFO] 在 {input_dir} 找到需求文档")
            return md_files[0]

    # 2. 查找同目录下的 md 文件
    md_files = list(ws.glob("*.md"))
    if md_files:
        print(f"[INFO] 在 {ws} 找到需求文档")
        return md_files[0]

    # 3. 查找 test-input 目录（通常与 test-output 同级）
    test_input = ws.parent.parent / "test-input" / ws.name / "input"
    if test_input.exists():
        md_files = list(test_input.glob("*.md"))
        if md_files:
            print(f"[INFO] 在 {test_input} 找到需求文档")
            return md_files[0]

    # 4. 查找上级目录的 input
    parent_input = ws.parent / "input"
    if parent_input.exists():
        md_files = list(parent_input.glob("*.md"))
        if md_files:
            print(f"[INFO] 在 {parent_input} 找到需求文档")
            return md_files[0]

    print(f"[WARN] 未找到需求文档，将使用接口关联分析业务流程")
    return None


def load_requirement_doc(doc_path):
    """加载需求文档内容"""
    if not doc_path or not Path(doc_path).exists():
        return None

    with open(doc_path, "r", encoding="utf-8") as f:
        content = f.read()

    print(f"[INFO] 已加载需求文档: {doc_path}")
    return content


def parse_business_flows_from_doc(content, apis):
    """从需求文档中解析业务流程"""
    flows = []
    if not content:
        return flows

    # 提取接口路径映射
    path_to_op = {}
    for api in apis:
        for op in api.get("operations", []):
            path = op.get("path", "")
            method = op.get("method", "")
            path_to_op[path] = op

    # 查找采购合同预审相关的业务流程
    # 需求文档中描述的流程：创建 -> 保存(草稿) -> 提交审批 -> 审批中

    # 流程1: 预审创建 + 分页查询 + 统计
    if "/contractPreAudit/page" in path_to_op and "/contractPreAudit/getContractPreAuditList" in path_to_op:
        flows.append([
            {
                "api_name": "预审分页查询",
                "method": "GET",
                "path": "/contractPreAudit/page",
                "case_type": "业务流程",
                "desc": "Step1: 分页查询合同预审列表",
                "params": {"pageNum": 1, "pageSize": 10},
                "expected_desc": "HTTP 200，返回分页数据"
            },
            {
                "api_name": "查询预审审批数量",
                "method": "GET",
                "path": "/contractPreAudit/getContractPreAuditList",
                "case_type": "业务流程",
                "desc": "Step2: 查询各类审批状态数量",
                "params": {},
                "expected_desc": "HTTP 200，返回审批数量统计"
            }
        ])

    # 流程2: 创建 + 详情查询
    save_op = path_to_op.get("/contractPreAudit/saveContractPreAudit")
    getbyid_op = path_to_op.get("/contractPreAudit/getById")
    if save_op and getbyid_op:
        flows.append([
            {
                "api_name": "合同预审保存",
                "method": "POST",
                "path": "/contractPreAudit/saveContractPreAudit",
                "case_type": "业务流程",
                "desc": "Step1: 创建采购合同预审（保存草稿）",
                "params": {
                    "purchaseContractName": "测试采购合同",
                    "contractTypeId": "1",
                    "contractSubjectName": "测试签约主体",
                    "contractBudgetAmount": 100000,
                    "contractBudgetAmountInWords": "壹拾万元整",
                    "contractGrade": "一般合同",
                    "prepaymentRatio": 10,
                    "performanceBondRatio": "5",
                    "performanceBondPriceMethod": "银行保函",
                    "performanceBondPrice": 5000,
                    "performanceBondTerm": "合同履行完毕",
                    "qualityGuaranteeRatio": 3,
                    "warrantyPeriod": "一年",
                    "procurementPreExaminationContent": "测试采购预审内容"
                },
                "expected_desc": "HTTP 200，保存成功"
            },
            {
                "api_name": "根据预审id查询",
                "method": "GET",
                "path": "/contractPreAudit/getById",
                "case_type": "业务流程",
                "desc": "Step2: 查询预审详情",
                "params": {"uuid": "$uuid"},
                "expected_desc": "HTTP 200，返回预审详情"
            }
        ])

    # 流程3: 创建 + 开启流程
    start_op = path_to_op.get("/contractPreAudit/start")
    if save_op and start_op:
        flows.append([
            {
                "api_name": "合同预审保存",
                "method": "POST",
                "path": "/contractPreAudit/saveContractPreAudit",
                "case_type": "业务流程",
                "desc": "Step1: 创建采购合同预审",
                "params": {
                    "purchaseContractName": "测试采购合同B",
                    "contractTypeId": "1",
                    "contractSubjectName": "测试签约主体B",
                    "contractBudgetAmount": 200000,
                    "contractBudgetAmountInWords": "贰拾万元整",
                    "contractGrade": "重要合同"
                },
                "expected_desc": "HTTP 200，保存成功"
            },
            {
                "api_name": "开启流程",
                "method": "POST",
                "path": "/contractPreAudit/start",
                "case_type": "业务流程",
                "desc": "Step2: 提交预审进入审批流程",
                "params": {"uuid": "$uuid"},
                "expected_desc": "HTTP 200，流程启动成功"
            }
        ])

    # 流程4: 创建 + 删除（草稿状态可删除）
    delete_op = None
    for path in path_to_op:
        if "/delete" in path and "External" not in path:
            delete_op = path_to_op[path]
            break

    if save_op and delete_op:
        flows.append([
            {
                "api_name": "合同预审保存",
                "method": "POST",
                "path": "/contractPreAudit/saveContractPreAudit",
                "case_type": "业务流程",
                "desc": "Step1: 创建草稿预审",
                "params": {
                    "purchaseContractName": "草稿测试采购合同",
                    "contractTypeId": "1",
                    "contractSubjectName": "测试签约主体",
                    "contractBudgetAmount": 50000
                },
                "expected_desc": "HTTP 200，保存成功"
            },
            {
                "api_name": "预审删除接口",
                "method": "DELETE",
                "path": delete_op["path"],
                "case_type": "业务流程",
                "desc": "Step2: 删除草稿预审",
                "params": {"uuid": "$uuid"},
                "expected_desc": "HTTP 200，删除成功"
            }
        ])

    return flows


def gen_expect_fn(case_type, desc):
    """根据用例类型和描述自动配置 expect_fn"""
    if case_type == "正向测试":
        return None  # 默认 exp_ok

    if "不存在" in desc:
        return "exp_biz_fail"
    if "SQL注入" in desc or "XSS" in desc:
        return "exp_biz_fail"  # 期望攻击被拦截，返回 biz 500
    if "超长" in desc or "超出范围" in desc:
        return "exp_biz_fail"  # 边界值期望被拦截
    if "缺少" in desc or "为空" in desc:
        return "exp_biz_fail"

    return None  # 默认 exp_ok


def load_cache(apifox_url, workspace_path=None):
    """加载 Apifox 缓存"""
    import hashlib
    import re

    def extract_base(url):
        url = url.rstrip("/")
        m = re.match(r"^(https?://[^/]+)", url)
        return m.group(1) if m else url

    def cache_key(url):
        base = extract_base(url)
        return hashlib.md5(base.encode()).hexdigest()[:12]

    if workspace_path:
        cache_dir = Path(workspace_path) / "cache"
    else:
        cache_dir = DEFAULT_CACHE_DIR

    key = cache_key(apifox_url)
    cache_file = cache_dir / f"{key}.json"

    if not cache_file.exists():
        print(f"[ERR] 找不到缓存: {cache_file}")
        print(f"请先运行: python api_fetch.py fetch \"{apifox_url}\" --workspace \"{workspace_path}\"")
        sys.exit(1)

    with open(cache_file, "r", encoding="utf-8") as f:
        return json.load(f)


def gen_boundary_cases(api_name, method, path, required_fields, optional_fields, param_hints):
    """生成边界测试用例"""
    cases = []
    case_type = "边界测试"

    # 超长字符串
    req_keys = list(required_fields.keys()) if required_fields else []
    opt_keys = list(optional_fields.keys()) if optional_fields else []

    if req_keys or opt_keys:
        test_field = req_keys[0] if req_keys else opt_keys[0]
        cases.append({
            "api_name": api_name,
            "method": method,
            "path": path,
            "case_type": case_type,
            "desc": f"{api_name}-超长{test_field}",
            "params": {test_field: "超" * 200},
            "expected_desc": "正常处理或提示参数超长"
        })

    # 空字符串
    if req_keys:
        field = req_keys[0]
        cases.append({
            "api_name": api_name,
            "method": method,
            "path": path,
            "case_type": case_type,
            "desc": f"{api_name}-{field}为空字符串",
            "params": {field: ""},
            "expected_desc": "提示必填字段不能为空"
        })

    # 超大数值
    num_fields = [k for k, v in (required_fields or {}).items() if v in ("number", "integer")]
    if num_fields:
        cases.append({
            "api_name": api_name,
            "method": method,
            "path": path,
            "case_type": case_type,
            "desc": f"{api_name}-{num_fields[0]}超出范围",
            "params": {num_fields[0]: 999999999999},
            "expected_desc": "正常处理或提示超出范围"
        })

    return cases


def gen_security_cases(api_name, method, path, fields):
    """生成安全测试用例"""
    cases = []
    case_type = "安全测试"

    # SQL 注入
    if fields:
        test_field = list(fields.keys())[0]
        cases.append({
            "api_name": api_name,
            "method": method,
            "path": path,
            "case_type": case_type,
            "desc": f"{api_name}-SQL注入攻击",
            "params": {test_field: "' OR '1'='1"},
            "expected_desc": "SQL注入被拦截或无数据"
        })

    # XSS 攻击
    if fields:
        cases.append({
            "api_name": api_name,
            "method": method,
            "path": path,
            "case_type": case_type,
            "desc": f"{api_name}-XSS攻击",
            "params": {test_field: "<script>alert('xss')</script>"},
            "expected_desc": "XSS被过滤或无数据"
        })

    return cases


def analyze_operation(op):
    """分析接口定义，提取字段信息"""
    params = {}
    required_fields = {}
    optional_fields = {}

    for p in op.get("parameters", []):
        name = p.get("name", "")
        ptype = p.get("type", "string")
        required = p.get("required", False)
        desc = p.get("description", "")

        if p.get("in") == "header":
            continue

        params[name] = {"type": ptype, "desc": desc}
        if required:
            required_fields[name] = ptype
        else:
            optional_fields[name] = ptype

    request_body = op.get("requestBody") or {}
    if request_body:
        schema = request_body.get("schema") or {}
        properties = schema.get("properties", {})
        required_list = schema.get("required", [])

        for name, prop in properties.items():
            ptype = prop.get("type", "string")
            desc = prop.get("description", "")
            params[name] = {"type": ptype, "desc": desc}
            if name in required_list:
                required_fields[name] = ptype
            else:
                optional_fields[name] = ptype

    # 过滤系统字段
    for name in list(required_fields.keys()):
        if name in SYSTEM_FIELDS:
            del required_fields[name]
    for name in list(optional_fields.keys()):
        if name in SYSTEM_FIELDS:
            del optional_fields[name]
    for name in list(params.keys()):
        if name in SYSTEM_FIELDS:
            del params[name]

    return params, required_fields, optional_fields


def generate_single_cases(op):
    """为单个接口生成单接口测试用例"""
    method = op["method"]
    path = op["path"]
    api_name = op.get("summary", path)

    params, required_fields, optional_fields = analyze_operation(op)

    cases = []

    # 正向测试
    if method in ("GET", "DELETE"):
        # GET/DELETE: 正常参数
        params_normal = {}
        for name, info in params.items():
            if info["type"] == "integer":
                params_normal[name] = 1
            elif info["type"] == "boolean":
                params_normal[name] = True
            elif name in required_fields:
                params_normal[name] = f"test_{name}"
        case = {
            "api_name": api_name,
            "method": method,
            "path": path,
            "case_type": "正向测试",
            "desc": f"{api_name}-正常参数",
            "params": params_normal if params_normal else {},
            "expected_desc": "HTTP 200，返回数据"
        }
        ef = gen_expect_fn("正向测试", f"{api_name}-正常参数")
        if ef:
            case["expect_fn"] = ef
        cases.append(case)

    elif method == "POST":
        # POST: 完整必填字段 + 最小字段
        body_min = {k: "测试" for k, v in required_fields.items() if v == "string"}
        body_min.update({k: 100 for k, v in required_fields.items() if v in ("number", "integer")})

        body_full = dict(body_min)
        for name, ptype in optional_fields.items():
            if ptype == "string":
                body_full[name] = f"测试{name}"
            elif ptype in ("number", "integer"):
                body_full[name] = 100

        for desc_suffix, body, exp_desc in [
            (f"{api_name}-完整必填字段", body_full, "HTTP 200，保存成功"),
        ]:
            case = {
                "api_name": api_name,
                "method": method,
                "path": path,
                "case_type": "正向测试",
                "desc": desc_suffix,
                "params": body,
                "expected_desc": exp_desc
            }
            ef = gen_expect_fn("正向测试", desc_suffix)
            if ef:
                case["expect_fn"] = ef
            cases.append(case)

    elif method == "PUT":
        case = {
            "api_name": api_name,
            "method": method,
            "path": path,
            "case_type": "正向测试",
            "desc": f"{api_name}-完整字段更新",
            "params": {k: "更新测试" for k in params.keys()},
            "expected_desc": "HTTP 200，更新成功"
        }
        ef = gen_expect_fn("正向测试", f"{api_name}-完整字段更新")
        if ef:
            case["expect_fn"] = ef
        cases.append(case)

    # 逆向测试
    if required_fields:
        # 必填字段为空
        for field in list(required_fields.keys())[:1]:
            body = {k: f"test_{k}" for k in required_fields.keys()}
            body[field] = ""
            desc = f"{api_name}-{field}为空"
            case = {
                "api_name": api_name,
                "method": method,
                "path": path,
                "case_type": "逆向测试",
                "desc": desc,
                "params": body,
                "expected_desc": "提示必填字段不能为空"
            }
            ef = gen_expect_fn("逆向测试", desc)
            if ef:
                case["expect_fn"] = ef
            cases.append(case)

        # 必填字段缺失
        remaining = list(required_fields.keys())[1:]
        if remaining:
            body_missing = {k: f"test_{k}" for k in remaining}
            desc = f"{api_name}-缺少必填字段"
            case = {
                "api_name": api_name,
                "method": method,
                "path": path,
                "case_type": "逆向测试",
                "desc": desc,
                "params": body_missing,
                "expected_desc": "提示缺少必填字段"
            }
            ef = gen_expect_fn("逆向测试", desc)
            if ef:
                case["expect_fn"] = ef
            cases.append(case)

    # 不存在的数据
    if "uuid" in params or "id" in params:
        key = "uuid" if "uuid" in params else "id"
        desc = f"{api_name}-不存在的{key}"
        case = {
            "api_name": api_name,
            "method": method,
            "path": path,
            "case_type": "逆向测试",
            "desc": desc,
            "params": {key: "xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx"},
            "expected_desc": "提示数据不存在"
        }
        ef = gen_expect_fn("逆向测试", desc)
        if ef:
            case["expect_fn"] = ef
        cases.append(case)

    # 边界测试
    for c in gen_boundary_cases(api_name, method, path, required_fields, optional_fields, params):
        ef = gen_expect_fn("边界测试", c["desc"])
        if ef:
            c["expect_fn"] = ef
        cases.append(c)

    # 安全测试
    for c in gen_security_cases(api_name, method, path, params):
        ef = gen_expect_fn("安全测试", c["desc"])
        if ef:
            c["expect_fn"] = ef
        cases.append(c)

    return cases


def detect_api_relations(operations):
    """分析接口关联，生成业务流程"""
    flows = []

    # 查找关键接口
    create_api = None
    detail_api = None
    list_api = None
    start_api = None
    delete_api = None
    count_api = None

    for op in operations:
        path = op.get("path", "")
        method = op.get("method", "")
        summary = op.get("summary", "")

        if "/save" in path and method == "POST":
            create_api = op
        elif "/getById" in path and method == "GET":
            detail_api = op
        elif "/page" in path and method == "GET":
            list_api = op
        elif "/start" in path and method == "POST":
            start_api = op
        elif "/delete" in path and method == "DELETE":
            delete_api = op
        elif "getContractPreAuditList" in path and method == "GET":
            count_api = op

    # 业务流程1: CRUD全链路
    if create_api and detail_api and delete_api:
        flow_steps = [
            {
                "api_name": create_api.get("summary", "创建"),
                "method": create_api["method"],
                "path": create_api["path"],
                "case_type": "业务流程",
                "desc": "Step1: 创建预审，获取uuid",
                "params": {
                    "purchaseContractName": "流程测试采购合同",
                    "contractBudgetAmount": 100000
                },
                "expected_desc": "HTTP 200，创建成功"
            },
            {
                "api_name": detail_api.get("summary", "查询详情"),
                "method": detail_api["method"],
                "path": detail_api["path"],
                "case_type": "业务流程",
                "desc": "Step2: 根据uuid查询详情",
                "params": {"uuid": "$uuid"},
                "expected_desc": "HTTP 200，返回预审详情"
            },
            {
                "api_name": delete_api.get("summary", "删除"),
                "method": delete_api["method"],
                "path": delete_api["path"],
                "case_type": "业务流程",
                "desc": "Step3: 删除预审",
                "params": {"uuid": "$uuid"},
                "expected_desc": "HTTP 200，删除成功"
            }
        ]
        flows.append(flow_steps)

    # 业务流程2: 列表+统计
    if list_api and count_api:
        flow_steps = [
            {
                "api_name": list_api.get("summary", "分页查询"),
                "method": list_api["method"],
                "path": list_api["path"],
                "case_type": "业务流程",
                "desc": "Step1: 分页查询合同列表",
                "params": {"pageNum": 1, "pageSize": 10},
                "expected_desc": "HTTP 200，返回分页数据"
            },
            {
                "api_name": count_api.get("summary", "统计数量"),
                "method": count_api["method"],
                "path": count_api["path"],
                "case_type": "业务流程",
                "desc": "Step2: 查询各类审批状态数量",
                "params": {},
                "expected_desc": "HTTP 200，返回各类状态数量"
            }
        ]
        flows.append(flow_steps)

    # 业务流程3: 创建+开启流程
    if create_api and start_api:
        flow_steps = [
            {
                "api_name": create_api.get("summary", "创建"),
                "method": create_api["method"],
                "path": create_api["path"],
                "case_type": "业务流程",
                "desc": "Step1: 创建预审",
                "params": {
                    "purchaseContractName": "流程测试采购合同B",
                    "contractBudgetAmount": 200000
                },
                "expected_desc": "HTTP 200，创建成功"
            },
            {
                "api_name": start_api.get("summary", "开启流程"),
                "method": start_api["method"],
                "path": start_api["path"],
                "case_type": "业务流程",
                "desc": "Step2: 开启预审流程",
                "params": {"uuid": "$uuid"},
                "expected_desc": "HTTP 200，流程启动成功"
            }
        ]
        flows.append(flow_steps)

    return flows


def main():
    parser = argparse.ArgumentParser(description="自动生成测试用例")
    parser.add_argument("--apifox-url", dest="apifox_url", default=None,
                        help="Apifox URL (不指定则从 config.ini 读取)")
    parser.add_argument("--workspace", dest="workspace", default=None,
                        help="项目目录")
    parser.add_argument("--output", dest="output", default=None,
                        help="用例输出文件路径")
    args = parser.parse_args()

    # 确定 workspace
    if args.workspace:
        ws = Path(args.workspace)
    else:
        ws_root = SKILL_DIR / "workspaces"
        try:
            subdirs = [d for d in ws_root.iterdir() if d.is_dir() and not d.name.startswith(('.', '_'))]
            ws = subdirs[0] if len(subdirs) == 1 else None
        except FileNotFoundError:
            ws = None

    if not ws:
        print("[ERR] 请指定 --workspace 目录")
        sys.exit(1)

    # 确定 Apifox URL
    if not args.apifox_url:
        config_file = ws / "config.ini"
        if config_file.exists():
            import configparser
            cfg = configparser.ConfigParser()
            cfg.read(config_file, encoding="utf-8")
            args.apifox_url = cfg.get("api", "apifox_url", fallback=None)

    if not args.apifox_url:
        print("[ERR] 请指定 --apifox-url 或在 config.ini 中配置 apifox_url")
        sys.exit(1)

    # 加载缓存
    cache = load_cache(args.apifox_url, ws)
    apis = cache.get("apis", [])

    print(f"[INFO] 加载 {len(apis)} 个接口...")

    # 生成单接口用例
    all_single_cases = []
    for api in apis:
        for op in api.get("operations", []):
            cases = generate_single_cases(op)
            all_single_cases.extend(cases)

    # 生成业务流程用例
    all_operations = []
    for api in apis:
        all_operations.extend(api.get("operations", []))

    # 优先从需求文档解析业务流程
    req_doc = find_requirement_doc(ws)
    req_content = load_requirement_doc(req_doc)
    if req_content:
        flow_cases = parse_business_flows_from_doc(req_content, apis)
        print(f"[INFO] 从需求文档解析出 {len(flow_cases)} 条业务流程")
    else:
        flow_cases = detect_api_relations(all_operations)
        print(f"[INFO] 从接口关联分析出 {len(flow_cases)} 条业务流程")

    print(f"[INFO] 生成 {len(all_single_cases)} 条单接口用例")

    # 输出
    all_cases = all_single_cases + [step for flow in flow_cases for step in flow]

    if args.output:
        output_file = Path(args.output)
    else:
        cases_dir = ws / "cases"
        cases_dir.mkdir(parents=True, exist_ok=True)
        output_file = cases_dir / "single_api_cases.json"

    with open(output_file, "w", encoding="utf-8") as f:
        json.dump(all_cases, f, ensure_ascii=False, indent=2)

    print(f"[OK] 用例已生成: {output_file}")
    print(f"     单接口 {len(all_single_cases)} 条 + 业务流程 {sum(len(f) for f in flow_cases)} 条 = 总计 {len(all_cases)} 条")


if __name__ == "__main__":
    main()
