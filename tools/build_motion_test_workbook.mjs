import fs from "node:fs/promises";
import { SpreadsheetFile, Workbook } from "@oai/artifact-tool";

const outputDir = "outputs/motion-test-package-20260831";
const outputFile = `${outputDir}/小车手动运动测试记录本.xlsx`;
await fs.mkdir(outputDir, { recursive: true });

const wb = Workbook.create();
const summary = wb.worksheets.add("总览");
const baseline = wb.worksheets.add("测试基线");
const tests = wb.worksheets.add("测试记录");
const motor = wb.worksheets.add("单轮标定");
const load = wb.worksheets.add("负载与温升");
const issues = wb.worksheets.add("问题日志");
const guide = wb.worksheets.add("安全与口径");

const colors = {
  navy: "#17365D",
  blue: "#D9EAF7",
  teal: "#0F766E",
  green: "#E2F0D9",
  amber: "#FFF2CC",
  red: "#FCE4D6",
  gray: "#F2F2F2",
  border: "#D9E2F3",
  white: "#FFFFFF",
};

function title(sheet, range, text) {
  sheet.getRange(range).merge();
  sheet.getRange(range.split(":")[0]).values = [[text]];
  sheet.getRange(range).format = {
    fill: colors.navy,
    font: { bold: true, color: colors.white, size: 16 },
    horizontalAlignment: "left",
    verticalAlignment: "center",
  };
  sheet.getRange(range).format.rowHeight = 30;
}

function section(sheet, range, text) {
  sheet.getRange(range).merge();
  sheet.getRange(range.split(":")[0]).values = [[text]];
  sheet.getRange(range).format = {
    fill: colors.blue,
    font: { bold: true, color: colors.navy },
    verticalAlignment: "center",
  };
}

function header(sheet, range) {
  sheet.getRange(range).format = {
    fill: colors.teal,
    font: { bold: true, color: colors.white },
    horizontalAlignment: "center",
    verticalAlignment: "center",
    wrapText: true,
    borders: { preset: "all", style: "thin", color: colors.border },
  };
  sheet.getRange(range).format.rowHeight = 34;
}

function body(sheet, range) {
  sheet.getRange(range).format = {
    verticalAlignment: "top",
    wrapText: true,
    borders: { preset: "all", style: "thin", color: colors.border },
  };
}

for (const sheet of [summary, baseline, tests, motor, load, issues, guide]) sheet.showGridLines = false;

