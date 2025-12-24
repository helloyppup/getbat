import os
import sys
import time
import  hashlib

try:
    import pandas as pd
except ImportError:
    pd = None

# ===========================
#  全局默认配置
# ===========================
DEFAULT_CONFIG = {
    "target_pkg": "cn.net.cloudthink.smartmirror",
    "duration_sec": 86400 * 3,
    "start_activity": ".MainActivity",
    "ping_target": "www.baidu.com",
    "log_whitelist": ""
}


class StressCompiler:
    def __init__(self, target_pkg, duration=3600, start_uri=None,ping_target="www.baidu.com",log_whitelist=""):
        self.target_pkg = target_pkg
        self.duration = int(duration)
        self.ping_target = ping_target
        self.log_whitelist = log_whitelist
        if "/" in str(start_uri):
            self.start_uri = start_uri
        else:
            self.start_uri = f"{target_pkg}/{start_uri}"

    def compile_sequence(self, plan_list):

        FEISHU_WEBHOOK = "https://open.feishu.cn/open-apis/bot/v2/hook/e162c2e1-d3b6-4211-9a23-58ff22c76986"
        shell = f"""#!/system/bin/sh
        
        # Target: {self.target_pkg}
    
        MY_PID=$$
        LOCK_FILE="/data/local/tmp/dognoise.lock"
    
        # === 1. 定义日志路径 ===
        LOG_DIR="/sdcard/dognoise_stress"
        mkdir -p $LOG_DIR
        EVENT_LOG="$LOG_DIR/event.log"
        CRASH_LOG="$LOG_DIR/crash_stack.log"
        ANR_LOG="$LOG_DIR/anr_history.log"
        touch $EVENT_LOG $CRASH_LOG $ANR_LOG
    
        # === 2. 【关键】获取系统开机时长(秒)，不受日期跳变影响 ===
        function log_info() {{
            local msg=$1
            # 格式: [2025-12-24 12:00:00] msg
            echo "[$(date "+%Y-%m-%d %H:%M:%S")] $msg" >> $EVENT_LOG
        }}
        
        function get_uptime_sec() {{
            read up_val _ < /proc/uptime
            echo ${{up_val%%.*}}
        }}
        
        # === 飞书通知函数 ===
        function send_feishu() {{
            local title=$1
            local content=$2
            curl -k -g -X POST "{FEISHU_WEBHOOK}" \\
                 -H "Content-Type: application/json" \\
                 -d '{{
                     "msg_type": "text",
                     "content": {{
                         "text": "【压测通知】 '"$title"'\\n----------------\\n'"$content"'"
                     }}
                 }}' > /dev/null 2>&1
        }}
    
        # === 3. 【关键】遗言系统：脚本挂掉前自动记录 ===
        function leave_last_words() {{
            local reason=$1
            local now_up=$(get_uptime_sec)
            local total_run=$((now_up - start_uptime))
    
            echo "" >> $EVENT_LOG
            echo "========= [ 脚本停止报告 ] =========" >> $EVENT_LOG
            echo "时间: $(date)" >> $EVENT_LOG
            echo "原因: $reason" >> $EVENT_LOG
            local status_msg="脚本停止！\\n原因: $reason\\n运行时长: ${{total_run}}秒\\n设备: $(getprop ro.product.model)"
            send_feishu "🚨 压测异常结束" "$status_msg"
            echo "已运行: ${{total_run}} 秒 (目标: {self.duration} 秒)" >> $EVENT_LOG
            echo "==================================" >> $EVENT_LOG
    
            rm -f "$LOCK_FILE"
            # 杀掉后台抓log的进程
            [ ! -z "$LOGCAT_PID" ] && kill $LOGCAT_PID > /dev/null 2>&1
        }}
    
        # 只要脚本退出(EXIT)、被中断(INT)、被杀(TERM)，都会触发上面那个函数
        trap 'leave_last_words "正常退出或脚本崩溃(EXIT)"' EXIT
        trap 'leave_last_words "被手动停止(Ctrl+C)"' INT
        trap 'leave_last_words "被系统强杀(TERM/OOM)"' TERM
    
        # === 4. 初始化环境 ===
        echo $MY_PID > $LOCK_FILE
        svc power stayon true
        logcat -c
        # 后台抓 Crash
        nohup logcat -v time {self.log_whitelist} *:I -f $CRASH_LOG -r 10240 -n 50 &
        LOGCAT_PID=$!
    
        # 记录开始时的“秒表读数”
        start_uptime=$(get_uptime_sec)
        last_heartbeat_time=$(get_uptime_sec)  
    
        last_heavy_check_time=0
        last_heavy_check_time=0
        last_net_check_time=0
        sysui_pid=$(pidof com.android.systemui)
    
        echo "=== 压测开始: $(date) ===" > $EVENT_LOG
        send_feishu "🚀 压测已启动" "目标: {self.target_pkg}\\n计划时长: {self.duration}秒"
        echo "=== 模式: 抗时间跳变 + 遗言记录 ===" >> $EVENT_LOG
    
        # === 5. 辅助函数 ===
        function take_snapshot() {{
            local type_name=$1
            screencap -p "$LOG_DIR/${{type_name}}_$(date +%Y%m%d_%H%M%S).png"
            echo "    [SNAPSHOT] ${{type_name}}" >> $EVENT_LOG
        }}
    
        function check_network() {{
            local now_ts=$(get_uptime_sec)
            if [ $((now_ts - last_net_check_time)) -ge 60 ]; then
                # Android 的 ping 输出通常包含 time=12.3 ms
                local ping_res=$(ping -c 1 -W 2 {self.ping_target})
                
                if echo "$ping_res" | grep -q "time="; then
                    # 提取 time= 后面的数字
                    local t_val=$(echo "$ping_res" | grep -o "time=[0-9.]*" | cut -d= -f2)
                    # 写入标准格式: [NETWORK] 时间 | Ping:数值
                    echo "[NETWORK] $(date "+%Y-%m-%d %H:%M:%S") | Ping:${{t_val}}" >> $EVENT_LOG
                else
                    echo "[NETWORK] $(date "+%Y-%m-%d %H:%M:%S") | Ping:TIMEOUT" >> $EVENT_LOG
                fi
                last_net_check_time=$now_ts
            fi
        }}
    
        function perform_heavy_check() {{
            local now_ts=$(get_uptime_sec)
            
            # 致命系统日志抓取 (抓 Media/Audio/OOM 报错) ---
            # 检查过去 200 行日志
            # - lowmemorykiller: 内存
            # - MediaProvider: 媒体库崩坏 (句柄泄露)
            # - AudioSystem: 音频崩坏
            # - audit: 系统内核报警
            local fatal_log=$(logcat -d -t 200 | grep -E "lowmemorykiller|MediaProvider|AudioSystem|audit" | grep -v "permissive=1" | tail -n 3)
        
        if [ ! -z "$fatal_log" ]; then
            # 智能识别类型
            local err_type="UNKNOWN"
            if echo "$fatal_log" | grep -q "lowmemorykiller"; then err_type="OOM"; fi
            if echo "$fatal_log" | grep -q "MediaProvider"; then err_type="MEDIA"; fi
            if echo "$fatal_log" | grep -q "AudioSystem"; then err_type="AUDIO"; fi
            if echo "$fatal_log" | grep -q "audit"; then err_type="KERNEL"; fi
            
            # 记录文字日志 (使用双大括号转义)
            echo "!!! [$(date "+%Y-%m-%d %H:%M:%S")] [CRITICAL_${{err_type}}] 发现严重征兆" >> $EVENT_LOG
            echo "$fatal_log" >> $EVENT_LOG

            # 冷却机制: 构造变量名 (使用双大括号转义)
            local last_var_name="last_shot_time_${{err_type}}"
            
            # 读取上次时间
            local last_val=$(eval echo \$$last_var_name)
            if [ -z "$last_val" ]; then last_val=0; fi
            
            # 检查 10分钟 (600秒) 冷却
            if [ $((now_ts - last_val)) -ge 600 ]; then
                 # 格式化截图命名
                 take_snapshot "SYS_${{err_type}}"
                 
                 # 更新时间
                 eval "${{last_var_name}}=$now_ts"
                 echo "    [SNAPSHOT] 已截图 (类型: ${{err_type}})" >> $EVENT_LOG
            else
                 echo "    [COOLDOWN] 跳过截图 (该类型 ${{err_type}} 在10min内已截过)" >> $EVENT_LOG
            fi
        fi
        
        # --- 2. 检查 ANR ---
        if logcat -b events -d -t 100 | grep "am_anr" | grep -q "{self.target_pkg}"; then
             echo "!!! [ANR_DETECTED] !!!" >> $EVENT_LOG
             take_snapshot "ANR"
             am force-stop {self.target_pkg}
             sleep 2
             am start -n {self.start_uri}
             sleep 5
             return
        fi

        # --- 3. 全能监控 (内存/CPU/温度) ---
        local app_pid=$(pidof {self.target_pkg})
        if [ ! -z "$app_pid" ]; then
            # (1) 获取内存
            local mem_kb=$(grep VmRSS /proc/$app_pid/status 2>/dev/null | awk '{{print $2}}')
            
            # (2) 获取 CPU (使用 grep 过滤 PID 确保准确)
            local cpu_val=$(top -n 1 | grep "$app_pid" | awk '{{print $9}}' | head -n 1)
            if [ -z "$cpu_val" ]; then cpu_val=0; fi
            
            # (3) 获取 温度 (自动适配格式)
            local temp_val=0
            for zone in /sys/class/thermal/thermal_zone*; do
                local t=$(cat $zone/temp 2>/dev/null)
                if [ ! -z "$t" ]; then
                    if [ "$t" -gt 10000 ]; then temp_val=$((t / 1000)); break;
                    elif [ "$t" -gt 20 ]; then temp_val=$t; break; fi
                fi
            done
            
            # (4) 统一写入日志
            if [ ! -z "$mem_kb" ]; then
                # 注意: 这里全部使用了 ${{}} 进行转义，不会再报红线
                echo "[STATUS] Mem:$((mem_kb / 1024))MB | CPU:${{cpu_val}}% | Temp:${{temp_val}}C" >> $EVENT_LOG
                
                if [ $((mem_kb / 1024)) -gt 800 ]; then
                    echo "    [WARN] 内存过高! 警惕 OOM!" >> $EVENT_LOG
                fi
                if [ "$temp_val" -gt 85 ]; then
                     echo "    [WARN] 设备过热! 当前 ${{temp_val}}C" >> $EVENT_LOG
                fi
            fi
        fi
        last_heavy_check_time=$now_ts
                        
        }}
    
        function check_health_fast() {{
            # 进程存活检查
            if [ -z "$(pidof {self.target_pkg})" ]; then
                echo "!!! [DIED] 进程消失，尝试拉起 !!!" >> $EVENT_LOG
                take_snapshot "DIED"
                am start -n {self.start_uri}
                sleep 5
                return
            fi
    
            check_network
    
            local current_ts=$(get_uptime_sec)
            if [ $((current_ts - last_heavy_check_time)) -ge 30 ]; then
                perform_heavy_check
            fi
            
            if [ $((current_ts - last_heartbeat_time)) -ge 1800 ]; then
                local run_h=$(( (current_ts - start_uptime) / 3600 ))
                local run_m=$(( ((current_ts - start_uptime) % 3600) / 60 ))
                
                # 顺便查一下当前内存
                local app_pid=$(pidof {self.target_pkg})
                local mem_info="App已死"
            if [ ! -z "$app_pid" ]; then
                 local mem_kb=$(grep VmRSS /proc/$app_pid/status 2>/dev/null | awk '{{print $2}}')
                 mem_info="$((mem_kb / 1024)) MB"
            fi
            
            send_feishu "[心跳] 脚本存活确认" "已运行: ${{run_h}}小时 ${{run_m}}分\\n当前内存: ${{mem_info}}\\n状态: 正常执行中..."
            
            # 重置心跳计时器
            last_heartbeat_time=$current_ts
        fi
        }}
    
        # === 6. 主循环 (使用死循环+手动判断时间) ===
        while true; do
            # 检查是否超时
            now_up=$(get_uptime_sec)
            run_sec=$((now_up - start_uptime))
    
            if [ $run_sec -ge {self.duration} ]; then
                echo "=== 达到设定时长 ($run_sec / {self.duration}), 正常结束 ===" >> $EVENT_LOG
                send_feishu "✅ 压测圆满完成" "脚本已运行满 {self.duration} 秒。\\ndone！"
                # 正常退出不需要触发遗言，先解除 trap
                trap - EXIT
                exit 0
            fi
        """

        for plan in plan_list:
            sheet_name = plan['name']
            sheet_loop = plan['loop']
            tasks = plan['tasks']

            safe_suffix = hashlib.md5(str(sheet_name).encode('utf-8')).hexdigest()[:8]
            shell += f"\n    # >>> {sheet_name} <<<\n"
            shell += f"    count_{safe_suffix}=0\n"
            shell += f"    while [ $count_{safe_suffix} -lt {sheet_loop} ]; do\n"
            shell += f"        count_{safe_suffix}=$((count_{safe_suffix} + 1))\n"

            for task in tasks:
                if pd.isna(task.get('action')): continue
                action = str(task.get('action')).upper().strip()
                seq_id = task.get('seq')
                indent = "        "

                # 1. 每次动作前检查健康
                def safe_int(val):
                    try:
                        return int(float(val))
                    except:
                        return val

                shell += f"{indent}check_health_fast\n"
                shell += f'{indent}log_info "[{sheet_name}][#{seq_id}] {action}"\n'
                # shell += f'{indent}echo "[$(date "+%Y-%m-%d %H:%M:%S")] [{sheet_name}][#{seq_id}] {action}" >> $EVENT_LOG\n'

                if action == "CLICK":
                    p1 = safe_int(task.get('p1'))
                    p2 = safe_int(task.get('p2'))
                    shell += f"{indent}input tap {p1} {p2}\n"
                elif action == "SWIPE":
                    p1 = safe_int(task.get('p1'))
                    p2 = safe_int(task.get('p2'))
                    p3 = safe_int(task.get('p3'))
                    p4 = safe_int(task.get('p4'))
                    shell += f"{indent}input swipe {p1} {p2} {p3} {p4} 300\n"
                elif action == "KEY":
                    shell += f"{indent}input keyevent {task.get('p1')}\n"
                elif action == "TEXT":
                    raw_txt = str(task.get('p1'))
                    txt = raw_txt.replace(" ", "%s").replace("'", "'\\''").replace('"', '\\"')
                    shell += f"{indent}input text '{txt}'\n"
                elif action == "ASSERT":
                    raw_keyword = str(task.get('p1')).strip()
                    keyword = raw_keyword.replace('"', '\\"')
                    wait_s = task.get('p2')
                    if pd.isna(wait_s) or str(wait_s).strip() == "": wait_s = 2
                    shell += f"{indent}sleep {wait_s}\n"
                    shell += f'{indent}if logcat -d -t 1000 | grep -q "{keyword}"; then\n'
                    shell += f'{indent}    echo "[ASSERT_PASS] Found: \'{keyword}\'" >> $EVENT_LOG\n'
                    shell += f'{indent}else\n'
                    shell += f'{indent}    echo "!!! [ASSERT_FAIL] Not found: \'{keyword}\'" >> $EVENT_LOG\n'
                    shell += f'{indent}    take_snapshot "ASSERT_FAIL"\n'
                    shell += f'{indent}fi\n'
                elif action == "WAIT":
                    wait_time = task.get('p1') if pd.notna(task.get('p1')) else 1
                    shell += f"{indent}sleep {wait_time}\n"
                elif action == "STOP":
                    shell += f"{indent}am force-stop {self.target_pkg}\n"
                elif action == "START":
                    shell += f"{indent}am start -n {self.start_uri}\n"
                elif action == "SHELL":
                    shell += f"{indent}{task.get('p1')}\n"

            shell += f"    done\n"

        shell += """
        sleep 1
    done
    """
        return shell


