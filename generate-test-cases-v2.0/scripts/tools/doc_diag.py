from docx import Document
from docx.oxml.ns import qn
import sys
import os

doc_path = sys.argv[1] if len(sys.argv) > 1 else None
if not doc_path:
    # 查找input目录下第一个docx
    input_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..', 'input')
    for f in os.listdir(input_dir):
        if f.endswith('.docx'):
            doc_path = os.path.join(input_dir, f)
            break

print(f"文档: {doc_path}")
doc = Document(doc_path)

print("\n=== 标题段落XML ===\n")
for para in doc.paragraphs:
    if para.style.name.startswith('Heading'):
        numPr = para._p.find(qn('w:numPr'))
        # 检查样式是否继承了numPr
        style_numPr = None
        try:
            style_numPr = para.style.element.find('.//' + qn('w:numPr'))
        except Exception:
            pass
        print(f"[{para.style.name}] text={repr(para.text[:50])}")
        print(f"  para numPr: {numPr is not None}")
        print(f"  style numPr: {style_numPr is not None}")
        if numPr is not None:
            ilvl = numPr.find(qn('w:ilvl'))
            numId = numPr.find(qn('w:numId'))
            print(f"  ilvl={ilvl.get(qn('w:val')) if ilvl is not None else None}, numId={numId.get(qn('w:val')) if numId is not None else None}")
        if style_numPr is not None:
            ilvl = style_numPr.find(qn('w:ilvl'))
            numId = style_numPr.find(qn('w:numId'))
            print(f"  style ilvl={ilvl.get(qn('w:val')) if ilvl is not None else None}, style numId={numId.get(qn('w:val')) if numId is not None else None}")
        print()