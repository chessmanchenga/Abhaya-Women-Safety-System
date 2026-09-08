const API = "http://127.0.0.1:8000/api";
let user = JSON.parse(localStorage.getItem("abhayaUser") || "null");
let position = null, dashMap, mainMap, dashUserMarker, mainUserMarker, zonesLayer, nearbyLayer;
let lastRoutes = [];

function $(id){return document.getElementById(id)}
function toast(msg, good=true){$("toast").textContent=msg;$("toast").className=good?"show good":"show bad";setTimeout(()=>$("toast").className="",3000)}
async function api(path, opts={}){const r=await fetch(API+path,{headers:{"Content-Type":"application/json",...(opts.headers||{})},...opts});let d={};try{d=await r.json()}catch{}if(!r.ok)throw new Error(d.detail||"Request failed");return d}

function showAuth(mode){
  $("loginForm").classList.toggle("hidden",mode!=="login");$("registerForm").classList.toggle("hidden",mode!=="register");
  document.querySelectorAll(".auth-tabs button").forEach((b,i)=>b.classList.toggle("active",(mode==="login"?i===0:i===1)));
}
async function login(e){e.preventDefault();try{user=await api("/auth/login",{method:"POST",body:JSON.stringify({email:$("loginEmail").value,password:$("loginPassword").value})});startApp()}catch(err){toast(err.message,false)}}
async function register(e){e.preventDefault();try{user=await api("/auth/register",{method:"POST",body:JSON.stringify({name:$("regName").value,email:$("regEmail").value,password:$("regPassword").value,emergency_contact:$("regEmergency").value})});toast("Account created. Welcome to Abhaya!");startApp()}catch(err){toast(err.message,false)}}
function demoLogin(){user={id:null,name:"Demo User",email:"demo@abhaya.local",emergency_contact:""};startApp()}
function logout(){localStorage.removeItem("abhayaUser");user=null;location.reload()}
function startApp(){
  localStorage.setItem("abhayaUser",JSON.stringify(user));$("authView").classList.add("hidden");$("appView").classList.remove("hidden");
  const name=user.name||"there";$("userName").textContent=name;$("helloName").textContent=name.split(" ")[0];$("headerName").textContent=name;
  $("avatar").textContent=name[0].toUpperCase();$("headerAvatar").textContent=name[0].toUpperCase();
  setupMaps();loadIncidents();loadDrivers();locateMe();
}
function showPage(page){
  document.querySelectorAll(".page").forEach(p=>p.classList.add("hidden"));$(page).classList.remove("hidden");
  document.querySelectorAll(".nav").forEach(n=>n.classList.toggle("active",n.dataset.page===page));
  const titles={dashboard:"Dashboard",map:"Safety map",routes:"Safer routes",rides:"Book a ride",report:"Report an incident",history:"My history"};$("pageTitle").textContent=titles[page]||"Abhaya";
  if(page==="map"){setTimeout(()=>{if(mainMap)mainMap.invalidateSize()},100)}
  if(page==="history")loadHistory();
}
document.querySelectorAll(".nav[data-page]").forEach(n=>n.onclick=()=>showPage(n.dataset.page));

const INDIA_BOUNDS = [[6.0,68.0],[37.5,98.5]];

function configureIndiaMap(map){
  if(!map)return;
  map.setMaxBounds(INDIA_BOUNDS);
  map.options.maxBoundsViscosity=1.0;
  map.options.minZoom=4;
  map.options.maxZoom=18;
}

