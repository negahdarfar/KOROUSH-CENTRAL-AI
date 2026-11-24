import pytest
from app.schema_registry import SchemaValidationError, compatibility_report, validate_instance, validate_schema

def test_nested_object_and_unknown_fields():
    schema={"type":"object","properties":{"title":{"type":"string","minLength":1,"maxLength":40},"count":{"type":"integer","minimum":0}},"required":["title"],"additionalProperties":False}
    validate_instance(schema,{"title":"Hello","count":2})
    with pytest.raises(SchemaValidationError,match="additional"): validate_instance(schema,{"title":"Hello","extra":True})

def test_bool_is_not_integer_and_required_is_enforced():
    schema={"type":"object","properties":{"n":{"type":"integer"}},"required":["n"]}
    with pytest.raises(SchemaValidationError,match="expected integer"): validate_instance(schema,{"n":True})
    with pytest.raises(SchemaValidationError,match="missing"): validate_instance(schema,{})

def test_array_enum_and_bounds():
    schema={"type":"array","items":{"type":"string","enum":["a","b"]},"minItems":1,"maxItems":2}
    validate_instance(schema,["a","b"])
    with pytest.raises(SchemaValidationError): validate_instance(schema,["c"])

@pytest.mark.parametrize("schema",[{"type":"object","required":["missing"]},{"type":"array"},{"type":"string","minimum":1},{"type":"object","properties":{"x":{"type":"function"}}},{"type":"object","unknown":True}])
def test_invalid_schema_rejected(schema):
    with pytest.raises(SchemaValidationError): validate_schema(schema)

def test_schema_size_and_depth_bounded():
    with pytest.raises(SchemaValidationError): validate_schema({"type":"string","description":"x"*17000})
    node={"type":"string"}
    for _ in range(14): node={"type":"array","items":node}
    with pytest.raises(SchemaValidationError): validate_schema(node)

def test_compatibility_detects_new_required_and_tightened_bounds():
    old={"type":"object","properties":{"name":{"type":"string"}},"required":["name"]}
    safe={"type":"object","properties":{"name":{"type":"string"},"extra":{"type":"integer"}},"required":["name"]}
    breaking={"type":"object","properties":{"name":{"type":"string","minLength":3},"extra":{"type":"integer"}},"required":["name","extra"]}
    assert compatibility_report(old,safe)["compatible"] is True
    assert compatibility_report(old,breaking)["compatible"] is False
