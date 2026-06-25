import httpx

VK_API_VERSION = "5.131"


async def test_vk(token: str, group_id: str | int | None = None) -> tuple[bool, str]:
    """Проверка VK-токена сообщества через groups.getById. Возвращает (ok, сообщение)."""
    if not token:
        return False, "VK-токен не задан."
    params = {"access_token": token, "v": VK_API_VERSION}
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get("https://api.vk.com/method/groups.getById", params=params)
        data = resp.json()
    except Exception as e:
        return False, f"Сеть/запрос не удался: {e}"
    if "error" in data:
        err = data["error"]
        return False, f"VK API ошибка: {err.get('error_msg', err)}"
    response = data.get("response")
    if not response:
        return False, "VK API вернул пустой ответ."
    groups = response if isinstance(response, list) else response.get("groups", [])
    if not groups:
        return False, "Не удалось определить сообщество по токену."
    g = groups[0]
    name = g.get("name", "?")
    gid = g.get("id", "?")
    msg = f"Успех: токен валиден. Сообщество: «{name}» (id {gid})."
    if group_id and str(group_id).strip() and str(gid) != str(group_id).strip():
        msg += f" ВНИМАНИЕ: указанный group_id={group_id} не совпадает с id токена ({gid})."
    return True, msg
