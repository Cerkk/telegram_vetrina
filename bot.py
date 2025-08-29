# bot.py
import os
import json
import time
import threading
from pathlib import Path
from flask import Flask, request, jsonify, send_from_directory
import requests

# -----------------------------
# CONFIG (già compilata con i tuoi valori da screenshot)
# -----------------------------
BOT_TOKEN = "8271496436:AAHME0_r544DURmsfGPXyfnHppM9SvNATLQ"
ADMIN_ID = 680122100
MINI_APP_URL = "https://vetrina-rho.vercel.app"  # link tua miniapp
HOSTNAME = "telegram-vetrina-bot.onrender.com"   # dominio render

BASE_API = f"https://api.telegram.org/bot{BOT_TOKEN}"
FILE_API = f"https://api.telegram.org/file/bot{BOT_TOKEN}"

# Paths
ROOT = Path(__file__).parent
PRODUCTS_JSON = ROOT / "products.json"
SESSIONS_JSON = ROOT / "sessions.json"
MEDIA_DIR = ROOT / "media"
MEDIA_DIR.mkdir(exist_ok=True)

# Thread lock
lock = threading.Lock()

# -----------------------------
# FILE HELPERS
# -----------------------------
def load_products():
    with lock:
        if not PRODUCTS_JSON.exists():
            return []
        return json.loads(PRODUCTS_JSON.read_text(encoding="utf-8"))

def save_products(products):
    with lock:
        PRODUCTS_JSON.write_text(json.dumps(products, ensure_ascii=False, indent=2), encoding="utf-8")

def load_sessions():
    with lock:
        if not SESSIONS_JSON.exists():
            return {}
        return json.loads(SESSIONS_JSON.read_text(encoding="utf-8"))

def save_sessions(sessions):
    with lock:
        SESSIONS_JSON.write_text(json.dumps(sessions, ensure_ascii=False, indent=2), encoding="utf-8")

# -----------------------------
# TELEGRAM HELPERS
# -----------------------------
def send_message(chat_id, text, reply_markup=None, parse_mode=None):
    data = {"chat_id": chat_id, "text": text}
    if reply_markup:
        data["reply_markup"] = json.dumps(reply_markup)
    if parse_mode:
        data["parse_mode"] = parse_mode
    requests.post(f"{BASE_API}/sendMessage", data=data)

def delete_message(chat_id, message_id):
    requests.post(f"{BASE_API}/deleteMessage", data={"chat_id": chat_id, "message_id": message_id})

def send_photo(chat_id, photo_url, caption="", reply_markup=None):
    data = {"chat_id": chat_id, "photo": photo_url}
    if caption:
        data["caption"] = caption
        data["parse_mode"] = "Markdown"
    if reply_markup:
        data["reply_markup"] = json.dumps(reply_markup)
    requests.post(f"{BASE_API}/sendPhoto", data=data)

def answer_with_keyboard(chat_id, text, options):
    keyboard = {"keyboard": [[o] for o in options], "one_time_keyboard": True, "resize_keyboard": True}
    send_message(chat_id, text, reply_markup=keyboard)

def get_file_path(file_id):
    r = requests.get(f"{BASE_API}/getFile", params={"file_id": file_id})
    data = r.json()
    if not data.get("ok"):
        return None
    return data["result"]["file_path"]

def download_file(file_path, dest_path: Path):
    url = f"{FILE_API}/{file_path}"
    r = requests.get(url, stream=True)
    if r.status_code == 200:
        with open(dest_path, "wb") as f:
            for chunk in r.iter_content(4096):
                f.write(chunk)
        return True
    return False

# -----------------------------
# SESSION HELPERS
# -----------------------------
def start_adding(chat_id, sessions):
    sessions[str(chat_id)] = {"mode": "adding", "step": "name", "buffer": {}}
    save_sessions(sessions)
    send_message(chat_id, "🟢 Aggiungi prodotto — inserisci il *nome* del prodotto:", parse_mode="Markdown")

def start_removing(chat_id, sessions):
    sessions[str(chat_id)] = {"mode": "removing", "step": "choice", "buffer": {}}
    save_sessions(sessions)
    answer_with_keyboard(chat_id, "Cosa vuoi rimuovere? scegli:", ["Prodotto", "Categoria"])

