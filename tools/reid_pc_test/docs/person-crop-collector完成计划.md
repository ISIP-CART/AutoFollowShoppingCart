# Person Crop Collector 完成计划

> 2026-07-07 补充：现有 `PersonCropCollector` 继续保持轻量，主要负责 ReID crop 数据采集。为了做真实时序状态机回放，已新增相邻的 `PersonSequenceCollector / SEQUENCE mode`，专门记录连续帧事实数据。

> 2026-07-07 最新状态：`PersonSequenceCollector` 已在 Android 端实现、构建通过并完成真机安装；已采集 `yrc_seq_20260707_140056` 与 `yrc2_seq_20260707_152237` 两条 sequence，PC 端 `simulate_sequence_session_replay_v1.py` 已可读取 `frame_log.csv / detections.csv / events.csv / crops/` 进行状态机回放。

> 项目：自主跟随购物车原型  
> 模块：OpenBot Android 上位机 / ReID 数据采集工具  
> 建议分支：`feature/person-crop-collector`  
> 建议入口名称：`Cart Crop Collector` 或 `Person Crop Collector`  
> 目标阶段：ReID Android 部署前的真实 person bbox crop 数据采集

---

## 1. 背景与开发动机

当前 ReID PC 端测试已经说明：

1. 人物姿态、相机视角、正面/侧面/背面、全身/局部等因素会显著影响 ReID embedding。
2. 人工裁剪图片会引入不确定因素，可能使 PC 端测试结果和 Android 真实输入不一致。
3. 后续 ReID 模型真正接收的输入不是人工裁剪图，而是 OpenBot 检测模型输出的 `person bounding box crop`。

因此，在继续做目标图库、target-follow 模拟和 Android ReID 部署之前，需要先完成一个独立的数据采集模式：

```text
手机摄像头画面
  ↓
OpenBot Detector 人物检测
  ↓
person bbox
  ↓
按 bbox 自动裁剪 crop
  ↓
保存 crop.jpg + metadata.csv
  ↓
导出到 PC
  ↓
继续做 OSNet / Torchreid 测试
```

这个模块的核心价值是：

> 让 ReID 评估数据从“人工裁剪图片”升级为“OpenBot Android 实际检测裁剪图片”，从而更真实地评估后续 Android 端 ReID 可行性。

---

## 2. 模块定位

`Person Crop Collector` 应作为一个独立工具入口，与 `Human Cart Simulator` 平级。

它不是跟随功能，也不直接接入控制闭环。它只负责数据采集。

### 2.1 与 Human Cart Simulator 的区别

| 项目 | Human Cart Simulator | Person Crop Collector |
|---|---|---|
| 主要目的 | 验证目标初始化、匹配、跟随指令、距离状态 | 采集真实 person bbox crop 数据 |
| 是否控制小车 | 否，仅输出人类可读指令 | 否 |
| 是否使用状态机 | 是，使用 `FollowStateMachine` | 否，首版不需要复杂状态机 |
| 是否保存图片 | 当前主要保存确认快照 | 连续保存检测框 crop |
| 是否服务 ReID | 间接服务 | 直接服务 ReID 数据集构建 |
| 是否多人跟随 | 否 | 首版只采单人，后续可扩展多人 |

### 2.2 首版边界

首版只做：

```text
OpenBot 摄像头预览
人物检测框显示
单人 person bbox 自动裁剪
按时间间隔保存 crop
写 metadata.csv
写 session_info.json
导出到 PC 复测
```

首版不做：

```text
Android 端 ReID 推理
多人身份自动标注
动态 gallery 更新
云端上传
视频录制
控制小车运动
接入 FollowStateMachine
复杂数据集管理界面
```

---

## 3. 预期使用流程

### 3.1 手机端采集流程

1. 打开 OpenBot App。
2. 在主菜单选择 `Cart Crop Collector`。
3. 输入当前被采集人的 ID，例如：`ysy`、`rxy`、`chy`。
4. 设置采集参数，首版可使用默认值。
5. 点击 `Start Session`。
6. 一名同学手持手机模拟购物车视角，另一名同学在前方自然行走或做动作。
7. 手机每隔一定时间检测并保存 person crop。
8. 点击 `Stop Session` 结束。
9. 使用 Android Studio Device Explorer 或 `adb pull` 导出数据。
10. 在 PC 端放入 `tools/reid_pc_test/images_openbot/` 继续测试。

