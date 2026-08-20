# 当前 AI 交接

> 本文件由 `python scripts/ai_memory.py render` 根据 `project-memory.json` 生成。

## 当前断点

- 更新时间：`2026-08-20T16:54:00+08:00`
- 分支：`fix/fast-probe-handshake`
- HEAD：`fix/fast-probe-handshake 已包含 RTOS Trace Timeline 固定页、DPR 取整、当前页平滑刷新、普通滚轮不冻结跟随、SystemView 流模式重连和放大窗口持续刷新修正。`
- 远端 HEAD：`Aladdin-Wang GitHub origin/fix/fast-probe-handshake 已推送至 271dfc4；origin/master 保持 284c879，未合并、未创建标签或 Release，未修改 updates/latest.json 或 Gitee。`
- 工作树：Timeline 放大窗口持续刷新源码已提交；项目记忆待提交；生产构建生成的 gui/dist 变化不进入源码提交。
- 当前任务：RTOS Trace Timeline 与普通滚轮跟随已修复；放大/平移后保持固定视口并持续刷新窗口内数据；连接握手先恢复 SystemView 流模式再尝试其他流模式，避免重连后无数据。
- 状态：`systemview_reconnect_recovery_fixed`

## 里程碑

- **产品与分发** — `complete`。Python、Skill、Web GUI 和 Tauri 版本统一为 v0.1.7，标准 NSIS 使用内置 sidecar。
- **烧录与兼容性** — `complete`。在线/脱机烧录、HPM ROM API、Pack/FLM、固件刷新、复合探针和扇区解析已集成。
- **调试与数据流** — `complete`。Memory、RTT、SystemView、VOFA、串口和 Modbus 共用资源仲裁与轻量流通道。
- **多实例与远程** — `complete`。每个桌面实例使用独立后端和探针连接；Site Agent 支持认证直连与 LAN STCP。

## 验证证据

