#!/bin/bash

# Albus Barks systemd installer for Raspberry Pi.
# Installs from the public GitHub repository and creates systemd services.

set -euo pipefail

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

# Logging configuration
LOG_DIR="${LOG_DIR:-/var/log/albus_install}"
LOG_FILE="${LOG_DIR}/albus_install_$(date +%Y%m%d_%H%M%S).log"
VERBOSE="${VERBOSE:-false}"

REPO_URL="${REPO_URL:-https://github.com/ErickYataco/albus-barks.git}"
ALBUS_USER="${ALBUS_USER:-albus}"
ALBUS_PATH="${ALBUS_PATH:-/home/${ALBUS_USER}/albus-barks}"
SERVICE_PREFIX="${SERVICE_PREFIX:-albus-barks}"
PYTHON_BIN="${PYTHON_BIN:-${ALBUS_PATH}/.venv/bin/python}"
UVICORN_BIN="${UVICORN_BIN:-${ALBUS_PATH}/.venv/bin/uvicorn}"
WEB_PORT="${WEB_PORT:-5582}"
UPDATE_REPO="${UPDATE_REPO:-true}"
SKIP_APT="${SKIP_APT:-false}"
CONFIGURE_INTERFACES="${CONFIGURE_INTERFACES:-true}"
CONFLICTS_SERVICE="${CONFLICTS_SERVICE:-}"

WEB_SERVICE="${SERVICE_PREFIX}-web.service"
DASHBOARD_SERVICE="${SERVICE_PREFIX}-dashboard.service"
KILL_PORT_SCRIPT="${ALBUS_PATH}/kill_port_${WEB_PORT}.sh"

log() {
    local level=$1
    shift
    local message="[$(date '+%Y-%m-%d %H:%M:%S')] [$level] $*"
    echo -e "${message}" >> "${LOG_FILE}"
    if [ "${VERBOSE}" = true ] || [ "${level}" != "DEBUG" ]; then
        case "${level}" in
            "ERROR") echo -e "${RED}${message}${NC}" ;;
            "SUCCESS") echo -e "${GREEN}${message}${NC}" ;;
            "WARNING") echo -e "${YELLOW}${message}${NC}" ;;
            "INFO") echo -e "${BLUE}${message}${NC}" ;;
            *) echo -e "${message}" ;;
        esac
    fi
}

run() {
    log "INFO" "$*"
    "$@"
}

configure_interfaces() {
    if [ "${CONFIGURE_INTERFACES}" != "true" ]; then
        log "INFO" "Skipping SPI/I2C configuration"
        return 0
    fi

    if ! command -v raspi-config >/dev/null 2>&1; then
        log "WARNING" "raspi-config not found; skipping SPI/I2C configuration"
        return 0
    fi

    log "INFO" "Enabling SPI and I2C interfaces"
    run raspi-config nonint do_spi 0
    run raspi-config nonint do_i2c 0
    log "SUCCESS" "SPI and I2C interfaces enabled"
}

setup_user() {
    if ! id -u "${ALBUS_USER}" >/dev/null 2>&1; then
        log "INFO" "Creating Albus user: ${ALBUS_USER}"
        run adduser --disabled-password --gecos "" "${ALBUS_USER}"
    else
        log "INFO" "Using existing user: ${ALBUS_USER}"
    fi

    for group in spi gpio i2c; do
        if getent group "${group}" >/dev/null 2>&1; then
            run usermod -a -G "${group}" "${ALBUS_USER}"
        else
            log "WARNING" "Group ${group} not found; skipping"
        fi
    done
}

if [ "$(id -u)" -ne 0 ]; then
    echo "Run with sudo: sudo ./install_albus_service.sh"
    exit 1
fi
if [ "${ALBUS_USER}" = "root" ]; then
    echo "ALBUS_USER cannot be root. Use a dedicated user such as albus."
    exit 1
fi
mkdir -p "${LOG_DIR}"

log "INFO" "Installing Albus Barks services from: ${ALBUS_PATH}"
log "INFO" "Log file: ${LOG_FILE}"

if [ "${SKIP_APT}" != "true" ]; then
    log "INFO" "Installing system dependencies"
    run apt-get update
    run apt-get install -y git lsof python3-venv python3-pip python3-pil python3-gpiozero python3-lgpio python3-rpi.gpio python3-spidev
