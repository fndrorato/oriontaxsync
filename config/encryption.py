"""
Sistema de Criptografia para Senhas
"""
import os
import base64
import bcrypt
from cryptography.fernet import Fernet
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC  # ✅ CORRETO
from cryptography.hazmat.backends import default_backend

class EncryptionManager:
    """
    Gerencia criptografia de senhas de banco de dados
    Usa Fernet (AES-128) com chave derivada de senha mestre
    """
    
    def __init__(self, master_password: str = None):
        """
        Inicializa o gerenciador de criptografia
        
        Args:
            master_password: Senha mestre para derivar chave (padrão: hostname)
        """
        if master_password is None:
            # Usar identificador único da máquina como senha mestre padrão
            import socket
            master_password = socket.gethostname()
        
        self.master_password = master_password.encode()
        self._cipher = None
    
    def _get_cipher(self) -> Fernet:
        """Obtém cipher Fernet (lazy loading)"""
        if self._cipher is None:
            # Salt fixo baseado no hostname (em produção, armazene separadamente)
            salt = b'oriontax_salt_v1'
            
            # Derivar chave de 32 bytes usando PBKDF2
            kdf = PBKDF2HMAC(  # ✅ CORRETO
                algorithm=hashes.SHA256(),
                length=32,
                salt=salt,
                iterations=100000,
                backend=default_backend()
            )
            
            key = base64.urlsafe_b64encode(kdf.derive(self.master_password))
            self._cipher = Fernet(key)
        
        return self._cipher
    
    def encrypt(self, plaintext: str) -> str:
        """
        Criptografa texto
        
        Args:
            plaintext: Texto em claro
            
        Returns:
            Texto criptografado (base64)
        """
        if not plaintext:
            return ''
        
        cipher = self._get_cipher()
        encrypted = cipher.encrypt(plaintext.encode())
        return encrypted.decode()
    
    def decrypt(self, ciphertext: str) -> str:
        """
        Descriptografa texto
        
        Args:
            ciphertext: Texto criptografado
            
        Returns:
            Texto em claro
        """
        if not ciphertext:
            return ''
        
        cipher = self._get_cipher()
        decrypted = cipher.decrypt(ciphertext.encode())
        return decrypted.decode()


class PasswordHasher:
    """
    Gerencia hash de senhas de login (bcrypt)
    """
    
    @staticmethod
    def hash_password(password: str) -> str:
        """
        Cria hash bcrypt da senha
        
        Args:
            password: Senha em texto claro
            
        Returns:
            Hash bcrypt (string)
        """
        salt = bcrypt.gensalt(rounds=12)
        hashed = bcrypt.hashpw(password.encode(), salt)
        return hashed.decode()
    
    @staticmethod
    def verify_password(password: str, hashed: str) -> bool:
        """
        Verifica se senha corresponde ao hash
        
        Args:
            password: Senha em texto claro
            hashed: Hash armazenado
            
        Returns:
            True se senha correta
        """
        return bcrypt.checkpw(password.encode(), hashed.encode())


# Instância global
encryption_manager = EncryptionManager()
password_hasher = PasswordHasher()