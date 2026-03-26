// api/update.js — Vercel Serverless Function
// Appelée tous les jours à 5h par Vercel Cron
// Récupère les prix depuis Amadeus API et met à jour Supabase

import { createClient } from '@supabase/supabase-js';

const SUPABASE_URL = process.env.SUPABASE_URL;
const SUPABASE_KEY = process.env.SUPABASE_SERVICE_KEY;
const AMADEUS_KEY  = process.env.AMADEUS_API_KEY;
const AMADEUS_SECRET = process.env.AMADEUS_API_SECRET;
const CRON_SECRET  = process.env.CRON_SECRET;

// Paramètres du vol à surveiller
const SEARCH = {
  originLocationCode: 'PAR',
  destinationLocationCode: 'RAI',
  departureDate: '2026-05-06',
  returnDate: '2026-05-13',
  adults: 1,
  currencyCode: 'EUR',
  max: 15,
};

async function getAmadeusToken() {
  const res = await fetch('https://test.api.amadeus.com/v1/security/oauth2/token', {
    method: 'POST',
    headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
    body: new URLSearchParams({
      grant_type: 'client_credentials',
      client_id: AMADEUS_KEY,
      client_secret: AMADEUS_SECRET,
    }),
  });
  const data = await res.json();
  return data.access_token;
}

async function fetchFlights(token) {
  const params = new URLSearchParams(SEARCH);
  const res = await fetch(
    `https://test.api.amadeus.com/v2/shopping/flight-offers?${params}`,
    { headers: { Authorization: `Bearer ${token}` } }
  );
  return res.json();
}

function parseOffer(offer) {
  const itin = offer.itineraries;
  const aller = itin[0];
  const retour = itin[1];
  const seg0 = aller.segments[0];
  const segLast = aller.segments[aller.segments.length - 1];
  const retSeg0 = retour.segments[0];
  const retSegLast = retour.segments[retour.segments.length - 1];

  const stops = aller.segments.length - 1;
  const stopDetail = stops === 0
    ? 'Direct'
    : aller.segments.slice(0, -1).map(s => s.arrival.iataCode).join(' + ');

  const depTime = seg0.departure.at.slice(11, 16);
  const arrTime = segLast.arrival.at.slice(11, 16);
  const retDepTime = retSeg0.departure.at.slice(11, 16);
  const retArrTime = retSegLast.arrival.at.slice(11, 16);

  // Durée aller
  const durRaw = aller.duration; // PT9H25M
  const durMatch = durRaw.match(/PT(\d+)H(\d+)M/);
  const durMin = durMatch ? parseInt(durMatch[1]) * 60 + parseInt(durMatch[2]) : 0;
  const durTxt = durMatch ? `${durMatch[1]}h${durMatch[2]}` : durRaw;

  const carriers = [...new Set(aller.segments.map(s => s.carrierCode))];
  const price = parseFloat(offer.price.total);

  return {
    airline: carriers.join('+'),
    code: carriers[0],
    dep: depTime,
    arr: arrTime,
    depA: seg0.departure.iataCode,
    arrA: segLast.arrival.iataCode,
    dur: durTxt,
    dur_min: durMin,
    stops,
    stop_txt: stops === 0 ? 'Sans escale' : `${stops} escale(s) · ${stopDetail}`,
    price,
    ret: `${retSeg0.departure.iataCode} ${retDepTime} → ${retSegLast.arrival.iataCode} ${retArrTime}`,
    source: 'Amadeus API',
    updated_at: new Date().toISOString(),
    offer_id: offer.id,
  };
}

export default async function handler(req, res) {
  // Sécurité : vérifier le secret cron (Vercel le passe en header)
  const authHeader = req.headers['authorization'];
  if (authHeader !== `Bearer ${CRON_SECRET}`) {
    return res.status(401).json({ error: 'Unauthorized' });
  }

  try {
    // 1. Token Amadeus
    const token = await getAmadeusToken();

    // 2. Récupérer les offres
    const data = await fetchFlights(token);
    if (!data.data || data.data.length === 0) {
      return res.status(200).json({ message: 'No flights found', raw: data });
    }

    // 3. Parser les offres
    const flights = data.data
      .map(parseOffer)
      .sort((a, b) => a.price - b.price)
      .slice(0, 10);

    // 4. Mettre à jour Supabase
    const sb = createClient(SUPABASE_URL, SUPABASE_KEY);

    // Vider l'ancienne data
    await sb.from('vols_praia').delete().neq('id', 0);

    // Insérer les nouvelles offres
    const { error } = await sb.from('vols_praia').insert(
      flights.map((f, i) => ({ rank: i + 1, ...f }))
    );

    if (error) throw error;

    // Log de la mise à jour
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
