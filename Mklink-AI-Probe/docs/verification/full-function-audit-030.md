# 0.3.0 全功能循环审计

本轮覆盖主机、公开 Skill、下载器应用层和目标测试工程。基线主机 `bef5c963`，V4 固件 `58c47a9`。已有报告仅作为历史证据，不自动计入本轮通过。禁止把静态清单、测试收集或模拟通过写成真机通过。长期稳定性测试暂停；不增加 WinUSB，不修改 SDK/Arm2D/MicroBoot，不自动合并或发布。

## 验收方法

每组功能分别记录正常、边界、并发、故障/恢复四类结果及准确提交、测试入口和证据。状态使用：待验证、自动化通过、真机通过、受阻。共享实现可以复用底层测试，但 GUI、CLI、MCP、SDK、远程入口的参数传递、错误反馈和生命周期必须分别验证。缺少器件、外部从站或另一物理主机的项目保持待验证。

## 功能矩阵

| 编号 | 功能及入口 | 本轮必须覆盖的行为与边界 | 当前状态 |
|---|---|---|---|
| A01 | 探针枚举、身份、别名、端口角色 | 零/单/多探针，热插拔，COM 改号，重复别名，不选错设备 | 待验证 |
| A02 | 共享后台和连接 | GUI/CLI/MCP/SDK 多客户端，多探针隔离，租约，关闭/强杀，端口释放 | 待验证 |
| A03 | 本地/远程会话与认证 | 服务启停，认证失败，过期令牌，代理边界，断连禁写，客户端独立关闭 | 待验证 |
| A04 | 配置和状态 | 时钟配置/错误确认、USB/串口重连，状态同步，错误恢复 | 待验证 |
| A05 | 电源与复位 | 遥测、合法/越界值，显式确认后才改变电压；无授权仅验证拒绝路径 | 待验证 |
| A06 | 工程和文件来源 | Keil/IAR/SEGGER/CMake，AXF/ELF/MAP/C 回退，文件变更、失效和重载 | 待验证 |
| A07 | 符号、类型和变量 | 结构/数组/指针/位域/宽整数/浮点，分页与搜索，缺失符号，边界地址 | 待验证 |
| A08 | 内存读写与导出 | 零长度/越界/非对齐/分片，读写校验、未知写入不重放，批量访问 | 待验证 |
| A09 | Dump/Flush/吞吐测量 | 区域重叠/大小上限/超时/取消，文件头与数据完整性，缓存边界 | 待验证 |
| A10 | 调试、寄存器、断点 | 暂停/运行/单步/复位，FPB 资源耗尽，状态恢复，ARM/JTAG 差异 | 待验证 |
| A11 | HardFault | 堆栈、寄存器、源码定位，缺失符号/无效栈/未发生故障 | 待验证 |
| A12 | SVD/外设观察 | 型号选择、寄存器宽度/访问权限，非法 SVD、只读外设及采样边界 | 待验证 |
| A13 | ARM 在线烧录 | BIN/HEX、多段、扇区/整片、FLM/Pack 选择、校验、失败恢复 | 待验证 |
| A14 | HPM 在线烧录 | BIN 与新增 HEX、ROM API、多段/稀疏/跨扇区/地址映射、错误校验与越界 | 已实现；自动化及HPM真机BIN/HEX、稀疏同扇区/空洞保持、错误校验/容量拒绝、在线GUI/CLI/MCP通过；其余边界继续 |
| A15 | 脱机部署和执行 | ARM/HPM BIN/HEX，预览、MSC 身份、已有文件、传输中断、完成反馈 | HPM HEX部署及生成脚本真机执行通过；完整脱机GUI、物理按键及ARM回归待验证 |
| A16 | 烧录任务生命周期 | 请求去重、超时未知终态、查询、取消、重启记录，多客户端观测 | 待验证 |
| A17 | 算法目录/Pack/自定义 FLM | 目录完整性，目标联想，资源缺失、范围及 Bank；HPM 不走 FLM | 待验证 |
| A18 | 选项字节/安全/OTP | 预览、确认和不可逆保护，型号限制、越界；禁止自动永久锁定测试 | 待验证；真机范围受授权约束 |
| A19 | RTT 初始化与停止 | 自动/显式地址，无效描述符、inactive 通道、启动失败回收、重试 | 自动化及真机inactive失败清理、无需stop直接重试通过；GUI故障提示/自动搜索边界继续 |
| A20 | RTT 0–7 Up/Down | 八路实体逐路/并发收发、二进制/中文/半字符/回绕、空/满、通道独立性 | STM32八路Up/Down含00/FF、256字节逐路哈希真机通过；半字符、满缓冲和跨入口边界待验证 |
| A21 | RTT 展示与交互 | 每路日志/终端/HEX/曲线，独立编码/暂停/清除/保存/收起/发送历史 | 待验证；旧报告仅两路实体 |
| A22 | RTT 流量和边界 | 包长上限、坏帧、CRC、序列、背压、队列淘汰、慢客户端、重连 | 待验证 |
| A23 | RTT 传统串口兼容 | 普通串口助手单路映射启停，MUX 切换和解析隔离、退出释放 | 待验证 |
| A24 | SuperWatch | 标量/数组/结构、多组、写入、曲线/回放/导出、15区域/128B/周期边界 | 待验证 |
| A25 | VOFA | 采样格式、通道/速率、显示/导出、背压，资源冲突及停止恢复 | 待验证 |
| A26 | SystemView/RTOS Trace | ARM/HPM 采集、解码/同步/溢出、启停、离线文件、RTT 通道共存 | 待验证 |
| A27 | UART/串口助手 | 参数、文本/HEX/编码/发送、日志、独立端口、多窗口、拔插恢复 | 待验证 |
| A28 | Modbus | 支持的功能码逐项、CRC/异常码/长度/地址、超时轮询、RTU 从站 | 待验证；外部从站待确认 |
| A29 | YMODEM | 多包/末包/重试/取消/超时/重复确认、传输资源隔离 | 待验证 |
| A30 | 固件升级 | V4 UF2 身份/格式/重枚举/恢复；V2/V3 不以 V4 成功代替 | 双V4升级路径已用于本轮真机；升级故障恢复、V2/V3实体仍待验证 |
| A31 | CMSIS-DAP 下载与仿真 | 流量开/关对照，八路 RTT+Watch 下真实下载/校验/断点/单步/重连 | 优先级/会话失效已修；STM32八路RTT+Watch并发DAP暂停/单步/继续和APP擦写读回通过，Bootloader保持；断点及更多负载对照待验证 |
| A32 | 固件调度与存储 | 目标访问仲裁、DAP 优先、USB背压、看门狗、栈/静态RAM/缓冲区上界 | 目标仲裁及MSC文件事务已修并有C harness；静态内存已复核，运行时栈/堆余量、MSC实机写冲突待验证 |
| A33 | 多任务冲突及恢复 | RTT/Watch/DAP/烧录/调试/复位互相切换，不死锁、不错误重放、不串探针 | STM32 DAP抢占后流失效、显式重启八路和Watch真机通过；完整多探针/跨入口矩阵待验证 |
| A34 | GUI 通用功能 | 配置持久化、主题/语言、窗口缩放、页面切换、版本说明、下载/上传 | 待验证 |
| A35 | 公开命令/API覆盖 | CLI 子命令、MCP 工具、SDK 公共方法、远程能力逐项映射到测试 | 已有510项静态入口清单；HPM HEX GUI/CLI/MCP真机入口通过，其余逐项映射待完成 |
| A36 | 发行与本地 Skill | 公开包边界、依赖/安装/升级/回滚、负载哈希、Web/原生及无开发环境启动 | 待验证 |

