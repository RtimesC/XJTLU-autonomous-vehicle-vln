# VLN ROS 2 接口契约

状态：v0.2 控制链实现，ROS 2 与实车仍待目标环境验证

目标平台：ROS 2 Humble

更新日期：2026-09-14

## 1. 目的

本契约定义 VLN 策略、ROS 运行时、安全层、车辆控制仲裁器和离线评测之间的稳定边界。接口设计必须同时支持在线运行、rosbag 回放、shadow mode 和实验复现。

本契约只定义 VLN 侧候选动作。最终车辆控制权、底盘串口和 STM32 固件由原车仓库负责。

## 2. 节点职责

| 节点 | 所属仓库 | 职责 | 明确禁止 |
|---|---|---|---|
| `vln_policy_node` | VLN | 图像和指令编码、历史状态、模型推理 | 发布 `/cmd_vel`、读取地图或 Nav2 路径；自行生成 episode ID |
| `vln_action_adapter` | VLN | 将策略动作转换为带上下文速度候选，执行停止阈值 | 规划路径、隐藏修改原始动作 |
| `vln_safety_node` | VLN | 限幅、加速度约束、超时和紧急停车 | 自动选择绕障方向 |
| `vln_episode_manager` | VLN | episode 生命周期、指令与结果记录 | 根据真实位置替模型触发正常停止 |
| `vln_evaluator` | VLN | 使用真值计算指标 | 向在线策略回传真值或导航提示 |
| `command_arbiter` | 原车 | VLN、Nav2、遥控和急停之间的唯一控制权仲裁 | 同时放行多个控制源 |
| `serial_twistctl_node` | 原车 | 将最终 `/cmd_vel` 转发至 STM32 | 解释语言或修改导航策略 |

## 3. 命名空间与主数据流

所有 VLN 专用在线接口使用 `/vln` 命名空间：

```text
/vln/input/image
    -> vln_policy_node
    -> /vln/policy_action
    -> vln_action_adapter
    -> /vln/raw_cmd_vel (`VlnCommand`)
    -> vln_safety_node
    -> /vln/safe_cmd_vel (`VlnCommand`)
    -> command_arbiter
    -> /cmd_vel
    -> serial_twistctl_node
```

物理相机 topic 必须 remap 到 `/vln/input/image`，模型配置和源代码不得依赖某个相机厂商的默认 topic 名称。

## 4. 自定义接口

### 4.1 `vln_interfaces/msg/PolicyAction.msg`

暂定字段：

```text
std_msgs/Header header
string episode_id
uint64 sequence_id

float32 linear_velocity
float32 angular_velocity
float32 stop_probability

float32 inference_latency_ms
bool valid
string model_version

uint8 outcome
string outcome_detail
uint8 OUTCOME_RUNNING = 0
uint8 OUTCOME_STOP_REQUESTED = 1
uint8 OUTCOME_FAILED = 2
```

语义：

- `header.stamp`：产生本次动作的主图像观测时间，不是消息发布时刻；
- `header.frame_id`：固定为 `base_link`；
- `linear_velocity`：m/s，正值表示沿 `base_link` x 轴前进；
- `angular_velocity`：rad/s，正值遵循 ROS REP-103，表示左转；
- `stop_probability`：范围 `[0, 1]`；
- `inference_latency_ms`：从输入张量准备完成到模型输出完成的单调时钟耗时；
- `valid=false`：动作不得继续进入速度适配链路；
- `model_version`：可追溯到模型配置与权重摘要，不得只写可变的 `latest`。

任何 NaN、Inf、越界停止概率、错误 frame、未知 outcome 或 episode ID 不匹配均视为无效动作。

`OUTCOME_FAILED` 表示策略无法完成任务，必须进入失败结果，不能通过 `p_stop=1` 模拟停车。

### 4.2 `vln_interfaces/msg/EpisodeControl.msg`

由 episode manager 发布到 `/vln/episode_control`，包含完整 `episode_id`、instruction 和 `START/CANCEL/TERMINATE` 命令。所有 policy、adapter 和 safety 节点必须使用该 ID，不得重新生成。

### 4.3 `vln_interfaces/msg/EpisodeEvent.msg`

