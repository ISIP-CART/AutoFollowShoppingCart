# ReID PC Test Workspace

`tools/reid_pc_test/` 是团队共享的 PC 端 ReID 调研与测试工作区。它的作用不是部署 Android 代码，而是在正式接入 OpenBot 之前，用可重复的脚本验证 ReID 模型、gallery 策略、目标缺席误接受风险、bbox 连续性门控等工程问题。

当前首版方向：

```text
model: osnet_x0_25
weight: osnet_x0_25_market1501.pth
gallery: diverse confirmedGallery(k=8)
role: ReID 作为身份置信度辅助，不作为独立身份判决器
```

最新结论与下一步计划见：

- `docs/ReID调研测试迭代记录与下一步计划.md`

## 目录总览

| 路径 | 是否提交 | 用途 |
|---|---:|---|
| `README.md` | 是 | 当前工作区索引，说明每个目录和脚本的用途。 |
| `docs/` | 是 | ReID 调研记录、测试结论、下一步计划、采集器计划等文档。 |
| `deep-person-reid/` | 是 | 上游 `torchreid` / `deep-person-reid` 参考源码，便于团队本地阅读和复现。当前按普通目录纳入主仓库，不作为 submodule。 |
| `images/` | 否 | 原始 OpenBot/person crop 采集数据，可能包含私人照片和 session metadata。禁止提交或公开上传。 |
| `images_openbot_clean/` | 否 | 从原始采集数据整理出的干净身份数据集，按 `identity/` 分目录，并带 `dataset_manifest.csv`。禁止提交或公开上传。 |
| `outputs/` | 否 | 各脚本生成的 CSV 结果、失败样本、summary 等。可能可反推出私人数据，禁止提交或公开上传。 |
| `weights/` | 否 | ReID 模型权重，例如 `osnet_x0_25_market1501.pth`。文件较大且来源单独管理，默认不提交。 |
| `__pycache__/` | 否 | Python 运行缓存，自动生成，不需要关心。 |

## 文档说明

| 文件 | 用途 |
|---|---|
| `docs/ReID调研测试迭代记录与下一步计划.md` | 主文档。记录 ReID 调研路线、已跑实验、指标解释、当前结论、Android 接入前的测试计划。 |
| `docs/person-crop-collector完成计划.md` | OpenBot/person crop 采集器相关计划，说明如何采集、筛选、保存 person crop 与 metadata。 |

## 数据目录说明

### `images/`

原始采集数据目录，通常按 session 保存，例如：

```text
images/
  cyx-1_20260706_160440/
    crops/
    metadata.csv
```

这里的 `metadata.csv` 通常包含真实原始帧尺寸：

```text
image_width,image_height,bbox_left,bbox_top,bbox_right,bbox_bottom,...
```

后续 bbox 连续性测试会优先回查这些 session metadata，使用真实原始帧尺寸做归一化。

### `images_openbot_clean/`

清洗后的 ReID 测试集，按身份分目录：

```text
images_openbot_clean/
  cyx/
  yrc/
  ysy/
  dataset_manifest.csv
```

`dataset_manifest.csv` 是 clean 数据和原始 session 的桥：

```text
identity,session_id,out_path,src_path,frame_id,timestamp_ms,bbox_left,...
```

其中：

- `out_path`：clean 数据集中的 crop 相对路径，用于对齐图片。
- `src_path`：原始 `images/` 下 crop 路径，用于回查 session metadata。
- `bbox_*`：OpenBot 检测框坐标，用于 bbox 连续性模拟。

## 脚本说明

| 脚本 | 当前状态 | 用途 |
|---|---|---|
| `prepare_openbot_crops_dataset.py` | 可用 | 从原始 OpenBot crop/session 数据整理出 `images_openbot_clean/`，生成 `dataset_manifest.csv`。 |
| `compare_reid_folders.py` | 旧版 | 早期按身份文件夹抽取 ReID 特征、计算相似度矩阵和同/不同人分布。 |
| `compare_reid_folders_v2.py` | 当前可用 | 改进版文件夹 ReID 对比脚本，输出 similarity matrix、pairwise scores、identity pair summary、top1 matches 等。 |
| `simulate_gallery_probe.py` | 旧版 | 早期 gallery/probe 模拟，评估 gallery 选取对识别的影响。 |
| `simulate_gallery_probe_v2.py` | 当前可用 | 改进版 gallery/probe 模拟，支持 `gallery-k`、`gallery-strategy=random/diverse`，输出 fail cases、reject summary 等。 |
| `simulate_target_follow_v1.py` | 当前可用 | 目标跟随候选模拟。构造 target-present 和 target-absent 场景，评估 margin 阈值下的误接受风险。 |
| `simulate_target_follow_v2.py` | 当前可用 | `best_score + margin` 双阈值网格评估。回答“best_score 是否能降低目标缺席 false accept”。 |
| `simulate_target_follow_with_bbox_v1.py` | 当前可用 | bbox 单步门控评估。回答“ReID + bbox 连续性是否比 ReID only 更安全”。 |
| `collect_diverse_gallery_images.py` | 辅助工具 | 根据特征多样性挑选 gallery 图片，便于人工检查 confirmedGallery 候选。 |
| `analyze_identity_pairs.py` | 辅助工具 | 分析身份对之间的相似度分布，定位最容易混淆的身份组合。 |
| `inspect_hard_pairs.py` | 辅助工具 | 检查 hard pairs / fail cases，帮助人工查看高相似误匹配样本。 |

## 当前推荐运行顺序

### 1. 全量相似度与身份对分析

