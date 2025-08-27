import logging
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, InputMediaPhoto
from telegram.error import TelegramError
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes, CallbackQueryHandler
import json
import os
import asyncio
import uuid # Per generare nomi file univoci
from flask import Flask, send_from_directory, request
from threading import Thread # Per eseguire Flask in un thread separato
import time # Per un piccolo ritardo all'avvio del server Flask
# ... (le tue importazioni esistenti) ...
from flask import Flask, send_from_directory, request
import os # Assicurati che os sia importato

# Inizializza l'app Flask. Importante: la variabile 'app' deve essere definita prima di essere usata in wsgi.py
app = Flask(__name__) 


@app.route('/media/<path:filename>')
def serve_media(filename):
    return send_from_directory(MEDIA_DIR, filename)

# Configura il logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO
)
logger = logging.getLogger(__name__)

# TOKEN del tuo bot Telegram (sostituisci con il tuo vero token)
BOT_TOKEN = "IL_TUO_BOT_TOKEN_QUI" # <--- SOSTITUISCI QUESTO!

# ID utente dell'amministratore (solo questo utente potrà usare i comandi admin)
ADMIN_ID = 123456789 # <--- SOSTITUISCI CON IL TUO ID ADMIN

# Percorsi dei file e delle directory
PRODUCTS_FILE = 'products.json' 
MEDIA_DIR = 'media/' # Directory dove salveremo i media caricati

# BASE_URL_MEDIA deve essere l'URL pubblico della cartella MEDIA_DIR
# IMPORTANTISSIMO per Render: questo sarà l'URL del tuo servizio Render + /media/
# Esempio per Render: "https://your-render-service-name.onrender.com/media/"
# Esempio per sviluppo locale: "http://localhost:8000/media/"
BASE_URL_MEDIA = "https://your-render-service-name.onrender.com/media/" # <--- SOSTITUISCI CON IL TUO URL PUBBLICO REALE!

# URL della tua Mini App (per Netlify, deve essere HTTPS)
# Esempio per Netlify: "https://your-netlify-site-name.netlify.app/vetrina.html"
MINI_APP_URL = "https://your-netlify-site-name.netlify.app/vetrina.html" # <--- SOSTITUISCI CON IL TUO URL PUBBLICO REALE!


# --- Variabili globali per lo stato del bot ---
user_data = {} 
last_bot_message_id = {} 

# --- Stati per la macchina a stati finiti ---
# Stati per l'aggiunta prodotto
ADD_PRODUCT_NAME = 1
ADD_PRODUCT_PRICE = 2
ADD_PRODUCT_MEDIA = 3
ADD_PRODUCT_CATEGORY_SELECT = 4 # Stato per la selezione della categoria esistente o nuova

# Stati per la modifica prodotto
MODIFY_PRODUCT_ASK_NAME = 10
MODIFY_PRODUCT_ASK_FIELD = 11
MODIFY_PRODUCT_ASK_MEDIA_UPLOAD = 13
MODIFY_PRODUCT_ASK_VALUE = 12 

# Stati per la gestione delle categorie
CATEGORY_ACTION_SELECT = 20 # Scegli aggiungi o elimina
ADD_CATEGORY_NAME = 21 # Chiede il nome della nuova categoria
DELETE_CATEGORY_NAME = 22 # Chiede il nome della categoria da eliminare

# Stati per l'eliminazione prodotto
DELETE_PRODUCT_ASK_NAME = 30
AWAITING_DELETE_CONFIRMATION = 31 # Nuovo stato per la conferma eliminazione


