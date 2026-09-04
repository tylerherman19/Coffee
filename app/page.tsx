'use client';

export const dynamic = 'force-static';

import nextDynamic from 'next/dynamic';
import { useEffect, useMemo, useState } from 'react';
import { ArrowLeft, ChevronRight, Clock3, Coffee, List, LoaderCircle, Map as MapIcon, Search, SlidersHorizontal, Star } from 'lucide-react';
import { loadCoffeeData, type CoffeeData, type Item, type Modifier, type Shop } from '@/lib/coffee-data';

const MapView = nextDynamic(() => import('@/components/coffee-map'), { ssr: false, loading: () => <div className="map-loading"><LoaderCircle aria-hidden="true" /> Loading the map…</div> });
type Metro = 'milwaukee' | 'twin_cities';
type View = 'shops' | 'compare' | 'map';
const drinkLabels: Record<string, string> = { latte: 'Latte', caramel_latte: 'Caramel latte', cappuccino: 'Cappuccino', espresso: 'Espresso', americano: 'Americano', drip: 'Drip coffee', cold_brew: 'Cold brew', mocha: 'Mocha', chai: 'Chai', tea: 'Tea', other: 'Other coffee' };
// Chip order for the compare view. Anything the collector produces that is
// not listed here still appears, after these.
const drinkOrder = ['latte', 'caramel_latte', 'cold_brew', 'drip', 'cappuccino', 'americano', 'espresso', 'mocha', 'chai', 'tea', 'other'];
// "oat" is also inside "Add Goat Cheese" and "Oatmeal", so match it as a whole
// word; and once the collector records a group, require the choice to sit in a
// milk group so a "Top with Oat Milk" extra is not read as the milk price.
const isOatMilk = (modifier: Modifier) => /\boat(\s?milk)?\b/i.test(modifier.choice_name || '') && (!modifier.group_name || /milk/i.test(modifier.group_name));
const money = new Intl.NumberFormat('en-US', { style: 'currency', currency: 'USD' });
const formatPrice = (cents: number | null) => cents == null ? '—' : money.format(cents / 100);

function freshLabel(value: string | null) {
  if (!value) return 'No price pull yet';
  return `Prices as of ${new Intl.DateTimeFormat('en-US', { month: 'short', day: 'numeric', hour: 'numeric', minute: '2-digit', timeZoneName: 'short' }).format(new Date(value))}`;
}

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
  if (value == null) return <span className="muted">Rating pending</span>;
  return <span className="rating"><Star aria-hidden="true" /> {value.toFixed(1)}{count ? ` (${count.toLocaleString()})` : ''}</span>;
}

function ShopRow({ shop, items, onOpen }: { shop: Shop; items: Item[]; onOpen: () => void }) {
  const menu = items.filter((item) => item.shop_id === shop.id && item.current_price_cents != null);
  const from = menu.length ? Math.min(...menu.map((item) => item.current_price_cents as number)) : null;
  return <button className="shop-row" onClick={onOpen}>
    <span className="shop-main"><span className="shop-name">{shop.name}</span><span className="shop-meta">{neighborhood(shop)} · {shop.platform ? `${shop.platform} menu` : menu.length ? 'direct menu' : 'menu pending'}</span><Rating value={shop.rating} count={shop.review_count} /></span>
    <span className="shop-price"><small>{from == null ? 'No menu yet' : 'From'}</small><strong>{formatPrice(from)}</strong></span><ChevronRight className="row-arrow" aria-hidden="true" />
  </button>;
}

