"""Render the editable Review 2 Markdown draft to a styled PDF."""
import html
import re
from pathlib import Path
from reportlab.lib import colors
from reportlab.lib.enums import TA_LEFT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, PageBreak, Table, TableStyle, Image
from reportlab.graphics.shapes import Drawing, Rect, String, Line, Polygon

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / 'docs/review2/IntentOS_Review2_Draft.md'
OUTPUT = ROOT / 'output/pdf/IntentOS_Review2_Draft.pdf'
INK, GREEN, MUTED, PALE = [colors.HexColor(c) for c in ('#213b38', '#286e5b', '#637873', '#eef4f0')]
FONT = Path('C:/Windows/Fonts')
pdfmetrics.registerFont(TTFont('Segoe', str(FONT / 'segoeui.ttf')))
pdfmetrics.registerFont(TTFont('SegoeBold', str(FONT / 'segoeuib.ttf')))
pdfmetrics.registerFontFamily('Segoe', normal='Segoe', bold='SegoeBold', italic='Segoe', boldItalic='SegoeBold')
W = A4[0] - 88
styles = {
    'body': ParagraphStyle('Body', fontName='Segoe', fontSize=9.4, leading=14.1, textColor=INK, spaceAfter=8, alignment=TA_LEFT),
    'h1': ParagraphStyle('H1', fontName='SegoeBold', fontSize=22, leading=27, textColor=GREEN, spaceBefore=4, spaceAfter=18, keepWithNext=True),
    'h2': ParagraphStyle('H2', fontName='SegoeBold', fontSize=15, leading=20, textColor=INK, spaceBefore=12, spaceAfter=12, keepWithNext=True),
    'h3': ParagraphStyle('H3', fontName='SegoeBold', fontSize=11, leading=15, textColor=GREEN, spaceBefore=12, spaceAfter=7, keepWithNext=True),
    'cell': ParagraphStyle('Cell', fontName='Segoe', fontSize=8.7, leading=12.5, textColor=INK),
    'bullet': ParagraphStyle('Bullet', fontName='Segoe', fontSize=9.4, leading=14.1, leftIndent=12, firstLineIndent=-10, textColor=INK, spaceAfter=5),
    'title': ParagraphStyle('Title', fontName='SegoeBold', fontSize=48, leading=53, textColor=GREEN, spaceBefore=15, spaceAfter=15),
}


def markup(text):
    text = text.replace('\u2013', '-').replace('\u2014', '-').replace('\u2011', '-')
    text = html.escape(text)
    text = re.sub(r'\*\*(.*?)\*\*', r'<b>\1</b>', text)
    text = re.sub(r'`([^`]+)`', r'<font color="#286e5b">\1</font>', text)
    return text


def diagram(kind):
    d = Drawing(W, 344 if kind == 'layers' else 268 if kind == 'architecture' else 154)
    def box(x, y, w, h, title, subtitle=''):
        d.add(Rect(x, y, w, h, rx=7, ry=7, fillColor=PALE, strokeColor=colors.HexColor('#c9dbd1')))
        d.add(String(x+w/2, y+h/2+(4 if subtitle else -3), title, textAnchor='middle', fontName='SegoeBold', fontSize=9, fillColor=INK))
        if subtitle: d.add(String(x+w/2, y+h/2-10, subtitle, textAnchor='middle', fontName='Segoe', fontSize=7.7, fillColor=MUTED))
    def arrow(x1,y1,x2,y2):
        d.add(Line(x1,y1,x2,y2,strokeColor=GREEN,strokeWidth=1))
        if y1==y2:
            s=1 if x2>x1 else -1
            pts=[x2,y2,x2-5*s,y2+3,x2-5*s,y2-3]
        else:
            s=1 if y2>y1 else -1
            pts=[x2,y2,x2-3,y2-5*s,x2+3,y2-5*s]
        d.add(Polygon(pts,fillColor=GREEN,strokeColor=GREEN))
    if kind=='layers':
        box(113,306,280,32,'1. User','Goal, priority and deadline')
        box(113,258,280,32,'2. Intent Interface','Composer, status, approval and evidence')
        arrow(253,306,253,290)
        d.add(Rect(0,104,W,138,rx=7,ry=7,fillColor=PALE,strokeColor=GREEN))
        d.add(String(W/2,224,'3. Intent Kernel (userspace)',textAnchor='middle',fontName='SegoeBold',fontSize=11,fillColor=GREEN))
        components=[('Understanding','Planner + validator'),('Process manager','Permission manager'),('Scheduler','Resource and lock manager'),('Recovery manager','Service registry')]
        for row,pair in enumerate(components):
            for col,label in enumerate(pair):
                d.add(String(126+col*254,202-row*25,label,textAnchor='middle',fontName='Segoe',fontSize=9,fillColor=INK))
        arrow(253,258,253,242)
        box(0,48,W,40,'4. Services through the registry','Calendar / Maps / Messaging / Files + RAG + OCR / Network APIs')
        arrow(253,104,253,88)
        box(0,0,W,32,'5. Host OS (unchanged)','Windows processes, files, memory and networking')
        arrow(253,48,253,32)
    elif kind=='architecture':
        box(113,220,280,40,'React workbench','Goal + uploads + scopes + output preferences')
        box(113,160,280,40,'Loopback API and event stream','Session token / origin checks / live snapshots')
        arrow(253,220,253,200)
        box(0,80,238,52,'Durable userspace runtime','Scheduler / permissions / completion checks')
        box(270,80,237,52,'Structured next-action planner','Gemini or local Ollama')
        arrow(160,160,120,132);arrow(238,110,270,110);arrow(270,96,238,96)
        box(0,0,238,52,'Local persistence and retrieval','SQLite checkpoints + FTS5 + local vectors')
        box(270,0,237,52,'Validated capabilities','Files / OCR / document export / Google APIs')
        arrow(120,80,120,52);arrow(190,80,385,52)
    else:
        boxes=[(0,'1. Admit','Goal, inputs, grants'),(174,'2. Schedule','Dependencies + slots'),(348,'3. Decide','Read / retrieve / act')]
        for x,t,s in boxes:box(x,96,159,48,t,s)
        arrow(159,120,174,120);arrow(333,120,348,120)
        box(348,12,159,48,'4. Validate + execute','Schema / scope / output checks')
        box(174,12,159,48,'5. Commit checkpoint','Result + audit + provenance')
        box(0,12,159,48,'6. Complete or continue','Answer / saved output / recovery')
        arrow(427,96,427,60);arrow(348,36,333,36);arrow(174,36,159,36)
    return d


