# V3/V4 USB 恢复与 DAP 中断保护修复

## 实现

- DAP 命令外层改为 RT-Thread 调度锁，允许 USB IRQ 响应；保留 SWD/JTAG 底层单次传输的中断保护，并在 SWJ/SWD 序列增加相同的 1–30 MHz 保护。低速 SWD 原有实现保持不变，未改变时钟校准或支持的频率档位。
- 每次工作线程处理一个包后让出一个 tick，避免连续主机请求令低优先级变量/喂狗线程一直无法运行。未关闭、延长或额外喂看门狗。单条极端长命令仍受原协议重试次数和看门狗约束。
- DAP 复位清理索引/计数，设 Abort 并递增 USB 会话代次。CPU 独立保存执行中的请求和响应，复位中到达的新包不会改写正在执行的包；旧会话完成的响应不再投递到新会话。
- 增加响应队列背压，保留在途 IN 缓冲区，避免主机不读响应时覆盖 DMA 数据；零长度 OUT 不执行旧命令，短包尾部清零。
- V3 控制台复位清理 TX 环形队列及端点状态；相同波特率重新打开也能启用，重复设置波特率不会错误释放在途 IN 的 busy 标志。V4 保留其已有控制台 DMA/恢复实现。
- 无链接脚本/堆栈大小修改。V4 新增的 1 KiB CPU 包暂存放入既有 AHB SRAM 段；避免挤占原来紧张的 DLM 堆空间。暂存数据使用前均被复制/写入，不依赖该段清零。

修改范围为 V3、V4；本轮未修改 V2 USB 实现。V2 的此前 AP 修复保持原状。

## 构建和模型

两版原 SEGGER Debug 工程构建成功。实际 C 代码模型验证：执行期间 IRQ 开启/调度锁持有，Abort IRQ 可达，执行中复位重配置且新请求不会覆盖旧请求，旧响应丢弃，响应队列背压、环绕、断线回调及重新配置。两版 AP 发现模型回归也通过。

固件版本号未更改，未发布：

| 固件 | 字节数 | SHA256 |
|---|---:|---|
| V3 UF2 | 770048 | `95add99c4a26f304203475c35a4ec0fd8fbf793ab2cadebee08b2e4db762aa61` |
| V4 UF2 | 1607168 | `76cdb5d517eb53d5a7d94aaafc081c8e3a22f16f704d0e8270ef24e4dc30d266` |

## V3 实机

已通过原命令口进入 UF2 模式，并写入上述 V3 固件。STM32H743 目标程序、Cache 和供电配置未修改。

1. 升级后真实 HTTP/串口 Memory/SuperWatch 完整验收通过。
2. 直接 CMSIS-DAP USB 测试完成 241 次 DPIDR 读取；覆盖 100 kHz、1/5/10/20/30 MHz 请求档位，各 20 次。15 MHz 按原有协议策略返回拒绝，此为预期结果，不改变原频率限制。未用示波器测量实际时钟。
3. 对 DPIDR 设置不可能匹配的值并将重试次数设为 65535，无目标内存写入。重试期间 EP0 GET_CONFIGURATION 返回正常；20 ms 后发送 Abort，约 21.28 ms 收到部分完成/不匹配响应，随后 ID 读取正常。
4. DAP 环形队列索引推进后执行 SET_CONFIGURATION 5 次，每次重新握手、读 ID 成功。这是 USB 重配置测试，不等同于物理断电、总线 RESET 或系统驱动卸载测试。
5. USB 测试后再次执行 H743 三场景验收：累计 4170 样本、0 读错误、0 丢弃；非对齐写入、全零回读和完整原数据恢复通过。电压查询返回 3251 mV，电流/功率为 null，age 3 ms。

实机仅有 V3/H743；V4 和 JTAG 没有本轮真机验证。尚未用真实断开的目标复现“连续识别失败后需卸载设备”，上述不匹配/Abort 提供可控重试压力，不能证明历史掉线只有一个原因。

## 本机独立的 WinUSB 注册问题

CMSIS-DAP 节点绑定微软 WinUSB 且 PnP=OK，但 Device Parameters 缺少 `DeviceInterfaceGUIDs`；libusb 可枚举 VID/PID，打开失败为 Entity not found。用户授权管理员操作后，脚本先备份该设备节点，再只补入固件 OS 2.0 描述符中的 GUID，并重启该接口。未卸载/替换驱动包。修复后直接 USB 测试通过。

这证明本机接口注册缺失确实阻碍应用访问，不证明它就是最初采样停滞的原因，也不要求给其他电脑盲目写注册表。脚本及备份留在本地测试目录，不提交设备实例标识。

参考：[Arm DAP_TransferAbort](https://arm-software.github.io/CMSIS_5/develop/DAP/html/group__DAP__TransferAbort.html) 允许传输中止命令在传输仍进行时执行；[微软 WinUSB 注册文档](https://learn.microsoft.com/en-us/windows-hardware/drivers/usbcon/automatic-installation-of-winusb) 说明接口 GUID 的注册用途。
