# ITEL ELIM — PostgreSQL

A aplicacao nao usa mais SQLite em runtime. O banco agora vem obrigatoriamente de `DATABASE_URL`.

## 1. Configuracao

Em producao, configure as variaveis diretamente no painel de Environment Variables/Secrets do seu provedor. Para desenvolvimento local, este pacote inclui um `.env` ignorado pelo Git. O `python-dotenv` carrega esse arquivo sem sobrescrever variaveis ja definidas pelo servidor (`override=False`). O `.env.example` continua sem segredos.

> **Importante:** a `DATABASE_URL` fornecida usa um hostname interno do Render (`dpg-...-a`). Essa URL normalmente funciona entre servicos dentro da rede privada do Render, mas nao a partir do seu computador. Para executar localmente fora do Render, substitua `DATABASE_URL` no `.env` pela **External Database URL** do mesmo banco.

- `DATABASE_URL` — URL do PostgreSQL.
- `SECRET_KEY` — chave longa e aleatoria.
- `ADMIN_EMAIL` e `ADMIN_PASSWORD` — opcionais para criar o primeiro administrador em um banco vazio.

O valor de `DATABASE_URL` e lido somente do ambiente do processo e nunca possui fallback ou credencial embutida no codigo. Formatos PostgreSQL comuns dos provedores sao normalizados automaticamente para o driver Psycopg 3.

## 2. Migrar os dados antigos

O SQLite original foi preservado somente para migracao em `migration_source/portal_elim_v9.db`.

Com `DATABASE_URL` apontando para o PostgreSQL, execute:

```bash
python scripts/migrate_sqlite_to_postgres.py
```

O script mantem IDs, usuarios, hashes de senha, aulas, progresso, notificacoes, feedbacks e logs. Se o PostgreSQL ja tiver dados, ele para por seguranca. `--force` substitui o conteudo atual e deve ser usado com cuidado.

## 3. Producao

Comando recomendado:

```bash
gunicorn app:app --workers 2 --threads 4 --timeout 120
```

Health checks:

- `/healthz` — processo Flask ativo.
- `/readyz` — processo + conexao com o banco disponivel.

## 4. Ajustes feitos

- PostgreSQL + Psycopg 3.
- Pool com `pool_pre_ping`, reciclagem e limites configuraveis.
- Indices em campos de autenticacao, papeis, aprovacoes, progresso, logs e notificacoes.
- Restricao unica para impedir progresso duplicado da mesma aula por usuario.
- Remocao do ZIP duplicado e templates legados nao usados por nenhuma rota.
- Dashboard redesenhado como ambiente educacional responsivo.
- Credenciais fixas de administrador removidas do codigo.
- Endpoint real de alunos em `/api/professor/alunos`.
