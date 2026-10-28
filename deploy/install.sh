#!/bin/bash
# Ejecutar como root dentro de EC2 mediante SSM Run Command.
set -euo pipefail
cd "$(dirname "$0")/.."
test "$(id -u)" -eq 0
test -s /etc/tickets/origin-secret
dnf install -y python3.11 python3.11-pip nginx
id tickets >/dev/null 2>&1 || useradd --system --home-dir /opt/tickets --shell /sbin/nologin tickets
install -d -m 750 -o root -g tickets /opt/tickets/backend
cp backend/*.py backend/requirements.txt /opt/tickets/backend/
python3.11 -m venv /opt/tickets/venv
/opt/tickets/venv/bin/pip install --no-cache-dir -r /opt/tickets/backend/requirements.txt
chown -R root:tickets /opt/tickets
chmod -R g+rX,o-rwx /opt/tickets
install -m 600 deploy/service.env /etc/tickets.env
install -d -m 755 /var/www/tickets
cp web/* /var/www/tickets/
chmod 644 /var/www/tickets/*
python3.11 - <<'PY'
from pathlib import Path
secret = Path('/etc/tickets/origin-secret').read_text().strip()
source = Path('deploy/nginx.conf').read_text()
Path('/etc/nginx/nginx.conf').write_text(source.replace('__ORIGIN_SECRET__', secret))
PY
chmod 600 /etc/nginx/nginx.conf
install -m 644 deploy/tickets.service /etc/systemd/system/tickets.service
install -d -m 755 /etc/systemd/journald.conf.d
cat > /etc/systemd/journald.conf.d/tickets.conf <<'EOF'
[Journal]
SystemMaxUse=100M
RuntimeMaxUse=50M
MaxRetentionSec=7day
EOF
systemctl restart systemd-journald
nginx -t
systemctl daemon-reload
systemctl enable tickets nginx
systemctl restart tickets
systemctl restart nginx
for attempt in $(seq 1 30); do
  if curl -fsS http://127.0.0.1:8000/healthz; then
    printf '\nServicio Flask listo.\n'
    exit 0
  fi
  sleep 2
done
journalctl -u tickets -n 30 --no-pager
exit 1
