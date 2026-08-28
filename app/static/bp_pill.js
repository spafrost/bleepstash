// Topbar blueprint fulfilment pill.
// Fetches /api/blueprints/current on load, on scan events (via the global
// window.refreshBlueprintPill), and on a 15 s poll. Hides itself when no
// blueprint is active.
(function () {
    const pill = document.getElementById("bp-pill");
    if (!pill) return;
    const nameEl = pill.querySelector("[data-bp-name]");
    const pctEl = pill.querySelector("[data-bp-pct]");

    function classify(pct) {
        if (pct >= 90) return "bp-pill--good";
        if (pct >= 50) return "bp-pill--partial";
        return "bp-pill--low";
    }

    async function refresh() {
        try {
            const res = await fetch("/api/blueprints/current");
            const data = await res.json();
            if (!data || !data.blueprint) {
                pill.hidden = true;
                return;
            }
            const t = data.totals;
            const pct = t.required > 0 ? Math.round((t.filled / t.required) * 100) : 0;
            nameEl.textContent = data.blueprint.name;
            pctEl.textContent = pct + "%";
            pill.classList.remove("bp-pill--good", "bp-pill--partial", "bp-pill--low");
            pill.classList.add(classify(pct));
            pill.hidden = false;
        } catch (_) {
            // silent
        }
    }

    window.refreshBlueprintPill = refresh;
    refresh();
    setInterval(refresh, 15000);
})();
