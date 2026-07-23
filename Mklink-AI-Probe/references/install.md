# 安装与可选依赖

> 触发词：pip、ensurepip、readelf、arm-none-eabi、winget
> 返回索引：[SKILL.md](../SKILL.md)

## 安装步骤

在使用本 Skill 之前，必须先安装 `mklink` Python 包：

```bash
# 1. 如果 Python 没有 pip，先引导安装
python -m ensurepip --upgrade

# 2. 从本 Skill 目录安装 mklink 包（ editable 模式）
python -m pip install -e .

# 3. 如果使用 Modbus 功能，确保安装 pymodbus（已在依赖中自动安装）
pip install pymodbus>=3.0
```

安装完成后，`python -m mklink` 命令即可正常使用。


## 作为 Claude Code 插件使用（MCP 能力层）

本 Skill 同时是一个 Claude Code **插件**：根目录 `.claude-plugin/plugin.json` + `.mcp.json` 暴露 **42 个 MCP tool**（`mcp__mklink__*`，覆盖连接/烧录/内存/变量/调试/符号/RTT/HardFault/Modbus/串口），由 `python -m mklink mcp` 以 stdio 方式启动。MCP server **依赖 `fastmcp`**，需安装 `mcp` extras：

```powershell
pip install -e ".[mcp]"
```

验证 MCP server 可启动（应向 stderr 打印 FastMCP 横幅并等待 stdio JSON-RPC 输入，Ctrl+C 退出）：

```powershell
python -m mklink mcp
```

**普通用户安装本插件**（无需上架 marketplace，走 skills-directory 机制）：

```powershell
# 1. 把本目录放到 Claude Code 的 skills 目录下
git clone <repo-url> "$env:USERPROFILE\.claude\skills\mklink-flash"
#   （或手动复制整个目录到 ~/.claude/skills/mklink-flash/）

# 2. 安装 Python 包 + MCP 依赖（使 .mcp.json 中的 python -m mklink mcp 可用）
cd "$env:USERPROFILE\.claude\skills\mklink-flash"
pip install -e ".[mcp]"

# 3. 重启 Claude Code —— 自动加载为 mklink-flash@skills-dir，MCP 工具即可用
```

> 仅使用 CLI、不用 MCP 的用户：跳过 `.[mcp]`，`pip install -e .` 即可。
> `pyelftools` 已作为正式依赖安装；标准桌面安装包也会把它打入 sidecar。

## Skill 与桌面版自动更新

从 v0.1.3 开始，AI 每个会话第一次使用 MKLink 能力时会执行一次带 24 小时
缓存的版本检查。检查不会占用探针，离线失败不会阻塞调试。发现新版本后，AI
会先说明版本和发布说明，只有得到用户明确同意才自动更新：

```powershell
python scripts/skill_update.py check --json
python scripts/skill_update.py install --yes --json
```

更新器从公开 `updates/latest.json` 读取桌面安装包和 Skill ZIP，对下载结果校验
大小与 SHA-256 后再安装。桌面程序和本地服务必须先关闭；Skill 更新后需要
重启 AI 客户端或开启新会话。Git checkout 会被识别并拒绝覆盖，应继续通过 Git
维护。早于 v0.1.3 的复制式 Skill 没有更新检查入口，需要先手动升级一次。


## ELF/AXF 解析后端

MKLink 默认使用内置 `pyelftools`，以下功能不需要用户安装 Keil、GNU Arm 或系统 binutils：

- `symbols`、`typeinfo`、`watch`、`superwatch` 和 VOFA 变量名解析
- `memmap`、函数名断点和符号目录
- HardFault PC/LR 源码行定位
- CLI、MCP、REST API 和桌面上位机的 AXF 重解析

后端选择优先级：命令/API 显式参数、`MKLINK_ELF_BACKEND`、项目
`.mklink/toolchain.json` 的 `elf_backend`，最后默认 `builtin`。

```powershell
python -m mklink symbols --source path/to/firmware.axf
python -m mklink hardfault --source path/to/firmware.axf --sp 0x20001FF0
```

### 可选 GNU 兼容后端

只有用户明确指定 `external` 时，MKLink 才会调用本机 `readelf` / `addr2line`。
仅设置 `MKLINK_READELF`、`MKLINK_ADDR2LINE` 或工具路径不会自动启用 external，
内置解析失败时也不会静默回退。

