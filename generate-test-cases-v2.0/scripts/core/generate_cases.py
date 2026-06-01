from docx import Document
import re
import os
import json
import html
from langchain_openai import ChatOpenAI

def _x(val):
    """Excel-safe转义：处理XML非法字符和特殊空白"""
    if not isinstance(val, str):
        return val
    # 替换XML非法字符（openpyxl内部用XML）
    val = val.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
    # 合并多余空白
    val = re.sub(r'[ \t]+', ' ', val)
    val = re.sub(r' *\n *', '\n', val)
    return val.strip()
from langchain_core.messages import HumanMessage
import configparser
import logging
from openpyxl import Workbook
from openpyxl.styles import Alignment
from concurrent.futures import ThreadPoolExecutor
import argparse
import httpx

# 配置日志
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# ====== 模型配置：优先使用 OpenClaw 本地模型，回退到 SiliconFlow ======

# 方式1：自动检测 OpenClaw 本地模型（推荐，零配置）
OPENCLAW_BASE_URL = "http://127.0.0.1:19000/proxy/llm"
OPENCLAW_MODEL = "modelroute"

def _check_openclaw_available():
    """检测 OpenClaw 本地模型是否可用（通过实际发一个最小请求验证）"""
    try:
        # 发送一个最小化测试请求验证连通性
        resp = httpx.post(
            f"{OPENCLAW_BASE_URL}/chat/completions",
            json={
                "model": OPENCLAW_MODEL,
                "messages": [{"role": "user", "content": "hi"}],
                "max_tokens": 2
            },
            headers={"Content-Type": "application/json"},
            timeout=10
        )
        return resp.status_code in (200, 400, 401, 403)  # 只要不是404/500等网络错误就算可用（400可能是模型名问题，后续可修正）
    except Exception:
        return False

# 方式2：从同技能目录级别的 llm-config/llm_config.ini 读取备用模型配置
def _load_fallback_config():
    """从同技能目录级别的 llm-config/llm_config.ini 读取备用模型配置"""
    config = configparser.ConfigParser()
    # 向上四级从 scripts/core/ 到达 skills/ 父目录
    # scripts/core -> scripts -> generate-test-cases -> AI -> skills
    skill_parent = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
    config_file_path = os.path.join(skill_parent, 'llm-config', 'llm_config.ini')
    if not os.path.exists(config_file_path):
        return None, None, None
    config.read(config_file_path, encoding='utf-8')
    # 支持 [llm] 和 [openai-chat] 两种 section 格式
    if config.has_section('llm'):
        api_key = config.get("llm", "api_key", fallback='').strip()
        base_url = config.get("llm", "base_url", fallback='').strip()
        model = config.get("llm", "model", fallback='').strip()
    else:
        api_key = config.get("openai-chat", "api_key", fallback='').strip()
        base_url = config.get("openai-chat", "base_url", fallback='').strip()
        model = config.get("openai-chat", "model", fallback='').strip()
    if not api_key or api_key == 'your_api_key_here' or not base_url or not model:
        return None, None, None
    logger.info(f"使用 llm-config 配置：{base_url} / {model}")
    return api_key, base_url, model

# 自动选择模型：优先使用 llm-config 配置的模型，回退到 OpenClaw 本地模型
api_key, base_url, model = _load_fallback_config()
if api_key and base_url and model:
    LLM_BASE_URL = base_url
    LLM_API_KEY = api_key
    LLM_MODEL = model
    logger.info(f"使用 llm-config 配置：{base_url} / {model}")
else:
    # 回退到 OpenClaw 本地模型
    if _check_openclaw_available():
        LLM_BASE_URL = OPENCLAW_BASE_URL
        LLM_API_KEY = "openclaw"
        LLM_MODEL = OPENCLAW_MODEL
        logger.info("llm-config 配置不可用，回退到 OpenClaw 本地模型")
    else:
        logger.error("无可用模型：llm-config 配置不完整，且 OpenClaw 本地模型不可用")
        print("错误：无可用模型。\n请配置 llm-config/llm_config.ini 或确认 OpenClaw 本地模型可用")
        exit(1)


def _get_num_start_values(doc):
    """从文档numbering定义中提取每个numId每个level的起始值"""
    from docx.oxml.ns import qn
    start_values = {}
    try:
        numbering_part = doc.part.numbering_part
        if numbering_part is None:
            return start_values
        elem = numbering_part.element
        abstract_map = {}
        for abstractNum in elem.findall(qn('w:abstractNum')):
            aid = int(abstractNum.get(qn('w:abstractNumId')))
            levels = {}
            for lvl in abstractNum.findall(qn('w:lvl')):
                ilvl = int(lvl.get(qn('w:ilvl')))
                start_el = lvl.find(qn('w:start'))
                levels[ilvl] = int(start_el.get(qn('w:val'))) if start_el is not None else 1
            abstract_map[aid] = levels
        for num in elem.findall(qn('w:num')):
            numId = int(num.get(qn('w:numId')))
            aid_el = num.find(qn('w:abstractNumId'))
            if aid_el is not None:
                aid = int(aid_el.get(qn('w:val')))
                for ilvl, start_val in abstract_map.get(aid, {}).items():
                    start_values[(numId, ilvl)] = start_val
    except Exception:
        pass
    return start_values


