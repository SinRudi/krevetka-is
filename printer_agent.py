#!/usr/bin/env python3
import sqlite3
import time
import os

DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'sushi.db')
last_printed_order_id = 0

print("🖨️ АГЕНТ ПЕЧАТИ ЗАПУЩЕН. Ожидание новых заказов...")
print("(Для выхода нажмите Ctrl+C)")

while True:
    try:
        conn = sqlite3.connect(DB_PATH)
        conn.row_factory = sqlite3.Row
        # Ищем заказы, которые появились после последнего напечатанного
        orders = conn.execute("SELECT * FROM orders WHERE id > ? AND status='new' ORDER BY id", (last_printed_order_id,)).fetchall()
        for o in orders:
            items = conn.execute("SELECT * FROM order_items WHERE order_id=?", (o['id'],)).fetchall()
            
            # Формируем чек
            print("\n" + "="*40)
            print(f"       ЗАКАЗ #{o['id']}")
            print("="*40)
            print(f"Время: {o['created_at']}")
            print(f"Тип: {o['delivery_type']}")
            if o['address']: print(f"Адрес: {o['address']}")
            print("-"*40)
            for i in items:
                print(f"{i['name']} x{i['qty']} = {i['price']*i['qty']} руб.")
            print("-"*40)
            print(f"ИТОГО: {o['total']} руб.")
            if o['comment']: print(f"КОММ: {o['comment']}")
            print("="*40 + "\n")
            
            # ЗДЕСЬ МОЖНО ПОДКЛЮЧИТЬ РЕАЛЬНЫЙ ПРИНТЕР:
            # import escpos.printer
            # printer = escpos.printer.Usb(0x0416, 0x5011) # ID вашего принтера
            # printer.text(f"ЗАКАЗ #{o['id']}\n")
            # printer.cut()
            
            last_printed_order_id = o['id']
        conn.close()
    except Exception as e:
        pass
    time.sleep(3)
