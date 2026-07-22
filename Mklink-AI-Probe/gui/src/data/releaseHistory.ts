export interface ReleaseHistoryEntry {
  version: string
  date: string
  summary: string
  changes: string[]
}

export const releaseHistory: ReleaseHistoryEntry[] = [
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
