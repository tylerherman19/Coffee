'use client';

// Lieflat Charts (F5 tick rows) adapted to this site's tokens: one row per shop,
// 1 tick = $0.50 of menu price, every fifth tick taller, cheapest cup in accent.
// Tick height/opacity jitter uses a seeded rnd - deterministic, never Math.random().

export type RungEntry = {
  id: string | number;
  name: string;
  sub: string;
  price: number; // cents
};

const TICK_CENTS = 50;

function rnd(seed: number, salt: number) {
  let a = (seed * 2654435761 + salt * 974634) >>> 0;
  a ^= a << 13; a ^= a >>> 17; a ^= a << 5;
  return ((a >>> 0) % 1000) / 1000;
}

const format = new Intl.NumberFormat('en-US', { style: 'currency', currency: 'USD' });

export default function PriceRungChart({ entries, onSelect }: { entries: RungEntry[]; onSelect?: (id: string | number) => void }) {
  if (!entries.length) return null;
  const maxTicks = Math.max(...entries.map((e) => Math.round(e.price / TICK_CENTS)));
  const tickW = 7;
  const gap = 5;
  const width = maxTicks * (tickW + gap) + 8;
  const height = 34;

  return (
    <figure className="rung-chart" aria-label="Price ladder, one tick per fifty cents">
      <figcaption className="rung-note">1 tick = $0.50 · cheapest cup in orange</figcaption>
      <div className="rung-rows">
        {entries.map((entry, row) => {
          const ticks = Math.round(entry.price / TICK_CENTS);
          const lead = row === 0;
          return (
            <button className={`rung-row${lead ? ' lead' : ''}`} key={entry.id} onClick={() => onSelect?.(entry.id)}>
              <span className="rung-label"><strong>{entry.name}</strong><small>{entry.sub}</small></span>
              <svg className="rung-ladder" viewBox={`0 0 ${width} ${height}`} style={{ width: '100%', maxWidth: width }} role="img" aria-label={`${entry.name}, ${format.format(entry.price / 100)}`}>
                <line x1={0} y1={height - 3} x2={width} y2={height - 3} className="rung-floor" />
                {Array.from({ length: ticks }, (_, i) => {
                  const tall = (i + 1) % 5 === 0;
                  const h = (tall ? 22 : 15) + rnd(row + 1, i) * 4;
                  const x = 4 + i * (tickW + gap);
                  const o = 0.62 + rnd(i + 1, row) * 0.38;
                  return <rect key={i} x={x} y={height - 3 - h} width={tickW - 2} height={h} rx={2} className={tall ? 'rung-tick tall' : 'rung-tick'} style={lead ? undefined : { opacity: o }} />;
                })}
              </svg>
              <span className="rung-price"><strong>{format.format(entry.price / 100)}</strong></span>
            </button>
          );
        })}
      </div>
    </figure>
  );
}
