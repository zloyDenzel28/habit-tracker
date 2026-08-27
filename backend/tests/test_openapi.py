"""Схема OpenAPI: собирается и описывает не только успешные ответы.

Смысл этих тестов — не в проверке FastAPI, а в том, что схема вообще
строится. Ошибка в `responses` (несуществующая модель, кривой словарь)
не роняет ни импорт, ни один эндпоинт: приложение поднимается, тесты
зелёные, и только /docs отдаёт 500 — а туда никто не заходит, пока не
понадобится показать API кому-то живому.
"""

from __future__ import annotations

import pytest


@pytest.fixture
async def schema(client) -> dict:
    response = await client.get("/openapi.json")
    assert response.status_code == 200
    return response.json()


async def test_схема_собирается_и_описывает_все_ручки(schema):
    paths = schema["paths"]
    assert "/occurrences/{occurrence_id}/complete" in paths
    assert schema["info"]["description"].strip()


async def test_у_защищённых_ручек_есть_схема_авторизации(schema):
    """Без этого в Swagger UI нет кнопки Authorize, и ни одну ручку
    нельзя вызвать со страницы — токен некуда вставить."""
    assert "HTTPBearer" in schema["components"]["securitySchemes"]
    assert schema["paths"]["/users/me"]["get"]["security"]


async def test_действия_над_занятием_документируют_404_и_409(schema):
    """§5 выражен кодами ответов: запрещённый переход — это 409, а не 500
    и не молчаливый успех. В схеме этого не было видно, пока коды не
    перечислили руками — вывести их из кода FastAPI не может."""
    for action in ("start", "snooze", "complete", "skip"):
        responses = schema["paths"][f"/occurrences/{{occurrence_id}}/{action}"]["post"][
            "responses"
        ]
        assert "404" in responses, action
        assert "409" in responses, action


async def test_у_кода_ошибки_описано_тело_ответа(schema):
    """Код без модели рисуется в Swagger пустым ответом, хотя API всегда
    отдаёт {"detail": ...}."""
    conflict = schema["paths"]["/occurrences/{occurrence_id}/complete"]["post"]["responses"][
        "409"
    ]
    ref = conflict["content"]["application/json"]["schema"]["$ref"]
    assert ref.endswith("/ErrorOut")


async def test_дев_логин_не_требует_токена(schema):
    """Единственная ручка без авторизации — иначе токен неоткуда взять."""
    assert not schema["paths"]["/auth/dev-login"]["post"].get("security")
