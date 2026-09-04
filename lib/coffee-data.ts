export type Shop = { id: number; name: string; metro: 'milwaukee' | 'twin_cities'; address: string | null; neighborhood: string | null; lat: number | null; lng: number | null; website: string | null; platform: string | null; opening_hours: string | null; rating: number | null; review_count: number | null };
export type Item = { id: number; shop_id: number; name: string; category: string | null; is_drink: boolean; drink_type: string | null; size_label: string | null; size_oz: number | null; size_confidence: 'explicit' | 'inferred' | 'none' | null; current_price_cents: number | null; last_checked_at: string | null };
export type Modifier = { id: number; item_id: number; name: string; price_delta_cents: number; observed_at: string };
export type PriceChange = { id: number; item_id: number; changed_at: string; old_price_cents: number | null; new_price_cents: number; pct_change: number | null; change_type: string };
export type CoffeeData = { shops: Shop[]; items: Item[]; modifiers: Modifier[]; changes: PriceChange[]; loadedAt: string | null };
const url = process.env.NEXT_PUBLIC_SUPABASE_URL || 'https://fptyiklgiagjegufexvq.supabase.co';
const key = process.env.NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY || 'sb_publishable_I4PlipLTVnuRS3DRmUyWzA_rB5rp0qJ';
async function table<T>(path: string): Promise<T[]> { const response = await fetch(`${url}/rest/v1/${path}`, { headers: { apikey: key, Authorization: `Bearer ${key}`, 'Accept-Profile': 'coffee' }, cache: 'no-store' }); if (!response.ok) throw new Error(`Coffee data request failed: ${response.status}`); return response.json(); }
export async function loadCoffeeData(): Promise<CoffeeData> {
  const [shopsRaw, items, ratings, modifiers, changes] = await Promise.all([
    table<Omit<Shop, 'rating' | 'review_count'>>('shops?select=id,name,metro,address,neighborhood,lat,lng,website,platform,opening_hours&closed_at=is.null&order=name'),
    table<Item>('items?select=id,shop_id,name,category,is_drink,drink_type,size_label,size_oz,size_confidence,current_price_cents,last_checked_at&removed_at=is.null&order=name'),
    table<{ shop_id: number; rating: number | null; review_count: number | null; observed_at: string }>('ratings?select=shop_id,rating,review_count,observed_at&order=observed_at.desc'),
    table<Modifier>('modifiers?select=id,item_id,name,price_delta_cents,observed_at&order=observed_at.desc&limit=2000'),
    table<PriceChange>('price_changes?select=id,item_id,changed_at,old_price_cents,new_price_cents,pct_change,change_type&order=changed_at.desc&limit=250'),
  ]);
  const latestRating = new Map<number, { rating: number | null; review_count: number | null }>();
  for (const row of ratings) if (!latestRating.has(row.shop_id)) latestRating.set(row.shop_id, row);
  const shops = shopsRaw.map((shop) => ({ ...shop, rating: latestRating.get(shop.id)?.rating ?? null, review_count: latestRating.get(shop.id)?.review_count ?? null }));
  const loadedAt = items.reduce<string | null>((latest, item) => !item.last_checked_at ? latest : !latest || item.last_checked_at > latest ? item.last_checked_at : latest, null);
  return { shops, items, modifiers, changes, loadedAt };
}
