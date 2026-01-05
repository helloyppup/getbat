import os
import sys
import time
import pandas as pd

# ===========================
#  全局默认配置
# ===========================
DEFAULT_CONFIG = {
    "target_pkg": "cn.net.cloudthink.smartmirror",
    "duration_sec": 86400 * 3,
    "start_activity": ".MainActivity",
    "ping_target": "www.baidu.com",
    "log_whitelist": "MainActivity",
    "device_name": "",
    # 建议把 Webhook 放在 Excel 配置里，这里先保留默认值
    "feishu_webhook": "https://open.feishu.cn/open-apis/bot/v2/hook/e162c2e1-d3b6-4211-9a23-58ff22c76986"
}


class StressCompiler:
    def __init__(self, config):
        self.cfg = config
        # 处理 uri 格式
        if "/" in str(config['start_activity']):
            self.start_uri = config['start_activity']
        else:
            self.start_uri = f"{config['target_pkg']}/{config['start_activity']}"

    def _format_block(self, text, indent_level=1):
        """
        核心工具：给生成的代码块加上缩进
        """
        indent = "    " * indent_level
        lines = text.strip().split('\n')
        # 过滤空行并添加缩进
        return '\n'.join([f"{indent}{line}" for line in lines])

    def compile_sequence(self, plan_list):
        """
        只生成任务部分的逻辑，然后注入模板
        """
        # === 1. 生成任务指令流 (The Meat) ===
        task_body = ""

        for plan in plan_list:
            sheet_name = plan['name']
            loop_count = plan['loop']
            tasks = plan['tasks']

            # 每个 Sheet 是一个大循环
            task_body += f"\n# >>> Sheet: {sheet_name} (Loop: {loop_count}) <<<\n"
            task_body += f"sheet_count=0\n"
            task_body += f"while [ $sheet_count -lt {loop_count} ]; do\n"
            task_body += f"    sheet_count=$((sheet_count + 1))\n"
            task_body += f"    # log_info \"[LOOP] {sheet_name} - 第 $sheet_count 次循环\"\n"


            # 遍历 Excel 里的每一行 Task
            for task in tasks:
                if pd.isna(task.get('action')): continue
                action = str(task.get('action')).upper().strip()
                p1 = task.get('p1')
                p2 = task.get('p2')
                p3 = task.get('p3')
                p4 = task.get('p4')

                # 每个动作前，都插入一次快速检查 (哨兵)
                task_body += "    check_health_fast\n"

                # 动作翻译
                if action == "CLICK":
                    try:
                        x, y = int(float(p1)), int(float(p2))
                        task_body += f"    log_info \"[STEP] 点击坐标: {x}, {y}\"\n"
                        task_body += f"    input tap {x} {y}\n"
                    except:
                        print(f"⚠️ 忽略无效坐标: {p1},{p2}")

                elif action == "SWIPE":
                    try:
                        x1, y1, x2, y2 = int(float(p1)), int(float(p2)), int(float(p3)), int(float(p4))
                        task_body += f"    log_info \"[STEP] 滑动: {x1},{y1} -> {x2},{y2}\"\n"
                        task_body += f"    input swipe {x1} {y1} {x2} {y2} 300\n"
                    except:
                        pass


                elif action == "wait" or action == "WAIT":
                    # 默认等待 1 秒
                    wait_t = p1 if pd.notna(p1) else 1
                    task_body += f"    log_info \"[STEP] 等待: {wait_t} 秒\"\n"
                    task_body += f"    sleep {wait_t}\n"

                elif action == "KEY":
                    task_body += f"    log_info \"[STEP] 按键: {p1}\"\n"
                    task_body += f"    input keyevent {p1}\n"


                elif action == "TEXT":
                    raw_txt = str(p1)
                    # 简单的特殊字符处理
                    txt = raw_txt.replace(" ", "%s").replace("'", "").replace('"', '')
                    task_body += f"    log_info \"[STEP] 输入文本\"\n"
                    task_body += f"    input text '{txt}'\n"

                elif action == "STOP":
                    task_body += f"    log_info \"[STEP] 强制停止应用\"\n"
                    task_body += f"    am force-stop {self.cfg['target_pkg']}\n"

                elif action == "START":
                    task_body += f"    log_info \"[STEP] 启动应用\"\n"
                    task_body += f"    am start -n {self.start_uri}\n"

                elif action == "SHELL":
                    clean_cmd = str(p1).replace('"', '\\"')
                    task_body += f"    log_info \"[STEP] 执行Shell: {clean_cmd}\"\n"
                    task_body += f"    {p1}\n"

            task_body += "done\n"  # 结束 Sheet 的循环

        # === 2. 读取模板文件 ===
        # 假设 template.sh 就在当前脚本旁边
        current_dir = os.path.dirname(os.path.abspath(__file__))
        template_path = os.path.join(current_dir, f"shell/stress_template.sh")

        if not os.path.exists(template_path):
            raise FileNotFoundError(
                f"找不到模板文件: {template_path}\n请确保 stress_template.sh 和 python 脚本在同一目录！")

        with open(template_path, "r", encoding="utf-8") as f:
            template_content = f.read()

        # === 3. 注入填空 (核心魔法) ===

        # 先处理 task_body 的缩进 (因为 {{TASK_SEQUENCE_HERE}} 在 while true 里面，所以是 1 级缩进)
        formatted_tasks = self._format_block(task_body, indent_level=1)

        final_script = template_content \
            .replace("{{TARGET_PKG}}", str(self.cfg['target_pkg'])) \
            .replace("{{START_URI}}", str(self.start_uri)) \
            .replace("{{DURATION_SEC}}", str(self.cfg['duration_sec'])) \
            .replace("{{PING_TARGET}}", str(self.cfg['ping_target'])) \
            .replace("{{LOG_WHITELIST}}", str(self.cfg['log_whitelist'])) \
            .replace("{{DEVICE_NAME}}", str(self.cfg['device_name'])) \
            .replace("{{FEISHU_WEBHOOK}}", str(self.cfg['feishu_webhook'])) \
            .replace("# {{TASK_SEQUENCE_HERE}}", formatted_tasks)

        return final_script


