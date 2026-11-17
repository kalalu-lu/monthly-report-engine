"""
Markdown → Word（.docx）转换器

用途：把项目里的说明文档转成可直接打开的 Word，保留结构（标题层级、表格、代码块、列表、引用）。

支持的语法子集：
    # / ## / ### 标题
    | 表格 |（含表头分隔行）
    ``` 代码块 ```
    - / * / + 无序列表，1. 有序列表
    > 引用
    **加粗**、`行内代码`
    --- 分隔线（忽略）

用法：
    python tools/md2docx.py <文件或目录> [...]      # 默认输出到同目录同名 .docx
    python tools/md2docx.py <目录> --out <输出目录>
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

from docx import Document
from docx.enum.table import WD_TABLE_ALIGNMENT
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Cm, Pt, RGBColor

INK = RGBColor(0x1F, 0x23, 0x28)
NAVY = RGBColor(0x1F, 0x4E, 0x79)
GRAY = RGBColor(0x5B, 0x64, 0x70)
CODE_BG = "F4F6F8"
HEAD_BG = "EEF3F8"
FONT_BODY = "微软雅黑"
FONT_CODE = "Consolas"

INLINE_RE = re.compile(r"(\*\*.+?\*\*|`[^`]+`)")
HEADING_RE = re.compile(r"^(#{1,6})\s+(.*)$")
ULIST_RE = re.compile(r"^(\s*)[-*+]\s+(.*)$")
OLIST_RE = re.compile(r"^(\s*)(\d+)\.\s+(.*)$")
TABLE_SEP_RE = re.compile(r"^\s*\|?[\s:|-]+\|[\s:|-]*$")


# ---------------------------------------------------------------- 低层工具
def shade(element, color: str) -> None:
    shd = OxmlElement("w:shd")
    shd.set(qn("w:val"), "clear")
    shd.set(qn("w:color"), "auto")
    shd.set(qn("w:fill"), color)
    element.append(shd)


def set_font(run, name: str = FONT_BODY, size: float | None = None,
             bold: bool | None = None, color: RGBColor | None = None) -> None:
    run.font.name = name
    run._element.rPr.rFonts.set(qn("w:eastAsia"), name)
    if size is not None:
        run.font.size = Pt(size)
    if bold is not None:
        run.font.bold = bold
    if color is not None:
        run.font.color.rgb = color


def add_page_number(paragraph) -> None:
    run = paragraph.add_run()
    fld_begin = OxmlElement("w:fldChar")
    fld_begin.set(qn("w:fldCharType"), "begin")
    instr = OxmlElement("w:instrText")
    instr.set(qn("xml:space"), "preserve")
    instr.text = " PAGE "
    fld_end = OxmlElement("w:fldChar")
    fld_end.set(qn("w:fldCharType"), "end")
    run._element.append(fld_begin)
    run._element.append(instr)
    run._element.append(fld_end)
    set_font(run, size=9, color=GRAY)


def add_inline(paragraph, text: str, size: float | None = None) -> None:
    """把 **加粗** 与 `行内代码` 渲染成不同的 run。"""
    for piece in INLINE_RE.split(text):
        if not piece:
            continue
        if piece.startswith("**") and piece.endswith("**"):
            run = paragraph.add_run(piece[2:-2])
            set_font(run, size=size, bold=True)
        elif piece.startswith("`") and piece.endswith("`"):
            run = paragraph.add_run(piece[1:-1])
            set_font(run, name=FONT_CODE, size=(size or 10.5) - 1, color=RGBColor(0xB0, 0x30, 0x2A))
        else:
            run = paragraph.add_run(piece)
            set_font(run, size=size)


# ---------------------------------------------------------------- 文档骨架
def new_document(title: str) -> Document:
    doc = Document()
    section = doc.sections[0]
    section.page_width, section.page_height = Cm(21.0), Cm(29.7)
    for attr, val in (("left_margin", 2.2), ("right_margin", 2.2),
                      ("top_margin", 2.2), ("bottom_margin", 2.0)):
        setattr(section, attr, Cm(val))

    normal = doc.styles["Normal"]
    normal.font.name = FONT_BODY
    normal.font.size = Pt(10.5)
    normal.font.color.rgb = INK
    normal.element.rPr.rFonts.set(qn("w:eastAsia"), FONT_BODY)
    pf = normal.paragraph_format
    pf.line_spacing = 1.5
    pf.space_after = Pt(4)

    # 页脚页码
    footer_p = section.footer.paragraphs[0]
    footer_p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    add_page_number(footer_p)
    return doc


def add_heading(doc: Document, level: int, text: str) -> None:
    # 标题里不保留 markdown 标记：`code` 和 **加粗** 直接去掉符号
    text = text.replace("`", "").replace("**", "")
    if level == 1:
        p = doc.add_paragraph()
        p.paragraph_format.space_before = Pt(6)
        p.paragraph_format.space_after = Pt(10)
        run = p.add_run(text)
        set_font(run, size=19, bold=True, color=NAVY)
        # 标题下加一条细线
        pPr = p._p.get_or_add_pPr()
        borders = OxmlElement("w:pBdr")
        bottom = OxmlElement("w:bottom")
        bottom.set(qn("w:val"), "single")
        bottom.set(qn("w:sz"), "6")
        bottom.set(qn("w:space"), "4")
        bottom.set(qn("w:color"), "C9D4E0")
        borders.append(bottom)
        pPr.append(borders)
    elif level == 2:
        p = doc.add_paragraph()
        p.paragraph_format.space_before = Pt(12)
        p.paragraph_format.space_after = Pt(5)
        run = p.add_run(text)
        set_font(run, size=14, bold=True, color=NAVY)
    elif level == 3:
        p = doc.add_paragraph()
        p.paragraph_format.space_before = Pt(8)
        p.paragraph_format.space_after = Pt(3)
        run = p.add_run(text)
        set_font(run, size=11.5, bold=True, color=INK)
    else:
        p = doc.add_paragraph()
        p.paragraph_format.space_before = Pt(6)
        run = p.add_run(text)
        set_font(run, size=10.5, bold=True, color=GRAY)


def add_code_block(doc: Document, lines: list[str]) -> None:
    for i, line in enumerate(lines):
        p = doc.add_paragraph()
        pf = p.paragraph_format
        pf.line_spacing = 1.15
        pf.space_before = Pt(0)
        pf.space_after = Pt(0)
        pf.left_indent = Cm(0.5)
        pf.keep_with_next = i < len(lines) - 1
        shade(p._p.get_or_add_pPr(), CODE_BG)
        run = p.add_run(line if line else " ")
        set_font(run, name=FONT_CODE, size=9, color=RGBColor(0x24, 0x29, 0x2F))


def add_table(doc: Document, header: list[str], rows: list[list[str]]) -> None:
    table = doc.add_table(rows=1, cols=len(header))
    table.style = "Table Grid"
    table.alignment = WD_TABLE_ALIGNMENT.CENTER
    table.autofit = True

    hdr = table.rows[0].cells
    for i, text in enumerate(header):
        hdr[i].text = ""
        p = hdr[i].paragraphs[0]
        p.paragraph_format.space_after = Pt(2)
        add_inline(p, text, size=9.5)
        for run in p.runs:
            run.font.bold = True
            run.font.color.rgb = RGBColor(0x33, 0x52, 0x6E)
        shade(hdr[i]._tc.get_or_add_tcPr(), HEAD_BG)

    for row in rows:
        cells = table.add_row().cells
        for i in range(len(header)):
            cells[i].text = ""
            p = cells[i].paragraphs[0]
            p.paragraph_format.space_after = Pt(2)
            add_inline(p, row[i] if i < len(row) else "", size=9.5)

    doc.add_paragraph().paragraph_format.space_after = Pt(2)


def split_row(line: str) -> list[str]:
    s = line.strip()
    if s.startswith("|"):
        s = s[1:]
    if s.endswith("|"):
        s = s[:-1]
    return [c.strip() for c in s.split("|")]


# ---------------------------------------------------------------- 主流程
def convert(md_path: Path, out_path: Path) -> tuple[int, int]:
    lines = md_path.read_text(encoding="utf-8").splitlines()
    doc = new_document(md_path.stem)
    i, n_par, n_tbl = 0, 0, 0
    in_code = False
    code_buf: list[str] = []
    first_heading_done = False

    while i < len(lines):
        line = lines[i]

        if line.strip().startswith("```"):
            if in_code:
                add_code_block(doc, code_buf)
                code_buf, in_code = [], False
            else:
                in_code = True
            i += 1
            continue
        if in_code:
            code_buf.append(line)
            i += 1
            continue

        stripped = line.strip()
        if not stripped:
            i += 1
            continue

        # 表格
        if stripped.startswith("|") and i + 1 < len(lines) and TABLE_SEP_RE.match(lines[i + 1]):
            header = split_row(stripped)
            rows = []
            i += 2
            while i < len(lines) and lines[i].strip().startswith("|"):
                rows.append(split_row(lines[i]))
                i += 1
            add_table(doc, header, rows)
            n_tbl += 1
            continue

        # 标题
        m = HEADING_RE.match(stripped)
        if m:
            level = len(m.group(1))
            text = m.group(2).strip()
            if level == 1 and not first_heading_done:
                first_heading_done = True
            add_heading(doc, level, text)
            n_par += 1
            i += 1
            continue

        # 分隔线
        if re.match(r"^(-{3,}|\*{3,}|_{3,})$", stripped):
            i += 1
            continue

        # 引用
        if stripped.startswith(">"):
            text = stripped.lstrip(">").strip()
            p = doc.add_paragraph()
            p.paragraph_format.left_indent = Cm(0.6)
            p.paragraph_format.space_before = Pt(3)
            p.paragraph_format.space_after = Pt(3)
            add_inline(p, text, size=10)
            for run in p.runs:
                run.font.color.rgb = GRAY
            pPr = p._p.get_or_add_pPr()
            borders = OxmlElement("w:pBdr")
            left = OxmlElement("w:left")
            left.set(qn("w:val"), "single")
            left.set(qn("w:sz"), "12")
            left.set(qn("w:space"), "6")
            left.set(qn("w:color"), "9DB2C8")
            borders.append(left)
            pPr.append(borders)
            n_par += 1
            i += 1
            continue

        # 列表
        m = ULIST_RE.match(line)
        if m:
            indent = len(m.group(1))
            style = "List Bullet" if indent < 2 else "List Bullet 2"
            p = doc.add_paragraph(style=style)
            p.paragraph_format.space_after = Pt(2)
            add_inline(p, m.group(2))
            n_par += 1
            i += 1
            continue
        m = OLIST_RE.match(line)
        if m:
            p = doc.add_paragraph(style="List Number")
            p.paragraph_format.space_after = Pt(2)
            add_inline(p, m.group(3))
            n_par += 1
            i += 1
            continue

        # 普通段落（连续行合并）
        buf = [stripped]
        i += 1
        while (i < len(lines) and lines[i].strip()
               and not HEADING_RE.match(lines[i].strip())
               and not lines[i].strip().startswith(("```", "|", ">"))
               and not ULIST_RE.match(lines[i]) and not OLIST_RE.match(lines[i])
               and not re.match(r"^(-{3,}|\*{3,})$", lines[i].strip())):
            buf.append(lines[i].strip())
            i += 1
        p = doc.add_paragraph()
        p.paragraph_format.first_line_indent = Cm(0.0)
        add_inline(p, " ".join(buf))
        n_par += 1

    if code_buf:
        add_code_block(doc, code_buf)

    out_path.parent.mkdir(parents=True, exist_ok=True)
    doc.save(out_path)
    return n_par, n_tbl


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("targets", nargs="+", help="md 文件或目录")
    ap.add_argument("--out", help="输出目录（默认与源文件同目录）")
    ap.add_argument("--exclude", default=".dsh", help="路径中含此片段则跳过")
    args = ap.parse_args()

    files: list[Path] = []
    for t in args.targets:
        p = Path(t)
        if p.is_dir():
            files += sorted(p.rglob("*.md"))
        elif p.suffix.lower() == ".md":
            files.append(p)

    out_dir = Path(args.out) if args.out else None
    done = 0
    for f in files:
        if args.exclude and args.exclude in str(f):
            continue
        target = (out_dir / f"{f.stem}.docx") if out_dir else f.with_suffix(".docx")
        try:
            n_par, n_tbl = convert(f, target)
            done += 1
            print(f"OK  {f.name} → {target.name}  (段落 {n_par} / 表格 {n_tbl})")
        except Exception as e:  # noqa: BLE001
            print(f"FAIL {f.name}: {type(e).__name__}: {e}")
    print(f"\n共转换 {done} 个文件")
    return 0 if done else 1


if __name__ == "__main__":
    sys.exit(main())
