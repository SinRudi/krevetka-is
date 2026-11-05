#!/bin/bash
cd ~/my-apps
source venv/bin/activate
python ~/my-apps/sushi_pos/app.py
echo ""
echo "Сервер остановлен. Нажмите Enter..."
read
