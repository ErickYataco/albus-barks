#!/bin/bash

# Albus Barks systemd uninstaller for Raspberry Pi.
# Removes services/timers by default and leaves app files, user, and secrets intact.

set -euo pipefail

SERVICE_PREFIX="${SERVICE_PREFIX:-albus-barks}"
ALBUS_USER="${ALBUS_USER:-albus}"
ALBUS_PATH="${ALBUS_PATH:-/home/${ALBUS_USER}/albus-barks}"
ENV_FILE="/etc/default/${SERVICE_PREFIX}"
REMOVE_APP_DIR="${REMOVE_APP_DIR:-false}"
REMOVE_ENV_FILE="${REMOVE_ENV_FILE:-false}"
REMOVE_USER="${REMOVE_USER:-false}"

WEB_SERVICE="${SERVICE_PREFIX}-web.service"
DASHBOARD_SERVICE="${SERVICE_PREFIX}-dashboard.service"
CALENDAR_SYNC_SERVICE="${SERVICE_PREFIX}-calendar-sync.service"
CALENDAR_SYNC_TIMER="${SERVICE_PREFIX}-calendar-sync.timer"
JOB_SYNC_SERVICE="${SERVICE_PREFIX}-job-sync.service"
JOB_SYNC_TIMER="${SERVICE_PREFIX}-job-sync.timer"

if [ "$(id -u)" -ne 0 ]; then
    echo "Run with sudo: sudo ./uninstall_albus_service.sh"
    exit 1
fi

stop_disable_unit() {
    local unit="$1"
    echo "Stopping/disabling ${unit}"
    systemctl disable --now "${unit}" >/dev/null 2>&1 || true
    systemctl stop "${unit}" >/dev/null 2>&1 || true
}

remove_unit_file() {
    local unit="$1"
    local path="/etc/systemd/system/${unit}"
    if [ -f "${path}" ]; then
        echo "Removing ${path}"
        rm -f "${path}"
    fi
}

echo "Uninstalling Albus Barks systemd units with prefix: ${SERVICE_PREFIX}"

stop_disable_unit "${JOB_SYNC_TIMER}"
stop_disable_unit "${CALENDAR_SYNC_TIMER}"
stop_disable_unit "${DASHBOARD_SERVICE}"
stop_disable_unit "${WEB_SERVICE}"
stop_disable_unit "${JOB_SYNC_SERVICE}"
stop_disable_unit "${CALENDAR_SYNC_SERVICE}"

remove_unit_file "${JOB_SYNC_TIMER}"
remove_unit_file "${JOB_SYNC_SERVICE}"
remove_unit_file "${CALENDAR_SYNC_TIMER}"
remove_unit_file "${CALENDAR_SYNC_SERVICE}"
remove_unit_file "${DASHBOARD_SERVICE}"
remove_unit_file "${WEB_SERVICE}"

if [ "${REMOVE_ENV_FILE}" = "true" ] && [ -f "${ENV_FILE}" ]; then
    echo "Removing ${ENV_FILE}"
    rm -f "${ENV_FILE}"
else
    echo "Keeping env file: ${ENV_FILE}"
fi

if [ "${REMOVE_APP_DIR}" = "true" ] && [ -d "${ALBUS_PATH}" ]; then
    echo "Removing app directory: ${ALBUS_PATH}"
    rm -rf "${ALBUS_PATH}"
else
    echo "Keeping app directory: ${ALBUS_PATH}"
fi

if [ "${REMOVE_USER}" = "true" ] && id -u "${ALBUS_USER}" >/dev/null 2>&1; then
    echo "Removing user: ${ALBUS_USER}"
    userdel "${ALBUS_USER}" || true
else
    echo "Keeping user: ${ALBUS_USER}"
fi

systemctl daemon-reload
systemctl reset-failed >/dev/null 2>&1 || true

echo
echo "Albus Barks services removed."
echo "To also remove secrets/env, rerun with: sudo REMOVE_ENV_FILE=true ./uninstall_albus_service.sh"
echo "To also remove the app folder, rerun with: sudo REMOVE_APP_DIR=true ./uninstall_albus_service.sh"
