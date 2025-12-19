"""
Diálogo de Alteração de Senha
"""
from PyQt5.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit,
    QPushButton, QMessageBox, QGroupBox
)
from PyQt5.QtCore import Qt
from PyQt5.QtGui import QFont


class ChangePasswordDialog(QDialog):
    """Diálogo para alterar senha do usuário"""
    
    def __init__(self, db_manager, username, parent=None):
        """
        Inicializa o diálogo
        
        Args:
            db_manager: Instância do DatabaseManager
            username: Nome do usuário logado
            parent: Widget pai
        """
        super().__init__(parent)
        self.db_manager = db_manager
        self.username = username
        
        self.setWindowTitle("Alterar Senha")
        self.setModal(True)
        self.setFixedSize(450, 450)
        
        self.init_ui()
        # self.apply_styles()
    
    def init_ui(self):
        """Inicializa interface"""
        layout = QVBoxLayout()
        layout.setSpacing(20)
        layout.setContentsMargins(30, 30, 30, 30)
        
        # Título
        title = QLabel(f"Alterar Senha - {self.username}")
        title.setAlignment(Qt.AlignCenter)
        title_font = QFont('Arial', 16, QFont.Bold)
        title.setFont(title_font)
        title.setStyleSheet('margin-bottom: 10px;')
        layout.addWidget(title)
        
        # Grupo de campos
        fields_group = QGroupBox()
        fields_layout = QVBoxLayout()
        fields_layout.setSpacing(15)
        
        # Senha atual
        current_label = QLabel('Senha Atual:')
        current_label.setStyleSheet('font-weight: bold;')
        fields_layout.addWidget(current_label)
        
        self.current_password = QLineEdit()
        self.current_password.setEchoMode(QLineEdit.Password)
        self.current_password.setPlaceholderText('Digite sua senha atual')
        self.current_password.setMinimumHeight(40)
        fields_layout.addWidget(self.current_password)
        
        # Nova senha
        new_label = QLabel('Nova Senha:')
        new_label.setStyleSheet('ont-weight: bold;')
        fields_layout.addWidget(new_label)
        
        self.new_password = QLineEdit()
        self.new_password.setEchoMode(QLineEdit.Password)
        self.new_password.setPlaceholderText('Digite a nova senha')
        self.new_password.setMinimumHeight(40)
        fields_layout.addWidget(self.new_password)
        
        # Confirmar nova senha
        confirm_label = QLabel('Confirmar Nova Senha:')
        confirm_label.setStyleSheet('font-weight: bold;')
        fields_layout.addWidget(confirm_label)
        
        self.confirm_password = QLineEdit()
        self.confirm_password.setEchoMode(QLineEdit.Password)
        self.confirm_password.setPlaceholderText('Digite a nova senha novamente')
        self.confirm_password.setMinimumHeight(40)
        fields_layout.addWidget(self.confirm_password)
        
        fields_group.setLayout(fields_layout)
        layout.addWidget(fields_group)
        
        # Botões
        buttons_layout = QHBoxLayout()
        
        save_button = QPushButton('Salvar')
        save_button.setMinimumHeight(45)
        save_button.clicked.connect(self.change_password)
        buttons_layout.addWidget(save_button)
        
        cancel_button = QPushButton('Cancelar')
        cancel_button.setMinimumHeight(45)
        cancel_button.clicked.connect(self.reject)
        buttons_layout.addWidget(cancel_button)
        
        layout.addLayout(buttons_layout)
        
        self.setLayout(layout)
        
        # Conectar Enter
        self.current_password.returnPressed.connect(self.new_password.setFocus)
        self.new_password.returnPressed.connect(self.confirm_password.setFocus)
        self.confirm_password.returnPressed.connect(self.change_password)
    
    def apply_styles(self):
        """Aplica estilos"""
        self.setStyleSheet("""
            QDialog {
                background-color: #ecf0f1;
            }
            QGroupBox {
                border: none;
                background-color: white;
                border-radius: 5px;
                padding: 20px;
            }
            QLineEdit {
                padding: 10px;
                border: 2px solid #bdc3c7;
                border-radius: 5px;
                background-color: white;
                color: #2c3e50;
                font-size: 13px;
            }
            QLineEdit:focus {
                border: 2px solid #3498db;
            }
            QPushButton {
                background-color: #3498db;
                color: white;
                border: none;
                border-radius: 5px;
                font-size: 14px;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: #2980b9;
            }
            QPushButton:pressed {
                background-color: #21618c;
            }
        """)
    
    def change_password(self):
        """Altera a senha"""
        current = self.current_password.text()
        new = self.new_password.text()
        confirm = self.confirm_password.text()
        
        # Validações
        if not current or not new or not confirm:
            QMessageBox.warning(self, "Aviso", "Preencha todos os campos")
            return
        
        if len(new) < 6:
            QMessageBox.warning(self, "Aviso", "A nova senha deve ter pelo menos 6 caracteres")
            return
        
        if new != confirm:
            QMessageBox.warning(self, "Aviso", "As senhas não coincidem")
            return
        
        # Alterar senha
        success, message = self.db_manager.change_password(self.username, current, new)
        
        if success:
            QMessageBox.information(self, "Sucesso", message)
            self.accept()
        else:
            QMessageBox.critical(self, "Erro", message)