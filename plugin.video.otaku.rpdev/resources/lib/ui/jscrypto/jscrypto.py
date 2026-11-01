import hashlib
import base64
import os
from resources.lib.ui.pyaes import AESModeOfOperationCBC
from resources.lib.ui.pyaes.util import append_PKCS7_padding, strip_PKCS7_padding


def evpKDF(
        passwd,
        salt,
        key_size=8,
        iv_size=4,
        iterations=1,
        hash_algorithm="md5"):
    if isinstance(passwd, str):
        passwd = passwd.encode('utf-8')
    if isinstance(salt, str):
        salt = salt.encode('utf-8')
    target_key_size = key_size + iv_size
    derived_bytes = b""
    number_of_derived_words = 0
    block = None
    hasher = hashlib.new(hash_algorithm)
    while number_of_derived_words < target_key_size:
        if block is not None:
            hasher.update(block)

        hasher.update(passwd)
        hasher.update(salt)
        block = hasher.digest()
        hasher = hashlib.new(hash_algorithm)

        for i in range(1, iterations):
            hasher.update(block)
            block = hasher.digest()
            hasher = hashlib.new(hash_algorithm)

        derived_bytes += block[0: min(len(block), (target_key_size - number_of_derived_words) * 4)]

        number_of_derived_words += len(block) // 4

    return {
        "key": derived_bytes[0: key_size * 4],
        "iv": derived_bytes[key_size * 4:]
    }


def encode(plaintext, passphrase, saltsize=8):
    salt = os.urandom(saltsize)
    pass_bytes = passphrase.encode('utf-8') if isinstance(passphrase, str) else passphrase
    data = evpKDF(pass_bytes, salt)
    cipher = AESModeOfOperationCBC(data['key'], iv=data['iv'])
    raw = plaintext.encode('utf-8') if isinstance(plaintext, str) else plaintext
    padded = append_PKCS7_padding(raw)
    enctext = b"".join(cipher.encrypt(padded[i:i + 16]) for i in range(0, len(padded), 16))
    return base64.b64encode(b"Salted__" + salt + enctext)

# ''if salt is provided, it should be string
# ciphertext is base64 and passphrase is string


def decode(ciphertext, passphrase, salt=None):
    ciphertext = base64.b64decode(ciphertext)
    if not salt:
        salt = ciphertext[8:16]
        ciphertext = ciphertext[16:]
    elif isinstance(salt, str):
        salt = salt.encode('utf-8')
    pass_bytes = passphrase.encode('utf-8') if isinstance(passphrase, str) else passphrase
    data = evpKDF(pass_bytes, salt)
    cipher = AESModeOfOperationCBC(data['key'], iv=data['iv'])
    d = b"".join(cipher.decrypt(ciphertext[i:i + 16]) for i in range(0, len(ciphertext), 16))
    unpadded = strip_PKCS7_padding(d)
    return unpadded.decode('utf-8', errors='replace') if isinstance(unpadded, bytes) else unpadded
