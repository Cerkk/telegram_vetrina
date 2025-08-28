import logging
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, InputMediaPhoto
from telegram.error import TelegramError
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes, CallbackQueryHandler
import json
import os
import asyncio
import uuid
from flask import Flask, send_from_directory, request
# Rimosso: from threading import Thread, import time (non necessari per questo setup)

# --- Configurazione del Logging (primo in assoluto) ---
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO
)
logger = logging.getLogger(__name__)

# --- 1. Definizione delle Variabili di Percorso Locali ---
PRODUCTS_FILE = 'products.json'
MEDIA_DIR = 'media/'

# --- 2. Inizializzazione dell'App Flask ---
app = Flask(__name__)

# --- 3. Definizione delle Rotte Flask ---
@app.route('/media/<path:filename>')
def serve_media(filename):
    """Serve i file media dalla directory specificata."""
    if not os.path.exists(MEDIA_DIR):
        logger.warning(f"La directory media '{MEDIA_DIR}' non esiste. Creazione...")
        os.makedirs(MEDIA_DIR)  # Assicurati che esista al momento del serving
    return send_from_directory(MEDIA_DIR, filename)


@app.route('/')
def home():
    """Pagina di benvenuto per la rotta radice."""
    return "Bot Telegram e server media Flask attivi!"


# --- 4. Lettura delle Variabili d'Ambiente ---
BOT_TOKEN = os.getenv("BOT_TOKEN")
ADMIN_ID = int(os.getenv("ADMIN_ID")) if os.getenv("ADMIN_ID") and os.getenv("ADMIN_ID").isdigit() else None
BASE_URL_MEDIA = os.getenv("BASE_URL_MEDIA")
MINI_APP_URL = os.getenv("MINI_APP_URL")
# RENDER_EXTERNAL_HOSTNAME è usato internamente da post_init, non serve definirlo qui
# ma deve essere una variabile d'ambiente su Render.

# --- 5. Validazione delle Variabili Cruciali ---
if not BOT_TOKEN:
    logger.critical("BOT_TOKEN non è stato trovato nelle variabili d'ambiente! Il bot non può avviarsi.")
    exit(1)  # Termina l'applicazione se il token non c'è
if ADMIN_ID is None:
    logger.warning("ADMIN_ID non è stato trovato o non è valido nelle variabili d'ambiente. I comandi admin non saranno disponibili.")
if not BASE_URL_MEDIA:
    logger.critical("BASE_URL_MEDIA non è stato trovato nelle variabili d'ambiente! Il server media potrebbe non funzionare correttamente.")
if not MINI_APP_URL:
    logger.critical("MINI_APP_URL non è stato trovato nelle variabili d'ambiente! La Mini App non sarà accessibile.")

# --- Variabili globali per lo stato del bot ---
user_data = {}
last_bot_message_id = {}

# --- Stati per la macchina a stati finiti ---
ADD_PRODUCT_NAME = 1
ADD_PRODUCT_PRICE = 2
ADD_PRODUCT_MEDIA = 3
ADD_PRODUCT_CATEGORY_SELECT = 4

MODIFY_PRODUCT_ASK_NAME = 10
MODIFY_PRODUCT_ASK_FIELD = 11
MODIFY_PRODUCT_ASK_VALUE = 12
MODIFY_PRODUCT_ASK_MEDIA_UPLOAD = 13

CATEGORY_ACTION_SELECT = 20
ADD_CATEGORY_NAME = 21
DELETE_CATEGORY_NAME = 22

DELETE_PRODUCT_ASK_NAME = 30
AWAITING_DELETE_CONFIRMATION = 31
# Fine stati

# --- Funzioni di utilità per la gestione del file JSON ---
async def read_products_and_categories():
    """Legge prodotti e categorie dal file JSON."""
    async with asyncio.Lock():
        if not os.path.exists(PRODUCTS_FILE) or os.path.getsize(PRODUCTS_FILE) == 0:
            initial_data = {'products': [], 'categories': []}
            with open(PRODUCTS_FILE, 'w', encoding='utf-8') as f:
                json.dump(initial_data, f, indent=2, ensure_ascii=False)
            return initial_data

        with open(PRODUCTS_FILE, 'r', encoding='utf-8') as f:
            try:
                data = json.load(f)
                if 'products' not in data:
                    data['products'] = []
                if 'categories' not in data:
                    data['categories'] = []
                return data
            except json.JSONDecodeError:
                logger.error(f"Errore: Il file {PRODUCTS_FILE} non è un JSON valido. Inizializzo con dati vuoti.")
                initial_data = {'products': [], 'categories': []}
                with open(PRODUCTS_FILE, 'w', encoding='utf-8') as f_write:
                    json.dump(initial_data, f_write, indent=2, ensure_ascii=False)
                return initial_data


async def write_products_and_categories(data):
    """Scrive prodotti e categorie nel file JSON."""
    async with asyncio.Lock():
        with open(PRODUCTS_FILE, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=2, ensure_ascii=False)


def is_admin(user_id):
    """Controlla se l'utente è l'admin."""
    return user_id == ADMIN_ID


