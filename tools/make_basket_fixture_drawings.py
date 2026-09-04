from pathlib import Path

from reportlab.graphics import renderPDF
from reportlab.graphics.shapes import Circle, Drawing, Group, Line, Polygon, Rect, String
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import Flowable, Image, PageBreak, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle


ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "output" / "pdf" / "basket_fixture_2020_drawings_v4.pdf"
BASEPLATE_PNG = ROOT / "tmp" / "pdfs" / "basket_baseplate-1.png"
REFERENCE_IMAGE = Path(r"C:\Users\MSI\.codex\generated_images\019f4b1c-92aa-7951-beb8-255b8b86b670\call_52GUPwdvRhO0SNtnwbZWFYoc.png")


pdfmetrics.registerFont(TTFont("SimHei", r"C:\Windows\Fonts\simhei.ttf"))
pdfmetrics.registerFont(TTFont("SimHei-Bold", r"C:\Windows\Fonts\simhei.ttf"))


BLUE = colors.HexColor("#1f5fbf")
LIGHT_BLUE = colors.HexColor("#eaf2ff")
METAL = colors.HexColor("#cfd3d6")
METAL_DARK = colors.HexColor("#9aa0a6")
BLACK = colors.HexColor("#222222")
YELLOW = colors.HexColor("#f1c232")
RUBBER = colors.HexColor("#333333")
ORANGE = colors.HexColor("#f28c28")
GREEN = colors.HexColor("#2e8b57")


class DrawingFlowable(Flowable):
    def __init__(self, drawing):
        super().__init__()
        self.drawing = drawing
        self.width = drawing.width
        self.height = drawing.height

    def draw(self):
        renderPDF.draw(self.drawing, self.canv, 0, 0)


def text(d, x, y, value, size=8, color=colors.black, anchor="start"):
    d.add(String(x, y, value, fontName="SimHei", fontSize=size, fillColor=color, textAnchor=anchor))


def callout(d, x1, y1, x2, y2, number):
    d.add(Line(x1, y1, x2, y2, strokeColor=BLUE, strokeWidth=1.2))
    d.add(Circle(x1, y1, 7, fillColor=BLUE, strokeColor=BLUE))
    text(d, x1, y1 - 3, str(number), 7, colors.white, "middle")


def cuboid(d, x, y, w, h, dx=10, dy=8, fill=METAL, stroke=colors.black):
    top = Polygon([x, y + h, x + dx, y + h + dy, x + w + dx, y + h + dy, x + w, y + h],
                  fillColor=colors.Color(fill.red, fill.green, fill.blue, alpha=0.85), strokeColor=stroke)
    side = Polygon([x + w, y, x + w + dx, y + dy, x + w + dx, y + h + dy, x + w, y + h],
                   fillColor=colors.Color(0.55, 0.58, 0.60, alpha=0.9), strokeColor=stroke)
    front = Rect(x, y, w, h, fillColor=fill, strokeColor=stroke)
    d.add(top)
    d.add(side)
    d.add(front)


def extrusion_2020(d, x, y, length, horizontal=True, label=None):
    if horizontal:
        cuboid(d, x, y, length, 22, 12, 8, METAL)
        d.add(Line(x + 8, y + 7, x + length - 4, y + 7, strokeColor=METAL_DARK, strokeWidth=2))
        d.add(Line(x + 8, y + 15, x + length - 4, y + 15, strokeColor=METAL_DARK, strokeWidth=2))
        if label:
            text(d, x + length / 2, y - 14, label, 8, BLUE, "middle")
    else:
        cuboid(d, x, y, 22, length, 12, 8, METAL)
        d.add(Line(x + 7, y + 8, x + 7, y + length - 4, strokeColor=METAL_DARK, strokeWidth=2))
        d.add(Line(x + 15, y + 8, x + 15, y + length - 4, strokeColor=METAL_DARK, strokeWidth=2))
        if label:
            text(d, x - 38, y + length / 2, label, 8, BLUE)


def knob(d, x, y):
    d.add(Circle(x, y, 8, fillColor=BLACK, strokeColor=colors.black))
    d.add(Line(x, y - 8, x, y - 26, strokeColor=BLACK, strokeWidth=3))


def slot_hole(d, x, y, w, h, fill=colors.white):
    d.add(Rect(x + h / 2, y, w - h, h, fillColor=fill, strokeColor=colors.black, strokeWidth=1))
    d.add(Circle(x + h / 2, y + h / 2, h / 2, fillColor=fill, strokeColor=colors.black, strokeWidth=1))
    d.add(Circle(x + w - h / 2, y + h / 2, h / 2, fillColor=fill, strokeColor=colors.black, strokeWidth=1))


def slot_vhole(d, x, y, w, h, fill=colors.white):
    d.add(Rect(x, y + w / 2, w, h - w, fillColor=fill, strokeColor=colors.black, strokeWidth=1))
    d.add(Circle(x + w / 2, y + w / 2, w / 2, fillColor=fill, strokeColor=colors.black, strokeWidth=1))
    d.add(Circle(x + w / 2, y + h - w / 2, w / 2, fillColor=fill, strokeColor=colors.black, strokeWidth=1))


