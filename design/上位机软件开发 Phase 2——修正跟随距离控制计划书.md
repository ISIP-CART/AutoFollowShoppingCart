# 自主跟随购物车项目——阶段2：距离控制方案设计（推荐方案）

> 更新时间：2026-07-06
> 适用阶段：上位机软件开发 Phase 2——修正跟随距离控制
> 当前推荐方案：**初始化距离标定 + 图像伺服（Image-based Visual Servoing）**

---

# 1. 设计背景

目前项目的软件开发计划中，距离估计采用的是多特征融合方案：

```text
target_distance_proxy =
    w1 * bbox_height_proxy
  + w2 * bbox_area_proxy
  + w3 * bbox_bottom_proxy
  + w4 * monocular_depth_proxy
  + w5 * temporal_prediction
```

虽然这种方法理论上能够融合多种信息，但存在几个明显问题：

1. **缺乏物理尺度来源。**

单目 RGB 图像天然无法恢复真实尺度，因此不存在一个天然准确的"距离"。

换句话说：

> 不是权重调得不好，而是输入本身就没有足够信息恢复绝对距离。

---

2. **不可解释。**

如果距离控制效果不好，很难判断原因：

* bbox高度失真？
* bbox面积变化？
* 深度模型错误？
* 时序预测漂移？
* 权重设置问题？

最终只能不停调参数。

---

3. **训练成本高。**

若希望学习这些权重，就必须采集大量带真实距离标签的数据：

```
bbox特征
↓

真实距离

↓

监督学习
```

但是：

* 数据采集困难；
* 泛化能力未知；
* 首版项目成本过高。

因此，这条路线并不适合作为首版主要方案。

---

# 2. 核心设计思想

## 2.1 不追求"测出真实距离"

购物车真正需要解决的问题其实不是：

> 用户距离我1.03米还是0.94米？

真正需要的是：

> 用户是不是比刚才更远了？

以及：

> 我现在应该前进还是停止？

因此：

首版目标应从：

```
估计真实距离（Meter）
```

转变为：

```
估计距离状态（Distance State）
```

输出：

```
TOO_FAR
OK
TOO_CLOSE
UNKNOWN
```

而不是连续的米数。

---

## 2.2 图像伺服（Image-based Visual Servoing）

机器人视觉中有一种经典思想：

**Image-based Visual Servoing（IBVS）**

其核心思想并不是恢复世界坐标，而是：

> 控制机器人，使目标始终保持在图像中的期望位置。

对于购物车来说，更适合控制：

* bbox高度
* bbox面积
* bbox位置

保持接近初始化时的状态。

因此：

距离控制实际上变成：

> 保持图像尺度不变。

---

# 3. 推荐方案：初始化距离标定

## 3.1 初始化流程

用户点击：

```
开始跟随
```

之后：

```
用户站在期望距离（约1m）

↓

系统完成目标确认

↓

记录当前图像状态
```

保存：

```text
desired_bbox_height_ratio

desired_bbox_area_ratio

desired_bbox_bottom_ratio

(optional)
desired_depth_proxy
```

注意：

这里记录的是：

> 图像尺度

不是：

> 真实距离。

---

## 3.2 后续控制

每帧计算：

```text
height_scale =
current_height
/
desired_height
```

面积：

```text
area_scale =
sqrt(current_area
/
desired_area)
```

bbox底部：

```text
bottom_shift =
current_bottom
-
desired_bottom
```

系统不断比较：

```
现在

VS

初始化
```

即可判断：

```
是不是远了？
```

而不需要恢复真实距离。

---

# 4. Distance State

系统最终输出四种状态：

```
TOO_FAR

OK

TOO_CLOSE

UNKNOWN
```

例如：

```
height_scale < 0.85

↓

TOO_FAR
```

```
0.85~1.15

↓

OK
```

```
>1.15

↓

TOO_CLOSE
```

如果：

* 遮挡严重
* bbox异常
* 姿态变化过大

则：

```
UNKNOWN
```

系统停车。

---

# 5. 为什么这种方案更适合购物车？

因为购物车不是自动驾驶。

购物车真正需要的是：

```
保持舒适距离
```

而不是：

```
精确恢复三维坐标
```

例如：

如果目标：

```
越来越小
```

那么：

```
慢慢向前
```

如果：

```
越来越大
```

那么：

```
停止
```

其实已经足够。

---

# 6. Ground Plane Distance（第二阶段增强）

虽然图像伺服已经足够完成首版，但仍建议预留一个更具有物理意义的距离估计模块：

```
GroundPlaneDistanceEstimator
```

思想：

利用：

* 相机高度
* 手机安装角度
* 相机内参
* 地面平面