## 当前发现及推进顺序

1. 固件 `chry_dap_handle` 每包后休眠一个 tick，`ml_target_take` 只有互斥及缓存失效，没有 DAP 忙期的低优先级准入规则。必须审计完整调试会话的 AP/DP/JTAG 状态，不能把互斥视为优先级保证。
2. 目标测试程序只声明三个 RTT 描述符，第三路未激活。八路验收必须修改并烧录目标程序；同时保留非法/inactive 描述符的拒绝及恢复测试。
3. HPM 上传端显式拒绝非 BIN，烧录入口也存在按文件后缀转入 ARM HEX 路径的风险。需统一镜像地址段处理，保留 ROM API，防止以填充巨大稀疏区或覆盖空洞来替代正确 HEX 支持。
4. 先保存静态入口清单和本轮全套自动化基线，再按上述问题实施与真机回归。旧证据见 `cdc-multiplex-host.md`，不扩大其八通道、HPM或跨主机范围。

### 第二轮静态审计

- 入口清单补入 SharedDevice 明确声明的 13 个公开方法，合计 510 项；不包含隐式继承/动态注册，不能据此宣称无遗漏。
- DAP 会话需要保持协议状态：应用 SWD 初始化也写入 DAP_Data.debug_port，因此不能直接把这个字段当成 USB 调试器是否已连接。仲裁应有应用层显式会话所有权，并覆盖组合 DAP 命令、USB reset、断开和 Abort；恢复时还需防止将 RTT 旧描述符的待提交偏移写入下载后的新目标程序。
- HPM HEX 限制同时存在于在线上传检查、HpmRomBackend 的 BIN 校验和脱机配置/脚本生成。设备 program_bin_flash 每次包含擦除，所以简单逐 HEX 段转 BIN 后调用会在同扇区多段时擦掉前段；实现前必须处理共同扇区、稀疏区、地址映射以及读回校验。不得仅移除文件扩展名限制。
- 全套 Python 基线尚在执行，已观察到失败与环境错误，最终分类以 pytest 完整摘要为准。