def load_project_config(excel_path):
    config = DEFAULT_CONFIG.copy()
    sequence_plan = []

    try:
        # 读取配置 Key-Value
        df_kv = pd.read_excel(excel_path, sheet_name='Config', usecols=[0, 1], header=None)
        cfg_dict = dict(zip(df_kv.iloc[:, 0], df_kv.iloc[:, 1]))

        if 'target_pkg' in cfg_dict and pd.notna(cfg_dict['target_pkg']):
            config['target_pkg'] = str(cfg_dict['target_pkg']).strip()
        if 'start_activity' in cfg_dict and pd.notna(cfg_dict['start_activity']):
            config['start_activity'] = str(cfg_dict['start_activity']).strip()
        if 'ping_target' in cfg_dict and pd.notna(cfg_dict['ping_target']):
            config['ping_target'] = str(cfg_dict['ping_target']).strip()
        if 'log_whitelist' in cfg_dict and pd.notna(cfg_dict['log_whitelist']):
            config['log_whitelist'] = str(cfg_dict['log_whitelist']).strip()
        # 时长解析逻辑
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

        # 解析 Sheet 列表
        print(" 解析excel...")
        df_full = pd.read_excel(excel_path, sheet_name='Config')

        seq_col = next((c for c in df_full.columns if "执行顺序" in str(c) or "Sheet" in str(c)), None)
        loop_col = next((c for c in df_full.columns if "本轮循环" in str(c) or "Loop" in str(c)), None)

        if seq_col:
            plan_df = df_full[[seq_col, loop_col]].dropna(subset=[seq_col])
            for _, row in plan_df.iterrows():
                s_name = str(row[seq_col]).strip()
                if s_name in ["执行顺序", "Sheet Name", "nan"]: continue
                try:
                    l_count = int(row[loop_col])
                except:
                    l_count = 1
                sequence_plan.append({"name": s_name, "loop": l_count})

    # [优化] 增加 Excel 文件占用的捕获
    except PermissionError:
        print(f"错误: 无法读取 '{excel_path}'")
        print("   原因: 文件可能被 Excel/WPS 打开并锁定。")
        print("   解决: 请关闭文件后重试！")
        sys.exit(1)
    except Exception as e:
        print(f"配置读取失败: {e}")
        sys.exit(1)

    return config, sequence_plan


