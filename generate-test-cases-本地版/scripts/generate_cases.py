from docx import Document
import re
import os
import json
from langchain_openai import ChatOpenAI
from langchain.schema import HumanMessage
import configparser
import logging
from openpyxl import Workbook
from openpyxl.styles import Alignment
from concurrent.futures import ThreadPoolExecutor
import argparse

# 配置日志
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# 读取配置文件，使用相对路径或允许用户指定
config = configparser.ConfigParser()
# 尝试读取配置文件，如果失败则提示用户设置
config_file_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'config.ini')
if not os.path.exists(config_file_path):
    # 创建默认配置文件
    config['openai-chat'] = {'api_key': 'your_api_key_here'}
    with open(config_file_path, 'w') as f:
        config.write(f)
    print(f"配置文件已创建: {config_file_path}，请填入您的API密钥")
    exit(1)

config.read(config_file_path)
api_key = config.get("openai-chat", "api_key")

# 检查API密钥是否已设置
if api_key == 'your_api_key_here':
    print(f"请在配置文件 {config_file_path} 中填入您的API密钥")
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


def docx_to_markdown(docx_path):
    """将docx文档转换为markdown格式"""
    try:
        from docx.oxml.ns import qn
        doc = Document(docx_path)
        markdown_content = []
        start_values = _get_num_start_values(doc)
        # num_counters: {(numId, ilvl): current_count}
        num_counters = {}

        for para in doc.paragraphs:
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
            # 普通段落
            else:
                markdown_content.append(f"{para.text}\n")

        return ''.join(markdown_content)
    except Exception as e:
        logger.error(f"转换DOCX到Markdown时出错: {str(e)}")
        return ""


def extract_content_with_titles(markdown_text, pattern):
    """从Markdown文件中提取匹配正则表达式的内容及其直属标题"""
    # # 读取Markdown文件
    # with open(markdown_file, 'r', encoding='utf-8') as f:
    #     markdown_text = f.read()
    
    # 查找所有匹配的内容及其位置
    matches = list(re.finditer(pattern, markdown_text, re.DOTALL))
    result = []
    
    for match in matches:
        # 获取匹配内容
        content = match.group(1).strip()
        
        # 获取匹配内容之前的文本，用于查找上一个层级
        before_match = markdown_text[:match.start()]
        
        # 从后向前收集所有层级标题，构建完整模块路径
        lines = before_match.split('\n')
        heading_map = {}
        current_min_level = 99

        for line in reversed(lines):
            line = line.strip()
            if line:
                title_match = re.match(r'^(#{1,10})\s+(.+)$', line)
                if title_match:
                    level = len(title_match.group(1))
                    title = title_match.group(2).strip()
                    if level < current_min_level:
                        heading_map[level] = title
                        current_min_level = level

        if heading_map:
            sorted_levels = sorted(heading_map.keys())
            # 去掉第一级（文档总标题）和最后两级（内容节标题），只保留功能模块层级
            middle_levels = sorted_levels[1:-2]
            if middle_levels:
                module_name = ' > '.join(heading_map[l] for l in middle_levels)
            elif len(sorted_levels) >= 2:
                # 层级不足时取第二级
                module_name = heading_map[sorted_levels[1]]
            else:
                module_name = heading_map[sorted_levels[0]]
        else:
            module_name = "未命名模块"

        result.append((module_name, content))
    
    return result


