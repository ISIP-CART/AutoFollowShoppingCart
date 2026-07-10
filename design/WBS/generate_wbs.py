from __future__ import annotations

from pathlib import Path
import textwrap

from PIL import Image, ImageDraw, ImageFont


ROOT = Path(__file__).resolve().parent
OUT = ROOT / "WBS.png"
FONT_PATH = Path(r"C:\Windows\Fonts\msyh.ttc")


PACKAGES = [
    {
        "title": "WBS 1  项目管理与建模",
        "owner": "成员 C 主，A/B 配合",
        "items": [
            ("已完成", "首版需求、架构边界、验收口径收口"),
            ("已完成", "采购清单、WBS、里程碑、甘特图初版"),
            ("已完成", "SysML 自动建模工作流与 12 图图集"),
            ("进行中", "第 2 周周报、甘特图、WBS 图更新"),
        ],
    },
    {
        "title": "WBS 2  Android 上位机",
        "owner": "成员 A",
        "items": [
            ("已完成", "Human Cart Simulator 主流程与安全状态机"),
            ("已完成", "初始化距离标定 + 图像伺服 DistanceState"),
            ("已完成", "Android TFLite ReID 与 upright crop 修正"),
            ("进行中", "track / bbox gate、relock、空间支持门控复测"),
        ],
    },
    {
        "title": "WBS 3  ESP32 / AT8236 下位机",
        "owner": "成员 B",
        "items": [
            ("已完成", "麦轮底盘、电机、AT8236、12V 电池接线"),
            ("已完成", "ESP32 与 AT8236 串口连接，WiFi 调控可用"),
            ("进行中", "M1-M4 轮向标定、限速、松手停车"),
            ("待验证", "通信超时、急停和 host 控制协议稳定性"),
        ],
    },
    {
        "title": "WBS 4  结构与物资",
        "owner": "成员 C 主，B 配合",
        "items": [
            ("已完成", "底盘、电池、驱动板、ESP32 等核心物资"),
            ("已完成", "螺丝、铜柱、手机支架、转接线补充采购"),
            ("进行中", "手机支架、电池、线束和控制板固定"),
            ("待开始", "购物筐 / 载物平台安装与负载复测"),
        ],
    },
    {
        "title": "WBS 5  联调与安全",
        "owner": "A/B/C 协同",
        "items": [
            ("进行中", "Human Cart Simulator 四类场景复测"),
            ("待验证", "真实底盘极低速联调准入检查"),
            ("待开始", "目标丢失 LOCAL_SEARCH 与 hard STOP 联调"),
            ("待开始", "基础障碍停车 / 等待策略联调"),
        ],
    },
    {
        "title": "WBS 6  测试与交付",
        "owner": "成员 C 主，A/B 提供内容",
        "items": [
            ("进行中", "cartfollow_diagnostics 与 PC compare 复盘"),
            ("待开始", "手动遥控、负载、转弯、急停测试记录"),
            ("待开始", "演示视频、PPT、海报、总结报告"),
            ("待开始", "最终彩排、参数冻结和现场预案"),
        ],
    },
]

STATUS_COLORS = {
    "已完成": ("#DCFCE7", "#166534"),
    "进行中": ("#DBEAFE", "#1D4ED8"),
    "待验证": ("#FEF3C7", "#92400E"),
    "待开始": ("#F1F5F9", "#475569"),
}


def font(size: int, bold: bool = False) -> ImageFont.FreeTypeFont:
    index = 1 if bold else 0
    return ImageFont.truetype(str(FONT_PATH), size=size, index=index)


TITLE_FONT = font(42, True)
SUBTITLE_FONT = font(24)
BOX_TITLE_FONT = font(27, True)
OWNER_FONT = font(18)
ITEM_FONT = font(19)
TAG_FONT = font(17, True)
FOOT_FONT = font(18)


def wrap_text(text: str, width: int) -> str:
    return "\n".join(textwrap.wrap(text, width=width, break_long_words=False))


def rounded(draw: ImageDraw.ImageDraw, xy, fill, outline="#CBD5E1", radius=18, width=2):
    draw.rounded_rectangle(xy, radius=radius, fill=fill, outline=outline, width=width)


