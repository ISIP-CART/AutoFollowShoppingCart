# ReID PC Test Workspace

`tools/reid_pc_test/` 是团队共享的 PC 端 ReID 调研与测试工作区。它的作用不是部署 Android 代码，而是在正式接入 OpenBot 之前，用可重复的脚本验证 ReID 模型、gallery 策略、目标缺席误接受风险、bbox 连续性门控等工程问题。

当前首版方向：

```text
model: osnet_x0_25
weight: osnet_x0_25_market1501.pth
gallery: diverse confirmedGallery(k=8)
role: ReID 作为身份置信度辅助，不作为独立身份判决器
current focus: Android 已实现 track/bbox gate、恢复后 relock、非 locked 空间支持门控与诊断日志开关；下一步采集新版 cartfollow_diagnostics 并用 compare 验证 blocker 是否下降
```

2026-07-09 最新焦点：

```text
Android ReID 已在 Human Cart Simulator 中跑通；
ReID crop 已修正为 upright 输入；
新旧 cartfollow_diagnostics 对比显示 upright 修正有效；
track/bbox gate 小步修正已进入 Android 代码；
Human Cart Simulator 已新增“记录日志”开关，默认不写 diagnostics；
下一轮重点检查 candidate_switch_penalty、belief_high_bbox_failed、recovered_rate、非目标转绿和 hard_stop_count。
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
| `simulate_state_machine_replay_v1.py` | 当前可用 | 初版状态机回放。把 bbox gate rows 串成证据流，检查是否会错误恢复 `FOLLOW`、过度 STOP 或长时间不确定。 |
| `simulate_chronological_session_replay_v1.py` | 当前可用 | 按真实 session 时间顺序回放。用同一人的前若干帧建 gallery，后续帧连续作为 probe，并支持人工缺失段和干扰者插入。 |
| `simulate_sequence_session_replay_v1.py` | 当前可用 | 回放 Android `PersonSequenceCollector` 采集的真实时序数据。读取 `frame_log.csv`、`detections.csv`、`events.csv` 和 crop，评估真实无人帧、多检测框、人工事件下的 ReID + bbox + 状态机行为。 |
| `analyze_cartfollow_diagnostics_v1.py` | 当前可用 | 分析 Human Cart Simulator 诊断日志。支持单目录分析和 `--compare-roots old=...,new=...` 新旧对比，输出恢复结果、blocker flags、gallery quality 和 upright crop 修正效果报告。 |
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

### 6. 状态机回放

```powershell
python simulate_state_machine_replay_v1.py ^
  --rows outputs\openbot_follow_x025_g8_d2_bboxgate_pred_bbox_gate_rows.csv ^
  --output-prefix openbot_follow_x025_g8_d2_state_replay
```

较宽松 timeout 对照：

```powershell
python simulate_state_machine_replay_v1.py ^
  --rows outputs\openbot_follow_x025_g8_d2_bboxgate_pred_bbox_gate_rows.csv ^
  --output-prefix openbot_follow_x025_g8_d2_state_replay_tuned ^
  --identity-timeout 20 ^
  --search-timeout 20