function setupMaps(){
  if(!window.L)return;
  dashMap=L.map("dashMap",{minZoom:4,maxZoom:18,maxBounds:INDIA_BOUNDS,maxBoundsViscosity:1.0}).setView([22.5,79.0],5);
  mainMap=L.map("mainMap",{minZoom:4,maxZoom:18,maxBounds:INDIA_BOUNDS,maxBoundsViscosity:1.0}).setView([22.5,79.0],5);
  configureIndiaMap(dashMap);configureIndiaMap(mainMap);
  const tile="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png";
  L.tileLayer(tile,{attribution:"© OpenStreetMap contributors",noWrap:true}).addTo(dashMap);
  L.tileLayer(tile,{attribution:"© OpenStreetMap contributors",noWrap:true}).addTo(mainMap);
}
async function loadIncidents(){
  try{
    const inc=await api("/incidents"); drawIncidents(inc);
    const zones=await api("/zones"); drawZones(zones);
  }catch(e){console.error(e)}
}
function drawIncidents(items){
  [dashMap,mainMap].forEach(map=>{if(!map)return;items.forEach(i=>{L.circleMarker([i.lat,i.lon],{radius:5,color:"#c83f4d",fillOpacity:.7,weight:1}).bindPopup(`<b>${i.type}</b><br>${i.description||""}<br><small>${i.city||""} · ${i.source||"User report"}</small>`).addTo(map)})})
}
function drawZones(zones){
  const colors={green:"#3b9b74",yellow:"#d5a133",red:"#d4505c",black:"#292c31"};
  [dashMap,mainMap].forEach(map=>{if(!map)return;zones.forEach(z=>L.circle([z.lat,z.lon],{radius:z.radius,color:colors[z.level],fillColor:colors[z.level],fillOpacity:.12,weight:2}).bindPopup(`<b>${z.level.toUpperCase()} ZONE</b><br>${z.count} report(s)`).addTo(map))})
}
function locateMe(){
  if(!navigator.geolocation){toast("This browser does not support location.",false);return}
  $("locationStatus").textContent="Requesting live location…";
  navigator.geolocation.getCurrentPosition(async p=>{await updatePosition(p)},()=>{toast("Location permission was denied.",false);$("locationStatus").textContent="Location permission denied."},{enableHighAccuracy:true,timeout:10000});
}
function updatePosition(p){
  position={lat:p.coords.latitude,lon:p.coords.longitude};$("locationStatus").textContent=`Live • ${position.lat.toFixed(4)}, ${position.lon.toFixed(4)}`;$("reportLocation").textContent=`${position.lat.toFixed(4)}, ${position.lon.toFixed(4)}`;
  if(dashUserMarker)dashUserMarker.remove();if(mainUserMarker)mainUserMarker.remove();dashUserMarker=L.marker([position.lat,position.lon]).addTo(dashMap).bindPopup("<b>You are here</b>");mainUserMarker=L.marker([position.lat,position.lon]).addTo(mainMap).bindPopup("<b>You are here</b>");[dashMap,mainMap].forEach(map=>{if(map)map.setView([position.lat,position.lon],14)});
  updateScore();loadNearby();
  navigator.geolocation.watchPosition(q=>{position={lat:q.coords.latitude,lon:q.coords.longitude};if(dashUserMarker)dashUserMarker.setLatLng([position.lat,position.lon]);if(mainUserMarker)mainUserMarker.setLatLng([position.lat,position.lon])},()=>{},{enableHighAccuracy:true});
}
async function updateScore(){if(!position)return;try{const s=await api(`/safety-score?lat=${position.lat}&lon=${position.lon}`);$("score").textContent=s.score;$("scoreBar").style.width=s.score+"%";$("nearbyIncidents").textContent=s.nearby_incidents;const lv=s.level.toLowerCase();$("scoreLevel").textContent=s.level.toUpperCase();$("scoreLevel").className="badge "+lv;$("scoreText").textContent=s.nearby_incidents?`${s.nearby_incidents} safety report(s) within approximately 1 km of you.`:"No recent safety reports nearby."}catch(e){}}
async function loadNearby(){if(!position)return;try{const places=await api(`/nearby?lat=${position.lat}&lon=${position.lon}`);$("policeCount").textContent=places.filter(x=>x.type==="police").length;$("hospitalCount").textContent=places.filter(x=>x.type==="hospital").length;places.forEach(p=>{[dashMap,mainMap].forEach(m=>{if(m)L.marker([p.lat,p.lon]).addTo(m).bindPopup(`<b>${p.name}</b><br>${p.type} • ${p.distance_km} km`)})})}catch(e){}}

