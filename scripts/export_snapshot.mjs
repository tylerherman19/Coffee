import { writeFile, readFile } from 'node:fs/promises';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const url = process.env.NEXT_PUBLIC_SUPABASE_URL || 'https://fptyiklgiagjegufexvq.supabase.co';
const key = process.env.NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY || 'sb_publishable_I4PlipLTVnuRS3DRmUyWzA_rB5rp0qJ';
async function table(tableName, params) {
  const rows = [];
  for (let offset = 0; ; offset += 1000) {
    let page;
    for (let attempt = 0; attempt < 3; attempt++) {
      try {
        const response = await fetch(`${url}/rest/v1/${tableName}?${new URLSearchParams({...params, order: 'id.asc', limit: '1000', offset: String(offset)})}`, {signal: AbortSignal.timeout(30000), headers: {apikey: key, 'Accept-Profile': 'coffee'}});
        if (!response.ok) throw new Error(`${tableName}: HTTP ${response.status}`);
        page = await response.json();
        if (!Array.isArray(page)) throw new Error('Invalid public data response');
        break;
      } catch (error) { if (attempt === 2) throw error; }
    }
    rows.push(...page);
    if (page.length < 1000) return rows;
  }
}
const [rawShops, rawItems, districts, neighborhoods] = await Promise.all([
  table('shops', {select:'id,name,metro,address,neighborhood,lat,lng,website,platform,opening_hours', closed_at:'is.null'}),
  table('items', {select:'id,shop_id,name,category,is_drink,drink_type,size_label,size_oz,size_confidence,current_price_cents,last_checked_at', removed_at:'is.null'}),
  readFile(path.join(root, 'public/subdistricts.json'), 'utf8').then(JSON.parse),
  readFile(path.join(root, 'data/neighborhoods.json'), 'utf8').then(JSON.parse),
]);
if (!rawShops.length || !rawItems.length) throw new Error('Refusing to publish an empty saved index');
const hoodById = new Map(neighborhoods.updates.map(row => [row.id, row.neighborhood]));
const shops = rawShops.map(shop => ({...shop, website: shop.website ? (/^https?:\/\//.test(shop.website) ? shop.website : `https://${shop.website}`) : null, neighborhood: shop.neighborhood || hoodById.get(shop.id) || null, subdistrict: districts.subdistricts[String(shop.id)] || null, rating: null, review_count: null}));
const ids = new Set(shops.map(shop => shop.id));
const items = rawItems.filter(item => ids.has(item.shop_id));
const loadedAt = items.reduce((latest, item) => item.last_checked_at && (!latest || item.last_checked_at > latest) ? item.last_checked_at : latest, null);
const snapshot = {shops, items, loadedAt, snapshotAt: new Date().toISOString()};
await writeFile(path.join(root, 'public/coffee-snapshot.json'), JSON.stringify(snapshot));
console.log(`Saved public index: ${shops.length} shops, ${items.length} menu rows`);
