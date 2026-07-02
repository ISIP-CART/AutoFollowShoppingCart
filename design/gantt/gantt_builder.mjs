import fs from "node:fs/promises";
import path from "node:path";
import { pathToFileURL } from "node:url";

const artifactToolModulePath = pathToFileURL(
  path.join(
    process.env.USERPROFILE || "C:\\Users\\MSI",
    ".cache",
    "codex-runtimes",
    "codex-primary-runtime",
    "dependencies",
    "node",
    "node_modules",
    "@oai",
    "artifact-tool",
    "dist",
    "artifact_tool.mjs",
  ),
).href;
const { SpreadsheetFile, Workbook } = await import(artifactToolModulePath);

const repoRoot = process.cwd();
const designDir = path.join(repoRoot, "design");
const ganttDir = path.join(designDir, "gantt");
const outputPath = path.join(ganttDir, "autofollowshoppingcart-day-gantt.xlsx");
const previewPath = path.join(ganttDir, "autofollowshoppingcart-day-gantt-preview.png");
const totalDays = 28;

const tasks = [
  { id: "T01", task: "需求收口与关键指标确定", owner: "成员 A / C", track: "项目规划", startDay: 1, endDay: 2, deliverable: "需求与指标口径定稿", note: "对齐场景、功能边界和验收指标" },
  { id: "T02", task: "WBS、分工与物料清单初版", owner: "成员 C", track: "项目规划", startDay: 1, endDay: 3, deliverable: "WBS、分工、BOM 初稿", note: "建立项目管理主文档" },
  { id: "T03", task: "方案 PPT 与汇报材料准备", owner: "成员 A / C", track: "项目规划", startDay: 1, endDay: 5, deliverable: "方案 PPT 初版", note: "用于第 1 周阶段汇报" },
  { id: "T04", task: "OpenBot App 环境搭建与编译", owner: "成员 A", track: "上位机", startDay: 1, endDay: 4, deliverable: "可运行 OpenBot App", note: "记录构建环境和依赖版本" },
  { id: "T05", task: "MCU 环境搭建与固件烧录", owner: "成员 B", track: "下位机", startDay: 1, endDay: 3, deliverable: "可运行基础固件", note: "打通 Arduino Nano 或 ESP32 基础控制" },
  { id: "T06", task: "底盘、电机、电源到货检查", owner: "成员 B / C", track: "硬件", startDay: 1, endDay: 4, deliverable: "到货验收记录", note: "核对型号、接口和供电需求" },
  { id: "T07", task: "手机与下位机串口通信打通", owner: "成员 B / A", track: "下位机", startDay: 3, endDay: 6, deliverable: "通信链路可用", note: "保留串口日志和异常记录" },
  { id: "T08", task: "底盘装配与基础运动联调", owner: "成员 B", track: "硬件", startDay: 3, endDay: 8, deliverable: "底盘可稳定运动", note: "完成前进、后退、转向、停车" },
  { id: "T09", task: "手机支架与视角固定", owner: "成员 C", track: "结构", startDay: 3, endDay: 6, deliverable: "支架固定完成", note: "保证画面稳定、视角合理" },
  { id: "T10", task: "手动遥控测试与记录", owner: "成员 B / C", track: "测试", startDay: 5, endDay: 7, deliverable: "手动遥控测试记录", note: "形成第 1 周基础链路验收证据" },
  { id: "T11", task: "人物检测与目标初始化", owner: "成员 A", track: "上位机", startDay: 8, endDay: 11, deliverable: "目标初始化可用", note: "先在单人、受控场景下完成" },
  { id: "T12", task: "单人直线跟随初版", owner: "成员 A", track: "上位机", startDay: 9, endDay: 13, deliverable: "直线跟随初版", note: "实现目标锁定与基础跟随控制" },
  { id: "T13", task: "购物筐与载物平台结构改造", owner: "成员 C", track: "结构", startDay: 8, endDay: 14, deliverable: "购物筐结构完成", note: "重点处理重心和安装稳固性" },
  { id: "T14", task: "供电、驱动与负载稳定性调试", owner: "成员 B", track: "下位机", startDay: 8, endDay: 12, deliverable: "供电与驱动稳定", note: "保证带载运行不掉压不过热" },
  { id: "T15", task: "跟随参数调节一轮", owner: "成员 A / C", track: "测试", startDay: 11, endDay: 16, deliverable: "第一版参数表", note: "调速度、距离、转向灵敏度" },
  { id: "T16", task: "急停按钮与停车执行链路", owner: "成员 B / C", track: "安全", startDay: 10, endDay: 15, deliverable: "急停功能可用", note: "未解除急停前不得再次启动" },
  { id: "T17", task: "通信超时停车保护", owner: "成员 B", track: "安全", startDay: 11, endDay: 15, deliverable: "断连保护可用", note: "配合通信测试复验" },
  { id: "T18", task: "目标丢失安全搜索与停车", owner: "成员 A / B / C", track: "安全", startDay: 14, endDay: 18, deliverable: "LOST / SEARCH / STOP 联调完成", note: "先取消前进，再短时原地搜索，超时停车" },
  { id: "T19", task: "障碍停车集成", owner: "成员 C / B", track: "安全", startDay: 15, endDay: 19, deliverable: "障碍停车可用", note: "首版优先实现减速或停车" },
  { id: "T20", task: "系统联调一轮", owner: "成员 A / B / C", track: "联调", startDay: 16, endDay: 20, deliverable: "核心闭环初通", note: "验证跟随与停车链路协同" },
  { id: "T21", task: "中期材料与问题清单整理", owner: "成员 C / A / B", track: "项目规划", startDay: 17, endDay: 18, deliverable: "中期汇报材料", note: "整理已完成内容、问题和最后一周计划" },
  { id: "T22", task: "转弯、停下与负载测试", owner: "成员 C / A / B", track: "测试", startDay: 18, endDay: 22, deliverable: "测试记录补全", note: "补足非直线路径和载物场景" },
  { id: "T23", task: "系统联调二轮与问题收敛", owner: "成员 A / B / C", track: "联调", startDay: 21, endDay: 24, deliverable: "稳定版参数与流程", note: "围绕最终演示脚本收敛问题" },
  { id: "T24", task: "演示视频录制与脚本固化", owner: "成员 C / A / B", track: "交付", startDay: 22, endDay: 26, deliverable: "演示视频与脚本", note: "保留分段演示与完整演示素材" },
  { id: "T25", task: "海报、PPT、总结报告收口", owner: "成员 C / A / B", track: "交付", startDay: 23, endDay: 27, deliverable: "海报、PPT、总结报告", note: "成员 C 主收口，A/B 提供技术内容" },
  { id: "T26", task: "最终彩排与现场预案确认", owner: "成员 A / B / C", track: "交付", startDay: 27, endDay: 28, deliverable: "最终演示预案", note: "保留保守参数、备件、电池和线材" },
];