- **POSIX venv Web 快速启动**：protocol_python_executable 在 sys.prefix != sys.base_prefix 时使用 absolute() 保留 venv 的 bin/python 入口，不再由 resolve() 展开到基础解释器；非 venv 继续 resolve()，Windows pythonw.exe 选择逻辑不变。两个跨平台回归用例分别禁止 venv 分支调用 resolve()、确认基础解释器仍调用 resolve()，旧实现会被前者稳定拦截且不依赖 Windows 符号链接权限。test_web_entry.py 35 项通过；最终 GUI 54 文件/524 项、Vite 生产构建和 Tauri cargo check 通过；最终 Python 为 1295 passed、1 skipped，12 项仅因当前 Windows 账户无目录符号链接权限失败。用户提供的 Linux 实机证据包括协议 start/stop、8765 健康接口、Edge 无头渲染和重新安装 quick-launch 全部通过；本机未重复运行 Linux 桌面协议处理器。
- **SuperWatch 窄窗按钮布局**：根因是桌面 SuperWatch 工具栏虽然保持单行并允许横向滚动，但按钮、触发控件和间隔组仍可被 flex 收缩。现让桌面两条工具栏的直接子项保持自身宽度，控制按钮与触发按钮强制 nowrap，间隔组使用不可收缩的单行布局。Browser 在真实 8766 Web GUI 验证 650x720 与 390x844：开始、暂停、停止、应用、触发均约 49x26 px，文字单行且 flex-shrink=0；650 px 下控制栏 clientWidth/scrollWidth 为 563/802，触发栏为 563/729，滚动发生在工具栏内部，页面无整体横向溢出；390 px 下工具栏正常换行，控制台无错误或警告。聚焦 WaveformViewer 83 项和 Dashboard 20 项通过；最终 GUI 54 文件/524 项、Vite 生产构建和 Tauri cargo check 通过；最终 Python 为 1293 passed、1 skipped，12 项仅因当前 Windows 账户无目录符号链接权限失败。
- **上位机探针控制收敛与 AI VCC 确认**：Config 已删除完整的探针电源与重启区及 VCC 控件；Dashboard 顶部并排显示带图标和文字的重启 MCU、重启 MKLink，两个动作在断连、连接切换和彼此执行期间互斥，MKLink 重启继续要求确认并提示重新枚举。Device/REST 电源能力保持不变；MCP set_power_on 对 1800/3300/5000 mV 均要求本次具体电压的 confirm_user=True，5000 mV 仍额外要求 confirm_5v=True。聚焦 Python 10 项、GUI 42 项通过；最终 GUI 54 文件/524 项、Vite 生产构建和 Tauri cargo check 通过；最终 Python 为 1293 passed、1 skipped，12 项仅因当前 Windows 账户无目录符号链接权限失败。Browser 在真实 8766 Web 后端完成桌面和 390x844 移动视口验证：Config 无 probe-controls/VCC，Dashboard 两个文字按钮无重叠或横向溢出，页面无框架覆盖层和控制台告警。真实连接请求返回 Failed to connect to an available MKLink port，因此本轮未完成已连接态浏览器闭环，未执行 MCU reset、probe reboot 或任何 VCC 输出；确认取消/执行路径由组件测试覆盖。
- **CMD 口残留命令与快速连接**：COM225 真机将未完成的 print('__mklink_probe 残片预置到探针 REPL 后，旧实现稳定拼成无效命令并在 3.305 秒后识别失败；修复后连续 5 次身份识别全部成功且为 63-64 ms，自动发现连续 3 次均选中正确 CMD 口且约 63 ms，CLI 完整连接和 IDCODE 读取为 466 ms。独立 Web 后端真实闭环完成残留命令、自动发现、连接、状态和断开：发现 62 ms、连接 192 ms。聚焦回归 9 项、GUI 54 文件/525 项、Vite 生产构建、Tauri cargo check 和补入未跟踪本地 mklink-stcp.dll 后的 Site Agent 5 项通过；补齐该 DLL 后的最终 Python 全量为 1293 passed、1 skipped，12 项仅因当前 Windows 账户无目录符号链接权限失败。真实只读 dump 流在 CDC 关闭后立即恢复提示符，未形成持续无提示符状态；0.3/0.7/1.0 秒恢复时序由自动化回归覆盖，不宣称该分支已完成真实慢恢复 HIL。
- **su5176 master 同步门禁**：origin/master 与 su5176/master 的真实分叉为本仓库独有 2 个、上游独有 14 个提交；合并预检仅 docs/ai 自动生成交接文件冲突，运行时代码无文本冲突。新增功能与更新源聚焦回归 121 项通过；Python 3.14 完整套件为 1290 passed、1 skipped，12 项仅因当前 Windows 账户无目录符号链接权限失败，桌面双实例运行时 JSON 的一次瞬时 PermissionError 随后连续 3 次通过。GUI 54 文件/525 项、Vite 生产构建和 Tauri cargo check 通过。未执行 VCC 或 probe reboot 真机操作，沿用上游 2026-08-16 已记录的真机门禁豁免且不宣称 HIL 通过。
- **僵尸锁与探针电源/重启控制**：Windows PID 判定现同时检查 OpenProcess 与 GetExitCodeProcess；真实已退出子进程仍保留句柄时正确返回死亡，serial_MKLINK_AUTO_CONNECT.lock 回归可自动删除。Device/MCP/REST/GUI 新增 1800/3300/5000 mV 与 probe reboot；5V 在 Device、REST、MCP、GUI 四层要求逐次显式确认，reboot 后释放串口与 HIL 锁，活动 RTT/SystemView 在参数校验通过后先安全停止。最终 Python 1300 passed、1 skipped；GUI 54 文件/525 项、Vite 生产构建、Tauri cargo check 通过。真实 Playwright 验证 3.3V 请求 confirm_5v=false、取消 5V 不发请求、确认 5V 才发送 confirm_5v=true、reboot 需确认。浏览器使用模拟后端，未对硬件输出电压；项目无已确认 bench.yaml，维护者于 2026-08-16 明确豁免本次真机门禁，不得把该豁免表述为真机验证通过。
- **双分支本地合并与隔离**：master 与 feature/eternal-chip-gui 均完成本地快进。立芯分支运行时 c9fc938 通过 Python 全量覆盖（首轮 1297 passed、1 skipped，PyPI 恢复后受影响文件 7/7 通过）、GUI 56 文件/529 项、生产构建、cargo check 和真实 Chromium + mock 验收。两分支 mklink 核心、Skill 与探针控制回归测试无差异；HIL 锁提交分别位于两条祖先链，立芯品牌提交 7ba8f57 不是 master 祖先。用户随后明确授权，两条分支通过 Git 原子推送同步到 GitHub origin。
- **FLM 查找修复选择性合并**：从 origin/master 8f6a094 创建 fix/pdsc-device-algorithm，仅摘取原提交 68d4e4f 为 8da2d2d；差异只有 mklink/mcu_detect.py 与 mklink/mcu_profiles.json，无 GUI 或 HIL 锁文件。真实 D:\Keil_v5\ARM\PACK 中 Keil.STM32F4xx_DFP.pdsc 对 STM32F411CEUx/RETx 均命中 device 级 CMSIS/Flash/STM32F4xx_512.FLM。Python 全量先得 1282 passed、1 skipped，环境性失败随后逐项联网复跑通过；GUI 54 文件/521 项、Vite 生产构建、Tauri cargo check 均通过。Site Agent 打包补入与当前 stcp_bridge 源码哈希一致的本地 DLL 后 3 项通过，DLL 与测试产物均不提交。
- **v0.1.6 运行时**：GUI 518 项、配置页 22 项和连接后端 12 项通过；Python 可比门禁 1262 项通过、1 项跳过。真实 Chrome、独立 Web 后端、下载器和 HPM5301 完成自动搜索、错误端口回退和再次连接闭环。
- **烧录与数据流**：HPM 在线烧录自动运行、重复固件加载、浏览器文件刷新和客户 HEX 解析已验证；串口/RTT 高吞吐与下载器 V2/V3/V4 数据完整性完成真机验证。
- **v0.1.6 正式分发**：七项资产哈希复算通过；正式 NSIS 已覆盖安装，健康与探针接口、内置 sidecar、零 Python 子进程、正常退出和动态端口释放通过。本地 Skill 指向 2f65f92c98；GitHub/Gitee Release、标签和 updates/latest.json 已核对一致。
- **浏览器后端生命周期**：真实 Chrome 双标签验证：关闭一个标签时后端继续运行；关闭最后标签后约 3 秒正常退出，8765 可立即重绑定。关闭前下载器保持连接，随后新后端能重新连接同一下载器，确认 CMD 串口和 Device 已释放。GUI 521 项、生产构建和 Tauri cargo check 通过；Python 1274 项通过、1 项跳过，12 项仅因 Windows 缺少符号链接权限失败。
- **源码与本地 Skill 同步**：Aladdin-Wang GitHub/Gitee master 与 su5176 PR #10 已同步；用户级 Skill、完整 GUI/MCP 依赖导入和 Skill 校验通过，快速启动网页已写入当前 MICROKEEN 卷。su5176 PR #10 于 2026-08-12 合并为 2f8e902。
- **PR #10 合并门禁复核**：GitHub 合并前状态 CLEAN、MERGEABLE，头 4d7d617 相对基线 6360843 前进 35 个提交且未落后；仓库未配置远端状态检查。本机隔离复核通过 GUI 54 文件/521 项、Vite 生产构建、Tauri Rust 12 项与 cargo check。首次 Python 全量得到 1284 passed、1 skipped；3 项仅因隔离 worktree 缺少未入库 mklink-stcp.dll 报错，在补入与 PR 完全相同 stcp_bridge 源码树生成且 SHA-256 一致的 DLL 后定向 3 项全通过。旧 Device 连接测试仍 mock 已移除的 _resolve_port，已改为 mock 当前 load_config 入口以消除本地项目配置依赖；修正后的最终 Python 全量为 1288 passed、1 skipped。PR 中既有真实 Chrome 双标签、下载器重连和 HPM/串口/RTT 真机闭环继续作为实机证据。
- **SystemView 界面抖动**：时间轴 canvas 原先固定预留 20 条泳道导致单任务时出现巨大空白。渲染器现从 2 条泳道起步，只在发现更多任务时增长容量并保持不回缩；容器保持 overflow:visible，普通鼠标滚轮仍滚动页面。SystemView/Dashboard/时间轴定向 51 项通过；Edge 浏览器 1440px 与 600px 视口实测 canvas 均为 102px 高且无控制台错误。
- **探针主动固件升级**：新增 /api/probe/firmware-upgrade；固件升级入口现位于配置页本地设备区，启动服务页不再承载该功能。版本优先读取 MICROKEEN readme.txt，GitHub Releases 不可用时回退 Gitee，再回退本地 MK-Firmware。此前 V3.3.7 真机 UF2 闭环仍有效；配置 GUI 定向 52 项通过。
- **在线目标读取与安装包验收**：在线烧录右侧新增读取面板：弹窗填写基地址和结束地址（结束地址不含），按 1024 字节请求读取并在窗口中累计显示进度，读取完成后由保存文件按钮调用系统保存选择器或浏览器下载回退；HPM ROM 读取继续禁用。GUI 定向 104 项、在线闪存 Python 128 项通过。Edge 浏览器真实页面验证弹窗、2048 字节读取、100% 进度、保存按钮、配置页固件入口和 RTOS Trace 宽窄视口均无控制台错误。标准 NSIS 已生成并覆盖安装；安装后 health 返回 ok、online-flash/probes 正常、进程树无 Python 子进程、关闭后 8765 释放。
- **三客户端生命周期与隔离联调**：AI CLI 使用 V3 探针完成发现、连接、IDCODE、0x20000000 处 16 字节只读 RAM、主动断开；资源状态显示桥接 owner 已退出、串口锁 owner 不存活。并行第二连接明确返回串口正在被其他进程使用，未抢占。Web REST 8769 和安装包 sidecar 8765 均用同一 V3 探针完成 `/api/device/connect`（STM32F10x、IDCODE 0x1ba01477）及 `/api/device/disconnect`，未执行写入；独立 Web 后端启用浏览器会话租约后，WebSocket 客户端关闭并释放最后租约，8767 自动退出；另一路 Web 8769 释放租约时安装包 8765 仍返回 health=ok。反向测试中关闭安装包窗口对应进程后，Web 8768 在检查时仍健康，8765 最终释放；安装包覆盖安装候选为 `MKLink-AI-Probe-0.1.7-b6b0171-setup.exe`，SHA-256 `0B60C53119A02652B58767590CE649781C1C79FE55608B320A7C001420616ED6`，健康接口正常、进程树无 Python。聚焦生命周期/桌面/协议 Python 测试 75 项通过，GUI browser-session/Config 测试 25 项通过。Chrome 控制插件初始化因运行时拒绝 node:process，未宣称插件自动化通过；浏览器页关闭路径以真实 WebSocket 会话协议验证。
- **0.1.7 在线读取界面与版本收口**：在线读取弹窗继续使用基地址到结束地址（结束地址不含）和目标扇区分块，读取结果自动加载到主 HEX 窗口；读取数据、保存文件、清空窗口位于选择 BIN/HEX 同一行，读取进度复用烧录总进度，分块状态复用底部任务日志，HPM ROM 读取继续禁用。新增主页面接线、保存/清空回归覆盖后，GUI 全量 55 文件/533 项、Vite 生产构建和 Tauri cargo check 通过；在线读取 Python 测试 352 项通过；Site Agent/版本元数据回归 10 项通过。Python 全量为 1311 passed、1 skipped，剩余 12 项因当前 Windows 账户无目录符号链接权限失败。源码、Tauri、Site Agent 元数据和右下角 release history 已统一为 v0.1.7。基于 6e19148 重新生成标准 NSIS 候选，SHA-256 为 9A09F563742AAD0F4B8F5244265185F770B8DBFBD93022F9B4CC1E7AB8235B52；覆盖安装后文件版本为 0.1.7，health 正常、探针列表返回 1 项、进程树无 Python，正常关闭后桌面进程、sidecar 和 8765 均释放。U 盘 MKLink Web GUI.html SHA-256 为 55FB43FFAD956299C8329DA4B237908C1583F868B57928A9B20269FAF5BDC078；协议处理器固定到用户级 0.1.7-6e19148 Web Runtime，资源包含 0.1.7/6e19148，Chrome 已打开且 Web health 正常。Chrome 控制扩展仍受当前运行环境限制，页面打开使用本机 Chrome 可执行文件完成。候选未发布为官方 Release。
- **Windows 托盘图标**：根因是 TrayIconBuilder 只创建菜单和事件，没有显式设置图标；Tauri 不会自动继承窗口图标，Windows 因此显示空白托盘项。现从 app.default_window_icon() 获取 bundle 已生成的图标并显式传给 TrayIconBuilder，未增加图像解码依赖。cargo fmt、Rust 12 项、cargo check、GUI 55 文件/534 项和标准 NSIS 构建通过；Python 为 1316 passed、1 skipped，12 项仅因当前 Windows 账户无目录符号链接权限失败。候选 SHA-256 A794BAFBBDC668E4F177C7DE01CF15489D06E4429E95A5C7783915E9DEAD692E 已覆盖安装，8765 health 正常，进程树无 Python；维护者截图确认 Windows 托盘显示 MKLink 芯片图标。
- **在线下载清空数据**：清空窗口现在同时清除芯片读取结果、用户加载的 HEX/BIN、桌面文件句柄与路径、BIN 地址弹窗状态、文件指纹、解析结果和 HEX 预览，同时保留目标器件与连接参数；按钮在任一数据来源存在时可用。新增用户加载 HEX 后清空的回归用例；聚焦测试 71 项、GUI 全量 55 文件/535 项、Vite 生产构建通过，Python 为 1316 passed、1 skipped，12 项仅因当前 Windows 账户无目录符号链接权限失败。Chrome 插件 26.814.41407 已恢复控制，真实 8766 Web GUI 完成探针连接、IDCODE 读取和主动断开；自动文件选择会使控制内核超时，因此加载 HEX 后的清空交互仍待维护者手动选择文件后补验。
- **在线下载读取图标**：目标芯片读取到上位机的方向统一使用 Lucide Upload 向上箭头，覆盖在线下载主工具栏、独立读取面板和地址弹窗开始读取三个入口；保存文件图标保持不变。DOM 回归断言锁定三个读取按钮的 lucide-upload；聚焦 2 文件/75 项、GUI 全量 55 文件/535 项与 Vite 生产构建通过。
- **RTOS Trace Timeline 抖动**：根因是实时窗口每个事件都追赶最新时间并使用缓动，以及 Chrome fractional devicePixelRatio（1.0000000298）直接参与 canvas 尺寸比较，导致每批数据反复清空画布。Timeline 现按固定整页时间段更新，当前页内只重绘数据，最新事件越过页边界才移动标尺；canvas 尺寸先 Math.round 后比较，重建时强制立即绘制，泳道容量只增不减。GUI 全量 55 文件/538 项、Vite 生产构建通过；真实 Chrome 600x844 连续采样无空白闪烁，桌面 V3 真机事件计数持续从 1,309,917 增长到 1,315,492，6 个任务时 canvas CSS 高度始终 242px，画布内容更新但尺寸不变；停止后 READY，页面无横向溢出和控制台错误。
- **RTOS Trace 普通滚轮冻结**：根因是 canvas wheel handler 把普通页面滚轮当作时间轴缩放，并调用 setFollowMode(false)，随后实时数据被保护逻辑冻结。现在普通滚轮不 preventDefault，只有 Ctrl/Cmd+滚轮才缩放；拖拽仍可进入手动查看模式。新增普通滚轮不冻结跟随回归用例；GUI 全量 55 文件/539 项和最新生产构建通过。最新 8766 页面页脚为 047367261341。重启后 V3 COM738/COM739 仍处于流模式且握手超时，尚未完成本次修复后的新一轮真机采集。
- **SystemView 流模式重连无数据**：连接握手恢复阶段现在先发送 SystemView 的二进制停止帧 0x02 和 SystemView.stop()，验证回到 REPL 后才结束；仅在无提示符时发送 RTT/VOFA/dump 兜底命令，避免命令拼接污染。新增桥接恢复回归断言，聚焦 Python 10 项通过。真实 8766 + V3 闭环先停止 SystemView，再断开/重连成功；重新启动后状态为 streaming，Chrome 事件列表持续增长（80,864 事件、6 个任务）。
- **RTOS Trace 放大后持续刷新**：手动缩放/平移不再冻结 setPrefilteredIntervals；Timeline 保留 viewStart/viewEnd，渲染调度器按当前视口向 worker 请求数据并持续重绘，只有实际拖动才退出跟随，单击不冻结。新增视口保持与点击/拖动回归测试；GUI 全量 55 文件/541 项、生产构建通过。真实 Chrome 放大后事件计数约 3,192,204 增长到 3,197,946，canvas 尺寸保持稳定。

## 架构决策

- 每个独立问题完成验证后形成独立 Git 提交并推送 GitHub，生成资产和项目记忆可作为单独的收口提交，便于按问题回退源码。
- web-entry 协议处理器在标准 venv 中保留 sys.executable 的绝对但未解引用路径；非 venv 继续规范化真实解释器路径。gui_server_command 直接复用当前 sys.executable，不做额外 resolve。
- SuperWatch 在宽度大于 640 px 时继续采用单行工具栏和工具栏内横向滚动，但所有直接子控件禁止 flex 收缩；控制、触发和间隔按钮文字保持 nowrap。640 px 及以下继续使用原有多行响应式布局。
- CMD 口发现先发送空行结束探针 REPL 残留输入，再发送唯一身份命令；读取在提示符出现时立即返回。bridge.connect 正常同步采用 0.3/0.7 秒分级等待，流恢复后的提示符上限为 1.0 秒。
- Windows 串口锁 owner 只有在进程退出码为 STILL_ACTIVE 时才判定存活；访问拒绝或查询失败保持保守，不自动删除可能属于活动进程的锁。
- 上位机 GUI 不提供 VCC 控件；重启 MCU 与重启 MKLink 在 Dashboard 并排显示且有明确文字。Device/REST 仍支持 1800/3300/5000 mV；AI 的 MCP set_power_on 任意电压每次都需显式 confirm_user=True，5000 mV 还需 confirm_5v=True。reset 复位目标 MCU，reboot_probe 重启探针并断开会话。
- 历史端口是软偏好，可回退自动发现；当前会话手选端口首次保持严格约束，失败后切回自动搜索。
- 运行时修改在 fix/feature 分支完成全量测试、生产构建、项目记忆和真机闭环后合并。
- HPM 目标只使用 ROM API；ELF/DWARF 默认使用内置 pyelftools。
- Dashboard 与烧录/调试操作共用资源租约；复位前停止 RTT、SuperWatch、VOFA 和 SystemView。
- 串口和 RTT 终端使用独立 Worker 与有界缓冲；终端模式不维护隐藏日志。
- 每个 Tauri 实例拥有独立 sidecar、动态端口和探针锁；正式发布默认只生成标准 NSIS。
- 由命令主动打开的浏览器 GUI 使用标签页会话租约；最后标签消失后正常关闭后端并释放资源，显式 --no-browser 和 Tauri sidecar 保持常驻。
- Skill 更新器和运行时/MCP 更新检查保持 24 小时缓存，优先官方 GitHub 更新清单，只有 GitHub 不可用时回退 Gitee。
- SystemView Timeline 使用固定整页时间窗口，只有跨越窗口边界才移动标尺；canvas backing 尺寸使用取整后的 CSS 尺寸乘 DPR，避免 fractional DPR 触发反复清空；普通滚轮交给页面滚动，Ctrl/Cmd+滚轮才缩放，拖拽用于手动查看。
- 连接握手遇到未知流模式时，先以 SystemView 0x02 + SystemView.stop() 序列恢复 REPL 并验证身份；验证失败才发送其他流模式停止命令，禁止把 fallback 命令紧跟在 SystemView 停止字符串后盲发。
- 探针升级只允许显式 confirm=true；版本从 MICROKEEN readme.txt 读取，Bootloader 阶段不依赖卷标而扫描 UF2 标志文件，升级失败返回手动操作提示。
- 在线目标读取使用基地址到结束地址（结束地址不含）的 1024 字节前端分块请求；读取结果保留在窗口中，保存文件动作才打开系统保存选择器。HPM ROM 读取继续明确禁用。
- 固件升级入口与本地设备连接设置放在同一配置页，保证 Web GUI 与安装包的功能入口一致。
- AI CLI、浏览器 Web 后端和 Tauri 安装包各自持有连接/资源生命周期；浏览器最后一个会话租约释放才停止其自有 Web 后端，关闭 Tauri 只终止其 sidecar，不触碰其他端口。

## 真机环境

- **probe**：维护机可使用 V2/V3/V4 下载器；交接不记录端口或完整设备标识。
- **target**：ARM 与 HPM 真机可用；部分客户芯片仅完成 Pack/HEX 软件验证。
- **permission**：维护者已授权把 su5176/master 同步并推送到 Aladdin-Wang GitHub master，并要求后续每个问题独立提交并推送 GitHub。上游于 2026-08-16 记录的 VCC/reboot 真机门禁豁免继续作为限制，不授权任何 5V 实机输出；标签、Release、Gitee 同步和破坏性烧录仍需单独授权。

## 下一动作

1. 继续用真实 Chrome 复测 RTT 停止与 SuperWatch 启停，重点确认高频流退出不会再出现 RTTView.stop 残缺命令。
2. 维护者在真实 Chrome 中手动选择测试 HEX 后，补测清空窗口移除文件名、元数据和 HEX 预览，并目视确认读取按钮向上箭头。
3. 下个正式版本发布时，公共 Skill ZIP 与 updates/latest.json 才会向既有安装分发本次同步代码。
4. 需要扩大分发证据时，在干净 Windows 环境复测安装更新和 USB Web Entry。

## 已知限制

- COM225 的真实只读 dump 流在 CDC 关闭后立即恢复提示符，未能保持持续无提示符状态；快速流恢复的超时时序已有自动化覆盖，但仍需在可稳定保持 RTT/VOFA 流的 V2/V3/V4 场景补充慢恢复 HIL。
- 本次真实 Browser 使用实际 8766 Web 后端时探针连接失败，未完成 Dashboard 已连接态或确认框的浏览器 HIL；组件测试覆盖两个复位动作、取消/确认与断连禁用，且未执行 MCU reset、probe reboot 或 VCC 输出。历史 VCC/reboot 真机门禁豁免仍只作为限制，不得表述为真机通过。
- 当前 Windows 测试账户不能创建目录符号链接，完整 Python 套件中的 12 个上传路径重定向安全测试无法建立前置条件。
- Python 3.14 完整门禁中桌面双实例运行时 JSON 曾出现一次瞬时 PermissionError；同一测试随后连续 3 次通过，需继续观察 Windows 文件替换时序。
- 高事件率 SystemView 仍可能溢出目标 RTT 缓冲。
- V4 脱机首次触发的瞬时空失败仍需冷启动复现。
- 部分客户芯片修复缺少物理目标板编程证据。
- 先楫定制店铺尚无权威链接，菜单项保持禁用。
- USB Web Entry 和安装更新仍需更多平台与干净 Windows 验证。
- 当前 GitHub/Gitee Release 尚未提供 V3.3.7/V4.3.6 UF2 远端资产；自动升级会优先尝试远端，缺失时回退安装包 MK-Firmware。本机已完成 V3.3.7 同版本 UF2 真机重刷闭环。
- Chrome 插件 26.814.41407 已恢复控制；由 agent 新建的 localhost 标签仍可能被 Chrome 以 ERR_BLOCKED_BY_CLIENT 阻止，维护者手动打开页面后可以正常 claim。文件选择器自动化会使浏览器控制内核超时，真实文件加载交互需要维护者手动选取文件后继续验证。

## 延续协议

- 开始前用 Git、进程和硬件状态校正项目记忆。
- 每修复并验证一个问题后，独立提交并推送 GitHub，提交范围必须能按问题回退。
- 不提交安装包、日志、硬件标识、凭据或构建缓存。
- 结束前执行 render、validate、diff 检查并保持工作树干净。
