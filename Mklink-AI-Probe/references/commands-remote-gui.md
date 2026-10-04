# 本地 Web 服务与 GUI

> 触发词：serve、gui、FastAPI、uvicorn、Tauri、桌面应用、本地 Web GUI/API
> 返回索引：[SKILL.md](../SKILL.md)

VPN/局域网站点、独立 Site Agent、工程师侧 remote CLI/SDK/MCP 请改读
[直连远程调试](commands-remote.md)；本页只描述本地 FastAPI、GUI 和 Tauri。

## 依赖安装

Python Web GUI 需要运行依赖和已打包的 Web 资源；桌面安装包自带后端。见[安装说明](install.md)，无需编译 MKLink。


## Web GUI（浏览器模式）

### 采集与显示

RTT、SystemView、VOFA 和 SuperWatch 的图表暂停或页面隐藏只减少绘制，不停止采集。
要释放探针或串口需明确停止对应会话；传输丢帧与设备端丢样分开报告，不把图表
抽样显示当作原始数据丢失。

### serve — FastAPI 服务

```powershell
python -m mklink serve --host 127.0.0.1 --port 8765
# 启动 FastAPI 服务器，访问 http://127.0.0.1:8765/docs 查看 API 文档
```

旧原始 socket 服务及 `mklink.serve()` 已移除；不再支持 `--backend` 选项。
GUI/AI 共用下载器使用 `mklink gui` / `mklink runtime`；局域网设备操作使用
“远程服务”页面或独立 Agent，参见[直连远程调试](commands-remote.md)。

选项：
- `--project-root <dir>` — 指定项目根目录

### gui — 一键启动 Web GUI

```powershell
# 一键启动（使用已打包前端、启动后端、打开浏览器）
python -m mklink gui

# 指定端口和设备
python -m mklink gui --port 8765 --device-port COM6

# 不自动打开浏览器
python -m mklink gui --no-browser
```

GUI 启动后在浏览器中提供三个主页面：
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

入口会复用现有 Web 服务；只停止自己启动的进程，不改变 `serve`、MCP 或 Tauri
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
| 列出 MKLink 探针 | `GET /probes` |
| 搜索目标 | `GET /targets?q=...&vendor=...&installed=...` |
| Pack 状态/更新索引 | `GET /packs/status`、`POST /packs/index/update` |
| 安装/导入/取消/删除 Pack | `POST /packs/install`、`POST /packs/import`、`POST /packs/cancel`、`DELETE /packs/{pack_id}/{version}` |
| 检查与分页预览固件 | `POST /images/inspect`、`GET /images/{image_id}/preview` |
| 启动/查询/停止任务 | `POST /jobs`、`GET /jobs/active`、`GET /jobs/{job_id}`、`POST /jobs/{job_id}/stop` |
| 重放式任务事件 | `GET /jobs/{job_id}/events?after={sequence}` (SSE) |

Pack 索引、已安装 Pack 和临时上传均位于用户数据根目录，Windows 默认为 `%LOCALAPPDATA%\MKLink\pyocd`；可在启动服务前设置 `MKLINK_PYOCD_HOME` 覆盖。可复用已下载的 Pack 缓存。更新索引和下载 Pack 继承服务进程的 `HTTP_PROXY`/`HTTPS_PROXY`/`NO_PROXY` 环境；断网时可用最后一份有效索引和已安装 Pack。

在线烧录会申请 `TARGET_DEBUG` 资源，与 RTT、SystemView、VOFA、SuperWatch 等会话冲突时返回 HTTP 409 及当前 owner/resource；先停止或由用户确认交接冲突会话。`POST /jobs/{job_id}/stop` 只设置协作式取消：运行中的底层操作返回后，任务才进入 `stopped`，执行 disconnect 并释放租约。页面显示“停止中”时不要立即开启新任务或拔除探针。

## Dashboard 生命周期

主 GUI 的 RTT / Serial / Modbus / SuperWatch 通过所选共享后台的 manager 运行，
不为每个面板另开 CDC 或固定 808x 端口。串口助手使用 `mklink serial dashboard`
打开主 GUI 对应页面，命令退出/关页面保留连接；在面板中显式停止。

串口启停/状态为 `/api/dash/serial/start`、`stop`、`status`；记录与命令序列共用该
后台，GUI/CLI/MCP 查看同源状态。广播给出逐端口结果，文件发送受大小限制并复用
命令序列。API 必须使用当前共享后台认证，不应向旧独立 Dashboard 路径发送请求。

## 资源管理 API

FastAPI 后端维护 `mklink_bridge`、`serial_port`、`modbus_port` 三类资源租约。串口/Modbus dashboard 启动后会登记租约；停止或强制释放时会同时关闭对应后台 manager，避免虚拟串口被占用后无法释放。

注意：REST API 是 GUI/dashboard 的 HTTP 包装层。Agent 或命令行释放本地串口资源时优先使用 CLI，不需要启动 FastAPI：

```powershell
python -m mklink resources status --port COM3
python -m mklink resources release-serial --port COM3
```

常用端点：

- `GET /api/resources/status` — 查询当前资源占用。
- `POST /api/resources/release-serial` — 释放当前 `serial_port` 持有者；用于串口 dashboard 占用虚拟串口时的一键释放。
- `POST /api/resources/release` — 按 owner 或 resource 释放，例如 `{"owner":"user:dashboard:serial"}` 或 `{"resource":"serial_port"}`。
- `POST /api/resources/release-all` — 停止所有已登记 dashboard 并释放全部租约。

示例：

```powershell
curl http://127.0.0.1:8765/api/resources/status
curl -X POST http://127.0.0.1:8765/api/resources/release-serial -H "Content-Type: application/json" -d "{}"
curl -X POST http://127.0.0.1:8765/api/resources/release -H "Content-Type: application/json" -d "{\"resource\":\"serial_port\"}"
```