### Python 全套基线与首批收敛

基线执行终态：4019 passed、26 failed、4 errors、3 skipped，427.93 秒。26 失败中，21 项涉及脱机安全白名单/本地选项算法资源，2 项涉及烧录队列取消与资源管理器断言，2 项为 RTT 写入测试旧签名，1 项为远程文档占位符。4 个打包环境错误均在新复制源树中缺少 builtin_flm manifest，不能记为安装通过。

首批修复 RTT 测试的 channel 参数契约，并增加 None 及 0–7 每路的精确二进制发送路由断言；统一远程文档主机占位符。两个完整相关测试文件共 121 passed。此证据证明 API 路由及文档契约，不证明实体八路收发。剩余 23 项失败及 4 个环境错误继续排查，不降低白名单约束。

### 第三轮基线收敛

烧录取消测试原本覆写 ResourceManager.acquire，但运行代码已使用原子 acquire_many。更新两个测试替身至真实调用点，并新增停止后的全部租约清空断言；同时合并 HPM/ARM 分支重复的 acquire_many 调用。完整 test_online_flash_jobs.py：64 passed。

设置既有 MKLINK_BUILTIN_FLM_ROOT 后，完整 test_offline_download.py：88 passed，原 21 项失败消失；未改算法或白名单。构建存储文档已补充隔离 worktree 的资源前置条件，避免再次把资源缺失误报为产品回归。远程独立包四个环境错误正在以同一资源配置重新构建，尚无通过结论。

### 第四轮：分发包、GUI 与 DAP 首版

配置真实算法资源后，独立远程包测试完成 5 passed/1 failed。唯一失败是将 Python 递归归档条目数量与外部包文件数量比较；新增 2224 个外部算法 blob 后，这个大小关系没有语义。改为检查递归条目中确有代码对象，保留全部 ZIP/manifest/算法哈希/敏感数据断言。直接对同一次新构建产物重新执行完整审计函数通过，未重新制造另一份包，也未跳过原有内容校验。

GUI 全套基线：85 文件、855 测试全部通过（静态脚本只统计 src 中的83文件，另有目录外测试）；这是自动化基线，不替代矩阵中的逐项浏览器/硬件验收。

固件应用层首版 57ac0ba 已推送：统一目标仲裁尊重 DAP 排队请求、响应和显式会话，其他调用者等待时释放锁，DAP 等待采用优先级继承。SES 编译、SWD布局检查、生产仲裁C测试、MUX调度和八路缓冲区模拟测试通过。未刷入硬件；完整会话生命周期、下载后旧RTT偏移清理与实际DAP下载/仿真仍待完成。参见固件 docs/dap-priority-audit.md。SDK/Arm2D/MicroBoot没有随本轮修改。

### 八通道目标程序与首轮实体测试

STM32 测试 APP 改为八个相同的 RTT 上/下行通道，暂停目标端 RTT 控制台和 SystemView 钩子对通道的消费。Keil 编译通过；APP ELF 加载起址纠正为 0x08005000，通过 CMSIS-DAP 按扇区下载、逐字节读回。下载前后 20 KiB Bootloader 区内容完全一致。APP 使用显式 MSP/PC/VTOR 启动，尚不证明现存 Bootloader 自动跳转行为。

实体首测八路上行均有数据，每路下行256字节（含00/FF）全部接收且逐路滚动哈希一致；同时取得211组Watch样本。这是底层适配器真机证据，尚不覆盖GUI、CLI、MCP或全部边界。第一次下行通道1被目标SystemView钩子消费；测试程序去掉冲突消费者后通过。去钩子时曾误用启用HOOKLIST的初始化接口导致目标HardFault，已修复并重新编译/下载验证，不是固件协议问题。

