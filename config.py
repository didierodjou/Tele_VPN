# --- START OF FILE config.py ---
import json
import os
from dataclasses import dataclass, field
from typing import List

CONFIG_FILE = 'config.json'
raw_data = {}

if os.path.exists(CONFIG_FILE):
    try:
        with open(CONFIG_FILE, 'r', encoding='utf-8') as f:
            raw_data = json.load(f)
    except Exception as e:
        print(f"⚠️ Ошибка чтения {CONFIG_FILE}: {e}")


@dataclass
class VPNConfig:
    # --- ВЫБОР ТРАНСПОРТА ---
    # 'telegram' или 'vk'

    transport_type: str = 'telegram'

    # --- TELEGRAM CONFIG ---
    api_id: int = int(raw_data.get('api_id', 0))
    api_hash: str = raw_data.get('api_hash', '')
    bot_token: str = raw_data.get('bot_token', '')
    chat_id: str = raw_data.get('chat_id', '')

    vk_login: str = raw_data.get('vk_login', '')
    vk_token: str = raw_data.get('vk_token', '')
    vk_peer_id: str = raw_data.get('vk_peer_id', '')
    vk_app_id: int = int(raw_data.get('vk_app_id', 0))

    # --- СЕТЕВЫЕ НАСТРОЙКИ ---
    tap_interface_name: str = 'Ethernet 5'
    server_ip: str = raw_data.get('server_ip', '')
    client_ip: str = raw_data.get('client_ip', '')
    netmask: str = raw_data.get('netmask', '')

    mtu: int = int(raw_data.get('mtu', 0))
    subnet: str = raw_data.get('subnet', '')
    encryption_key: str = raw_data.get('encryption_key', '')

    # Сжатие (True экономит трафик, False уменьшает пинг)
    compression_enabled: bool = False

    # Настройки пакетирования
    batch_interval: float = float(raw_data.get('batch_interval', 0.05))
    max_batch_size: int = int(raw_data.get('max_batch_size', 524288))

    # --- СПИСОК ИСКЛЮЧЕНИЙ (IP, которые идут мимо VPN) ---
    # Включает подсети Telegram и VKontakte/Mail.ru
    telegram_subnets: List[str] = field(default_factory=lambda: [
        # === TELEGRAM NETWORKS ===
        "91.108.4.0/22",
        "91.108.8.0/22",
        "91.108.12.0/22",
        "91.108.16.0/22",
        "91.108.56.0/22",
        "149.154.160.0/20",
        "149.154.164.0/22",
        "149.154.168.0/22",
        "149.154.172.0/22",

        # === VKONTAKTE (VK & Mail.ru Group) NETWORKS ===
        # Основная подсеть VK
        "87.240.128.0/18",
        # Инфраструктура и дата-центры
        "93.186.224.0/20",
        "95.142.192.0/20",
        # CDN, Медиа и прочие сервисы Mail.ru/VK
        "185.32.248.0/22",
        "188.93.56.0/24",
        "128.140.168.0/21",
        "195.218.169.0/24",
        "79.137.183.0/24"
    ])

    def get_ip_for_mode(self, mode: str) -> str:
        return self.server_ip if mode == "server" else self.client_ip

    @classmethod
    def load_from_file(cls, filename: str = 'config.json'):
        if os.path.exists(filename):
            try:
                with open(filename, 'r') as f:
                    data = json.load(f)
                # Фильтруем ключи, чтобы брать только те, что есть в классе
                valid_keys = {k: v for k, v in data.items() if k in cls.__annotations__}
                return cls(**valid_keys)
            except:
                pass
        return cls()

    def save_to_file(self, filename: str = 'config.json'):
        with open(filename, 'w') as f:
            json.dump(self.__dict__, f, indent=4)


# Загружаем конфиг сразу при импорте
config = VPNConfig.load_from_file()