const criticalTaskIds = new Set([
  "T04", "T05", "T06", "T07", "T08", "T10",
  "T11", "T12", "T14", "T15",
  "T16", "T17", "T18", "T20",
  "T23", "T26",
]);

const milestoneNodes = [
  {
    id: "M1",
    taskId: "T10",
    day: 7,
    label: "基础链路跑通",
    description: "若 Week 1 前未跑通手动遥控与基础链路，后续自主跟随与安全联调无法开展。",
  },
  {
    id: "M2",
    taskId: "T15",
    day: 16,
    label: "自主跟随初版完成",
    description: "若目标初始化、直线跟随与首轮参数调节未完成，后续安全策略和系统联调无法开展。",
  },
  {
    id: "M3",
    taskId: "T20",
    day: 20,
    label: "安全闭环联调完成",
    description: "若急停、失联停车、目标丢失与系统联调未完成，后续展示录制和最终交付无法开展。",
  },
  {
    id: "M4",
    taskId: "T26",
    day: 28,
    label: "最终展示闭环完成",
    description: "若最终彩排与现场预案未完成，课程展示和材料收口无法按计划交付。",
  },
];

const milestoneByTaskId = new Map(milestoneNodes.map((item) => [item.taskId, item]));
const milestoneDays = new Set(milestoneNodes.map((item) => item.day));

