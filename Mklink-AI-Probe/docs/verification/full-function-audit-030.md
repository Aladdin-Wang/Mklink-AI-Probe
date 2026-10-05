# 0.3.0 全功能循环审计

本轮覆盖主机、公开 Skill、下载器应用层和目标测试工程。基线主机 `bef5c963`，V4 固件 `58c47a9`。已有报告仅作为历史证据，不自动计入本轮通过。禁止把静态清单、测试收集或模拟通过写成真机通过。长期稳定性测试暂停；不增加 WinUSB，不修改 SDK/Arm2D/MicroBoot，不自动合并或发布。

## 验收方法

每组功能分别记录正常、边界、并发、故障/恢复四类结果及准确提交、测试入口和证据。目标镜像必须先核对ELF/MAP载入布局与BIN基址；BIN转HEX不得默认从Flash起点生成。烧录读回通过与应用启动通过分开记录，后者需确认运行计数推进和新生成的输出，残留RAM/历史RTT不算运行证据。状态使用：待验证、自动化通过、真机通过、受阻。共享实现可以复用底层测试，但 GUI、CLI、MCP、SDK、远程入口的参数传递、错误反馈和生命周期必须分别验证。缺少器件、外部从站或另一物理主机的项目保持待验证。

## 功能矩阵

| 编号 | 功能及入口 | 本轮必须覆盖的行为与边界 | 当前状态 |
|---|---|---|---|
| A01 | 探针枚举、身份、别名、端口角色 | 零/单/多探针，热插拔，COM 改号，重复别名，不选错设备 | 身份/卷绑定等121项分组通过；双V4实体显式选择和禁止客户端换绑通过；实际热插拔/改号继续 |
| A02 | 共享后台和连接 | GUI/CLI/MCP/SDK 多客户端，多探针隔离，租约，关闭/强杀，端口释放 | 双V4只读后台隔离、独立退出真机通过；CLI/WebEntry延迟交接通过，其余入口/异常退出矩阵继续 |
| A03 | 本地/远程会话与认证 | 服务启停，认证失败，过期令牌，代理边界，断连禁写，客户端独立关闭 | 当前STM32回环及同机WLAN实体双远程/本地隔离、认证拒绝、停止及轮换旧令牌失效通过；GUI/代理/跨物理主机等继续 |
| A04 | 配置和状态 | 时钟配置/错误确认、USB/串口重连，状态同步，错误恢复 | 待验证 |
| A05 | 电源与复位 | 遥测、合法/越界值，显式确认后才改变电压；无授权仅验证拒绝路径 | 双V4只读遥测接口真机通过，陈旧/损坏/零值/未就绪解析及控制保护自动化通过；无调压、无精度校准 |
| A06 | 工程和文件来源 | Keil/IAR/SEGGER/CMake，AXF/ELF/MAP/C 回退，文件变更、失效和重载 | 当前STM32 AXF副本变更/缺失拒绝变量访问、恢复及无客户端时显式重载真机通过；各工程格式、GUI及其余边界继续 |
| A07 | 符号、类型和变量 | 结构/数组/指针/位域/宽整数/浮点，分页与搜索，缺失符号，边界地址 | STM32数组0/255/256/3071索引、末页分页、float和有符号结构成员解码、越界/缺失拒绝实体通过；指针/位域/宽整数及各入口继续 |
| A08 | 内存读写与导出 | 零长度/越界/非对齐/分片，读写校验、未知写入不重放，批量访问 | SDK实体4KiB/16区域/重叠乱序非对齐批读、变量写入校验恢复、14类拒绝及双客户端busy恢复通过；导出及各入口边界继续 |
| A09 | Dump/Flush/吞吐测量 | 区域重叠/大小上限/超时/取消，文件头与数据完整性，缓存边界 | Dump模式切换/容量/文件失败及有限采集取消已修并有实体证据；STM32 Flush SDK/CLI/MCP12KiB及八区域合计12KiB写回通过、数组恢复；HPM Flush 4KiB/八区域/CLI及拒绝边界通过；已修正测试镜像基址并重验运行推进/RTT恢复，GUI及其余故障边界继续 |
| A10 | 调试、寄存器、断点 | 暂停/运行/单步/复位，FPB 资源耗尽，状态恢复，ARM/JTAG 差异 | STM32实体DAP六槽耗尽拒绝/释放/实际命中通过；低层负槽位写入已修、相关90项自动化通过；共享各入口/JTAG继续 |
| A11 | HardFault | 堆栈、寄存器、源码定位，缺失符号/无效栈/未发生故障 | 已修显式零故障快照误暂停及HPM绕过检查；STM32零故障/非法SP、HPM明确拒绝及恢复实体通过；STM32真实UDF异常PSP帧/故障函数源码行及CLI/stdio MCP入口、恢复八路RTT通过，GUI/缺符号等继续 |
| A12 | SVD/外设观察 | 型号选择、寄存器宽度/访问权限，非法 SVD、只读外设及采样边界 | 有限外设采样取消接入既有机制，103项相关回归通过；STM32 GPIOB.IDR真实TCP断连释放/读取和重采集恢复通过，其余入口及边界继续 |
| A13 | ARM 在线烧录 | BIN/HEX、多段、扇区/整片、FLM/Pack 选择、校验、失败恢复 | 新固件STM32 DAP强制APP扇区擦写/完整读回及boot边界通过；GUI/CLI及格式/算法矩阵继续 |
| A14 | HPM 在线烧录 | BIN 与新增 HEX、ROM API、多段/稀疏/跨扇区/地址映射、错误校验与越界 | 已实现；自动化及HPM实体写入/读回、稀疏/空洞保持、错误校验/容量拒绝和在线入口有证据；旧测试BIN转HEX基址错误已发现，正确BIN基址下载/启动本轮通过，正确HEX CLI/真实MCP完整读回及启动已补验；GUI在线HEX正确布局完整读回和启动本轮通过 |
| A15 | 脱机部署和执行 | ARM/HPM BIN/HEX，预览、MSC 身份、已有文件、传输中断、完成反馈 | HPM HEX完整GUI预览/部署/CDC触发脚本及终态查询真机通过；正确布局HEX部署/CDC触发脚本完整读回及应用启动已补验；GUI正确布局部署/触发与启动本轮通过；物理按键、MSC中断及ARM回归待验证 |
| A16 | 烧录任务生命周期 | 请求去重、超时未知终态、查询、取消、重启记录，多客户端观测 | 待验证 |
| A17 | 算法目录/Pack/自定义 FLM | 目录完整性，目标联想，资源缺失、范围及 Bank；HPM 不走 FLM | 待验证 |
| A18 | 选项字节/安全/OTP | 预览、确认和不可逆保护，型号限制、越界；禁止自动永久锁定测试 | 待验证；真机范围受授权约束 |
| A19 | RTT 初始化与停止 | 自动/显式地址，无效描述符、inactive 通道、启动失败回收、重试 | 自动化及真机inactive失败清理、无需stop直接重试通过；GUI故障提示/自动搜索边界继续 |
| A20 | RTT 0–7 Up/Down | 八路实体逐路/并发收发、二进制/中文/半字符/回绕、空/满、通道独立性 | STM32八路Up/Down含00/FF、256字节逐路哈希真机通过；半字符、满缓冲和跨入口边界待验证 |
| A21 | RTT 展示与交互 | 每路日志/终端/HEX/曲线，独立编码/暂停/清除/保存/收起/发送历史 | 八路实体GUI日志导出内容/保存故障注入、发送历史恢复及双窗口暂停隔离通过；原生磁盘保存/历史重载/慢客户端等继续 |
| A22 | RTT 流量和边界 | 包长上限、坏帧、CRC、序列、背压、队列淘汰、慢客户端、重连 | 八路64KiB历史淘汰/精确损失计数与快慢SDK客户端实体通过；容量/游标/新会话32项及相关125项通过；八路TCP完全不读反压/队列回收自动化通过；物理断连继续 |
| A23 | RTT 传统串口兼容 | 普通串口助手单路映射启停，MUX 切换和解析隔离、退出释放 | 实体八路逐路传统映射Up/268字节Down哈希、退出到MUX及八路恢复通过；已改有界批写，满队列/DAP占用时停止回执通过；停止取消不保证排空，USB上游溢出仍未覆盖 |
| A24 | SuperWatch | 标量/数组/结构、多组、写入、曲线/回放/导出、15区域/128B/周期边界 | 当前AXF数组8元素采样与内存一致、四类非法范围拒绝保留选择、八路RTT并行、Watch停止不影响RTT及重启新采样真机通过；GUI/曲线/回放/容量等继续 |
| A25 | VOFA | 采样格式、通道/速率、显示/导出、背压，资源冲突及停止恢复 | 待验证 |
| A26 | SystemView/RTOS Trace | ARM/HPM 采集、解码/同步/溢出、启停、离线文件、RTT 通道共存 | 待验证 |
| A27 | UART/串口助手 | 参数、文本/HEX/编码/发送、日志、独立端口、多窗口、拔插恢复 | 本轮相关后端747项分组与GUI39项通过；模拟生命周期及本机网络路径已验，物理UART/拔插及真实GUI继续 |
| A28 | Modbus | 支持的功能码逐项、CRC/异常码/长度/地址、超时轮询、RTU 从站 | 相关自动化通过；FC1/2/3/4/5/6/15/16共享CLI及FC7/22/23真实编解码+模拟串口已覆盖，物理从站待验证 |
| A29 | YMODEM | 多包/末包/重试/取消/超时/重复确认、传输资源隔离 | 协议14项及共享上传/生命周期相关测试通过，新增ACK超时重传、截断源、包间取消与尾包边界；物理接收器及重复确认剩余边界继续 |
| A30 | 固件升级 | V4 UF2 身份/格式/重枚举/恢复；V2/V3 不以 V4 成功代替 | 双V4升级路径已用于本轮真机；升级故障恢复、V2/V3实体仍待验证 |
| A31 | CMSIS-DAP 下载与仿真 | 流量开/关对照，八路 RTT+Watch 下真实下载/校验/断点/单步/重连 | 优先级/会话失效已修；STM32八路RTT+Watch并发DAP暂停/单步/继续和APP擦写读回通过，Bootloader保持；实体六槽断点及耗尽/命中已补验；更多负载对照待验证 |
| A32 | 固件调度与存储 | 目标访问仲裁、DAP 优先、USB背压、看门狗、栈/静态RAM/缓冲区上界 | 25项应用C harness均有通过结果；双V4 Pika只读命令短测未见增长，不能代表全堆/栈余量；双板有限烧录负载RT堆与线程水位已实测；全功能峰值/系统栈及MSC实机写冲突待验证 |
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

### Web 入口启动交接与 CLI 复用

WebEntry 原本在打开浏览器后立即返回，没有客户端租约，存在页面接入前约5秒被空闲回收的空窗。把 CLI 已验证的交接逻辑提取为 runtime.handoff_gui，CLI/WebEntry共同使用普通无目标UART scope会话，准备/开页后最多等待60秒，GUI注册即交接，超时/异常/中断finally释放。WebEntry超时明确报错；不延长后台全局空闲时间，不新增硬件或保活协议。

