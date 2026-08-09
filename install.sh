#!/usr/bin/env bash
# ============================================================================
# EC2 Sentinel — Installer
# ============================================================================
# Usage:
#   curl -sSL https://raw.githubusercontent.com/YOUR_USER/ec2-sentinel/main/install.sh | bash
#   ./install.sh                   # install to /opt/ec2-sentinel
#   ./install.sh --systemd         # install + enable systemd service
#   ./install.sh --uninstall       # remove everything
# ============================================================================

set -euo pipefail

INSTALL_DIR="/opt/ec2-sentinel"
REPO_URL="https://github.com/YOUR_USER/ec2-sentinel.git"
SERVICE_NAME="ec2-sentinel"
PYTHON_MIN="3.9"

# Colors (degrade if not a tty)
if [ -t 1 ]; then
    RED='\033[0;31m'
    GREEN='\033[0;32m'
    YELLOW='\033[0;33m'
    CYAN='\033[0;36m'
    BOLD='\033[1m'
    NC='\033[0m'
else
    RED='' GREEN='' YELLOW='' CYAN='' BOLD='' NC=''
fi

log()  { echo -e "${GREEN}[✓]${NC} $1"; }
warn() { echo -e "${YELLOW}[!]${NC} $1"; }
err()  { echo -e "${RED}[✗]${NC} $1" >&2; }
info() { echo -e "${CYAN}[i]${NC} $1"; }

# ---------------------------------------------------------------------------
# Pre-flight checks
# ---------------------------------------------------------------------------

