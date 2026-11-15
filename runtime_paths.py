"""Portable runtime discovery. Stdlib only; never imports Hermes or credentials."""
import ast
import os
import shlex
from pathlib import Path
import shutil


def _executable(value):
    path = Path(value).expanduser() if value else None
    if path is None or not path.is_file() or not os.access(path, os.X_OK):
        raise ValueError('hermes_runtime_unavailable')
    return str(path.absolute())


def hermes_cli():
    """Explicit HERMES_BIN is authoritative, including invalid/empty values."""
    if 'HERMES_BIN' in os.environ:
        return _executable(os.environ['HERMES_BIN'])
    return _executable(shutil.which('hermes') or Path.home() / '.local/bin/hermes')


def hermes_runtime():
    """Return (Python executable, source root) from the installed CLI launcher.

    Understand plain Python entrypoints and nested `exec` shell launchers,
    including the platform's isolated `python -I -c` launcher. Inspect only;
    never execute launcher code. Unknown layouts fail closed. HERMES_PYTHON
    and HERMES_SOURCE_ROOT may explicitly override discovery independently.
    """
    if 'HERMES_BIN' in os.environ:
        hermes_cli()  # Never silently bypass a bad explicit CLI override.
    python = (_executable(os.environ['HERMES_PYTHON'])
              if 'HERMES_PYTHON' in os.environ else None)
    source = None
    if 'HERMES_SOURCE_ROOT' in os.environ:
        value = os.environ['HERMES_SOURCE_ROOT']
        source = Path(value).expanduser().absolute() if value else None
        if source is None or not (source / 'hermes_cli/runtime_provider.py').is_file():
            raise ValueError('hermes_runtime_unavailable')
    if python is not None and source is not None:
        return python, source
    launcher = Path(hermes_cli()).resolve()
    seen = set()
    while launcher not in seen and len(seen) < 8:
        seen.add(launcher)
        text = launcher.read_text()
        if text.startswith('#!') and 'python' in Path(text.splitlines()[0][2:].strip()).name:
            python = python or _executable(text.splitlines()[0][2:].strip())
            break
        lines = text.splitlines()
        command = next((line[5:] for line in lines if line.startswith('exec ')), None)
        if command is None:
            raise ValueError('hermes_runtime_unavailable')
        # shlex handles the multiline single-quoted -c payload without running it.
        argv = shlex.split(text[text.index('exec ') + 5:])
        target = Path(_executable(argv[0]))
        if '-c' in argv:
            python = python or str(target)
            tree = ast.parse(argv[argv.index('-c') + 1])
            for node in ast.walk(tree):
                if (isinstance(node, ast.Call) and ast.unparse(node.func) == 'sys.path.insert'
                        and len(node.args) == 2 and isinstance(node.args[1], ast.Constant)
                        and isinstance(node.args[1].value, str)):
                    source = source or Path(node.args[1].value)
                    break
            break
        launcher = target.resolve()
    else:
        raise ValueError('hermes_runtime_unavailable')
    if source is None:
        source = next((p for p in launcher.parents
                       if (p / 'hermes_cli/runtime_provider.py').is_file()), None)
    if python is None or source is None or not (source / 'hermes_cli/runtime_provider.py').is_file():
        raise ValueError('hermes_runtime_unavailable')
    return python, source.absolute()


def isolated_runpy_command(python, source, script) -> list[str]:
    """Isolated (-I) runtime argv: scrub env, Hermes dependency bootstrap, then run script."""
    script = Path(script)
    bootstrap = (
        "import os, sys, runpy; "
        "os.environ.pop('PYTHONHOME', None); os.environ.pop('PYTHONPATH', None); "
        "os.environ.pop('VIRTUAL_ENV', None); "
        f"sys.path.insert(0, {str(source)!r}); "
        "sys._hermes_pin_default_home = True; import hermes_bootstrap; "
        "os.environ.get('HERMES_HOME') or os.environ.__setitem__('HERMES_HOME', "
        "str(__import__('hermes_constants').get_default_hermes_root())); "
        f"sys.path.insert(0, {str(script.parent)!r}); "
        f"runpy.run_path({str(script)!r}, run_name='__main__')"
    )
    return [python, '-I', '-c', bootstrap]
