-- Créer les tables dans Supabase
-- Coller dans l'éditeur SQL de supabase.com → project iagsrbmeviwmozauhenk

create table if not exists vols_praia (
  id          serial primary key,
  rank        int,
  airline     text,
  code        text,
  dep         text,
  arr         text,
  "depA"      text,
  "arrA"      text,
  dur         text,
  dur_min     int,
  stops       int,
  stop_txt    text,
  price       numeric,
  ret         text,
  source      text,
  url         text,
  best        boolean default false,
  offer_id    text,
  updated_at  timestamptz default now()
);

create table if not exists vols_praia_log (
  id          serial primary key,
  updated_at  timestamptz default now(),
  nb_results  int,
  min_price   numeric
);

-- Accès public en lecture (pour le frontend)
alter table vols_praia enable row level security;
alter table vols_praia_log enable row level security;

create policy "lecture publique vols"
  on vols_praia for select using (true);

create policy "lecture publique log"
  on vols_praia_log for select using (true);
