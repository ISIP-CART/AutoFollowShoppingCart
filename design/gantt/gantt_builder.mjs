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
  { id: "T01", task: "需求收口与首版边界确认", owner: "成员 A / C", track: "项目规划", startDay: 1, endDay: 2, deliverable: "需求与验收口径", note: "明确 OpenBot + Android + ESP32/MCU + 底盘主线，不引入 SLAM/服务器主脑" },
  { id: "T02", task: "WBS、分工、BOM 初版", owner: "成员 C", track: "项目规划", startDay: 1, endDay: 3, deliverable: "WBS、分工、采购清单", note: "完成首版任务拆解和核心物资采购口径" },
  { id: "T03", task: "OpenBot App 环境与源码梳理", owner: "成员 A", track: "上位机", startDay: 1, endDay: 4, deliverable: "OpenBot 上位机分析", note: "确认 Android 手机作为上位机主脑" },
  { id: "T04", task: "下位机方案与 AT8236 风险分析", owner: "成员 B", track: "下位机", startDay: 1, endDay: 4, deliverable: "AT8236/ESP32 接口说明", note: "确认 UART/I2C、驱动板、编码器和安全保护风险" },
  { id: "T05", task: "底盘、电机、电池、驱动板采购", owner: "成员 B / C", track: "硬件", startDay: 1, endDay: 5, deliverable: "核心硬件到货/采购记录", note: "覆盖麦轮底盘、AT8236、ESP32、12V 电池" },
  { id: "T06", task: "方案 PPT 与第 1 周材料", owner: "成员 A / C", track: "交付", startDay: 3, endDay: 7, deliverable: "第 1 周周志与汇报材料", note: "形成第一轮课程交付材料" },
  { id: "T07", task: "Human Cart Simulator 主流程", owner: "成员 A", track: "上位机", startDay: 6, endDay: 10, deliverable: "目标初始化与状态机", note: "完成目标采集、截图确认、重识别、LOST/SEARCH/STOP 主链路" },
  { id: "T08", task: "距离控制图像伺服", owner: "成员 A", track: "上位机", startDay: 7, endDay: 10, deliverable: "DistanceState 距离控制", note: "初始化 setpoint + height/area/bottom_shift，UNKNOWN 时停车" },
  { id: "T09", task: "ReID PC 实验与 gallery 策略", owner: "成员 A", track: "上位机", startDay: 7, endDay: 11, deliverable: "ReID 复测脚本与结论", note: "osnet_x0_25 + diverse gallery(k=8)，ReID 只作身份置信辅助" },
  { id: "T10", task: "Android TFLite ReID 接入", owner: "成员 A", track: "上位机", startDay: 9, endDay: 12, deliverable: "Android ReID 可运行", note: "Human Cart Simulator 中 ReID 字段正常，仍不作为单帧 FOLLOW 判决" },
  { id: "T11", task: "诊断日志与 PC compare 闭环", owner: "成员 A", track: "测试", startDay: 10, endDay: 13, deliverable: "cartfollow_diagnostics", note: "记录 frame/identity/events/gallery/crops，支持新旧数据对比" },
  { id: "T12", task: "track/bbox gate 与 relock 策略", owner: "成员 A", track: "上位机", startDay: 11, endDay: 14, deliverable: "目标轨迹与身份信念层", note: "lockedTrack、suspectedTrack、ghost memory、空间支持门控已进入代码" },
  { id: "T13", task: "底盘、麦轮与 AT8236 接线", owner: "成员 B", track: "硬件", startDay: 8, endDay: 12, deliverable: "实体底盘接线完成", note: "四电机与 AT8236 完成连接，12V 电池搭载" },
  { id: "T14", task: "ESP32 串口与 WiFi 调控", owner: "成员 B", track: "下位机", startDay: 9, endDay: 13, deliverable: "CartESP32 WiFi 控制页", note: "支持前后、转向、横移、停止和 host 控制命令" },
  { id: "T15", task: "轮向标定与限速保护", owner: "成员 B / C", track: "测试", startDay: 12, endDay: 16, deliverable: "轮向/速度测试记录", note: "确认 M1-M4 对应关系、麦轮向量、低速限幅和松手停车" },
  { id: "T16", task: "通信超时与急停执行验证", owner: "成员 B", track: "安全", startDay: 13, endDay: 17, deliverable: "失联停车记录", note: "WiFi/host 指令超时、!S 停车和异常保护验证" },
  { id: "T17", task: "手机支架、线束与电池固定", owner: "成员 C / B", track: "结构", startDay: 11, endDay: 16, deliverable: "结构固定初版", note: "螺丝、铜柱、支架、转接线等补齐并安装" },
  { id: "T18", task: "购物筐/载物平台安装", owner: "成员 C", track: "结构", startDay: 14, endDay: 19, deliverable: "载物平台初版", note: "优先低重心、机械限位和轻载稳定演示" },
  { id: "T19", task: "Human Cart Simulator 手机复测", owner: "成员 A / C", track: "测试", startDay: 14, endDay: 17, deliverable: "四类场景复测数据", note: "目标返回、遮挡恢复、干扰者进入、干扰者穿越" },
  { id: "T20", task: "极低速真实底盘联调门槛", owner: "成员 A / B / C", track: "联调", startDay: 17, endDay: 20, deliverable: "联调准入结论", note: "只有上位机复测和下位机停车保护稳定后才开放真实前进" },
  { id: "T21", task: "目标丢失与 LOCAL_SEARCH 联调", owner: "成员 A / B", track: "安全", startDay: 18, endDay: 22, deliverable: "LOST/SEARCH/STOP 测试", note: "先 motion_stop，再短时原地搜索，失败 hard STOP" },
  { id: "T22", task: "基础障碍停车/等待策略", owner: "成员 A / C", track: "安全", startDay: 19, endDay: 23, deliverable: "障碍处理测试记录", note: "首版保守停车或等待，不做复杂 SLAM 绕障" },
  { id: "T23", task: "负载、转弯与稳定性测试", owner: "成员 C / B", track: "测试", startDay: 20, endDay: 24, deliverable: "1-3 kg 负载测试", note: "验证结构松动、重心、转弯、急停与供电稳定性" },
  { id: "T24", task: "系统联调与演示脚本固化", owner: "成员 A / B / C", track: "联调", startDay: 22, endDay: 25, deliverable: "稳定演示流程", note: "固化手动遥控、目标确认、跟随、丢失搜索、停车演示" },
  { id: "T25", task: "测试记录、视频与异常预案", owner: "成员 C / A / B", track: "交付", startDay: 23, endDay: 26, deliverable: "测试记录与演示视频", note: "保留分段演示素材和失败降级预案" },
  { id: "T26", task: "PPT、海报、报告收口", owner: "成员 C / A / B", track: "交付", startDay: 24, endDay: 27, deliverable: "最终材料", note: "A/B 提供技术内容，C 统一展示叙事" },
  { id: "T27", task: "最终彩排与参数冻结", owner: "成员 A / B / C", track: "交付", startDay: 27, endDay: 28, deliverable: "最终演示预案", note: "冻结保守参数、备份电池、备用线材和分段演示方案" },
];

const criticalTaskIds = new Set([
  "T03", "T04", "T05", "T07", "T10", "T12",
  "T13", "T14", "T15", "T16", "T17",
  "T19", "T20", "T21", "T24", "T27",
]);

const milestoneNodes = [
  {
    id: "M1",
    taskId: "T06",
    day: 7,
    label: "需求与基础方案收口",
    description: "第 1 周完成需求、WBS、BOM、OpenBot/下位机方案分析和阶段材料。",
  },
  {
    id: "M2",
    taskId: "T12",
    day: 14,
    label: "上位机策略闭环完成",
    description: "Human Cart Simulator、ReID、诊断日志和 track/bbox gate 形成可复盘闭环。",
  },
  {
    id: "M3",
    taskId: "T20",
    day: 20,
    label: "真实底盘联调准入",
    description: "ESP32/AT8236、轮向标定、通信超时停车、结构固定和上位机复测均达到低速联调门槛。",
  },
  {
    id: "M4",
    taskId: "T27",
    day: 28,
    label: "最终展示闭环完成",
    description: "完成最终彩排、参数冻结、材料收口和现场预案。",
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
