# 自主跟随购物车 ReID 调研、测试迭代记录与下一步计划

项目背景：基于 OpenBot 的室内自主跟随购物车原型  
当前阶段：阶段 3「升级 ReID」的 PC 端理解、模型筛选、OpenBot 自动 crop 数据验证与状态机接入策略设计

---

## 0. 当前阶段结论摘要

本轮 ReID 调研和实验已经从“人工裁剪图片理解模型”推进到“OpenBot 自动检测框 crop 真实输入验证”。当前结论比上一版更明确：

1. **ReID 可以作为目标身份匹配的有效辅助特征，但不能单独决定跟随目标。**  
   早期人工裁剪数据中，OSNet 输出的同人/异人相似度高度重叠；后续 OpenBot 自动 crop 数据明显改善了区分度，但目标缺席时仍存在较高误接受风险。

2. **OpenBot 自动 crop 数据比人工裁剪数据更有工程参考价值。**  
   在真实检测框 crop 数据上，`osnet_x0_25 + Market1501` 的同人/异人均值差距从旧均衡数据的约 `0.029` 提升到 `0.089`，说明自动检测框裁剪更接近未来 Android 端实际输入。

3. **Gallery 的构成比单纯数量更重要，且 diverse gallery 已被验证有效。**  
   在旧均衡数据中，`diverse gallery` 在 `k=3/5/8` 上均优于随机 gallery；在 OpenBot crop 数据中，`gallery-k=8` 明显优于 `gallery-k=5`。

4. **当前最优 PC 测试组合暂定为 `osnet_x0_25 + diverse gallery-k=8`。**  
   `osnet_x0_5` 参数更多，但在当前数据的 Gallery-Probe 测试中没有优于 `osnet_x0_25`。因此首版继续以 `x0_25` 为主线更合理。

5. **ReID margin 在目标存在场景下有用，但不能单独判断目标是否已经回到画面。**  
   在 Target-follow 模拟中，`gallery-k=8` 时目标存在场景下 `margin>=0.05` 的 accepted accuracy 达到 `0.957`；但目标缺席场景下 `margin>=0.05` 的 false accept rate 仍为 `0.457`。因此 ReID margin 必须与位置连续性、bbox 尺寸、运动趋势和连续多帧稳定性融合。

6. **阶段 3 的重点应从“找更强模型”转向“安全地使用 ReID”。**  
   当前关键不再是证明 ReID 是否有用，而是设计 `TargetMemory / ReIDGallery / TargetMatcher / FollowStateMachine` 如何利用 ReID 作为身份置信证据，并在不确定时进入 `IDENTITY_UNCERTAIN / STOP`。

## 1. 技术路线背景

### 1.1 ReID 在本项目中的作用

ReID 不负责检测人，也不直接控制小车。它的作用是：

```text
OpenBot 人物检测 → 得到多个 person bbox
                    ↓
              裁剪每个人物框
                    ↓
              ReID 提取 embedding
                    ↓
      与目标用户 TargetMemory / Gallery 比较
                    ↓
      输出 reid_score / reid_margin
                    ↓
 与位置、运动、尺寸、颜色、状态机融合
```

因此，本项目里的 ReID 不是“识别某个人是谁”，而是判断：

> 当前候选人是否更像用户初始化确认过的目标。

### 1.2 初始推荐模型

前期调研后，优先关注以下模型/框架：

| 方向 | 代表 | 用途 | 当前判断 |
|---|---|---|---|
| 轻量 CNN ReID | OSNet / Torchreid | 首选 PC/Android 端 ReID 候选 | 当前主线 |
| 移动端友好模型 | MobileNetV2 ReID | 备选路线 | 后续再评估 |
| 跟踪+外观特征 | DeepSORT | 借鉴“运动预测+外观匹配”结构 | 作为系统思想参考 |
| 训练平台 | FastReID | 后续自采数据微调、对比实验 | 暂不作为首版部署路线 |
| Transformer / Part-based | TransReID / BPBReID / Occluded ReID | 前沿参考 | 不作为首版工程路线 |

当前工程判断：

```text
首选：OSNet x0_25 / x0_5 + Torchreid
目标：先在 PC 上理解 embedding 和 cosine similarity，再考虑 Android 部署
```

---

## 2. 第 1 轮：PC 端 ReID 基础实验

### 2.1 实验目标

先不碰 Android，也不训练模型，只在 PC 上理解 ReID 的基本工作方式：

```text
人物裁剪图 → OSNet → 512 维 embedding → cosine similarity
```

期望看到：

```text
同一个人之间相似度较高
不同人之间相似度较低
```

### 2.2 环境进展

用户使用 conda 环境 `reid_pc_test`，成功安装 Torchreid，并验证模型列表可用：

```python
import torchreid
torchreid.models.show_avai_models()
```

输出中包含：

```text
osnet_x1_0
osnet_x0_75
osnet_x0_5
osnet_x0_25
osnet_ibn_x1_0
osnet_ain_x1_0
...
```

说明 Torchreid 安装成功，可以继续进行 OSNet 测试。

---

## 3. 第 2 轮：两人数据初测

### 3.1 数据结构

用户最初在 `images/` 下建立两个身份文件夹：

```text
images/
├─ ysy/
└─ rxy/
```

其中 `ysy` 图片更多，`rxy` 图片较少。

### 3.2 初测结果

使用：

```text
model = osnet_x0_25
weight = osnet_x0_25_market1501.pth
```

结果：

| 指标 | 数值 |
|---|---:|
| 图片总数 | 28 |
| 同一人相似度 mean | 0.829 |
| 不同人相似度 mean | 0.814 |
| gap | 0.015 |
| Top-1 最近邻身份正确率 | 0.964 |

### 3.3 解释

这个结果说明：

1. **绝对相似度拉不开。**  
   同人和异人均值只差 0.015，不能用固定阈值直接判断是不是同一个人。

2. **排序关系仍有一定价值。**  
   Top-1 很高，说明模型大多数情况下仍能在最近邻上找到同身份图片。

3. **不能用 `reid_score > 0.8` 这类规则。**  
   因为不同人也可能达到很高分数。

### 3.4 用户观察

用户通过 hard pairs 检查发现：

> 人物动作姿态、相机视角、正面/侧面/背面、全身/局部可见区域，会显著影响“像不像”。不同人如果相机视角和姿态相似，可能更像；同一个人如果视角差异大，也可能不像。

这个观察非常重要，直接引出了后续 gallery 多样性策略。

---

## 4. 第 3 轮：四人数据扩展测试

### 4.1 数据扩展

用户进一步采集了四个人的照片：

```text
images/
├─ chy/ 16 张
├─ ysy/ 24 张
├─ rxy/ 18 张
└─ zhz/ 26 张
```

共 84 张。

### 4.2 84 张全量结果

使用 `osnet_x0_25 + market1501`：

| 指标 | 数值 |
|---|---:|
| 图片总数 | 84 |
| 同一人相似度 mean | 0.834 |
| 不同人相似度 mean | 0.805 |
| gap | 0.029 |
| Top-1 最近邻身份正确率 | 0.845 |

### 4.3 身份对身份混淆

部分身份 pair 的均值：

| 身份对 | mean |
|---|---:|
| chy vs chy | 0.843 |
| zhz vs zhz | 0.839 |
| ysy vs ysy | 0.828 |
| rxy vs rxy | 0.824 |
| chy vs rxy | 0.818 |
| chy vs ysy | 0.816 |
| rxy vs ysy | 0.816 |
| chy vs zhz | 0.799 |
| ysy vs zhz | 0.798 |
| rxy vs zhz | 0.793 |

### 4.4 结论

最危险的混淆组大致为：

```text
chy ↔ rxy
chy ↔ ysy
rxy ↔ ysy
```

这些异人均值已经接近同人均值，进一步证明：

```text
ReID 不能作为唯一身份判据。
```

---

## 5. 第 4 轮：Gallery-Probe 模拟

### 5.1 为什么要做 Gallery-Probe

真实小车初始化时不会只有一张目标图，而应该保存多张目标 embedding，形成 gallery：

```text
target_gallery = [emb1, emb2, emb3, ...]
```

候选人与 gallery 的相似度可取：

```text
target_score = max cosine(candidate, target_gallery)
```

因此 Gallery-Probe 比单纯 pairwise similarity 更接近实际系统。

### 5.2 84 张非均衡数据上的初步结果

`osnet_x0_25` 下：

| gallery-k | mean_acc | min_acc | max_acc | mean_margin |
|---:|---:|---:|---:|---:|
| 3 | 0.562 | 0.431 | 0.681 | 0.027 |
| 5 | 0.634 | 0.500 | 0.750 | 0.026 |
| 8 | 0.710 | 0.519 | 0.846 | 0.027 |

### 5.3 结论

1. 增加 gallery 数量有帮助。  
2. 但平均 margin 仍很小，约 0.026–0.027。  
3. 失败样例中大量 `best_score` 和 `second_score` 非常接近。  
4. 因此 `reid_margin = best_score - second_score` 比绝对分数更重要。

---

## 6. 第 5 轮：均衡数据与脚本升级

### 6.1 脚本需求

为了方便后续测试，脚本升级支持：

```text
--per-id        每个身份抽取多少张图
--weight        模型权重的相对/绝对路径
--model         模型名，如 osnet_x0_25 / osnet_x0_5
--output-prefix 输出文件前缀
```

新增两个脚本：

```text
compare_reid_folders_v2.py
simulate_gallery_probe_v2.py
```

### 6.2 均衡数据结果

使用 `--per-id 16`，每人 16 张，共 64 张：

| 指标 | 数值 |
|---|---:|
| 同一人相似度 mean | 0.835 |
| 不同人相似度 mean | 0.806 |
| gap | 0.029 |
| Top-1 最近邻身份正确率 | 0.766 |

