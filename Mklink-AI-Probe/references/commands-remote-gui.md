# 本地 Web 服务与 GUI

> 触发词：serve、gui、FastAPI、uvicorn、Tauri、桌面应用、本地 Web GUI/API
> 返回索引：[SKILL.md](../SKILL.md)

VPN/局域网站点、独立 Site Agent、工程师侧 remote CLI/SDK/MCP 请改读
[直连远程调试](commands-remote.md)；本页描述本地 FastAPI、GUI、Tauri 和远程仪表盘。

## 依赖安装

Python Web GUI 需要运行依赖和已打包的 Web 资源；桌面安装包自带后端。见[安装说明](install.md)，无需编译 MKLink。


## Web GUI（浏览器模式）

### 采集与显示

RTT、SystemView、VOFA 和 SuperWatch 的图表暂停或页面隐藏只减少绘制，不停止采集。
要释放探针或串口需明确停止对应会话；传输丢帧与设备端丢样分开报告，不把图表
抽样显示当作原始数据丢失。

### 共享后台

旧 `serve`、`mklink.serve()` 和 `mklink.remote.serve_fastapi()` 已移除。
本机 GUI/AI 统一使用 `mklink gui` / `mklink runtime`，无需启动第二个服务器。
只启动共享后台、不打开浏览器时使用 `python -m mklink gui --no-browser`。
局域网设备操作使用“远程服务”页面或独立 Agent，参见[直连远程调试](commands-remote.md)。
桌面内部 `desktop-proxy` 仅转发共享后台，不直接连接下载器。

配置页依次为本地设备、文件来源、固件升级和后台管理；本机别名在后台管理中修改，仅影响本机，不写下载器固件。
固件升级支持自动与手动两条路径：能进入并确认对应 Bootloader U 盘时自动复制 UF2，
重新读到新版本才显示完成；老版本缺少进入指令或未检测到对应盘时显示下载按钮和
按键步骤，不弹升级错误。无法识别型号时由用户选择 MicroLink V3/V4 或 HPMLink V4，
不自动猜测。文件复制结果未确认时先检查设备，不自动重试。
远程功能统一在顶部“远程服务”，包含本机提供服务和连接远端下载器。

1. 下载器所在电脑选择目标下载器，在“远程服务”启动局域网监听，取得服务地址和访问令牌。
2. 操作电脑打开“远程服务 > 连接远端下载器”，输入地址和令牌，点击“连接并打开远程仪表盘”。两端均需支持本功能的新版服务。
3. 默认浏览器打开同一套 GUI 仪表盘，顶部显示固定的远端地址与探针身份。原本地窗口保持本地目标；远程窗口的“返回本地 / 更换设备”会结束本窗口远程会话并返回连接页。
4. 远程模式复用 RTT View、Memory、SuperWatch、HardFault、符号表与 RTOS Trace 原有面板及数据流。符号文件需先在目标电脑加载。烧录、串口/Modbus、VOFA、文件上传/目标机录制文件及主机管理本阶段未开放；对应入口禁用或隐藏。
5. 每次新连接创建独立会话；关闭窗口释放本窗口远程连接；与本地GUI一样，后台采集继续运行，需要停止时先点击采集停止。断线后保留数据显示并禁用操作，需显式重新连接，不自动切到本地或重放命令。

令牌不持久化到浏览器。每个本机后台最多8个远程窗口；无请求90秒后会话可过期。使用原GUI有界流缓冲和丢失计数，不保证无损。窗口刷新也需重新连接。旧配置页仅建立 WebSocket 的连接框已移除。

### gui — 一键启动 Web GUI

```powershell
# 一键启动（使用已打包前端、启动后端、打开浏览器）
python -m mklink gui

# 指定端口和设备
python -m mklink gui --port 8765 --device-port COM6

# 不自动打开浏览器
python -m mklink gui --no-browser
```

GUI 启动后在浏览器中提供以下主页面：
- **远程服务页** (`/remote-service`) — LAN/VPN 监听、认证令牌、启动/停止及连接说明
- **配置页** (`/config`) — COM 口选择、MCU 配置、项目初始化
- **仪表盘页** (`/dashboard`) — RTT View、烧录、调试控制、串口、Modbus、SuperWatch
- **在线烧录页** (`/online-flash`) — MKLink-only 探针、目标/Pack、HEX/BIN 检查与预览、烧录任务和 SSE 日志

浏览器版“配置 > 文件来源”可直接选择本机 AXF/ELF/OUT 文件。AXF/ELF/OUT
已经包含 SuperWatch 符号、类型信息，也可用于 RTT/SystemView 地址搜索，用户不需要
再手动加载 MAP 文件。浏览器
不会暴露本机绝对路径，因此前端使用 multipart 将文件上传到本机 Mklink 服务的
受控 `.mklink/uploads/file-sources` 目录，再把服务端路径用于连接和符号解析。
单文件上限为 256 MiB；Tauri 桌面版继续使用原生文件对话框，不经过上传。

AXF 重新编译后自动重载：桌面版选择原文件即可；Web 配置页可填写后端电脑上的原文件路径。
支持文件访问授权的浏览器还可在选择 AXF/ELF/OUT 时保留文件句柄，在当前页面会话内
按内容变化上传新版本并重载符号。刷新或关闭页面后须重新选择文件以恢复该授权。
配置页显示“自动跟踪”或“文件快照”；普通上传快照无法跟随原文件变化。
AXF 重载会停止依赖采集，不会自动烧录或恢复采集。

