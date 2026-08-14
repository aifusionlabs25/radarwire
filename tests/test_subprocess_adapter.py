import sys, os, json, stat
from pathlib import Path
import yaml, pytest
sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'src'))
from radar.config import load_config
from radar.analysis import AnalysisValidationError, HermesCliAnalysisAdapter, json_instruction
from radar.models import Article

def make_cfg(tmp_path, script):
    data=yaml.safe_load(Path('config.v0.2.example.yaml').read_text()); data['data_dir']=str(tmp_path/'data'); data['database_url']='sqlite:///'+str(tmp_path/'data'/'x.db').replace('\\','/'); data['hermes']['command']=sys.executable; data['hermes']['profile_flag']=str(script); data['hermes']['profile']=''; data['hermes']['skill_flag']=''; data['hermes']['skill']=''; data['hermes']['toolsets']=None; data['hermes']['one_shot_flag']=''
    p=tmp_path/'c.yaml'; p.write_text(yaml.safe_dump(data)); return load_config(p)
def article(): return Article(workspace_id='w',source_id='s',canonical_url='https://x/a',title='T',content_hash='h',sanitized_text='body',status='pending')
def test_subprocess_success(tmp_path):
    s=tmp_path/'ok.py'; s.write_text('import json,sys; sys.stdin.read(); print(json.dumps({"article":{"title":"T","url":"u","summary":"s","observed_facts":["f"]},"confidence":.9}))')
    res,meta=HermesCliAnalysisAdapter(make_cfg(tmp_path,s)).analyze(article()); assert res.confidence==.9
@pytest.mark.parametrize('body',["print('not json')", "import sys; sys.exit(3)"])
def test_subprocess_invalid_and_nonzero(tmp_path, body):
    s=tmp_path/'bad.py'; s.write_text(body)
    with pytest.raises(Exception): HermesCliAnalysisAdapter(make_cfg(tmp_path,s)).analyze(article())
def test_repair_behavior(tmp_path):
    s=tmp_path/'repair.py'; s.write_text('import sys,json\np=sys.stdin.read()\nprint(json.dumps({"article":{"title":"T","url":"u","summary":"fixed","observed_facts":["f"]},"confidence":.5}) if "invalid_output" in p else "oops")')
    res,meta=HermesCliAnalysisAdapter(make_cfg(tmp_path,s)).analyze(article()); assert res.article.summary=='fixed'

def test_hermes_subprocess_env_keeps_home_runtime_and_provider_vars_without_smtp(tmp_path, monkeypatch):
    captured = {}
    def fake_run(*args, **kwargs):
        captured['env'] = kwargs['env']
        captured['encoding'] = kwargs['encoding']
        captured['errors'] = kwargs['errors']
        class Proc:
            returncode = 0
            stdout = json.dumps({"article":{"title":"T","url":"u","summary":"s","observed_facts":["f"]},"confidence":.9})
            stderr = ""
        return Proc()
    monkeypatch.setattr('radar.analysis.subprocess.run', fake_run)
    monkeypatch.setenv('USERPROFILE', r'C:\Users\AI Fusion Labs')
    monkeypatch.setenv('LOCALAPPDATA', r'C:\Users\AI Fusion Labs\AppData\Local')
    monkeypatch.setenv('HERMES_HOME', r'C:\Users\AI Fusion Labs\.hermes')
    monkeypatch.setenv('OPENROUTER_API_KEY', 'provider-secret')
    monkeypatch.setenv('RADAR_SMTP_PASSWORD', 'smtp-secret')
    s=tmp_path/'ok.py'; s.write_text('')
    HermesCliAnalysisAdapter(make_cfg(tmp_path,s)).analyze(article())
    env = captured['env']
    assert env['USERPROFILE'] == r'C:\Users\AI Fusion Labs'
    assert env['LOCALAPPDATA'] == r'C:\Users\AI Fusion Labs\AppData\Local'
    assert env['HERMES_HOME'] == r'C:\Users\AI Fusion Labs\.hermes'
    assert env['OPENROUTER_API_KEY'] == 'provider-secret'
    assert env['PYTHONIOENCODING'] == 'utf-8'
    assert env['PYTHONUTF8'] == '1'
    assert 'RADAR_SMTP_PASSWORD' not in env
    assert captured['encoding'] == 'utf-8'
    assert captured['errors'] == 'replace'


def test_subprocess_unicode_input_and_output_are_utf8(tmp_path):
    s=tmp_path/'unicode.py'
    s.write_text(
        'import json,sys\n'
        'payload=json.loads(sys.stdin.read())\n'
        'print(json.dumps({"article":{"title":payload["title"],"url":payload["url"],"summary":"UTF-8 nonbreaking hyphen: ‑","observed_facts":["café"]},"confidence":.9}, ensure_ascii=False))',
        encoding='utf-8',
    )
    item = article()
    item.title = 'UTF-8 title ‑ café'
    item.sanitized_text = 'Body with UTF-8 ‑ café'

    result, meta = HermesCliAnalysisAdapter(make_cfg(tmp_path,s)).analyze(item)

    assert result.article.title == item.title
    assert result.article.summary == 'UTF-8 nonbreaking hyphen: ‑'
    assert result.article.observed_facts == ['café']