# 使用字符串格式化而不是PromptTemplate来避免变量解析问题
def create_test_case_prompt(feature_point):
    # 先定义完整的模板字符串，使用双花括号来转义JSON中的花括号
    prompt = """
    需求：{feature_point}
    # 角色
    你是一位资深的软件测试专家，善于根据需求编写详细测试用例。

    ## 目标
    你需要根据需求内容，编写详细可执行的测试用例。

    ## 测试用例设计方法与技巧
    ### 必须应用的6种测试设计方法
    1. **等价类划分 (Equivalence Class Partitioning)**
       - 将输入数据划分为有效的和无效的等价类
       - 从每个等价类中选取一个或少数代表性数据作为测试输入
       - 每个等价类至少设计1个测试用例

    2. **边界值分析 (Boundary Value Analysis)**
       - 重点测试输入和输出的边界条件（最小值、最大值、略高于最小值、略低于最大值、空值、临界长度等）
       - 边界值分析是等价类划分的补充
       - 包括正常边界、异常边界、特殊边界测试

    3. **判定表驱动法 (Decision Table Testing)**
       - 适用于有多个条件组合，并且每个组合对应不同操作的场景
       - 列出所有条件桩和动作桩，形成判定表
       - 确保所有条件组合都被测试覆盖

    4. **场景法 (Use Case/Scenario Testing)**
       - 基于用户实际使用系统的场景来设计测试用例
       - 模拟用户操作流程，验证系统在真实场景下的行为
       - 包括正常场景、异常场景、边界场景

    5. **错误猜测法 (Error Guessing)**
       - 基于经验、直觉和对系统薄弱环节的分析，推测可能存在的缺陷和错误
       - 常用于补充其他结构化测试方法
       - 关注系统容易出错的地方

    6. **状态迁移法 (State Transition Testing)**
       - 适用于被测对象具有明确状态转换的系统或模块
       - 关注系统在不同状态之间的转换路径和事件触发
       - 验证状态转换的正确性和完整性


    ## 工作流
    1. 分析用户提供的每个需求。
    2. 依次把每个需求，转换为详细测试用例，内容包含用例标题 优先级 预置条件 操作步骤 预期结果。
    3. 编写用例完成后，检查用例，确保所有测试点全部被用例覆盖。

    ## 输出格式：
    请严格按照以下JSON格式输出，不要添加任何额外的说明文字或Markdown标记：
    {{"cases":[{{"用例标题":"<用例标题>","优先级":"高","预置条件":"<预置条件>","操作步骤":["<步骤一>","<步骤二>"...],"预期结果":"<期望结果>"}},{{"用例标题":"<用例标题>","优先级":"中","预置条件":"<预置条件>","操作步骤":["<步骤一>","<步骤二>"...],"预期结果":"<期望结果>"}}]}}}}

    ## 限制：
    1. 输出内容必须是一个合法的JSON字符串
    2. 请确保JSON格式严格正确，特别是字符串的引号和逗号
    3. 不要在JSON外部添加任何其他内容
    4. 优先级只能是：高、中、低中的一个
    """
    # 使用字符串format方法进行格式化，避免f-string解析问题
    return prompt.format(feature_point=feature_point)

def generate_test_cases_parallel(feature_points, max_concurrent=20):
    llm = ChatOpenAI(
                api_key=api_key,
                base_url="https://api.siliconflow.cn/v1",
                model="deepseek-ai/DeepSeek-V3.1")
    with ThreadPoolExecutor(max_workers=max_concurrent) as executor:
        #异步执行 ： 向线程池/进程池提交任务
        futures = [executor.submit(llm.invoke, [HumanMessage(content=create_test_case_prompt(fp))]) for fp in feature_points]
        results = [future.result().content for future in futures]
    return results