title(summary, "A1:J1", "小车手动运动测试总览");
summary.getRange("A2:J2").merge();
summary.getRange("A2").values = [["仅限空旷场地、双人值守、手动低速。任何安全失败立即切断电机电源，并停止进入下一阶段。"]];
summary.getRange("A2:J2").format = { fill: colors.red, font: { bold: true, color: "#9C0006" }, wrapText: true };
section(summary, "A4:J4", "现场状态");
summary.getRange("A5:B10").values = [
  ["当前阶段", "待填写"],
  ["测试日期", "待填写"],
  ["操作者", "待填写"],
  ["安全监护人", "待填写"],
  ["场地", "待填写"],
  ["电机总电源可立即切断", "否 / 待确认"],
];
body(summary, "A5:B10");
summary.getRange("A5:A10").format = { fill: colors.gray, font: { bold: true }, borders: { preset: "all", style: "thin", color: colors.border } };
summary.getRange("B5:B10").format = { fill: "#FFFDE7", borders: { preset: "all", style: "thin", color: colors.border } };
section(summary, "D4:J4", "测试状态汇总（由“测试记录”自动统计）");
summary.getRange("D5:G10").values = [
  ["状态", "数量", "说明", "是否可推进"],
  ["PASS", null, "满足本轮预期", "是"],
  ["FAIL", null, "必须修复并复测", "否"],
  ["BLOCKED", null, "缺少条件或证据", "否"],
  ["NOT RUN", null, "尚未执行", "否"],
  ["总记录数", null, "已预置测试用例", "—"],
];
summary.getRange("E6:E10").formulas = [
  ["=COUNTIF('测试记录'!$N$6:$N$200,D6)"],
  ["=COUNTIF('测试记录'!$N$6:$N$200,D7)"],
  ["=COUNTIF('测试记录'!$N$6:$N$200,D8)"],
  ["=COUNTIF('测试记录'!$N$6:$N$200,D9)"],
  ["=COUNTA('测试记录'!$A$6:$A$200)"],
];
header(summary, "D5:G5");
body(summary, "D6:G10");
summary.getRange("D6:D6").format.fill = colors.green;
summary.getRange("D7:D7").format.fill = colors.red;
summary.getRange("D8:D8").format.fill = colors.amber;
summary.getRange("D9:D9").format.fill = colors.gray;
section(summary, "A12:J12", "阶段准入清单");
summary.getRange("A13:J22").values = [
  ["阶段", "名称", "进入条件", "核心验收", "状态", "备注", "", "", "", ""],
  ["P0", "静态检查", "断开电机电源", "结构、接线、轮子、电池均正常", "NOT RUN", "", "", "", "", ""],
  ["P1", "无运动链路", "P0 PASS", "握手、Ready、日志和禁止运动正确", "NOT RUN", "", "", "", "", ""],
  ["P2", "悬空单轮标定", "P1 PASS；四轮悬空", "映射/方向正确，12/14 连续 5/5 起转", "NOT RUN", "", "", "", "", ""],
  ["P3", "悬空 BLE 手动", "P2 PASS", "方向、松手、换向 5/5 正确", "NOT RUN", "", "", "", "", ""],
  ["P4", "悬空安全停车", "P3 PASS", "断连/急停不续动", "NOT RUN", "", "", "", "", ""],
  ["P5", "空载落地运动", "P0--P4 全 PASS", "直线、转向、启停符合口径", "NOT RUN", "", "", "", "", ""],
  ["P6", "落地安全停车", "P5 PASS", "500 ms 输出归零，1.5 s 内停稳", "NOT RUN", "", "", "", "", ""],
  ["P7", "负载", "P6 PASS", "购物筐、1 kg、3 kg 稳定", "NOT RUN", "", "", "", "", ""],
  ["P8", "10 分钟稳定性", "P7 PASS", "无危险温升、断连或机械问题", "NOT RUN", "", "", "", "", ""],
];
header(summary, "A13:F13");
body(summary, "A14:F22");
summary.getRange("E14:E22").dataValidation = { rule: { type: "list", values: ["NOT RUN", "PASS", "FAIL", "BLOCKED"] } };
summary.getRange("A:A").format.columnWidth = 14;
summary.getRange("B:B").format.columnWidth = 19;
summary.getRange("C:C").format.columnWidth = 22;
summary.getRange("D:D").format.columnWidth = 36;
summary.getRange("E:E").format.columnWidth = 13;
summary.getRange("F:F").format.columnWidth = 28;
summary.freezePanes.freezeRows(4);