def dimension_h(d, x1, x2, y, label):
    d.add(Line(x1, y, x2, y, strokeColor=colors.HexColor("#555555"), strokeWidth=0.8))
    d.add(Line(x1, y - 4, x1, y + 4, strokeColor=colors.HexColor("#555555"), strokeWidth=0.8))
    d.add(Line(x2, y - 4, x2, y + 4, strokeColor=colors.HexColor("#555555"), strokeWidth=0.8))
    text(d, (x1 + x2) / 2, y + 5, label, 7.2, colors.HexColor("#333333"), "middle")


def extrusion_end(d, x, y, s=44):
    d.add(Rect(x, y, s, s, fillColor=METAL, strokeColor=colors.black, strokeWidth=1.2))
    slot_hole(d, x + 7, y + s - 14, s - 14, 7, fill=colors.HexColor("#f5f5f5"))
    slot_hole(d, x + 7, y + 7, s - 14, 7, fill=colors.HexColor("#f5f5f5"))
    slot_vhole(d, x + 3, y + 16, 7, s - 32, fill=colors.HexColor("#f5f5f5"))
    slot_vhole(d, x + s - 10, y + 16, 7, s - 32, fill=colors.HexColor("#f5f5f5"))
    d.add(Circle(x + s / 2, y + s / 2, 5, fillColor=colors.white, strokeColor=colors.black))


def t_nut(d, x, y, scale=1.0):
    w, h = 32 * scale, 16 * scale
    d.add(Rect(x, y, w, h, fillColor=METAL_DARK, strokeColor=colors.black))
    d.add(Circle(x + w / 2, y + h / 2, 4 * scale, fillColor=colors.white, strokeColor=colors.black))
    d.add(Line(x + 5 * scale, y + h, x + 10 * scale, y + h + 5 * scale, strokeColor=colors.black))
    d.add(Line(x + w - 5 * scale, y + h, x + w - 10 * scale, y + h + 5 * scale, strokeColor=colors.black))


def title(story, value, subtitle=None):
    story.append(Paragraph(value, ParagraphStyle("TitleCN", fontName="SimHei-Bold", fontSize=17, leading=22)))
    if subtitle:
        story.append(Paragraph(subtitle, ParagraphStyle("SubCN", fontName="SimHei", fontSize=9, leading=13, textColor=colors.HexColor("#555555"))))
    story.append(Spacer(1, 5 * mm))


def styles():
    ss = getSampleStyleSheet()
    ss.add(ParagraphStyle("CN", fontName="SimHei", fontSize=9, leading=13))
    ss.add(ParagraphStyle("CNsmall", fontName="SimHei", fontSize=8, leading=11))
    ss.add(ParagraphStyle("CNtiny", fontName="SimHei", fontSize=6.6, leading=8.8))
    ss.add(ParagraphStyle("H", fontName="SimHei-Bold", fontSize=11, leading=15, textColor=BLUE))
    return ss


