'use client';

export const dynamic = 'force-static';

import nextDynamic from 'next/dynamic';
import { useEffect, useMemo, useRef, useState } from 'react';
import { LoaderCircle } from 'lucide-react';
import { drinkLabels, isPlainLatte, loadCoffeeData, loadSnapshotData, loadMenuSource, platformLabel, shopDrink, type CoffeeData, type Item, type Shop } from '@/lib/coffee-data';

import { isOpenNow } from '@/lib/opening-hours';

const MapView = nextDynamic(() => import('@/components/coffee-map'), { ssr: false, loading: () => <div className="map-loading"><LoaderCircle aria-hidden="true" /> Loading the map…</div> });
type Metro = 'milwaukee' | 'twin_cities';
type View = 'near' | 'shops' | 'compare' | 'map';
// Chip order for the compare view. Anything the collector produces that is
// not listed here still appears, after these.
const drinkOrder = ['latte', 'caramel_latte', 'cold_brew', 'drip', 'cappuccino', 'americano', 'espresso', 'mocha', 'chai', 'tea', 'other'];
// A menu is stale after two months. Read once at module load rather than
// during render: the threshold is 60 days, so a per-render clock buys nothing
// and makes the component impure.
const RENDERED_AT = Date.now();
const STALE_AFTER_MS = 60 * 864e5;
const money = new Intl.NumberFormat('en-US', { style: 'currency', currency: 'USD' });
const formatPrice = (cents: number | null) => cents == null ? '—' : money.format(cents / 100);
const MILES_PER_KM = 0.621371;
function distanceMiles(aLat: number, aLng: number, bLat: number, bLng: number) {
  const rad = Math.PI / 180; const dLat = (bLat - aLat) * rad; const dLng = (bLng - aLng) * rad;
  const h = Math.sin(dLat / 2) ** 2 + Math.cos(aLat * rad) * Math.cos(bLat * rad) * Math.sin(dLng / 2) ** 2;
  return 2 * 6371 * Math.asin(Math.sqrt(h)) * MILES_PER_KM;
}
const METRO_CENTERS: Record<Metro, { lat: number; lng: number }> = { milwaukee: { lat: 43.0389, lng: -87.9065 }, twin_cities: { lat: 44.9778, lng: -93.265 } };
const nearestMetro = (lat: number, lng: number): Metro => distanceMiles(lat, lng, METRO_CENTERS.milwaukee.lat, METRO_CENTERS.milwaukee.lng) <= distanceMiles(lat, lng, METRO_CENTERS.twin_cities.lat, METRO_CENTERS.twin_cities.lng) ? 'milwaukee' : 'twin_cities';
const formatMiles = (miles: number) => miles < 0.1 ? `${Math.round(miles * 5280 / 100) * 100} FT` : `${miles.toFixed(1)} MI`;

const fold = (value: string) => value.normalize('NFD').replace(/\p{Diacritic}/gu, '').toLowerCase();

function neighborhood(shop: Shop) {
  if (shop.neighborhood) return shop.neighborhood;
  const parts = shop.address?.split(',').map((part) => part.trim()) ?? [];
  return parts.length > 1 ? parts[1] : 'Area unavailable';
}


function ratingStr(shop: Shop) {
  if (shop.rating == null) return null;
  return `${shop.rating.toFixed(1)}★${shop.review_count ? ` ${shop.review_count.toLocaleString()}` : ''}`;
}

function ShopRow({ shop, items, onOpen, dimmed = false }: { shop: Shop; items: Item[]; onOpen: () => void; dimmed?: boolean }) {
  const menu = items.filter((item) => item.shop_id === shop.id && item.current_price_cents != null);
  const drink = shopDrink(menu);
  const meta = [neighborhood(shop), shop.platform ? platformLabel(shop.platform).toUpperCase() : null, ratingStr(shop)].filter(Boolean).join('  ·  ');
  return <button className={dimmed ? 'shop-row dimmed' : 'shop-row'} onClick={onOpen} aria-label={shop.name}>
    <span className="shop-main"><span className="shop-name">{shop.name}</span><span className="shop-meta">{meta}</span></span>
    <span className="shop-price"><strong>{formatPrice(drink.price)}</strong><small>{drink.label}</small></span>
  </button>;
}

