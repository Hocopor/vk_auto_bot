/* Админка — общий клиентский скрипт.
   1. Вставка переменных {токен} в textarea по клику на чип.
   2. Индикатор «Сохранение…» на кнопках при отправке формы.
   Прогрессивное улучшение: без JS формы и так работают. */
(function () {
    "use strict";

    /* ---- 1. Чипы вставки переменных ------------------------------------ */
    // Кнопка-чип: <button data-insert="{name}" data-target="msg_after_payment">
    // Вставляет токен в textarea с указанным name на позицию курсора.
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
        // Сообщаем слушателям (превью) об изменении.
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
    // На submit любой формы с data-loading: блокируем submit-кнопку и
    // подменяем текст, чтобы убрать ощущение «зависания».
    document.addEventListener("submit", function (e) {
        var form = e.target;
        if (!form.matches("form")) return;
        if (form.getAttribute("data-no-loading") !== null) return;

        var btn = form.querySelector(
            'button[type="submit"], button:not([type]), input[type="submit"]'
        );
        if (!btn || btn.disabled) return;

        var busyText = btn.getAttribute("data-loading-text") || "Сохранение…";
        // Небольшая задержка, чтобы значение кнопки успело уйти в POST (на случай
        // именованных submit), и форма успела отправиться до disable.
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
})();
