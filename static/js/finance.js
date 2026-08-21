(function () {
    const body = document.body;
    const sidebar = document.getElementById("appSidebar");
    const mobileMenuButton = document.getElementById("mobileMenuButton");
    const sidebarOverlay = document.getElementById("sidebarOverlay");
    const sidebarCollapse = document.getElementById("sidebarCollapse");

    const isDesktop = () => window.matchMedia("(min-width: 992px)").matches;

    function closeMobileSidebar() {
        body.classList.remove("sidebar-open");
    }

    if (localStorage.getItem("financeSidebarCompact") === "true" && isDesktop()) {
        body.classList.add("sidebar-collapsed");
    }

    mobileMenuButton?.addEventListener("click", function () {
        body.classList.toggle("sidebar-open");
    });

    sidebarOverlay?.addEventListener("click", closeMobileSidebar);

    sidebarCollapse?.addEventListener("click", function () {
        if (!isDesktop()) {
            closeMobileSidebar();
            return;
        }

        body.classList.toggle("sidebar-collapsed");
        localStorage.setItem(
            "financeSidebarCompact",
            body.classList.contains("sidebar-collapsed") ? "true" : "false"
        );
    });

    sidebar?.querySelectorAll("a").forEach(function (link) {
        link.addEventListener("click", function () {
            if (!isDesktop()) closeMobileSidebar();
        });
    });

    window.addEventListener("resize", function () {
        if (isDesktop()) closeMobileSidebar();
    });

    document.querySelectorAll("[data-dismiss-alert]").forEach(function (button) {
        button.addEventListener("click", function () {
            button.closest(".app-alert")?.remove();
        });
    });

    document.querySelectorAll("[data-toggle-password]").forEach(function (button) {
        button.addEventListener("click", function () {
            const input = document.getElementById(button.dataset.togglePassword);
            if (!input) return;

            const showPassword = input.type === "password";
            input.type = showPassword ? "text" : "password";
            const icon = button.querySelector("i");
            icon?.classList.toggle("bi-eye", !showPassword);
            icon?.classList.toggle("bi-eye-slash", showPassword);
            button.setAttribute("aria-label", showPassword ? "Sembunyikan password" : "Tampilkan password");
        });
    });

    document.querySelectorAll("form[data-loading-form]").forEach(function (form) {
        form.addEventListener("submit", function () {
            const button = form.querySelector("button[type='submit']");
            if (!button || button.disabled) return;

            button.disabled = true;
            button.dataset.originalHtml = button.innerHTML;
            button.innerHTML = '<span class="spinner-border spinner-border-sm" aria-hidden="true"></span><span>Memproses...</span>';
        });
    });

    document.querySelectorAll("form[data-confirm]").forEach(function (form) {
        form.addEventListener("submit", function (event) {
            const message = form.dataset.confirm || "Lanjutkan tindakan ini?";
            if (!window.confirm(message)) event.preventDefault();
        });
    });
})();