WebEntry与CLI共67项自动化通过，含开浏览器前已持有租约、超时与异常释放。实际调用start_web_entry，延迟超过5秒再以IAB打开认证页面：后台正常、未连接目标；入口进程退出0，后台状态仅一个GUI客户端。关页后PID自然退出。未改写操作系统协议注册，故不把此证据当作Windows外壳、macOS/Linux协议入口或桌面安装验收。公开Web入口文档同步共享停止/启动会话语义，删除旧owned进程管理说法。

### 串口、Modbus、YMODEM 分组审计

主机e63983eb分组回归747 passed、5项既有websockets弃用警告，65.12秒；XML位于reports/serial-modbus-ymodem-e63983eb.xml。覆盖UART命令口拒绝、开口重分类/失败回滚、短写不重放、读失败终态、停止等待期间租约保留；Modbus串行工作线程、队列上限、排队超时撤销、执行中未知写入不重放、轮询组边界及远程断开清理。共享CLI功能码1/2/3/4/5/6/15/16均有路由参数化，7/22/23有生产RTU编解码正常/异常响应测试，串口Wire为模拟；本机真实网络套接字测试不等于物理从站。

新增YMODEM六项边界：1/1024/1025字节尾包和CRC，数据ACK超时原包重传后再推进，源截断不补造数据，包间取消阻止下一数据包/EOT。整个协议文件14项通过；原有跨255回绕、NAK重传、握手超时、首包前取消和单CAN接收方取消保留。无生产代码修改。GUI串口/Modbus八文件39项组件测试通过；不能替代真实页面/物理串口测试。实体接收器、物理RTU从站、拔插、重复ACK及其他剩余矩阵仍继续，不按分组全绿认定全功能完成。

### 双下载器隔离与只读电源真机

主机0f427faf对当前两台V4同时建立独立普通会话，明确USB身份，各自PID和HTTP端口不同；多探针无选择参数被拒绝，已绑定客户端改绑另一台被拒绝。通过既有query_probe接口各读取版本和电源，两台后台均connected=false，不初始化目标、不改变电压。初版验收误用UART-only客户端的目标能力调用被409拒绝，已改用正式probe-only接口；没有放宽scope保护。

第一台最后客户端关闭后6.645秒HTTP发现消失，第二台原PID仍可读电源；第二台关闭后6.836秒HTTP发现消失。随后确认两个PID均已退出。这些时间是发现轮询观察值，不是精确串口句柄释放时间。读数为3454mV/37.706mA和3430mV/1.021mA，接口正常但没有外部仪器精度校准。证据reports/dual-probe-readonly-audit.json；初次scope拒绝状态单独保存。

身份、共享probe查询、MSC卷绑定、控制与电源遥测五文件121项自动化通过，包含COM重编号模拟、重复序列号隔离、别名唯一性、端口归属、陈旧/错误/未就绪测量；真实USB拔插与完整双目标并发仍待验证。本轮不改变生产代码或用户别名。

### 固件测试入口与有限内存实测

固件分支213cb3d修复三处过时的应用测试入口：JTAG缓存失效桩、SWD批量读新增初始化辅助函数及故障注入计数、SBA源码提取与XIP边界断言。25项脚本中24项在整组复验通过；剩余SBA随后独立复验，五种编译配置全部通过。补充跨旧1MiB边界、16MiB边界越界和ILM别名边界。仅修改测试和审计文档，未重新刷写固件；不能把主机模型当作物理时序证据。

主机c9c401dc在确认无共享后台后，按明确探针身份顺序打开两台V4，使用现有PikaStdLib.MemChecker，每台执行100次只读cmd.get_version()，在0/20/40/60/80/100次采样。STM32侧Pika当前占用5.05→5.03 KiB，HPM侧5.59→5.57 KiB，六个采样点均未持续增长。历史峰值分别保持15.98、18.14 KiB；未重置峰值，不能归因于本轮负载。删除诊断对象后关闭串口；未修改目标RAM/Flash或供电。证据为本地reports/probe-pika-memory-audit.py/json。

测量包含诊断对象本身，仅覆盖Pika分配器和有限只读命令，不是RT-Thread堆、各线程栈或RTT/Watch/烧录负载的内存验收。静态12KiB RT堆与链接器堆属于不同口径，不从Pika峰值推导可用余量。USB与Pika线程同名console，后续栈诊断必须区分实例。未据此削减任何缓冲、栈或堆配置。

### 有界线程栈诊断候选及构建缺口

固件f449147新增cmd.get_memory(-1)查询RT堆，0..31按实例查询线程栈水位；每64字节释放调度锁并重新确认对象身份，输出在锁外，最多扫描8KiB，不分配常驻缓冲。同名线程可区分；水位仅为填充值前缀估计，不是溢出证明。新增生产C模型测试通过，覆盖块边界、空/满水位、同名、线程删除、非法索引与栈范围。尚未刷机，不计真机通过。

本次重新生成SES工程发现既有prepare脚本把绝对中间目录拼成双盘符路径，已修复。随后以当前SDK生成Debug工程编译到链接阶段，但Flash布局失败，伴随FSymTab/TLS等放置符号错误；历史成功map与当前代码尺寸明显不同，构建参数/缓存来源仍须核对。没有扩大Flash区或改SDK来掩盖。当前artifacts目录UF2仍是此前旧固件，不能用于诊断候选升级；失败map/log为本轮输出。下一步优先恢复可复现构建，再做真实堆/栈负载测量。

### 构建恢复与诊断固件首轮真机

固件f89a562恢复构建：同工具链历史对象和无诊断对照链接可成功，失败map尚未完成布局/松弛，不可当最终尺寸。应用生成的Pika绑定采用-Os，CMake/SES一致保留其他选项；SWD/JTAG内核选项不变。SES未因工程选项改变自动重编对象，现由成功工程指纹触发全量重编；新增准备脚本重复执行/绝对路径/选项保留测试通过。最终全量及后续增量构建均通过，SWD关键地址未移动。802246字节BIN，UF2 SHA256为73a37598f7d81e9547c01fd551f3e54a0e0a05374aebeb40fdb9dfc2b4bbc59a。诊断模块RX434/RO162，静态RW/ZI为0；全映像RW4016/ZI230877，既有依赖警告仍在。

STM32侧V4已单次升级。升级脚本等待运行盘20秒超时，没有重复刷写；后续USB枚举/运行盘readme及新会话cmd.get_memory成功，故确认已运行候选，但不把初版升级脚本标为通过，也未查明恢复延迟原因。本地证据reports/upgrade-memory-diag.py和memory-diag-first-hil.json。RT堆total/used/peak为12200/10680/10680字节，剩余1520字节；13个线程均枚举，两条console未触及栈前缀为1736/3872字节，DAP708、RTT784、var784、main4264。数值是启动后估计，负载最小余量仍待测。HPM侧保留f74af2a。本轮未改目标工程/Flash，未重置峰值。下一步做八路RTT/Watch/DAP负载与负载后水位，再继续其余矩阵。


### 新固件八路负载、DAP断点和堆栈水位

STM32侧f89a562，两次有限负载均完成八路Up数据及每路256字节Down目标哈希匹配，SuperWatch同时产出。DAP会话期间MUX目标访问返回busy，ECHO仍可用，RTT/Watch收到失效通知；会话退出后显式重启八路和Watch均恢复。第一轮273个Watch样本、恢复143个；第二轮211个、恢复141个。真实DAP暂停/单步/继续及后续断点均经CMSIS-DAP；没有把busy让出描述为采集无中断。

第二轮实际FPB资源为6槽，全部占用后第7个请求被拒绝，比较器寄存器不变；清除后均为0。重新在与AXF字节匹配的SEGGER_RTT_Read入口设断点，实际停在0x08009022，移除并恢复运行；对应Flash32字节前后相同。此项验证的是pyOCD真实DAP/FPB路径，不代替GUI/共享调试API逐入口验收。有限时间约0.547秒包含调试步骤，不是DAP硬实时延迟保证。

两次负载后RT堆total/used/peak仍为12200/10680/10680字节；第二轮DAP栈未触及前缀596字节，RTT/var784，Pika console1736，USB console3844，main4264。填充值水位是估计，尚不包含APP重烧录、HPM、全部功能峰值和系统/中断栈。诊断-2/32索引均拒绝且后续堆查询成功。报告为reports/rtt8-dap-memory-hil.json及rtt8-dap-breakpoint-memory-hil.json；测试结束已停止采集、清除硬件断点并关闭串口。

审计还发现低层debug_control.set_breakpoint/clear_breakpoint接受负槽位，可能写到FP_COMP_BASE之前的FP_REMAP；set还会在高槽位校验前启用FPB。现拒绝负值、布尔及非整型地址/槽位，清除验证硬件槽位范围，分配/验证成功后才启用FPB。新增19项边界回归，相关共享/CLI/HPM四文件合计90项通过。测试模型首轮错误地允许FP_CTRL写入抹掉只读比较器数量，修正模型后通过；未在真机重放非法寄存器写入。此修复尚未进入安装版。


### 新固件双板烧录负载和完整读回

两台V4现均运行f89a562对应UF2（固件e1f761e只追加证据）。STM32在八路RTT和Watch活动时由实体CMSIS-DAP强制APP扇区擦写，关闭smart flash，全部ELF加载段读回一致，首20KiB boot区域与保存基线相同。显式MSP/PC/VTOR启动0x08005000 APP，非bootloader自动跳转测试。DAP期间MUX目标访问busy、流失效；显式重启后八路均恢复，Watch恢复144个样本。擦写/读回所在DAP阶段约8.518秒，不是调度时限保证。RT堆total/used/peak保持12200/10680/10680字节；DAP未触及栈前缀596→592，其余采样未下降。证据reports/rtt8-dap-flash-memory-hil.json。

HPM侧单次升级，运行盘及新诊断接口在45秒等待窗口内恢复，报告hpm-memory-diag-upgrade.json。随后BIN下载、HEX坏末尾校验/超16MiB容量拒绝、同扇区多记录及跨扇区稀疏读回、跳过4KiB扇区保持均通过，结束恢复hello_world BIN。独立全量读回51244字节，SHA256与源BIN均为57169b40aa606a8c70b5761215ee8122a3000e9cb0721a434e8961c4d18ec025。此为现有设备端烧录函数实测，不替代新固件上的GUI/CLI/MCP逐入口验收。

HPM RT堆used/peak保持10680，HEX后Pika console栈前缀1664/4096、DAP676/1024、main4264/6144。BIN脚本的内联采样插入未生效，未将其当内存证据；实际内存来自独立hpm-bin-memory-snapshot.json和hpm-hex-memory-snapshot.json。功能报告hpm-bin-memory-hil.json、hpm-hex-boundaries-f89a562-hil.json及hpm-final-readback-f89a562.json均通过。全部测试关闭串口、恢复目标镜像，没有为测试永久修改电源配置。仍缺全部功能峰值、系统/中断栈、MSC并发写与其他待验证矩阵，不削减堆栈，不启用长期soak。


### 02f92bb6 完整 Python 回归与资源前置条件复核

首轮未设置隔离工作树的 MKLINK_BUILTIN_FLM_ROOT：4137 passed、21 failed、4 errors、3 skipped，407.72秒。21项失败均涉及内置选项算法安全白名单，4个远程包夹具错误均缺少算法manifest。原因是本次执行漏配既有文档规定的资源前置条件，不通过修改白名单或跳过检查处理。原始证据full-python-02f92bb6.xml保留。

