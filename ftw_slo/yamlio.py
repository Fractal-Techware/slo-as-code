"""Safe, strict YAML loading and deterministic YAML output.

Loading uses yaml.SafeLoader (no Python object construction) and additionally
rejects duplicate keys, which PyYAML silently accepts by default.
"""
import yaml


class StrictLoader(yaml.SafeLoader):
    pass


def _construct_mapping(loader, node, deep=False):
    loader.flatten_mapping(node)
    seen = {}
    for key_node, _ in node.value:
        key = loader.construct_object(key_node, deep=deep)
        try:
            hash(key)
        except TypeError:
            raise yaml.constructor.ConstructorError(None, None, "unhashable mapping key", key_node.start_mark)
        if key in seen:
            raise yaml.constructor.ConstructorError(
                None, None, f"duplicate key {key!r} (first defined on line {seen[key] + 1})", key_node.start_mark)
        seen[key] = key_node.start_mark.line
    return yaml.SafeLoader.construct_mapping(loader, node, deep=deep)


StrictLoader.add_constructor(yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG, _construct_mapping)


def load_all(text):
    """Parse every YAML document in text (strict, safe). Empty documents are dropped."""
    return [d for d in yaml.load_all(text, Loader=StrictLoader) if d is not None]


def load(text):
    return yaml.load(text, Loader=StrictLoader)


class _Dumper(yaml.SafeDumper):
    def increase_indent(self, flow=False, indentless=False):
        return super().increase_indent(flow, False)

    def ignore_aliases(self, data):
        return True


def _repr_str(dumper, data):
    if "\n" in data:
        data = "\n".join(line.rstrip() for line in data.split("\n"))
        return dumper.represent_scalar("tag:yaml.org,2002:str", data, style="|")
    return dumper.represent_scalar("tag:yaml.org,2002:str", data)


_Dumper.add_representer(str, _repr_str)


def dump(obj):
    return yaml.dump(obj, Dumper=_Dumper, sort_keys=False, default_flow_style=False, width=10000, allow_unicode=True)