均衡后 Top-1 下降，说明原先全量 84 张的 Top-1 可能受数据不均衡影响。

---

## 7. 第 6 轮：Random Gallery vs Diverse Gallery

### 7.1 思想

用户提出：

> 同一个人在不同视角/姿态下可能差异很大，因此 gallery 不应该随机选，而应该挑选同一个人里看起来差异更大的图片，尽量覆盖不同特征。

将这个想法转为 embedding 空间策略：

```text
Diverse gallery：每次选择和已有 gallery 最不相似的样本，使 gallery 覆盖更广。
```

### 7.2 `osnet_x0_25` 的结果汇总

| 模型 | gallery-k | strategy | mean_acc | margin≥0.03 accepted_rate | margin≥0.03 accepted_acc |
|---|---:|---|---:|---:|---:|
| x0_25 | 3 | random | 0.549 | 0.333 | 0.783 |
| x0_25 | 3 | diverse | 0.596 | 0.346 | 0.889 |
| x0_25 | 5 | random | 0.608 | 0.292 | 0.871 |
| x0_25 | 5 | diverse | 0.705 | 0.364 | 1.000 |
| x0_25 | 8 | random | 0.681 | 0.311 | 0.945 |
| x0_25 | 8 | diverse | 0.750 | 0.438 | 1.000 |

### 7.3 结论

1. Diverse gallery 在 k=3/5/8 上均优于 random gallery。
2. k 越大，强制识别准确率越高。
3. k=8 + diverse 是当前 `x0_25` 下最好的组合。
4. 在 `margin >= 0.03` 的已接受样本上，diverse g5/g8 达到 1.000 的 accepted accuracy。
5. 这支持“多样性目标特征库”的设计。

---

## 8. 第 7 轮：`osnet_x0_5` 对比

### 8.1 Pairwise 结果

使用 `osnet_x0_5 + market1501`：

| 指标 | 数值 |
|---|---:|
| 参数量 | 636,520 |
| FLOPs | 272,901,064 |
| 同一人相似度 mean | 0.806 |
| 不同人相似度 mean | 0.769 |
| gap | 0.037 |
| Top-1 | 0.734 |

与 `x0_25` 对比：

| 模型 | 参数量 | pairwise gap | Top-1 |
|---|---:|---:|---:|
| osnet_x0_25 | 203,568 | 0.029 | 0.766 |
| osnet_x0_5 | 636,520 | 0.037 | 0.734 |

`x0_5` 的 gap 稍大，但 Top-1 更低。

### 8.2 Gallery-Probe 结果

| 模型 | gallery-k | strategy | mean_acc | margin≥0.03 accepted_rate | margin≥0.03 accepted_acc |
|---|---:|---|---:|---:|---:|
| x0_25 | 5 | diverse | 0.705 | 0.364 | 1.000 |
| x0_25 | 8 | diverse | 0.750 | 0.438 | 1.000 |
| x0_5 | 5 | diverse | 0.636 | 0.273 | 0.917 |
| x0_5 | 8 | diverse | 0.688 | 0.375 | 0.917 |

### 8.3 结论

虽然 `x0_5` 参数更多，但在当前数据下没有优于 `x0_25`。当前暂定：

```text
PC 端继续以 osnet_x0_25 + diverse gallery 为主线。
```

---

## 9. 关于 Manual Gallery 的讨论

用户认为当前暂不需要优先做 manual gallery，原因包括：

1. diverse 已经能较好选出不同动作、视角的图片；
2. 手动选图很难量化“差异程度”；
3. 真实购物车不适合要求顾客转圈或摆姿势；
4. 更合理的是自动连续采集，并自动选择 diverse gallery。

这一判断合理。当前工程方向应为：

```text
用户自然站到车前 / 车前方
系统连续采集 1-2 秒
自动从检测框 crop 中选择多样性较高的 5-8 张作为 confirmedGallery
```

---

## 10. 最新思考：应采集 OpenBot 检测框 crop 数据

### 10.1 问题

目前 PC 测试图片主要来自人工裁剪或手动整理。这会引入不确定因素：

```text
人工裁剪是否过紧/过松？
是否包含背景？
是否与未来 Android 检测框 crop 一致？
是否改变了 ReID 输入分布？
```

### 10.2 用户提出的新方案

在 OpenBot 程序里加入图片数据采集功能：

```text
用户模拟小车，手持手机
另一位同学在前方行走、随意做动作
OpenBot 每隔一定时间保存一次人物检测框 crop
每次运行保存到同一个 session 文件夹
目标唯一，无其他行人干扰
最后导出到 PC 测试
```

### 10.3 方案价值

这个方案非常值得做，因为它让 PC 测试数据更接近真实系统输入：

| 方面 | 人工裁剪数据 | OpenBot crop 数据 |
|---|---|---|
| 裁剪来源 | 人工主观裁剪 | 模型检测框自动裁剪 |
| 视角 | 可能不稳定 | 手机真实低机位视角 |
| 运动模糊 | 不一定体现 | 可体现真实手持/车体运动 |
| bbox 偏差 | 人工较理想 | 真实检测框偏差 |
| Android 输入一致性 | 较低 | 高 |
| 对后续部署价值 | 中 | 高 |

### 10.4 需要保存的数据

每个 session 建议保存：

```text
session_20260704_153000/
├─ crops/
│  ├─ 000001_person0.jpg
│  ├─ 000002_person0.jpg
│  └─ ...
├─ frames/                  可选，保存原始帧方便回溯
│  ├─ 000001.jpg
│  └─ ...
└─ metadata.csv
```

`metadata.csv` 建议字段：

```csv
timestamp_ms,frame_id,crop_path,frame_path,bbox_left,bbox_top,bbox_right,bbox_bottom,bbox_width,bbox_height,detection_confidence,num_person,state,session_id
```

### 10.5 采集策略建议

首版采集策略：

```text
仅在检测到 1 个人时保存 crop
每 300-500 ms 保存一次
每个 session 保存 30-100 张
保存 JPEG，质量 90 左右
crop bbox 可加 5%-10% padding，避免检测框过紧
```

推荐采集动作：

```text
直线远离手机
靠近手机
左转/右转
正面、背面、侧面自然出现
短暂停下取物
蹲下/弯腰/局部遮挡
短时离开再回来
```

注意：不需要要求用户刻意转圈，而是通过自然动作获得多样性。

---
---

## 11. 第 8 轮：OpenBot 自动 crop 数据采集与真实输入复测

### 11.1 为什么要做 OpenBot crop 数据

前期测试使用的图片主要来自人工裁剪或手动整理，这会引入额外不确定因素：

```text
人工裁剪是否过紧/过松？
是否包含背景？
是否与未来 Android 检测框 crop 一致？
是否改变了 ReID 输入分布？
```

因此，用户在 OpenBot 程序中加入了 `PersonCropCollector` 数据采集功能，让手机每隔固定时间保存一次人物检测框 crop，并附带 metadata 与 session 信息。这一步让 PC 端测试更接近未来真实小车输入。

采集链路变为：

```text
OpenBot 摄像头帧
  ↓
OpenBot 人物检测
  ↓
person bbox
  ↓
bbox padding 后裁剪 crop
  ↓
保存到 session/crops
  ↓
导出到 PC
  ↓
OSNet / Torchreid 测试
```

### 11.2 Session 数据结构

新的目录结构示例：

```text
images/
├─ cyx-1_20260706_160440/
│  ├─ crops/
│  ├─ metadata.csv
│  └─ session_info.json
├─ yrc-1_20260706_161319/
│  ├─ crops/
│  ├─ metadata.csv
│  └─ session_info.json
├─ ysy-1_20260706_161110/
│  ├─ crops/
│  ├─ metadata.csv
│  └─ session_info.json
└─ manual/
```

其中一个 session 的配置为：

| 字段 | 数值 |
|---|---:|
| capture_interval_ms | 500 |
| min_confidence | 0.5 |
| single_person_only | true |
| bbox_padding_ratio | 约 0.08 |
| max_crops | 120 |
| jpeg_quality | 95 |
| app_mode | PersonCropCollector |

这个采集策略比较合理：既保留了自然动作带来的姿态变化，又避免多人干扰导致身份标签不可靠。

### 11.3 数据集整理

由于 OpenBot session 的图片位于：

```text
session_id/crops/*.jpg
```

而旧测试脚本默认以图片直接父文件夹作为身份标签，因此不能直接把 session 目录传给旧脚本。为此新增脚本：

```text
prepare_openbot_crops_dataset.py
```

该脚本将 session 数据转换为标准 ReID 数据集结构：

```text
images_openbot_clean/
├─ cyx/
├─ yrc/
├─ ysy/
└─ dataset_manifest.csv
```

建议初始过滤参数：

```bash
python prepare_openbot_crops_dataset.py ^
  --src images ^
  --dst images_openbot_clean ^
  --identity-mode base ^
  --min-conf 0.75 ^
  --skip-edge-touch ^
  --max-per-session 80 ^
  --sample-mode even ^
  --overwrite
```

其含义是：

| 参数 | 作用 |
|---|---|
| `--identity-mode base` | 将 `ysy-1 / ysy-2` 归并为 `ysy` |
| `--min-conf 0.75` | 只保留检测置信度较高的 crop |
| `--skip-edge-touch` | 跳过接触画面边缘、人体可能被截断的 crop |
| `--max-per-session 80` | 避免同一个 session 连续帧过多重复 |
| `--sample-mode even` | 在时间轴上均匀采样，而不是只取前半段 |

### 11.4 OpenBot crop 基础 ReID 结果

使用：

```text
images = images_openbot_clean
model = osnet_x0_25
weight = osnet_x0_25_market1501.pth
```

数据规模：