adapter 在停止确认或策略失败时发布 `/vln/episode_event`。事件包括 `EVENT_STOP_LATCH` 和 `EVENT_POLICY_FAILED`，episode manager 只根据这些事件完成或失败 episode。

### 4.4 `vln_interfaces/msg/VlnCommand.msg`

候选和安全命令使用带 `episode_id`、`policy_sequence_id`、原始 `Header` 与 `geometry_msgs/Twist` 的 envelope，确保速度命令转换后仍可追溯到策略动作。

### 4.5 `vln_interfaces/msg/SafetyStatus.msg`

暂定字段：

```text
std_msgs/Header header
string episode_id
uint64 action_sequence_id

bool command_accepted
bool command_modified
bool emergency_stop
bool policy_timeout
bool human_takeover

uint8 reason_code
string reason_detail
```

`reason_code` 必须使用消息内定义的稳定枚举，至少覆盖：正常、速度限幅、加速度限幅、动作无效、动作过期、策略超时、近障停车、人工接管、控制权丢失和内部错误。

`reason_detail` 只用于人类诊断，指标统计必须依据 `reason_code`，不能解析自由文本。

### 4.6 `vln_interfaces/action/NavigateLanguage.action`

暂定定义：

```text
# Goal
string episode_id
string instruction
---
# Result
bool completed
string termination_reason
float32 elapsed_time_s
---
# Feedback
string state
uint64 latest_action_sequence_id
float32 latest_stop_probability
```

约束：

- `episode_id` 在一次实验中必须唯一；
- 新 goal 到达时不得静默覆盖正在运行的 episode；
- cancel 必须导致候选速度归零并释放控制权；
- `completed=true` 只表示 episode manager 接受了模型停止决定，不等于离线裁判已经判定成功；
- 真正的实验成功由 evaluator 根据预注册场景协议离线计算。

## 5. Topic 契约

| Topic | 类型 | 发布者 | 订阅者 | 建议 QoS |
|---|---|---|---|---|
| `/vln/input/image` | `sensor_msgs/msg/Image` | 相机驱动，经 remap | policy | Sensor Data、Keep Last 1 |
| `/vln/input/camera_info` | `sensor_msgs/msg/CameraInfo` | 相机驱动，经 remap | 预处理/记录 | Reliable、Keep Last 1 |
| `/vln/policy_action` | `vln_interfaces/msg/PolicyAction` | policy | adapter、logger | Reliable、Keep Last 1 |
| `/vln/episode_control` | `vln_interfaces/msg/EpisodeControl` | episode manager | policy、adapter、safety | Reliable、Transient Local、Keep Last 1 |
| `/vln/episode_event` | `vln_interfaces/msg/EpisodeEvent` | adapter | episode manager、logger | Reliable、Keep Last 20 |
| `/vln/raw_cmd_vel` | `vln_interfaces/msg/VlnCommand` | adapter | safety、logger | Reliable、Keep Last 1 |
| `/vln/safe_cmd_vel` | `vln_interfaces/msg/VlnCommand` | safety | arbiter、logger | Reliable、Keep Last 1 |
| `/vln/safety_status` | `vln_interfaces/msg/SafetyStatus` | safety | episode manager、logger | Reliable、Keep Last 20 |
| `/cmd_vel` | `geometry_msgs/msg/Twist` | 原车 arbiter | serial bridge、logger | 服从原车契约 |

ROS 2 QoS 的具体 deadline 和 liveliness 参数需通过 Jetson 与实际相机测试确认，但任何实现都必须保持队列有界，避免积压旧图像或旧动作。

## 6. `VlnCommand` 时间与速度字段约定

对 `/vln/raw_cmd_vel` 和 `/vln/safe_cmd_vel` 的 `VlnCommand.header`：

- `header.stamp` 沿用产生该动作的图像观测时间；
- `header.frame_id = base_link`；
- 只允许使用 `twist.linear.x` 和 `twist.angular.z`；
- 其余线速度与角速度分量必须为零；
- 不得通过高频重发改变原始动作时间戳；
- 超时判断必须依据原始观测时间和本机单调时钟状态，而不是只看最近一次重发时间。

最终 `/cmd_vel` 因现有底盘接口使用未带时间戳的 `geometry_msgs/msg/Twist`，由车辆级仲裁器在最后一步转换。

## 7. 时间同步与动作新鲜度

