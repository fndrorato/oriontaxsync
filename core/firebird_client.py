"""
Cliente Firebird - Gerencia conexão e operações com Firebird 2.5

Implementa a mesma interface do OracleClient para que o restante
do sistema possa usar os dois bancos de forma transparente.
"""
import math
import pandas as pd
import logging
from typing import Dict, Tuple

from .oracle_client import TABLE_COLUMNS, TABLE_NUMBER_COLUMNS, TABLE_ZFILL_COLUMNS


class FirebirdClient:
    """Cliente para conexão e operações com Firebird 2.5"""

    def __init__(self, config: Dict):
        """
        Inicializa o cliente Firebird.

        Args:
            config: Dicionário com configuração de conexão
                - host: str
                - port: int  (padrão: 3050)
                - database_path: str  (caminho do arquivo .fdb)
                - username: str
                - password: str
                - charset: str (padrão: 'UTF8')
        """
        self.config = config
        self.connection = None
        self.logger = logging.getLogger(__name__)

    # ------------------------------------------------------------------
    # CONEXÃO
    # ------------------------------------------------------------------

    # Mapa charset configurado → codec Python para decode manual de bytes (colunas NONE)
    _PYTHON_CODEC_MAP = {
        'WIN1252': 'cp1252',
        'WIN1251': 'cp1251',
        'WIN1250': 'cp1250',
        'ISO8859_1': 'iso-8859-1',
        'LATIN1': 'iso-8859-1',
        'UTF8': 'cp1252',       # banco configurado como UTF8 mas dados em WIN1252
        'UNICODE_FSS': 'utf-8',
        'NONE': 'cp1252',
    }

    def connect(self) -> bool:
        """Conecta ao Firebird via firebirdsql."""
        import firebirdsql

        fb_charset = self.config.get('charset', 'WIN1252').upper()

        # Sempre conecta com ISO8859_1: está no charset_map do firebirdsql
        # ('ISO8859_1' → 'iso8859_1'), evitando falhas com WIN1252/NONE/UTF8.
        # Firebird converte dados para ISO-8859-1 antes de enviar, o que cobre
        # todos os caracteres do português brasileiro (faixa 0xA0–0xFF).
        self._python_codec = self._PYTHON_CODEC_MAP.get(fb_charset, 'cp1252')

        self.connection = firebirdsql.connect(
            host=self.config['host'],
            database=self.config['database_path'],
            user=self.config['username'],
            password=self.config['password'],
            port=self.config.get('port', 3050),
            charset='ISO8859_1',
            auth_plugin_name='Legacy_Auth',
        )
        self.logger.info(f"✓ Conectado ao Firebird: {self.config['host']}")
        return True

    def disconnect(self):
        """Desconecta do Firebird."""
        if self.connection:
            try:
                self.connection.close()
                self.logger.info("Desconectado do Firebird")
            except Exception as e:
                self.logger.error(f"Erro ao desconectar do Firebird: {e}")
            finally:
                self.connection = None

    def test_connection(self) -> Tuple[bool, str]:
        """Testa a conexão com o Firebird."""
        try:
            self.connect()
            cursor = self.connection.cursor()
            cursor.execute(
                "SELECT RDB$GET_CONTEXT('SYSTEM', 'ENGINE_VERSION') FROM RDB$DATABASE"
            )
            version = cursor.fetchone()[0]
            cursor.close()
            self.disconnect()
            return True, f"Conexão Firebird bem-sucedida\nVersão: {version}"
        except Exception as e:
            self.logger.error(f"Erro ao testar conexão Firebird: {e}")
            return False, f"Erro: {str(e)}"

    # ------------------------------------------------------------------
    # LEITURA DE VIEWS
    # ------------------------------------------------------------------

    def _decode_value(self, value):
        """Decodifica bytes para string usando o codec da conexão."""
        if isinstance(value, (bytes, bytearray)):
            return value.decode(self._python_codec, errors='replace')
        return value

    def _read_view(self, view_name: str) -> pd.DataFrame:
        """Lê uma VIEW e retorna um DataFrame."""
        codec = getattr(self, '_python_codec', 'cp1252')
        cursor = self.connection.cursor()
        cursor.execute(f"SELECT * FROM {view_name}")
        columns = [
            (desc[0].decode(codec, errors='replace') if isinstance(desc[0], bytes) else desc[0]).strip()
            for desc in cursor.description
        ]
        rows = [
            tuple(self._decode_value(val) for val in row)
            for row in cursor.fetchall()
        ]
        cursor.close()
        return pd.DataFrame(rows, columns=columns)

    def read_views_to_dataframes(self) -> Dict[str, pd.DataFrame]:
        """
        Lê dados das VIEWs do Firebird para enviar à OrionTax.

        Returns:
            Dict com 4 DataFrames das VIEWs
        """
        try:
            if not self.connection:
                self.connect()

            self.logger.info("Lendo VIEWs Firebird (todos os registros)...")

            self.logger.info("Lendo MXF_VW_ICMS_ENTRADA...")
            df_icms_entrada = self._read_view("MXF_VW_ICMS_ENTRADA")
            self.logger.info(f"✓ ICMS Entrada: {len(df_icms_entrada)} registros")

            self.logger.info("Lendo MXF_VW_ICMS...")
            df_icms_saida = self._read_view("MXF_VW_ICMS")
            self.logger.info(f"✓ ICMS Saída: {len(df_icms_saida)} registros")

            self.logger.info("Lendo MXF_VW_PIS_COFINS...")
            df_pis_cofins = self._read_view("MXF_VW_PIS_COFINS")
            self.logger.info(f"✓ PIS/COFINS: {len(df_pis_cofins)} registros")

            self.logger.info("Lendo MXF_VW_CBS_IBS...")
            df_cbs_ibs = self._read_view("MXF_VW_CBS_IBS")
            self.logger.info(f"✓ CBS/IBS: {len(df_cbs_ibs)} registros")

            return {
                'icms_entrada': df_icms_entrada,
                'icms_saida': df_icms_saida,
                'pis_cofins': df_pis_cofins,
                'cbs_ibs': df_cbs_ibs,
            }

        except Exception as e:
            self.logger.error(f"Erro ao ler VIEWs Firebird: {e}")
            raise

    # ------------------------------------------------------------------
    # INSERÇÃO NAS TABELAS TMP
    # ------------------------------------------------------------------

    def _insert_dataframe_firebird(
        self,
        df: pd.DataFrame,
        table_name: str,
        cursor,
        batch_size: int = 1000,
    ) -> int:
        """
        Insere um DataFrame no Firebird usando executemany.

        Usa '?' como bind parameter (padrão Firebird/ODBC)
        e CURRENT_TIMESTAMP para as colunas de data.
        """
        logger = self.logger

        if table_name not in TABLE_COLUMNS:
            raise ValueError(f"Tabela não mapeada em TABLE_COLUMNS: {table_name}")

        df.columns = [c.upper() for c in df.columns]
        expected_columns = TABLE_COLUMNS[table_name]
        df = df.reindex(columns=expected_columns)

        logger.info(f"{table_name} | Colunas finais para insert: {list(df.columns)}")

        inserted_rows = 0

        if table_name == "MXF_TMP_ICMS_SAIDA":
            insert_sql = """
                INSERT INTO MXF_TMP_ICMS_SAIDA (
                    CODIGO_PRODUTO, EAN, NCM, FUNDAMENTO_LEGAL, CEST,
                    FECP, SSS_CSOSN, SNC_CST, SNC_ALQ, SNC_ALQST,
                    SNC_RBC, SNC_RBCST, SNC_CBENEF, SNC_ALQ_BENEF, SAC_CST,
                    SAC_ALQ, SAC_ALQST, SAC_RBC, SAC_RBCST, SAC_CBENEF,
                    SAC_ALQ_BENEF, SVC_CST, SVC_ALQ, SVC_ALQST, SVC_RBC,
                    SVC_RBCST, DTA_ALTERACAO, DTA_CADASTRO
                ) VALUES (
                    ?, ?, ?, ?, ?,
                    ?, ?, ?, ?, ?,
                    ?, ?, ?, ?, ?,
                    ?, ?, ?, ?, ?,
                    ?, ?, ?, ?, ?,
                    ?, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP
                )
            """
            expected_cols = 26

        elif table_name == "MXF_TMP_PIS_COFINS":
            insert_sql = """
                INSERT INTO MXF_TMP_PIS_COFINS (
                    CODIGO_PRODUTO, EAN, NCM, COD_NATUREZA_RECEITA,
                    PIS_CST_E, PIS_ALQ_E, PIS_CST_S, PIS_ALQ_S,
                    COFINS_CST_E, COFINS_ALQ_E, COFINS_CST_S, COFINS_ALQ_S,
                    FUNDAMENTO_LEGAL
                ) VALUES (
                    ?, ?, ?, ?, ?, ?, ?,
                    ?, ?, ?, ?, ?, ?
                )
            """
            expected_cols = 13

        elif table_name == "MXF_TMP_CBS_IBS":
            insert_sql = """
                INSERT INTO MXF_TMP_CBS_IBS (
                    CODIGO_PRODUTO, EAN, CCLASSTRIB, CST_CBS_IBS,
                    ALQ_CBS, RBC_CBS, ALQ_IBS, RBC_IBS,
                    ALQ_IBS_MUN, RBC_IBS_MUN,
                    ALQ_IS, ALQ_IS_ESPEC, CST_IS, CCLASSTRIB_IS,
                    FUNDAMENTO_LEGAL
                ) VALUES (
                    ?, ?, ?, ?, ?,
                    ?, ?, ?, ?, ?,
                    ?, ?, ?, ?, ?
                )
            """
            expected_cols = 15

        else:
            raise ValueError(f"Tabela não suportada: {table_name}")

        columns = list(df.columns)

        def clean_value(value, col_name):
            try:
                if value is None:
                    return None
                try:
                    if pd.isna(value):
                        return None
                except (TypeError, ValueError):
                    pass

                if isinstance(value, str):
                    v = value.strip()
                    if v.lower() in ("none", "null", "", "nan", "nat", "na", "<na>"):
                        return None
                    if col_name in TABLE_NUMBER_COLUMNS.get(table_name, set()):
                        try:
                            return float(v.replace(",", "."))
                        except ValueError:
                            logger.error(
                                f"{table_name} | {col_name} | Valor numérico inválido: '{value}'"
                            )
                            return None
                    zfill_width = TABLE_ZFILL_COLUMNS.get(table_name, {}).get(col_name)
                    if zfill_width and v.isdigit():
                        v = v.zfill(zfill_width)
                    return v

                if col_name in TABLE_NUMBER_COLUMNS.get(table_name, set()):
                    try:
                        return float(value)
                    except Exception:
                        logger.error(
                            f"{table_name} | {col_name} | Valor numérico inválido: {value}"
                        )
                        return None

                # Colunas não-numéricas com tipo numérico (int/float/numpy scalar):
                # converte para string preservando exatamente o valor do PostgreSQL.
                native = value.item() if hasattr(value, 'item') else value
                if isinstance(native, (int, float)):
                    return str(int(native))
                return native
            except Exception as e:
                logger.error(
                    f"{table_name} | {col_name} | Erro no valor '{value}': {e}"
                )
                return None

        batch = []

        for _, row in df.iterrows():
            clean_row = [clean_value(row[col], col) for col in columns]

            if len(clean_row) != expected_cols:
                raise ValueError(
                    f"{table_name} | Quantidade de colunas inválida: "
                    f"{len(clean_row)} (esperado {expected_cols})"
                )

            batch.append(tuple(clean_row))

            if len(batch) >= batch_size:
                try:
                    cursor.executemany(insert_sql, batch)
                    inserted_rows += len(batch)
                    batch.clear()
                except Exception as e:
                    logger.critical(f"Falha no executemany para {table_name}: {e}")
                    logger.error("Amostra de dados do erro: %s", batch[0])
                    raise

        if batch:
            try:
                cursor.executemany(insert_sql, batch)
                inserted_rows += len(batch)
            except Exception as e:
                logger.critical(f"Falha no executemany para {table_name}: {e}")
                logger.error("Amostra de dados do erro: %s", batch[0])
                raise

        logger.info(f"{table_name} | Inseridos {inserted_rows} registros com sucesso")
        return inserted_rows

    def write_dataframes_to_tmp_tables(
        self,
        dataframes: Dict[str, pd.DataFrame],
    ) -> Tuple[bool, str]:
        """
        Grava DataFrames nas tabelas TMP do Firebird (dados vindos da OrionTax).

        Limpa tudo e insere tudo — sem filtro de CNPJ.
        """
        try:
            if not self.connection:
                self.connect()

            cursor = self.connection.cursor()
            total_inserted = 0

            self.logger.info("Limpando tabelas TMP do Firebird...")
            cursor.execute("DELETE FROM MXF_TMP_ICMS_ENTRADA")
            cursor.execute("DELETE FROM MXF_TMP_ICMS_SAIDA")
            cursor.execute("DELETE FROM MXF_TMP_PIS_COFINS")
            cursor.execute("DELETE FROM MXF_TMP_CBS_IBS")
            self.logger.info("✓ Tabelas TMP limpas")

            table_map = {
                "icms_entrada": "MXF_TMP_ICMS_ENTRADA",
                "icms_saida":   "MXF_TMP_ICMS_SAIDA",
                "pis_cofins":   "MXF_TMP_PIS_COFINS",
                "cbs_ibs":      "MXF_TMP_CBS_IBS",
            }

            for df_key, table_name in table_map.items():
                if df_key not in dataframes:
                    continue
                df = dataframes[df_key]
                if df.empty:
                    continue
                if table_name == 'MXF_TMP_ICMS_ENTRADA':
                    continue

                self.logger.info(f"Inserindo {len(df)} registros em {table_name}...")

                inserted = self._insert_dataframe_firebird(
                    df=df,
                    table_name=table_name,
                    cursor=cursor,
                    batch_size=5000,
                )
                total_inserted += inserted
                self.logger.info(f"✓ {inserted} registros inseridos em {table_name}")

            self.connection.commit()
            cursor.close()

            message = f"✓ {total_inserted} registros inseridos no Firebird!"
            self.logger.info(message)
            return True, message

        except Exception:
            self.logger.error("Erro ao inserir dados no Firebird", exc_info=True)
            if self.connection:
                self.connection.rollback()
            raise

    # ------------------------------------------------------------------
    # CONTEXT MANAGER
    # ------------------------------------------------------------------

    def __enter__(self):
        self.connect()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.disconnect()
