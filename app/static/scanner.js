// Minimal scanner front-end. Keeps the input focused, POSTs to /api/scan on
// Enter, refreshes the mode banner + pending state from the response.
(function () {
    const form = document.getElementById("scan-form");
    const input = document.getElementById("scan-input");
    const status = document.getElementById("scan-status");
    const stateDump = document.getElementById("state-dump");
    const banner = document.getElementById("mode-banner");

    if (!form || !input) return;

    const refocus = () => setTimeout(() => input.focus(), 0);
    document.addEventListener("click", refocus);
    window.addEventListener("focus", refocus);

    async function submitScan(code) {
        status.className = "status waiting";
        status.textContent = "Processing…";
        try {
            const res = await fetch("/api/scan", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ code }),
            });
            const data = await res.json();
            renderResult(data);
        } catch (err) {
            status.className = "status error";
            status.textContent = "Network error: " + err.message;
        }
    }

    function renderResult(data) {
        const cls = data.status || "ok";
        status.className = "status " + cls;
        status.textContent = data.message || JSON.stringify(data);
        if (data.mode) {
            document.body.setAttribute("data-mode", data.mode);
            banner.innerHTML = "Mode: <strong>" + data.mode + "</strong>";
        }
        fetch("/api/mode")
            .then((r) => r.json())
            .then((s) => {
                if (stateDump) stateDump.textContent = JSON.stringify(s, null, 2);
            })
            .catch(() => {});
        if (typeof window.refreshInventory === "function") {
            window.refreshInventory();
        }
        if (typeof window.refreshBlueprintPill === "function") {
            window.refreshBlueprintPill();
        }
    }

    form.addEventListener("submit", (ev) => {
        ev.preventDefault();
        const code = input.value.trim();
        input.value = "";
        refocus();
        if (!code) return;
        submitScan(code);
    });
})();
