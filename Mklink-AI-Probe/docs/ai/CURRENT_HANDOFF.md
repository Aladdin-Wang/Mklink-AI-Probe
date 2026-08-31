# 当前 AI 交接

> 本文件由 `python scripts/ai_memory.py render` 根据 `project-memory.json` 生成。

## 当前断点

- 更新时间：`2026-08-31T11:50:00+08:00`
- 分支：`codex/v0.1.9-development`
- HEAD：`v0.1.9 Modbus RTU 工作台、单一串口 I/O 会话、循环事务和真实帧日志已完成；本交接提交随后追加，精确提交号以 git rev-parse HEAD 为准。`
- 远端 HEAD：`每项修复独立提交并立即推送 origin/codex/v0.1.9-development；不改 master、标签或正式发布指针。`
- 工作树：Modbus 工作台源码、自动化回归、生产 Web 资源和 GD32E517 真机只读 HIL 已闭环；交接提交推送后保持工作树与远端分支一致。
- 当前任务：Modbus RTU 第一阶段工作台已完成源码、浏览器与 COM752 真机闭环；后续问题继续在预发布分支按复现、最小修复、回归、真机闭环、独立提交和立即推送处理。
- 状态：`v0.1.9-modbus-workbench-hil-complete`

## 里程碑

- **v0.1.9 开发与维护基线** — `complete`。预发布分支改为持续维护，不再为每个问题创建修复分支；构建、测试和缓存集中在 E:\software\HPM5300\Mklink-AI-Probe\.build，用户 Skill 与维护流程分离。
- **安装、WebGUI 与符号加载修复** — `complete`。修复覆盖升级丢程序/桌面图标、WebGUI 18% MIME 缓存、AXF 压缩 RW 段遗漏全局对象和 GUI MAP 依赖；U 盘 HTML 继续使用跨平台 Skill Web handler，Windows 浏览器友好名称改为 MKLink Web GUI。
- **SuperWatch 性能与历史交互** — `complete`。批量直接解码、动态批量阈值、Worker 单一完整历史和按事务成本合并地址已落地；暂停/停止后缩放不再丢波形，STM32H743 16 路与采样周期补偿完成真机验证。
- **器件目录与 Pack 导入** — `complete`。搜索加入输入联想并列出 FLM 范围；修复缺顶层 url Pack 的 staging 索引、只读属性和事务恢复，导入/安装后自动刷新并保留精确已选器件。pyOCD 全部生产冷导入经进程级可重入锁串行化，消除首屏探针/芯片并发请求的 Python 3.14 模块锁死锁。
- **串口 YMODEM 与快捷键** — `complete`。串口助手加入 YMODEM 文件传输与终端进度；真实 STM32F103 Bootloader 完成 115216 B 升级和应用重启。浏览器与当前 Tauri 0.1.9 均完成 Ctrl+A/C/V 真机字节级验证。
- **RTT/SystemView、AI 安全边界与 Modbus** — `complete`。RTT/SystemView 与 AI 调用边界已闭环；Modbus 的轮询、手动事务和循环请求统一进入单一 I/O Worker，WebGUI 支持 8 个常用功能码、完整串口参数、持久化、循环、响应解析及完整帧 CRC 日志。

## 验证证据

