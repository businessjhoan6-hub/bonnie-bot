"""Bot que vigila tus puestos en la leaderboard de bonnieblue.bet y avisa por Telegram con imagen + resumen.

Uso:
    py bonnie_bot.py           # revisa y manda Telegram si hay algo que avisar
    py bonnie_bot.py --test    # genera la imagen e imprime el mensaje, no manda nada
    py bonnie_bot.py --force   # manda el resumen ahora aunque no haya cambios
"""
import html
import json
import math
import os
import subprocess
import sys
import time
import urllib.parse
import urllib.request
import uuid
from datetime import datetime, timezone
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

HERE = Path(__file__).resolve().parent
# En la PC se usa config.json (con el token); en GitHub Actions no existe y se usa el
# example, con el token y el chat_id llegando por variables de entorno (secretos).
CONFIG_FILE = HERE / "config.json" if (HERE / "config.json").exists() else HERE / "config.example.json"
STATE_FILE = HERE / "state.json"
LOG_FILE = HERE / "bot.log"
IMAGE_FILE = HERE / "leaderboard.png"

API_URL = "https://bonnieblue.bet/api/leaderboard/current"
TELEGRAM_URL = "https://api.telegram.org/bot{token}/{method}"
HEADERS = {"User-Agent": "Mozilla/5.0"}

# Premio en $ por puesto (de la tabla de la web)
PRIZES = {
    1: 25000, 2: 15000, 3: 10000, 4: 7500, 5: 5500, 6: 4500, 7: 3500, 8: 3000, 9: 2500, 10: 2000,
    11: 1750, 12: 1500, 13: 1300, 14: 1150, 15: 1000, 16: 900, 17: 800, 18: 725, 19: 650, 20: 600,
    21: 585, 22: 570, 23: 555, 24: 540, 25: 525, 26: 510, 27: 495, 28: 480, 29: 465, 30: 450,
    31: 440, 32: 425, 33: 410, 34: 395, 35: 380, 36: 365, 37: 350, 38: 335, 39: 320, 40: 305,
    41: 290, 42: 275, 43: 260, 44: 245, 45: 230, 46: 215, 47: 200, 48: 185, 49: 170, 50: 155,
}


def log(msg):
    line = f"[{datetime.now():%Y-%m-%d %H:%M:%S}] {msg}"
    print(line)
    with LOG_FILE.open("a", encoding="utf-8") as f:
        f.write(line + "\n")


def load_json(path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8-sig"))
    except (FileNotFoundError, json.JSONDecodeError):
        return default


def fetch_leaderboard():
    req = urllib.request.Request(API_URL, headers=HEADERS)
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read().decode("utf-8"))


def money(x):
    return f"${x:,.2f}"


def pts(x):
    return f"{x:,.2f}"


def time_left(board):
    end = datetime.fromisoformat(board["end_date"].replace("Z", "+00:00"))
    left = end - datetime.now(timezone.utc)
    if left.total_seconds() <= 0:
        return "terminó", end
    return f"{left.days}d {left.seconds // 3600}h {(left.seconds % 3600) // 60}m", end


# ---------------------------------------------------------------- análisis