def assembly_3d():
    d = Drawing(255 * mm, 132 * mm)
    # Platform
    cuboid(d, 45, 34, 360, 250, 18, 12, colors.HexColor("#303030"))
    for i in range(11):
        for j in range(7):
            d.add(Circle(82 + i * 28, 68 + j * 28, 2.4, fillColor=colors.HexColor("#777777"), strokeColor=None))
    text(d, 225, 18, "载物平台约 230 × 305 mm；图中只示意连接关系，实际孔位按底板尺寸页复核", 8, colors.black, "middle")

    # Rails
    extrusion_2020(d, 85, 65, 205, horizontal=False)
    extrusion_2020(d, 325, 65, 205, horizontal=False)

    # Rail end bases
    for x in [74, 314]:
        for y in [52, 275]:
            cuboid(d, x, y, 44, 18, 6, 4, colors.HexColor("#e8e8e8"))
            d.add(Circle(x + 13, y + 9, 3, fillColor=BLACK))
            d.add(Circle(x + 31, y + 9, 3, fillColor=BLACK))

    # Transverse rods and main sliders
    for y in [112, 215]:
        extrusion_2020(d, 103, y, 240, horizontal=True)
        for x in [83, 323]:
            cuboid(d, x, y - 6, 42, 35, 8, 6, colors.HexColor("#eeeeee"))
            knob(d, x + 21, y + 48)

    # Rubber blocks and basket outline
    for y in [112, 215]:
        for x in [158, 280]:
            cuboid(d, x, y + 24, 28, 18, 5, 4, YELLOW)
            knob(d, x + 14, y + 58)
    d.add(Rect(150, 135, 155, 76, fillColor=colors.Color(0.75, 0.88, 1, alpha=0.15), strokeColor=BLUE, strokeWidth=1.5))

    # Arrows
    d.add(Line(57, 142, 57, 238, strokeColor=colors.red, strokeWidth=2))
    d.add(Line(51, 232, 57, 242, strokeColor=colors.red, strokeWidth=2))
    d.add(Line(63, 232, 57, 242, strokeColor=colors.red, strokeWidth=2))
    d.add(Line(51, 148, 57, 138, strokeColor=colors.red, strokeWidth=2))
    d.add(Line(63, 148, 57, 138, strokeColor=colors.red, strokeWidth=2))

    d.add(Line(164, 254, 293, 254, strokeColor=BLUE, strokeWidth=2))
    d.add(Line(286, 248, 296, 254, strokeColor=BLUE, strokeWidth=2))
    d.add(Line(286, 260, 296, 254, strokeColor=BLUE, strokeWidth=2))
    d.add(Line(171, 248, 161, 254, strokeColor=BLUE, strokeWidth=2))
    d.add(Line(171, 260, 161, 254, strokeColor=BLUE, strokeWidth=2))

    text(d, 495, 256, "红色箭头：调长度", 8.5, colors.red)
    text(d, 495, 238, "蓝色箭头：调宽度", 8.5, BLUE)
    text(d, 495, 220, "蓝框：篮筐底部外轮廓", 8.5, BLUE)
    text(d, 495, 202, "篮筐另购，重量由平台承受", 8.5, colors.black)

    # Callouts numbers only in figure
    callout(d, 85, 285, 98, 260, 1)
    callout(d, 133, 294, 111, 233, 2)
    callout(d, 374, 233, 343, 225, 3)
    callout(d, 392, 268, 337, 260, 4)
    callout(d, 418, 120, 301, 146, 5)
    callout(d, 420, 82, 325, 76, 6)
    return d


def part_gallery():
    d = Drawing(255 * mm, 145 * mm)
    items = [
        ("A1/A2 固定纵向导轨", "2020欧标铝型材，250 mm ×2", 40, 305, "rail_long"),
        ("B1/B2 横向限位杆", "2020欧标铝型材，200 mm ×2", 395, 305, "rail_short"),
        ("C 导轨安装座", "2020角码/底座，底部选长圆孔", 40, 190, "base"),
        ("D 主滑块连接组", "角码 + T型螺母 + 手拧旋钮，4套", 260, 190, "slider"),
        ("G 橡胶块固定片", "2-3 mm铝片/不锈钢片，M5长圆孔", 500, 190, "plate"),
        ("H 橡胶接触块", "约30×15×8 mm，4-8个", 40, 80, "rubber"),
        ("E/F T型螺母与旋钮", "2020欧标M5 T型螺母 + M5×12/16旋钮", 260, 80, "nutknob"),
        ("I 端盖/限位挡块", "2020端盖8个，限位挡块4个", 500, 80, "stop"),
    ]
    for name, spec, x, y, kind in items:
        d.add(Rect(x - 12, y - 36, 185, 104, fillColor=colors.HexColor("#fafafa"), strokeColor=colors.HexColor("#cccccc")))
        text(d, x, y - 8, name, 8, BLUE)
        text(d, x, y - 24, spec, 6.7, colors.black)
        draw_y = y + 20 if kind in ("rail_long", "rail_short") else y
        if kind == "rail_long":
            extrusion_2020(d, x, draw_y, 135, True)
        elif kind == "rail_short":
            extrusion_2020(d, x, draw_y, 100, True)
        elif kind == "base":
            cuboid(d, x + 12, draw_y, 58, 12, 6, 5, METAL)
            cuboid(d, x + 35, draw_y + 12, 16, 45, 5, 5, METAL)
            d.add(Rect(x + 20, draw_y + 4, 34, 4, fillColor=colors.white, strokeColor=colors.black))
        elif kind == "slider":
            cuboid(d, x + 25, draw_y, 58, 35, 8, 6, colors.HexColor("#eeeeee"))
            knob(d, x + 54, draw_y + 56)
        elif kind == "plate":
            cuboid(d, x + 25, draw_y, 45, 55, 5, 5, colors.HexColor("#eeeeee"))
            d.add(Rect(x + 42, draw_y + 14, 9, 28, fillColor=colors.white, strokeColor=colors.black))
        elif kind == "rubber":
            cuboid(d, x + 38, draw_y + 10, 35, 45, 5, 5, YELLOW)
            cuboid(d, x + 72, draw_y + 10, 9, 45, 3, 3, RUBBER)
        elif kind == "nutknob":
            d.add(Rect(x + 25, draw_y + 12, 32, 18, fillColor=METAL, strokeColor=colors.black))
            knob(d, x + 96, draw_y + 48)
        elif kind == "stop":
            cuboid(d, x + 25, draw_y + 10, 40, 22, 5, 4, BLACK)
            d.add(Circle(x + 45, draw_y + 21, 4, fillColor=colors.white, strokeColor=colors.black))
    return d


