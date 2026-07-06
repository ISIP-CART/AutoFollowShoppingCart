# AGENTS.md

## 项目概要

本仓库对应“基于 OpenBot 的自主跟随购物车原型”课程项目。首版目标是在 4 周集中实践内完成一个室内、低速、安全优先、可展示的购物车跟随闭环，而不是追求商业级全功能智能购物车。

项目的核心场景是：在室内超市或模拟超市场地中，让购物车跟随单个目标用户移动，并在目标丢失、急停、通信异常、前方障碍等情况下进入安全状态。

## 首版验收口径

首版应至少满足以下条件：

- OpenBot 基础链路跑通
- 手机端可手动遥控底盘
- 能完成人物检测、目标锁定与低速自主跟随
- 集成购物筐或载物平台
- 目标丢失时先取消前进，再执行短时原地搜寻，超时后发送 `STOP`
- 急停和通信异常停车可靠
- 有基础测试记录和稳定演示流程

不属于首版目标的内容：

- 完整 SLAM
- 复杂路径规划
- 高精地图
- 自动结账
- 真实超市长期部署
- 额外高性能计算平台驱动的复杂方案

## 架构硬约束

本项目首版必须保持以下主线，不应擅自漂移：

- `OpenBot + Android 手机 + MCU + 差速底盘`
- Android 手机作为上位机主脑，承担视觉感知、AI 推理、跟随决策和交互
- Arduino Nano 或 ESP32 作为下位机，承担串口解析、电机驱动和安全保护
- 不默认引入服务器、树莓派、SLAM 全栈、云端调度等额外复杂系统

## 目标丢失策略

当前确认的目标丢失处理策略如下：

1. 连续若干帧未检测到已锁定目标时，判定目标丢失。
2. 立即取消线速度输出，禁止继续向前跟随。
3. 进入 `LOST/SEARCH`，启动短时搜索计时。
4. 仅允许原地低速左右扫描，不允许继续前向位移。
5. 若重新找到目标，返回 `FOLLOW`。
6. 若搜索超时，或期间触发急停、障碍、通信异常，则发送 `STOP` 并进入安全停止状态。

这个策略属于“安全优先的有限重定位”，不是连续追踪搜索。

## 文档优先级与事实来源

当文档之间存在冲突时，优先参考：

1. `design/structure.md`
2. `design/doc/项目汇报超市自主跟随购物车.md`
3. `design/doc/2-9自主跟随机器人平台-深研院-张凯.pptx`
4. `design/doc/智能系统创新实践学生手册.pdf`

如果新信息与以上已确认内容冲突，不要直接覆盖，应先向用户确认。

## 协作约定

- 修改文档时，保持首版范围收敛，不要把选做功能写成必做功能。
- 遇到内容冲突时，先向用户报告冲突点并确认口径，再继续修改。
- 优先复用 OpenBot 现有架构和成熟模块，避免从零重造整套系统。
- 任何扩展到 SLAM、复杂规划、服务器或树莓派主脑的建议，都必须先说明为什么首版需要它。
- 当补充 README、设计文档或计划材料时，优先写“课程可交付原型”视角，而不是商业产品宣传视角。

## 关键文档索引

| 文档 | 路径 | 用途 |
|------|------|------|
| 系统设计主文档 | `design/structure.md` | 需求、架构、WBS、甘特图 |
| 工程决策记录 | `design/工程决策与实现策略记录.md` | 方案演化、硬件选型、范围收敛 |
| 下位机适配风险说明 | `design/OpenBot与四驱麦轮AT8236下位机适配风险说明.md` | 下位机核心参考：OpenBot 协议、AT8236 架构 |
| 上位机架构分析 | `design/OpenBot源码分析与上位机架构理解.md` | 上位机核心参考：源码架构、通信协议、调用链路 |
| 上位机总计划 | `design/自主跟随购物车上位机软件开发计划.md` | 上位机总方案收口：ReID、距离控制、障碍处理、阶段顺序 |
| 距离控制专项计划 | `design/上位机软件开发 Phase 2——修正跟随距离控制计划书.md` | 距离控制主线：初始化标定 + 图像伺服 |
| 障碍处理专项计划 | `design/障碍处理计划书.md` | 左 / 中 / 右可通行空间与跟随式局部避障 |
| ReID 深度调研报告 | `design/ReID-deep-research-report.md` | Android 端 ReID 部署路线、模型选择与风险分析 |
| **上位机开发进度记录** | `dev/OpenBot/android/cartfollow-devlog.md` | Human Cart Simulator 功能状态、待办项、状态机设计 |
| 产品参数汇总 | `design/doc/产品参数信息汇总报告.md` | 4 件采购商品的详细参数 |
| 采购清单 | `design/采购.md` | 商品链接与购买配置 |

补充说明：

- 上位机相关文档现在采用“总计划收口、专项计划展开”的结构。若距离控制计划、障碍处理计划和总计划书出现冲突，应优先回写 `design/自主跟随购物车上位机软件开发计划.md`，保持统一口径。
- 当前上位机主线已经明确为：
  - ReID 作为身份置信度辅助，而不是身份判决器；
  - 距离控制首版采用“初始化距离标定 + 图像伺服 + Distance State”；
  - 障碍处理从“固定前方风险停车”升级为“左 / 中 / 右可通行空间 + 跟随式局部避障”。

