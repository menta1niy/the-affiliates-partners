import sqlite3
import unittest
from unittest.mock import Mock

from database.migrate_sqlite import validate_source_schema


class MigrationUnknownSchemaTests(unittest.TestCase):
    def setUp(self):
        self.src = sqlite3.connect(':memory:')
        self.src.execute('CREATE TABLE users (id INTEGER, legacy_extra TEXT)')
        self.dst = Mock()
        self.dst.execute.return_value = [('id',)]

    def tearDown(self):
        self.src.close()

    def test_unknown_nonempty_table_fails(self):
        self.src.execute('CREATE TABLE future_records (amount INTEGER)')
        self.src.execute('INSERT INTO future_records VALUES (42)')
        with self.assertRaisesRegex(ValueError, 'Nonempty unsupported SQLite table'):
            validate_source_schema(self.src, self.dst)

    def test_unknown_nonempty_column_fails(self):
        self.src.execute("INSERT INTO users VALUES (1, 'must preserve')")
        with self.assertRaisesRegex(ValueError, 'Unsupported SQLite columns in users'):
            validate_source_schema(self.src, self.dst)

    def test_empty_historical_tables_and_columns_are_compatible(self):
        self.src.execute('CREATE TABLE old_optional (id INTEGER)')
        validate_source_schema(self.src, self.dst)

    def test_known_column_data_is_compatible(self):
        self.src.execute('DROP TABLE users')
        self.src.execute('CREATE TABLE users (id INTEGER)')
        self.src.execute('INSERT INTO users VALUES (1)')
        validate_source_schema(self.src, self.dst)


if __name__ == '__main__':
    unittest.main()
