#!/usr/bin/env python3
"""
Bot de Telegram para seguimiento de series
Autor: Assistant
Fecha: 2025
"""

import logging
import json
import os
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple
import asyncio
import aiohttp
import csv
import io

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, InputFile
from telegram.ext import (
    Application, 
    CommandHandler, 
    CallbackQueryHandler, 
    MessageHandler, 
    filters, 
    ContextTypes,
    ConversationHandler
)

# Configuración de logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Configuración
TELEGRAM_TOKEN = "8330446033:AAGS0lI8HwD094x51yY9EqOFyDrshc-gOu4"
TMDB_API_KEY = "01cd640b434a6e8273b7d0a7e8d31fcd"
TMDB_BASE_URL = "https://api.themoviedb.org/3"
TMDB_IMAGE_BASE_URL = "https://image.tmdb.org/t/p/w500"

# Estados de conversación
(
    SEARCHING_SERIES,
    SELECTING_SERIES,
    SELECTING_SEASON,
    SERIES_ENDED,
    NEXT_SEASON_DATE,
    EDITING_SERIES,
    EDITING_FIELD,
    DELETING_SERIES,
    SEARCHING_IN_LIST
) = range(9)

# Archivo de datos
DATA_FILE = "series_data.json"

class SeriesBot:
    def __init__(self):
        self.data = self.load_data()
    
    def load_data(self) -> Dict:
        """Carga los datos desde el archivo JSON"""
        if os.path.exists(DATA_FILE):
            try:
                with open(DATA_FILE, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    # CORRECCIÓN: Validar estructura de datos
                    if not isinstance(data, dict):
                        return {"series": {}}
                    return data
            except (json.JSONDecodeError, FileNotFoundError, UnicodeDecodeError) as e:
                logger.error(f"Error cargando datos: {e}")
                return {"series": {}}
        return {"series": {}}
    
    def save_data(self) -> None:
        """Guarda los datos en el archivo JSON"""
        try:
            with open(DATA_FILE, 'w', encoding='utf-8') as f:
                json.dump(self.data, f, ensure_ascii=False, indent=2)
        except Exception as e:
            logger.error(f"Error guardando datos: {e}")
    
    async def search_series_tmdb(self, query: str) -> List[Dict]:
        """Busca series en TMDB"""
        try:
            async with aiohttp.ClientSession() as session:
                url = f"{TMDB_BASE_URL}/search/tv"
                params = {
                    'api_key': TMDB_API_KEY,
                    'query': query,
                    'language': 'es-ES'
                }
                async with session.get(url, params=params) as response:
                    if response.status == 200:
                        data = await response.json()
                        return data.get('results', [])[:10]  # Limitar a 10 resultados
        except Exception as e:
            logger.error(f"Error buscando series: {e}")
        return []
    
    async def get_series_details(self, series_id: int) -> Optional[Dict]:
        """Obtiene detalles completos de una serie"""
        try:
            async with aiohttp.ClientSession() as session:
                url = f"{TMDB_BASE_URL}/tv/{series_id}"
                params = {
                    'api_key': TMDB_API_KEY,
                    'language': 'es-ES'
                }
                async with session.get(url, params=params) as response:
                    if response.status == 200:
                        return await response.json()
        except Exception as e:
            logger.error(f"Error obteniendo detalles de serie: {e}")
        return None
    
    def add_series(self, user_id: int, series_data: Dict) -> None:
        """Añade una serie a los datos del usuario"""
        user_key = str(user_id)
        if user_key not in self.data:
            self.data[user_key] = {"series": {}}
        
        series_key = str(series_data['tmdb_id'])
        self.data[user_key]["series"][series_key] = series_data
        self.save_data()
    
    def get_user_series(self, user_id: int) -> Dict:
        """Obtiene todas las series de un usuario"""
        user_key = str(user_id)
        user_data = self.data.get(user_key, {})
        # CORRECCIÓN: Validar que user_data sea un diccionario
        if not isinstance(user_data, dict):
            return {}
        return user_data.get("series", {})
    
    def delete_series(self, user_id: int, series_key: str) -> bool:
        """Elimina una serie de los datos del usuario"""
        user_key = str(user_id)
        if user_key in self.data and series_key in self.data[user_key]["series"]:
            del self.data[user_key]["series"][series_key]
            self.save_data()
            return True
        return False
    
    def update_series(self, user_id: int, series_key: str, field: str, value) -> bool:
        """Actualiza un campo específico de una serie"""
        user_key = str(user_id)
        if user_key in self.data and series_key in self.data[user_key]["series"]:
            self.data[user_key]["series"][series_key][field] = value
            # Recalcular si está al día
            series = self.data[user_key]["series"][series_key]
            series['up_to_date'] = series['seasons_watched'] >= series['total_seasons']
            self.save_data()
            return True
        return False
    
    def get_series_stats(self, user_id: int) -> Dict:
        """Calcula estadísticas de las series del usuario"""
        series = self.get_user_series(user_id)
        if not series:
            return {}
        
        total_series = len(series)
        total_seasons = sum(s.get('seasons_watched', 0) for s in series.values())
        completed_series = sum(1 for s in series.values() if s.get('up_to_date', False) and s.get('has_ended', False))
        ongoing_series = sum(1 for s in series.values() if not s.get('has_ended', False))
        behind_series = sum(1 for s in series.values() if not s.get('up_to_date', False))
        
        return {
            'total_series': total_series,
            'total_seasons': total_seasons,
            'completed_series': completed_series,
            'ongoing_series': ongoing_series,
            'behind_series': behind_series
        }

# Instancia global del bot
series_bot = SeriesBot()

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Comando /start"""
    keyboard = [
        [InlineKeyboardButton("➕ Añadir serie", callback_data="add_series")],
        [InlineKeyboardButton("📋 Ver mis series", callback_data="view_series")],
        [InlineKeyboardButton("🔍 Buscar serie", callback_data="search_series")],
        [InlineKeyboardButton("✏️ Editar serie", callback_data="edit_series")],
        [InlineKeyboardButton("🗑️ Eliminar serie", callback_data="delete_series")],
        [InlineKeyboardButton("📊 Estadísticas", callback_data="stats")],
        [InlineKeyboardButton("⏰ Recordatorios", callback_data="reminders")],
        [InlineKeyboardButton("💾 Exportar datos", callback_data="export_data")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    welcome_text = """
🎬 ¡Bienvenido al Bot de Seguimiento de Series!

Con este bot podrás:
• Llevar un registro de las series que has visto
• Saber qué temporadas te faltan por ver
• Recibir recordatorios de próximos estrenos
• Organizar tu lista de series

¿Qué te gustaría hacer?
"""
    
    if update.message:
        await update.message.reply_text(welcome_text, reply_markup=reply_markup)
    else:
        # Handle callback query (button press)
        try:
            await update.callback_query.edit_message_text(welcome_text, reply_markup=reply_markup)
        except Exception:
            # If editing fails (message was deleted for photo), send new message
            await update.callback_query.message.reply_text(welcome_text, reply_markup=reply_markup)

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Maneja los botones del teclado inline"""
    query = update.callback_query
    await query.answer()
    
    data = query.data
    
    if data == "main_menu":
        await start(update, context)
        return ConversationHandler.END
    
    elif data == "add_series":
        # CORRECCIÓN: Establecer el estado correctamente
        context.user_data['state'] = SEARCHING_SERIES
        
        keyboard = [[InlineKeyboardButton("🔙 Volver al menú", callback_data="main_menu")]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await query.edit_message_text(
            "🔍 Escribe el nombre de la serie que quieres añadir:",
            reply_markup=reply_markup
        )
        return SEARCHING_SERIES
    
    elif data == "view_series":
        await show_series_lists_menu(update, context)
        return ConversationHandler.END
    
    elif data == "search_series":
        # CORRECCIÓN: Establecer el estado correctamente
        context.user_data['state'] = SEARCHING_IN_LIST
        
        keyboard = [[InlineKeyboardButton("🔙 Volver al menú", callback_data="main_menu")]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await query.edit_message_text(
            "🔍 Escribe el nombre de la serie que quieres buscar en tu lista:",
            reply_markup=reply_markup
        )
        return SEARCHING_IN_LIST
    
    elif data == "edit_series":
        await show_edit_series_list(update, context)
        return ConversationHandler.END
    
    elif data == "delete_series":
        await show_delete_series_list(update, context)
        return ConversationHandler.END
    
    elif data == "stats":
        await show_statistics(update, context)
        return ConversationHandler.END
    
    elif data == "reminders":
        await show_reminders(update, context)
        return ConversationHandler.END
    
    elif data == "export_data":
        await export_user_data(update, context)
        return ConversationHandler.END
    
    elif data.startswith("list_"):
        list_type = data.split("_", 1)[1]
        await show_series_list(update, context, list_type)
        return ConversationHandler.END
    
    elif data.startswith("series_"):
        series_key = data.split("_", 1)[1]
        await show_series_details(update, context, series_key)
        return ConversationHandler.END
    
    elif data.startswith("select_"):
        series_id = data.split("_", 1)[1]
        await handle_series_selection(update, context, series_id)
        return SELECTING_SEASON
    
    elif data.startswith("season_"):
        season_num = int(data.split("_", 1)[1])
        context.user_data['selected_season'] = season_num
        
        keyboard = [
            [InlineKeyboardButton("✅ Sí, ya terminó", callback_data="ended_yes")],
            [InlineKeyboardButton("❌ No, aún se emite", callback_data="ended_no")],
            [InlineKeyboardButton("🔙 Atrás", callback_data="back_to_seasons")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        message_text = (
            f"¿La serie ya terminó de emitirse completamente?\n\n"
            f"(Has visto {season_num} temporada{'s' if season_num != 1 else ''})"
        )
        
        # Try to edit the message, if it fails, send a new one
        try:
            await query.edit_message_text(message_text, reply_markup=reply_markup)
        except Exception as e:
            # If editing fails (message was deleted for photo), send new message
            await query.message.reply_text(message_text, reply_markup=reply_markup)
        
        return SERIES_ENDED
    
    elif data in ["ended_yes", "ended_no"]:
        has_ended = data == "ended_yes"
        context.user_data['has_ended'] = has_ended
        
        if has_ended:
            await save_series_data(update, context)
            return ConversationHandler.END
        else:
            # CORRECCIÓN: Establecer el estado correctamente
            context.user_data['state'] = NEXT_SEASON_DATE
            
            keyboard = [[InlineKeyboardButton("🔙 Atrás", callback_data="back_to_ended")]]
            reply_markup = InlineKeyboardMarkup(keyboard)
            
            message_text = (
                "📅 ¿Cuándo se estrena la próxima temporada?\n\n"
                "Escribe la fecha en formato DD/MM/AAAA\n"
                "O escribe 'desconocida' si no se sabe aún:"
            )
            
            # Try to edit the message, if it fails, send a new one
            try:
                await query.edit_message_text(message_text, reply_markup=reply_markup)
            except Exception as e:
                await query.message.reply_text(message_text, reply_markup=reply_markup)
            
            return NEXT_SEASON_DATE
    
    elif data.startswith("edit_"):
        series_key = data.split("_", 1)[1]
        await show_edit_options(update, context, series_key)
        return ConversationHandler.END
    
    elif data.startswith("delete_confirm_"):
        series_key = data.split("_", 2)[2]
        user_id = update.effective_user.id
        
        if series_bot.delete_series(user_id, series_key):
            await query.edit_message_text(
                "✅ Serie eliminada correctamente.",
                reply_markup=InlineKeyboardMarkup([[
                    InlineKeyboardButton("🔙 Volver al menú", callback_data="main_menu")
                ]])
            )
        else:
            await query.edit_message_text(
                "❌ Error al eliminar la serie.",
                reply_markup=InlineKeyboardMarkup([[
                    InlineKeyboardButton("🔙 Volver al menú", callback_data="main_menu")
                ]])
            )
        return ConversationHandler.END
    
    return ConversationHandler.END

async def handle_text_input(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Maneja las entradas de texto del usuario"""
    text = update.message.text
    # CORRECCIÓN: Asegurar que 'state' tenga un valor por defecto válido
    state = context.user_data.get('state', SEARCHING_SERIES)
    
    if state == SEARCHING_SERIES:
        # Establecer el estado correctamente para el flujo
        context.user_data['state'] = SEARCHING_SERIES
        
        # Buscar series en TMDB
        series_results = await series_bot.search_series_tmdb(text)
        
        if not series_results:
            keyboard = [[InlineKeyboardButton("🔙 Volver al menú", callback_data="main_menu")]]
            reply_markup = InlineKeyboardMarkup(keyboard)
            
            await update.message.reply_text(
                "❌ No se encontraron series con ese nombre. Intenta con otro término de búsqueda.",
                reply_markup=reply_markup
            )
            return ConversationHandler.END
        
        # Mostrar resultados
        keyboard = []
        for series in series_results[:10]:  # Máximo 10 resultados
            title = series.get('name', 'Sin título')
            year = ""
            if series.get('first_air_date'):
                try:
                    year = f" ({series['first_air_date'][:4]})"
                except:
                    pass
            
            keyboard.append([InlineKeyboardButton(
                f"{title}{year}",
                callback_data=f"select_{series['id']}"
            )])
        
        keyboard.append([InlineKeyboardButton("🔙 Volver al menú", callback_data="main_menu")])
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await update.message.reply_text(
            "📺 Selecciona la serie correcta:",
            reply_markup=reply_markup
        )
        return SELECTING_SERIES
    
    elif state == NEXT_SEASON_DATE:
        date_text = text.lower().strip()
        
        if date_text in ['desconocida', 'no se sabe', 'unknown']:
            context.user_data['next_season_date'] = 'Desconocida'
        else:
            # Validar formato de fecha
            try:
                date_obj = datetime.strptime(text, "%d/%m/%Y")
                # Verificar que la fecha sea futura y razonable (máximo 5 años)
                now = datetime.now()
                max_date = now + timedelta(days=5*365)
                
                if date_obj < now:
                    await update.message.reply_text(
                        "⚠️ La fecha debe ser futura. Por favor, ingresa una fecha válida en formato DD/MM/AAAA:"
                    )
                    return NEXT_SEASON_DATE
                elif date_obj > max_date:
                    await update.message.reply_text(
                        "⚠️ La fecha parece demasiado lejana. Por favor, verifica la fecha:"
                    )
                    return NEXT_SEASON_DATE
                
                context.user_data['next_season_date'] = date_obj.strftime("%d/%m/%Y")
            except ValueError:
                await update.message.reply_text(
                    "⚠️ Formato de fecha incorrecto. Usa el formato DD/MM/AAAA o escribe 'desconocida':"
                )
                return NEXT_SEASON_DATE
        
        await save_series_data(update, context)
        return ConversationHandler.END
    
    elif state == SEARCHING_IN_LIST:
        await search_in_user_series(update, context, text)
        return ConversationHandler.END
    
    return ConversationHandler.END

async def handle_series_selection(update: Update, context: ContextTypes.DEFAULT_TYPE, series_id: str) -> None:
    """Maneja la selección de una serie específica"""
    series_details = await series_bot.get_series_details(int(series_id))
    
    if not series_details:
        await update.callback_query.edit_message_text(
            "❌ Error al obtener los detalles de la serie.",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("🔙 Volver al menú", callback_data="main_menu")
            ]])
        )
        return
    
    # Guardar datos de la serie seleccionada
    context.user_data['selected_series'] = series_details
    
    # Crear mensaje con información de la serie
    title = series_details.get('name', 'Sin título')
    overview = series_details.get('overview', 'Sin sinopsis disponible')
    first_air_date = series_details.get('first_air_date', 'Desconocida')
    total_seasons = series_details.get('number_of_seasons', 0)
    poster_path = series_details.get('poster_path')
    
    # Truncar sinopsis si es muy larga
    if len(overview) > 300:
        overview = overview[:300] + "..."
    
    info_text = f"📺 **{title}**\n\n"
    info_text += f"📅 **Fecha de estreno:** {first_air_date}\n"
    info_text += f"🎬 **Temporadas totales:** {total_seasons}\n\n"
    info_text += f"📖 **Sinopsis:**\n{overview}\n\n"
    info_text += "¿Cuál fue la última temporada que viste completa?"
    
    # Crear botones para selección de temporadas
    keyboard = []
    for i in range(1, min(total_seasons + 1, 21)):  # Máximo 20 temporadas por limitación de botones
        keyboard.append([InlineKeyboardButton(f"Temporada {i}", callback_data=f"season_{i}")])
    
    if total_seasons > 20:
        keyboard.append([InlineKeyboardButton("Más temporadas...", callback_data="more_seasons")])
    
    keyboard.append([InlineKeyboardButton("🔙 Volver a resultados", callback_data="add_series")])
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    # Enviar imagen si está disponible
    if poster_path:
        image_url = f"{TMDB_IMAGE_BASE_URL}{poster_path}"
        try:
            await update.callback_query.delete_message()
            await context.bot.send_photo(
                chat_id=update.effective_chat.id,
                photo=image_url,
                caption=info_text,
                reply_markup=reply_markup,
                parse_mode='Markdown'
            )
            return
        except Exception as e:
            logger.warning(f"No se pudo enviar la imagen: {e}")
    
    # Si no hay imagen o falla el envío, enviar solo texto
    await update.callback_query.edit_message_text(
        info_text,
        reply_markup=reply_markup,
        parse_mode='Markdown'
    )

async def save_series_data(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Guarda los datos de la serie en la base de datos"""
    series_details = context.user_data.get('selected_series')
    seasons_watched = context.user_data.get('selected_season')
    has_ended = context.user_data.get('has_ended')
    next_season_date = context.user_data.get('next_season_date', 'Desconocida')
    
    if not series_details or seasons_watched is None:
        # CORRECCIÓN: Manejo de error cuando faltan datos
        error_message = "❌ Error: Datos incompletos para guardar la serie."
        keyboard = [[InlineKeyboardButton("🔙 Volver al menú", callback_data="main_menu")]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        if update.callback_query:
            try:
                await update.callback_query.edit_message_text(error_message, reply_markup=reply_markup)
            except Exception:
                await update.callback_query.message.reply_text(error_message, reply_markup=reply_markup)
        else:
            await update.message.reply_text(error_message, reply_markup=reply_markup)
        return
    
    user_id = update.effective_user.id
    total_seasons = series_details.get('number_of_seasons', 0)
    
    series_data = {
        'tmdb_id': series_details['id'],
        'name': series_details.get('name', ''),
        'overview': series_details.get('overview', ''),
        'first_air_date': series_details.get('first_air_date', ''),
        'poster_path': series_details.get('poster_path', ''),
        'total_seasons': total_seasons,
        'seasons_watched': seasons_watched,
        'has_ended': has_ended,
        'up_to_date': seasons_watched >= total_seasons,
        'next_season_date': next_season_date if not has_ended else None,
        'added_date': datetime.now().strftime("%d/%m/%Y %H:%M")
    }
    
    # Verificar si ya existe la serie
    user_series = series_bot.get_user_series(user_id)
    series_key = str(series_details['id'])
    
    if series_key in user_series:
        keyboard = [[InlineKeyboardButton("🔙 Volver al menú", callback_data="main_menu")]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        message = "⚠️ Esta serie ya está en tu lista. Puedes editarla desde el menú de edición."
    else:
        series_bot.add_series(user_id, series_data)
        
        keyboard = [[InlineKeyboardButton("🔙 Volver al menú", callback_data="main_menu")]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        message = f"✅ Serie '{series_data['name']}' añadida correctamente a tu lista."
    
    # Limpiar datos temporales
    context.user_data.clear()
    
    if update.callback_query:
        try:
            await update.callback_query.edit_message_text(message, reply_markup=reply_markup)
        except Exception:
            # If editing fails, send new message
            await update.callback_query.message.reply_text(message, reply_markup=reply_markup)
    else:
        await update.message.reply_text(message, reply_markup=reply_markup)

async def show_series_lists_menu(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Muestra el menú de listas de series"""
    keyboard = [
        [InlineKeyboardButton("📋 Todas las series", callback_data="list_all")],
        [InlineKeyboardButton("✅ Series completadas", callback_data="list_completed")],
        [InlineKeyboardButton("📺 Series en emisión", callback_data="list_ongoing")],
        [InlineKeyboardButton("⏳ Series pendientes", callback_data="list_pending")],
        [InlineKeyboardButton("🏁 Series finalizadas", callback_data="list_ended")],
        [InlineKeyboardButton("🔙 Volver al menú", callback_data="main_menu")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    message = "📋 **Listas de Series**\n\nSelecciona qué tipo de lista quieres ver:"
    
    if update.callback_query:
        try:
            await update.callback_query.edit_message_text(message, reply_markup=reply_markup, parse_mode='Markdown')
        except Exception:
            # If editing fails (message was deleted for photo), send new message
            await update.callback_query.message.reply_text(message, reply_markup=reply_markup, parse_mode='Markdown')
    else:
        await update.message.reply_text(message, reply_markup=reply_markup, parse_mode='Markdown')

async def show_series_list(update: Update, context: ContextTypes.DEFAULT_TYPE, list_type: str) -> None:
    """Muestra una lista específica de series"""
    user_id = update.effective_user.id
    user_series = series_bot.get_user_series(user_id)
    
    if not user_series:
        keyboard = [[InlineKeyboardButton("🔙 Volver a listas", callback_data="view_series")]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        try:
            await update.callback_query.edit_message_text(
                "🔭 No tienes series en tu lista aún.",
                reply_markup=reply_markup
            )
        except Exception:
            await update.callback_query.message.reply_text(
                "🔭 No tienes series en tu lista aún.",
                reply_markup=reply_markup
            )
        return
    
    # Filtrar series según el tipo de lista
    filtered_series = []
    
    for series_key, series_data in user_series.items():
        if list_type == "all":
            filtered_series.append((series_key, series_data))
        elif list_type == "completed":
            if series_data.get('up_to_date', False) and series_data.get('has_ended', False):
                filtered_series.append((series_key, series_data))
        elif list_type == "ongoing":
            if not series_data.get('has_ended', True):
                filtered_series.append((series_key, series_data))
        elif list_type == "pending":
            if not series_data.get('up_to_date', True) and series_data.get('has_ended', False):
                filtered_series.append((series_key, series_data))
        elif list_type == "ended":
            if series_data.get('has_ended', False):
                filtered_series.append((series_key, series_data))
    
    if not filtered_series:
        keyboard = [[InlineKeyboardButton("🔙 Volver a listas", callback_data="view_series")]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        list_names = {
            "all": "todas",
            "completed": "completadas",
            "ongoing": "en emisión",
            "pending": "pendientes",
            "ended": "finalizadas"
        }
        
        message = f"🔭 No tienes series {list_names.get(list_type, '')} en tu lista."
        
        try:
            await update.callback_query.edit_message_text(message, reply_markup=reply_markup)
        except Exception:
            await update.callback_query.message.reply_text(message, reply_markup=reply_markup)
        return
    
    # Ordenar series
    if list_type == "ongoing":
        # Ordenar por fecha de próximo estreno
        def sort_key(item):
            next_date = item[1].get('next_season_date', 'Desconocida')
            if next_date == 'Desconocida':
                return datetime.max
            try:
                return datetime.strptime(next_date, "%d/%m/%Y")
            except:
                return datetime.max
        filtered_series.sort(key=sort_key)
    else:
        # Ordenar alfabéticamente
        filtered_series.sort(key=lambda x: x[1].get('name', '').lower())
    
    # Crear mensaje
    list_titles = {
        "all": "📋 Todas mis Series",
        "completed": "✅ Series Completadas",
        "ongoing": "📺 Series en Emisión",
        "pending": "⏳ Series Pendientes",
        "ended": "🏁 Series Finalizadas"
    }
    
    message = f"{list_titles.get(list_type, '📋 Lista')}\n\n"
    
    keyboard = []
    for series_key, series_data in filtered_series:
        name = series_data.get('name', 'Sin nombre')[:30]  # Limitar longitud
        seasons_info = f"{series_data.get('seasons_watched', 0)}/{series_data.get('total_seasons', 0)}"
        
        status_emoji = ""
        if series_data.get('up_to_date', False):
            status_emoji = "✅" if series_data.get('has_ended', False) else "⏸️"
        else:
            status_emoji = "⏳"
        
        button_text = f"{status_emoji} {name} ({seasons_info})"
        keyboard.append([InlineKeyboardButton(button_text, callback_data=f"series_{series_key}")])
    
    keyboard.append([InlineKeyboardButton("🔙 Volver a listas", callback_data="view_series")])
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    message += f"Total: {len(filtered_series)} serie{'s' if len(filtered_series) != 1 else ''}\n\n"
    message += "Toca una serie para ver más detalles:"
    
    try:
        await update.callback_query.edit_message_text(message, reply_markup=reply_markup)
    except Exception:
        await update.callback_query.message.reply_text(message, reply_markup=reply_markup)

async def show_series_details(update: Update, context: ContextTypes.DEFAULT_TYPE, series_key: str) -> None:
    """Muestra los detalles completos de una serie"""
    user_id = update.effective_user.id
    user_series = series_bot.get_user_series(user_id)
    
    if series_key not in user_series:
        keyboard = [[InlineKeyboardButton("🔙 Volver a listas", callback_data="view_series")]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await update.callback_query.edit_message_text(
            "❌ Serie no encontrada.",
            reply_markup=reply_markup
        )
        return
    
    series = user_series[series_key]
    
    # Crear mensaje detallado
    name = series.get('name', 'Sin nombre')
    overview = series.get('overview', 'Sin sinopsis disponible')
    first_air_date = series.get('first_air_date', 'Desconocida')
    total_seasons = series.get('total_seasons', 0)
    seasons_watched = series.get('seasons_watched', 0)
    has_ended = series.get('has_ended', False)
    up_to_date = series.get('up_to_date', False)
    next_season_date = series.get('next_season_date', 'Desconocida')
    added_date = series.get('added_date', 'Desconocida')
    
    # Truncar sinopsis si es muy larga
    if len(overview) > 400:
        overview = overview[:400] + "..."
    
    status = ""
    if up_to_date and has_ended:
        status = "✅ Completada"
    elif up_to_date and not has_ended:
        status = "⏸️ Al día (en emisión)"
    else:
        status = "⏳ Pendiente"
    
    message = f"📺 **{name}**\n\n"
    message += f"📅 **Estreno:** {first_air_date}\n"
    message += f"🎬 **Temporadas:** {seasons_watched}/{total_seasons}\n"
    message += f"📊 **Estado:** {status}\n"
    
    if not has_ended and next_season_date:
        message += f"⏰ **Próximo estreno:** {next_season_date}\n"
    
    message += f"📝 **Añadida:** {added_date}\n\n"
    message += f"📖 **Sinopsis:**\n{overview}"
    
    keyboard = [
        [InlineKeyboardButton("🔙 Volver a listas", callback_data="view_series")],
        [InlineKeyboardButton("🏠 Menú principal", callback_data="main_menu")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    # Enviar imagen si está disponible
    poster_path = series.get('poster_path')
    if poster_path:
        image_url = f"{TMDB_IMAGE_BASE_URL}{poster_path}"
        try:
            await update.callback_query.delete_message()
            await context.bot.send_photo(
                chat_id=update.effective_chat.id,
                photo=image_url,
                caption=message,
                reply_markup=reply_markup,
                parse_mode='Markdown'
            )
            return
        except Exception as e:
            logger.warning(f"No se pudo enviar la imagen: {e}")
    
    # Si no hay imagen o falla el envío, enviar solo texto
    await update.callback_query.edit_message_text(
        message,
        reply_markup=reply_markup,
        parse_mode='Markdown'
    )

async def show_edit_series_list(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Muestra la lista de series para editar"""
    user_id = update.effective_user.id
    user_series = series_bot.get_user_series(user_id)
    
    if not user_series:
        keyboard = [[InlineKeyboardButton("🔙 Volver al menú", callback_data="main_menu")]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await update.callback_query.edit_message_text(
            "🔭 No tienes series en tu lista para editar.",
            reply_markup=reply_markup
        )
        return
    
    # Ordenar alfabéticamente
    sorted_series = sorted(user_series.items(), key=lambda x: x[1].get('name', '').lower())
    
    keyboard = []
    for series_key, series_data in sorted_series:
        name = series_data.get('name', 'Sin nombre')[:35]  # Limitar longitud
        keyboard.append([InlineKeyboardButton(f"✏️ {name}", callback_data=f"edit_{series_key}")])
    
    keyboard.append([InlineKeyboardButton("🔙 Volver al menú", callback_data="main_menu")])
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    message = "✏️ **Editar Series**\n\nSelecciona la serie que quieres editar:"
    
    if update.callback_query:
        try:
            await update.callback_query.edit_message_text(message, reply_markup=reply_markup, parse_mode='Markdown')
        except Exception:
            await update.callback_query.message.reply_text(message, reply_markup=reply_markup, parse_mode='Markdown')
    else:
        await update.message.reply_text(message, reply_markup=reply_markup, parse_mode='Markdown')

async def show_edit_options(update: Update, context: ContextTypes.DEFAULT_TYPE, series_key: str) -> None:
    """Muestra las opciones de edición para una serie"""
    user_id = update.effective_user.id
    user_series = series_bot.get_user_series(user_id)
    
    if series_key not in user_series:
        keyboard = [[InlineKeyboardButton("🔙 Volver al menú", callback_data="main_menu")]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await update.callback_query.edit_message_text(
            "❌ Serie no encontrada.",
            reply_markup=reply_markup
        )
        return
    
    series = user_series[series_key]
    context.user_data['editing_series'] = series_key
    
    keyboard = [
        [InlineKeyboardButton("🎬 Temporadas vistas", callback_data=f"edit_field_seasons_{series_key}")],
        [InlineKeyboardButton("🏁 Serie terminada", callback_data=f"edit_field_ended_{series_key}")],
        [InlineKeyboardButton("📅 Fecha próximo estreno", callback_data=f"edit_field_date_{series_key}")],
        [InlineKeyboardButton("🔄 Actualizar desde TMDB", callback_data=f"edit_field_update_{series_key}")],
        [InlineKeyboardButton("🔙 Volver a edición", callback_data="edit_series")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    name = series.get('name', 'Sin nombre')
    current_info = f"📺 **{name}**\n\n"
    current_info += f"🎬 Temporadas vistas: {series.get('seasons_watched', 0)}/{series.get('total_seasons', 0)}\n"
    current_info += f"🏁 Serie terminada: {'Sí' if series.get('has_ended', False) else 'No'}\n"
    
    if not series.get('has_ended', True):
        next_date = series.get('next_season_date', 'Desconocida')
        current_info += f"📅 Próximo estreno: {next_date}\n"
    
    current_info += "\n¿Qué quieres editar?"
    
    if update.callback_query:
        try:
            await update.callback_query.edit_message_text(current_info, reply_markup=reply_markup, parse_mode='Markdown')
        except Exception:
            await update.callback_query.message.reply_text(current_info, reply_markup=reply_markup, parse_mode='Markdown')
    else:
        await update.message.reply_text(current_info, reply_markup=reply_markup, parse_mode='Markdown')

async def show_delete_series_list(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Muestra la lista de series para eliminar"""
    user_id = update.effective_user.id
    user_series = series_bot.get_user_series(user_id)
    
    if not user_series:
        keyboard = [[InlineKeyboardButton("🔙 Volver al menú", callback_data="main_menu")]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await update.callback_query.edit_message_text(
            "🔭 No tienes series en tu lista para eliminar.",
            reply_markup=reply_markup
        )
        return
    
    # Ordenar alfabéticamente
    sorted_series = sorted(user_series.items(), key=lambda x: x[1].get('name', '').lower())
    
    keyboard = []
    for series_key, series_data in sorted_series:
        name = series_data.get('name', 'Sin nombre')[:35]  # Limitar longitud
        keyboard.append([InlineKeyboardButton(f"🗑️ {name}", callback_data=f"delete_confirm_{series_key}")])
    
    keyboard.append([InlineKeyboardButton("🔙 Volver al menú", callback_data="main_menu")])
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    message = "🗑️ **Eliminar Series**\n\n⚠️ Selecciona la serie que quieres eliminar (esta acción no se puede deshacer):"
    
    if update.callback_query:
        try:
            await update.callback_query.edit_message_text(message, reply_markup=reply_markup, parse_mode='Markdown')
        except Exception:
            await update.callback_query.message.reply_text(message, reply_markup=reply_markup, parse_mode='Markdown')
    else:
        await update.message.reply_text(message, reply_markup=reply_markup, parse_mode='Markdown')

async def show_statistics(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Muestra estadísticas del usuario"""
    user_id = update.effective_user.id
    stats = series_bot.get_series_stats(user_id)
    
    if not stats:
        keyboard = [[InlineKeyboardButton("🔙 Volver al menú", callback_data="main_menu")]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        message = "🔭 No tienes estadísticas aún. ¡Añade algunas series primero!"
        
        try:
            await update.callback_query.edit_message_text(message, reply_markup=reply_markup)
        except Exception:
            await update.callback_query.message.reply_text(message, reply_markup=reply_markup)
        return
    
    message = "📊 **Tus Estadísticas**\n\n"
    message += f"📺 **Total de series:** {stats['total_series']}\n"
    message += f"🎬 **Temporadas vistas:** {stats['total_seasons']}\n"
    message += f"✅ **Series completadas:** {stats['completed_series']}\n"
    message += f"📡 **Series en emisión:** {stats['ongoing_series']}\n"
    message += f"⏳ **Series pendientes:** {stats['behind_series']}\n\n"
    
    if stats['total_series'] > 0:
        completion_rate = (stats['completed_series'] / stats['total_series']) * 100
        message += f"📈 **Tasa de finalización:** {completion_rate:.1f}%"
    
    keyboard = [[InlineKeyboardButton("🔙 Volver al menú", callback_data="main_menu")]]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    try:
        await update.callback_query.edit_message_text(message, reply_markup=reply_markup, parse_mode='Markdown')
    except Exception:
        await update.callback_query.message.reply_text(message, reply_markup=reply_markup, parse_mode='Markdown')

async def show_reminders(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Muestra recordatorios de próximos estrenos"""
    user_id = update.effective_user.id
    user_series = series_bot.get_user_series(user_id)
    
    if not user_series:
        keyboard = [[InlineKeyboardButton("🔙 Volver al menú", callback_data="main_menu")]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await update.callback_query.edit_message_text(
            "🔭 No tienes series para mostrar recordatorios.",
            reply_markup=reply_markup
        )
        return
    
    # Filtrar series con fechas de estreno próximas
    upcoming_series = []
    now = datetime.now()
    
    for series_key, series_data in user_series.items():
        if not series_data.get('has_ended', True):
            next_date_str = series_data.get('next_season_date')
            if next_date_str and next_date_str != 'Desconocida':
                try:
                    next_date = datetime.strptime(next_date_str, "%d/%m/%Y")
                    days_until = (next_date - now).days
                    
                    if days_until <= 60 and days_until >= 0:  # Próximos 60 días
                        upcoming_series.append((series_key, series_data, days_until, next_date))
                except:
                    pass
    
    if not upcoming_series:
        keyboard = [[InlineKeyboardButton("🔙 Volver al menú", callback_data="main_menu")]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        message = "⏰ **Recordatorios**\n\nNo tienes estrenos próximos en los siguientes 60 días."
        await update.callback_query.edit_message_text(message, reply_markup=reply_markup, parse_mode='Markdown')
        return
    
    # Ordenar por fecha más próxima
    upcoming_series.sort(key=lambda x: x[3])
    
    message = "⏰ **Próximos Estrenos**\n\n"
    
    for series_key, series_data, days_until, next_date in upcoming_series:
        name = series_data.get('name', 'Sin nombre')
        next_season = series_data.get('seasons_watched', 0) + 1
        
        if days_until == 0:
            time_text = "🔥 ¡HOY!"
        elif days_until == 1:
            time_text = "📅 Mañana"
        elif days_until <= 7:
            time_text = f"📅 En {days_until} días"
        else:
            time_text = f"📅 En {days_until} días ({next_date.strftime('%d/%m')})"
        
        message += f"📺 **{name}** - Temporada {next_season}\n{time_text}\n\n"
    
    keyboard = [[InlineKeyboardButton("🔙 Volver al menú", callback_data="main_menu")]]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    if update.callback_query:
        try:
            await update.callback_query.edit_message_text(message, reply_markup=reply_markup, parse_mode='Markdown')
        except Exception:
            await update.callback_query.message.reply_text(message, reply_markup=reply_markup, parse_mode='Markdown')
    else:
        await update.message.reply_text(message, reply_markup=reply_markup, parse_mode='Markdown')

async def export_user_data(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Exporta los datos del usuario en formato CSV"""
    user_id = update.effective_user.id
    user_series = series_bot.get_user_series(user_id)
    
    if not user_series:
        keyboard = [[InlineKeyboardButton("🔙 Volver al menú", callback_data="main_menu")]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await update.callback_query.edit_message_text(
            "🔭 No tienes datos para exportar.",
            reply_markup=reply_markup
        )
        return
    
    try:
        # Crear CSV en memoria
        output = io.StringIO()
        writer = csv.writer(output)
        
        # Escribir cabeceras
        headers = [
            'Nombre', 'Fecha_Estreno', 'Temporadas_Totales', 'Temporadas_Vistas',
            'Serie_Terminada', 'Al_Dia', 'Fecha_Proximo_Estreno', 'Fecha_Añadida'
        ]
        writer.writerow(headers)
        
        # Escribir datos
        for series_data in user_series.values():
            # CORRECCIÓN: Validar que series_data sea un diccionario
            if not isinstance(series_data, dict):
                continue
                
            row = [
                series_data.get('name', ''),
                series_data.get('first_air_date', ''),
                series_data.get('total_seasons', 0),
                series_data.get('seasons_watched', 0),
                'Sí' if series_data.get('has_ended', False) else 'No',
                'Sí' if series_data.get('up_to_date', False) else 'No',
                series_data.get('next_season_date', '') if not series_data.get('has_ended', True) else '',
                series_data.get('added_date', '')
            ]
            writer.writerow(row)
        
        # Obtener contenido del CSV
        csv_content = output.getvalue()
        output.close()
        
        # Crear archivo en bytes
        csv_bytes = csv_content.encode('utf-8-sig')  # BOM para Excel
        
        # Enviar archivo
        filename = f"mis_series_{datetime.now().strftime('%Y%m%d_%H%M')}.csv"
        
        await update.callback_query.delete_message()
        await context.bot.send_document(
            chat_id=update.effective_chat.id,
            document=InputFile(io.BytesIO(csv_bytes), filename=filename),
            caption="💾 **Datos exportados**\n\nAquí tienes tu lista de series en formato CSV.",
            parse_mode='Markdown'
        )
        
        keyboard = [[InlineKeyboardButton("🔙 Volver al menú", callback_data="main_menu")]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await context.bot.send_message(
            chat_id=update.effective_chat.id,
            text="✅ Exportación completada.",
            reply_markup=reply_markup
        )
        
    except Exception as e:
        logger.error(f"Error exportando datos: {e}")
        keyboard = [[InlineKeyboardButton("🔙 Volver al menú", callback_data="main_menu")]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        # CORRECCIÓN: Manejar el caso donde update.callback_query podría ser None
        try:
            if update.callback_query:
                await update.callback_query.edit_message_text(
                    "❌ Error al exportar los datos.",
                    reply_markup=reply_markup
                )
            else:
                await context.bot.send_message(
                    chat_id=update.effective_chat.id,
                    text="❌ Error al exportar los datos.",
                    reply_markup=reply_markup
                )
        except Exception:
            await context.bot.send_message(
                chat_id=update.effective_chat.id,
                text="❌ Error al exportar los datos.",
                reply_markup=reply_markup
            )

async def search_in_user_series(update: Update, context: ContextTypes.DEFAULT_TYPE, search_term: str) -> None:
    """Busca series en la lista del usuario"""
    user_id = update.effective_user.id
    user_series = series_bot.get_user_series(user_id)
    
    if not user_series:
        keyboard = [[InlineKeyboardButton("🔙 Volver al menú", callback_data="main_menu")]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await update.message.reply_text(
            "📭 No tienes series en tu lista para buscar.",
            reply_markup=reply_markup
        )
        return
    
    # Buscar series que coincidan
    search_term_lower = search_term.lower()
    matching_series = []
    
    for series_key, series_data in user_series.items():
        name = series_data.get('name', '').lower()
        if search_term_lower in name:
            matching_series.append((series_key, series_data))
    
    if not matching_series:
        keyboard = [[InlineKeyboardButton("🔙 Volver al menú", callback_data="main_menu")]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await update.message.reply_text(
            f"🔍 No se encontraron series que contengan '{search_term}' en tu lista.",
            reply_markup=reply_markup
        )
        return
    
    # Mostrar resultados
    keyboard = []
    for series_key, series_data in matching_series:
        name = series_data.get('name', 'Sin nombre')[:35]
        seasons_info = f"{series_data.get('seasons_watched', 0)}/{series_data.get('total_seasons', 0)}"
        
        status_emoji = ""
        if series_data.get('up_to_date', False):
            status_emoji = "✅" if series_data.get('has_ended', False) else "⏸️"
        else:
            status_emoji = "⏳"
        
        button_text = f"{status_emoji} {name} ({seasons_info})"
        keyboard.append([InlineKeyboardButton(button_text, callback_data=f"series_{series_key}")])
    
    keyboard.append([InlineKeyboardButton("🔙 Volver al menú", callback_data="main_menu")])
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    message = f"🔍 **Resultados de búsqueda**\n\nEncontradas {len(matching_series)} serie{'s' if len(matching_series) != 1 else ''} que contienen '{search_term}':\n\nToca una serie para ver más detalles:"
    
    await update.message.reply_text(message, reply_markup=reply_markup, parse_mode='Markdown')

async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Cancela la conversación actual"""
    await update.message.reply_text("❌ Operación cancelada.")
    return ConversationHandler.END

def main():
    """Función principal del bot"""
    # Crear aplicación
    application = Application.builder().token(TELEGRAM_TOKEN).build()
    
    # Manejador de conversación para añadir series
    conv_handler = ConversationHandler(
        entry_points=[
            CommandHandler("start", start),
            CallbackQueryHandler(button_handler)
        ],
        states={
            SEARCHING_SERIES: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text_input),
                CallbackQueryHandler(button_handler)
            ],
            SELECTING_SERIES: [
                CallbackQueryHandler(button_handler)
            ],
            SELECTING_SEASON: [
                CallbackQueryHandler(button_handler)
            ],
            SERIES_ENDED: [
                CallbackQueryHandler(button_handler)
            ],
            NEXT_SEASON_DATE: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text_input),
                CallbackQueryHandler(button_handler)
            ],
            SEARCHING_IN_LIST: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text_input),
                CallbackQueryHandler(button_handler)
            ]
        },
        fallbacks=[
            CommandHandler("cancel", cancel),
            CallbackQueryHandler(button_handler, pattern="^main_menu$")
        ],
        allow_reentry=True
    )
    
    # Añadir manejadores
    application.add_handler(conv_handler)
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CallbackQueryHandler(button_handler))
    
    # Iniciar bot
    logger.info("Bot iniciado...")
    application.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == '__main__':
    main()