def analyze(board, cfg, state):
    """Arma, por cada jugador de la config, su puesto, vecinos y distancias."""
    ratio = cfg["points_per_dollar"]
    entries = board["entries"]
    by_pos = {e["position"]: e for e in entries}
    prev = state.get("players", {})
    players = []
    for p in cfg["players"]:
        me = next((e for e in entries if e["username"].lower() == p["username"].lower()), None)
        info = {"name": p["name"], "username": p["username"], "found": me is not None}
        if me:
            pos, points = me["position"], float(me["points"])
            neighbors = []
            for n in range(pos - cfg["show_above"], pos + 3):
                e = by_pos.get(n)
                if not e:
                    continue
                gap = float(e["points"]) - points
                neighbors.append({
                    "position": n, "username": e["username"], "points": float(e["points"]),
                    "gap": gap, "wager": abs(gap) / ratio, "is_me": n == pos,
                })
            # Escalera: wager real para PASAR (no empatar) cada puesto de arriba
            ladder = []
            for n in range(pos - 1, max(pos - 1 - cfg["ladder_steps"], 0), -1):
                e = by_pos[n]
                gap = float(e["points"]) - points + 0.01
                ladder.append({"position": n, "username": e["username"], "gap": gap,
                               "wager": math.ceil(gap / ratio * 100) / 100,
                               "prize": PRIZES.get(n, 0)})
            below = by_pos.get(pos + 1)
            last = prev.get(p["username"], {})
            info.update({
                "position": pos, "points": points, "wagered": float(me["wagered"]),
                "prize": PRIZES.get(pos, 0), "neighbors": neighbors, "ladder": ladder,
                "gap_below": points - float(below["points"]) if below else None,
                "last_position": last.get("position"),
                "points_gained": points - last["points"] if "points" in last else None,
            })
        players.append(info)
    return players


# ---------------------------------------------------------------- imagen

def font(size, bold=False):
    candidates = (
        ["C:/Windows/Fonts/segoeuib.ttf", "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"] if bold else
        ["C:/Windows/Fonts/segoeui.ttf", "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"]
    )
    for path in candidates:
        try:
            return ImageFont.truetype(path, size)
        except OSError:
            continue
    return ImageFont.load_default(size)


BG = (14, 12, 28)
CARD = (28, 24, 52)
ROW_ME = (236, 72, 153)
TEXT = (240, 238, 250)
MUTED = (160, 155, 190)
GREEN = (52, 211, 153)
RED = (248, 113, 113)
PINK = (236, 72, 153)
BLUE = (59, 130, 246)

W = 1080
PAD = 40
ROW_H = 58


def render_image(board, players, path):
    cards_h = sum(150 + (len(p["neighbors"]) + 1) * ROW_H + 40 if p["found"] else 120 for p in players)
    H = 200 + cards_h + PAD * len(players) + 70
    img = Image.new("RGB", (W, H), BG)
    d = ImageDraw.Draw(img)

    # Encabezado con degradado rosa → azul
    for x in range(W):
        t = x / W
        c = tuple(int(PINK[i] * (1 - t) + BLUE[i] * t) for i in range(3))
        d.line([(x, 0), (x, 170)], fill=c)
    left, end = time_left(board)
    d.text((PAD, 28), "BONNIE BLUE  ·  LEADERBOARD", font=font(46, True), fill="white")
    d.text((PAD, 96), f"Termina en {left}   ·   cierre {end.astimezone():%d/%m %H:%M}", font=font(28), fill="white")
    d.text((PAD, 132), f"Actualizado {datetime.now():%d/%m %H:%M}", font=font(22), fill=(255, 255, 255))

    y = 200
    cols = [PAD + 24, PAD + 130, PAD + 470, PAD + 650, PAD + 830]
    for p in players:
        if not p["found"]:
            d.rounded_rectangle([PAD, y, W - PAD, y + 120], 24, fill=CARD)
            d.text((PAD + 30, y + 38), f"{p['name']} ({p['username']}) no está en el top 50", font=font(30, True), fill=RED)
            y += 120 + PAD
            continue

        card_h = 150 + (len(p["neighbors"]) + 1) * ROW_H + 40
        d.rounded_rectangle([PAD, y, W - PAD, y + card_h], 24, fill=CARD)

        # Cabecera de la tarjeta
        d.text((PAD + 30, y + 22), p["name"].upper(), font=font(34, True), fill=TEXT)
        d.text((PAD + 30, y + 66), p["username"], font=font(24), fill=MUTED)
        d.text((PAD + 30, y + 98), f"Wager total {money(p['wagered'])}", font=font(24), fill=MUTED)
        rank = f"#{p['position']}"
        rw = d.textlength(rank, font=font(84, True))
        d.text((W - PAD - 30 - rw, y + 6), rank, font=font(84, True), fill=PINK)
        sub = f"{pts(p['points'])} pts  ·  premio {money(p['prize'])}"
        sw = d.textlength(sub, font=font(26, True))
        d.text((W - PAD - 30 - sw, y + 108), sub, font=font(26, True), fill=GREEN)

        # Tabla de vecinos
        ty = y + 150
        for x, label in zip(cols, ["PUESTO", "USUARIO", "PUNTOS", "DIFERENCIA", "WAGER"]):
            d.text((x, ty + 16), label, font=font(20, True), fill=MUTED)
        ty += ROW_H
        for n in p["neighbors"]:
            if n["is_me"]:
                d.rounded_rectangle([PAD + 12, ty + 4, W - PAD - 12, ty + ROW_H - 4], 14, fill=ROW_ME)
            fg = "white" if n["is_me"] else TEXT
            uname = n["username"] if len(n["username"]) <= 18 else n["username"][:17] + "…"
            d.text((cols[0], ty + 12), f"{n['position']}°", font=font(26, True), fill=fg)
            d.text((cols[1], ty + 12), uname, font=font(26, n["is_me"]), fill=fg)
            d.text((cols[2], ty + 12), pts(n["points"]), font=font(26), fill=fg)
            if n["is_me"]:
                d.text((cols[3], ty + 12), "TÚ" if p is players[0] else "ÉL", font=font(26, True), fill=fg)
            elif n["gap"] > 0:
                d.text((cols[3], ty + 12), f"+{pts(n['gap'])}", font=font(26), fill=RED)
                d.text((cols[4], ty + 12), money(n["wager"]), font=font(26, True), fill=TEXT)
            else:
                d.text((cols[3], ty + 12), f"−{pts(-n['gap'])}", font=font(26), fill=GREEN)
                d.text((cols[4], ty + 12), money(n["wager"]), font=font(26), fill=MUTED)
            ty += ROW_H
        y += card_h + PAD

    d.text((PAD, H - 60), "WAGER (diferencia × 4):  arriba = para alcanzarlo  ·  abajo = lo que le basta para alcanzarte",
           font=font(22), fill=MUTED)
    img.save(path)


