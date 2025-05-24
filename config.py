"""
Sistem Pakar Jagung Terpadu - Konfigurasi Aplikasi
"""

# Konfigurasi aplikasi
DEBUG = True
KNOWLEDGE_BASE_PATH = "knowledge_base.json"

# Konfigurasi logging
LOG_FORMAT = '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
LOG_LEVEL = 'INFO'
LOG_FILE = 'app.log'

# Konfigurasi cache
CACHE_TIMEOUT = 3600  # 1 jam dalam detik
