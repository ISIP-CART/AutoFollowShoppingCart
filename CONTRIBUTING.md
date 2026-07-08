# 协作与 Git 工作流程

本文面向项目组所有成员，记录本仓库和 `dev/OpenBot` 子模块的固定协作流程。原则是：主仓库记录课程文档、设计材料和 OpenBot 子模块指针；OpenBot Android / firmware 代码改动先在 `dev/OpenBot` 子仓库中提交，再回到主仓库提交新的 submodule 指针。

## 1. 每次开始工作前

先回到主仓库，确认基于最新主分支创建自己的工作分支：

```bash
cd E:\THU\2026Summer\AutoFollowShoppingCart
git switch master
git pull
git checkout -b your-branch-name
```

分支命名建议：

- 文档：`docs/xxx` 或 `codex/docs-xxx`
- Android：`android/xxx`
- 硬件 / 固件：`firmware/xxx`
- 采购 / 测试：`docs/procurement-xxx` 或 `test/xxx`

不要直接在 `master` 上提交日常改动。

## 2. 首次克隆或同步子模块

首次克隆主仓库后，或主仓库更新了 submodule 指针后，执行：

```bash
git pull
git submodule sync --recursive
git submodule update --init --recursive
```

当前 OpenBot 子模块位置：

```text
E:\THU\2026Summer\AutoFollowShoppingCart\dev\OpenBot
```

Android Studio 打开：

```text
E:\THU\2026Summer\AutoFollowShoppingCart\dev\OpenBot\android
```

## 3. 修改主仓库文档或设计材料

如果只修改 `README.md`、`design/`、采购记录、测试记录等主仓库内容：

```bash
cd E:\THU\2026Summer\AutoFollowShoppingCart
git status
git add README.md design/ CONTRIBUTING.md
git commit -m "Update project documentation"
```

提交后按团队约定发起 PR；除非已经确认，不要直接推到 `master`。

如果这次还涉及上位机规划，请顺手检查下面几份文档是否需要一起同步：

- `design/自主跟随购物车上位机软件开发计划.md`
- `design/上位机软件开发 Phase 2——修正跟随距离控制计划书.md`
- `design/障碍处理计划书.md`
- `design/ReID-deep-research-report.md`

## 4. 修改 OpenBot Android 工程

> **上位机开发进度**：修改 Human Cart Simulator 代码后，请同步更新 `dev/OpenBot/android/cartfollow-devlog.md`。

如果要改 OpenBot Android 工程，先进入子仓库并切到团队开发分支：

```bash
cd E:\THU\2026Summer\AutoFollowShoppingCart\dev\OpenBot
git switch shopping-cart-dev
git pull
```

然后用 Android Studio 打开：

```text
E:\THU\2026Summer\AutoFollowShoppingCart\dev\OpenBot\android
```

修改并测试后，先在 `dev/OpenBot` 子仓库提交并推送：
```bash
git status
git add android/你改过的文件
git commit -m "Adapt OpenBot Android app for shopping cart"
git push
```

## 5. 回到主仓库提交 submodule 指针

OpenBot 子仓库提交并 push 后，回到主仓库：

```bash
cd E:\THU\2026Summer\AutoFollowShoppingCart
git status
```

如果看到类似：

```text
modified: dev/OpenBot (new commits)
```

说明主仓库检测到 `dev/OpenBot` 指向了新的 OpenBot commit。此时提交这个指针：

```bash
git add dev/OpenBot
git commit -m "Update OpenBot submodule"
```

固定顺序必须是：

1. 先提交并 push `dev/OpenBot` 子仓库。
2. 再提交 AutoFollowShoppingCart 主仓库里的 `dev/OpenBot` submodule 指针。

如果顺序反了，队友拉主仓库时可能拿不到对应的 OpenBot commit。

## 6. 队友同步你的改动

等你的 PR 合并进 `master` 后，队友在主仓库执行：

```bash
cd E:\THU\2026Summer\AutoFollowShoppingCart
git switch master
git pull
git submodule sync --recursive
git submodule update --init --recursive
```

如果队友也要继续改 OpenBot：

```bash
cd dev/OpenBot
git fetch origin
git switch shopping-cart-dev
git pull
```

## 7. 提交前自检

提交前至少确认：

- `git status` 中没有误提交本地工具配置、临时文件、构建产物。
- 文档改动同时检查 `README.md`、`design/structure.md` 和相关补充文档是否口径一致。
- OpenBot 代码改动已经在 `dev/OpenBot` 子仓库中提交。
- 主仓库只记录 OpenBot 的 submodule 指针，不把 OpenBot 源码复制进主仓库。
- 不要误提交 `tools/reid_pc_test/images/`、`tools/reid_pc_test/outputs/`、`tools/reid_pc_test/weights/`。
- 如果修改了 ReID 研究脚本或上位机计划，请确认隐私相关目录仍然被 `.gitignore` 正确忽略。
