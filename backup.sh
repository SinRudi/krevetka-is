#!/bin/bash
# Скрипт резервного копирования базы данных Креветки
DB_PATH="$HOME/my-apps/sushi_pos/sushi.db"
BACKUP_DIR="$HOME/my-apps/sushi_pos/backups"
DATE=$(date +"%Y-%m-%d_%H-%M-%S")
DEST="$BACKUP_DIR/sushi_$DATE.db"

# Создаем папку, если ее нет
mkdir -p "$BACKUP_DIR"

# Копируем базу
cp "$DB_PATH" "$DEST"

# Удаляем бэкапы старше 30 дней, чтобы не забивать диск
find "$BACKUP_DIR" -type f -name "sushi_*.db" -mtime +30 -delete

echo "Бэкап создан: $DEST"