真实DAP并发测试中，暂停/单步/继续、CDC ECHO可用、MUX目标请求返回busy、RTT/Watch明确失效均通过；断开DAP后直接重启采集返回status5，**恢复尚未通过**。当前仲裁只使AP缓存失效，DAP断开后物理SWD连接可能需重新attach，下一步定位并补恢复路径。详细本地证据：rtt8-app-flash.json、rtt8-first-hil.json、rtt8-dap-debug-hil.py。后者失败，未生成成功JSON。

### DAP 恢复与实际下载并发补验

明确一次无复位SWD attach可恢复后，固件ba0a1cf在目标epoch改变后、首次新目标IO之前恢复SWD连接；失败不执行目标读写，旧RTT游标不重放。四组C模拟回归、SES构建及SWD布局通过，新固件已升级STM32下载器。升级时磁盘返回超过脚本20秒观察窗口，随后按实际序列号及CDC行为确认已返回，没有重复升级。

原始失败脚本无需额外attach即通过：八路256字节哈希、275组Watch、真实DAP暂停/单步/继续、目标busy拒绝与流失效通知；显式重启采集后八路均有数据、141组Watch。强制扇区擦写（smart_flash=false）并发测试也通过：APP完整读回，前20KiB Bootloader未变；包含下载/校验的DAP阶段约8.54秒，重启采集后八路及143组Watch恢复。证据为本地rtt8-dap-debug-hil.json及rtt8-dap-flash-hil.json。未据此宣称GUI/CLI/MCP全边界、HPM或硬实时延迟完成。

Flash harness第一次从任意暂停状态直接执行算法发生IPSR=3，加入reset_and_halt后通过并恢复APP。产品backend已有_prepare_algorithm_execution，但目前按_algorithm_reset_required条件执行；下一轮检查内置目标是否也需要该保护，避免只覆盖Pack/自定义FLM。

### 内置算法的下载前状态保护

检查发现PyOcdBackend以前仅为Pack/FLM、security_family=stm32f103-rdp1和少数nRF内置目标启用算法前reset-and-halt；直接指定stm32f103rc而不带security_family时会跳过。已统一该Cortex-M后端的破坏性Flash操作前置状态，保留连接/只读不复位和一次算法准备复位的行为，删除按型号重复判断。整个test_online_flash_backend.py：137通过。

真实PyOcdBackend（非单独FileProgrammer）使用内置stm32f103rc，解析测试HEX、program、verify通过。计数确认program前一次reset-and-halt、verify无额外复位，boot前20KiB保持不变；随后显式启动测试APP。证据：本地rtt8-production-backend-hil.json。该结果不外推所有支持芯片真机认证。

### HPM HEX 基础实现（尚未接入烧录）

新增hpm_image.prepare_hpm_hex，复用ImageInspector解析，完整验证后在调用方暂存目录原子替换规范HEX；排序并保留稀疏地址，不展开大BIN，数据记录最多128字节并切开64KiB边界。8项测试通过，包含同扇区不连续记录、逆序输入、地址边界、重叠/校验/EOF错误以及失败不覆盖旧文件。

固件应用层837104e新增固定内存的规范HEX reader，严格长度、校验、EOF、错误锁定、XPI地址、32MiB数据及记录数量限制的C编译测试通过。现有子模块解析器只读审查，未修改。该模块尚未纳入固件烧录绑定/构建，不声称HPM HEX已可用；下一步完整预检、先合并擦除后写入校验、在线/脱机接入及真机。约定详见固件docs/hpm-hex-upgrade.md。

### HPM HEX 调度核心

固件9a85ffb新增hpm_hex_program：固定524字节行缓冲及单记录，完整预检后初始化，合并覆盖扇区并完成全部擦除，再写入和校验；不为稀疏空洞分配整片BIN。编译生产C代码的模拟NOR测试通过：末尾非法记录零擦除、同扇区多段、整段空白扇区保持、地址越界及各阶段失败终止。解析器及调度测试已加入固件CI，尚未取得CI结果。

仍未接入SD/ROM绑定和实际固件构建，不宣称HEX功能可用。发现generic algo表dev_sz=1MiB，而HPM6E00EVK SDK board定义16MiB，绑定前需核实当前加载算法flash_get_info ABI并取得真实geometry；不能误用静态表作容量限制。若查询需初始化，应在完整语法预检之后查询，然后在任何擦除前校验最大数据地址。