# --- Funzioni di utilità per la gestione del file JSON ---
async def read_products_and_categories():
    """Legge prodotti e categorie dal file JSON."""
    async with asyncio.Lock(): 
        if not os.path.exists(PRODUCTS_FILE) or os.path.getsize(PRODUCTS_FILE) == 0:
            initial_data = {'products': [], 'categories': []}
            with open(PRODUCTS_FILE, 'w', encoding='utf-8') as f:
                json.dump(initial_data, f, indent=2, ensure_ascii=False)
            return {'products': [], 'categories': []}
        
        with open(PRODUCTS_FILE, 'r', encoding='utf-8') as f:
            try:
                data = json.load(f)
                # Assicurati che le chiavi 'products' e 'categories' esistano
                if 'products' not in data:
                    data['products'] = []
                if 'categories' not in data:
                    data['categories'] = []
                return data
            except json.JSONDecodeError:
                logger.error(f"Errore: Il file {PRODUCTS_FILE} non è un JSON valido. Inizializzo con array vuoto.")
                initial_data = {'products': [], 'categories': []}
                with open(PRODUCTS_FILE, 'w', encoding='utf-8') as f_write:
                    json.dump(initial_data, f_write, indent=2, ensure_ascii=False)
                return {'products': [], 'categories': []}

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
    user_message_id = update.message.message_id 

    try:
        await context.bot.delete_message(chat_id=chat_id, message_id=user_message_id)
    except TelegramError as e:
        logger.warning(f"Impossibile cancellare il messaggio utente {user_message_id}: {e}")

    if chat_id in last_bot_message_id:
        try:
            await context.bot.delete_message(chat_id=chat_id, message_id=last_bot_message_id[chat_id])
            del last_bot_message_id[chat_id]
        except TelegramError as e:
            logger.warning(f"Impossibile cancellare l'ultimo messaggio del bot {last_bot_message_id[chat_id]}: {e}")

