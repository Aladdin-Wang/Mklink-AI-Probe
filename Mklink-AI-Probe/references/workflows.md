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
