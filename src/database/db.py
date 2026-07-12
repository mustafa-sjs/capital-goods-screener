"""Database connection layer.

Local development : DuckDB file at data/capital_goods.duckdb (default).
Production        : Supabase Postgres via DATABASE_URL env var
                    (postgresql://...) — same schema, same queries.

Both paths expose the tiny common surface the platform actually uses:
execute(sql, params), executemany(sql, rows), fetchall(sql, params) -> list
of tuples, and upsert(table, cols, rows, key_cols) which renders the
dialect-correct INSERT ... ON CONFLICT ... DO UPDATE.
"""
import os

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
DUCKDB_PATH = os.path.join(ROOT, 'data', 'capital_goods.duckdb')
SCHEMA_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'schema.sql')


class DB:
    def __init__(self, url=None):
        url = url or os.environ.get('DATABASE_URL', '')
        if url.startswith('postgres'):
            import psycopg2
            self.kind = 'postgres'
            self.conn = psycopg2.connect(url)
            self.conn.autocommit = True
            self.ph = '%s'
        else:
            import duckdb
            self.kind = 'duckdb'
            self.conn = duckdb.connect(DUCKDB_PATH)
            self.ph = '?'

    def init_schema(self):
        raw = open(SCHEMA_PATH).read()
        sql = '\n'.join(l.split('--')[0] for l in raw.splitlines())
        for stmt in sql.split(';'):
            if stmt.strip():
                self.execute(stmt)

    def execute(self, sql, params=None):
        if self.kind == 'postgres':
            with self.conn.cursor() as c:
                c.execute(sql, params or ())
        else:
            self.conn.execute(sql, params or [])

    def executemany(self, sql, rows):
        if not rows:
            return
        if self.kind == 'postgres':
            # batch VALUES lists: one round trip per page instead of per row
            # (per-row executemany over a remote pooler is ~100x slower)
            import re
            from psycopg2.extras import execute_values
            m = re.match(r'(INSERT INTO .+?) VALUES \([%s, ]+\)(.*)$', sql, re.S)
            with self.conn.cursor() as c:
                if m:
                    execute_values(c, f'{m.group(1)} VALUES %s{m.group(2)}',
                                   rows, page_size=500)
                else:
                    c.executemany(sql, rows)
        else:
            self.conn.executemany(sql, rows)

    def fetchall(self, sql, params=None):
        if self.kind == 'postgres':
            with self.conn.cursor() as c:
                c.execute(sql, params or ())
                return c.fetchall()
        return self.conn.execute(sql, params or []).fetchall()

    def upsert(self, table, cols, rows, key_cols):
        """Idempotent upsert: running twice never duplicates or corrupts."""
        if not rows:
            return 0
        ph = ', '.join([self.ph] * len(cols))
        collist = ', '.join(cols)
        keylist = ', '.join(key_cols)
        setters = ', '.join(f'{c}=EXCLUDED.{c}' for c in cols if c not in key_cols)
        action = f'DO UPDATE SET {setters}' if setters else 'DO NOTHING'
        sql = (f'INSERT INTO {table} ({collist}) VALUES ({ph}) '
               f'ON CONFLICT ({keylist}) {action}')
        self.executemany(sql, rows)
        return len(rows)

    def table_counts(self):
        tables = [r[0] for r in self.fetchall(
            "SELECT table_name FROM information_schema.tables "
            "WHERE table_schema IN ('main','public') ORDER BY 1")]
        return {t: self.fetchall(f'SELECT count(*) FROM {t}')[0][0] for t in tables}

    def close(self):
        self.conn.close()


def connect(url=None):
    db = DB(url)
    db.init_schema()
    return db