```powershell
$env:MKLINK_ELF_BACKEND = "external"
$env:MKLINK_READELF = "C:\tools\arm-gnu\bin\arm-none-eabi-readelf.exe"
$env:MKLINK_ADDR2LINE = "C:\tools\arm-gnu\bin\arm-none-eabi-addr2line.exe"

python -m mklink symbols --source path/to/firmware.axf --elf-backend external
```

项目级配置：

```json
{
  "elf_backend": "external",
  "readelf": "C:/tools/arm-gnu/bin/arm-none-eabi-readelf.exe",
  "addr2line": "C:/tools/arm-gnu/bin/arm-none-eabi-addr2line.exe"
}
```

需要安装 GNU Arm 工具链时可执行：

```powershell
winget install --id Arm.GnuArmEmbeddedToolchain -e --accept-package-agreements --accept-source-agreements
```

MCP `ping` 和 REST `/api/health` 会同时报告 `elf_backend`、
`builtin_elf_available`、`external_elf_available`、`readelf_available` 和
`addr2line_available`。后两个字段只描述可选 GNU 后端，不再决定 AXF 功能是否可用。


## GUI 依赖（Web GUI 与 Tauri 桌面应用）

当用户需要以下功能时，需要安装 GUI 依赖：

- `mklink serve` — 远程调试服务器（REST API + WebSocket JSON-RPC）
- `mklink gui` — 启动 Web GUI（FastAPI 后端 + Vue 3 前端）
- Tauri 桌面应用 — 原生窗口体验

### Python GUI 依赖

先检查是否已安装：

```powershell
python -c "import fastapi, uvicorn; print('GUI deps OK')"
```

若导入失败：

```powershell
pip install -e ".[gui]"
```

### Node.js 依赖

Tauri 桌面应用和 Vue 3 前端需要 Node.js。先检查：

```powershell
node --version
```

若未安装，使用 winget：

```powershell
winget install --id OpenJS.NodeJS.LTS -e --accept-package-agreements --accept-source-agreements
```

然后安装前端依赖：

```powershell
cd gui
npm install
```

### Rust 工具链（Tauri 桌面应用）

Tauri v2 桌面应用需要 Rust 编译器。先检查：

```powershell
rustc --version
cargo --version
```

若未安装，分两步：

**步骤 1 — 安装 MSVC Build Tools**（Rust Windows 编译必需）：

```powershell
# 检查是否已有 Visual Studio 或 Build Tools
if (-not (Get-Command cl -ErrorAction SilentlyContinue)) {
    winget install --id Microsoft.VisualStudio.2022.BuildTools -e --accept-package-agreements --accept-source-agreements --override "--add Microsoft.VisualStudio.Workload.VCTools --includeRecommended --passive"
}
```

**步骤 2 — 安装 Rust**：

```powershell
# 下载并静默安装 rustup
$installer = "$env:TEMP\rustup-init.exe"
Invoke-WebRequest -Uri https://win.rustup.rs/x86_64 -OutFile $installer
& $installer -y --default-toolchain stable --default-host x86_64-pc-windows-msvc
Remove-Item $installer -Force

# 刷新当前会话 PATH
$env:Path += ";$env:USERPROFILE\.cargo\bin"
```

验证 Rust 安装：

```powershell
rustc --version
cargo --version
```

### Tauri 桌面应用启动

```powershell
# 开发模式（热重载，需同时手动启动 Python 后端）
cd gui
python -m mklink serve --port 8765 &   # 后端（另一终端）
npx tauri dev                           # Tauri 窗口
```

### Sidecar 打包（发布构建）

发布桌面安装包（MSI/NSIS）前，需将 Python 后端打包为独立可执行文件：

```powershell
pip install pyinstaller

# 打包 Python 后端为 mklink-sidecar.exe
pyinstaller --onefile --name mklink-sidecar --collect-all mklink -p .. mklink\__main__.py

# 将产物放入 Tauri 预期位置
New-Item -ItemType Directory -Force -Path "src-tauri\binaries" | Out-Null
Copy-Item dist\mklink-sidecar.exe "src-tauri\binaries\mklink-sidecar-x86_64-pc-windows-msvc.exe" -Force

# 构建桌面安装包
npx tauri build
```

构建产物位于 `gui/src-tauri/target/release/bundle/`。
