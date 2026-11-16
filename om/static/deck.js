// Shared: POST /api/deck and save the returned .pptx
async function downloadDeck(body, btn) {
  const label = btn ? btn.textContent : "";
  if (btn) { btn.disabled = true; btn.textContent = "Building slides…"; }
  try {
    const r = await fetch("/api/deck", {method: "POST", body: JSON.stringify(body)});
    if (!r.ok) { const j = await r.json().catch(() => ({})); alert("Couldn't build slides: " + (j.error || r.status)); return; }
    const name = ((r.headers.get("Content-Disposition") || "").match(/filename="([^"]+)"/) || [])[1] || "deck.pptx";
    const a = document.createElement("a"); a.href = URL.createObjectURL(await r.blob()); a.download = name;
    document.body.appendChild(a); a.click(); a.remove();
  } catch (e) { alert("Couldn't build slides: " + e.message); }
  finally { if (btn) { btn.disabled = false; btn.textContent = label; } }
}
