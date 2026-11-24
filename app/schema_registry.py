"""Bounded JSON-schema subset validation and conservative compatibility checks."""
from __future__ import annotations
import json, re
from typing import Any

_TYPES = {"object", "array", "string", "integer", "number", "boolean", "null"}
_KEYS = {"type","properties","required","additionalProperties","items","enum","minLength","maxLength","minItems","maxItems","minimum","maximum","description"}
MAX_BYTES, MAX_DEPTH, MAX_NODES = 16384, 12, 256

class SchemaValidationError(ValueError):
    pass

def _size(value: Any) -> int:
    try:
        return len(json.dumps(value, ensure_ascii=True, separators=(",", ":")).encode("utf-8"))
    except (TypeError, ValueError) as exc:
        raise SchemaValidationError("value must be JSON serializable") from exc

def validate_schema(schema: Any) -> dict:
    if not isinstance(schema, dict) or _size(schema) > MAX_BYTES:
        raise SchemaValidationError("schema must be an object no larger than 16 KiB")
    count = 0
    def walk(node: Any, depth: int) -> None:
        nonlocal count
        count += 1
        if count > MAX_NODES or depth > MAX_DEPTH:
            raise SchemaValidationError("schema exceeds structural limits")
        if not isinstance(node, dict):
            raise SchemaValidationError("each schema node must be an object")
        unknown = set(node) - _KEYS
        if unknown:
            raise SchemaValidationError("unsupported schema keywords: " + ", ".join(sorted(unknown)))
        kind = node.get("type")
        if kind not in _TYPES:
            raise SchemaValidationError("schema type is required and must be supported")
        if "description" in node and (not isinstance(node["description"], str) or len(node["description"]) > 300):
            raise SchemaValidationError("description must be text up to 300 characters")
        if "enum" in node:
            values = node["enum"]
            if not isinstance(values, list) or not 1 <= len(values) <= 100 or len({_size(v) for v in values}) != len(values):
                raise SchemaValidationError("enum must contain 1 to 100 distinct JSON values")
        for key in ("minLength","maxLength","minItems","maxItems"):
            if key in node and (isinstance(node[key], bool) or not isinstance(node[key], int) or not 0 <= node[key] <= 100000):
                raise SchemaValidationError(f"{key} must be an integer from 0 to 100000")
        for key in ("minimum","maximum"):
            if key in node and (isinstance(node[key], bool) or not isinstance(node[key], (int,float))):
                raise SchemaValidationError(f"{key} must be numeric")
        if "minimum" in node and "maximum" in node and node["minimum"] > node["maximum"]:
            raise SchemaValidationError("minimum cannot exceed maximum")
        if kind == "object":
            props, required = node.get("properties", {}), node.get("required", [])
            if not isinstance(props, dict) or len(props) > 100 or any(not isinstance(k,str) or not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_-]{0,63}", k) for k in props):
                raise SchemaValidationError("object properties must be a bounded named object")
            if not isinstance(required,list) or len(required)>len(props) or any(not isinstance(k,str) or k not in props for k in required) or len(set(required)) != len(required):
                raise SchemaValidationError("required must contain unique declared property names")
            if "additionalProperties" in node and not isinstance(node["additionalProperties"],bool):
                raise SchemaValidationError("additionalProperties must be boolean")
            for child in props.values(): walk(child, depth+1)
        elif any(k in node for k in ("properties","required","additionalProperties")):
            raise SchemaValidationError("object keywords require type=object")
        if kind == "array":
            if "items" not in node: raise SchemaValidationError("array schemas require items")
            walk(node["items"], depth+1)
        elif "items" in node: raise SchemaValidationError("items requires type=array")
        if kind == "string" and any(k in node for k in ("minimum","maximum","minItems","maxItems")):
            raise SchemaValidationError("numeric and array bounds require matching types")
        if kind != "string" and any(k in node for k in ("minLength","maxLength")):
            raise SchemaValidationError("string length bounds require type=string")
        if kind != "array" and any(k in node for k in ("minItems","maxItems")):
            raise SchemaValidationError("item bounds require type=array")
        if kind not in {"integer","number"} and any(k in node for k in ("minimum","maximum")):
            raise SchemaValidationError("numeric bounds require numeric types")
    walk(schema,0)
    return schema