def detailed_part_gallery():
    d = Drawing(255 * mm, 150 * mm)

    # 2020 extrusion with length and cross-section
    text(d, 35, 384, "A/B  2020欧标铝型材：定尺切割", 10.5, BLUE)
    extrusion_2020(d, 42, 330, 245, True)
    dimension_h(d, 42, 287, 316, "A1/A2: 250 mm；B1/B2: 200 mm")
    extrusion_end(d, 324, 326, 44)
    text(d, 316, 312, "端面约20 × 20 mm；四面槽；槽内配M5 T型螺母", 7.2)
    text(d, 42, 302, "材料：铝合金，2020欧标；表面普通氧化即可；切口去毛刺，配端盖。", 7.6)

    # Rail mounting base
    text(d, 35, 270, "C  导轨安装座/角码：连接导轨和小车底板", 10.5, BLUE)
    cuboid(d, 56, 168, 92, 18, 8, 6, METAL)
    cuboid(d, 92, 186, 24, 66, 7, 6, METAL)
    slot_hole(d, 74, 174, 52, 8)
    slot_vhole(d, 99, 207, 10, 30)
    text(d, 190, 237, "下单描述：2020型材角码/底座，底部带长圆孔，数量8个。", 8)
    text(d, 190, 213, "底板侧用 M3；型材侧接 M5 T型螺母。", 8)
    text(d, 190, 189, "注意：底座固定不动；孔位不准时用长圆孔或转接片。", 8)

    # T nut and knob
    text(d, 35, 155, "E/F  滑动锁紧件：M5 T型螺母 + M5手拧旋钮", 10.5, BLUE)
    cuboid(d, 60, 70, 145, 22, 10, 7, METAL)
    d.add(Line(72, 85, 192, 85, strokeColor=METAL_DARK, strokeWidth=3))
    t_nut(d, 105, 87, 1.0)
    knob(d, 121, 142)
    d.add(Line(121, 118, 121, 100, strokeColor=BLACK, strokeWidth=2.2))
    text(d, 240, 132, "T型螺母放在2020型材槽里；旋钮的M5螺杆穿过连接片后拧进T型螺母。", 8)
    text(d, 240, 108, "拧松可以滑动调位置，拧紧后固定。旋钮建议 M5×12 或 M5×16。", 8)

    # End cap and stopper
    text(d, 500, 155, "I  端盖/限位挡块", 10.5, BLUE)
    cuboid(d, 520, 105, 42, 24, 5, 4, BLACK)
    d.add(Circle(541, 117, 5, fillColor=colors.white, strokeColor=colors.black))
    cuboid(d, 585, 102, 28, 30, 4, 4, colors.HexColor("#444444"))
    text(d, 500, 78, "端盖防刮手；限位挡块锁在导轨端部，防止滑块脱出。", 8)
    text(d, 500, 56, "数量：2020端盖8个，限位挡块4个。", 8)
    return d


def adjustable_parts_gallery():
    d = Drawing(255 * mm, 150 * mm)

    # Main slider group
    text(d, 45, 382, "D  主滑块连接组：让横向限位杆沿纵向导轨前后调", 11, BLUE)
    extrusion_2020(d, 80, 205, 155, False)
    extrusion_2020(d, 118, 280, 310, True)
    cuboid(d, 86, 268, 68, 52, 8, 6, colors.HexColor("#eeeeee"))
    knob(d, 120, 342)
    d.add(Line(120, 317, 120, 293, strokeColor=BLACK, strokeWidth=2.2))
    d.add(Line(60, 223, 60, 307, strokeColor=colors.red, strokeWidth=2))
    d.add(Line(54, 301, 60, 311, strokeColor=colors.red, strokeWidth=2))
    d.add(Line(66, 301, 60, 311, strokeColor=colors.red, strokeWidth=2))
    d.add(Line(54, 229, 60, 219, strokeColor=colors.red, strokeWidth=2))
    d.add(Line(66, 229, 60, 219, strokeColor=colors.red, strokeWidth=2))
    text(d, 460, 324, "每根横向限位杆的左右两端各一套主滑块连接组。", 8.2)
    text(d, 460, 300, "每套建议包含：2020连接片/角码1个、M5 T型螺母2个、M5旋钮1个。", 8.2)
    text(d, 460, 276, "拧松左右两端旋钮，整根横杆前后移动；位置合适后同时拧紧。", 8.2, colors.red)

    # Rubber block and fixing plate
    text(d, 45, 178, "G/H  橡胶块固定片 + 橡胶接触块", 11, BLUE)
    text(d, 45, 158, "作用：让篮筐左右方向可调，并防滑防刮。", 8.2, colors.HexColor("#333333"))
    extrusion_2020(d, 80, 58, 300, True)
    cuboid(d, 194, 91, 60, 82, 7, 7, colors.HexColor("#eeeeee"))
    slot_vhole(d, 218, 113, 12, 38)
    knob(d, 224, 196)
    d.add(Line(224, 171, 224, 142, strokeColor=BLACK, strokeWidth=2.1))
    cuboid(d, 267, 111, 36, 50, 5, 5, YELLOW)
    cuboid(d, 302, 111, 9, 50, 3, 3, RUBBER)
    d.add(Rect(338, 98, 40, 86, fillColor=colors.Color(0.75, 0.88, 1, alpha=0.15), strokeColor=BLUE))
    callout(d, 92, 85, 130, 72, 1)
    callout(d, 204, 172, 211, 155, 2)
    callout(d, 224, 210, 224, 194, 3)
    callout(d, 286, 175, 291, 156, 4)
    callout(d, 388, 149, 362, 141, 5)
    text(d, 460, 152, "1 横向限位杆；2 固定片；3 M5锁紧旋钮；4 橡胶接触块；5 篮筐外壁。", 8.2)
    text(d, 460, 128, "固定片贴在横杆侧面，T型螺母在型材槽内。拧松后可左右滑动。", 8.2)
    text(d, 460, 104, "橡胶块装在固定片内侧，只顶住篮筐外壁，不给篮筐打孔。", 8.2)
    return d


