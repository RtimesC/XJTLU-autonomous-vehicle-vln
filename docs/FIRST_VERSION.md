# 第一版交付范围

## 已交付能力

1. 平台无关的导航数据契约：目标、RGB-D 观察、深度摘要、导航意图、执行反馈和历史记忆。
2. macOS 可运行的 JSONL 离线回放。
3. 确定性的模拟 VLM，支持在没有相机和网络的情况下验证闭环。
4. OpenAI-compatible 远程 VLM 客户端，未绑定具体厂商或 API key。
5. Intel RealSense D455f 的 Linux 运行端适配器，依赖懒加载。
6. 人工执行反馈和 JSON 运行记录持久化。
7. localhost 本地网页交互界面。
8. macOS 开发端和 Linux 运行端边界文档。

## 第一版不包含

- 在当前 macOS 上安装或验证 RealSense SDK
- 真实 API key 或远程 API 调用
- SLAM、Nav2、车辆控制和云台控制
- 自动识别全部地标的完整检测模型
- 生产级权限、并发控制和长时间运行服务

## 验证命令

```text
PYTHONPATH=src python scripts/verify_first_version.py
```

本地回放界面：

```text
PYTHONPATH=src python scripts/run_web.py \\
  --input examples/replay_episode.jsonl \\
  --goal 4205
```
