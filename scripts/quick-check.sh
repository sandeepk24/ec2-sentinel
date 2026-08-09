#!/usr/bin/env bash
# ============================================================================
# EC2 Sentinel — Quick Check (zero dependencies)
# ============================================================================
# The script you run FIRST when you SSH into a troubled server.
# Zero Python, zero pip, zero config. Just bash and standard Linux tools.
#
# Usage:
#   ./quick-check.sh
#   curl -sSL https://raw.githubusercontent.com/YOUR_USER/ec2-sentinel/main/scripts/quick-check.sh | bash
# ============================================================================

set -uo pipefail

# Colors
if [ -t 1 ]; then
    R='\033[0;31m' G='\033[0;32m' Y='\033[0;33m' C='\033[0;36m'
    B='\033[1m' D='\033[2m' N='\033[0m'
else
    R='' G='' Y='' C='' B='' D='' N=''
fi

icon_ok="${G}✅${N}"
icon_warn="${Y}⚠️ ${N}"
icon_crit="${R}❌${N}"

echo ""
echo -e "${B}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${N}"
echo -e "  ${B}${C}EC2 SENTINEL${N} — Quick Check (bash)"
echo -e "  Host: ${B}$(hostname)${N}  |  $(date -u '+%Y-%m-%d %H:%M:%S UTC')"
echo -e "${B}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${N}"

# ---------------------------------------------------------------------------
# CPU
# ---------------------------------------------------------------------------
echo -e "\n  ${B}CPU${N}"

cores=$(nproc 2>/dev/null || grep -c ^processor /proc/cpuinfo)
load=$(awk '{print $1}' /proc/loadavg)
load5=$(awk '{print $2}' /proc/loadavg)
load15=$(awk '{print $3}' /proc/loadavg)

# CPU usage via /proc/stat (1-second sample)
read -r _ u1 n1 s1 i1 w1 q1 sq1 st1 < /proc/stat
sleep 1
read -r _ u2 n2 s2 i2 w2 q2 sq2 st2 < /proc/stat

total1=$((u1+n1+s1+i1+w1+q1+sq1+st1))
total2=$((u2+n2+s2+i2+w2+q2+sq2+st2))
idle1=$((i1+w1))
idle2=$((i2+w2))
steal_delta=$((st2-st1))
total_delta=$((total2-total1))

if [ $total_delta -gt 0 ]; then
    cpu_pct=$(( (total_delta - (idle2-idle1)) * 100 / total_delta ))
    steal_pct=$(( steal_delta * 100 / total_delta ))
else
    cpu_pct=0
    steal_pct=0
fi

cpu_icon=$icon_ok
[ "$cpu_pct" -ge 80 ] && cpu_icon=$icon_warn
[ "$cpu_pct" -ge 95 ] && cpu_icon=$icon_crit

echo -e "  ├─ Usage: ${B}${cpu_pct}%${N}  (${cores} cores, load: ${load} ${load5} ${load15})  ${cpu_icon}"
[ "$steal_pct" -gt 1 ] && echo -e "  │  ${Y}↳ Steal time: ${steal_pct}% (CPU throttling detected)${N}"

# ---------------------------------------------------------------------------
# Memory
# ---------------------------------------------------------------------------
echo -e "\n  ${B}MEMORY${N}"

mem_total=$(awk '/MemTotal/ {print $2}' /proc/meminfo)
mem_avail=$(awk '/MemAvailable/ {print $2}' /proc/meminfo)
mem_used=$((mem_total - mem_avail))
mem_pct=$((mem_used * 100 / mem_total))
mem_total_gb=$(awk "BEGIN {printf \"%.1f\", $mem_total/1048576}")
mem_used_gb=$(awk "BEGIN {printf \"%.1f\", $mem_used/1048576}")

mem_icon=$icon_ok
[ "$mem_pct" -ge 80 ] && mem_icon=$icon_warn
[ "$mem_pct" -ge 95 ] && mem_icon=$icon_crit

echo -e "  ├─ RAM: ${B}${mem_used_gb} / ${mem_total_gb} GB${N} (${mem_pct}%)  ${mem_icon}"

