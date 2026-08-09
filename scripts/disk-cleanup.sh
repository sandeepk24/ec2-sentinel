#!/usr/bin/env bash
# ============================================================================
# EC2 Sentinel — Safe Disk Cleanup for Build Servers
# ============================================================================
# Targets the usual suspects: old build artifacts, rotated logs, caches.
# DRY RUN by default — shows what would be cleaned without touching anything.
#
# Usage:
#   ./disk-cleanup.sh                # dry run — preview only
#   ./disk-cleanup.sh --execute      # actually clean up
#   ./disk-cleanup.sh --days 14      # only target files older than 14 days
# ============================================================================

set -uo pipefail

DAYS=7
EXECUTE=false

# Parse args
while [[ $# -gt 0 ]]; do
    case $1 in
        --execute) EXECUTE=true; shift ;;
        --days)    DAYS="$2"; shift 2 ;;
        --help|-h)
            echo "Usage: $0 [--execute] [--days N]"
            echo "  --execute   Actually delete files (default: dry run)"
            echo "  --days N    Only target files older than N days (default: 7)"
            exit 0 ;;
        *) echo "Unknown option: $1"; exit 1 ;;
    esac
done

if [ -t 1 ]; then
    R='\033[0;31m' G='\033[0;32m' Y='\033[0;33m' C='\033[0;36m' B='\033[1m' N='\033[0m'
else
    R='' G='' Y='' C='' B='' N=''
fi

echo ""
echo -e "${B}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${N}"
echo -e "  ${B}EC2 Sentinel — Disk Cleanup${N}"
if $EXECUTE; then
    echo -e "  Mode: ${R}EXECUTE${N} — files WILL be deleted"
else
    echo -e "  Mode: ${Y}DRY RUN${N} — preview only (use --execute to clean)"
fi
echo -e "  Targeting files older than ${B}${DAYS} days${N}"
echo -e "${B}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${N}"

total_freed=0

cleanup_target() {
    local label="$1"
    local path="$2"
    local pattern="${3:-*}"

    if [ ! -d "$path" ]; then
        return
    fi

    local size
    size=$(find "$path" -name "$pattern" -type f -mtime +"$DAYS" -exec du -sb {} + 2>/dev/null | \
           awk '{s+=$1} END {print s+0}')

    if [ "$size" -eq 0 ]; then
        return
    fi

    local size_mb=$((size / 1048576))
    total_freed=$((total_freed + size))

    local count
    count=$(find "$path" -name "$pattern" -type f -mtime +"$DAYS" 2>/dev/null | wc -l)

    echo -e "\n  ${C}${label}${N}"
    echo -e "  Path: ${path}"
    echo -e "  Files: ${count}  |  Size: ${B}${size_mb} MB${N}"

    if $EXECUTE; then
        find "$path" -name "$pattern" -type f -mtime +"$DAYS" -delete 2>/dev/null
        echo -e "  ${G}✓ Cleaned${N}"
    else
        echo -e "  ${Y}→ Would clean (use --execute)${N}"
    fi
}

# ---------------------------------------------------------------------------
# Cleanup targets
# ---------------------------------------------------------------------------

echo -e "\n  Scanning..."

# Jenkins workspaces
cleanup_target "Jenkins Workspaces" "/var/lib/jenkins/workspace"
cleanup_target "Jenkins Build Logs" "/var/lib/jenkins/jobs" "*.log"
cleanup_target "Jenkins Temp" "/var/lib/jenkins/tmp"

# Bamboo
cleanup_target "Bamboo Build Artifacts" "/var/atlassian/application-data/bamboo/xml-data/build-dir"
cleanup_target "Bamboo Temp" "/tmp/bamboo-*"

# System logs (rotated/compressed)
cleanup_target "Rotated System Logs" "/var/log" "*.gz"
cleanup_target "Old System Logs" "/var/log" "*.old"
cleanup_target "Numbered Logs" "/var/log" "*.[0-9]"

# Application logs (rotated)
cleanup_target "Rotated App Logs" "/var/log/tomcat9" "*.gz"
cleanup_target "Rotated App Logs" "/var/log/tomcat" "*.gz"
cleanup_target "Old Catalina Logs" "/var/log/tomcat9" "catalina.*.log"

# Package manager caches
cleanup_target "APT Cache" "/var/cache/apt/archives" "*.deb"
cleanup_target "YUM Cache" "/var/cache/yum"
cleanup_target "Pip Cache" "$HOME/.cache/pip"

# Docker (if present)
if command -v docker &>/dev/null; then
    echo -e "\n  ${C}Docker Cleanup${N}"
    if $EXECUTE; then
        docker system prune -f --filter "until=${DAYS}d" 2>/dev/null && echo -e "  ${G}✓ Docker pruned${N}" || true
    else
        docker system df 2>/dev/null || true
        echo -e "  ${Y}→ Would prune images/containers older than ${DAYS}d${N}"
    fi
fi

# Temp files
cleanup_target "System Temp" "/tmp" "tmp.*"
cleanup_target "Var Temp" "/var/tmp"

# Maven/Gradle caches (build servers)
cleanup_target "Maven Cache" "$HOME/.m2/repository"
cleanup_target "Gradle Cache" "$HOME/.gradle/caches"

# npm caches
cleanup_target "NPM Cache" "$HOME/.npm/_cacache"

# Core dumps
cleanup_target "Core Dumps" "/var/crash"
cleanup_target "Core Dumps" "/tmp" "core.*"

# ---------------------------------------------------------------------------
# Summary
# ---------------------------------------------------------------------------

total_mb=$((total_freed / 1048576))
total_gb=$((total_freed / 1073741824))

echo ""
echo -e "${B}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${N}"
if $EXECUTE; then
    if [ $total_gb -gt 0 ]; then
        echo -e "  ${G}Freed: ${B}${total_gb} GB${N}"
    else
        echo -e "  ${G}Freed: ${B}${total_mb} MB${N}"
    fi
else
    if [ $total_gb -gt 0 ]; then
        echo -e "  ${Y}Would free: ${B}${total_gb} GB${N}"
    else
        echo -e "  ${Y}Would free: ${B}${total_mb} MB${N}"
    fi
    echo -e "  Run with ${B}--execute${N} to actually clean up."
fi

# Show current disk state
echo ""
echo -e "  ${B}Current disk usage:${N}"
df -h --output=target,pcent,avail -x tmpfs -x devtmpfs -x squashfs 2>/dev/null | head -10
echo -e "${B}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${N}"
echo ""