def write_test_cases_to_excel(module_test_cases, output_file='test_cases.xlsx'):
    """
    将测试用例结果写入Excel文件，按模块名组织
    
    参数:
        module_test_cases: 包含模块名和对应测试用例结果的列表，格式为[(module_name, result), ...]
        output_file: 输出的Excel文件路径
    """
    # 创建一个新的工作簿
    wb = Workbook()
    ws = wb.active
    ws.title = "测试用例"
    
    # 设置表头
    headers = ['用例标题', '优先级', '预置条件', '操作步骤', '预期结果']
    for col_idx, header in enumerate(headers, 1):
        ws.cell(row=1, column=col_idx, value=header)
        # 设置表头样式
        ws.cell(row=1, column=col_idx).alignment = Alignment(horizontal='center', vertical='center')
    
    # 行号从2开始，因为第一行是表头
    row_num = 2
    
    # 解析每个模块的测试用例结果并写入Excel
    for module_name, result in module_test_cases:
        try:
            # 写入模块名，合并单元格
            ws.merge_cells(start_row=row_num, start_column=1, end_row=row_num, end_column=5)
            ws.cell(row=row_num, column=1, value=module_name)
            # 设置模块名样式：靠左对齐
            ws.cell(row=row_num, column=1).alignment = Alignment(horizontal='left', vertical='top')
            # 设置行高为五行的高度（默认行高约为15，五行约为75）
            ws.row_dimensions[row_num].height = 75
            row_num += 1
            
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
                # 写入用例标题
                ws.cell(row=row_num, column=1, value=case.get('用例标题', ''))
                # 写入优先级
                ws.cell(row=row_num, column=2, value=case.get('优先级', ''))
                # 写入预置条件
                ws.cell(row=row_num, column=3, value=case.get('预置条件', ''))
                # 写入操作步骤，将列表转换为字符串
                steps = case.get('操作步骤', [])
                steps_str = '\n'.join(steps) if steps else ''
                ws.cell(row=row_num, column=4, value=steps_str)
                # 设置操作步骤单元格自动换行
                ws.cell(row=row_num, column=4).alignment = Alignment(wrap_text=True)
                # 写入预期结果
                ws.cell(row=row_num, column=5, value=case.get('预期结果', ''))
                # 设置预期结果单元格自动换行
                ws.cell(row=row_num, column=5).alignment = Alignment(wrap_text=True)
                
                row_num += 1
        except json.JSONDecodeError as e:
            logger.error(f"解析测试用例JSON失败: {str(e)}")
            logger.error(f"错误的JSON内容: {result}")
            # 继续处理下一个结果
            continue
        
        # # 每个模块处理完后空两行
        # row_num += 2
    
    # 调整列宽以适应内容
    for col_idx in range(1, 6):
        ws.column_dimensions[chr(64 + col_idx)].width = 30
    
    # 保存Excel文件
    try:
        wb.save(output_file)
        logger.info(f"测试用例已成功写入Excel文件: {output_file}")
    except Exception as e:
        logger.error(f"保存Excel文件失败: {str(e)}")


# 运行
if __name__ == "__main__":
    # 添加命令行参数解析
    parser = argparse.ArgumentParser(description='根据需求文档生成测试用例')
    parser.add_argument('--requirements_file', type=str, default='需求文档.docx', 
                       help='需求文档路径')
    parser.add_argument('--output_file', type=str, default='测试用例.xlsx',
                       help='输出测试用例路径')
    
    args = parser.parse_args()
    
    # 使用命令行参数或默认值
    requirements_file = args.requirements_file
    output_file = args.output_file
    
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
    markdown_text = docx_to_markdown(requirements_file)
    
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
        logger.warning("未找到匹配的内容，将使用整个文档内容")
        print("警告: 未找到特定模式的内容，将使用整个文档内容")
        extracted_modules = [("未命名模块", markdown_text)]
    
    logger.info(f"已提取 {len(extracted_modules)} 个功能点")
    
    try:
        # 提取所有内容，用于生成测试用例
        extracted_content = [content for module_name, content in extracted_modules]
        test_cases = generate_test_cases_parallel(extracted_content)
        
        # 将生成的测试用例与对应的模块名结合起来
        module_test_cases = list(zip([module_name for module_name, content in extracted_modules], test_cases))
        
        # 写入Excel文件
        write_test_cases_to_excel(module_test_cases, output_file=output_file)
        logger.info(f"测试用例生成完成，保存至: {output_file}")
        print(f"成功: 测试用例已生成并保存至 {output_file}")
    except Exception as e:
        logger.error(f"生成测试用例时出错: {str(e)}")
        print(f"错误: 生成测试用例时出错: {str(e)}")
        exit(1)
