import test from 'node:test';
import assert from 'node:assert/strict';
import { isOpenNow } from '../lib/opening-hours.ts';
import { isPlainLatte, shopDrink, loadCoffeeData } from '../lib/coffee-data.ts';
const saturday = new Date('2026-10-10T16:00:00Z');
test('weekly hours and unsupported syntax', () => {
  assert.equal(isOpenNow('Mo-Fr 07:00-20:00; Sa-Su 08:00-20:00', saturday), true);
  assert.equal(isOpenNow('Mo-Fr 07:00-20:00; Sa-Su off', saturday), false);
  assert.equal(isOpenNow('Mo-Su 07:00-10:00,12:00-20:00', saturday), false);
  assert.equal(isOpenNow('Jun-Aug Mo-Su 07:00-20:00', saturday), null);
  assert.equal(isOpenNow('Mo-Su 07:00-20:00; PH off', saturday), null);
  assert.equal(isOpenNow(null, saturday), null);
  assert.equal(isOpenNow('24/7', saturday), true);
});
test('overnight hours belong to the preceding opening day', () => {
  assert.equal(isOpenNow('Fr 20:00-02:00', new Date('2026-10-10T06:00:00Z')), true);
  assert.equal(isOpenNow('Fr 20:00-02:00', new Date('2026-10-09T06:00:00Z')), false);
  assert.equal(isOpenNow('Fr 20:00-02:00', new Date('2026-10-10T07:00:00Z')), false);
});
test('plain latte ranking excludes specialty and non-coffee lattes', () => {
  for (const name of ['Latte', 'Iced Latte 16oz', 'Café Latte', 'Latte (12 oz)']) assert.equal(isPlainLatte({name}), true, name);
  for (const name of ['Blue Hour Latte', 'Matcha Latte', 'Vanilla Latte', 'Chai Latte', 'Flat White']) assert.equal(isPlainLatte({name}), false, name);
  const item = {is_drink: true, current_price_cents: 600, drink_type: 'latte', name: 'Latte', size_oz: 12, size_confidence: 'explicit'};
  assert.deepEqual(shopDrink([item]), {price: 600, label: 'Latte · 12oz', fallback: false});
  assert.equal(shopDrink([{...item, drink_type: 'other', name: 'Smoothie'}]).price, null);
});
test('optional ratings failure cannot take down the index; closed shops have no orphan menu rows', async () => {
  const original = globalThis.fetch;
  globalThis.fetch = async url => {
    if (String(url).includes('ratings?')) return new Response('unavailable', {status: 503});
    if (String(url).includes('shops?')) return Response.json([{id: 1, name: 'Cafe'}]);
    if (String(url).includes('items?')) return Response.json([{id: 1, shop_id: 1}, {id: 2, shop_id: 2}]);
    return Response.json({subdistricts: {}});
  };
  try { const data = await loadCoffeeData(); assert.equal(data.shops.length, 1); assert.equal(data.items.length, 1); } finally { globalThis.fetch = original; }
});
test('public data pagination includes rows past the API cap', async () => {
  const original = globalThis.fetch;
  globalThis.fetch = async (url, options) => {
    if (String(url).includes('shops?')) {
      const from = Number(options.headers.Range.split('-')[0]);
      const shops = from === 0 ? Array.from({length: 1000}, (_, i) => ({id: i + 1, name: `Cafe ${i + 1}`})) : [{id: 1001, name: 'Last Cafe'}];
      return Response.json(shops, {headers: {'content-range': `${from}-${from + shops.length - 1}/1001`}});
    }
    if (String(url).includes('items?')) return Response.json([{id: 1, shop_id: 1001}]);
    if (String(url).includes('ratings?')) return Response.json([]);
    return Response.json({subdistricts: {}});
  };
  try { const data = await loadCoffeeData(); assert.equal(data.shops.length, 1001); assert.equal(data.items[0].shop_id, 1001); } finally { globalThis.fetch = original; }
});
