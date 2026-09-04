'use client';
import { MapContainer, Marker, Popup, TileLayer, useMap } from 'react-leaflet';
import L from 'leaflet';
import { useEffect } from 'react';
import type { Shop } from '@/lib/coffee-data';
import 'leaflet/dist/leaflet.css';
const marker = L.divIcon({ className: 'coffee-marker', html: '<span>●</span>', iconSize: [28, 28], iconAnchor: [14, 14], popupAnchor: [0, -12] });
const centers = { milwaukee: [43.0389, -87.9065] as [number, number], twin_cities: [44.9537, -93.09] as [number, number] };
function Recenter({ metro }: { metro: keyof typeof centers }) { const map = useMap(); useEffect(() => { map.setView(centers[metro], metro === 'milwaukee' ? 12 : 10); }, [map, metro]); return null; }
export default function CoffeeMap({ shops, metro, onOpen }: { shops: Shop[]; metro: keyof typeof centers; onOpen: (shop: Shop) => void }) { return <MapContainer center={centers[metro]} zoom={metro === 'milwaukee' ? 12 : 10} scrollWheelZoom className="coffee-map" zoomControl><Recenter metro={metro} /><TileLayer attribution='&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap contributors</a>' url="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png" detectRetina maxZoom={19} />{shops.filter((shop) => shop.lat != null && shop.lng != null).map((shop) => <Marker key={shop.id} position={[shop.lat as number, shop.lng as number]} icon={marker}><Popup><div className="map-popup"><strong>{shop.name}</strong><span>{shop.neighborhood || shop.address || 'Location mapped'}</span><button onClick={() => onOpen(shop)}>See menu</button></div></Popup></Marker>)}</MapContainer>; }
