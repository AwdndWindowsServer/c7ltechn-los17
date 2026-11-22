#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
md2docx.py — 零依赖的 Markdown → .docx 生成器（手写 OOXML）

  用法: python3 tools/md2docx.py <输入.md> <输出.docx> [--title "封面标题"]

为什么自己写：这台机器上没有 pandoc / libreoffice，pip 又被 PEP668 挡住，
但 .docx 本质就是个 zip + 几个 XML，直接生成最省事、也最可靠。

支持的 Markdown 子集（够写工程文档）：
  # ## ### ####  标题（映射到 Heading1-4）
  - * 或 1.      无序/有序列表（统一渲染成带缩进的 • 段落，少一层 numbering.xml 依赖）
  | a | b |      表格（首行当表头，加粗 + 灰底）
  ```…```        代码块（等宽字体 + 浅灰底，保留缩进）
  >              引用/注意事项（灰底方框样式）
  ---            分隔线
  **粗体**  `行内代码`
"""

import html
import os
import re
import sys
import zipfile

CT = '''<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>
<Default Extension="xml" ContentType="application/xml"/>
<Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>
<Override PartName="/word/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.styles+xml"/>
</Types>'''

RELS = '''<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/>
</Relationships>'''

DOC_RELS = '''<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles" Target="styles.xml"/>
</Relationships>'''

# 中文字体：西文用 Segoe UI/Calibri，eastAsia 用微软雅黑（Windows/Mac Word 都常见）
FONTS = ('<w:rFonts w:ascii="Segoe UI" w:hAnsi="Segoe UI" w:eastAsia="\u5fae\u8f6f\u96c5\u9ed1" '
         'w:cs="Segoe UI"/>')
MONO = '<w:rFonts w:ascii="Consolas" w:hAnsi="Consolas" w:eastAsia="\u5b8b\u4f53" w:cs="Consolas"/>'


def _styles():
    def st(sid, name, size, bold=False, before=120, after=80, outline=None, base="Normal"):
        b = '<w:b/><w:bCs/>' if bold else ''
        ol = '<w:outlineLvl w:val="%d"/>' % outline if outline is not None else ''
        return ('<w:style w:type="paragraph" w:styleId="%s"><w:name w:val="%s"/><w:basedOn w:val="%s"/>'
                '<w:pPr><w:spacing w:before="%d" w:after="%d"/><w:keepNext/>%s</w:pPr>'
                '<w:rPr>%s<w:sz w:val="%d"/><w:szCs w:val="%d"/>%s</w:rPr></w:style>'
                % (sid, name, base, before, after, ol, FONTS, size, size, b))

    return ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<w:styles xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
            '<w:docDefaults><w:rPrDefault><w:rPr>%s<w:sz w:val="21"/><w:szCs w:val="21"/></w:rPr>'
            '</w:rPrDefault><w:pPrDefault><w:pPr>'
            '<w:spacing w:after="80" w:line="300" w:lineRule="auto"/></w:pPr></w:pPrDefault>'
            '</w:docDefaults>'
            '<w:style w:type="paragraph" w:default="1" w:styleId="Normal"><w:name w:val="Normal"/>'
            '<w:qFormat/></w:style>'
            + st("Heading1", "heading 1", 36, True, 300, 140, 0)
            + st("Heading2", "heading 2", 28, True, 260, 120, 1)
            + st("Heading3", "heading 3", 24, True, 220, 100, 2)
            + st("Heading4", "heading 4", 22, True, 180, 80, 3)
            + '<w:style w:type="paragraph" w:styleId="Code"><w:name w:val="Code"/><w:basedOn w:val="Normal"/>'
              '<w:pPr><w:spacing w:before="0" w:after="0"/><w:shd w:val="clear" w:color="auto" w:fill="F4F4F4"/>'
              '<w:ind w:left="120"/></w:pPr><w:rPr>%s<w:sz w:val="18"/></w:rPr></w:style>' % MONO
            + '<w:style w:type="paragraph" w:styleId="Quote"><w:name w:val="Quote"/><w:basedOn w:val="Normal"/>'
              '<w:pPr><w:shd w:val="clear" w:color="auto" w:fill="FFF7E0"/>'
              '<w:ind w:left="200"/><w:pBdr><w:left w:val="single" w:sz="18" w:space="6" w:color="E0A800"/></w:pBdr>'
              '</w:pPr></w:style>'
            + '<w:style w:type="paragraph" w:styleId="Bullet"><w:name w:val="Bullet"/><w:basedOn w:val="Normal"/>'
              '<w:pPr><w:ind w:left="420" w:hanging="240"/></w:pPr></w:style>'
            + '</w:styles>')


def esc(t):
    return html.escape(t, quote=False)


def runs(text, force_code=False, bold=False):
    """把一段文本转成若干 <w:r>：支持 **粗体** 与 `行内代码`。"""
    out = []

    def run(t, b=False, code=False):
        if t == "":
            return
        rpr = "<w:rPr>"
        if code:
            rpr += MONO
        else:
            rpr += FONTS
        if b:
            rpr += "<w:b/>"
        if code:
            rpr += '<w:shd w:val="clear" w:color="auto" w:fill="F0F0F0"/>'
        rpr += "</w:rPr>"
        out.append('<w:r>%s<w:t xml:space="preserve">%s</w:t></w:r>' % (rpr, esc(t)))

    if force_code:
        run(text, code=True)
        return "".join(out)
    for part in re.split(r"(\*\*[^*]+\*\*|`[^`]+`)", text):
        if not part:
            continue
        if part.startswith("**") and part.endswith("**"):
            run(part[2:-2], b=True)
        elif part.startswith("`") and part.endswith("`"):
            run(part[1:-1], code=True)
        else:
            run(part, b=bold)
    return "".join(out)


def para(text, style=None, extra_ppr="", code_block=None):
    ppr = "<w:pPr>"
    if style:
        ppr += '<w:pStyle w:val="%s"/>' % style
    ppr += extra_ppr + "</w:pPr>"
    if code_block is not None:
        # 代码块：一个段落里用 <w:br/> 分行，保留缩进
        lines = code_block.split("\n")
        body = ""
        for i, ln in enumerate(lines):
            if i:
                body += "<w:r><w:br/></w:r>"
            body += ('<w:r><w:rPr>%s<w:sz w:val="18"/></w:rPr>'
                     '<w:t xml:space="preserve">%s</w:t></w:r>' % (MONO, esc(ln)))
        return "<w:p>%s%s</w:p>" % (ppr, body)
    return "<w:p>%s%s</w:p>" % (ppr, runs(text))


def table(rows):
    borders = ('<w:tblBorders>'
               + "".join('<w:%s w:val="single" w:sz="4" w:space="0" w:color="BBBBBB"/>' % s
                         for s in ("top", "left", "bottom", "right", "insideH", "insideV"))
               + "</w:tblBorders>")
    xml = ('<w:tbl><w:tblPr><w:tblW w:w="5000" w:type="pct"/>%s'
           '<w:tblLayout w:type="autofit"/></w:tblPr>' % borders)
    for ri, row in enumerate(rows):
        trpr = '<w:trPr><w:tblHeader/></w:trPr>' if ri == 0 else ''
        xml += "<w:tr>%s" % trpr
        for cell in row:
            shd = ('<w:shd w:val="clear" w:color="auto" w:fill="EEEEEE"/>' if ri == 0 else '')
            bold = ri == 0
            xml += ('<w:tc><w:tcPr><w:tcW w:w="0" w:type="auto"/>%s</w:tcPr>'
                    '<w:p><w:pPr><w:spacing w:after="0"/></w:pPr>%s</w:p></w:tc>'
                    % (shd, runs(cell, bold=bold)))
        xml += "</w:tr>"
    return xml + "</w:tbl>"


def hr():
    return ('<w:p><w:pPr><w:pBdr><w:bottom w:val="single" w:sz="6" w:space="1" '
            'w:color="CCCCCC"/></w:pBdr></w:pPr></w:p>')


def convert(md, title=None):
    body = []
    if title:
        body.append(para(title, style="Heading1"))
    lines = md.split("\n")
    i = 0
    in_code = False
    code_buf = []
    while i < len(lines):
        ln = lines[i]
        if ln.strip().startswith("```"):
            if in_code:
                body.append(para("", style="Code", code_block="\n".join(code_buf)))
                code_buf, in_code = [], False
            else:
                in_code = True
            i += 1
            continue
        if in_code:
            code_buf.append(ln)
            i += 1
            continue

        s = ln.strip()
        # 表格
        if s.startswith("|") and i + 1 < len(lines) and re.match(r"^\|[\s:|-]+\|$", lines[i + 1].strip()):
            rows = []
            hdr = [c.strip() for c in s.strip("|").split("|")]
            rows.append(hdr)
            i += 2
            while i < len(lines) and lines[i].strip().startswith("|"):
                rows.append([c.strip() for c in lines[i].strip().strip("|").split("|")])
                i += 1
            body.append(table(rows))
            body.append(para(""))
            continue
        # 标题
        m = re.match(r"^(#{1,4})\s+(.*)$", s)
        if m:
            lvl = len(m.group(1))
            body.append(para(m.group(2), style="Heading%d" % lvl))
            i += 1
            continue
        # 分隔线
        if re.match(r"^-{3,}$", s) or re.match(r"^\*{3,}$", s):
            body.append(hr())
            i += 1
            continue
        # 引用
        if s.startswith(">"):
            buf = []
            while i < len(lines) and lines[i].strip().startswith(">"):
                buf.append(lines[i].strip().lstrip(">").strip())
                i += 1
            body.append(para(" ".join(buf), style="Quote"))
            continue
        # 列表
        m = re.match(r"^([-*]|\d+\.)\s+(.*)$", s)
        if m:
            marker = "•" if m.group(1) in ("-", "*") else m.group(1)
            body.append(para("%s %s" % (marker, m.group(2)), style="Bullet"))
            i += 1
            continue
        if s == "":
            i += 1
            continue
        body.append(para(s))
        i += 1
    if code_buf:
        body.append(para("", style="Code", code_block="\n".join(code_buf)))

    sect = ('<w:sectPr><w:pgSz w:w="11906" w:h="16838"/>'
            '<w:pgMar w:top="1134" w:right="1134" w:bottom="1134" w:left="1134" '
            'w:header="720" w:footer="720" w:gutter="0"/></w:sectPr>')
    return ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
            '<w:body>%s%s</w:body></w:document>' % ("".join(body), sect))


def main():
    if len(sys.argv) < 3:
        print(__doc__)
        sys.exit(1)
    src, dst = sys.argv[1], sys.argv[2]
    title = None
    if "--title" in sys.argv:
        title = sys.argv[sys.argv.index("--title") + 1]
    md = open(src, encoding="utf-8").read()
    with zipfile.ZipFile(dst, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("[Content_Types].xml", CT)
        z.writestr("_rels/.rels", RELS)
        z.writestr("word/_rels/document.xml.rels", DOC_RELS)
        z.writestr("word/styles.xml", _styles())
        z.writestr("word/document.xml", convert(md, title))
    print("已生成 %s（%.1f KB，源 %s）" % (dst, os.path.getsize(dst) / 1024.0, src))


if __name__ == "__main__":
    main()