对既有主工作区资源执行完整性校验，7059目标/2224算法通过；显式设置资源路径并保持生产及测试代码不变，重新运行整个_maintainer/testing/tests，最终4162 passed、3 skipped、44 warnings，640.83秒，退出0。证据full-python-02f92bb6-assets.xml。三项跳过为仓库本地目录资源检查（本轮采用外部现有资源路径）以及两项缺少hil_core.observe的真实观察桥；不能记为通过。44条为websockets弃用警告。独立远程包构建和生命周期自动化已通过，不替代NSIS安装或跨物理主机验收。包含测试链接的运行目录由构建包装器安全保留，未强删。

只读审计发现RttChannelPanel.saveLog对saveBlobFile使用void而未处理拒绝，文件写入失败可能无界面反馈。该问题本轮尚未修改；下一轮补充通道独立错误、取消、重试、重复点击和采集不受影响的验证，再进行真实浏览器验收。发送历史当前由各面板独立内存维护，重新加载后的行为仍待验收。此次没有操作硬件或更新安装版/Skill，也没有据此标记全功能审计完成。


### 八路 RTT 保存错误反馈、发送历史和双 GUI

RttChannelPanel日志保存改为等待saveBlobFile并捕获异常，各面板独立记录保存错误与进行中状态。保存进行中防重复点击，失败可重试；用户取消不报错，新尝试清除旧错误。日志和采集不随保存失败清除或停止。新增RTT0–7参数化边界测试，逐路验证失败隔离、其他通道可保存、取消、重试以及保存期间新数据仍进入导出；相关49项通过。完整GUI为85文件869项通过，74.86秒；生产类型检查/构建通过，既有chunk大小及Node localStorage提示保留。更新跟踪的gui/dist。

实体STM32八路采集进入生产构建GUI，浏览器逐路注入文件选择器拒绝/取消/成功写入接收器：八路错误均只出现在本面板，取消清除错误，重试导出409–425行，各行ch字段均匹配对应通道，按钮重新可用。证据rtt8-save-browser.txt。真实数据来自下载器，选择器/写入接收器为测试替身：本轮未验证OS保存对话框或真实磁盘写入，不能把这项记作桌面文件保存通过。

八路通过GUI分别发送唯一字符串、从发送历史恢复输入均正确且无发送错误，目标后续日志各路rx为14。此处验证发送历史交互及目标计数，不替代先前256字节逐路哈希证据；跨页面重载历史仍未验证。证据rtt8-history-browser.txt。第二GUI同订阅八路，第一GUI各路暂停后行数固定1164/1146，第二GUI各路在1.2秒内均增长12行，证据rtt8-peer-browser.txt。证明两个窗口显示暂停互不影响，不等于已测慢消费者溢出或无限历史。

结束关闭第二窗口，第一窗口恢复后停止采集，界面回到开始且无错误，随后关闭窗口；陪测CLI正常退出0，后台8765无监听。未测量本轮退出时限、未重新刷写固件、未更新本地安装/Skill。下一步继续原生保存、八路显示/数据边界和其余全功能矩阵。


### 八路共享历史饱和、延迟读取与命令并行

STM32实体测试临时将目标日志周期从100ms改为5ms，同时采集RTT0–7和SuperWatch。一个SDK客户端持续逐路读取，另一个保持旧游标不读，八路均产生超过128KiB后再读。每路慢客户端报告lost_bytes等于available_end减65536，单页16384字节；本次丢失69441–70789字节。八路取回的每个字节均与快客户端相应绝对位置一致，快客户端全过程lost_bytes为0。证明64KiB保留容量及每客户端游标隔离，不能证明源端完全无丢包。证据rtt8-delayed-reader-hil.py/json。

有限负载约20.344秒，同时52次内存读取均返回，观察到单次最长0.091秒；SuperWatch末次sequence6906，仍running且样本年龄约0.012秒。此为该负载下的观测，不是实时延迟保证，也不替代DAP优先级证据。关闭两个读取客户端后owner采集仍运行；随后停止RTT/Watch，恢复并读回验证100ms原周期，关闭连接，后台8765无监听。未修改Flash、电源或下载器固件。

新增32项参数化自动化覆盖八路在65535/65536/65537/131075字节、997字节不等分写入边界、重复独立读取、16KiB分页、空尾页、其他通道隔离、负/布尔/字符串/越界游标和会话重启。与StreamHub、WebSocket API、远程订阅合计125项通过，6.07秒，无生产代码修改。TCP接收端完全停止读取导致的实际网络反压和物理拔插仍待验，不能将本次SDK延迟读取替代该项。


### 八路实际 TCP 反压及断开回收

新增test_stream_tcp_backpressure.py，使用生产StreamHub、stream_api路由及真实uvicorn/loopback TCP，逐一覆盖rtt-terminal-0到7。每路建立快/慢两个鉴权连接；慢连接缩小TCP接收缓冲且WebSocket max_queue为1，只读初始状态后停止消费。逐帧发布64KiB测试数据，直到实际服务端dropped_batches至少8，断言队列水位不超过64、dropped_bytes与淘汰批数乘载荷大小一致。快连接每帧序列和载荷与发布值完全匹配。

主动shutdown慢TCP连接后，3秒内active_clients降至1；继续发布neighbor-alive，快连接接收一致。最后关闭快连接并确认active_clients为0，服务器线程退出。测试同时限制20秒和512批次，若未制造实际服务端溢出则失败，不将“没观察到反压”当成功。数据由测试程序产生，属于真实网络层自动化，不是MCU数据/固件/DAP/物理跨机网络的复验。

八路新测试单独8通过，修正测试连接为显式loopback socket以避免依赖新版本proxy参数后，与现有StreamHub/API/远程订阅合计85通过，6.03秒；18条websockets弃用警告保留。新测试已纳入shared-runtime-checks工作流显式清单；远端CI结果待检查。无生产代码或固件改动。本轮补齐网络完全不读反压边界，后续仍需传统串口RTT兼容和其余功能矩阵。


### 传统串口 RTT 八路逐路映射与 MUX 互切

当前固件传统RTTView实现已经复用ml_rtt_channels，按目标实际Up计数计算Down偏移，支持选择0–7中的一路；SEGGER_RTTView.h遗留3通道宏未决定此路径。使用低层RTTSession模拟普通串口助手文本命令/裸数据，避免GUI自动选择MUX掩盖传统路径。每路先读目标计数/哈希，退出MUX后RTTView.start精确地址启用单路映射，成功解析8Up/8Down描述符；接收对应ch行，发送全部00–FF及近似停止标记RTTView.stoX共268字节。

首轮只等待150ms即停止，通道0计数仅增加30，哈希检查失败，脚本finally关闭连接；证据legacy-rtt-eight-mux-hil.py/json及终端异常。不能记为通过或直接判为串口控制字符损坏。随后独立测试每次发送等待2秒：八路每路268字节计数/哈希全部一致，其他7路计数不变；每次停止映射后MUX ECHO成功，最后恢复MUX八路采集均出现对应ch数据，报告legacy-rtt-eight-mux-wait-hil.py/json。首次失败已保留，不以第二次通过宣称快速停止无损。

应用固件write_rtt_and_receive_usb每处理一个串口字节即flush_rtt_down，而外层每轮最多64字节并持有目标访问锁；这一逐字节目标事务开销值得下一轮收敛，同时必须保留停止标记、部分前缀超时、环形队列、目标满缓冲与DAP让出的行为。尚未修改固件、未测量该临界区最大时长，也未证明停止会排空待发送数据。主机传统RTT会话/地址相关85项自动化通过，0.89秒。结束停止采集并关闭串口；本轮未写Flash或修改电源。


### 传统 RTT 批量下行固件 5ad7233

改为每轮最多64字节入队后一次有界目标写，空队列不访问目标描述符，无新增常驻内存。生产C测试覆盖实际外层泵、空轮询/单次写、满目标/环绕/失败重试/前缀超时；RTT引擎和DAP仲裁模型均通过。SES构建、SWD布局通过，UF2 SHA256 fc8aa31038ac8b1571b08456f8ac29a266038a0cc8498fdc568cba3da002727c，1604608字节。只升级STM32侧；HPM仍f89a562。

等待2秒的传统八路逐路268字节收发哈希/邻路隔离/MUX互切通过。150ms即停仍未收齐，停止后再观察3秒仍缺字节，证据legacy-rtt-eight-batch-consume-hil.json；停止是取消，不保证排空，不能声称提升了实测端到端吞吐。传统流期间实体DAP暂停/单步/运行及恢复通过，场景0.392秒；八路MUX+Watch实体DAP让出/失效/显式恢复也通过，Down每路256字节哈希正确，Watch274个样本、恢复140。见legacy-dap-batch-hil.json和rtt8-dap-legacy-batch-hil.json。

RT堆used/peak仍10680/12200；传统路径RTT栈未触及前缀436/1024，DAP负载后596，有限水位不代表所有峰值。串口已关闭。本轮模型暴露另一个待审边界：pending队列完全满时停止标记可能无法被消费，现有halted-target stop用例只填256字节未覆盖全满。下一轮优先复现并收敛该项，不将传统兼容标为全部完成。


### 传统队列全满及DAP占用时的停止修复

固件1a4bd0c将传统RTT输入/停止标记解析移出目标锁，DAP占用时仍解析；每轮最多64字节，512字节暂存保留旧数据，超量计数饱和保护。停止取消未发送数据，回执RTT stopped: unsent=N dropped=N明确标记暂存未发和暂存溢出，不代表目标应用确认，也不包含USB上游丢失。前缀超时在接收新字节前处理。C生产泵满队列/完整停止/无目标访问/计数/饱和及引擎、仲裁测试通过；首版测试误写13字节标记，修正为sizeof-1后旧5ad7233仍复现失败，新实现通过。

SES构建与SWD布局通过。STM32侧单次复制UF2 ce5c3b4544b0644039940f58548a9d37e375ffc8cc2dab57d7ab8b83ec282624；45秒等待运行盘超时，未重复刷写。随后正常USB枚举和新停止回执确认恢复，此限制保留。HPM仍f89a562。

实体DAP保持连接并暂停目标，传统RTT送入1024字节，约0.0519秒收到unsent512/dropped512停止回执；DAP读取/单步继续正常，退出后命令及MUX恢复。八路传统268字节收发哈希/邻路隔离/模式恢复通过；MUX八路256字节哈希+Watch+DAP让出/恢复通过，Watch211/恢复142样本。堆峰值10680/12200，RTT栈前缀436/1024、DAP596，有限水位无全功能峰值承诺。报告legacy-full-stop-dap-hil.json、legacy-rtt-eight-full-stop-hil.json、rtt8-dap-full-stop-hil.json。全部句柄关闭。后续转向HPM侧候选升级及其余矩阵，仍未更新安装/Skill。

### HPM 同版本升级及完整固件 CI 回归

HPM侧已单次升级1a4bd0c候选（UF2 ce5c3b4544b0644039940f58548a9d37e375ffc8cc2dab57d7ab8b83ec282624），运行盘45秒内返回；两个V4现在同一应用固件。BIN烧录51244字节通过，HEX末尾校验错误和实际16MiB容量越界拒绝后首64字节未改变；稀疏奇数长度记录读回一致，跳过4KiB扇区未改变。恢复hello BIN后全51244字节逐块读回，SHA256与源文件同为57169b40aa606a8c70b5761215ee8122a3000e9cb0721a434e8961c4d18ec025。堆used/peak10680/12200，两个console栈未触及前缀1736/3780，main4264；这是有限负载观测，不证明HPM RTT/DAP并发或最坏栈峰值。