```

用途：

- 回放 `FOLLOW_CONFIDENT / FOLLOW_CAUTION / REACQUIRE_TARGET / LOST_SEARCH / IDENTITY_UNCERTAIN / STOP`。
- 检查目标缺席时是否会错误恢复 `FOLLOW`。
- 检查目标存在时是否过度进入 `STOP`。
- 注意：当前输入 rows 来自随机抽样模拟，不是真实连续视频轨迹，因此 `over_stop_rate` 更适合作为压力测试信号，不能直接等同真实跟随表现。

### 7. 连续 session 时间顺序回放

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

人工目标缺失 + 干扰者插入：

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

用途：

- 用真实 session 的 `timestamp_ms / frame_id` 顺序替代随机抽样 rows。
- 验证连续目标存在时是否还能稳定保持 `FOLLOW_CONFIDENT / FOLLOW_CAUTION`。
- 验证人工缺失段和插入干扰者时是否会错误恢复 `FOLLOW`。
- 为后续 Android `PersonSequenceCollector / SEQUENCE` 数据格式提供 PC 侧回放入口。

### 8. Android sequence 真实时序回放

基础命令：

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

更接近真实控制循环的无人帧推进版本：

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

用途：

- 直接读取 `PersonSequenceCollector` 导出的真实序列目录。
- 用前若干秒单人稳定 crop 自动构建 gallery。
- 将 `target_left/target_return`、`distractor_enter/distractor_leave`、`occlusion_start/occlusion_end` 展开成分析窗口。
- 对每个有 crop 的采样帧执行 ReID 打分、bbox 连续性计算和状态机回放。
- 输出额外的 `_diagnostic_summary.csv`，把 `pre_stop` 和 `at_or_post_stop` 分开，避免把终态 `STOP` 后的尾段误读成算法一直过度停车。
- `--missing-frame-policy advance_empty` 会让 `num_persons=0` 的无人帧推进 `LOST_SEARCH / STOP` 计时，更接近真实 Android 控制循环；默认 `hold` 主要用于和旧结果对照。

当前真实 sequence 结论：

- `yrc_seq_20260707_140056`：安全性成立，没有目标缺席时错误恢复 `FOLLOW`；高 over-stop 主要来自终态 `STOP` 后尾段。
- `yrc2_seq_20260707_152237`：流程更清晰，包含目标离开、无人帧、返回、干扰者、遮挡；暴露出“目标返回后看到了人，但恢复条件过严，容易卡在 `IDENTITY_UNCERTAIN` 后 STOP”的问题。
- 加入 `advance_empty` 后，无人帧会更真实地推进搜索超时；这说明后续不能只调大 timeout，还要设计更主动的 `LOCAL_SEARCH / REACQUIRE` 恢复路径。
- 宽松恢复条件对照中，`stop_count=0`、`over_stop_rate=0`、`final_state=FOLLOW_CAUTION`，且 `wrong_recovery_count=0`。这说明“安全前提下更主动恢复”是可行方向。

### 9. Human Cart Simulator 诊断日志分析

默认分析最新诊断目录：

```powershell
python analyze_cartfollow_diagnostics_v1.py
```

指定新旧数据对比：

```powershell
python analyze_cartfollow_diagnostics_v1.py ^
  --compare-roots old=images/cartfollow_diagnostics_old,new=images/cartfollow_diagnostics ^
  --output outputs/cartfollow_diagnostics_analysis/compare
