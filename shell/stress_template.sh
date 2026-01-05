#!/system/bin/sh
# ==========================================
# Dognoise Stress Core Template
# ==========================================

# --- 1. 配置参数 (由 Python 注入) ---
TARGET_PKG="{{TARGET_PKG}}"
START_URI="{{START_URI}}"
DURATION_SEC={{DURATION_SEC}}
PING_TARGET="{{PING_TARGET}}"
LOG_WHITELIST="{{LOG_WHITELIST}}"
FEISHU_WEBHOOK="{{FEISHU_WEBHOOK}}"

# 设备名逻辑
DEV_NAME="{{DEVICE_NAME}}"
if [ -z "$DEV_NAME" ]; then
    DEV_NAME=$(getprop ro.product.model)
fi

# --- 2. 基础设施初始化 (合并清理版) ---
WORKDIR="/sdcard/dognoise_stress"
if [ ! -d "$WORKDIR" ]; then
    mkdir -p "$WORKDIR"
fi

# 定义目录结构 (截图放入子目录)
LOG_DIR="$WORKDIR/screenshots"
if [ ! -d "$LOG_DIR" ]; then
    mkdir -p "$LOG_DIR"
fi

EVENT_LOG="$WORKDIR/event.log"
CRASH_LOG="$WORKDIR/crash_stack.log"
ANR_LOG="$WORKDIR/anr_history.log"
LOCK_FILE="/data/local/tmp/dognoise.lock"
MY_PID=$$

# 初始化文件
touch "$EVENT_LOG" "$CRASH_LOG" "$ANR_LOG"

# 写入锁文件
echo $MY_PID > "$LOCK_FILE"

# 防睡设置
svc power stayon true

# 启动后台 Logcat
logcat -c
nohup logcat -v time $LOG_WHITELIST *:E -f "$CRASH_LOG" -r 10240 -n 20 &
LOGCAT_PID=$!
# --- 3. 核心函数库 ---

function log_info() {
    echo "[$(date "+%Y-%m-%d %H:%M:%S")] $1" >> $EVENT_LOG
}

function get_uptime_sec() {
    read up_val _ < /proc/uptime
    echo ${up_val%%.*}
}




# 飞书发送函数 
function send_feishu() {
    local title=$1
    local content=$2

    # 1. 净化 Title & Content (Shell 内部转义)
    local clean_title=$(echo "$title" | sed 's/"/\\"/g' | tr -d '\r' | tr '\n' ' ')
    local clean_content=$(echo "$content" | sed 's/"/\\"/g' | tr -d '\r' | awk '{printf "%s\\n", $0}' | sed 's/\\n$//')

    # 2. 构造 JSON
    local json_body="{\"msg_type\":\"text\",\"content\":{\"text\":\"【$DEV_NAME】 $clean_title\n----------------\n$clean_content\"}}"

    # 3. 发送
    local res=$(curl -s -k -g --connect-timeout 5 -X POST "$FEISHU_WEBHOOK" \
            -H "Content-Type: application/json" \
            -d "$json_body")

    if [ $? -eq 0 ] && echo "$res" | grep -q "code.:0"; then
        log_info "[FEISHU] SUCCESS"
    else
        log_info "[FEISHU] FAIL | Resp: $res"
    fi
}

function leave_last_words() {
    trap - EXIT  # <--- 防止退出时再次触发 EXIT
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

    send_feishu "🚨 压测停止" "原因: $reason\\n运行时长: ${run_h}小时 ${run_m}分"

    rm -f "$LOCK_FILE"
    [ ! -z "$LOGCAT_PID" ] && kill $LOGCAT_PID > /dev/null 2>&1
    exit 0
}

trap 'leave_last_words "正常退出或脚本崩溃(EXIT)"' EXIT
trap 'leave_last_words "被手动停止(INT)"' INT
trap 'leave_last_words "被系统强杀(TERM)"' TERM