# ===========================
#  Excel 解析逻辑 (基本保持不变)
# ===========================
def load_project_config(excel_path):
    config = DEFAULT_CONFIG.copy()
    sequence_plan = []

    try:
        # 读取配置 Key-Value
        df_kv = pd.read_excel(excel_path, sheet_name='Config', usecols=[0, 1], header=None)
        # 简单清洗数据
        cfg_dict = dict(zip(df_kv.iloc[:, 0], df_kv.iloc[:, 1]))

        # 映射 Excel 里的中文 Key 到 Config Key
        key_map = {
            "target_pkg": "target_pkg",
            "start_activity": "start_activity",
            "ping_target": "ping_target",
            "log_whitelist": "log_whitelist",
            "device_name": "device_name",
            "飞书Webhook": "feishu_webhook"  # 支持在 Excel 里配 Webhook
        }

        for k, v in cfg_dict.items():
            if pd.isna(v): continue
            # 尝试直接匹配或通过 map 匹配
            if str(k) in config:
                config[str(k)] = str(v).strip()
            elif str(k) in key_map:
                config[key_map[str(k)]] = str(v).strip()

        # 时长解析
        if 'duration_value' in cfg_dict and pd.notna(cfg_dict['duration_value']):
            try:
                val = float(cfg_dict['duration_value'])
                unit = str(cfg_dict.get('duration_unit', 'sec')).lower()
                if 'day' in unit or '天' in unit:
                    config['duration_sec'] = int(val * 86400)
                elif 'hour' in unit or '时' in unit:
                    config['duration_sec'] = int(val * 3600)
                elif 'min' in unit or '分' in unit:
                    config['duration_sec'] = int(val * 60)
                else:
                    config['duration_sec'] = int(val)
            except ValueError:
                print("时长配置格式错误，使用默认值")

        # 解析执行计划 (Sheet Loop)
        print("解析 Excel 任务计划...")
        df_full = pd.read_excel(excel_path, sheet_name='Config')
        seq_col = next((c for c in df_full.columns if "执行顺序" in str(c) or "Sheet" in str(c)), None)
        loop_col = next((c for c in df_full.columns if "本轮循环" in str(c) or "Loop" in str(c)), None)

        if seq_col:
            plan_df = df_full[[seq_col, loop_col]].dropna(subset=[seq_col])
            for _, row in plan_df.iterrows():
                s_name = str(row[seq_col]).strip()
                if s_name in ["执行顺序", "Sheet Name", "nan"]: continue
                l_count = int(row[loop_col]) if pd.notna(row[loop_col]) else 1
                sequence_plan.append({"name": s_name, "loop": l_count})

    except Exception as e:
        print(f"配置读取失败: {e}")
        sys.exit(1)

    return config, sequence_plan


