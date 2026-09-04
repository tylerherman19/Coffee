'use client';

export const dynamic = 'force-static';

import nextDynamic from 'next/dynamic';
import { useEffect, useMemo, useRef, useState } from 'react';
import { ArrowLeft, ChevronRight, Coffee, List, LoaderCircle, Map as MapIcon, Search, SlidersHorizontal, Star, Tag, X } from 'lucide-react';
import { drinkLabels, loadCoffeeData, platformLabel, shopDrink, type CoffeeData, type Item, type Shop } from '@/lib/coffee-data';

const MapView = nextDynamic(() => import('@/components/coffee-map'), { ssr: false, loading: () => <div className="map-loading"><LoaderCircle aria-hidden="true" /> Loading the map…</div> });
type Metro = 'milwaukee' | 'twin_cities';
type View = 'shops' | 'compare' | 'map';
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


const fold = (value: string) => value.normalize('NFD').replace(/\p{Diacritic}/gu, '').toLowerCase();

function neighborhood(shop: Shop) {
  if (shop.neighborhood) return shop.neighborhood;
  const parts = shop.address?.split(',').map((part) => part.trim()) ?? [];
  return parts.length > 2 ? parts[parts.length - 3] : parts[0] || 'Neighborhood unavailable';
}

function isOpenNow(hours: string | null) {
  if (!hours) return null;
  if (/24\/7/.test(hours)) return true;
  const parts = new Intl.DateTimeFormat('en-US', { timeZone: 'America/Chicago', weekday: 'short', hour: '2-digit', minute: '2-digit', hourCycle: 'h23' }).formatToParts(new Date());
  const today = ({ Mon: 'Mo', Tue: 'Tu', Wed: 'We', Thu: 'Th', Fri: 'Fr', Sat: 'Sa', Sun: 'Su' } as Record<string, string>)[parts.find((p) => p.type === 'weekday')?.value || ''];
  const minute = Number(parts.find((p) => p.type === 'hour')?.value) * 60 + Number(parts.find((p) => p.type === 'minute')?.value);
  const days = ['Mo', 'Tu', 'We', 'Th', 'Fr', 'Sa', 'Su'];
  for (const rule of hours.split(';')) {
    const match = rule.trim().match(/^([A-Za-z,-]+)\s+(\d{2}):(\d{2})-(\d{2}):(\d{2})/);
    if (!match) continue;
    const active = match[1].split(',').some((token) => { const [from, to = from] = token.split('-'); const a = days.indexOf(from); const b = days.indexOf(to); const now = days.indexOf(today); return a >= 0 && b >= 0 && (a <= b ? now >= a && now <= b : now >= a || now <= b); });
    const start = Number(match[2]) * 60 + Number(match[3]); const end = Number(match[4]) * 60 + Number(match[5]);
    if (active && (end < start ? minute >= start || minute < end : minute >= start && minute < end)) return true;
  }
  return false;
}

function Rating({ value, count }: { value: number | null; count?: number | null }) {
  if (value == null) return null;
  return <span className="rating"><Star aria-hidden="true" /> {value.toFixed(1)}{count ? ` (${count.toLocaleString()})` : ''}</span>;
}

function ShopRow({ shop, items, onOpen, dimmed = false }: { shop: Shop; items: Item[]; onOpen: () => void; dimmed?: boolean }) {
  const menu = items.filter((item) => item.shop_id === shop.id && item.current_price_cents != null);
  const drink = shopDrink(menu);
  return <button className={dimmed ? 'shop-row dimmed' : 'shop-row'} onClick={onOpen}>
    <span className="shop-main"><span className="shop-name">{shop.name}</span><span className="shop-meta">{neighborhood(shop)} · {shop.platform ? `${platformLabel(shop.platform)} menu` : menu.length ? 'direct menu' : 'menu pending'}</span><Rating value={shop.rating} count={shop.review_count} /></span>
    <span className="shop-price"><strong>{formatPrice(drink.price)}</strong><small>{drink.label}</small></span>
  </button>;
}

