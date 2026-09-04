'use client';

import { MapContainer, Marker, TileLayer, useMap } from 'react-leaflet';
import L from 'leaflet';
import 'leaflet.markercluster';
import { useEffect, useMemo } from 'react';
import { shopDrink, type Item, type Shop } from '@/lib/coffee-data';
import 'leaflet/dist/leaflet.css';
import 'leaflet.markercluster/dist/MarkerCluster.css';

const money = new Intl.NumberFormat('en-US', { style: 'currency', currency: 'USD' });
const priceIcon = (price: number) => L.divIcon({ className: 'coffee-marker pmk', html: money.format(price / 100), iconSize: [40, 19], iconAnchor: [20, 10], popupAnchor: [0, -12] });
const unpricedIcon = L.divIcon({ className: 'coffee-marker pmk no', html: '', iconSize: [9, 9], iconAnchor: [4, 4], popupAnchor: [0, -12] });
const clusterIcon = (cluster: L.MarkerCluster) => L.divIcon({ className: 'coffee-cluster pcl', html: `<span>${cluster.getChildCount()}</span>`, iconSize: [28, 28], iconAnchor: [14, 14] });
const youIcon = L.divIcon({ className: 'you-marker pyou', html: '', iconSize: [13, 13], iconAnchor: [6, 6] });
const centers = { milwaukee: [43.0389, -87.9065] as [number, number], twin_cities: [44.9537, -93.09] as [number, number] };

function Recenter({ metro, user }: { metro: keyof typeof centers; user: { lat: number; lng: number } | null }) {
  const map = useMap();
  useEffect(() => {
    if (user) {
      const center = centers[metro];
      // Rough miles: when the active metro is far from the user, the metro
      // toggle was tapped by hand, so show that metro instead of the user.
      const milesAway = Math.hypot((user.lat - center[0]) * 69, (user.lng - center[1]) * 54);
      if (milesAway > 50) { map.setView(center, metro === 'milwaukee' ? 12 : 10); return; }
      map.setView([user.lat, user.lng], 13);
      return;
    }
    map.setView(centers[metro], metro === 'milwaukee' ? 12 : 10);
  }, [map, metro, user]);
  return null;
}

function Clusters({ shops, drinkByShop, onOpen }: { shops: Shop[]; drinkByShop: Map<number, { price: number | null; label: string }>; onOpen: (shop: Shop) => void }) {
  const map = useMap();
  useEffect(() => {
    const group = L.markerClusterGroup({ iconCreateFunction: clusterIcon, maxClusterRadius: 40, showCoverageOnHover: false });
    const layers: L.Marker[] = [];
    for (const shop of shops) {
      if (shop.lat == null || shop.lng == null) continue;
      const drink = drinkByShop.get(shop.id);
      const priced = drink && drink.price != null;
      const m = L.marker([shop.lat, shop.lng], { icon: priced ? priceIcon(drink!.price as number) : unpricedIcon, zIndexOffset: priced ? 400 : 0 });
      const price = priced ? `<span class="popup-price">${drink!.label} <strong>${money.format((drink!.price as number) / 100)}</strong></span>` : '';
      const el = document.createElement('div');
      el.className = 'map-popup';
      el.innerHTML = `<strong></strong><span></span>${price}<button type="button">See menu</button>`;
      (el.querySelector('strong') as HTMLElement).textContent = shop.name;
      (el.querySelector('span:not(.popup-price)') as HTMLElement).textContent = shop.neighborhood || shop.address || 'Location mapped';
      el.querySelector('button')!.addEventListener('click', () => onOpen(shop));
      m.bindPopup(el);
      layers.push(m);
    }
    group.addLayers(layers);
    map.addLayer(group);
    return () => { map.removeLayer(group); };
  }, [map, shops, drinkByShop, onOpen]);
  return null;
}

export default function CoffeeMap({ shops, items, metro, user, onOpen }: { shops: Shop[]; items: Item[]; metro: keyof typeof centers; user: { lat: number; lng: number } | null; onOpen: (shop: Shop) => void }) {
  const drinkByShop = useMemo(() => {
    const menuByShop = new Map<number, Item[]>();
    for (const item of items) {
      if (item.current_price_cents == null) continue;
      const list = menuByShop.get(item.shop_id);
      if (list) list.push(item); else menuByShop.set(item.shop_id, [item]);
    }
    const map = new Map<number, { price: number | null; label: string }>();
    for (const [id, menu] of menuByShop) { const drink = shopDrink(menu); map.set(id, { price: drink.price, label: drink.label }); }
    return map;
  }, [items]);
  return <MapContainer center={centers[metro]} zoom={metro === 'milwaukee' ? 12 : 10} scrollWheelZoom className="coffee-map" zoomControl>
    <Recenter metro={metro} user={user} />
    <TileLayer attribution='Tiles &copy; Esri &mdash; Esri, HERE, Garmin &copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors' url="https://server.arcgisonline.com/ArcGIS/rest/services/Canvas/World_Light_Gray_Base/MapServer/tile/{z}/{y}/{x}" detectRetina maxZoom={19} />
    {user && <Marker position={[user.lat, user.lng]} icon={youIcon} />}
    <Clusters shops={shops} drinkByShop={drinkByShop} onOpen={onOpen} />
  </MapContainer>;
}