| 身份 | 图片数 |
|---|---:|
| cyx | 80 |
| yrc | 49 |
| ysy | 80 |
| total | 209 |

基础 pairwise / nearest-neighbor 结果：

| 指标 | 数值 |
|---|---:|
| 同一人相似度 mean | 0.709 |
| 不同人相似度 mean | 0.620 |
| gap | 0.089 |
| Top-1 最近邻身份正确率 | 0.990 |

与旧均衡手动图数据对比：

| 数据来源 | same_mean | diff_mean | gap | Top-1 |
|---|---:|---:|---:|---:|
| 旧均衡手动图 | 0.835 | 0.806 | 0.029 | 0.766 |
| OpenBot 自动 crop | 0.709 | 0.620 | 0.089 | 0.990 |

### 11.5 结果解释

这说明：

1. OpenBot 自动 crop 的输入分布更稳定，更接近模型预期，也更接近未来 Android 端实际输入。
2. 同人/异人的均值差距显著扩大，ReID 在真实 crop 上比人工裁剪数据更有区分度。
3. `Top-1=0.990` 是积极信号，但不能过度乐观，因为这些图片很多来自同一 session，相邻帧高度相似，最近邻任务较容易。
4. 后续应做更严格的跨 session 测试，例如 gallery 来自 session A，probe 来自 session B。

### 11.6 身份对身份混淆

OpenBot crop 数据中的身份 pair 均值：

| 身份对 | mean |
|---|---:|
| ysy vs ysy | 0.758 |
| yrc vs yrc | 0.694 |
| yrc vs ysy | 0.683 |
| cyx vs cyx | 0.665 |
| cyx vs yrc | 0.600 |
| cyx vs ysy | 0.593 |

关键观察：

```text
cyx 与其他人较容易区分；
yrc 与 ysy 是当前最危险的困难干扰对。
```

`yrc vs ysy mean = 0.683` 已经接近 `yrc vs yrc mean = 0.694`，说明在某些角度、姿态和 crop 条件下，`yrc` 与 `ysy` 很容易互相混淆。后续测试应重点使用这一困难干扰对验证状态机安全策略。

---

## 12. 第 9 轮：OpenBot crop 上的 Gallery-Probe 测试

### 12.1 测试目标

在真实检测框 crop 数据上验证：

```text
osnet_x0_25 + diverse gallery
```

是否仍然优于早期人工裁剪数据，并比较 `gallery-k=5` 与 `gallery-k=8`。

### 12.2 Gallery-Probe 结果

| 测试 | mean_acc | margin≥0.03 | margin≥0.05 | margin≥0.08 | margin≥0.10 |
|---|---:|---:|---:|---:|---:|
| g5 diverse | 0.840 | acc 0.917 / rate 0.809 | acc 0.942 / rate 0.711 | acc 0.990 / rate 0.495 | acc 1.000 / rate 0.361 |
| g8 diverse | 0.876 | acc 0.953 / rate 0.805 | acc 0.977 / rate 0.692 | acc 1.000 / rate 0.486 | acc 1.000 / rate 0.389 |

### 12.3 结论

1. `gallery-k=8` 明显优于 `gallery-k=5`。  
   强制识别准确率从 `0.840` 提升到 `0.876`。

2. 在相同 margin 阈值下，`k=8` 的 accepted accuracy 更高。  
   例如 `margin>=0.05` 时，`g5` 为 `0.942`，`g8` 为 `0.977`。

3. 当 `margin>=0.08` 时，`g8` 的 accepted accuracy 达到 `1.000`，但接受率下降到 `0.486`。  
   这体现了 ReID 使用中的核心取舍：越保守越安全，但会拒绝更多不确定情况。

4. Android 首版若性能允许，应优先选择：

```text
confirmedGallerySize = 8
galleryStrategy = diverse
model = osnet_x0_25
```

### 12.4 对失败样例的解释

失败样例中，很多 margin 很小：

```text
best=0.770, second=0.769, margin=0.001
best=0.791, second=0.791, margin=0.001
best=0.858, second=0.853, margin=0.005
```

这类错误在工程上不应该被视为“模型确定地选错”，而应被解释为：

```text
身份证据不充分，应进入 IDENTITY_UNCERTAIN。
```

但也存在少数中等 margin 的错误，例如 `yrc → ysy` 中出现 `margin=0.065 / 0.079` 等，这说明 margin 仍不能单独使用，必须和位置连续性、bbox 尺寸、运动趋势、多帧稳定性融合。

---

## 13. 第 10 轮：Target-follow 模拟

### 13.1 为什么要做 Target-follow 模拟

Gallery-Probe 是“每个人都有 gallery”的闭集身份分类；真实购物车只有目标用户的 gallery。

真实小车更接近：

```text
当前目标 = ysy
系统中只有 ysy_gallery

当前画面候选人：
  candidate A = ysy
  candidate B = yrc
  candidate C = cyx

系统只计算：
  score(A, ysy_gallery)
  score(B, ysy_gallery)
  score(C, ysy_gallery)
```

因此新增测试：

```text
simulate_target_follow_v1.py
```

它模拟两类场景：

1. **目标存在**：当前帧中有目标 + 若干路人。  
2. **目标缺席**：当前帧中没有目标，只有路人。

### 13.2 目标存在场景

#### gallery-k=5

| 指标 | 数值 |
|---|---:|
| total_frames | 3000 |
| top1_target_selected_acc | 0.767 |
| margin mean | 0.087 |
| margin median | 0.069 |
| margin p75 | 0.127 |

Reject by margin：

| margin 阈值 | accepted_rate | accepted_acc | reject_rate |
|---:|---:|---:|---:|
| 0.000 | 1.000 | 0.767 | 0.000 |
| 0.030 | 0.768 | 0.838 | 0.232 |
| 0.050 | 0.626 | 0.879 | 0.374 |
| 0.080 | 0.445 | 0.933 | 0.555 |
| 0.100 | 0.354 | 0.953 | 0.646 |

#### gallery-k=8

| 指标 | 数值 |
|---|---:|
| total_frames | 3000 |
| top1_target_selected_acc | 0.843 |
| margin mean | 0.094 |
| margin median | 0.082 |
| margin p75 | 0.138 |

Reject by margin：

| margin 阈值 | accepted_rate | accepted_acc | reject_rate |
|---:|---:|---:|---:|
| 0.000 | 1.000 | 0.843 | 0.000 |
| 0.030 | 0.793 | 0.921 | 0.207 |
| 0.050 | 0.675 | 0.957 | 0.325 |
| 0.080 | 0.510 | 0.986 | 0.490 |
| 0.100 | 0.417 | 0.997 | 0.583 |

### 13.3 目标存在场景结论

`gallery-k=8` 在真实跟随模拟中显著优于 `gallery-k=5`：

| 指标 | g5 | g8 |
|---|---:|---:|
| 强制选择目标正确率 | 0.767 | 0.843 |
| margin≥0.03 accepted_acc | 0.838 | 0.921 |
| margin≥0.05 accepted_acc | 0.879 | 0.957 |
| margin≥0.08 accepted_acc | 0.933 | 0.986 |

这说明：

```text
目标仍在画面中时，ReID margin 对候选人排序和安全确认有明显帮助；
gallery-k=8 是当前更推荐的参数。
```

### 13.4 目标缺席场景

#### gallery-k=5

| margin 阈值 | false_accept_rate | reject_rate |
|---:|---:|---:|
| 0.000 | 1.000 | 0.000 |
| 0.030 | 0.636 | 0.364 |
| 0.050 | 0.457 | 0.543 |
| 0.080 | 0.274 | 0.726 |
| 0.100 | 0.194 | 0.806 |

#### gallery-k=8

| margin 阈值 | false_accept_rate | reject_rate |
|---:|---:|---:|
| 0.000 | 1.000 | 0.000 |
| 0.030 | 0.636 | 0.364 |
| 0.050 | 0.457 | 0.543 |
| 0.080 | 0.267 | 0.733 |
| 0.100 | 0.184 | 0.816 |

### 13.5 目标缺席场景结论

这是当前最重要的风险发现：

> ReID margin 可以判断“当前候选人中谁更像目标”，但不能可靠判断“目标是否真的在画面里”。

当目标缺席时，系统仍然可能从路人中选出一个最像目标的人，且 margin 不一定很小。例如 `gallery-k=8` 时：

```text
margin >= 0.05 false_accept_rate = 0.457
margin >= 0.08 false_accept_rate = 0.267
margin >= 0.10 false_accept_rate = 0.184
```

因此，Android 端绝不能写成：

```java
if (reidMargin > 0.05f) {
    reacquireTarget();
}
```

而必须写成：

```java
if (reidMargin > threshold
        && positionIsReasonable
        && bboxSizeIsReasonable
        && motionIsContinuous
        && stableForNFrames) {
    reacquireTarget();
} else {
    stayUncertainOrStop();
}
```

---

## 14. 当前工程判断：ReID 如何进入状态机

### 14.1 模型与 gallery 选择

当前推荐：

```text
MODEL = osnet_x0_25
GALLERY_SELECTION = diverse
CONFIRMED_GALLERY_SIZE = 8
```

原因：

1. `x0_25` 在当前测试中优于 `x0_5` 的 Gallery-Probe 表现；
2. `x0_25` 更轻，更适合未来 Android 部署；
3. OpenBot crop 数据中 `gallery-k=8` 明显优于 `k=5`；
4. diverse gallery 已经证明优于 random gallery。

### 14.2 ReID 输出字段

`TargetMatcher` 不应该只输出一个 `reid_score`。建议输出：

```java
class ReIDMatchResult {
    float bestScore;
    float secondScore;
    float margin;
    int bestCandidateIndex;
    boolean weakIdentityEvidence;
    boolean mediumIdentityEvidence;
    boolean strongIdentityEvidence;
}
```

