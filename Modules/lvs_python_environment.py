"""Standard-library-only environment metadata; safe before LVS can import.

Package versions belong exclusively to the requirement files. Python policy is
read from the shared POSIX policy, rather than maintaining another version list.
Keep this module compatible with older Python bootstrap interpreters.
"""
import re
from pathlib import Path

PYTHON_GROUPS = {
    'baseline': {'requirements': 'requirements.txt', 'imports': ('textual',)},
    'google': {'requirements': 'requirements-google.txt', 'imports': (
        'google.oauth2.service_account', 'googleapiclient.discovery', 'googleapiclient.http')},
}


def python_policy(root):
    text = (Path(root) / 'scripts/lvs_python_policy.sh').read_text(encoding='utf-8')
    def version(prefix):
        values = []
        for part in ('MAJOR', 'MINOR'):
            match = re.search(r'^readonly ' + prefix + '_' + part + r'=(\d+)\s*$', text, re.M)
            if not match:
                raise ValueError('Python policy unavailable in scripts/lvs_python_policy.sh')
            values.append(int(match.group(1)))
        return tuple(values)
    return {'minimum': version('MINIMUM'), 'tested': version('TESTED')}


def requirement_pins(root, group):
    """Inspect this project's exact direct pins; never guess unsupported syntax."""
    result = []
    path = Path(root) / PYTHON_GROUPS[group]['requirements']
    for line in path.read_text(encoding='utf-8').splitlines():
        line = line.split('#', 1)[0].strip()
        if not line:
            continue
        match = re.fullmatch(r'([A-Za-z0-9][A-Za-z0-9_.-]*)==([A-Za-z0-9_.+!-]+)', line)
        if not match:
            raise ValueError('Cannot independently verify requirement syntax: ' + line)
        result.append(match.groups())
    return result