def _matches(value: Any, kind: str) -> bool:
    return {
      "object":lambda v:isinstance(v,dict), "array":lambda v:isinstance(v,list),
      "string":lambda v:isinstance(v,str),
      "integer":lambda v:isinstance(v,int) and not isinstance(v,bool),
      "number":lambda v:isinstance(v,(int,float)) and not isinstance(v,bool),
      "boolean":lambda v:isinstance(v,bool), "null":lambda v:v is None,
    }[kind](value)

def validate_instance(schema: dict, value: Any) -> None:
    validate_schema(schema)
    def check(node: dict, current: Any, path: str, depth: int) -> None:
        if depth > MAX_DEPTH: raise SchemaValidationError(f"{path}: value nesting is too deep")
        kind=node["type"]
        if not _matches(current,kind): raise SchemaValidationError(f"{path}: expected {kind}")
        if "enum" in node and current not in node["enum"]: raise SchemaValidationError(f"{path}: value is not in enum")
        if kind=="object":
            props=node.get("properties",{})
            if set(node.get("required",[]))-set(current): raise SchemaValidationError(f"{path}: missing required properties")
            if node.get("additionalProperties",True) is False and set(current)-set(props): raise SchemaValidationError(f"{path}: additional properties are not allowed")
            for key,child in props.items():
                if key in current: check(child,current[key],f"{path}.{key}",depth+1)
        elif kind=="array":
            if len(current)<node.get("minItems",0) or len(current)>node.get("maxItems",100000): raise SchemaValidationError(f"{path}: array length is out of bounds")
            for i,item in enumerate(current): check(node["items"],item,f"{path}[{i}]",depth+1)
        elif kind=="string":
            if len(current)<node.get("minLength",0) or len(current)>node.get("maxLength",100000): raise SchemaValidationError(f"{path}: string length is out of bounds")
        elif kind in {"integer","number"}:
            if current < node.get("minimum",float("-inf")) or current > node.get("maximum",float("inf")): raise SchemaValidationError(f"{path}: number is out of bounds")
    check(schema,value,"$",0)

def compatibility_report(old_schema: dict, new_schema: dict) -> dict:
    """Conservative screening: identify obvious changes that can reject old valid data."""
    validate_schema(old_schema); validate_schema(new_schema)
    reasons=[]
    def compare(old: dict,new: dict,path: str) -> None:
        if old["type"]!=new["type"] and not (old["type"]=="integer" and new["type"]=="number"):
            reasons.append(f"{path}: type changed"); return
        if "enum" in new and ("enum" not in old or not {_size(v) for v in old["enum"]}.issubset({_size(v) for v in new["enum"]})):
            reasons.append(f"{path}: enum may reject previously valid values")
        if old["type"]=="object" and new["type"]=="object":
            if not set(new.get("required",[])).issubset(set(old.get("required",[]))): reasons.append(f"{path}: new required property added")
            op,np=old.get("properties",{}),new.get("properties",{})
            for key in op.keys() & np.keys(): compare(op[key],np[key],f"{path}.{key}")
            if new.get("additionalProperties",True) is False and old.get("additionalProperties",True) is not False: reasons.append(f"{path}: additional properties newly forbidden")
        if old["type"]=="array" and new["type"]=="array": compare(old["items"],new["items"],path+"[]")
        for key in ("minimum","minLength","minItems"):
            if key in new and (key not in old or new[key]>old[key]): reasons.append(f"{path}: {key} tightened or newly introduced")
        for key in ("maximum","maxLength","maxItems"):
            if key in new and (key not in old or new[key]<old[key]): reasons.append(f"{path}: {key} tightened or newly introduced")
    compare(old_schema,new_schema,"$")
    return {"compatible":not reasons,"reasons":reasons}
