#!/bin/bash
# ==============================================================================
# Pickle Telegram Connector 1-Click Deployment Script for Linux / RHEL / Ubuntu
# ==============================================================================
set -e

INSTALL_DIR="/opt/pickle-telegram-connector"
SERVICE_NAME="pickle-telegram-connector.service"

echo "[+] Starting Pickle Telegram Connector deployment..."

if [ "$EUID" -ne 0 ]; then
    echo "[-] Please run as root (or use sudo)."
    exit 1
fi

echo "[+] Target installation directory: ${INSTALL_DIR}"
mkdir -p "${INSTALL_DIR}"
cp -r pyproject.toml pickle_tg bin systemd docker config scripts "${INSTALL_DIR}/"

if [ ! -f "${INSTALL_DIR}/config/local.json" ]; then
    echo "[!] config/local.json not found. Copying template..."
    cp "${INSTALL_DIR}/config/local.json.template" "${INSTALL_DIR}/config/local.json"
    echo "[!] Please edit ${INSTALL_DIR}/config/local.json with your actual bot token."
fi

echo "[+] Registering systemd service..."
cp "${INSTALL_DIR}/systemd/${SERVICE_NAME}" /etc/systemd/system/
systemctl daemon-reload
systemctl enable "${SERVICE_NAME}"

echo "[✓] Deployment complete! Start the service with:"
echo "    sudo systemctl start ${SERVICE_NAME}"
echo "    sudo journalctl -u ${SERVICE_NAME} -f"
