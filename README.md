# XJTLU Autonomous Vehicle VLN

面向 XJTLU 自动驾驶小车的独立端到端视觉语言导航（Vision-Language Navigation, VLN）科研仓库。

本项目研究由前视 RGB 图像、自然语言指令和有限历史信息驱动的策略，使其直接预测底盘线速度、角速度与停止决策。项目不把 VLN 简化为 Nav2 目标点或路径生成器。

## 当前状态

- 研究阶段：v0.1 范围与接口定义
- 运行状态：尚无可运行模型或 ROS 2 节点
- 实车状态：尚未验证，不得用于车辆控制

## 文档

- [研究范围](research_scope.md)
- [ROS 2 接口契约](docs/ros_interface_contract.md)

## 与原车仓库的关系

`XJTLU-autonomous-vehicle-rtk` 继续拥有传感器驱动、TF、底盘串口、STM32 固件、传统定位导航基线和车辆级安全。本仓库作为 ROS 2 overlay，拥有 VLN 数据、模型、策略运行时、VLN 专属安全适配和实验评测。

两个仓库之间只通过版本化 ROS 接口和明确的兼容版本连接，不复制原车驱动与固件代码。

