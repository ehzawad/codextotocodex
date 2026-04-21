from __future__ import annotations

from codex_chronicle.summarizer import CHRONICLE_JSON_SCHEMA


def _all_object_nodes(schema):
    if not isinstance(schema, dict):
        return
    if schema.get("type") == "object":
        yield schema
        for value in (schema.get("properties") or {}).values():
            yield from _all_object_nodes(value)
    items = schema.get("items")
    if isinstance(items, dict):
        yield from _all_object_nodes(items)
    elif isinstance(items, list):
        for item in items:
            yield from _all_object_nodes(item)


def test_all_object_schemas_are_strict():
    objects = list(_all_object_nodes(CHRONICLE_JSON_SCHEMA))
    assert objects, "expected at least one object node in chronicle schema"
    for node in objects:
        assert node.get("additionalProperties") is False
        assert node.get("required") == list((node.get("properties") or {}).keys())