const ownerColors = {
  "成员 A": "#DBEAFE",
  "成员 B": "#DCFCE7",
  "成员 C": "#FCE7F3",
  "成员 A / B": "#E0E7FF",
  "成员 B / A": "#E0E7FF",
  "成员 A / C": "#E0F2FE",
  "成员 B / C": "#ECFCCB",
  "成员 C / B": "#ECFCCB",
  "成员 C / A / B": "#FAE8FF",
  "成员 A / B / C": "#F3F4F6",
};

const trackColors = {
  项目规划: "#0F766E",
  上位机: "#2563EB",
  下位机: "#16A34A",
  硬件: "#B45309",
  结构: "#A21CAF",
  安全: "#DC2626",
  测试: "#7C3AED",
  联调: "#1D4ED8",
  交付: "#374151",
};

function excelColName(n) {
  let s = "";
  let x = n;
  while (x > 0) {
    const m = (x - 1) % 26;
    s = String.fromCharCode(65 + m) + s;
    x = Math.floor((x - 1) / 26);
  }
  return s;
}

const workbook = Workbook.create();
const tasksSheet = workbook.worksheets.add("任务清单");
const ganttSheet = workbook.worksheets.add("日甘特图");
const lastDayCol = excelColName(6 + totalDays);
const baseRow = 6;
const noteRow = baseRow + tasks.length + 2;

tasksSheet.showGridLines = false;
ganttSheet.showGridLines = false;

tasksSheet.getRange("A1:H1").merge();
tasksSheet.getRange("A1").values = [["自主跟随购物车项目 - 4 周日级任务清单"]];
tasksSheet.getRange("A1").format = {
  fill: "#0F172A",
  font: { bold: true, color: "#FFFFFF", size: 16 },
  horizontalAlignment: "center",
  verticalAlignment: "center",
};
tasksSheet.getRange("A1:H1").format.rowHeight = 28;

tasksSheet.getRange("A3:H3").values = [[
  "编号",
  "任务",
  "负责人",
  "开始天",
  "结束天",
  "工期(天)",
  "任务线",
  "交付件 / 备注",
]];
tasksSheet.getRange("A3:H3").format = {
  fill: "#E2E8F0",
  font: { bold: true, color: "#0F172A" },
  horizontalAlignment: "center",
  verticalAlignment: "center",
  borders: { preset: "all", style: "thin", color: "#CBD5E1" },
};

const taskRows = tasks.map((task) => [
  task.id,
  task.task,
  task.owner,
  task.startDay,
  task.endDay,
  task.endDay - task.startDay + 1,
  task.track,
  `${task.deliverable}；${task.note}`,
]);

tasksSheet.getRange(`A4:H${3 + tasks.length}`).values = taskRows;
tasksSheet.getRange(`A4:H${3 + tasks.length}`).format = {
  verticalAlignment: "center",
  borders: { preset: "all", style: "thin", color: "#E2E8F0" },
  wrapText: true,
};
tasksSheet.getRange(`D4:F${3 + tasks.length}`).format.numberFormat = "0";

for (let i = 0; i < tasks.length; i += 1) {
  const row = i + 4;
  tasksSheet.getRange(`C${row}`).format.fill = ownerColors[tasks[i].owner] || "#F8FAFC";
  tasksSheet.getRange(`G${row}`).format = {
    fill: trackColors[tasks[i].track] || "#64748B",
    font: { bold: true, color: "#FFFFFF" },
    horizontalAlignment: "center",
  };
}