其中：

```text
margin = bestScore - secondScore
```

### 14.3 阈值分级

建议将 margin 作为证据强度，而不是单独决策条件：

```text
MARGIN_WEAK   = 0.03
MARGIN_MEDIUM = 0.05
MARGIN_STRONG = 0.08
```

含义：

| 分级 | 条件 | 用法 |
|---|---|---|
| weak | `margin >= 0.03` | 正常 FOLLOW 中可作为支持证据 |
| medium | `margin >= 0.05` | REACQUIRE 中需叠加多帧稳定 |
| strong | `margin >= 0.08` | 更强身份信号，但仍不能单独恢复 LOST |

### 14.4 不同状态下的使用方式

#### FOLLOW_CONFIDENT

目标上一帧仍在，位置连续，ReID 只做低频校验：

```text
margin >= 0.03：作为身份稳定证据
margin < 0.03：不立刻丢目标，降级为 FOLLOW_CAUTION
```

#### FOLLOW_CAUTION

```text
margin >= 0.03 + 位置连续 + 连续多帧稳定：
    回到 FOLLOW_CONFIDENT

margin 持续低 / 候选跳变 / 多人接近：
    进入 IDENTITY_UNCERTAIN
```

#### REACQUIRE_TARGET

短时遮挡后重新找回：

```text
margin >= 0.05 + 连续 3 帧稳定：
    允许恢复 FOLLOW

margin >= 0.08 + 位置合理：
    可作为强恢复证据

否则：
    保持 REACQUIRE / IDENTITY_UNCERTAIN
```

#### LOST / SEARCH

目标是否仍在画面中已经不确定，此时最保守：

```text
ReID margin 永远不能单独恢复 FOLLOW。
```

必须同时满足：

```text
候选人位于目标最后消失位置附近或预测区域
bbox 尺寸与丢失前相近
候选人连续多帧稳定
没有多人得分接近
必要时要求用户重新确认
```

### 14.5 Dynamic Gallery 暂缓

动态更新 gallery 是合理方向，但第一版不应立刻做。建议先完成：

```text
confirmedGallery + diverse selection + margin reject + 状态机融合
```

之后再加入 dynamicGallery。动态更新条件必须非常保守：

```text
state == FOLLOW_CONFIDENT
位置连续
无多人交叉
margin >= 0.05
连续 N 帧稳定
新 embedding 与现有 gallery 有足够差异
```

---

## 15. 当前可写入项目报告的阶段性结论（更新版）

在早期人工裁剪图测试中，`osnet_x0_25 + Market1501` 的同人/异人均值差距很小，均衡 4 人数据下 gap 仅为 0.029，说明绝对余弦相似度不适合作为身份判断依据。后续引入 diverse gallery 后，均衡数据中 `gallery-k=8` 的强制识别准确率提升到 0.750，并在 `margin>=0.03` 的已接受样本上达到 1.000 的 accepted accuracy，证明多样性目标特征库优于随机 gallery。

进一步在 OpenBot 自动检测框 crop 数据上复测后，ReID 表现明显改善。`osnet_x0_25` 在 3 人 209 张真实 crop 数据上得到同人均值 0.709、异人均值 0.620，gap 提升到 0.089，Top-1 最近邻身份正确率达到 0.990。Gallery-Probe 中，`diverse gallery-k=8` 的强制识别准确率达到 0.876，`margin>=0.05` 时 accepted accuracy 为 0.977，`margin>=0.08` 时达到 1.000。

在更接近真实购物车的 Target-follow 模拟中，`gallery-k=8` 在目标存在场景下强制选择目标的准确率为 0.843；当 `margin>=0.05` 时 accepted accuracy 为 0.957，`margin>=0.08` 时为 0.986。这说明 ReID margin 对目标存在时的候选选择非常有帮助。但目标缺席场景中，即使 `margin>=0.05`，false accept rate 仍为 0.457，说明 ReID margin 不能单独判断目标是否已经重新出现。

因此，阶段 3 的正确路线不是“让 ReID 独立决定跟随目标”，而是将 ReID 作为状态机中的身份置信证据，与位置连续性、bbox 尺寸、运动趋势、多帧稳定性共同融合。系统在身份不确定时应进入 `IDENTITY_UNCERTAIN / STOP`，而不是赌最高 ReID 分数继续跟随。

---

## 16. 接入 OpenBot 前的下一步测试计划（修订版）

### 16.1 当前判断：不再优先做“证明 ReID 有用”的测试

前几轮测试已经证明：

```text
osnet_x0_25 + diverse confirmedGallery(k=8)
在当前 OpenBot crop 数据上有明显可用性。
```

因此，下一步的重点不应继续停留在“ReID / gallery 策略是否有效”，而应转为：

```text
如何把 ReID 安全地接入跟随状态机，
避免目标缺席时把路人误认为目标。
```

原计划中的“补充真实 crop 数据”和“跨 session 测试”仍然有价值，但它们主要用于增强证据可信度：

- 补数据：检查当前 3 人 209 张 crop 是否太少，是否覆盖姿态和距离变化不够；
- 跨 session：避免同一 session 连续帧太像，导致 Top-1 指标被抬高；
- 它们回答的是“实验结论是否更稳”，不是“Android 接入前必须先解决什么”。

所以这两项调整为**可选复核**，不作为当前接入前的阻塞任务。

建议把接入前测试拆成三个脚本阶段：

| 阶段 | 脚本 | 解决的问题 |
|---|---|---|
| A | `simulate_target_follow_v2.py` | `best_score + margin` 双阈值是否能压低目标缺席时的误接受 |
| B | `simulate_target_follow_with_bbox_v1.py` | 叠加 bbox 连续性后，能否进一步拒绝位置/尺寸不合理的候选 |
| C | `simulate_state_machine_replay_v1.py` | 把 ReID、bbox、连续帧稳定性翻译成 Android 状态机规则 |

### 16.2 近期必须完成的测试 1：`best_score + margin` 双阈值评估

#### 测试目的

当前 `margin` 只能说明第一名比第二名领先多少，不能说明第一名本身是否真的像目标。

```text
best_score：候选人与目标 gallery 的最高相似度，回答“像不像目标”
margin：第一名和第二名的差距，回答“是不是明显比别人更像目标”
```

只看 `margin` 会出现一种危险情况：

```text
第一名 0.45，第二名 0.30，margin = 0.15
margin 很大，但第一名本身并不够像目标。
```

因此正式接入前，应测试双阈值：

```text
只有 best_score 足够高
并且 margin 足够大
才把 ReID 结果视为可用身份信号。
```

#### 具体做法

建议在 `simulate_target_follow_v1.py` 基础上新增或改出一个 `simulate_target_follow_v2.py`，加入如下阈值网格：

```text
BEST_SCORE_THRESHOLDS = [0.70, 0.75, 0.80, 0.85]
MARGIN_THRESHOLDS     = [0.03, 0.05, 0.08, 0.10]
```

对每组阈值分别统计：

| 场景 | 指标 | 含义 |
|---|---|---|
| target-present | accepted_rate | 目标在画面中时，系统敢于确认的比例 |
| target-present | accepted_acc | 已确认样本中，选中真实目标的比例 |
| target-present | true_accept_rate | `accepted_rate * accepted_acc`，表示所有目标存在帧中被正确确认的比例 |
| target-absent | false_accept_rate | 目标不在画面中时，误把路人当目标的比例 |
| target-absent | reject_rate | 目标不在画面中时，系统正确拒绝恢复的比例 |

推荐命令形态：

```powershell
python simulate_target_follow_v2.py ^
  --images images_openbot_clean ^
  --model osnet_x0_25 ^
  --weight weights\osnet_x0_25_market1501.pth ^
  --gallery-k 8 ^
  --gallery-strategy diverse ^
  --distractors 2 ^
  --trials 20 ^
  --frames-per-target 50 ^
  --absent-frames-per-target 50 ^
  --output-prefix openbot_follow_x025_g8_d2_gategrid
```

#### 预期产出

输出一个网格表，例如：

```text
best_threshold,margin_threshold,present_accept_rate,present_accept_acc,present_true_accept_rate,absent_false_accept_rate,absent_reject_rate
```

本轮测试的目标不是追求一个“全局完美阈值”，而是为不同状态找到不同强度的门槛。首版可以按下面的口径理解：

| 状态 | ReID 门槛 | 含义 |
|---|---|---|
| `FOLLOW_CONFIDENT` | 弱门槛 | 低频检查身份是否仍然合理，不因为单帧 ReID 抖动立刻切目标 |
| `FOLLOW_CAUTION` | 中等门槛 | 需要连续多帧恢复稳定，才能回到高置信跟随 |
| `REACQUIRE_TARGET` | 强门槛 + bbox 连续性 | 目标刚丢后重新捕获，必须更谨慎 |
| `LOST / SEARCH` | ReID 不能单独恢复 | 即使 ReID 分数高，也必须结合预测区域和多帧稳定 |
| `IDENTITY_UNCERTAIN` | 禁止前进 | 身份不确定时等待重新确认或进入 STOP |

可以先把结果映射成如下工程规则，再由测试结果微调：

```text
reid_weak_ok   = best_score >= 0.75 && margin >= 0.03
reid_mid_ok    = best_score >= 0.80 && margin >= 0.05
reid_strong_ok = best_score >= 0.85 && margin >= 0.05
```

### 16.3 近期必须完成的测试 2：bbox 连续性模拟

#### 测试目的

ReID 只看“这个人长得像不像目标”，但跟随系统还知道一个运动常识：

```text
目标不会一帧之间从画面左边瞬移到右边；
目标不会突然变成两倍大或一半小；
目标重新出现时，通常应在最后消失位置或预测区域附近。
```