function ShopDetail({ shop, items, onBack }: { shop: Shop; items: Item[]; onBack: () => void }) {
  const menu = items.filter((item) => item.shop_id === shop.id);
  const [sourceUrl, setSourceUrl] = useState<string | null>(null);
  useEffect(() => { let active = true; loadMenuSource(shop.id).then(source => { if (active) setSourceUrl(source); }).catch(() => {}); return () => { active = false; }; }, [shop.id]);
  const checked = menu.reduce<string | null>((latest, item) => !item.last_checked_at ? latest : !latest || item.last_checked_at > latest ? item.last_checked_at : latest, null);
  const openNow = isOpenNow(shop.opening_hours);
  const detailMeta = [
    openNow === true ? 'OPEN NOW' : openNow === false ? 'CLOSED NOW' : null,
    ratingStr(shop), neighborhood(shop), shop.address,
    checked ? `READ ${new Intl.DateTimeFormat('en-US', { month: 'short', day: 'numeric' }).format(new Date(checked)).toUpperCase()}${RENDERED_AT - new Date(checked).getTime() > STALE_AFTER_MS ? ' · STALE' : ''}` : null,
  ].filter(Boolean) as string[];
  const groups = menu.reduce<Record<string, Item[]>>((acc, item) => { const key = item.category || (item.is_drink ? 'Coffee & drinks' : 'Food & bakery'); (acc[key] ??= []).push(item); return acc; }, {});
  const drinkPrices = menu.filter((item) => item.is_drink && item.current_price_cents != null && item.current_price_cents > 0).map((item) => item.current_price_cents as number).sort((a, b) => a - b);
  const medianDrink = drinkPrices.length ? (drinkPrices.length % 2 ? drinkPrices[drinkPrices.length >> 1] : Math.round((drinkPrices[(drinkPrices.length >> 1) - 1] + drinkPrices[drinkPrices.length >> 1]) / 2)) : null;
  const foodCount = menu.filter((item) => !item.is_drink).length;
  const detailStats = menu.length ? [
    { label: 'Cheapest drink', value: drinkPrices.length ? formatPrice(drinkPrices[0]) : '—' },
    { label: 'Median drink', value: medianDrink == null ? '—' : formatPrice(medianDrink) },
    { label: 'Drinks listed', value: String(menu.filter((item) => item.is_drink).length) },
    { label: 'Food & bakery', value: String(foodCount) },
  ] : [];
  return <main className="detail-shell">
    <button className="back-button" onClick={onBack}>← Back to results</button>
    <section className="shop-heading"><h1>{shop.name}</h1></section>
    <div className="detail-meta">{detailMeta.map((line) => <span key={line}>{line}</span>)}</div>
    <div className="detail-actions">
      {shop.website && <a className="order-link" href={shop.website} target="_blank" rel="noreferrer">Visit website</a>}
      {shop.lat != null && shop.lng != null && <a className="order-link ghost" href={`https://maps.apple.com/?q=${encodeURIComponent(`${shop.name}, ${shop.address || neighborhood(shop)}`)}`} target="_blank" rel="noreferrer">Directions</a>}
    </div>
    {detailStats.length > 0 && <div className="detail-stats">{detailStats.map((stat) => <div key={stat.label}><div className="label">{stat.label}</div><div className="value">{stat.value}</div></div>)}</div>}
    {Object.keys(groups).length === 0
      ? <div className="empty"><h2>No menu read yet</h2><p>The location is mapped. Its direct menu source hasn&apos;t been collected.</p></div>
      : Object.entries(groups).map(([group, entries]) => <section className="menu-section" key={group}>
          <h2><span>{group}</span><span className="count">{String(entries.length).padStart(2, '0')}</span></h2>
          {entries.sort((a, b) => a.name.localeCompare(b.name)).map((item) => <div className="menu-row" key={item.id}>
            <div className="menu-item"><h3>{item.name}</h3><p>{[item.size_label || (item.size_oz ? `${item.size_oz} OZ` : 'SIZE NOT LISTED'), item.size_confidence === 'inferred' ? 'EST.' : null, item.current_price_cents == null ? 'NOT LISTED' : null, item.last_checked_at ? `Checked ${new Date(item.last_checked_at).toLocaleDateString('en-US', {month: 'short', day: 'numeric', year: 'numeric'})}${RENDERED_AT - new Date(item.last_checked_at).getTime() > STALE_AFTER_MS ? ' · Stale' : ''}` : 'Date unknown'].filter(Boolean).join(' · ')}</p></div>
            <div className="menu-price"><strong>{formatPrice(item.current_price_cents)}</strong>{item.current_price_cents && item.size_oz ? <small>{item.size_confidence === 'inferred' ? '~' : ''}{money.format(item.current_price_cents / 100 / item.size_oz)}/oz</small> : null}</div>
          </div>)}
        </section>)}
    <p className="source-note">{sourceUrl && <><a href={sourceUrl} target="_blank" rel="noreferrer">View price source</a>. </>}Published menu prices before tax and add-ons. Each item retains its last verified date; menus can change.</p>
  </main>;
}