```

用途：

- 汇总每个诊断 session 的 state/action/persons/fps/ReID/belief/bbox gate。
- 对每次 `target_return` 输出 `recovered_fast / recovered_slow / not_recovered_in_window / hard_stop_before_return`。
- 同时输出 frame 差值和 ms 差值，避免只看 frame_id 误判恢复时间。
- 标记 blocker flags：`belief_high_bbox_failed`、`bbox_gate_lag`、`candidate_switch_penalty`、`reid_low_or_margin_low`、`no_visible_track`。
- 区分 `gallery_candidate` 和 `confirmed_snapshot`；只有 `gallery_candidate` 算作 ReID gallery 输入质量。

当前新旧对比结论：

| 数据 | target_return | recovered_rate | hard_stop_count | best_score_mean | margin_mean | bbox_default_ok_rate | gallery_candidate_landscape_rate |
|---|---:|---:|---:|---:|---:|---:|---:|
| old | 11 | 0.5455 | 2 | 0.5017 | 0.3431 | 0.4451 | 1.0000 |
| new | 16 | 0.8750 | 0 | 0.5992 | 0.4611 | 0.5485 | 0.0000 |

解释：

- `reid_crop_upright=true` 后，gallery candidate 已从横向输入变成竖向输入，ReID 分数和恢复率都有改善。
- 新数据中不再以 hard STOP 为主要问题。
- 剩余主要 blocker 是 `candidate_switch_penalty` 和 `belief_high_bbox_failed`；下一轮应优先修 track association、locked track 保护、分状态 bbox gate，而不是继续盲目调 ReID 阈值。

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
| `_state_replay_summary.csv` | 状态机回放汇总，包含 wrong follow recovery、over stop、uncertain duration 等。 |
| `_state_replay_transitions.csv` | 状态机转换明细。 |
| `_state_replay_frame_rows.csv` | 状态机逐帧回放明细。 |
| `_chronological_summary.csv` | 连续 session 回放汇总，包含 wrong follow、over stop、uncertain、reacquire 等。 |
| `_chronological_transitions.csv` | 连续 session 中的状态转换明细。 |
| `_chronological_frame_rows.csv` | 连续 session 逐帧回放明细。 |
| `_data_quality.csv` | sequence replay 数据质量检查，包含 frame/detection/event/crop 数量和缺失 crop 统计。 |
| `_diagnostic_summary.csv` | sequence replay 分段诊断，包含 `all_reid`、`pre_stop`、`at_or_post_stop` 和 `post_stop_only`。 |
| `_summary.csv` / `_transitions.csv` / `_frame_rows.csv` | sequence replay 的汇总、状态转换和逐帧明细；文件名前缀由 `--output-prefix` 决定。 |
| `diagnostic_compare_summary.csv` | Human Cart diagnostic 新旧根目录对比汇总。 |
| `diagnostic_return_comparison.csv` | 每次 `target_return` 的 outcome、blocker flags、恢复帧数和恢复时间。 |
| `diagnostic_upright_effect_report.md` | upright crop 修正前后效果报告。 |
| `diagnostic_gallery_quality.csv` | gallery candidate / confirmed snapshot 的尺寸和质量标签。 |

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

最新 sequence replay 还需要额外区分：

- `STOP` 与 `motion_stop` 不应混为一谈。`motion_stop` 表示禁止前进但继续观察/搜索；`STOP` 应是搜索失败后的兜底终态。
- 无人帧必须推进丢失/搜索计时，否则 PC 回放会低估目标离开的影响。
- 目标返回后若出现连续多帧 `ReID + bbox + prediction` 稳定证据，应允许进入 `REACQUIRE_TARGET`，而不是一直卡在 `IDENTITY_UNCERTAIN`。

## Git 与隐私边界

可以提交：

- `README.md`
- `docs/`
- 自研脚本，例如 `simulate_target_follow_v2.py`、`simulate_target_follow_with_bbox_v1.py`、`simulate_state_machine_replay_v1.py`、`simulate_chronological_session_replay_v1.py`、`simulate_sequence_session_replay_v1.py`
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

## 当前 Android 接入状态（2026-07-08）

PC 侧 ReID 调研已进入 Android 实机验证阶段：

- `osnet_x0_25_market1501.pth` 已成功导出为 Android 可加载的 float32 TFLite 测试资产。
- Android 端模型输入为 `[1,3,256,128]`，输出为 `[1,512]`。
- 最新 Human Cart Simulator 中 `reidAvailable=true`，debug 面板 ReID 字段显示正常。
- 手机实测帧率约 30 FPS，首版 TFLite ReID 调度性能可接受。

本地模型文件位置：

```text
dev/OpenBot/android/robot/src/main/assets/networks/reid/osnet_x0_25_market1501.tflite
```

注意：该文件仍属于本地测试资产，不提交到版本库。

当前实机结论：

```text
ReID 已能作为身份线索运行；
但单帧 ReID / margin / bbox gate 仍不足以保证不跟错人；
目标返回后的重捕获有时偏慢或无法确认；
下一步应从“每帧选最像的人”升级为“维护目标 track 与身份 belief”。
```

建议下一步主线：

1. 在 Android Human Cart Simulator 中新增 `TargetTrackManager`，用 bbox IoU / center distance / area ratio 做短时 track 关联。
2. 新增 `IdentityBeliefAccumulator`，将 ReID、bbox 连续性、prediction、候选切换次数累积为 `targetBelief`。
3. 状态机只允许稳定 track + 稳定 belief 触发 `REACQUIRE_TARGET -> FOLLOW`，不允许单帧高分直接恢复前进。
4. debug 面板新增 `trackId / trackAge / missedFrames / targetBelief / beliefReason`。

PC 侧后续仍保留价值，但主要用于离线复盘和参数对照；主线验证应优先在 Android Human Cart Simulator 中进行。

最新诊断分析结论：

```text
upright crop 修正已经有效；
继续只调 ReID bestScore/margin 的收益有限；
下一步更应围绕 trackId 稳定、candidate switch 惩罚、lockedTrack 保护和分状态 bbox gate 做 Android 策略修正。
```