`metadata.csv` 里保存了每个 crop 的 bbox 信息：

```text
bbox_left / bbox_top / bbox_right / bbox_bottom
bbox_width / bbox_height
image_width / image_height
timestamp_ms / frame_id
```

这些信息可以用来模拟状态机中的位置连续性和尺寸稳定性。

需要注意：当前 `images_openbot_clean` 主要来自单人 session，很多 distractor 是从其他 session 抽出来拼成的“模拟路人”，不是同一真实画面里的路人。因此 bbox 连续性测试只能作为近似模拟，用来提前筛掉明显不合理的恢复逻辑，不能等价于真实多人场景结论。真实多人干扰仍然要在 OpenBot 联调或后续多人采集中验证。

#### 具体做法

建议新增一个轻量脚本，例如 `simulate_target_follow_with_bbox_v1.py`，在原有 ReID 候选排序基础上增加三个门控：

1. **位置门控**

   计算候选 bbox 中心点与上一帧目标中心点的距离：

   ```text
   center_distance = distance(candidate_center, last_target_center)
   normalized_distance = center_distance / image_diagonal
   center_x_jump_ratio = abs(candidate_cx - last_cx) / image_width
   center_y_jump_ratio = abs(candidate_cy - last_cy) / image_height
   ```

   若距离太大，说明候选人不像是上一帧目标自然移动过来的。

2. **尺寸门控**

   比较候选 bbox 面积与上一帧目标面积：

   ```text
   area_ratio = candidate_area / last_target_area
   ```

   若面积突然变得过大或过小，说明可能是另一个更近或更远的人。

3. **预测区域门控**

   用上一帧目标位置做一个简单预测：

   ```text
   predicted_center = last_center + recent_velocity
   prediction_ok = candidate near predicted_center
   ```

   首版不需要 Kalman，只用最近两帧中心点差值估计速度即可。候选人如果不在预测区域附近，就降低可信度或拒绝。

可选补充指标：

```text
bbox_iou = IoU(candidate_bbox, predicted_or_last_bbox)
```

#### 推荐的首版门控参数

不同状态不应使用同一组 bbox 门槛。建议先用三档参数做网格或固定配置：

| 档位 | 适用状态 | 中心跳变上限 | 面积比例范围 |
|---|---|---:|---:|
| loose | `FOLLOW_CONFIDENT` | `0.30` | `0.45 - 2.20` |
| default | `FOLLOW_CAUTION` | `0.25` | `0.50 - 2.00` |
| strict | `REACQUIRE_TARGET` / `LOST` | `0.18` | `0.60 - 1.67` |

首版默认值可以先采用：

```text
MAX_CENTER_JUMP_RATIO = 0.25      # 中心点跳变不超过画面对角线的 25%
MIN_AREA_RATIO        = 0.50      # 面积不能突然小于上一帧的一半
MAX_AREA_RATIO        = 2.00      # 面积不能突然大于上一帧的两倍
STABLE_MATCH_FRAMES   = 3         # 至少连续 3 帧满足 ReID + bbox 门控
```

#### 预期产出

重点比较两种策略：

```text
strategy = reid_only
strategy = reid_bbox_gate
```

输出指标建议包括：

```text
strategy,present_accept_rate,present_accept_acc,present_true_accept_rate,absent_false_accept_rate
reject_reason_counts
```

`reject_reason_counts` 至少拆分为：

```text
rejected_by_best_score
rejected_by_margin
rejected_by_center_jump
rejected_by_area_ratio
rejected_by_prediction
```

目标是验证：

- target-present 下 `present_true_accept_rate` 不要明显崩掉；
- target-absent 下 false accept rate 是否明显下降；
- 被拒绝的样本是否确实多为位置跳变、尺寸突变或候选不在预测区域附近。

#### 2026-07-07 首轮 bbox 单步门控结果

已新增 `simulate_target_follow_with_bbox_v1.py`，并基于 `images_openbot_clean/dataset_manifest.csv` 完成基础版和 prediction 版测试。脚本优先通过 manifest 中的 `src_path` 回查原始 session 的 `metadata.csv`，使用真实原始帧 `image_width / image_height` 做 bbox 归一化；只有查不到原始 metadata 时才回退到命令行默认值。

基础版命令：

```powershell
python simulate_target_follow_with_bbox_v1.py ^
  --images images_openbot_clean ^
  --manifest images_openbot_clean\dataset_manifest.csv ^
  --model osnet_x0_25 ^
  --weight weights\osnet_x0_25_market1501.pth ^
  --gallery-k 8 ^
  --gallery-strategy diverse ^
  --distractors 2 ^
  --trials 20 ^
  --frames-per-target 50 ^
  --gap-values 1,3,5 ^
  --output-prefix openbot_follow_x025_g8_d2_bboxgate
```

关键结果（`reid_profile=strong`）：

| gap | strategy | bbox_profile | present_true_accept_rate | present_accept_acc | absent_false_accept_rate |
|---:|---|---|---:|---:|---:|
| 1 | `reid_only` | default/strict | 0.255 | 0.804 | 0.088 |
| 1 | `reid_center_area` | default | 0.255 | 0.841 | 0.069 |
| 1 | `reid_center_area` | strict | 0.246 | 0.871 | 0.049 |
| 3 | `reid_only` | default/strict | 0.250 | 0.811 | 0.091 |
| 3 | `reid_center_area` | default | 0.229 | 0.859 | 0.066 |
| 3 | `reid_center_area` | strict | 0.205 | 0.880 | 0.048 |
| 5 | `reid_only` | default/strict | 0.234 | 0.810 | 0.089 |
| 5 | `reid_center_area` | default | 0.200 | 0.857 | 0.069 |
| 5 | `reid_center_area` | strict | 0.188 | 0.882 | 0.050 |

加入 `--enable-prediction` 后，`reid_prediction_area` 能继续降低 target-absent false accept，但 gap 越大，对真实目标的 `present_true_accept_rate` 杀伤越明显。例如：

| gap | strategy | bbox_profile | present_true_accept_rate | present_accept_acc | absent_false_accept_rate |
|---:|---|---|---:|---:|---:|
| 1 | `reid_prediction_area` | strict | 0.243 | 0.885 | 0.044 |
| 3 | `reid_prediction_area` | strict | 0.164 | 0.884 | 0.037 |
| 5 | `reid_prediction_area` | strict | 0.147 | 0.881 | 0.038 |

阶段性判断：

```text
bbox center + area gate 确实能作为 ReID false accept 的安全刹车；
strict 档能把 strong ReID 下的 absent false accept 从约 0.09 压到约 0.05；
prediction gate 更适合 REACQUIRE / LOST 场景，不适合作为普通 FOLLOW 的强制门槛；
gap 越大，bbox/prediction 越容易误拒真实目标，后续应在状态机中按状态分级使用。
```

进一步解释：

1. `default center_area` 更适合普通 `FOLLOW / FOLLOW_CAUTION`。  
   例如 gap=1 时，`strong + default center_area` 将 absent false accept 从 `0.088` 降到 `0.069`，同时 `present_true_accept_rate` 仍为 `0.255`，几乎没有额外损失，且 accepted 样本准确率从 `0.804` 提升到 `0.841`。

2. `strict center_area` 更适合 `REACQUIRE_TARGET / IDENTITY_UNCERTAIN / LOST`。  
   它能把 false accept 进一步压到约 `0.05`，但 gap=3/5 时真实目标也更容易被拒绝，因此不适合在普通 `FOLLOW_CONFIDENT` 中每帧强制使用。

3. `prediction gate` 是更强的安全刹车，不是通用门控。  
   它能将 strict 档 false accept 进一步压到约 `0.04`，但在 gap=3/5 时 `present_true_accept_rate` 明显下降。原因是当前 prediction 只是用最近两帧做线性外推，遇到转弯、停下、靠近/远离和手机视角晃动时会变得不稳定。

4. `present_true_accept_rate` 低不等于策略无效。  
   strong profile 本身就是保守门槛，目标不是每帧都接受，而是在较有把握时给状态机提供强证据。因此要同时看 `present_accept_acc` 和 `absent_false_accept_rate`，不能只看 true accept。

当前工程结论可以收束为：

```text
ReID 判断“像不像目标”；
margin 判断“是不是明显比别人更像”；
bbox 判断“是不是像连续运动过来的同一个人”；
状态机判断“是否允许继续前进或恢复 FOLLOW”。
```

### 16.4 近期必须完成的测试 3：状态机门控回放

双阈值和 bbox 连续性已经证明了单步证据有效。下一步不要继续单独优化 ReID 阈值或 bbox 阈值，而应进入状态机回放：把单帧证据串起来，检查系统会不会错误恢复 `FOLLOW`。

建议新增 `simulate_state_machine_replay_v1.py`，在 PC 端用表格回放方式模拟：

```text
FOLLOW_CONFIDENT
FOLLOW_CAUTION
REACQUIRE_TARGET
LOST / SEARCH
IDENTITY_UNCERTAIN
STOP
```

首版输入可以直接复用 bbox 单步门控明细：

```text
outputs/openbot_follow_x025_g8_d2_bboxgate_bbox_gate_rows.csv
outputs/openbot_follow_x025_g8_d2_bboxgate_pred_bbox_gate_rows.csv
```

这些 row 已经包含：

```text
scenario / gap / strategy / reid_profile / bbox_profile
best_score / margin
center_jump_ratio / x_jump_ratio / area_ratio / prediction_error
accepted / correct
```

状态机回放不再关心单帧 accuracy 本身，而是检查“连续多帧证据”会不会导致危险动作。

每一帧根据以下信号更新状态：

```text
best_score
second_score
margin
bbox_position_ok
bbox_size_ok
candidate_in_prediction_region
stable_match_count
uncertain_count
missing_count
candidate_switch_count
```