def docx_to_markdown(docx_path, para_start=None, para_end=None):
    """
    将docx文档转换为markdown格式。
    若传入 para_start/para_end，则从 docx_path 的指定段落范围读取
    （用于直接读原始文档，保留 Heading 样式）。
    """

    """将docx文档转换为markdown格式"""
    try:
        from docx.oxml.ns import qn
        doc = Document(docx_path)
        markdown_content = []
        start_values = _get_num_start_values(doc)
        num_counters = {}
        p_start = para_start if para_start is not None else 0
        p_end = para_end if para_end is not None else len(doc.paragraphs)

        # 关键修复：当从中间段落开始读取时，需要先"空跑"文档前半部分
        # 来同步Word编号计数器，否则编号会从1开始（如4.11变成1.1）
        if p_start > 0:
            for pre_para in doc.paragraphs[:p_start]:
                if pre_para.style.name.startswith('Heading'):
                    pre_text = pre_para.text
                    if not re.match(r'^\d+(\.\d+)*\s', pre_text):
                        pre_numPr = pre_para._p.find(qn('w:numPr'))
                        if pre_numPr is None:
                            try:
                                pre_numPr = pre_para.style.element.find('.//' + qn('w:numPr'))
                            except Exception:
                                pre_numPr = None
                        if pre_numPr is not None:
                            pre_ilvl_el = pre_numPr.find(qn('w:ilvl'))
                            pre_numId_el = pre_numPr.find(qn('w:numId'))
                            if pre_ilvl_el is not None and pre_numId_el is not None:
                                pre_ilvl = int(pre_ilvl_el.get(qn('w:val')))
                                pre_numId = int(pre_numId_el.get(qn('w:val')))
                                pre_key = (pre_numId, pre_ilvl)
                                if pre_key not in num_counters:
                                    num_counters[pre_key] = start_values.get(pre_key, 1)
                                else:
                                    num_counters[pre_key] += 1
                                for k in list(num_counters.keys()):
                                    if k[0] == pre_numId and k[1] > pre_ilvl:
                                        del num_counters[k]

        for para in doc.paragraphs[p_start:p_end]:
            # 处理标题（根据样式判断）
            if para.style.name.startswith('Heading'):
                level = int(para.style.name.split()[-1])
                text = para.text

                # 尝试从 XML 读取自动编号（仅当文本本身无编号前缀时）
                numPr = para._p.find(qn('w:numPr'))
                # 如果段落本身没有numPr，尝试从样式继承
                if numPr is None:
                    try:
                        numPr = para.style.element.find('.//' + qn('w:numPr'))
                    except Exception:
                        numPr = None
                if numPr is not None and not re.match(r'^\d+(\.\d+)*\s', text):
                    ilvl_el = numPr.find(qn('w:ilvl'))
                    numId_el = numPr.find(qn('w:numId'))
                    if ilvl_el is not None and numId_el is not None:
                        ilvl = int(ilvl_el.get(qn('w:val')))
                        numId = int(numId_el.get(qn('w:val')))
                        key = (numId, ilvl)
                        if key not in num_counters:
                            num_counters[key] = start_values.get(key, 1)
                        else:
                            num_counters[key] += 1
                        # 重置更深层级的计数
                        for k in list(num_counters.keys()):
                            if k[0] == numId and k[1] > ilvl:
                                del num_counters[k]
                        # 拼接编号字符串
                        parts = [str(num_counters.get((numId, i), start_values.get((numId, i), 1))) for i in range(ilvl + 1)]
                        number = '.'.join(parts)
                        text = f"{number} {text}"

                markdown_content.append(f"{'#' * level} {text}\n")
            # 处理列表
            elif para.style.name in ['List Paragraph', 'List Bullet']:
                markdown_content.append(f"- {para.text}\n")
            # 普通段落（增加fallback：从段落文本编号推断是否为标题）
            else:
                txt = para.text.strip()
                # fallback：文本以编号开头（如"4.10.1.1. 功能描述"），从中推断Heading级别
                txt_clean = re.sub(r'\t\d+$', '', txt)
                nm = re.match(r'^(\d+(?:\.\d+)*)\.\s*', txt_clean)
                if nm:
                    depth = nm.group(1).count('.') + 1  # "4.10"->3, "4.10.1"->4
                    markdown_content.append(f"{'#' * depth} {txt_clean}\n")
                else:
                    markdown_content.append(f"{txt}\n")

        return ''.join(markdown_content)
    except Exception as e:
        logger.error(f"转换DOCX到Markdown时出错: {str(e)}")
        return ""


# ====== 模块路径提取：黑名单排除法 ======

# 已知的非模块段落标题关键词（文档内容段落，不是模块层级名）
_CONTENT_SECTION_KEYWORDS = [
    # 文档内容段落标题（非模块名）
    '处理流程', '业务逻辑', '业务规则',
    '原型界面', '界面说明', '界面设计', '界面原型',
    '数据要求', '数据字典', '非功能需求', '数据结构',
    '接口说明', '接口设计',
    '流程说明', '流程描述',
    '状态说明', '状态转换', '状态机',
    '备注说明', '补充说明', '其他说明',
    '约束条件', '前提条件', '异常处理',
    '性能要求', '安全要求',
    # 结构性章节标题（非功能模块）
    '功能点划分', '功能描述', '功能说明', '功能概述',
    '需求描述', '总体描述', '概述', '总则',
    '功能需求模型', '项目功能需求',
    # 注意：'功能模块' 不在黑名单中，因为它是合法模块名的一部分
]

def _is_content_section(title_text):
    """判断标题是否为文档内容段落标题（非模块名），命中则返回True"""
    # 1. 关键词黑名单匹配
    for kw in _CONTENT_SECTION_KEYWORDS:
        if kw in title_text:
            return True
    # 2. 去掉章节编号后无实质文字（如纯 "4.3.2.1.2"）
    stripped = re.sub(r'^[\d.]+\s*', '', title_text).strip()
    if not stripped or len(stripped) <= 2:
        return True
    return False