### 3.2 推荐采集动作

单次 session 建议持续 30-60 秒，目标人物自然完成：

```text
直行远离
靠近手机
左转 / 右转
短暂停下
侧身
背对手机行走
轻微弯腰 / 蹲下
短时靠近画面边缘
被检测框裁成局部
```

注意：不建议让用户明显“转圈拍照”，因为真实购物车项目应尽量减少用户尴尬和额外交互。

---

## 4. 入口集成计划

参考 `Human Cart Simulator` 的入口集成方式，新增独立主菜单入口。

### 4.1 需要修改的文件

| 文件 | 修改内容 |
|---|---|
| `FeatureList.java` | 新增 `CART_CROP_COLLECTOR` 功能项 |
| `MainFragment.java` | 添加点击入口和导航逻辑 |
| `nav_graph.xml` | 注册 `personCropCollectorFragment` |
| `strings.xml` | 新增页面名称与按钮文案 |
| `fragment_person_crop_collector.xml` | 新建布局文件 |
| `PersonCropCollectorFragment.java` | 新建主 Fragment |

### 4.2 建议入口文案

```xml
<string name="cart_crop_collector">Cart Crop Collector</string>
<string name="cart_crop_collector_start">Start Session</string>
<string name="cart_crop_collector_stop">Stop Session</string>
<string name="cart_crop_collector_idle">Ready to collect person crops</string>
```

---

## 5. UI 设计

### 5.1 页面结构

建议页面保持简单，以可靠采集为主。

```text
FrameLayout
├─ Camera Preview
├─ OverlayView：绘制 person bbox
└─ Bottom Panel
   ├─ TextView：状态信息
   ├─ EditText：Person ID
   ├─ Button：Start Session
   ├─ Button：Stop Session
   ├─ TextView：Saved / Skipped / Persons / FPS
   ├─ Button：Interval -
   ├─ TextView：Interval 当前值
   ├─ Button：Interval +
   ├─ Switch：Single Person Only
   └─ ImageView：最近保存 crop 预览，可选
```

### 5.2 默认参数

| 参数 | 默认值 | 说明 |
|---|---:|---|
| `captureIntervalMs` | 500 ms | 每 0.5 秒最多保存一张 |
| `minConfidence` | 0.50 | 低于该置信度不保存 |
| `singlePersonOnly` | true | 只在检测到 1 个人时保存 |
| `bboxPaddingRatio` | 0.08 | bbox 外扩 8%，避免裁剪过紧 |
| `maxCropsPerSession` | 120 | 防止一次采集过多 |
| `jpegQuality` | 95 | 保留较高图像质量 |

---

## 6. 数据保存设计

### 6.1 保存目录

建议保存到 App 专属外部目录：

```java
getExternalFilesDir(Environment.DIRECTORY_PICTURES)
```

目录结构：

```text
/sdcard/Android/data/org.openbot/files/Pictures/cartfollow_crops/
└─ ysy_20260706_153012/
   ├─ crops/
   │  ├─ 000001_person0_conf0.87.jpg
   │  ├─ 000002_person0_conf0.91.jpg
   │  └─ ...
   ├─ metadata.csv
   └─ session_info.json
```

### 6.2 session 命名规则

```text
<person_id>_<yyyyMMdd_HHmmss>
```

示例：

```text
ysy_20260706_153012
rxy_20260706_154230
```

---

## 7. metadata.csv 设计

`metadata.csv` 每保存一张 crop 追加一行。

推荐字段：

```csv
session_id,person_id,frame_id,crop_id,timestamp_ms,crop_path,num_persons,person_index,confidence,bbox_left,bbox_top,bbox_right,bbox_bottom,bbox_width,bbox_height,image_width,image_height,edge_touch,save_reason
```

字段说明：

