"""Strict experiment-only YAML configuration; never activates routing policy."""
from pathlib import Path
import yaml
from .contracts import ExperimentConfig

class _UniqueLoader(yaml.SafeLoader):
    pass

def _mapping(loader, node):
    result = {}
    for key_node, value_node in node.value:
        key = loader.construct_object(key_node)
        if key in result:
            raise ValueError('duplicate experiment setting')
        result[key] = loader.construct_object(value_node)
    return result

_UniqueLoader.add_constructor(yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG, _mapping)

def load_config(path):
    try:
        data = yaml.load(Path(path).read_text(encoding='utf-8'), Loader=_UniqueLoader)
        if not isinstance(data, dict) or type(data.get('schema_version')) is not int:
            raise ValueError('invalid experiment version')
        return ExperimentConfig.model_validate(data)
    except (OSError, TypeError, ValueError, yaml.YAMLError):
        raise ValueError('invalid experiment configuration') from None
