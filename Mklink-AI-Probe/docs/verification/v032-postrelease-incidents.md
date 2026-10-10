# 0.3.2 发布后故障：下一会话排查入口

2026-10-10 用户明确要求：本轮可先不修复，完成发布收尾、归档和临时工作空间清理，将问题留给下一会话。本报告只记录代码阅读与已有日志，不代表已经复现、修复或回归通过。不要覆盖已发布的 v0.3.2 标签、安装包或签名。

## SuperWatch 运行中停采并显示断开（优先）

- 用户截图是正式 0.3.2，构建 `3d511e94742a`。30 MHz，单变量，请求间隔 0.000001 s，缓冲 1,000,000 点；截图显示约 262307.69 Hz。错误 `CDC queued read failed`，采集已停止、顶部未连接，但采集区仍显示 `transport connected`。速率/配置是截图证据，不能当作已测量的故障触发阈值。
- 普通安装态后台日志多次出现 `SuperWatch stream error: CDC queued read failed`，另有一次 `Write timeout`。部分错误后，日志中再次 `cmd.get_idcode()` 得到有效 IDCODE；不能据此断言错误期间 USB 或目标一直正常。
- Windows `_serial_worker.py::_WindowsReadQueue.read()` 在 `GetOverlappedResult` 失败时抛出这个通用错误。只有队列已关闭且 `ERROR_OPERATION_ABORTED` 才正常结束。当前异常没有记录 Win32 错误码，无法从已有日志进一步区分取消、USB 复位/驱动失败等原因。
- 确认的传播链：worker `receive()` 将异常编码为 E 帧并关闭读取队列 → `_isolated_serial.py::_drain()` 转为 `SerialException` → `bridge.py::_reader_loop()` 调用 `mux.fail`、保存 `_transport_error` 并设置 `DeviceState.ERROR` → `remote/dashboards.py` SuperWatch 轮询捕获异常，发送 error/stopped，结束采集。仍亮的 transport 徽标需核对状态快照/前端来源，尚未定位其根因。
- 这不是此前用户接受延后的目标访问 `status 5`；不可把本次 CDC 错误归类为已通过的偶发目标读错，也没有证据能断言已发生多少接收字节丢失。
- 待核查（假设，不是结论）：8 个 16 KiB 重叠读取槽的提交/回收、取消与 reset 生命周期、Windows 错误码保留、worker 错误后状态一致性与安全恢复。不能仅吞掉异常继续报告已连接，不能未确认设备身份就盲目重连或重放操作。
- 现有 `test_isolated_serial.py` 的 loop:// 验证不能证明 Windows USB 重叠读取路径可靠；下一会话需覆盖该路径，并在普通安装态做长时间采集、停止/重启和断开/恢复验证。丢点/最大间隔优先使用已有采样时间戳，用户此前不希望为此增加诊断代码。

## 普通启动后台离线（仍未关闭）

用户先报告普通桌面启动后“无法连接本地服务”。此前真实覆盖安装通过，但运行验收使用隔离 runtime/project/locks 目录；不能将隔离启动成功当作普通用户状态已通过。后续普通后台确实启动并进行过采集，但未证明启动故障已解决。

普通日志存在一次保存串口不存在的 FileNotFoundError，之后有成功 IDCODE。尚无证据证明该条导致最初的后台离线。下一会话对比默认 runtime/工程/锁目录、旧端点发现、desktop proxy 与 sidecar 生命周期、退出/重启日志。不得先清空用户配置或全杀后台掩盖原因。

## 证据和边界

本地原 Git 根 `.build/artifacts/v032-official/post-release-incidents/` 保存两张用户截图、普通后台 runtime/startup 日志快照及 SHA-256 清单；不含 endpoint 令牌，未上传这些私有证据。普通安装目录、当前设备身份以本地环境重新核实；本次日志对应设备与之前最终 V4 HIL 设备不同，不能沿用旧接线、固件版本或供电结论。

本轮未打开串口、操作 SWD、改 VCC、烧录、重启或终止用户程序，未修改运行时代码。下一会话先确认当前设备/接线/固件；VCC 每次调整仍需用户确认具体电压。只有证据指向固件时再协调原固件会话。旧正式发布与 HIL 证据保留，但其结论只限原测试范围。
