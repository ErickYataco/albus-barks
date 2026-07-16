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
REQUIRE_GOOGLE_CALENDAR="${REQUIRE_GOOGLE_CALENDAR:-true}"
PROMPT_SECRETS="${PROMPT_SECRETS:-true}"
PROMPT_INTERVALS="${PROMPT_INTERVALS:-true}"
INPUT_BRIGHT_DATA_API_TOKEN="${BRIGHT_DATA_API_TOKEN:-}"
INPUT_OPENAI_API_KEY="${OPENAI_API_KEY:-}"
CALENDAR_SYNC_INTERVAL="${CALENDAR_SYNC_INTERVAL:-5min}"
JOB_SYNC_INTERVAL="${JOB_SYNC_INTERVAL:-2d}"

WEB_SERVICE="${SERVICE_PREFIX}-web.service"
DASHBOARD_SERVICE="${SERVICE_PREFIX}-dashboard.service"
CALENDAR_SYNC_SERVICE="${SERVICE_PREFIX}-calendar-sync.service"
CALENDAR_SYNC_TIMER="${SERVICE_PREFIX}-calendar-sync.timer"
JOB_SYNC_SERVICE="${SERVICE_PREFIX}-job-sync.service"
JOB_SYNC_TIMER="${SERVICE_PREFIX}-job-sync.timer"
ENV_FILE="/etc/default/${SERVICE_PREFIX}"

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

load_env_file() {
    if [ -f "${ENV_FILE}" ]; then
        set -a
        # shellcheck disable=SC1090
        . "${ENV_FILE}"
        set +a
    fi
}

secret_is_blank() {
    local value="${1:-}"
    [ -z "${value}" ] || [ "${value}" = "replace_me" ] || [ "${value}" = "your_bright_data_token" ] || [ "${value}" = "your_openai_api_key" ]
}

set_env_value() {
    local key="$1"
    local value="$2"
    local tmp_file
    tmp_file="$(mktemp)"

    if [ -f "${ENV_FILE}" ]; then
        awk -v key="${key}" -v value="${value}" '
            BEGIN { found = 0 }
            $0 ~ "^" key "=" {
                print key "=" value
                found = 1
                next
            }
            { print }
            END {
                if (!found) {
                    print key "=" value
                }
            }
        ' "${ENV_FILE}" > "${tmp_file}"
    else
        echo "${key}=${value}" > "${tmp_file}"
    fi

    install -m 600 "${tmp_file}" "${ENV_FILE}"
    rm -f "${tmp_file}"
}

prompt_secret() {
    local key="$1"
    local label="$2"
    local current_value="${!key:-}"
    local value

    if ! secret_is_blank "${current_value}"; then
        log "INFO" "${key} already configured"
        return 0
    fi

    if [ "${PROMPT_SECRETS}" != "true" ] || [ ! -t 0 ]; then
        log "WARNING" "${key} is empty. Add it to ${ENV_FILE} before running the related sync."
        return 0
    fi

    echo
    echo "${label}"
    read -r -s -p "Enter ${key} (leave blank to skip for now): " value
    echo

    if [ -n "${value}" ]; then
        set_env_value "${key}" "${value}"
        # shellcheck disable=SC2034
        printf -v "${key}" "%s" "${value}"
        log "SUCCESS" "${key} saved to ${ENV_FILE}"
    else
        log "WARNING" "${key} left empty"
    fi
}

