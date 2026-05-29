# -*- coding: utf-8 -*-
"""
自动生成测试用例脚本
====================
根据 Apifox 缓存的接口定义 + 需求文档，自动生成单接口用例和业务流程用例。

规则说明：
- 规则文件位于 rules/ 目录
- api_classification.json: 接口分类规则
- flow_patterns.json: 业务流程模式
- case_templates.json: 用例生成模板

用法:
    python generate_cases.py --workspace "D:/test-output/项目名"
    python generate_cases.py --apifox-url "https://xxx.apifox.cn" --workspace "D:/test-output/项目名"
    python generate_cases.py --use-ai  # 使用 AI 辅助生成业务流程
"""
import sys
import io
import json
import argparse
import re
import os
from pathlib import Path
from datetime import datetime

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

SKILL_DIR = Path(__file__).resolve().parent.parent
DEFAULT_CACHE_DIR = Path.home() / ".qclaw" / "cache" / "apifox-api"


# ═══════════════════════════════════════════════════════════════════════════
# 规则引擎
# ═══════════════════════════════════════════════════════════════════════════

class RuleEngine:
    """规则引擎 - 从规则文件加载并应用规则"""

    def __init__(self, workspace_path=None):
        self.workspace_path = workspace_path
        self.rules_dir = self._find_rules_dir()
        self.classification = {}
        self.flow_patterns = []
        self.case_templates = {}
        self.system_fields = set()
        self.expect_fn_overrides = []  # 期望函数覆盖规则
        self._load_rules()

    def _find_rules_dir(self):
        """查找规则目录（项目目录 > 技能包默认目录）"""
        # 1. 项目目录下的 rules/
        if self.workspace_path:
            project_rules = Path(self.workspace_path) / "rules"
            if project_rules.exists():
                return project_rules

        # 2. 技能包目录下的 rules/
        skill_rules = SKILL_DIR / "rules"
        if skill_rules.exists():
            return skill_rules

        return None

    def _load_rules(self):
        """加载所有规则文件（通用规则为基础，项目规则覆盖）"""
        # 主规则目录（技能包目录，始终存在）
        main_rules_dir = SKILL_DIR / "rules"
        if not main_rules_dir.exists():
            print("[ERROR] 未找到规则目录，请确保 api-testing/rules/ 目录存在")
            raise FileNotFoundError("规则目录不存在")

        # 加载接口分类规则（先通用，再项目覆盖）
        class_file = main_rules_dir / "api_classification.json"
        if not class_file.exists():
            raise FileNotFoundError(f"规则文件不存在: {class_file}")
        with open(class_file, 'r', encoding='utf-8') as f:
            data = json.load(f)
            self.classification = data.get('classifications', {})
            self.system_fields = set(data.get('system_fields', []))
        # 项目规则覆盖
        if self.rules_dir:
            project_class_file = self.rules_dir / "api_classification.json"
            if project_class_file.exists():
                with open(project_class_file, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    # 合并分类规则
                    self.classification.update(data.get('classifications', {}))
                    # 项目规则完全覆盖 system_fields
                    project_system_fields = data.get('system_fields', [])
                    if project_system_fields:
                        self.system_fields = set(project_system_fields)
                        print("[INFO] 项目规则已覆盖通用 api_classification.json")

        # 加载业务流程模式（项目规则完全覆盖通用规则）
        flow_file = main_rules_dir / "flow_patterns.json"
        if not flow_file.exists():
            raise FileNotFoundError(f"规则文件不存在: {flow_file}")
        with open(flow_file, 'r', encoding='utf-8') as f:
            data = json.load(f)
            self.flow_patterns = data.get('patterns', [])
        # 项目规则完全覆盖
        if self.rules_dir:
            project_flow_file = self.rules_dir / "flow_patterns.json"
            if project_flow_file.exists():
                with open(project_flow_file, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    # 项目规则完全替换
                    self.flow_patterns = data.get('patterns', [])
                    print("[INFO] 项目规则已覆盖通用 flow_patterns.json")

        # 加载用例模板
        template_file = main_rules_dir / "case_templates.json"
        if not template_file.exists():
            raise FileNotFoundError(f"规则文件不存在: {template_file}")
        with open(template_file, 'r', encoding='utf-8') as f:
            data = json.load(f)
            self.case_templates = data.get('templates', {})
            self.biz_key_fields = data.get('biz_key_fields', [])

        # 加载期望函数覆盖规则（从项目目录，由 run_test.py --learn 生成）
        if self.rules_dir:
            override_file = self.rules_dir / "expect_fn_overrides.json"
            if override_file.exists():
                try:
                    with open(override_file, 'r', encoding='utf-8') as f:
                        data = json.load(f)
                    self.expect_fn_overrides = data.get('overrides', [])
                    if self.expect_fn_overrides:
                        print(f"[INFO] 已加载 {len(self.expect_fn_overrides)} 条期望覆盖规则")
                except Exception as e:
                    print(f"[WARN] 加载期望覆盖规则失败: {e}")
                    self.expect_fn_overrides = []

    def get_expect_fn_override(self, api_name, case_type, desc):
        """检查是否有覆盖规则适用于当前用例"""
        for override in self.expect_fn_overrides:
            # 匹配接口名（支持模糊匹配）
            api_pattern = override.get('api_name_pattern', '')
            if api_pattern and api_pattern not in api_name:
                continue

            # 匹配用例类型
            type_pattern = override.get('case_type_pattern', '')
            if type_pattern and type_pattern != case_type:
                continue

            # 匹配描述关键词（至少匹配一个）
            desc_patterns = override.get('desc_patterns', [])
            if desc_patterns:
                if not any(p in desc for p in desc_patterns):
                    continue
            else:
                # 没有描述模式时，只要接口名和类型匹配即可
                pass

            # 找到匹配的覆盖规则
            return override.get('override', {})

        return None

    def classify_api(self, op):
        """根据规则分类接口"""
        path = op.get("path", "").lower()
        method = op.get("method", "")
        summary = op.get("summary", "").lower()

        for class_name, class_info in self.classification.items():
            # 检查 method
            if method not in class_info.get("method", []):
                continue

            # 检查 path 和 summary 关键词
            keywords = class_info.get("keywords", {})
            path_kws = keywords.get("path", [])
            summary_kws = keywords.get("summary", [])

            path_match = any(kw.lower() in path for kw in path_kws)
            summary_match = any(kw.lower() in summary for kw in summary_kws)

            if path_match or summary_match:
                return class_name

        return "unknown"

    def is_system_field(self, field_name):
        """判断是否为系统字段"""
        return field_name in self.system_fields

    def match_flow_pattern(self, operations):
        """匹配业务流程模式"""
        flows = []

        # 按角色分类接口
        role_to_ops = {}
        for op in operations:
            role = self.classify_api(op)
            if role not in role_to_ops:
                role_to_ops[role] = []
            role_to_ops[role].append(op)

        # 尝试匹配每个模式
        for pattern in self.flow_patterns:
            steps = pattern.get("steps", [])
            if len(steps) < 2:
                continue

            # 检查模式所需的角色是否存在
            all_roles_exist = all(
                any(step.get("role") in role_to_ops for step in steps)
                for step in steps
            )
            if not all_roles_exist:
                continue

            # 构建流程
            flow_steps = []
            prev_op = None

            for step in steps:
                role = step.get("role")
                action = step.get("action")

                # 查找匹配的接口
                matching_ops = role_to_ops.get(role, [])
                if not matching_ops:
                    break

                # 选择最佳匹配
                op = self._select_best_op(matching_ops, action, prev_op)

                # 构建步骤
                extract_field = step.get("extract_field")
                params_template = step.get("params_template", {})
                params = self._build_params(op, extract_field, prev_op, params_template)

                api_name = op.get("summary") or self._path_to_name(op.get("path", ""))
                case_type = "业务流程"
                desc = f"Step{len(flow_steps)+1}: {action}"

                flow_step = {
                    "api_name": api_name,
                    "method": op.get("method"),
                    "path": op.get("path"),
                    "case_type": case_type,
                    "desc": desc,
                    "params": params,
                    "expected_desc": "HTTP 200，成功"
                }
                # 应用期望函数覆盖规则
                apply_expect_fn(self, api_name, case_type, desc, flow_step)
                flow_steps.append(flow_step)

                prev_op = op

            if len(flow_steps) == len(steps):
                flows.append(flow_steps)

        return flows

    def _select_best_op(self, ops, action, prev_op):
        """选择最佳匹配的接口"""
        if len(ops) == 1:
            return ops[0]

        # 如果有前一个接口，尝试选择路径相似的
        if prev_op:
            prev_path = prev_op.get("path", "")
            prev_prefix = "/".join(prev_path.strip("/").split("/")[:-1])

            for op in ops:
                op_path = op.get("path", "")
                if prev_prefix in op_path:
                    return op

        return ops[0]

    def _build_params(self, op, extract_field, prev_op, params_template=None):
        """构建接口参数"""
        params = {}
        if params_template is None:
            params_template = {}

        # 如果有前序接口的提取字段，使用变量引用
        if extract_field and prev_op:
            params[extract_field] = f"${{{extract_field}}}"
            return params

        # 优先使用 params_template 中的参数
        if params_template:
            params.update(params_template)
            return params

        # 否则返回默认参数
        for p in op.get("parameters", []):
            name = p.get("name", "")
            ptype = p.get("type", "string")
            required = p.get("required", False)

            if required and not self.is_system_field(name):
                if ptype == "string":
                    params[name] = f"test_{name}"
                elif ptype in ("number", "integer"):
                    params[name] = 1
                elif ptype == "boolean":
                    params[name] = True

        # requestBody
        body = op.get("requestBody") or {}
        schema = body.get("schema") or {}
        required_list = schema.get("required", [])
        properties = schema.get("properties", {})

        if required_list:
            # 使用 API 定义的 required 列表
            for name in required_list:
                if self.is_system_field(name):
                    continue
                prop = properties.get(name, {})
                ptype = prop.get("type", "string")
                if ptype == "string":
                    params[name] = f"test_{name}"
                elif ptype in ("number", "integer"):
                    params[name] = 100
        elif properties:
            # required_list 为空时，使用业务关键字段模式匹配
            for name, prop in properties.items():
                if self.is_system_field(name):
                    continue
                # 检查字段名是否匹配业务关键字段模式
                is_key_field = any(kw.lower() in name.lower() for kw in self.biz_key_fields)
                if is_key_field:
                    ptype = prop.get("type", "string")
                    if ptype == "string":
                        params[name] = f"test_{name}"
                    elif ptype in ("number", "integer"):
                        params[name] = 100

        return params

    def _path_to_name(self, path):
        """从路径提取名称"""
        parts = path.strip("/").split("/")
        name = parts[-1] if parts else ""
        # 去掉常见前缀
        for prefix in ["get", "query", "find", "search", "list", "page"]:
            if name.lower().startswith(prefix):
                name = name[len(prefix):]
        return name or path


# ═══════════════════════════════════════════════════════════════════════════
# 原有辅助函数
# ═══════════════════════════════════════════════════════════════════════════

def find_requirement_doc(workspace_path):
    """查找需求文档（md格式）"""
    ws = Path(workspace_path)

    input_dir = ws / "input"
    if input_dir.exists():
        md_files = list(input_dir.glob("*.md"))
        if md_files:
            print(f"[INFO] 在 {input_dir} 找到需求文档")
            return md_files[0]

    md_files = list(ws.glob("*.md"))
    if md_files:
        print(f"[INFO] 在 {ws} 找到需求文档")
        return md_files[0]

    test_input = ws.parent.parent / "test-input" / ws.name / "input"
    if test_input.exists():
        md_files = list(test_input.glob("*.md"))
        if md_files:
            print(f"[INFO] 在 {test_input} 找到需求文档")
            return md_files[0]

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


def extract_keywords_from_doc(content):
    """从需求文档中提取关键词"""
    keywords = set()
    chinese_words = re.findall(r'[一-鿿]{2,8}', content)
    keywords.update(chinese_words)
    stop_words = {
        '的', '了', '和', '与', '或', '在', '是', '为', '于', '上', '下', '中', '内', '外',
        '项目', '系统', '功能', '模块', '描述', '输入', '输出', '数据', '列表', '详细',
        '接口', '方法', '处理', '流程', '如下', '所示', '其中', '以及', '包括',
    }
    return set(w for w in keywords if len(w) >= 2 and w not in stop_words)


def load_cache(apifox_url, workspace_path=None):
    """加载 Apifox 缓存"""
    import hashlib

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


def gen_expect_fn(case_type, desc, rule_engine=None):
    """根据用例类型和描述自动配置 expect_fn，支持覆盖规则"""
    # 先检查覆盖规则
    if rule_engine:
        override = rule_engine.get_expect_fn_override("", case_type, desc)
        if override and override.get('expect_fn'):
            return override['expect_fn']

    # 通用规则
    if case_type == "正向测试":
        return None

    if "不存在" in desc:
        return "exp_biz_fail"
    if "SQL注入" in desc or "XSS" in desc:
        return "exp_biz_fail"
    if "超长" in desc or "超出范围" in desc:
        return None  # 边界测试默认 exp_ok
    if "缺少" in desc or "为空" in desc:
        return "exp_biz_fail"

    return None


def apply_expect_fn(rule_engine, api_name, case_type, desc, case):
    """为用例应用期望函数，检查覆盖规则"""
    if not rule_engine:
        ef = gen_expect_fn(case_type, desc)
        if ef:
            case["expect_fn"] = ef
        return

    # 先检查覆盖规则
    override = rule_engine.get_expect_fn_override(api_name, case_type, desc)
    if override and override.get('expect_fn'):
        case["expect_fn"] = override['expect_fn']
        return

    # 没有覆盖规则，使用通用规则
    ef = gen_expect_fn(case_type, desc)
    if ef:
        case["expect_fn"] = ef


def analyze_operation(op, rule_engine):
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

        if rule_engine.is_system_field(name):
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
            if rule_engine.is_system_field(name):
                continue
            ptype = prop.get("type", "string")
            desc = prop.get("description", "")
            params[name] = {"type": ptype, "desc": desc}
            if name in required_list:
                required_fields[name] = ptype
            else:
                optional_fields[name] = ptype

    return params, required_fields, optional_fields


# ── 通用辅助函数 ──────────────────────────────────────────────────────────────

# 通用金额关键词（用于判断数字字段是否为金额类型）
AMOUNT_KEYWORDS = ["amount", "price", "total", "sum", "money", "fee", "cost", "budget", "balance"]

def is_amount_field(name):
    """判断字段名是否为金额相关字段"""
    return any(kw in name.lower() for kw in AMOUNT_KEYWORDS)

def get_test_number_value(field_name):
    """获取数字字段的测试值（金额字段用大值，其他用1）"""
    return 100000 if is_amount_field(field_name) else 1

def build_base_params(fields_dict, use_uuid_placeholder=True):
    """构建基础参数字典，智能处理 uuid/fileId 占位符"""
    params = {}
    for name, info in fields_dict.items():
        if use_uuid_placeholder and name in ("uuid", "fileId"):
            params[name] = f"${name}"
        elif info.get("type") == "integer":
            params[name] = get_test_number_value(name)
        elif info.get("type") == "boolean":
            params[name] = True
        else:
            params[name] = f"test_{name}"
    return params


def generate_single_cases(op, rule_engine):
    """为单个接口生成单接口测试用例"""
    method = op["method"]
    path = op["path"]
    api_name = op.get("summary", path)

    params, required_fields, optional_fields = analyze_operation(op, rule_engine)

    cases = []

    # 正向测试
    if method in ("GET", "DELETE"):
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
        apply_expect_fn(rule_engine, api_name, "正向测试", f"{api_name}-正常参数", case)
        cases.append(case)

    elif method == "POST":
        # POST: 完整必填字段 + 最小字段
        body_min = {}
        for k, v in required_fields.items():
            if v == "string":
                body_min[k] = "测试"
            elif v in ("number", "integer"):
                body_min[k] = get_test_number_value(k)
            elif v == "boolean":
                body_min[k] = False

        body_full = dict(body_min)
        for name, ptype in optional_fields.items():
            if ptype == "string":
                body_full[name] = f"测试{name}"
            elif ptype in ("number", "integer"):
                body_full[name] = get_test_number_value(name)

        case = {
            "api_name": api_name,
            "method": method,
            "path": path,
            "case_type": "正向测试",
            "desc": f"{api_name}-完整必填字段",
            "params": body_full,
            "expected_desc": "HTTP 200，保存成功"
        }
        apply_expect_fn(rule_engine, api_name, "正向测试", f"{api_name}-完整必填字段", case)
        cases.append(case)

    elif method == "PUT":
        # PUT: 智能处理 uuid/fileId 占位符
        body_normal = build_base_params(params)
        case = {
            "api_name": api_name,
            "method": method,
            "path": path,
            "case_type": "正向测试",
            "desc": f"{api_name}-完整字段更新",
            "params": body_normal,
            "expected_desc": "HTTP 200，更新成功"
        }
        apply_expect_fn(rule_engine, api_name, "正向测试", f"{api_name}-完整字段更新", case)
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
            apply_expect_fn(rule_engine, api_name, "逆向测试", desc, case)
            cases.append(case)

        # 缺少必填字段
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
            apply_expect_fn(rule_engine, api_name, "逆向测试", desc, case)
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
        apply_expect_fn(rule_engine, api_name, "逆向测试", desc, case)
        cases.append(case)

    # 边界测试（期望函数已在 gen_boundary_cases 内部应用）
    for c in gen_boundary_cases(api_name, method, path, required_fields, optional_fields, params, rule_engine):
        cases.append(c)

    # 安全测试（期望函数已在 gen_security_cases 内部应用）
    for c in gen_security_cases(api_name, method, path, params, rule_engine):
        cases.append(c)

    return cases


def gen_boundary_cases(api_name, method, path, required_fields, optional_fields, param_hints, rule_engine=None):
    """生成边界测试用例"""
    cases = []
    case_type = "边界测试"
    long_string_length = 100  # 通用超长字符串长度

    req_keys = list(required_fields.keys()) if required_fields else []
    opt_keys = list(optional_fields.keys()) if optional_fields else []

    def build_boundary_base_params(fields_dict):
        """构建边界测试的基础参数，智能处理 uuid/fileId 占位符"""
        params = {}
        for name in fields_dict.keys():
            if name in ("uuid", "fileId"):
                params[name] = f"${name}"
            else:
                params[name] = f"test_{name}"
        return params

    # 超长字符串
    string_fields = [k for k, v in (required_fields or {}).items() if v == "string"]
    if not string_fields:
        string_fields = [k for k, v in (optional_fields or {}).items() if v == "string"]
    for name in string_fields[:3]:
        params_base = build_boundary_base_params(required_fields or {})
        params_base[name] = "超" * long_string_length
        cases.append({
            "api_name": api_name,
            "method": method,
            "path": path,
            "case_type": case_type,
            "desc": f"{api_name}-超长{name}",
            "params": params_base,
            "expected_desc": "正常处理或提示参数超长"
        })

    # 空字符串
    for name in string_fields[:3]:
        params_base = build_boundary_base_params(required_fields or {})
        params_base[name] = ""
        cases.append({
            "api_name": api_name,
            "method": method,
            "path": path,
            "case_type": case_type,
            "desc": f"{api_name}-{name}为空字符串",
            "params": params_base,
            "expected_desc": "提示必填字段不能为空"
        })

    # 超出范围数值
    num_fields = [k for k, v in (required_fields or {}).items() if v in ("number", "integer")]
    if num_fields:
        params_base = build_boundary_base_params(required_fields or {})
        params_base[num_fields[0]] = 999999999999
        cases.append({
            "api_name": api_name,
            "method": method,
            "path": path,
            "case_type": case_type,
            "desc": f"{api_name}-{num_fields[0]}超出范围",
            "params": params_base,
            "expected_desc": "正常处理或提示超出范围"
        })

    # 应用期望函数（支持覆盖规则）
    for case in cases:
        apply_expect_fn(rule_engine, api_name, "边界测试", case["desc"], case)

    return cases


def gen_security_cases(api_name, method, path, fields, rule_engine=None):
    """生成安全测试用例"""
    cases = []
    case_type = "安全测试"

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

        cases.append({
            "api_name": api_name,
            "method": method,
            "path": path,
            "case_type": case_type,
            "desc": f"{api_name}-XSS攻击",
            "params": {test_field: "<script>alert('xss')</script>"},
            "expected_desc": "XSS被过滤或无数据"
        })

    # 应用期望函数（支持覆盖规则）
    for case in cases:
        apply_expect_fn(rule_engine, api_name, "安全测试", case["desc"], case)

    return cases


# ═══════════════════════════════════════════════════════════════════════════
# AI 层：业务流程用例生成
# ═══════════════════════════════════════════════════════════════════════════

def get_llm_client(workspace_path=None):
    """自动检测并创建 LLM 客户端（SDK 不可用时优雅降级）"""
    import configparser

    # 1. 技能包同级别目录的配置（优先）
    skill_dir = Path(__file__).resolve().parent.parent
    skill_parent = skill_dir.parent
    external_config_dir = skill_parent / "llm-config"
    if not external_config_dir.exists():
        external_config_dir = skill_parent / "config"
    if not external_config_dir.exists():
        external_config_dir = skill_parent / "llm_config"

    # 1.1 llm_config.ini
    external_config_file = external_config_dir / "llm_config.ini"
    if external_config_file.exists():
        config = configparser.ConfigParser()
        config.read(external_config_file, encoding='utf-8')
        api_key = config.get('llm', 'api_key', fallback='')
        if api_key:
            provider = config.get('llm', 'provider', fallback='openai').lower()
            base_url = config.get('llm', 'base_url', fallback='')
            model = config.get('llm', 'model', fallback='')
            try:
                if provider == 'anthropic':
                    from anthropic import Anthropic
                    kwargs = {'api_key': api_key}
                    if base_url:
                        kwargs['base_url'] = base_url
                    return Anthropic(**kwargs)
                else:
                    from langchain_openai import ChatOpenAI
                    kwargs = {'api_key': api_key, 'model': model if model else None}
                    if base_url:
                        kwargs['base_url'] = base_url
                    return ChatOpenAI(**kwargs)
            except ImportError:
                pass

    # 1.2 llm_config.json
    llm_config_file = external_config_dir / "llm_config.json"
    if llm_config_file.exists():
        try:
            with open(llm_config_file, 'r', encoding='utf-8') as f:
                llm_config = json.load(f)
            provider = llm_config.get('provider', '').lower()
            api_key = llm_config.get('api_key', '')
            base_url = llm_config.get('base_url', '')
            model = llm_config.get('model', '')

            if provider == 'openai' and api_key:
                try:
                    from langchain_openai import ChatOpenAI
                    kwargs = {'api_key': api_key, 'model': model if model else None}
                    if base_url:
                        kwargs['base_url'] = base_url
                    return ChatOpenAI(**kwargs)
                except ImportError:
                    pass
            elif provider == 'anthropic' and api_key:
                try:
                    from anthropic import Anthropic
                    kwargs = {'api_key': api_key}
                    if base_url:
                        kwargs['base_url'] = base_url
                    return Anthropic(**kwargs)
                except ImportError:
                    pass
        except Exception:
            pass

    # 2. Claude Code / OpenClaw 环境
    if os.environ.get('ANTHROPIC_BASE_URL'):
        try:
            from anthropic import Anthropic
            return Anthropic()
        except ImportError:
            pass

    # 3. OpenAI 环境
    if os.environ.get('OPENAI_API_KEY'):
        try:
            from langchain_openai import ChatOpenAI
            base_url = os.environ.get('OPENAI_BASE_URL', 'https://api.openai.com/v1')
            return ChatOpenAI(
                api_key=os.environ['OPENAI_API_KEY'],
                base_url=base_url
            )
        except ImportError:
            pass

    # 4. workspace config.ini
    if workspace_path:
        config_file = Path(workspace_path) / "config.ini"
        if config_file.exists():
            config = configparser.ConfigParser()
            config.read(config_file, encoding='utf-8')
            api_key = config.get('llm', 'api_key', fallback='')
            if not api_key:
                api_key = config.get('openai-chat', 'api_key', fallback='')
            if api_key:
                try:
                    from langchain_openai import ChatOpenAI
                    return ChatOpenAI(api_key=api_key)
                except ImportError:
                    pass

    return None


def build_flow_prompt(requirement_doc, apis):
    """构建业务流程生成的 prompt"""
    # 构建接口详情列表（通用）
    api_details = []
    for api in apis[:20]:  # 限制数量避免 prompt 太长
        for op in api.get("operations", []):
            path = op.get("path", "")
            method = op.get("method", "")
            summary = op.get("summary", path)

            # 提取参数定义（简化版）
            params_info = []
            for p in op.get("parameters", []):
                name = p.get("name", "")
                p_in = p.get("in", "query")
                required = p.get("required", False)
                if name.lower() not in ("mobile",):
                    params_info.append(f"{name}({p_in},{'必' if required else '可'})")

            # 提取 requestBody 必填字段
            body_fields = []
            request_body = op.get("requestBody") or {}
            if request_body:
                schema = request_body.get("schema", {})
                required_list = schema.get("required", [])
                properties = schema.get("properties", {})
                for name in required_list:
                    if name.lower() not in ("mobile",):
                        prop = properties.get(name, {})
                        ptype = prop.get("type", "string")
                        body_fields.append(f"{name}({ptype})")

            params_str = ", ".join(params_info) if params_info else ""
            body_str = ", ".join(body_fields) if body_fields else ""
            api_text = f"{method} {path} # {summary}"
            if params_str:
                api_text += f" | 参数:{params_str}"
            if body_str:
                api_text += f" | Body:{body_str}"
            api_details.append(api_text)

    api_detail_str = "\n".join(api_details)

    # 截取需求文档前部（通常包含业务流程概述）
    req_lines = requirement_doc.split('\n')[:150]
    relevant_doc = '\n'.join(req_lines)

    prompt = f"""你是资深测试专家，根据需求文档设计业务流程测试用例。

## 需求文档
{relevant_doc}

## 可用接口（带参数）
{api_detail_str}

## 任务
1. 分析需求文档中的业务流程
2. 选择接口组合成完整业务流程（如：创建 → 提交 → 查询 → 删除）
3. params 参数名必须与接口定义中的参数名完全一致
4. 后续步骤用 $变量名 引用上一步返回的字段

## 输出格式（严格JSON）
[
  [
    {{"api_name": "接口中文名", "method": "GET/POST/DELETE", "path": "/接口路径", "desc": "Step1: 操作描述", "params": {{"字段名": "值"}}, "expected_desc": "预期结果"}},
    {{"api_name": "接口中文名", "method": "GET/POST/DELETE", "path": "/接口路径", "desc": "Step2: 操作描述", "params": {{"uuid": "$uuid"}}, "expected_desc": "预期结果"}}
  ]
]

## 规则
1. case_type 必须是"业务流程"
2. 变量名用 $uuid（因为创建接口返回的字段名通常是 uuid）
3. 只输出JSON
"""
    return prompt


def generate_flows_by_ai(requirement_doc, apis, workspace_path=None):
    """用 AI 生成业务流程用例"""
    client = get_llm_client(workspace_path)
    if not client:
        print("[WARN] 未检测到可用 LLM，跳过 AI 业务流程生成")
        return []

    prompt = build_flow_prompt(requirement_doc, apis)

    try:
        if hasattr(client, 'messages'):
            response = client.messages.create(
                model=os.environ.get('ANTHROPIC_MODEL', 'claude-sonnet-4-20250514'),
                max_tokens=4096,
                timeout=120,
                messages=[{"role": "user", "content": prompt}]
            )
            content_blocks = response.content
            result = ""
            for block in content_blocks:
                if hasattr(block, 'text') and block.text:
                    result = block.text
                    break
            if not result:
                result = str(content_blocks[0]) if content_blocks else ""
        else:
            from langchain.schema import HumanMessage
            response = client.invoke([HumanMessage(content=prompt)], timeout=120)
            result = response.content

        result = result.strip()
        result = re.sub(r'^```json\s*', '', result)
        result = re.sub(r'\s*```$', '', result)

        flows = json.loads(result)

        normalized = []
        for flow in flows:
            if isinstance(flow, list):
                for step in flow:
                    if isinstance(step, dict):
                        step['case_type'] = '业务流程'
                normalized.append(flow)

        print(f"[INFO] AI 生成 {len(normalized)} 条业务流程")
        return normalized

    except Exception as e:
        print(f"[WARN] AI 生成失败: {e}")
        return []


# ═══════════════════════════════════════════════════════════════════════════
# 业务流程生成（基于规则的通用方法）
# ═══════════════════════════════════════════════════════════════════════════

def detect_flows_by_rules(operations, workspace_path=None):
    """基于规则引擎识别业务流程"""
    rule_engine = RuleEngine(workspace_path)
    return rule_engine.match_flow_pattern(operations)


# ═══════════════════════════════════════════════════════════════════════════
# 主入口
# ═══════════════════════════════════════════════════════════════════════════

def main():
    parser = argparse.ArgumentParser(description="自动生成测试用例")
    parser.add_argument("--apifox-url", dest="apifox_url", default=None,
                        help="Apifox URL (不指定则从 config.ini 读取)")
    parser.add_argument("--workspace", dest="workspace", default=None,
                        help="项目目录")
    parser.add_argument("--output", dest="output", default=None,
                        help="用例输出文件路径")
    parser.add_argument("--use-ai", action="store_true",
                        help="强制使用 AI 生成业务流程（需配置 LLM）")
    parser.add_argument("--no-ai", action="store_true",
                        help="禁用 AI，仅使用规则生成")
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

    # 初始化规则引擎
    rule_engine = RuleEngine(ws)

    # 生成单接口用例
    all_single_cases = []
    for api in apis:
        for op in api.get("operations", []):
            cases = generate_single_cases(op, rule_engine)
            all_single_cases.extend(cases)

    # 生成业务流程用例
    all_operations = []
    for api in apis:
        all_operations.extend(api.get("operations", []))

    # 业务流程生成：AI 优先，规则兜底
    req_doc = find_requirement_doc(ws)
    req_content = load_requirement_doc(req_doc)
    flow_cases = []

    use_ai = args.use_ai and not args.no_ai

    if req_content:
        if use_ai:
            flow_cases = generate_flows_by_ai(req_content, apis, ws)
            if not flow_cases:
                print("[INFO] AI 生成失败，回退到规则解析")
                flow_cases = detect_flows_by_rules(all_operations, ws)
        else:
            flow_cases = detect_flows_by_rules(all_operations, ws)
            if flow_cases:
                print(f"[INFO] 从规则解析出 {len(flow_cases)} 条业务流程")
            elif not args.no_ai:
                flow_cases = generate_flows_by_ai(req_content, apis, ws)
                if not flow_cases:
                    print("[WARN] 规则和 AI 都未生成业务流程")
    else:
        flow_cases = detect_flows_by_rules(all_operations, ws)
        if flow_cases:
            print(f"[INFO] 从规则解析出 {len(flow_cases)} 条业务流程")
        elif use_ai:
            print("[WARN] 无需求文档，AI 无法生成业务流程")

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
