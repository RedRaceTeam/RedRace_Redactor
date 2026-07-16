import hashlib
import os
from typing import Tuple

# Константы helpSha
HELP_SHA_SPLIT = 32
HELP_SHA_TRASH_LEN = 16

def generate_salt() -> str:
    """Генерирует случайную соль"""
    return os.urandom(32).hex()

def generate_trash() -> str:
    """Генерирует случайный мусор для helpSha"""
    return os.urandom(HELP_SHA_TRASH_LEN).hex()

def encrypt_password(password: str, salt: str) -> Tuple[str, str]:
    """
    Шифрует пароль с помощью helpSha.
    Возвращает: (хеш_с_мусором, мусор)
    """
    raw_hash = hashlib.sha256((password + salt).encode()).hexdigest()
    trash = generate_trash()
    mixed = raw_hash[:HELP_SHA_SPLIT] + trash + raw_hash[HELP_SHA_SPLIT:]
    return mixed, trash

def check_password(password: str, salt: str, mixed_hash: str, trash: str) -> bool:
    """Проверяет пароль"""
    clean_hash = mixed_hash[:HELP_SHA_SPLIT] + mixed_hash[HELP_SHA_SPLIT + len(trash):]
    expected = hashlib.sha256((password + salt).encode()).hexdigest()
    return clean_hash == expected