# ---------------------------------------------------------------- texto

def render_text(board, players, alerts):
    left, end = time_left(board)
    out = []
    if alerts:
        out += [f"<b>{html.escape(a)}</b>" for a in alerts] + [""]
    out += [
        "🏆 <b>BONNIE BLUE · LEADERBOARD MENSUAL</b>",
        f"⏳ Termina en <b>{left}</b> (cierre {end.astimezone():%d/%m %H:%M})",
    ]
    for p in players:
        out.append("")
        name = f"{html.escape(p['name'])} — <code>{html.escape(p['username'])}</code>"
        if not p["found"]:
            out.append(f"👤 <b>{name}</b>\n⚠️ No aparece en el top 50")
            continue
        out.append(f"👤 <b>{name}</b>")
        out.append(f"🎯 Puesto <b>{p['position']}°</b> · {pts(p['points'])} pts · premio <b>{money(p['prize'])}</b>")
        out.append(f"💵 Wager acumulado: {money(p['wagered'])}")
        if p["points_gained"]:
            out.append(f"📈 Desde la última revisión: +{pts(p['points_gained'])} pts")
        if p["ladder"]:
            out.append("🪜 <b>Wager real para pasar a cada puesto:</b>")
            for n in p["ladder"]:
                extra = n["prize"] - p["prize"]
                out.append(f"   • <b>{n['position']}°</b> ({html.escape(n['username'])}): "
                           f"<b>{money(n['wager'])}</b> → premio {money(n['prize'])} (+{money(extra)})")
        downs = [n for n in p["neighbors"] if n["gap"] < 0]
        if downs:
            out.append("⬇️ <b>Vienen detrás:</b>")
            for n in sorted(downs, key=lambda n: -n["gap"]):
                icon = "🔥" if -n["gap"] < 50 else "•"
                out.append(f"   {icon} {n['position']}° {html.escape(n['username'])}: a {pts(-n['gap'])} pts "
                           f"(le bastan {money(n['wager'])} de wager)")
    out += ["", f"<i>Datos de la web sincronizados {datetime.fromisoformat(board['last_synced_at'].replace('Z', '+00:00')).astimezone():%H:%M}</i>"]
    return "\n".join(out)


