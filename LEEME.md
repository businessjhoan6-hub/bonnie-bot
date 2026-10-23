# Bot de Telegram — BonnieBlue leaderboard

Revisa la tabla cada 30 min y te manda un Telegram cuando:
- subís o bajás de puesto,
- el de abajo queda a menos de `alert_gap_points` puntos de pasarte,
- cada `summary_every_hours` horas (resumen).

## 1. Crear tu bot (una sola vez)
1. En Telegram buscá **@BotFather** y mandale `/newbot`.
2. Elegí un nombre y un usuario que termine en `bot`.
3. Copiá el **token** que te da (tipo `123456789:ABC...`).
4. Abrí el chat con tu bot nuevo y mandale cualquier mensaje (ej. `hola`).

## 2. Completar `config.json`
- `telegram_token`: el token de BotFather
- `telegram_chat_id`: dejalo vacío, el script lo detecta solo la primera vez
- `alert_gap_points`: ventaja mínima sobre el de abajo antes de alertarte (50 pts = $200 de wager)
- `summary_every_hours`: cada cuántas horas mandar el resumen (0 = nunca)

## 3. Probar
```
py bonnie_bot.py --test     # solo muestra el mensaje
py bonnie_bot.py --force    # manda un Telegram de prueba
```

## 4. Dejarlo corriendo
Ya está instalada la tarea `BonnieBlueBot` (cada 30 min). Para reinstalarla:
```
powershell -ExecutionPolicy Bypass -File instalar_tarea.ps1
```
Quitarla: `schtasks /Delete /TN "BonnieBlueBot" /F`. El historial queda en `bot.log`.