prompt_service_secrets() {
    load_env_file

    if secret_is_blank "${BRIGHT_DATA_API_TOKEN:-}" && ! secret_is_blank "${INPUT_BRIGHT_DATA_API_TOKEN}"; then
        set_env_value "BRIGHT_DATA_API_TOKEN" "${INPUT_BRIGHT_DATA_API_TOKEN}"
        BRIGHT_DATA_API_TOKEN="${INPUT_BRIGHT_DATA_API_TOKEN}"
    fi

    if secret_is_blank "${OPENAI_API_KEY:-}" && ! secret_is_blank "${INPUT_OPENAI_API_KEY}"; then
        set_env_value "OPENAI_API_KEY" "${INPUT_OPENAI_API_KEY}"
        OPENAI_API_KEY="${INPUT_OPENAI_API_KEY}"
    fi

    prompt_secret "BRIGHT_DATA_API_TOKEN" "Bright Data token is used by the LinkedIn job sync."
    prompt_secret "OPENAI_API_KEY" "OpenAI API key is used to score LinkedIn jobs for relevance."
}

prompt_interval() {
    local key="$1"
    local label="$2"
    local current_value="${!key:-}"
    local value

    if [ "${PROMPT_INTERVALS}" != "true" ] || [ ! -t 0 ]; then
        log "INFO" "${key}=${current_value}"
        return 0
    fi

    echo
    read -r -p "${label} [${current_value}]: " value
    if [ -n "${value}" ]; then
        # shellcheck disable=SC2034
        printf -v "${key}" "%s" "${value}"
    fi
    log "INFO" "${key}=${!key}"
}

prompt_timer_intervals() {
    prompt_interval "CALENDAR_SYNC_INTERVAL" "How often should Google Calendar sync run? Use systemd time syntax like 5min, 30min, 1h"
    prompt_interval "JOB_SYNC_INTERVAL" "How often should LinkedIn job sync run? Use systemd time syntax like 12h, 1d, 2d"
}

show_google_file_help() {
    echo
    echo "Google Calendar files required before services are installed:"
    echo "  ${ALBUS_PATH}/config/google_credentials.json  OAuth Desktop app client from Google Cloud"
    echo "  ${ALBUS_PATH}/config/google_token.json        Authorized Calendar read-only user token"
    echo "Docs:"
    echo "  https://developers.google.com/workspace/guides/create-credentials"
    echo "  https://developers.google.com/calendar/api/quickstart/python"
    echo
}

require_google_calendar_files() {
    load_env_file

    if [ "${REQUIRE_GOOGLE_CALENDAR}" != "true" ]; then
        log "WARNING" "Google Calendar file check skipped because REQUIRE_GOOGLE_CALENDAR=false"
        return 0
    fi

    local credentials_file="${ALBUS_PATH}/config/google_credentials.json"
    local token_file="${ALBUS_PATH}/config/google_token.json"

    if [ ! -f "${credentials_file}" ]; then
        log "ERROR" "Missing Google credentials file: ${credentials_file}"
        log "ERROR" "Copy it into ${ALBUS_PATH}/config/, then rerun the installer."
        show_google_file_help
        exit 1
    fi

    if [ ! -f "${token_file}" ]; then
        log "ERROR" "Missing Google token file: ${token_file}"
        log "ERROR" "Create/copy it into ${ALBUS_PATH}/config/, then rerun the installer."
        show_google_file_help
        exit 1
    fi

    log "SUCCESS" "Google Calendar credentials found: ${credentials_file}"
    log "SUCCESS" "Google Calendar token found: ${token_file}"
}

