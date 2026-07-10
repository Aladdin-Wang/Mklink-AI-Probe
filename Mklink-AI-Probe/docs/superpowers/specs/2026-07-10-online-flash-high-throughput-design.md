# MKLink 在线烧录与高吞吐实时数据链路设计

- 状态：已确认，待实施计划
- 日期：2026-07-10
- 项目：Mklink-AI-Probe
- 主要目标：新增仅支持 MKLink CMSIS-DAP 接口的在线烧录页面，并将 SystemView、VOFA、RTT、SuperWatch 的数据链路优化到探针实际能力上限

## 1. 背景

现有桌面 GUI 使用 Vue 3、FastAPI 和 Tauri v2。GUI 已包含配置、设备连接、RTT、SystemView、VOFA、SuperWatch、串口、Modbus、内存和调试功能。当前“仪表盘 → 烧录”通过 MKLink CDC 与探针端 FLM/下载命令完成，不是标准 CMSIS-DAP/pyOCD 在线烧录链路。

另一个 DAPFlash 原型项目已经验证了基于 pyOCD 的探针扫描、目标选择、HEX/BIN 解析、擦除、烧录、校验和复位流程，但其界面基于 PySide6，不适合直接嵌入现有 Vue/Tauri GUI。应复用其中与 Qt 无关的领域逻辑和错误模型，并按 Mklink-AI-Probe 的 FastAPI/Vue 架构重新组织。

现有 SystemView 链路已经具备批量 SSE、前端 `requestAnimationFrame` 合并、有限历史缓冲和 Canvas 时间线等优化；VOFA/SuperWatch 波形模块也已经使用 TypedArray 环形缓冲。但是当前实现仍存在 JSON/SSE 解析成本、逐消息数组复制、逐点日志字符串增长、绘图时全量转换与遍历、采集和渲染耦合等瓶颈。优化目标是优先保证采集频率，绘图刷新最高 30 FPS。

## 2. 已确认需求

### 2.1 在线烧录

- 新增顶层“在线烧录”页面。
- 只支持 MKLink 暴露的 CMSIS-DAP 接口，不展示其他厂商探针。
- 支持 Intel HEX 和 BIN 固件。
- HEX 使用文件内地址；BIN 默认使用目标 Flash 起始地址，并允许修改基址。
- 首版提供只读固件预览，不提供字节编辑、撤销、重做或保存修改版。
- 支持连接、擦除、烧录、校验、复位、一键烧录和停止。
- 显示固件范围、Flash 映射、涉及扇区、任务进度和结构化日志。
- 芯片目录基于完整的 CMSIS-Pack 在线索引；GitHub 和安装包不携带厂商 Pack。
- 用户选择芯片后按需下载对应 Device Family Pack（DFP）到本机缓存，后续离线复用。
- 现有“仪表盘 → 烧录”暂时只改名为“脱机烧录”。真正把固件和配置写入 MKLink、断开电脑后独立烧录的功能不在本项目范围内。

### 2.2 高吞吐数据链路

- 采集上限以探针实际能力为准，目标尽量达到或超过 10 kSamples/s。
- 优先保证采集频率和数据完整性，绘图最高 30 FPS。
- 当显示数据量超过像素分辨率时允许显示降采样，但不得把显示降采样反向施加到采集和记录链路。
- 必须显示实测采样率、吞吐量、缓冲区水位、丢包数和解码积压。
- 优先优化 SystemView 和 VOFA，再迁移高频 RTT 与 SuperWatch。

## 3. 范围与非目标

### 3.1 本项目范围

1. 在线烧录页面和路由。
2. 模块化 CMSIS-DAP/pyOCD 后端。
3. MKLink CMSIS-DAP 接口识别与过滤。
4. 目标配置、CMSIS-Pack、Flash 几何信息和固件解析。
5. 后台烧录任务、进度、日志、停止和状态恢复。
6. 目标调试资源互斥。
7. 高吞吐二进制流协议、Web Worker 解码、TypedArray 缓冲和 30 FPS 绘图。
8. 单元、集成、模拟、硬件在环和 Tauri 打包验证。

