# 自主跟随购物车 ReID 调研、测试迭代记录与下一步计划

项目背景：基于 OpenBot 的室内自主跟随购物车原型  
当前阶段：阶段 3「升级 ReID」的 PC 端理解、模型筛选与数据采集方案设计

---

## 0. 当前阶段结论摘要

本轮 ReID 调研和实验已经验证了几个关键事实：

1. **ReID 可以作为目标身份匹配的有效辅助特征，但不能单独决定跟随目标。**  
   在当前测试数据中，OSNet 输出的同人/异人余弦相似度整体都偏高，绝对阈值很难直接使用。

2. **姿态、相机视角、人体可见区域对 ReID 影响很大。**  
   同一个人若出现正面/背面、全身/局部、站立/动作变化，可能被模型认为“不太像”；不同人如果视角、姿态、上下身颜色分布相似，也可能被认为“很像”。

3. **Gallery 的构成比单纯数量更重要。**  
   随机选择 gallery 容易选到相似帧；diverse gallery，即在 embedding 空间里选择彼此差异较大的帧，能更好覆盖不同姿态与视角。

4. **当前最优 PC 测试组合暂定为 `osnet_x0_25 + diverse gallery`。**  
   `osnet_x0_5` 参数更多，但在当前数据的 Gallery-Probe 测试中没有优于 `osnet_x0_25`。

5. **下一步应让数据采集更接近真实小车输入。**  
   也就是不再依赖人工裁剪图片，而是在 OpenBot Android 程序中保存人物检测框 crop，形成真实检测框裁剪数据，再导出到 PC 继续测试。

---

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

## 11. 最新 ReID 工程路线建议

### 11.1 PC 端下一步

在继续 `simulate_target_follow_v1.py` 之前，先做真实 crop 数据采集：

```text
Step 1：OpenBot 中加入 crop 保存功能
Step 2：每位同学采集 2-3 个 session
Step 3：导出 crop 到 PC，按身份和 session 整理
Step 4：用 compare_reid_folders_v2.py 重新评估
Step 5：用 diverse gallery 重新评估
Step 6：再做 target-follow simulation
```

### 11.2 Android 端后续设计

建议的 ReID 数据结构：

```text
ReIDGallery
├─ confirmedGallery    初始化阶段确定，容量 5
├─ dynamicGallery      跟随中高置信更新，容量 3
└─ maxGallerySize      总上限 8
```

初始化阶段：

```text
连续采集 10-15 个目标 crop
提取 embedding
用 diverse selection 选 5 个进入 confirmedGallery
```

匹配阶段：

```text
对候选人计算 target_score
对多个候选计算 best_score, second_score
reid_margin = best_score - second_score
```

状态机建议：

```text
margin < 0.03:
    IDENTITY_UNCERTAIN / STOP

0.03 <= margin < 0.05:
    弱确认，需要位置连续 + 连续 N 帧稳定

margin >= 0.05:
    ReID 较可信，但仍需检查位置、运动、尺寸
```

### 11.3 Dynamic Gallery 暂缓

动态更新 gallery 是合理方向，但第一版不应立刻做。建议先完成：

```text
confirmedGallery + diverse selection + margin reject
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

## 12. 当前可写入项目报告的阶段性结论

在均衡后的 4 人、每人 16 张测试集中，`osnet_x0_25 + Market1501` 的同人平均余弦相似度为 0.835，异人平均相似度为 0.806，二者间隔仅 0.029，说明绝对相似度阈值不适合作为目标身份判断依据。随机 gallery-k=5 的 Gallery-Probe 平均准确率为 0.608，而采用 embedding 多样性选择的 diverse gallery-k=5 提升到 0.705，gallery-k=8 进一步提升到 0.750。引入 margin 拒绝机制后，diverse gallery 在 `margin >= 0.03` 的已接受样本上达到 1.000 的准确率，但接受率为 0.364 到 0.438，说明 ReID 更适合作为高置信身份确认信号，而不是每帧强制识别器。对比 `osnet_x0_5` 后发现，虽然其参数量更大、pairwise gap 略高，但 Gallery-Probe 表现不如 `osnet_x0_25`，因此当前阶段优先保留 `osnet_x0_25 + diverse gallery` 作为后续 Android 部署候选方案。

---

## 13. 下一步计划

### 13.1 近期立即做

1. 在 OpenBot Android 端加入人物 crop 数据采集功能。
2. 使用真实手机视角采集单目标 session 数据。
3. 导出检测框 crop 到 PC。
4. 使用 `compare_reid_folders_v2.py` 和 `simulate_gallery_probe_v2.py` 复测真实 crop 数据。
5. 再运行 `simulate_target_follow_v1.py`，模拟“目标图库 vs 当前候选人”的真实跟随逻辑。

### 13.2 中期再做

1. 比较真实 crop 数据下 `x0_25`、`x0_5` 是否仍是当前结论。
2. 尝试 OSNet MSMT17 权重，检查跨场景泛化是否改善。
3. 测试不同 bbox padding 对 ReID 的影响。
4. 设计 Android 端 `ReIDFeatureExtractor` 和 `ReIDGallery` 接口。

### 13.3 暂不做

1. 不急于训练/微调模型。
2. 不急于部署 Android ONNX/TFLite。
3. 不急于做 dynamic gallery 更新。
4. 不让用户配合复杂转身/摆姿势完成初始化。

---

## 14. 最终阶段性判断

本轮 ReID 调研的最大价值不是找到一个“完美模型”，而是明确了工程事实：

```text
ReID 有用，但不可靠；
绝对分数不可靠，margin 更有用；
随机 gallery 不如 diverse gallery；
真实检测框 crop 数据比人工裁剪图更有价值；
不确定时停车，比错误跟随更重要。
```

因此，阶段 3 的 ReID 升级应定义为：

> 基于 OpenBot 人物检测框 crop，构建多样性目标特征库，并将 ReID margin 作为目标身份确认的安全辅助信号；在身份不确定时，系统不切换目标、不恢复前进，而是进入谨慎跟随、等待确认或停车状态。