策略必须保存以下时间信息：

- 输入图像 ROS 时间戳；
- 推理开始和结束的单调时钟；
- 策略动作发布时间；
- 安全层处理时间；
- 最终命令发布时间。

暂定原则：

- shadow mode 可以从 1 Hz 推理开始进行资源评估；
- 实车控制频率必须通过模型实测、底盘动态和安全测试共同确定；
- Jetson 侧动作 watchdog 目标区间暂定为 300--500 ms；
- STM32 合法串口命令 watchdog 目标区间暂定为 500--1000 ms；
- 在实车推理频率不能满足 watchdog 前，不得靠持续重发过期动作进入实车阶段。

上述数值是待验证的设计区间，不是已通过的实车参数。

## 8. 停止语义

`vln_action_adapter` 根据配置的停止阈值和连续动作确认数处理 `stop_probability`：

1. 始终原样记录 `PolicyAction`；
2. 达到停止条件后立即输出零速度；
3. 发布 `EVENT_STOP_LATCH` 通知 episode manager 策略请求终止；
4. 后续非零动作不得自动恢复同一 episode；
5. evaluator 独立判断停止位置是否位于成功区域。

停止阈值、连续确认数和最终判定原因必须写入每次实验元数据。

## 9. 控制权与故障行为

必须保证 `/cmd_vel` 只有一个最终发布者。VLN 节点只发布候选命令并申请控制权，不得绕过仲裁器直接控制串口节点。

以下情况必须输出或维持零速度，并记录原因：

- 尚未取得 VLN 控制权；
- episode 未开始、已取消或已结束；
- 图像过期或丢失；
- 模型动作无效或过期；
- 推理节点退出或失去 heartbeat；
- 安全节点内部错误；
- 人工接管或物理急停；
- 仲裁器拒绝 VLN 控制权。
- episode 未收到 `COMMAND_START` 或已收到 `COMMAND_CANCEL/TERMINATE`。

车辆级 watchdog 必须独立于 VLN 进程存在。即使整个 VLN 仓库中的节点崩溃，底盘也必须在验证过的超时时间内归零。

## 10. 评测数据隔离

FAST-LIO2、TF、RTK、雷达真值和目标区域信息可以由 `vln_evaluator` 读取，但必须满足：

- policy 进程不订阅这些 topic；
- policy launch 不向模型参数传递真值 topic 名称；
- 真值和模型输入分别记录；
- 回放测试能够证明移除真值 topic 后策略输出不变；
- 任何将深度、IMU 或里程计加入策略的实验使用独立配置和实验名称。

## 11. rosbag 最低记录集合

每次实验至少记录：

```text
/vln/input/image
/vln/input/camera_info
/vln/policy_action
/vln/raw_cmd_vel
/vln/safe_cmd_vel
/vln/safety_status
/cmd_vel
/tf
/tf_static
```

还必须保存 action goal/result、模型版本、配置快照、Git commit、控制权事件和人工接管事件。用于评测的定位、雷达和底盘状态 topic 按实验场景加入，但不得因此接入策略节点。

## 12. 契约测试

接口实现后至少需要以下自动化测试：

1. 固定图像和指令产生可重复、可记录的动作结构；
2. NaN、Inf、错误 episode ID 和过期动作被拒绝；
3. 停止条件触发后不再恢复非零速度；
4. policy 退出后 Jetson 侧在阈值内归零；
5. VLN 与 Nav2 不能同时获得控制权；
6. 移除 TF、定位和雷达真值后，主策略输出不变；
7. rosbag 回放使用原始图像时间戳，而不是回放机器的墙钟；
8. 日志能够对应同一动作的原始、安全和最终三个版本；
9. STM32 通信中断后在验证过的阈值内归零。
10. policy failure 不得被 episode manager 判定为正常完成；
11. 新 episode 的 ID 必须贯穿 control、action、command 和 safety status。

## 13. 版本与兼容性

接口发生以下变化时必须提升契约版本并记录迁移说明：

- 消息字段或单位改变；
- topic 语义改变；
- 停止判定或超时语义改变；
- 控制权所有者改变；
- 新增进入主策略的信息源。

每次实车实验必须保存本仓库 commit、原车仓库 commit、消息接口版本和模型版本。不得只记录分支名。