function ShopDetail({ shop, items, onBack }: { shop: Shop; items: Item[]; onBack: () => void }) {
  const menu = items.filter((item) => item.shop_id === shop.id);
  const checked = menu.reduce<string | null>((latest, item) => !item.last_checked_at ? latest : !latest || item.last_checked_at > latest ? item.last_checked_at : latest, null);
  const groups = menu.reduce<Record<string, Item[]>>((acc, item) => { const key = item.category || (item.is_drink ? 'Coffee & drinks' : 'Food'); (acc[key] ??= []).push(item); return acc; }, {});
  return <main className="detail-shell">
    <button className="back-button" onClick={onBack}><ArrowLeft aria-hidden="true" /> All shops</button>
    <p className="eyebrow">{neighborhood(shop)}</p>
    <section className="shop-heading"><h1>{shop.name}</h1>{shop.website && <a className="order-link" href={shop.website} target="_blank" rel="noreferrer">Visit shop</a>}</section>
    <div className="detail-meta"><Rating value={shop.rating} count={shop.review_count} /><span>{shop.address || 'Address unavailable'}</span><span>{shop.opening_hours || 'Hours unavailable'}</span>{checked ? <span>Menu checked {new Intl.DateTimeFormat('en-US', { month: 'short', day: 'numeric' }).format(new Date(checked))}{RENDERED_AT - new Date(checked).getTime() > STALE_AFTER_MS ? ' (stale)' : ''}</span> : null}</div>
    {Object.keys(groups).length === 0 ? <div className="empty"><Coffee aria-hidden="true" /><h2>Menu collection is pending</h2><p>The shop is mapped. Its direct menu source has not been collected yet.</p></div> : Object.entries(groups).map(([group, entries]) => <section className="menu-section" key={group}><h2>{group}</h2>{entries.sort((a, b) => a.name.localeCompare(b.name)).map((item) => <div className="menu-row" key={item.id}><div className="menu-item"><h3>{item.name}</h3><p>{item.size_label || (item.size_oz ? `${item.size_oz} oz` : 'Size not listed')}{item.size_confidence === 'inferred' ? ' · estimated size' : ''}</p></div><span className="leader" aria-hidden="true"></span><div className="menu-price"><strong>{formatPrice(item.current_price_cents)}</strong>{item.current_price_cents && item.size_oz ? <small>{item.size_confidence === 'inferred' ? '~' : ''}{money.format(item.current_price_cents / 100 / item.size_oz)}/oz</small> : null}</div></div>)}</section>)}
    <p className="source-note">Direct-order menu prices only. Item names are shortened when needed; descriptions are not republished.</p>
  </main>;
}