async function planRoutes(){
  const dest=$("destination").value.trim();if(!dest)return toast("Enter a destination.",false);
  if(!position)return toast("Allow location access first.",false);
  $("routeResults").innerHTML='<div class="empty">Finding road alternatives and scoring them with Abhaya safety data…</div>';
  try{
    // Restrict destination geocoding to India. This prevents names such as
    // "Hyderabad" from resolving to a place in another country.
    const query = /\bindia\b/i.test(dest) ? dest : `${dest}, India`;
    const geoUrl=`https://nominatim.openstreetmap.org/search?format=jsonv2&addressdetails=1&countrycodes=in&bounded=1&viewbox=68,37.5,98.5,6.0&limit=5&q=${encodeURIComponent(query)}`;
    const geo=await fetch(geoUrl,{headers:{"Accept-Language":"en","User-Agent":"Abhaya-Safety-App/1.0"}}).then(r=>r.json());
    const indianPlace=geo.find(g=>g.address?.country_code?.toLowerCase()==="in");
    if(!indianPlace)throw new Error("Destination not found in India. Please enter an Indian city or place.");
    const dlat=+indianPlace.lat,dlon=+indianPlace.lon;
    const city=indianPlace.address?.city||indianPlace.address?.town||indianPlace.address?.municipality||indianPlace.address?.state||dest;
    const data=await api(`/routes?city=${encodeURIComponent(city)}&start_lat=${position.lat}&start_lon=${position.lon}&dest_lat=${dlat}&dest_lon=${dlon}`);
    lastRoutes=data.routes||[];
    const fastest=data.fastest_route.route_id,safest=data.safest_route.route_id,highest=data.highest_risk_route.route_id;
    $("routeResults").innerHTML="";
    data.routes.forEach(r=>{
      const label=r.route_id===safest&&r.route_id===fastest?"Best overall":r.route_id===safest?"Safest route":r.route_id===fastest?"Fastest route":r.route_id===highest?"Highest risk":"Alternative";
      const el=document.createElement("div");el.className="route-card";
      el.innerHTML=`<div class="route-icon">${label.includes("Safest")||label.includes("Best")?"🛡️":label.includes("risk")?"⚠️":"➤"}</div><div><h3>${label}</h3><p>${r.distance_km.toFixed(1)} km • ${Math.round(r.duration_min)} min • safety ${r.safety_score}/100</p></div><strong>${r.safety_score>=75?"🟢":r.safety_score>=50?"🟡":r.safety_score>=25?"🔴":"⚫"}</strong>`;
      el.onclick=()=>drawRoute(r);$("routeResults").appendChild(el);
    });
    drawRoute(data.safest_route);
  }catch(e){$("routeResults").innerHTML=`<div class="empty">${e.message}<br><small>Check your internet connection and try again.</small></div>`}
}
function drawRoute(r){
  showPage("map");setTimeout(()=>{if(window.routeLine)window.routeLine.remove();const latlngs=r.geometry.coordinates.map(c=>[c[1],c[0]]);window.routeLine=L.polyline(latlngs,{color:r.safety_score>=75?"#16a34a":r.safety_score>=50?"#d5a133":"#d4505c",weight:7,opacity:.9}).addTo(mainMap);mainMap.fitBounds(window.routeLine.getBounds(),{padding:[30,30]});window.routeLine.bindPopup(`<b>Safety ${r.safety_score}/100</b><br>${r.distance_km} km · ${r.duration_min} min`);},100)
}

async function loadDrivers(){
  try{const ds=await api("/drivers");$("drivers").innerHTML=ds.map(d=>`<div class="driver"><div class="driver-avatar">${d.name[0]}</div><div><b>${d.name}</b><small>${d.vehicle} • ${d.plate}</small><div class="stars">★ ${d.rating.toFixed(1)} · 🛡 ${d.safety_rating.toFixed(1)}</div></div><strong>₹${Math.round(d.price_per_km)}/km</strong><button class="book" onclick="bookRide(${d.id},'${d.name.replace(/'/g,"")}')">Book this driver</button></div>`).join("")}catch(e){}}
function estimateRides(){const d=$("rideDestination").value.trim();if(!d)return toast("Enter a destination.",false);const km=5+Math.min(20,d.length/3);$("olaPrice").textContent="₹"+Math.round(80+km*18);$("uberPrice").textContent="₹"+Math.round(90+km*19);toast("Demo ride estimates updated. Final fare and availability must be confirmed in the provider app.")}
function externalRide(provider){toast(`${provider} integration requires its official supported API/app.`,false)}
async function bookRide(driverId,name){
  const destination=$("rideDestination").value.trim();if(!destination)return toast("Enter a destination first.",false);
  const distance=5+Math.random()*5;
  try{const r=await api("/rides",{method:"POST",body:JSON.stringify({user_id:user?.id,driver_id:driverId,pickup:$("pickup").value,destination,distance,provider:"Abhaya"})});toast(`Ride booked with ${name}. Fare ₹${r.fare}`);loadHistory()}catch(e){toast(e.message,false)}
}
async function submitIncident(){
  if(!position)return toast("Please allow location access so the report can be placed accurately.",false);
  try{await api("/incidents",{method:"POST",body:JSON.stringify({user_id:user?.id||null,lat:position.lat,lon:position.lon,type:$("incidentType").value,description:$("incidentDescription").value})});toast(user?.id?"Thank you. Incident reported and saved to your incident history.":"Thank you. Incident reported.");$("incidentDescription").value="";loadIncidents();loadIncidentHistory();updateScore()}catch(e){toast(e.message,false)}
}
async function loadIncidentHistory(){
  if(!user?.id){$("incidentHistoryList").innerHTML='<div class="empty">Create an account to save and view your incident reports.</div>';return}
  try{
    const rs=await api(`/incidents/user/${user.id}`);
    $("incidentHistoryList").innerHTML=rs.length?rs.map(i=>`<div class="history-item incident-history-item"><div><b>📍 ${i.type}</b><p>${i.city||"Reported from your current location"}</p><small>${i.description||"No description provided."}</small></div><span class="history-status">Submitted</span></div>`).join(""):'<div class="empty">You have not reported any incidents yet.</div>';
  }catch(e){$("incidentHistoryList").innerHTML='<div class="empty">Could not load your incident history.</div>'}
}