### HPM ROM/SD绑定接入（未真机）

固件e69b96b已接入hpm.program对HEX扩展名的大小写无关识别。BIN/HEX复用目标初始化，HEX固定1KiB文件缓存、严格完整语法预检后查询实际ROM geometry，再校验最高地址，之后擦除/写入/校验，成功才reset。地址参数要求0x80000000，实际数据地址来自HEX。

对当前1196字节algo_hpm5300.inc实际反汇编确认0x336为单输出指针ABI，返回容量/扇区两个u32；新flash_get_geometry校验当前blob形状并调用该接口。生产函数编译测试覆盖寄存器参数、错误和结果范围，HEX解析/调度测试通过。SES候选构建和SWD布局通过；未刷HPM探针，实际geometry/SD/性能/内存/BIN回归以及主机双路径仍未验收，未声明HPM_HEX能力。

### HPM HEX 首轮真机闭环

固件6cfdc45已升级到HPM下载器；STM32下载器保持ba0a1cf。独立`hpm.program_hex(filename)`及Pika生成绑定避免旧固件把HEX当BIN，尚未开放主机公共入口。SD读取边界/EOF/读错/seek错/IRQ恢复及独立入口编译测试通过，SES构建和SWD布局通过。

真机确认geometry为16MiB/4KiB。HEX逐记录误用BIN流水线的final标记导致第二条记录失败，已改用既有同步flash_program；最终51,244字节hello-world HEX烧录、逐段校验与复位成功，用时4.34秒。同程序BIN回归成功，固件报告822ms。初次无诊断失败发生在擦写前，新增allocation/open诊断；文件更新后进入烧录，尚未确证初次失败根因，不能据此宣称MSC/固件缓存一致性已通过。

证据在本地构建根reports/hpm-hex-upgrade.json、hpm-hex-first-hil.json、hpm-bin-regression-hil.json。仍待稀疏未覆盖扇区/负面输入真机、MSC并发修改防护、内存/性能、主机在线脱机及GUI/CLI/MCP。未进行长稳，未更新安装包和Skill。

### HPM HEX 边界与文件事务

同名文件覆盖测试重现FatFs旧缓存问题：第二份文件仍按上一份错误文件处理。固件f74af2a为HPM BIN/HEX增加统一文件读事务，打开前拒绝脏metadata并失效干净窗口，整个预检/擦写/校验期间与MSC写互斥；MSC独立线程使用双向原子占用，不在SPI写期间持续关闭IRQ。未修改FatFs/CherryUSB SDK；既有MSC回调错误沿SDK WRITEFAULT返回。

新增生产C编译测试覆盖缓存/双向占用/拒绝与释放，五项相关C harness及SES/SWD布局通过。最终固件已刷HPM，真机通过同名连续覆盖、末尾校验错误在初始化前拒绝、16MiB容量越界在擦除前拒绝、奇数长度同扇区稀疏写入回读、中间未覆盖4KiB保持一致、恢复hello BIN。证据reports/hpm-hex-boundaries-hil.json。并发MSC写拒绝尚未实机，只能引用编译回调测试；其他文件消费者也未因此获得保护。公共在线/脱机入口、内存审计和最终安装仍待推进。

### HPM HEX 主机底层与脱机准备接入

MKLinkFlash.burn_hpm_hex复用prepare_hpm_hex，完整解析后探测无副作用的hpm.program_hex()，严格要求签名返回-1；旧固件在复制前拒绝。BIN/HEX共用配置/复制/结果解析，配置失败停止后续烧录，文件名沿用统一转义，HPM_HEX_FAIL/HPM_BIN_FAIL不能被先前成功文本掩盖。Device.flash按HEX绝对地址路由，不加载FLM或追加SWD复位。

实际主机burn_hpm_hex已在HPM6E通过规范化、能力检查、绑定磁盘复制、配置和烧录校验；证据reports/hpm-host-hex-hil.json。Device路由及BIN回归28项通过。脱机配置允许V4 HPM HEX，整组烧录前检查独立入口，暂存阶段统一规范化所有HEX后才修改设备文件；脱机及HEX相关99项通过（指定本地FLM资源后）。首次缺FLM环境的21项失败不属于功能回归。

这是底层与部署准备验收：HpmRomBackend、online_flash_api和GUI尚有BIN限制，尚未开放完整在线流程；脱机脚本尚未实机执行，AI/CLI/MCP和Skill尚未完成HEX集成验收。持续目标未完成。