建议把状态机拆成两层，避免把分数判断和运动控制混在一起。

**证据层：**

```text
reid_weak_ok   = best_score >= 0.75 && margin >= 0.03
reid_mid_ok    = best_score >= 0.80 && margin >= 0.05
reid_strong_ok = best_score >= 0.85 && margin >= 0.05
bbox_loose_ok  = loose center_area gate
bbox_default_ok = default center_area gate
bbox_strict_ok = strict center_area gate
prediction_ok  = candidate near predicted region
stable_ok      = stable_match_count >= 3
```

**动作层：**

| 当前状态 | 条件 | 下一状态/动作 |
|---|---|---|
| `FOLLOW_CONFIDENT` | bbox default ok | 保持低速跟随 |
| `FOLLOW_CONFIDENT` | ReID 弱或抖动，但 bbox default ok | 进入 `FOLLOW_CAUTION`，不立刻丢目标 |
| `FOLLOW_CONFIDENT` | bbox 明显跳变或候选频繁切换 | 进入 `IDENTITY_UNCERTAIN`，禁止继续前进 |
| `FOLLOW_CAUTION` | `reid_mid_ok && bbox_default_ok` 连续 3 帧 | 回到 `FOLLOW_CONFIDENT` |
| `FOLLOW_CAUTION` | 连续 3 帧不稳定 | 进入 `IDENTITY_UNCERTAIN` |
| `REACQUIRE_TARGET` | `reid_strong_ok && bbox_default_ok` 连续 3 帧 | 恢复 `FOLLOW_CONFIDENT` |
| `REACQUIRE_TARGET` | `reid_strong_ok && bbox_strict_ok` 连续 2 帧 | 恢复 `FOLLOW_CONFIDENT` |
| `REACQUIRE_TARGET` | ReID 高但 bbox fail | 进入 `IDENTITY_UNCERTAIN` |
| `IDENTITY_UNCERTAIN` | `reid_strong_ok && bbox_strict_ok` 连续 3 帧 | 进入 `REACQUIRE_TARGET`，不直接恢复 FOLLOW |
| `IDENTITY_UNCERTAIN` | 超时 | `STOP` |
| `LOST / SEARCH` | 仅 ReID 高 | 保持 `SEARCH` 或进入 `IDENTITY_UNCERTAIN`，不能直接恢复 FOLLOW |
| `LOST / SEARCH` | `reid_strong_ok && bbox_strict_ok && prediction_ok` 连续 5 帧 | 进入 `REACQUIRE_TARGET`，不直接恢复 FOLLOW |
| 任意状态 | 超时、连续不确定或急停/通信异常 | `STOP` |

预期输出不只看模型指标，而是看状态机安全性：

```text
state_transition_counts
wrong_follow_recovery_count
target_present_over_stop_count
average_uncertainty_duration
```

其中 `wrong_follow_recovery_count` 最关键：它表示目标缺席时，系统有没有被 ReID 误导而恢复 `FOLLOW`。这个数应尽量接近 0。

首版验收口径：

```text
wrong_follow_recovery_count 尽量为 0；
target_present_over_stop_count 不应明显过高；
IDENTITY_UNCERTAIN 可以频繁出现，但不能直接输出前进；
LOST / SEARCH 中即使 ReID 高，也只能进入 REACQUIRE_TARGET，不能直接 FOLLOW_CONFIDENT；
prediction gate 只在 REACQUIRE / LOST 高风险状态启用，不作为普通 FOLLOW 的强制条件。
```

#### 2026-07-07 初版状态机回放结果

已新增 `simulate_state_machine_replay_v1.py`，输入使用 bbox 单步门控输出：

```text
outputs/openbot_follow_x025_g8_d2_bboxgate_pred_bbox_gate_rows.csv
```

默认参数命令：

```powershell
python simulate_state_machine_replay_v1.py ^
  --rows outputs\openbot_follow_x025_g8_d2_bboxgate_pred_bbox_gate_rows.csv ^
  --output-prefix openbot_follow_x025_g8_d2_state_replay
```

默认参数结果：

| gap | scenario | wrong_follow_recovery_count | wrong_follow_frame_rate | target_present_over_stop_rate | target_present_uncertain_rate |
|---:|---|---:|---:|---:|---:|
| 1 | target_absent | 0 | 0.000 | 0.000 | 0.000 |
| 3 | target_absent | 0 | 0.000 | 0.000 | 0.000 |
| 5 | target_absent | 0 | 0.000 | 0.000 | 0.000 |
| 1 | target_present | 0 | 0.000 | 0.400 | 0.123 |
| 3 | target_present | 0 | 0.000 | 0.478 | 0.145 |
| 5 | target_present | 0 | 0.000 | 0.629 | 0.154 |

较宽松 timeout 对照命令：

```powershell
python simulate_state_machine_replay_v1.py ^
  --rows outputs\openbot_follow_x025_g8_d2_bboxgate_pred_bbox_gate_rows.csv ^
  --output-prefix openbot_follow_x025_g8_d2_state_replay_tuned ^
  --identity-timeout 20 ^
  --search-timeout 20
```

较宽松 timeout 结果：

| gap | scenario | wrong_follow_recovery_count | wrong_follow_frame_rate | target_present_over_stop_rate | target_present_uncertain_rate |
|---:|---|---:|---:|---:|---:|
| 1 | target_absent | 0 | 0.000 | 0.000 | 0.000 |
| 3 | target_absent | 0 | 0.000 | 0.000 | 0.000 |
| 5 | target_absent | 0 | 0.000 | 0.000 | 0.000 |
| 1 | target_present | 0 | 0.000 | 0.180 | 0.290 |
| 3 | target_present | 0 | 0.000 | 0.230 | 0.353 |
| 5 | target_present | 0 | 0.000 | 0.366 | 0.383 |

阶段性判断：

```text
初版状态机规则能守住最关键安全目标：target_absent 下没有错误恢复 FOLLOW；
默认 timeout 过于保守，target_present 下 over_stop_rate 偏高；
放宽 identity/search timeout 后 over_stop 明显下降，但 IDENTITY_UNCERTAIN 持续时间变长；
当前 bbox gate rows 是随机抽样证据流，不是真实连续视频轨迹，因此 over_stop_rate 是压力测试信号，不应直接等同真实跟随表现；
下一步若继续优化状态机，应优先用真实连续 session 生成 replay rows，而不是继续在随机抽样 rows 上调参。
```

#### 2026-07-07 连续 session 时间顺序回放路线

状态机回放之后，下一步不再继续围绕随机 bbox gate rows 调参，而是转向真实 session 的时间顺序回放。原因是：

```text
随机 rows 可以验证安全门控是否足够保守；
真实 chronological session 才能验证用户体验是否过度保守；
Android 接入前真正需要回答的是：连续目标存在时是否稳定，目标缺失或干扰者出现时是否安全。
```

已新增 `simulate_chronological_session_replay_v1.py`，输入继续使用：

```text
images_openbot_clean/dataset_manifest.csv
```

基础连续目标测试命令：

```powershell
python simulate_chronological_session_replay_v1.py ^
  --images images_openbot_clean ^
  --manifest images_openbot_clean\dataset_manifest.csv ^
  --model osnet_x0_25 ^
  --weight weights\osnet_x0_25_market1501.pth ^
  --identity ysy ^
  --session-id ysy-1_20260706_161110 ^
  --gallery-k 8 ^
  --gap 1 ^
  --distractors 2 ^
  --output-prefix openbot_chrono_ysy_continuous
```

人工缺失 + 干扰者插入测试命令：

```powershell
python simulate_chronological_session_replay_v1.py ^
  --images images_openbot_clean ^
  --manifest images_openbot_clean\dataset_manifest.csv ^
  --model osnet_x0_25 ^
  --weight weights\osnet_x0_25_market1501.pth ^
  --identity ysy ^
  --session-id ysy-1_20260706_161110 ^
  --gallery-k 8 ^
  --gap 1 ^
  --distractors 2 ^
  --missing-ranges 20:35 ^
  --distractor-identity yrc ^
  --distractor-session-id yrc-1_20260706_161319 ^
  --distractor-ranges 20:35 ^
  --output-prefix openbot_chrono_ysy_missing_yrc
```

当前 smoke test 结果：

| case | total_frames | wrong_follow_frame_rate | wrong_recovery_count | over_stop_rate | uncertain_rate | stop_count | final_state |
|---|---:|---:|---:|---:|---:|---:|---|
| `ysy` continuous | 72 | 0.000 | 0 | 0.000 | 0.000 | 0 | `FOLLOW_CAUTION` |
| `ysy` missing 20:35 | 72 | 0.000 | 0 | 0.000 | 0.000 | 0 | `FOLLOW_CAUTION` |
| `ysy` missing 20:35 + `yrc` distractor | 72 | 0.000 | 0 | 0.643 | 0.125 | 1 | `STOP` |

阶段性解释：

```text
连续目标存在时，chronological replay 明显比随机 rows 更稳定；
缺失段没有错误恢复 FOLLOW，这是安全目标；
缺失段插入强干扰者后进入 STOP，说明当前规则偏安全；
一旦进入 STOP，脚本不会自动恢复，这会放大后续 over_stop_rate；
因此下一轮应区分“STOP 后必须人工恢复”和“SEARCH/REACQUIRE 可自动恢复”的真实 Android 策略。
```

这一步的价值不是直接给出最终 Android 参数，而是把后续需要真实时序数据验证的问题暴露出来：如果只有 crop 数据，没有“无人帧、多检测框、人工事件”的连续记录，就无法判断状态机在目标离开、遮挡、返回和干扰者进入时的体验是否合理。

#### 2026-07-07 Android sequence 真实时序回放结果

