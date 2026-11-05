import time, sqlite3, os, sys
DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'sushi.db')
last_order_id = 0

def print_ticket(order):
    # ЗДЕСЬ МОЖНО ПОДКЛЮЧИТЬ РЕАЛЬНЫЙ ПРИНТЕР (python-escpos)
    # Сейчас мы просто выводим в консоль
    print("\n" + "="*30)
    print(f"   НОВЫЙ ЗАКАЗ #{order['id']}")
    print("="*30)
    print(f"Время: {order['created_at']}")
    print("-"*30)
    for item in order['items']:
        print(f"{item['name']} x{item['qty']}")
    print("-"*30 + "\n")

print("🖨️ Агент печати запущен. Ожидание заказов...")
while True:
    try:
        conn = sqlite3.connect(DB_PATH)
        conn.row_factory = sqlite3.Row
        orders = conn.execute("SELECT * FROM orders WHERE status='new' AND id > ?", (last_order_id,)).fetchall()
        for o in orders:
            items = conn.execute("SELECT * FROM order_items WHERE order_id=?", (o['id'],)).fetchall()
            print_ticket({"id": o['id'], "created_at": o['created_at'], "items": [dict(i) for i in items]})
            last_order_id = max(last_order_id, o['id'])
        conn.close()
    except Exception as e:
        print("Ошибка:", e)
    time.sleep(5)
