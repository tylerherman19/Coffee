"""Regression tests for menu persistence, curated sources and discovery outages."""
from pathlib import Path
import unittest
from unittest.mock import patch
import collect

class FakeDB:
    def __init__(self, items=None):
        self.items = items or []
        self.calls = []
    def get(self, table, params=None):
        self.calls.append(('get', table, params))
        return self.items if table == 'items' else []
    def patch(self, table, query, values):
        self.calls.append(('patch', table, query, values))
    def post(self, table, rows):
        self.calls.append(('post', table, rows))
        rows = rows if isinstance(rows, list) else [rows]
        return [{**row, 'id': index + 1} for index, row in enumerate(rows)]

class CollectorTests(unittest.TestCase):
    def test_blue_hour_actual_menu(self):
        menu = collect.extract_blue_hour((Path(__file__).parent / 'fixtures/bluehour.html').read_text())
        self.assertEqual(len(menu), 28)
        rows = {item.name: item for item in menu}
        self.assertEqual(rows['Latte'].price_cents, 600)
        self.assertEqual(rows['Espresso 2 oz'].price_cents, 400)
        self.assertEqual(rows['Blue Hour Latte Iced 16oz'].price_cents, 800)
        self.assertNotIn('Maple Pecan Cold Brew Hot 12oz', rows)
        self.assertFalse(any('Extra Shot' in item.name for item in menu))
        self.assertEqual(len({item.platform_id for item in menu}), len(menu))
        with self.assertRaises(RuntimeError): collect.extract_blue_hour('<main>Temporarily unavailable</main>')
    def test_blocked_directory_stops_after_one_request(self):
        import menu_sources, requests
        response = requests.Response(); response.status_code = 403
        with patch.object(menu_sources, 'toast_query', side_effect=requests.HTTPError(response=response)) as query:
            self.assertEqual(menu_sources.toast_directory('milwaukee'), [])
            self.assertEqual(query.call_count, 1)
    def test_platform_failure_uses_published_website_menu(self):
        import menu_sources
        shop = {'id': 7, 'name': 'Cafe', 'website': 'https://cafe.example', 'metro': 'milwaukee'}
        menu = [collect.MenuItem('latte', 'Latte', None, 600)]
        with patch.object(collect, 'resolve_source', return_value=('toast', 'https://order.toasttab.com/online/cafe', None)), \
             patch.object(menu_sources, 'extract', side_effect=RuntimeError('platform unavailable')), \
             patch.object(collect, 'extract_site_menu', return_value=menu), patch.object(collect, 'get', side_effect=RuntimeError('no rating')):
            result = collect.collect_source(shop)
            self.assertEqual(result[2], shop['website'])
            self.assertEqual(result[3], menu)
    def test_no_menu_preserves_prior_prices(self):
        db = FakeDB([{'id': 1, 'platform_item_id': 'old'}])
        collect.save_menu(db, {'id': 7}, None, None, [], (None, None))
        self.assertFalse(any(call[1] == 'items' for call in db.calls))
        self.assertEqual(db.calls[-1][-1]['scrape_status'], 'unsupported')
    def test_unchanged_menu_is_batched_and_checked(self):
        entry = collect.MenuItem('latte', 'Latte', None, 600)
        base = {'platform_item_id': 'latte', 'name': 'Latte', 'category': None, 'is_drink': True,
                'drink_type': 'latte', 'size_label': None, 'size_oz': None, 'size_confidence': 'none',
                'removed_at': None, 'current_price_cents': 600}
        db = FakeDB([{**base, 'id': 10}])
        collect.save_menu(db, {'id': 7}, None, 'https://bluehourcoffee.com/menu', [entry, entry], (None, None))
        self.assertFalse(any(call[0] == 'post' for call in db.calls))
        checks = [call for call in db.calls if call[0] == 'patch' and call[1] == 'items']
        self.assertEqual(len(checks), 1)
        self.assertIn('last_checked_at', checks[0][-1])
        self.assertEqual(db.calls[-1][-1]['scrape_status'], 'collected')
    def test_failed_write_does_not_publish_success(self):
        db = FakeDB()
        with patch.object(db, 'post', side_effect=RuntimeError('write failure')):
            with self.assertRaises(RuntimeError):
                collect.save_menu(db, {'id': 7}, None, 'https://example.org/menu', [collect.MenuItem('latte', 'Latte', None, 600)], (None, None))
        self.assertFalse(any(call[1] == 'shops' for call in db.calls))
    def test_discovery_outage_still_refreshes_known_shops(self):
        shop = {'id': 7, 'name': 'Known Cafe', 'website': 'https://example.org'}
        with patch.object(collect, 'Supabase'), patch.object(collect, 'sync_verified_shops', return_value=[7]), \
             patch.object(collect, 'discover', side_effect=RuntimeError('Overpass outage')), \
             patch.object(collect, 'sync_shops', return_value=[shop]) as sync, \
             patch.object(collect, 'collect_source', return_value=(shop, None, 'https://example.org', [collect.MenuItem('latte', 'Latte', None, 600)], (None, None))), \
             patch.object(collect, 'save_menu') as save, patch.dict(collect.os.environ, {'VERIFIED_ONLY': '', 'MISSING_ONLY': ''}):
            collect.main()
            self.assertEqual(sync.call_args.args[1], [])
            save.assert_called_once()

if __name__ == '__main__': unittest.main()
