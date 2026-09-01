# 当前 AI 交接

> 本文件由 `python scripts/ai_memory.py render` 根据 `project-memory.json` 生成。

## 当前断点

- 更新时间：`2026-09-01T18:10:00+08:00`
- 分支：`codex/v0.2.0-development`
- HEAD：`0.2.0 预发布开发从 origin/master 的 0.1.9 已发布基线 3af000d 开始。`
- 远端 HEAD：`每次维护前校正 GitHub origin/codex/v0.2.0-development。`
- 工作树：发布前应保持干净；构建产物仅位于仓库外层 .build。
- 当前任务：将常用型号算法保存为维护仓库本地资产，并生成包含同一资产的 0.2.0 桌面安装包与普通用户 Skill ZIP。
- 状态：`v0.2.0-development`

## 里程碑

- **0.2.0 开发周期** — `in_progress`。预发布分支从 origin/master 的 0.1.9 已发布基线建立；已完成 RTT/串口高频显示、不规范本地 CMSIS-Pack 宽松导入及常用型号内置算法目录扩充。
- **RTT 与串口高频显示** — `complete`。RTT 终端按帧合并并限制单次 xterm 写入；RTT/串口日志默认字符串、可切 HEX、时间戳独立开关，保存只写原始数据；RTT 曲线维持 Worker 降采样与 30 FPS 调度。
- **0.1.9 桌面端与 WebGUI** — `complete`。修复覆盖升级、WebGUI 启动、AXF 全局符号、Pack 导入刷新；完成器件联想、烧录算法展示、串口 YMODEM、Modbus 工作台与快捷键。
- **SuperWatch 与流式性能** — `complete`。使用批量直接解码、动态批量、Worker 单一历史和事务成本地址合并；修复暂停/停止后历史消失，并完成采样周期补偿。
- **AI Skill/MCP 安全边界** — `complete`。普通用户 Skill 与维护流程分离；同一探针强制串行，限制读取、写入、批量、flush、dump_memory 和采集时长，超时后隔离会话。
- **0.1.9 发布候选** — `complete`。标准 NSIS、updater 签名、普通用户 Skill 和 Site Agent 便携包已生成；新增 MicroLink V3.3.8/V4.3.9 UF2 已通过发布预检。

## 验证证据

- **常用型号内置算法**：维护仓库本地资产包含 7059 个目标和 2224 个按内容去重的 FLM；每个目标均有主编程算法，所有 blob 均被引用并通过大小与 SHA-256 校验。桌面 sidecar 和普通用户 Skill ZIP 共用同一份资产，正式构建缺失、不完整或损坏时直接失败。
- **Linko/WHXY 本地 Pack 导入**：真实 Linko.LKS07x.1.1.2.pack 导入 11 个器件并提取 12672B ELF FLM；真实 WHXY.CW32L012_DFP.1.0.2.pack 导入 1 个器件并提取 17540B ELF FLM；两个源文件 SHA-256 均保持不变，相关 Pack/算法/API 测试 246 项通过。
- **RTT/串口滚动与 RTT 曲线**：STM32F103RE 真机 1ms RTT 与 UART 压测：RTT/串口终端、日志及 RTT 曲线各连续 60 秒保持响应且主机队列无丢弃；V4.3.9 原始 RTT 120 秒采集 3649670B，启动 0.6 秒处一次 616ms 初始化空窗，此后约 119 秒最大到达间隔 14.26ms，未复现周期性停顿。固件静态审计确认任意 RTT SWD 访问失败仍会退避 200ms。
- **0.2.0 流式自动化**：GUI 629 项与相关 Python 流测试 87 项通过；VOFA 10kHz×8 通道×10 秒基准处理 100000 项，reported/unreported drops 与 sequence errors 均为 0；生产构建通过。
- **STM32F103RE 真机 HIL**：烧录、调试读写、16 路 SuperWatch、RTT/SystemView、串口/YMODEM、在线烧录、MCP 越界拒绝均通过；详情见 docs/verification/v0.1.9-stm32f103re-release-hil.md。
- **SuperWatch**：V4.3.9 下 16×float、1ms 请求得到 4690 样本，中位周期 1000us；暂停/停止后历史仍可查看。
- **自动化与构建**：GUI 626 项通过；Python 1675 passed、12 failed、1 skipped，12 项均为当前 Windows 账户无目录 symlink 权限导致的 WinError 1314；标准生产构建和 NSIS 成功。
- **发布运行时**：release 程序在仅系统 PATH 下启动内置 sidecar，无 Python 回退，关闭后释放 8765；GitHub/Gitee v0.1.9 均包含完整资产，应用与固件公开索引字节一致。