function take_snapshot() {
    local type_name=$1
    screencap -p "$LOG_DIR/${type_name}_$(date +%Y%m%d_%H%M%S).png"
    echo "    [SNAPSHOT] ${type_name}" >> $EVENT_LOG
}

function check_network() {
    local now_ts=$(get_uptime_sec)
    
    # 检查全局变量是否存在，如果不存在则初始化为0 (兼容性写法)
    last_net_check_time=${last_net_check_time:-0}

    if [ $((now_ts - last_net_check_time)) -ge 60 ]; then
        local ping_res
        local exit_code

        # 1. 执行 ping
        ping_res=$(ping -c 1 -w 3 -W 2 $PING_TARGET 2>&1)
        exit_code=$?

        # 2. 检查结果
        if [ $exit_code -eq 0 ] && echo "$ping_res" | grep -q "time="; then
            local t_val
            t_val=$(echo "$ping_res" | sed -n 's/.*time=\([0-9.]*\).*/\1/p')

            if [ -n "$t_val" ]; then
                log_info "[NETWORK] Ping:${t_val}ms"
            else
                log_info "[NETWORK] Ping:ParseError"
            fi
        else
            log_info "[NETWORK] Ping:FAIL (Exit:$exit_code)"
        fi
        
        last_net_check_time=$now_ts
    fi
}

LAST_FATAL_LOG_CONTENT="" 

function check_fatal_logs() {
    local now_ts=$(get_uptime_sec)
    # 1. 抓取报错 (只看 OOM)
    local fatal_log=$(logcat -d -t 5000 | grep -E "lowmemorykiller|FATAL EXCEPTION" | grep -v "permissive=1" | tail -n 1)

    if [ -z "$fatal_log" ]; then
        return 0
    fi

    # 去重检查
    if [ "$fatal_log" == "$LAST_FATAL_LOG_CONTENT" ]; then
        return 0
    fi

    LAST_FATAL_LOG_CONTENT="$fatal_log"
    local err_type="OOM"

    log_info "[CRITICAL_${err_type}] 发现严重征兆"
    log_info "${fatal_log}"

    # 4. 截图冷却逻辑 (1200秒)
    local last_var_name="last_shot_time_${err_type}"
    local last_val=$(eval echo \$$last_var_name)
    last_val=${last_val:-0}

    if [ $((now_ts - last_val)) -ge 1200 ]; then
            take_snapshot "SYS_${err_type}"
            eval "${last_var_name}=$now_ts"
            log_info "[SNAPSHOT] 已截图 (类型: ${err_type})"
            send_feishu "🚨 发现严重报错 ($err_type)" "$fatal_log"
    else
            log_info "[COOLDOWN] ${err_type} 正在冷却中，跳过截图"
    fi
}

function check_anr_state() {
    # 扫描 Events Log 里的 am_anr 标签
    if logcat -b events -d -t 100 | grep "am_anr" | grep -q "$TARGET_PKG"; then
            log_info "!!![ANR_DETECTED]!!!"
            take_snapshot "ANR"
            
            # 自救重启逻辑
            am force-stop $TARGET_PKG
            sleep 2
            am start -n $START_URI
            sleep 5
            return 1 # 返回 1 表示发生了重启
    fi
    return 0
}

