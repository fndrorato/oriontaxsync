"""
Gerenciador de Banco de Dados SQLite
"""
import sqlite3
import os
import logging
from datetime import datetime
from pathlib import Path
from typing import Optional, Dict, List
from .encryption import encryption_manager, password_hasher


class DatabaseManager:
    """Gerencia o banco SQLite local"""
    
    def __init__(self, db_path: str = None):
        """
        Inicializa o gerenciador
        
        Args:
            db_path: Caminho do banco SQLite
        """
        if db_path is None:
            # Criar pasta data se não existir
            data_dir = Path(__file__).parent.parent / 'data'
            data_dir.mkdir(exist_ok=True)
            db_path = data_dir / 'oriontax.db'

        self.logger = logging.getLogger(__name__) 
        self.db_path = db_path
        self.conn = None
        self._init_database()
    
    def connect(self):
        """Conecta ao banco"""
        if self.conn is None:
            self.conn = sqlite3.connect(self.db_path)
            self.conn.row_factory = sqlite3.Row
    
    def disconnect(self):
        """Desconecta do banco"""
        if self.conn:
            self.conn.close()
            self.conn = None
    
    def _init_database(self):
        """Cria estrutura do banco se não existir"""
        self.connect()
        cursor = self.conn.cursor()
        
        # Tabela de usuários do sistema
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS usuarios (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT UNIQUE NOT NULL,
                password_hash TEXT NOT NULL,
                nome_completo TEXT,
                email TEXT,
                is_active INTEGER DEFAULT 1,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                last_login TIMESTAMP
            )
        """)
        
        # Tabela de clientes
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS clientes (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                nome TEXT NOT NULL,
                cnpj TEXT UNIQUE NOT NULL,
                is_active INTEGER DEFAULT 1,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)        
        
        # Tabela de configuração Oracle
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS config_oracle (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                nome_conexao TEXT UNIQUE NOT NULL,
                host TEXT NOT NULL,
                port INTEGER DEFAULT 1521,
                service_name TEXT NOT NULL,
                username TEXT NOT NULL,
                password_encrypted TEXT NOT NULL,
                instant_client_path TEXT,
                is_active INTEGER DEFAULT 1,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        
        # Tabela de configuração OrionTax (PostgreSQL)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS config_oriontax (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                host TEXT NOT NULL,
                port INTEGER DEFAULT 5432,
                database_name TEXT NOT NULL,
                username TEXT NOT NULL,
                password_encrypted TEXT NOT NULL,
                use_ssl INTEGER DEFAULT 1,
                is_active INTEGER DEFAULT 1,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        
        # Tabela de agendamentos
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS agendamentos (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                tipo_operacao TEXT NOT NULL CHECK(tipo_operacao IN ('ENVIAR', 'BUSCAR')),
                frequencia TEXT NOT NULL CHECK(frequencia IN ('DIARIA', 'SEMANAL', 'MENSAL')),
                dias_semana TEXT,  -- JSON: [0,1,2,3,4,5,6] (0=segunda)
                hora TEXT NOT NULL,  -- Formato: "HH:MM"
                is_active INTEGER DEFAULT 1,
                ultima_execucao TIMESTAMP,
                proxima_execucao TIMESTAMP,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        
        
        
        # Tabela de logs de execução
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS logs_execucao (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                tipo_operacao TEXT NOT NULL,
                status TEXT NOT NULL CHECK(status IN ('SUCESSO', 'ERRO', 'EM_ANDAMENTO')),
                mensagem TEXT,
                registros_processados INTEGER DEFAULT 0,
                tempo_execucao_segundos REAL,
                error_details TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        
        self.conn.commit()
        
        # Criar usuário padrão se não existir
        self._create_default_user()
    
    def _create_default_user(self):
        """Cria usuário admin padrão"""
        cursor = self.conn.cursor()
        cursor.execute("SELECT COUNT(*) FROM usuarios")
        count = cursor.fetchone()[0]
        
        if count == 0:
            # Usuário: admin / Senha: admin123
            password_hash = password_hasher.hash_password('admin123')
            cursor.execute("""
                INSERT INTO usuarios (username, password_hash, nome_completo, is_active)
                VALUES (?, ?, ?, 1)
            """, ('admin', password_hash, 'Administrador'))
            self.conn.commit()
            print("✓ Usuário padrão criado: admin / admin123")
    
    # ================================================================
    # MÉTODOS DE USUÁRIOS
    # ================================================================
    
    def authenticate_user(self, username: str, password: str) -> Optional[Dict]:
        """
        Autentica usuário
        
        Returns:
            Dict com dados do usuário se autenticado, None caso contrário
        """
        cursor = self.conn.cursor()
        cursor.execute("""
            SELECT id, username, password_hash, nome_completo, email, is_active
            FROM usuarios
            WHERE username = ? AND is_active = 1
        """, (username,))
        
        user = cursor.fetchone()
        
        if user and password_hasher.verify_password(password, user['password_hash']):
            # Atualizar last_login
            cursor.execute("""
                UPDATE usuarios SET last_login = ? WHERE id = ?
            """, (datetime.now(), user['id']))
            self.conn.commit()
            
            return dict(user)
        
        return None
    
    def create_user(self, username: str, password: str, nome_completo: str = None, 
                   email: str = None) -> bool:
        """Cria novo usuário"""
        try:
            password_hash = password_hasher.hash_password(password)
            cursor = self.conn.cursor()
            cursor.execute("""
                INSERT INTO usuarios (username, password_hash, nome_completo, email)
                VALUES (?, ?, ?, ?)
            """, (username, password_hash, nome_completo, email))
            self.conn.commit()
            return True
        except sqlite3.IntegrityError:
            return False

    # ================================================================
    # MÉTODOS DE CLIENTES
    # ================================================================
    
    def create_cliente(self, nome: str, cnpj: str) -> bool:
        """
        Cria novo cliente
        
        Args:
            nome: Nome do cliente
            cnpj: CNPJ (apenas números)
        
        Returns:
            True se criado com sucesso
        """
        try:
            # Limpar CNPJ (remover qualquer caractere que não seja número)
            cnpj_limpo = ''.join(filter(str.isdigit, cnpj))
            
            if len(cnpj_limpo) != 14:
                return False
            
            cursor = self.conn.cursor()
            cursor.execute("""
                INSERT INTO clientes (nome, cnpj)
                VALUES (?, ?)
            """, (nome, cnpj_limpo))
            self.conn.commit()
            return True
        except sqlite3.IntegrityError:
            return False
        except Exception as e:
            print(f"Erro ao criar cliente: {e}")
            return False
    
    def update_cliente(self, cliente_id: int, nome: str, cnpj: str) -> bool:
        """
        Atualiza cliente
        
        Args:
            cliente_id: ID do cliente
            nome: Nome do cliente
            cnpj: CNPJ (apenas números)
        
        Returns:
            True se atualizado com sucesso
        """
        try:
            # Limpar CNPJ
            cnpj_limpo = ''.join(filter(str.isdigit, cnpj))
            
            if len(cnpj_limpo) != 14:
                return False
            
            cursor = self.conn.cursor()
            cursor.execute("""
                UPDATE clientes 
                SET nome = ?, cnpj = ?, updated_at = ?
                WHERE id = ?
            """, (nome, cnpj_limpo, datetime.now(), cliente_id))
            self.conn.commit()
            return True
        except Exception as e:
            print(f"Erro ao atualizar cliente: {e}")
            return False
    
    def delete_cliente(self, cliente_id: int) -> bool:
        """
        Desativa cliente (soft delete)
        
        Args:
            cliente_id: ID do cliente
        
        Returns:
            True se desativado com sucesso
        """
        try:
            cursor = self.conn.cursor()
            cursor.execute("""
                UPDATE clientes SET is_active = 0 WHERE id = ?
            """, (cliente_id,))
            self.conn.commit()
            return True
        except Exception as e:
            print(f"Erro ao deletar cliente: {e}")
            return False
    
    def get_cliente(self, cliente_id: int) -> Optional[Dict]:
        """Obtém cliente por ID"""
        cursor = self.conn.cursor()
        cursor.execute("""
            SELECT * FROM clientes WHERE id = ? AND is_active = 1
        """, (cliente_id,))
        
        cliente = cursor.fetchone()
        return dict(cliente) if cliente else None
    
    def get_all_clientes(self) -> List[Dict]:
        """Obtém todos os clientes ativos"""
        cursor = self.conn.cursor()
        cursor.execute("""
            SELECT * FROM clientes WHERE is_active = 1 ORDER BY nome
        """)
        
        return [dict(row) for row in cursor.fetchall()]
    
    def format_cnpj(self, cnpj: str) -> str:
        """
        Formata CNPJ para exibição: 12.345.678/0001-90
        
        Args:
            cnpj: CNPJ sem formatação (14 dígitos)
        
        Returns:
            CNPJ formatado
        """
        cnpj_limpo = ''.join(filter(str.isdigit, cnpj))
        
        if len(cnpj_limpo) != 14:
            return cnpj
        
        return f"{cnpj_limpo[:2]}.{cnpj_limpo[2:5]}.{cnpj_limpo[5:8]}/{cnpj_limpo[8:12]}-{cnpj_limpo[12:]}"
    
    # ================================================================
    # MÉTODOS DE CONFIGURAÇÃO ORACLE
    # ================================================================
    
    def save_oracle_config(self, nome_conexao: str, host: str, port: int,
                          service_name: str, username: str, password: str,
                          instant_client_path: str = None) -> bool:
        """Salva configuração Oracle"""
        try:
            password_enc = encryption_manager.encrypt(password)
            cursor = self.conn.cursor()
            
            # Verificar se já existe
            cursor.execute("SELECT id FROM config_oracle WHERE nome_conexao = ?", 
                         (nome_conexao,))
            existing = cursor.fetchone()
            
            if existing:
                # Atualizar
                cursor.execute("""
                    UPDATE config_oracle 
                    SET host = ?, port = ?, service_name = ?, username = ?,
                        password_encrypted = ?, instant_client_path = ?, updated_at = ?
                    WHERE nome_conexao = ?
                """, (host, port, service_name, username, password_enc,
                     instant_client_path, datetime.now(), nome_conexao))
            else:
                # Inserir
                cursor.execute("""
                    INSERT INTO config_oracle 
                    (nome_conexao, host, port, service_name, username, password_encrypted, instant_client_path)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                """, (nome_conexao, host, port, service_name, username, password_enc, instant_client_path))
            
            self.conn.commit()
            return True
        except Exception as e:
            print(f"Erro ao salvar config Oracle: {e}")
            return False
    
    def get_oracle_config(self, nome_conexao: str = None) -> Optional[Dict]:
        """Obtém configuração Oracle (descriptografada)"""
        cursor = self.conn.cursor()
        
        if nome_conexao:
            cursor.execute("""
                SELECT * FROM config_oracle 
                WHERE nome_conexao = ? AND is_active = 1
            """, (nome_conexao,))
        else:
            cursor.execute("""
                SELECT * FROM config_oracle 
                WHERE is_active = 1 
                ORDER BY created_at DESC LIMIT 1
            """)
        
        config = cursor.fetchone()
        
        if config:
            config_dict = dict(config)
            # Descriptografar senha
            config_dict['password'] = encryption_manager.decrypt(
                config_dict['password_encrypted']
            )
            del config_dict['password_encrypted']
            return config_dict
        
        return None
    
    # ================================================================
    # MÉTODOS DE CONFIGURAÇÃO ORIONTAX
    # ================================================================
    
    def save_oriontax_config(self, host: str, port: int, database_name: str,
                            username: str, password: str, use_ssl: bool = True) -> bool:
        """Salva configuração OrionTax"""
        try:
            password_enc = encryption_manager.encrypt(password)
            cursor = self.conn.cursor()
            
            # Limpar configs antigas
            cursor.execute("UPDATE config_oriontax SET is_active = 0")
            
            # Inserir nova
            cursor.execute("""
                INSERT INTO config_oriontax 
                (host, port, database_name, username, password_encrypted, use_ssl)
                VALUES (?, ?, ?, ?, ?, ?)
            """, (host, port, database_name, username, password_enc, int(use_ssl)))
            
            self.conn.commit()
            return True
        except Exception as e:
            print(f"Erro ao salvar config OrionTax: {e}")
            return False
    
    def get_oriontax_config(self) -> Optional[Dict]:
        """Obtém configuração OrionTax ativa"""
        cursor = self.conn.cursor()
        cursor.execute("""
            SELECT * FROM config_oriontax 
            WHERE is_active = 1 
            ORDER BY created_at DESC LIMIT 1
        """)
        
        config = cursor.fetchone()
        
        if config:
            config_dict = dict(config)
            config_dict['password'] = encryption_manager.decrypt(
                config_dict['password_encrypted']
            )
            del config_dict['password_encrypted']
            return config_dict
        
        return None
    
    # ================================================================
    # MÉTODOS DE AGENDAMENTO
    # ================================================================
    
    def create_schedule(self, operation_type: str, schedule_type: str, 
                       schedule_time: str, schedule_day: int = None, 
                       is_active: bool = True) -> int:
        """
        Cria um novo agendamento
        
        Args:
            operation_type: 'ENVIAR' ou 'BUSCAR'
            schedule_type: 'daily', 'weekly', 'monthly'
            schedule_time: Horário (HH:MM)
            schedule_day: Dia (para weekly/monthly)
            is_active: Se está ativo
        
        Returns:
            ID do agendamento criado
        """
        try:
            import json
            
            # Mapear schedule_type para frequencia
            frequencia_map = {
                'daily': 'DIARIA',
                'weekly': 'SEMANAL',
                'monthly': 'MENSAL'
            }
            frequencia = frequencia_map.get(schedule_type, 'DIARIA')
            
            # Para weekly/monthly, armazenar o dia em dias_semana como JSON
            dias_semana = None
            if schedule_day is not None:
                dias_semana = json.dumps([schedule_day])
            
            cursor = self.conn.cursor()
            
            cursor.execute("""
                INSERT INTO agendamentos 
                (tipo_operacao, frequencia, dias_semana, hora, is_active)
                VALUES (?, ?, ?, ?, ?)
            """, (operation_type, frequencia, dias_semana, schedule_time, 
                  1 if is_active else 0))
            
            self.conn.commit()
            schedule_id = cursor.lastrowid
            cursor.close()
            
            self.logger.info(f"Agendamento {schedule_id} criado")
            return schedule_id
            
        except Exception as e:
            self.logger.error(f"Erro ao criar agendamento: {e}")
            raise
    
    def update_schedule(self, schedule_id: int, operation_type: str,
                       schedule_type: str, schedule_time: str, 
                       schedule_day: int = None, is_active: bool = True):
        """Atualiza um agendamento existente"""
        try:
            import json
            
            # Mapear schedule_type para frequencia
            frequencia_map = {
                'daily': 'DIARIA',
                'weekly': 'SEMANAL',
                'monthly': 'MENSAL'
            }
            frequencia = frequencia_map.get(schedule_type, 'DIARIA')
            
            # Para weekly/monthly, armazenar o dia
            dias_semana = None
            if schedule_day is not None:
                dias_semana = json.dumps([schedule_day])
            
            cursor = self.conn.cursor()
            
            cursor.execute("""
                UPDATE agendamentos
                SET 
                    tipo_operacao = ?,
                    frequencia = ?,
                    dias_semana = ?,
                    hora = ?,
                    is_active = ?
                WHERE id = ?
            """, (operation_type, frequencia, dias_semana, schedule_time,
                  1 if is_active else 0, schedule_id))
            
            self.conn.commit()
            cursor.close()
            
            self.logger.info(f"Agendamento {schedule_id} atualizado")
            
        except Exception as e:
            self.logger.error(f"Erro ao atualizar agendamento: {e}")
            raise
    
    def get_schedule(self, schedule_id: int):
        """Busca um agendamento pelo ID"""
        try:
            import json
            
            cursor = self.conn.cursor()
            
            cursor.execute("""
                SELECT 
                    id, tipo_operacao, frequencia, hora, 
                    dias_semana, is_active, ultima_execucao
                FROM agendamentos
                WHERE id = ?
            """, (schedule_id,))
            
            row = cursor.fetchone()
            cursor.close()
            
            if row:
                # Mapear frequencia para schedule_type
                schedule_type_map = {
                    'DIARIA': 'daily',
                    'SEMANAL': 'weekly',
                    'MENSAL': 'monthly'
                }
                
                frequencia = row[2]
                schedule_type = schedule_type_map.get(frequencia, 'daily')
                
                # Extrair schedule_day de dias_semana
                schedule_day = None
                if row[4]:  # dias_semana
                    try:
                        dias = json.loads(row[4])
                        if dias and len(dias) > 0:
                            schedule_day = dias[0]
                    except:
                        pass
                
                return {
                    'id': row[0],
                    'operation_type': row[1],
                    'schedule_type': schedule_type,
                    'schedule_time': row[3],
                    'schedule_day': schedule_day,
                    'is_active': bool(row[5]),
                    'last_run': row[6]
                }
            
            return None
            
        except Exception as e:
            self.logger.error(f"Erro ao buscar agendamento: {e}")
            return None
    
    def get_all_schedules(self):
        """Retorna todos os agendamentos"""
        try:
            import json
            
            cursor = self.conn.cursor()
            
            cursor.execute("""
                SELECT 
                    id, tipo_operacao, frequencia, hora,
                    dias_semana, is_active, ultima_execucao
                FROM agendamentos
                ORDER BY id
            """)
            
            schedules = []
            for row in cursor.fetchall():
                # Mapear frequencia para schedule_type
                schedule_type_map = {
                    'DIARIA': 'daily',
                    'SEMANAL': 'weekly',
                    'MENSAL': 'monthly'
                }
                
                frequencia = row[2]
                schedule_type = schedule_type_map.get(frequencia, 'daily')
                
                # Extrair schedule_day
                schedule_day = None
                if row[4]:  # dias_semana
                    try:
                        dias = json.loads(row[4])
                        if dias and len(dias) > 0:
                            schedule_day = dias[0]
                    except:
                        pass
                
                schedules.append({
                    'id': row[0],
                    'operation_type': row[1],
                    'schedule_type': schedule_type,
                    'schedule_time': row[3],
                    'schedule_day': schedule_day,
                    'is_active': bool(row[5]),
                    'last_run': row[6]
                })
            
            cursor.close()
            return schedules
            
        except Exception as e:
            self.logger.error(f"Erro ao buscar agendamentos: {e}")
            return []
    
    def delete_schedule(self, schedule_id: int) -> bool:
        """Remove um agendamento"""
        try:
            cursor = self.conn.cursor()
            cursor.execute("DELETE FROM agendamentos WHERE id = ?", (schedule_id,))
            self.conn.commit()
            cursor.close()
            return True
        except Exception as e:
            self.logger.error(f"Erro ao deletar agendamento: {e}")
            return False
    
    def update_schedule_last_run(self, operation_type: str):
        """Atualiza a última execução de um agendamento"""
        try:
            # ✅ CRIAR NOVA CONEXÃO (thread-safe)
            import sqlite3
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            
            cursor.execute("""
                UPDATE agendamentos
                SET ultima_execucao = CURRENT_TIMESTAMP
                WHERE tipo_operacao = ?
            """, (operation_type,))
            
            conn.commit()
            cursor.close()
            conn.close()
            
        except Exception as e:
            self.logger.error(f"Erro ao atualizar última execução: {e}")
    
    def get_all_clients(self) -> List[Dict]:
        """Alias para get_all_clientes (para compatibilidade com GUI)"""
        return self.get_all_clientes()
    
    # ================================================================
    # MÉTODOS DE LOGS
    # ================================================================
    
    def add_log(self, tipo_operacao: str, status: str, mensagem: str = None,
               registros: int = 0, tempo: float = 0, error_details: str = None):
        """Adiciona log de execução"""
        cursor = self.conn.cursor()
        cursor.execute("""
            INSERT INTO logs_execucao 
            (tipo_operacao, status, mensagem, registros_processados, 
             tempo_execucao_segundos, error_details)
            VALUES (?, ?, ?, ?, ?, ?)
        """, (tipo_operacao, status, mensagem, registros, tempo, error_details))
        self.conn.commit()
    
    def get_logs_recentes(self, limit: int = 100) -> List[Dict]:
        """Obtém logs recentes"""
        cursor = self.conn.cursor()
        cursor.execute("""
            SELECT * FROM logs_execucao 
            ORDER BY created_at DESC LIMIT ?
        """, (limit,))
        
        return [dict(row) for row in cursor.fetchall()]
    
    # ============================
    # PEGAR AS CONEXOES DO SQLITE
    # ============================
    def get_connection(self):
        return sqlite3.connect(
            self.db_path,
            detect_types=sqlite3.PARSE_DECLTYPES
        )    
        
    # ================================================================
    # MÉTODOS THREAD-SAFE (para uso em threads diferentes)
    # ================================================================
    
    def _get_thread_safe_connection(self):
        """Cria uma nova conexão SQLite (thread-safe)"""
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn
    
    def get_oracle_config_threadsafe(self, nome_conexao: str = None):
        """Obtém configuração Oracle (thread-safe)"""
        conn = self._get_thread_safe_connection()
        cursor = conn.cursor()
        
        try:
            if nome_conexao:
                cursor.execute("""
                    SELECT * FROM config_oracle 
                    WHERE nome_conexao = ? AND is_active = 1
                """, (nome_conexao,))
            else:
                cursor.execute("""
                    SELECT * FROM config_oracle 
                    WHERE is_active = 1 
                    ORDER BY created_at DESC LIMIT 1
                """)
            
            config = cursor.fetchone()
            
            if config:
                from .encryption import encryption_manager
                config_dict = dict(config)
                # Descriptografar senha
                config_dict['password'] = encryption_manager.decrypt(
                    config_dict['password_encrypted']
                )
                del config_dict['password_encrypted']
                return config_dict
            
            return None
            
        finally:
            cursor.close()
            conn.close()
    
    def get_oriontax_config_threadsafe(self):
        """Obtém configuração OrionTax (thread-safe)"""
        conn = self._get_thread_safe_connection()
        cursor = conn.cursor()
        
        try:
            cursor.execute("""
                SELECT * FROM config_oriontax 
                WHERE is_active = 1 
                ORDER BY created_at DESC LIMIT 1
            """)
            
            config = cursor.fetchone()
            
            if config:
                from .encryption import encryption_manager
                config_dict = dict(config)
                config_dict['password'] = encryption_manager.decrypt(
                    config_dict['password_encrypted']
                )
                del config_dict['password_encrypted']
                return config_dict
            
            return None
            
        finally:
            cursor.close()
            conn.close()
    
    def get_all_clientes_threadsafe(self):
        """Obtém todos os clientes ativos (thread-safe)"""
        conn = self._get_thread_safe_connection()
        cursor = conn.cursor()
        
        try:
            cursor.execute("""
                SELECT * FROM clientes WHERE is_active = 1 ORDER BY nome
            """)
            
            return [dict(row) for row in cursor.fetchall()]
            
        finally:
            cursor.close()
            conn.close()
    
    def add_log_threadsafe(self, tipo_operacao: str, status: str, mensagem: str = None,
                          registros: int = 0, tempo: float = 0, error_details: str = None):
        """Adiciona log de execução (thread-safe)"""
        conn = self._get_thread_safe_connection()
        cursor = conn.cursor()
        
        try:
            cursor.execute("""
                INSERT INTO logs_execucao 
                (tipo_operacao, status, mensagem, registros_processados, 
                 tempo_execucao_segundos, error_details)
                VALUES (?, ?, ?, ?, ?, ?)
            """, (tipo_operacao, status, mensagem, registros, tempo, error_details))
            
            conn.commit()
            
        finally:
            cursor.close()
            conn.close()    
            
    def change_password(self, username: str, old_password: str, new_password: str) -> tuple:
        """
        Altera senha do usuário
        
        Args:
            username: Nome do usuário
            old_password: Senha antiga
            new_password: Nova senha
            
        Returns:
            (success: bool, message: str)
        """
        cursor = self.conn.cursor()
        
        try:
            # Verificar senha antiga
            cursor.execute("""
                SELECT id, password_hash FROM usuarios
                WHERE username = ? AND is_active = 1
            """, (username,))
            
            user = cursor.fetchone()
            
            if not user:
                return False, "Usuário não encontrado"
            
            if not password_hasher.verify_password(old_password, user['password_hash']):
                return False, "Senha atual incorreta"
            
            # Atualizar senha
            new_hash = password_hasher.hash_password(new_password)
            
            cursor.execute("""
                UPDATE usuarios SET password_hash = ? WHERE id = ?
            """, (new_hash, user['id']))
            
            self.conn.commit()
            
            return True, "Senha alterada com sucesso!"
            
        except Exception as e:
            return False, f"Erro ao alterar senha: {e}"                


# Instância global
db_manager = DatabaseManager()