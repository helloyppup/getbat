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
    "log_whitelist": "",
    "device_name": ""
}


class StressCompiler:
    def __init__(self, target_pkg, duration=3600, start_uri=None, ping_target="www.baidu.com", log_whitelist="",
                 device_name=""):
        self.target_pkg = target_pkg
        self.duration = int(duration)
        self.ping_target = ping_target
        self.log_whitelist = log_whitelist
        self.device_name = device_name
        if "/" in str(start_uri):
            self.start_uri = start_uri
        else:
            self.start_uri = f"{target_pkg}/{start_uri}"

    def compile_sequence(self, plan_list):
        FEISHU_WEBHOOK = "https://open.feishu.cn/open-apis/bot/v2/hook/e162c2e1-d3b6-4211-9a23-58ff22c76986"

        # 优先拿配置表里的设备信息，否则拿出厂信息$(getprop ro.product.model)
        dev_logic = f'DEV_NAME="{self.device_name}"\n'
        dev_logic += '        if [ -z "$DEV_NAME" ]; then DEV_NAME=$(getprop ro.product.model); fi'

        shell = f"""#!/system/bin/sh

        # Target: {self.target_pkg}

        MY_PID=$$
        LOCK_FILE="/data/local/tmp/dognoise.lock"

        # === 0. 获取设备名 ===
        {dev_logic}

        # === 1. 定义日志路径 ===
        LOG_DIR="/sdcard/dognoise_stress"
        mkdir -p $LOG_DIR
        EVENT_LOG="$LOG_DIR/event.log"
        CRASH_LOG="$LOG_DIR/crash_stack.log"
        ANR_LOG="$LOG_DIR/anr_history.log"
        touch $EVENT_LOG $CRASH_LOG $ANR_LOG

        function log_info() {{
            echo "[$(date "+%Y-%m-%d %H:%M:%S")] $1" >> $EVENT_LOG
        }}

        function get_uptime_sec() {{
            read up_val _ < /proc/uptime
            echo ${{up_val%%.*}}
        }}

        function send_feishu() {{
            local title=$1
            local content=$2
            
            # 1. 净化 Title: 
            #    sed: 将 " 替换为 \\" (Shell中转义引号) -> Python中需写 \\\\
            #    tr: 删除 \\r, 将 \\n 换为空格
            local clean_title=$(echo "$title" | sed 's/"/\\\\"/g' | tr -d '\\r' | tr '\\n' ' ')

            # 2. 净化 Content:
            #    sed: 将 " 替换为 \\"
            #    tr: 删除 \\r
            #    awk: 将多行合并为一行，行尾加 \\n (字面量)
            local clean_content=$(echo "$content" | sed 's/"/\\\\"/g' | tr -d '\\r' | awk '{{printf "%s\\\\n", $0}}' | sed 's/\\\\n$//')

            # 3. 构造 JSON Body (必须在一行内完成，防止 Shell 断行错误)
            #    \\\" 代表输出到文件是 \"
            local json_body="{{\\\"msg_type\\\":\\\"text\\\",\\\"content\\\":{{\\\"text\\\":\\\"【$DEV_NAME】 $clean_title\\\\n----------------\\\\n$clean_content\\\"}}}}"

            # 4. 发送请求 (使用 constructed json_body)
            local res=$(curl -s -k -g --connect-timeout 5 -X POST "{FEISHU_WEBHOOK}" \\
                 -H "Content-Type: application/json" \\
                 -d "$json_body")
            
            local exit_code=$?

            if [ $exit_code -eq 0 ]; then
                if echo "$res" | grep -q "code.:0"; then
                    log_info "[FEISHU_SEND] SUCCESS"
                else
                    log_info "[FEISHU_SEND] SERVER_ERR | Resp: $res"
                fi
            else
                log_info "[FEISHU_SEND] CURL_FAILED | ExitCode: $exit_code"
            fi
        }}

        # === 3. 遗言系统 (已修复防重复) ===
        function leave_last_words() {{
            trap - EXIT  # <--- 【关键】：防止退出时再次触发 EXIT
            local reason=$1
            local now_up=$(get_uptime_sec)
            local total_run=$((now_up - start_uptime))

            # 格式化时间
            local run_h=$((total_run / 3600))
            local run_m=$(( (total_run % 3600) / 60 ))

            echo "" >> $EVENT_LOG
            echo "========= [ 脚本停止报告 ] =========" >> $EVENT_LOG
            echo "时间: $(date)" >> $EVENT_LOG
            echo "原因: $reason" >> $EVENT_LOG

            send_feishu "🚨 压测停止" "原因: $reason\\n运行时长: ${{run_h}}小时 ${{run_m}}分"

            rm -f "$LOCK_FILE"
            [ ! -z "$LOGCAT_PID" ] && kill $LOGCAT_PID > /dev/null 2>&1
            exit 0
        }}

        trap 'leave_last_words "正常退出或脚本崩溃(EXIT)"' EXIT
        trap 'leave_last_words "被手动停止(INT)"' INT
        trap 'leave_last_words "被系统强杀(TERM)"' TERM

        # === 4. 初始化环境 ===
        echo $MY_PID > $LOCK_FILE
        svc power stayon true
        logcat -c
        nohup logcat -v time {self.log_whitelist} *:I -f $CRASH_LOG -r 10240 -n 50 &
        LOGCAT_PID=$!

        start_uptime=$(get_uptime_sec)
        last_heartbeat_time=$(get_uptime_sec)  
        last_heavy_check_time=0
        last_net_check_time=0

        log_info "=== 压测开始: {self.target_pkg} ==="
        send_feishu "🚀 压测已启动" "目标: {self.target_pkg}\\n计划时长: {self.duration}秒"

        # === 5. 辅助函数 ===
        function take_snapshot() {{
            local type_name=$1
            screencap -p "$LOG_DIR/${{type_name}}_$(date +%Y%m%d_%H%M%S).png"
            echo "    [SNAPSHOT] ${{type_name}}" >> $EVENT_LOG
        }}
        
        
        function check_network() {{
            local now_ts=$(get_uptime_sec)
            last_net_check_time=${{last_net_check_time:-0}}
            
            if [ $((now_ts - last_net_check_time)) -ge 60 ]; then
                local ping_res
                local exit_code
                
                # 1. 执行 ping (确保等号两边没空格)
                ping_res=$(ping -c 1 -w 3 -W 2 {self.ping_target} 2>&1)
                exit_code=$?
            
                if [ $exit_code -eq 0 ] && echo "$ping_res" | grep -q "time="; then
                    # 2. 改用 awk 解析：
                    # 先找包含 'time=' 的那一行
                    # 然后用 '=' 分割取出第二部分
                    # 最后只保留数字和点
                    local t_val
                    t_val=$(echo "$ping_res" | grep "time=" | awk -F'time=' '{{print $2}}' | awk '{{print $1}}' | tr -cd '0-9.')
                    
                    if [ -n "$t_val" ]; then
                        log_info "[NETWORK] Ping:${{t_val}}ms"
                    else
                        # 如果还是失败，打印第一行 ping 结果方便调试
                        local brief=$(echo "$ping_res" | head -n 2 | tr -d '\\n')
                        log_info "[NETWORK] Ping:ParseError ($brief)"
                    fi
                else
                    log_info "[NETWORK] Ping:FAIL (Exit:$exit_code)"
                fi
                last_net_check_time=$now_ts
            fi
        }}

        function perform_heavy_check() {{
            local now_ts=$(get_uptime_sec)
            local fatal_log=$(logcat -d -t 200 | grep -E "lowmemorykiller|MediaProvider|AudioSystem|audit" | grep -v "permissive=1" | tail -n 3)
            local app_pkg="{self.target_pkg}"
            local now=$(get_uptime_sec)
        
            
            if [ ! -z "$fatal_log" ]; then
                local err_type="UNKNOWN"
                # 改用 if/elif/else 结构，更清晰，避免重复覆盖
                if echo "$fatal_log" | grep -q "lowmemorykiller"; then err_type="OOM"
                elif echo "$fatal_log" | grep -q "MediaProvider"; then err_type="MEDIA"
                elif echo "$fatal_log" | grep -q "AudioSystem"; then err_type="AUDIO"
                elif echo "$fatal_log" | grep -q "audit"; then err_type="KERNEL"
                fi

                log_info "[CRITICAL_${{err_type}}] 发现严重征兆"
                log_info "${{fatal_log}}"

                local last_var_name="last_shot_time_${{err_type}}"
                # 【改进点】：给变量一个默认值 0，防止数学运算报错
                local last_val=$(eval echo \$$last_var_name)
                last_val=${{last_val:-0}} 

                if [ $((now_ts - last_val)) -ge 600 ]; then
                     take_snapshot "SYS_${{err_type}}"
                     eval "${{last_var_name}}=$now_ts"
                     log_info "[SNAPSHOT] 已截图 (类型: ${{err_type}})"
                else
                     log_info "[COOLDOWN] ${{err_type}} 正在冷却中，跳过截图"
                fi
            fi

            # --- ANR 检查 ---
            if logcat -b events -d -t 100 | grep "am_anr" | grep -q "{self.target_pkg}"; then
                 log_info "!!![ANR_DETECTED]!!!"
                 take_snapshot "ANR"
                 am force-stop {self.target_pkg}
                 sleep 2
                 am start -n {self.start_uri}
                 sleep 5
                 return
            fi

            # --- 性能监控  ---
            local app_pid=$(pidof $app_pkg | awk '{{print $1}}')

            if [ ! -z "$app_pid" ]; then
                # --- 1. 内存抓取 (PSS 方案，更贴近 Android 真实情况) ---
                # 如果觉得 dumpsys 太慢，可以保留原有的 VmRSS 逻辑
                local mem_pss=$(dumpsys meminfo $app_pkg | grep "TOTAL PSS:" | awk '{{print $3}}')
                if [ -z "$mem_pss" ]; then
                    # 兜底方案：如果 dumpsys 失败，使用 VmRSS
                    local mem_kb=$(grep VmRSS /proc/$app_pid/status 2>/dev/null | awk '{{print $2}}')
                    mem_pss=$((mem_kb / 1024))
                else
                    mem_pss=$((mem_pss / 1024)) # 转换为 MB
                fi

                # --- 2. CPU 抓取 (归一化处理) ---
                # 获取核心数 (用于解决 124% 的问题)
                local cpu_cores=$(grep -c ^processor /proc/cpuinfo)
                [ -z "$cpu_cores" ] || [ "$cpu_cores" -eq 0 ] && cpu_cores=1

                # 使用 top 抓取 CPU，并根据核心数换算
                local raw_cpu=$(top -n 1 -b | grep -w "$app_pkg" | head -n 1 | awk '{{
                    for(i=1;i<=NF;i++) {{ if($i ~ /%/) {{print $i; break}} }}
                }}' | tr -d '%')
                
                # 如果 top 没带 % 号，尝试抓取第 9 列（通用位置）
                [ -z "$raw_cpu" ] && raw_cpu=$(top -n 1 -b | grep -w "$app_pkg" | head -n 1 | awk '{{print $9}}')
                
                # 计算归一化后的 CPU ( 原始值 / 核心数 )
                local cpu_val=0
                if [ ! -z "$raw_cpu" ]; then
                    cpu_val=$(echo "$raw_cpu $cpu_cores" | awk '{{printf "%.1f", $1/$2}}')
                fi

                # --- 3. 温度抓取 ---
                local temp_val=0
                for zone in /sys/class/thermal/thermal_zone*; do
                    local type=$(cat $zone/type 2>/dev/null)
                    if echo "$type" | grep -qE "cpu|battery|tsens_tz_sensor"; then
                        local t=$(cat $zone/temp 2>/dev/null)
                        [ "$t" -gt 10000 ] && temp_val=$((t / 1000)) || temp_val=$t
                        break
                    fi
                done

                log_info "[STATUS] Mem:${{mem_pss}}MB(PSS) | CPU:${{cpu_val}}% | Temp:${{temp_val}}C"
                
                if [ $((now_ts - last_heartbeat_time)) -ge 600 ]; then
                
                # 1. 计算运行时长
                local run_sec=$((now_ts - start_uptime))
                local run_h=$((run_sec / 3600))
                local run_m=$(( (run_sec % 3600) / 60 ))
                
                # 2. 组装消息内容
                local hb_content="运行时长: ${{run_h}}小时 ${{run_m}}分\\n"
                hb_content+="内存占用: ${{mem_pss}} MB\\n"
                hb_content+="CPU负载: ${{cpu_val}}%\\n"
                hb_content+="机身温度: ${{temp_val}}°C"
                
                # 3. 发送
                send_feishu "压测心跳报告" "$hb_content"
                
                # 4. 更新心跳时间
                last_heartbeat_time=$now_ts
                
                fi
            fi
            last_heavy_check_time=$now_ts
        }}

        
        
        function check_health_fast() {{
            local now=$(get_uptime_sec)
            
            # 如果距离上次检查超过 5 秒，才执行 heavy_check
            # last_heavy_check_time 会在 perform_heavy_check 内部更新
            if [ $((now - last_heavy_check_time)) -ge 5 ]; then
                perform_heavy_check
            fi

            # 网络检查 (check_network 内部已有 60s 冷却，所以这里直接调)
            check_network
        }}
        

        while true; do
            now_up=$(get_uptime_sec)
            if [ $((now_up - start_uptime)) -ge {self.duration} ]; then
                send_feishu "✅ 压测完成" "已满 {self.duration} 秒。"
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

                def safe_int(val):
                    try:
                        return int(float(val))
                    except:
                        return val

                shell += f"{indent}check_health_fast\n"
                shell += f'{indent}log_info "[{sheet_name}][#{seq_id}] {action}"\n'

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
        # 读取配置 Key-Value (读取 A列和B列)
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
        if 'device_name' in cfg_dict and pd.notna(cfg_dict['device_name']):
            config['device_name'] = str(cfg_dict['device_name']).strip()
        else:
            config['device_name'] = ""

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
        log_whitelist=final_config.get('log_whitelist', ""),
        device_name=final_config.get('device_name', "")
    )
    print(f"设备名称: {final_config.get('device_name', '未获取到')}")
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
adb shell "ps -A | grep stress_core | awk '{{print $2}}' | xargs kill -9 >/dev/null 2>&1"
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