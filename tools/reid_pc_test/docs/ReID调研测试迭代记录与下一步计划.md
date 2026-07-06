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

## 16. 下一步计划（更新版）

### 16.1 近期立即做

1. **补充真实 crop 数据。**  
   每位成员尽量采集 2-3 个 session，覆盖远近、正面、背面、侧面、转身、短暂停下、弯腰/局部遮挡等自然动作。

2. **做跨 session 测试。**  
   将同一人的 session A 用作 gallery，session B 用作 probe，避免同一 session 连续帧抬高 Top-1。

3. **更新 target-follow 测试脚本。**  
   加入 `best_score + margin` 双阈值网格评估，检查是否能降低目标缺席时的 false accept。

4. **加入 bbox 连续性模拟。**  
   利用 `metadata.csv` 中的 bbox 信息，模拟位置连续性、bbox 尺寸稳定性和候选人是否位于预测区域。

5. **准备 Android 端接口设计。**  
   明确 `ReIDFeatureExtractor`、`ReIDGallery`、`TargetMatcher`、`TargetMemory` 和状态机之间的数据结构。

### 16.2 中期再做

1. 测试 OSNet MSMT17 权重，检查跨场景泛化是否改善。
2. 测试不同 bbox padding 对 ReID 的影响，例如 0.05 / 0.08 / 0.12。
3. 评估 Android 端 ONNX Runtime Mobile 或 TFLite 路线的模型加载和推理耗时。
4. 在 Human Cart Simulator 中显示 `best_score / second_score / margin / gallery_size / state`。
5. 做多人真实场景采集，验证困难干扰对下的状态机安全策略。

### 16.3 暂不做

1. 不急于训练/微调模型。
2. 不急于做 dynamic gallery 更新。
3. 不让用户配合复杂转身/摆姿势完成初始化。
4. 不把 ReID 作为单一身份判据。
5. 不在目标缺席状态下仅凭 margin 恢复 FOLLOW。

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
安全状态机必须融合位置、运动、尺寸和多帧稳定性。
```

因此，阶段 3 的 ReID 升级应定义为：

> 基于 OpenBot 人物检测框 crop，构建多样性目标特征库；以 `osnet_x0_25 + diverse gallery-k=8` 作为首版候选组合；将 ReID margin 作为目标身份确认的安全辅助信号，并通过位置连续性、bbox 尺寸、运动预测和连续多帧稳定性进行融合。在身份不确定或目标缺席风险较高时，系统不切换目标、不恢复前进，而是进入 `FOLLOW_CAUTION / IDENTITY_UNCERTAIN / STOP`。