def draw_package(draw: ImageDraw.ImageDraw, x: int, y: int, w: int, h: int, package: dict):
    rounded(draw, (x, y, x + w, y + h), "#FFFFFF", "#CBD5E1", radius=22, width=2)
    draw.rounded_rectangle((x, y, x + w, y + 58), radius=22, fill="#0F172A", outline="#0F172A")
    draw.rectangle((x, y + 32, x + w, y + 58), fill="#0F172A")
    draw.text((x + 24, y + 13), package["title"], font=BOX_TITLE_FONT, fill="#FFFFFF")
    draw.text((x + 24, y + 70), f"负责人：{package['owner']}", font=OWNER_FONT, fill="#64748B")

    item_y = y + 108
    for status, text in package["items"]:
        bg, fg = STATUS_COLORS[status]
        tag_w = 76
        draw.rounded_rectangle((x + 24, item_y, x + 24 + tag_w, item_y + 30), radius=10, fill=bg)
        draw.text((x + 35, item_y + 3), status, font=TAG_FONT, fill=fg)
        wrapped = wrap_text(text, 23)
        draw.text((x + 116, item_y + 1), wrapped, font=ITEM_FONT, fill="#0F172A", spacing=4)
        item_y += 57 if "\n" not in wrapped else 80


def main() -> None:
    width, height = 2200, 1700
    img = Image.new("RGB", (width, height), "#F8FAFC")
    draw = ImageDraw.Draw(img)

    draw.rectangle((0, 0, width, 132), fill="#0F172A")
    draw.text((60, 34), "自主跟随购物车项目 WBS（第 2 周进度更新）", font=TITLE_FONT, fill="#FFFFFF")
    draw.text(
        (60, 90),
        "更新时间：2026-07-10    当前重点：上位机策略复测 + 下位机停车保护 + 结构固定，满足极低速真实底盘联调门槛",
        font=SUBTITLE_FONT,
        fill="#CBD5E1",
    )

    root_x, root_y, root_w, root_h = 530, 172, 1140, 86
    rounded(draw, (root_x, root_y, root_x + root_w, root_y + root_h), "#E0F2FE", "#0284C7", radius=20, width=3)
    draw.text((root_x + 45, root_y + 24), "总目标：4 周内完成低速、安全优先、可展示的 OpenBot 自主跟随购物车原型", font=BOX_TITLE_FONT, fill="#075985")

    box_w, box_h = 650, 450
    xs = [70, 775, 1480]
    ys = [330, 830]
    centers = []
    for idx, _package in enumerate(PACKAGES):
        x = xs[idx % 3]
        y = ys[idx // 3]
        centers.append((x + box_w // 2, y))

    root_center = (root_x + root_w // 2, root_y + root_h)
    for cx, cy in centers:
        draw.line((root_center[0], root_center[1], cx, cy), fill="#94A3B8", width=3)

    for idx, package in enumerate(PACKAGES):
        x = xs[idx % 3]
        y = ys[idx // 3]
        draw_package(draw, x, y, box_w, box_h, package)

    legend_y = 1340
    draw.text((70, legend_y), "状态图例", font=BOX_TITLE_FONT, fill="#0F172A")
    lx = 70
    for status, (bg, fg) in STATUS_COLORS.items():
        draw.rounded_rectangle((lx, legend_y + 50, lx + 96, legend_y + 84), radius=10, fill=bg)
        draw.text((lx + 18, legend_y + 56), status, font=TAG_FONT, fill=fg)
        lx += 128

    notes = [
        "本版 WBS 与当前实际进度对齐：上位机已完成 Human Cart Simulator、ReID、诊断日志和 track/bbox gate 代码接入。",
        "下位机已完成 ESP32 + AT8236 + 电机 + 12V 电池实体链路，当前进入轮向标定、限速和通信超时停车验证。",
        "真实底盘自动跟随尚未开放，必须先完成上位机复测、下位机停车保护和结构固定，再进入极低速联调。",
    ]
    y = legend_y + 130
    for line in notes:
        draw.text((70, y), f"- {line}", font=FOOT_FONT, fill="#334155")
        y += 38

    OUT.parent.mkdir(parents=True, exist_ok=True)
    img.save(OUT)
    print(OUT)


if __name__ == "__main__":
    main()