title(baseline, "A1:F1", "测试基线与现场准备");
baseline.getRange("A3:F3").values = [["字段", "填写值", "字段", "填写值", "字段", "填写值"]];
header(baseline, "A3:F3");
baseline.getRange("A4:F13").values = [
  ["测试日期", "", "测试地点", "", "操作者", ""],
  ["安全监护人", "", "记录人", "", "天气/地面", ""],
  ["主仓库提交", "", "OpenBot 提交", "", "APK 安装时间", ""],
  ["正式固件文件", "esp32_at8236_openbot_ble.ino", "固件编译时间", "", "烧录人员", ""],
  ["电池型号", "", "静态电压 (V)", "", "测试后电压 (V)", ""],
  ["物理急停已接入", "否", "近场传感器已接入", "否", "人工断电可用", "待确认"],
  ["M1 对应车轮", "", "M2 对应车轮", "", "M3 对应车轮", ""],
  ["M4 对应车轮", "", "购物筐状态", "拆下 / 待填写", "测试场地尺寸", "至少 3 m × 5 m"],
  ["手动前进 / 后退 / 转向", "14 / 12 / 5", "输出上限", "40", "控制保鲜 (ms)", "500"],
  ["遥测超时 / 换向静止", "1000 / 1000 ms", "M1/M2/M3/M4 补偿", "105% / 110% / 110% / 110%", "版本来源", "实际烧录源码"],
];
body(baseline, "A4:F13");
baseline.getRange("A4:A13").format.fill = colors.gray;
baseline.getRange("C4:C13").format.fill = colors.gray;
baseline.getRange("E4:E13").format.fill = colors.gray;
baseline.getRange("A15:F15").merge();
baseline.getRange("A15").values = [["通电前勾选：四轮悬空支架牢固（悬空阶段）/ 落地区域清空（落地阶段）/ 电机总电源可立即切断 / 无人站在车前 / 购物筐初始拆下。"]];
baseline.getRange("A15:F15").format = { fill: colors.red, font: { bold: true, color: "#9C0006" }, wrapText: true };
baseline.getRange("A:A").format.columnWidth = 22;
baseline.getRange("B:B").format.columnWidth = 26;
baseline.getRange("C:C").format.columnWidth = 22;
baseline.getRange("D:D").format.columnWidth = 26;
baseline.getRange("E:E").format.columnWidth = 22;
baseline.getRange("F:F").format.columnWidth = 26;