tasksSheet.getRange("A:A").format.columnWidth = 10;
tasksSheet.getRange("B:B").format.columnWidth = 28;
tasksSheet.getRange("C:C").format.columnWidth = 18;
tasksSheet.getRange("D:F").format.columnWidth = 10;
tasksSheet.getRange("G:G").format.columnWidth = 12;
tasksSheet.getRange("H:H").format.columnWidth = 42;
tasksSheet.getRange(`A4:H${3 + tasks.length}`).format.autofitRows();
tasksSheet.freezePanes.freezeRows(3);

ganttSheet.getRange(`A1:${lastDayCol}1`).merge();
ganttSheet.getRange("A1").values = [["自主跟随购物车项目 - 4 周日级甘特图"]];
ganttSheet.getRange("A1").format = {
  fill: "#0F172A",
  font: { bold: true, color: "#FFFFFF", size: 16 },
  horizontalAlignment: "center",
  verticalAlignment: "center",
};
ganttSheet.getRange(`A1:${lastDayCol}1`).format.rowHeight = 30;

ganttSheet.getRange("A2:F2").values = [[
  "排期单位",
  "第 X 天",
  "总周期",
  `${totalDays} 天`,
  "总工期",
  `${totalDays} 天`,
]];
ganttSheet.getRange("A2:F2").format = {
  fill: "#F8FAFC",
  borders: { preset: "all", style: "thin", color: "#CBD5E1" },
  verticalAlignment: "center",
  wrapText: true,
};
ganttSheet.getRange("A2,C2,E2").format = { font: { bold: true } };

ganttSheet.getRange("A4:F4").values = [[
  "任务编号",
  "任务",
  "负责人",
  "任务线",
  "开始天",
  "结束天",
]];
ganttSheet.getRange("A4:F4").format = {
  fill: "#E2E8F0",
  font: { bold: true, color: "#0F172A" },
  horizontalAlignment: "center",
  verticalAlignment: "center",
  borders: { preset: "all", style: "thin", color: "#CBD5E1" },
};

const weekHeader = [];
const dayIndexHeader = [];
const dayLabelHeader = [];
for (let day = 1; day <= totalDays; day += 1) {
  weekHeader.push(`第${Math.floor((day - 1) / 7) + 1}周`);
  dayIndexHeader.push(day);
  dayLabelHeader.push(`第${day}天`);
}

ganttSheet.getRange(`G3:${lastDayCol}3`).values = [weekHeader];
ganttSheet.getRange(`G4:${lastDayCol}4`).values = [dayIndexHeader];
ganttSheet.getRange(`G5:${lastDayCol}5`).values = [dayLabelHeader];
ganttSheet.getRange(`G3:${lastDayCol}5`).format = {
  borders: { preset: "all", style: "thin", color: "#CBD5E1" },
  horizontalAlignment: "center",
  verticalAlignment: "center",
};
ganttSheet.getRange(`G3:${lastDayCol}3`).format = {
  fill: "#C7D2FE",
  font: { bold: true, color: "#312E81" },
  horizontalAlignment: "center",
};
ganttSheet.getRange(`G4:${lastDayCol}4`).format = {
  fill: "#DBEAFE",
  font: { bold: true, color: "#1D4ED8" },
  horizontalAlignment: "center",
};
ganttSheet.getRange(`G5:${lastDayCol}5`).format = {
  fill: "#F8FAFC",
  font: { color: "#0F172A" },
  horizontalAlignment: "center",
};

const leftMeta = tasks.map((task) => [
  task.id,
  task.task,
  task.owner,
  task.track,
  task.startDay,
  task.endDay,
]);
ganttSheet.getRange(`A${baseRow}:F${baseRow + tasks.length - 1}`).values = leftMeta;
ganttSheet.getRange(`A${baseRow}:F${baseRow + tasks.length - 1}`).format = {
  borders: { preset: "all", style: "thin", color: "#E2E8F0" },
  verticalAlignment: "center",
  wrapText: true,
};
ganttSheet.getRange(`E${baseRow}:F${baseRow + tasks.length - 1}`).format.numberFormat = "0";