function ShopDetail({ shop, items, onBack }: { shop: Shop; items: Item[]; onBack: () => void }) {
  const menu = items.filter((item) => item.shop_id === shop.id);
  const groups = menu.reduce<Record<string, Item[]>>((acc, item) => { const key = item.category || (item.is_drink ? 'Coffee & drinks' : 'Food'); (acc[key] ??= []).push(item); return acc; }, {});
  return <main className="detail-shell">
    <button className="back-button" onClick={onBack}><ArrowLeft aria-hidden="true" /> All shops</button>
    <section className="shop-heading"><div><p>{neighborhood(shop)}</p><h1>{shop.name}</h1><Rating value={shop.rating} count={shop.review_count} /></div>{shop.website && <a className="order-link" href={shop.website} target="_blank" rel="noreferrer">Visit shop</a>}</section>
    <div className="detail-address">{shop.address || 'Address unavailable'} · {shop.opening_hours || 'Hours unavailable'}</div>
    {Object.keys(groups).length === 0 ? <div className="empty"><Coffee aria-hidden="true" /><h2>Menu collection is pending</h2><p>The shop is mapped. Its direct menu source has not been collected yet.</p></div> : Object.entries(groups).map(([group, entries]) => <section className="menu-section" key={group}><h2>{group}</h2>{entries.sort((a, b) => a.name.localeCompare(b.name)).map((item) => <div className="menu-row" key={item.id}><div><h3>{item.name}</h3><p>{item.size_label || (item.size_oz ? `${item.size_oz} oz` : 'Size not listed')}{item.size_confidence === 'inferred' ? ' · estimated size' : ''}</p></div><div className="menu-price"><strong>{formatPrice(item.current_price_cents)}</strong>{item.current_price_cents && item.size_oz ? <small>{item.size_confidence === 'inferred' ? '~' : ''}{money.format(item.current_price_cents / 100 / item.size_oz)}/oz</small> : null}</div></div>)}</section>)}
    <p className="source-note">Direct-order menu prices only. Item names are shortened when needed; descriptions are not republished.</p>
  </main>;
}

