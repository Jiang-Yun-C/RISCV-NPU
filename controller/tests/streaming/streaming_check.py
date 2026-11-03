import importlib.util
from pathlib import Path
_spec=importlib.util.spec_from_file_location('nx_stream_independent_check',Path(__file__).with_name('check.py'))
_module=importlib.util.module_from_spec(_spec);_spec.loader.exec_module(_module)
score=_module.score
