# macOS 开发端与 Linux 运行端

## macOS 开发端

用途：

- 编写和审查代码
- 运行核心模块的静态检查和本地验证
- 使用模拟输入或已保存的 RGB-D 回放
- 检查 VLM 输入输出和实验日志
- 进行提示词、记忆和评价逻辑迭代

macOS 不作为真实 D455f 实验的默认运行平台，也不承担车辆控制。

## Linux 运行端

用途：

- 连接 Intel RealSense D455f
- 加载 RealSense 采集适配器
- 运行实时 RGB-D 采集
- 调用远程 VLM API 或本地模型
- 运行本地网页交互界面
- 后续连接小车和云台执行适配器

## 代码边界

```text
core/
  不依赖操作系统、相机 SDK、ROS 或具体 VLM

adapters/
  realsense/       Linux 运行端可选
  vlm_remote/      macOS 和 Linux 均可使用
  vlm_local/       取决于 Linux 本地模型环境
  human_executor/  macOS 和 Linux 均可使用
  vehicle/         Linux 运行端可选

replay/
  macOS 和 Linux 均可使用

ui/
  本地网页服务，macOS 和 Linux 均可使用
```

## 迁移规则

1. macOS 先生成可移植的 episode 数据和配置示例。
2. 复制或克隆仓库到 Linux。
3. 只在 Linux 安装和验证 RealSense 运行依赖。
4. 用同一 episode 回放检查实时适配器和离线行为是否一致。
5. 真实相机实验生成的新数据可以复制回 macOS 做分析。

## D455f 适配器

`reasonnav_stage1.camera.RealSenseD455fCamera` 只在调用 `start()` 时加载 `pyrealsense2`。因此 macOS 可以导入和测试核心代码而不安装 RealSense SDK；真实 D455f 采集必须在 Linux 运行端完成。
