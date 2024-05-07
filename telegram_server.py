import os
import json
import queue
import logging
import telebot
import requests
import configparser
from datetime import datetime

config = configparser.ConfigParser()
config.read('config.ini', encoding='utf-8')

log_path = config.get('LOCAL', 'LOGS_PATH')
debug = config.getboolean('LOCAL', 'DEBUG')
level_logging = logging.INFO if debug else logging.CRITICAL
name_bot = config.get('BOT', 'NAME_BOT')
log_name = ''


def track_dir(file_path):
    absolute_path = os.path.abspath(file_path)
    directory = os.path.dirname(absolute_path)
    if not os.path.exists(directory):
        os.makedirs(directory)


def update_loger(check_log_name):
    global logger
    global log_name
    global log_path
    new_log_name = f'{log_path}/{datetime.now().strftime("%Y%m%d")}.log'
    if new_log_name != check_log_name:
        log_name = str(new_log_name)
        track_dir(log_name)
        logging.basicConfig(level=level_logging, filename=log_name, format="%(asctime)s %(levelname)s %(message)s")
        logger = logging.getLogger(__name__)


update_loger(log_name)


def save_message(user_id, message_text, username, is_bot_message, history_path=''):
    file_name = f"{history_path}history_{user_id}.json"

    record = {
        "time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "user_id": user_id,
        "username": username,
        "is_bot": is_bot_message,
        "text": message_text
    }

    track_dir(file_path=file_name)

    try:
        with open(file_name, 'r', encoding='utf-8') as file:
            history = json.load(file)
    except FileNotFoundError:
        history = []
    history.append(record)

    with open(file_name, 'w', encoding='utf-8') as file:
        json.dump(history, file, ensure_ascii=False, indent=4)


def del_history_messages(user_id, history_path=''):
    file_name = f"{history_path}history_{user_id}.json"
    if os.path.isfile(file_name):
        os.remove(file_name)


def read_last_messages(user_id, num=10, history_path=''):

    def get_last_elements(lst, pat="cut"):
        for i in range(len(lst) - 1, -1, -1):
            if lst[i].get("text") == pat:
                return lst[i+1:]
        return lst

    file_name = f"{history_path}history_{user_id}.json"
    try:
        with open(file_name, 'r', encoding='utf-8') as file:
            history = json.load(file)
    except FileNotFoundError:
        return []
    return get_last_elements(history[-num:], pat="forget")


class TELEkash:

    def __init__(self,
                 token,
                 name_model='',
                 gpt_host="localhost:18888",
                 timeout=60,
                 history_path="temp/history_messages/"
                 ):

        self.bot = telebot.TeleBot(token)
        self.message_queue = queue.Queue()
        self.name_model = name_model
        self.gpt_host = gpt_host
        self.timeout = timeout
        self.history_path = history_path
        self.waiting_list = []

        @self.bot.message_handler(commands=['start'])
        def start(message):

            markup = update_keyboard(message)
            start_text = f"{name_bot} готов"
            self.bot.send_message(message.chat.id, start_text, reply_markup=markup, parse_mode='MARKDOWN')

        @self.bot.message_handler(func=lambda message: message.text == "Очистить контекст")
        def clear_context(message):

            markup = update_keyboard(message)
            try:
                save_message(user_id=message.from_user.id,
                             message_text='forget',
                             username=message.from_user.username,
                             is_bot_message=False,
                             history_path=history_path)

                self.bot.send_message(message.chat.id, f"Контекст очищен", reply_markup=markup, parse_mode='MARKDOWN')
                self.bot.delete_message(message.chat.id, message.message_id)

                logger.info(f'request clear: {message.from_user.id}: len({len(message.text)})')

            except Exception as e:
                logger.error(e)

        @self.bot.message_handler(content_types=['text'])
        def get_text_messages(message):

            update_loger(log_name)

            markup = update_keyboard(message)

            if message.chat.id in self.waiting_list:
                self.bot.send_message(message.chat.id, "У вас уже есть запрос. Попробуйте позже.", reply_markup=markup, parse_mode='MARKDOWN')
                return
            else:
                self.waiting_list.append(message.chat.id)

            message_bot = self.bot.send_message(message.chat.id, "Отвечаем...", reply_markup=markup, parse_mode='MARKDOWN')

            try:

                save_message(user_id=message.from_user.id,
                             message_text=message.text,
                             username=message.from_user.username,
                             is_bot_message=False,
                             history_path=history_path)

                history_messages = read_last_messages(user_id=message.from_user.id, history_path=history_path)

                list_messages = []
                for mes in history_messages:
                    if len(mes["text"]) > 0:
                        role = "assistant" if mes["is_bot"] else "user"
                        list_messages.append({"role": role, "condition": "GPT4 Correct", "content": mes["text"]})

                if len(list_messages) < 1:
                    clear_context(message)
                    raise Exception("Context empty")

                r = requests.post(f'http://{self.gpt_host}/v1/chat/completions', json={
                    "model": self.name_model,
                    "messages": list_messages
                }, timeout=timeout)

                if r.status_code == 200:

                    response_text = r.json()["choices"][0]["message"]["content"]

                    save_message(user_id=message.from_user.id,
                                 message_text=response_text,
                                 username=message.from_user.username,
                                 is_bot_message=True,
                                 history_path=history_path)

                    logger.info(f'good request gpt: {message.from_user.id}: len({len(message.text)})')

                else:
                    response_text = "Модель не ответила на запрос или ответила с ошибкой. Попробуйте позже."
                    logger.error(f'error request: {r}')

            except Exception as e:
                response_text = "Произошла внутренняя ошибка. Попробуйте позже."
                logger.critical(e)
            
            self.waiting_list.remove(message.chat.id)
            self.bot.delete_message(message.chat.id, message_bot.message_id)

            try:
                send_message_with_split(message_chat_id=message.chat.id, text=response_text, reply_markup=markup)
            except Exception as e:
                response_text = "Ошибка в ответе. Попробуйте еще раз."
                self.bot.send_message(message.chat.id, response_text, reply_markup=markup)
                logger.critical(e)

        def send_message_with_split(message_chat_id, text, reply_markup=None, max_len_response=3000, str_line='\n', only_split=False):

            if len(text) < max_len_response and not only_split:
                try:
                    self.bot.send_message(message_chat_id, text, reply_markup=reply_markup, parse_mode='MARKDOWN')
                except Exception as e:
                    logger.error(e)
                    send_message_with_split(message_chat_id=message_chat_id,
                                            text=text,
                                            reply_markup=reply_markup,
                                            max_len_response=max_len_response,
                                            str_line=str_line,
                                            only_split=True)
            else:
                parts = text.split(str_line)
                part_res_text = ''
                for part in parts:
                    part_res_text += part + str_line
                    if len(part_res_text) > max_len_response:
                        part_res_text = part_res_text[:-len(str(part + str_line))]
                        self.bot.send_message(message_chat_id, part_res_text, reply_markup=reply_markup, parse_mode=None)
                        part_res_text = part + str_line
                if part_res_text != '':
                    self.bot.send_message(message_chat_id, part_res_text, reply_markup=reply_markup, parse_mode=None)

        def update_keyboard(message):
            markup = telebot.types.ReplyKeyboardMarkup(resize_keyboard=True)
            markup.add(telebot.types.KeyboardButton(text="Очистить контекст"))
            return markup

    def poll(self):
        self.bot.polling(none_stop=True, interval=0)
