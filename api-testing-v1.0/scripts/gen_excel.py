# -*- coding: utf-8 -*-
"""
生成 Excel 测试用例文档（严格按照模板）：
- 2 个 Sheet：单接口 / 业务流程
- 单接口 Sheet：10 列，用例编号 TC001 起
- 业务流程 Sheet：10 列，用例编号 FC001 起
- 表头 4472C4 深蓝背景，白色粗体字，数据行根据 PASS/FAIL 着色。
"""
import sys
import io
import json
from pathlib import Path
from datetime import datetime

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

from openpyxl import Workbook
from openpyxl.styles import Font, PatternFill, Alignment, Border, Side

import argparse

SKILL_DIR = Path(__file__).resolve().parent.parent
RESULTS_DIR = SKILL_DIR / "test_results"
REPORTS_DIR = SKILL_DIR / "reports"


def _style_header_row(ws, row_idx, border, header_fill, header_font, center_align):
    for cell in ws[row_idx]:
        cell.fill = header_fill
        cell.font = header_font
        cell.alignment = center_align
        cell.border = border


def _style_data_row(ws, row_idx, case, border, normal_font, center_align, left_align,
                     pass_font, fail_font, pass_fill, fail_fill):
    for col_idx, cell in enumerate(ws[row_idx], start=1):
        cell.border = border
        cell.font = normal_font
        if col_idx in (1, 3, 5, 9, 10):
            cell.alignment = center_align
        else:
            cell.alignment = left_align
    result_cell = ws.cell(row=row_idx, column=10)
    if case["result"] == "PASS":
        result_cell.font = pass_font
        result_cell.fill = pass_fill
    else:
        result_cell.font = fail_font
        result_cell.fill = fail_fill


def _build_row(c):
    """构建数据行"""
    expected = c["expected"]
    if not expected:
        # 根据 expect_fn 自动生成预期结果描述
        expect_fn = c.get("expect_fn", "")
        if expect_fn == "exp_ok":
            expected = "HTTP 200，接口成功"
        elif expect_fn == "exp_biz_fail":
            expected = "HTTP 200，业务失败"
        elif expect_fn.startswith("exp_contains:"):
            keyword = expect_fn.split(":", 1)[1]
            expected = f"HTTP 200，响应包含'{keyword}'"
        elif expect_fn == "exp_biz_fail_or_http_4xx5xx":
            expected = "HTTP 4xx/5xx 或业务失败"
        elif expect_fn == "exp_ok_or_empty_data":
            expected = "HTTP 200"
    return [
        c["case_id"],
        c["api_name"],
        c["method"],
        c["path"],
        c["case_type"],
        c["desc"],
        c["request_params"] or "",
        expected,
        f"HTTP {c.get('http_status', '')}, {c.get('actual_msg', '')}",
        c["result"],
    ]


def _is_flow_case(case):
    """判断是否为业务流程用例"""
    return case.get("case_type") == "业务流程"


def _setup_sheet(ws, title):
    """设置 Sheet 样式"""
    header = ["用例编号", "接口名称", "请求方式", "请求路径", "测试类型",
              "测试描述", "请求参数", "预期结果", "实际结果", "执行结果"]
    ws.append(header)

    header_fill = PatternFill(start_color="4472C4", end_color="4472C4", fill_type="solid")
    header_font = Font(color="FFFFFF", bold=True, size=11, name="微软雅黑")
    center_align = Alignment(horizontal="center", vertical="center", wrap_text=True)

    _style_header_row(ws, 1, None, header_fill, header_font, center_align)

    # 列宽
    widths = {"A": 12, "B": 28, "C": 10, "D": 42, "E": 14,
              "F": 40, "G": 55, "H": 45, "I": 35, "J": 12}
    for col, w in widths.items():
        ws.column_dimensions[col].width = w

    # 首行行高
    ws.row_dimensions[1].height = 28
    # 冻结首行
    ws.freeze_panes = "A2"


