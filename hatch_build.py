"""Keep backend editable installs independent of generated dashboard assets."""
from hatchling.builders.hooks.plugin.interface import BuildHookInterface


class CustomBuildHook(BuildHookInterface):
    def initialize(self, version, build_data):
        if self.target_name == 'wheel' and version == 'editable':
            # Normal release wheels still require the compiled dashboard via
            # pyproject force-include. Editable Python setup only needs migrations.
            build_data['force_include_editable'] = {
                'migrations': 'model_router/storage/alembic',
            }
