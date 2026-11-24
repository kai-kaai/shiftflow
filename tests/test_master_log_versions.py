import importlib.util
import json
import os
from pathlib import Path
import sqlite3
import tempfile
import unittest


class MasterLogVersionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory()
        cls.db_path = str(Path(cls.temp.name) / 'shiftflow.db')
        # Start with a real legacy schema to exercise the migration.
        with sqlite3.connect(cls.db_path) as conn:
            conn.execute('''CREATE TABLE team_month_queues (
                id INTEGER PRIMARY KEY AUTOINCREMENT, team_id TEXT NOT NULL,
                year_month TEXT NOT NULL, columns_json TEXT DEFAULT '[]',
                roster_json TEXT, updated_at TEXT, UNIQUE(team_id, year_month))''')
            columns = [
                {'date': '2026-11-01', 'shift_type': 'M8/A14', 'queue': ['AA'], 'supervisor': 'MM'},
                {'date': '2026-11-02', 'shift_type': 'A+N', 'queue': ['BB'], 'supervisor': 'NN'},
            ]
            conn.execute('INSERT INTO team_month_queues (team_id, year_month, columns_json, roster_json) VALUES (?, ?, ?, ?)',
                         ('purple', '2026-11', json.dumps(columns), json.dumps(cls.roster(13))))
        previous = os.environ.get('SHIFTFLOW_DB_PATH')
        os.environ['SHIFTFLOW_DB_PATH'] = cls.db_path
        try:
            spec = importlib.util.spec_from_file_location('shiftflow_test_app', Path(__file__).resolve().parents[1] / 'app.py')
            cls.module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(cls.module)
        finally:
            if previous is None:
                os.environ.pop('SHIFTFLOW_DB_PATH', None)
            else:
                os.environ['SHIFTFLOW_DB_PATH'] = previous
        cls.client = cls.module.app.test_client()

    @classmethod
    def tearDownClass(cls):
        cls.temp.cleanup()

    @staticmethod
    def roster(count, prefix='E'):
        return [{'initials': f'{prefix}{i}', 'working': True} for i in range(count)]

    def plan(self, group, month='2026-11', team='green'):
        response = self.client.get('/api/team-month-queues', query_string={
            'team_id': team, 'year_month': month, 'shift_type': group})
        self.assertEqual(response.status_code, 200)
        return response.json

    def save(self, group, count, month='2026-11', team='green', prefix='E'):
        return self.client.put('/api/team-month-queues', json={
            'team_id': team, 'year_month': month, 'shift_type': group,
            'columns': [{'date': f'{month}-03', 'shift_type': group, 'queue': [prefix], 'supervisor': prefix}],
            'roster': self.roster(count, prefix)})

    def test_template_boundary_and_new_assignments(self):
        for kind in ('M8/A14', 'A+N'):
            old = self.module.get_log_layout(kind, '2026-10-31')
            new = self.module.get_log_layout(kind, '2026-11-01')
            future = self.module.get_log_layout(kind, '2027-01-01')
            self.assertNotIn('FDO3', [r['slot_id'] for r in old['rows']])
            self.assertIn('FDO3', [r['slot_id'] for r in new['rows']])
            self.assertEqual(new, future)
            selections = {'AA': 'FDO3', 'BB': 'A6' if kind == 'A+N' else '1/2'}
            rows = self.module.build_hourly_log_rows(new, kind == 'M8/A14', selections)
            by_id = {r['slot_id']: r for r in rows}
            self.assertEqual(by_id['FDO3']['employee'], 'AA')
            if kind == 'A+N':
                self.assertEqual(by_id['A6']['employee'], 'BB')
                self.assertEqual(by_id['A1']['cells'][0]['value'], 'GNN')
                self.assertEqual(by_id['A6']['cells'][5]['value'], 'GND')
                self.assertEqual(by_id['N4']['cells'][8]['value'], 'CDC+GMC')
                self.assertEqual(by_id['N3']['cells'][7]['value'], 'GMC')
            else:
                self.assertEqual(by_id['1']['employee'], 'BB')
                self.assertEqual(by_id['2']['employee'], 'BB')
                self.assertEqual(by_id['FDO3']['cells'][0]['value'], 'FDO')
                self.assertFalse(any('GMC+F2' in c['value'] for r in rows for c in r['cells']))

    def test_queue_groups_are_independent_and_enforce_limits(self):
        self.assertEqual(self.save('M8/A14', 13, prefix='M').status_code, 200)
        self.assertEqual(self.save('A+N', 14, prefix='N').status_code, 200)
        morning = self.plan('M8/A14')
        night = self.plan('A+N')
        self.assertEqual(morning['working_limit'], 13)
        self.assertEqual(night['working_limit'], 14)
        self.assertEqual(len(morning['roster']), 13)
        self.assertEqual(len(night['roster']), 14)
        self.assertEqual(morning['columns'][0]['supervisor'], 'M')
        self.assertEqual(night['columns'][0]['supervisor'], 'N')
        self.assertEqual(self.save('M8/A14', 14).status_code, 400)
        self.assertEqual(self.save('A+N', 15).status_code, 400)
        self.assertEqual(self.plan('M8/A14')['roster'], morning['roster'])
        self.assertEqual(self.plan('A+N', '2026-12')['roster'], night['roster'])
        self.assertEqual(self.plan('M8/A14', '2026-12')['roster'], morning['roster'])

    def test_december_extra_workers_persist_and_carry_forward(self):
        for group in ('M8/A14', 'A+N'):
            for count in (14, 15, 16):
                with self.subTest(group=group, count=count):
                    response = self.save(group, count, month='2026-12', team='extra')
                    self.assertEqual(response.status_code, 200)
                    self.assertEqual(len(response.json['roster']), count)
                    self.assertEqual(len(self.plan(group, '2026-12', 'extra')['roster']), count)
                    self.assertEqual(len(self.plan(group, '2027-01', 'extra')['roster']), count)
        self.assertEqual(self.save('M8/A14', 14, month='2026-11').status_code, 400)
        self.assertEqual(self.save('A+N', 15, month='2026-11').status_code, 400)

    def test_afternoon_reference_and_night_fdo_hours(self):
        response = self.client.get('/api/templates/A_N/hourly-log?date=2026-11-01')
        self.assertEqual(response.status_code, 200)
        rows = {row['slot_id']: row for row in response.json['rows']}
        # Reference image: afternoon duties from 1200 to 1800 UTC.
        expected = [
            ['GNN', 'CDC+GMC', 'LCL', '', '', ''],
            ['GMC', 'LCL', 'GND', '', '', ''],
            ['', 'GND', 'CDC+GMC', 'GND', '', ''],
            ['', '', '', 'CDC', 'LCL', 'CDC+GMC'],
            ['', '', '', 'GMC', 'GND', 'LCL'],
            ['', '', '', 'LCL', 'CDC+GMC', 'GND'],
        ]
        for number, values in enumerate(expected, 1):
            cells = rows[f'A{number}']['cells']
            self.assertEqual([cell['value'] for cell in cells[:6]], values)
            for cell in cells[:6]:
                self.assertEqual(cell['bg_color'], '#EA9999' if cell['value'] else '#F4CCCC')
            self.assertTrue(all(not cell['value'] for cell in cells[6:]))
        expected_fdo_hours = {
            'FDO1': ['1700-1800', '1800-1900', '2300-0000', '0000-0100'],
            'FDO2': ['1700-1800', '1800-1900', '1900-2000', '2000-2100'],
            'FDO3': ['2100-2200', '2200-2300', '2300-0000', '0000-0100'],
        }
        for slot, hours in expected_fdo_hours.items():
            cells = rows[slot]['cells']
            self.assertEqual([hour for hour, cell in zip(response.json['hours'], cells) if cell['value']], hours)
            self.assertTrue(all(cell['bg_color'] == '#999999' for cell in cells if cell['value']))
        self.assertEqual([cell['bg_color'] for cell in rows['FDO1']['cells'][3:5]], ['#CCCCCC'] * 2)
        self.assertEqual(rows['N4']['cells'][8]['value'], 'CDC+GMC')
        self.assertEqual(rows['FDO A']['cells'][1]['value'], 'FDO')

    def test_fdo_reference_labels_hours_and_employee_mapping(self):
        morning = self.module.get_log_layout('M8/A14', '2026-11-01')
        morning_rows = {row['slot_id']: row for row in morning['rows']}
        expected_morning = {
            'FDO1': ('M1', ['0100-0200', '0200-0300', '0400-0500', '0500-0600', '0700-0800', '0800-0900', '1000-1100', '1100-1200']),
            'FDO2': ('M2', ['0200-0300', '0300-0400', '0500-0600', '0600-0700', '0800-0900', '0900-1000', '1100-1200', '1200-1300']),
            'FDO3': ('M3', ['0100-0200', '0300-0400', '0400-0500', '0600-0700', '0700-0800', '0900-1000', '1000-1100', '1200-1300']),
        }
        for slot, (label, hours) in expected_morning.items():
            row = morning_rows[slot]
            self.assertEqual(row['slot'], label)
            self.assertEqual([hour for hour, cell in zip(morning['hours'], row['cells']) if cell['value']], hours)
            self.assertTrue(all(cell['value'] in ('', 'FDO') for cell in row['cells']))
            self.assertTrue(all(cell['bg_color'] == ('#BFE0CE' if cell['value'] else '#FFFFFF') for cell in row['cells']))
        rows = self.module.build_hourly_log_rows(morning, True, {'AA': 'FDO M1', 'BB': 'M1'})
        by_id = {row['slot_id']: row for row in rows}
        self.assertEqual(by_id['FDO1']['employee'], 'AA')
        self.assertEqual(by_id['1']['employee'], 'BB')

        layout = self.module.get_log_layout('A+N', '2026-11-01')
        fdo_rows = [row for row in layout['rows'] if row['slot_id'].startswith('FDO')]
        self.assertEqual([row['slot'] for row in fdo_rows], ['N1', 'N2', 'N3', 'N4', 'N5'])
        self.assertEqual([row['section'] for row in fdo_rows], ['afternoon', 'afternoon', 'night', 'night', 'night'])
        for row in fdo_rows[:2]:
            self.assertEqual([hour for hour, cell in zip(layout['hours'], row['cells']) if cell['value']],
                             ['1300-1400', '1400-1500', '1500-1600', '1600-1700'])
        self.assertTrue(all(row['slot_bg'] == row['employee_bg'] == '#999999' for row in fdo_rows))
        self.assertTrue(all(cell['bg_color'] == ('#999999' if cell['value'] else '#CCCCCC')
                            for row in fdo_rows for cell in row['cells']))
        afternoon_rows = [row for row in layout['rows']
                          if row.get('section') == 'afternoon' or row['slot_id'].startswith('A')]
        self.assertEqual(afternoon_rows[-1]['slot'], 'N2')
        self.assertEqual(afternoon_rows[-1]['slot_id'], 'FDO A2')
        for selections in ({'AA': 'FDO N1', 'BB': 'FDO N2', 'CC': 'N1'},
                           {'AA': 'FDOA', 'BB': 'FDOA2', 'CC': 'N1'}):
            rows = self.module.build_hourly_log_rows(layout, False, selections)
            by_id = {row['slot_id']: row for row in rows}
            self.assertEqual(by_id['FDO A']['employee'], 'AA')
            self.assertEqual(by_id['FDO A2']['employee'], 'BB')
            self.assertEqual(by_id['N1']['employee'], 'CC')

    def test_migration_and_legacy_fallback_preserve_both_groups(self):
        self.module.init_db()  # migration is safe to run more than once
        morning = self.plan('M8/A14', team='purple')
        night = self.plan('A+N', team='purple')
        self.assertEqual([c['shift_type'] for c in morning['columns']], ['M8/A14'])
        self.assertEqual([c['shift_type'] for c in night['columns']], ['A+N'])
        self.assertEqual(len(night['roster']), 13)
        self.assertEqual(self.save('A+N', 14, team='purple').status_code, 200)
        self.assertEqual(self.plan('M8/A14', team='purple'), morning)

    def test_recovers_interrupted_legacy_migration(self):
        with self.module.get_db() as conn:
            conn.execute("CREATE TABLE team_month_queues_legacy AS SELECT * FROM team_month_queues WHERE 0")
            conn.execute("""INSERT INTO team_month_queues_legacy
                (team_id, year_month, columns_json, roster_json) VALUES (?, ?, ?, ?)""",
                ('recovery', '2026-10', '[]', json.dumps(self.roster(13))))
        self.module.init_db()
        plan = self.plan('A+N', '2026-10', 'recovery')
        self.assertEqual(len(plan['roster']), 13)
        with self.module.get_db() as conn:
            self.assertIsNone(conn.execute("SELECT name FROM sqlite_master WHERE name = 'team_month_queues_legacy'").fetchone())

    def test_pre_november_combined_plan_remains_shared(self):
        self.assertEqual(self.save('A+N', 14, month='2026-10', team='gray').status_code, 400)
        self.assertEqual(self.save('A+N', 13, month='2026-10', team='gray').status_code, 200)
        self.assertEqual(self.plan('A+N', '2026-10', 'gray'), self.plan('M8/A14', '2026-10', 'gray'))
        for group in ('M8/A14', 'A+N'):
            plan = self.plan(group, team='gray')
            self.assertEqual(plan['roster_copied_from'], '2026-10')
            self.assertEqual(len(plan['roster']), 13)

    def test_master_edits_and_new_shifts_use_the_correct_version(self):
        morning_url = '/api/templates/M8_A14/hourly-log'
        self.assertEqual(self.client.get(morning_url + '?date=2026-10-31').json['display_hour_count'], 12)
        self.assertEqual(self.client.get(morning_url + '?date=2026-11-01').json['display_hour_count'], 14)
        url = '/api/templates/A_N/hourly-log'
        change = {'custom_log': [{'slot': 'A1', 'cells': [{'value': 'NEW'}]}], 'password': 'admin'}
        self.assertEqual(self.client.post(url + '?date=2026-11-01', json=change).status_code, 200)
        self.assertNotEqual(self.client.get(url + '?date=2026-10-31').json['rows'][0]['cells'][0]['value'], 'NEW')
        for date_str in ('2026-10-31', '2026-11-01'):
            response = self.client.post('/api/shifts', json={'date': date_str, 'shift_type': 'A+N', 'queue': ['AA']})
            self.assertEqual(response.status_code, 200)
            with self.module.get_db() as conn:
                shift = conn.execute('SELECT * FROM shifts WHERE date = ?', (date_str,)).fetchone()
            result = self.client.get(f"/api/shifts/{shift['id']}/hourly-log")
            self.assertEqual(result.status_code, 200)
            ids = [r['slot_id'] for r in result.json['rows']]
            self.assertEqual('A6' in ids, date_str >= '2026-11-01')
            self.assertEqual(result.json['rows'][0]['cells'][0]['value'] == 'NEW', date_str >= '2026-11-01')


if __name__ == '__main__':
    unittest.main()