def main_slider_detail():
    d = Drawing(255 * mm, 134 * mm)
    text(d, 45, 330, "主滑块连接组的实际连接顺序", 12, BLUE)
    extrusion_2020(d, 88, 85, 225, False)
    extrusion_2020(d, 130, 205, 315, True)
    cuboid(d, 92, 190, 74, 58, 8, 6, colors.HexColor("#eeeeee"))
    cuboid(d, 142, 214, 42, 28, 6, 5, colors.HexColor("#dddddd"))
    t_nut(d, 100, 179, 0.85)
    t_nut(d, 165, 245, 0.85)
    knob(d, 129, 284)
    d.add(Line(129, 260, 129, 223, strokeColor=BLACK, strokeWidth=2.4))

    callout(d, 72, 270, 104, 242, 1)
    callout(d, 460, 236, 401, 223, 2)
    callout(d, 189, 285, 136, 262, 3)
    callout(d, 72, 174, 104, 189, 4)
    callout(d, 230, 266, 170, 247, 5)

    text(d, 500, 290, "1  纵向导轨 A：固定在底板上，不移动", 8.0)
    text(d, 500, 266, "2  横向限位杆 B：左右横跨，两端被主滑块夹住", 8.0)
    text(d, 500, 242, "3  手拧旋钮：穿过连接片，拧入T型螺母", 8.0)
    text(d, 500, 218, "4  T型螺母：在纵向导轨槽内滑动", 8.0)
    text(d, 500, 194, "5  横杆侧T型螺母：把横杆和连接片锁在一起", 8.0)
    text(d, 500, 154, "工作方式：左右两端同时拧松，横杆前后移动。", 8.0, colors.red)
    text(d, 500, 132, "位置合适后同时拧紧。", 8.0, colors.red)
    text(d, 500, 108, "横杆两端均有主滑块支撑，不是悬空件。", 8.0, colors.red)
    return d


def joint_detail():
    d = Drawing(255 * mm, 135 * mm)
    # Left detail: rubber block on transverse extrusion
    extrusion_2020(d, 50, 190, 300, True)
    d.add(Rect(176, 219, 30, 14, fillColor=METAL, strokeColor=colors.black))
    cuboid(d, 150, 235, 70, 75, 6, 6, colors.HexColor("#eeeeee"))
    d.add(Rect(177, 250, 10, 35, fillColor=colors.white, strokeColor=colors.black))
    knob(d, 184, 333)
    d.add(Line(184, 325, 184, 233, strokeColor=BLACK, strokeWidth=2))
    cuboid(d, 225, 252, 24, 52, 4, 4, YELLOW)
    cuboid(d, 248, 252, 8, 52, 3, 3, RUBBER)
    d.add(Rect(280, 236, 28, 92, fillColor=colors.Color(0.75, 0.88, 1, alpha=0.15), strokeColor=BLUE))

    text(d, 50, 350, "横向限位杆上的橡胶块连接", 12, BLUE)
    callout(d, 62, 218, 95, 205, 1)
    callout(d, 162, 278, 152, 268, 2)
    callout(d, 184, 333, 184, 325, 3)
    callout(d, 230, 317, 236, 301, 4)
    callout(d, 310, 295, 292, 282, 5)
    text(d, 380, 306, "1  2020横向限位杆：作为可左右调节的基础", 8)
    text(d, 380, 286, "2  橡胶块固定片：带M5长圆孔，贴靠在型材侧面", 8)
    text(d, 380, 266, "3  锁紧旋钮：M5螺杆穿过固定片", 8)
    text(d, 380, 246, "4  橡胶接触块：固定在固定片内侧，接触篮筐", 8)
    text(d, 380, 226, "5  篮筐外壁：只被顶住，不打孔、不承重", 8)

    # Bottom detail: loose/locked principle
    d.add(Rect(52, 52, 300, 50, fillColor=METAL, strokeColor=colors.black))
    d.add(Line(65, 75, 340, 75, strokeColor=METAL_DARK, strokeWidth=2))
    d.add(Rect(170, 83, 30, 12, fillColor=METAL_DARK, strokeColor=colors.black))
    d.add(Rect(145, 103, 80, 18, fillColor=colors.HexColor("#eeeeee"), strokeColor=colors.black))
    d.add(Line(185, 121, 185, 95, strokeColor=BLACK, strokeWidth=2))
    knob(d, 185, 142)
    text(d, 58, 32, "拧松：T型螺母在型材槽内滑动；拧紧：旋钮把固定片压紧，T型螺母卡住槽。", 9, colors.black)
    return d


