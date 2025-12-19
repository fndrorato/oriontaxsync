"""
Cliente Oracle - Gerencia conexão e operações com Oracle
"""
import math
import oracledb
import pandas as pd
import logging
from typing import Dict, Tuple

# ============================================
# MAPEAMENTO DE COLUNAS POR TABELA (ORACLE)
# ============================================

TABLE_COLUMNS = {
    "MXF_TMP_ICMS_SAIDA": [
        "CODIGO_PRODUTO", "EAN", "NCM", "FUNDAMENTO_LEGAL", "CEST",
        "FECP", "SSS_CSOSN", "SNC_CST", "SNC_ALQ", "SNC_ALQST",
        "SNC_RBC", "SNC_RBCST", "SNC_CBENEF", "SNC_ALQ_BENEF",
        "SAC_CST", "SAC_ALQ", "SAC_ALQST", "SAC_RBC", "SAC_RBCST",
        "SAC_CBENEF", "SAC_ALQ_BENEF",
        "SVC_CST", "SVC_ALQ", "SVC_ALQST", "SVC_RBC", "SVC_RBCST"
    ],

    "MXF_TMP_PIS_COFINS": [
        "CODIGO_PRODUTO", "EAN", "NCM", "COD_NATUREZA_RECEITA",
        "PIS_CST_E", "PIS_ALQ_E", "PIS_CST_S", "PIS_ALQ_S",
        "COFINS_CST_E", "COFINS_ALQ_E", "COFINS_CST_S", "COFINS_ALQ_S",
        "FUNDAMENTO_LEGAL"
    ],

    "MXF_TMP_CBS_IBS": [
        "CODIGO_PRODUTO", "EAN", "CCLASSTRIB", "CST_CBS_IBS",
        "ALQ_CBS", "RBC_CBS", "ALQ_IBS", "RBC_IBS",
        "ALQ_IBS_MUN", "RBC_IBS_MUN",
        "ALQ_IS", "ALQ_IS_ESPEC", "CST_IS", "CCLASSTRIB_IS",
        "FUNDAMENTO_LEGAL"
    ]
}

TABLE_NUMBER_COLUMNS = {
    "MXF_TMP_ICMS_SAIDA": {
        "FECP", "SNC_ALQ", "SNC_ALQST", "SNC_RBC", "SNC_RBCST",
        "SNC_ALQ_BENEF",
        "SAC_ALQ", "SAC_ALQST", "SAC_RBC", "SAC_RBCST", "SAC_ALQ_BENEF",
        "SVC_ALQ", "SVC_ALQST", "SVC_RBC", "SVC_RBCST"
    },

    "MXF_TMP_PIS_COFINS": {
        "PIS_ALQ_E", "PIS_ALQ_S",
        "COFINS_ALQ_E", "COFINS_ALQ_S"
    },

    "MXF_TMP_CBS_IBS": {
        "ALQ_CBS", "RBC_CBS", "ALQ_IBS", "RBC_IBS",
        "ALQ_IBS_MUN", "RBC_IBS_MUN",
        "ALQ_IS", "ALQ_IS_ESPEC"
    }
}