```powershell
python compare_reid_folders_v2.py ^
  --images images_openbot_clean ^
  --model osnet_x0_25 ^
  --weight weights\osnet_x0_25_market1501.pth ^
  --output-prefix openbot_x025_clean
```

用途：

- 看同一人/不同人的整体相似度分布。
- 看哪些身份对最容易混淆。
- 确认模型和数据是否具有基本区分度。

### 2. gallery/probe 策略验证

```powershell
python simulate_gallery_probe_v2.py ^
  --images images_openbot_clean ^
  --model osnet_x0_25 ^
  --weight weights\osnet_x0_25_market1501.pth ^
  --gallery-k 8 ^
  --gallery-strategy diverse ^
  --output-prefix openbot_x025_g8_diverse
```

用途：

- 验证 `diverse gallery` 是否比随便选连续帧更稳。
- 目前 `gallery-k=8 + diverse` 是首版推荐 confirmedGallery 策略。

### 3. target-follow 候选模拟

```powershell
python simulate_target_follow_v1.py ^
  --images images_openbot_clean ^
  --model osnet_x0_25 ^
  --weight weights\osnet_x0_25_market1501.pth ^
  --gallery-k 8 ^
  --gallery-strategy diverse ^
  --distractors 2 ^
  --trials 20 ^
  --frames-per-target 50 ^
  --absent-frames-per-target 50 ^
  --output-prefix openbot_follow_x025_g8_d2
```

用途：

- 构造 target-present：目标在候选框中。
- 构造 target-absent：目标不在候选框中，只有路人。
- 初步观察 margin 阈值对 accepted accuracy / false accept 的影响。

### 4. `best_score + margin` 双阈值评估

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

用途：

- 同时测试 `best_score` 和 `margin`。
- 结论：`best_score` 是降低 target-absent false accept 的主力，但仍不是充分条件。
- 当前建议：

```text
FOLLOW_CONFIDENT: best>=0.75 && margin>=0.03 仅作弱身份辅助
FOLLOW_CAUTION:   best>=0.80 && margin>=0.05 需叠加 bbox 和多帧稳定
REACQUIRE:        best>=0.85 && margin>=0.05 仍不能单独恢复 FOLLOW
LOST/SEARCH:      ReID 不能单独恢复 FOLLOW
```

### 5. bbox 单步门控评估

基础版，不启用 prediction：

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

启用 prediction：

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
  --enable-prediction ^
  --output-prefix openbot_follow_x025_g8_d2_bboxgate_pred
```

用途：

- 比较 `reid_only`、`reid_center`、`reid_center_area`、`reid_prediction_area`。
- 验证 bbox 连续性是否能作为 ReID false accept 的安全刹车。
- 当前观察：`strong + strict + center_area` 能将 absent false accept 从约 `0.09` 压到约 `0.05`，但也会降低 true accept。

## 输出文件命名

所有脚本默认输出到 `outputs/`。常见文件包括：

| 后缀 | 含义 |
|---|---|
| `_similarity_matrix.csv` | 图片两两相似度矩阵。 |
| `_pairwise_scores.csv` | 两两图片相似度明细。 |
| `_identity_pair_summary.csv` | 身份对级别相似度汇总。 |
| `_top1_matches.csv` | 每张图的最近邻匹配结果。 |
| `_fail_cases.csv` | gallery/probe 或跟随模拟中的失败样本。 |
| `_reject_summary.csv` | 按阈值统计 accepted/rejected 情况。 |
| `_target_present_rows.csv` | target-present 模拟逐帧明细。 |
| `_target_absent_rows.csv` | target-absent 模拟逐帧明细。 |
| `_present_gate_grid.csv` | 目标存在时的双阈值网格结果。 |
| `_absent_gate_grid.csv` | 目标缺席时的双阈值网格结果。 |
| `_bbox_gate_summary.csv` | bbox gate 汇总结果。 |
| `_bbox_gate_rows.csv` | bbox gate 逐样本明细。 |
| `_bbox_reject_reasons.csv` | bbox gate 拒绝原因统计。 |

## 结果解读口径

不要只看 Top-1。对于跟随购物车，更重要的是：

```text
target-present:
  present_accept_rate
  present_accept_acc
  present_true_accept_rate

target-absent:
  absent_false_accept_rate
  absent_reject_rate
```

其中：

- `present_accept_rate`：目标在场时系统敢不敢确认。
- `present_accept_acc`：已经确认的样本中是否选对了目标。
- `present_true_accept_rate`：所有目标在场帧中，被正确确认的比例。
- `absent_false_accept_rate`：目标不在场时，是否误把路人当目标。

工程上宁可进入 `FOLLOW_CAUTION / IDENTITY_UNCERTAIN / STOP`，也不能在目标缺席时仅凭 ReID 恢复 `FOLLOW`。

## Git 与隐私边界

可以提交：

- `README.md`
- `docs/`
- 自研脚本，例如 `simulate_target_follow_v2.py`、`simulate_target_follow_with_bbox_v1.py`
- 必要的小型配置或说明文件

不要提交：

- `images/`
- `images_openbot_clean/`
- `outputs/`
- `weights/`
- `__pycache__/`

原因：

- `images/` 和 `images_openbot_clean/` 可能包含私人照片。
- `outputs/` 可能包含由私人照片导出的结果和路径。
- `weights/` 文件大，且模型来源需要单独管理。

## 上游参考

- `deep-person-reid/` 原始项目：https://github.com/KaiyangZhou/deep-person-reid

本仓库中的 `deep-person-reid/` 仅作为团队本地参考和复现基础。若后续修改其中源码，应按本仓库普通目录处理，而不是 submodule 流程。
