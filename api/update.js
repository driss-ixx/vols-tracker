// api/update.js — Vercel Serverless Function
// Appelée chaque jour à 5h par Vercel Cron
// Récupère les prix Google Flights via SerpAPI → stocke dans Supabase

import { createClient } from '@supabase/supabase-js';

const SUPABASE_URL    = process.env.SUPABASE_URL;
const SUPABASE_KEY    = process.env.SUPABASE_SERVICE_KEY;
const SERPAPI_KEY     = process.env.SERPAPI_KEY;
const CRON_SECRET     = process.env.CRON_SECRET;

// Paramètres du vol
const PARAMS = {
  engine: 'google_flights',
  departure_id: 'PAR',
  arrival_id: 'RAI',
  outbound_date: '2026-05-06',
  return_date: '2026-05-13',
  currency: 'EUR',
  hl: 'fr',
  type: '1',        // 1 = aller-retour
  adults: '1',
  sort_by: '1',     // 1 = par prix
  stops: '0',       // 0 = tous
  api_key: '',      // injecté dynamiquement
};

async function fetchFlights() {
  const params = new URLSearchParams({ ...PARAMS, api_key: SERPAPI_KEY });
  const res = await fetch(`https://serpapi.com/search.json?${params}`);
  if (!res.ok) throw new Error(`SerpAPI error ${res.status}: ${await res.text()}`);
  return res.json();
}

function parseResult(data) {
  const results = [];

  // Vols "best_flights" (les meilleurs)
  const allOffers = [
    ...(data.best_flights || []),
    ...(data.other_flights || []),
  ];

  allOffers.forEach((offer, i) => {
    const flights = offer.flights || [];
    if (!flights.length) return;

    const first = flights[0];
    const last = flights[flights.length - 1];
    const stops = flights.length - 1;

    const stopAirports = flights
      .slice(0, -1)
      .map(f => f.arrival_airport?.id || '')
      .filter(Boolean)
      .join(' + ');

    const stopTxt = stops === 0
      ? 'Direct'
      : `${stops} escale${stops > 1 ? 's' : ''} · ${stopAirports}`;

    // Retour
    const retFlights = offer.layovers || [];
    const retTxt = offer.return_flight
      ? `${offer.return_flight.departure_airport?.id} ${offer.return_flight.departure_time} > ${offer.return_flight.arrival_airport?.id} ${offer.return_flight.arrival_time}`
      : 'Voir Google Flights';

    // Durée en minutes
    const totalDur = offer.total_duration || 0;
    const durH = Math.floor(totalDur / 60);
    const durM = totalDur % 60;
    const durTxt = `${durH}h${durM.toString().padStart(2, '0')}`;

    const airlines = [...new Set(flights.map(f => f.airline))].join('+');

    results.push({
      rank: i + 1,
      airline: airlines,
      code: flights[0]?.airline_logo ? airlines.slice(0, 2).toUpperCase() : 'XX',
      dep: first.departure_airport?.time?.slice(0, 5) || '',
      arr: last.arrival_airport?.time?.slice(0, 5) || '',
      depA: first.departure_airport?.id || 'PAR',
      arrA: last.arrival_airport?.id || 'RAI',
      dur: durTxt,
      dur_min: totalDur,
      stops,
      stop_txt: stopTxt,
      price: offer.price,
      ret: retTxt,
      source: 'Google Flights via SerpAPI',
      url: 'https://www.google.com/travel/flights/search?tfs=CBwQAhoeEgoyMDI2LTA1LTA2agcIARIDUEFScgcIARIDUkFJGh4SCjIwMjYtMDUtMTNqBwgBEgNSQUlyBwgBEgNQQVIiASoqAggBQgIIAUgB&hl=fr&curr=EUR',
      best: i === 0,
      offer_id: `serp_${Date.now()}_${i}`,
      updated_at: new Date().toISOString(),
    });
  });

  return results.sort((a, b) => a.price - b.price).slice(0, 10);
}

export default async function handler(req, res) {
  const authHeader = req.headers['authorization'];
  if (authHeader !== `Bearer ${CRON_SECRET}`) {
    return res.status(401).json({ error: 'Unauthorized' });
  }

  try {
    const data = await fetchFlights();
    const flights = parseResult(data);

    if (!flights.length) {
      return res.status(200).json({ message: 'No flights parsed', raw: data });
    }

    const sb = createClient(SUPABASE_URL, SUPABASE_KEY);

    // Vider + réinsérer
    await sb.from('vols_praia').delete().neq('id', 0);
    const { error } = await sb.from('vols_praia').insert(flights);
    if (error) throw error;

    // Log
    await sb.from('vols_praia_log').insert({
      updated_at: new Date().toISOString(),
      nb_results: flights.length,
      min_price: flights[0]?.price,
    });

    return res.status(200).json({
      success: true,
      updated: flights.length,
      cheapest: flights[0]?.price + ' EUR',
      at: new Date().toISOString(),
    });

  } catch (err) {
    console.error(err);
    return res.status(500).json({ error: err.message });
  }
}