def build_pdf():
    OUT.parent.mkdir(parents=True, exist_ok=True)
    doc = SimpleDocTemplate(
        str(OUT),
        pagesize=landscape(A4),
        rightMargin=12 * mm,
        leftMargin=12 * mm,
        topMargin=10 * mm,
        bottomMargin=10 * mm,
    )
    ss = styles()
    story = []

    title(story, "可调购物篮固定组件 - 2020铝型材加工图纸包（新版）", "用途：发给淘宝/京东 2020 铝型材定制商家，用于切割型材并配齐标准件。")
    overview = [
        ["设计边界", "本组件不包含篮筐和车架；篮筐直接放在载物平台上，限位组件只防滑、防晃、定位。"],
        ["推荐结构", "两根固定纵向导轨 + 两根可前后调节的横向限位杆 + 四到八个可左右调节的橡胶接触块。"],
        ["默认尺寸", "按底板约 230 × 305 mm 设计：纵向导轨 250 mm ×2；横向限位杆 200 mm ×2。"],
        ["已确认口径", "底板连接螺丝按 M3；导轨安装座底部要求长圆孔；横向限位杆确定为 200 mm。"],
    ]
    story.append(make_table(overview, [32 * mm, 210 * mm], header=False))
    story.append(PageBreak())

    title(story, "0. 目标效果参考图", "这张图作为和商家沟通的直观参考；后续表格给出本次下单的确定尺寸和数量。")
    if REFERENCE_IMAGE.exists():
        story.append(Image(str(REFERENCE_IMAGE), width=230 * mm, height=129 * mm))
    else:
        story.append(Paragraph("未找到目标效果参考图，请确认图片路径。", ss["CN"]))
    story.append(PageBreak())

    title(story, "1. 三维总装关系", "数字标注放在图外说明，避免图文重叠。")
    story.append(DrawingFlowable(assembly_3d()))
    story.append(PageBreak())

    title(story, "1.1 总装编号解释", "这一页对应上一页的数字标注。")
    legend = [
        ["编号", "部件", "作用/注意事项"],
        ["1", "固定纵向导轨 A1/A2", "2020欧标型材，左右各一根，必须固定到载物平台。"],
        ["2", "前/后横向限位杆 B1/B2", "两端连接主滑块，整体沿纵向导轨前后移动，用于长度调节。"],
        ["3", "主滑块连接组", "角码/T型螺母/旋钮组合，调好前后位置后锁紧。"],
        ["4", "锁紧旋钮", "M5手拧螺丝，拧紧后把连接件压在型材槽上。"],
        ["5", "橡胶接触块", "装在固定片内侧，顶住篮筐外壁，防滑防刮。"],
        ["6", "导轨安装座", "底部要求长圆孔，用M3螺丝接到底板现有孔位。"],
    ]
    story.append(make_table(legend, [18 * mm, 45 * mm, 178 * mm], header=True))
    story.append(PageBreak())

    title(story, "2. 小车底板尺寸参考", "商家需要理解安装对象是一块多孔底板；导轨安装座底部要求长圆孔，用 M3 螺丝连接。")
    if BASEPLATE_PNG.exists():
        img = Image(str(BASEPLATE_PNG), width=185 * mm, height=131 * mm)
        note = Paragraph(
            "底板参考尺寸约 230 mm × 305 mm。建议把两根 250 mm 纵向导轨放在底板左右两侧偏内位置，导轨中心距暂按约 160 mm。导轨安装座底部使用长圆孔，通过 M3 螺丝连接底板。实际安装时以不挡轮子、手机支架、传感器和线束为准。",
            ss["CN"],
        )
        story.append(Table([[img, note]], colWidths=[190 * mm, 55 * mm], style=[("VALIGN", (0, 0), (-1, -1), "TOP")]))
    else:
        story.append(Paragraph("未找到底板尺寸渲染图，请先把底板尺寸PDF渲染为 tmp/pdfs/basket_baseplate-1.png。", ss["CN"]))
    story.append(PageBreak())

    title(story, "3. 固定类零件识别图", "这一页把 2020 型材、导轨安装座、T型螺母、旋钮和端盖画清楚，方便商家判断配件系列。")
    story.append(DrawingFlowable(detailed_part_gallery()))
    story.append(PageBreak())

    title(story, "4. 可调类零件识别图", "这一页重点说明主滑块连接组和橡胶接触组件，避免商家误以为横杆或夹块是悬空件。")
    story.append(DrawingFlowable(adjustable_parts_gallery()))
    story.append(PageBreak())

    title(story, "5. 主滑块连接细节", "横向限位杆不是悬空的；它的左右两端分别通过主滑块连接到两根固定纵向导轨。")
    story.append(DrawingFlowable(main_slider_detail()))
    story.append(PageBreak())

    title(story, "6. 下单确认表 A：需要商家定尺/加工的部分", "先让商家确认这些尺寸，尤其是 2020 型材切割长度和橡胶块固定片。")
    bom加工 = [
        ["编号", "要买/加工的件", "材料与规格", "尺寸确认", "数量", "给商家的确认话术"],
        ["A1-A2", "固定纵向导轨；搜索：2020欧标铝型材 定制切割", "铝合金 2020 欧标槽型材，四面槽，适配 M5 T型螺母", "长度 250 mm ×2；端面切平去毛刺；配 2020 端盖", "2 根", "这是固定在小车底板上的左右导轨，不需要打孔，槽内要能装 M5 T型螺母。"],
        ["B1-B2", "前/后横向限位杆；搜索：2020欧标铝型材 200mm", "同上，2020 欧标槽型材", "长度固定 200 mm ×2；端面切平去毛刺；配 2020 端盖", "2 根", "这两根横杆负责限制篮筐前后位置，左右两端要能用角码和T型螺母连接。"],
        ["C", "导轨安装座/角码；搜索：2020角码 长圆孔 底座", "铝合金或锌合金 2020 角码/底座，底面必须为长圆孔", "底板侧孔支持 M3；型材侧支持 M5", "8 个", "用于把 A1/A2 两根纵向导轨固定到小车多孔底板上，底部要长圆孔，便于对齐底板 M3 孔。"],
        ["D", "主滑块连接组；搜索：2020型材滑块连接件 手拧锁紧", "2020角码/连接板 + M5 T型螺母 + M5手拧旋钮", "每套用于一个横杆端部；旋钮建议 M5×12 或 M5×16", "4 套", "横向限位杆的两端各一套，拧松可沿纵向导轨前后滑动，拧紧后固定。"],
        ["G", "橡胶块固定片；可让商家加工或买成品连接片", "2-3 mm 铝片/不锈钢片，带 M5 长圆孔", "建议约 20-25 mm 宽、45-60 mm 高；中间开竖向 M5 长圆孔", "4-8 片", "固定片装在横向限位杆侧面，橡胶块装在固定片内侧，固定片可沿横杆左右调。"],
    ]
    story.append(make_table(bom加工, [13 * mm, 42 * mm, 50 * mm, 48 * mm, 18 * mm, 72 * mm], header=True, font_size=7.0, leading=9.0))
    story.append(Spacer(1, 4 * mm))
    story.append(Paragraph("建议给商家补充一句：本组件用于学生项目原型，要求能手动调节并可靠锁紧，不要求高精密滑台。", ss["CNsmall"]))
    story.append(PageBreak())

    title(story, "7. 下单确认表 B：标准配件与紧固件", "这些通常淘宝和京东都能直接买到；如果让型材商家一并配齐，也按这一页核对。")
    bom标准 = [
        ["编号", "要买/加工的件", "材料与规格", "尺寸确认", "数量", "给商家的确认话术"],
        ["E", "T型螺母/滑块螺母；搜索：2020欧标 M5 T型螺母", "2020 欧标槽用，螺纹 M5，优先弹片螺母或滑块螺母", "M5；数量含备用", "约 30 个", "所有角码、固定片、限位块都靠它锁进型材槽内，请按 2020 欧标槽配。"],
        ["F", "锁紧旋钮；搜索：M5 梅花手拧螺丝 旋钮螺丝", "塑料梅花头或星形头，内置 M5 螺杆", "M5×12 或 M5×16；螺杆不要太长以免顶穿型材槽底", "12 个", "用于手动调节后锁紧，要求不用工具就能拧紧。"],
        ["H", "橡胶接触块；搜索：橡胶防滑垫 硅胶垫 方块", "橡胶或硅胶，硬度中等，防滑不刮篮筐", "建议约 30×15×8 mm；可按固定片宽度调整", "4-8 个", "橡胶块只顶住购物篮外壁，不能直接承重；可螺丝固定或强力胶固定到 G 固定片。"],
        ["I", "端盖/限位挡块；搜索：2020型材端盖 2020限位块", "2020 端盖 + 可锁在槽内的限位挡块", "端盖按 2020；限位挡块配 M5", "端盖 8 个，限位挡块 4 个", "端盖防刮手；限位挡块装在导轨端部，防止主滑块滑出。"],
        ["J", "底板连接螺丝", "M3 螺丝、螺母、平垫、弹垫", "M3×8/10/12，按底板和安装座厚度选", "1 批", "用于 C 安装座和小车底板现有 M3 孔连接；若孔不对齐，需要长圆孔底座或转接片。"],
        ["K", "型材连接螺丝", "M5 内六角螺丝或配旋钮螺丝", "M5×8/10/12 常用，按角码厚度选", "1 批", "用于 2020 型材、角码和 T型螺母连接。"],
    ]
    story.append(make_table(bom标准, [13 * mm, 42 * mm, 50 * mm, 48 * mm, 18 * mm, 72 * mm], header=True, font_size=7.0, leading=9.0))
    story.append(Spacer(1, 4 * mm))
    story.append(Paragraph("推荐搜索/沟通关键词：2020欧标铝型材 定制切割、2020角码 长圆孔、2020欧标M5 T型螺母、M5梅花手拧螺丝、2020型材限位块、橡胶防滑垫。", ss["CNsmall"]))
    story.append(PageBreak())

    title(story, "8. 关键连接细节：橡胶块如何装到横杆上", "橡胶块不是直接粘在篮筐上，而是固定在可调固定片上；固定片通过T型螺母锁在横向限位杆槽内。")
    story.append(DrawingFlowable(joint_detail()))
    story.append(PageBreak())

    title(story, "9. 发给商家的文字说明", "可复制给商家确认。")
    msg = """
请按 2020 欧标铝型材配一套可调购物篮固定组件。本组件安装在约 230 mm × 305 mm 的多孔小车载物平台上，不包含篮筐和车架。需要定尺切割 2020 欧标铝型材：250 mm 两根作为左右固定纵向导轨，200 mm 两根作为前/后横向限位杆。型材要求端面切平、去毛刺、配 2020 端盖。请配套 2020 角码或长圆孔底座 8 个，要求底板侧用 M3 螺丝固定，底座底部必须为长圆孔，型材侧可接 M5 T型螺母；2020 欧标 M5 T型螺母/滑块螺母约 30 个；M5×12 或 M5×16 梅花手拧旋钮 12 个；M5 型材连接螺丝若干；2020 型材限位挡块 4 个。另需 4 到 8 片橡胶块固定片，材料为 2-3 mm 铝片或不锈钢片，带 M5 长圆孔，可锁在横向限位杆侧面并左右滑动；每片内侧配约 30×15×8 mm 橡胶/硅胶接触块，用于顶住塑料购物篮外壁、防滑、防刮。要求所有可调位置均为手动调节，调好后用旋钮锁紧，不需要电动滑台。
"""
    story.append(Paragraph(msg, ss["CN"]))
    story.append(Spacer(1, 5 * mm))
    checks = [
        ["复核项", "原因"],
        ["篮筐底部外长", "决定前/后横向限位杆之间的调节范围。"],
        ["篮筐底部外宽", "本次横向限位杆已确定为 200 mm，需确认橡胶块调节余量。"],
        ["底板孔径和可用孔位", "底板连接按 M3，导轨安装座底部要求长圆孔。"],
        ["手机、URM09、VL53L1X位置", "组件不能遮挡摄像头和近场传感器视野。"],
    ]
    story.append(make_table(checks, [55 * mm, 180 * mm], header=True))

    doc.build(story)
    print(str(OUT))


