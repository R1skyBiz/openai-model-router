from pathlib import Path
import pytest
import yaml
from model_router.policy.loader import load_bundle
from model_router.policy.phase4 import load_phase4

@pytest.mark.parametrize('mutation',[
    lambda v:v.update(unrecognized=True),
    lambda v:v['evaluators'][0].update(model_alias='missing'),
    lambda v:v['evaluators'][0].update(reasoning_effort='unsupported'),
    lambda v:v['evaluators'][0].update(pass_threshold=2.),
    lambda v:v['evaluators'][0].update(score_max=float('nan')),
    lambda v:v['evaluators'][0].update(timeout_ms=0),
    lambda v:v['evaluators'][0].update(max_retries=-1),
    lambda v:v['evaluators'][0].update(max_output_tokens=99999999),
    lambda v:v['health'].update(freshness_ms=0),
    lambda v:v['health'].update(recovery_success_threshold=2),
    lambda v:v.update(synthetic_only=False),
])
def test_unsafe_phase4_config_rejected(tmp_path,mutation):
    values=yaml.safe_load(Path('config/phase4.yaml').read_text())
    mutation(values)
    path=tmp_path/'phase4.yaml';path.write_text(yaml.safe_dump(values))
    with pytest.raises(ValueError): load_phase4(path,load_bundle('config'))


def test_duplicate_yaml_keys_rejected(tmp_path):
    path=tmp_path/'phase4.yaml';path.write_text(Path('config/phase4.yaml').read_text()+'\nversion: duplicate\n')
    with pytest.raises(ValueError):load_phase4(path,load_bundle('config'))
