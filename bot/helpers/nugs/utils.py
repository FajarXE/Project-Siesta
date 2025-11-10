# [TARUH DI: bot/helpers/nugs/utils.py]

import os
import random
import string
import tempfile

def create_temp_filename(suffix: str = '.tmp') -> str:
    """Membuat nama file temporer yang aman."""
    # Didasarkan pada logika 'utils.utils' dan 'mqa_identifier'
    rand = ''.join(random.choices(string.ascii_letters + string.digits, k=10))
    return os.path.join(tempfile.gettempdir(), f"nugs_temp_{rand}{suffix}")
