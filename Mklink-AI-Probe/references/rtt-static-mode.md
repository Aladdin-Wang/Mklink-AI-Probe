# RTT 静态编译模式（rtt_storage_mode=1）

## 背景

RTT 控制块（`_SEGGER_RTT`）默认放在链接器自动分配的 `.bss` 段，每次链接地址都
会浮动。**静态模式**让用户在 C 代码中用 `SEGGER_RTT_SECTION` 宏把 RTT 控制块固
定到已知 RAM 地址，避免：
- 控制块地址浮动（每次 build 后 mklink-flash 都要重新解析）
- 探针固件需要扫描整个 RAM 范围找控制块
- 同 idcode 兼容芯片（如 STM32F4 / HC32F4A0 共享 `0x2BA01477`）的歧义

## 字段定义

| 字段 | 类型 | 存储位置 | 取值 |
|---|---|---|---|
| `rtt_storage_mode` | int | `.mklink/rtt_config.json` | `0` = 动态搜寻（默认）/ `1` = 静态编译 |

`rtt_addr` 在两种模式下的语义：

| 模式 | 语义 |
|---|---|
| 0 | 搜索起点（来自 MAP/ELF `_SEGGER_RTT` 符号），`search_size=1024` |
| 1 | CB 精确地址（用户用 `SEGGER_RTT_SECTION` 宏固定），`search_size=0`（试探探针无扫描） |

## 实现要点

### 1. 固件侧（Keil AC5 + STM32 范式）

**`src/SEGGER_RTT.c` call site 用 `.ARM.__at_0x<HEX>` 段名 + `zero_init`**：

```c
#if defined(MKLINK_RTT_STATIC)
  SEGGER_RTT_CB_ALIGN(SEGGER_RTT_CB _SEGGER_RTT)
      __attribute__((section(".ARM.__at_0x2001F000"), zero_init));
  static char _acUpBuffer  [BUFFER_SIZE_UP]
      __attribute__((section(".ARM.__at_0x2001F0A8"), zero_init));  /* +168 */
  static char _acDownBuffer[BUFFER_SIZE_DOWN]
      __attribute__((section(".ARM.__at_0x2001F4A8"), zero_init));  /* +1024 */
#else
  /* 默认 .bss 布局 */
  SEGGER_RTT_PUT_CB_SECTION(SEGGER_RTT_CB_ALIGN(SEGGER_RTT_CB _SEGGER_RTT));
  ...
#endif
```

**为什么用 `.ARM.__at_0xADDR` 而非 `at(0xADDR)` 或 `SEGGER_RTT_SECTION` 宏**：
- `.ARM.__at_0xADDR` 是 ARM-CC 官方识别的特殊段名，链接器直接放绝对地址，**段名是字面量**
- `at(0xADDR)` 会让 CB + 两个 buffer 都撞到同一地址（SEGGER_RTT 三个变量用同一个宏，缺位移）
- `SEGGER_RTT_SECTION=...` 形式在 AC5 编译器 Define 字段里**会被 IDE/lint 工具自动剥离引号**

**重要：`zero_init` 标记 BSS**，让标准 AC5 启动代码（`__main` + `Image$$...$$ZI$$Base`）零填充。

### 2. scatter 文件预留 RAM 区

```scat
RW_IRAM1 0x20000200 0x0001EE00  {   ; 缩小到 0x2001EFFF
   *.o (.tf_data)
   .ANY (+RW +ZI)
}
RW_IRAM_RTT 0x2001F000 0x00001000  {   ; 4KB 区域覆盖 RTT
   *.o (.segger_rtt_ops)
}
```

**关键陷阱**：
- 地址必须**避开 RT-Thread 内核 init 表**（实测 0x2001F800 会被 init 表覆盖）
- 推荐的"安全"地址：`0x2001F000`（SRAM1 末端 4KB 区域中间）
- `RW_IRAM1` 必须**缩小**留出 RTT 区域，否则 `.ANY (+RW +ZI)` 会越过边界

### 3. 编译器 Define

```xml
<Define>__CC_ARM, ..., USE_RTT, MKLINK_RTT_STATIC</Define>
```

`MKLINK_RTT_STATIC` 是**无值无引号**的触发宏，避开 IDE/lint 自动剥离引号。

### 4. mklink-flash 解析器

`mklink/rtt_addr.py::find_rtt_addr_from_uvprojx()` 检测 `MKLINK_RTT_STATIC` 触发宏，
从 `*.uvprojx` 的 `<Define>` 提取 → 段名硬编码为 `.segger_rtt_ops` → 解析
`*.sct` 中 `RW_IRAM_RTT` 执行域起始地址。

### 5. 运行时初始化

`SEGGER_RTT_Init()` 在 `main()` 入口被调用，触发 `_DoInit()`：
- 设置 `acID = "SEGGER RTT\0\0\0\0"`（前 16 字节）
- 设置缓冲指针
- 设置 `MaxNumUpBuffers=3`、`MaxNumDownBuffers=3`

**重要**：RTT 启动前需等待 ~8 秒让 RT-Thread 完成 init（`SEGGER_RTT_Init` 才执行）。