def footer(canvas, doc):
    canvas.saveState()
    canvas.setStrokeColor(colors.HexColor('#d8e4dd'));canvas.line(44, A4[1]-30, A4[0]-44, A4[1]-30)
    canvas.setFont('Segoe',7.5);canvas.setFillColor(MUTED)
    canvas.drawString(44,A4[1]-22,'INTENTOS  /  REVIEW 2  /  IMPLEMENTATION DRAFT')
    canvas.drawString(44,25,'16 OCTOBER 2026  |  Measured prototype evidence')
    canvas.drawRightString(A4[0]-44,25,str(doc.page))
    canvas.restoreState()


def build():
    lines=SOURCE.read_text(encoding='utf-8').splitlines();story=[];i=0
    while i<len(lines):
        line=lines[i].strip()
        if not line:i+=1;continue
        if line=='<!-- page -->':story.append(PageBreak())
        elif line.startswith(':::'):story.extend([diagram(line[3:]),Spacer(1,10)])
        elif line.startswith('!['):
            match=re.match(r'!\[(.*?)\]\((.*?)\)',line)
            image=Image(str(SOURCE.parent/match[2]));ratio=image.imageHeight/image.imageWidth
            image.drawHeight=min(W*ratio,470);image.drawWidth=image.drawHeight/ratio
            story.extend([image,Spacer(1,12)])
        elif line.startswith('|'):
            rows=[]
            while i<len(lines) and lines[i].startswith('|'):
                cells=[x.strip() for x in lines[i].strip('|').split('|')]
                if not all(re.fullmatch(r'[-: ]+',x) for x in cells):rows.append(cells)
                i+=1
            i-=1
            count=len(rows[0]);widths=[W*.35,W*.65] if count==2 else [W*.42,W*.25,W*.33]
            data=[[Paragraph(markup(('**'+v+'**') if r==0 else v),styles['cell']) for v in row] for r,row in enumerate(rows)]
            table=Table(data,colWidths=widths,repeatRows=1,hAlign='LEFT')
            table.setStyle(TableStyle([('BACKGROUND',(0,0),(-1,0),PALE),('VALIGN',(0,0),(-1,-1),'TOP'),('LINEBELOW',(0,0),(-1,0),.6,GREEN),('LINEBELOW',(0,1),(-1,-1),.35,colors.HexColor('#dde6e0')),('LEFTPADDING',(0,0),(-1,-1),9),('RIGHTPADDING',(0,0),(-1,-1),9),('TOPPADDING',(0,0),(-1,-1),8),('BOTTOMPADDING',(0,0),(-1,-1),8)]))
            story.extend([table,Spacer(1,13)])
        elif line.startswith('#'):
            depth=len(line)-len(line.lstrip('#'));value=line[depth:].strip()
            style='title' if value=='IntentOS' else 'h'+str(min(depth,3))
            story.append(Paragraph(markup(value),styles[style]))
        elif line.startswith('- '):story.append(Paragraph('- '+markup(line[2:]),styles['bullet']))
        else:story.append(Paragraph(markup(line),styles['body']))
        i+=1
    OUTPUT.parent.mkdir(parents=True,exist_ok=True)
    doc=SimpleDocTemplate(str(OUTPUT),pagesize=A4,rightMargin=44,leftMargin=44,topMargin=49,bottomMargin=45,title='IntentOS - Review 2',author='IntentOS project',pageCompression=1)
    doc.build(story,onFirstPage=footer,onLaterPages=footer)
    print(OUTPUT)


if __name__=='__main__':
    import argparse
    parser=argparse.ArgumentParser()
    parser.add_argument('--source',type=Path,default=SOURCE)
    parser.add_argument('--output',type=Path,default=OUTPUT)
    args=parser.parse_args()
    SOURCE,OUTPUT=args.source.resolve(),args.output.resolve()
    build()
