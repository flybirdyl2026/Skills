#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
docx 转 md 工具
从 docx 文件中提取文本并转换为 Markdown 格式
"""

import sys
import re
import zipfile
from pathlib import Path


def extract_text_from_docx(docx_path: str) -> str:
    """
    从 docx 文件中提取纯文本
    优先使用 python-docx，失败则回退到 XML 直接解析
    """
    # 尝试用 python-docx 提取
    try:
        from docx import Document
        doc = Document(docx_path)
        paragraphs = []
        for para in doc.paragraphs:
            text = para.text.strip()
            if text:
                paragraphs.append(text)

        result = '\n\n'.join(paragraphs)
        # 检查是否成功提取（非乱码）
        if result and not is_garbled(result):
            return result
    except Exception as e:
        print(f"python-docx 提取失败: {e}", file=sys.stderr)

    # 回退到 XML 直接解析
    return extract_from_xml(docx_path)


def is_garbled(text: str, threshold: float = 0.3) -> bool:
    """
    检查文本是否乱码（包含无法识别的字符过多）
    """
    if not text:
        return True
    # 计算乱码字符比例（中文范围和其他语言字符）
    import re
    # 统计可识别中文字符
    chinese_chars = len(re.findall(r'[一-鿿]', text))
    total_chars = len(text.replace(' ', '').replace('\n', ''))
    if total_chars == 0:
        return True
    return chinese_chars / total_chars < threshold


def extract_from_xml(docx_path: str) -> str:
    """
    直接从 docx 的 XML 中提取文本
    """
    with zipfile.ZipFile(docx_path, 'r') as z:
        with z.open('word/document.xml') as f:
            content = f.read().decode('utf-8', errors='ignore')

    # 提取所有 w:t 标签内的文本
    text_runs = re.findall(r'<w:t[^>]*>([^<]*)</w:t>', content)

    # 合并文本
    full_text = ''
    for run in text_runs:
        # 处理转义字符
        run = run.replace('&amp;', '&').replace('&lt;', '<').replace('&gt;', '>').replace('&quot;', '"').replace('&#xA;', '\n')
        full_text += run

    # 按段落分组（基于原始 XML 结构）
    # 重新解析 XML 以保持段落结构
    paragraphs = re.split(r'</w:p>', content)
    para_texts = []

    for para in paragraphs:
        # 提取段落内的所有文本
        runs = re.findall(r'<w:t[^>]*>([^<]*)</w:t>', para)
        para_text = ''.join(runs).strip()
        if para_text:
            para_texts.append(para_text)

    return '\n\n'.join(para_texts)


def convert_to_markdown(text: str) -> str:
    """
    将纯文本转换为基本的 Markdown 格式
    """
    lines = text.split('\n')
    md_lines = []

    for line in lines:
        line = line.strip()
        if not line:
            md_lines.append('')
            continue

        # 标题识别（TOC 条目等）
        if re.match(r'^\d+(\.\d+)+[\s一-鿿]', line):
            # 可能是标题
            level = len(re.match(r'^(\d+\.)*', line).group())
            if level <= 4:
                md_lines.append(f"{'#' * (level)} {line}")
                continue

        md_lines.append(line)

    return '\n\n'.join(md_lines)


def docx_to_md(docx_path: str, output_path: str = None) -> str:
    """
    主转换函数
    返回转换后的 md 文件路径
    """
    docx_file = Path(docx_path)
    if not docx_file.exists():
        raise FileNotFoundError(f"文件不存在: {docx_path}")

    if output_path is None:
        # 默认输出到同目录下的同名 .md 文件
        output_path = docx_file.with_suffix('.md')

    # 提取文本
    text = extract_text_from_docx(docx_path)

    # 转换为 Markdown
    md_content = convert_to_markdown(text)

    # 写入文件
    with open(output_path, 'w', encoding='utf-8') as f:
        f.write(md_content)

    return output_path


if __name__ == '__main__':
    if len(sys.argv) < 2:
        print("用法: python docx_to_md.py <docx文件路径> [输出md路径]")
        sys.exit(1)

    docx_path = sys.argv[1]
    output_path = sys.argv[2] if len(sys.argv) > 2 else None

    try:
        result = docx_to_md(docx_path, output_path)
        print(f"转换完成: {result}")
    except Exception as e:
        print(f"转换失败: {e}", file=sys.stderr)
        sys.exit(1)
