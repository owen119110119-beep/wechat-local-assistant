"""Create a compact Chinese, source-indexed summary and render every page for review."""
import argparse
import hashlib
import json
import os
from pathlib import Path
from xml.sax.saxutils import escape


def font_name():
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont
    roots = [Path(os.environ.get('WINDIR', 'C:/Windows')) / 'Fonts', Path('/usr/share/fonts/truetype')]
    for root in roots:
        for name in ['msyh.ttc', 'simsun.ttc', 'DroidSansFallbackFull.ttf']:
            try:
                path = root / name
                if path.is_file():
                    pdfmetrics.registerFont(TTFont('SummaryCJK', str(path), subfontIndex=0))
                    return 'SummaryCJK'
            except Exception:
                continue
    raise ValueError('IMAGE_PDF_CJK_FONT_MISSING')


def create_report(spec, output):
    from reportlab.lib import colors
    from reportlab.lib.enums import TA_LEFT
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import ParagraphStyle
    from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Image, PageBreak, Table, TableStyle
    from pypdf import PdfReader
    import pypdfium2 as pdfium
    from PIL import Image as PILImage, ImageDraw

    output = Path(output)
    output.mkdir(parents=True, exist_ok=True)
    font = font_name()
    title = str(spec['title']).strip()
    if not title or not spec.get('sections'):
        raise ValueError('IMAGE_REPORT_EMPTY')
    pdf = output / 'summary.pdf'
    width, height = A4
    styles = {
        'title': ParagraphStyle('Title', fontName=font, fontSize=21, leading=30, textColor=colors.HexColor('#152D43'), spaceAfter=18, wordWrap='CJK'),
        'heading': ParagraphStyle('Heading', fontName=font, fontSize=13, leading=21, textColor=colors.HexColor('#176B7A'), spaceBefore=14, spaceAfter=6, keepWithNext=True, wordWrap='CJK'),
        'body': ParagraphStyle('Body', fontName=font, fontSize=10.5, leading=18, spaceAfter=7, wordWrap='CJK', alignment=TA_LEFT),
        'source': ParagraphStyle('Source', fontName=font, fontSize=8, leading=12, textColor=colors.HexColor('#64748B'), spaceAfter=9, wordWrap='CJK'),
    }
    def paragraph(text, style='body'):
        return Paragraph(escape(str(text)).replace('\n', '<br/>'), styles[style])
    story = [paragraph(title, 'title')]
    if spec.get('overview'):
        story.extend([paragraph(spec['overview']), Spacer(1, 6)])
    images = spec.get('images', [])
    for section in spec['sections']:
        pages = section.get('sourcePages', [])
        if not pages or any(type(p) is not int or p < 1 or p > len(images) for p in pages):
            raise ValueError('IMAGE_REPORT_SOURCE_INVALID')
        if section.get('heading'):
            story.append(paragraph(section['heading'], 'heading'))
        text = section.get('body', '')
        if not str(text).strip():
            raise ValueError('IMAGE_REPORT_EMPTY_SECTION')
        # Paragraphs can split across pages; do not put entire sections in KeepTogether.
        for block in str(text).split('\n\n'):
            story.append(paragraph(block))
        for data in section.get('tables', []):
            headers, rows = data.get('headers', []), data.get('rows', [])
            if not headers or len(headers) > 8 or any(len(row) != len(headers) for row in rows):
                raise ValueError('IMAGE_REPORT_TABLE_INVALID')
            table = Table([[paragraph(cell) for cell in row] for row in [headers, *rows]], colWidths=[(width-96)/len(headers)]*len(headers), repeatRows=1, hAlign='LEFT')
            table.setStyle(TableStyle([
                ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#E6F3F2')),
                ('VALIGN', (0, 0), (-1, -1), 'TOP'),
                ('GRID', (0, 0), (-1, -1), 0.3, colors.HexColor('#DCE6EC')),
                ('LEFTPADDING', (0, 0), (-1, -1), 7), ('RIGHTPADDING', (0, 0), (-1, -1), 7),
                ('TOPPADDING', (0, 0), (-1, -1), 6), ('BOTTOMPADDING', (0, 0), (-1, -1), 3),
            ]))
            story.extend([table, Spacer(1, 7)])
        story.append(paragraph('来源图：' + '、'.join(str(p) for p in pages), 'source'))
    uncertainties = list(spec.get('uncertainties', []))
    for image in images:
        if not image.get('path'):
            uncertainties.append(f'第{image["page"]}张图未取得可读原图，相关内容未据此补写。')
    if uncertainties:
        story.append(paragraph('待核对', 'heading'))
        for text in dict.fromkeys(uncertainties):
            story.append(paragraph(text))
    if spec.get('includeOriginals'):
        for image in images:
            if not image.get('path'):
                continue
            path = Path(image['path'])
            with PILImage.open(path) as original:
                size = original.size
            ratio = min((width-100)/size[0], (height-150)/size[1])
            story.extend([PageBreak(), paragraph('来源图 ' + str(image['page']), 'heading'), Image(str(path), width=size[0]*ratio, height=size[1]*ratio)])
    def footer(canvas, doc):
        canvas.saveState()
        canvas.setStrokeColor(colors.HexColor('#DCE6EC'))
        canvas.line(48, 39, width-48, 39)
        canvas.setFont(font, 8)
        canvas.setFillColor(colors.HexColor('#64748B'))
        canvas.drawRightString(width-48, 25, str(doc.page))
        canvas.restoreState()
    doc = SimpleDocTemplate(str(pdf), pagesize=A4, leftMargin=48, rightMargin=48, topMargin=43, bottomMargin=54, title=title, author='')
    doc.build(story, onFirstPage=footer, onLaterPages=footer)
    reader = PdfReader(pdf)
    if not reader.pages or any(not (page.extract_text() or '').strip() for page in reader.pages):
        raise ValueError('IMAGE_PDF_EMPTY')
    if title not in (reader.pages[0].extract_text() or '').replace('\n', ''):
        raise ValueError('IMAGE_PDF_TEXT_INVALID')
    rendered = pdfium.PdfDocument(str(pdf))
    previews, thumbnails = [], []
    for index in range(len(rendered)):
        page = rendered[index]
        bitmap = page.render(scale=1.1)
        picture = bitmap.to_pil().convert('RGB')
        path = output / f'page-{index+1:03}.png'
        picture.save(path)
        picture.thumbnail((360, 510))
        thumbs = PILImage.new('RGB', (380, 550), '#E7EDF2')
        thumbs.paste(picture, ((380-picture.width)//2, 10))
        ImageDraw.Draw(thumbs).text((16, 527), str(index+1), fill='#153447')
        thumbnails.append(thumbs)
        bitmap.close()
        page.close()
        if len(thumbnails) == 8 or index == len(rendered)-1:
            columns = min(2, len(thumbnails))
            sheet = PILImage.new('RGB', (380*columns, 550*((len(thumbnails)+1)//2)), 'white')
            for n, thumb in enumerate(thumbnails):
                sheet.paste(thumb, ((n % columns)*380, (n//columns)*550))
            preview = output / f'review-{len(previews)+1}.jpg'
            sheet.save(preview, quality=90)
            previews.append(str(preview))
            thumbnails = []
    rendered.close()
    receipt = {'status': 'ready', 'path': str(pdf), 'pages': len(reader.pages), 'previews': previews, 'sha256': hashlib.sha256(pdf.read_bytes()).hexdigest()}
    (output/'receipt.json').write_text(json.dumps(receipt, ensure_ascii=False), encoding='utf-8')
    return receipt


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--spec', required=True)
    parser.add_argument('--output-dir', required=True)
    args = parser.parse_args()
    receipt = create_report(json.loads(Path(args.spec).read_text(encoding='utf-8-sig')), args.output_dir)
    print(json.dumps(receipt, ensure_ascii=False))


if __name__ == '__main__':
    main()