check_python() {
    local py_cmd=""
    for cmd in python3 python; do
        if command -v "$cmd" &>/dev/null; then
            local version
            version=$($cmd -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')" 2>/dev/null)
            if [ "$(echo "$version >= $PYTHON_MIN" | bc -l 2>/dev/null || python3 -c "print(float('$version') >= float('$PYTHON_MIN'))")" = "True" ] || \
               [ "$(echo "$version >= $PYTHON_MIN" | bc -l 2>/dev/null)" = "1" ]; then
                py_cmd="$cmd"
                break
            fi
        fi
    done

    if [ -z "$py_cmd" ]; then
        err "Python $PYTHON_MIN+ is required but not found."
        info "Install with: sudo apt install python3 python3-pip   (Debian/Ubuntu)"
        info "          or: sudo yum install python3 python3-pip   (RHEL/Amazon Linux)"
        exit 1
    fi

    log "Found Python: $($py_cmd --version)"
    echo "$py_cmd"
}

check_root() {
    if [ "$(id -u)" -ne 0 ]; then
        warn "Not running as root. Will install to user space."
        INSTALL_DIR="$HOME/.ec2-sentinel"
    fi
}

# ---------------------------------------------------------------------------
# Install
# ---------------------------------------------------------------------------

install() {
    echo ""
    echo -e "${BOLD}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
    echo -e "  ${BOLD}EC2 Sentinel — Installer${NC}"
    echo -e "${BOLD}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
    echo ""

    check_root
    local py_cmd
    py_cmd=$(check_python)

    # Clone or update
    if [ -d "$INSTALL_DIR/.git" ]; then
        info "Existing installation found — updating..."
        cd "$INSTALL_DIR"
        git pull --ff-only
        log "Updated to latest version"
    else
        info "Installing to $INSTALL_DIR..."
        if command -v git &>/dev/null; then
            git clone "$REPO_URL" "$INSTALL_DIR"
        else
            warn "git not found — downloading archive..."
            mkdir -p "$INSTALL_DIR"
            curl -sSL "${REPO_URL%.git}/archive/main.tar.gz" | tar xz --strip-components=1 -C "$INSTALL_DIR"
        fi
        log "Downloaded EC2 Sentinel"
    fi

    # Install Python deps
    cd "$INSTALL_DIR"
    $py_cmd -m pip install -r requirements.txt --quiet --break-system-packages 2>/dev/null || \
    $py_cmd -m pip install -r requirements.txt --quiet 2>/dev/null || \
    $py_cmd -m pip install -r requirements.txt --quiet --user
    log "Python dependencies installed"

    # Create default config if not present
    if [ ! -f "$INSTALL_DIR/config.yaml" ]; then
        cp "$INSTALL_DIR/config.example.yaml" "$INSTALL_DIR/config.yaml"
        log "Created config.yaml — edit this for your environment"
    else
        warn "config.yaml already exists — not overwriting"
    fi

    # Make scripts executable
    chmod +x "$INSTALL_DIR/sentinel.py"
    chmod +x "$INSTALL_DIR/scripts/"*.sh 2>/dev/null || true
    chmod +x "$INSTALL_DIR/install.sh"
    log "Made scripts executable"

    # Symlink for convenience
    if [ "$(id -u)" -eq 0 ]; then
        ln -sf "$INSTALL_DIR/sentinel.py" /usr/local/bin/ec2-sentinel
        log "Created symlink: ec2-sentinel -> $INSTALL_DIR/sentinel.py"
    fi

    echo ""
    log "${BOLD}Installation complete!${NC}"
    echo ""
    info "Quick start:"
    echo "   cd $INSTALL_DIR"
    echo "   vim config.yaml          # configure your services"
    echo "   python3 sentinel.py --once   # test it"
    echo ""
}

# ---------------------------------------------------------------------------
# systemd setup
# ---------------------------------------------------------------------------

setup_systemd() {
    install  # run install first

    if [ "$(id -u)" -ne 0 ]; then
        err "systemd setup requires root. Run with sudo."
        exit 1
    fi

    if ! command -v systemctl &>/dev/null; then
        err "systemd not found. Use cron instead:"
        echo "   */5 * * * * $INSTALL_DIR/sentinel.py --once --json >> /var/log/ec2-sentinel.json 2>&1"
        exit 1
    fi

    local py_path
    py_path=$(which python3 || which python)

    # Write unit file
    cat > "/etc/systemd/system/${SERVICE_NAME}.service" << EOF
[Unit]
Description=EC2 Sentinel — Instance Health Monitor
After=network.target
Wants=network.target

[Service]
Type=simple
ExecStart=${py_path} ${INSTALL_DIR}/sentinel.py --daemon --config ${INSTALL_DIR}/config.yaml
WorkingDirectory=${INSTALL_DIR}
Restart=always
RestartSec=10
StandardOutput=journal
StandardError=journal
SyslogIdentifier=${SERVICE_NAME}

# Hardening
NoNewPrivileges=true
ProtectSystem=strict
ReadWritePaths=/var/log /tmp
PrivateTmp=true

[Install]
WantedBy=multi-user.target
EOF

    systemctl daemon-reload
    systemctl enable "$SERVICE_NAME"
    systemctl start "$SERVICE_NAME"

    log "systemd service installed and started"
    info "Commands:"
    echo "   sudo systemctl status $SERVICE_NAME"
    echo "   sudo journalctl -u $SERVICE_NAME -f"
    echo "   sudo systemctl restart $SERVICE_NAME"
}

# ---------------------------------------------------------------------------
# Uninstall
# ---------------------------------------------------------------------------

uninstall() {
    echo ""
    warn "Uninstalling EC2 Sentinel..."

    if [ "$(id -u)" -eq 0 ]; then
        systemctl stop "$SERVICE_NAME" 2>/dev/null || true
        systemctl disable "$SERVICE_NAME" 2>/dev/null || true
        rm -f "/etc/systemd/system/${SERVICE_NAME}.service"
        systemctl daemon-reload 2>/dev/null || true
        rm -f /usr/local/bin/ec2-sentinel
    fi

    rm -rf "$INSTALL_DIR"
    rm -f /tmp/ec2_sentinel_*.json

    log "EC2 Sentinel uninstalled"
}

# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

case "${1:-}" in
    --systemd)    setup_systemd ;;
    --uninstall)  uninstall ;;
    *)            install ;;
esac
