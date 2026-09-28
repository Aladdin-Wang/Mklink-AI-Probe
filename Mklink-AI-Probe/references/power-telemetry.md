# VCC 输出测量（0.2.3）

读取的是下载器 VCC 输出的 ADC 滤波测量值，不是设定电压，也不是目标 VREF。
需要支持 `cmd.get_power()` 的配套固件；仅升级 CLI/Skill 不能让旧固件具备接口。

| 下载器 | 电压 | 电流 | 功率 |
|---|---|---|---|
| V3 | 实测 | 不支持 | 不支持 |
| V4 | 实测 | 实测 | 实测电压 × 实测电流 |

## 调用

- MCP：建立连接后调用 `get_power()`，使用已有空闲命令会话。
- CLI：`python -m mklink power-read --port COM4 --json`，端口替换为实际命令口。
- Python：已连接的 `Device` 调用 `device.get_power()`。
- 固件 Pika 命令：`cmd.get_power()`。

这是只读查询，无需供电电压确认；它不调用开关供电、复位、目标内存读取或设置电压。
不得为了取得读数自动调用 `set_power_on`。调整供电仍遵循原有逐次电压确认规则。
需要仅连接下载器、不初始化目标调试口时使用 CLI `power-read`。

## 返回值

```json
{"voltage_mv":3300,"current_ma":12.345,"power_mw":40.739,"current_supported":true,"sample_age_ms":10}
```

上述是示例值。V3 的 `current_supported=false`，`current_ma` 和 `power_mw` 为 `null`。
采样尚未完成滤波预热或 ADC 读取失败时，相应测量为 `null`；不能解释成零。
实测 `0` 是有效值。旧固件、响应损坏或超过 1000 ms 的陈旧快照会报错，不伪造读数。

测量来自后台周期采样、10 点均值滤波；V4 功率是滤波电压与电流的乘积，
不是高频瞬时功率、累计能量或精密功率分析仪测量。电压直接使用 ADC 换算值，
不套用屏幕显示的固定偏移。`sample_age_ms` 是发布快照至查询时的时差。

同一命令口不能同时用于 RTT/SystemView/VOFA/SuperWatch 流和该查询。
先停止采集并按正常流程恢复空闲命令会话，不发送原始命令绕过占用检查。