## ReID 研究工作区约定

`tools/reid_pc_test/` 现在作为团队共享的 ReID 研究工作区存在，供队友阅读脚本、调研文档和上游参考代码。

协作时必须注意：

- `tools/reid_pc_test/images/` 可能包含私人照片，禁止提交或公开上传；
- `tools/reid_pc_test/outputs/` 可能包含由私人照片导出的结果，禁止提交或公开上传；
- `tools/reid_pc_test/weights/` 默认不进入版本库；
- `tools/reid_pc_test/deep-person-reid/` 已按普通目录纳入主仓库，不再作为单独 submodule 使用。

## Git 提交与推送流程


本项目已经有固定的 Git 协作约定，详细版见 `CONTRIBUTING.md`。下面这份流程面向 GitHub 新手，默认目标是：**把你在主仓库中的更改提交并推送到一个新的分支**。

### 1. 先确认你现在在哪个仓库

本项目有两个层次：

- **主仓库**：当前这个仓库，用来放 `README.md`、`design/`、`AGENTS.md`、`CONTRIBUTING.md` 等课程文档，以及 `dev/OpenBot` 的子模块指针。
- **子仓库 `dev/OpenBot`**：团队的 OpenBot fork。如果你改的是 OpenBot Android / firmware 代码，提交流程和主仓库不一样。

如果你这次改的是文档、采购记录、设计分析、测试记录等内容，通常都在**主仓库**提交。

### 2. 日常开发不要直接在 `master` 上提交

开始工作前，先同步主分支，再从主分支切出你自己的新分支：

```bash
git switch master
git pull
git switch -c your-branch-name
```

分支命名建议：

- 文档：`docs/xxx`
- 采购：`docs/procurement-xxx`
- 测试：`test/xxx`
- Android：`android/xxx`
- 固件：`firmware/xxx`

示例：

```bash
git switch -c docs/update-motor-params
```

### 3. 在主仓库提交你改过的文件

先查看改动：

```bash
git status
```

如果你改的是主仓库里的文档，可以按需添加文件，例如：

```bash
git add AGENTS.md CONTRIBUTING.md README.md design/
```

然后提交：

```bash
git commit -m "Update project documentation"
```

提交说明建议写清楚这次改了什么，例如：

- `Update motor parameter documentation`
- `Add git workflow guide for beginners`
- `Revise procurement notes for encoder wiring`

### 4. 把新分支推送到 GitHub

第一次把这个新分支推到远端时，执行：

```bash
git push -u origin your-branch-name
```

示例：

```bash
git push -u origin docs/update-motor-params
```

其中：

- `origin` 是远端仓库名
- `your-branch-name` 是你刚创建的新分支名
- `-u` 的作用是把本地分支和远端分支关联起来，后面你再推送时可以直接用 `git push`

### 5. 以后继续在这个分支上更新

如果你已经推送过一次，后面继续修改后通常只需要：

```bash
git status
git add 你改过的文件
git commit -m "Describe your update"
git push
```

### 6. 如果你改的是 `dev/OpenBot`

如果你改的是 `dev/OpenBot/android` 或 `dev/OpenBot` 里的 firmware，不要只在主仓库提交。正确顺序是：

1. 先进入 `dev/OpenBot`
2. 在 `dev/OpenBot` 里提交并 push 代码
3. 回到主仓库
4. 再提交主仓库里更新后的 `dev/OpenBot` 子模块指针

示例流程：

```bash
cd dev/OpenBot
git switch shopping-cart-dev
git pull
git status
git add android/你改过的文件
git commit -m "Adapt OpenBot Android app for shopping cart"
git push
```

然后回到主仓库：

```bash
cd ..
git status
git add dev/OpenBot
git commit -m "Update OpenBot submodule"
git push
```

注意：**不要把 `dev/OpenBot` 的源码直接复制进主仓库提交**。主仓库只记录它当前指向的 commit。

### 7. 提交前自检

每次提交前至少检查这几件事：

- `git status` 里没有误加临时文件、构建产物、下载文件或本地工具配置
- 你当前不在 `master` 上做日常开发
- 如果改了 OpenBot 代码，是否已经先在 `dev/OpenBot` 提交
- 如果只改文档，是否只提交了主仓库相关文件

### 8. 你现在这类需求的推荐做法

如果你像现在这样，已经在主仓库改了文档，想**提交并推送到一个新的分支**，最标准的命令顺序就是：

```bash
git switch master
git pull
git switch -c docs/your-branch-name
git status
git add AGENTS.md README.md design/
git commit -m "Describe your change"
git push -u origin docs/your-branch-name
```

如果不确定自己该提交哪些文件，先运行 `git status`，确认后再 `git add`。

## 当前仓库状态提示

当前仓库以文档规划为主，代码与硬件实现尚未整理入库。后续若引入代码、固件、BOM、测试记录，应继续遵守上面的架构主线和冲突确认规则。
