# 资料来源清单

本文档统一存放项目背景调研、技术分析和硬件采购的参照来源。

每条记录包含：标题、链接/文件路径、用途、可信度、备注。

---

## 项目内部文档

| 标题 | 链接/路径 | 用途 | 可信度 | 备注 |
| --- | --- | --- | --- | --- |
| 周二调研与初步设计讨论记录 | `design/structure.md` | 主设计文档，需求、架构、状态机、WBS、里程碑 | 高 | 项目核心参考 |
| 工程决策与实现策略记录 | `design/工程决策与实现策略记录.md` | 方案收敛、选型依据、内部决策记录 | 高 | 补充主文档口径 |
| 采购清单 | `design/采购.md` | 已采购硬件型号、规格和链接 | 高 | 含淘宝/天猫链接 |
| 项目汇报 | `design/doc/项目汇报超市自主跟随购物车.md` | 早期需求分析和初步方案 | 中 | 与 structure.md 有差异时以后者为准 |
| 课程 PPT | `design/doc/2-9自主跟随机器人平台-深研院-张凯.pptx` | 课程展示材料 | 中 | 未解析，后续需补充 |
| 学生手册 | `design/doc/智能系统创新实践学生手册.pdf` | 课程要求和评分标准 | 中 | PDF 格式，未解析 |

---

## OpenBot 平台

| 标题 | 链接/路径 | 用途 | 可信度 | 备注 |
| --- | --- | --- | --- | --- |
| OpenBot 官网 | https://www.openbot.org/ | 项目定位、核心思路（智能手机作为机器人大脑） | 高 | 官方 |
| OpenBot GitHub 主页 | https://github.com/ob-f/OpenBot | 架构概述、快速入门、版本发布 | 高 | 官方仓库 |
| OpenBot Android README | https://github.com/ob-f/OpenBot/blob/master/android/README.md | App 构建步骤、故障排除 | 高 | 官方 |
| OpenBot Robot App README | https://github.com/ob-f/OpenBot/blob/master/android/robot/README.md | App 功能、模型列表、基准测试、代码结构 | 高 | 官方 |
| OpenBot Firmware README | https://github.com/ob-f/OpenBot/blob/master/firmware/README.md | 通信协议、硬件配置宏、传感器支持、测试流程 | 高 | 官方 |
| OpenBot Body README | https://github.com/ob-f/OpenBot/blob/master/body/README.md | 车体方案概览 | 高 | 官方 |
| OpenBot Controller README | https://github.com/ob-f/OpenBot/blob/master/controller/README.md | 控制方式汇总 | 高 | 官方 |
| OpenBot 论文 | https://arxiv.org/abs/2008.10631 | 学术背景和系统验证 | 高 | IEEE 论文 |
| OpenBot 固件源码 | `dev/OpenBot/firmware/openbot/openbot.ino` | 通信协议实现、安全机制、电机控制、硬件配置宏 | 高 | 直接源码 |
| OpenBot Releases | https://github.com/ob-f/OpenBot/releases | 版本历史和重要变更 | 高 | 官方 |

---

## ESP32 / MCU

| 标题 | 链接/路径 | 用途 | 可信度 | 备注 |
| --- | --- | --- | --- | --- |
| ESP32 技术规格 | https://www.espressif.com/en/products/socs/esp32 | ESP32 硬件参数和性能参考 | 高 | 厂商官方 |
| ESP-IDF 编程指南 | https://docs.espressif.com/projects/esp-idf/en/latest/esp32/ | ESP32 开发框架和芯片能力 | 高 | 厂商官方 |

---

## 竞品与行业背景

| 标题 | 链接/路径 | 用途 | 可信度 | 备注 |
| --- | --- | --- | --- | --- |
| Piaggio Gita 官网 | https://mygita.com/ | 载物跟随机器人参照 | 高 | 已确认可访问 |
| Airwheel 官网 | https://www.airwheel.net/ | 跟随行李箱参照 | 高 | 已确认可访问 |
| WHO Ageing and health | https://www.who.int/news-room/fact-sheets/detail/ageing-and-health | 全球老龄化趋势和公共空间辅助设备意义 | 高 | WHO 官方 |
| ISO 13482:2014 | https://www.iso.org/standard/53820.html | 个人护理机器人安全要求标准摘要 | 高 | ISO 标准（摘要公开） |
| Caper Cart 商业页面 | https://www.caper.ai/ | 商业智能购物车背景对照 | 低 | **访问失败**（返回 404），信息来自科技媒体报道交叉验证 |
| Amazon Dash Cart 新闻页 | 多篇科技媒体报道 | 商业智能购物车背景对照 | 中 | **部分页面 404**，信息来自交叉验证 |
| ForwardX Ovis | 多篇科技产品评测 | 视觉跟随行李箱参照 | 中 | 官网访问受限，信息来自交叉验证 |
| Travelmate Robotics | 众筹页面 / 科技媒体报道 | 全向跟随行李箱参照 | 中 | 众筹产品，信息来自交叉验证 |
| Burro (原 Auro) | 多篇科技媒体报道 | 农业跟随运输机器人参照 | 中 | 行业报道 |

