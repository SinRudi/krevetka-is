import sqlite3
import os
import re

DB_PATH = 'sushi.db'
UPLOAD_DIR = 'static/uploads'

print("="*50)
print("📸 ПРОВЕРКА ФОТО И БАЗЫ ДАННЫХ")
print("="*50)

# 1. Смотрим, какие файлы реально есть на диске
if os.path.exists(UPLOAD_DIR):
    files_on_disk = os.listdir(UPLOAD_DIR)
    print(f"Файлов в папке {UPLOAD_DIR}: {len(files_on_disk)}")
    if len(files_on_disk) > 0:
        print("Примеры:", ", ".join(files_on_disk[:5]))
else:
    print(f"❌ Папка {UPLOAD_DIR} не найдена!")
    files_on_disk = []

# 2. Чистим базу
db = sqlite3.connect(DB_PATH)
db.row_factory = sqlite3.Row
rows = db.execute("SELECT id, name, image FROM menu").fetchall()

fixed_count = 0
missing_files = []

for r in rows:
    img = r['image']
    if not img:
        continue
    
    orig_img = img
    # Убираем лишние префиксы, если они есть в базе
    img = img.replace('/static/uploads/', '').replace('static/uploads/', '')
    img = os.path.basename(img) # Оставляем только имя файла
    
    if img != orig_img:
        db.execute("UPDATE menu SET image=? WHERE id=?", (img, r['id']))
        fixed_count += 1
        
    if img and img != 'None' and img not in files_on_disk:
        missing_files.append(f"Блюдо '{r['name']}' (файл {img} отсутствует)")

db.commit()
db.close()

if fixed_count > 0:
    print(f"\n✅ Исправлено путей в базе: {fixed_count}")

if missing_files:
    print(f"\n⚠️ ВНИМАНИЕ! Эти файлы записаны в базе, но физически отсутствуют на диске:")
    for m in missing_files:
        print(" -", m)
    print("\n👉 Решение: Зайди в админку и загрузи фото для этих блюд заново.")
else:
    print("\n✅ Все файлы, указанные в базе, физически присутствуют на диске!")

print("="*50)