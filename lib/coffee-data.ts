export type Shop = { id: number; name: string; metro: 'milwaukee' | 'twin_cities'; address: string | null; neighborhood: string | null; subdistrict: string | null; lat: number | null; lng: number | null; website: string | null; platform: string | null; opening_hours: string | null; rating: number | null; review_count: number | null };
// shops.platform holds the ordering platform's slug; these are its brand names.
const platformNames: Record<string, string> = { square: 'Square', toast: 'Toast', spoton: 'SpotOn', chownow: 'ChowNow' };
export const platformLabel = (platform: string) => platformNames[platform] ?? platform;
export type Item = { id: number; shop_id: number; name: string; category: string | null; is_drink: boolean; drink_type: string | null; size_label: string | null; size_oz: number | null; size_confidence: 'explicit' | 'inferred' | 'none' | null; current_price_cents: number | null; last_checked_at: string | null };
export type CoffeeData = { shops: Shop[]; items: Item[]; loadedAt: string | null };
const url = process.env.NEXT_PUBLIC_SUPABASE_URL || 'https://fptyiklgiagjegufexvq.supabase.co';
const key = process.env.NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY || 'sb_publishable_I4PlipLTVnuRS3DRmUyWzA_rB5rp0qJ';
// PostgREST caps an unbounded response at 1000 rows and says so only in the
// Content-Range header, so a plain fetch silently truncated the menu. Page
// through with Range until a short page arrives.
const PAGE_SIZE = 1000;
// A stalled request must fail loudly, not pin the loading screen: abort at
// 20s so the retry loop (and then the error state) can do its job.
const FETCH_TIMEOUT_MS = 20000;
const PARALLEL = 12;
async function fetchPage<T>(path: string, from: number): Promise<{ rows: T[]; total: number | null }> {
  // One flaky request (mobile network, edge hiccup) must not sink the whole
  // load: retry a page twice before giving up.
  let lastError: unknown = null;
  for (let attempt = 0; attempt < 3; attempt++) {
    if (attempt) await new Promise((resolve) => setTimeout(resolve, 600 * attempt));
    try {
      const response = await fetch(`${url}/rest/v1/${path}`, {
        signal: AbortSignal.timeout(FETCH_TIMEOUT_MS),
        headers: { apikey: key, Authorization: `Bearer ${key}`, 'Accept-Profile': 'coffee', 'Range-Unit': 'items', Range: `${from}-${from + PAGE_SIZE - 1}`, Prefer: 'count=exact' },
        cache: 'no-store',
      });
      if (!response.ok) throw new Error(`Coffee data request failed: ${response.status}`);
      const rows = (await response.json()) as T[];
      const range = response.headers.get('content-range') || '';
      const total = range.includes('/') && !range.endsWith('/*') ? Number(range.split('/')[1]) : null;
      return { rows, total };
    } catch (error) {
      lastError = error;
    }
  }
  throw lastError;
}
async function table<T>(path: string): Promise<T[]> {
  const first = await fetchPage<T>(path, 0);
  if (first.rows.length < PAGE_SIZE) return first.rows;
  if (first.total === null) {
    // No total advertised: fall back to sequential paging until a short page.
    const rows = [...first.rows];
    for (let from = PAGE_SIZE; ; from += PAGE_SIZE) {
      const page = await fetchPage<T>(path, from);
      rows.push(...page.rows);
      if (page.rows.length < PAGE_SIZE) return rows;
    }
  }
  const pages = Math.ceil(first.total / PAGE_SIZE);
  const rows = [...first.rows];
  for (let start = 1; start < pages; start += PARALLEL) {
    const batch = await Promise.all(
      Array.from({ length: Math.min(PARALLEL, pages - start) }, (_, i) => fetchPage<T>(path, (start + i) * PAGE_SIZE)),
    );
    for (const page of batch) rows.push(...page.rows);
  }
  return rows;
}
export async function loadCoffeeData(): Promise<CoffeeData> {
  const [shopsRaw, items, ratings] = await Promise.all([
    table<Omit<Shop, 'rating' | 'review_count'>>('shops?select=id,name,metro,address,neighborhood,lat,lng,website,platform,opening_hours&closed_at=is.null&order=name,id.asc'),
    table<Item>('items?select=id,shop_id,name,category,is_drink,drink_type,size_label,size_oz,size_confidence,current_price_cents,last_checked_at&removed_at=is.null&order=name,id.asc'),
    table<{ shop_id: number; rating: number | null; review_count: number | null; observed_at: string }>('ratings?select=shop_id,rating,review_count,observed_at&order=observed_at.desc,shop_id.asc'),
  ]);
  // Fine-grained districts inside a neighborhood (e.g. Historic Third Ward
  // inside Downtown), staged as a static file so the split ships with the
  // site - no schema change, no runtime geocoding. Fail open: no file, no split.
  let subdistricts: Record<string, string> = {};
  try {
    const response = await fetch('subdistricts.json', { cache: 'no-store', signal: AbortSignal.timeout(FETCH_TIMEOUT_MS) });
    if (response.ok) subdistricts = ((await response.json()) as { subdistricts: Record<string, string> }).subdistricts || {};
  } catch { /* no split available */ }
  const latestRating = new Map<number, { rating: number | null; review_count: number | null }>();
  for (const row of ratings) if (!latestRating.has(row.shop_id)) latestRating.set(row.shop_id, row);
  const shops = shopsRaw.map((shop) => ({ ...shop, subdistrict: subdistricts[String(shop.id)] ?? null, rating: latestRating.get(shop.id)?.rating ?? null, review_count: latestRating.get(shop.id)?.review_count ?? null }));
  const loadedAt = items.reduce<string | null>((latest, item) => !item.last_checked_at ? latest : !latest || item.last_checked_at > latest ? item.last_checked_at : latest, null);
  return { shops, items, loadedAt };
}

