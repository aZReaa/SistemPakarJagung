import os

"""
Sistem Pakar Jagung Terpadu - Konfigurasi Aplikasi
"""

# Konfigurasi aplikasi
DEBUG = os.environ.get('FLASK_ENV') != 'production'  # Auto-detect production
APP_ROOT = os.path.dirname(os.path.abspath(__file__))  # Define APP_ROOT
KNOWLEDGE_BASE_PATH = os.path.join(APP_ROOT, "knowledge_base.json")  # Make path absolute

# Konfigurasi logging
LOG_FORMAT = '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
LOG_LEVEL = 'INFO'
LOG_FILE = os.path.join(APP_ROOT, 'app.log')  # Make path absolute

# Konfigurasi cache
CACHE_TIMEOUT = 3600  # 1 jam dalam detik