| 字段 | 说明 |
|---|---|
| `session_id` | 当前采集 session ID |
| `person_id` | 用户输入的人物 ID |
| `frame_id` | 当前帧编号 |
| `crop_id` | 当前 crop 编号 |
| `timestamp_ms` | 保存时间戳 |
| `crop_path` | crop 相对路径 |
| `num_persons` | 当前帧检测到的人数 |
| `person_index` | 当前保存的是第几个检测人框 |
| `confidence` | person 检测置信度 |
| `bbox_left/top/right/bottom` | 原始 bbox 坐标 |
| `bbox_width/height` | bbox 尺寸 |
| `image_width/height` | bbox 所属 bitmap 尺寸 |
| `edge_touch` | crop 是否接触画面边界 |
| `save_reason` | 保存原因，例如 `single_person_valid` |

### 7.1 session_info.json

建议额外保存一份 session 配置：

```json
{
  "session_id": "ysy_20260706_153012",
  "person_id": "ysy",
  "created_at": "2026-07-06 15:30:12",
  "capture_interval_ms": 500,
  "min_confidence": 0.5,
  "single_person_only": true,
  "bbox_padding_ratio": 0.08,
  "max_crops": 120,
  "jpeg_quality": 95,
  "app_mode": "PersonCropCollector"
}
```

---

## 8. 核心类设计

### 8.1 `PersonCropCollectorFragment`

主 Fragment，负责 UI、摄像头帧处理、检测结果显示和采集控制。

职责：

```text
加载摄像头预览
调用 OpenBot Detector
筛选 person Recognition
绘制检测框
管理 Start / Stop Session
调用 PersonCropSaver 保存 crop
更新 UI 状态
```

可参考 `HumanCartSimulatorFragment`，但首版应删除跟随相关复杂逻辑：

```text
不接 FollowStateMachine
不接 TargetMatcher
不接 ControlGenerator
不接 DistanceEstimator
不做目标确认 / 倒计时
```

### 8.2 `PersonCropCaptureConfig`

保存采集参数。

```java
public class PersonCropCaptureConfig {
    public String personId;
    public long intervalMs = 500;
    public float minConfidence = 0.5f;
    public boolean singlePersonOnly = true;
    public float paddingRatio = 0.08f;
    public int maxCrops = 120;
    public int jpegQuality = 95;
}
```

### 8.3 `PersonCropSession`

管理一次采集 session。

```java
public class PersonCropSession {
    public final String sessionId;
    public final String personId;
    public final File sessionDir;
    public final File cropsDir;
    public final File metadataCsv;
    public int savedCount;
    public int skippedCount;
}
```

职责：

```text
创建 session 文件夹
创建 crops 子文件夹
初始化 metadata.csv
写 session_info.json
维护 saved / skipped 计数
```

### 8.4 `PersonCropSaver`

负责裁剪与异步保存。

职责：

```text
根据 Recognition bbox 裁剪 Bitmap
给 bbox 添加 padding
clamp 到图像边界
JPEG 压缩保存
追加写 metadata.csv
异步执行，避免阻塞推理和 UI
```

建议使用：

```java
ExecutorService saveExecutor = Executors.newSingleThreadExecutor();
```

---

## 9. 关键流程伪代码

### 9.1 processFrame 逻辑

```java
void processFrame(Bitmap bitmap, List<Recognition> recognitions) {
    List<Recognition> persons = filterPersons(recognitions, config.minConfidence);

    overlayView.setPersons(persons);
    updateDetectionStatus(persons);

    if (!captureEnabled || currentSession == null) {
        return;
    }

    long now = System.currentTimeMillis();

    if (now - lastSaveTimeMs < config.intervalMs) {
        return;
    }

    if (currentSession.savedCount >= config.maxCrops) {
        stopCapture("Reached max crops");
        return;
    }

    if (config.singlePersonOnly && persons.size() != 1) {
        currentSession.skippedCount++;
        updateStatus("Skipped: persons=" + persons.size());
        return;
    }

    if (persons.isEmpty()) {
        currentSession.skippedCount++;
        updateStatus("Skipped: no person");
        return;
    }

    if (config.singlePersonOnly) {
        saver.saveCropAsync(bitmap, persons.get(0), currentSession, config);
    } else {
        for (int i = 0; i < persons.size(); i++) {
            saver.saveCropAsync(bitmap, persons.get(i), currentSession, config);
        }
    }

    lastSaveTimeMs = now;
}
```