### 3.2 非目标

- 真正的 MKLink 脱机烧录配置和探针固件协议。
- 支持任意第三方 CMSIS-DAP/DAPLink 探针。
- 首版固件字节编辑器。
- 自动解除 RDP、读保护或安全启动配置。
- Option Bytes、TrustZone、安全生命周期或外部 QSPI/OSPI 的通用配置编辑器。
- 用新的在线烧录后端替换现有 MKLink CDC/FLM 后端。
- 把第三方厂商 CMSIS-Pack 二进制文件提交到 GitHub 或打入主安装包。

## 4. 总体架构

采用“模块化单体 + 独立高速数据面”。继续使用一个 Python FastAPI sidecar，不新增常驻微服务。

### 4.1 控制面

- REST：探针扫描、目标列表、固件解析、任务创建、停止、状态查询和资源状态。
- SSE：低频任务进度与日志。烧录进度不需要二进制 WebSocket。
- 后台线程：执行 pyOCD 阻塞操作，避免阻塞 FastAPI 事件循环。

### 4.2 高速数据面

- 二进制 WebSocket：传输 SystemView、VOFA、高频 RTT 和 SuperWatch 批帧。
- Web Worker：完成解帧、类型转换、序号检查、统计和显示降采样准备。
- TypedArray 环形缓冲：保存前端实时窗口数据，避免对象数组和重复复制。
- Canvas：最高 30 FPS，仅绘制可见窗口和可见通道。

### 4.3 目录边界

建议新增：

```text
mklink/
  cmsis_dap/
    __init__.py
    probes.py           # MKLink CMSIS-DAP 识别与扫描
    pack_catalog.py     # 全量 CMSIS-Pack 索引、查询和本地缓存状态
    pack_manager.py     # DFP 按需下载、版本、校验和清理
    targets.py          # pyOCD 内置目标与已安装 Pack 目标适配
    images.py           # HEX/BIN 解析、范围和扇区覆盖
    backend.py          # pyOCD 会话、擦除、烧录、校验、复位
    jobs.py             # 任务状态机、进度、日志和停止
    errors.py           # 稳定错误码及用户提示
  remote/
    api.py              # 仅挂载子路由，不承载在线烧录实现
    online_flash_api.py # 在线烧录 REST/SSE 路由
    stream_protocol.py  # 高速二进制批帧协议
gui/src/
  views/OnlineFlashView.vue
  components/online-flash/
  composables/useOnlineFlashApi.ts
  workers/streamDecoder.worker.ts
  lib/stream/
```

具体文件可在实施计划中按现有依赖方向进一步拆分，但不得把 CMSIS-DAP 逻辑直接堆入已接近 70 KB 的 `mklink/remote/api.py`。

## 5. 在线烧录页面设计

页面参考用户提供的烧录器工作台图片，采用四区结构，并保持现有 GUI 的暖白浅色视觉体系。

### 5.1 左侧：设备与目标配置

- 设备接入：MKLink CMSIS-DAP 下拉列表、序列号和刷新按钮。
- 基本设置：SWD 接口、频率、连接方式和复位方式。
- 器件选择：搜索、厂商、系列、型号。
- 烧录算法：pyOCD 内置目标或 CMSIS-Pack 来源与可用状态。

### 5.2 中央：固件工作区

- 固件标签：文件名、文件大小和关闭操作。
- 固件信息：格式、BIN 基址、地址范围和 SHA-256。
- 只读 HEX/BIN 预览：地址列、16 字节十六进制列和 ASCII 列。
- 操作栏：连接、擦除、烧录、校验、复位、一键烧录和停止。
- 进度：当前阶段、阶段百分比、总百分比、速度和耗时。

预览必须虚拟化或按页读取，不能把大固件完整渲染为 DOM 行。首版中的“只读”是固定行为；参考图中的撤销、重做和保存文件仅作为后续增强位置，不实现可用按钮。

### 5.3 右侧：Flash 映射