在 `PersonSequenceCollector` 完成 Android 端实现后，已经采集第一条真实 sequence：

```text
tools/reid_pc_test/images/yrc_seq_20260707_140056
```

采集数据概况：

| item | count |
|---|---:|
| `frame_log.csv` rows | 380 |
| `detections.csv` rows | 384 |
| `events.csv` rows | 11 |
| usable crop files | 136 |
| `num_persons=0` frames | 26 |
| `num_persons=1` frames | 326 |
| `num_persons>=2` frames | 28 |

已新增 `simulate_sequence_session_replay_v1.py`，用于直接读取 Android sequence 目录：

```powershell
python simulate_sequence_session_replay_v1.py ^
  --sequence images\yrc_seq_20260707_140056 ^
  --identity yrc ^
  --model osnet_x0_25 ^
  --weight weights\osnet_x0_25_market1501.pth ^
  --gallery-seconds 5 ^
  --gallery-k 8 ^
  --event-tolerance-ms 1000 ^
  --identity-timeout 20 ^
  --search-timeout 20 ^
  --output-prefix yrc_seq_140056_replay
```

基准结果：

| metric | value |
|---|---:|
| total_reid_frames | 126 |
| target_visible_reid_frames | 118 |
| target_absent_reid_frames | 8 |
| wrong_follow_frame_rate | 0.000 |
| wrong_recovery_count | 0 |
| over_stop_rate | 0.517 |
| terminal_stop_tail_share_of_visible | 0.517 |
| uncertain_rate | 0.220 |
| stop_count | 1 |
| final_state | `STOP` |

分段诊断结果：

| segment | reid_frames | visible_reid_frames | absent_reid_frames | wrong_follow_absent_rate | uncertain_visible_rate | stop_visible_rate |
|---|---:|---:|---:|---:|---:|---:|
| all_reid | 126 | 118 | 8 | 0.000 | 0.220 | 0.517 |
| pre_stop | 65 | 57 | 8 | 0.000 | 0.456 | 0.000 |
| at_or_post_stop | 61 | 61 | 0 | 0.000 | 0.000 | 1.000 |

这个分段结果说明：

```text
当前真实 sequence 中没有发生目标缺席时错误 FOLLOW；
高 over_stop_rate 主要来自进入终态 STOP 之后的尾段，而不是 STOP 前连续误判；
因此 sequence replay 需要同时看 all_reid 和 pre_stop，两者不能混在一起解释；
当前策略更像“安全兜底足够，但恢复偏保守”。
```

对 `event_tolerance_ms = 0 / 1000 / 2000` 和 `identity_timeout = 20 / 30 / 40` 做了参数扫：

| event_tolerance_ms | identity_timeout | target_absent_reid_frames | wrong_follow_frame_rate | wrong_recovery_count | over_stop_rate | first_stop_frame_id |
|---:|---:|---:|---:|---:|---:|---:|
| 0 | 20 | 3 | 0.000 | 0 | 0.496 | 1427 |
| 0 | 30 | 3 | 0.000 | 0 | 0.415 | 1588 |
| 0 | 40 | 3 | 0.000 | 0 | 0.333 | 1743 |
| 1000 | 20 | 8 | 0.000 | 0 | 0.517 | 1427 |
| 1000 | 30 | 8 | 0.000 | 0 | 0.432 | 1588 |
| 1000 | 40 | 8 | 0.000 | 0 | 0.347 | 1743 |
| 2000 | 20 | 14 | 0.071 | 1 | 0.536 | 1444 |
| 2000 | 30 | 14 | 0.071 | 1 | 0.446 | 1604 |
| 2000 | 40 | 14 | 0.071 | 1 | 0.357 | 1759 |

参数扫解释：

```text
identity_timeout 从 20 增加到 40，会把 STOP 明显后移，over_stop_rate 下降；
但 timeout 增大也意味着 IDENTITY_UNCERTAIN 持续更久，真实车上应对应“停止前进、原地谨慎等待/搜索”，不能继续向前跟随；
event_tolerance_ms=2000 会把 target_return 之后约 2 秒仍标成 target_absent，导致 frame_id=776 这种已经很像目标返回的帧被算成 wrong recovery；
因此当前默认建议使用 event_tolerance_ms=1000，2000 只作为事件按钮明显滞后的压力观察，不作为主评估口径。
```

下一步建议：

1. 保留 `simulate_sequence_session_replay_v1.py` 的分段诊断输出，后续所有真实 sequence 都同时查看 `pre_stop` 和 `at_or_post_stop`。
2. 首版 Android 接入前暂以 `identity_timeout=20~40` 作为候选范围，但真实控制策略中 `IDENTITY_UNCERTAIN` 必须禁止前进。
3. 再采一条结构更清晰的 sequence：正常单目标、目标完全离开、目标返回、目标离开 + 干扰者进入、目标在场 + 干扰者进入、明确遮挡。
4. 如果手机性能允许，可以把 sequence crop 采样间隔从 500 ms 缩短到 300 ms，提高 ReID replay 的帧密度。

#### 2026-07-07 第二条 Android sequence 与主动重捕获结论

第二条真实 sequence 已采集：

```text
tools/reid_pc_test/images/yrc2_seq_20260707_152237
```

用户描述流程：

```text
正常跟随 -> 目标离开 -> 画面中没人 -> 目标返回 -> 正常跟随 -> 干扰者进入 -> 干扰者离开 -> 正常跟随 -> 遮挡
```

数据质量：

| item | count / value |
|---|---:|
| `frame_log.csv` rows | 284 |
| `detections.csv` rows | 292 |
| `events.csv` rows | 6 |
| usable crop files | 147 |
| `num_persons=0` frames | 22 |
| `num_persons=1` frames | 233 |
| `num_persons>=2` frames | 29 |
| actual crop interval | 300 ms |

事件记录更干净：

```text
target_left -> target_return
distractor_enter -> distractor_leave
occlusion_start -> occlusion_end
```

基础回放命令：

```powershell
python simulate_sequence_session_replay_v1.py ^
  --sequence images\yrc2_seq_20260707_152237 ^
  --identity yrc2 ^
  --model osnet_x0_25 ^
  --weight weights\osnet_x0_25_market1501.pth ^
  --gallery-seconds 5 ^
  --gallery-k 8 ^
  --event-tolerance-ms 1000 ^
  --identity-timeout 20 ^
  --search-timeout 20 ^
  --output-prefix yrc2_seq_152237_replay_t1000_id20
```

基础结果：

| metric | value |
|---|---:|
| total_reid_frames | 131 |
| target_visible_reid_frames | 126 |
| target_absent_reid_frames | 5 |
| wrong_follow_frame_rate | 0.200 |
| wrong_recovery_count | 0 |
| over_stop_rate | 0.706 |
| terminal_stop_tail_share_of_visible | 0.706 |
| stop_count | 1 |
| final_state | `STOP` |

解释：

```text
wrong_follow_frame_rate=0.2 主要来自目标刚离开窗口附近 1 个有 crop 的帧仍处于 FOLLOW_CONFIDENT；
这不是“把干扰者当目标恢复 FOLLOW”，因为 wrong_recovery_count=0；
高 over_stop_rate 仍然主要来自终态 STOP 后的尾段。
```

随后发现旧 replay 口径还有一个不足：没有 crop 的无人帧原本不会推进状态机。但真实 Android 控制循环中，无人帧必须推进目标丢失、搜索、超时逻辑。因此 `simulate_sequence_session_replay_v1.py` 新增：

```text
--missing-frame-policy advance_empty
```

含义：

```text
hold:
  默认旧口径。没有 crop 特征的帧保持状态不变，便于和旧实验对照。

advance_empty:
  当 num_persons=0 时推进 LOST_SEARCH / IDENTITY_UNCERTAIN / STOP 计数；
  当有检测但本帧未保存 crop 时仍保持状态，避免把采样间隔误判成目标丢失。
```

`advance_empty` 基准结果：

| timeout | wrong_follow_frame_rate | wrong_recovery_count | over_stop_rate | stop_count | final_state |
|---:|---:|---:|---:|---:|---|
| 20 | 0.200 | 0 | 0.833 | 1 | `STOP` |
| 30 | 0.200 | 0 | 0.802 | 1 | `STOP` |
| 40 | 0.200 | 0 | 0.722 | 1 | `STOP` |
| 60 | 0.200 | 0 | 0.563 | 1 | `STOP` |

关键观察：

```text
把 timeout 从 20 拉到 60 只能推迟 STOP，不能从根本上解决恢复过保守；
目标返回后其实有连续多帧 bbox 很稳定，且 ReID 分数多在 0.73-0.85；
当前规则要求 strong/strict 连续证据，导致状态长期卡在 IDENTITY_UNCERTAIN；
最后在干扰者窗口附近超时 STOP；
因此问题不是“看不到人”，而是“看到了也不敢确认”。
```

宽松恢复条件对照：

```powershell
python simulate_sequence_session_replay_v1.py ^
  --sequence images\yrc2_seq_20260707_152237 ^
  --identity yrc2 ^
  --model osnet_x0_25 ^
  --weight weights\osnet_x0_25_market1501.pth ^
  --gallery-seconds 5 ^
  --gallery-k 8 ^
  --event-tolerance-ms 1000 ^
  --identity-timeout 60 ^
  --search-timeout 60 ^
  --missing-frame-policy advance_empty ^
  --uncertain-recover-frames 2 ^
  --reacquire-strict-frames 1 ^
  --reacquire-default-frames 2 ^
  --lost-recover-frames 3 ^
  --output-prefix yrc2_seq_152237_advance_empty_recover_soft_a
```

结果：

| metric | value |
|---|---:|
| wrong_follow_frame_rate | 0.200 |
| wrong_recovery_count | 0 |
| over_stop_rate | 0.000 |
| stop_count | 0 |
| uncertain_rate | 0.190 |
| final_state | `FOLLOW_CAUTION` |

