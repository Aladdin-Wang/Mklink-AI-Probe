# 固件下载优先级

> 触发词：下载固件、编译并烧录、Keil、IAR、pyOCD、在线烧录、脱机烧录、FLM
> 返回索引：[SKILL.md](../SKILL.md)

## 强制路由

除 HPM 例外外，自动下载严格按以下顺序选择：

1. **IDE 原生编译和下载**：工程文件存在且对应 IDE 可用时首选。
2. **pyOCD 在线烧录**：IDE 不可用、不适用，或用户只有预编译 HEX/BIN 时使用。
3. **MKLink 脱机下载 API**：前两种能力都不适用，或用户明确要求把任务部署到下载器时使用。

`python -m mklink flash` 是原生 MKLink 串口/FLM 路径，只在用户明确要求该路径、兼容旧流程或诊断时使用，不参与上述自动优先级。

“不可用/不适用”可以进入下一优先级，例如没有 IDE、没有工程文件、只有预编译镜像或 pyOCD 不支持目标。“已经开始但失败”不能静默换后端；先保留日志并报告编译错误、下载错误、目标配置或硬件问题，得到用户同意后再切换。

## Keil 默认流程

用户表示“Keil 能正常下载”时，优先复用该工程已有的下载器、目标和 Flash 算法配置。
先停止 GUI/MCP 的采集并释放探针，避免与 IDE 抢占。不要为了使用 MKLink MCP
而改走脱机下载，也不要要求用户重新选择已经由工程确定的算法。

先从 `.mklink/project_info.json` 或 `python -m mklink project-init` 获取 `uvprojx_path` 和 `target_name`，再定位 `UV4.exe`。默认执行编译后下载：

先按[工作目录约定](work-files.md)确定并创建本次日志目录，将其绝对路径赋给
`$MklinkLogDir`；不要使用系统临时目录。

```powershell
$BuildLog = Join-Path $MklinkLogDir 'mklink-keil-build.log'
$FlashLog = Join-Path $MklinkLogDir 'mklink-keil-flash.log'

& $Uv4 -b $Uvprojx -t $Target -j0 -o $BuildLog
if ($LASTEXITCODE -ge 2) { throw 'Keil build failed' }

& $Uv4 -f $Uvprojx -t $Target -j0 -o $FlashLog
if ($LASTEXITCODE -ge 2) { throw 'Keil download failed' }
```

Keil 返回码 `0` 表示成功，`1` 表示仅警告，`2` 及以上视为失败。即使返回码可接受，也要检查日志没有错误，并确认预期 HEX/AXF/MAP 已生成或更新。

仅当用户明确说“不要编译，只下载”，且现有产物存在并与目标一致时，跳过 `-b`，直接执行 `-f`。不要根据文件存在就擅自跳过默认编译。

## IAR 和其他 IDE

IAR 工程优先用 `IarBuild.exe <project.ewp> -build <configuration>` 编译。只有项目已经提供并验证过 C-SPY/批处理下载配置时才直接调用 IDE 下载；不要猜测通用 C-SPY 参数。缺少可靠的 IDE 下载入口时，将该能力视为不可用并进入 pyOCD 在线烧录。

其他 IDE 同样要求已知且可验证的命令行编译/下载入口。不要为赶进度临时拼接未验证参数。

## pyOCD 在线烧录

在线烧录使用 `/online-flash` 页面或 `/api/online-flash` REST 工作流，不要用原生串口 `python -m mklink flash` 冒充 pyOCD：

1. 启动 `python -m mklink gui --no-browser --host 127.0.0.1 --port 8765 --project-root <project>`。
2. `GET /api/online-flash/probes` 选择 MKLink CMSIS-DAP 探针。
3. `GET /api/online-flash/targets` 确认精确器件。
4. `POST /api/online-flash/images/inspect` 上传并检查 HEX/BIN；BIN 必须给基址。
5. `POST /api/online-flash/jobs` 按 `connect, erase/program, verify, reset, disconnect` 启动作业。
6. 轮询作业或 SSE 事件直到 `succeeded`，失败时保留稳定错误码并停止回退。

详细端点和资源冲突处理见 [commands-remote-gui.md](commands-remote-gui.md)。

## 脱机下载兜底

最后使用 `/offline-flash` 页面或 `/api/offline-download` 的 `status`、`detect-model`、`algorithms`、`preview`、`deploy` 和 `trigger` 流程。部署前确认下载器型号、固件顺序、自动次数、IDCODE 超时、SWD 时钟和固件/算法绑定；部署成功不等于目标已经执行，触发后要等待设备输出结束并验证目标结果。

## FLM 来源

以下是已选定 FLM 路径后的来源顺序，不改变 IDE → pyOCD → 脱机的下载优先级。

自动选择顺序：

1. 发布包内置的精简 Pack 算法；
2. 发布包内置的 DAPLink FLM；
3. 当前用户已安装的 CMSIS-Pack；
4. 已登记的用户自定义 FLM。

自动选择优先使用覆盖固件地址范围且标记为默认的内置算法。只有内置源没有精确器件/地址覆盖时才查询已安装 Pack 和自定义目录。用户显式提供 `--flm` 或在界面选择算法时，显式选择覆盖自动顺序；执行前仍校验文件后缀、范围和摘要。

HPM 型号是固定例外：只使用设备端 HPM ROM API，不发现、下载或加载任何 FLM/Pack。支持 BIN；新版 V4 固件还支持 HEX，使用文件内绝对地址，由工具检查能力并规范化文件。

## FLM 兼容性

STM32 的一个 FLM 常由同系列多个型号共享，文件名不必包含芯片完整料号。
精确名称没有命中时，继续核对当前 IDE 工程使用的算法和本地 Pack 的 `.pdsc`
器件继承/算法映射；已知可用的工程配置优先作为兼容性证据，必要时显式指定 FLM。

执行前核对 Flash 控制器/容量组、起始地址、实际容量、扇区布局、算法 RAM
工作区以及镜像所有段的范围。算法声明的范围不能代替目标芯片实际容量；仅覆盖
镜像地址也不足以证明算法兼容。保留真实目标型号，不改成更大容量型号来通过检查。

例如 STM32F103CB 找不到同名 FLM 时，应检查工程或 Pack 是否映射到
`STM32F10x_128.FLM`，确认布局和 RAM 工作区后复用；不能默认回退到
`STM32F10x_1024.FLM`。C8 与 CB 不能仅因引脚相同就假定可用容量相同。

多个候选先用上述证据筛选。唯一兼容项可自动显式选定；仍存在实质歧义才请用户
选择。工具若仍拒绝已确认的映射，记录限制并使用可用的 IDE 路径，不绕过校验。
这项兼容复用只适用于普通烧录，不扩大选项字节、加锁或解锁的精确型号白名单。

## 完成信号

IDE/pyOCD/脱机任一路径都必须记录实际使用的后端、产物摘要和目标型号。下载后至少完成 Flash 回读或后端 verify，并通过 RTT、运行计数或用户指定行为证明固件在目标上运行；最后释放探针和服务资源。