- **Python 全量（2026-08-31）**：1674 passed、12 failed、1 skipped。12 项均为 _maintainer/testing/tests/test_remote_review_repairs.py 创建目录符号链接时触发 WinError 1314，属于当前 Windows 账户缺少 symlink 权限；其余功能测试通过，不能把整套门禁表述为全绿。
- **GUI、标准 NSIS、Skill 与覆盖安装**：GUI 全量 59 文件/626 项通过；Web 入口与安装钩子 76 项、Skill 发布/更新/上下文 64 项通过。标准 NSIS 0.1.9 和 updater 签名生成成功，在仅含 Windows 系统目录的 PATH 下将本机 0.1.8 覆盖为 0.1.9，安装位置保持 D:\Program Files，公共桌面和开始菜单快捷方式存在。已安装应用 /api/health=ok，探针枚举请求成功且发现 1 个设备；进程树只有 Tauri 与内置 sidecar，无 Python，正常关闭后 sidecar 和 8765 均释放。 U 盘 H:\MKLink Web GUI.html 已由最终 Skill 重新生成，系统关联名为 MKLink Web GUI，维护者实际点击确认 WebGUI 可以打开。
- **器件联想与烧录算法浏览器闭环**：真实 WebGUI 输入 STM32F103 展开完整候选并选中 STM32F103RE；器件下方列出 STM32F10x_512.FLM（0x08000000..0x08080000）和 STM32F10x_OPT.FLM（0x1FFFF800..0x1FFFF810），本地目录 12511 型号可用。真实 WHXY.CW32L012_DFP.1.0.2.pack 导入后索引 217 型号并自动刷新。修复前全新服务首次并发请求中 /probes 返回 502 且出现 _frozen_importlib._DeadlockError；修复后换全新 Python 进程与唯一页面 URL，首个 /probes、/targets、算法和内存映射请求全部 200，stderr 无 DeadlockError/Traceback。新增 6 项导入门禁及相关 487 项回归通过。
- **串口 YMODEM 与浏览器/Tauri 快捷键 HIL**：COM227@115200 传 rtthread.bin 115216/115216 B 后 Bootloader 跳转应用。浏览器 Ctrl+V 精确发送剪贴板 22 B，Ctrl+A/C 复制历史且 TX 不变；Tauri 原生剪贴板 23 B 使 TX 32→55，Ctrl+A/C 后 TX 保持 55。
- **RTT REST 真机 HIL**：STM32F103RE：16 项危险请求与 inactive channel 2 均安全拒绝；清理/重连后心跳继续。RTT channel 0 终端回显通过；SystemView channel 1 同步采集 17191 B、4174 事件并正常停止。证据位于测试工程 .build/reports/rtt-rest-hil-current.json。
- **MCP 与 AI 边界真机 HIL**：完整 MCP HIL 47 步通过；专项 RTT AI 边界拒绝 17 项危险调用和 2 项 inactive channel，完整/跨调用 RTTView.stop() 被宿主拒绝，重连、终端回显、SystemView 11254 B/2646 事件均通过且探针未 quarantine。
- **SuperWatch、AXF 与 Pack 回归**：50k×16 预编译解码吞吐较旧对象链路提升 92.16%，调用约减 48.03%；STM32H743 16 路三角波、暂停/停止后历史缩放和 1ms/100us/尽快采样已真机闭环。GD32E517 AXF 恢复 board_info_data；GUI 移除 MAP 选择仍保留后端兼容。Pack、在线 API、符号与生产构建相关回归均通过。
- **Modbus RTU 浏览器与真机 HIL**：COM752@115200、8N1、slave 1 下 FC01/02/03/04 均响应，单次约 25–44 ms；WebGUI FC04 正确解析 16 个输入寄存器，有限循环 5 次无错误，50 ms 周期的 TX 起点约 50 ms。追踪回调的部分接收缓冲不再误报 CRC，完整请求/响应各显示一帧且 CRC OK。线圈 0–3 控制充放电、DCDC 和快充，未做危险写入；目标 GD32E517 工程未修改。

## 架构决策

- 0.1.9 只在 codex/v0.1.9-development 持续维护；每个问题独立提交并立即推送，不再创建临时修复分支，不改 master、标签和正式发布指针。
- 维护构建、测试、日志、临时脚本和可复用缓存统一放在仓库 .build，并经 scripts/build_workspace.ps1 运行；禁止向 C 盘或工程外散落中间文件，也不上传 .build。目标测试工程的分析材料只放该工程 .build。
- 普通用户 Skill 只携带运行时白名单、安全边界和按需参考，不触发源码维护、构建或发布流程；U 盘 HTML 固定使用 mklink-ai-probe:// 调用各平台 Skill Web handler，不绑定 Windows Tauri。Windows 注册 MKLink Web GUI 友好名称，用户中间文件默认放目标工程 .mklink，Skill 必须从 sanitized archive 同步。
- GUI 工程文件只要求 AXF/ELF/OUT，MAP 仅在旧 API/CLI 后备兼容。Keil 压缩 RW 段按受 section 边界约束的 OBJECT 执行地址扩展，不能用压缩 sh_size 过滤 RAM 对象。
- 器件联想用当前可见搜索词返回候选，已选器件用独立精确查询保持稳定；选择后必须展示实际 FLM 名称和地址范围。Pack 只规范化 staging PDSC，安装/导入成功后先刷新后端 catalog 再刷新 GUI。生产代码禁止直接导入 pyOCD，所有惰性首次导入必须经过同一进程级 RLock，不能按模块分锁。
- SuperWatch 连续采样固定走 dump_memory；地址块只合并连续/重叠区域，最多 15 region。后端按预编译字段直接解码，512 样本/64KiB/20ms 联合批量；完整历史只存 Worker，暂停/停止时按可见区间取包络。
- 串口 YMODEM 复用串口助手会话和终端，不另开同一端口；浏览器依赖可信 paste 事件，Tauri 使用 HWND 所有者的原生 Unicode 剪贴板命令。Modbus 的轮询、手动读写和循环事务也必须进入单一 I/O Worker，完整 RTU 帧到齐后才判定 CRC。
- 同一下载器只允许串行 AI 控制并复用连接；超时只查一次状态。MCP direct read/write≤4096B、batch≤16项/4096B、capture≤30秒、flush≤8项/16300B、dump_memory≤15 region，停止流后至少排空50ms。
- V4 RTT/SystemView 宿主仅允许 channel 0..2、4 字节对齐且位于已知目标 RAM 的控制块；inactive/零尺寸/越界描述符拒绝。任何分片都禁止拼出 RTTView.stop()，失败后释放连接并用心跳/重连验证恢复。
- 下载器固件与上位机分别归因：宿主先做全部可判定校验；固件仍需修复通道索引、Down 表偏移和流式描述符 TOCTOU。用户明确下载器固件修改由其自行提交，因此本轮只报告，不提交固件仓库。

