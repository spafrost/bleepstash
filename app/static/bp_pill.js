// Topbar blueprint pill. Shows slots_matched/slots_total since mixed units
// across slots make a single "% filled" number nonsensical.
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
            const total = t.slots_total || 0;
            const matched = t.slots_matched || 0;
            const pct = total > 0 ? Math.round((matched / total) * 100) : 0;
            nameEl.textContent = data.blueprint.name;
            pctEl.textContent = `${matched}/${total}`;
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