require_alert_config_file() {
    load_env_file

    local config_file="${ALBUS_PATH}/config/alerts.json"

    if [ ! -f "${config_file}" ]; then
        log "ERROR" "Missing alert config file: ${config_file}"
        log "ERROR" "Copy ${ALBUS_PATH}/config/alerts.example.json to ${ALBUS_PATH}/config/alerts.json, edit it, then rerun the installer."
        exit 1
    fi

    log "SUCCESS" "Alert config found: ${config_file}"
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
    run apt-get install -y git python3-venv python3-pip python3-pil python3-gpiozero python3-lgpio python3-rpi.gpio python3-spidev
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

if [ ! -f "${ENV_FILE}" ]; then
    cat > "${ENV_FILE}" << EOF
# Albus Barks service configuration.
# Default file locations are:
#   ${ALBUS_PATH}/config/google_credentials.json
#   ${ALBUS_PATH}/config/google_token.json
#   ${ALBUS_PATH}/config/alerts.json
# Fill these before running the LinkedIn job sync.
BRIGHT_DATA_API_TOKEN=
OPENAI_API_KEY=
EOF
    chmod 600 "${ENV_FILE}"
fi

require_google_calendar_files
require_alert_config_file
prompt_service_secrets
prompt_timer_intervals

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
EnvironmentFile=-${ENV_FILE}
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
EnvironmentFile=-${ENV_FILE}
ExecStart=${PYTHON_BIN} -m dashboard.main
WorkingDirectory=${ALBUS_PATH}
StandardOutput=inherit
StandardError=inherit
Restart=always
User=${ALBUS_USER}

[Install]
WantedBy=multi-user.target
EOF

cat > "/etc/systemd/system/${CALENDAR_SYNC_SERVICE}" << EOF
[Unit]
Description=Albus Barks Google Calendar Sync
After=network-online.target
Wants=network-online.target

[Service]
Type=oneshot
EnvironmentFile=-${ENV_FILE}
ExecStart=${PYTHON_BIN} -m background.calendar_sync
WorkingDirectory=${ALBUS_PATH}
StandardOutput=journal
StandardError=journal
User=${ALBUS_USER}
EOF

cat > "/etc/systemd/system/${CALENDAR_SYNC_TIMER}" << EOF
[Unit]
Description=Run Albus Barks Google Calendar Sync Every ${CALENDAR_SYNC_INTERVAL}

[Timer]
OnBootSec=2min
OnUnitActiveSec=${CALENDAR_SYNC_INTERVAL}
Unit=${CALENDAR_SYNC_SERVICE}

[Install]
WantedBy=timers.target
EOF

cat > "/etc/systemd/system/${JOB_SYNC_SERVICE}" << EOF
[Unit]
Description=Albus Barks Bright Data LinkedIn Job Sync
After=network-online.target
Wants=network-online.target

[Service]
Type=oneshot
EnvironmentFile=-${ENV_FILE}
ExecStart=${PYTHON_BIN} -m background.job_sync
WorkingDirectory=${ALBUS_PATH}
StandardOutput=journal
StandardError=journal
User=${ALBUS_USER}
EOF

cat > "/etc/systemd/system/${JOB_SYNC_TIMER}" << EOF
[Unit]
Description=Run Albus Barks Bright Data LinkedIn Job Sync Every ${JOB_SYNC_INTERVAL}

[Timer]
OnBootSec=3min
OnUnitActiveSec=${JOB_SYNC_INTERVAL}
Unit=${JOB_SYNC_SERVICE}

[Install]
WantedBy=timers.target
EOF

run chown -R "${ALBUS_USER}:${ALBUS_USER}" "${ALBUS_PATH}"
run systemctl daemon-reload
run systemctl enable "${WEB_SERVICE}"
run systemctl enable "${DASHBOARD_SERVICE}"
run systemctl enable "${CALENDAR_SYNC_TIMER}"
run systemctl enable "${JOB_SYNC_TIMER}"

log "SUCCESS" "Installed and enabled:"
echo "  ${WEB_SERVICE}"
echo "  ${DASHBOARD_SERVICE}"
echo "  ${CALENDAR_SYNC_TIMER} (${CALENDAR_SYNC_INTERVAL})"
echo "  ${JOB_SYNC_TIMER} (${JOB_SYNC_INTERVAL})"
echo
echo "Start them with:"
echo "  sudo systemctl start ${WEB_SERVICE}"
echo "  sudo systemctl start ${DASHBOARD_SERVICE}"
echo "  sudo systemctl start ${CALENDAR_SYNC_TIMER}"
echo "  sudo systemctl start ${JOB_SYNC_TIMER}"
echo
echo "If another app owns port ${WEB_PORT} or the Waveshare EPD, stop it first."
echo "For Bjorn, run: sudo systemctl stop bjorn.service"