def _parse_md_sections(markdown_text):
    """
    将 markdown 解析为 section 树。
    返回 [(heading_level, heading_text, section_body), ...]，body 为标题后的纯内容行。
    """
    lines = markdown_text.split('\n')
    sections = []
    for i, line in enumerate(lines):
        line = line.rstrip()
        hm = re.match(r'^(#{1,10})\s+(.+)$', line.strip())
        if hm:
            level = len(hm.group(1))
            heading = hm.group(2).strip()
            # body: 从当前行之后到下一个同级或更深标题之前的所有非标题行
            body_lines = []
            for j in range(i + 1, len(lines)):
                nxt = lines[j].strip()
                nxt_hm = re.match(r'^(#{1,10})\s+(.+)$', nxt)
                if nxt_hm and len(nxt_hm.group(1)) >= level:
                    break
                if nxt:
                    body_lines.append(nxt)
            sections.append((level, heading, '\n'.join(body_lines)))
    return sections


def extract_content_with_titles(markdown_text, pattern):
    """
    解析 markdown 结构，对每个模块子节应用正则，提取匹配的内容块及其完整模块路径。
    不再用纯 regex 全局搜索（会错误跨节匹配），而是按章节边界隔离处理。
    核心逻辑：遍历 markdown 标题树，遇到功能点级（H4+）时聚合其直属子节内容再匹配，
    保证模块路径精确到"功能点"层级，子节内容不跨功能点边界。
    关键修复：只用 child_lvl <= lvl 作为停止条件，而非 child_lvl < lvl，
    这样同级节（如 4.10.3.4 vs 4.10.2.4）不会被误收入。
    
    修复：同一功能点下的多个匹配结果合并为一条，避免重复生成用例
    """
    sections = _parse_md_sections(markdown_text)
    result = []

    level_stack = {}  # level -> heading

    i = 0
    while i < len(sections):
        lvl, heading, body = sections[i]

        # 清除更深层级（遇到新同级标题时重置子级）
        for existing_lvl in list(level_stack.keys()):
            if existing_lvl >= lvl:
                del level_stack[existing_lvl]

        level_stack[lvl] = heading

        # 功能点层级（H4+）→ 聚合直属子节内容并匹配
        if lvl >= 4:
            combined_body_lines = []
            j = i + 1
            while j < len(sections):
                child_lvl, child_h, child_body = sections[j]
                # 遇到更浅层级 → 不属于当前功能点，停止收集
                if child_lvl < lvl:
                    break
                # 遇到同级层级 → 检查编号深度：编号段数更多说明仍是子内容，应继续收集
                if child_lvl == lvl:
                    def get_num_segments(text):
                        m = re.match(r'^([\d.]+)', text.strip())
                        return len(m.group(1).split('.')) if m else 0
                    cur_segs = get_num_segments(heading)
                    child_segs = get_num_segments(child_h)
                    # 子节编号段数 > 当前标题段数，说明编号更深，仍是子内容，继续收集
                    # 否则是同级功能点，停止收集
                    if not (child_segs > cur_segs):
                        break
                # 将子节标题也纳入聚合文本，使正则能匹配到标题中的关键词
                if child_body.strip():
                    combined_body_lines.append(f"{child_h}\n{child_body}")
                elif child_h.strip():
                    combined_body_lines.append(child_h)
                j += 1

            combined = '\n'.join(combined_body_lines)
            matches = list(re.finditer(pattern, combined, re.DOTALL))

            if matches:
                path_parts = []
                for l in sorted(level_stack.keys()):
                    h = level_stack[l]
                    if not _is_content_section(h):
                        path_parts.append(h)
                module_name = ' > '.join(path_parts) if path_parts else '未命名模块'
                # 修复：合并同一功能点下的所有匹配内容，而非添加多条记录
                all_matched_content = '\n\n'.join([m.group(1).strip() for m in matches])
                result.append((module_name, all_matched_content))

        i += 1

    return result




from prompt import create_test_case_prompt

def generate_test_cases_parallel(feature_points, max_concurrent=20):
    llm = ChatOpenAI(
                api_key=LLM_API_KEY,
                base_url=LLM_BASE_URL,
                model=LLM_MODEL)
    with ThreadPoolExecutor(max_workers=max_concurrent) as executor:
        #异步执行 ： 向线程池/进程池提交任务
        futures = [executor.submit(llm.invoke, [HumanMessage(content=create_test_case_prompt(fp))]) for fp in feature_points]
        results = [future.result().content for future in futures]
    return results

