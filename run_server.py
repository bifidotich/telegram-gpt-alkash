import configparser
from telegram_server import TELEkash

config = configparser.ConfigParser()
config.read('config.ini')

token = config.get('BOT', 'TOKEN')
name_model = config.get('MODEL', 'NAME_MODEL')
host = config.get('MODEL', 'HOST')
timeout = int(config.get('MODEL', 'TIMEOUT'))
history_path = config.get('LOCAL', 'HISTORY_PATH')

bot = TELEkash(token=token,
               name_model=name_model,
               gpt_host=host,
               timeout=timeout,
               history_path=history_path)
bot.poll()