swap_total=$(awk '/SwapTotal/ {print $2}' /proc/meminfo)
swap_free=$(awk '/SwapFree/ {print $2}' /proc/meminfo)
if [ "$swap_total" -gt 0 ]; then
    swap_used=$((swap_total - swap_free))
    swap_pct=$((swap_used * 100 / swap_total))
    swap_icon=$icon_ok
    [ "$swap_pct" -ge 50 ] && swap_icon=$icon_warn
    echo -e "  └─ Swap: ${swap_pct}%  ${swap_icon}"
fi

# OOM kills
oom_count=$(awk '/oom_kill/ {print $2}' /proc/vmstat 2>/dev/null || echo 0)
[ "$oom_count" -gt 0 ] && echo -e "  ${R}   ↳ OOM kills since boot: ${oom_count}${N}"

# ---------------------------------------------------------------------------
# Disk
# ---------------------------------------------------------------------------
echo -e "\n  ${B}DISK${N}"

df -h --output=target,pcent,size,used,avail -x tmpfs -x devtmpfs -x squashfs 2>/dev/null | \
    tail -n +2 | while read -r mount pct size used avail; do
    pct_num=${pct%\%}
    d_icon=$icon_ok
    [ "$pct_num" -ge 75 ] && d_icon=$icon_warn
    [ "$pct_num" -ge 90 ] && d_icon=$icon_crit
    printf "  ├─ %-12s %4s  (%s used of %s)  %b\n" "$mount" "$pct" "$used" "$size" "$d_icon"
done

# Inode check
echo -e "  ${D}Inodes:${N}"
df -i --output=target,ipcent -x tmpfs -x devtmpfs -x squashfs 2>/dev/null | \
    tail -n +2 | while read -r mount pct; do
    pct_num=${pct%\%}
    [ "$pct_num" -ge 80 ] && echo -e "  │  ${Y}↳ ${mount}: ${pct} inodes used${N}"
done

# ---------------------------------------------------------------------------
# Top processes by CPU and Memory
# ---------------------------------------------------------------------------
echo -e "\n  ${B}TOP PROCESSES${N} (by CPU)"
ps aux --sort=-%cpu | head -6 | tail -5 | \
    awk '{printf "  ├─ %-15s  cpu: %5s  mem: %5s  pid: %s\n", $11, $3"%", $4"%", $2}'

echo -e "\n  ${B}TOP PROCESSES${N} (by Memory)"
ps aux --sort=-%mem | head -6 | tail -5 | \
    awk '{printf "  ├─ %-15s  mem: %5s  rss: %sKB  pid: %s\n", $11, $4"%", $6, $2}'

# ---------------------------------------------------------------------------
# Listening ports
# ---------------------------------------------------------------------------
echo -e "\n  ${B}LISTENING PORTS${N}"
ss -tlnp 2>/dev/null | grep LISTEN | awk '{
    split($4, a, ":");
    port = a[length(a)];
    proc = $6;
    gsub(/.*"/, "", proc);
    gsub(/".*/, "", proc);
    if (port != "" && port+0 > 0)
        printf "  ├─ :%s  %s\n", port, proc
}' | sort -t: -k2 -n | head -20

# ---------------------------------------------------------------------------
# Uptime
# ---------------------------------------------------------------------------
echo -e "\n  ${B}UPTIME${N}"
echo -e "  └─ $(uptime -p 2>/dev/null || uptime)"

# ---------------------------------------------------------------------------
# Recent trouble in logs
# ---------------------------------------------------------------------------
echo -e "\n  ${B}RECENT LOG ISSUES${N} (last 100 lines of syslog)"
log_file="/var/log/syslog"
[ ! -f "$log_file" ] && log_file="/var/log/messages"

if [ -r "$log_file" ]; then
    trouble=$(tail -100 "$log_file" 2>/dev/null | grep -ciE 'error|critical|fatal|oom|killed|no space' || true)
    if [ "$trouble" -gt 0 ]; then
        echo -e "  ${Y}↳ ${trouble} concerning lines found${N}"
    else
        echo -e "  ${G}↳ No recent errors detected${N}"
    fi
else
    echo -e "  ${D}↳ Cannot read ${log_file} (permission denied)${N}"
fi

echo -e "\n${B}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${N}"
echo -e "  Quick check complete. For full monitoring:"
echo -e "  ${C}https://github.com/YOUR_USER/ec2-sentinel${N}"
echo -e "${B}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${N}"
echo ""
