import os
import re
import sys
import datetime
from collections import defaultdict


class StressLogAnalyzer:
    def __init__(self, log_path):
        self.log_path = log_path
        self.data = {
            "start_time": None,
            "end_time": None,
            "duration": "N/A",
            "target_pkg": "Unknown",
            "total_actions": 0,
            "mem_records": [],
            "cpu_records": [],
            "temp_records": [],
            "net_records": [],
            "net_failures": 0,
            "errors": defaultdict(int),
            "warnings": 0,
            "snapshots": [],
            "error_timeline": [],
        }

    def parse(self):
        if not os.path.exists(self.log_path):
            print(f"❌ 错误: 找不到日志文件 {self.log_path}")
            return False

        print(f"正在分析日志: {self.log_path} ...")

        # =========================================================
        # 1. 定义正则 (清理了重复定义，只保留核心)
        # =========================================================

        # 主正则: 提取开头的标准时间 [2025-12-24 10:00:00]
        re_master = re.compile(r"^\[(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})\]\s+(.+)")

        # 子正则: 用于匹配具体内容 (Content)
        re_status = re.compile(r"\[STATUS\]\s+Mem:(?P<mem>\d+)MB(?:.*CPU:(?P<cpu>[\d\.]+)%)?(?:.*Temp:(?P<temp>\d+)C)?")
        re_net = re.compile(r"\[NETWORK\]\s+(?:\|\s+)?Ping:(?P<val>.+)")  # 兼容有没有 | 的情况
        re_action = re.compile(r"\[.+?\]\[#\d+\]\s+(.+)")
        re_target_start = re.compile(r"=== 压测开始: 目标 (.+) ===")

        re_header_target = re.compile(r"(?:Target:|目标)\s+([a-zA-Z0-9\._]+)")
        re_header_start = re.compile(r"Log-Term Stress Test Start:\s+(.+)")

        with open(self.log_path, 'r', encoding='utf-8', errors='ignore') as f:
            for line in f:
                line = line.strip()
                if not line: continue



                # --- 第一步：主正则拆解 ---
                m_master = re_master.match(line)

                # 如果这行连时间头都没有（比如Crash堆栈），直接跳过
                if m_master:
                    # >>> 场景 A: 标准日志行 (有时间戳) <<<
                    time_str = m_master.group(1)
                    content = m_master.group(2)

                    # 顺便更新一下开始时间
                    if self.data["start_time"] is None:
                        self.data["start_time"] = time_str
                else:
                    # >>> 场景 B: 可能是 Header (无时间戳) <<<
                    # 比如: "Target: com.example.app"
                    content = line
                    time_str = self.data["start_time"] or "Unknown"

                time_str = m_master.group(1)
                content = m_master.group(2)  # 去掉时间后的纯内容

                # --- 第二步：分类解析 ---

                if "Target:" in content or "目标" in content:
                    m_t = re_header_target.search(content)
                    if m_t:
                        self.data["target_pkg"] = m_t.group(1)
                        # 如果还没找到开始时间，但这行有时间戳，就用这行的时间
                        if self.data["start_time"] is None and m_master:
                            self.data["start_time"] = time_str

                # 1. 状态监控 (STATUS)
                if "[STATUS]" in content:
                    m = re_status.search(content)
                    if m:
                        # 内存
                        self.data["mem_records"].append((time_str, int(m.group("mem"))))
                        # CPU
                        if m.group("cpu"):
                            try:
                                self.data["cpu_records"].append((time_str, float(m.group("cpu"))))
                            except:
                                pass
                        # 温度
                        if m.group("temp"):
                            try:
                                self.data["temp_records"].append((time_str, int(m.group("temp"))))
                            except:
                                pass
                    continue

                # 2. 网络监控 (NETWORK)
                if "[NETWORK]" in content:
                    m = re_net.search(content)
                    if m:
                        val_str = m.group("val").strip()
                        if "TIMEOUT" in val_str or "FAIL" in val_str:
                            self.data["net_failures"] += 1
                            self.data["net_records"].append((time_str, 1000))
                        else:
                            try:
                                latency = float(re.sub(r"[^0-9\.]", "", val_str))
                                self.data["net_records"].append((time_str, latency))
                            except:
                                pass
                    continue

                # 3. 动作记录 (包含 [#数字])
                if "[#" in content:
                    m = re_action.search(content)
                    if m:
                        self.data["total_actions"] += 1
                    continue

                # 4. 严重错误 (CRITICAL)
                if "CRITICAL_" in content:
                    err_type = "SYSTEM_ERROR"
                    if "OOM" in content:
                        err_type = "OOM"
                    elif "MEDIA" in content:
                        err_type = "MEDIA"
                    elif "AUDIO" in content:
                        err_type = "AUDIO"
                    elif "KERNEL" in content:
                        err_type = "KERNEL"

                    self.data["errors"][err_type] += 1
                    self.data["error_timeline"].append({
                        "time": time_str,
                        "type": err_type,
                        "msg": content
                    })
                    continue

                # 5. 其他信息
                if "[WARN]" in content:
                    self.data["warnings"] += 1
                elif "[SNAPSHOT]" in content:
                    snap_name = content.split(" ")[-1]
                    self.data["snapshots"].append(snap_name)
                elif "=== 压测开始" in content:
                    m = re_target_start.search(content)
                    if m:
                        self.data["target_pkg"] = m.group(1)
                        self.data["start_time"] = time_str

        self._calc_duration()
        return True

    def _calc_duration(self):
        # 简单计算时长
        pass

    def print_summary(self):
        d = self.data
        print("\n" + "=" * 40)
        print("📊 [Dognoise] 压测报告摘要")
        print("=" * 40)
        print(f"目标应用 : {d['target_pkg']}")
        print(f"执行动作 : {d['total_actions']} Steps")
        print("-" * 40)

        mem_vals = [m[1] for m in d['mem_records']]
        if mem_vals:
            avg_mem = sum(mem_vals) / len(mem_vals)
            max_mem = max(mem_vals)
            print(f"内存峰值 : {max_mem} MB")
            print(f"内存均值 : {int(avg_mem)} MB")
        else:
            print("内存数据 : 无记录")

        if d['cpu_records']:
            avg_cpu = sum([x[1] for x in d['cpu_records']]) / len(d['cpu_records'])
            print(f"CPU 均值  : {avg_cpu:.1f}%")

        if d['temp_records']:
            max_temp = max([x[1] for x in d['temp_records']])
            print(f"最高温度  : {max_temp}°C")

        print("-" * 40)
        print(f"警告 (Warn)  : {d['warnings']}")
        print(f"错误 (Error) : {sum(d['errors'].values())}")

        if d['errors']:
            for k, v in d['errors'].items():
                print(f"   - {k:<12} : {v}")

        print("=" * 40)
        print(f"截图文件数 : {len(d['snapshots'])}")

    def generate_html(self, output_file="stress_report.html"):
        d = self.data

        # 准备图表数据
        times = [f"'{x[0]}'" for x in d['mem_records']]
        mems = [str(x[1]) for x in d['mem_records']]

        cpu_times = [f"'{x[0]}'" for x in d['cpu_records']]
        cpu_vals = [str(x[1]) for x in d['cpu_records']]

        temp_times = [f"'{x[0]}'" for x in d['temp_records']]
        temp_vals = [str(x[1]) for x in d['temp_records']]

        net_times = [f"'{x[0]}'" for x in d['net_records']]
        net_vals = [str(x[1]) for x in d['net_records']]

        html_content = f"""
<!DOCTYPE html>
<html>
<head>
    <meta charset="utf-8">
    <title>Dognoise Stress Report</title>
    <script src="https://cdn.jsdelivr.net/npm/echarts@5.4.3/dist/echarts.min.js"></script>
    <style>
        body {{ font-family: 'Segoe UI', sans-serif; background: #f4f6f9; margin: 0; padding: 20px; }}
        .container {{ max-width: 1200px; margin: 0 auto; background: #fff; padding: 30px; border-radius: 8px; box-shadow: 0 2px 10px rgba(0,0,0,0.05); }}
        h1 {{ color: #2c3e50; border-bottom: 2px solid #3498db; padding-bottom: 15px; }}
        h3 {{ color: #34495e; margin-top: 30px; border-left: 4px solid #3498db; padding-left: 10px; }}
        .card-grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); gap: 20px; margin-bottom: 30px; }}
        .card {{ background: #f8f9fa; padding: 20px; border-radius: 8px; text-align: center; border: 1px solid #e9ecef; }}
        .card h4 {{ margin: 0; color: #7f8c8d; font-size: 14px; text-transform: uppercase; }}
        .card p {{ margin: 10px 0 0; font-size: 28px; font-weight: bold; color: #2c3e50; }}
        .chart-box {{ height: 400px; width: 100%; margin-bottom: 20px; }}
        .danger {{ color: #e74c3c !important; }}
    </style>
</head>
<body>
    <div class="container">
        <h1>🐕 Dognoise 压测报告</h1>
        <p>Target: <strong>{d['target_pkg']}</strong> | Generated: {datetime.datetime.now().strftime('%Y-%m-%d %H:%M')}</p>

        <div class="card-grid">
            <div class="card"><h4>执行动作 (Steps)</h4><p>{d['total_actions']}</p></div>
            <div class="card"><h4>内存峰值 (MB)</h4><p>{max([m[1] for m in d['mem_records']]) if d['mem_records'] else 0}</p></div>
            <div class="card"><h4>网络超时 (次)</h4><p class="{'danger' if d['net_failures'] > 0 else ''}">{d['net_failures']}</p></div>
            <div class="card"><h4>严重错误 (个)</h4><p class="{'danger' if sum(d['errors'].values()) > 0 else ''}">{sum(d['errors'].values())}</p></div>
        </div>

        <h3>📈 全能监控趋势 (CPU / Temp / Mem)</h3>
        <div id="comboChart" class="chart-box"></div>

        <h3>📡 网络延迟 (Ping)</h3>
        <div id="netChart" class="chart-box"></div>

        <h3>🚫 异常统计</h3>
        <div id="pieChart" style="height: 350px;"></div>

    </div>

    <script type="text/javascript">
        var comboChart = echarts.init(document.getElementById('comboChart'));
        var comboOption = {{
            tooltip: {{ trigger: 'axis', axisPointer: {{ type: 'cross' }} }},
            legend: {{ data: ['Memory (MB)', 'CPU (%)', 'Temp (°C)'] }},
            grid: {{ right: '20%' }},
            xAxis: [{{ type: 'category', data: [{",".join(times)}] }}],
            yAxis: [
                {{ type: 'value', name: 'Memory', position: 'left', axisLine: {{ show: true, lineStyle: {{ color: '#5470C6' }} }} }},
                {{ type: 'value', name: 'CPU', position: 'right', axisLine: {{ show: true, lineStyle: {{ color: '#91CC75' }} }} }},
                {{ type: 'value', name: 'Temp', position: 'right', offset: 80, axisLine: {{ show: true, lineStyle: {{ color: '#EE6666' }} }} }}
            ],
            series: [
                {{ name: 'Memory (MB)', type: 'line', yAxisIndex: 0, data: [{",".join(mems)}], smooth: true, areaStyle: {{ opacity: 0.1 }} }},
                {{ name: 'CPU (%)', type: 'line', yAxisIndex: 1, data: [{",".join(cpu_vals)}], smooth: true }},
                {{ name: 'Temp (°C)', type: 'line', yAxisIndex: 2, data: [{",".join(temp_vals)}], smooth: true, itemStyle: {{ color: '#EE6666' }} }}
            ]
        }};
        comboChart.setOption(comboOption);

        var netChart = echarts.init(document.getElementById('netChart'));
        var netOption = {{
            tooltip: {{ trigger: 'axis' }},
            xAxis: {{ type: 'category', data: [{",".join(net_times)}] }},
            yAxis: {{ type: 'value', name: 'ms' }},
            visualMap: {{
                show: false,
                pieces: [ {{gt: 0, lte: 200, color: '#2ecc71'}}, {{gt: 200, color: '#e74c3c'}} ]
            }},
            series: [{{ type: 'line', data: [{",".join(net_vals)}], markLine: {{ data: [ {{ yAxis: 1000, name: 'Timeout' }} ] }} }}]
        }};
        netChart.setOption(netOption);

        var pieChart = echarts.init(document.getElementById('pieChart'));
        var pieOption = {{
            tooltip: {{ trigger: 'item' }},
            series: [{{
                type: 'pie',
                radius: '60%',
                data: [
                    {",".join([f"{{value: {v}, name: '{k}'}}" for k, v in d['errors'].items()])}
                ]
            }}]
        }};
        pieChart.setOption(pieOption);

        window.onresize = function() {{ comboChart.resize(); netChart.resize(); pieChart.resize(); }};
    </script>
</body>
</html>
        """

        with open(output_file, "w", encoding="utf-8") as f:
            f.write(html_content)
        print(f"✅ HTML 报告已生成: {output_file}")


if __name__ == "__main__":
    possible_paths = [os.path.join("dist_stress", "event.log"), "event.log"]
    log_file = None
    for p in possible_paths:
        if os.path.exists(p):
            log_file = p
            break
    if len(sys.argv) > 1:
        log_file = sys.argv[1]

    if not log_file:
        print("未找到 event.log。请将脚本放在日志同级目录，或使用: python analyze_log.py <path_to_log>")
    else:
        analyzer = StressLogAnalyzer(log_file)
        if analyzer.parse():
            analyzer.print_summary()
            analyzer.generate_html()