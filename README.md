# ReasonNav Stage 1 Navigation Research

第一阶段研究项目：人携带 Ubuntu 电脑和 RGB-D 相机移动，系统结合视觉、深度信息和历史记忆生成单步导航意图，由人执行并反馈结果。

## 当前范围

- 人在回路中的 RGB-D 视觉语言导航实验
- 单步决策、单步执行、单步反馈
- 可回放的观测、记忆、决策和执行日志
- 为未来小车底盘和云台保留执行适配接口

## 暂不固定

- 具体 RGB-D 相机型号和 SDK
- VLM 服务或本地模型
- 小车消息接口和连续速度参数
- SLAM、Nav2 和车辆控制

## 目录

```text
src/reasonnav_stage1/   稳定的核心数据契约
adapters/               相机、VLM、人工执行器和车辆执行器（后续添加）
docs/                   范围、决策和实验协议
runs/                   实验运行数据（不提交原始大文件）
```

第一版核心代码不依赖外部 Python 包，先用模拟或离线回放数据验证流程。

## 开发端与运行端

本项目采用 macOS 开发、Linux 运行的双端结构。macOS 负责代码和离线回放；Linux 负责 D455f 实时采集、VLM 运行和未来车辆适配。核心代码不依赖操作系统专用组件，平台依赖只放在可选适配器中。详见 [docs/DEVELOPMENT_RUNTIME.md](docs/DEVELOPMENT_RUNTIME.md)。

## 第一版本地运行

macOS 或 Linux 均可使用示例回放启动本地交互界面：

```text
PYTHONPATH=src python scripts/run_web.py \\
  --input examples/replay_episode.jsonl \\
  --goal 4205
```

浏览器打开 `http://127.0.0.1:8765`。当前界面使用确定性的模拟 VLM；接入远程 API 和 D455f 时替换对应适配器，不改变交互流程。
