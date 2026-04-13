"""
Heartbeat Service - Monitora e envia dados de saúde do sistema para o OrionTax.

A cada intervalo configurado, envia métricas do sistema para as tabelas
cliente_monitor e cliente_monitor_historico no PostgreSQL do OrionTax.
"""
import logging
import os
import platform
import socket
from datetime import datetime, timedelta
from pathlib import Path

import psutil


class HeartbeatService:
    """
    Envia heartbeats periódicos com métricas do sistema para o PostgreSQL.

    Para cada cliente (CNPJ) ativo no SQLite local, realiza UPSERT em
    cliente_monitor e INSERT em cliente_monitor_historico.
    """

    def __init__(self, db_manager, app_start_time: datetime, app_version: str):
        """
        Args:
            db_manager: Instância do DatabaseManager (acesso ao SQLite local)
            app_start_time: Datetime em que a aplicação foi iniciada
            app_version: Versão da aplicação (ex: "1.0.0")
        """
        self.db_manager = db_manager
        self.app_start_time = app_start_time
        self.app_version = app_version
        self.logger = logging.getLogger(__name__)

    # ------------------------------------------------------------------
    # Ponto de entrada chamado pelo APScheduler
    # ------------------------------------------------------------------

    def send(self):
        """
        Executa o heartbeat para todos os clientes ativos.
        Chamado automaticamente pelo scheduler no intervalo configurado.
        """
        try:
            oriontax_config = self.db_manager.get_oriontax_config_threadsafe()
            if not oriontax_config:
                self.logger.warning("Heartbeat: configuração OrionTax não encontrada, pulando.")
                return

            clientes = self.db_manager.get_all_clientes_threadsafe()
            if not clientes:
                self.logger.warning("Heartbeat: nenhum cliente cadastrado, pulando.")
                return

            # Coleta métricas do sistema uma única vez (idênticas para todos os clientes)
            system_data = self._collect_system_data()

            for cliente in clientes:
                cnpj = cliente['cnpj']
                try:
                    self._send_for_client(oriontax_config, cnpj, system_data)
                except Exception as e:
                    self.logger.error(f"Heartbeat falhou para CNPJ {cnpj}: {e}")

        except Exception as e:
            self.logger.error(f"Erro geral no heartbeat: {e}")
            import traceback
            self.logger.error(traceback.format_exc())

    # ------------------------------------------------------------------
    # Coleta de dados
    # ------------------------------------------------------------------

    def _collect_system_data(self) -> dict:
        """Coleta métricas do sistema operacional e do processo da aplicação."""
        now = datetime.now()

        hostname = socket.gethostname()

        try:
            usuario_so = os.getlogin()
        except OSError:
            usuario_so = (
                os.environ.get('USERNAME')
                or os.environ.get('USER')
                or 'desconhecido'
            )

        try:
            ip_local = socket.gethostbyname(hostname)
        except Exception:
            ip_local = None

        cpu_percent = psutil.cpu_percent(interval=0.5)
        memoria = psutil.virtual_memory()
        disco = psutil.disk_usage('/')

        try:
            memoria_app_mb = round(psutil.Process().memory_info().rss / (1024 * 1024), 2)
        except Exception:
            memoria_app_mb = None

        uptime_segundos = int((now - self.app_start_time).total_seconds())

        # platform.version() pode ser muito longo no macOS/Linux — limitar ao VARCHAR(50)
        so_versao = platform.version()[:50]

        return {
            'timestamp': now,
            'hostname': hostname[:255],
            'usuario_so': usuario_so[:100],
            'so_nome': platform.system()[:50],
            'so_versao': so_versao,
            'ip_local': ip_local,
            'cpu_percent': cpu_percent,
            'memoria_percent': memoria.percent,
            'disco_percent': disco.percent,
            'memoria_app_mb': memoria_app_mb,
            'uptime_segundos': uptime_segundos,
        }

    def _get_atividade_data(self) -> dict:
        """
        Consulta logs de execução no SQLite para enriquecer o heartbeat com
        dados de atividade (registros processados hoje, erros nas últimas 24h, etc).
        """
        try:
            conn = self.db_manager._get_thread_safe_connection()
            cursor = conn.cursor()

            hoje = datetime.now().date().isoformat()
            limite_24h = (datetime.now() - timedelta(hours=24)).strftime('%Y-%m-%d %H:%M:%S')
            limite_1h = (datetime.now() - timedelta(hours=1)).strftime('%Y-%m-%d %H:%M:%S')

            # Registros processados hoje (operações com SUCESSO)
            cursor.execute("""
                SELECT COALESCE(SUM(registros_processados), 0)
                FROM logs_execucao
                WHERE status = 'SUCESSO' AND DATE(created_at) = ?
            """, (hoje,))
            registros_hoje = int(cursor.fetchone()[0] or 0)

            # Quantidade de erros nas últimas 24h (para o campo erros_ultimas_24h)
            cursor.execute("""
                SELECT COUNT(*) FROM logs_execucao
                WHERE status = 'ERRO' AND created_at >= ?
            """, (limite_24h,))
            erros_24h = int(cursor.fetchone()[0] or 0)

            # Status 'error' apenas se houve erro na última 1h
            cursor.execute("""
                SELECT COUNT(*) FROM logs_execucao
                WHERE status = 'ERRO' AND created_at >= ?
            """, (limite_1h,))
            erros_1h = int(cursor.fetchone()[0] or 0)

            # Último erro registrado
            cursor.execute("""
                SELECT mensagem, error_details, created_at FROM logs_execucao
                WHERE status = 'ERRO'
                ORDER BY created_at DESC LIMIT 1
            """)
            row = cursor.fetchone()
            ultimo_erro = None
            ultimo_erro_ts = None
            if row:
                ultimo_erro = (row[1] or row[0] or '')[:500]
                ultimo_erro_ts = row[2]

            # Última operação bem-sucedida
            cursor.execute("""
                SELECT created_at FROM logs_execucao
                WHERE status = 'SUCESSO'
                ORDER BY created_at DESC LIMIT 1
            """)
            row_atividade = cursor.fetchone()
            ultima_atividade = row_atividade[0] if row_atividade else None

            conn.close()

            return {
                'registros_processados_hoje': registros_hoje,
                'erros_ultimas_24h': erros_24h,
                'ultimo_erro': ultimo_erro,
                'ultimo_erro_timestamp': ultimo_erro_ts,
                'ultima_atividade': ultima_atividade,
                'status': 'error' if erros_1h > 0 else 'running',
            }

        except Exception as e:
            self.logger.error(f"Heartbeat: erro ao consultar atividade no SQLite: {e}")
            return {
                'registros_processados_hoje': 0,
                'erros_ultimas_24h': 0,
                'ultimo_erro': None,
                'ultimo_erro_timestamp': None,
                'ultima_atividade': None,
                'status': 'running',
            }

    def _read_log_file(self) -> str:
        """
        Lê todos os arquivos de log da pasta /logs e retorna as linhas
        das últimas 12h como string, independente do nome do arquivo.
        """
        try:
            log_dir = Path(__file__).parent.parent / 'logs'
            if not log_dir.exists():
                return ''

            limite = datetime.now() - timedelta(hours=12)

            # Coleta todos os arquivos .log ordenados por data de modificação
            arquivos = sorted(
                log_dir.glob('*.log*'),
                key=lambda p: p.stat().st_mtime
            )

            linhas = []
            for arquivo in arquivos:
                # Pula arquivos modificados antes da janela de 12h
                if arquivo.stat().st_mtime < limite.timestamp():
                    continue
                with open(arquivo, 'r', encoding='utf-8', errors='replace') as f:
                    linhas.extend(f.readlines())

            if not linhas:
                return ''

            # Filtra linha a linha pelo timestamp
            linhas_filtradas = []
            for linha in linhas:
                try:
                    ts = datetime.strptime(linha[:19], '%Y-%m-%d %H:%M:%S')
                    if ts >= limite:
                        linhas_filtradas.append(linha)
                except (ValueError, IndexError):
                    # Linha de continuação (traceback, etc.)
                    if linhas_filtradas:
                        linhas_filtradas.append(linha)

            return ''.join(linhas_filtradas)

        except Exception as e:
            self.logger.warning(f"Heartbeat: não foi possível ler arquivo de log: {e}")
            return ''

    # ------------------------------------------------------------------
    # Envio para PostgreSQL
    # ------------------------------------------------------------------

    def _send_for_client(self, oriontax_config: dict, cnpj: str, system_data: dict):
        """Executa UPSERT em cliente_monitor e INSERT em cliente_monitor_historico."""
        from core.oriontax_client import OrionTaxClient

        atividade = self._get_atividade_data()
        logs_24h = self._read_log_file()
        now = system_data['timestamp']

        client = OrionTaxClient(oriontax_config)
        client.connect()

        try:
            cursor = client.connection.cursor()

            # --- UPSERT em cliente_monitor ---
            cursor.execute("""
                INSERT INTO cliente_monitor (
                    cliente_id, hostname, usuario_so, versao_app, status,
                    so_nome, so_versao, ip_local,
                    cpu_percent, memoria_percent, disco_percent, memoria_app_mb,
                    uptime_segundos, registros_processados_hoje, ultima_atividade,
                    erros_ultimas_24h, ultimo_erro, ultimo_erro_timestamp,
                    ultimo_heartbeat, primeiro_heartbeat,
                    logs_ultimas_24h
                ) VALUES (
                    %s, %s, %s, %s, %s,
                    %s, %s, %s,
                    %s, %s, %s, %s,
                    %s, %s, %s,
                    %s, %s, %s,
                    %s, %s,
                    %s
                )
                ON CONFLICT (cliente_id) DO UPDATE SET
                    hostname                   = EXCLUDED.hostname,
                    usuario_so                 = EXCLUDED.usuario_so,
                    versao_app                 = EXCLUDED.versao_app,
                    status                     = EXCLUDED.status,
                    so_nome                    = EXCLUDED.so_nome,
                    so_versao                  = EXCLUDED.so_versao,
                    ip_local                   = EXCLUDED.ip_local,
                    cpu_percent                = EXCLUDED.cpu_percent,
                    memoria_percent            = EXCLUDED.memoria_percent,
                    disco_percent              = EXCLUDED.disco_percent,
                    memoria_app_mb             = EXCLUDED.memoria_app_mb,
                    uptime_segundos            = EXCLUDED.uptime_segundos,
                    registros_processados_hoje = EXCLUDED.registros_processados_hoje,
                    ultima_atividade           = EXCLUDED.ultima_atividade,
                    erros_ultimas_24h          = EXCLUDED.erros_ultimas_24h,
                    ultimo_erro                = EXCLUDED.ultimo_erro,
                    ultimo_erro_timestamp      = EXCLUDED.ultimo_erro_timestamp,
                    ultimo_heartbeat           = EXCLUDED.ultimo_heartbeat,
                    logs_ultimas_24h           = EXCLUDED.logs_ultimas_24h
            """, (
                cnpj,
                system_data['hostname'],
                system_data['usuario_so'],
                self.app_version,
                atividade['status'],
                system_data['so_nome'],
                system_data['so_versao'],
                system_data['ip_local'],
                system_data['cpu_percent'],
                system_data['memoria_percent'],
                system_data['disco_percent'],
                system_data['memoria_app_mb'],
                system_data['uptime_segundos'],
                atividade['registros_processados_hoje'],
                atividade['ultima_atividade'],
                atividade['erros_ultimas_24h'],
                atividade['ultimo_erro'],
                atividade['ultimo_erro_timestamp'],
                now,
                now,  # primeiro_heartbeat só é usado no INSERT (ignorado no UPDATE)
                logs_24h,
            ))

            # --- INSERT em cliente_monitor_historico ---
            cursor.execute("""
                INSERT INTO cliente_monitor_historico (
                    cliente_id, timestamp,
                    cpu_percent, memoria_percent, disco_percent,
                    status, uptime_segundos, logs_ultimas_24h
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
            """, (
                cnpj,
                now,
                system_data['cpu_percent'],
                system_data['memoria_percent'],
                system_data['disco_percent'],
                atividade['status'],
                system_data['uptime_segundos'],
                logs_24h,
            ))

            client.connection.commit()

            self.logger.info(
                f"Heartbeat OK | CNPJ={cnpj} | "
                f"CPU={system_data['cpu_percent']}% | "
                f"MEM={system_data['memoria_percent']}% | "
                f"DISCO={system_data['disco_percent']}% | "
                f"STATUS={atividade['status']}"
            )

        except Exception:
            client.connection.rollback()
            raise

        finally:
            client.disconnect()