async def send_start_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Invia il messaggio di benvenuto con logo e pulsante Mini App."""
    if update.message: # Solo se il comando /start proviene da un messaggio
        await delete_bot_messages(update, context) 

    keyboard = [
        [InlineKeyboardButton("Avvia Vetrina", web_app={"url": MINI_APP_URL})]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)

    # Puoi impostare un logo qui o lasciare che sia solo testo
    logo_url = "https://www.freeiconspng.com/uploads/logo-new-png-5.png" # <--- Sostituisci con il tuo logo
    caption = "Benvenuto nella vetrina dei prodotti! Clicca qui sotto per il menu."

    try:
        if logo_url and not logo_url.strip() == "": # Verifica se l'URL del logo è valido
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

# --- Funzione per salvare i media ---
async def save_media_from_telegram(file_id: str, file_extension: str, context: ContextTypes.DEFAULT_TYPE) -> str:
    """
    Scarica un file da Telegram e lo salva nella directory media/.
    Restituisce l'URL pubblico del file salvato.
    """
    if not os.path.exists(MEDIA_DIR):
        os.makedirs(MEDIA_DIR) # Crea la directory se non esiste

    new_filename = f"{uuid.uuid4()}.{file_extension}" # Nome file univoco
    file_path = os.path.join(MEDIA_DIR, new_filename)

    file_obj = await context.bot.get_file(file_id)
    await file_obj.download_to_drive(file_path)

    return f"{BASE_URL_MEDIA}{new_filename}"

# --- Comandi Admin ---
async def admin_only_check(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    """Verifica se l'utente è l'admin e invia un messaggio di avviso in caso contrario."""
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("Non sei autorizzato a usare questo comando.")
        return False
    return True

async def add_product_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Inizia il processo di aggiunta di un prodotto."""
    if not await admin_only_check(update, context):
        return

    await update.message.reply_text("Ok, iniziamo ad aggiungere un nuovo prodotto.\nNome del prodotto?")
    user_data[update.effective_user.id] = {'state': ADD_PRODUCT_NAME}

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Gestisce i messaggi in base allo stato corrente dell'utente."""
    user_id = update.effective_user.id
    chat_id = update.effective_chat.id

    if not is_admin(user_id):
        # Se non è admin, e non ha usato /start, gli diciamo cosa fare
        if update.message.text and not update.message.text.startswith('/'):
            await update.message.reply_text("Benvenuto! Usa /start per avviare la vetrina.")
        return # Ignora i messaggi da non-admin che non sono comandi specifici

    if user_id not in user_data:
        # Se l'utente è admin ma non è in un flusso di aggiunta/modifica, e ha scritto un testo non comando
        if update.message.text and not update.message.text.startswith('/'):
            await update.message.reply_text("Non ho capito. Usa /start per la vetrina o un comando admin come /aggiungi, /modifica, /elimina, /categoria.")
        return # Ignora il messaggio, probabilmente è fuori da un contesto operativo

    current_state = user_data[user_id].get('state')

    # --- FASE DI AGGIUNTA PRODOTTO ---
    if current_state == ADD_PRODUCT_NAME:
        if update.message.text:
            user_data[user_id]['name'] = update.message.text
            user_data[user_id]['state'] = ADD_PRODUCT_PRICE
            await update.message.reply_text("Prezzo del prodotto?")
        else:
            await update.message.reply_text("Per favore, inserisci un nome valido.")

    elif current_state == ADD_PRODUCT_PRICE:
        if update.message.text:
            user_data[user_id]['price'] = update.message.text # Prezzo come stringa, verrà mostrato così
            user_data[user_id]['state'] = ADD_PRODUCT_MEDIA
            await update.message.reply_text("Media del prodotto? (Invia una foto o un video)")
        else:
            await update.message.reply_text("Per favore, inserisci un prezzo valido.")

    elif current_state == ADD_PRODUCT_MEDIA:
        media_url = None
        if update.message.photo:
            file_id = update.message.photo[-1].file_id # Prendi la foto di qualità più alta
            media_url = await save_media_from_telegram(file_id, "jpg", context)
        elif update.message.video:
            file_id = update.message.video.file_id
            media_url = await save_media_from_telegram(file_id, "mp4", context) # O l'estensione appropriata

        if media_url:
            user_data[user_id]['image'] = media_url
            user_data[user_id]['state'] = ADD_PRODUCT_CATEGORY_SELECT
            
            json_data = await read_products_and_categories()
            categories = json_data['categories']
            
            if not categories:
                # Se non ci sono categorie, chiedi di crearne una nuova
                await update.message.reply_text("Non ci sono categorie esistenti. Per favore, inserisci il nome della nuova categoria per questo prodotto.")
                user_data[user_id]['state'] = ADD_PRODUCT_CATEGORY_SELECT # Resta in questo stato, ma si aspetta un input testuale
            else:
                # Mostra le categorie esistenti e l'opzione per crearne una nuova
                keyboard = [[InlineKeyboardButton(cat, callback_data=f"select_category_{cat}")] for cat in categories]
                keyboard.append([InlineKeyboardButton("Crea Nuova Categoria", callback_data="create_new_category")])
                reply_markup = InlineKeyboardMarkup(keyboard)
                await update.message.reply_text("Scegli una categoria esistente o creane una nuova:", reply_markup=reply_markup)
        else:
            await update.message.reply_text("Per favore, invia una foto o un video valido.")

    elif current_state == ADD_PRODUCT_CATEGORY_SELECT:
        if update.message.text: # L'utente ha digitato una nuova categoria
            new_category = update.message.text.strip()
            
            json_data = await read_products_and_categories()
            if new_category not in json_data['categories']:
                json_data['categories'].append(new_category)
                await write_products_and_categories(json_data)
                await update.message.reply_text(f"Categoria '{new_category}' creata e selezionata.")
            else:
                await update.message.reply_text(f"Categoria '{new_category}' già esistente e selezionata.")

            # Ora salva il prodotto
            products = json_data['products']
            new_id = 1
            if products:
                new_id = max(p['id'] for p in products) + 1
            
            new_product = {
                'id': new_id,
                'nome': user_data[user_id]['name'],
                'prezzo': user_data[user_id]['price'],
                'immagine': user_data[user_id]['image'],
                'tipologia': new_category # Usa la categoria appena creata/selezionata
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
                await update.message.reply_text("Nessun prodotto trovato con quel nome. Riprova con il nome esatto o /annulla per uscire.")
                return
            
            if len(found_products) > 1:
                msg_text = "Trovati più prodotti con lo stesso nome. Per favore, indica l'ID del prodotto che vuoi modificare:\n"
                for p in found_products:
                    msg_text += f"ID: {p['id']}, Nome: {p['nome']} (Categoria: {p.get('tipologia', 'N/A')})\n"
                # Fornisci l'opzione per selezionare con pulsante
                keyboard = [[InlineKeyboardButton(f"ID: {p['id']}, Nome: {p['nome']}", callback_data=f"select_modify_product_{p['id']}")] for p in found_products]
                reply_markup = InlineKeyboardMarkup(keyboard)
                await update.message.reply_text(msg_text + "Oppure seleziona qui sotto:", reply_markup=reply_markup)
                user_data[user_id]['state'] = MODIFY_PRODUCT_ASK_FIELD # Aspetta la selezione tramite callback
                return

            product_to_modify = found_products[0]
            user_data[user_id]['product_id_to_modify'] = product_to_modify['id']
            
            keyboard = [
                [InlineKeyboardButton("Nome", callback_data="modify_nome"),
                 InlineKeyboardButton("Prezzo", callback_data="modify_prezzo")],
                [InlineKeyboardButton("Immagine", callback_data="modify_immagine"),
                 InlineKeyboardButton("Tipologia", callback_data="modify_tipologia")]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)
            
            await update.message.reply_text(
                f"Hai selezionato '{product_to_modify['nome']}' (ID: {product_to_modify['id']}).\nQuale campo vuoi modificare?",
                reply_markup=reply_markup
            )
            user_data[user_id]['state'] = MODIFY_PRODUCT_ASK_FIELD
        else:
            await update.message.reply_text("Per favor, inserisci un nome valido per il prodotto da modificare.")

    elif current_state == MODIFY_PRODUCT_ASK_VALUE: # Per campi di testo (Nome, Prezzo, Tipologia)
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
            await update.message.reply_text("Per favor, inserisci un valore valido.")

    elif current_state == MODIFY_PRODUCT_ASK_MEDIA_UPLOAD: # Per il campo immagine (media) in modifica
        media_url = None
        if update.message.photo:
            file_id = update.message.photo[-1].file_id
            media_url = await save_media_from_telegram(file_id, "jpg", context)
        elif update.message.video:
            file_id = update.message.video.file_id
            media_url = await save_media_from_telegram(file_id, "mp4", context)

        if media_url:
            field_to_modify = user_data[user_id]['field_to_modify'] # Dovrebbe essere 'immagine'
            product_id = user_data[user_id]['product_id_to_modify']
            
            json_data = await read_products_and_categories()
            products = json_data['products']
            product_found = False
            for p in products:
                if p['id'] == product_id:
                    # Se c'era un vecchio media, prova a eliminarlo
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
            await update.message.reply_text("Per favor, invia una foto o un video valido.")

    # --- FASE DI GESTIONE CATEGORIE ---
    elif current_state == CATEGORY_ACTION_SELECT:
        if update.message.text:
            action = update.message.text.strip().lower()
            if action == "aggiungi":
                user_data[user_id]['state'] = ADD_CATEGORY_NAME
                await update.message.reply_text("Qual è il nome della nuova categoria che vuoi aggiungere?")
            elif action == "elimina":
                json_data = await read_products_and_categories()
                categories = json_data['categories']
                if not categories:
                    await update.message.reply_text("Non ci sono categorie da eliminare.")
                    del user_data[user_id]
                    return
                
                await update.message.reply_text(
                    "Quale categoria vuoi eliminare? (Scrivi il nome esatto, ignorando maiuscole/minuscole).\n"
                    f"Categorie attuali: {', '.join(categories)}"
                )
                user_data[user_id]['state'] = DELETE_CATEGORY_NAME
            else:
                await update.message.reply_text("Scelta non valida. Scrivi 'aggiungi' o 'elimina'.")
        else:
            await update.message.reply_text("Per favor, scrivi 'aggiungi' o 'elimina'.")

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
            await update.message.reply_text("Per favor, inserisci un nome valido per la categoria.")

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
                    
                    # Aggiorna i prodotti che usano questa categoria
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
            await update.message.reply_text("Per favor, inserisci un nome valido per la categoria da eliminare.")
    
    # --- FASE DI ELIMINAZIONE PRODOTTO ---
    elif current_state == DELETE_PRODUCT_ASK_NAME:
        if update.message.text:
            search_term = update.message.text.strip().lower()
            
            json_data = await read_products_and_categories()
            products = json_data['products']
            
            products_to_delete = [p for p in products if search_term in p.get('nome', '').lower()]

            if not products_to_delete:
                await update.message.reply_text(f"Nessun prodotto trovato che corrisponda a '{search_term}'. Riprova o /annulla.")
                return
            
            if len(products_to_delete) > 1:
                keyboard = []
                for p in products_to_delete:
                    keyboard.append([InlineKeyboardButton(f"ID: {p['id']}, Nome: {p['nome']} (Categoria: {p.get('tipologia', 'N/A')})", callback_data=f"confirm_delete_{p['id']}")])
                reply_markup = InlineKeyboardMarkup(keyboard)
                await update.message.reply_text("Trovati più prodotti. Quale vuoi eliminare? Seleziona qui sotto:", reply_markup=reply_markup)
                user_data[user_id]['state'] = AWAITING_DELETE_CONFIRMATION
            else:
                await confirm_delete_product(update, context, products_to_delete[0]['id'])
                del user_data[user_id] # Termina il processo dopo l'eliminazione
        else:
            await update.message.reply_text("Per favor, inserisci un nome valido del prodotto da eliminare.")

    else:
        await update.message.reply_text("Comando non riconosciuto o stato sconosciuto. Usa /start per iniziare o un comando admin.")

async def list_products(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Mostra la lista dei prodotti attuali."""
    if not await admin_only_check(update, context):
        return

    json_data = await read_products_and_categories()
    products = json_data['products']

    if not products:
        await update.message.reply_text("Nessun prodotto presente nella vetrina.")
        return

    message = "<b>Prodotti attuali nella vetrina:</b>\n\n"
    for product in products:
        message += (
            f"<b>ID:</b> <code>{product.get('id', 'N/A')}</code>\n"
            f"<b>Nome:</b> {product.get('nome', 'N/A')}\n"
            f"<b>Prezzo:</b> €{product.get('prezzo', 'N/A')}\n"
            f"<b>Tipologia:</b> {product.get('tipologia', 'N/A')}\n"
            f"<b>Immagine/Video:</b> <a href='{product.get('immagine', '#')}'>Link</a>\n\n"
        )
    await update.message.reply_html(message, disable_web_page_preview=True) 

async def delete_product_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Gestisce il comando /elimina."""
    if not await admin_only_check(update, context):
        return

    if not context.args:
        await update.message.reply_text("Che prodotto vuoi rimuovere? Scrivi il nome del prodotto (anche parziale e ignorando maiuscole/minuscole).")
        user_data[update.effective_user.id] = {'state': DELETE_PRODUCT_ASK_NAME}
    else:
        # Se hanno fornito un argomento direttamente, prova a eliminarlo
        search_term = " ".join(context.args)
        await process_delete_product_request(update, context, search_term)

async def process_delete_product_request(update: Update, context: ContextTypes.DEFAULT_TYPE, search_term: str):
    user_id = update.effective_user.id
    json_data = await read_products_and_categories()
    products = json_data['products']
    
    products_to_delete = []
    
    # Cerca per ID
    try:
        product_id = int(search_term)
        product = next((p for p in products if p.get('id') == product_id), None)
        if product:
            products_to_delete.append(product)
    except ValueError:
        # Cerca per nome (case-insensitive, anche parziale)
        products_to_delete = [p for p in products if search_term.lower() in p.get('nome', '').lower()]

    if not products_to_delete:
        await update.effective_chat.send_message(f"Nessun prodotto trovato che corrisponda a '{search_term}'.")
        return
    
    if len(products_to_delete) > 1:
        keyboard = []
        for p in products_to_delete:
            keyboard.append([InlineKeyboardButton(f"ID: {p['id']}, Nome: {p['nome']} (Categoria: {p.get('tipologia', 'N/A')})", callback_data=f"confirm_delete_{p['id']}")])
        reply_markup = InlineKeyboardMarkup(keyboard)
        await update.effective_chat.send_message("Trovati più prodotti. Quale vuoi eliminare? Seleziona qui sotto:", reply_markup=reply_markup)
        user_data[user_id]['state'] = AWAITING_DELETE_CONFIRMATION
        return

    # Se un solo prodotto trovato o specificato da ID
    product_to_remove = products_to_delete[0]
    await confirm_delete_product_logic(update.effective_chat.id, context, product_to_remove['id'])


async def confirm_delete_product_logic(chat_id: int, context: ContextTypes.DEFAULT_TYPE, product_id: int):
    json_data = await read_products_and_categories()
    products = json_data['products']
    
    product_to_delete_obj = next((p for p in products if p.get('id') == product_id), None)
    
    if not product_to_delete_obj:
        await context.bot.send_message(chat_id=chat_id, text=f"Errore: Prodotto con ID {product_id} non trovato per l'eliminazione.")
        return

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