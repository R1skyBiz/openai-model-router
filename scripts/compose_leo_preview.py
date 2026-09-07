"""Create a new classifier-only LEO release from an existing verified composition.

Does not activate, refresh account evidence, read tokens, or call a provider.
"""
from argparse import ArgumentParser
from pathlib import Path
import sys
import yaml

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from model_router.release import load_release


def compose(source: Path, destination: Path):
    release = load_release(source)
    if (release.live_evidence is None or release.classifier_config is None
            or release.classifier_config.status != 'active'
            or not release.classifier_config.live_enabled):
        raise ValueError('a verified composition with an active live classifier is required')
    example = yaml.safe_load((Path(__file__).resolve().parents[1] /
        'config/releases/leo-shadow-v1.yaml').read_text())
    manifest = release.canonical_manifest
    manifest['release_id'] = example['release_id']
    manifest['policy']['directory'] = str((release.source.parent / release.config.policy.directory).resolve())
    for name in ('evidence', 'classifier_config'):
        manifest['live'][name]['path'] = str((release.source.parent / manifest['live'][name]['path']).resolve())
    manifest['operations'].update(route=False, read=False, execute=False, health=True,
        classify_route=True, live_classifier=True, live_provider=False, tools=False, shadow=False)
    manifest['auth'].update(credentials_env='LEO_ROUTER_APPLICATION_CREDENTIALS_JSON',
        required_scopes=['classify_route','health'])
    for field in ('allocation_id', 'application_cost_ceiling_usd', 'task_cost_ceiling_usd',
                  'max_concurrent_tasks', 'max_preview_records'):
        manifest['limits'][field] = example['limits'][field]
    manifest['database']['required_migration_revision'] = '0004_routing_previews'
    # All other bounds and private current evidence stay pinned to the source.
    from model_router.release.schema import ReleaseConfig
    normalized = ReleaseConfig.model_validate(manifest).model_dump(mode='json')
    destination.parent.mkdir(parents=True,exist_ok=True)
    with destination.open('x',encoding='utf-8') as stream:
        yaml.safe_dump(normalized, stream, sort_keys=False)
    return load_release(destination)


def main():
    parser = ArgumentParser(description=__doc__)
    parser.add_argument('source',type=Path)
    parser.add_argument('destination',type=Path)
    args = parser.parse_args()
    release = compose(args.source,args.destination)
    print(f'Prepared {release.config.release_id}; activation and current readiness are still required.')


if __name__ == '__main__':
    main()