def write_test_cases_to_excel(module_test_cases, output_file='test_cases.xlsx', problems=None):
    """
    将测试用例结果写入Excel文件，按模块名组织。

    输出列结构（8列）：
        A: 用例编号  — 格式 CS-{前缀}-{序号3位}，每个唯一 module_name 从001递增
        B: 用例标题  — 模块行=模块路径文本；用例行=用例名称
        C: 优先级
        D: 预置条件
        E: 操作步骤
        F: 预期结果
        G: 执行结果  — 默认空，测试时填写
        H: 备注      — P0/P1问题标注（联动 req-quality-scorer 时自动写入）

    用例编号规则：
        前缀：由 `_extract_module_prefix()` 从模块路径中动态提取（自动识别，无需修改）
        编号：每个唯一 module_name 从 001 递增；同前缀跨模块不重复

    参数:
        module_test_cases: 包含模块名和对应测试用例结果的列表，格式为[(module_name, result), ...]
        output_file: 输出的Excel文件路径
        problems: list，评估摘要中的问题列表 [{severity, title, suggest}, ...]，用于备注列
    """
    if problems is None:
        problems = []
    # 构建备注文本（P0/P1 问题汇总）
    p0_notes = [f"{p['severity']} {p['title']}：{p['suggest']}" 
                for p in problems if 'P0' in p.get('severity','') or 'P1' in p.get('severity','')]
    note_banner = '\n'.join(p0_notes) if p0_notes else ''


    # 已使用的前缀计数器（用于防重：同名前缀追加 W\d 后缀）
    used_prefixes = {}

    def _extract_module_prefix(module_name):
        """
        从模块路径名中提取最低级子模块的拼音代码，作为用例编号前缀。

        模块路径示例：
          恶劣天气 > 获取当前事件 > 查看当前事件列表
          → 从括号编码（F_UC_B_ELTQ_DQSJ_SJLB）提取 SJLB

        防重规则：
          如果末级子模块拼音相同，则追加 W\d 后缀区分。
          示例：F_UC_B_FBTZ_SQ_W1 和 F_UC_B_FBTZ_SQ_W2
            → 基础前缀都是 SQ，但分别追加 → SQW1、SQW2

        处理步骤：
          1. 从路径中提取所有括号内编码
          2. 取最后一个编码（最细粒度子级）
          3. 去掉前导固定框架前缀（F_UC_B_ 等）
          4. 提取 W\d 后缀（如有）
          5. 去掉 W\d 后缀，取末段拼音
          6. 检查是否重复：重复则追加 W\d 后缀
        """
        brackets = re.findall(r'[（(]([^)）]+)[）)]', module_name)
        if not brackets:
            return "UNKNOWN"

        # 取最后一个编码（最细粒度的子级）
        last_code = brackets[-1].strip()

        # 去掉前导固定框架前缀
        prefixes_to_try = ['F_UC_B_', 'F_UC_', 'F_U_', 'F_UCB_', 'F_U_']
        for pf in prefixes_to_try:
            if last_code.startswith(pf):
                last_code = last_code[len(pf):]
                break

        # 提取 W\d 后缀（如有）
        w_suffix_match = re.search(r'_?(W\d+)$', last_code)
        w_suffix = w_suffix_match.group(1) if w_suffix_match else ""
        last_code = re.sub(r'_?W\d+$', '', last_code)

        # 去掉框架残留段
        framework_parts = {'U', 'UC', 'B', 'UCB', 'FB', 'FA', 'FC'}
        segments = [p for p in last_code.split('_')
                    if p not in framework_parts and len(p) >= 2]

        if not segments:
            return "UNKNOWN"

        # 取最后一节（最低级子模块）
        base_prefix = segments[-1].upper()

        # 防重检查：如果前缀已使用过，追加 W\d 后缀
        if base_prefix in used_prefixes:
            # 已有同名前缀，需要追加 W 后缀区分
            if w_suffix:
                final_prefix = base_prefix + w_suffix
            else:
                # 没有 W 后缀，用计数器生成
                used_prefixes[base_prefix] += 1
                final_prefix = f"{base_prefix}W{used_prefixes[base_prefix]}"
        else:
            # 首次使用该前缀
            used_prefixes[base_prefix] = 1
            # 如果有 W 后缀，也追加（避免后续冲突）
            final_prefix = base_prefix + w_suffix if w_suffix else base_prefix

        return final_prefix

    # ============================================================
    # 样式定义（与旧版本保持一致）
    # ============================================================
    from openpyxl.styles import PatternFill, Font, Border, Side, GradientFill

    # 表头样式：深蓝色底 + 白色粗体字
    HEADER_FILL   = PatternFill(fill_type='solid', fgColor='4472C4')  # 蓝色
    HEADER_FONT    = Font(name='微软雅黑', bold=True, color='FFFFFF', size=11)
    HEADER_ALIGN   = Alignment(horizontal='center', vertical='center', wrap_text=True)

    # 模块行样式：浅蓝色底（功能点区分色）
    MODULE_FILL    = PatternFill(fill_type='solid', fgColor='DCE6F1')  # 浅蓝
    MODULE_FONT    = Font(name='微软雅黑', bold=True, color='1F3864', size=11)
    MODULE_ALIGN_A = Alignment(horizontal='left',   vertical='center', wrap_text=True)
    MODULE_ALIGN_H = Alignment(horizontal='center',  vertical='center', wrap_text=True)

    # 用例行样式：无底色，字体正常
    CASE_ALIGN_C   = Alignment(horizontal='center', vertical='top',    wrap_text=True)  # 居中列
    CASE_ALIGN_L   = Alignment(horizontal='left',   vertical='top',   wrap_text=True)  # 左对齐列

    # 边框：浅色内边框
    thin = Side(style='thin', color='BDD7EE')
    CELL_BORDER    = Border(left=thin, right=thin, top=thin, bottom=thin)

    # ============================================================
    # 创建一个新的工作簿
    # ============================================================
    wb = Workbook()
    ws = wb.active
    ws.title = "测试用例"

    # ---- 表头行（9列）----
    headers = ['需求编号', '用例编号', '用例等级', '用例标题', '预置条件', '操作步骤', '预期结果', '执行结果', '备注']
    for col_idx, header in enumerate(headers, 1):
        cell = ws.cell(row=1, column=col_idx, value=header)
        cell.fill      = HEADER_FILL
        cell.font      = HEADER_FONT
        cell.alignment = HEADER_ALIGN
        cell.border    = CELL_BORDER
    ws.row_dimensions[1].height = 30

    # ---- 用例编号列样式：无底色，正常字体 ----
    # （用户要求不加底色）

    # 行号从2开始
    row_num = 2

    # 每模块独立计数器，模块切换时重置为0
    prev_module_name = None
    module_seq = 0

    # 解析每个模块的测试用例结果并写入Excel
    for module_name, result in module_test_cases:
        
        # ---- 检查模块名是否包含功能点编码（括号内有任意编码即可）----
        if not re.search(r'[（(][^)）]+[）)]', module_name):
            logger.warning(f"跳过无效模块（无功能点编码）: {module_name[:60]}...")
            continue

        # 模块切换时重置计数器
        if module_name != prev_module_name:
            module_seq = 0
            prev_module_name = module_name

        PREFIX = _extract_module_prefix(module_name)

        # ---- 提取需求编号（取最后一个括号内的编码，即最细粒度子级）----
        req_codes = re.findall(r'[（(]([^)）]+)[）)]', module_name)
        REQ_CODE = req_codes[-1] if req_codes else ''

        # ---- 替换分隔符：> 改为 - ----
        module_name_display = module_name.replace(' > ', ' - ')

        try:
            # ---- 写入模块路径行 ----
            # 列A: 需求编号
            # 列B: 完整模块路径文本
            # 列I: 【模块】标记；B~H 列加边框使表格更整齐
            a_cell = ws.cell(row=row_num, column=1, value=REQ_CODE)
            a_cell.fill      = MODULE_FILL
            a_cell.font      = MODULE_FONT
            a_cell.alignment = MODULE_ALIGN_H
            a_cell.border    = CELL_BORDER
            b_cell = ws.cell(row=row_num, column=2, value=module_name_display)
            b_cell.fill      = MODULE_FILL
            b_cell.font      = MODULE_FONT
            b_cell.alignment = Alignment(horizontal='left', vertical='center', wrap_text=False)
            b_cell.border    = CELL_BORDER
            for col in range(3, 9):   # C~H 列加边框
                c = ws.cell(row=row_num, column=col)
                c.fill      = MODULE_FILL
                c.font      = MODULE_FONT
                c.border    = CELL_BORDER
                c.alignment = Alignment(horizontal='left', vertical='center', wrap_text=False)
            i_cell = ws.cell(row=row_num, column=9, value="【模块】")
            i_cell.fill      = MODULE_FILL
            i_cell.font      = MODULE_FONT
            i_cell.alignment = MODULE_ALIGN_H
            i_cell.border    = CELL_BORDER

            ws.row_dimensions[row_num].height = 60
            row_num += 1
            
            # ---- 验证返回内容是否有效 ----
            # 检查是否包含英文思考过程（无效响应的特征词）
            invalid_patterns = [
                r'generate perhaps',
                r"let'?s generate",
                r'equivalence partitioning',
                r'boundary value analysis',
                r'decision table',
                r'error guessing',
                r'state transition',
                r'We need to',
                r'Now let',
                r'Yes\.',
                r'The code:',
                r'just the JSON',
                r'double-check',
            ]
            is_invalid = False
            for pattern in invalid_patterns:
                if re.search(pattern, result, re.IGNORECASE):
                    is_invalid = True
                    break
            
            # 检查中文比例（有效响应应该主要是中文）
            chinese_chars = sum(1 for c in result if '\u4e00' <= c <= '\u9fff')
            total_chars = len(result.replace(' ', '').replace('\n', ''))
            if total_chars > 50 and chinese_chars / total_chars < 0.5:
                is_invalid = True
            
            if is_invalid:
                logger.warning(f"模块 {module_name} 返回内容无效（含英文思考过程），跳过")
                continue
            
            # 全面预处理JSON内容，提高解析成功率
            # 1. 去除Markdown标记
            result = re.sub(r'^```json\s*|\s*```$', '', result, flags=re.MULTILINE)
            # 2. 去除BOM（字节顺序标记）
            result = result.lstrip('\ufeff')
            # 3. 去除多余的空白字符
            result = result.strip()
            # 4. 处理可能的换行符问题
            result = result.replace('\n', ' ').replace('\r', '')
            # 5. 将中文标点符号转换为英文标点符号（解决主要解析问题）
            chinese_to_english = {
                '，': ',',
                '：': ':',
                '；': ';',
                '。': '.',
                '（': '(',
                '）': ')',
                '【': '[',
                '】': ']',
                '“': '"',
                '”': '"',
                '‘': "'",
                '’': "'",
                '、': ',',
                '《': '<',
                '》': '>',
                '？': '?',
                '！': '!',
                '—': '-',
                '…': '...',
                '≥': '>=',
                '≤': '<='
            }
            for zh, en in chinese_to_english.items():
                result = result.replace(zh, en)
            
            # 6. 修复常见的JSON格式问题
            # 去除多余的逗号（在}或]之前）
            result = re.sub(r',\s*([]}])', r'\1', result)
            # 确保所有字符串使用双引号
            result = re.sub(r"'([^']*?)'", r'"\1"', result)
            # 修复未闭合的字符串（尝试找到最近的引号）
            result = re.sub(r'"([^"]*?)(?=\s*[\]}])', r'"\1"', result)
            
            cases = []
            # 6. 直接提取测试用例字段，不依赖完整JSON解析（更稳健）
            try:
                # 1. 简化处理：直接将结果按用例标题分割，提取每个用例
                # 分割字符串，每个用例以"用例标题"开始
                case_parts = result.split('用例标题')
                
                for i in range(1, len(case_parts)):  # 从1开始，跳过第一个分割部分
                    case_part = case_parts[i]
                    
                    # 2. 提取各个字段（使用简单的字符串处理）
                    case = {}
                    
                    # 用例标题：从当前位置提取到第一个冒号后的内容
                    if '：' in case_part:  # 处理中文冒号
                        title_part = case_part.split('：', 1)[1]
                    else:  # 处理英文冒号
                        title_part = case_part.split(':', 1)[1] if ':' in case_part else ''
                    # 提取标题内容（到第一个引号结束）
                    title = title_part.split('"')[1] if '"' in title_part else ''
                    case['用例标题'] = title.strip()
                    
                    # 优先级
                    if '优先级' in case_part:
                        priority_part = case_part.split('优先级')[1]
                        if '：' in priority_part:
                            priority_content = priority_part.split('：', 1)[1]
                        else:
                            priority_content = priority_part.split(':', 1)[1] if ':' in priority_part else ''
                        priority = priority_content.split('"')[1] if '"' in priority_content else ''
                        case['优先级'] = priority.strip()
                    else:
                        case['优先级'] = ''
                    
                    # 预置条件
                    if '预置条件' in case_part:
                        pre_cond_part = case_part.split('预置条件')[1]
                        if '：' in pre_cond_part:
                            pre_cond_content = pre_cond_part.split('：', 1)[1]
                        else:
                            pre_cond_content = pre_cond_part.split(':', 1)[1] if ':' in pre_cond_part else ''
                        # 提取到下一个字段前的内容
                        for next_field in ['操作步骤', '预期结果', '},', '}]']:
                            if next_field in pre_cond_content:
                                pre_cond_content = pre_cond_content.split(next_field, 1)[0]
                        # 清理引号
                        pre_cond = pre_cond_content.replace('"', '').replace('\'', '')
                        case['预置条件'] = pre_cond.strip()
                    else:
                        case['预置条件'] = ''
                    
                    # 操作步骤
                    if '操作步骤' in case_part:
                        steps_part = case_part.split('操作步骤')[1]
                        if '：' in steps_part:
                            steps_content = steps_part.split('：', 1)[1]
                        else:
                            steps_content = steps_part.split(':', 1)[1] if ':' in steps_part else ''
                        # 提取到下一个字段前的内容
                        for next_field in ['预期结果', '},', '}]']:
                            if next_field in steps_content:
                                steps_content = steps_content.split(next_field, 1)[0]
                        # 清理格式，提取步骤
                        steps = []
                        # 简单处理：按逗号分割，清理引号和空格
                        step_items = steps_content.split('，') if '，' in steps_content else steps_content.split(',')
                        for item in step_items:
                            item = item.replace('"', '').replace('\'', '').replace('[', '').replace(']', '').strip()
                            if item and not item.isspace():
                                steps.append(item)
                        case['操作步骤'] = steps
                    else:
                        case['操作步骤'] = []
                    
                    # 预期结果
                    if '预期结果' in case_part:
                        expected_part = case_part.split('预期结果')[1]
                        if '：' in expected_part:
                            expected_content = expected_part.split('：', 1)[1]
                        else:
                            expected_content = expected_part.split(':', 1)[1] if ':' in expected_part else ''
                        # 提取到用例结束前的内容
                        for end_marker in ['},', '}]']:
                            if end_marker in expected_content:
                                expected_content = expected_content.split(end_marker, 1)[0]
                        # 清理引号
                        expected = expected_content.replace('"', '').replace('\'', '')
                        case['预期结果'] = expected.strip()
                    else:
                        case['预期结果'] = ''
                    
                    # 4. 添加有效的测试用例
                    if case['用例标题']:
                        cases.append(case)
            except Exception as e:
                logger.error(f"直接提取测试用例失败: {str(e)}")
                cases = []
            
            for case in cases:
                # 每模块独立编号，模块切换时从001重新开始
                module_seq += 1
                case_id = f"CS-{PREFIX}-{module_seq:03d}"

                # A: 需求编号
                c = ws.cell(row=row_num, column=1, value=REQ_CODE)
                c.alignment = CASE_ALIGN_C
                c.border    = CELL_BORDER
                # B: 用例编号（无底色，正常字体）
                c = ws.cell(row=row_num, column=2, value=_x(case_id))
                c.alignment = CASE_ALIGN_C
                c.border    = CELL_BORDER
                # C: 用例等级
                c = ws.cell(row=row_num, column=3, value=_x(case.get('用例等级', case.get('优先级', ''))))
                c.alignment = CASE_ALIGN_C
                c.border    = CELL_BORDER
                # D: 用例标题
                c = ws.cell(row=row_num, column=4, value=_x(case.get('用例标题', '')))
                c.alignment = CASE_ALIGN_L
                c.border    = CELL_BORDER
                # E: 预置条件（去旧编号，加 1. 2. 3. 序号，换行显示）
                precond = case.get('预置条件', '')
                if precond:
                    precond = precond.replace('\\n', '\n')
                    raw_parts = re.split(r'[\n;；,，]', precond)
                    lines = []
                    for p in raw_parts:
                        p = p.strip()
                        if not p:
                            continue
                        p = re.sub(r'^\d+[.)、\s]+', '', p)
                        p = re.sub(r'^\d+[)）]\s*', '', p)
                        if p:
                            lines.append(p)
                    precond = '\n'.join(f'{i+1}. {l}' for i, l in enumerate(lines))
                c = ws.cell(row=row_num, column=5, value=_x(precond))
                c.alignment = CASE_ALIGN_L
                c.border    = CELL_BORDER
                # F: 操作步骤（去旧编号，加 1. 2. 3. 序号，换行显示）
                steps = case.get('操作步骤', [])
                # 去掉每步头部残留的旧编号，再统一加新编号
                clean_steps = []
                for s in steps:
                    s = s.strip()
                    if not s:
                        continue
                    # 去掉 "1. " "2. " "1、 " 等前缀
                    s = re.sub(r'^\d+[.)、\s]+', '', s)
                    s = re.sub(r'^\d+[)）]\s*', '', s)
                    if s:
                        clean_steps.append(s)
                steps_str = '\n'.join(f'{i+1}. {s}' for i, s in enumerate(clean_steps)) if clean_steps else ''
                c = ws.cell(row=row_num, column=6, value=_x(steps_str))
                c.alignment = CASE_ALIGN_L
                c.border    = CELL_BORDER
                # G: 预期结果（统一加 1. 2. 3. 序号，自动换行）
                expected = case.get('预期结果', '')
                if expected:
                    import re as _re
                    # 0. 先把字面量 \\n 替换为真正的换行符
                    #    LLM 有时返回 "1. xxx\\n2. yyy"，\\n 是两个字符（反斜杠+n）
                    expected = expected.replace('\\n', '\n')
                    # 1. 按换行符/分号 分割成各 item
                    # 2. 每段去掉头部的旧编号（"1. " "2. " "1、" 等），再统一加新序号
                    raw_parts = _re.split(r'[\n;；]', expected)
                    lines = []
                    for p in raw_parts:
                        p = p.strip()
                        if not p:
                            continue
                        # 去掉头部残留的旧编号（数字+标点）
                        p = _re.sub(r'^\d+[.)、\s]+', '', p)
                        p = _re.sub(r'^\d+[)）]\s*', '', p)
                        if p:
                            lines.append(p)
                    expected = '\n'.join(f'{i+1}. {l}' for i, l in enumerate(lines))
                c = ws.cell(row=row_num, column=7, value=expected)
                c.alignment = CASE_ALIGN_L
                c.border    = CELL_BORDER
                # H: 执行结果（默认空，测试时填写）
                c = ws.cell(row=row_num, column=8, value='')
                c.alignment = CASE_ALIGN_C
                c.border    = CELL_BORDER
                # I: 备注（空列，测试时手工填写）
                c = ws.cell(row=row_num, column=9, value='')
                c.alignment = CASE_ALIGN_L
                c.border    = CELL_BORDER

                row_num += 1
        except json.JSONDecodeError as e:
            logger.error(f"解析测试用例JSON失败: {str(e)}")
            logger.error(f"错误的JSON内容: {result}")
            # 继续处理下一个结果
            continue
        
        # 每个模块处理完后不空行（用户要求）
    
    # ---- 自适应列宽（遍历每列，取最长内容的字符宽度，排除模块行）----
    from openpyxl.utils import get_column_letter
    for col_idx in range(1, ws.max_column + 1):
        col_letter = get_column_letter(col_idx)
        max_len = 0
        for row_idx in range(2, ws.max_row + 1):
            cell = ws.cell(row=row_idx, column=col_idx)
            if cell.value is None:
                continue
            # 跳过模块行（最后一列标记为【模块】）
            if ws.cell(row=row_idx, column=ws.max_column).value == '【模块】':
                continue
            text = str(cell.value)
            for line in text.split('\n'):
                width = sum(2 if '\u4e00' <= ch <= '\u9fff' or ch in '，。、；：""''！？（）《》【】—…≥≤' else 1 for ch in line)
                if width > max_len:
                    max_len = width
        # 表头也参与计算
        header_text = str(ws.cell(1, column=col_idx).value or '')
        for line in header_text.split('\n'):
            width = sum(2 if '\u4e00' <= ch <= '\u9fff' or ch in '，。、；：""''！？（）《》【】—…≥≤' else 1 for ch in line)
            if width > max_len:
                max_len = width
        # 列宽 = 最长内容宽度 + 边距(4字符)，最小10，上限60
        ws.column_dimensions[col_letter].width = max(10, min(max_len + 4, 60))
    
    # 保存Excel文件
    try:
        wb.save(output_file)
        logger.info(f"测试用例已成功写入Excel文件: {output_file}")
    except Exception as e:
        logger.error(f"保存Excel文件失败: {str(e)}")
        raise