### HPM 在线后端与脱机脚本真机

HpmRomBackend和online_flash_api已接受HEX；共用decode_hpm_hex校验XPI边界，在线verify按真实稀疏地址分块读取，空洞不展开，进度以有效数据量计算。OfflineFlashView允许HEX且说明绝对地址、新V4固件要求及扇区空隙擦除语义。后端/API/HEX相关264项通过（API测试使用实际ImageInspector），在线/脱机GUI142项通过。

生产HpmRomBackend在真实HPM6E完成51244字节HEX烧录约5.68秒、独立二进制回读校验约1.01秒。主机deploy_offline_bundle生成并复制规范HEX和真实Pika脚本，load.offline执行至loaded successfully及auto download finished，未走FLM或通用SWD复位。证据reports/hpm-online-backend-hex-hil.json及hpm-offline-hex-hil.json。这不是物理按键触发验收，也不是浏览器完整操作验收；真实浏览器、CLI/MCP/Skill、安装包及其他功能矩阵仍待推进。

### HPM HEX CLI与真实Web在线验收

真实CLI flash经共享后台返回success/verified=true，无重放，证据reports/hpm-cli-hex-hil.log。源码Skill及两份参考页更新HEX能力门禁、绝对地址、扇区空隙和烧录期间磁盘写入约束；Skill验证器及55项上下文边界测试通过，尚未替换本地安装版Skill。

生产前端构建通过。真实IAB浏览器选择HPM6E80/hpm6e00evk、上传HEX发现原canStart仍强制isBin，已去除并将现有HPM用例参数化BIN/HEX，补检无BIN地址弹窗、可启动、请求base_address=null；116在线GUI测试通过。重新构建后真实浏览器完成HEX烧录/独立校验/复位/断开，显示100%及succeeded。前端HPM几何提示改为ROM容量检查，避免错误显示不能正常擦写。

已知待修：任务日志PROGRAM/VERIFY字节数沿用HEX源文本大小107731，实际有效数据51244，比例正确但数量文案错误。GUI --no-browser未保持会话时可能在浏览器接入前5秒回收，旧提示仍称后台保持运行；验收以一个限时正常CLI伴随会话保持启动，关闭后已结束。脱机GUI完整操作、stdio MCP、安装及剩余矩阵未完成。


### HEX 进度字节数收敛

任务PROGRAM/VERIFY日志改为有效数据段长度合计，不计算HEX文本编码和稀疏地址空洞；文件元数据大小保持原含义。BIN与稀疏HEX参数化回归验证25%/50%/100%日志和总进度，任务及镜像相关117项通过。本轮未重复硬件擦写：上一轮真实Web烧录正确，本次仅修改日志统计。关闭本轮创建的在线测试页面和遗留配置页面后，后台进程已自动退出；未强制终止。本地安装及其他矩阵项仍待完成。


### HPM HEX stdio MCP 真机

通过实际子进程stdio传输调用connect/start_job/job_status/disconnect，明确选择HPM探针和hpm6e00evk，单次提交HEX烧录；保留任务ID并轮询原任务，最终succeeded、success=true、verified=true、algorithm_source=hpm-rom-api，无重放。Pika输出实际16MiB/4096字节几何与loaded successfully，固件耗时约4.94秒。证据reports/hpm-mcp-hex-hil.json与hpm-mcp-server.log。此项覆盖真实MCP路由；未代替全部MCP工具验证。GUI启动提示已同步当前约5秒无人使用自动退出策略，手动开页前的启动等待仍需处理。

### 固件静态内存复核

本轮检查已用于HPM真机的Debug链接map：hpm_hex对象1190字节代码/24字节只读数据、hpm_hex_program 836字节代码，二者无静态RW/ZI；mux_runtime静态ZI为676字节。全镜像RW4016、ZI230877字节，其中链接器预留heap48128/stack4096；这些分区数字不能相加推断动态可用堆。Pika控制台栈4096放置AHB SRAM，HEX使用有界行/记录缓冲；尚未测量最坏调用路径的栈高水位。静态map不是运行时内存裕量验收，也不是全固件内存优化完成。


### 完整Python回归与FLM失败边界