def parse_tasks_from_sheet(excel_path, sheet_name):
    try:
        df = pd.read_excel(excel_path, sheet_name=sheet_name)
    except:
        return []

    tasks = []
    # 模糊匹配列名
    cols = df.columns

    def find_col(keywords):
        for c in cols:
            if any(k in str(c) for k in keywords): return c
        return None

    col_action = find_col(['指令', 'Action'])
    col_p1 = find_col(['参数1', 'P1'])
    col_p2 = find_col(['参数2', 'P2'])
    col_p3 = find_col(['参数3', 'P3'])
    col_p4 = find_col(['参数4', 'P4'])

    if not col_action: return []

    for _, row in df.iterrows():
        act = row.get(col_action)
        if pd.isna(act): continue
        tasks.append({
            "action": act,
            "p1": row.get(col_p1), "p2": row.get(col_p2),
            "p3": row.get(col_p3), "p4": row.get(col_p4)
        })
    return tasks


# ===========================
#  主程序入口
# ===========================
if __name__ == "__main__":
    current_dir = os.path.dirname(os.path.abspath(__file__))
    EXCEL_FILE = os.path.join(current_dir, "test plan.xlsx")  # 你的 Excel 文件名
    OUTPUT_DIR = os.path.join(current_dir, "dist_stress")

    if not os.path.exists(EXCEL_FILE):
        print(f"找不到配置文件: {EXCEL_FILE}")
        sys.exit(1)

    # 1. 加载配置
    final_config, seq_plan = load_project_config(EXCEL_FILE)
    print(f"目标应用: {final_config['target_pkg']}")
    print(f"设备名称: {final_config['device_name'] or '自动获取'}")

    # 2. 加载所有 Sheet 的任务
    full_execution_plan = []
    for stage in seq_plan:
        s_name = stage['name']
        s_tasks = parse_tasks_from_sheet(EXCEL_FILE, s_name)
        if s_tasks:
            full_execution_plan.append({"name": s_name, "loop": stage['loop'], "tasks": s_tasks})
            print(f"   -> Sheet [{s_name}]: {len(s_tasks)} 动作 / {stage['loop']} 循环")

    # 3. 编译脚本 (核心步骤)
    compiler = StressCompiler(final_config)
    try:
        shell_code = compiler.compile_sequence(full_execution_plan)
    except FileNotFoundError as e:
        print(f"\n❌ 错误: {e}")
        sys.exit(1)

    # 4. 输出文件
    if not os.path.exists(OUTPUT_DIR):
        os.makedirs(OUTPUT_DIR)

    sh_path = os.path.join(OUTPUT_DIR, "stress_core.sh")
    with open(sh_path, "w", encoding="utf-8", newline='\n') as f:
        f.write(shell_code)

    # 5. 生成 BAT 启动器 (保持原样，方便你在 Windows 点)
    bat_content = f"""@echo off
title Dognoise Stress Launcher
color 0A
echo.
echo [Dognoise] Initializing...
adb wait-for-device
adb root
adb remount

echo.
echo [1/3] Cleaning old processes...
adb shell "pkill -f stress_core.sh"
adb shell "rm -f /data/local/tmp/dognoise.lock"
adb logcat -c
adb shell "rm -rf /sdcard/dognoise_stress/*"

echo.
echo [2/3] Pushing script...
adb push stress_core.sh /data/local/tmp/stress_core.sh
adb shell chmod 777 /data/local/tmp/stress_core.sh

echo.
echo [3/3] Starting stress test...
echo Log Path: /sdcard/dognoise_stress/event.log
echo ------------------------------------------
adb shell "nohup sh /data/local/tmp/stress_core.sh > /dev/null 2>&1 &"

echo.
echo Start Success! You can close this window.
pause
"""
    bat_path = os.path.join(OUTPUT_DIR, "一键开始压测.bat")
    with open(bat_path, "w", encoding="gbk") as f:
        f.write(bat_content)

    print(f"\n✅ 编译完成！")
    print(f"   输出目录: {OUTPUT_DIR}")
    print(f"   请运行 [一键开始压测.bat]")