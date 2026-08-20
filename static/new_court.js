const $ = (s) => document.querySelector(s);
async function api(url, options={}) {
  const r = await fetch(url, {headers:{"Content-Type":"application/json", ...(options.headers||{})}, ...options});
  if (!r.ok) { let m=`Request failed (${r.status})`; try {m=(await r.json()).detail||m;} catch(_){} throw new Error(m); }
  return r.json();
}
const holderId = Number(new URLSearchParams(location.search).get("holder_id"));
if (!holderId) location.href = "/";

async function loadHolder() {
  try {
    const p = await api(`/api/players/${holderId}`);
    $("#holder-line").textContent = `${p.name} is holding this court · Current balance $${Number(p.balance).toFixed(2)}`;
  } catch (e) { $("#booking-msg").textContent = e.message; }
}

$("#booking-form").addEventListener("submit", async e => {
  e.preventDefault();
  const msg = $("#booking-msg"); msg.textContent="";
  try {
    const b = await api("/api/bookings", {method:"POST", body:JSON.stringify({
      holder_player_id: holderId,
      court_name: $("#court_name").value,
      booking_date: $("#booking_date").value,
      start_time: $("#start_time").value,
      end_time: $("#end_time").value,
      total_cost: Number($("#total_cost").value),
      max_players: Number($("#max_players").value),
      notes: $("#notes").value || null,
    })});
    location.href = `/court/${b.id}`;
  } catch (e) { msg.textContent=e.message; }
});
loadHolder();