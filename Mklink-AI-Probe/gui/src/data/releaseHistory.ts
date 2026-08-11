export interface ReleaseHistoryEntry {
  version: string
  date: string
  summary: string
  summaryEn: string
  changes: string[]
  changesEn: string[]
}

export const releaseHistory: ReleaseHistoryEntry[] = [
  {
    version: '0.1.6',
    date: '2026-08-11',
    summary: '完善现场 Agent、在线烧录与高吞吐终端',
    summaryEn: 'Improved Site Agent, online flashing, and high-rate terminals',
    changes: [
      '主 GUI 新增 Site Agent 页面，统一管理直连与 LAN STCP 配置、运行状态和工程师连接入口。',
      '本地 GUI 与远程 Agent 共用同一个 sidecar、探针设备实例和资源管理器。',
      '访问令牌与 STCP 凭据使用 Windows DPAPI 加密保存，明文不进入命令行或前端状态。',
      '启用现场服务后关闭主窗口会转入托盘，显式退出才停止统一后端。',
      '正式 Release 同时提供主安装包、Skill 包和独立 Site Agent portable ZIP。',
      '在线烧录在同一路径重复加载或固件重新编译后重新读取并解析最新内容，修复 HEX 不重新解析和手动加载仍使用旧文件的问题。',
      '修复 HPM 复合 USB 探针的端口匹配与可烧录状态，并支持 CST92F41KxVxxx 相对扇区几何解析。',
      '串口助手与 RTT 终端改用隔离的数据解码和渲染通道，终端模式不再挂载或同步隐藏日志 DOM，避免高数据流运行后卡死。',
      '串口与 RTT 日志模式支持将保留的数据保存到本地文件，终端模式保持轻量实时刷新。',
    ],
    changesEn: [
      'Add a Site Agent page for direct and LAN STCP configuration, runtime status, and engineer connection guidance.',
      'Share one sidecar, probe device instance, and resource manager between the local GUI and remote Agent.',
      'Protect Site Agent and STCP credentials with Windows DPAPI without exposing plaintext to command lines or frontend status.',
      'Keep the unified backend in the tray while Site Agent is enabled and stop it only on explicit exit.',
      'Publish the standalone Site Agent portable ZIP alongside the installer and Skill archive.',
      'Reload and reparse rebuilt firmware even when the same path is selected, fixing stale manual loads and repeated HEX loads that were not reparsed.',
      'Fix port matching and flash readiness for composite HPM USB probes, and support relative sector geometry for CST92F41KxVxxx devices.',
      'Isolate Serial Assistant and RTT terminal decoding and rendering, and avoid mounting or synchronizing hidden log DOM in terminal mode to prevent high-rate stream freezes.',
      'Allow retained Serial and RTT log data to be saved to local files while keeping terminal mode lightweight and responsive.',
    ],
  },
  {
    version: '0.1.5',
    date: '2026-08-03',
    summary: '集成远程 Site Agent 并完善调试工作流',
    summaryEn: 'Integrated remote Site Agent and completed the debugging workflows',
    changes: [
      '集成远程 Site Agent、远程 SDK/CLI/MCP 与认证的直接 WebSocket 协议。',
      '修复开发服务器对 RTT、SuperWatch、SystemView 和 VOFA 二进制 WebSocket 的代理。',
      '完善 RTT View、串口助手终端模式、ANSI 解析和独立资源生命周期。',
      'SuperWatch 支持 16 通道、高吞吐采集、历史暂停浏览和独立纵轴分离。',
      '大数组符号按 256 项分页展开，支持继续浏览数组尾部。',
    ],
    changesEn: [
      'Integrate the remote Site Agent, remote SDK/CLI/MCP, and authenticated direct WebSocket protocol.',
      'Proxy RTT, SuperWatch, SystemView, and VOFA binary WebSocket streams in the development server.',
      'Improve RTT View and Serial Assistant terminal modes, ANSI parsing, and independent resource lifecycles.',
      'Support 16-channel high-rate SuperWatch acquisition, paused history browsing, and split Y axes.',
      'Browse large symbol arrays in 256-item pages, including later tail ranges.',
    ],
  },
  {
    version: '0.1.4',
    date: '2026-07-25',
    summary: '完善烧录、符号解析与 HardFault 定位',
    summaryEn: 'Improved flashing, symbol parsing, and HardFault diagnostics',
    changes: [
      'BIN 文件加载后主动提示填写下载地址，并在加载前使用中性扇区提示，避免误判固件检查失败。',
      '本地设备和文件来源改为自动保存，切换页面后配置保持不丢失。',
      '在线与脱机烧录支持拖拽加载、文件路径保持和重新编译后自动刷新。',
      '脱机烧录仅刷新 MICROKEEN U 盘；V2/V3 固定 offline_download.py，V4 可自定义脚本名，刷新过程不再弹出命令行窗口。',
      '桌面端显示用户选择的完整 AXF 路径，浏览器端继续使用安全上传路径。',
      '符号、变量、RTT 搜索与 HardFault 默认使用内置 pyelftools，外部工具仅作为显式兼容后端。',
      'HardFault 分析新增故障函数、源码位置、异常栈帧和调用栈展示。',
      'AI Skill 默认通过 MKLink 读取目标数据，并隔离 MCP 串口日志，避免污染 JSON-RPC；仅在读取失败后使用 pyOCD 只读后备。',
    ],
    changesEn: [
      'Prompt for a BIN base address after loading and use neutral sector guidance before inspection.',
      'Automatically save local device and file-source settings across page changes.',
      'Support drag-and-drop, retained paths, and automatic reloads after rebuilds for online and offline flashing.',
      'Refresh only the MICROKEEN drive for offline flashing; use fixed scripts for V2/V3 and custom script names for V4.',
      'Show the complete AXF path on desktop while retaining safe upload paths in browsers.',
      'Use built-in pyelftools by default for symbols, variables, RTT search, and HardFault analysis.',
      'Show fault functions, source locations, exception frames, and call stacks in HardFault reports.',
      'Read targets through MKLink by default in the AI Skill, with isolated MCP serial logs and read-only pyOCD fallback.',
    ],
  },
  {
    version: '0.1.3',
    date: '2026-07-24',
    summary: '修复符号解析并完善调试资源协同',
    summaryEn: 'Fixed symbol parsing and improved debug resource coordination',
    changes: [
      '修复 AXF/ELF 文件源切换与共享符号状态，重新解析后立即使用当前文件。',
      '支持匿名 struct/union 成员展开，并可粘贴 C 语言定义恢复复杂结构变量。',
      'RTT View 增加 UTF-8、GB2312、GBK、GB18030 和 Big5 中文编码切换。',
      '统一 SuperWatch、RTT、内存读写和在线/脱机下载的 SWD 资源互斥。',
      '新增 AI Skill 主动版本提醒，以及经用户确认后的桌面端与 Skill 自动更新。',
    ],
    changesEn: [
      'Fixed AXF/ELF source switching and shared symbol state so reparsing immediately uses the current file.',
      'Expanded anonymous struct/union members and added pasted C definitions for complex variables.',
      'Added UTF-8, GB2312, GBK, GB18030, and Big5 encoding selection to RTT View.',
      'Unified SWD resource ownership across SuperWatch, RTT, memory access, and flashing.',
      'Added proactive AI Skill update notices and approved desktop/Skill updates.',
    ],
  },
  {
    version: '0.1.2',
    date: '2026-07-22',
    summary: '完善 Web 调试交互与快速启动',
    summaryEn: 'Improved Web debugging interactions and quick launch',
    changes: [
      'RTT View 增加曲线开关、坐标轴、缩放拖动，并在暂停或停止后保留曲线。',
      'SuperWatch 增加时间戳原始数据保存、功能互斥和输入框快捷键隔离。',
      '增加离线版本历史、跨平台 U 盘单 HTML 启动入口和网页版 AXF/MAP 文件上传。',
    ],
    changesEn: [
      'Added charts, axes, zooming, and panning to RTT View while retaining plots after pause or stop.',
      'Added timestamped raw-data export, resource coordination, and input shortcut isolation to SuperWatch.',
      'Added offline release history, a portable single-HTML launcher, and browser AXF/MAP upload.',
    ],
  },
  {
    version: '0.1.1',
    date: '2026-07-21',
    summary: '增强 V4 脱机烧录过程反馈',
    summaryEn: 'Improved V4 offline flashing feedback',
    changes: [
      'V4 脱机烧录下载过程支持按脚本名称实时显示设备输出。',
      '完善签名更新包的 GitHub/Gitee 发布与校验流程。',
    ],
    changesEn: [
      'Streamed V4 offline flashing output under the selected script name.',
      'Improved signed GitHub/Gitee update publication and verification.',
    ],
  },
  {
    version: '0.1.0',
    date: '2026-07-21',
    summary: '首个稳定桌面版本',
    summaryEn: 'First stable desktop release',
    changes: [
      '提供在线烧录、脱机烧录以及目标与算法管理。',
      '集成 RTT、SuperWatch、SystemView、串口和 Modbus 调试视图。',
      '加入符号、内存、HardFault 分析和签名自动更新能力。',
    ],
    changesEn: [
      'Provided online and offline flashing with target and algorithm management.',
      'Integrated RTT, SuperWatch, SystemView, serial, and Modbus debug views.',
      'Added symbol, memory, HardFault analysis, and signed automatic updates.',
    ],
  },
]