async def delete_bot_messages(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Tenta di cancellare i messaggi precedenti del bot e dell'utente."""
    chat_id = update.effective_chat.id
    if update.message and update.message.message_id:
        try:
            await context.bot.delete_message(chat_id=chat_id, message_id=update.message.message_id)  # Cancella il comando utente
        except TelegramError as e:
            logger.debug(f"Impossibile cancellare il messaggio utente {update.message.message_id}: {e}")

    if chat_id in last_bot_message_id:
        try:
            await context.bot.delete_message(chat_id=chat_id, message_id=last_bot_message_id[chat_id])
            del last_bot_message_id[chat_id]
        except TelegramError as e:
            logger.debug(f"Impossibile cancellare l'ultimo messaggio del bot {last_bot_message_id[chat_id]}: {e}")


async def send_start_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Invia il messaggio di benvenuto con logo e pulsante Mini App."""
    await delete_bot_messages(update, context)

    keyboard = [
        [InlineKeyboardButton("Avvia Vetrina", web_app={"url": MINI_APP_URL})]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)

    logo_url = "https://www.freeiconspng.com/uploads/logo-new-png-5.png"  # <--- Sostituisci con il tuo logo reale
    caption = "Benvenuto nella vetrina dei prodotti! Clicca qui sotto per accedere al menu e scoprire le offerte."

    try:
        if logo_url and not logo_url.strip() == "":
            message = await context.bot.send_photo(
                chat_id=update.effective_chat.id,
                photo=logo_url,
                caption=caption,
                reply_markup=reply_markup
            )
        else:
            message = await context.bot.send_message(
                chat_id=update.effective_chat.id,
                text=caption,
                reply_markup=reply_markup
            )
        last_bot_message_id[update.effective_chat.id] = message.message_id
    except TelegramError as e:
        logger.error(f"Errore nell'invio del messaggio di start: {e}")
        await update.effective_chat.send_message("Si è verificato un errore nell'avvio del bot. Riprova più tardi.")


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Gestisce il comando /start."""
    await send_start_message(update, context)


async def save_media_from_telegram(file_id: str, file_extension: str, context: ContextTypes.DEFAULT_TYPE) -> str:
    """
    Scarica un file da Telegram e lo salva nella directory media/.
    Restituisce l'URL pubblico del file salvato.
    """
    if not os.path.exists(MEDIA_DIR):
        os.makedirs(MEDIA_DIR)

    new_filename = f"{uuid.uuid4()}.{file_extension}"
    file_path = os.path.join(MEDIA_DIR, new_filename)

    file_obj = await context.bot.get_file(file_id)
    await file_obj.download_to_drive(file_path)
    logger.info(f"File scaricato: {file_path}")

    return f"{BASE_URL_MEDIA}{new_filename}"


# --- Comandi Admin ---
async def admin_only_check(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    """Verifica se l'utente è l'admin e invia un messaggio di avviso in caso contrario."""
    if ADMIN_ID is None or not is_admin(update.effective_user.id):
        await update.message.reply_text("Non sei autorizzato a usare questo comando.")
        return False
    return True


async def add_product_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Inizia il processo di aggiunta di un prodotto."""
    if not await admin_only_check(update, context):
        return
    await delete_bot_messages(update, context)
    message = await update.message.reply_text("Ok, iniziamo ad aggiungere un nuovo prodotto.\nNome del prodotto?")
    user_data[update.effective_user.id] = {'state': ADD_PRODUCT_NAME}
    last_bot_message_id[update.effective_chat.id] = message.message_id


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Gestisce i messaggi in base allo stato corrente dell'utente."""
    user_id = update.effective_user.id
    chat_id = update.effective_chat.id

    if not is_admin(user_id) and update.message.text and not update.message.text.startswith('/'):
        # Messaggio non comando da utente non admin
        await update.message.reply_text("Benvenuto! Usa /start per avviare la vetrina.")
        return

    if user_id not in user_data:
        # Messaggio da admin che non è un comando e non è in un flusso specifico
        if is_admin(user_id) and update.message.text and not update.message.text.startswith('/'):
            await update.message.reply_text("Non ho capito. Usa /start per la vetrina o un comando admin come /aggiungi, /modifica, /elimina, /categoria.")
        return  # Ignora il messaggio, probabilmente è fuori da un contesto operativo

    current_state = user_data[user_id].get('state')

    # --- FASE DI AGGIUNTA PRODOTTO ---
    if current_state == ADD_PRODUCT_NAME:
        if update.message.text:
            user_data[user_id]['name'] = update.message.text
            user_data[user_id]['state'] = ADD_PRODUCT_PRICE
            next_message = await update.message.reply_text("Prezzo del prodotto?")
        else:
            next_message = await update.message.reply_text("Per favore, inserisci un nome valido.")
        last_bot_message_id[chat_id] = next_message.message_id

    elif current_state == ADD_PRODUCT_PRICE:
        if update.message.text:
            user_data[user_id]['price'] = update.message.text
            user_data[user_id]['state'] = ADD_PRODUCT_MEDIA
            next_message = await update.message.reply_text("Media del prodotto? (Invia una foto o un video)")
        else:
            next_message = await update.message.reply_text("Per favore, inserisci un prezzo valido.")
        last_bot_message_id[chat_id] = next_message.message_id

    elif current_state == ADD_PRODUCT_MEDIA:
        media_url = None
        file_extension = None
        file_id = None

        if update.message.photo:
            file_id = update.message.photo[-1].file_id  # Prendi la foto di qualità più alta
            file_extension = "jpg"
        elif update.message.video:
            file_id = update.message.video.file_id
            file_extension = "mp4"

        if file_id and file_extension:
            media_url = await save_media_from_telegram(file_id, file_extension, context)

        if media_url:
            user_data[user_id]['image'] = media_url
            user_data[user_id]['state'] = ADD_PRODUCT_CATEGORY_SELECT

            json_data = await read_products_and_categories()
            categories = json_data['categories']

            if not categories:
                next_message = await update.message.reply_text("Non ci sono categorie esistenti. Per favore, inserisci il nome della nuova categoria per questo prodotto.")
            else:
                keyboard = [[InlineKeyboardButton(cat, callback_data=f"select_category_{cat}")] for cat in categories]
                keyboard.append([InlineKeyboardButton("Crea Nuova Categoria", callback_data="create_new_category")])
                reply_markup = InlineKeyboardMarkup(keyboard)
                next_message = await update.message.reply_text("Scegli una categoria esistente o creane una nuova:", reply_markup=reply_markup)
        else:
            next_message = await update.message.reply_text("Per favore, invia una foto o un video valido.")
        last_bot_message_id[chat_id] = next_message.message_id

    elif current_state == ADD_PRODUCT_CATEGORY_SELECT:
        if update.message.text:
            new_category = update.message.text.strip()

            json_data = await read_products_and_categories()
            if new_category not in json_data['categories']:
                json_data['categories'].append(new_category)
                await write_products_and_categories(json_data)
                await update.message.reply_text(f"Categoria '{new_category}' creata e selezionata.")
            else:
                await update.message.reply_text(f"Categoria '{new_category}' già esistente e selezionata.")

            products = json_data['products']
            new_id = 1
            if products:
                new_id = max(p['id'] for p in products if isinstance(p.get('id'), int)) + 1  # Assicura che l'ID sia int

            new_product = {
                'id': new_id,
                'nome': user_data[user_id]['name'],
                'prezzo': user_data[user_id]['price'],
                'immagine': user_data[user_id]['image'],
                'tipologia': new_category
            }

            json_data['products'].append(new_product)
            await write_products_and_categories(json_data)

            await update.message.reply_text(f"Prodotto '{new_product['nome']}' aggiunto con successo alla vetrina nella categoria '{new_category}'!")

            del user_data[user_id]
        else:
            await update.message.reply_text("Per favore, inserisci un nome valido per la categoria.")

    # --- FASE DI MODIFICA PRODOTTO ---
    elif current_state == MODIFY_PRODUCT_ASK_NAME:
        if update.message.text:
            product_name_to_modify = update.message.text.lower()
            json_data = await read_products_and_categories()
            products = json_data['products']

            found_products = [p for p in products if p['nome'].lower() == product_name_to_modify]

            if not found_products:
                next_message = await update.message.reply_text("Nessun prodotto trovato con quel nome. Riprova con il nome esatto o /annulla per uscire.")
                return

            if len(found_products) > 1:
                msg_text = "Trovati più prodotti con lo stesso nome. Per favore, indica l'ID del prodotto che vuoi modificare:\n"
                for p in found_products:
                    msg_text += f"ID: {p['id']}, Nome: {p['nome']} (Categoria: {p.get('tipologia', 'N/A')})\n"
                keyboard = [[InlineKeyboardButton(f"ID: {p['id']}, Nome: {p['nome']}", callback_data=f"select_modify_product_{p['id']}")] for p in found_products]
                reply_markup = InlineKeyboardMarkup(keyboard)
                next_message = await update.message.reply_text(msg_text + "Oppure seleziona qui sotto:", reply_markup=reply_markup)
                user_data[user_id]['state'] = MODIFY_PRODUCT_ASK_FIELD  # Aspetta la selezione tramite callback
            else:
                product_to_modify = found_products[0]
                user_data[user_id]['product_id_to_modify'] = product_to_modify['id']

                keyboard = [
                    [InlineKeyboardButton("Nome", callback_data="modify_nome"),
                     InlineKeyboardButton("Prezzo", callback_data="modify_prezzo")],
                    [InlineKeyboardButton("Immagine", callback_data="modify_immagine"),
                     InlineKeyboardButton("Tipologia", callback_data="modify_tipologia")]
                ]
                reply_markup = InlineKeyboardMarkup(keyboard)

                next_message = await update.message.reply_text(
                    f"Hai selezionato '{product_to_modify['nome']}' (ID: {product_to_modify['id']}).\nQuale campo vuoi modificare?",
                    reply_markup=reply_markup
                )
                user_data[user_id]['state'] = MODIFY_PRODUCT_ASK_FIELD
        else:
            next_message = await update.message.reply_text("Per favore, inserisci un nome valido per il prodotto da modificare.")
        last_bot_message_id[chat_id] = next_message.message_id

    elif current_state == MODIFY_PRODUCT_ASK_VALUE:  # Per campi di testo (Nome, Prezzo, Tipologia)
        if update.message.text:
            field_to_modify = user_data[user_id]['field_to_modify']
            new_value = update.message.text.strip()
            product_id = user_data[user_id]['product_id_to_modify']

            json_data = await read_products_and_categories()
            products = json_data['products']
            product_found = False
            for p in products:
                if p['id'] == product_id:
                    p[field_to_modify] = new_value
                    product_found = True
                    break

            if product_found:
                await write_products_and_categories(json_data)
                await update.message.reply_text(f"Campo '{field_to_modify}' del prodotto ID {product_id} modificato con successo al valore: '{new_value}'!")
            else:
                await update.message.reply_text("Errore: Prodotto non trovato durante la modifica.")

            del user_data[user_id]
        else:
            await update.message.reply_text("Per favore, inserisci un valore valido.")

    elif current_state == MODIFY_PRODUCT_ASK_MEDIA_UPLOAD:  # Per il campo immagine (media) in modifica
        media_url = None
        file_extension = None
        file_id = None

        if update.message.photo:
            file_id = update.message.photo[-1].file_id
            file_extension = "jpg"
        elif update.message.video:
            file_id = update.message.video.file_id
            file_extension = "mp4"

        if file_id and file_extension:
            media_url = await save_media_from_telegram(file_id, file_extension, context)

        if media_url:
            field_to_modify = user_data[user_id]['field_to_modify']
            product_id = user_data[user_id]['product_id_to_modify']

            json_data = await read_products_and_categories()
            products = json_data['products']
            product_found = False
            for p in products:
                if p['id'] == product_id:
                    if 'immagine' in p and p['immagine'].startswith(BASE_URL_MEDIA):
                        old_media_filename = os.path.basename(p['immagine'])
                        old_media_filepath = os.path.join(MEDIA_DIR, old_media_filename)
                        if os.path.exists(old_media_filepath):
                            try:
                                os.remove(old_media_filepath)
                                logger.info(f"Vecchio file media {old_media_filepath} eliminato.")
                            except OSError as e:
                                logger.error(f"Errore nell'eliminazione del vecchio file media {old_media_filepath}: {e}")

                    p[field_to_modify] = media_url
                    product_found = True
                    break

            if product_found:
                await write_products_and_categories(json_data)
                await update.message.reply_text(f"Immagine/Video del prodotto ID {product_id} modificata con successo!")
            else:
                await update.message.reply_text("Errore: Prodotto non trovato durante la modifica del media.")

            del user_data[user_id]
        else:
            await update.message.reply_text("Per favore, invia una foto o un video valido.")

    # --- FASE DI GESTIONE CATEGORIE ---
    elif current_state == CATEGORY_ACTION_SELECT:
        if update.message.text:
            action = update.message.text.strip().lower()
            if action == "aggiungi":
                user_data[user_id]['state'] = ADD_CATEGORY_NAME
                next_message = await update.message.reply_text("Qual è il nome della nuova categoria che vuoi aggiungere?")
            elif action == "elimina":
                json_data = await read_products_and_categories()
                categories = json_data['categories']
                if not categories:
                    next_message = await update.message.reply_text("Non ci sono categorie da eliminare.")
                    del user_data[user_id]
                else:
                    next_message = await update.message.reply_text(
                        "Quale categoria vuoi eliminare? (Scrivi il nome esatto, ignorando maiuscole/minuscole).\n"
                        f"Categorie attuali: {', '.join(categories)}"
                    )
                    user_data[user_id]['state'] = DELETE_CATEGORY_NAME
            else:
                next_message = await update.message.reply_text("Scelta non valida. Scrivi 'aggiungi' o 'elimina'.")
        else:
            next_message = await update.message.reply_text("Per favore, scrivi 'aggiungi' o 'elimina'.")
        last_bot_message_id[chat_id] = next_message.message_id

    elif current_state == ADD_CATEGORY_NAME:
        if update.message.text:
            new_category = update.message.text.strip()
            json_data = await read_products_and_categories()

            if new_category.lower() in [c.lower() for c in json_data['categories']]:
                await update.message.reply_text(f"La categoria '{new_category}' esiste già. Nessuna modifica.")
            else:
                json_data['categories'].append(new_category)
                await write_products_and_categories(json_data)
                await update.message.reply_text(f"Categoria '{new_category}' aggiunta con successo!")

            del user_data[user_id]
        else:
            await update.message.reply_text("Per favore, inserisci un nome valido per la categoria.")

    elif current_state == DELETE_CATEGORY_NAME:
        if update.message.text:
            category_to_delete = update.message.text.strip()
            json_data = await read_products_and_categories()

            categories_lower = [c.lower() for c in json_data['categories']]
            if category_to_delete.lower() not in categories_lower:
                await update.message.reply_text(f"La categoria '{category_to_delete}' non esiste. Nessuna eliminazione.")
            else:
                original_category_name = next((c for c in json_data['categories'] if c.lower() == category_to_delete.lower()), None)
                if original_category_name:
                    json_data['categories'].remove(original_category_name)

                    products_updated_count = 0
                    for product in json_data['products']:
                        if product.get('tipologia', '').lower() == category_to_delete.lower():
                            product['tipologia'] = 'Non Assegnato'
                            products_updated_count += 1

                    await write_products_and_categories(json_data)
                    await update.message.reply_text(f"Categoria '{original_category_name}' eliminata con successo!")
                    if products_updated_count > 0:
                        await update.message.reply_text(f"Attenzione: {products_updated_count} prodotti che appartenevano alla categoria '{original_category_name}' sono stati riassegnati a 'Non Assegnato'.")
                else:
                    await update.message.reply_text(f"Errore interno: Impossibile trovare la categoria '{category_to_delete}' per l'eliminazione.")

            del user_data[user_id]
        else:
            await update.message.reply_text("Per favore, inserisci un nome valido per la categoria da eliminare.")

    # --- FASE DI ELIMINAZIONE PRODOTTO ---
    elif current_state == DELETE_PRODUCT_ASK_NAME:
        if update.message.text:
            search_term = update.message.text.strip().lower()

            json_data = await read_products_and_categories()
            products = json_data['products']

            products_to_delete = [p for p in products if search_term in p.get('nome', '').lower()]

            if not products_to_delete:
                next_message = await update.message.reply_text(f"Nessun prodotto trovato che corrisponda a '{search_term}'. Riprova o /annulla.")
                return

            if len(products_to_delete) > 1:
                keyboard = []
                for p in products_to_delete:
                    keyboard.append([InlineKeyboardButton(f"ID: {p['id']}, Nome: {p['nome']} (Categoria: {p.get('tipologia', 'N/A')})", callback_data=f"confirm_delete_{p['id']}")])
                reply_markup = InlineKeyboardMarkup(keyboard)
                next_message = await update.message.reply_text("Trovati più prodotti. Quale vuoi eliminare? Seleziona qui sotto:", reply_markup=reply_markup)
                user_data[user_id]['state'] = AWAITING_DELETE_CONFIRMATION
            else:
                await confirm_delete_product_logic(update.effective_chat.id, context, products_to_delete[0]['id'])
                if user_id in user_data:
                    del user_data[user_id]  # Assicurati di pulire lo stato
            last_bot_message_id[chat_id] = next_message.message_id if 'next_message' in locals() else None
        else:
            await update.message.reply_text("Per favore, inserisci un nome valido del prodotto da eliminare.")

    # Aggiunto per gestire il caso in cui un messaggio non è gestito dallo stato
    else:
        await update.message.reply_text("Comando non riconosciuto o stato sconosciuto. Usa /start per iniziare o un comando admin.")


async def list_products(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Mostra la lista dei prodotti attuali."""
    if not await admin_only_check(update, context):
        return
    await delete_bot_messages(update, context)  # Cancelliamo il messaggio /listaprodotti
    json_data = await read_products_and_categories()
    products = json_data['products']

    if not products:
        message = await update.message.reply_text("Nessun prodotto presente nella vetrina.")
        last_bot_message_id[update.effective_chat.id] = message.message_id
        return

    message_text = "<b>Prodotti attuali nella vetrina:</b>\n\n"
    for product in products:
        message_text += (
            f"<b>ID:</b> <code>{product.get('id', 'N/A')}</code>\n"
            f"<b>Nome:</b> {product.get('nome', 'N/A')}\n"
            f"<b>Prezzo:</b> {product.get('prezzo', 'N/A')}€\n"
            f"<b>Tipologia:</b> {product.get('tipologia', 'N/A')}\n"
            f"<b>Immagine/Video:</b> <a href='{product.get('immagine', '#')}'>Link</a>\n\n"
        )
    bot_message = await update.message.reply_html(message_text, disable_web_page_preview=True)
    last_bot_message_id[update.effective_chat.id] = bot_message.message_id


async def modify_product_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Inizia il processo di modifica di un prodotto."""
    if not await admin_only_check(update, context):
        return
    await delete_bot_messages(update, context)
    message = await update.message.reply_text("Quale prodotto vuoi modificare? Inserisci il nome esatto (ignorando maiuscole/minuscole).")
    user_data[update.effective_user.id] = {'state': MODIFY_PRODUCT_ASK_NAME}
    last_bot_message_id[update.effective_chat.id] = message.message_id


async def delete_product_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Gestisce il comando /elimina."""
    if not await admin_only_check(update, context):
        return
    await delete_bot_messages(update, context)

    if not context.args:
        message = await update.message.reply_text("Che prodotto vuoi rimuovere? Scrivi il nome del prodotto (anche parziale e ignorando maiuscole/minuscole).")
        user_data[update.effective_user.id] = {'state': DELETE_PRODUCT_ASK_NAME}
        last_bot_message_id[update.effective_chat.id] = message.message_id
    else:
        search_term = " ".join(context.args)
        await process_delete_product_request(update, context, search_term)


async def process_delete_product_request(update: Update, context: ContextTypes.DEFAULT_TYPE, search_term: str):
    user_id = update.effective_user.id
    chat_id = update.effective_chat.id
    json_data = await read_products_and_categories()
    products = json_data['products']

    products_to_delete = []

    try:
        product_id_str = search_term.replace('ID: ', '').strip()  # Pulisce la stringa se viene da un callback o input utente
        product_id = int(product_id_str)
        product = next((p for p in products if p.get('id') == product_id), None)
        if product:
            products_to_delete.append(product)
    except ValueError:
        products_to_delete = [p for p in products if search_term.lower() in p.get('nome', '').lower()]

    if not products_to_delete:
        message = await update.effective_chat.send_message(f"Nessun prodotto trovato che corrisponda a '{search_term}'.")
        last_bot_message_id[chat_id] = message.message_id
        return

    if len(products_to_delete) > 1:
        keyboard = []
        for p in products_to_delete:
            keyboard.append([InlineKeyboardButton(f"ID: {p['id']}, Nome: {p['nome']} (Categoria: {p.get('tipologia', 'N/A')})", callback_data=f"confirm_delete_{p['id']}")])
        reply_markup = InlineKeyboardMarkup(keyboard)
        message = await update.effective_chat.send_message("Trovati più prodotti. Quale vuoi eliminare? Seleziona qui sotto:", reply_markup=reply_markup)
        user_data[user_id] = {'state': AWAITING_DELETE_CONFIRMATION}  # Imposta lo stato per attendere la conferma tramite callback
        last_bot_message_id[chat_id] = message.message_id
        return

    product_to_remove = products_to_delete[0]
    await confirm_delete_product_logic(update.effective_chat.id, context, product_to_remove['id'])
    if user_id in user_data:
        del user_data[user_id]  # Pulisci lo stato dopo l'eliminazione diretta


async def confirm_delete_product_logic(chat_id: int, context: ContextTypes.DEFAULT_TYPE, product_id: int):
    """Logica per la conferma e l'eliminazione effettiva di un prodotto."""
    json_data = await read_products_and_categories()
    products = json_data['products']

    product_to_delete_obj = next((p for p in products if p.get('id') == product_id), None)

    if not product_to_delete_obj:
        await context.bot.send_message(chat_id=chat_id, text=f"Errore: Prodotto con ID {product_id} non trovato per l'eliminazione.")
        return

    # Elimina il file media associato, se presente e se è un URL locale
    if 'immagine' in product_to_delete_obj:
        image_url = product_to_delete_obj['immagine']
        if image_url and image_url.startswith(BASE_URL_MEDIA):
            media_filename = os.path.basename(image_url)
            media_filepath = os.path.join(MEDIA_DIR, media_filename)
            if os.path.exists(media_filepath):
                try:
                    os.remove(media_filepath)
                    logger.info(f"File media {media_filepath} eliminato.")
                except OSError as e:
                    logger.error(f"Errore nell'eliminazione del file media {media_filepath}: {e}")

    initial_len = len(products)
    json_data['products'] = [p for p in products if p.get('id') != product_id]

    if len(json_data['products']) < initial_len:
        await write_products_and_categories(json_data)
        await context.bot.send_message(chat_id=chat_id, text=f"Prodotto '{product_to_delete_obj.get('nome', 'Sconosciuto')}' (ID: {product_id}) eliminato con successo!")
    else:
        await context.bot.send_message(chat_id=chat_id, text=f"Nessun prodotto trovato con ID {product_id}.")


async def category_management_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Inizia il flusso di gestione delle categorie."""
    if not await admin_only_check(update, context):
        return
    await delete_bot_messages(update, context)
    keyboard = [
        [InlineKeyboardButton("Aggiungi Categoria", callback_data="category_add")],
        [InlineKeyboardButton("Elimina Categoria", callback_data="category_delete")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    message = await update.message.reply_text("Cosa vuoi fare con le categorie?", reply_markup=reply_markup)
    user_data[update.effective_user.id] = {'state': CATEGORY_ACTION_SELECT}
    last_bot_message_id[update.effective_chat.id] = message.message_id


async def handle_callback_query(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Gestisce le callback query dai pulsanti inline."""
    query = update.callback_query
    await query.answer()  # Rispondi alla query per rimuovere lo stato di caricamento dal pulsante

    user_id = query.from_user.id
    chat_id = query.message.chat_id
    data = query.data

    # Logica per la selezione della categoria durante l'aggiunta prodotto
    if user_id in user_data and user_data[user_id].get('state') == ADD_PRODUCT_CATEGORY_SELECT:
        if data.startswith("select_category_"):
            selected_category = data.replace("select_category_", "")

            # Ora salva il prodotto con la categoria selezionata
            json_data = await read_products_and_categories()
            products = json_data['products']
            new_id = 1
            if products:
                new_id = max(p['id'] for p in products if isinstance(p.get('id'), int)) + 1

            new_product = {
                'id': new_id,
                'nome': user_data[user_id]['name'],
                'prezzo': user_data[user_id]['price'],
                'immagine': user_data[user_id]['image'],
                'tipologia': selected_category
            }

            json_data['products'].append(new_product)
            await write_products_and_categories(json_data)

            await query.edit_message_text(f"Prodotto '{new_product['nome']}' aggiunto con successo alla vetrina nella categoria '{selected_category}'!")

            del user_data[user_id]
            return

        elif data == "create_new_category":
            await query.edit_message_text("Ok, per favore inserisci il nome della nuova categoria:")
            # Lo stato rimane ADD_PRODUCT_CATEGORY_SELECT e il prossimo messaggio di testo verrà gestito lì
            return

    # Logica per la selezione del campo da modificare
    elif user_id in user_data and user_data[user_id].get('state') == MODIFY_PRODUCT_ASK_FIELD:
        if data.startswith("select_modify_product_"):
            product_id_to_modify = int(data.replace("select_modify_product_", ""))
            user_data[user_id]['product_id_to_modify'] = product_id_to_modify

            json_data = await read_products_and_categories()
            product_to_modify = next((p for p in json_data['products'] if p['id'] == product_id_to_modify), None)

            if not product_to_modify:
                await query.edit_message_text("Errore: Prodotto non trovato.")
                del user_data[user_id]
                return

            keyboard = [
                [InlineKeyboardButton("Nome", callback_data="modify_nome"),
                 InlineKeyboardButton("Prezzo", callback_data="modify_prezzo")],
                [InlineKeyboardButton("Immagine", callback_data="modify_immagine"),
                 InlineKeyboardButton("Tipologia", callback_data="modify_tipologia")]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)

            await query.edit_message_text(
                f"Hai selezionato '{product_to_modify['nome']}' (ID: {product_to_modify['id']}).\nQuale campo vuoi modificare?",
                reply_markup=reply_markup
            )
            return

        if data.startswith("modify_"):
            field = data.replace("modify_", "")
            user_data[user_id]['field_to_modify'] = field

            if field == "immagine":
                await query.edit_message_text(f"Ok, invia la nuova immagine o video per il prodotto ID {user_data[user_id]['product_id_to_modify']}.")
                user_data[user_id]['state'] = MODIFY_PRODUCT_ASK_MEDIA_UPLOAD
            elif field == "tipologia":
                json_data = await read_products_and_categories()
                categories = json_data['categories']
                if not categories:
                    await query.edit_message_text("Non ci sono categorie esistenti. Per favore, inserisci il nome della nuova categoria per questo prodotto.")
                    user_data[user_id]['state'] = MODIFY_PRODUCT_ASK_VALUE  # Trattalo come un input testuale
                else:
                    keyboard = [[InlineKeyboardButton(cat, callback_data=f"select_modify_category_{cat}")] for cat in categories]
                    keyboard.append([InlineKeyboardButton("Crea Nuova Categoria", callback_data="create_new_category_modify")])
                    reply_markup = InlineKeyboardMarkup(keyboard)
                    await query.edit_message_text("Scegli una categoria esistente o creane una nuova:", reply_markup=reply_markup)
                    user_data[user_id]['state'] = MODIFY_PRODUCT_ASK_VALUE  # Aspetta ora la selezione o input
            else:
                await query.edit_message_text(f"Ok, invia il nuovo valore per il campo '{field}' del prodotto ID {user_data[user_id]['product_id_to_modify']}.")
                user_data[user_id]['state'] = MODIFY_PRODUCT_ASK_VALUE
            return

        elif data.startswith("select_modify_category_"):
            selected_category = data.replace("select_modify_category_", "")
            product_id = user_data[user_id]['product_id_to_modify']

            json_data = await read_products_and_categories()
            for p in json_data['products']:
                if p['id'] == product_id:
                    p['tipologia'] = selected_category
                    break
            await write_products_and_categories(json_data)
            await query.edit_message_text(f"Categoria del prodotto ID {product_id} modificata con successo a '{selected_category}'!")
            del user_data[user_id]
            return

        elif data == "create_new_category_modify":
            await query.edit_message_text("Ok, per favore inserisci il nome della nuova categoria per questo prodotto.")
            user_data[user_id]['field_to_modify'] = 'tipologia'  # Assicurati che il campo sia corretto
            user_data[user_id]['state'] = MODIFY_PRODUCT_ASK_VALUE  # Attende l'input testuale
            return

    # Logica per la conferma eliminazione prodotto
    elif user_id in user_data and user_data[user_id].get('state') == AWAITING_DELETE_CONFIRMATION:
        if data.startswith("confirm_delete_"):
            product_id_to_delete = int(data.replace("confirm_delete_", ""))
            await confirm_delete_product_logic(chat_id, context, product_id_to_delete)
            await query.edit_message_text(f"Prodotto ID {product_id_to_delete} eliminato.")
            del user_data[user_id]
            return

    # Logica per la gestione categorie
    elif user_id in user_data and user_data[user_id].get('state') == CATEGORY_ACTION_SELECT:
        if data == "category_add":
            await query.edit_message_text("Qual è il nome della nuova categoria che vuoi aggiungere?")
            user_data[user_id]['state'] = ADD_CATEGORY_NAME
        elif data == "category_delete":
            json_data = await read_products_and_categories()
            categories = json_data['categories']
            if not categories:
                await query.edit_message_text("Non ci sono categorie da eliminare.")
                del user_data[user_id]
                return

            message_text = "Quale categoria vuoi eliminare? (Scrivi il nome esatto, ignorando maiuscole/minuscole).\nCategorie attuali: " + ", ".join(categories)
            await query.edit_message_text(message_text)
            user_data[user_id]['state'] = DELETE_CATEGORY_NAME
        return

    # Se una callback query non è gestita, informiamo l'utente
    else:
        await query.edit_message_text("Azione non riconosciuta o sessione scaduta. Per favore, riprova con un comando.")
        if user_id in user_data:
            del user_data[user_id]  # Pulisci lo stato se non riconosciuto


async def unhandled_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Gestisce tutti i messaggi che non sono stati gestiti da altri handler."""
    if update.effective_user.id != ADMIN_ID:
        await update.message.reply_text("Benvenuto! Usa /start per avviare la vetrina.")
    else:
        # Se è un admin e il messaggio non è stato gestito, potrebbe essere un errore o un comando non riconosciuto
        if update.message.text and not update.message.text.startswith('/'):
            await update.message.reply_text("Non ho capito. Usa /start per la vetrina o un comando admin come /aggiungi, /modifica, /elimina, /categoria.")
        else:  # Per comandi sconosciuti o altri tipi di messaggi
            await update.message.reply_text("Comando non riconosciuto o tipo di messaggio non gestito. Usa /start per la vetrina.")


# --- Configurazione e Avvio del Bot ---
def main() -> None:
    """Funzione principale per l'avvio del bot."""
    # Inizializza l'applicazione python-telegram-bot
    application = Application.builder().token(BOT_TOKEN).build()

    # Callback per impostare il webhook all'avvio dell'applicazione
    async def post_init(app_instance: Application):
        webhook_host = os.getenv("RENDER_EXTERNAL_HOSTNAME")
        if not webhook_host:
            logger.critical("RENDER_EXTERNAL_HOSTNAME non trovato. Impossibile impostare il webhook.")
            exit(1)  # Termina se l'host non è configurato

        webhook_url_full = f"https://{webhook_host}/{BOT_TOKEN}"
        await app_instance.bot.set_webhook(url=webhook_url_full)
        logger.info(f"Webhook impostato su: {webhook_url_full}")

    application.post_init = post_init

    # Aggiungi gli handler per i comandi e i messaggi
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("aggiungi", add_product_start))
    application.add_handler(CommandHandler("listaprodotti", list_products))
    application.add_handler(CommandHandler("modifica", modify_product_start))
    application.add_handler(CommandHandler("elimina", delete_product_command))
    application.add_handler(CommandHandler("categoria", category_management_start))

    # Handler per i messaggi testuali e media (foto/video)
    application.add_handler(MessageHandler(filters.PHOTO | filters.VIDEO | filters.TEXT & ~filters.COMMAND, handle_message))

    # Handler per le callback query (pulsanti inline)
    application.add_handler(CallbackQueryHandler(handle_callback_query))

    # Handler per i comandi non riconosciuti
    application.add_handler(MessageHandler(filters.COMMAND, unhandled_message))

    # Handler per tutti i messaggi non gestiti dagli altri handler (dovrebbe essere l'ultimo)
    application.add_handler(MessageHandler(filters.ALL, unhandled_message))

    # Rotta per il webhook (Flask)
    @app.route(f"/{BOT_TOKEN}", methods=["POST"])
    async def webhook_handler():
        if request.method == "POST":
            update_data = request.get_json(force=True)
            logger.info(f"Received webhook update: {update_data}")
            # Processa l'update con l'applicazione python-telegram-bot
            # Questo è il modo corretto per passare l'update a PTB in un contesto Flask/Webhook
            update = Update.de_json(update_data, application.bot)
            await application.process_update(update)
        return "ok"

    # Avvia l'applicazione PTB (ma non il polling, lo avvia 'logicamente' per i webhook)
    # application.run_polling() # Rimosso, non usato con i webhook su Render

    # Questo blocco if __name__ == '__main__': non è per l'ambiente Render con Gunicorn.
    # Gunicorn userà la variabile 'app' da wsgi.py per avviare l'applicazione Flask.
    # L'Application di python-telegram-bot viene inizializzata e il webhook viene impostato
    # quando il modulo viene caricato da Gunicorn.
    logger.info("Bot Telegram configurato. In attesa di webhook tramite Flask/Gunicorn.")


# Chiamata alla funzione main per configurare l'applicazione PTB
main()

# Questo blocco è per l'esecuzione diretta del file (es. python bot.py) per test locali.
# Render userà 'wsgi.py' per avviare l'applicazione 'app'.
if __name__ == '__main__':
    # Per testare Flask localmente e l'endpoint del webhook
    # Assicurati che BOT_TOKEN e ADMIN_ID siano definiti direttamente o tramite variabili d'ambiente locali
    # E che BASE_URL_MEDIA e MINI_APP_URL siano anch'essi configurati per il testing locale.
    # Per testare i webhook localmente, avresti bisogno di uno strumento come ngrok per esporre il tuo localhost.
    port = int(os.getenv("PORT", 5000))
    # Il logger di Flask potrebbe essere troppo verboso, puoi limitarlo
    logging.getLogger('werkzeug').setLevel(logging.WARNING)
    logger.info(f"Avvio del server Flask locale sulla porta {port}...")
    app.run(host='0.0.0.0', port=port, debug=True)
