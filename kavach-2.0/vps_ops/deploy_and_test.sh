#!/bin/bash
set -eu

echo "=== VPS cleanup + deploy ==="

# 1. Disable duplicate telegram service
sudo systemctl stop telegrambot.service 2>/dev/null || true
sudo systemctl disable telegrambot.service 2>/dev/null || true
sudo systemctl mask telegrambot.service 2>/dev/null || true
sudo rm -f /etc/systemd/system/telegrambot.service

# 2. Truncate bloated log
truncate -s 0 /home/ubuntu/my_telegram_bot/telegram_bot.log 2>/dev/null || true

# 3. Remove test Stockmock deploy (not needed on VPS)
rm -rf /home/ubuntu/stockmock-batman-src 2>/dev/null || true

# 4. Deploy fixed bot + notifier
cp /home/ubuntu/vps_ops/bot.py /home/ubuntu/my_telegram_bot/bot.py
cp /home/ubuntu/vps_ops/notifier.py /home/ubuntu/my_telegram_bot/notifier.py

# 5. Logrotate
sudo cp /home/ubuntu/vps_ops/logrotate-telegram /etc/logrotate.d/vps-telegram

# 6. Passwordless sudo for monitor restarts
sudo cp /home/ubuntu/vps_ops/sudoers-vps-monitor /etc/sudoers.d/vps-monitor
sudo chmod 440 /etc/sudoers.d/vps-monitor

# 7. Systemd units
sudo cp /home/ubuntu/vps_ops/my_telegram_bot.service /etc/systemd/system/my_telegram_bot.service
sudo cp /home/ubuntu/vps_ops/vps-monitor.service /etc/systemd/system/vps-monitor.service
sudo systemctl daemon-reload

# 8. venv for vps_ops
cd /home/ubuntu/vps_ops
python3 -m venv venv
./venv/bin/pip install -q --upgrade pip
./venv/bin/pip install -q python-dotenv python-telegram-bot requests

# 9. Restart services
sudo systemctl enable my_telegram_bot vps-monitor
sudo systemctl restart my_telegram_bot
sleep 3
sudo systemctl restart vps-monitor

echo "=== Service status ==="
systemctl is-active my_telegram_bot vps-monitor
systemctl is-enabled my_telegram_bot vps-monitor 2>/dev/null || true

echo "=== Running stability test (10 iterations) ==="
cd /home/ubuntu/vps_ops
./venv/bin/python run_stability_test.py 10

echo "=== DONE ==="