本地证据hpm-full-stop-upgrade.json、hpm-bin-1a4bd0c-hil.json、hpm-hex-boundaries-1a4bd0c-hil.json、hpm-final-readback-1a4bd0c.json、hpm-1a4bd0c-memory-snapshot.json。全部串口句柄已关闭。

固件1a4bd0c远端CI失败暴露REPL测试桩未同步新拆分的目标flush；完整执行工作流又发现旧USB DAP恢复测试桩缺少会话状态定义。固件eabccc6只修正测试及文档，无新生产代码、无需重复刷机。REPL测试增加解析/目标I/O分开计数、锁持有断言、DAP/脱机/锁占用期间仅解析停止、REPL输出期间两者均禁止，以及SystemView单独运行。16项工作流命令现已本地全部通过，包括249087个USB发送和576个DMA模型用例。不能将之前局部测试通过等同于完整CI通过；远端推送后的结果另核对。安装包/本地Skill仍待最终资格验证，不增加WinUSB。
远端补核：eabccc6的push与PR工作流均success（37361730510、37361736627），旧失败保留在历史记录中。

### 共享 SDK 内存边界、流并行与双客户端冲突恢复

主机9ceccc1a、STM32侧固件1a4bd0c，两个SharedDevice客户端连接同一实际后台。先读取APP只读Flash的4096字节基线，再开启八路RTT及SuperWatch。通过单区域4096字节、倒序16个256字节区域和5个非对齐/重叠/重复/末字节范围读取，逐字节与基线切片比较。14类非法调用（零/负/超限/布尔长度、32位范围溢出、空/坏HEX/超长写入、空批次/17区域/总量超限/布尔地址）均获422；主机自动化补充不触达设备的拒绝证明，实体返回本身不证明总线未访问。

测试程序周期变量从100改125并验证，再非对齐写其后三字节并读回；全部结束后恢复100并确认。首次并发脚本错误要求两个同时请求均成功，被现有运行时非排队互斥策略409拒绝，finally仍恢复周期并关闭客户端，失败报告shared-memory-boundaries-hil.json保留。修正本地验收脚本后24次竞争请求12成功、12明确busy，成功读取逐字节一致，最大单次约141ms；冲突解除后两个客户端各自读取成功。没有自动重放未知写入；这里不证明排队公平性，当前接口根本不承诺排队。

八路日志各1230至1740字节，主机历史丢失计数均0；这不是目标端生成数据零丢失保证。SuperWatch持续运行并取得sequence922样本。关闭借用客户端后拥有者采集仍在运行，最终主动停止、恢复变量、关闭全部会话，10秒观察窗内后台发现接口确认退出。报告shared-memory-boundaries-recovery-hil.py/json。内存批读、SDK、共享运行时相关80项自动化通过（6.97秒）；带测试链接的临时目录保留，未强删。此轮无需生产代码修改或重新刷机，GUI/CLI/MCP导出、未知写入断连及其他芯片边界仍待验。

### HardFault 零故障误暂停与 HPM 架构拒绝

静态审计发现decode_hardfault只判断fault_regs字典是否为空，显式传入CFSR=HFSR=0或仅BFAR地址的快照会继续halt并返回Unknown fault。新增6个用例先在旧实现确认5失败/1通过，再在解码入口复用Cortex-M保护，并在CFSR/HFSR均零时直接返回None；不增加新的兼容分支。补全既有测试桥的current_mcu字段以适配真实架构检查。

首次双板实体测试确认STM32修复通过，但HPM旧hardfault检查路由把架构ValueError变为无正文说明的500。修复检查/详细路由返回带原因的422，并将检查放入已有异步目标租约及线程池，避免同步设备I/O阻塞事件循环。新增四个HTTP用例覆盖GET检查、GET详细、POST零/非零显式快照；设备读写与halt均未调用。HardFault/HPM保护/共享调试73通过，API/共享运行时另109通过。两个HardFault测试文件加入现有CI显式清单。

最终实体报告hardfault-zero-guard-fixed-hil.py/json：STM32实际CFSR/HFSR均0，MMFAR/BFAR仍含非零旧地址；默认检查返回null，三类显式无故障快照均返回fault:null。四种非法SP（布尔、非对齐、32位越界、负数）拒绝；目标tick由1397032增至1397834且DHCSR的S_HALT为0。HPM的fault_snapshot、hardfault_check及显式零/非零hardfault_decode均返回422和Cortex-M说明，随后32字节Flash读取成功；STM32周期仍100。两后台最终退出，未刷Flash、未改变电压。首次HPM500失败证据hardfault-zero-guard-hil.json保留。

此轮证明无故障和错误输入路径，不证明真实异常栈、缺符号时回退、源码定位、GUI操作或所有Cortex-M型号。安装/Skill仍待最终验证更新。非零故障详细诊断仍可能按既有行为暂停CPU，不应把本次修复理解为所有诊断均无暂停。

### STM32 真实 HardFault 栈、源码与恢复

预检查发现现有AXF不含g_hardfault_demo_arm：目标源码的hfdemo与关闭的背景压力测试共用启动条件，被链接裁剪。预检查失败发生在连接硬件前。目标main只增加背景测试关闭时启动已有hfdemo任务，保持显式魔数触发，不启用其他压力任务。Keil增量编译0错误0警告；APP AXF SHA256 0570dee765df4207c020521a4dfea90ecca86fcebaeebbbbb2437bead9156f9e。CMSIS-DAP按扇区烧录，所有ELF载入段均限定0x08005000及之后，逐段完整读回；前20KiB Bootloader与原始基线相同（SHA256 d7f5ba1130c7f5a3f624285350a2ea347e70d0e10c7220d4ae0fc73e0835b29c）。通过MSP/PC/VTOR显式启动APP，不代表Bootloader自动跳转已认证。见rtt8-hardfault-app-flash.json和rtt8-hardfault-keil-build.log。

主机92ceb8fa/探针1a4bd0c，SharedDevice写入明确触发变量，真实CFSR=0x00010000、HFSR=0x40000000，解码UNDEFINSTR/FORCED。报告定位mklink_hardfault_demo_entry及main.c:145，异常PC位于该函数ELF范围，现场读取其两字节为00de（udf #0）；PSP异常帧偏移36、EXC_RETURN=0xfffffffd，与RT-Thread保存布局一致。报告附带的LR候选不等同于完整精确调用栈，未扩大证明范围。

诊断后finally通过DAP复位并显式启动APP，Bootloader再次完整比较未变。首次脚本仅等0.7秒即检查RTT，通道0无数据导致失败；独立诊断确认tick递增、故障清除和八路数据。改为5秒上限轮询现有采集、不重复启动请求后，重做完整真实故障流程通过，八路恢复采集约1.483秒（各256至567字节）。最终故障已清除、触发变量归零、RTT停止且后台退出。失败hardfault-real-stack-hil.json、诊断hardfault-recovery-diagnostic.json及成功hardfault-real-stack-recovery-hil.json均保留。

目标重编译改变部分RAM符号：rt_tick=0x20004800、rtt_test_modes=0x20005060、rx_bytes=0x20005080、rx_hash=0x200050a0；RTT控制块仍0x20000b88、周期仍0x20000524。后续脚本应解析当前AXF，不能直接复用旧硬编码地址。此轮未修改主机/探针生产代码，无需重复已有自动化；GUI/CLI/MCP故障入口及缺失符号/栈损坏边界仍继续。92ceb8fa远端反馈契约成功，共享运行时检查尚在执行。

### HardFault CLI 与真实 stdio MCP 入口

主机e1ffdf18代码（生产行为92ceb8fa）、相同目标APP，重新触发一次真实UDF异常。SDK持有共享后台现场，实际python -m mklink hardfault子进程不带SP时返回UNDEFINSTR/FORCED及只读说明；带解析出的异常frame_address时返回完整八寄存器及main.c:145；非对齐SP返回退出码1及422说明。CLI不负责自动找SP，该能力由详细诊断提供，不能把寄存器快照与自动堆栈诊断混淆。

通过PythonStdioTransport启动真实runtime_mcp服务器，connect到同一后台后gui_call(hardfault)返回同样的故障函数、源码行和与SDK逐字段一致的异常栈。首次本地脚本按顶层fault_function取值失败：实际结构为单键result包装。第二版保留完整mcp_wire并按实际结构取值后通过，未修改产品协议。MCP disconnect及CLI退出均不关闭SDK拥有者，SDK仍可读取故障PC的00de指令。

结束通过DAP复位与APP显式向量启动，20KiB Bootloader完整比较未变，故障/触发变量归零；八路RTT在约1.349秒内重新收到各自通道行，主动停止并关闭后后台退出。成功hardfault-cli-mcp-wire-hil.py/json、首次脚本解析失败hardfault-cli-mcp-hil.json保留。未改生产代码或目标固件，本轮没有新的无关自动化重复。GUI与缺失符号/损坏栈等仍待验证；远端CI查询曾因GitHub API EOF失败，不能据此判断运行失败或完成，后续继续核对。

### Dump 模式切换与 MUX 完整样本修复

实体测试暴露两处生产缺陷。第一，RTT停止后MUX解码器仍保留，单次B1快照直接_write_raw文本命令，导致dump-memory stop did not restore command mode。_enter_dump_stream现在先调用现有Bridge._leave_multiplex，只有空闲且退出握手成功后才声明传统流；运行中的采样或退出失败直接拒绝，不发送文本、不回退重试。保留B1大块快照能力，没有改用多次小内存读来替代其语义。第二，DumpSampleAssembler不认识MuxWatchSession的format=mux完整区域帧，将其误作B1并报Dump sample size mismatch。现复用OLD完整帧的覆盖/长度校验分支处理mux；有序/无序及缺区域/长度错误仍有测试。

本地新增回归验证退出先于流声明/写入、活动采样与丢失退出回执不发送，及实际MuxWatchSession输出的拆分区域完整组装；MUX、快照、流、吞吐相关174项通过（12.95秒）。首次测试配置误把流接口15区域上限用于快照（快照上限8），在主机校验时拒绝，未当作产品缺陷；后续实体的两个生产失败报告均保留。

最终dump-memory-mux-fixed-hil.py/json：八路RTT运行时Dump返回409且RTT仍运行；停止后8个非对齐区域、2次快照共64字节逐区比较正确。MUX128字节区域5帧完整采集正确；9区域快照、period0多帧及无数量/时间上限请求拒绝。真实CLI采集2区域3帧并写入本地二进制文件243字节，与基线按样本/区域顺序拼接逐字节相同，SHA256 d35c56231db0860a1030dc02895cc10c2d0bd1e247d000e9b82699d277692b05。

0.5秒、10ms请求周期、64字节区域测量取得27个暖机后有效样本，约91.23Hz；协议总46帧，报告的CRC/帧丢弃/固件标志均0，无不完整尾部。这不是最大吞吐或实时保证，也不代表USB噪声物理注入验证。之后只读内存一致、显式重启八路RTT均有各自通道数据，停止并关闭后后台退出。未改Flash、电压或探针固件；其余Dump容量边界、文件失败/取消及Flush仍待继续。

