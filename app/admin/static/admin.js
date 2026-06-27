/* Админка — общий клиентский скрипт.
   1. Вставка переменных {токен} в textarea по клику на чип.
   2. Индикатор «Сохранение…» на кнопках при отправке формы.
   3. Превью QR-кода при загрузке файла.
   4. Переключатель тёмной темы. */
(function () {
    "use strict";

    /* ---- 1. Чипы вставки переменных ------------------------------------ */
    function insertAtCursor(field, text) {
        field.focus();
        var start = field.selectionStart;
        var end = field.selectionEnd;
        if (typeof start !== "number") {
            field.value += text;
        } else {
            var v = field.value;
            field.value = v.slice(0, start) + text + v.slice(end);
            var pos = start + text.length;
            field.setSelectionRange(pos, pos);
        }
        field.dispatchEvent(new Event("input", { bubbles: true }));
    }

    document.addEventListener("click", function (e) {
        var chip = e.target.closest("[data-insert]");
        if (!chip) return;
        e.preventDefault();
        var targetName = chip.getAttribute("data-target");
        var token = chip.getAttribute("data-insert");
        var field = document.querySelector(
            'textarea[name="' + targetName + '"]'
        );
        if (field) insertAtCursor(field, token);
    });

    /* ---- 2. Индикатор отправки формы ----------------------------------- */
    document.addEventListener("submit", function (e) {
        var form = e.target;
        if (!form.matches("form")) return;
        if (form.getAttribute("data-no-loading") !== null) return;

        var btn = form.querySelector(
            'button[type="submit"], button:not([type]), input[type="submit"]'
        );
        if (!btn || btn.disabled) return;

        var busyText = btn.getAttribute("data-loading-text") || "Сохранение…";
        setTimeout(function () {
            if (btn.tagName === "BUTTON") {
                btn.dataset.originalHtml = btn.innerHTML;
                btn.textContent = busyText;
            } else {
                btn.value = busyText;
            }
            btn.disabled = true;
        }, 0);
    });

    /* ---- 3. Превью QR-кода -------------------------------------------- */
    var qrInput = document.getElementById("f-qr-file");
    var qrPreview = document.getElementById("qr-preview");
    if (qrInput && qrPreview) {
        qrInput.addEventListener("change", function () {
            var file = this.files && this.files[0];
            if (!file) return;
            var reader = new FileReader();
            reader.onload = function (ev) {
                qrPreview.src = ev.target.result;
                qrPreview.style.display = "block";
            };
            reader.readAsDataURL(file);
        });
    }

    /* ---- 3b. Превью картинок к сообщениям бота ------------------------- */
    var msgImageInputs = document.querySelectorAll(".msg-image-input[data-preview]");
    msgImageInputs.forEach(function (input) {
        var preview = document.getElementById(input.getAttribute("data-preview"));
        if (!preview) return;
        input.addEventListener("change", function () {
            var file = this.files && this.files[0];
            if (!file) return;
            var reader = new FileReader();
            reader.onload = function (ev) {
                preview.src = ev.target.result;
                preview.classList.remove("is-hidden");
                preview.style.display = "block";
            };
            reader.readAsDataURL(file);
        });
    });

    /* ---- 4. Переключатель темы ----------------------------------------- */
    function getTheme() {
        return localStorage.getItem("theme") || "light";
    }
    function setTheme(t) {
        document.documentElement.setAttribute("data-theme", t);
        localStorage.setItem("theme", t);
        var btn = document.querySelector(".theme-toggle");
        if (btn) btn.textContent = t === "dark" ? "\u2600" : "\u263E";
    }
    /* Применяем тему при загрузке */
    setTheme(getTheme());

    document.addEventListener("click", function (e) {
        var btn = e.target.closest(".theme-toggle");
        if (!btn) return;
        setTheme(getTheme() === "dark" ? "light" : "dark");
    });
})();