def generate(results_file: Path, output_file: Path, project_name: str):
    with open(results_file, "r", encoding="utf-8") as f:
        data = json.load(f)
    cases = data["cases"]

    wb = Workbook()

    # 分离单接口和业务流程用例
    single_cases = []
    flow_cases = []

    for c in cases:
        if _is_flow_case(c):
            flow_cases.append(c)
        else:
            single_cases.append(c)

    # Sheet 1: 单接口
    ws_single = wb.active
    ws_single.title = "单接口"
    _setup_sheet(ws_single, "单接口")

    # Sheet 2: 业务流程
    ws_flow = wb.create_sheet("业务流程")
    _setup_sheet(ws_flow, "业务流程")

    # 样式定义
    thin = Side(style="thin", color="BFBFBF")
    border = Border(left=thin, right=thin, top=thin, bottom=thin)
    pass_font = Font(color="006100", bold=True, name="微软雅黑")
    fail_font = Font(color="9C0006", bold=True, name="微软雅黑")
    pass_fill = PatternFill(start_color="E2EFDA", end_color="E2EFDA", fill_type="solid")
    fail_fill = PatternFill(start_color="FFC7CE", end_color="FFC7CE", fill_type="solid")
    flow_fill = PatternFill(start_color="D9E1F2", end_color="D9E1F2", fill_type="solid")
    flow_font = Font(color="1F3864", bold=True, size=11, name="微软雅黑")
    normal_font = Font(size=10, name="微软雅黑")
    left_align = Alignment(horizontal="left", vertical="center", wrap_text=True)
    center_align = Alignment(horizontal="center", vertical="center", wrap_text=True)

    # 写入单接口用例
    for idx, c in enumerate(single_cases, start=1):
        # 重新编号 TC001, TC002, ...
        tc_id = f"TC{idx:03d}"
        c["case_id"] = tc_id
        ws_single.append(_build_row(c))
        row_idx = ws_single.max_row
        _style_data_row(ws_single, row_idx, c, border, normal_font, center_align,
                        left_align, pass_font, fail_font, pass_fill, fail_fill)
        ws_single.row_dimensions[row_idx].height = 36

    # 写入业务流程用例
    # 编号 FC001, FC002, FC003... 顺序往下排
    fc_counter = 0
    for fc in flow_cases:
        fc_counter += 1
        tc_id = f"FC{fc_counter:03d}"
        fc["case_id"] = tc_id
        ws_flow.append(_build_row(fc))
        row_idx = ws_flow.max_row
        _style_data_row(ws_flow, row_idx, fc, border, normal_font, center_align,
                        left_align, pass_font, fail_font, pass_fill, fail_fill)
        ws_flow.row_dimensions[row_idx].height = 36

    wb.save(output_file)

    total = len(cases)
    passed = sum(1 for c in cases if c["result"] == "PASS")
    failed = total - passed
    single_pass = sum(1 for c in single_cases if c["result"] == "PASS")
    flow_pass = sum(1 for c in flow_cases if c["result"] == "PASS")

    print(f"[OK] Excel 已生成: {output_file}")
    print(f"     总用例 {total} 条，PASS {passed} 条，FAIL {failed} 条")
    print(f"     单接口 {len(single_cases)} 条（PASS {single_pass}）")
    print(f"     业务流程 {len(flow_cases)} 条（PASS {flow_pass}）")


def main():
    parser = argparse.ArgumentParser(description="Generate Excel test cases report")
    parser.add_argument("--workspace", dest="workspace", default=None,
                        help="Path to workspace directory (overrides default paths)")
    parser.add_argument("--output", dest="output_dir", default=None,
                        help="Output directory for reports (default: same as workspace)")
    parser.add_argument("--results-file", dest="results_file", default=None,
                        help="Path to results JSON (default: workspace/test_results/latest_results.json)")
    args = parser.parse_args()

    # Resolve results and reports dirs from workspace or defaults
    if args.workspace:
        ws = Path(args.workspace)
    else:
        ws_root = SKILL_DIR / "workspaces"
        try:
            subdirs = [d for d in ws_root.iterdir() if d.is_dir() and not d.name.startswith(('.', '_'))]
            ws = subdirs[0] if len(subdirs) == 1 else None
        except FileNotFoundError:
            ws = None

    # 如果指定了 --output，直接使用 output 目录
    if args.output_dir:
        ws = Path(args.output_dir)

    if ws:
        results_dir = ws / "test_results"
        reports_dir = ws / "reports"
    else:
        results_dir = RESULTS_DIR
        reports_dir = REPORTS_DIR
    reports_dir.mkdir(parents=True, exist_ok=True)

    if args.results_file:
        latest = Path(args.results_file)
    else:
        latest = results_dir / "latest_results.json"

    if not latest.exists():
        print("[ERR] 找不到 latest_results.json，请先运行测试脚本")
        sys.exit(1)
    with open(latest, "r", encoding="utf-8") as f:
        data = json.load(f)
    project = data.get("project", "接口测试")
    end_time = data.get("end_time") or datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    dt = datetime.strptime(end_time, "%Y-%m-%d %H:%M:%S")
    ts = dt.strftime("%Y%m%d_%H%M%S")
    out = reports_dir / f"{project}接口测试用例及测试结果_{ts}.xlsx"
    generate(latest, out, project)


if __name__ == "__main__":
    main()
