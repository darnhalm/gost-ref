import io
import json

import pytest

from gost_ref.cli import main


@pytest.mark.parametrize('command', ['format', 'pair', 'all', 'reformat', 'list'])
@pytest.mark.parametrize('enabled', [False, True])
def test_cli_content_profile(command, enabled, monkeypatch, capsys):
    """Every rendering command must honor the user's selected profile."""
    fields = dict(type='article', authors='Иванов И. И.', title='Заглавие',
                  container='Журнал', year='2020', issue='1', pages='2-5')
    args = [command]
    if enabled:
        args.append('--content-type')
    if command == 'reformat':
        args.append('Иванов И. И. Заглавие // Журнал. 2020. № 1. С. 2-5.')
    else:
        payload = [fields] if command == 'list' else fields
        monkeypatch.setattr('sys.stdin', io.StringIO(json.dumps(payload)))
    assert main(args) == 0
    result = json.loads(capsys.readouterr().out)
    if command == 'pair':
        text = result['record']['text']
        assert 'Текст :' not in result['footnote']['text']
    elif command == 'all':
        text = result['7.0.100']
        assert all('Текст :' not in result[s] for s in ['7.0.5', '7.1', '7.0.108'])
    elif command == 'list':
        text = result['entries'][0]['reference']
    else:
        text = result['reference']
    assert ('Текст : непосредственный' in text) == enabled
    if enabled:
        assert text.index('Текст : непосредственный') < text.index('//')