export default function Home() {
  const [data, setData] = useState<CoffeeData>({ shops: [], items: [], modifiers: [], changes: [], loadedAt: null });
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [metro, setMetro] = useState<Metro>('milwaukee');
  const [view, setView] = useState<View>('shops');
  const [query, setQuery] = useState('');
  const [openOnly, setOpenOnly] = useState(false);
  const [selectedShop, setSelectedShop] = useState<Shop | null>(null);
  const [drink, setDrink] = useState('latte');
  useEffect(() => { loadCoffeeData().then(setData).catch(() => setError('Price data could not be loaded. Try again shortly.')).finally(() => setLoading(false)); }, []);
  const metroShops = useMemo(() => data.shops.filter((shop) => shop.metro === metro), [data.shops, metro]);
  const visibleShops = useMemo(() => metroShops.filter((shop) => { const haystack = `${shop.name} ${shop.neighborhood || ''} ${shop.address || ''}`.toLowerCase(); return haystack.includes(query.toLowerCase()) && (!openOnly || isOpenNow(shop.opening_hours) === true); }), [metroShops, query, openOnly]);
  const drinkTypes = useMemo(() => Array.from(new Set(data.items.filter((item) => item.is_drink && item.drink_type).map((item) => item.drink_type as string))).sort((a, b) => { const ai = drinkOrder.indexOf(a); const bi = drinkOrder.indexOf(b); return (ai < 0 ? drinkOrder.length : ai) - (bi < 0 ? drinkOrder.length : bi) || a.localeCompare(b); }), [data.items]);
  // modifiers arrive newest-first, so the first oat row per item is the current price.
  const oatByItem = useMemo(() => { const map = new Map<number, number>(); for (const modifier of data.modifiers) if (isOatMilk(modifier) && !map.has(modifier.item_id)) map.set(modifier.item_id, modifier.price_delta_cents); return map; }, [data.modifiers]);
  const shopsById = useMemo(() => new Map(data.shops.map((shop) => [shop.id, shop])), [data.shops]);
  const comparisons = useMemo(() => { const baseDrink = drink === 'oat_latte' ? 'latte' : drink; return data.items.filter((item) => item.drink_type === baseDrink && item.current_price_cents != null && (drink !== 'oat_latte' || oatByItem.has(item.id))).map((item) => ({ item, shop: shopsById.get(item.shop_id), price: (item.current_price_cents as number) + (drink === 'oat_latte' ? oatByItem.get(item.id) || 0 : 0) })).filter((entry): entry is { item: Item; shop: Shop; price: number } => Boolean(entry.shop && entry.shop.metro === metro)).sort((a, b) => a.price - b.price); }, [data.items, shopsById, drink, oatByItem, metro]);
  if (selectedShop) return <ShopDetail shop={selectedShop} items={data.items} onBack={() => setSelectedShop(null)} />;
  return <div className="site-shell">
    <header className="topbar"><button className="wordmark" onClick={() => setView('shops')} aria-label="Coffee Prices home"><Coffee aria-hidden="true" /><span>Coffee Prices</span></button><div className="metro-toggle" aria-label="Choose a metro"><button className={metro === 'milwaukee' ? 'active' : ''} onClick={() => setMetro('milwaukee')}>Milwaukee</button><button className={metro === 'twin_cities' ? 'active' : ''} onClick={() => setMetro('twin_cities')}>Twin Cities</button></div><p className="freshness"><Clock3 aria-hidden="true" /> {freshLabel(data.loadedAt)}</p></header>
    <nav className="desktop-nav" aria-label="Main navigation"><button className={view === 'shops' ? 'active' : ''} onClick={() => setView('shops')}>Shops</button><button className={view === 'compare' ? 'active' : ''} onClick={() => setView('compare')}>Compare</button><button className={view === 'map' ? 'active' : ''} onClick={() => setView('map')}>Map</button></nav>
    {view === 'shops' && <main className="content-shell"><section className="section-heading"><div><p>{metro === 'milwaukee' ? 'Milwaukee' : 'Minneapolis–Saint Paul'}</p><h1>What does coffee cost today?</h1></div><span>{metroShops.length} shops mapped</span></section><div className="filters"><label className="search"><Search aria-hidden="true" /><input value={query} onChange={(event) => setQuery(event.target.value)} placeholder="Search shops or neighborhoods" /></label><button className={openOnly ? 'filter-button active' : 'filter-button'} onClick={() => setOpenOnly(!openOnly)}><SlidersHorizontal aria-hidden="true" /> Open now</button></div>{loading ? <div className="loading-list"><LoaderCircle aria-hidden="true" /> Pulling the latest menus…</div> : error ? <div className="error-state">{error}</div> : visibleShops.length ? <div className="shop-list">{visibleShops.map((shop) => <ShopRow key={shop.id} shop={shop} items={data.items} onOpen={() => setSelectedShop(shop)} />)}</div> : <div className="empty"><Coffee aria-hidden="true" /><h2>No shops match</h2><p>Clear the filters or check back after the next menu pull.</p></div>}</main>}
    {view === 'compare' && <main className="content-shell compare-shell"><section className="section-heading"><div><p>Same drink, fair comparison</p><h1>Find your cup</h1></div><span>{comparisons.length} menu matches</span></section><div className="drink-scroll" aria-label="Drink type">{['oat_latte', ...(drinkTypes.length ? drinkTypes : ['latte', 'caramel_latte', 'cappuccino', 'espresso', 'drip', 'cold_brew'])].map((type) => <button key={type} className={drink === type ? 'active' : ''} onClick={() => setDrink(type)}>{type === 'oat_latte' ? 'Oat milk latte' : drinkLabels[type] || type.replaceAll('_', ' ')}</button>)}</div><div className="compare-note">Prices use direct shop menus. Oat latte totals include a listed oat-milk surcharge. A tilde marks an inferred serving size.</div><div className="rank-list">{comparisons.map(({ item, shop, price }, index) => <button className="rank-row" key={item.id} onClick={() => setSelectedShop(shop)}><span className="rank-number">{index + 1}</span><span className="rank-main"><strong>{shop.name}</strong><small>{item.name} · {neighborhood(shop)}</small><Rating value={shop.rating} count={shop.review_count} /></span><span className="rank-price"><strong>{formatPrice(price)}</strong>{item.size_oz ? <small>{item.size_confidence === 'inferred' ? '~' : ''}{money.format(price / 100 / item.size_oz)}/oz</small> : <small>size unlisted</small>}</span></button>)}{!comparisons.length && <div className="empty"><Coffee aria-hidden="true" /><h2>No comparable prices yet</h2><p>This fills in as direct menus are collected.</p></div>}</div></main>}
    {view === 'map' && <main className="map-shell"><div className="map-caption"><div><p>{metro === 'milwaukee' ? 'Milwaukee' : 'Twin Cities'}</p><h1>Every cup on the map</h1></div><span>{visibleShops.length} locations</span></div><MapView shops={visibleShops} metro={metro} onOpen={setSelectedShop} /></main>}
    <nav className="mobile-nav" aria-label="Main navigation"><button className={view === 'shops' ? 'active' : ''} onClick={() => setView('shops')}><List aria-hidden="true" /><span>Shops</span></button><button className={view === 'compare' ? 'active' : ''} onClick={() => setView('compare')}><Coffee aria-hidden="true" /><span>Compare</span></button><button className={view === 'map' ? 'active' : ''} onClick={() => setView('map')}><MapIcon aria-hidden="true" /><span>Map</span></button></nav>
  </div>;
}