# ---------------------------------------------------------------- telegram

def multipart(params, files):
    boundary = uuid.uuid4().hex
    body = b""
    for k, v in params.items():
        body += f'--{boundary}\r\nContent-Disposition: form-data; name="{k}"\r\n\r\n{v}\r\n'.encode()
    for k, p in files.items():
        body += (f'--{boundary}\r\nContent-Disposition: form-data; name="{k}"; filename="{p.name}"\r\n'
                 f"Content-Type: image/png\r\n\r\n").encode() + p.read_bytes() + b"\r\n"
    body += f"--{boundary}--\r\n".encode()
    return body, {**HEADERS, "Content-Type": f"multipart/form-data; boundary={boundary}"}


def telegram(cfg, method, params, files=None):
    url = TELEGRAM_URL.format(token=cfg["telegram_token"], method=method)
    if files:
        body, headers = multipart(params, files)
    else:
        body = urllib.parse.urlencode(params).encode("utf-8")
        headers = HEADERS
    req = urllib.request.Request(url, data=body, headers=headers)
    with urllib.request.urlopen(req, timeout=60) as resp:
        result = json.loads(resp.read().decode("utf-8"))
    if not result.get("ok"):
        raise RuntimeError(f"Telegram respondió un error: {result}")
    return result["result"]


def ensure_chat_id(cfg):
    """Si falta el chat_id, lo saca del último mensaje que le mandaste al bot y lo guarda."""
    if cfg.get("telegram_chat_id"):
        return
    updates = telegram(cfg, "getUpdates", {})
    chats = [u["message"]["chat"]["id"] for u in updates if "message" in u]
    if not chats:
        raise RuntimeError("Mandale cualquier mensaje a tu bot en Telegram y volvé a correr el script.")
    cfg["telegram_chat_id"] = chats[-1]
    CONFIG_FILE.write_text(json.dumps(cfg, indent=2, ensure_ascii=False), encoding="utf-8")
    log(f"chat_id detectado y guardado: {cfg['telegram_chat_id']}")


def send_telegram(cfg, text, image):
    ensure_chat_id(cfg)
    chat = cfg["telegram_chat_id"]
    telegram(cfg, "sendPhoto", {"chat_id": chat}, files={"photo": image})
    telegram(cfg, "sendMessage", {"chat_id": chat, "text": text, "parse_mode": "HTML"})


# ---------------------------------------------------------------- discord

def to_discord(text):
    """Pasa el HTML de Telegram al markdown de Discord."""
    for a, b in (("<b>", "**"), ("</b>", "**"), ("<i>", "*"), ("</i>", "*"), ("<code>", "`"), ("</code>", "`")):
        text = text.replace(a, b)
    return html.unescape(text)


def chunks(text, limit=1900):
    """Discord acepta hasta 2000 caracteres por mensaje: corta por bloques (líneas en blanco)."""
    parts, cur = [], ""
    for block in text.split("\n\n"):
        if cur and len(cur) + len(block) + 2 > limit:
            parts.append(cur)
            cur = block
        else:
            cur = f"{cur}\n\n{block}" if cur else block
    return parts + [cur] if cur else parts


def discord_post(webhook, payload, image=None):
    if image:
        body, headers = multipart({"payload_json": json.dumps(payload)}, {"files[0]": image})
    else:
        body, headers = json.dumps(payload).encode("utf-8"), {**HEADERS, "Content-Type": "application/json"}
    req = urllib.request.Request(webhook, data=body, headers=headers)
    with urllib.request.urlopen(req, timeout=60) as resp:
        resp.read()


