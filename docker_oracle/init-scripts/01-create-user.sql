-- Conecta como SYSTEM e cria o usuário
ALTER SESSION SET CONTAINER = FREEPDB1;

-- Cria o usuário
CREATE USER intersolid IDENTIFIED BY "1nt3rs0l1d"
  DEFAULT TABLESPACE USERS
  TEMPORARY TABLESPACE TEMP
  QUOTA UNLIMITED ON USERS;

-- Concede privilégios necessários
GRANT CONNECT, RESOURCE TO intersolid;
GRANT CREATE SESSION TO intersolid;
GRANT CREATE TABLE TO intersolid;
GRANT CREATE VIEW TO intersolid;
GRANT CREATE SEQUENCE TO intersolid;

-- Mensagem de confirmação
SELECT 'Usuario intersolid criado com sucesso!' FROM DUAL;