export default function Home() {
  const [data, setData] = useState<CoffeeData>({ shops: [], items: [], loadedAt: null });
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [metro, setMetro] = useState<Metro>('milwaukee');
  const [view, setView] = useState<View>(() => {
    if (typeof window === 'undefined') return 'compare';
    const v = new URLSearchParams(window.location.search).get('view');
    return v === 'shops' || v === 'map' ? v : 'compare';
  });
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
  useEffect(() => { loadCoffeeData().then(setData).catch(() => setError('Price data could not be loaded. Try again shortly.')).finally(() => setLoading(false)); }, []);
  useEffect(() => {
    const id = typeof window !== 'undefined' ? new URLSearchParams(window.location.search).get('shop') : null;
    if (id && data.shops.length && !selectedShop) { const hit = data.shops.find((shop) => String(shop.id) === id); if (hit) setSelectedShop(hit); }
  }, [data.shops, selectedShop]);
  const metroShops = useMemo(() => data.shops.filter((shop) => shop.metro === metro), [data.shops, metro]);
  const hoods = useMemo(() => { const counts = new Map<string, number>(); for (const shop of metroShops) if (shop.neighborhood) counts.set(shop.neighborhood, (counts.get(shop.neighborhood) || 0) + 1); return Array.from(counts.entries()).sort((a, b) => b[1] - a[1] || a[0].localeCompare(b[0])); }, [metroShops]);
  const activeHood = hoods.some(([name]) => name === hood) ? hood : '';
  const rankingKey = `${metro}|${drink}|${activeHood}`;
  const showAll = showAllKey === rankingKey;
  const pricedShopIds = useMemo(() => { const set = new Set<number>(); for (const item of data.items) if (item.current_price_cents != null) set.add(item.shop_id); return set; }, [data.items]);
  const visibleShops = useMemo(() => metroShops.filter((shop) => { const haystack = fold(`${shop.name} ${shop.neighborhood || ''} ${shop.address || ''}`); return haystack.includes(fold(query)) && (!openOnly || isOpenNow(shop.opening_hours) !== false) && (!pricedOnly || pricedShopIds.has(shop.id)) && (!activeHood || shop.neighborhood === activeHood); }), [metroShops, query, openOnly, pricedOnly, pricedShopIds, activeHood]);
  const drinkTypes = useMemo(() => Array.from(new Set(data.items.filter((item) => item.is_drink && item.drink_type).map((item) => item.drink_type as string))).sort((a, b) => { const ai = drinkOrder.indexOf(a); const bi = drinkOrder.indexOf(b); return (ai < 0 ? drinkOrder.length : ai) - (bi < 0 ? drinkOrder.length : bi) || a.localeCompare(b); }), [data.items]);
  const shopsById = useMemo(() => new Map(data.shops.map((shop) => [shop.id, shop])), [data.shops]);
  const comparisons = useMemo(() => data.items.filter((item) => item.drink_type === drink && item.current_price_cents != null && item.current_price_cents > 0).map((item) => ({ item, shop: shopsById.get(item.shop_id), price: item.current_price_cents as number })).filter((entry): entry is { item: Item; shop: Shop; price: number } => Boolean(entry.shop && entry.shop.metro === metro && (!activeHood || entry.shop.neighborhood === activeHood))).sort((a, b) => a.price - b.price), [data.items, shopsById, drink, metro, activeHood]);
  // Chain fan-out: identical item at identically-named shops (Caribou x87,
  // Stone Creek x5, ...) collapses to one annotated row; source data is untouched.
  const ranked = useMemo(() => {
    const seen = new Map<string, { item: Item; shop: Shop; price: number; locations: number }>();
    for (const entry of comparisons) {
      const key = `${entry.shop.name}|${entry.item.name}|${entry.price}|${entry.item.size_oz ?? ''}`;
      const hit = seen.get(key);
      if (hit) hit.locations += 1; else seen.set(key, { ...entry, locations: 1 });
    }
    return Array.from(seen.values());
  }, [comparisons]);
  if (selectedShop) return <div className="site-shell"><ShopDetail shop={selectedShop} items={data.items} onBack={() => { setSelectedShop(null); requestAnimationFrame(() => window.scrollTo(0, scrollRef.current)); }} /></div>;
  return <div className="site-shell">
    <header className="masthead">
      <div className="masthead-top">
        <button className="wordmark" onClick={() => setView('compare')} aria-label="Coffee Prices home"><Coffee aria-hidden="true" /><span>Coffee Prices</span></button>
        <div className="masthead-tools">
          <div className="metro-toggle" aria-label="Choose a metro"><button className={metro === 'milwaukee' ? 'active' : ''} onClick={() => setMetro('milwaukee')}>Milwaukee</button><button className={metro === 'twin_cities' ? 'active' : ''} onClick={() => setMetro('twin_cities')}>Twin Cities</button></div>
          <button className={pricedOnly ? 'prices-toggle active' : 'prices-toggle'} aria-pressed={pricedOnly} onClick={() => setPricedOnly(!pricedOnly)}><Tag aria-hidden="true" /> Has prices</button>
        </div>
      </div>
      <nav className="tab-strip" aria-label="Main navigation">
        <button className={view === 'compare' ? 'active' : ''} onClick={() => setView('compare')}>Compare</button>
        <button className={view === 'shops' ? 'active' : ''} onClick={() => setView('shops')}>Shops</button>
        <button className={view === 'map' ? 'active' : ''} onClick={() => setView('map')}>Map</button>
      </nav>
    </header>
    {view === 'compare' && <main className="content-shell">
      <section className="menu-title"><p className="eyebrow">Same drink, fair comparison</p><div className="menu-title-row"><h1>{drinkLabels[drink] || drink.replaceAll('_', ' ')}</h1><span>{loading ? 'Pulling menus…' : `${ranked.length} prices · ${metro === 'milwaukee' ? 'Milwaukee' : 'Twin Cities'}`}</span></div></section>
      <div className="drink-scroll" aria-label="Drink type">{(drinkTypes.length ? drinkTypes : ['latte', 'caramel_latte', 'cappuccino', 'espresso', 'drip', 'cold_brew']).map((type) => <button key={type} className={drink === type ? 'active' : ''} onClick={() => setDrink(type)}>{drinkLabels[type] || type.replaceAll('_', ' ')}</button>)}</div>
      <div className="controls">{hoods.length > 1 && <select className="hood-select" value={activeHood} onChange={(event) => setHood(event.target.value)} aria-label="Filter by neighborhood"><option value="">All neighborhoods</option>{hoods.map(([name, count]) => <option key={name} value={name}>{name} ({count})</option>)}</select>}<p className="fine-print">Direct shop menus. A tilde marks an inferred serving size.</p></div>
      {loading ? <div className="loading-list"><LoaderCircle aria-hidden="true" /> Pulling the latest menus…</div> : error ? <div className="error-state">{error}</div> : <div className="rank-list">{(showAll ? ranked : ranked.slice(0, 75)).map(({ item, shop, price, locations }, index) => <button className="rank-row" key={item.id} onClick={() => { scrollRef.current = window.scrollY; setSelectedShop(shop); }}><span className="rank-number">{index + 1}</span><span className="rank-main"><strong>{shop.name}</strong><small>{item.name} · {locations > 1 ? `${locations} locations · chain menu` : neighborhood(shop)}</small><Rating value={shop.rating} count={shop.review_count} /></span><span className="leader" aria-hidden="true"></span><span className="rank-price"><strong>{formatPrice(price)}</strong>{item.size_oz ? <small>{item.size_confidence === 'inferred' ? '~' : ''}{money.format(price / 100 / item.size_oz)}/oz</small> : <small>size unlisted</small>}</span></button>)}{!comparisons.length && <div className="empty"><Coffee aria-hidden="true" /><h2>No comparable prices yet</h2><p>This fills in as direct menus are collected.</p></div>}{!showAll && ranked.length > 75 && <button className="show-more" onClick={() => setShowAllKey(rankingKey)}>Show all {ranked.length} matches</button>}{showAll && ranked.length > 75 && <button className="show-more" onClick={() => setShowAllKey(null)}>Show top 75</button>}</div>}
    </main>}
    {view === 'shops' && <main className="content-shell">
      <section className="menu-title"><p className="eyebrow">{metro === 'milwaukee' ? 'Milwaukee' : 'Minneapolis–Saint Paul'}</p><div className="menu-title-row"><h1>Every shop</h1><span>{loading ? 'Pulling menus…' : pricedOnly || query || openOnly ? `${visibleShops.length} shown of ${metroShops.length}` : `${metroShops.length} shops mapped`}</span></div></section>
      <div className="controls"><label className="search"><Search aria-hidden="true" /><input value={query} onChange={(event) => setQuery(event.target.value)} placeholder="Search shops or neighborhoods" /></label><button className={openOnly ? 'filter-button active' : 'filter-button'} onClick={() => setOpenOnly(!openOnly)}><SlidersHorizontal aria-hidden="true" /> Open now</button>{hoods.length > 1 && <select className="hood-select" value={activeHood} onChange={(event) => setHood(event.target.value)} aria-label="Filter by neighborhood"><option value="">All neighborhoods</option>{hoods.map(([name, count]) => <option key={name} value={name}>{name} ({count})</option>)}</select>}</div>
      {loading ? <div className="loading-list"><LoaderCircle aria-hidden="true" /> Pulling the latest menus…</div> : error ? <div className="error-state">{error}</div> : visibleShops.length ? <div className="shop-list">{visibleShops.map((shop, index) => { const letter = (fold(shop.name).trimStart().charAt(0) || '#').replace(/[0-9]/, '#').toUpperCase(); const prev = index > 0 ? (fold(visibleShops[index - 1].name).trimStart().charAt(0) || '#').replace(/[0-9]/, '#').toUpperCase() : ''; return <div key={shop.id}>{letter !== prev && <div className="letter-head">{letter}</div>}<ShopRow shop={shop} items={data.items} dimmed={openOnly && isOpenNow(shop.opening_hours) == null} onOpen={() => { scrollRef.current = window.scrollY; setSelectedShop(shop); }} /></div>; })}</div> : <div className="empty"><Coffee aria-hidden="true" /><h2>No shops match</h2><p>Clear the filters or check back after the next menu pull.</p></div>}
    </main>}
    {view === 'map' && <main className="map-shell">
      <div className="map-caption"><div><p className="eyebrow">{metro === 'milwaukee' ? 'Milwaukee' : 'Twin Cities'}</p><h1>Every cup on the map</h1></div><span>{visibleShops.length === metroShops.length ? `${visibleShops.length} locations` : `${visibleShops.length} of ${metroShops.length} locations`}</span></div>
      {(query || openOnly) && <div className="map-filter-note"><span>Filtered by {[query && `"${query}"`, openOnly && 'open now'].filter(Boolean).join(' · ')}</span><button onClick={() => { setQuery(''); setOpenOnly(false); }}><X aria-hidden="true" /> Clear</button></div>}
      {hoods.length > 1 && <select className="hood-select map-hood" value={activeHood} onChange={(event) => setHood(event.target.value)} aria-label="Filter by neighborhood"><option value="">All neighborhoods</option>{hoods.map(([name, count]) => <option key={name} value={name}>{name} ({count})</option>)}</select>}
      <MapView shops={visibleShops} items={data.items} metro={metro} onOpen={setSelectedShop} />
    </main>}
    <nav className="mobile-nav" aria-label="Main navigation"><button className={view === 'compare' ? 'active' : ''} onClick={() => setView('compare')}><Coffee aria-hidden="true" /><span>Compare</span></button><button className={view === 'shops' ? 'active' : ''} onClick={() => setView('shops')}><List aria-hidden="true" /><span>Shops</span></button><button className={view === 'map' ? 'active' : ''} onClick={() => setView('map')}><MapIcon aria-hidden="true" /><span>Map</span></button></nav>
  </div>;
}