def send_discord(webhook, text, image):
    parts = chunks(to_discord(text))
    discord_post(webhook, {"content": parts[0]}, image)
    for part in parts[1:]:
        discord_post(webhook, {"content": part})


def notify(cfg, text, image):
    """Manda a Telegram y, si hay webhook, a Discord. Si uno falla, el otro igual sale.
    Solo falla (y se reintenta) si no salió por ningún lado, para no duplicar en el que sí funcionó."""
    errors, sent = [], 0
    try:
        send_telegram(cfg, text, image)
        sent += 1
    except Exception as exc:
        errors.append(f"Telegram: {exc}")
    if cfg.get("discord_webhook"):
        try:
            send_discord(cfg["discord_webhook"], text, image)
            sent += 1
        except Exception as exc:
            errors.append(f"Discord: {exc}")
    if errors and not sent:
        raise RuntimeError(" | ".join(errors))
    if errors:
        log("Aviso: " + " | ".join(errors))


# ---------------------------------------------------------------- main

def check(test=False, force=False, quiet=False):
    """Una revisión. Devuelve 'ended' si la leaderboard ya terminó y se mandó el resultado final."""
    cfg = load_json(CONFIG_FILE, None)
    if cfg is None:
        log("Falta config.json (copiá config.example.json y completalo).")
        return 1
    if os.environ.get("TELEGRAM_TOKEN"):
        cfg["telegram_token"] = os.environ["TELEGRAM_TOKEN"]
    if os.environ.get("TELEGRAM_CHAT_ID"):
        cfg["telegram_chat_id"] = os.environ["TELEGRAM_CHAT_ID"]
    if os.environ.get("DISCORD_WEBHOOK"):
        cfg["discord_webhook"] = os.environ["DISCORD_WEBHOOK"]
    if not test and (not cfg.get("telegram_token") or "PON_AQUI" in cfg["telegram_token"]):
        log("Completá 'telegram_token' en config.json (o corré con --test).")
        return 1

    state = load_json(STATE_FILE, {})
    prev = state.get("players", {})
    board = fetch_leaderboard()
    players = analyze(board, cfg, state)

    end = datetime.fromisoformat(board["end_date"].replace("Z", "+00:00"))
    if board.get("status") != "IN_PROGRESS" or datetime.now(timezone.utc) >= end:
        if state.get("finished_board") == board.get("id"):
            return "ended"
        alerts = ["🏁 ¡TERMINÓ LA LEADERBOARD! Resultado final:"] + [
            f"{p['name']}: {p['position']}° → premio {money(p['prize'])}" if p["found"]
            else f"{p['name']}: fuera del top 50" for p in players]
        render_image(board, players, IMAGE_FILE)
        text = render_text(board, players, alerts)
        if test:
            print(text)
            return "ended"
        notify(cfg, text, IMAGE_FILE)
        state["finished_board"] = board.get("id")
        STATE_FILE.write_text(json.dumps(state, indent=2), encoding="utf-8")
        log("Leaderboard terminada: resultado final enviado.")
        return "ended"

    alerts = []
    new_players = {}
    for p in players:
        last = prev.get(p["username"], {})
        if not p["found"]:
            if not last.get("missing"):
                alerts.append(f"⚠️ {p['name']} salió del top 50")
            new_players[p["username"]] = {"missing": True}
            continue
        if p["last_position"] is not None and p["position"] != p["last_position"]:
            if p["position"] < p["last_position"]:
                alerts.append(f"🟢 {p['name']}: subió del {p['last_position']}° al {p['position']}°")
            else:
                alerts.append(f"🔴 {p['name']}: bajó del {p['last_position']}° al {p['position']}°")
        danger = p["gap_below"] is not None and p["gap_below"] < cfg["alert_gap_points"]
        if danger and not last.get("danger"):
            alerts.append(f"🚨 {p['name']}: el de abajo está a solo {pts(p['gap_below'])} pts")
        new_players[p["username"]] = {"position": p["position"], "points": p["points"], "danger": danger}

    reasons = list(alerts)
    if not prev:
        reasons.append("bot activado")
    hours = cfg["summary_every_hours"]
    last_summary = state.get("last_summary")
    if hours and (last_summary is None or
                  (datetime.now(timezone.utc) - datetime.fromisoformat(last_summary)).total_seconds() >= hours * 3600):
        reasons.append("resumen periódico")
    if force:
        reasons.append("resumen pedido")

    new_state = {"players": new_players, "last_summary": last_summary}
    if not reasons:
        if not quiet:
            log("Sin cambios (" + ", ".join(f"{p['name']} {p.get('position', '-')}°" for p in players) + ").")
        STATE_FILE.write_text(json.dumps(new_state, indent=2), encoding="utf-8")
        return 0

    render_image(board, players, IMAGE_FILE)
    text = render_text(board, players, alerts)

    if test:
        print(f"----- MODO PRUEBA (no se envía) — imagen en {IMAGE_FILE} -----")
        print(text)
        return 0

    notify(cfg, text, IMAGE_FILE)
    new_state["last_summary"] = datetime.now(timezone.utc).isoformat()
    STATE_FILE.write_text(json.dumps(new_state, indent=2), encoding="utf-8")
    log(f"Telegram enviado ({', '.join(reasons)}).")
    return 0