def parse_tasks_from_sheet(excel_path, sheet_name, global_seq_start):
    try:
        df = pd.read_excel(excel_path, sheet_name=sheet_name)
    except Exception as e:
        print(f"无法读取 Sheet [{sheet_name}]: {e}")
        return [], global_seq_start

    tasks = []
    current_seq = global_seq_start
    cols = df.columns

    def find_col(keywords):
        for c in cols:
            if any(k in str(c) for k in keywords):
                return c
        return None

    col_action = find_col(['指令', 'Action'])
    col_repeat = find_col(['重复', 'Repeat'])
    col_p1 = find_col(['参数1', 'P1'])
    col_p2 = find_col(['参数2', 'P2'])
    col_p3 = find_col(['参数3', 'P3'])
    col_p4 = find_col(['参数4', 'P4'])

    if not col_action:
        print(f"Sheet [{sheet_name}] 找不到 '指令' 列，跳过。")
        return [], global_seq_start

    for index, row in df.iterrows():
        act = row.get(col_action)
        if pd.isna(act): continue

        try:
            repeat_count = int(row.get(col_repeat, 1))
        except:
            repeat_count = 1
        if repeat_count < 1: repeat_count = 1

        for i in range(repeat_count):
            current_seq += 1
            tasks.append({
                "seq": current_seq,
                "action": act,
                "p1": row.get(col_p1),
                "p2": row.get(col_p2),
                "p3": row.get(col_p3),
                "p4": row.get(col_p4),
            })

    return tasks, current_seq