def start_modifying(chat_id, sessions):
    sessions[str(chat_id)] = {"mode": "modifying", "step": "choice", "buffer": {}}
    save_sessions(sessions)
    answer_with_keyboard(chat_id, "Vuoi modificare un *Prodotto* o una *Categoria*?", ["Prodotto", "Categoria"])

def list_products_by_category():
    products = load_products()
    by_cat = {}
    for p in products:
        cat = p.get("tipologia", "Senza categoria")
        by_cat.setdefault(cat, []).append(p)
    return by_cat

def find_product_by_name(name):
    products = load_products()
    for p in products:
        if p.get("nome", "").strip().lower() == name.strip().lower():
            return p
    return None

def remove_product_by_name(name):
    products = load_products()
    new = [p for p in products if p.get("nome","").strip().lower() != name.strip().lower()]
    if len(new) == len(products):
        return False
    save_products(new)
    return True

def remove_category(cat_name):
    products = load_products()
    new = [p for p in products if p.get("tipologia","") != cat_name]
    removed = len(products) - len(new)
    save_products(new)
    return removed

def create_product_entry(buffer):
    products = load_products()
    new_id = int(time.time() * 1000)
    entry = {
        "id": new_id,
        "nome": buffer.get("nome"),
        "prezzo": buffer.get("prezzo"),
        "tipologia": buffer.get("tipologia"),
        "immagine": buffer.get("immagine", "")
    }
    products.append(entry)
    save_products(products)
    return entry

# -----------------------------
# FLASK APP
# -----------------------------
app = Flask(__name__)

@app.route("/")
def index():
    return "Bot Telegram vetrina attivo."

@app.route("/webhook", methods=["POST"])
def webhook():
    update = request.get_json(force=True)
    try:
        if "message" in update:
            handle_message(update["message"])
    except Exception as e:
        send_message(ADMIN_ID, f"Errore nel webhook: {e}")
    return jsonify({"ok": True})

@app.route("/media/<path:filename>")
def media_serve(filename):
    return send_from_directory(str(MEDIA_DIR), filename)

