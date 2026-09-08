from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from typing import Optional
import sqlite3, hashlib, math, json, os, csv, urllib.parse, urllib.request
from datetime import datetime, timezone


DB = os.path.join(os.path.dirname(__file__), "abhaya.db")
NEWS_CSV = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data", "crime_news_final_2026_city_proper.csv")
NCRB_CSV = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data", "ncrb_historical_2022_2023.csv")
RELIABLE_SOURCES = {
    "The Indian Express": 1.0,
    "The Times of India": 0.95,
    "The New Indian Express": 1.0,
    "Hindustan Times": 0.95,
    "India Today": 0.95,
    "Onmanorama": 0.90,
}

app = FastAPI(title="Abhaya Safety API", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

def db():
    conn = sqlite3.connect(DB)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    conn = db()
    cur = conn.cursor()
    cur.execute("""CREATE TABLE IF NOT EXISTS users(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL,
        email TEXT UNIQUE NOT NULL,
        password TEXT NOT NULL,
        emergency_contact TEXT DEFAULT ''
    )""")
    cur.execute("""CREATE TABLE IF NOT EXISTS incidents(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER,
        incident_id TEXT UNIQUE,
        city TEXT DEFAULT '',
        incident_date TEXT,
        reported_date TEXT,
        lat REAL NOT NULL, lon REAL NOT NULL,
        type TEXT NOT NULL,
        severity INTEGER DEFAULT 3,
        location_text TEXT DEFAULT '',
        description TEXT DEFAULT '',
        source TEXT DEFAULT 'User Report',
        source_url TEXT DEFAULT '',
        geographic_scope TEXT DEFAULT '',
        coordinate_status TEXT DEFAULT '',
        coordinate_source TEXT DEFAULT '',
        geocoded_place TEXT DEFAULT '',
        source_weight REAL DEFAULT 1.0,
        created_at TEXT NOT NULL
    )""")
    # Migrate databases created by earlier versions of Abhaya.
    existing = {r[1] for r in cur.execute("PRAGMA table_info(incidents)").fetchall()}
    migrations = {
        "user_id":"INTEGER",
        "incident_id":"TEXT", "city":"TEXT DEFAULT ''", "incident_date":"TEXT",
        "reported_date":"TEXT", "severity":"INTEGER DEFAULT 3", "location_text":"TEXT DEFAULT ''",
        "source":"TEXT DEFAULT 'User Report'", "source_url":"TEXT DEFAULT ''",
        "geographic_scope":"TEXT DEFAULT ''", "coordinate_status":"TEXT DEFAULT ''",
        "coordinate_source":"TEXT DEFAULT ''", "geocoded_place":"TEXT DEFAULT ''",
        "source_weight":"REAL DEFAULT 1.0"
    }
    for col, typ in migrations.items():
        if col not in existing:
            cur.execute(f"ALTER TABLE incidents ADD COLUMN {col} {typ}")
    cur.execute("""CREATE TABLE IF NOT EXISTS drivers(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL, rating REAL DEFAULT 4.5,
        safety_rating REAL DEFAULT 4.5, vehicle TEXT NOT NULL,
        plate TEXT NOT NULL, price_per_km REAL DEFAULT 18,
        available INTEGER DEFAULT 1, lat REAL, lon REAL
    )""")
    cur.execute("""CREATE TABLE IF NOT EXISTS rides(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER, driver_id INTEGER, pickup TEXT,
        destination TEXT, distance REAL, fare REAL,
        provider TEXT DEFAULT 'Abhaya',
        status TEXT DEFAULT 'Booked',
        created_at TEXT NOT NULL
    )""")
    cur.execute("""CREATE TABLE IF NOT EXISTS feedback(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        ride_id INTEGER, driver_id INTEGER,
        rating INTEGER, safety INTEGER, behavior INTEGER,
        driving INTEGER, comment TEXT DEFAULT '',
        created_at TEXT NOT NULL
    )""")

    if cur.execute("SELECT COUNT(*) FROM drivers").fetchone()[0] == 0:
        drivers = [
            ("Ravi Kumar",4.8,4.9,"Swift Dzire","AP 07 AB 1234",18,1,16.305,80.438),
            ("Arjun Reddy",4.7,4.8,"Hyundai Aura","AP 07 CD 5678",19,1,16.312,80.430),
            ("Sandeep Rao",4.9,4.9,"Toyota Etios","AP 07 EF 9012",20,1,16.298,80.446),
            ("Kiran Kumar",4.6,4.7,"Maruti Ertiga","AP 07 GH 3456",17,1,16.318,80.451),
        ]
        cur.executemany("""INSERT INTO drivers
            (name,rating,safety_rating,vehicle,plate,price_per_km,available,lat,lon)
            VALUES (?,?,?,?,?,?,?,?,?)""", drivers)

    # Keep a small set of clearly-labelled demo incidents for offline/demo use.
    if cur.execute("SELECT COUNT(*) FROM incidents WHERE source='Demo' OR source='User Report'").fetchone()[0] == 0 and cur.execute("SELECT COUNT(*) FROM incidents").fetchone()[0] == 0:
        demo = [
            ("DEMO-001", "Demo City", 16.305,80.438,"Harassment","Demo-only safety report near a busy junction."),
            ("DEMO-002", "Demo City", 16.310,80.432,"Stalking","Demo-only stalking report."),
            ("DEMO-003", "Demo City", 16.298,80.446,"Poor lighting","Demo-only lighting complaint."),
        ]
        cur.executemany("""INSERT INTO incidents(incident_id,city,lat,lon,type,severity,description,source,source_weight,created_at)
            VALUES(?,?,?,?,?,?,?,?,?,?)""", [(a,b,c,d,e,2,f,"Demo",0.5,datetime.now(timezone.utc).isoformat()) for a,b,c,d,e,f in demo])

    # Import the curated newspaper incident dataset once. The CSV carries source,
    # URL, dates, locality and coordinate provenance for every record.
    if os.path.exists(NEWS_CSV):
        imported = 0
        with open(NEWS_CSV, newline='', encoding='utf-8-sig') as fh:
            for r in csv.DictReader(fh):
                iid = (r.get('incident_id') or '').strip()
                if not iid:
                    continue
                exists = cur.execute("SELECT 1 FROM incidents WHERE incident_id=?", (iid,)).fetchone()
                if exists:
                    continue
                try:
                    lat=float(r.get('latitude') or 0); lon=float(r.get('longitude') or 0)
                    if not (-90 <= lat <= 90 and -180 <= lon <= 180):
                        continue
                    sev=max(1,min(5,int(float(r.get('severity') or 3))))
                except ValueError:
                    continue
                source=(r.get('source') or 'Unknown').strip()
                weight=RELIABLE_SOURCES.get(source, 0.85)
                cur.execute("""INSERT INTO incidents(incident_id,city,incident_date,reported_date,lat,lon,type,severity,location_text,description,source,source_url,geographic_scope,coordinate_status,coordinate_source,geocoded_place,source_weight,created_at)
                    VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""", (
                    iid, r.get('city',''), r.get('incident_date') or None, r.get('reported_date') or None,
                    lat, lon, r.get('crime_type','Other'), sev, r.get('location_text',''), r.get('description',''),
                    source, r.get('source_url',''), r.get('geographic_scope',''), r.get('coordinate_status',''),
                    r.get('coordinate_source',''), r.get('geocoded_place',''), weight,
                    r.get('reported_date') or datetime.now(timezone.utc).isoformat()
                ))
                imported += 1
        if imported:
            print(f"Imported {imported} curated news incidents into Abhaya database.")

    # NCRB is retained as a city-level historical baseline, not a street-level point.
    cur.execute("""CREATE TABLE IF NOT EXISTS city_baselines(
        id INTEGER PRIMARY KEY AUTOINCREMENT, city TEXT NOT NULL, year INTEGER NOT NULL,
        rape_cases INTEGER, rape_rate REAL, assault_cases INTEGER, assault_rate REAL,
        kidnapping_cases INTEGER, kidnapping_rate REAL, total_crime_cases INTEGER, total_crime_rate REAL,
        UNIQUE(city,year)
    )""")
    if os.path.exists(NCRB_CSV) and cur.execute("SELECT COUNT(*) FROM city_baselines").fetchone()[0] == 0:
        with open(NCRB_CSV, newline='', encoding='utf-8-sig') as fh:
            for r in csv.DictReader(fh):
                city=(r.get('city') or '').strip()
                try:
                    cur.execute("""INSERT OR IGNORE INTO city_baselines(city,year,rape_cases,rape_rate,assault_cases,assault_rate,kidnapping_cases,kidnapping_rate,total_crime_cases,total_crime_rate)
                        VALUES(?,?,?,?,?,?,?,?,?,?)""", (city,int(r['year']),int(float(r['rape_cases'])),float(r['rape_rate']),int(float(r['assault_cases'])),float(r['assault_rate']),int(float(r['kidnapping_cases'])),float(r['kidnapping_rate']),int(float(r['total_crime_cases'])),float(r['total_crime_rate'])))
                except (KeyError,ValueError):
                    pass

    conn.commit()
    conn.close()

init_db()

class Register(BaseModel):
    name: str
    email: str
    password: str = Field(min_length=4)
    emergency_contact: str = ""

class Login(BaseModel):
    email: str
    password: str

class Incident(BaseModel):
    user_id: Optional[int] = None
    lat: float
    lon: float
    type: str
    description: str = ""
    city: str = ""

class RideRequest(BaseModel):
    user_id: Optional[int] = None
    driver_id: Optional[int] = None
    pickup: str
    destination: str
    distance: float
    provider: str = "Abhaya"

class Feedback(BaseModel):
    ride_id: int
    driver_id: int
    rating: int = Field(ge=1, le=5)
    safety: int = Field(ge=1, le=5)
    behavior: int = Field(ge=1, le=5)
    driving: int = Field(ge=1, le=5)
    comment: str = ""

def hash_pw(p): return hashlib.sha256(p.encode()).hexdigest()

@app.get("/")
def root():
    return {"name":"Abhaya Safety API","status":"online"}

@app.post("/api/auth/register")
def register(x: Register):
    conn=db()
    try:
        cur=conn.execute("INSERT INTO users(name,email,password,emergency_contact) VALUES(?,?,?,?)",
                         (x.name,x.email.lower(),hash_pw(x.password),x.emergency_contact))
        conn.commit()
        return {"id":cur.lastrowid,"name":x.name,"email":x.email.lower()}
    except sqlite3.IntegrityError:
        raise HTTPException(409,"An account with this email already exists.")
    finally: conn.close()

@app.post("/api/auth/login")
def login(x: Login):
    conn=db()
    row=conn.execute("SELECT id,name,email,emergency_contact FROM users WHERE email=? AND password=?",
                     (x.email.lower(),hash_pw(x.password))).fetchone()
    conn.close()
    if not row: raise HTTPException(401,"Invalid email or password.")
    return dict(row)

@app.get("/api/incidents")
def incidents(city: Optional[str] = None, limit: int = 200):
    conn=db()
    public_columns="id,incident_id,city,incident_date,reported_date,lat,lon,type,severity,location_text,description,source,source_url,geographic_scope,coordinate_status,coordinate_source,geocoded_place,source_weight,created_at"
    if city:
        rows=conn.execute(f"SELECT {public_columns} FROM incidents WHERE lower(city)=lower(?) ORDER BY COALESCE(reported_date,created_at) DESC LIMIT ?", (city,limit)).fetchall()
    else:
        rows=conn.execute(f"SELECT {public_columns} FROM incidents ORDER BY COALESCE(reported_date,created_at) DESC LIMIT ?", (limit,)).fetchall()
    conn.close()
    return [dict(r) for r in rows]

@app.post("/api/incidents")
def add_incident(x: Incident):
    # User reports are tied to the logged-in account so the reporter can view
    # only their own incident history later.
    conn=db()
    cur=conn.execute("""INSERT INTO incidents(user_id,incident_id,city,lat,lon,type,severity,description,source,source_weight,created_at)
                        VALUES(?,?,?,?,?,?,?,?,?,?,?)""",
                     (x.user_id,None,x.city,x.lat,x.lon,x.type,3,x.description,"User Report",1.0,datetime.now(timezone.utc).isoformat()))
    conn.commit(); new_id=cur.lastrowid; conn.close()
    return {"id":new_id,"message":"Incident reported successfully."}

@app.get("/api/incidents/user/{user_id}")
def user_incident_history(user_id: int, limit: int = 100):
    conn=db()
    rows=conn.execute("""SELECT id,city,lat,lon,type,severity,description,source,created_at
                         FROM incidents
                         WHERE user_id=? AND source='User Report'
                         ORDER BY id DESC LIMIT ?""", (user_id, limit)).fetchall()
    conn.close()
    return [dict(r) for r in rows]

def distance_km(a,b,c,d):
    R=6371
    p1,p2=math.radians(a),math.radians(c)
    dp=math.radians(c-a); dl=math.radians(d-b)
    h=math.sin(dp/2)**2+math.cos(p1)*math.cos(p2)*math.sin(dl/2)**2
    return R*2*math.atan2(math.sqrt(h),math.sqrt(1-h))

@app.get("/api/zones")
def zones(city: Optional[str] = None):
    conn=db()
    if city:
        rows=conn.execute("SELECT lat,lon,type,severity,incident_date,reported_date,source_weight FROM incidents WHERE lower(city)=lower(?)",(city,)).fetchall()
    else:
        rows=conn.execute("SELECT lat,lon,type,severity,incident_date,reported_date,source_weight FROM incidents").fetchall()
    conn.close()
    # Grid cells are presentation zones. Risk is weighted by severity, source
    # confidence and recency; this is a prototype risk estimate, not a safety guarantee.
    cells={}
    now=datetime.now(timezone.utc)
    for r in rows:
        key=(round(r["lat"],2),round(r["lon"],2))
        try:
            ds=r["incident_date"] or r["reported_date"]
            age=(now-datetime.fromisoformat(ds).replace(tzinfo=timezone.utc)).days if ds else 365
        except Exception:
            age=365
        recency=1.0 if age<=30 else 0.8 if age<=90 else 0.6 if age<=180 else 0.4
        sev=max(1,min(5,int(r["severity"] or 3)))
        contribution=sev*recency*float(r["source_weight"] or 1.0)
        cells.setdefault(key,{"risk":0.0,"count":0})
        cells[key]["risk"]+=contribution
        cells[key]["count"]+=1
    result=[]
    for (lat,lon),v in cells.items():
        risk=v["risk"]
        level="green" if risk<2.5 else "yellow" if risk<5 else "red" if risk<8 else "black"
        radius=420 if level=="green" else 480 if level=="yellow" else 550 if level=="red" else 620
        result.append({"lat":lat,"lon":lon,"count":v["count"],"risk_score":round(risk,2),"level":level,"radius":radius})
    return result

@app.get("/api/safety-score")
def safety_score(lat: float, lon: float):
    conn=db()
    rows=conn.execute("SELECT lat,lon,severity,incident_date,reported_date,source_weight FROM incidents").fetchall()
    conn.close()
    now=datetime.now(timezone.utc); risk=0.0; nearby=0
    for r in rows:
        d=distance_km(lat,lon,r["lat"],r["lon"])
        if d<=2.0:
            nearby+=1
            try:
                ds=r["incident_date"] or r["reported_date"]
                age=(now-datetime.fromisoformat(ds).replace(tzinfo=timezone.utc)).days if ds else 365
            except Exception:
                age=365
            recency=1.0 if age<=30 else 0.8 if age<=90 else 0.6 if age<=180 else 0.4
            sev=max(1,min(5,int(r["severity"] or 3)))
            risk += (sev*recency*float(r["source_weight"] or 1.0))*max(0.0,1-d/2.0)
    score=round(max(0,min(100,100-risk*8)),1)
    level="Green" if score>=75 else "Yellow" if score>=50 else "Red" if score>=25 else "Black"
    return {"score":score,"level":level,"nearby_incidents":nearby,"risk_weight":round(risk,2)}


def incident_risk_at(lat: float, lon: float, conn) -> float:
    rows=conn.execute("SELECT lat,lon,severity,incident_date,reported_date,source_weight FROM incidents").fetchall()
    now=datetime.now(timezone.utc); risk=0.0
    for r in rows:
        d=distance_km(lat,lon,r["lat"],r["lon"])
        if d <= 1.5:
            try:
                ds=r["incident_date"] or r["reported_date"]
                age=(now-datetime.fromisoformat(ds).replace(tzinfo=timezone.utc)).days if ds else 365
            except Exception:
                age=365
            recency=1.0 if age<=30 else 0.8 if age<=90 else 0.6 if age<=180 else 0.4
            sev=max(1,min(5,int(r["severity"] or 3)))
            risk += sev*recency*float(r["source_weight"] or 1.0)*max(0,1-d/1.5)
    return risk

INDIA_BOUNDS = {"min_lat": 6.0, "max_lat": 37.5, "min_lon": 68.0, "max_lon": 98.5}

def in_india_bounds(lat: float, lon: float) -> bool:
    return (INDIA_BOUNDS["min_lat"] <= lat <= INDIA_BOUNDS["max_lat"] and
            INDIA_BOUNDS["min_lon"] <= lon <= INDIA_BOUNDS["max_lon"])

@app.get("/api/routes")
def routes(city: str, start_lat: float, start_lon: float, dest_lat: float, dest_lon: float):
    """Get Indian road alternatives from OSRM and score them using Abhaya safety data."""
    if not in_india_bounds(start_lat, start_lon) or not in_india_bounds(dest_lat, dest_lon):
        raise HTTPException(400, "Abhaya currently supports routes within India only.")
    params=f"overview=full&geometries=geojson&alternatives=true&steps=false"
    url=("https://router.project-osrm.org/route/v1/driving/"
         f"{start_lon},{start_lat};{dest_lon},{dest_lat}?{params}")
    try:
        with urllib.request.urlopen(url, timeout=15) as resp:
            data=json.loads(resp.read().decode("utf-8"))
    except Exception as exc:
        raise HTTPException(502, f"Routing service unavailable: {exc}")
    if data.get("code") != "Ok" or not data.get("routes"):
        raise HTTPException(502, "No road route was returned.")
    conn=db(); scored=[]
    try:
        for idx,r in enumerate(data["routes"][:3],1):
            coords=r.get("geometry",{}).get("coordinates",[])
            if not coords: continue
            # Sample up to 30 points to keep scoring fast.
            step=max(1,len(coords)//30); samples=coords[::step]
            if samples[-1] != coords[-1]: samples.append(coords[-1])
            risks=[incident_risk_at(lat,lon,conn) for lon,lat in samples]
            mean=sum(risks)/len(risks); peak=max(risks)
            risk_score=round(min(100, mean*9 + peak*4),1)
            safety_score=round(max(0,100-risk_score),1)
            segments=[]
            for a,b in zip(samples[:-1],samples[1:]):
                lon=(a[0]+b[0])/2; lat=(a[1]+b[1])/2; rr=incident_risk_at(lat,lon,conn)
                zone="safe" if rr<2.5 else "moderate" if rr<5 else "unsafe"
                segments.append({"start":[a[0],a[1]],"end":[b[0],b[1]],"risk":round(rr,2),"zone":zone,"safety_score":round(max(0,100-rr*12),1)})
            scored.append({"route_id":idx,"distance_km":round(r.get("distance",0)/1000,2),"duration_min":round(r.get("duration",0)/60,1),"safety_score":safety_score,"risk_score":risk_score,"geometry":r["geometry"],"segments":segments})
    finally: conn.close()
    if not scored: raise HTTPException(502,"No usable route geometry was returned.")
    fastest=min(scored,key=lambda x:x["duration_min"]); safest=max(scored,key=lambda x:x["safety_score"]); highest=min(scored,key=lambda x:x["safety_score"])
    return {"city":city,"start":{"latitude":start_lat,"longitude":start_lon},"destination":{"latitude":dest_lat,"longitude":dest_lon},"routes_available":len(scored),"routes":scored,"fastest_route":fastest,"safest_route":safest,"highest_risk_route":highest,"model_note":"Prototype route-risk estimate using geocoded news incidents and user reports. It is not a guarantee of safety."}

@app.get("/api/drivers")
def drivers():
    conn=db()
    rows=conn.execute("SELECT * FROM drivers WHERE available=1 ORDER BY safety_rating DESC").fetchall()
    conn.close()
    return [dict(r) for r in rows]

@app.post("/api/rides")
def book_ride(x: RideRequest):
    if x.provider != "Abhaya":
        return {"external":True,"provider":x.provider,
                "message":f"{x.provider} booking should be completed through its official app/API."}
    conn=db()
    driver_id=x.driver_id
    if not driver_id:
        row=conn.execute("SELECT id FROM drivers WHERE available=1 ORDER BY safety_rating DESC LIMIT 1").fetchone()
        driver_id=row["id"] if row else None
    fare=round(x.distance*18+35,2)
    cur=conn.execute("""INSERT INTO rides(user_id,driver_id,pickup,destination,distance,fare,provider,status,created_at)
                        VALUES(?,?,?,?,?,?,?,?,?)""",
                     (x.user_id,driver_id,x.pickup,x.destination,x.distance,fare,x.provider,"Booked",datetime.utcnow().isoformat()))
    conn.commit(); ride_id=cur.lastrowid
    conn.close()
    return {"ride_id":ride_id,"driver_id":driver_id,"fare":fare,"status":"Booked"}

@app.get("/api/rides/{user_id}")
def ride_history(user_id:int):
    conn=db()
    rows=conn.execute("""SELECT rides.*,drivers.name driver_name,drivers.vehicle,drivers.plate
                         FROM rides LEFT JOIN drivers ON rides.driver_id=drivers.id
                         WHERE rides.user_id=? ORDER BY rides.id DESC""",(user_id,)).fetchall()
    conn.close()
    return [dict(r) for r in rows]

@app.post("/api/feedback")
def add_feedback(x: Feedback):
    conn=db()
    conn.execute("""INSERT INTO feedback(ride_id,driver_id,rating,safety,behavior,driving,comment,created_at)
                    VALUES(?,?,?,?,?,?,?,?)""",
                 (x.ride_id,x.driver_id,x.rating,x.safety,x.behavior,x.driving,x.comment,datetime.utcnow().isoformat()))
    conn.execute("""UPDATE drivers SET rating=(SELECT AVG(rating) FROM feedback WHERE driver_id=?),
                    safety_rating=(SELECT AVG(safety) FROM feedback WHERE driver_id=?)
                    WHERE id=?""",(x.driver_id,x.driver_id,x.driver_id))
    conn.commit(); conn.close()
    return {"message":"Thank you. Your feedback improves the Abhaya safety system."}

@app.get("/api/nearby")
def nearby(lat:float,lon:float):
    # Demo nearby facilities. Replace with OSM Overpass/Google Places in production.
    places=[
        {"name":"Abhaya Police Support Point","type":"police","lat":lat+0.004,"lon":lon+0.003},
        {"name":"City Emergency Hospital","type":"hospital","lat":lat-0.005,"lon":lon+0.006},
        {"name":"Central Police Station","type":"police","lat":lat+0.008,"lon":lon-0.004},
        {"name":"24/7 Medical Centre","type":"hospital","lat":lat-0.007,"lon":lon-0.003},
    ]
    for p in places: p["distance_km"]=round(distance_km(lat,lon,p["lat"],p["lon"]),2)
    return places