状态转换链：

```text
目标离开 -> IDENTITY_UNCERTAIN
目标返回后连续稳定 -> REACQUIRE_TARGET -> FOLLOW_CONFIDENT
干扰者进入 -> IDENTITY_UNCERTAIN
干扰者离开/正常后 -> REACQUIRE_TARGET -> FOLLOW_CONFIDENT
遮挡窗口中 -> FOLLOW_CAUTION / FOLLOW_CONFIDENT 之间谨慎切换
```

阶段性判断：

```text
当前最大问题不是 ReID 完全不可用；
也不是简单把 timeout 调大；
而是状态机缺少“安全但主动”的 LOCAL_SEARCH / REACQUIRE 恢复路径。
```

新的策略口径应改为：

```text
目标丢失时：
  立即取消线速度，禁止继续前进；
  进入 LOCAL_SEARCH / IDENTITY_UNCERTAIN，允许原地低速搜索；
  如果目标返回并出现多帧 ReID + bbox + prediction 稳定证据，进入 REACQUIRE_TARGET；
  REACQUIRE_TARGET 连续稳定后恢复 FOLLOW；
  若搜索超时、干扰风险过高、障碍/急停/通信异常，则进入 STOP。
```

这里必须区分两个概念：

```text
motion_stop:
  线速度为 0，不向前走，但仍继续观察、原地搜索、尝试重捕获。

hard STOP:
  真正终态停车，搜索失败或风险过高后等待人工重新开始。
```

因此下一阶段的核心不再是“让 STOP 更晚一点”，而是：

> 让系统在 `motion_stop` 的安全边界内更主动地找人，并用多帧证据从 `LOCAL_SEARCH / IDENTITY_UNCERTAIN` 恢复到 `REACQUIRE_TARGET`。

### 16.5 Android 接入前应产出的最小清单

完成上述测试后，再开始 OpenBot 代码接入。接入前至少应得到：

1. `ReIDMatchResult` 字段定义：

   ```java
   class ReIDMatchResult {
       float bestScore;
       float secondScore;
       float margin;
       int bestCandidateIndex;
       boolean bestScoreOk;
       boolean marginOk;
       boolean bboxPositionOk;
       boolean bboxSizeOk;
       boolean predictionOk;
       boolean stableForRecovery;
       int stableMatchCount;
       int uncertainCount;
       int candidateSwitchCount;
   }
   ```

2. `ReIDGallery` 策略：

   ```text
   模型：osnet_x0_25
   gallery 选择：diverse
   confirmedGallery 大小：8
   dynamicGallery：暂不启用
   ```

3. 首版门控参数：

   ```text
   BEST_WEAK / BEST_MEDIUM / BEST_STRONG
   MARGIN_WEAK / MARGIN_MEDIUM / MARGIN_STRONG
   MAX_CENTER_JUMP_RATIO
   MIN_AREA_RATIO / MAX_AREA_RATIO
   PREDICTION_RADIUS_RATIO
   STABLE_MATCH_FRAMES
   ```

4. 状态机接入规则：

   ```text
   ReID 只提供身份证据；
   bbox 连续性提供运动合理性证据；
   prediction region 提供短时重定位证据；
   连续多帧稳定提供恢复 FOLLOW 的安全证据；
   无人帧必须推进 LOST/SEARCH 计时；
   motion_stop 与 hard STOP 必须区分；
   任何单一证据都不能独立恢复 FOLLOW。
   ```

### 16.6 可选复核：补数据与跨 session

以下工作有价值，但不阻塞当前 Android 接入前测试：

1. 每位成员补采 2-3 个 session，覆盖远近、正面、背面、侧面、转身、短暂停下、弯腰、局部遮挡等自然动作。
2. 做跨 session 测试：同一人的 session A 用作 gallery，session B 用作 probe。
3. 如果跨 session 表现明显下降，再回头调整 gallery 采集策略或测试更强权重。

判断标准：

```text
如果当前目标是“先把 ReID 安全接进状态机”，补数据不是阻塞项；
如果当前目标是“写报告证明泛化能力”，补数据和跨 session 就很有价值。
```

### 16.7 中期再做

1. 测试 OSNet MSMT17 权重，检查跨场景泛化是否改善。
2. 测试不同 bbox padding 对 ReID 的影响，例如 0.05 / 0.08 / 0.12。
3. 评估 Android 端 ONNX Runtime Mobile 或 TFLite 路线的模型加载和推理耗时。
4. 在 Human Cart Simulator 中显示 `best_score / second_score / margin / gallery_size / state`。
5. 做多人真实场景采集，验证困难干扰对下的状态机安全策略。

### 16.8 暂不做

1. 不急于训练/微调模型。
2. 不急于做 dynamic gallery 更新。
3. 不让用户配合复杂转身/摆姿势完成初始化。
4. 不把 ReID 作为单一身份判据。
5. 不在目标缺席状态下仅凭 margin 恢复 FOLLOW。
6. 不把 `STOP` 当作唯一安全动作；应优先设计 `motion_stop + LOCAL_SEARCH + REACQUIRE`。

---

## 17. 最终阶段性判断（更新版）

本轮 ReID 调研的最大价值不是找到一个“完美模型”，而是明确了几个工程事实：

```text
ReID 有用，但不能独立决策；
OpenBot 自动检测框 crop 数据比人工裁剪图更可靠；
osnet_x0_25 + diverse gallery-k=8 是当前最优组合；
margin 比绝对分数更有价值；
目标存在时 ReID 能显著帮助候选排序；
目标缺席时 ReID false accept 风险仍高；
安全状态机必须融合位置、运动、尺寸和多帧稳定性；
无人帧、多人帧和人工事件 sequence 比随机 crop rows 更能暴露真实体验问题；
首版应区分 motion_stop 与 hard STOP，让系统在停止前进的同时继续主动搜索和重捕获。
```

因此，阶段 3 的 ReID 升级应定义为：

> 基于 OpenBot 人物检测框 crop，构建多样性目标特征库；以 `osnet_x0_25 + diverse gallery-k=8` 作为首版候选组合；将 ReID margin 作为目标身份确认的安全辅助信号，并通过位置连续性、bbox 尺寸、运动预测和连续多帧稳定性进行融合。在身份不确定或目标缺席风险较高时，系统不切换目标、不恢复前进，而是进入 `FOLLOW_CAUTION / IDENTITY_UNCERTAIN / LOCAL_SEARCH`；若多帧证据稳定，再进入 `REACQUIRE_TARGET` 并恢复 `FOLLOW`。只有搜索失败、风险过高或触发安全异常时才进入 hard `STOP`。

---

## 18. 2026-07-08 Android TFLite 实机接入结果

### 18.1 模型导出与接入状态

已完成 `osnet_x0_25_market1501.pth` 到 Android TFLite 测试资产的导出与验证：

```text
pth -> legacy ONNX -> onnx2tf -> float32 TFLite
```

最终 Android 测试模型：

```text
dev/OpenBot/android/robot/src/main/assets/networks/reid/osnet_x0_25_market1501.tflite
```

该文件属于本地测试资产，默认不提交。实际检查结果：

```text
TFLite input  = [1, 3, 256, 128], float32
TFLite output = [1, 512], float32
```

这与 Android 端 `TfliteReIDFeatureExtractor` 的 NCHW 输入和 512 维 embedding 预期一致。

最新 `robot-debug.apk` 已成功构建并安装到手机；Human Cart Simulator 中 `reidAvailable=true`，ReID 推理能够运行，debug 面板中的 ReID 字段显示正常。

### 18.2 实机观察

当前实机表现比 PC 纯脚本更接近真实问题：

- 帧率约 30 FPS，说明首版 ReID 低频/事件触发式调度对手机性能压力可接受。
- ReID 对目标身份有帮助，但仍不能单独保证“不跟错人”。
- 目标离开画面或多人进入时，仍存在把干扰者识别为目标并错误跟随的风险。
- 目标重新进入画面时，有时重捕获较慢，甚至识别不出来。

这与 PC 端结论一致：ReID 是有效证据，但不是最终身份判决器。

### 18.3 新判断：需要目标轨迹与身份信念层

当前问题不应继续只靠调高阈值解决。阈值过严会让目标返回后长期卡在 `IDENTITY_UNCERTAIN`；阈值过松又会提高 false accept 和跟错风险。

下一阶段应新增：

```text
TargetTrackManager:
  把连续 bbox 关联为短时 track，记录 trackId、年龄、missedFrames、位置和尺寸连续性。

IdentityBeliefAccumulator:
  对每个 track 累积 target_belief，融合 ReID、bbox、prediction、候选切换和多帧稳定性。
```

状态机恢复规则应从：

```text
单帧候选满足 ReID / bbox 条件 -> 恢复 FOLLOW
```

升级为：

```text
稳定 track + 稳定 identity belief + 多帧证据
  -> REACQUIRE_TARGET
  -> FOLLOW_CAUTION
  -> FOLLOW_CONFIDENT
```

### 18.4 下一步最小验收口径

下一轮 Android 测试不再只看 `bestScore / margin`，而要同时观察：

```text
trackId
trackAge
missedFrames
targetBelief
beliefReason
candidateSwitchCount
stableMatchCount
state
selectedAction
```

验收重点：

1. 目标离开后，干扰者进入画面时不能获得足够 belief 并恢复前进。
2. 目标返回后，应允许先成为疑似目标，再经多帧稳定进入 `REACQUIRE_TARGET`。
3. 已锁定目标时，干扰者一帧 ReID 高分不能抢走目标身份。
4. 搜索阶段可以提高 ReID 频率和原地扫描积极性，但线速度必须保持 0。


