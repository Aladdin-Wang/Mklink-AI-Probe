"""
SEGGER SystemView 事件分析器。

对解码出的事件列表（SystemViewParser 产出）做 RTOS 运行态分析，输出结构化报告：
  * 每任务 CPU 占用 / 切换次数 / 平均&最大运行片
  * ISR 次数 / 占用 / 最大 ISR 时长（ISR 延迟线索）
  * 空闲率、上下文切换频率
  * 异常标记（CPU 饥饿、切换过频、ISR 过重/过长、接近满载等）

分析方法论参考 SEGGER SystemView User Guide (UM08027)：
  - 每任务/ISR 耗时统计
  - 优先级反转：低优任务持资源阻塞高优任务（时间轴模式）
  - ISR 延迟：中断触发到对应任务恢复的间隔
  - 任务调度：上下文切换、抢占、空闲段

纯函数，无设备依赖——可对实时采集或离线 dump 的事件做分析。供 MCP 工具 /
CLI / AI Agent（skill）调用。
"""

from __future__ import annotations

from typing import Any


def _t(e: dict) -> float:
    """事件的绝对时间，优先 µs（已按 CPUFreq 换算），否则 ticks。"""
    if isinstance(e.get("t_us"), (int, float)):
        return float(e["t_us"])
    return float(e.get("t_ticks") or 0)