title(tests, "A1:R1", "分阶段测试记录");
tests.getRange("A2:R3").merge();
tests.getRange("A2").values = [["每一行是一条可判定测试记录。安全失败必须填写问题编号、日志/视频位置，并停止进入后续阶段。状态由现场人员确认，不以表格自动判定替代安全判断。"]];
tests.getRange("A2:R3").format = { fill: colors.amber, wrapText: true, font: { bold: true, color: "#7F6000" } };
tests.getRange("A5:R5").values = [["测试编号", "阶段", "测试内容", "重复", "前置条件", "输入/动作", "预期结果", "量化口径", "实际测量", "单位", "日志/视频位置", "问题编号", "测试人员", "状态", "是否安全失败", "复测日期", "复测结论", "备注"]];
header(tests, "A5:R5");
const testRows = [
  ["P0-01", "P0", "结构与车轮静态检查", "1", "电机电源断开", "检查车架、车轮、联轴器、螺丝", "无松动、损伤或卡滞", "全部正常", "", "", "", "", "", "NOT RUN", "否", "", "", ""],
  ["P0-02", "P0", "接线与电池检查", "1", "电机电源断开", "检查共地、串口、电机/编码器线、电池极性和静态电压", "接线可靠、电压正常", "记录电压", "", "V", "", "", "", "NOT RUN", "否", "", "", ""],
  ["P1-01", "P1", "BLE 握手与 Ready", "1", "P0 PASS；悬空或无电机", "发现设备、发送 f、确认 r", "设备名、固件信息、Ready 正确", "完整握手", "", "", "", "", "", "NOT RUN", "否", "", "", ""],
  ["P1-02", "P1", "禁止运动与诊断链路", "1", "P1-01 PASS", "USB !Q、!D,1；Android 开记录日志", "未 Ready 禁止运动；两侧日志可对齐", "触摸→写入→motion_rx", "", "", "", "", "", "NOT RUN", "否", "", "", ""],
  ["P2-01", "P2", "M1 悬空单轮标定", "44", "P1 PASS；烧录标定固件", "正负 3/5/8/12/14/20", "方向、映射、$MSPD 正确", "12/14 各 5/5 起转", "", "", "", "", "", "NOT RUN", "否", "", "", "详见“单轮标定”"],
  ["P2-02", "P2", "M2 悬空单轮标定", "44", "同上", "正负 3/5/8/12/14/20", "方向、映射、$MSPD 正确", "12/14 各 5/5 起转", "", "", "", "", "", "NOT RUN", "否", "", "", "详见“单轮标定”"],
  ["P2-03", "P2", "M3 悬空单轮标定", "44", "同上", "正负 3/5/8/12/14/20", "方向、映射、$MSPD 正确", "12/14 各 5/5 起转", "", "", "", "", "", "NOT RUN", "否", "", "", "详见“单轮标定”"],
  ["P2-04", "P2", "M4 悬空单轮标定", "44", "同上", "正负 3/5/8/12/14/20", "方向、映射、$MSPD 正确", "12/14 各 5/5 起转", "", "", "", "", "", "NOT RUN", "否", "", "", "详见“单轮标定”"],
  ["P3-01", "P3", "悬空前进—松手", "5", "P2 PASS；正式 BLE 固件", "按前进后松手", "方向正确；松手 c0,0", "5/5", "", "", "", "", "", "NOT RUN", "否", "", "", ""],
  ["P3-02", "P3", "悬空后退—松手", "5", "同上", "按后退后松手", "方向正确；松手 c0,0", "5/5", "", "", "", "", "", "NOT RUN", "否", "", "", ""],
  ["P3-03", "P3", "悬空左/右转—松手", "10", "同上", "左右转各 5 次", "方向正确；松手 c0,0", "各 5/5", "", "", "", "", "", "NOT RUN", "否", "", "", ""],
  ["P3-04", "P3", "悬空切换与换向保护", "20", "同上", "前→左、前→后、左→右、双指/滑动", "旧输入不覆盖；先停车后换向", "各 5/5；静止 1000 ms", "", "ms", "", "", "", "NOT RUN", "否", "", "", ""],
  ["P4-01", "P4", "悬空松手与离页停车", "6", "P3 PASS", "松手/离开控制页各 3 次", "立即 c0,0；无续转", "各 3/3", "", "", "", "", "", "NOT RUN", "否", "", "", ""],
  ["P4-02", "P4", "悬空断连/停止 App", "6", "同上", "关闭蓝牙、断开 BLE、停止 App", "500 ms 内撤销非零输出", "每项 3/3", "", "ms", "", "", "", "NOT RUN", "否", "", "", ""],
  ["P4-03", "P4", "悬空软件急停与恢复", "3", "同上", "运动中软件急停后重连", "急停锁存；不自动续动", "3/3", "", "", "", "", "", "NOT RUN", "否", "", "", ""],
  ["P5-01", "P5", "空载短按四方向", "20", "P0--P4 PASS；空旷落地", "前后左右各 5 次，0.5--1 s", "方向正确、完全停稳", "各 5/5", "", "", "", "", "", "NOT RUN", "否", "", "", ""],
  ["P5-02", "P5", "空载前进 2 m", "5", "P5-01 PASS", "前进 2 m", "轨迹稳定", "横向偏差 ≤20 cm", "", "cm", "", "", "", "NOT RUN", "否", "", "", ""],
  ["P5-03", "P5", "空载后退 1 m", "3", "P5-01 PASS", "后退 1 m", "轨迹稳定", "记录偏差", "", "cm", "", "", "", "NOT RUN", "否", "", "", ""],
  ["P5-04", "P5", "空载左右 90°", "6", "P5-01 PASS", "左右各约 90°", "无明显横向窜动", "误差 ≤15°", "", "°", "", "", "", "NOT RUN", "否", "", "", ""],
  ["P5-05", "P5", "空载弧线与启停", "16", "P5-01 PASS", "左右弧线各 3；启停 10", "无蛇形、打滑、单轮停转", "启停 10/10", "", "", "", "", "", "NOT RUN", "否", "", "", ""],
  ["P6-01", "P6", "落地松手停车", "3", "P5 PASS", "低速直线后松手", "输出撤销、车体停稳", "≤30 cm；≤1.5 s", "", "cm / s", "", "", "", "NOT RUN", "否", "", "", ""],
  ["P6-02", "P6", "落地 BLE 断开停车", "3", "P5 PASS", "低速直线后断开 BLE", "500 ms 内输出归零；不续动", "≤30 cm；≤1.5 s", "", "cm / s", "", "", "", "NOT RUN", "否", "", "", ""],
  ["P6-03", "P6", "落地页面失焦/退出停车", "3", "P5 PASS", "低速直线后失焦或退出", "停车且恢复后不续动", "≤30 cm；≤1.5 s", "", "cm / s", "", "", "", "NOT RUN", "否", "", "", ""],
  ["P6-04", "P6", "落地软件急停", "3", "P5 PASS", "低速直线中急停", "锁存停车；不直接恢复", "≤30 cm；≤1.5 s", "", "cm / s", "", "", "", "NOT RUN", "否", "", "", ""],
  ["P7-01", "P7", "空购物筐路线", "3", "P6 PASS", "2m→停→左90°→1m→停→右90°→后退1m", "结构稳定", "完成 3/3", "", "", "", "", "", "NOT RUN", "否", "", "", "详见“负载与温升”"],
  ["P7-02", "P7", "1 kg 负载路线", "3", "P7-01 PASS", "同上", "无滑动、倾覆或异常温升", "完成 3/3；恶化 ≤25%", "", "", "", "", "", "NOT RUN", "否", "", "", "详见“负载与温升”"],
  ["P7-03", "P7", "3 kg 负载路线", "3", "P7-02 PASS", "同上", "无滑动、倾覆或异常温升", "完成 3/3；恶化 ≤25%", "", "", "", "", "", "NOT RUN", "否", "", "", "详见“负载与温升”"],
  ["P8-01", "P8", "10 分钟稳定性", "1", "P7 PASS", "低速往返和左右转；每 2 分钟检查", "无断连、复位、危险温升或松动", "10 min", "", "min", "", "", "", "NOT RUN", "否", "", "", "详见“负载与温升”"],
  ["P8-02", "P8", "稳定性后复检", "1", "P8-01 PASS", "前后左右和停车各一次", "能力未下降", "全部通过", "", "", "", "", "", "NOT RUN", "否", "", "", ""],
];
tests.getRange(`A6:R${5 + testRows.length}`).values = testRows;
body(tests, `A6:R${5 + testRows.length}`);
tests.getRange(`N6:N200`).dataValidation = { rule: { type: "list", values: ["NOT RUN", "PASS", "FAIL", "BLOCKED"] } };
tests.getRange(`O6:O200`).dataValidation = { rule: { type: "list", values: ["否", "是"] } };
tests.getRange(`N6:N200`).conditionalFormats.add("containsText", { text: "PASS", format: { fill: colors.green, font: { bold: true, color: "#006100" } } });
tests.getRange(`N6:N200`).conditionalFormats.add("containsText", { text: "FAIL", format: { fill: colors.red, font: { bold: true, color: "#9C0006" } } });
tests.getRange(`N6:N200`).conditionalFormats.add("containsText", { text: "BLOCKED", format: { fill: colors.amber, font: { bold: true, color: "#7F6000" } } });
tests.getRange(`O6:O200`).conditionalFormats.add("containsText", { text: "是", format: { fill: colors.red, font: { bold: true, color: "#9C0006" } } });
const testWidths = [14, 10, 24, 9, 22, 25, 26, 22, 18, 12, 24, 14, 13, 13, 14, 14, 14, 28];
testWidths.forEach((width, index) => tests.getRangeByIndexes(0, index, 200, 1).format.columnWidth = width);
tests.freezePanes.freezeRows(5);