### MUX Dump 容量实测与大块采集缺口

主机99f706b8、STM32现有APP和V4候选，dump-mux-capacity-hil.py/json实测两种1920字节配置：15个128字节独立区域，以及单区域1920字节由MuxWatchSession拆为15部分。每种3个完整样本（5760字节）逐区域与直接Flash读基线比较一致，完整帧/样本3，报告丢失与错误计数0。

1921及2048字节流式请求被422明确拒绝（最多15个128字节部分）；每次拒绝后128字节普通内存读取正确，再次正常流式采集成功，未留下采集占用。关闭后后台退出。未写Flash、未改目标变量或固件。本轮为实体容量证据，无生产代码改动，不重复运行无关测试。

尚未收敛的能力缺口：通用capture_dump验证允许更大的传统B1采集，但DumpMemoryStreamSession在支持MUX的设备上始终选择MuxWatchSession，因此大于1920字节的合法旧式批量采集被MUX容量限制拒绝；measure_dump_memory公开上限4096也受影响。不能通过缩小公开范围或把多个独立读拼成有采样时间戳的完整帧来隐藏缺口。后续需审查显式独占批量Dump与并行Watch的协议选择：保留完整B1/CRC/停止确认，在已开始MUX传输失败时不回退重放，避免普通SuperWatch悄然转成独占模式。该项保持待修，不将边界拒绝及恢复通过写成所有容量通过。

### 大块有限 Dump 保留 B1 能力

有限capture_dump与measure_dump_memory显式允许大块B1协议。DumpMemoryStreamSession在启动前构造MUX配置；只有配置容量/周期无法表示且调用者允许时才选择传统路径。MuxWatchCapacityError区分此情况与传输/其他错误。MUX握手或启动失败不会落入B1重试；普通SuperWatch默认不允许大块协议切换，仍严格使用并行容量限制。传统流通过既有确认退出MUX与原子READY声明，复用B1分块、CRC及停止确认，没有用独立内存读伪造完整样本。

新增容量1920/1921/4096选择、普通Watch拒绝和MUX响应丢失不回退测试。Dump/MUX/测量相关179通过（13.18秒）。扩展SuperWatch回归首轮5失败暴露两个旧测试桥停止成功后未设READY；真实Bridge成功停止已有该契约。修正测试桥状态，未削弱生产准入保护，完整188通过（2.08秒），包括暂停状态、写失败及HPM写入能力边界。

真机dump-bulk-capacity-fixed-hil.py/json：原15x128与单1920各3样本仍通过；1921、2048、4096字节B1各3个完整样本逐字节与Flash基线一致，其中4096样本由两帧组成。每次大块后普通读取及MUX128字节采集恢复。4KiB测量0.5秒取得8个暖机后样本，约25Hz/102400.7字节每秒；请求20ms，实测间隔约40ms，此为有限观测不是吞吐上限保证。传统路径每次parser_dropped_bytes=46，保留计数；CRC/丢弃帧/固件标志均0，完整payload校验正确，不能称全链路零丢弃。最终后台退出。没有重新刷机或改电压。更大容量、取消、磁盘失败以及该批量路径与实体DAP优先级组合仍需继续验证。

### 实体 DAP 打断大块采集：明确失效与显式恢复

16KiB B1采集与实体DAP重叠首次失败：DAP暂停/读取/单步在0.444秒完成，但旧固件暂停时重置采集状态，之后从第0块自动继续，主机因此报Periodic dump lost block sequence。保留失败证据bulk-dump-dap-hil.json，未将不完整数据作为成功样本。

固件03d72f5在配置时记录现有DAP epoch，每次读取或重发批次之前检查；目标变化则只发送带0x10标志的28字节CRC终止帧。队列忙时只重试终止通知，停止时核对请求generation以保护新请求；复用现有缓存，增加两个32位epoch字段。主机组装器在分块覆盖校验之前识别该通知，明确报Dump invalidated by DAP target change，不拼接新旧样本。错误目前仍按既有采集错误返回HTTP500；DAP持续占用时固件需待其释放才能发通知，主机可能先超时，不宣称即时取消。

主机相关145测试通过；新C测试验证实际终止帧字节/CRC、背压与新请求保护，固件17组检查全部通过。SES编译/SWD布局通过，原有宏重定义和unused-parameter警告保留。仅STM32所接V4升级到UF2 b1732bd861ad5ff8757859ee8f292d0346ef3946b6d0088ef65bb465adbaaa73（1605120字节）；HPM下载器仍1a4bd0c待补验。

真机复测bulk-dump-dap-fixed-hil：采集期间DAP暂停/读取/单步0.413秒完成；采集明确报失效。显式新采集取得两个16KiB样本，32768字节全部匹配Flash基线，随后普通读取及小块MUX恢复、后台退出。新版固件常规回归dump-bulk-after-dap-firmware-hil：1920字节MUX、1921/2048/4096字节B1每项3样本正确，4KiB测量约25Hz；parser_dropped_bytes46/47仍如实保留，不宣称全链路零丢弃。

dump-memory-after-dap-firmware-hil再次验证RTT运行时Dump拒绝409、8区域非对齐快照、MUX采集、非法参数、实际CLI落盘243字节哈希一致，以及8路RTT全部显式恢复，各通道均收到独立数据。停止后后台退出。本轮未写目标Flash或改变电压，APP/Bootloader保持原状；HPM候选补验、取消/磁盘失败、矩阵其余项目和最终安装仍待推进。

### HPM 新固件回归与 MUX 调试接口选择修复

HPM所接V4已单次升级到固件03d72f5，UF2 SHA256 b1732bd861ad5ff8757859ee8f292d0346ef3946b6d0088ef65bb465adbaaa73；双下载器现在一致。BIN hello烧录通过；HEX末尾校验错误在目标初始化前拒绝，超过实际16MiB容量的记录在擦除前拒绝。稀疏奇数长度记录逐段读回正确，同扇区多段保留且间隔4KiB扇区未变；恢复hello BIN后，完整51244字节读回SHA256仍57169b40aa606a8c70b5761215ee8122a3000e9cb0721a434e8961c4d18ec025。证据hpm-dump-dap-upgrade、hpm-bin-03d72f5-hil、hpm-hex-boundaries-03d72f5-hil、hpm-final-readback-03d72f5。此轮通过原有设备端ROM入口验证固件，不冒充重新验收全部GUI/CLI部署入口。

随后HPM MUX采集首轮失败（hpm-dump-bulk-03d72f5-hil）：Bridge.enable_multiplex在握手后无条件请求0x13 SWD附着，固件对JTAG明确返回status1。修复为使用现有0x10状态返回的debug_port选择：SWD1才发送非复位附着；JTAG2保留既有sysbus连接；长度不等于16或接口未识别则终止转换，不回退文本、不重放。新增SWD/JTAG各一项、损坏/未连接/未知状态四项回归；MUX/Dump相关151通过。首次命令误引用不存在的test_bridge.py，pytest未运行；纠正路径后的151才是有效结果。

修复后hpm-dump-bulk-jtag-fixed-hil：15x128和单1920字节MUX配置各3个完整样本正确；1921/2048/4096字节B1各3样本全部匹配直接Flash基线，每次大块后普通读取与小块MUX恢复。4KiB测量有效8样本约25Hz；27协议帧/13完整样本，结束时有不完整尾部，未计入完整样本。clock_hz=0表示本次未取得有效时钟值，不解释成目标零时钟。B1解析丢弃46字节计数保留，CRC/丢弃帧/固件错误标志0。关闭后后台退出。

STM32回归stm32-dump-jtag-selection-regression：16KiB采集期间DAP暂停/读取/单步0.441秒完成，采集明确失效；显式重启两个完整样本32768字节正确，普通读取与MUX恢复、后台退出。未更改STM32 APP或电压。固件/主机远端CI本次查询仍queued，不能写为CI成功；取消/文件失败、Flush及全矩阵剩余项继续。

### Dump 导出在写入失败时保留已有文件

CLI原来直接Path.write_bytes，会先截断既有导出文件，随后磁盘或写入错误可能留下半份内容。改为file_content.write_atomic_chunks：在目标目录建立唯一临时文件，逐段写入并检查短写，复用sync_file完成同步，关闭成功后才os.replace；任何提交前失败清理本次临时文件。已有文件正常成功时仍按既有语义替换。避免b''.join额外复制整份采集，不改变探针存储写入流程；不宣称掉电后的目录元数据持久性。

10项新测试覆盖有/无旧文件、部分内容后失败、实际流短写/ENOSPC、同步失败、替换失败、完整成功及临时文件清理；与既有文件/CLI回归共66项通过，新测试已加入CI。磁盘满使用故障注入，没有填满实际E盘。

真实STM32+CLI+Windows文件句柄测试dump-export-locked-file-hil.py/json：将既有文件以不共享方式打开，再执行4096字节x2样本采集并保存，替换被系统WinError5拒绝，CLI退出1且无成功输出，旧文件逐字节保持、临时文件清理。SDK同一后台随后普通读取和小块MUX成功；解除占用后显式新采集保存8192字节，与Flash基线重复两次完全一致，CLI已分离且最后后台退出。未写目标Flash或改电压。

取消仍为独立待验项：当前有限capture_dump在线程池执行，循环没有客户端取消令牌，必须验证CLI中断/失联后的租约、操作锁和最终释放；不能将文件失败恢复写成取消通过。后续继续该路径与Flush及完整矩阵。

### 有限 Dump 发起客户端退出后的协作取消

实体基线dump-client-exit-hil：CLI发起8秒/4KiB采集，确认资源准入后终止本测试子进程。存活SDK持续观察，CLI终止后8.56秒资源才释放，5秒以后仍busy。最终读取/MUX恢复且后台退出，说明没有永久死锁，但不满足约5秒释放预期。

复用既有active_operation会话上下文及5秒租约，新增只读operation_session_ended检查。有限capture_dump在启动/改时钟前及循环/逐帧检查发起会话消失或过期，抛出明确取消错误，finally仍通过原有stop确认；run_operation/settle继续持有准入直到线程结束。没有另建后台、定时器、采集登记表或直接关闭共享CDC；其他客户端存在不延长已离开发起者的有限采集。未给烧录/写入路径增加可中断行为。

回归115通过：启动前取消无IO、部分B1采集中取消不返回数据、只检查发起者租约且续租保持有效、停止确认失败不得伪装成功。首次测试把含同一4096参数的stop命令也算作重复start而失败；改为精确断言启动命令一次后通过，没有削弱停止检查。

修复后的dump-client-exit-fixed-hil把请求延长到15秒，终止CLI后约4.83秒资源释放；仍在线SDK普通读取与小块MUX重采集正确，最后后台退出。dump-live-lease-hil正常客户端持续续租，实际7.496秒返回175个4KiB样本共716800字节，全字节匹配Flash基线，无不完整尾部，关闭后退出；传统解析丢弃46字节计数保留。这是有限测试，不是长期soak。

范围限制：该合作取消依赖有效会话，只覆盖有限capture_dump。无会话GUI直接HTTP请求、measure及其他有限采集的断连/取消仍需继续审查；单次阻塞IO和stop同步有自身超时，4.83秒是本次实测，不是所有异常下5秒硬上界。未改固件、目标Flash/电压。主机CI查询仍queued。