async function loadHistory(){
  loadIncidentHistory();
  if(!user?.id){$("historyList").innerHTML='<div class="empty">Create an account to save and view your ride history.</div>';return}
  try{const rs=await api(`/rides/${user.id}`);$("historyList").innerHTML=rs.length?rs.map(r=>`<div class="history-item"><div><b>🚕 ${r.destination}</b><p>${r.driver_name||"Driver"} · ${r.vehicle||""} · ₹${r.fare} · ${r.status}</p></div><button onclick="openFeedback(${r.id},${r.driver_id})">Rate driver</button></div>`).join(""):'<div class="empty">No rides yet.</div>'}catch(e){}
}
function openFeedback(ride,driver){$("feedbackRide").value=ride;$("feedbackDriver").value=driver;$("feedbackModal").classList.remove("hidden")}
function closeFeedback(){$("feedbackModal").classList.add("hidden")}
async function submitFeedback(){try{await api("/feedback",{method:"POST",body:JSON.stringify({ride_id:+$("feedbackRide").value,driver_id:+$("feedbackDriver").value,rating:+$("feedbackRating").value,safety:+$("feedbackSafety").value,behavior:+$("feedbackBehavior").value,driving:+$("feedbackDriving").value,comment:$("feedbackComment").value})});closeFeedback();toast("Feedback submitted — thank you!");loadDrivers()}catch(e){toast(e.message,false)}}
function openSOS(){
  const modal=$("sosModal");
  if(!modal)return;
  modal.classList.remove("hidden");
  modal.setAttribute("aria-hidden","false");
  $("sosLocation").textContent=position?`Last known location: ${position.lat.toFixed(6)}, ${position.lon.toFixed(6)}`:"Location unavailable. Please enable location access.";
}
function closeSOS(){
  const modal=$("sosModal");
  if(!modal)return;
  modal.classList.add("hidden");
  modal.setAttribute("aria-hidden","true");
}
function callEmergency(){
  // India emergency number. tel: works on phones and on desktops with a registered calling app.
  const link=document.createElement("a");
  link.href="tel:112";
  link.rel="noopener";
  document.body.appendChild(link);
  link.click();
  link.remove();
  toast("Opening emergency call to 112…");
}
function sendSOS(){
  const loc=position?` My last known location: https://maps.google.com/?q=${position.lat},${position.lon}`:"";
  const contact=(user&&user.emergency_contact||"").trim();
  const body=encodeURIComponent("EMERGENCY — I need help."+loc);
  const href=contact?`sms:${contact}?body=${body}`:`sms:?body=${body}`;
  const link=document.createElement("a");
  link.href=href;
  link.rel="noopener";
  document.body.appendChild(link);
  link.click();
  link.remove();
  toast(contact?"Opening SOS message to your emergency contact…":"Opening SOS message. Add an emergency contact to send it directly.");
}
async function shareLocation(){
  if(!position)return toast("Location unavailable. Please allow location access first.",false);
  const url=`https://maps.google.com/?q=${position.lat},${position.lon}`;
  const text=`My current location: ${url}`;
  try{
    if(navigator.share){
      await navigator.share({title:"Abhaya emergency location",text,url});
      toast("Location shared successfully.");
      return;
    }
  }catch(e){
    if(e&&e.name==="AbortError")return;
  }
  try{
    await navigator.clipboard.writeText(url);
    toast("Location link copied. Share it with your trusted contact.");
  }catch(e){
    window.prompt("Copy this location link:",url);
  }
}
document.addEventListener("keydown",e=>{if(e.key==="Escape"&&!$("sosModal").classList.contains("hidden"))closeSOS()});
$("sosModal")?.addEventListener("click",e=>{if(e.target.id==="sosModal")closeSOS()});

if(user)startApp();