- 起始地址、设备大小、编程粒度和扇区数量。
- 固件实际覆盖范围。
- 扇区列表：序号、地址、大小、固件覆盖状态和选择状态。
- 全选、取消选择、擦除选中、擦除范围和擦除全片。

仅当目标配置或 pyOCD memory map 能提供可靠几何信息时启用扇区操作。几何信息不完整时，页面退化为范围摘要和全片擦除，不猜测扇区边界。

### 5.4 底部：操作日志

- 全宽日志区，包含时间、阶段、级别、错误码和消息。
- 日志行使用有界缓冲和虚拟列表。
- 提供清除、复制和导出日志。

## 6. 芯片目录与 Pack 管理

在线烧录芯片列表采用“pyOCD 内置目标 + 完整 CMSIS-Pack 在线索引 + 本地按需缓存”，不把第三方 Pack 固化进仓库，也不要求用户预装 RT-Thread Studio、Keil 或其他 IDE。

### 6.1 全量索引

- 使用 pyOCD Pack Manager/Open-CMSIS-Pack 公共索引作为上游数据源。
- 首次进入在线烧录页时，如果本机没有索引，后台下载索引；索引就绪前仍可使用 pyOCD 内置目标。
- 索引缓存在用户数据目录，后续启动直接读取缓存，并在后台按更新策略检查新版本。
- GUI 支持按芯片完整/部分型号、厂商、系列查询全量目录，不把全部型号一次性渲染到下拉框。
- 搜索结果显示目标型号、厂商、DFP 名称、版本、安装状态和验证状态。
- 索引更新失败时继续使用上一次成功缓存，只有首次且无缓存时返回明确的索引不可用状态。

索引只包含元数据，不把 100 多个 Pack 的二进制内容下载到本机。

### 6.2 选择后按需下载

用户选择未安装芯片时，GUI 展示所需 DFP、版本、来源和预计下载信息，并在用户确认后执行安装：

1. 根据芯片 part number 在索引中解析唯一或候选 DFP。
2. 多个候选时让用户明确选择，不自动猜测。
3. 下载到临时文件，成功完成并通过可用校验后再原子移动到本地 Pack 缓存。
4. 调用 pyOCD 注册/解析目标，验证 memory map 和内部 Flash Algorithm。
5. 下载成功后自动刷新芯片状态并允许连接。

下载过程必须提供进度、取消、超时和重试。取消或失败不得留下被识别为已安装的半包。支持系统代理和可配置镜像/索引源；网络不可用时提示使用已缓存目标或导入本地 `.pack`。

### 6.3 本地存储与版本

Pack 索引和 DFP 存放在操作系统用户数据目录，例如 `%LOCALAPPDATA%\MKLink\pyocd\`，不得写入程序安装目录或 Git 工作树。具体子目录由 Pack Manager 适配层统一提供，避免前后端硬编码路径。

- 记录 Pack ID、版本、源 URL、本地路径、安装时间和可用状态。
- 同一 Pack 默认只激活一个版本；升级前保留可回退信息。
- 提供“已安装 Pack”管理界面，可检查更新、移除未使用版本和打开缓存目录。
- 已下载 Pack 可在无网络环境下继续使用。
- 安装包卸载默认不删除用户 Pack 缓存，提供显式清理选项。

### 6.4 目标信息来源与验证标签

在线目标的 part number、memory map、Flash Algorithm 和 pyOCD target 主要来自内置目标或已安装 DFP。`mklink/mcu_profiles.json` 继续服务现有 MKLink 原生/脱机、RTT 和调试配置，但不再作为在线烧录完整芯片目录。

项目可维护一个轻量覆盖表，只保存 MKLink 实测结果、推荐 SWD 频率、已知连接模式和 Pack 缺陷修正，不复制 Pack 的完整芯片定义。GUI 区分：

- `pyOCD 内置`
- `Pack 可用`
- `Pack 未安装`
- `MKLink 已验证`
- `已知限制`

“Pack 可用”表示 pyOCD 能解析目标，不等同于已经通过 MKLink 硬件烧录验证。未知 MCU 禁止直接使用 `cortex_m` 或 `custom` 执行 Flash，因为通用 CoreSight 连接不包含可靠 Flash Algorithm。

### 6.5 本地 Pack 导入兜底

保留导入单个 `.pack` 的离线入口，用于网络受限、私有芯片或公共索引尚未收录的情况。导入包走与在线下载相同的解析、校验、版本和状态流程，不直接修改 `mcu_profiles.json`。

## 7. MKLink 探针识别

探针过滤采用多信号匹配，配置优先级如下：

1. 已知 MKLink VID/PID 白名单。
2. USB 产品名、厂商名或 CMSIS-DAP 描述中包含 MKLink/MicroLink/MicroKeen 标识。
3. 可选序列号前缀白名单。

扫描结果必须保留 pyOCD unique ID。无法确认属于 MKLink 的探针不显示，也不能在没有明确选择的情况下自动使用 pyOCD 返回的第一个探针。

白名单放入可测试的配置文件或常量模块，不散落在 Vue 和 API 路由中。

## 8. 烧录任务模型

任务阶段：

```text
queued → connecting → erasing → programming → verifying → resetting
       → disconnecting → succeeded
