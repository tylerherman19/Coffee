alter table coffee.shops add column if not exists neighborhood text;
alter table coffee.shops add column if not exists opening_hours text;
alter table coffee.shops add column if not exists data_source text;
alter table coffee.shops add column if not exists last_checked_at timestamptz;
alter table coffee.shops add column if not exists scrape_status text;
alter table coffee.observations add column if not exists raw jsonb;

create index if not exists idx_coffee_shops_metro on coffee.shops (metro) where closed_at is null;
create index if not exists idx_coffee_items_shop_type on coffee.items (shop_id, drink_type) where removed_at is null;
create index if not exists idx_coffee_observations_item_time on coffee.observations (item_id, observed_at desc);
create index if not exists idx_coffee_changes_time on coffee.price_changes (changed_at desc);

alter view coffee.shop_price_index set (security_invoker = true);

comment on schema coffee is 'Direct-menu coffee and food price snapshots for Milwaukee and the Twin Cities.';
comment on column coffee.items.size_confidence is 'explicit: ounces stated; inferred: mapped from a size word; none: no defensible serving size.';
comment on column coffee.observations.price_channel is 'Collection channel. Public comparisons use direct prices only.';