## 验证流程

```bash
# 1. 编译（Keil 真实环境）
"D:/Keil_v5/UV4/UV4.exe" -sg -j0 -r -t rt-thread project.uvprojx
# 预期：0 errors, warnings only

# 2. 检查 .map 确认放置
grep "_SEGGER_RTT\s+0x" build/keil/List/rt-thread.map
# 预期：_SEGGER_RTT  0x2001f000  Data/Zero  168  segger_rtt.o(.ARM.__at_0x2001F000)

# 3. 按统一固件下载优先级下载
# 本例 Keil 工程默认用 UV4.exe -f；IDE 不可用时才进入 pyOCD，最后才是脱机 API。
# 完整规则见 firmware-download-priority.md。

# 4. 重置设备并等待 RT-Thread init
python -c "
from mklink.bridge import MKLinkSerialBridge
import time
b = MKLinkSerialBridge('COM5')
b.connect()
b.send_command('cmd.reset_chip()', timeout=10.0)
time.sleep(8)  # 关键：等 RT-Thread 完成 init
print(b.send_command('RTTView.start(0x2001F000, 1024, 0)', timeout=10.0))
"

# 5. 预期响应
# Find SEGGER RTT addr 0x2001f000
# UpBuffer Channel 0 Size: 1024 Mode: 0

# 6. 读心跳流
python -c "
from mklink.bridge import MKLinkSerialBridge
b = MKLinkSerialBridge('COM5')
b.connect()
b.send_command('RTTView.start(0x2001F000, 1024, 0)', timeout=10.0)
import time; time.sleep(8)
print(b.read_stream(duration=3.0))
"
# 预期：[HB] tick=N seq=M 持续输出
```

## GEC6100D 实测结果（2026-06-09）

- ✅ Keil 编译 0 errors
- ✅ 探针响应 `Find SEGGER RTT addr 0x2001f000`
- ✅ UpBuffer Channel 0 Size: 1024 Mode: 0 识别正确
- ✅ 心跳 `[HB] tick=N seq=M` 持续输出（每秒一帧，连续 18 秒稳定）

## 关闭静态模式（回退到动态搜寻）

只需在 `project.uvprojx` 的 `<Define>` 中**删除 `MKLINK_RTT_STATIC`**，重新编译
烧录即可。mklink-flash 自动从 MAP/ELF 解析控制块地址。

## 集成路径（重要！）

**`mklink rtt-integrate` 命令**会把 `mklink/rtt_sources/SEGGER_RTT.c` 复制到目标项目。
该 master 文件**已包含** `MKLINK_RTT_STATIC` 守卫（参见第 254-269 行），
所以**新集成的项目也支持静态模式**，无需手动修改集成后的 SEGGER_RTT.c。

集成后启用静态模式只需两步：
1. 在 `<Define>` 加 `MKLINK_RTT_STATIC`
2. 在 scatter 加 `RW_IRAM_RTT <ADDR> <SIZE> { *.o (.segger_rtt_ops) }`

**注意**：master 文件用的是**通用段名** `.segger_rtt_ops`（不带硬编码地址），
**地址由用户的 scatter 文件决定**。这与 GEC6100D 项目的方案不同（它用
`.ARM.__at_0x<HEX>` 段名硬编码地址）——两种方案都有效，scatter 段名方案更**可移植**。

**GEC6100D 项目的特殊方案**（用 `.ARM.__at_0x2001F000`）适用于：
- scatter 文件不便改的工程
- 需要 AC5 的绝对地址放置语义
- 不在意 scatter 文件的兼容性

**新项目推荐**：用通用段名 + scatter 映射方案。

## 跨编译器兼容性

| 编译器 | 段名方案 | 备注 |
|---|---|---|
| AC5 (`__CC_ARM`) | `.ARM.__at_0x<HEX>` + `zero_init` | **推荐**（官方支持） |
| AC6 (`__ARMCC_VERSION >= 6000000`) | `.ARM.__at_0x<HEX>` + `zero_init` | 相同 |
| GCC (`__GNUC__`) | `.segger_rtt_ops` + scatter 映射 | 用普通段名 |
| IAR (`__ICCARM__`) | `location=".segger_rtt_ops"` 配合 `#pragma` | 详见 IAR 文档 |

## 故障排查

| 现象 | 根因 | 修复 |
|---|---|---|
| 编译报 `#1066: expected a string literal` | AC5 不展开 `__attribute__` 内的宏参数 | 改用 `.ARM.__at_0xADDR` 段名（字面量） |
| 编译报 `#1187E: cannot find address` | `RW_IRAM1` 覆盖了 RTT 区域 | 缩小 `RW_IRAM1` 留出 RTT 区 |
| 探针响应 `no find _SEGGER RTT addr` | (1) 地址错  (2) `SEGGER_RTT_Init` 未执行  (3) 区域被 RT-Thread init 表覆盖 | 查 .map 确认地址 + 重置后等 8 秒 + 换地址 |
| 探针响应 OK 但心跳流为空 | 控制块 magic 缺失 | 检查 `USE_RTT` 宏 + `main()` 是否调用 `SEGGER_RTT_Init()` |