title(motor, "A1:N1", "四轮悬空单轮标定记录");
motor.getRange("A3:N3").values = [["电机", "实际车轮", "方向", "命令速度", "重复", "时长 (ms)", "是否起转", "起转延迟 (ms)", "停止尾速 (ms)", "峰值 $MSPD", "$MSPD 字段", "串通道", "状态", "备注"]];
header(motor, "A3:N3");
const motorRows = [];
for (const m of ["M1", "M2", "M3", "M4"]) {
  for (const direction of ["正转", "反转"]) {
    for (const speed of [3, 5, 8, 12, 14, 20]) {
      const repetitions = [12, 14].includes(speed) ? 5 : 3;
      for (let repeat = 1; repeat <= repetitions; repeat += 1) {
        motorRows.push([m, "", direction, direction === "正转" ? speed : -speed, repeat, 500, "", "", "", "", "", "否", "NOT RUN", ""]);
      }
    }
  }
}
motor.getRange(`A4:N${3 + motorRows.length}`).values = motorRows;
body(motor, `A4:N${3 + motorRows.length}`);
motor.getRange(`G4:G${3 + motorRows.length}`).dataValidation = { rule: { type: "list", values: ["是", "否"] } };
motor.getRange(`L4:L${3 + motorRows.length}`).dataValidation = { rule: { type: "list", values: ["否", "是"] } };
motor.getRange(`M4:M${3 + motorRows.length}`).dataValidation = { rule: { type: "list", values: ["NOT RUN", "PASS", "FAIL", "BLOCKED"] } };
motor.getRange(`M4:M${3 + motorRows.length}`).conditionalFormats.add("containsText", { text: "FAIL", format: { fill: colors.red, font: { bold: true, color: "#9C0006" } } });
motor.getRange(`M4:M${3 + motorRows.length}`).conditionalFormats.add("containsText", { text: "PASS", format: { fill: colors.green, font: { bold: true, color: "#006100" } } });
[10, 15, 11, 12, 8, 13, 11, 15, 15, 14, 14, 10, 13, 28].forEach((width, index) => motor.getRangeByIndexes(0, index, motorRows.length + 3, 1).format.columnWidth = width);
motor.freezePanes.freezeRows(3);