### 无会话 HTTP 断连和吞吐测量取消

有限capture和measure两条路由共用一个断连观察器：FastAPI读完JSON正文后等待后续ASGI receive消息，用线程安全Event通知工作线程；会话调用同时复用现有发起者租约检查。Dump与measure共享check_capture_cancelled，均在开始前、循环及逐帧检查，finally确认stop后才返回。观察器在任何终态设置退出标志并取消/等待清理，不新增采集注册表或轮询硬件，不用于烧录及写入。

首版Request.is_disconnected轮询没有可靠穿过当前中间件链：自动化正常终态观察器清理也曾卡住，停止了对应pytest进程；随后实体TCP断连仍超过4秒未释放，保留dump-http-disconnect-hil失败记录。最终使用直接await request.receive，不再轮询取消范围内的receive。重新完整执行83项相关测试通过，其中两路断连测试让工作线程停在cleanup阶段，明确验证操作锁/资源仍占用、RTT启动拒绝409；只有清理完成才释放。

真实socket+STM32测试dump-http-disconnect-receive-hil：仅认证令牌、无session请求15秒采集/测量，确认资源已占用后断开TCP。capture约0.123秒、measure约0.134秒释放；存活SDK随后读取正确，正常0.5秒测量取得8个暖机后有效样本约25Hz，关闭后后台退出。该证据证明真实HTTP端点，不代替浏览器按钮/页面关闭验收。

测量CLI异常退出测试首次误带不支持的--json，命令未进入采集，未计成功。纠正后measure-client-exit-valid-cli-hil：15秒测量期间终止本测试CLI，约4.846秒资源释放，存活SDK读取和小块MUX恢复、最后后台退出。既有有限Dump的租约路径仍通过相关回归。无目标Flash/电压及固件变化。

范围仍明确：仅有限流capture/measure加入合作取消；传统多次快照及其他采样接口、浏览器交互和远程代理断连语义继续验收。取消不强杀工作线程，单次阻塞IO/stop仍有自身超时，不承诺任何故障下的硬释放上界。下一阶段推进Flush与其余完整功能矩阵。

### Flush 共享参数容量修复与当前候选真机回归

审计发现Flush解码上限12KiB与/_runtime/call通用16KiB JSON参数上限不一致：正常12KiB数据的HEX编码已超过24KiB，被共享入口提前拒绝。仅flush_memory允许48KiB JSON参数，以容纳12KiB含空格HEX及八区域头；其余能力仍16KiB。解码长度12288、区域数8、地址边界及禁止重叠的既有校验完全保留，不增加写入重试。MCP说明同步。

五项新共享入口回归包括12KiB紧凑/空格HEX成功（三次4KiB校验）、12289字节拒绝、过大JSON拒绝、其他能力仍拒绝超16KiB；与Flush/共享运行时共56项通过。首次测试复用不完整设备fixture执行attach导致current_mcu缺失，未到容量入口；改为建立真实Session并测试完整call路由后通过，没有改生产attach。12KiB是当前自动化边界证据，尚不称整块真机通过。

flush-current-candidate-hil在现有STM32专用mklink_benchmark_words符号解析出的4096字节数组内测试：SDK a5填充单批4096字节并完整读回，真实stdio MCP八个非对齐区域（二批，共40字节，含00/FF/80）逐区校验，真实CLI96个非重复字节按30/30/30/6四批正确写入。12289字节、九区域和重叠请求均拒绝，每次拒绝后数组完整4096字节与拒绝前一致。finally通过既有Flush分批恢复全部原值并校验，原始SHA256 61e1679eac869a152e6eccec16d4cf37ccfe137bf0253bc4cff5e1b8d9ac67bd，所有客户端关闭后后台退出。

本轮未写Flash/Bootloader、电压或升级固件；HPM Flush、12KiB整块实体边界、GUI入口及现场传输异常仍待验证。已有失败即停止后续批次、未知结果不重放保持相关自动化覆盖。远端a776e784反馈检查已成功，共享运行时检查仍queued；不是本轮新提交CI结果。

### Flush 12KiB 全容量实体边界

仅扩大STM32测试工程专用mklink_benchmark_words从1024到3072个uint32，初始化循环改为sizeof派生上限，未改下载器或主机生产代码。Keil0错误0警告，Code93264/RO19448/RW2616/ZI33272；新AXF SHA256 976acece4cf1fcaa393ecb15ebc89c398aef8becf32f899220bb0491d16300b0。所有有文件内容的ELF载入段均在0x08005000..0x08040000内，扇区模式更新APP并逐段读回，前20KiB Bootloader烧前/烧后完全一致，SHA256 d7f5ba1130c7f5a3f624285350a2ea347e70d0e10c7220d4ae0fc73e0835b29c。通过显式MSP/PC/VTOR启动APP，不扩大为Bootloader自动路由验证。

flush12k-hil：SDK写a5、真实stdio MCP以空格HEX写55、真实CLI写3c，各12288字节单批并经工具verify及独立三次4KiB读回全字节一致。八个1536字节区域合计12288字节，分两批（9216/3072）执行和校验通过。测试客户端全部关闭、后台退出后，用独立DAP暂停/恢复原始专用数组12288字节并完整读回；这是明确的恢复动作，不是重放Flush未知结果。未将此恢复称为Flush非重复12KiB吞吐验证。

flush12k-recovery-hil再次比较完整专用数组与保存原值、20KiB Bootloader与基线一致；按当前AXF符号启动RTT0–7，八路各自数据均收到，tick从120370推进到122364，主动stop/close后后台退出。证据还包括flush12k-app-flash.json与本地Keil日志。本轮仅新增实体证据与目标fixture，无主机生产变化，不重复无关自动化。

RAM符号因扩容发生变化：mklink_benchmark_words仍0x20003558（现在12288字节）；rt_tick变为0x20006800，rtt_test_modes0x20007060，rx_bytes0x20007080，rx_hash0x200070a0；RTT控制块仍0x20000b88。必须从当前AXF解析，旧硬编码脚本不可直接复用。双V4仍03d72f5，HPM目标未动。HPM Flush、GUI入口和真实传输中断边界继续，1b3060bd两个CI查询仍queued。
### HPM Flush 三入口与运行恢复分项验收

沿用现有HPM目标ELF的memory_test专用4KiB数组，在写入前确认全部1024个初始化值与源码公式一致，并保存原值。hpm-flush-current-candidate-hil：SDK 4096字节a5单批、真实stdio MCP八个非对齐5字节区域两批、真实CLI非重复96字节四批均verify及独立读回正确。12289字节、九区域、重叠请求均拒绝，每次拒绝后整块4KiB与基线一致。最后通过Flush恢复完整非重复原值并读回，SHA256 1ec2861ca0fdd6f30d15298e2d401cf11544515d9fb7858df415f66209d1ceaa；后台退出。本轮没有改Flash、电压或固件。

恢复验证不能记为通过：第一次RTT等待2秒为空；第二次5秒收到866字节历史日志，但wave_tick前后均10324677。随后独立只读诊断hpm-state-after-flush确认build_id正确、boot_stage=4、assert_line/trap_cause/trap_pc/trap_value均0，tick相隔1秒仍不变，后台退出。测试开始前未记录tick推进，因此不能认定由Flush导致；现有证据只证明写入正确和数组恢复，不证明目标继续运行。保留hpm-flush-recovery-stalled失败记录，下一轮定位目标调试连接/调度状态，不用Cortex-M专用resume API控制HPM。未将HPM 4KiB结果外推为12KiB容量验证。

此次主机11a9d579的Feedback与Shared runtime checks仍queued；前一提交检查显示cancelled，不记为通过。全矩阵及最终安装包/Skill验收继续。
### HPM 停留 ROM 根因：修正测试镜像基址与验收标准

hpm-controlled-reset-wrong-image显示cmd.set_reset返回正常提示符但RAM tick不变。独立CMSIS-DAP JTAG只读DMSTATUS为running而非halted；随后显式暂停读寄存器、确认恢复运行，PC=0x20019394、mtvec=0x20016080、mstatus=0，指向ROM执行状态。它不能证明应用正常运行。诊断使用单独测试脚本，不为产品增加第二套JTAG控制接口。

核对现有SEGGER MAP：option在0x80000400，header在0x80001000，fw_info在0x80001010。此demo.bin省略Flash前0x400字节，正确基址为0x80000400。此前本地hpm-bin-03d72f5-hil及canonical HEX生成脚本错误使用0x80000000；读回虽一致，镜像整体偏移导致复位不能启动。上一轮观察的RAM数值是残留，不能据此推断Flush停机。保留旧报告作为写入/读回及拒绝测试证据，撤回对这组错误基址镜像的应用恢复推断；其他入口也必须按正确布局补验启动，不能自动外推通过。旧canonical HEX及恢复脚本禁止继续用于目标恢复，改用hpm-hello-elf-base.hex与正确基址BIN脚本。

hpm-bin-correct-elf-base-hil按0x80000400下载同一51244字节BIN，hpm-correct-base-readback完整读回SHA256匹配57169b40aa606a8c70b5761215ee8122a3000e9cb0721a434e8961c4d18ec025。恢复后RTT出现新的tick日志，计数推进。hpm-flush-running-hil先证明tick运行，再完整执行SDK4KiB、MCP八非对齐区域、CLI96字节及三类非法请求不修改内存，最后Flush恢复4KiB原值；tick从52474推进到118777，后台退出。随后原有cmd.set_reset将tick从150586复位到1023，下一秒2061，原有HPM复位路径可以正常启动正确镜像，无需为本例增加固件补丁。最终再次RTT读取及运行恢复检查通过，关闭后后台退出。

本轮没有修改下载器生产代码、目标源码或电压，明确改进的是硬件验收标准、测试镜像布局和证据。HPM正确HEX启动/多入口回归仍需补齐；全功能矩阵与最终安装仍未完成。最后一次GitHub CI查询网络EOF，未取得新状态，不能记为CI通过。
### 正确布局 HPM HEX 的 MCP、CLI 与脱机脚本启动验收

hpm-hex-correct-base-entries先检查当前ELF所有Flash内有内容的可载入section与BIN相应偏移完全一致，最小地址0x80000400，再使用上轮生成的hpm-hello-elf-base.hex。依次通过真实stdio MCP start_job(flash)、实际python -m mklink flash、部署HEX与生成脱机脚本并CDC触发三条路径烧录。每条路径结束后独立共享SDK完整读回51244字节，SHA256均57169b40aa606a8c70b5761215ee8122a3000e9cb0721a434e8961c4d18ec025；开始RTT后先取一次游标，再等待新数据，第二次读取均有新HPM6E80日志且lost_bytes=0。运行计数分别21650→27493、23077→28953、9860→15720，逐次关闭后后台退出。

首次CLI测试误加该命令不支持的--confirm，被参数解析拒绝且未发起烧录；修正测试参数后只继续CLI与脱机两项，没有重放已通过的MCP作业。完整报告与分入口日志保存在本地hpm-hex-correct-base-entries.json及hpm-hex-correct-*.log。物理按键触发、GUI本次页面操作、MSC中断仍未验证，不能用本次底层脚本替代。