export default function Home() {
  const [data, setData] = useState<CoffeeData>({ shops: [], items: [], loadedAt: null });
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [metro, setMetro] = useState<Metro>('milwaukee');
  const [view, setView] = useState<View>('near');
  const [coords, setCoords] = useState<{ lat: number; lng: number } | null>(null);
  // `false` by default on every render pass, including the client's first
  // (pre-hydration) one - unlike a branch on `navigator.geolocation`, a plain
  // literal default can never disagree between server and client, so this
  // can't throw a hydration mismatch the way the old `geoState` enum did.
  const [geoDenied, setGeoDenied] = useState(false);
  const [geoRequested, setGeoRequested] = useState(false);
  const [size, setSize] = useState('all');
  const [plainOnly, setPlainOnly] = useState(true);
  const [includeStale, setIncludeStale] = useState(false);
  const [nearExpanded, setNearExpanded] = useState(false);
  const [, setClock] = useState(0);
  useEffect(() => { const timer = setInterval(() => setClock(value => value + 1), 60000); return () => clearInterval(timer); }, []);
  const [query, setQuery] = useState('');
  const [openOnly, setOpenOnly] = useState(false);
  const [pricedOnly, setPricedOnly] = useState(true);
  const [hood, setHood] = useState('');
  const [selectedShop, setSelectedShop] = useState<Shop | null>(null);
  const [drink, setDrink] = useState('latte');
  // "Show all" belongs to one ranking. Storing the ranking it was opened for,
  // instead of resetting a boolean from an effect, collapses the list the
  // moment the metro, drink or neighborhood changes - with no extra render.
  const [showAllKey, setShowAllKey] = useState<string | null>(null);
  const scrollRef = useRef(0);
  // A hand-tapped metro is the user's stated choice; the geolocation
  // auto-switch must never override it, even if the fix lands after the tap.
  const metroTouched = useRef(false);
  useEffect(() => {
    if (!geoRequested || coords || geoDenied) return;
    if (!('geolocation' in navigator)) return;
    let active = true;
    // First cold fix on a phone can take well over 10s; a short timeout was
    // reporting 'denied' on devices that just needed longer. Retry once on
    // a genuine timeout before falling back.
    let attempts = 0;
    const locate = () => navigator.geolocation.getCurrentPosition(
      (position) => { if (!active) return; setCoords({ lat: position.coords.latitude, lng: position.coords.longitude }); if (!metroTouched.current) setMetro(nearestMetro(position.coords.latitude, position.coords.longitude)); },
      (error) => { if (!active) return; attempts += 1; if (error.code === error.TIMEOUT && attempts < 2) locate(); else setGeoDenied(true); },
      { timeout: 30000, maximumAge: 300000, enableHighAccuracy: false },
    );
    locate();
    return () => { active = false; };
  }, [coords, geoDenied, geoRequested]);
  useEffect(() => {
    let active = true, liveLoaded = false, snapshotLoaded = false, initialized = false;
    const show = (d: CoffeeData) => {
      if (!active) return;
      setData(d); setLoading(false);
      const params = new URLSearchParams(window.location.search);
      if (!initialized) {
        initialized = true;
        const viewParam = params.get('view');
        if (viewParam === 'shops' || viewParam === 'map' || viewParam === 'compare') setView(viewParam);
        if (params.get('prices') === 'off') setPricedOnly(false);
        const ll = params.get('ll');
        if (ll) {
          const values = ll.split(','); const [lat, lng] = values.map(Number);
          if (values.length === 2 && values.every(value => value.trim()) && Number.isFinite(lat) && Number.isFinite(lng) && Math.abs(lat) <= 90 && Math.abs(lng) <= 180) {
            setCoords({lat, lng}); setMetro(nearestMetro(lat, lng));
          }
        }
      }
      const id = params.get('shop');
      const hit = id ? d.shops.find(shop => String(shop.id) === id) : undefined;
      if (hit) { setSelectedShop(hit); setMetro(hit.metro); }
    };
    const snapshot = loadSnapshotData().then(d => { snapshotLoaded = true; if (!liveLoaded) show(d); }).catch(() => {});
    loadCoffeeData().then(d => { liveLoaded = true; show(d); }).catch(async () => {
      await snapshot;
      if (active && !snapshotLoaded) { setError('The saved index and live prices are unavailable. Check your connection and retry.'); setLoading(false); }
    });
    return () => { active = false; };
  }, []);
  const openShop = (shop: Shop) => {
    scrollRef.current = window.scrollY; setSelectedShop(shop);
    const url = new URL(window.location.href); url.searchParams.set('shop', String(shop.id)); window.history.replaceState(null, '', url);
    window.scrollTo(0, 0);
  };
  const metroShops = useMemo(() => data.shops.filter((shop) => shop.metro === metro), [data.shops, metro]);
  const hoods = useMemo(() => { const counts = new Map<string, number>(); for (const shop of metroShops) if (shop.neighborhood) counts.set(shop.neighborhood, (counts.get(shop.neighborhood) || 0) + 1); return Array.from(counts.entries()).sort((a, b) => b[1] - a[1] || a[0].localeCompare(b[0])); }, [metroShops]);
  const subDistricts = useMemo(() => { const counts = new Map<string, number>(); for (const shop of metroShops) if (shop.subdistrict) counts.set(shop.subdistrict, (counts.get(shop.subdistrict) || 0) + 1); return Array.from(counts.entries()).sort((a, b) => b[1] - a[1] || a[0].localeCompare(b[0])); }, [metroShops]);
  const hoodOptions = useMemo(() => {
    const flat = hoods.filter(([name]) => name !== 'Downtown').map(([name, count]) => <option key={name} value={name}>{name} ({count})</option>);
    const downtown = hoods.find(([name]) => name === 'Downtown');
    if (!downtown && !subDistricts.length) return flat;
    const withSubs = subDistricts.length
      ? <optgroup key="dt-sub" label="Downtown districts">{subDistricts.map(([name, count]) => <option key={name} value={`sub:${name}`}>{name} ({count})</option>)}</optgroup>
      : null;
    return [...flat, downtown ? <option key="Downtown" value="Downtown">Downtown - all ({downtown[1]})</option> : null, withSubs];
  }, [hoods, subDistricts]);
  const activeHood = hoods.some(([name]) => name === hood) || (hood.startsWith('sub:') && subDistricts.some(([name]) => `sub:${name}` === hood)) ? hood : '';
  const rankingKey = `${metro}|${drink}|${activeHood}|${size}|${plainOnly}|${includeStale}|${query}|${openOnly}`;
  const showAll = showAllKey === rankingKey;
  const pricedShopIds = useMemo(() => { const set = new Set<number>(); for (const item of data.items) if (item.is_drink && item.current_price_cents != null && item.current_price_cents > 0) set.add(item.shop_id); return set; }, [data.items]);
  const visibleShops = useMemo(() => metroShops.filter((shop) => { const haystack = fold(`${shop.name} ${shop.neighborhood || ''} ${shop.address || ''}`); return haystack.includes(fold(query)) && (!openOnly || isOpenNow(shop.opening_hours) === true) && (!pricedOnly || pricedShopIds.has(shop.id)) && (!activeHood || (activeHood.startsWith('sub:') ? shop.subdistrict === activeHood.slice(4) : shop.neighborhood === activeHood)); }), [metroShops, query, openOnly, pricedOnly, pricedShopIds, activeHood]);
  const nearBase = visibleShops;
  const nearShops = useMemo(() => {
    const rows = nearBase.map((shop) => {
      const open = isOpenNow(shop.opening_hours);
      const miles = coords && shop.lat != null && shop.lng != null ? distanceMiles(coords.lat, coords.lng, shop.lat, shop.lng) : null;
      return { shop, open, miles };
    });
    const openRank = (open: boolean | null) => open === false ? 1 : 0;
    const sorted = rows.sort((a, b) => (a.miles ?? Infinity) - (b.miles ?? Infinity) || openRank(a.open) - openRank(b.open) || a.shop.name.localeCompare(b.shop.name));
    // Chain cap: only the 2 closest locations of each same-named chain earn a
    // row; the rest collapse into a "+N more" note on the chain's last row.
    const kept: { shop: Shop; open: boolean | null; miles: number | null; extra: number }[] = [];
    const seen = new Map<string, number>();
    for (const row of sorted) {
      const n = seen.get(row.shop.name) || 0;
      seen.set(row.shop.name, n + 1);
      if (n >= 2) continue;
      kept.push({ ...row, extra: 0 });
    }
    // Assign the hidden count to the last visible row of each chain. With
    // coords, "nearby" means it: only hidden locations within 15 mi count, so
    // a Plymouth user never reads "+75 more" about shops in Saint Paul.
    const lastOf = new Map<string, number>();
    kept.forEach((row, i) => { lastOf.set(row.shop.name, i); });
    for (const [name, i] of lastOf) {
      const hidden = sorted.filter((row) => row.shop.name === name).slice(2);
      kept[i].extra = coords ? hidden.filter((row) => row.miles != null && row.miles <= 15).length : hidden.length;
    }
    return kept;
  }, [nearBase, coords]);
  const drinkTypes = useMemo(() => Array.from(new Set(data.items.filter((item) => item.is_drink && item.drink_type).map((item) => item.drink_type as string))).sort((a, b) => { const ai = drinkOrder.indexOf(a); const bi = drinkOrder.indexOf(b); return (ai < 0 ? drinkOrder.length : ai) - (bi < 0 ? drinkOrder.length : bi) || a.localeCompare(b); }), [data.items]);
  const shopsById = useMemo(() => new Map(data.shops.map((shop) => [shop.id, shop])), [data.shops]);
  const visibleIds = useMemo(() => new Set(visibleShops.map(shop => shop.id)), [visibleShops]);
  const comparisonSizes = useMemo(() => Array.from(new Set(data.items.filter(item => item.drink_type === drink && shopsById.get(item.shop_id)?.metro === metro && item.size_oz != null && item.size_confidence === 'explicit').map(item => item.size_oz as number))).sort((a, b) => a - b), [data.items, drink, shopsById, metro]);
  const comparisons = useMemo(() => data.items.filter(item => item.is_drink && item.drink_type === drink && visibleIds.has(item.shop_id) && item.current_price_cents != null && item.current_price_cents > 0
    && (drink !== 'latte' || !plainOnly || isPlainLatte(item))
    && (size === 'all' || (item.size_confidence === 'explicit' && item.size_oz === Number(size)))
    && (includeStale || (item.last_checked_at != null && RENDERED_AT - new Date(item.last_checked_at).getTime() <= STALE_AFTER_MS)))
    .map(item => ({ item, shop: shopsById.get(item.shop_id)!, price: item.current_price_cents as number })).sort((a, b) => a.price - b.price || a.shop.name.localeCompare(b.shop.name)), [data.items, visibleIds, shopsById, drink, plainOnly, size, includeStale]);
  // Chain fan-out: identical item at identically-named shops (Caribou x87,
  // Stone Creek x5, ...) collapses to one annotated row; source data is untouched.
  const ranked = useMemo(() => {
    const seen = new Map<string, { item: Item; shop: Shop; price: number; locations: number }>();
    for (const entry of comparisons) {
      const key = `${entry.shop.name}|${entry.item.name}|${entry.price}|${entry.item.size_oz ?? ''}`;
      const hit = seen.get(key);
      if (hit) { hit.locations += 1; if ((entry.item.last_checked_at || '') > (hit.item.last_checked_at || '')) { hit.item = entry.item; hit.shop = entry.shop; } } else seen.set(key, { ...entry, locations: 1 });
    }
    return Array.from(seen.values());
  }, [comparisons]);
  const medianCents = useMemo(() => { const values = ranked.map((entry) => entry.price).sort((a, b) => a - b); if (!values.length) return null; const mid = values.length >> 1; return values.length % 2 ? values[mid] : Math.round((values[mid - 1] + values[mid]) / 2); }, [ranked]);
  // Price distribution: 20 bins spanning the ranked price range, for the
  // compare view's histogram. Purely presentational - derived from `ranked`.
  const histogram = useMemo(() => {
    const sorted = ranked.map((entry) => entry.price).sort((a, b) => a - b);
    const lo = sorted.length ? sorted[0] : 0, hi = sorted.length ? sorted[sorted.length - 1] : 0;
    const BINS = 20;
    const counts = Array.from({ length: BINS }, () => 0);
    for (const price of sorted) counts[hi === lo ? 0 : Math.min(BINS - 1, Math.floor(((price - lo) / (hi - lo)) * BINS))] += 1;
    const peak = Math.max(1, ...counts);
    const median = medianCents;
    const bars = counts.map((count, i) => {
      const binLo = lo + ((hi - lo) * i) / BINS;
      const binHi = lo + ((hi - lo) * (i + 1)) / BINS;
      const isMedianBin = median != null && (hi === lo ? i === 0 : binLo <= median && (median < binHi || (i === BINS - 1 && median === binHi)));
      return { height: Math.max(count ? 3 : 1, Math.round((count / peak) * 58)), cls: isMedianBin ? 'median' : count ? 'filled' : '' };
    });
    return { bars, min: sorted.length ? formatPrice(lo) : '', max: sorted.length ? formatPrice(hi) : '' };
  }, [ranked, medianCents]);
  // Price ticks in the near view: each row's position along the low->high
  // range of the (first 75) visible prices, colored by tercile.
  const nearTickRange = useMemo(() => {
    const pool = nearShops.map(({ shop }) => shopDrink(data.items.filter((item) => item.shop_id === shop.id && item.current_price_cents != null)).price).filter((p): p is number => p != null);
    return { lo: pool.length ? Math.min(...pool) : 0, hi: pool.length ? Math.max(...pool) : 1 };
  }, [nearShops, data.items]);
  if (selectedShop) return <div className="site-shell"><ShopDetail shop={selectedShop} items={data.items} onBack={() => { setSelectedShop(null); const url = new URL(window.location.href); url.searchParams.delete('shop'); window.history.replaceState(null, '', url); requestAnimationFrame(() => window.scrollTo(0, scrollRef.current)); }} /></div>;
  const metroName = metro === 'milwaukee' ? 'Milwaukee' : 'Twin Cities';
  const geoStamp = coords ? 'Location on' : geoRequested && !geoDenied ? 'Locating' : 'Location off';
  const navCounts = { near: nearShops.length, compare: ranked.length, shops: visibleShops.length, map: visibleShops.filter((s) => s.lat != null).length };
  const columnLabels = view === 'compare' ? ['RANK', 'SHOP · ITEM · UNIT PRICE', 'PRICE / VS MEDIAN']
    : view === 'near' ? ['#', 'SHOP · DISTANCE · AREA · STATUS', 'PRICE / LOW→HIGH']
    : view === 'shops' ? ['', 'SHOP · AREA · SOURCE', 'PRICE']
    : null;
  return <div className="site-shell">
    <header className="masthead">
      <div className="masthead-top">
        <button className="wordmark" onClick={() => setView('near')} aria-label="Coffee Prices home"><span>Coffee Prices</span><span>MKE / MSP</span></button>
        <div className="metro-toggle" aria-label="Choose a metro"><button className={metro === 'milwaukee' ? 'active' : ''} onClick={() => { metroTouched.current = true; setMetro('milwaukee'); setHood(''); setShowAllKey(null); setSelectedShop(null); }}>Milwaukee</button><button className={metro === 'twin_cities' ? 'active' : ''} onClick={() => { metroTouched.current = true; setMetro('twin_cities'); setHood(''); setShowAllKey(null); setSelectedShop(null); }}>Twin Cities</button></div>
        <button className={pricedOnly ? 'prices-toggle active' : 'prices-toggle'} onClick={() => setPricedOnly(!pricedOnly)} aria-pressed={pricedOnly}>{pricedOnly ? 'Priced only' : 'All shops'}</button><div className="masthead-stamp"><div>{geoStamp}</div></div>
      </div>
      <nav className="tab-strip" aria-label="Main navigation">
        <button className={view === 'near' ? 'active' : ''} onClick={() => setView('near')}>Near you<sup>{navCounts.near}</sup></button>
        <button className={view === 'compare' ? 'active' : ''} onClick={() => setView('compare')}>Compare<sup>{navCounts.compare}</sup></button>
        <button className={view === 'shops' ? 'active' : ''} onClick={() => setView('shops')}>Index<sup>{navCounts.shops}</sup></button>
        <button className={view === 'map' ? 'active' : ''} onClick={() => setView('map')}>Map<sup>{navCounts.map}</sup></button>
      </nav>
      {columnLabels && <div className={`column-header visible${view === 'compare' ? ' compare' : view === 'shops' ? ' shops' : ''}`}>
        <span className={view === 'shops' ? 'col-a hide' : 'col-a'}>{columnLabels[0]}</span>
        <span>{columnLabels[1]}</span>
        <span className="col-c">{columnLabels[2]}</span>
        {view !== 'compare' && view !== 'shops' && <span />}
      </div>}
    </header>
    {loading ? <div className="skeleton-list">{Array.from({ length: 9 }, (_, i) => <div className="skeleton-row" key={i}><span className="sk-rank" /><span className="sk-name" style={{ width: `${[58, 44, 67, 39, 52, 61, 47, 55, 42][i]}%` }} /><span className="sk-price" /></div>)}</div>
    : error ? <div className="error-state"><h2>The index didn&apos;t load</h2><p>{error}</p><button className="show-more" onClick={() => window.location.reload()}>Retry</button></div>
    : <>
    <div className="data-status" aria-live="polite"><span>{data.source === 'snapshot' ? `Saved index · ${new Date(data.snapshotAt!).toLocaleDateString('en-US', {month: 'short', day: 'numeric', year: 'numeric'})}` : 'Live index'} · {metroShops.length} shops · {metroShops.filter(shop => pricedShopIds.has(shop.id)).length} with drink prices</span><span>Prices before tax & add-ons</span></div>
    <div className="controls">
      <label className="search"><input aria-label="Search shops and areas" value={query} onChange={event => setQuery(event.target.value)} placeholder="Shop, address or area" />{query && <button aria-label="Clear search" onClick={() => setQuery('')}>✕</button>}</label>
      <button className={openOnly ? 'filter-button active' : 'filter-button'} aria-pressed={openOnly} onClick={() => setOpenOnly(!openOnly)}>Open now</button>
      {hoods.length > 1 && <select className="hood-select" value={activeHood} onChange={event => setHood(event.target.value)} aria-label="Filter by neighborhood"><option value="">All areas ({metroShops.length})</option>{hoodOptions}</select>}
      {(query || openOnly || activeHood) && <button className="filter-button" onClick={() => { setQuery(''); setOpenOnly(false); setHood(''); }}>Clear filters</button>}
    </div>
    {view === 'near' && <main className="content-shell">
      {!coords && <div className="locate-band">
        <span>{geoRequested && !geoDenied ? 'Finding your location…' : 'Use your location to sort shops by distance.'}</span>
        <button onClick={() => { setGeoDenied(false); setGeoRequested(true); }}>Use location</button>
      </div>}

      {(nearExpanded ? nearShops : nearShops.slice(0, 75)).map(({ shop, open, miles, extra }, index) => {
        const menu = data.items.filter((item) => item.shop_id === shop.id && item.current_price_cents != null);
        const d = shopDrink(menu);
        const { lo, hi } = nearTickRange;
        const pos = d.price == null || hi === lo ? null : Math.round(((d.price - lo) / (hi - lo)) * 100);
        const tickCls = pos == null ? '' : pos <= 34 ? 'under' : pos >= 72 ? 'accent' : '';
        return <div className="near-row" key={shop.id}>
          <button className="near-open" onClick={() => openShop(shop)}>
            <span className="rank-number">{String(index + 1).padStart(2, '0')}</span>
            <span className="rank-main">
              <strong>{shop.name}</strong>
              <small>{[miles != null ? formatMiles(miles) : null, neighborhood(shop), open === true ? 'OPEN' : open === false ? 'CLOSED' : null, ratingStr(shop), extra > 0 ? `+${extra}` : null].filter(Boolean).join('  ·  ')}</small>
            </span>
            <span className="rank-price">
              <strong>{formatPrice(d.price)}</strong>
              <small>{d.price != null ? d.label : pricedShopIds.has(shop.id) ? 'no coffee price' : 'menu pending'}</small>
              <span className="near-tick-track">{pos != null && <span className={`near-tick ${tickCls}`} style={{ left: `${pos}%` }} />}</span>
            </span>
          </button>
          {shop.lat != null && shop.lng != null && <a className="dir-link" href={`https://maps.apple.com/?q=${encodeURIComponent(`${shop.name}, ${shop.address || `${neighborhood(shop)}, ${metro === 'milwaukee' ? 'Milwaukee, WI' : 'Minneapolis, MN'}`}`)}`} target="_blank" rel="noreferrer" aria-label={`Directions to ${shop.name}`}>GO</a>}
        </div>;
      })}
      {!nearShops.length && <div className="empty"><h2>No shops match</h2><p>Clear a filter or switch to all shops.</p></div>}
      {!nearExpanded && nearShops.length > 75 && <button className="show-more" onClick={() => setNearExpanded(true)}>Show all {nearShops.length} shops</button>}
    </main>}
    {view === 'compare'  && <main className="content-shell">
      <div className="drink-scroll" role="tablist" aria-label="Drink type">{(drinkTypes.length ? drinkTypes : ['latte', 'caramel_latte', 'cappuccino', 'espresso', 'drip', 'cold_brew']).map((type) => <button key={type} role="tab" aria-selected={drink === type} className={drink === type ? 'active' : ''} onClick={() => { setDrink(type); setSize('all'); }}>{drinkLabels[type] || type.replaceAll('_', ' ')}</button>)}</div>
      <div className="controls comparison-controls">
        <select className="hood-select" aria-label="Compare drink size" value={size} onChange={event => setSize(event.target.value)}><option value="all">All sizes</option>{comparisonSizes.map(oz => <option key={oz} value={oz}>{oz} oz · stated sizes</option>)}</select>
        {drink === 'latte' && <button className={plainOnly ? 'filter-button active' : 'filter-button'} aria-pressed={plainOnly} onClick={() => setPlainOnly(!plainOnly)}>{plainOnly ? 'Plain lattes' : 'All latte flavors'}</button>}
        <button className={includeStale ? 'filter-button' : 'filter-button active'} aria-pressed={!includeStale} onClick={() => setIncludeStale(!includeStale)}>{includeStale ? 'Include older prices' : 'Checked within 60 days'}</button>
      </div>
      <p className="fine-print">{size === 'all' ? 'Different serving sizes are included. Choose a size for a closer comparison.' : `Only explicitly stated ${size} oz servings.`} Median is across listed menu options; identical prices at same-named locations are grouped.</p>
      <div className="median-panel">
        <div className="median-figure">
          <div className="label">Median {(drinkLabels[drink] || drink.replaceAll('_', ' ')).toLowerCase()}</div>
          <div className="value">{medianCents == null ? '—' : formatPrice(medianCents)}</div>
          <div className="meta">{ranked.length} prices · {metroName}{activeHood ? ` · ${activeHood}` : ''}{histogram.min ? ` · ${histogram.min}–${histogram.max}` : ''}</div>
        </div>
        <div className="histogram-wrap">
          <div className="histogram">{histogram.bars.map((bar, i) => <span key={i} className={bar.cls} style={{ height: `${bar.height}px` }} />)}</div>
          <div className="histogram-axis"><span>{histogram.min}</span><span>DISTRIBUTION</span><span>{histogram.max}</span></div>
        </div>
      </div>
      {(showAll ? ranked : ranked.slice(0, 75)).map(({ item, shop, price, locations }, index) => {
        const diff = medianCents == null ? 0 : price - medianCents;
        const deltaCls = medianCents == null ? '' : diff < 0 ? 'under' : diff > 0 ? 'over' : '';
        return <button className="rank-row" key={item.id} onClick={() => openShop(shop)}>
          <span className="rank-number">{String(index + 1).padStart(2, '0')}</span>
          <span className="rank-main"><strong>{shop.name}</strong><small>{[item.name, locations > 1 ? `${locations} LOCATIONS` : neighborhood(shop), item.size_oz ? `${item.size_oz}oz · ${item.size_confidence === 'inferred' ? '~' : ''}${money.format(price / 100 / item.size_oz)}/OZ` : null, item.last_checked_at ? `Checked ${new Date(item.last_checked_at).toLocaleDateString('en-US', {month: 'short', day: 'numeric', year: 'numeric'})}${RENDERED_AT - new Date(item.last_checked_at).getTime() > STALE_AFTER_MS ? ' · Stale' : ''}` : 'Date unknown'].filter(Boolean).join('  ·  ')}</small></span>
          <span className="rank-price"><strong>{formatPrice(price)}</strong><span className={`rank-delta ${deltaCls}`}>{medianCents == null ? '' : `${diff >= 0 ? '+' : '−'}${money.format(Math.abs(diff) / 100)}`}</span></span>
        </button>;
      })}
      {!comparisons.length && <div className="empty"><h2>No comparable prices</h2><p>This drink fills in as direct menus are collected.</p></div>}
      {!showAll && ranked.length > 75 && <button className="show-more" onClick={() => setShowAllKey(rankingKey)}>All {ranked.length} prices</button>}
      {showAll && ranked.length > 75 && <button className="show-more" onClick={() => setShowAllKey(null)}>Show top 75</button>}
    </main>}
    {view === 'shops' && <main className="content-shell">
      {visibleShops.length ? visibleShops.map((shop, index) => { const letter = (fold(shop.name).trimStart().charAt(0) || '#').replace(/[0-9]/, '#').toUpperCase(); const prev = index > 0 ? (fold(visibleShops[index - 1].name).trimStart().charAt(0) || '#').replace(/[0-9]/, '#').toUpperCase() : ''; const groupCount = visibleShops.filter((s) => (fold(s.name).trimStart().charAt(0) || '#').replace(/[0-9]/, '#').toUpperCase() === letter).length; return <div key={shop.id}>{letter !== prev && <div className="letter-head"><span className="letter">{letter}</span><span className="rule" /><span className="count">{String(groupCount).padStart(2, '0')}</span></div>}<ShopRow shop={shop} items={data.items} dimmed={openOnly && isOpenNow(shop.opening_hours) == null} onOpen={() => openShop(shop)} /></div>; }) : <div className="empty"><h2>Nothing matches</h2><p>Clear a filter, or check back after the next menu pull.</p></div>}
    </main>}
    {view === 'map' && <main className="content-shell">
      <div className="map-panel">
        <div className="map-panel-title">{navCounts.map} mapped · {metroName}{pricedOnly ? ' · priced menus only' : ''}{activeHood ? ` · ${activeHood}` : ''}</div>

      </div>
      {(query || openOnly) && <div className="map-filter-note"><span>Filtered by {[query && `"${query}"`, openOnly && 'open now'].filter(Boolean).join(' · ')}</span><button onClick={() => { setQuery(''); setOpenOnly(false); }}>✕ Clear</button></div>}
      <div className="map-shell">
        <MapView shops={visibleShops} items={data.items} metro={metro} user={coords} onOpen={openShop} />
        <div className="map-tint" />
        <div className="map-glow" />
      </div>
      <div className="map-caption">Markers show each shop&apos;s representative drink price. Locations and basemap from OpenStreetMap.</div>
    </main>}
    </>}
  </div>;
}
