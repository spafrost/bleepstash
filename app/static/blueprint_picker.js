// Attach behaviour to every .ean-picker in the blueprint detail page.
// Picker appends bare EAN strings to the paired textarea (deduped). Filter
// input hides list items that don't match by name or EAN.
(function () {
    function initPicker(picker) {
        const filter = picker.querySelector(".picker-filter");
        const list = picker.querySelector(".picker-list");
        const form = picker.closest("form");
        const textarea = form ? form.querySelector('textarea[name="accepted_eans"]') : null;
        if (!list || !textarea) return;

        if (filter) {
            filter.addEventListener("input", () => {
                const q = filter.value.trim().toLowerCase();
                list.querySelectorAll("li").forEach((li) => {
                    const nm = li.dataset.nameLc || "";
                    const en = li.dataset.eanLc || "";
                    li.hidden = q !== "" && !nm.includes(q) && !en.includes(q);
                });
            });
        }

        list.addEventListener("click", (ev) => {
            const btn = ev.target.closest(".picker-add");
            if (!btn) return;
            ev.preventDefault();
            const li = btn.closest("li");
            const ean = li ? li.dataset.ean : null;
            if (!ean) return;
            const current = textarea.value
                .split(/\r?\n/)
                .map((s) => s.trim())
                .filter(Boolean);
            if (current.includes(ean)) {
                btn.classList.add("picker-done");
                setTimeout(() => btn.classList.remove("picker-done"), 800);
                return;
            }
            current.push(ean);
            textarea.value = current.join("\n") + "\n";
            btn.classList.add("picker-done");
            setTimeout(() => btn.classList.remove("picker-done"), 800);
        });
    }

    document.querySelectorAll(".ean-picker").forEach(initPicker);
})();