顺带删除CLI RTT帮助中陈旧的first is primary表述，改为各通道独立数据，实际rtt --help确认呈现。只有帮助文字变化，不新增镜像处理或调试实现，不重复无关自动化。67ca031b两项CI查询仍queued；下一步继续正确布局GUI入口和全矩阵。
### 正确布局 HEX 的真实 GUI 在线及脱机验收

主机affd1bf2、生产前端88de0f38002c、V4固件03d72f5，使用真实Chrome页面操作。在线选择绑定HPM下载器、HPM6E80/hpm6e00evk，上传hpm-hello-elf-base.hex，预览明确0x80000400–0x8000CC2C与51244载荷字节。点击开始后任务3bba7114-af0b-4277-bd03-30456e4d4983终态succeeded，界面显示program/verify/reset/disconnect完成。独立共享SDK全镜像读回一致、tick48374→54192，第二次RTT游标读取有新日志，网页会话未中断。

脱机页选V4/HPM6E80/hpm6e00evk，上传同一HEX并使用专用audit-correct-hex.py脚本名；预览包含hpm.program_hex，10MHz，未启用全片擦除/安全操作。部署返回2文件，随后点击触发测试，页面显示loaded successfully、auto download finished和绿色完成提示。独立共享SDK读回51244字节与BIN完全一致，tick27616→33413，后续游标收到新日志。两次读回SHA256仍57169b40aa606a8c70b5761215ee8122a3000e9cb0721a434e8961c4d18ec025。证据hpm-gui-online-hex-verification.json、hpm-gui-offline-hex-verification.json和已查看的hpm-gui-correct-hex.png，仅保存在本地。

开始时本轮CLI保活辅助进程持有build_workspace锁，独立验证命令被拒绝且未运行；仅结束该测试辅助进程后重试，网页独立会话保持，后台与其他进程未被强杀。最后关闭测试网页并核查后台进程退出。此次无生产代码改动，不重复无关单测；物理按键、MSC中断以及其余完整矩阵仍待验。
### 有限外设采样复用 HTTP 断连与会话取消

审计发现peripherals/capture可持续30秒，但没有接入已有有限Dump取消。路由改为使用同一_run_cancellable_capture；Device.capture_peripherals和capture_items透传可选cancelled，构造采集前、循环及逐帧调用既有check_capture_cancelled。取消抛错、不返回部分成功结果，finally仍确认session.stop，准入锁保留到工作线程清理终态。未增加独立线程、租约表或关闭共享端口，也未给写入/烧录增加中断行为。普通单次watch快照没有持续循环，本轮不改；传统多次memory_dump仍需另审。

103项相关回归通过，新增启动前取消无IO、部分样本取消后stop、stop失败继续暴露，以及模拟HTTP断连时清理未完成仍持有操作/资源锁、其他RTT启动拒绝409。现有CI已包含这两个测试文件，无需重复建工作流。

peripheral-http-disconnect-hil真实STM32使用现有SVD选择的GPIOB.IDR，只读15秒请求确认资源准入后断开TCP，约0.111秒资源释放。仍存活SDK读取APP基线一致，显式0.5秒新采样取得24个有效样本、无invalid/CRC/解析丢弃/固件错误标志，最后后台退出。未更改SVD选择、目标Flash、RAM或电压；这是本次有限实测，不承诺阻塞IO/stop异常下的硬时间上限，未覆盖物理USB拔插或长期测试。
### 多次内存快照取消贯通到单次等帧

普通/api/device/dump-memory允许最多64次快照，单次等待可到60秒，此前未接入会话/HTTP取消。现在沿用既有_run_cancellable_capture，capture_memory在调速前、每次读取前和结果返回前检查；read_dump_memory_regions_once将可选cancelled透传到底层等帧循环，并在进入流模式前及逐帧检查。取消不返回整批成功，原有_stop_dump_read在finally确认停止后才释放准入，不重放、不强杀线程。既有单次读/停止IO仍有自己的超时，这不是所有异常下的硬5秒保证。

新增回归验证启动前取消无IO、B1部分帧取消完成停止、停止确认失败继续抛出，以及样本发布后取消不再发起下一次读取；共享路由断连测试增加普通快照，清理未完成时操作锁与资源仍保持。首轮117项通过；追加MCP/观察记录测试发现三个测试替身不接受新增可选参数而有4项失败，更新替身签名后合并149通过、1跳过，未修改生产行为迁就替身。

snapshot-http-disconnect-hil实体STM32：发起64次4KiB快照，确认资源准入后关闭真实TCP，约0.113秒资源释放；存活SDK读取APP基线正确，后续0.5秒测量8个暖机后完整样本、CRC/帧丢失/固件标志0，解析丢弃46字节旧计数保留，后台退出。未改Flash/RAM/电压或固件。未测物理USB拔插/阻塞IO故障，长期soak继续暂停。下一步转向其余全功能矩阵与最终收敛，不反复重跑已覆盖正常入口。

### 完整后端回归与调试路由测试契约收敛

7eeaf300在显式设置既有MKLINK_BUILTIN_FLM_ROOT后执行全部Python测试：4261通过、1失败、3跳过、60条弃用警告，659.43秒；报告full-python-7eeaf300.xml保留。唯一失败是test_shared_debug直接调用内部endpoint时漏传新增Request，尚未进入设备操作；同一提交GitHub Shared runtime checks也为这一项失败（2420通过），Feedback checks通过。

将该测试改为httpx ASGITransport经过FastAPI实际路由调用，保留线程等待期间事件循环能运行、资源租约只获取一次且直到读取结束才释放的断言，并检查HTTP 200与halt_requested=false。未修改生产代码或放宽准入。调试、Dump、外设三个完整相关文件复测109通过，12.06秒。没有把分组复测写成修复后的全套重跑通过；后续CI和最终发行资格仍须核对。

三项跳过为仓库本地算法目录（本次使用外部资源路径）及两项缺少hil_core.observe；不可算作通过。含链接的临时目录由包装器保留，未强删；E盘剩余约1GiB，后续构建前需继续核查空间。此次没有操作实体设备，不增加已有真机覆盖结论；远程、符号、原生保存及最终安装/Skill等矩阵余项继续，长期soak仍暂停。

### 当前候选的符号源失效与恢复实体检查

主机a7f4dc09、双V4仍03d72f5，本轮仅使用STM32。symbol-source-current-hil复制当前AXF到独立报告目录，从原ELF解析rt_tick与专用测试数组地址。正常read_variable读取数组首元素与独立read_memory结果一致；随后依次追加一个字节、删除副本。两种状态均显示stale，read_variable/watch/write_variable各返回HTTP409，目录generation保持1；另一个无会话HTTP重载请求在SDK仍连接时也返回409。写入拒绝请求使用专用数组首元素的原值，读取前后相同不能单独证明总线零写入，未扩大此项结论。

每次通过copy2恢复原始内容和时间戳后，stale=false且变量读取恢复。SDK关闭后显式/api/symbols/reparse成功，generation仅从1增到2；未声称恢复相同文件必须重载，也没有绕过共享配置准入。tick3434363→3435424，原AXF SHA256仍976acece4cf1fcaa393ecb15ebc89c398aef8becf32f899220bb0491d16300b0，后台最后自行退出。没有写目标Flash、修改源AXF或改变电压；临时副本最后恢复原内容。

证据symbol-source-current-hil.py/json保存在本地.build/reports。无需生产修复，不重复上一轮完整自动化。本次只补共享SDK/HTTP实体文件生命周期证据，不能替代GUI、其他工程格式、复杂类型和远程入口；a7f4dc09 Feedback checks已成功，Shared runtime checks查询仍在运行。
### 损坏符号重载事务与类型边界实体补验

5d6eaac5候选使用当前STM32 AXF的独立副本。客户端退出后将副本替换为无效ELF，再调用实际/api/symbols/reparse，返回409、superwatch_transaction_failed、phase=reparse和Magic number does not match，确认不是活动客户端准入拒绝。旧目录generation与指纹保持，但stale=true，变量读取409；恢复副本并重载后generation从1到2、stale=false，专用数组首元素正常读取，后台退出。报告symbol-malformed-current-hil.py/json，无目标写入。

symbol-types-current-hil逐项搜索并读取3072元素数组的0/255/256/3071索引、g_pid_kp浮点和g_mklink_demo.temperature_x10有符号16位结构成员。首轮不停核比较动态温度的两次读取得到291/290，保留dynamic-comparison失败记录；这不是稳定快照，不能推断解码错误。修正测试方式为每项暂停目标，在try/finally内比较原始字节与变量解码并恢复运行，六项相等；只读操作没有写数据或Flash。末页offset3068/limit8返回最后4项，3072/负索引/不存在名称均422，随后有效末元素读取恢复，最后后台退出。这里证明当前正值的有符号类型解码，不扩大为负数、全浮点边界或任意结构覆盖。

无生产修复，无重复全套自动化。两份本地实体报告补足A06/A07部分边界；GUI、复杂类型、其他工程格式与远程仍待完成。最新查询5d6eaac5共享运行时CI pending，a7f4dc09仍in_progress，不能记为通过。
### 远程服务当前候选的回环与同机 LAN 实体生命周期

09d34d10、STM32 V4固件03d72f5。分别使用实际回环接口和本机当前WLAN地址，后者显式allow_lan并仅绑定指定地址，不使用通配监听。每轮创建随机临时认证令牌、空闲端口，原后台不存在且服务未启用才开始。缺失/错误令牌均RPC -32001且不新增设备会话；两个正确认证远程客户端显式agent.connect后，对绑定探针APP读取128字节，与本地SDK基线完全一致。首次脚本漏agent.connect导致-32004，保留before-connect报告；这是连接步骤缺失，不通过产品自动重连绕过。

通过probe.info确认绑定身份，后台客户端数由1到3；第一个远程客户端关闭后降至2，剩余远程与本地仍正常读取。运行时令牌轮换409；停止远程服务后降至1、旧连接读取失败，本地读取仍正确。停服务后生成新令牌再启动，旧令牌-32001，新令牌可连接并读取。两轮finally都停止服务，全部客户端退出后后台自行释放。APP前128字节SHA256 7315e68d5db0762b6810b2619ae9035f35c602bcf416dd7cd5719e7f1d501568；未修改RAM/Flash/电压，也未改变持久远程配置。令牌未写报告或输出。

报告remote-service-current-hil与remote-service-lan-current-hil的py/json仅保存在本地。两组都是真实WebSocket、共享后台和STM32，LAN仍为同一物理主机，不能替代跨主机、GUI、STCP代理、断连写入及远程流完整验收。无生产修复，不重复已通过自动化。最新09d34d10 Feedback checks成功、Shared runtime checks在运行；前两个文档推进前后的共享CI被取消，未当成通过。
### 远程 RTT RPC 多通道缺口修复

审计发现远程GUI使用通道API，而公开远程RTT RPC仍拒绝channels且读写只暴露默认终端。新增rtt.read_channel(channel,cursor)，经既有共享能力读取同一通道缓存，传递订阅session并在读取前后检查采集身份；原始HEX、游标、丢失统计原样返回，不新建八套线程/历史缓存。rtt.start透传channels；rtt.write增加通道及与data互斥的data_hex，仍限256字节、不重放。RemoteClient增加通道读取，bytes写入保留任意二进制。现有默认终端读取保留，能力操作目录从44增至45，增加操作是v2的可选扩展；旧服务器拒绝新操作，无自动回退。

