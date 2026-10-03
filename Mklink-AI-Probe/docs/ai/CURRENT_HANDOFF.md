# 当前 AI 交接

> 本文件由 `python scripts/ai_memory.py render` 根据 `project-memory.json` 生成。

## 当前断点

- 更新时间：`2026-10-03T00:21:04.7235043+08:00`
- 分支：`codex/superwatch-drag-groups`
- HEAD：`Pointer-based group drag fix based on main 391918f.`
- 远端 HEAD：`main 391918f; PR23 retains installation evidence.`
- 工作树：Isolated task worktree; original main user firmware preserved.
- 当前任务：修复Windows桌面SuperWatch拖入分组失败；真实桌面与浏览器拖动通过，提交PR待合并。
- 状态：`in_progress`

## 里程碑

- **正式发布** — `complete`。0.2.2 标准安装包、Skill、Site Agent 已同步新旧 GitHub 和 Gitee；四份探针固件已同步，UF2 三端索引通过。

## 验证证据

- **0.2.3集成验收**：docs/verification/v0.2.3-integration-20261002.md：集成Python2446/GUI755/Rust19；打包修复Python2449通过/2跳过、GUI755及生产/NSIS构建通过。安装版HPM RAM128项、ROM烧录51244字节回读、RTT/SystemView、Web/桌面实时写入、2648行CLI日志回放一致；新Skill CLI2714样本通过。修复包覆盖安装、受限PATH、Web入口、7059型号/2224算法及退出释放通过。
- **SuperWatch实时写入及回放**：superwatch-live-write-20261002.md、superwatch-live-write-v23-20261002.md、superwatch-live-write-hpm6e80-20261002.md和superwatch-replay-20261002.md记录各版本实机及浏览器验证。V4 HPM需DUMP_WRITE_HPM=1；本轮V2/V3未更新。
- **SuperWatch界面及恢复**：PR22/main391918f已覆盖安装，安装记录保存在PR23。本轮改用Pointer Events修复Tauri拦截HTML5拖动；桌面真实鼠标移入普通组及折叠空组、浏览器合成信号拖动通过，GUI762项及生产/原生构建通过。详见superwatch-drag-groups-20261003.md；此修复尚未安装。
- **0.2.2 发布、安装与固件**：docs/verification/v0.2.2-release-final.md：Python2306通过/2跳过，GUI720、Rust19通过；正式NSIS87.6MiB，覆盖安装、内置后端、7059型号/2224FLM哈希、退出释放、更新签名及三端公开索引通过。 HPMLinkV4.5.1、MicroLinkV4.5.1/V3.5.0/V2.8.0已公开下载校验；25项发布/升级测试通过。V2 RBL头/体CRC、长度及程序版本验证，打包头V1.0.0保留原件。此发布轮未刷机，不新增硬件认证。 PR #6同步四份固件至源码目录，合并前Python2306/2跳过、GUI720及生产构建通过。
- **nRF54L15保护**：Python真机 APPROTECT/SECUREAPPROTECT 写入、复位保护状态3、AHB关闭、CTRL-AP恢复0.923秒、1560576字节全空检查、客户HEX恢复校验通过。原始证据保存在用户测试目录 .mklink/security_roundtrip_20260924.json。别名与算法目录回归19项通过。
- **0.2.3在线烧录扇区几何修复**：docs/verification/v0.2.3-sector-geometry-20260924.md：审计7059型号，27个存在地址重叠且扇区声明冲突，STM32F767xG 双Bank/单Bank分别16/32KiB。按所选FLM绑定检查、映射和任务，未选择或冲突自定义FLM时拒绝；Pack优先使用FLM可变扇区范围，缺口和不完整尾部保持不可验证。Python全量2326通过/2跳过，最后冲突保护定向1项通过；GUI全量723、最后按钮门禁定向97项通过，生产Web构建与真实Chrome入口检查通过。未执行真机擦写。
- **0.2.3 电源、AP 与 USB 实机验收**：docs/verification/v0.2.3-power-telemetry-20260928.md：主机135项、Skill及V3/V4模型和SEGGER构建通过，V3电压/不可用电流字段实机通过。v0.2.3-v3-h743-acceptance-20260928.md：AP/内存/变量三场景及RAM表头解析修复通过。v3-v4-usb-recovery-20260928.md：V3已刷机、USB241次ID/5次重配置/约21ms Abort及H7434170样本通过，缺WinUSB GUID经定向备份修复。v0.2.3-v4-f103-regression-20260930.md：V4.5.2实机电源CLI/MCP、USB恢复、AP/变量/CPU/RTT/VOFA/SystemView/UART及真实GUI通过；在线6轮、脱机算法6轮独立回读，应用与Bootloader一致，GUI686585次无错误/丢样。目标运行，未改固件或发布；外部测量精度仍未标定。
- **0.2.3安装版STM32F103**：docs/verification/v0.2.3-installed-f103-20261002.md：应用114840字节在线烧录回读、Bootloader20480字节保留；RAM128项、实时四种宽度1776样本最大间隔1197us；Web/桌面361269次采集零错误/丢样，CLI2670行日志两端回放一致，RTT317行/SystemView22570事件通过。测试变量恢复、心跳正常、设备及进程释放。