### 9.2 裁剪逻辑

```java
RectF bbox = recognition.getLocation();

float padX = bbox.width() * config.paddingRatio;
float padY = bbox.height() * config.paddingRatio;

int left = clamp((int) (bbox.left - padX), 0, bitmap.getWidth() - 1);
int top = clamp((int) (bbox.top - padY), 0, bitmap.getHeight() - 1);
int right = clamp((int) (bbox.right + padX), left + 1, bitmap.getWidth());
int bottom = clamp((int) (bbox.bottom + padY), top + 1, bitmap.getHeight());

Bitmap crop = Bitmap.createBitmap(bitmap, left, top, right - left, bottom - top);
```

---

## 10. 坐标系注意事项

裁剪时最容易出错的是坐标系。

必须保证：

```text
Recognition.getLocation() 的 bbox 坐标属于哪张 Bitmap，
就必须从同一张 Bitmap 上裁剪。
```

不要从屏幕 View 上裁剪，也不要从已经缩放/旋转过但坐标未同步的 bitmap 上裁剪。

建议原则：

```text
Human Cart Simulator 中检测和 overlay 使用的 bitmap / bbox 坐标如何对应，
Person Crop Collector 就复用同样的数据流。
```

如果发现 crop 错位，优先检查：

```text
bitmap 是否旋转
bbox 是否归一化
bbox 是否已经映射到屏幕坐标
preview 尺寸和 detector 输入尺寸是否不同
```

---

## 11. 开发分支与 Commit 计划

建议从当前稳定分支拉出新分支：

```powershell
cd E:\THU\2026Summer\AutoFollowShoppingCart\dev\OpenBot

git status
git branch -vv
git switch -c feature/person-crop-collector
```

如果当前有未提交修改，应先提交或 stash。

### Commit 1：入口骨架

```text
feat(crop): add Person Crop Collector entry
```

内容：

```text
FeatureList.java
MainFragment.java
nav_graph.xml
strings.xml
fragment_person_crop_collector.xml
PersonCropCollectorFragment.java 空壳
```

验收：

```text
主菜单出现入口
点击能进入页面
返回不崩溃
```

### Commit 2：人物检测与 Overlay

```text
feat(crop): show person detections in crop collector
```

内容：

```text
复用 OpenBot Detector
筛选 classType="person"
绘制 person bbox
显示 persons / fps / confidence
```

验收：

```text
打开页面能看到实时人物检测框
不保存文件
UI 不明显卡顿
```

### Commit 3：Session 与 crop 保存

```text
feat(crop): save detected person crops with metadata
```

内容：

```text
PersonCropCaptureConfig
PersonCropSession
PersonCropSaver
Start / Stop Session
保存 crops/
写 metadata.csv
写 session_info.json
```

验收：

```text
检测到单人时每 500 ms 保存一张 crop
metadata.csv 与图片数量一致
session 结束后文件可导出
```

### Commit 4：调试体验完善

```text
feat(crop): add capture controls and status panel
```

内容：

```text
interval +/-
single person only switch
max crop 限制
last crop preview
skipped reason 显示
session path 显示
```

验收：

```text
可以稳定采集 30-60 秒
能看见 saved / skipped / persons / fps
能定位 session 保存路径
```

---

## 12. Android 端验收标准

### 12.1 单 session 验收

测试方式：

```text
测试者 A 手持手机模拟购物车视角；
测试者 B 在前方自然行走和做动作；
采集 30-60 秒。
```

通过标准：

```text
session 文件夹成功生成
crops 文件夹有图片
metadata.csv 行数与图片数一致
图片确实是 person bbox crop，而不是整帧
bbox 没有明显坐标错位
保存过程 UI 不崩溃
保存过程 FPS 不明显崩溃
Start / Stop 可重复使用
```

### 12.2 数据质量检查

人工抽查 20 张 crop：

```text
人物主体是否完整
是否裁剪过紧
是否存在大量背景
是否有明显错位
是否有局部/贴边样本
图片方向是否正确
```