# 运行
if __name__ == "__main__":
    # 添加命令行参数解析
    parser = argparse.ArgumentParser(description='根据需求文档生成测试用例')
    parser.add_argument('--project', type=str, default=None,
                        help='项目名称（如 "xxx项目"），用于确定输入输出路径')
    parser.add_argument('--requirements_file', type=str, default=None,
                        help='需求文档路径')
    parser.add_argument('--source-para-range', type=str, default=None,
                        help='原始文档段落范围，格式: start:end，示例: 2754:3055')
    parser.add_argument('--output_file', type=str, default=None,
                       help='输出测试用例路径（默认自动写入 output/ 目录）')
    parser.add_argument('--summary', type=str, default=None,
                       help='评估摘要 JSON 路径（由 req-quality-scorer 生成），传入后在测试用例备注列标注P0/P1问题')
    parser.add_argument('--force', action='store_true',
                       help='强制生成，即使评估等级为 D/E（默认跳过）')
    
    args = parser.parse_args()

    # ---- 确定项目名与路径 ----
    # 标准目录结构：
    #   D:\test-input\{项目名}\input\   ← 需求文档放这边
    #   D:\test-output\{项目名}\output\  ← 测试用例输出这边

    import re as _re
    from datetime import datetime as _datetime

    requirements_file = args.requirements_file

    # 项目名优先级：1) --project 参数  2) 从 --requirements_file 路径提取  3) 交互输入
    project_name = args.project

    if not project_name and requirements_file:
        # 从 --requirements_file 路径提取项目名（input 的父目录）
        if not os.path.isabs(requirements_file):
            requirements_file = os.path.abspath(requirements_file)
        parts = requirements_file.replace('\\', '/').split('/')
        if 'input' in parts:
            idx = parts.index('input')
            project_name = parts[idx - 1] if idx > 0 else None

    if not project_name:
        # 交互输入
        project_name = input("请输入项目名称: ").strip()
        if not project_name:
            print("错误: 项目名称不能为空")
            exit(1)

    # 标准目录
    input_dir = os.path.join(r"D:\test-input", project_name, "input")
    output_dir = os.path.join(r"D:\test-output", project_name, "output")

    # 确保目录存在（自动创建，已存在不报错）
    os.makedirs(input_dir, exist_ok=True)
    os.makedirs(output_dir, exist_ok=True)

    # 查找需求文档（从 input 目录中找）
    if not requirements_file or not os.path.exists(requirements_file):
        docx_files = [f for f in os.listdir(input_dir) if f.endswith('.docx')]
        if docx_files:
            latest_file = max(docx_files, key=lambda f: os.path.getmtime(os.path.join(input_dir, f)))
            requirements_file = os.path.join(input_dir, latest_file)
            logger.info(f"自动选择需求文档: {requirements_file}")
            print(f"[AUTO] 自动选择需求文档: {latest_file}")
        else:
            print(f"提示: 请将需求文档(.docx)放入 {input_dir}")
            exit(1)

    # 解析 --output_file 参数
    output_file = args.output_file
    if not output_file:
        doc_name = project_name
        date_str = _datetime.now().strftime('%Y%m%d')
        # 序号递增：找到同一天最大的序号
        seq = 1
        while True:
            candidate = os.path.join(output_dir, f"{doc_name}功能测试用例_{date_str}-{seq}.xlsx")
            if not os.path.exists(candidate):
                break
            seq += 1
        output_file = candidate
        logger.info(f"自动生成输出路径: {output_file}")
        print(f"[AUTO] 自动生成输出路径: {doc_name}功能测试用例_{date_str}-{seq}.xlsx")

    # ---- 加载评估摘要（如有） ----
    problems = []
    assessment_level = None
    if args.summary and os.path.exists(args.summary):
        try:
            import json as _json
            with open(args.summary, encoding='utf-8') as f:
                summ_data = _json.load(f)
            problems = summ_data.get('problems', [])
            assessment_level = summ_data.get('level', '未知')
            logger.info(f"已加载评估摘要：等级={assessment_level}，问题数={len(problems)}")
            print(f"[SUMMARY] 已加载评估摘要: 等级={assessment_level}, 问题数={len(problems)}")
            # 检查 D/E 级且未加 --force
            if assessment_level in ('D（较差）', 'E（不合格）') and not args.force:
                print(f"[WARN] 评估等级为 {assessment_level}，建议先修复 P0 问题。")
                print(f"       如需强制生成测试用例，请加 --force 参数。")
                # 不退出，继续生成（warning 提示用户）
        except Exception as e:
            logger.warning(f"评估摘要读取失败: {e}，继续生成不含问题标注的用例")
            print(f"[WARN] 评估摘要读取失败: {e}")


    
    # 验证需求文档文件是否存在
    if not os.path.exists(requirements_file):
        logger.error(f"需求文档文件不存在: {requirements_file}")
        print(f"错误: 需求文档文件不存在: {requirements_file}")
        exit(1)
    
    # 确保输出目录存在
    output_dir = os.path.dirname(output_file)
    if output_dir and not os.path.exists(output_dir):
        try:
            os.makedirs(output_dir)
            logger.info(f"已创建输出目录: {output_dir}")
        except Exception as e:
            logger.error(f"创建输出目录失败: {str(e)}")
            print(f"错误: 创建输出目录失败: {str(e)}")
            exit(1)
    
    logger.info(f"开始处理需求文档: {requirements_file}")
    src_para_start = None
    src_para_end = None
    if args.source_para_range:
        try:
            parts = args.source_para_range.split(':')
            src_para_start = int(parts[0])
            src_para_end = int(parts[1])
        except Exception as e:
            print(f"错误: --source-para-range 格式错误: {e}")
            exit(1)
    markdown_text = docx_to_markdown(requirements_file, src_para_start, src_para_end)
    
    if not markdown_text:
        logger.error("无法解析需求文档内容")
        print("错误: 无法解析需求文档内容")
        exit(1)
    
    # 使用用户指定的正则表达式模式
    pattern = r'业务规则(.*?)原型界面'
    extracted_modules = extract_content_with_titles(markdown_text, pattern)
    
    if not extracted_modules:
        # 尝试其他可能的模式
        logger.debug("第一次模式匹配失败，尝试其他模式")
        # 尝试更通用的模式
        pattern = r'业务处理流程及逻辑(.*?)输出数据及界面样式'
        extracted_modules = extract_content_with_titles(markdown_text, pattern)

    if not extracted_modules:
        # 第三次尝试：处理流程及逻辑（无"业务"前缀）
        logger.debug("第二次模式匹配失败，尝试第三种模式")
        pattern = r'处理流程及逻辑(.*?)输出数据及界面样式'
        extracted_modules = extract_content_with_titles(markdown_text, pattern)

    if not extracted_modules:
        # 第四次尝试：处理流程及业务逻辑
        logger.debug("第三次模式匹配失败，尝试第四种模式")
        pattern = r'业务处理流程及业务逻辑(.*?)输出数据及界面样式'
        extracted_modules = extract_content_with_titles(markdown_text, pattern)

    if not extracted_modules:
        logger.warning("未找到匹配的内容，将使用整个文档内容")
        print("警告: 未找到特定模式的内容，将使用整个文档内容")
        extracted_modules = [("未命名模块", markdown_text)]
    
    # ---- 去重：同一功能编码只保留第一次出现 ----
    seen_codes = set()
    deduped_modules = []
    for module_name, content in extracted_modules:
        # 从模块名中提取功能编码
        code_match = re.search(r'F_UC_B_\w+', module_name)
        code = code_match.group(0) if code_match else module_name
        if code not in seen_codes:
            seen_codes.add(code)
            deduped_modules.append((module_name, content))
        else:
            logger.debug(f"跳过重复功能点: {code}")
    
    extracted_modules = deduped_modules
    logger.info(f"已提取 {len(extracted_modules)} 个功能点（去重后）")
    print(f"[INFO] 已提取 {len(extracted_modules)} 个功能点（去重后）")
    
    try:
        # 提取所有内容，用于生成测试用例
        extracted_content = [content for module_name, content in extracted_modules]
        test_cases = generate_test_cases_parallel(extracted_content)
        
        # 将生成的测试用例与对应的模块名结合起来
        module_test_cases = list(zip([module_name for module_name, content in extracted_modules], test_cases))
        
        # 写入Excel文件（传入评估问题列表）
        write_test_cases_to_excel(module_test_cases, output_file=output_file, problems=problems)
        logger.info(f"测试用例生成完成，保存至: {output_file}")
        print(f"成功: 测试用例已生成并保存至 {output_file}")
    except Exception as e:
        logger.error(f"生成测试用例时出错: {str(e)}")
        print(f"错误: 生成测试用例时出错: {str(e)}")
        exit(1)