// Keys are the drink_type values the items table allows (see the check
// constraint in supabase/migrations). "other" is the catch-all the collector
// gives every drink it will not rank - sodas, juice, milk, blended coolers -
// so it is labelled as drinks rather than as coffee.
export const drinkLabels: Record<string, string> = { latte: 'Latte', caramel_latte: 'Caramel latte', cappuccino: 'Cappuccino', espresso: 'Espresso', americano: 'Americano', drip: 'Drip coffee', cold_brew: 'Cold brew', mocha: 'Mocha', chai: 'Chai', tea: 'Tea', other: 'Other drinks' };

const espressoFallbackOrder = ['cappuccino', 'americano', 'espresso', 'mocha', 'cold_brew'];

// Shop-level price: a regular latte, else drip, else the closest standard
// espresso drink - median size, never the smallest or largest.
export function shopDrink(menu: Item[]): { price: number | null; label: string; fallback: boolean } {
  const drinks = menu.filter((item) => item.is_drink && item.current_price_cents != null && item.current_price_cents > 0);
  if (!drinks.length) return { price: null, label: menu.length ? 'No coffee price' : 'No menu yet', fallback: false };
  const medianPick = (cands: Item[]): Item => {
    const sized = cands.filter((c) => c.size_oz != null).sort((a, b) => (a.size_oz as number) - (b.size_oz as number) || (a.current_price_cents as number) - (b.current_price_cents as number));
    const pool = sized.length ? sized : cands.slice().sort((a, b) => (a.current_price_cents as number) - (b.current_price_cents as number));
    return pool[Math.ceil((pool.length - 1) / 2)];
  };
  const named = (re: RegExp) => drinks.filter((item) => re.test(item.name));
  const latteExact = named(/^caff?[eé]?\s+latte$/i).concat(named(/^latte$/i));
  const lattePool = latteExact.length ? latteExact : drinks.filter((item) => item.drink_type === 'latte');
  if (lattePool.length) { const pick = medianPick(lattePool); return { price: pick.current_price_cents, label: 'Latte', fallback: false }; }
  const dripExact = named(/^(drip|brewed|filter|house)\b/i).concat(named(/^coffee$/i));
  const dripPool = dripExact.length ? dripExact : drinks.filter((item) => item.drink_type === 'drip');
  if (dripPool.length) { const pick = medianPick(dripPool); return { price: pick.current_price_cents, label: 'Drip', fallback: false }; }
  for (const type of espressoFallbackOrder) {
    const cands = drinks.filter((item) => item.drink_type === type);
    if (cands.length) { const pick = medianPick(cands); return { price: pick.current_price_cents, label: drinkLabels[type] || type.replaceAll('_', ' '), fallback: true }; }
  }
  const pick = medianPick(drinks);
  return { price: pick.current_price_cents, label: pick.name, fallback: true };
}