---

## 硬件采购

| 标题 | 链接/路径 | 用途 | 可信度 | 备注 |
| --- | --- | --- | --- | --- |
| 305 系列底盘 | 淘宝 804493296943 | 底盘规格和尺寸 | 中 | 商家资料，实际参数以到手实物为准 |
| ESP32 WROOM-32E 开发板（备用） | 淘宝 672885629326, sku 5020289247705 | ESP32 开发板 + 拓展盘 | 中 | 已采购 |
| ESP32 WROOM-32E 开发板（主用） | 淘宝 672885629326, sku TYPEC-USB-32E | ESP32 开发板 + 已焊排针 | 中 | 已采购 |
| 12V 锂电池组 9600mAh | 天猫 675985006603, sku 4860353077903 | 电池规格 | 中 | 已采购 |
| 12V 锂电池充电器 2A | 天猫 675985006603, sku 4860353077904 | 充电器规格 | 中 | 已采购 |
| AT8236 四路编码器电机驱动模块 | 天猫 895192929302, sku 5913351087734 | 驱动板规格和接口 | 中 | 已采购 |
| 杜邦线（母对母，21cm，40 根） | 天猫 14466195609 | 装配接线与联调辅材 | 中 | 已采购 |
| 手机支架 | 天猫 1030199333857 | 手机固定与车体集成 | 中 | 已采购 |
| 麦克纳姆轮夹紧式联轴器 6mm | 淘宝 1040186559237 | 电机与车轮连接件 | 中 | 已采购 |
| 铜单通六角固定柱 M3x60+6 | 京东 100260800118 | 双层板连接与抬高结构 | 中 | 已采购 |
| 十字薄头螺丝 M3x8x5 | 京东 100234999133 | 结构装配紧固件 | 中 | 已采购 |
| 亚博智能底盘（参考对比） | `design/doc/亚博智能 轮式电动小车底盘铝合金四驱TI杯...pdf` | 备选底盘参考 | 中 | 未采购，作为对比 |
| R3X 系列底盘（参考对比） | `design/doc/R3X系列智能小车底盘阿克曼差速四驱麦轮...pdf` | 备选底盘参考 | 中 | 未采购，作为对比 |

---

## 人物检测与跟随

| 标题 | 链接/路径 | 用途 | 可信度 | 备注 |
| --- | --- | --- | --- | --- |
| OpenBot Robot App README | https://github.com/ob-f/OpenBot/blob/master/android/robot/README.md | 模型列表、Object Tracking 功能说明、模型基准测试数据 | 高 | 官方文档 |
| SORT 论文 (Bewley et al., 2016) | https://arxiv.org/abs/1602.00763 | 简单在线实时跟踪算法原理（卡尔曼滤波 + 匈牙利匹配） | 高 | 学术论文 |
| TensorFlow Lite 模型 | https://www.tensorflow.org/lite/models | TFLite 预训练检测模型列表 | 高 | 官方 |
| OpenBot Detector.java | `dev/OpenBot/android/robot/src/main/java/org/openbot/tflite/Detector.java` | 检测模型加载和推理实现 | 高 | 直接源码 |
| 仓库 `design/background/04-person-detection-and-following.md` | 仓库本地 | 本项目人物检测与跟随控制的完整方案 | 高 | 已基于 OpenBot 文档和学术资料撰写 |

---

## 购物场景与需求

| 标题 | 链接/路径 | 用途 | 可信度 | 备注 |
| --- | --- | --- | --- | --- |
| WHO Ageing and health | https://www.who.int/news-room/fact-sheets/detail/ageing-and-health | 老龄化趋势、公共空间辅助设备需求 | 高 | WHO 官方 |
| ISO 13482:2014 | https://www.iso.org/standard/53820.html | 个人护理机器人安全标准（参考，不作合规要求） | 高 | ISO 标准摘要 |
| 仓库 `design/background/06-shopping-scenario-and-requirements.md` | 仓库本地 | 购物场景分析、演示设计、需求映射 | 高 | 已基于项目内部文档和行业知识撰写 |
| 零售空间设计规范（行业通则） | 行业知识 | 通道宽度、照明标准、地面材料等行业典型值 | 中 | 行业经验参考，非特定文件

---

## 备注

- 可信度分为：**高**（官方文档/直接源码/标准文献）、**中**（商家资料/交叉验证报道/行业信息）、**低**（访问失败/仅有摘要）。
- 标记为"交叉验证"的信息来自多项独立来源的综合，部分产品规格可能随产品迭代而变化，建议后续直接访问最新官网页面确认。
- 淘宝/天猫链接包含 session 信息，可能在数周后失效。建议保存购买记录中的商家名称和商品型号作为备用。
