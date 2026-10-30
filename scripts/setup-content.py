"""Compatibility entry; delegates to the same installation verification."""
import importlib.util
from pathlib import Path

if __name__ == '__main__':
    spec = importlib.util.spec_from_file_location('assistant_setup', Path(__file__).with_name('setup-assistant.py'))
    module = importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    raise SystemExit(module.main())
