// Inventory live view — polls /api/inventory/current every 5 s and re-renders
// the progress numbers, product table and unknown-scans list in place.
(function () {
    const tbody = document.getElementById("inv-tbody");
    if (!tbody) return;

    const escape = (s) =>
        String(s || "").replace(/[&<>"']/g, (c) => (
            { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]
        ));

    function updateProgress(p) {
        document.querySelectorAll("[data-progress-done]").forEach((el) => (el.textContent = p.products_done));
        document.querySelectorAll("[data-progress-total]").forEach((el) => (el.textContent = p.products_total));
        document.querySelectorAll("[data-units-counted]").forEach((el) => (el.textContent = p.units_counted));
        document.querySelectorAll("[data-units-expected]").forEach((el) => (el.textContent = p.units_expected));
    }

    function renderRows(rows) {
        tbody.innerHTML = rows.map((r) => {
            const delta = r.delta > 0 ? `+${r.delta}` : r.delta;
            return `
                <tr class="inv-row inv-row--${escape(r.status)}">
                    <td>${escape(r.name)}</td>
                    <td class="mono">${escape(r.ean)}</td>
                    <td>${r.expected}</td>
                    <td>${r.counted}</td>
                    <td>${delta}</td>
                    <td>${escape(r.status)}</td>
                </tr>`;
        }).join("");
    }

    function renderUnknowns(unknowns) {
        const ul = document.getElementById("inv-unknown");
        if (!ul) return;
        ul.innerHTML = unknowns.map((e) => `<li class="chip mono">${escape(e)}</li>`).join("");
        const badge = document.querySelector("[data-unknown-count]");
        if (badge) badge.textContent = unknowns.length;
    }

    async function tick() {
        try {
            const res = await fetch("/api/inventory/current");
            const data = await res.json();
            if (!data) {
                // Session closed while we were watching; refresh page to show landing.
                location.reload();
                return;
            }
            updateProgress(data.progress);
            renderRows(data.rows);
            renderUnknowns(data.unknown_scans);
        } catch (_) {
            // silent — next tick will retry
        }
    }

    setInterval(tick, 5000);
})();
