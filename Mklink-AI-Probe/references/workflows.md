# 工作流程与错误处理

> 触发词：首次烧录、RTT 集成、故障排查
> 返回索引：[SKILL.md](../SKILL.md)

## 工作流程

### 新项目首次烧录

1. 运行 `python -m mklink project-init` 解析工程与目标配置。
2. 工程 IDE 可用时，优先通过 IDE 原生命令行编译并下载。Keil 默认依次执行 `UV4.exe -b` 和 `UV4.exe -f`。
3. IDE 不可用、不适用或只有预编译镜像时，使用 pyOCD 在线烧录。
4. 前两种能力都不可用或用户要求脱机部署时，使用 MKLink 脱机下载 API。

完整的停止条件、命令和 FLM 来源顺序见 [firmware-download-priority.md](firmware-download-priority.md)。`python -m mklink flash` 仅在用户明确要求原生串口/FLM 兼容路径时使用。

### 编译、下载 + 查看 RTT

1. 按 [firmware-download-priority.md](firmware-download-priority.md) 选择后端；IDE 工程默认先编译再下载。
2. 检查编译/下载日志，并完成 Flash 回读或后端 verify。
3. 执行 `python -m mklink rtt --duration 15`，确认新固件运行输出。

某个后端一旦开始执行后失败，必须停止并报告根因，不能静默切换到下一后端。

### RTT 首次集成

```bash
# 1. 集成 RTT 源码到项目（自动检测工程类型和头文件路径）
python -m mklink rtt-integrate --project-root .

# 2. 在 Keil/IAR 中重新编译项目（手动）

# 3. 按固件下载优先级完成下载，再查看 RTT
python -m mklink rtt
```

**生产固件：** 从工程定义中移除 `USE_RTT` 宏即可禁用所有 RTT 输出。

### VPN/局域网现场机直连

1. 先读 [commands-remote.md](commands-remote.md)，确认现场机只部署官方独立
   Site Agent，工程师机才读取本 Skill。
2. 现场维护者先在回环地址完成 readiness/health 验证；需要监听受管 VPN/局域网
   地址时，显式使用 `--allow-lan` 并配置 token。
3. 工程师机从环境变量读取 token，用 `sites add` 注册
   `ws://<VPN_OR_LAN_HOST>:<PORT>`，再用 `sites use` 设置项目 active pointer。
4. 按 `health` → `status` → `capabilities` → `ports` 顺序检查监听器、协议协商、
   能力和探针状态；不要把网络故障误当成探针故障。
5. 普通读操作可通过 SDK、CLI 或可选 MCP 执行。文件先原子上传并取得 opaque
   reference；只有后续消费该 reference 的操作才会产生设备影响。
6. 烧录、擦除、写内存/变量、上传后激活、停止或替换现场 Agent 前，向用户展示
   站点、目标、输入摘要和影响，取得本地明确授权，再使用 CLI `--yes` 或 MCP
   `confirm=True`。替换 Agent 文件只能由现场维护者在旧进程退出后完成。

---

## 错误处理

| 场景 | 处理方式 |
|------|----------|
| COM 口不存在 | `python -m mklink discover` 查找端口 |
| IDCODE 无效 | 检查 SWD 接线和目标板供电 |
| 新 MCU 未知 / profile 缺失 | 先按内置 Pack、内置 DAPLink FLM、已安装 Pack、自定义 FLM 顺序解析；仍无匹配时运行 `python -m mklink mcu-detect`，多候选再选择内部 Flash FLM 固化 |
| 找不到 H723/H7 等 FLM | 先确认发布包内置 Pack/DAPLink 算法；再检查已安装 Keil/Arm Pack；最后才使用显式自定义 `--flm` |
| FLM 加载失败 | 先 `python -m mklink mcu-detect` 确认 profile/FLM，再 `python -m mklink copy-flm` 拷贝 FLM |
| RTT 搜索失败 | 检查固件是否已集成 RTT 并重新编译 |
| RTT 集成验证失败 | 确认 `main()` 在合适位置调用了 `SEGGER_RTT_Init()`（通常在系统初始化之后） |
| 头文件目录不存在 | 检查项目的 Include Path 配置，使用 --inc-dir 指定正确路径 |
| HEX 文件未找到 | 先编译项目，再运行 `python -m mklink project-init` 更新路径 |
| 项目未配置 | `python -m mklink project-init` |
| 远程 listener 不可达 | 先检查受管 VPN/局域网可达性、现场 Agent 进程和 host/port；不要打印 token，也不要把 `remote reconnect` 当成网络修复 |
| 远程认证失败 | 确认工程师侧 `--token-env` 与现场 Agent 的环境变量或 owner-only token file 指向同一密钥；不要把密钥复制到 URL、日志或聊天 |
| `health` 成功但探针未连接 | 用 `status`/`ports` 检查现场探针，再运行 `remote reconnect`；该操作只重连探针 |
| capability unavailable | 以 `remote capabilities` 的协商结果为准；停止调用未发布能力，不猜测 operation 或参数 |
| 上传中断或校验失败 | 重新执行 `remote upload`；协议会中止未完成 session，不支持续传，也不接受客户端指定现场路径 |
| 高风险操作被拒绝 | 回到工程师本地确认站点、目标和影响；CLI 添加 `--yes`，MCP 传 `confirm=True`，SDK 传 `confirm=True`，不得绕过现场 Agent 的二次校验 |