def analyze_events(events: list[dict]) -> dict:
    """分析 SystemView 事件列表，返回 RTOS 运行态报告 dict。

    Args:
        events: SystemViewParser.feed() 产出的事件字典列表。

    Returns:
        {
          "summary": {observed_us, switch_count, switches_per_sec, idle_pct, ...},
          "tasks": [{id, name, run_us, cpu_pct, switches, avg_slice_us, max_slice_us}],
          "isr": {count, total_us, cpu_pct, max_duration_us},
          "anomalies": [{kind, severity, detail}],
        }
    """
    if not events:
        return {"summary": {"error": "无事件"}, "tasks": [], "isr": {}, "anomalies": [
            {"kind": "no_data", "severity": "warn", "detail": "未采集到 SystemView 事件"}
        ]}

    all_events = events
    overflow_events = [
        (index, event)
        for index, event in enumerate(all_events)
        if event.get("kind") == "overflow"
    ]
    if overflow_events:
        # An overflow timestamp includes the interval since the target last
        # enqueued a packet. On initial attachment that interval predates the
        # capture, so analyze only the latest continuous trace segment.
        events = all_events[overflow_events[-1][0] + 1:]

    times = [_t(e) for e in events]
    first = min(times) if times else 0.0
    last = max(times) if times else 0.0
    observed = max(last - first, 1.0)
    unit_source = events[-1] if events else all_events[-1]
    unit = "us" if isinstance(unit_source.get("t_us"), (int, float)) else "ticks"

    # ---- 任务执行区间（task_start_exec / task_stop_exec）----
    pending: dict[int, float] = {}
    task_run: dict[int, float] = {}
    task_switches: dict[int, int] = {}
    task_names: dict[int, str] = {}
    task_slices: dict[int, list[float]] = {}
    switch_count = 0

    # ---- ISR ----
    isr_enter_t: dict[int, float] = {}   # isr_id -> enter time（嵌套按 nest 计）
    isr_total = 0.0
    isr_count = 0
    isr_max = 0.0
    # isr_enter 可能无 id（SEGGER ISR_ENTER 带 interrupt id）；用栈处理嵌套
    isr_stack: list[float] = []

    for e in events:
        k = e.get("kind")
        t = _t(e)
        if k == "task_start_exec":
            tid = e.get("task_id")
            if isinstance(tid, int):
                pending[tid] = t
                task_switches[tid] = task_switches.get(tid, 0) + 1
                switch_count += 1
                if e.get("task_name"):
                    task_names[tid] = e["task_name"]
        elif k == "task_stop_exec":
            tid = e.get("task_id")
            if isinstance(tid, int) and tid in pending:
                dur = max(t - pending[tid], 0.0)
                task_run[tid] = task_run.get(tid, 0.0) + dur
                task_slices.setdefault(tid, []).append(dur)
                del pending[tid]
        elif k == "task_info":
            tid = e.get("task_id")
            if isinstance(tid, int) and e.get("name"):
                task_names[tid] = e["name"]
        elif k == "isr_enter":
            isr_stack.append(t)
        elif k == "isr_exit" or k == "isr_to_scheduler":
            if isr_stack:
                enter_t = isr_stack.pop()
                dur = max(t - enter_t, 0.0)
                isr_total += dur
                isr_count += 1
                isr_max = max(isr_max, dur)
        # 注：空闲率由空闲线程（tidle0）的 CPU% 推导，不累计 OnIdle 事件 delta

    # ---- 任务报告 ----
    # CPU% 归一化到「总任务运行时间」（含空闲线程）→ 各任务加总 100%，与空闲率
    # 自洽。observed=last-first 会被缓冲回压/翻卷的不连续 inflate，直接相除会让
    # 所有 CPU% 偏低且对不上空闲率，故改用 total_run 做分母。
    total_run = sum(task_run.values()) or 1.0
    tasks = []
    for tid, run in sorted(task_run.items(), key=lambda kv: kv[1], reverse=True):
        slices = task_slices.get(tid, [])
        tasks.append({
            "id": tid,
            "id_hex": f"0x{tid:X}",
            "name": task_names.get(tid, ""),
            "run_us": round(run, 1),
            "cpu_pct": round(run / total_run * 100, 2),
            "switches": task_switches.get(tid, 0),
            "avg_slice_us": round(sum(slices) / len(slices), 1) if slices else 0,
            "max_slice_us": round(max(slices), 1) if slices else 0,
        })

    # 空闲率 = 空闲线程的 CPU%（与任务表一致）。识别：名字 tidle*/idle*
    idle_tid = next((tid for tid, nm in task_names.items()
                     if nm and nm.lower().startswith(("tidle", "idle"))), None)
    idle_pct = round(task_run.get(idle_tid, 0.0) / total_run * 100, 2) if idle_tid is not None else 0.0

    # ---- 异常检测 ----
    anomalies: list[dict] = []
    if overflow_events:
        target_drop_count = overflow_events[-1][1].get("drop_count")
        anomalies.append({
            "kind": "trace_overflow",
            "severity": "high",
            "detail": (
                "SystemView target buffer overflowed; CPU/ISR analysis uses "
                "only the continuous segment after the latest overflow "
                f"(target cumulative drop count: {target_drop_count})."
            ),
        })
    switches_per_sec = switch_count / (observed / 1_000_000.0) if unit == "us" and observed else 0.0
    # ISR intervals are wall-time intervals. Incomplete task slices are not a
    # valid denominator when capture starts mid-task.
    isr_cpu = round(isr_total / observed * 100, 2) if observed else 0.0

    if unit == "us":
        # CPU 饥饿：单任务 > 90%
        for tk in tasks:
            if tk["cpu_pct"] > 90:
                anomalies.append({
                    "kind": "cpu_starvation", "severity": "high",
                    "detail": f"任务 {tk['name'] or tk['id_hex']} 占用 {tk['cpu_pct']}% CPU——可能独占 CPU，其他任务被饿死",
                })
        # 切换过频：> 2000 次/秒
        if switches_per_sec > 2000:
            anomalies.append({
                "kind": "excessive_switching", "severity": "warn",
                "detail": f"上下文切换 {switches_per_sec:.0f} 次/秒——过频，调度开销大",
            })
        # ISR 过重
        if isr_cpu > 30:
            anomalies.append({
                "kind": "isr_heavy", "severity": "high",
                "detail": f"ISR 占用 {isr_cpu}% CPU——中断处理过重，挤压任务",
            })
        # 长 ISR（延迟线索）
        if isr_max > 100:
            anomalies.append({
                "kind": "long_isr", "severity": "warn",
                "detail": f"最长 ISR 达 {isr_max:.0f}µs——可能导致中断延迟/丢中断",
            })
        # 接近满载
        non_idle = 100.0 - idle_pct
        if non_idle > 95:
            anomalies.append({
                "kind": "near_capacity", "severity": "warn",
                "detail": f"非空闲 {non_idle:.1f}%——系统接近满载，余量不足",
            })
        # 优先级反转线索：高优任务切换少但存在、低优任务长运行（粗略启发式）
        # （精确定位需结合内核对象事件，当前精简适配器未采集 sem/mutex——留作增强）

    summary = {
        "unit": unit,
        "observed_us": round(observed, 1) if unit == "us" else None,
        "observed_ticks": round(observed, 1) if unit == "ticks" else None,
        "event_count": len(all_events),
        "analyzed_event_count": len(events),
        "target_overflow_events": len(overflow_events),
        "target_drop_count": (
            overflow_events[-1][1].get("drop_count")
            if overflow_events else 0
        ),
        "switch_count": switch_count,
        "switches_per_sec": round(switches_per_sec, 1) if unit == "us" else None,
        "task_count": len(tasks),
        # 空闲率/ISR 占用是 total_run 的比率，与单位无关，始终给出
        "idle_pct": idle_pct,
        "isr_cpu_pct": isr_cpu,
    }
    isr_report = {
        "count": isr_count,
        "total_us": round(isr_total, 1),
        "cpu_pct": isr_cpu if unit == "us" else None,
        "max_duration_us": round(isr_max, 1),
    }
    return {"summary": summary, "tasks": tasks, "isr": isr_report, "anomalies": anomalies}


