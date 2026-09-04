-- classify_name in scripts/collect.py gained a "caramel_latte" drink kind
-- (PR #4); allow it in the coffee.items drink_type check constraint.
alter table coffee.items drop constraint items_drink_type_check;
alter table coffee.items add constraint items_drink_type_check
  check (drink_type = any (array['latte','cappuccino','espresso','americano','drip','cold_brew','mocha','tea','chai','caramel_latte','other']::text[]));