def make_table(rows, widths, header=False, font_size=8.5, leading=None):
    leading = leading or font_size + 3
    body_style = ParagraphStyle("table_body", fontName="SimHei", fontSize=font_size, leading=leading)
    header_style = ParagraphStyle("table_header", fontName="SimHei", fontSize=font_size, leading=leading, textColor=colors.white)
    wrapped = []
    for r, row in enumerate(rows):
        wrapped_row = []
        for cell in row:
            if isinstance(cell, str):
                style = header_style if header and r == 0 else body_style
                wrapped_row.append(Paragraph(cell.replace("\n", "<br/>"), style))
            else:
                wrapped_row.append(cell)
        wrapped.append(wrapped_row)
    t = Table(wrapped, colWidths=widths, repeatRows=1 if header else 0)
    style = [
        ("FONTNAME", (0, 0), (-1, -1), "SimHei"),
        ("FONTSIZE", (0, 0), (-1, -1), font_size),
        ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#888888")),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("LEFTPADDING", (0, 0), (-1, -1), 5),
        ("RIGHTPADDING", (0, 0), (-1, -1), 5),
        ("TOPPADDING", (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
    ]
    if header:
        style += [("BACKGROUND", (0, 0), (-1, 0), BLUE), ("TEXTCOLOR", (0, 0), (-1, 0), colors.white)]
    else:
        style += [("BACKGROUND", (0, 0), (0, -1), LIGHT_BLUE)]
    t.setStyle(TableStyle(style))
    return t


if __name__ == "__main__":
    build_pdf()
