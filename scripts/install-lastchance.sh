#!/bin/bash
set -e

# Must be run as root for systemd operations
if [[ $EUID -ne 0 ]]; then
    echo "Error: This script must be run as root (use sudo)"
    exit 1
fi

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
SYSTEMD_DIR="/etc/systemd/system"
DEFAULT_TIME="03:00:00"
DEFAULT_WORKDIR="/opt/kometa"
RUN_TIME="${1:-$DEFAULT_TIME}"
WORK_DIR="${2:-$DEFAULT_WORKDIR}"

# Validate time format (HH:MM or HH:MM:SS)
if ! [[ "$RUN_TIME" =~ ^[0-9]{2}:[0-9]{2}(:[0-9]{2})?$ ]]; then
    echo "Error: Invalid time format '$RUN_TIME'. Use HH:MM or HH:MM:SS"
    exit 1
fi

# Normalize to HH:MM:SS
if [[ "$RUN_TIME" =~ ^[0-9]{2}:[0-9]{2}$ ]]; then
    RUN_TIME="${RUN_TIME}:00"
fi

# Validate working directory exists
if [ ! -d "$WORK_DIR" ]; then
    echo "Error: Working directory '$WORK_DIR' does not exist"
    exit 1
fi

echo "=== Last Chance Cleanup - systemd installer ==="
echo "Scheduled time: $RUN_TIME on the 1st of each month"
echo "Working directory: $WORK_DIR"

# Install Python dependencies (uv if available, otherwise pip3)
echo "Installing Python dependencies..."
if command -v uv &>/dev/null; then
    uv pip install -q -r "$SCRIPT_DIR/requirements.txt" --system
else
    pip3 install -q -r "$SCRIPT_DIR/requirements.txt"
fi

# Generate timer with configured time
echo "Generating timer unit..."
sed "s/%LASTCHANCE_TIME%/$RUN_TIME/g" "$SCRIPT_DIR/lastchance.timer" > "$SYSTEMD_DIR/lastchance.timer"

# Generate service with configured working directory
echo "Generating service unit..."
sed "s|%LASTCHANCE_WORKDIR%|$WORK_DIR|g" "$SCRIPT_DIR/lastchance.service" > "$SYSTEMD_DIR/lastchance.service"

# Reload and enable
systemctl daemon-reload
systemctl enable lastchance.timer
systemctl restart lastchance.timer

echo ""
echo "Done! Timer is active:"
systemctl status lastchance.timer --no-pager
echo ""
echo "Useful commands:"
echo "  systemctl list-timers lastchance*             # Check next run"
echo "  systemctl start lastchance.service            # Run cleanup now"
echo "  journalctl -u lastchance.service -f           # Watch logs"
echo "  python3 $WORK_DIR/config/scripts/lastchance.py --env-file $WORK_DIR/config/.env --dry-run"
echo ""
echo "To change settings:"
echo "  sudo $SCRIPT_DIR/install-lastchance.sh <TIME> <WORKDIR>"
echo "  sudo $SCRIPT_DIR/install-lastchance.sh 05:30"
echo "  sudo $SCRIPT_DIR/install-lastchance.sh 03:00 /srv/kometa"