主机a9badd2a整套运行完成：4091 passed、1 failed、3 skipped，796.79秒，证据reports/full-python-a9badd2a.xml。唯一失败为test_custom_flm_remove_deletes_unreferenced_payload的Windows WinError5原子registry替换拒绝；单独完整文件复跑5项通过，尚未证明外部占用来源，不称整套绿色。代码读取/写入路径均关闭文件句柄，未添加猜测性自动重试。新增添加/删除时替换拒绝的事务回归：旧registry及算法保持、无残余新算法或临时文件；自定义FLM及在线API共114项通过。

三项跳过分别为仓库本地算法包路径检查，以及两项依赖未安装hil_core.observe的真实观察桥测试；本轮通过MKLINK_BUILTIN_FLM_ROOT使用外部现有算法包，不能把该路径检查跳过写为通过。随后GUI整套回归完成：85个文件、858项全部通过，76.91秒；存在既有Node localStorage及Vue生命周期测试警告，未据此宣称浏览器实机覆盖。


### RTT八路共享SDK与SuperWatch并行真机

两个SharedDevice客户端通过同一共享后台运行：非法通道8被拒绝后可正常启动0–7；第二客户端无参数订阅，不创建第二串口读取器；逐通道从cursor0读取同一历史前缀，均lost_bytes=0。借用客户端逐路发送256字节（覆盖00/FF）后，目标八路计数与滚动哈希全部匹配；借用者停止被拒绝，关闭借用者后原采集继续运行。证据reports/rtt8-shared-sdk-hil.json。此项不等于GUI八路格式与暂停已验收。

实机发现SuperWatch标量入口接受32字节整数组后，异步解码报unsupported scalar layout并停止线程。修复SuperWatchRuntime.add：先构建并编译候选采样布局，再提交items/blocks/version；不支持的布局返回错误、提示选择成员或数组快照，保持已运行布局。显式聚合类型也拒绝按标量加入。相关167项回归通过。复验使用数组元素标量与八路RTT并行，1971组完整采样、无报告CRC/解析丢帧；运行中再次添加整数组被拒绝，原采样无错误且仍运行。初始失败证据单独保存在reports/rtt8-shared-array-failure.json。数组快照自身、多种格式和其他边界仍待验证。


### 八路真实Web界面初验

主机8082c471配已构建前端（界面版本fdef5b0f7a00），通过真实IAB操作STM32：启动0–7，逐路切换日志/HEX/终端均收到对应通道数据，日志曲线可见。暂停0时显示seq82515保持不变，其他通道继续；恢复0、展开1后均推进seq82929，缓冲分别886/872行，未报告丢失。1920×1080下为三列多面板，窄窗口为纵向排列。

八路GUI分别发送GUI_CH_0至GUI_CH_7，目标回显rx均从1024增加至1032，通道7发送历史正确。使用GUI停止后按钮恢复开始，页面关闭且临时viewport已恢复。观察记录reports/rtt8-browser-hil.json；截图仅经CUA查看，未保存图像工件。此轮仅ASCII，编码/半字符、逐路全部暂停组合、保存日志和慢客户端边界仍待验证。


### inactive失败回收与八路UTF-8真机

在授权STM32测试RAM中，先关闭第7路生产使能，再把其UpBuffer大小临时设0：共享RTT start为异步受理，随后status明确running=false、error含channel7 inactive，资源表为空。恢复合法描述符/生产开关后，不调用stop直接再次start，八路采集均恢复。第一版验收脚本误把start受理视为同步成功，已按生产异步契约改为等待status终态；不是新增产品故障。

切换测试程序八路为ANSI/UTF-8模式，全部上行含UTF8=测试的正确原始字节；逐路下行测试🙂（每路10字节），目标计数和滚动哈希全部匹配。结束后停止采集，描述符、模式数组和生产mask全部逐项读回恢复。证据reports/rtt8-inactive-utf8-hil.json。本项证明真机传输及共享启动失败恢复，不替代GUI中文渲染、半字符跨帧和非UTF-8编码验收。


### 共享数组快照能力补齐

审计发现共享客户端只有superwatch_snapshot读取，无法执行GUI已有的选择/清除。新增superwatch_snapshot_select/clear能力映射及MCP superwatch同名action，直接复用现有GUI路由、目录解析和有界采样；未新增硬件读取器。共享参考文档同步，68项MCP/共享后台/SDK回归通过。

真实stdio MCP在STM32选择rtt_test_rx_bytes的8元素快照并启动采样，8值与一次目标RAM读取完全一致；选择start7/count2被拒绝，原start0/count8仍保持；clear后snapshot=null，随后正常停止/断开。证据reports/superwatch-array-mcp-hil.json。此项不证明所有数组类型、256元素上限或GUI快照交互已验收。