八通道转发、原始数据/游标/损失保留、非法索引/布尔/负游标、文本HEX互斥、257字节及坏HEX、SDK二进制参数共新增20项。与远程共享、客户端、协议、订阅和GUI会话共117通过，11条弃用警告。扩展目录计数断言分散三处，前几次回归分别暴露尚未同步的44计数，最终全部同步到45；未删除目录一致性检查。

remote-rtt8-current-hil通过真实远程WebSocket启动STM32 RTT0–7，本地SDK借用。每路原始上行1054–2890字节与本地缓存同游标前缀一致，历史lost_bytes=0；八路分别下发256字节覆盖00–FF，目标每路rx计数+256、滚动哈希均匹配。远程拥有者关闭后本地仍running且八路可读，最后借用者退出、远程服务停止，后台自行退出。没有刷固件或写Flash；测试输入正常改变目标RTT接收统计。

首轮脚本固定等待0.6秒读到空页，失败清理又由借用者请求stop得到409；原记录保留。改为4秒有界等首数据且借用者只close，未绕过资源归属。两轮间确认旧后台已退出，不重放未知写入。证据只证明本机远程RPC，不替代GUI/跨物理主机/远程断网和长稳。公开远程文档同步，安装Skill仍待最后构建更新。
### 远程扩大回归、换代拒绝与 MCP 首次连接补齐

1e2f5e05基础上先增加通道读取前/读取过程中采集session变化两项测试，确认丢弃换代页且后续不继续读取。除文件名含packag的构建测试外，全部27个test_remote文件共471通过、32条弃用警告，136.82秒；包含干净MCP依赖安装验证，不等于完整安装包验收。

继续审计发现dispatcher的RTT详情覆盖了原操作清单，修复为保留清单再追加说明。远程MCP仅有remote_call且不接受agent.connect，首次目标接入缺少工具；新增remote_connect(site)，只调用已有非强制agent.connect，复用已有目标而不调用agent.reconnect。不新增设备连接实现或重连重试。公开文档与精确工具清单同步，文档检查首次因旧清单缺remote_connect失败，更新后最终相关55项通过；不把修改后的局部复测写成再次471全套通过。

remote-mcp-current-hil通过真实stdio FastMCP子进程和真实WebSocket访问STM32。首次remote_connect成功，握手详情包含rtt.read_channel；remote_call启动八路，逐路读取512–864字节，与本地缓存相同游标前缀一致且lost_bytes=0。采集期间再次remote_connect返回reused且session不变。MCP退出后本地仍运行，最终本地退出/服务停止/后台自行退出。临时registry仅存在子进程内，令牌通过子进程环境传入、不落配置或报告；无Flash、电压及固件变化。报告remote-mcp-current-hil.py/json和stdio辅助脚本保存在本地。

本轮不是GUI或跨主机验证。最近1e2f5e05反馈CI已成功，共享检查查询仍运行；新改动的CI待核对，安装与Skill仍待最终推进。

### 远程 CLI 非强制连接与构建空间检查

CLI此前仅提供agent.reconnect，缺少与GUI/MCP一致的非强制连接。增加remote connect子命令，复用agent.connect；reconnect保留明确强制语义，不增加连接实现或自动重试。两个语义分离测试与CLI/文档共20项通过。

remote-cli-connect-current-hil以实际python -m mklink remote子进程运行。仅该子进程使用报告目录内隔离的LOCALAPPDATA站点配置，令牌经环境传入；sites add后首次connect成功。本地SDK开启RTT0–7，再次CLI connect返回reused=true，采集session不变且八路读取612–1080字节。最后本地拥有者stop、CLI sites remove清除临时站点、远程服务停止、后台退出。未更改用户正常站点配置，无Flash/电压变化。此证据是CLI连接与共存，不是CLI持续RTT采集通过；独立remote call进程每次退出都会释放订阅，持续多通道CLI入口仍需设计和验证，不能将多条独立call假定为同一会话。

E盘约685MiB。检查上一轮依赖测试创建的remote-mcp虚拟环境：172345138字节、无reparse链接、无使用进程；拟删除该单一临时目录，但工具自动审批返回blocked by policy，未执行删除，也未更换方式绕过。含链接运行目录、报告、固件与安装包均保留。后续大额构建前仍须处理空间，当前不因此停止其他可验证工作。

### 远程 CLI 单连接多通道 RTT 持续采集

新增remote rtt命令：复用非强制agent.connect与既有RTT订阅，按各通道独立cursor读取原始页并输出JSON lines，不在CLI累计历史。--start显式携带channels和可选addr新建采集；省略时沿用无配置订阅/默认通道0启动语义。duration有限正数，默认10秒；通道重复/越界/空列表、非有限或非正时长、无start指定addr均在连接前拒绝。退出通过现有close_all关闭本客户端，Ctrl+C返回130，失败不重试，不新增后台线程或采集归属表。

新增13项参数/游标/数据损失保留/读取失败/中断清理测试，与CLI/文档/远程RTT共68项通过。文档新增两个真实命令后精确命令计数检查先报17/19差异，更新清单数量而保留逐命令真实解析，10项文档检查通过。

remote-cli-rtt-current-hil使用实际python -m mklink remote rtt与STM32八通道。拥有者2秒采集每路720–1188字节，退出后采集停止；本地SDK启动八路后CLI借用1秒，每路628–1044字节，退出后本地仍running且session不变。所有输出页按通道验证cursor=前cursor+字节数，lost_bytes=0。最终本地stop、隔离站点移除、远程服务停止、后台退出。此为有限真机测试，不是长期稳定性或实际Ctrl+C/网络中断验收；异常路径当前为自动化证据。无Flash/电压/固件变化。

E盘低空间仍未解决；上一轮临时venv删除被自动审批拒绝，本轮未重试或绕过。安装包及本地Skill尚待最终构建更新，继续其余矩阵。

### 远程 CLI 强制退出的拥有者与借用者实体清理

0758804d候选，remote-cli-rtt-kill-hil通过真实python -m mklink remote rtt请求30秒采集，但每次仅等待八个通道都输出数据后即终止本测试子进程；不是30秒soak。拥有者路径通过--start启动，强杀后约0.2865秒采集running=false、后台仅剩本地SDK。借用者路径先由本地SDK启动，强杀CLI后约0.2776秒仅剩本地SDK，采集仍running且session不变。两次读取APP前128字节均与原基线一致；最后本地stop、站点移除、服务停止，后台自行退出。

这两个耗时包含本地状态及读取验证，是本次观测值，不是网络故障下的硬释放期限。测试使用子进程句柄terminate，退出码1，不冒充Ctrl+C/130路径；实际Ctrl+C、TCP半开、远程GUI关闭仍需各自证据。没有停止其他用户进程、修改Flash/电压或升级固件。py/json/jsonl证据保存在本地，未重复正常收发和既有自动化。

最新0758804d Feedback checks成功，Shared runtime checks仍在运行；E盘717385728字节可用，此前清理拒绝仍未绕过。其余全功能矩阵及安装/Skill继续。

### 当前符号下的 SuperWatch 与八路 RTT 并行验收

基线主机88c49aba、下载器03d72f5，复用当前STM32测试镜像。测试从当前AXF解析RTT及数组地址，避免旧脚本硬编码地址失效。共享SDK选择8元素数组并启动SuperWatch，采样值与目标内存32字节解码一致；负起点、零数量、尾部越界与超出数组长度均返回422，原选择保持。八路RTT在Watch运行期间均收到数据；停止Watch后RTT仍运行且session不变。Watch重启后必须观察sequence大于停止后记录值，确认新采样，再清除选择并停止两路采集；最后后台自行退出。证据为本地reports/superwatch-current-rtt8-hil.py及json。

本次无生产代码、固件、Flash或电压修改；不代表GUI绘图/回放/导出、15区域/128B容量、最大负载或长稳已通过。首版验收脚本仅检查缓存有值，已改为检查重启后序号推进并重跑通过。

### SuperWatch 数组容量的提交前校验

发现合法数组范围仍可能超过MUX的15个128B区域：原实现先替换选择，再由后台线程发现容量超限并停止。现数组选择复用同一采样布局和既有dump/MuxWatchSession校验，在更新选择、配置代数及restart事件之前拒绝；计算包含已选标量，不另写协议容量规则。相关三组245项通过，补充远端标量占一区域的边界用例后流式组127项通过。首轮遗漏局部import及测试数组字节数模型错误已修，最终结果为通过。

STM32当前镜像真机：480个uint32（1920B，15×128）采样与内存一致，481个返回400且旧选择保留；拒绝后采样序号继续推进。0、负值、小于1us及大于60s的四种周期返回422，原周期不变且采样继续；八路RTT均有数据，Watch停止不改变RTT session，重启产生新采样，最终后台退出。报告reports/superwatch-capacity-rtt8-hil.py/json。请求周期最低1us，MUX实际配置向上取整至毫秒且至少2ms，不等于实际采样率保证。

此轮仅数组选择入口获得配置前容量保护；新增标量/重绑定等入口仍需审查，GUI可见错误和曲线回放/导出未以此替代验收。无固件、Flash及电压修改。

### SuperWatch 标量增删容量事务

新增标量原本只验证类型/解码，不校验与数组合并后的MUX容量；删除连续区域内部元素也可能分裂区域并超限。现在Runtime增删在发布items/blocks/version前接受布局校验，Dashboard与数组选择共用同一布局及协议校验。拒绝不更新元数据版本，空布局允许保留为空闲配置。既有无数组采样仍复用缓存blocks，避免增加采集循环开销。

四组相关257项通过，覆盖16个稀疏标量的第16个拒绝、1920B连续布局删除内部元素导致分裂的拒绝、删除端点及最后元素成功。首轮5项测试替身未接受新增校验参数，已更新契约后全部通过。STM32实体满容量数组新增rt_tick返回item.error且列表未改变、采样sequence推进；缩小到448个元素后新增/删除成功，恢复480元素，八路RTT及Watch重启/后台退出通过。证据reports/superwatch-scalar-capacity-hil.py/json；删除分裂边界为自动化证据，并非实体480次增删。无Flash/固件/电压变更。

符号重绑定/目录替换的完整容量事务、GUI实际提示及其余矩阵继续，不能把增删验收扩展为所有配置入口通过。

### SuperWatch 重绑定后的同步启动校验

目录重载可能把相同数组元素从32位改成64位，使原来可采集的480元素超出MUX容量。原start先标记运行再由线程检查，重载接口可能成功返回而线程随后停止。现在start在创建线程/标记运行前复用统一布局校验；失败同步返回，state为stopped并记录error。目录已成功重载时保留新目录、新类型及选择，恢复阶段报告SuperWatchTransactionError(restore)，用户可缩小选择；不回退到可能已失效的旧地址/类型。

四组258项回归通过；新增真实Manager路径测试验证32→64位重绑定超限同步失败、无MUX启动IO、新目录一致、可缩小到240元素。该类型变化测试使用构造目录，不宣称真实更换目标固件验收。修改启动路径后重跑STM32 superwatch-scalar-capacity-hil：480元素与内存一致、超限和非法周期保留采集、缩容后标量增删、八路RTT、重启及最终后台退出通过。GUI实际反馈、无采集时重载后操作及其他矩阵仍继续。