若裁剪过紧：增大 `paddingRatio` 到 `0.10` 或 `0.12`。  
若背景过多：减小 `paddingRatio` 或提高检测置信度。  
若错位：优先排查 bitmap 与 bbox 坐标系。

---

## 13. PC 端复测计划

导出命令示例：

```powershell
adb pull /sdcard/Android/data/org.openbot/files/Pictures/cartfollow_crops E:\THU\2026Summer\AutoFollowShoppingCart\tools\reid_pc_test\android_crops
```

整理目录：

```text
tools/reid_pc_test/images_openbot/
├─ ysy/
├─ rxy/
├─ chy/
└─ zhz/
```

复测命令：

```powershell
python compare_reid_folders_v2.py ^
  --images images_openbot ^
  --per-id 16 ^
  --model osnet_x0_25 ^
  --weight weights\osnet_x0_25_market1501.pth ^
  --output-prefix openbot_x025_bal16
```

Gallery-Probe 测试：

```powershell
python simulate_gallery_probe_v2.py ^
  --images images_openbot ^
  --per-id 16 ^
  --model osnet_x0_25 ^
  --weight weights\osnet_x0_25_market1501.pth ^
  --gallery-k 5 ^
  --gallery-strategy diverse ^
  --output-prefix openbot_x025_g5_diverse
```

重点比较：

| 指标 | 意义 |
|---|---|
| `same_mean - diff_mean` | 同人与异人整体可分性 |
| `Top-1` | 最近邻身份是否稳定 |
| `gallery-probe mean_acc` | 多样性 gallery 是否有效 |
| `accepted_acc@margin>=0.03` | 高置信识别准确率 |
| `accepted_rate@margin>=0.03` | 系统敢于确认的比例 |

---

## 14. 风险与应对

| 风险 | 表现 | 应对 |
|---|---|---|
| bbox 坐标错位 | crop 不是人物，或只裁到背景 | 统一 bitmap 与 bbox 坐标系；复用 Simulator 数据流 |
| 裁剪过紧 | 身体被切掉，影响 ReID | padding 从 0.08 提高到 0.10/0.12 |
| 背景过多 | ReID 受背景干扰 | 调低 padding；只保存较高置信度 bbox |
| 保存阻塞 UI | 画面卡顿、FPS 下降 | 用单线程 Executor 异步保存 |
| 混入路人 | 单目标数据不干净 | 默认开启 `singlePersonOnly=true` |
| 图片数量过多 | 手机存储压力 | 设置 `maxCrops`，默认 120 |
| Android 权限复杂 | 文件不可导出 | 保存到 App 专属外部目录，用 Device Explorer 或 adb pull |

---

## 15. 完成定义 Definition of Done

`Person Crop Collector` 首版完成需要满足：

```text
主菜单独立入口可进入
可实时显示 person 检测框
可输入 person_id 并创建 session
可按间隔保存真实 person bbox crop
可写 metadata.csv 与 session_info.json
可显示 saved / skipped / persons / fps
可稳定采集至少 60 秒
可通过 adb pull 导出数据
导出的数据可直接用于 PC 端 ReID 测试
```

完成后，本模块将成为 ReID 后续研发的数据基础。

---

## 16. 后续扩展方向

首版完成后，可继续扩展：

```text
多 session 数据合并工具
自动剔除模糊 crop
自动按 edge_touch / bbox_size 分组
保存整帧缩略图用于定位问题
多人模式下保存所有 person bbox
与 ReID embedding 提取器联动
初始化阶段自动 diverse gallery selection
高置信 FOLLOW 状态下 dynamic gallery 更新
```

但这些都不应阻塞首版完成。

---

## 17. PersonSequenceCollector / SEQUENCE mode 规划

### 17.1 为什么不直接加重 PersonCropCollector

`PersonCropCollector` 当前已经能完成 ReID 早期最需要的数据：干净的 person crop、bbox 坐标、置信度和 session metadata。它适合回答：

```text
这个人的 crop 能不能被 ReID 特征区分？
gallery 选几张比较稳？
best_score / margin / bbox gate 的阈值大概在哪里？
```

但它不适合直接回答状态机问题，因为状态机还需要知道：

