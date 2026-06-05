# -*- coding: utf-8 -*-
"""
通用工具函数
浏览器自动化测试项目的公共工具，不绑定任何项目
"""
import os
import configparser
import shutil
from datetime import datetime
from openpyxl import load_workbook
from openpyxl.styles import PatternFill
from openpyxl.drawing.image import Image as XLImage
from openpyxl.drawing.spreadsheet_drawing import OneCellAnchor


# ==================== 文件名处理 ====================
def safe_filename(name):
    """将文件名转换为安全格式，移除Windows不支持的字符"""
    invalid = '/\\:*?"<>|'
    for c in invalid:
        name = name.replace(c, '_')
    return name


# ==================== 配置文件读取 ====================
def load_config(ini_path: str) -> dict:
    """
    加载 config.ini 配置文件
    返回 dict，键为 section 名，值为 {key: value} 字典
    """
    cfg = configparser.ConfigParser()
    cfg.read(ini_path, encoding='utf-8')
    result = {}
    for section in cfg.sections():
        result[section] = dict(cfg.items(section))
    return result


# ==================== Excel 用例读取 ====================
def load_cases_from_excel(excel_path: str, start_row: int = 10,
                          id_col: int = 3, item_col: int = 5,
                          step_col: int = 7, expected_col: int = 8) -> list:
    """
    从 Excel 加载测试用例

    参数：
        excel_path: Excel 文件路径
        start_row: 用例起始行（默认第10行）
        id_col: 用例ID列（默认第3列=C）
        item_col: 测试项列（默认第5列=E）
        step_col: 测试步骤列（默认第7列=G）
        expected_col: 预期结果列（默认第8列=H）

    返回：
        [{row, id, item, step, expected, result, remark, screenshot}, ...]
    """
    wb = load_workbook(excel_path, data_only=True)
    ws = wb.active
    cases = []

    for row_idx in range(start_row, ws.max_row + 1):
        case_id = ws.cell(row_idx, id_col).value
        if case_id and str(case_id).strip():
            case = {
                'row': row_idx,
                'id': str(case_id),
                'item': ws.cell(row_idx, item_col).value,
                'precondition': ws.cell(row_idx, 6).value,
                'step': ws.cell(row_idx, step_col).value,
                'expected': ws.cell(row_idx, expected_col).value,
                'result': None,
                'remark': None,
                'screenshot': None,
            }
            # 兼容不同格式的 Excel
            if case['item'] is None:
                case['item'] = ''
            cases.append(case)

    return cases


# ==================== 截图 ====================
def take_screenshot(page, output_path: str):
    """截图保存"""
    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    page.screenshot(path=output_path)


# ==================== 报告生成 ====================
def generate_report(cases: list, template_excel: str, dst_excel: str,
                    screenshot_base_dir: str = None):
    """
    生成 Excel + HTML 测试报告

    参数：
        cases: 用例列表，每项包含 row/result/remark/screenshot
        template_excel: 源 Excel 模板文件（会被复制到 dst_excel）
        dst_excel: 输出 Excel 路径
        screenshot_base_dir: 截图基础目录（用于生成相对路径）
    """
    # 复制模板
    os.makedirs(os.path.dirname(dst_excel), exist_ok=True)
    shutil.copy2(template_excel, dst_excel)

    # 写入 Excel
    wb = load_workbook(dst_excel)
    ws = wb.active

    # 检查是否需要添加表头（如果第5行或第6行已有"执行结果"则跳过）
    header_row_5 = ws.cell(5, 9).value
    header_row_6 = ws.cell(6, 9).value
    if not header_row_5 and not header_row_6:
        # 表头不存在，添加标准表头
        ws.cell(5, 9, "执行结果")
        ws.cell(5, 10, "备注")
        ws.cell(5, 11, "截图")

    green = PatternFill(start_color="C6EFCE", fill_type="solid")
    red = PatternFill(start_color="FFC7CE", fill_type="solid")

    for case in cases:
        row = case['row']
        ws.cell(row, 9, case.get('result', 'N/A'))
        ws.cell(row, 10, case.get('remark', ''))

        screenshot = case.get('screenshot')
        if screenshot and os.path.exists(screenshot):
            try:
                img = XLImage(screenshot)
                img.width = 200
                img.height = 120
                img.anchor = OneCellAnchor()
                ws.add_image(img, f'K{row}')
                ws.row_dimensions[row].height = 80
            except Exception as e:
                print(f"[WARN] 截图嵌入失败: {e}")

        fill = green if case.get('result') == 'PASS' else red
        ws.cell(row, 9).fill = fill

    wb.save(dst_excel)

    # HTML 报告
    html_dir = os.path.dirname(dst_excel)
    html_path = os.path.join(html_dir, 'test_report.html')
    pass_count = sum(1 for c in cases if c.get('result') == 'PASS')
    fail_count = sum(1 for c in cases if c.get('result') == 'FAIL')

    rows = ''
    for case in cases:
        cls = (case.get('result') or '').lower() or 'skip'
        screenshot = case.get('screenshot')
        if screenshot:
            rel_path = os.path.basename(screenshot)
            img_tag = f'<img src="../screenshots/{rel_path}" class="screenshot-thumb" onclick="window.open(this.src)" />'
        else:
            img_tag = ''

        rows += f'''<tr class="{cls}">
            <td>{case['id']}</td>
            <td>{case.get('item', '')}</td>
            <td>{str(case.get('step', ''))[:100]}</td>
            <td>{str(case.get('expected', ''))[:100]}</td>
            <td>{case.get('result', '')}</td>
            <td>{case.get('remark', '')}</td>
            <td>{img_tag}</td>
        </tr>'''

    html = f'''<!DOCTYPE html>
<html>
<head>
    <meta charset="utf-8">
    <title>测试报告</title>
    <style>
        body{{font-family:Arial;margin:20px;background:#f5f5f5}}
        table{{width:100%;border-collapse:collapse;background:#fff;margin-top:20px}}
        th,td{{padding:8px;border:1px solid #ddd;text-align:left}}
        th{{background:#4CAF50;color:white}}
        .pass{{background:#C6EFCE}}.fail{{background:#FFC7CE}}.skip{{background:#FFEB9C}}
        img{{max-width:200px;cursor:pointer}}
        .screenshot-thumb{{cursor:pointer;border:1px solid #ddd;margin:5px}}
    </style>
</head>
<body>
    <h1>{os.path.basename(dst_excel).replace('.xlsx', '')}</h1>
    <p>时间: {datetime.now().strftime("%Y-%m-%d %H:%M:%S")}</p>
    <p>用例总数: {len(cases)} | 通过: {pass_count} | 失败: {fail_count}</p>
    <table>
        <tr><th>用例ID</th><th>测试项</th><th>步骤</th><th>预期结果</th><th>执行结果</th><th>备注</th><th>截图</th></tr>
        {rows}
    </table>
    <script>document.querySelectorAll(".screenshot-thumb").forEach(img=>img.addEventListener("click",e=>window.open(e.target.src)))</script>
</body>
</html>'''

    with open(html_path, 'w', encoding='utf-8') as f:
        f.write(html)
    print(f"Excel: {dst_excel}")
    print(f"HTML:  {html_path}")
