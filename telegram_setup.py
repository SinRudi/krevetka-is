import urllib.request
import json

print("="*55)
print("🤖 НАСТРОЙКА TELEGRAM-БОТА")
print("="*55)
print("1. Откройте Telegram, найдите бота @BotFather")
print("2. Напишите ему /newbot и придумайте имя (например, SushiKrevetkaBot)")
print("3. Он выдаст вам ТОКЕН (длинная строка с двоеточием).")
token = input("\n👉 Вставьте ТОКЕН сюда и нажмите Enter: ").strip()

print("\nТеперь найдите своего нового бота в Telegram и напишите ему ЛЮБОЕ сообщение (например, 'Привет').")
input("Когда напишете, нажмите Enter здесь...")

url = f"https://api.telegram.org/bot{token}/getUpdates"
try:
    req = urllib.request.urlopen(url)
    data = json.loads(req.read().decode())
    if data['result']:
        chat_id = data['result'][-1]['message']['chat']['id']
        print("\n" + "="*55)
        print(f"✅ УСПЕХ! Ваш Chat ID: {chat_id}")
        print(f"✅ Ваш Token: {token}")
        print("="*55)
        print("Скопируйте эти два значения, они понадобятся в следующем шаге.")
    else:
        print("\n❌ Бот не видит сообщений. Убедитесь, что вы написали ему в Telegram и запустите скрипт заново.")
except Exception as e:
    print("\n❌ Ошибка. Проверьте, правильно ли скопирован ТОКЕН.", e)