title(load, "A1:P1", "购物筐、负载与温升记录");
load.getRange("A3:P3").values = [["负载档", "轮次", "路线完成", "2m 偏差 (cm)", "90° 误差 (°)", "停车距离 (cm)", "电池前 (V)", "电池后 (V)", "M1 (°C)", "M2 (°C)", "M3 (°C)", "M4 (°C)", "AT8236 (°C)", "购物筐/载荷位移", "状态", "备注"]];
header(load, "A3:P3");
const loadRows = [];
for (const tier of ["空购物筐", "1 kg", "3 kg"]) {
  for (let run = 1; run <= 3; run += 1) loadRows.push([tier, run, "", "", "", "", "", "", "", "", "", "", "", "", "NOT RUN", ""]);
}
for (let check = 1; check <= 5; check += 1) loadRows.push(["10 分钟稳定性", `第 ${check * 2} 分钟`, "", "", "", "", "", "", "", "", "", "", "", "", "NOT RUN", "停车检查"]);
load.getRange(`A4:P${3 + loadRows.length}`).values = loadRows;
body(load, `A4:P${3 + loadRows.length}`);
load.getRange(`C4:C${3 + loadRows.length}`).dataValidation = { rule: { type: "list", values: ["是", "否"] } };
load.getRange(`O4:O${3 + loadRows.length}`).dataValidation = { rule: { type: "list", values: ["NOT RUN", "PASS", "FAIL", "BLOCKED"] } };
load.getRange(`O4:O${3 + loadRows.length}`).conditionalFormats.add("containsText", { text: "FAIL", format: { fill: colors.red, font: { bold: true, color: "#9C0006" } } });
load.getRange(`O4:O${3 + loadRows.length}`).conditionalFormats.add("containsText", { text: "PASS", format: { fill: colors.green, font: { bold: true, color: "#006100" } } });
[16, 11, 13, 15, 14, 16, 13, 13, 11, 11, 11, 11, 13, 22, 13, 30].forEach((width, index) => load.getRangeByIndexes(0, index, loadRows.length + 3, 1).format.columnWidth = width);
load.freezePanes.freezeRows(3);

title(issues, "A1:K1", "问题与复测日志");
issues.getRange("A3:K3").values = [["问题编号", "发现阶段", "严重性", "现象", "复现条件", "初步归属", "安全动作", "日志/视频位置", "临时处置", "复测结论", "关闭日期"]];
header(issues, "A3:K3");
issues.getRange("A4:K28").values = Array.from({ length: 25 }, (_, i) => [`ISS-${String(i + 1).padStart(3, "0")}`, "", "", "", "", "", "", "", "", "", ""]);
body(issues, "A4:K28");
issues.getRange("C4:C28").dataValidation = { rule: { type: "list", values: ["安全关键", "高", "中", "低"] } };
issues.getRange("F4:F28").dataValidation = { rule: { type: "list", values: ["Android", "BLE", "ESP32", "AT8236", "电机", "机械", "供电", "待分析"] } };
issues.getRange("J4:J28").dataValidation = { rule: { type: "list", values: ["待复测", "仍失败", "已通过", "不适用"] } };
[14, 12, 12, 28, 26, 14, 22, 24, 22, 16, 14].forEach((width, index) => issues.getRangeByIndexes(0, index, 28, 1).format.columnWidth = width);
issues.freezePanes.freezeRows(3);