if __name__ == "__main__":
    import os
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
# -----------------------------
# MESSAGE HANDLER
# -----------------------------
def handle_message(message):
    chat_id = message["chat"]["id"]
    text = message.get("text", "")
    message_id = message.get("message_id")
    sessions = load_sessions()
    sess = sessions.get(str(chat_id), {})

    # comandi
    if text and text.startswith("/"):
        command = text.split()[0].lower()

        # elimina messaggio comando
        if message_id:
            delete_message(chat_id, message_id)

        if command in ("/aggiungi", "/rimuovi", "/modifica", "/info") and chat_id != ADMIN_ID:
            send_message(chat_id, "❌ Non sei autorizzato a usare questo comando.")
            return


        if command == "/start":
            keyboard = {
                "inline_keyboard": [[{"text": "🛒 Apri la Vetrina", "url": MINI_APP_URL}]]
            }
            send_message(chat_id, "Benvenuto Fratm! Usa il pulsante sotto per aprire la vetrina.", reply_markup=keyboard, parse_mode="Markdown")
            sessions.pop(str(chat_id), None)
            save_sessions(sessions)
            return

        if command == "/info":
            text = (
                "Comandi disponibili:\n"
                "/start - avvia il bot e mostra il pulsante\n"
                "/aggiungi - aggiungi un nuovo prodotto\n"
                "/rimuovi - rimuovi un prodotto o una categoria\n"
                "/modifica - modifica un prodotto o una categoria\n"
            )
            send_message(chat_id, text)
            return

        if command == "/aggiungi":
            start_adding(chat_id, sessions)
            return
        if command == "/rimuovi":
            start_removing(chat_id, sessions)
            return
        if command == "/modifica":
            start_modifying(chat_id, sessions)
            return

        send_message(chat_id, "Comando non riconosciuto. Usa /aggiungi /rimuovi /modifica")
        return

    # ... resto del codice identico (aggiungi/rimuovi/modifica flussi) ...
    # (QUI va copiato tutto il blocco delle logiche "adding / removing / modifying"
    # che ti ho già fornito nel codice precedente, senza cambiare nulla)
    # If there is no session, ignora
    if not sess:
        send_message(chat_id, "Usa /aggiungi per aggiungere un prodotto, /rimuovi o /modifica. /start per info.")
        return

    mode = sess.get("mode")
    step = sess.get("step")
    buffer = sess.get("buffer", {})

    # ---- ADDING FLOW ----
    if mode == "adding":
        if step == "name":
            if not text:
                send_message(chat_id, "Inserisci il nome del prodotto (testo).")
                return
            buffer["nome"] = text.strip()
            sess["step"] = "prezzo"
            sess["buffer"] = buffer
            sessions[str(chat_id)] = sess
            save_sessions(sessions)
            send_message(chat_id, "Ok — inserisci il *prezzo* (es. 9.90):", parse_mode="Markdown")
            return

        if step == "prezzo":
            if not text:
                send_message(chat_id, "Inserisci il prezzo (testo numerico).")
                return
            buffer["prezzo"] = text.strip()
            sess["step"] = "categoria"
            sess["buffer"] = buffer
            sessions[str(chat_id)] = sess
            save_sessions(sessions)
            send_message(chat_id, "Inserisci la *categoria* (tipologia):", parse_mode="Markdown")
            return

        if step == "categoria":
            if not text:
                send_message(chat_id, "Inserisci la categoria (testo).")
                return
            buffer["tipologia"] = text.strip()
            sess["step"] = "media"
            sess["buffer"] = buffer
            sessions[str(chat_id)] = sess
            save_sessions(sessions)
            send_message(chat_id, "Ora invia un *video* o immagine, oppure scrivi 'nessuno'.", parse_mode="Markdown")
            return

        if step == "media":
            if "video" in message:
                file_id = message["video"]["file_id"]
            elif "photo" in message:
                file_id = message["photo"][-1]["file_id"]
            elif text and text.strip().lower() == "nessuno":
                file_id = None
            else:
                send_message(chat_id, "Invia un video o un’immagine o scrivi 'nessuno'.")
                return

            if file_id:
                fp = get_file_path(file_id)
                if fp:
                    ext = Path(fp).suffix or ""
                    filename = f"{int(time.time()*1000)}{ext}"
                    dest = MEDIA_DIR / filename
                    if download_file(fp, dest):
                        buffer["immagine"] = f"media/{filename}"
                        send_message(chat_id, f"Media salvato come media/{filename}")
            else:
                buffer["immagine"] = ""

            entry = create_product_entry(buffer)
            send_message(chat_id, f"✅ Prodotto aggiunto:\nNome: {entry['nome']}\nPrezzo: {entry['prezzo']}\nCategoria: {entry['tipologia']}")
            sessions.pop(str(chat_id), None); save_sessions(sessions)
            return

    # ---- REMOVING FLOW ----
    if mode == "removing":
        if step == "choice":
            if not text:
                send_message(chat_id, "Rispondi 'Prodotto' o 'Categoria'.")
                return
            t = text.strip().lower()
            if t.startswith("prod"):
                products = load_products()
                if not products:
                    send_message(chat_id, "Non ci sono prodotti.")
                    sessions.pop(str(chat_id), None); save_sessions(sessions); return
                names = [p["nome"] for p in products]
                sess["step"] = "remove_product"; sess["buffer"] = {}
                sessions[str(chat_id)] = sess; save_sessions(sessions)
                answer_with_keyboard(chat_id, "Quale prodotto vuoi rimuovere?", names)
                return
            elif t.startswith("cat"):
                by_cat = list_products_by_category()
                cats = list(by_cat.keys())
                if not cats:
                    send_message(chat_id, "Non ci sono categorie.")
                    sessions.pop(str(chat_id), None); save_sessions(sessions); return
                sess["step"] = "remove_category"; sess["buffer"] = {}
                sessions[str(chat_id)] = sess; save_sessions(sessions)
                answer_with_keyboard(chat_id, "Quale categoria vuoi rimuovere?", cats)
                return
            else:
                send_message(chat_id, "Rispondi 'Prodotto' o 'Categoria'.")
                return

        if step == "remove_product":
            if not text:
                send_message(chat_id, "Scrivi il nome del prodotto.")
                return
            ok = remove_product_by_name(text.strip())
            send_message(chat_id, f"{'✅ Rimosso' if ok else '❌ Non trovato'}: {text.strip()}")
            sessions.pop(str(chat_id), None); save_sessions(sessions)
            return

        if step == "remove_category":
            if not text:
                send_message(chat_id, "Scrivi il nome della categoria.")
                return
            removed = remove_category(text.strip())
            send_message(chat_id, f"Rimossi {removed} prodotti dalla categoria '{text.strip()}'.")
            sessions.pop(str(chat_id), None); save_sessions(sessions)
            return

    # ---- MODIFY FLOW ----
    if mode == "modifying":
        if step == "choice":
            if not text:
                send_message(chat_id, "Rispondi 'Prodotto' o 'Categoria'.")
                return
            t = text.strip().lower()
            if t.startswith("cat"):
                sess["step"] = "modify_category_name"
                sessions[str(chat_id)] = sess; save_sessions(sessions)
                send_message(chat_id, "Scrivi 'VecchioNome -> NuovoNome'")
                return
            elif t.startswith("prod"):
                products = load_products()
                if not products:
                    send_message(chat_id, "Non ci sono prodotti.")
                    sessions.pop(str(chat_id), None); save_sessions(sessions); return
                names = [p["nome"] for p in products]
                sess["step"] = "modify_select_product"
                sessions[str(chat_id)] = sess; save_sessions(sessions)
                answer_with_keyboard(chat_id, "Quale prodotto vuoi modificare?", names)
                return
            else:
                send_message(chat_id, "Rispondi 'Prodotto' o 'Categoria'.")
                return

        if step == "modify_category_name":
            if not text or "->" not in text:
                send_message(chat_id, "Formato errato. Usa 'Vecchio -> Nuovo'")
                return
            old, new = [s.strip() for s in text.split("->", 1)]
            products = load_products()
            changed = False
            for p in products:
                if p.get("tipologia") == old:
                    p["tipologia"] = new
                    changed = True
            if changed:
                save_products(products)
                send_message(chat_id, f"✅ Categoria rinominata: {old} -> {new}")
            else:
                send_message(chat_id, f"Nessuna categoria '{old}' trovata.")
            sessions.pop(str(chat_id), None); save_sessions(sessions)
            return

        if step == "modify_select_product":
            prod = find_product_by_name(text.strip())
            if not prod:
                send_message(chat_id, "Prodotto non trovato.")
                sessions.pop(str(chat_id), None); save_sessions(sessions); return
            buffer["prod_id"] = prod["id"]
            sess["step"] = "modify_field_choice"; sess["buffer"] = buffer
            sessions[str(chat_id)] = sess; save_sessions(sessions)
            answer_with_keyboard(chat_id, "Cosa vuoi modificare?", ["nome", "prezzo", "media", "categoria"])
            return

        if step == "modify_field_choice":
            choice = text.strip().lower()
            if choice not in ("nome", "prezzo", "media", "categoria"):
                send_message(chat_id, "Scegli nome, prezzo, media o categoria.")
                return
            buffer["field"] = choice
            if choice == "media":
                sess["step"] = "modify_waiting_media"
                sess["buffer"] = buffer
                sessions[str(chat_id)] = sess; save_sessions(sessions)
                send_message(chat_id, "Invia il nuovo media.")
                return
            else:
                sess["step"] = "modify_new_value"
                sess["buffer"] = buffer
                sessions[str(chat_id)] = sess; save_sessions(sessions)
                send_message(chat_id, f"Inserisci il nuovo {choice}:")
                return

        if step == "modify_new_value":
            prod_id = buffer.get("prod_id")
            field = buffer.get("field")
            products = load_products()
            for p in products:
                if p["id"] == prod_id:
                    p[field if field != "categoria" else "tipologia"] = text.strip()
                    save_products(products)
                    send_message(chat_id, f"✅ {field} aggiornato.")
                    break
            sessions.pop(str(chat_id), None); save_sessions(sessions)
            return

        if step == "modify_waiting_media":
            if "video" in message:
                file_id = message["video"]["file_id"]
            elif "photo" in message:
                file_id = message["photo"][-1]["file_id"]
            else:
                send_message(chat_id, "Invia un video o immagine.")
                return
            fp = get_file_path(file_id)
            ext = Path(fp).suffix or ""
            filename = f"{int(time.time()*1000)}{ext}"
            dest = MEDIA_DIR / filename
            if download_file(fp, dest):
                prod_id = buffer.get("prod_id")
                products = load_products()
                for p in products:
                    if p["id"] == prod_id:
                        p["immagine"] = f"media/{filename}"
                        save_products(products)
                        send_message(chat_id, f"✅ Media aggiornato: media/{filename}")
                        break
            sessions.pop(str(chat_id), None); save_sessions(sessions)
            return

    # fallback
    send_message(chat_id, "Non ho capito. Usa /aggiungi /rimuovi /modifica oppure /start.")