## 真机环境

- **probe**：USB Serial Port COM752（VID:PID 0403:6001）作为 RS485/Modbus RTU 主站链路；所有事务串行执行。
- **target**：GD32E517 BMS 工程 E:\PHDZ\PROJECT\64 red source\gd32e517_RACK_V1.0.4，Modbus 从站位于 applications\modus_slave.c，UART5 115200 8N1、slave 1；输入寄存器 0..1023，保持寄存器 0..9 只读，线圈 0..3 关联实际控制。
- **permission**：目标工程默认只读，最多只允许修改 Modbus 相关代码；本轮未修改、未编译、未下载目标工程，只读取源码映射并完成安全的 FC01/02/03/04 HIL。

## 下一动作

1. 保持已安装的 0.1.9 桌面上位机可供维护者继续复测其他功能。
2. 继续接收下一个 0.1.9 上位机问题，按复现、最小修复、自动化回归、真实浏览器/真机闭环、独立提交和立即推送处理。
3. 后续单独修复 V4 RTT 固件通道索引、Down 表偏移和 descriptor 一致性问题，并按 STM32F103RE 夹具复跑 REST 与 MCP HIL。
4. HPM 系列功能梳理、跨固件仓库改造和官方手册重写留作后续小步任务，不混入当前 ARM 0.1.9 基线。

## 已知限制

- 当前 Windows 账户没有目录 symlink 权限，Python 全量固定有 12 项 WinError 1314；需要管理员开发者模式或 Create symbolic links 权限后才能把整套门禁跑绿。
- cargo test --lib 在本机编译成功但测试进程以 0xc0000139 STATUS_ENTRYPOINT_NOT_FOUND 退出；cargo check --tests 和 Tauri 生产构建通过，仍需在干净 Windows 构建机定位缺失入口。
- V4.3.8 Pika 文本 API 的 33 参数边界会失去响应；即使固件帧可容纳 16 region，Skill/CLI/MCP 仍固定最多 15 region，且与堆大小无关。
- V4 固件 py_rttview.c 仍未校验 RTT_wChannel；MaxNumUpBuffers 被截为3后用于计算 Down 表偏移；流式热路径重复读取 Down descriptor 后无零尺寸、offset<size、目标 RAM 范围校验，存在越界和 TOCTOU 风险。宿主已防护可判定输入，但不能替代固件修复。
- 0.1.9 NSIS 候选包尚未做 Authenticode/驱动签名、跨账号安装和 0.1.7 实包升级；本机 0.1.8→0.1.9 覆盖安装、快捷方式恢复、内置 sidecar 和协议友好名称已通过。
- Modbus 写入成功路径仅做自动化回归：当前 GD32E517 保持寄存器映射只读，线圈 0–3 直接控制充电、放电、DCDC 与快充，未在真机执行危险写入。
- V4 + STM32H743 连续 16×float 当前约 9.54k samples/s；100us 请求中位周期可达 100us，但不能保证稳定 10kHz，更不能满足 16 变量 20kHz。

## 延续协议

- 开始前校正 Git、WebGUI/桌面进程、端口占用和目标固件状态。
- 所有硬件操作串行；失败先清理会话并确认心跳/重连，不盲目重试。
- 不把环境失败或未验证硬件现象写成 PASS；结束前更新本文件、渲染 CURRENT_HANDOFF.md 并推送。