title(guide, "A1:F1", "现场安全与判定口径");
section(guide, "A3:E3", "任何一项触发即停止");
guide.getRange("A4:E11").values = [
  ["松手/断连后仍运动", "切断电机电源", "FAIL", "禁止进入下一阶段", "记录时间点和日志"],
  ["轮向错误或相互对抗", "切断电机电源", "FAIL", "检查映射/接线", "禁止落地"],
  ["换向时提前反转", "切断电机电源", "FAIL", "检查 REVERSAL_BLOCKED", "禁止落地"],
  ["遥测中断仍转动", "切断电机电源", "FAIL", "检查 AT8236/超时", "禁止落地"],
  ["异响、抖动、卡死、焦味", "切断电机电源", "FAIL", "检查机械/供电", "等待排障"],
  ["购物筐/载荷松动或倾覆风险", "切断电机电源", "FAIL", "检查结构固定", "停止负载测试"],
  ["温度达到 50°C", "暂停检查", "BLOCKED", "测温/供电检查", "不得继续加负载"],
  ["温度达到 60°C", "切断电机电源", "FAIL", "检查负载/电流/散热", "不得继续"],
];
body(guide, "A4:E11");
guide.getRange("A4:A11").format.fill = colors.red;
section(guide, "A13:F13", "量化通过口径");
guide.getRange("A14:F21").values = [
  ["项目", "口径", "数值", "备注", "", ""],
  ["悬空 12/14 起转", "连续成功", "5/5", "每个电机、每个方向", "", ""],
  ["悬空手动与换向", "连续成功", "5/5", "各手势/方向", "", ""],
  ["断连输出撤销", "最大时间", "500 ms", "非零控制保鲜超时", "", ""],
  ["落地完全停稳", "最大时间", "1.5 s", "低速短距离", "", ""],
  ["低速停车距离", "最大距离", "30 cm", "低速短距离", "", ""],
  ["前进 2m 横向偏差", "最大偏差", "20 cm", "空载基线", "", ""],
  ["90° 转向误差", "最大误差", "15°", "空载基线", "", ""],
];
header(guide, "A14:F14");
body(guide, "A15:F21");
guide.getRange("A:A").format.columnWidth = 30;
guide.getRange("B:B").format.columnWidth = 16;
guide.getRange("C:C").format.columnWidth = 16;
guide.getRange("D:D").format.columnWidth = 34;
guide.getRange("E:E").format.columnWidth = 24;
guide.getRange("F:F").format.columnWidth = 4;

const output = await SpreadsheetFile.exportXlsx(wb);
await output.save(outputFile);

const inspect = await wb.inspect({
  kind: "table",
  range: "总览!A1:J22",
  include: "values,formulas",
  tableMaxRows: 22,
  tableMaxCols: 10,
});
console.log(inspect.ndjson);
const errors = await wb.inspect({
  kind: "match",
  searchTerm: "#REF!|#DIV/0!|#VALUE!|#NAME\\?|#N/A",
  options: { useRegex: true, maxResults: 100 },
  summary: "formula error scan",
});
console.log(errors.ndjson);
for (const sheetName of ["总览", "测试基线", "测试记录", "单轮标定", "负载与温升", "问题日志", "安全与口径"]) {
  const preview = await wb.render({ sheetName, autoCrop: "all", scale: 1, format: "png" });
  await fs.writeFile(`${outputDir}/${sheetName}.png`, new Uint8Array(await preview.arrayBuffer()));
}