```text
某一帧没有检测到人；
某一帧检测到了多个人；
目标离开后过了多少帧又回来；
干扰者是什么时候进入画面；
bbox 是否连续移动，而不是随机抽样跳变。
```

因此下一阶段建议保留 `PersonCropCollector`，再新增一个相邻模块：

```text
PersonSequenceCollector
```

它的定位是“时序事实记录器”，不是跟随状态机，也不是 Android ReID 判决器。

### 17.2 采集模式

建议新增采集模式枚举：

```java
enum CollectorMode {
    OFF,
    CROP_ONLY,
    SEQUENCE
}
```

含义：

| 模式 | 行为 |
|---|---|
| `OFF` | 不采集数据。 |
| `CROP_ONLY` | 沿用现有 `PersonCropCollector`，只保存有效 crop 和 `metadata.csv`。 |
| `SEQUENCE` | 保存连续帧日志、检测框日志、可选 crop、可选 overlay 和人工事件。 |

### 17.3 SEQUENCE 目录结构

建议保存到：

```text
/sdcard/Android/data/org.openbot/files/Pictures/cartfollow_sequences/
└── ysy_seq_20260707_153012/
    ├── frame_log.csv
    ├── detections.csv
    ├── events.csv
    ├── session_info.json
    ├── crops/
    └── overlays/
```

其中 `crops/` 和 `overlays/` 可以按开关启用，不应成为首轮必须项。

### 17.4 frame_log.csv

`frame_log.csv` 每个采样帧一行，即使没有检测到任何人也要写入。

推荐字段：

```csv
session_id,frame_id,timestamp_ms,elapsed_ms,image_width,image_height,num_persons,raw_frame_path,overlay_path,event_tag,note
```

字段说明：

| 字段 | 说明 |
|---|---|
| `session_id` | 当前 sequence session。 |
| `frame_id` | OpenBot/Camera 当前帧编号。 |
| `timestamp_ms` | 当前帧时间戳。 |
| `elapsed_ms` | 距离 session 开始的毫秒数。 |
| `image_width/image_height` | detector 所使用的图像尺寸。 |
| `num_persons` | 当前帧检测到的人数，可以为 0。 |
| `raw_frame_path` | 可选整帧路径，首轮可为空。 |
| `overlay_path` | 可选可视化叠加图路径。 |
| `event_tag` | 可选人工事件标签。 |
| `note` | 可选人工备注。 |

### 17.5 detections.csv

`detections.csv` 每个检测框一行。若某帧 `num_persons=0`，则 `frame_log.csv` 有记录，但 `detections.csv` 不写 detection 行。

推荐字段：

```csv
session_id,frame_id,det_id,timestamp_ms,confidence,bbox_left,bbox_top,bbox_right,bbox_bottom,bbox_width,bbox_height,bbox_area_ratio,center_x,center_y,edge_touch,crop_path
```

首轮不要求 Android 端判断哪个 detection 是目标，只记录 detector 事实。目标身份、状态机状态和是否错误恢复，都交给 PC 端 replay 脚本推导。

### 17.6 events.csv

`events.csv` 是可选人工事件记录。建议支持以下事件名：

```text
target_visible
target_left
target_return
occlusion_start
occlusion_end
distractor_enter
distractor_leave
manual_note
```

推荐字段：

```csv
session_id,timestamp_ms,frame_id,event_type,note
```

它的作用不是训练模型，而是让 PC 端回放时知道“这一段为什么目标消失/为什么路人进入”。

### 17.7 session_info.json

建议增加以下信息：

```json
{
  "session_id": "ysy_seq_20260707_153012",
  "collector": "PersonSequenceCollector",
  "mode": "SEQUENCE",
  "person_id": "ysy",
  "frame_log_interval_ms": 200,
  "crop_interval_ms": 500,
  "overlay_interval_ms": 1000,
  "save_crops": true,
  "save_overlays": false,
  "detector": "OpenBot person detector"
}
```

实际第二轮采集 `yrc2_seq_20260707_152237` 中，界面将 crop interval 调整为 300 ms，因此 `session_info.json` 记录为：