for (let i = 0; i < tasks.length; i += 1) {
  const row = baseRow + i;
  const task = tasks[i];
  ganttSheet.getRange(`C${row}`).format.fill = ownerColors[task.owner] || "#F8FAFC";
  ganttSheet.getRange(`D${row}`).format = {
    fill: trackColors[task.track] || "#64748B",
    font: { bold: true, color: "#FFFFFF" },
    horizontalAlignment: "center",
  };
}

for (let i = 0; i < tasks.length; i += 1) {
  const task = tasks[i];
  const milestone = milestoneByTaskId.get(task.id);
  const dayValues = [];
  for (let day = 0; day < totalDays; day += 1) {
    const currentDay = day + 1;
    if (currentDay < task.startDay || currentDay > task.endDay) {
      dayValues.push("");
    } else if (milestone && currentDay === task.endDay) {
      dayValues.push(3);
    } else if (criticalTaskIds.has(task.id)) {
      dayValues.push(2);
    } else {
      dayValues.push(1);
    }
  }
  const row = baseRow + i;
  ganttSheet.getRange(`G${row}:${lastDayCol}${row}`).values = [dayValues];

  for (let day = task.startDay; day <= task.endDay; day += 1) {
    const col = excelColName(6 + day);
    const cell = ganttSheet.getRange(`${col}${row}`);
    let fill = "#60A5FA";
    let fontColor = "#60A5FA";
    if (criticalTaskIds.has(task.id)) {
      fill = "#F59E0B";
      fontColor = "#F59E0B";
    }
    if (milestone && day === task.endDay) {
      fill = "#DC2626";
      fontColor = "#DC2626";
      cell.format = {
        fill,
        font: { color: fontColor },
        borders: { preset: "all", style: "medium", color: "#7F1D1D" },
        horizontalAlignment: "center",
        verticalAlignment: "center",
        numberFormat: ";;;",
      };
    } else {
      cell.format = {
        fill,
        font: { color: fontColor },
        horizontalAlignment: "center",
        verticalAlignment: "center",
        numberFormat: ";;;",
      };
    }
  }
}
ganttSheet.getRange(`G${baseRow}:${lastDayCol}${baseRow + tasks.length - 1}`).format = {
  borders: { preset: "all", style: "thin", color: "#E2E8F0" },
  horizontalAlignment: "center",
  verticalAlignment: "center",
  numberFormat: ";;;",
};

for (let day = 1; day <= totalDays; day += 1) {
  if (day % 7 === 6 || day % 7 === 0) {
    const col = excelColName(6 + day);
    ganttSheet.getRange(`${col}3:${col}${baseRow + tasks.length - 1}`).format.fill = "#F8FAFC";
  }
}

for (const day of milestoneDays) {
  const col = excelColName(6 + day);
  ganttSheet.getRange(`${col}3:${col}5`).format = {
    fill: "#FECACA",
    font: { bold: true, color: "#991B1B" },
    horizontalAlignment: "center",
    verticalAlignment: "center",
    borders: { preset: "all", style: "thin", color: "#FCA5A5" },
  };
}

for (let i = 0; i < tasks.length; i += 1) {
  const row = baseRow + i;
  const task = tasks[i];
  const milestone = milestoneByTaskId.get(task.id);
  for (let day = task.startDay; day <= task.endDay; day += 1) {
    const col = excelColName(6 + day);
    const cell = ganttSheet.getRange(`${col}${row}`);
    let fill = "#60A5FA";
    let fontColor = "#60A5FA";
    if (criticalTaskIds.has(task.id)) {
      fill = "#F59E0B";
      fontColor = "#F59E0B";
    }
    if (milestone && day === task.endDay) {
      fill = "#DC2626";
      fontColor = "#DC2626";
      cell.format = {
        fill,
        font: { color: fontColor },
        borders: { preset: "all", style: "medium", color: "#7F1D1D" },
        horizontalAlignment: "center",
        verticalAlignment: "center",
        numberFormat: ";;;",
      };
    } else {
      cell.format = {
        fill,
        font: { color: fontColor },
        horizontalAlignment: "center",
        verticalAlignment: "center",
        numberFormat: ";;;",
      };
    }
  }
}