在线烧录通过“选择 BIN / HEX”加载固件；桌面原生路径和支持文件访问授权的浏览器
会自动跟踪内容变化。工具栏不再提供单独的文件路径入口。普通浏览器上传或拖入的
File 是快照，编译后需要重新选择；自动加载新固件不会自动启动烧录。

### web-entry — U 盘单 HTML 快速启动

`web-entry` 为已经安装完整 Mklink skill/runtime 的电脑注册
`mklink-ai-probe://` 用户级协议。U 盘只需保存一个跨 Windows、macOS、Linux
通用的 HTML 文件：

```bash
python -m mklink web-entry install --html "/path/to/usb/启动 Mklink Web.html"
```

入口会复用现有 Web 服务；只停止自己启动的进程，不改变共享后台、MCP 或 Tauri
sidecar 的所有权。平台安装位置、权限和故障排查见
[跨平台 U 盘 Web 启动入口](web-entry.md)。


## Tauri 桌面应用（原生窗口）

Tauri v2 将 Vue 3 前端包装为原生桌面应用，内嵌 Python FastAPI sidecar。

Windows 标准 NSIS 安装包采用 per-machine 安装，在安装结束后以非阻断方式检查
当前在线的 MKLink V2/V3/V4，并为完整校验通过的 CDC 接口设置可区分的设备管理器
名称。安装时没有连接下载器时，可在“配置 > 本地设备”使用“修改端口名称”；
“恢复名称”会请求 UAC 并恢复 Windows 驱动默认显示。浏览器版不提供注册表操作。

## 在线烧录 API

`/online-flash` 页调用以下 `/api/online-flash` 端点：

| 用途 | 端点 |
|------|------|
| 列出当前后台绑定的 MKLink 探针；未选择或设备缺失时为空 | `GET /probes` |
| 搜索目标 | `GET /targets?q=...&vendor=...&installed=...` |
| Pack 状态/更新索引 | `GET /packs/status`、`POST /packs/index/update` |
| 安装/导入/取消/删除 Pack | `POST /packs/install`、`POST /packs/import`、`POST /packs/cancel`、`DELETE /packs/{pack_id}/{version}` |
| 检查与分页预览固件 | `POST /images/inspect`、`GET /images/{image_id}/preview` |
| 启动/查询/停止任务 | `POST /jobs`、`GET /jobs/active`、`GET /jobs/{job_id}`、`POST /jobs/{job_id}/stop` |
| 重放式任务事件 | `GET /jobs/{job_id}/events?after={sequence}` (SSE) |

Pack 索引、已安装 Pack 和临时上传均位于用户数据根目录，Windows 默认为 `%LOCALAPPDATA%\MKLink\pyocd`；可在启动服务前设置 `MKLINK_PYOCD_HOME` 覆盖。可复用已下载的 Pack 缓存。更新索引和下载 Pack 继承服务进程的 `HTTP_PROXY`/`HTTPS_PROXY`/`NO_PROXY` 环境；断网时可用最后一份有效索引和已安装 Pack。

在线烧录会申请 `TARGET_DEBUG` 资源。0.3.1 后台自动暂停 RTT、SystemView、VOFA、SuperWatch，任务结束后按原参数恢复；暂停或恢复失败会报告，其他在途硬件任务仍返回冲突。`POST /jobs/{job_id}/stop` 只设置协作式取消：运行中的底层操作返回后才完成停止、释放资源和恢复采集。页面显示“停止中”时不要立即开启新任务或拔除探针。

## Dashboard 生命周期

主 GUI 的 RTT / Serial / Modbus / SuperWatch 通过所选共享后台的 manager 运行，
不为每个面板另开 CDC 或固定 808x 端口。串口助手使用 `mklink serial dashboard`
打开主 GUI 对应页面，命令退出/关页面保留连接；在面板中显式停止。

串口启停/状态为 `/api/dash/serial/start`、`stop`、`status`；记录与命令序列共用该
后台，GUI/CLI/MCP 查看同源状态。广播给出逐端口结果，文件发送受大小限制并复用
命令序列。API 必须使用当前共享后台认证，不应向旧独立 Dashboard 路径发送请求。

## 资源管理 API

FastAPI 后端维护 `mklink_bridge`、`serial_port`、`modbus_port` 三类资源租约。串口/Modbus dashboard 启动后会登记租约；停止或强制释放时会同时关闭对应后台 manager，避免虚拟串口被占用后无法释放。

REST API 是当前已认证后台的 HTTP 包装层，端口不固定。AI 优先用
`runtime_status`/`runtime_control`，CLI 用 `runtime control`，见
[控制权与恢复](runtime-recovery.md)。查询本机端口锁可用：

```powershell
python -m mklink resources status --port COM3
```

常用端点：

- `GET /api/resources/status` — 查询当前资源占用。
- `POST /api/resources/release-serial` — 释放当前 `serial_port` 持有者；用于串口 dashboard 占用虚拟串口时的一键释放。
- `POST /api/resources/release` — 按 owner 或 resource 释放，例如 `{"owner":"user:dashboard:serial"}` 或 `{"resource":"serial_port"}`。
- `POST /api/resources/release-all` — 停止所有已登记 dashboard 并释放全部租约。

这些端点遵守共享准入，仍有会话或任务时不会强制释放。独立 CLI
`resources release-serial` 仅清理失效锁；其 `--force` 会结束活跃持有进程，
不能作为正常结束 AI 会话或停止某路采集的方法。

远程 GUI 两端需支持 `gui.bridge` 版本1，并核对当前共享后台协议；HTTP/SSE和二进制WebSocket复用原数据格式。转发固定于握手时的后台实例，服务重启需显式重连，不提供通用网络代理或本机管理隧道。