if __name__ == "__main__":

    if pd is None:
        print("错误: 需安装 pandas openpyxl")
        sys.exit(1)

    current_dir = os.path.dirname(os.path.abspath(__file__))
    EXCEL_FILE = os.path.join(current_dir, "test plan.xlsx")
    OUTPUT_DIR = os.path.join(current_dir, "dist_stress")

    if not os.path.exists(EXCEL_FILE):
        print(f"找不到配置文件: {EXCEL_FILE}")
        sys.exit(1)

    final_config, seq_plan = load_project_config(EXCEL_FILE)

    if not seq_plan:
        print("Config Sheet 未指定顺序，尝试自动扫描...")
        xl = pd.ExcelFile(EXCEL_FILE)
        for s in xl.sheet_names:
            if s.lower().startswith("round") or s.lower() == "main":
                seq_plan.append({"name": s, "loop": 1})

    if not seq_plan:
        print("错误: 无法构建执行计划。")
        sys.exit(1)

    print(f"目标应用: {final_config['target_pkg']}")

    full_execution_plan = []
    global_seq_counter = 0

    for stage in seq_plan:
        s_name = stage['name']
        s_loop = stage['loop']
        stage_tasks, new_seq = parse_tasks_from_sheet(EXCEL_FILE, s_name, global_seq_counter)
        global_seq_counter = new_seq
        if stage_tasks:
            full_execution_plan.append({"name": s_name, "loop": s_loop, "tasks": stage_tasks})
            print(f"   -> Sheet [{s_name}]: {len(stage_tasks)} 动作 / {s_loop} 循环")

    compiler = StressCompiler(
        target_pkg=final_config['target_pkg'],
        duration=final_config['duration_sec'],
        start_uri=final_config['start_activity'],
        ping_target=final_config.get('ping_target', "www.baidu.com"),
        log_whitelist=final_config.get('log_whitelist', "")
    )
    shell_code = compiler.compile_sequence(full_execution_plan)

    if not os.path.exists(OUTPUT_DIR):
        os.makedirs(OUTPUT_DIR)

    sh_path = os.path.join(OUTPUT_DIR, "stress_core.sh")
    with open(sh_path, "w", encoding="utf-8", newline='\n') as f:
        f.write(shell_code)

    bat_content = f"""@echo off
title Dognoise Stress Launcher
color 0A
echo.
echo [Dognoise] 正在初始化环境...
adb wait-for-device
adb root
adb remount

echo.
echo [1/3] 正在清理旧的压测进程 (防止冲突)...
echo ------------------------------------------
adb shell "pkill -f stress_core.sh"
adb shell "killall stress_core.sh >/dev/null 2>&1"
adb shell "rm -f /data/local/tmp/dognoise.lock"
adb logcat -c
adb shell "rm -rf /sdcard/dognoise_stress/*"
echo ------------------------------------------

echo.
echo [2/3] 推送新脚本...
adb push stress_core.sh /data/local/tmp/stress_core.sh
adb shell chmod 777 /data/local/tmp/stress_core.sh

echo.
echo [3/3] 启动压测任务...
echo.
echo ------------------------------------------
echo 脚本已在后台启动。
echo 日志路径: /sdcard/dognoise_stress/event.log
echo ------------------------------------------
adb shell "nohup sh /data/local/tmp/stress_core.sh > /dev/null 2>&1 &"

echo.
echo 启动成功！
pause
"""
    bat_path = os.path.join(OUTPUT_DIR, "一键开始压测.bat")
    with open(bat_path, "w", encoding="gbk") as f:
        f.write(bat_content)

    print(f"\n✅ 编译完成！目录: {OUTPUT_DIR}")
    print(f"   请务必运行 [一键开始压测.bat]")