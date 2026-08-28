// Small dashboard helpers: refreshes bell count, wires dismiss buttons.
(function () {
    const badge = document.getElementById("notif-badge");

    async function refreshBadge() {
        if (!badge) return;
        try {
            const res = await fetch("/api/notifications?unread=true");
            const items = await res.json();
            if (items.length > 0) {
                badge.hidden = false;
                badge.textContent = String(items.length);
            } else {
                badge.hidden = true;
            }
        } catch (_) {
            // silent — bell just stays as-is
        }
    }

    document.querySelectorAll(".notif-dismiss").forEach((btn) => {
        btn.addEventListener("click", async () => {
            const id = btn.dataset.id;
            await fetch(`/api/notifications/${id}/dismiss`, { method: "POST" });
            const li = btn.closest(".notif");
            if (li) li.remove();
            refreshBadge();
        });
    });

    const dismissAll = document.getElementById("dismiss-all");
    if (dismissAll) {
        dismissAll.addEventListener("click", async () => {
            await fetch("/api/notifications/dismiss-all", { method: "POST" });
            document.querySelectorAll(".notif").forEach((el) => el.remove());
            refreshBadge();
        });
    }

    refreshBadge();
    setInterval(refreshBadge, 15000);
})();
