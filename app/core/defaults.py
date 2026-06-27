DEFAULT_MSG_INSTRUCTION = (
    "Здравствуйте! Чтобы участвовать в розыгрыше «{event_name}», переведите "
    "{price}₽ за один билет по QR-коду на изображении. После оплаты пришлите "
    "сюда фото чека, ваше имя и номер телефона одним сообщением."
)
DEFAULT_MSG_RECEIPT_RECEIVED = (
    "Спасибо! Чек получен и отправлен на проверку. Пожалуйста, пришлите в "
    "ответ ваше ФИО и номер телефона одним сообщением. Как только оплата "
    "подтвердится, я пришлю ваши номера участника."
)
DEFAULT_MSG_AFTER_PAYMENT = (
    "Оплата подтверждена! Ваши номера участника: {numbers} (всего: {count}). "
    "Список участников: {sheet_url}. Удачи в розыгрыше!"
)
DEFAULT_MSG_NEED_CONTACTS = (
    "Пожалуйста, пришлите ваше имя и номер телефона, чтобы мы могли связаться "
    "с вами в случае выигрыша."
)
DEFAULT_MSG_CONTACTS_SAVED = (
    "Спасибо! Ваши данные приняты. Как только оплата подтвердится, "
    "я пришлю ваши номера участника."
)

DEFAULT_TEXTS = {
    "msg_instruction": DEFAULT_MSG_INSTRUCTION,
    "msg_after_payment": DEFAULT_MSG_AFTER_PAYMENT,
    "msg_receipt_received": DEFAULT_MSG_RECEIPT_RECEIVED,
    "msg_need_contacts": DEFAULT_MSG_NEED_CONTACTS,
    "msg_contacts_saved": DEFAULT_MSG_CONTACTS_SAVED,
}
