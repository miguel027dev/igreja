#!/usr/bin/env python3
"""Migra a base SQLite legada do ITEL ELIM para o PostgreSQL configurado em DATABASE_URL."""
import argparse
import json
import os
import sqlite3
from datetime import datetime
from pathlib import Path

os.environ.setdefault("AUTO_CREATE_DB", "false")

from sqlalchemy import text
from app import app, db, User, Aula, ProgressoAula, LogAtividade, Notification, Feedback

MODELS = [User, Aula, ProgressoAula, LogAtividade, Notification, Feedback]
DATETIME_FIELDS = {
    "users": {"last_login", "created_at"},
    "aulas": {"data_criacao"},
    "progresso_aulas": {"data_conclusao"},
    "logs_atividades": {"timestamp"},
    "notifications": {"created_at"},
    "feedbacks": {"data_envio"},
}
BOOLEAN_FIELDS = {
    "users": {"is_active", "is_approved"},
    "progresso_aulas": {"concluido"},
    "notifications": {"lida"},
    "feedbacks": {"lido"},
}
JSON_FIELDS = {"aulas": {"quiz_data"}}


def convert_row(table, row):
    data = dict(row)
    for key in DATETIME_FIELDS.get(table, set()):
        value = data.get(key)
        if isinstance(value, str) and value:
            data[key] = datetime.fromisoformat(value)
    for key in BOOLEAN_FIELDS.get(table, set()):
        if data.get(key) is not None:
            data[key] = bool(data[key])
    for key in JSON_FIELDS.get(table, set()):
        value = data.get(key)
        if isinstance(value, str) and value:
            try:
                data[key] = json.loads(value)
            except json.JSONDecodeError:
                data[key] = None
    return data


def main():
    parser = argparse.ArgumentParser(description="Migra SQLite legado para PostgreSQL.")
    parser.add_argument("--source", default="migration_source/portal_elim_v9.db", help="Caminho do SQLite legado")
    parser.add_argument("--force", action="store_true", help="Apaga dados existentes no PostgreSQL antes de importar")
    args = parser.parse_args()

    source = Path(args.source).resolve()
    if not source.exists():
        raise SystemExit(f"SQLite nao encontrado: {source}")

    if not os.environ.get("DATABASE_URL", "").startswith(("postgres://", "postgresql://")):
        raise SystemExit("Defina DATABASE_URL apontando para o PostgreSQL antes de executar a migracao.")

    sqlite = sqlite3.connect(source)
    sqlite.row_factory = sqlite3.Row

    with app.app_context():
        db.create_all()

        existing = db.session.query(User.id).first()
        if existing and not args.force:
            raise SystemExit("O PostgreSQL ja possui dados. Use --force somente se quiser substituir o conteudo atual.")

        if args.force:
            for model in reversed(MODELS):
                db.session.execute(model.__table__.delete())
            db.session.commit()

        total = 0
        for model in MODELS:
            table = model.__tablename__
            rows = [convert_row(table, row) for row in sqlite.execute(f'SELECT * FROM "{table}" ORDER BY id')]
            if rows:
                db.session.execute(model.__table__.insert(), rows)
                db.session.commit()
            total += len(rows)
            print(f"{table}: {len(rows)} registro(s) migrado(s)")

        # Corrige sequencias SERIAL/IDENTITY apos inserir IDs legados explicitamente.
        for model in MODELS:
            table = model.__tablename__
            db.session.execute(text(
                f"SELECT setval(pg_get_serial_sequence('{table}', 'id'), "
                f"COALESCE((SELECT MAX(id) FROM {table}), 1), "
                f"EXISTS(SELECT 1 FROM {table}))"
            ))
        db.session.commit()

    sqlite.close()
    print(f"Migracao concluida: {total} registro(s) copiado(s) para PostgreSQL.")


if __name__ == "__main__":
    main()
