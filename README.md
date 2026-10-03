<div align="center">

# MKLink AI Probe

**把嵌入式烧录与调试交给 AI，用波形和日志看结果。**

[官方仓库](https://github.com/MicroKeen/Mklink-AI-Probe) · [下载与更新](https://github.com/MicroKeen/Mklink-AI-Probe/releases/latest) · [使用文档](https://microboot.readthedocs.io/zh-cn/latest/tools/microlink/microlink/) · [问题反馈](https://github.com/MicroKeen/Mklink-AI-Probe/issues)

</div>

## 从一句话开始

把下面这段话发给能够操作本机文件和软件的 AI 助手，例如 Codex、Claude Code 或 Cursor：

> 请从 https://github.com/MicroKeen/Mklink-AI-Probe 安装 MKLink AI Probe 最新正式版。按仓库的 Skill 和安装文档，为你自己安装完整的 MKLink Skill，配置需要的运行环境，检查设备连接，并帮我打开调试界面。优先使用正式发布的安装包，完成后告诉我检查结果。

你不需要复制命令、修改代码或寻找依赖。AI 会按当前电脑环境完成安装、配置与自检；遇到系统授权提示时，由你确认。普通网页聊天需要连接本地执行环境，才能操作你的电脑。

## 接好设备，告诉 AI 你想做什么

将 MKLink/MicroLink 下载器接到电脑和目标板，再把工程文件夹、芯片型号和任务告诉 AI。例如：

| 想完成的事 | 可以直接这样说 |
| --- | --- |
| 下载程序 | “板子已经接好，请检查这个工程，编译并下载固件，再确认程序正常运行。” |
| 观察变量 | “打开 SuperWatch，帮我观察目标转速和反馈转速，分别命名为中文，放在同一组比较。” |
| 调节参数 | “在持续采样时修改这个参数，让我看到修改前后的阶跃变化。” |
| 整理波形 | “把电机相关变量放一组，温度放另一组，突出显示反馈值。” |
| 分析历史数据 | “导入这份采集日志，回放异常前后的波形，帮我分析原因。” |
| 排查故障 | “程序进入 HardFault 了，请读取现场并结合工程定位问题。” |
| 配置脱机下载 | “把这些固件配置到下载器，之后不用电脑也能烧录。” |
| 更新软件 | “检查 MKLink 正式版更新，更新应用和你的 Skill，并确认可以使用。” |

AI 会结合实际工程、探针和芯片选择可用方式。你负责连接硬件、说明目标，并确认需要授权的操作；其余步骤可以交给 AI。

## 也能直观看到每一步

Windows 桌面版自带运行环境，安装后可直接打开。Web 界面在浏览器中显示同一套调试功能。你可以让 AI 操作，也可以在界面查看进度、选择变量和调整波形。

- **在线与脱机烧录**：预览固件、选择芯片和算法，执行擦除、下载、校验与复位。
- **SuperWatch**：连续采样、实时写入、日志导入回放；每个分组对应一个波形区，支持中文名称、加粗、采样点显示和专注视图。
- **日志与任务分析**：RTT、VOFA 和 SystemView，查看运行日志、波形与任务时间轴。
- **变量与故障定位**：查看结构体成员、内存和寄存器，结合工程符号分析 HardFault。
- **串口与 Modbus**：收发数据、读取设备和观察变化。
- **远程协作**：通过现场 Agent 连接远端设备，由 AI 协助完成调试。

需要 U 盘快捷入口、远程连接或特定芯片配置时，直接告诉 AI；详细配置交由 AI 查阅仓库文档。

## 0.2.3 更新

- SuperWatch 新增日志回放和采样中写入，V4 支持 HPM/JTAG 实时通道（需配套固件）。
- 分组与波形区合一，支持原位中文命名、拖动移组、加粗、采样点和专注视图；改进多关键词与结构体成员搜索。
- 修复烧录扇区识别与采集稳定性问题，完善电源遥测。

## 设备与支持

使用 MKLink/MicroLink 探针。可用功能取决于探针版本、固件和目标芯片；型号出现在算法列表中，并不代表所有功能都已完成真机验证。把具体型号告诉 AI，它会先检查支持情况。HPM 实时通道需要 V4，V2/V3 不支持此通道。

Windows 提供桌面安装包；其他系统的运行环境由 AI 根据发布内容和支持情况配置。下载统一使用 [MicroKeen 官方 Releases](https://github.com/MicroKeen/Mklink-AI-Probe/releases/latest)，访问不便时可让 AI 使用 [Gitee 镜像](https://gitee.com/Aladdin-Wang/Mklink-AI-Probe/releases)。

## 遇到问题

可以告诉 AI：

> 请检查 MKLink 的版本、设备连接和错误日志，尝试定位问题。如果需要向开发者反馈，请先整理复现步骤和脱敏报告给我确认。

开发与问题反馈统一在 [MicroKeen/Mklink-AI-Probe](https://github.com/MicroKeen/Mklink-AI-Probe)。请勿公开设备序列号、私有固件、完整工程或访问凭据。

MIT License