```json
{
  "frame_log_interval_ms": 200,
  "crop_interval_ms": 300,
  "overlay_interval_ms": 1000,
  "save_crops": true,
  "save_overlays": false
}
```

这说明 SEQUENCE 模式中的采样间隔应视为“可调采集参数”，文档中的默认值不是固定实验条件。

### 17.8 默认采样频率

首轮推荐：

| 数据 | 默认频率 | 说明 |
|---|---:|---|
| `frame_log.csv` | 5 Hz | 足够做状态机时间顺序回放。 |
| `detections.csv` | 5 Hz | 与 frame log 对齐。 |
| `crops/` | 2 Hz | 控制存储量，同时保留 ReID probe。 |
| `overlays/` | 1 Hz | 仅用于人工排查，可关闭。 |

实测建议：

```text
首轮排查可用 cropIntervalMs=500；
需要更密集 ReID replay 时可调到 300；
若手机发热、卡顿或存储压力明显，再调回 500。
```

### 17.9 Definition of Done

`PersonSequenceCollector / SEQUENCE mode` 首轮完成标准：

```text
可从 App 进入 SEQUENCE 采集模式；
可创建 cartfollow_sequences/<session_id>/；
无人帧会写入 frame_log.csv；
多人帧会在 detections.csv 写多行；
不写 FOLLOW / LOST / REACQUIRE / STOP 状态标签；
可选保存 crop 和 overlay；
60 秒采集无明显 UI 卡顿；
adb pull 后 PC 端可读取 CSV；
PC chronological replay 可基于导出的 sequence 数据继续扩展。
```

当前完成情况：

| 项目 | 状态 |
|---|---|
| App 入口 | 已完成，主菜单存在 `Person Sequence Collector`。 |
| 无人帧记录 | 已验证，`frame_log.csv` 中存在 `num_persons=0`。 |
| 多人帧记录 | 已验证，第二条 sequence 中存在 `num_persons>=2` 帧。 |
| 事件按钮 | 已验证，`target_left/return`、`distractor_enter/leave`、`occlusion_start/end` 可写入 `events.csv`。 |
| crop 保存 | 已验证，第二条 sequence 147 个可用 crop。 |
| PC replay | 已验证，`simulate_sequence_session_replay_v1.py` 可读取并输出 summary / transitions / diagnostic_summary。 |
| 状态标签边界 | 已满足，采集器只记录事实，不写 `FOLLOW / LOST / REACQUIRE / STOP`。 |

### 17.10 对 PC 回放的新要求

第二条 sequence 暴露出一个重要测试口径：真实控制循环不能只在有 crop 的帧推进状态机，无人帧也必须推进丢失/搜索计时。因此 PC 端已新增：

```text
simulate_sequence_session_replay_v1.py --missing-frame-policy advance_empty
```

解释：

```text
hold:
  旧口径，便于复现早期结果。

advance_empty:
  num_persons=0 时推进 LOST_SEARCH / STOP；
  有检测但本帧未保存 crop 时保持状态，避免把 crop 采样间隔误判为目标丢失。
```

后续所有用于 Android 接入决策的 sequence replay，应优先参考 `advance_empty` 结果。

## 18. 最近执行清单

```text
[x] 新建 feature/person-crop-collector 分支
[x] 新增主菜单入口和 nav_graph 路由
[x] 新建 PersonCropCollectorFragment 页面
[x] 复用 Detector，显示 person bbox
[x] 新建 PersonCropCaptureConfig
[x] 新建 PersonCropSession
[x] 新建 PersonCropSaver
[x] 实现 Start / Stop Session
[x] 保存 crops/*.jpg
[x] 写 metadata.csv
[x] 写 session_info.json
[x] 显示 saved / skipped / persons / fps
[x] 真机采集 crop session
[x] adb pull 导出
[x] PC 端跑 ReID 复测
[x] 新增 PersonSequenceCollector
[x] 采集真实 sequence：yrc_seq_20260707_140056
[x] 采集更结构化 sequence：yrc2_seq_20260707_152237
[x] PC 端 sequence replay
[ ] 基于 sequence replay 设计 LOCAL_SEARCH / REACQUIRE 主动重捕获策略
[ ] 将 ReID 作为证据接入 Android FollowStateMachine
```
