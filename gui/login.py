"""
Tela de Login do Sistema OrionTax Sync
"""
from PyQt5.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QLabel, 
                             QLineEdit, QPushButton, QMessageBox, QFrame,
                             QSpacerItem, QSizePolicy)
from PyQt5.QtCore import Qt, pyqtSignal
from PyQt5.QtGui import QIcon, QFont, QPalette, QColor


class LoginDialog(QDialog):
    """Diálogo de Login"""
    
    login_successful = pyqtSignal(dict)  # Emite dados do usuário ao logar
    
    def __init__(self, db_manager, parent=None):  # ✅ Receber db_manager
        """
        Inicializa o diálogo de login
        
        Args:
            db_manager: Instância do DatabaseManager
            parent: Widget pai (opcional)
        """
        super().__init__(parent)
        self.db_manager = db_manager  # ✅ Armazenar db_manager
        self.user_data = None
        self.username = None  # ✅ Adicionar atributo username
        
        self.init_ui()
        self.apply_styles()
    
    def init_ui(self):
        """Inicializa a interface"""
        self.setWindowTitle('OrionTax Sync - Login')
        self.setFixedSize(550, 500)
        self.setWindowFlags(Qt.Dialog | Qt.MSWindowsFixedSizeDialogHint)
        
        # Layout principal
        layout = QVBoxLayout()
        layout.setSpacing(15)
        layout.setContentsMargins(50, 40, 50, 40)
        
        # Espaço superior
        layout.addSpacing(20)
        
        # Logo/Título
        title_label = QLabel('OrionTax Sync')
        title_label.setAlignment(Qt.AlignCenter)
        title_font = QFont('Arial', 28, QFont.Bold)
        title_label.setFont(title_font)
        title_label.setStyleSheet('color: #2c3e50; margin-bottom: 5px;')
        title_label.setWordWrap(False)
        layout.addWidget(title_label)
        
        # Subtítulo
        subtitle_label = QLabel('Sistema de Sincronização Fiscal')
        subtitle_label.setAlignment(Qt.AlignCenter)
        subtitle_label.setStyleSheet('color: #7f8c8d; font-size: 18px; margin-bottom: 20px;')
        subtitle_label.setWordWrap(False)
        layout.addWidget(subtitle_label)
        
        # Separador
        line = QFrame()
        line.setFrameShape(QFrame.HLine)
        line.setStyleSheet('background-color: #bdc3c7; margin: 10px 0px;')
        layout.addWidget(line)
        
        # Espaço
        layout.addSpacing(20)
        
        # Label Usuário
        username_label = QLabel('Usuário:')
        username_label.setStyleSheet('color: #34495e; font-weight: bold; font-size: 14px;')
        layout.addWidget(username_label)
        
        # Campo Usuário
        self.username_input = QLineEdit()
        self.username_input.setPlaceholderText('Digite seu usuário')
        self.username_input.setMinimumHeight(45)
        layout.addWidget(self.username_input)
        
        # Espaço entre campos
        layout.addSpacing(15)
        
        # Label Senha
        password_label = QLabel('Senha:')
        password_label.setStyleSheet('color: #34495e; font-weight: bold; font-size: 14px;')
        layout.addWidget(password_label)
        
        # Campo Senha
        self.password_input = QLineEdit()
        self.password_input.setPlaceholderText('Digite sua senha')
        self.password_input.setEchoMode(QLineEdit.Password)
        self.password_input.setMinimumHeight(45)
        layout.addWidget(self.password_input)
        
        # Conectar eventos
        self.username_input.returnPressed.connect(self.password_input.setFocus)
        self.password_input.returnPressed.connect(self.login)
        
        # Espaço antes do botão
        layout.addSpacing(20)
        
        # Botão Login
        self.login_button = QPushButton('Entrar')
        self.login_button.setMinimumHeight(50)
        self.login_button.setCursor(Qt.PointingHandCursor)
        self.login_button.clicked.connect(self.login)
        layout.addWidget(self.login_button)
        
        # Espaço
        layout.addSpacing(15)
        
        # Espaço inferior
        layout.addStretch()
        
        self.setLayout(layout)
        
        # Focar no campo usuário
        self.username_input.setFocus()

    def apply_styles(self):
        """Aplica estilos CSS"""
        self.setStyleSheet("""
            QDialog {
                background-color: #ecf0f1;
            }
            QLineEdit {
                padding: 12px 15px;
                border: 2px solid #bdc3c7;
                border-radius: 6px;
                background-color: white;
                color: #2c3e50;
                font-size: 14px;
            }
            QLineEdit:focus {
                border: 2px solid #3498db;
                background-color: #ffffff;
            }
            QLineEdit::placeholder {
                color: #95a5a6;
            }
            QPushButton {
                background-color: #3498db;
                color: white;
                border: none;
                border-radius: 6px;
                font-size: 16px;
                font-weight: bold;
                padding: 5px;
            }
            QPushButton:hover {
                background-color: #2980b9;
            }
            QPushButton:pressed {
                background-color: #21618c;
            }
        """)
    
    def login(self):
        """Realiza o login"""
        username = self.username_input.text().strip()
        password = self.password_input.text()
        
        if not username or not password:
            QMessageBox.warning(self, "Aviso", "Preencha todos os campos")
            return
        
        # ✅ Usar self.db_manager (recebido no construtor)
        user = self.db_manager.authenticate_user(username, password)
        
        if user:
            self.user_data = user
            self.username = user['username']  # ✅ Definir username
            self.login_successful.emit(user)
            self.accept()
        else:
            QMessageBox.critical(self, "Erro", "Usuário ou senha inválidos")
            self.password_input.clear()
            self.password_input.setFocus()