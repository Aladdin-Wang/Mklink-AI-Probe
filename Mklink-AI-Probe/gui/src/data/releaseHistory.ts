export interface ReleaseHistoryEntry {
  version: string
  date: string
  summary: string
  changes: string[]
}

export const releaseHistory: ReleaseHistoryEntry[] = [
  {
    version: '0.1.4',
    date: '2026-07-25',
    summary: '完善烧录、符号解析与 HardFault 定位',
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
  },
  {
    version: '0.1.3',
    date: '2026-07-24',
    summary: '修复符号解析并完善调试资源协同',
    changes: [
      '修复 AXF/ELF 文件源切换与共享符号状态，重新解析后立即使用当前文件。',
      '支持匿名 struct/union 成员展开，并可粘贴 C 语言定义恢复复杂结构变量。',
      'RTT View 增加 UTF-8、GB2312、GBK、GB18030 和 Big5 中文编码切换。',
      '统一 SuperWatch、RTT、内存读写和在线/脱机下载的 SWD 资源互斥。',
      '新增 AI Skill 主动版本提醒，以及经用户确认后的桌面端与 Skill 自动更新。',
    ],
  },
  {
    version: '0.1.2',
    date: '2026-07-22',
    summary: '完善 Web 调试交互与快速启动',
    changes: [
      'RTT View 增加曲线开关、坐标轴、缩放拖动，并在暂停或停止后保留曲线。',
      'SuperWatch 增加时间戳原始数据保存、功能互斥和输入框快捷键隔离。',
      '增加离线版本历史、跨平台 U 盘单 HTML 启动入口和网页版 AXF/MAP 文件上传。',
    ],
  },
  {
    version: '0.1.1',
    date: '2026-07-21',
    summary: '增强 V4 脱机烧录过程反馈',
    changes: [
      'V4 脱机烧录下载过程支持按脚本名称实时显示设备输出。',
      '完善签名更新包的 GitHub/Gitee 发布与校验流程。',
    ],
  },
  {
    version: '0.1.0',
    date: '2026-07-21',
    summary: '首个稳定桌面版本',
    changes: [
      '提供在线烧录、脱机烧录以及目标与算法管理。',
      '集成 RTT、SuperWatch、SystemView、串口和 Modbus 调试视图。',
      '加入符号、内存、HardFault 分析和签名自动更新能力。',
    ],
  },
]