## 架构决策

- 预发布分支持续维护，每个问题独立提交并及时推送；不再创建临时修复分支。
- 0.2.0 常用型号算法以维护仓库内被 Git 忽略的本地目录作为唯一打包源；桌面 sidecar、WebGUI 和普通用户 Skill ZIP 共用该资产，按内容哈希去重并在构建与运行时校验。
- 不规范本地 Pack 只修正送入严格索引器的临时 PDSC 副本；原归档继续按哈希和安全路径管理，并由 pyOCD 从原归档发现、提取 FLM。
- 高频终端输出在 animation frame 边界合并，并等待 xterm 写回调后再提交下一批；日志只对可见虚拟行生成文本/HEX，记录路径与显示格式解耦。
- 构建、测试、日志、临时脚本和可复用缓存统一位于 E:\software\HPM5300\Mklink-AI-Probe\.build，并经 scripts/build_workspace.ps1 运行；不上传 .build。
- 普通用户 Skill 只包含运行时能力、安全边界和按需参考，不加载源码维护、构建或发布流程；U 盘 HTML 使用跨平台 Skill Web handler。
- SuperWatch 连续采样使用 dump_memory；最多 15 region。MCP direct read/write≤4096B、batch≤16项/4096B、flush≤8项/12288B、capture≤30秒。
- 串口、YMODEM、Modbus 和硬件控制共用单一 I/O 所有权；同一下载器不得并行调用，超时后先检查状态并重建会话。
- 应用发布与探针固件发布相互独立；正式索引必须在所有资产上传并校验后最后更新。

## 真机环境

- **probe**：主要 ARM 回归夹具为 MKLink V4；发布前验证固件 V4.3.9，调试端口 COM228、UART COM227。
- **target**：STM32F103RE 工程 E:\PHDZ\PROJECT\liu\STM32F103_test\STM32F103RC；当前板上保留 1ms RTT 与约 5.2KB/s UART 联合压力固件，原 main.c 备份在工程 .mklink/work/rtt-scroll-repro-20260901。
- **permission**：测试工程允许修改与下载；其分析材料只放工程自身 .build。

## 下一动作

1. 若 V4.3.9 现场再次出现 RTT 周期性停顿，先同步记录 SWD 失败、DapBusy、USB 环形队列水位和主机到达间隔，区分 200ms 固件退避与界面渲染背压。
2. 后续问题在 codex/v0.2.0-development 预发布分支持续小步修复、验证并及时推送。
3. HPM 系列回归、下载器固件深层问题和官方手册重构继续拆分推进。

## 已知限制

- V4.3.9 USB2RTT 健康链路未复现稳态停顿，但单次 SWD 读写失败会触发 200ms 退避，连续错误还会重新扫描 RTT 控制块；若现场再次出现应先采集错误/队列计数再决定是否改固件。
- 当前 Windows 账户缺少目录 symlink 权限，Python 全量有 12 项 WinError 1314；这不是业务测试失败。
- 0.1.9 未覆盖 Authenticode/驱动签名、跨账号安装和 0.1.7 实包升级；per-machine 安装验证需要 UAC。
- Modbus 真机只验证安全读取；GD32E517 线圈 0–3 控制真实功率功能，未执行危险写入。
- V4 + STM32H743 的 16×float 连续采样约 9.54k samples/s，不能承诺 16 变量稳定 10kHz 或 20kHz。

## 延续协议

- 开始前校正 Git、端口、目标固件和运行进程；硬件操作保持串行。
- 不把环境失败或未覆盖场景写成 PASS；关键证据写验证报告，交接只保留结论。
- 结束前更新 project-memory.json、渲染 CURRENT_HANDOFF.md，并保持工作树与远端同步。
