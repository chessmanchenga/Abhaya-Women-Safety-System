# Abhaya incident data and zone methodology

## News incident database

`data/crime_news_final_2026_city_proper.csv` contains 54 curated 2026 incident records. Each record includes:

- incident ID
- city and locality
- incident/report date when available
- crime type and severity (1–5)
- latitude/longitude
- description
- source publication and source URL
- geographic scope
- coordinate status/source

The current dataset uses established Indian news publications including The Indian Express, The New Indian Express, The Times of India, Hindustan Times, India Today and Onmanorama. The app stores the source URL with each record so the incident can be traced back to the published report.

This is a curated research dataset, not a complete national incident registry. News reports can be delayed, duplicated, incomplete, or based on allegations; an article being stored does not mean a court has established guilt.

## NCRB baseline

`data/ncrb_historical_2022_2023.csv` is retained as a city-level historical baseline. It is not converted into street-level incident points. The SQLite database stores it in `city_baselines`.

## How zones are determined

The backend imports the news records into SQLite table `incidents`. Zone risk uses:

1. incident severity;
2. recency of the incident;
3. source confidence weight;
4. geographic proximity.

The `/api/zones` endpoint groups incident points into map cells and returns `green`, `yellow`, `red`, or `black` presentation zones. `/api/safety-score` uses a distance-weighted risk score around the requested location.

These are prototype risk estimates for an academic safety application. They must not be presented as guarantees that a road or area is objectively safe or unsafe.