## 架构决策

- 开发主仓库MicroKeen/main；后续修改从最新main创建codex分支，经PR及必需CI整合。审批人数0，发布和合并仍需明确授权；标签不可变。
- 应用主索引MicroKeen/release，旧GitHub/updates兼容，Gitee/updates备用。固件三个firmware索引保持兼容，客户端URL仍可指向旧GitHub。
- 现有自动固件更新仅支持UF2；V2 RBL作为手动升级附件，不写入严格UF2索引，避免破坏0.2.2解析。
- 按维护者授权，Gitee应用发布页仅保留最新0.2.2，固件渠道独立保留；GitHub历史版本不删除。
- 保留正式包、唯一备份、依赖缓存和必要HIL证据。原主工作区用户固件替换不得reset。mklink-issues-pr自动任务维持暂停。

## 真机环境

- **state**：V4/F103已连接用于桌面信号分组验证，采样停止；本轮未写入目标内存或固件。
- **backups**：本地.build/reports保留原始HIL证据；Gitee历史备份与清理记录在.build/artifacts/gitee-historical-backup-20260921。
- **installer**：当前安装版0.2.3/391918f及本地Skill已验证；拖动修复仅测试原生构建，尚未覆盖安装。

## 下一动作

1. 提交拖动修复PR；获授权合并时执行完整合并门禁及覆盖安装。
2. 内部保留既有nRF54L15 GUI验收边界。

## 已知限制

- 有限缓冲不保证无限暂停/物理断线无损；外设轮询可能漏短脉冲，多变量不是原子快照。 VCC遥测需要配套新固件；V3仅电压，V4功率为滤波电压电流乘积，未新增校准。135项测试和固件编译不能替代真实负载精度验证。Web静态资源遗漏已修复并覆盖验收。
- 客户原始ELF/程序不可用，不能宣称复现其毛刺根因；odd-address packed halfword不保证原子性。
- HPM OTP仅按报告限定型号和字段；当前HPM5301组18/19永久锁定，禁止重放配方。其他安全GUI写入口未开放。
- PY32F030保护后恢复、物理Modbus、所有板卡、Mac/Linux与跨主机Agent未完整认证；STM32看门狗、STOP/STANDBY、WRP拒写仍待专测。
- Windows安装器无Authenticode签名（未知发布者），自动更新签名已验证；标准包不含离线WebView2。本轮已验证原生桌面实时写入和CLI日志回放。
- HPM6E80回归有限时长且无UART；本次用户更新的四份固件只做格式/CRC/公开发布验证，不把历史实测外推到新二进制。
- nRF54L15 CTRL-AP 解锁已在 V4.5.1 真机验证：脚本恢复后客户 HEX 脱机烧录、全量回读和运行后保护状态通过；未在固件中写入 nRF54L15 型号。在线GUI已接入安全操作，但尚未做本轮真机加锁/CTRL-AP解锁闭环；脱机GUI仍仅解锁配方。此前Python真机配方通过不能外推为本轮GUI验收。 2026-10-02用户明确豁免nRF54L15在线GUI保护闭环缺失，允许带限制合并和本地构建；不等于该路径真机验收通过。
- STM32F767xG等重叠FLM型号需用户核对实际Bank模式并选择对应算法；本轮仅验证元数据、API和真实浏览器，未连接STM32F767xG真机擦写。另有26个内置FLM无扇区表且当前解析器无法解析，扇区操作继续禁用，需可信Pack或厂商几何资料。

## 延续协议

- 先核对 Git、任务和设备状态；仅按需读相关验证报告，不加载历史流水账。
