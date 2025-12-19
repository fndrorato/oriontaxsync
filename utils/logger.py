"""
Sistema de Logging Customizado
"""
import logging
from pathlib import Path
from datetime import datetime


class OrionTaxLogger:
    """Logger customizado para OrionTax Sync"""
    
    @staticmethod
    def setup(log_dir: str = None):
        """
        Configura o sistema de logging
        
        Args:
            log_dir: Diretório para salvar logs
        """
        if log_dir is None:
            log_dir = Path(__file__).parent.parent / 'logs'
        else:
            log_dir = Path(log_dir)
        
        log_dir.mkdir(exist_ok=True)
        
        # Nome do arquivo de log com data
        log_file = log_dir / f'oriontax_{datetime.now().strftime("%Y%m%d")}.log'
        
        # Configurar formato
        formatter = logging.Formatter(
            '%(asctime)s | %(levelname)-8s | %(name)-20s | %(message)s',
            datefmt='%Y-%m-%d %H:%M:%S'
        )
        
        # Handler para arquivo
        file_handler = logging.FileHandler(log_file, encoding='utf-8')
        file_handler.setLevel(logging.DEBUG)
        file_handler.setFormatter(formatter)
        
        # Handler para console
        console_handler = logging.StreamHandler()
        console_handler.setLevel(logging.INFO)
        console_handler.setFormatter(formatter)
        
        # Configurar logger raiz
        root_logger = logging.getLogger()
        root_logger.setLevel(logging.DEBUG)
        root_logger.addHandler(file_handler)
        root_logger.addHandler(console_handler)
        
        return root_logger
    
    @staticmethod
    def get_logger(name: str) -> logging.Logger:
        """
        Obtém logger com nome específico
        
        Args:
            name: Nome do logger
            
        Returns:
            Logger configurado
        """
        return logging.getLogger(name)