function monitor_performance() {
    local app_pkg="$TARGET_PKG"
    local app_pid=$(pidof $app_pkg 2>/dev/null)
    if [ -z "$app_pid" ]; then
        # 备选方案：通过 ps 查找
        app_pid=$(ps -A | grep "$app_pkg" | awk '{print $2}' | head -n 1)
    fi

    if [ -z "$app_pid" ]; then
        return
    fi

    # --- 1. 获取内存 (PSS) ---
    local mem_pss=$(dumpsys meminfo $app_pkg | grep "TOTAL PSS:" | awk '{print $3}')
    if [ -z "$mem_pss" ]; then
        local mem_kb=$(grep VmRSS /proc/$app_pid/status 2>/dev/null | awk '{print $2}')
        mem_pss=$((mem_kb / 1024))
    else
        mem_pss=$((mem_pss / 1024))
    fi

    # --- 2. 获取 CPU (归一化) ---
    local cpu_cores=$(grep -c ^processor /proc/cpuinfo)
    [ -z "$cpu_cores" ] || [ "$cpu_cores" -eq 0 ] && cpu_cores=1
    
    local raw_cpu=$(top -n 1 -b | grep -w "$app_pkg" | head -n 1 | awk '{for(i=1;i<=NF;i++) {if($i ~ /%/) {print $i; break}}}' | tr -d '%')
    [ -z "$raw_cpu" ] && raw_cpu=$(top -n 1 -b | grep -w "$app_pkg" | head -n 1 | awk '{print $9}')
    
    local cpu_val=0
    if [ ! -z "$raw_cpu" ]; then
        cpu_val=$(echo "$raw_cpu $cpu_cores" | awk '{printf "%.1f", $1/$2}')
    fi

    # --- 3. 获取温度 ---
    local temp_val=0
    for zone in /sys/class/thermal/thermal_zone*; do
        local type=$(cat $zone/type 2>/dev/null)
        if echo "$type" | grep -qE "cpu|battery|tsens_tz_sensor|soc-thermal|gpu-thermal"; then
            local t=$(cat $zone/temp 2>/dev/null)
            [ "$t" -gt 10000 ] && temp_val=$((t / 1000)) || temp_val=$t
            break
        fi
    done

    log_info "[STATUS] Mem:${mem_pss}MB | CPU:${cpu_val}% | Temp:${temp_val}C"

    # --- 4. 心跳上报逻辑 (每20分钟) ---
    local now_ts=$(get_uptime_sec)
    if [ $((now_ts - last_heartbeat_time)) -ge 1200 ]; then
        local run_sec=$((now_ts - start_uptime))
        local run_h=$((run_sec / 3600))
        local run_m=$(( (run_sec % 3600) / 60 ))
        
        local hb_content="运行时长: ${run_h}小时 ${run_m}分\n"
        hb_content+="内存占用: ${mem_pss} MB\n"
        hb_content+="CPU负载: ${cpu_val}%\n"
        hb_content+="机身温度: ${temp_val}°C"
        
        send_feishu "💓 压测心跳报告" "$hb_content"
        last_heartbeat_time=$now_ts
    fi
}

function perform_heavy_check() {
    local now_ts=$(get_uptime_sec)
    
    # 1. 检查报错
    check_fatal_logs
    
    # 2. 检查 ANR (如果发生了重启，就不查性能了，因为进程号变了)
    check_anr_state
    local anr_status=$?
    
    if [ $anr_status -eq 0 ]; then
        # 3. 只有 APP 活着才查性能
        monitor_performance
    fi

    last_heavy_check_time=$now_ts
}

function check_health_fast() {
    local now=$(get_uptime_sec)

    # 门禁 1: 重型检查 (60s)
    if [ $((now - last_heavy_check_time)) -ge 60 ]; then
        perform_heavy_check
    fi

    # 门禁 2: 网络检查 (60s)
    check_network
}

# ==========================================
# ▼▼▼ 主循环 (任务执行区) ▼▼▼
# ==========================================

# 校对时间
start_uptime=$(get_uptime_sec)
last_heartbeat_time=$(get_uptime_sec)
last_heavy_check_time=0
last_net_check_time=0

log_info "=== 压测开始: $TARGET_PKG ==="
send_feishu "🚀 压测已启动" "目标: $TARGET_PKG\n计划时长: $DURATION_SEC 秒"

while true; do
    # 1. 全局时长检查
    now_up=$(get_uptime_sec)
    if [ $((now_up - start_uptime)) -ge $DURATION_SEC ]; then
        send_feishu "✅ 压测完成" "已满 $DURATION_SEC 秒。"
        exit 0
    fi

    # 2. 插入 Excel 生成的动作序列
    # {{TASK_SEQUENCE_HERE}}

    # 3. 每一轮大循环后的缓冲
    sleep 1
done