def test_hermes_prompt_includes_article_payload_for_oneshot(tmp_path, monkeypatch):
    captured = {}
    def fake_run(cmd, **kwargs):
        captured['cmd'] = cmd
        class Proc:
            returncode = 0
            stdout = json.dumps({"article":{"title":"T","url":"https://x/a","summary":"s","observed_facts":["f"]},"confidence":.9})
            stderr = ""
        return Proc()
    monkeypatch.setattr('radar.analysis.subprocess.run', fake_run)
    s=tmp_path/'ok.py'; s.write_text('')
    HermesCliAnalysisAdapter(make_cfg(tmp_path,s)).analyze(article())
    prompt = captured['cmd'][-1]
    assert 'ARTICLE_PAYLOAD_JSON' in prompt
    assert '"title": "T"' in prompt
    assert '"url": "https://x/a"' in prompt


def test_hermes_schema_valid_no_payload_fallback_is_rejected(tmp_path, monkeypatch):
    def fake_run(*args, **kwargs):
        class Proc:
            returncode = 0
            stdout = json.dumps({"article":{"title":"","url":"","summary":"No competitor article payload was provided to analyze.","observed_facts":[]},"confidence":0})
            stderr = ""
        return Proc()
    monkeypatch.setattr('radar.analysis.subprocess.run', fake_run)
    s=tmp_path/'ok.py'; s.write_text('')
    with pytest.raises(ValueError, match='title or URL|no-payload|confidence'):
        HermesCliAnalysisAdapter(make_cfg(tmp_path,s)).analyze(article())


def test_evidence_quotes_over_five_are_trimmed_with_metadata_warning(tmp_path, monkeypatch):
    def fake_run(*args, **kwargs):
        class Proc:
            returncode = 0
            stdout = json.dumps({"article":{"title":"T","url":"https://x/a","summary":"s","observed_facts":["f"],"evidence_quotes":[str(i) for i in range(10)]},"confidence":.9})
            stderr = ""
        return Proc()
    monkeypatch.setattr('radar.analysis.subprocess.run', fake_run)
    s=tmp_path/'ok.py'; s.write_text('')
    result, meta = HermesCliAnalysisAdapter(make_cfg(tmp_path,s)).analyze(article())
    assert result.article.evidence_quotes == ['0', '1', '2', '3', '4']
    assert meta['repair_notes'] == ['trimmed article.evidence_quotes from 10 to 5']


def test_prompt_explicitly_caps_evidence_quotes():
    instruction = json_instruction(False)
    assert 'evidence_quotes' in instruction
    assert '0 to 5 strings' in instruction
    assert '<= 240 chars' in instruction
    assert 'client_relevance' in instruction


def test_hermes_prompt_includes_public_client_context(tmp_path, monkeypatch):
    captured = {}
    def fake_run(cmd, **kwargs):
        captured['cmd'] = cmd
        class Proc:
            returncode = 0
            stdout = json.dumps({"article":{"title":"T","url":"https://x/a","summary":"s","observed_facts":["f"]},"confidence":.9,"client_relevance":.95,"relevance_reason":"Direct fit"})
            stderr = ""
        return Proc()
    monkeypatch.setattr('radar.analysis.subprocess.run', fake_run)
    s=tmp_path/'ok.py'; s.write_text('')
    cfg = make_cfg(tmp_path,s)
    cfg.client.name = '1099FIRE'
    cfg.client.offerings = ['1099 e-filing software']

    result, _ = HermesCliAnalysisAdapter(cfg).analyze(article())

    prompt = captured['cmd'][-1]
    assert 'CLIENT_CONTEXT_JSON' in prompt
    assert '1099FIRE' in prompt
    assert '1099 e-filing software' in prompt
    assert result.client_relevance == .95


def test_validation_error_preserves_raw_subprocess_metadata(tmp_path, monkeypatch):
    def fake_run(*args, **kwargs):
        class Proc:
            returncode = 0
            stdout = json.dumps({"article":{"title":"","url":"","summary":"No competitor article payload was provided to analyze.","observed_facts":[]},"confidence":0})
            stderr = "stderr stays available"
        return Proc()
    monkeypatch.setattr('radar.analysis.subprocess.run', fake_run)
    s=tmp_path/'ok.py'; s.write_text('')
    with pytest.raises(AnalysisValidationError) as exc:
        HermesCliAnalysisAdapter(make_cfg(tmp_path,s)).analyze(article())
    assert exc.value.meta['exit_code'] == 0
    assert 'No competitor article payload' in exc.value.meta['stdout']
    assert exc.value.meta['stderr'] == 'stderr stays available'