ganttSheet.getRange(`A${noteRow}:F${noteRow}`).merge();
ganttSheet.getRange(`A${noteRow}`).values = [[
  "说明：本甘特图使用第 1 天至第 28 天的相对排期，不绑定自然日。蓝色条表示普通计划任务，橙色条表示关键路径任务，红色节点表示“不完成则后续无法开展”的里程碑节点，浅灰底用于标识每周后两天的节奏参考。",
]];
ganttSheet.getRange(`A${noteRow}:F${noteRow}`).format = {
  fill: "#F8FAFC",
  font: { color: "#334155" },
  borders: { preset: "all", style: "thin", color: "#CBD5E1" },
  wrapText: true,
};

const milestoneLegendRows = milestoneNodes.map((item) => [
  "里程碑",
  item.id,
  `${item.label}：${item.description}`,
]);
ganttSheet.getRange(`A${noteRow + 1}:C${noteRow + 4}`).values = milestoneLegendRows;
ganttSheet.getRange(`A${noteRow + 1}:C${noteRow + 4}`).format = {
  borders: { preset: "all", style: "thin", color: "#CBD5E1" },
  wrapText: true,
};
ganttSheet.getRange(`A${noteRow + 1}:A${noteRow + 4}`).format.fill = "#FEE2E2";
ganttSheet.getRange(`B${noteRow + 1}:B${noteRow + 4}`).format = {
  fill: "#FECACA",
  font: { bold: true, color: "#991B1B" },
  horizontalAlignment: "center",
};

ganttSheet.getRange(`A${noteRow + 6}:C${noteRow + 8}`).values = [
  ["并行主线", "成员 A", "OpenBot App、人物检测、目标锁定、跟随参数调节"],
  ["并行主线", "成员 B", "MCU、通信、电机驱动、供电与急停执行"],
  ["并行主线", "成员 C", "结构改造、安全测试、视频记录与材料收口"],
];
ganttSheet.getRange(`A${noteRow + 6}:C${noteRow + 8}`).format = {
  borders: { preset: "all", style: "thin", color: "#CBD5E1" },
  wrapText: true,
};

ganttSheet.getRange("A:A").format.columnWidth = 10;
ganttSheet.getRange("B:B").format.columnWidth = 28;
ganttSheet.getRange("C:C").format.columnWidth = 18;
ganttSheet.getRange("D:D").format.columnWidth = 12;
ganttSheet.getRange("E:F").format.columnWidth = 9;
for (let day = 0; day < totalDays; day += 1) {
  const col = excelColName(7 + day);
  ganttSheet.getRange(`${col}:${col}`).format.columnWidth = 6.5;
}

ganttSheet.getRange(`A4:${lastDayCol}${baseRow + tasks.length - 1}`).format.autofitRows();
ganttSheet.getRange(`A${noteRow}:C${noteRow + 8}`).format.autofitRows();
ganttSheet.freezePanes.freezeRows(5);
ganttSheet.freezePanes.freezeColumns(6);

await fs.mkdir(ganttDir, { recursive: true });

const preview = await workbook.render({
  sheetName: "日甘特图",
  range: `A1:${lastDayCol}${noteRow + 8}`,
  scale: 0.9,
  format: "png",
});
await fs.writeFile(previewPath, new Uint8Array(await preview.arrayBuffer()));

const output = await SpreadsheetFile.exportXlsx(workbook);
await output.save(outputPath);

console.log(outputPath);