任意活动阶段 → stopping → stopped
任意阶段 → failed
```

一键烧录默认执行：连接、按策略擦除、烧录、校验、复位、断开。单步操作复用同一任务引擎。

任务记录至少包含：

- 任务 ID、创建时间、更新时间和状态。
- 探针 unique ID、目标 ID、SWD 参数。
- 固件路径、格式、地址范围、大小和 SHA-256。
- 当前阶段、阶段进度、总进度、速度和耗时。
- 结构化日志和最终错误。

页面刷新后通过任务状态接口恢复正在运行或最近结束的任务。首版只允许一个活动在线烧录任务。

pyOCD 的单次擦除、烧录或校验调用通常不能安全地被强制中断。停止请求设置取消标志，并在当前不可中断阶段完成后阻止后续阶段；UI 必须显示“正在等待当前阶段结束”。

## 9. 固件解析与校验

### 9.1 Intel HEX

- 解析所有数据段及其绝对地址。
- 合并相邻段用于范围展示，但保留原始段边界用于校验。
- 检查每个段是否位于目标可编程 Flash region。
- 预览地址为文件中的真实地址。

### 9.2 BIN

- 默认基址为目标 profile 的 `flash_base`。
- 用户可以修改基址；每次修改后重新计算结束地址和涉及扇区。
- 缺少或无法解析基址时禁止烧录。
- 检查 `base + size` 是否越过允许的 Flash region。

### 9.3 通用规则

- 只允许 `.hex`、`.bin`，通过内容解析再次验证，不能只信任扩展名。
- 计算 SHA-256 并在任务开始时再次检查，防止预览后文件被替换。
- 预览和烧录必须引用同一份已验证的固件元数据。

## 10. 资源互斥

当前 `ResourceManager` 只有 `mklink_bridge`、`serial_port` 和 `modbus_port`。新增 `target_debug` 资源组，表示对目标 MCU 的 SWD/调试访问。

以下操作必须持有 `target_debug`：

- CMSIS-DAP 在线连接与烧录任务。
- MKLink 原生烧录、擦除、复位、内存和调试操作。
- RTT、SystemView、VOFA 和 SuperWatch 会话。

在线烧录所有者使用 `user:online-flash:<job-id>`。用户启动在线烧录时，如果 AI 持有资源，可以沿用现有用户优先策略请求抢占；如果其他用户仪表盘持有资源，必须展示冲突并由用户确认停止相关会话。任务结束、失败、停止和应用关闭时均释放租约。

同一物理 MKLink 的 CDC 与 CMSIS-DAP 虽是不同 USB 接口，但最终共享目标 SWD 访问，因此不能以接口不同为理由并行访问目标。

## 11. 高吞吐数据链路

### 11.1 采集与背压

- 探针读取线程尽可能批量读取，减少命令往返和 Python 调度。
- 读取结果进入有界批队列；队列满时采用明确策略并累计丢包，而不是静默无限增长。
- 每个批次携带流 ID、批序号、首样本时间、样本数、通道定义版本和载荷长度。
- 后端分别统计探针读取速率、解析速率、发送速率、队列水位和丢弃量。

### 11.2 二进制协议

控制与错误仍使用 JSON，数据批使用版本化二进制帧。首版协议必须包含魔数、版本、流类型、序号、时间基准、样本/事件数和载荷长度。浮点波形优先使用 little-endian Float32/Float64 TypedArray；SystemView 可使用紧凑事件记录或原始批加 Worker 解码。

协议实现必须有编码/解码黄金样例测试，并为未来字段扩展预留版本或 flags，不依赖未记录的对象字段顺序。

### 11.3 Web Worker 与缓冲

- WebSocket 消息以 `ArrayBuffer` 转交 Worker，尽量使用 transferable，避免主线程复制。
- Worker 负责解帧、序号检查、通道映射和 TypedArray 环形缓冲写入。
- 主线程通过快照索引或双缓冲获取当前可见窗口，不把每个采样点包装成 Vue 响应式对象。
- 记录/导出与显示缓冲分离。显示缓冲达到上限时覆盖旧数据，不影响后端原始记录。

### 11.4 30 FPS 绘图

- 渲染调度最多 30 FPS；页面隐藏时进一步降低或暂停绘图，但继续采集和记录。
- 只绘制可见时间范围和可见通道。
- 当一个像素列对应多个样本时使用 Min/Max 包络降采样，保留尖峰。
- 禁止每帧为所有通道创建完整 `{t, y}` 对象数组。
- 原始日志面板使用独立有界缓冲和虚拟列表；禁止逐点执行 `textContent += ...`。
- 鼠标移动、缩放和 resize 统一通过单一 render scheduler 合并，避免重复重绘。

### 11.5 性能指标

性能不是固定宣称值，而是可测量目标：

- 采集：由探针能力决定，争取达到或超过 10 kSamples/s。
- 绘图：活动页面最高 30 FPS，长期运行不持续下降。
- 主线程：连续采集时避免长时间任务；测试环境中单次渲染预算目标小于 33 ms。
- 内存：固定窗口运行 30 分钟后缓冲内存趋于稳定。
- 可观测性：显示实测速率、吞吐量、队列水位、丢包和 Worker 延迟。

## 12. 错误处理

在线烧录模块使用稳定错误码，至少包括：

- `MKLINK_DAP_NOT_FOUND`
- `PROBE_BUSY`
- `TARGET_NOT_SUPPORTED`
- `PACK_INDEX_UNAVAILABLE`
- `PACK_NOT_FOUND`
- `PACK_DOWNLOAD_FAIL`
- `PACK_INTEGRITY_ERROR`
- `CONNECT_FAIL`
- `FILE_NOT_FOUND`
- `FILE_FORMAT_ERROR`
- `BIN_ADDRESS_MISSING`
- `IMAGE_OUT_OF_RANGE`
- `TARGET_LOCKED`
- `ERASE_FAIL`
- `PROGRAM_FAIL`
- `VERIFY_FAIL`
- `RESET_FAIL`
- `USER_ABORT`
- `UNKNOWN_ERROR`

API 返回机器可读错误码、用户标题、说明和可选技术细节。UI 对用户显示简洁说明，把完整 traceback 仅写入后端诊断日志。任何失败路径都必须尝试关闭 pyOCD session 并释放资源租约。

高速流错误必须区分探针端丢失、后端队列丢弃、网络/IPC 断开、Worker 解码错误和渲染滞后，不能统一显示为“连接失败”。

## 13. API 草案

建议接口：

```text
GET    /api/online-flash/probes
GET    /api/online-flash/targets?q={part}&vendor={vendor}&installed={bool}
GET    /api/online-flash/packs/status
POST   /api/online-flash/packs/index/update
POST   /api/online-flash/packs/install
POST   /api/online-flash/packs/import
DELETE /api/online-flash/packs/{pack_id}/{version}
POST   /api/online-flash/images/inspect
POST   /api/online-flash/jobs
GET    /api/online-flash/jobs/active
GET    /api/online-flash/jobs/{job_id}
POST   /api/online-flash/jobs/{job_id}/stop
GET    /api/online-flash/jobs/{job_id}/events
```

大文件预览通过分页或范围接口返回，不在 `inspect` 响应中嵌入整个文件：

```text
GET /api/online-flash/images/{image_id}/preview?offset=0&length=4096
```

高速流使用独立 WebSocket 路由，并保留当前 SSE 路由直到相应页面迁移完成：

```text
WS /ws/streams/{stream_type}
```

## 14. 测试策略

### 14.1 Python 单元测试

- MKLink 探针过滤：VID/PID、描述、序列号和拒绝第三方探针。
- HEX/BIN 解析、地址范围、扇区覆盖、越界和哈希变更。
- 全量索引查询、旧缓存回退、芯片到 DFP 的唯一/多候选映射。
- Pack 下载、取消、失败清理、版本切换、本地导入和目标注册。
- 任务状态机、停止语义、失败清理和租约释放。
- 错误映射。
- 二进制协议编码/解码和非法帧。

### 14.2 FastAPI 集成测试

- 使用假的 pyOCD backend 验证扫描、任务、进度、日志、停止和恢复。
- 验证资源冲突和抢占流程。
- 验证文件预览分页和路径安全。
- 验证索引首次下载、缓存复用、离线降级、Pack 安装进度和失败恢复。
- 验证 WebSocket 序号、批量传输和断线重连。

### 14.3 Vue/Vitest 测试

- 页面四区布局与路由。
- HEX/BIN 表单规则和 BIN 基址重算。
- 任务按钮状态、进度、停止等待和错误展示。
- 固件虚拟预览与扇区选择。
- Worker 协议解码、环形缓冲和 Min/Max 降采样。

### 14.4 性能与稳定性测试

- 合成 10 kSamples/s 及更高数据流，测量采集、Worker、绘图、内存和丢包。
- 30 分钟持续运行测试。
- 多通道和尖峰信号验证，确认 Min/Max 降采样不吞掉尖峰。
- SystemView 高事件率批流和日志导入回放。

### 14.5 硬件在环

- MKLink CMSIS-DAP 扫描和过滤。
- 每个声明在线支持的 MCU 至少验证连接和复位。
- 代表性目标验证 HEX 与 BIN 的擦除、烧录、校验和复位。
- 拔出探针、目标掉电、Pack 缺失、烧录中停止和固件越界。
- 实测探针最大稳定采样率和丢包拐点。

### 14.6 打包验证

- pyOCD、Pack Manager、USB backend 和轻量覆盖配置随 PyInstaller sidecar 正确收集。
- 第三方 DFP 不进入 GitHub、sidecar 或 Tauri 安装包；release 环境能把 DFP 下载到用户缓存并加载。
- Tauri 开发模式、release EXE、NSIS/MSI 安装包均能扫描 MKLink 和加载前端 Worker。

## 15. 分阶段实施与验收

每个阶段可以根据实测结果调整后续任务，但阶段内必须先定义验收命令和输出，再开始实现。

### 阶段 1：PackCatalog、基础契约与配置

- 新增设计/实施文档、在线烧录错误码和接口模型。
- 实现 pyOCD 内置目标目录、全量 Pack 索引更新、查询和本地缓存。
- 实现芯片到 DFP 映射、按需下载、本地导入、失败清理和版本状态。
- 建立轻量 MKLink 验证/覆盖配置，不复制 Pack 设备定义。
- 建立 fake backend 和基础测试夹具。

验收：索引查询、缓存离线回退、Pack 安装/取消/损坏场景和错误模型单元测试通过；仓库与安装产物不包含第三方 `.pack`；现有测试不回归。

### 阶段 2：探针、会话和资源互斥

- 实现只识别 MKLink 的 CMSIS-DAP 扫描。
- 实现 pyOCD session 生命周期。
- 增加 `target_debug` 资源并接入在线烧录与现有目标访问入口。

验收：模拟测试覆盖第三方探针拒绝、资源冲突、连接失败清理；硬件验证至少完成扫描、连接、断开和复位。

### 阶段 3：固件解析与页面骨架

- 实现 HEX/BIN inspection、哈希、范围、扇区覆盖和分页预览。
- 新增 `/online-flash` 路由和四区页面。
- 接入全量芯片搜索、Pack 下载确认、进度、已安装状态和本地导入。
- 把现有仪表盘“烧录”改名为“脱机烧录”。

验收：HEX/BIN 正常、越界、空洞段、BIN 基址等测试通过；前端构建和组件测试通过。

### 阶段 4：完整在线烧录任务

- 实现擦除、烧录、校验、复位、一键流程、停止、日志和状态恢复。
- 接入进度、速度、错误提示和危险操作确认。

验收：fake backend 全流程通过；MKLink 硬件完成至少一个 HEX 和一个 BIN 的烧录校验闭环。

### 阶段 5：SystemView 高速数据面

- 定义并实现二进制批帧协议。
- 增加 WebSocket、Worker、TypedArray 缓冲、序号和丢包统计。
- 时间线绘制限制为 30 FPS，并只处理可见窗口。

验收：协议黄金测试、合成高事件率测试和 30 分钟稳定性测试通过；硬件记录实际吞吐和丢包拐点。

### 阶段 6：VOFA、RTT、SuperWatch 迁移

- VOFA 首先迁移到共享高速流管线。
- 高频 RTT 和 SuperWatch 按相同协议迁移。
- 替换逐点日志增长和全量对象数组绘制。

验收：合成流达到或超过 10 kSamples/s 时采集持续稳定，绘图不超过 30 FPS，内存有界；硬件实测以探针极限为准并记录结果。

### 阶段 7：打包、回归和发布准备

- 完成完整测试矩阵、Tauri 构建、安装包和升级路径验证。
- 验证全新用户环境可完成“搜索芯片 → 下载 Pack → 在线烧录”，且已缓存环境可离线使用。
- 更新 README、技能 references 和用户操作说明。

验收：Python 测试、Vue 测试、前端构建、Tauri release 构建和关键硬件在环检查全部通过。

## 16. Git 与阶段保存策略

- 每个阶段在开始前确认当前工作树和验收标准。
- 每个阶段形成一个或少量聚焦提交，不混入无关改动。
- 每阶段测试通过后推送当前分支到 GitHub，保存可回退检查点。
- 硬件验证结果、性能数据和已知限制随对应阶段一并记录。
- 若阶段任务需要调整，先更新实施计划或阶段说明，再修改代码，避免文档与实现长期偏离。

## 17. 完成标准

本项目完成需同时满足：

1. GUI 中存在独立在线烧录页，且现有烧录已标记为脱机烧录。
2. 页面只展示 MKLink CMSIS-DAP，并能对已配置目标完成 HEX/BIN 烧录闭环。
3. 芯片目录来自完整在线索引，用户选定芯片后仅下载对应 Pack；GitHub 和安装包不含第三方 Pack。
4. 固件越界、索引不可用、Pack 下载/校验失败、探针忙、任务失败和停止均有明确错误与可靠清理。
5. 在线烧录与所有目标调试/数据会话通过 `target_debug` 互斥。
6. SystemView、VOFA、RTT 和 SuperWatch 使用共享的高吞吐基础设施或完成约定的迁移范围。
7. 合成数据测试达到或超过 10 kSamples/s，绘图最高 30 FPS，内存有界且丢包可观测。
8. MKLink 硬件实测记录实际最大稳定吞吐，不能用合成测试替代硬件结论。
9. 自动测试、Tauri 打包和阶段文档完整，GitHub 上有可回退的阶段提交。