class OracleClient:
    """Cliente para conexão e operações com Oracle"""
    
    def __init__(self, config: Dict):
        """
        Inicializa o cliente Oracle
        
        Args:
            config: Dicionário com configuração de conexão
                - host: str
                - port: int
                - service_name: str
                - username: str
                - password: str
                - instant_client_path: str (opcional)
        """
        self.config = config
        self.connection = None
        self.logger = logging.getLogger(__name__)
        self.thick_mode_initialized = False
    
    def _init_thick_mode(self):
        """
        Inicializa o modo thick (necessário para Oracle < 12.1)
        
        O modo thick requer Oracle Instant Client instalado
        """
        if not self.thick_mode_initialized:
            try:
                # Se caminho foi configurado, usar ele
                instant_client_path = self.config.get('instant_client_path')
                
                if instant_client_path:
                    self.logger.info(f"Inicializando modo thick com: {instant_client_path}")
                    oracledb.init_oracle_client(lib_dir=instant_client_path)
                    self.logger.info(f"✓ Modo thick inicializado: {instant_client_path}")
                else:
                    self.logger.info("Inicializando modo thick (PATH do sistema)")
                    oracledb.init_oracle_client()
                    self.logger.info("✓ Modo thick inicializado (Oracle Client detectado no PATH)")
                
                self.thick_mode_initialized = True
                
            except Exception as e:
                self.logger.error(f"Erro ao inicializar modo thick: {e}")
                raise Exception(
                    f"Erro ao inicializar modo thick: {str(e)}\n\n"
                    "Oracle Database < 12.1 detectado, mas Oracle Instant Client não está configurado corretamente.\n\n"
                    "Configure o caminho do Instant Client:\n"
                    f"Caminho configurado: {self.config.get('instant_client_path') or 'Nenhum'}\n\n"
                    "Verifique se o caminho está correto e o Instant Client está instalado."
                )
    
    def connect(self) -> bool:
        """
        Conecta ao Oracle (tenta thin mode primeiro, depois thick mode)
        
        Returns:
            True se conectou com sucesso
        """
        dsn = oracledb.makedsn(
            self.config['host'],
            self.config['port'],
            service_name=self.config['service_name']
        )
        
        # ✅ ESTRATÉGIA: Tentar thin primeiro, se falhar com DPY-3010, usar thick
        try:
            self.logger.info("Tentando conexão em modo thin...")
            self.connection = oracledb.connect(
                user=self.config['username'],
                password=self.config['password'],
                dsn=dsn
            )
            
            self.logger.info(f"✓ Conectado ao Oracle (modo thin): {self.config['host']}")
            return True
            
        except oracledb.DatabaseError as e:
            error_code = e.args[0].code if e.args and hasattr(e.args[0], 'code') else None
            error_message = str(e)
            
            self.logger.warning(f"Erro thin mode: {error_message}")
            self.logger.warning(f"Error code: {error_code}")
            
            # ✅ Verificar se é o erro DPY-3010 (versão não suportada)
            if error_code == 3010 or 'DPY-3010' in error_message:
                self.logger.info("Modo thin não suportado para esta versão do Oracle")
                self.logger.info("Tentando modo thick...")
                
                try:
                    # Inicializar modo thick
                    self._init_thick_mode()
                    
                    # Tentar conectar em modo thick
                    self.logger.info("Conectando em modo thick...")
                    self.connection = oracledb.connect(
                        user=self.config['username'],
                        password=self.config['password'],
                        dsn=dsn
                    )
                    
                    self.logger.info(f"✓ Conectado ao Oracle (modo thick): {self.config['host']}")
                    return True
                    
                except Exception as thick_error:
                    self.logger.error(f"Erro ao conectar em modo thick: {thick_error}")
                    raise
            else:
                # Outro tipo de erro
                self.logger.error(f"Erro de conexão: {e}")
                raise
        
        except Exception as e:
            self.logger.error(f"Erro geral ao conectar: {e}")
            raise
    
    def disconnect(self):
        """Desconecta do Oracle"""
        if self.connection:
            try:
                self.connection.close()
                self.logger.info("Desconectado do Oracle")
            except Exception as e:
                self.logger.error(f"Erro ao desconectar: {e}")
            finally:
                self.connection = None
    
    def test_connection(self) -> Tuple[bool, str]:
        """
        Testa a conexão
        
        Returns:
            Tuple (sucesso, mensagem)
        """
        try:
            self.logger.info(f"Config recebida - Host: {self.config['host']}")
            self.logger.info(f"Instant Client Path: {self.config.get('instant_client_path')}")
            
            self.connect()
            
            cursor = self.connection.cursor()
            cursor.execute("SELECT 1 FROM DUAL")
            result = cursor.fetchone()
            
            # Obter versão do Oracle
            cursor.execute("SELECT banner FROM v$version WHERE ROWNUM = 1")
            version = cursor.fetchone()[0]
            self.logger.info(f"Versão Oracle: {version}")
            
            # Verificar qual modo está sendo usado
            mode = "thick" if self.thick_mode_initialized else "thin"
            
            cursor.close()
            self.disconnect()
            
            return True, f"Conexão bem-sucedida (modo {mode})\n{version}"
            
        except Exception as e:
            self.logger.error(f"Erro ao testar conexão: {e}")
            import traceback
            self.logger.error(traceback.format_exc())
            return False, f"Erro: {str(e)}"
        
    def _get_table_columns(self, cursor, table_name: str) -> set:
        try:
            self.logger.debug(
                f"Buscando colunas da tabela Oracle: [{table_name}]"
            )

            sql = """
                SELECT column_name
                FROM all_tab_columns
                WHERE table_name = :table_name
            """

            self.logger.debug(
                f"SQL _get_table_columns:\n{sql}\nPARAMS: {table_name.upper()}"
            )

            cursor.execute(
                sql,
                {"table_name": table_name.upper()}
            )

            cols = {row[0] for row in cursor.fetchall()}

            self.logger.debug(
                f"Colunas encontradas em {table_name}: {sorted(cols)}"
            )

            return cols

        except Exception as e:
            self.logger.error(
                f"Erro ao buscar colunas da tabela {table_name}",
                exc_info=True
            )
            raise

    def _normalize_dataframe_for_oracle(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        Normaliza tipos para evitar ORA-01722 / DPY-4004
        """
        df = df.copy()

        for col in df.columns:
            # Datas
            if "DATA" in col or col.startswith("DT_"):
                df[col] = pd.to_datetime(df[col], errors="coerce")

            # Numéricos
            elif df[col].dtype == object:
                # tenta converter string → número
                df[col] = (
                    df[col]
                    .astype(str)
                    .str.replace(",", ".", regex=False)
                    .replace({"": None, "nan": None, "NaN": None})
                )

        return df
        
    def _insert_dataframe_oracle(
        self,
        df,
        table_name: str,
        cursor,
        batch_size: int = 1000
    ) -> int:
        """
        Insere um DataFrame no Oracle usando executemany,
        com SQL específico por tabela.
        """

        logger = self.logger

        # ==========================
        # NORMALIZA E REINDEXA DF
        # ==========================
        if table_name not in TABLE_COLUMNS:
            raise ValueError(f"Tabela não mapeada em TABLE_COLUMNS: {table_name}")

        # Normaliza nomes das colunas
        df.columns = [c.upper() for c in df.columns]

        expected_columns = TABLE_COLUMNS[table_name]

        # Mantém somente as colunas esperadas e na ordem correta
        df = df.reindex(columns=expected_columns)

        logger.info(
            f"{table_name} | Colunas finais para insert: {list(df.columns)}"
        )

        inserted_rows = 0

        # ==========================
        # SQL POR TABELA
        # ==========================
        if table_name == "MXF_TMP_ICMS_SAIDA":
            insert_sql = """
                INSERT INTO MXF_TMP_ICMS_SAIDA (
                    CODIGO_PRODUTO, EAN, NCM, FUNDAMENTO_LEGAL, CEST, 
                    FECP, SSS_CSOSN, SNC_CST, SNC_ALQ, SNC_ALQST, 
                    SNC_RBC, SNC_RBCST, SNC_CBENEF, SNC_ALQ_BENEF, SAC_CST, 
                    SAC_ALQ, SAC_ALQST, SAC_RBC, SAC_RBCST, SAC_CBENEF, 
                    SAC_ALQ_BENEF, SVC_CST, SVC_ALQ, SVC_ALQST, SVC_RBC, 
                    SVC_RBCST,
                    DTA_ALTERACAO,
                    DTA_CADASTRO
                ) VALUES (
                    :1, :2, :3, :4, :5,
                    :6, :7, :8, :9, :10,
                    :11, :12, :13, :14, :15,
                    :16, :17, :18, :19, :20,
                    :21, :22, :23, :24, :25,
                    :26,
                    SYSDATE,
                    SYSDATE
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
                    :1, :2, :3, :4, :5, :6, :7,
                    :8, :9, :10, :11, :12, :13
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
                    :1, :2, :3, :4, :5,
                    :6, :7, :8, :9, :10,
                    :11, :12, :13, :14, :15
                )
            """
            expected_cols = 15

        else:
            raise ValueError(f"Tabela não suportada: {table_name}")

        columns = list(df.columns)

        # ==========================
        # LIMPEZA DE VALORES
        # ==========================
        def clean_value(value, col_name):
            try:
                # NULLs
                if value is None:
                    return None

                if isinstance(value, float) and math.isnan(value):
                    return None

                # Strings
                if isinstance(value, str):
                    v = value.strip()

                    if v.lower() in ("none", "null", ""):
                        return None

                    # Se coluna é NUMBER, tentar converter
                    if col_name in TABLE_NUMBER_COLUMNS.get(table_name, set()):
                        try:
                            return float(v.replace(",", "."))
                        except ValueError:
                            logger.error(
                                f"{table_name} | {col_name} | Valor numérico inválido: '{value}'"
                            )
                            return None

                    return v

                # Números reais
                if col_name in TABLE_NUMBER_COLUMNS.get(table_name, set()):
                    try:
                        return float(value)
                    except Exception:
                        logger.error(
                            f"{table_name} | {col_name} | Valor numérico inválido: {value}"
                        )
                        return None

                return value

            except Exception as e:
                logger.error(
                    f"{table_name} | {col_name} | Erro no valor '{value}': {e}"
                )
                return None

        # ==========================
        # MONTAGEM DO BATCH
        # ==========================
        batch = []

        for row_idx, row in df.iterrows():
            clean_row = []

            for i, col in enumerate(columns):
                clean_row.append(clean_value(row[col], col))

            if len(clean_row) != expected_cols:
                raise ValueError(
                    f"{table_name} | Quantidade de colunas inválida: "
                    f"{len(clean_row)} (esperado {expected_cols})"
                )

            batch.append(tuple(clean_row))

            # ==========================
            # EXECUTA BATCH
            # ==========================
            if len(batch) >= batch_size:
                try:
                    cursor.executemany(insert_sql, batch)
                    inserted_rows += len(batch)
                    batch.clear()

                except Exception as e:
                    logger.critical(
                        f"Falha no executemany para {table_name}: {e}"
                    )
                    logger.error("Amostra de dados do erro: %s", batch[0])
                    raise

        # ==========================
        # ÚLTIMO BATCH
        # ==========================
        if batch:
            try:
                cursor.executemany(insert_sql, batch)
                inserted_rows += len(batch)

            except Exception as e:
                logger.critical(
                    f"Falha no executemany para {table_name}: {e}"
                )
                logger.error("Amostra de dados do erro: %s", batch[0])
                raise

        logger.info(
            f"{table_name} | Inseridos {inserted_rows} registros com sucesso"
        )

        return inserted_rows
    
    def read_views_to_dataframes(self) -> Dict[str, pd.DataFrame]:
        """
        Lê dados das VIEWs do Oracle para enviar à OrionTax
        
        ✅ SEM filtro de CNPJ - pega todos os registros
        
        Returns:
            Dict com 4 DataFrames das VIEWs
        """
        try:
            if not self.connection:
                self.connect()
            
            self.logger.info("Lendo VIEWs Oracle (todos os registros)...")
            
            # 1. ICMS ENTRADA
            self.logger.info("Lendo MXF_VW_ICMS_ENTRADA...")
            df_icms_entrada = pd.read_sql("""
                SELECT * FROM MXF_VW_ICMS_ENTRADA
            """, self.connection)
            self.logger.info(f"✓ ICMS Entrada: {len(df_icms_entrada)} registros")
            
            # 2. ICMS SAÍDA
            self.logger.info("Lendo MXF_VW_ICMS...")
            df_icms_saida = pd.read_sql("""
                SELECT * FROM MXF_VW_ICMS
            """, self.connection)
            self.logger.info(f"✓ ICMS Saída: {len(df_icms_saida)} registros")
            
            # 3. PIS/COFINS
            self.logger.info("Lendo MXF_VW_PIS_COFINS...")
            df_pis_cofins = pd.read_sql("""
                SELECT * FROM MXF_VW_PIS_COFINS
            """, self.connection)
            self.logger.info(f"✓ PIS/COFINS: {len(df_pis_cofins)} registros")
            
            # 4. CBS/IBS
            self.logger.info("Lendo MXF_VW_CBS_IBS...")
            df_cbs_ibs = pd.read_sql("""
                SELECT * FROM MXF_VW_CBS_IBS
            """, self.connection)
            self.logger.info(f"✓ CBS/IBS: {len(df_cbs_ibs)} registros")
            
            return {
                'icms_entrada': df_icms_entrada,
                'icms_saida': df_icms_saida,
                'pis_cofins': df_pis_cofins,
                'cbs_ibs': df_cbs_ibs
            }
            
        except Exception as e:
            self.logger.error(f"Erro ao ler VIEWs: {e}")
            raise
    
    def write_dataframes_to_tmp_tables(
        self,
        dataframes: Dict[str, pd.DataFrame]
    ) -> Tuple[bool, str]:
        """
        Grava DataFrames nas tabelas TMP do Oracle (dados vindos da OrionTax)

        ✅ SEM CNPJ - limpa tudo e insere tudo
        ✅ Usa oracledb + executemany
        ✅ Ignora colunas que não existem no Oracle
        ✅ Commit único (melhor performance)

        Args:
            dataframes: Dict com DataFrames:
                - icms_entrada
                - icms_saida
                - pis_cofins
                - cbs_ibs

        Returns:
            Tuple (sucesso, mensagem)
        """
        try:
            if not self.connection:
                self.connect()

            cursor = self.connection.cursor()
            total_inserted = 0

            # -------------------------------------------------
            # 1. Limpar tabelas TMP
            # -------------------------------------------------
            self.logger.info("Limpando tabelas TMP do Oracle...")

            cursor.execute("DELETE FROM MXF_TMP_ICMS_ENTRADA")
            cursor.execute("DELETE FROM MXF_TMP_ICMS_SAIDA")
            cursor.execute("DELETE FROM MXF_TMP_PIS_COFINS")
            cursor.execute("DELETE FROM MXF_TMP_CBS_IBS")

            self.logger.info("✓ Tabelas TMP limpas")

            # -------------------------------------------------
            # 2. Mapeamento dataframe -> tabela
            # -------------------------------------------------
            table_map = {
                "icms_entrada": "MXF_TMP_ICMS_ENTRADA",
                "icms_saida": "MXF_TMP_ICMS_SAIDA",
                "pis_cofins": "MXF_TMP_PIS_COFINS",
                "cbs_ibs": "MXF_TMP_CBS_IBS",
            }

            # -------------------------------------------------
            # 3. Inserções
            # -------------------------------------------------
            for df_key, table_name in table_map.items():

                if df_key not in dataframes:
                    continue

                df = dataframes[df_key]

                if df.empty:
                    continue
                
                if table_name == 'MXF_TMP_ICMS_ENTRADA':
                    continue
                else:
                    self.logger.info(
                        f"Inserindo {len(df)} registros em {table_name}..."
                    )

                    df = self._normalize_dataframe_for_oracle(df)
                    
                    
                    inserted = self._insert_dataframe_oracle(
                        df=df, 
                        table_name=table_name, 
                        cursor=cursor,
                        batch_size=5000
                    )

                    total_inserted += inserted

                    self.logger.info(
                        f"✓ {inserted} registros inseridos em {table_name}"
                    )

            # -------------------------------------------------
            # 4. Commit final
            # -------------------------------------------------
            self.connection.commit()
            cursor.close()

            message = f"✓ {total_inserted} registros inseridos no Oracle!"
            self.logger.info(message)

            return True, message

        except Exception as e:
            self.logger.error("Erro ao inserir dados no Oracle", exc_info=True)
            if self.connection:
                self.connection.rollback()
            raise
    
    
    def write_dataframes_to_tmp_tables_old_version(self, dataframes: Dict[str, pd.DataFrame]) -> Tuple[bool, str]:
        """
        Grava DataFrames nas tabelas TMP do Oracle (dados vindos da OrionTax)
        
        ✅ SEM CNPJ - limpa tudo e insere tudo
        
        Args:
            dataframes: Dict com 4 DataFrames do PostgreSQL
            
        Returns:
            Tuple (sucesso, mensagem)
        """
        try:
            if not self.connection:
                self.connect()
            
            cursor = self.connection.cursor()
            
            # 1. Limpar tabelas TMP (TUDO, sem filtro de CNPJ)
            self.logger.info("Limpando tabelas TMP do Oracle...")
            cursor.execute("DELETE FROM MXF_TMP_ICMS_ENTRADA")
            cursor.execute("DELETE FROM MXF_TMP_ICMS_SAIDA")
            cursor.execute("DELETE FROM MXF_TMP_PIS_COFINS")
            cursor.execute("DELETE FROM MXF_TMP_CBS_IBS")
            self.connection.commit()
            self.logger.info("✓ Tabelas TMP limpas")
            
            total_inserted = 0
            
            # 2. Inserir ICMS ENTRADA
            if 'icms_entrada' in dataframes and not dataframes['icms_entrada'].empty:
                df = dataframes['icms_entrada']
                self.logger.info(f"Inserindo {len(df)} registros em MXF_TMP_ICMS_ENTRADA...")
                
                df.to_sql(
                    'MXF_TMP_ICMS_ENTRADA',
                    self.connection,
                    if_exists='append',
                    index=False,
                    method='multi',
                    chunksize=1000
                )
                total_inserted += len(df)
                self.logger.info(f"✓ {len(df)} registros inseridos")
            
            # 3. Inserir ICMS SAÍDA
            if 'icms_saida' in dataframes and not dataframes['icms_saida'].empty:
                df = dataframes['icms_saida']
                self.logger.info(f"Inserindo {len(df)} registros em MXF_TMP_ICMS_SAIDA...")
                
                df.to_sql(
                    'MXF_TMP_ICMS_SAIDA',
                    self.connection,
                    if_exists='append',
                    index=False,
                    method='multi',
                    chunksize=1000
                )
                total_inserted += len(df)
                self.logger.info(f"✓ {len(df)} registros inseridos")
            
            # 4. Inserir PIS/COFINS
            if 'pis_cofins' in dataframes and not dataframes['pis_cofins'].empty:
                df = dataframes['pis_cofins']
                self.logger.info(f"Inserindo {len(df)} registros em MXF_TMP_PIS_COFINS...")
                
                df.to_sql(
                    'MXF_TMP_PIS_COFINS',
                    self.connection,
                    if_exists='append',
                    index=False,
                    method='multi',
                    chunksize=1000
                )
                total_inserted += len(df)
                self.logger.info(f"✓ {len(df)} registros inseridos")
            
            # 5. Inserir CBS/IBS
            if 'cbs_ibs' in dataframes and not dataframes['cbs_ibs'].empty:
                df = dataframes['cbs_ibs']
                self.logger.info(f"Inserindo {len(df)} registros em MXF_TMP_CBS_IBS...")
                
                df.to_sql(
                    'MXF_TMP_CBS_IBS',
                    self.connection,
                    if_exists='append',
                    index=False,
                    method='multi',
                    chunksize=1000
                )
                total_inserted += len(df)
                self.logger.info(f"✓ {len(df)} registros inseridos")
            
            cursor.close()
            
            message = f"✓ {total_inserted} registros inseridos no Oracle!"
            self.logger.info(message)
            
            return True, message
            
        except Exception as e:
            self.logger.error(f"Erro ao inserir dados no Oracle: {e}")
            if self.connection:
                self.connection.rollback()
            raise
    
    def __enter__(self):
        """Context manager entry"""
        self.connect()
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        """Context manager exit"""
        self.disconnect()