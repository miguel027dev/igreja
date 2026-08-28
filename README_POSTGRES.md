# ITEL ELIM — PostgreSQL

A aplicacao nao usa mais SQLite em runtime. O banco agora vem obrigatoriamente de `DATABASE_URL`.

## 1. Configuracao

Copie `.env.example` para as variaveis de ambiente do seu provedor e configure pelo menos:

- `DATABASE_URL` — URL do PostgreSQL.
- `SECRET_KEY` — chave longa e aleatoria.
- `ADMIN_EMAIL` e `ADMIN_PASSWORD` — opcionais para criar o primeiro administrador em um banco vazio.

URLs `postgres://...` e `postgresql://...` sao normalizadas automaticamente para o driver Psycopg 3.

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