def format_report(report: dict) -> str:
    """把分析报告格式化成人类可读的中文文本（CLI 输出）。"""
    s = report.get("summary", {})
    if s.get("error"):
        return f"[FAIL] {s['error']}\n{report['anomalies'][0]['detail']}"
    unit = s.get("unit", "us")
    obs = s.get("observed_us") or s.get("observed_ticks")
    lines = ["=" * 60, " SystemView RTOS 运行态分析", "=" * 60]
    lines.append(f"观测时长 : {obs:,.1f} {unit}  | 事件 {s.get('event_count')} | 任务 {s.get('task_count')}")
    sps = s.get("switches_per_sec")
    lines.append(f"切换次数 : {s.get('switch_count')}" + (f"  ({sps} 次/秒)" if sps else "（无 CPUFreq，未换算秒率）"))
    lines.append(f"空闲率   : {s.get('idle_pct')}%    | ISR 占用: {s.get('isr_cpu_pct')}%  (相对执行时间；ISR 与任务有重叠)")

    lines.append("\n--- 任务 CPU 占用 ---")
    if report["tasks"]:
        usuf = "µs" if unit == "us" else "tk"
        lines.append(f"{'任务':<16}{'CPU%':>8}{('运行'+usuf):>14}{'切换':>8}{('均片'+usuf):>12}{('最长'+usuf):>12}")
        for t in report["tasks"]:
            name = (t["name"] or t["id_hex"])[:14]
            lines.append(
                f"{name:<16}{t['cpu_pct']:>8}{t['run_us']:>14}{t['switches']:>8}"
                f"{t['avg_slice_us']:>12}{t['max_slice_us']:>12}"
            )
    else:
        lines.append("（无任务执行区间——可能未抓到 task_start_exec/stop_exec 事件）")

    isr = report.get("isr", {})
    if isr.get("count"):
        usuf2 = "µs" if unit == "us" else "tk"
        lines.append("\n--- 中断 (ISR) ---")
        cpu_txt = f"{isr.get('cpu_pct')}%" if isr.get("cpu_pct") is not None else "N/A(无CPUFreq)"
        lines.append(f"次数 {isr['count']}  | 总时长 {isr['total_us']}{usuf2}  | "
                     f"占用 {cpu_txt}  | 最长 {isr['max_duration_us']}{usuf2}")

    anoms = report.get("anomalies", [])
    if anoms:
        lines.append("\n--- 异常 / 风险 ---")
        for a in anoms:
            tag = "⚠ " if a["severity"] == "warn" else "⛔ "
            lines.append(f"{tag}[{a['kind']}] {a['detail']}")
    else:
        lines.append("\n--- 异常 / 风险 --- 无")
    return "\n".join(lines)