### CLI GUI启动交接收敛

修复mklink gui/--no-browser在页面尚未打开前5秒退出的问题：启动器复用已有RuntimeClient的无目标UART scope租约，最多等待60秒，GUI窗口注册后立即返回；超时/异常/中断统一finally释放。不增加后台全局宽限、额外保活协议或硬件初始化。指定device-port/AXF时仍按原请求连接目标。54项CLI/空闲回归通过，包含交接、超时及异常释放。

真实启动CLI --no-browser，超过5秒后经IAB打开，页面显示后台正常且目标未连接；CLI退出0，后台status只剩GUI window、connected=false。关页后观察后台PID已退出。此轮未精确测量从关页到退出的总时长，不能引用观察命令的短耗时作为5秒实测值；60秒超时路径当前为自动化证据。WebEntry/桌面各自启动路径仍按矩阵继续验收。

### HPM HEX 完整脱机 GUI 真机闭环

主机 fc413b7e、已构建前端 fdef5b0f7a00，通过真实 IAB 选择 V4/HPM6E80/hpm6e00evk、1 MHz，载入 HEX，生成独立测试脚本、部署两文件并点击触发测试。预览使用 hpm.program_hex() 能力检查及独立 HEX 入口，不需要 BIN 基地址。设备返回 16 MiB/4096 字节几何、loaded successfully 和 auto download finished，页面显示脱机下载执行完成。

按原 request_id 查询部署结果显示成功且未重新写入。U 盘文件经过规范化后文本哈希不同，但解码后的全部地址段与源文件逐项一致：51244 字节，与原 BIN 的 SHA256 一致。此项为 GUI 经 CDC 触发脱机脚本的真机验证，不是实体按键触发或物理 MSC 中断验证。关闭测试页面后后台 PID 已自然退出，无强杀。证据 reports/hpm-offline-gui-hil.json；截图经 CUA 查看，未保存图像文件。

### RTT 曲线刻度与八路中文显示边界

发现所有 RTT 通道共用的纵轴格式化在 decimals=0 时仍删除末尾零，110 会显示为 11、-1100 显示为 -11。改为整数直接保留 toFixed 输出，仅对小数去尾零。绘图回归直接检查 canvas.fillText 的六个纵轴刻度，覆盖正整数、负整数和小数；RttViewTab 共41项通过，生产前端构建通过。RTT/SuperWatch streaming 全文件93项通过，包含跨块中文与通道解码隔离；这些跨块结论为自动化证据。

真实 STM32 页面八路切换 UTF-8 测试模式，日志均显示 UTF8=测试，暂停快照保持。逐路清空后恢复均再次显示中文，最终八路暂停清空均显示0行。批量点击期间三路按钮状态未保持预期暂停，未将首次批量比较计为通过；按实际按钮状态逐项复核三路，清空自身且其他通道序号保持。此观察不证明批量点击异常根因，也不替代逐路全部组合。结束后目标八个模式字恢复0并读回确认，GUI停止、关闭。当前未保存截图；日志保存、半字符真机、非UTF-8 GUI及慢客户端继续。

### 编码切换保留已解码终端数据

复现 RttChannelDecoder.set_encoding 在更换解码器后清空 _pending_terminal，导致推送前的旧编码文本消失，而日志队列仍保留。移除这一步清空：编码只影响后续字节，已解码文本继续按原顺序推送；不新增锁、线程或采集路径。未完成的当前通道字节仍在编码切换时重置，其他通道半字符保持。

新增八通道×GB2312/GBK/GB18030/Big5 共32项回归，逐字节喂入新编码并检查旧终端文本保留及其他七路UTF-8半字符完整。完整RTT/SuperWatch流测试125项通过。此证据是生产解码器的自动化验证，不声称已触发实机编码切换的竞争时间窗。

STM32八路短测初次因固定等待1秒只读到目标RTT已有数字日志而失败，RAM已恢复；失败保存在 reports/rtt8-encoding-audit-initial.json（旧rtt8-inactive-utf8-hil.json被本轮运行写入此失败结果，历史通过记录仅为历史证据）。改用沿返回游标、最多5秒等待新标记，不重启/重放命令；reports/rtt8-encoding-audit-hil.json通过八路中文上行、每路10字节下行哈希、inactive失败释放与直接恢复，最终RAM恢复确认。启动受理不等于新模式数据已抵达，验收需观察有效数据而不是固定延时。
