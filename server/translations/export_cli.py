"""Export reviewed translations without changing an active database or Git."""

import argparse
from pathlib import Path
import sqlite3

from server.persistence.database import Database
from server.translations.catalog import Catalog, ROOT
from server.translations.exporter import export_bundle, snapshot
from server.translations.service import TranslationService


def main():
    parser = argparse.ArgumentParser(description='Export approved PlayAural translations for the next coordinated release.')
    parser.add_argument('--database', type=Path, required=True)
    parser.add_argument('--reviewer', required=True, help='Approved administrator or developer account')
    parser.add_argument('--output', type=Path, required=True, help='New ZIP path; existing files are never overwritten')
    parser.add_argument('--source', type=Path, default=ROOT)
    args = parser.parse_args()
    database = Database(args.database)
    database._conn = sqlite3.connect(args.database.resolve().as_uri() + '?mode=ro', uri=True)
    database._conn.row_factory = sqlite3.Row
    try:
        if database._conn.execute('PRAGMA application_id').fetchone()[0] != Database.APPLICATION_ID:
            raise ValueError('Not a PlayAural database')
        if database._conn.execute('PRAGMA user_version').fetchone()[0] != Database.CURRENT_SCHEMA_VERSION:
            raise ValueError('The database and export tool must have the same schema version')
        database._conn.execute('BEGIN')
        reviewer = database.get_user(args.reviewer)
        if reviewer is None:
            raise ValueError('Reviewer account not found')
        service = TranslationService(database, Catalog(args.source))
        data = snapshot(service, reviewer.uuid)
        database._conn.rollback()
        path = export_bundle(data, service.catalog, args.output)
        print(f'Exported {len(data["entries"])} approved translations to {path}')
    finally:
        database.close()


if __name__ == '__main__':
    main()