fi

setup_user
configure_interfaces

if [ ! -d "${ALBUS_PATH}" ]; then
    log "INFO" "Cloning ${REPO_URL}"
    run install -d -o "${ALBUS_USER}" -g "${ALBUS_USER}" "${ALBUS_PATH}"
    run sudo -u "${ALBUS_USER}" git clone "${REPO_URL}" "${ALBUS_PATH}"
elif [ -d "${ALBUS_PATH}/.git" ] && [ "${UPDATE_REPO}" = "true" ]; then
    log "INFO" "Updating ${ALBUS_PATH}"
    run chown -R "${ALBUS_USER}:${ALBUS_USER}" "${ALBUS_PATH}"
    run sudo -u "${ALBUS_USER}" git -C "${ALBUS_PATH}" pull --ff-only
fi

if [ ! -f "${ALBUS_PATH}/requirements.txt" ]; then
    log "ERROR" "requirements.txt not found in ${ALBUS_PATH}"
    exit 1
fi

if [ ! -x "${PYTHON_BIN}" ]; then
    log "INFO" "Creating virtual environment at ${ALBUS_PATH}/.venv"
    run sudo -u "${ALBUS_USER}" /usr/bin/python3 -m venv --system-site-packages "${ALBUS_PATH}/.venv"
fi

log "INFO" "Installing Python dependencies"
run sudo -u "${ALBUS_USER}" "${PYTHON_BIN}" -m pip install --upgrade pip
run sudo -u "${ALBUS_USER}" "${PYTHON_BIN}" -m pip install -r "${ALBUS_PATH}/requirements.txt"

cat > "${KILL_PORT_SCRIPT}" << EOF
#!/bin/bash
PORT=${WEB_PORT}
PIDS=\$(lsof -t -i:\${PORT})
if [ -n "\${PIDS}" ]; then
    echo "Killing PIDs using port \${PORT}: \${PIDS}"
    kill -9 \${PIDS}
fi
EOF
chmod +x "${KILL_PORT_SCRIPT}"
chown "${ALBUS_USER}:${ALBUS_USER}" "${KILL_PORT_SCRIPT}"

CONFLICTS_LINE=""
if [ -n "${CONFLICTS_SERVICE}" ]; then
    CONFLICTS_LINE="Conflicts=${CONFLICTS_SERVICE}"
fi

cat > "/etc/systemd/system/${WEB_SERVICE}" << EOF
[Unit]
Description=Albus Barks Web App
After=network-online.target
Wants=network-online.target
${CONFLICTS_LINE}

[Service]
ExecStart=${UVICORN_BIN} web.main:app --host 0.0.0.0 --port ${WEB_PORT}
WorkingDirectory=${ALBUS_PATH}
StandardOutput=inherit
StandardError=inherit
Restart=always
User=${ALBUS_USER}

[Install]
WantedBy=multi-user.target
EOF

cat > "/etc/systemd/system/${DASHBOARD_SERVICE}" << EOF
[Unit]
Description=Albus Barks E-Ink Dashboard
After=network-online.target ${WEB_SERVICE}
Wants=network-online.target ${WEB_SERVICE}
${CONFLICTS_LINE}

[Service]
ExecStart=${PYTHON_BIN} -m dashboard.main
WorkingDirectory=${ALBUS_PATH}
StandardOutput=inherit
StandardError=inherit
Restart=always
User=${ALBUS_USER}

[Install]
WantedBy=multi-user.target
EOF

run chown -R "${ALBUS_USER}:${ALBUS_USER}" "${ALBUS_PATH}"
run systemctl daemon-reload
run systemctl enable "${WEB_SERVICE}"
run systemctl enable "${DASHBOARD_SERVICE}"

log "SUCCESS" "Installed and enabled:"
echo "  ${WEB_SERVICE}"
echo "  ${DASHBOARD_SERVICE}"
echo
echo "Start them with:"
echo "  sudo systemctl start ${WEB_SERVICE}"
echo "  sudo systemctl start ${DASHBOARD_SERVICE}"
echo
echo "If another app owns port ${WEB_PORT} or the Waveshare EPD, stop it first."
echo "For Bjorn, run: sudo systemctl stop bjorn.service"