def single_instance():
    """True si esta es la única copia del bot en modo bucle corriendo."""
    import ctypes
    ctypes.windll.kernel32.CreateMutexW(None, False, "BonnieBlueBotLoop")
    return ctypes.windll.kernel32.GetLastError() != 183  # ERROR_ALREADY_EXISTS


def keep_awake():
    """Pide a Windows que no suspenda la PC mientras el bot corre (la pantalla sí puede apagarse)."""
    import ctypes
    ctypes.windll.kernel32.SetThreadExecutionState(0x80000000 | 0x00000001)  # CONTINUOUS | SYSTEM_REQUIRED


def run_loop():
    if not single_instance():
        return 0
    keep_awake()
    log("Bot en marcha (modo 24h).")
    while True:
        interval = load_json(CONFIG_FILE, {}).get("check_every_seconds", 60)
        try:
            if check(quiet=True) == "ended":
                subprocess.run(["schtasks", "/Delete", "/TN", "BonnieBlueBot", "/F"], capture_output=True)
                log("Tarea de Windows eliminada. Bot apagado.")
                return 0
        except Exception as exc:
            log(f"Error (reintento en {interval}s): {exc}")
        time.sleep(interval)


def run_cloud_loop(minutes):
    """GitHub Actions: revisa cada minuto durante `minutes` y sale (el workflow lanza la siguiente corrida)."""
    deadline = time.time() + minutes * 60
    log(f"Bot en marcha en la nube ({minutes} min).")
    while time.time() < deadline:
        interval = load_json(CONFIG_FILE, {}).get("check_every_seconds", 60)
        try:
            if check(quiet=True) == "ended":
                return "ended"
        except Exception as exc:
            log(f"Error (reintento en {interval}s): {exc}")
        time.sleep(interval)
    log("Fin del turno en la nube.")
    return 0


def main():
    if "--loop" in sys.argv:
        return run_loop()
    if "--cloud-loop" in sys.argv:
        result = run_cloud_loop(int(sys.argv[sys.argv.index("--cloud-loop") + 1]))
        if result == "ended" and os.environ.get("GITHUB_OUTPUT"):
            with open(os.environ["GITHUB_OUTPUT"], "a", encoding="utf-8") as f:
                f.write("ended=true\n")
        return 0
    result = check(test="--test" in sys.argv, force="--force" in sys.argv)
    if result == "ended" and os.environ.get("GITHUB_OUTPUT"):
        with open(os.environ["GITHUB_OUTPUT"], "a", encoding="utf-8") as f:
            f.write("ended=true\n")
    return 0 if result in (None, 0, "ended") else result


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as exc:
        log(f"Error: {exc}")
        sys.exit(1)