将：

```
bbox bottom
```

映射到：

```
地面距离
```

优点：

* 不依赖用户身高
* 不依赖衣服颜色
* 不依赖ReID
* 可得到近似米制距离

缺点：

必须能够看到：

```
脚

或者

bbox底部对应地面
```

因此建议：

作为第二阶段增强。

---

# 7. 为什么不推荐一开始做深度估计？

目前主流：

* MiDaS
* Depth Anything
* Metric3D
* ZoeDepth
* Depth Pro

虽然越来越优秀，

但是：

首版项目存在几个问题：

## （1）算力压力

手机同时运行：

```
Person Detection

+

ReID

+

Depth

+

Control
```

压力较大。

---

## （2）仍然存在尺度问题

多数模型输出：

```
Relative Depth
```

不是：

```
Absolute Meter
```

仍需要标定。

---

## （3）难以调试

如果距离不准：

很难判断：

* 深度模型错误？
* bbox错误？
* 参数错误？

因此：

建议：

深度模型只作为：

```
辅助信息
```

而不是主要距离来源。

---

# 8. 为什么不推荐直接训练权重？

如果训练：

```
w1

w2

w3

...
```

首先需要：

大量真实标签：

```
图像

↓

真实距离
```

数据采集工作巨大。

而且：

即使训练完成，

也很难解释：

为什么今天突然跟远了。

因此：

首版不建议。

---

# 9. 推荐的软件结构

建议将原来的：

```
FusedDistanceEstimator
```

修改为：

```text
DistanceEstimator
│
├── ImageSetpointDistanceEstimator
│
├── GroundPlaneDistanceEstimator
│
├── MonocularDepthDistanceEstimator
│
├── MarkerDistanceEstimator（调试用）
│
└── DistanceStateFusion
```

每个估计器统一输出：

```text
value

state

confidence

failure_reason
```

例如：

```
GroundPlane

value = 1.05m

state = OK

confidence = 0.82
```

```
BBoxScale

value = 0.91

state = TOO_FAR

confidence = 0.73
```

最后由：

```
DistanceStateFusion
```

决定最终状态。

---

# 10. 控制策略

控制器不直接根据距离数值控制。

而是根据：

```
DistanceState
```

控制。

例如：

```
UNKNOWN

↓

停车
```

```
TOO_CLOSE

↓

停车
```

```
OK

↓

停止前进
```

```
TOO_FAR

↓

低速前进
```

随后：

结合：

```
目标中心偏差
```

完成左右转向即可。

---

# 11. Human Cart Simulator新增显示内容

建议增加：

```
Height Scale

Area Scale

Bottom Shift

Distance State

Distance Confidence
```

实时观察：

```
TOO_FAR

OK

TOO_CLOSE

UNKNOWN
```

方便调试。

---

# 12. 后续研究路线

建议按以下顺序推进：

## 第一阶段

完成：

```
ImageSetpointDistanceEstimator
```

验证：

```
TOO_FAR

OK

TOO_CLOSE
```

是否稳定。

---

## 第二阶段

加入：

```
GroundPlaneDistanceEstimator
```

提升距离估计可信度。

---

## 第三阶段

加入：

```
Depth Anything

MiDaS
```

仅作为：

辅助信息。

---

## 第四阶段

若效果仍不足：

考虑：

```
Metric3D

Depth Pro

ZoeDepth
```

或者：

增加：

```
ToF

超声波
```

作为安全冗余。

---

# 13. 最终方案总结

经过分析，本项目距离控制模块建议采用：

> **初始化距离标定 + 图像伺服（Image-based Visual Servoing）** 作为首版核心方案。

其设计原则如下：

1. 不追求精确恢复真实米制距离，而是稳定判断距离状态。
2. 初始化时记录目标在期望跟随距离下的图像尺度。
3. 后续持续保持目标图像尺度接近初始化状态。
4. 输出统一的 Distance State（TOO_FAR / OK / TOO_CLOSE / UNKNOWN）。
5. Ground Plane Distance 作为第二阶段增强。
6. 单目深度估计仅作为辅助信息，不参与首版核心控制。
7. 所有距离估计模块均输出置信度，由 DistanceStateFusion 统一仲裁。
8. 当距离状态不可信时，系统优先停车，而不是继续跟随。

相比于多权重线性融合方案，该方案具有以下优势：

* 更符合机器人视觉控制思想；
* 不需要大量训练数据；
* 可解释性强；
* 参数调试简单；
* 更容易定位问题来源；
* 更符合首版购物车项目的工程需求；
* 为后续引入 Ground Plane、单目深度和外部传感器保留良好的扩展接口。
