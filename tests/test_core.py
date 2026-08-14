import json, os, sys, subprocess, textwrap, threading, time
from pathlib import Path
import pytest, yaml
from typer.testing import CliRunner
sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'src'))
from radar.cli import app
from radar.config import load_config
from radar.urlsec import canonicalize_url, validate_public_http_url
from radar.extract import extract_article, sanitize_text
from radar.models import make_session_factory, Article, Outbox
from radar.repository import RadarRepository
from radar.analysis import HermesCliAnalysisAdapter, DeterministicAnalysisAdapter, AnalysisEnvelope
from radar.emailer import build_email, deliver_or_preview, deliver_existing_report, email_subject
from radar.pipeline import run_pipeline, status, backup, restore, fetch_article_with_retries


def cfg_file(tmp_path, extra=None):
    data=yaml.safe_load(Path('config.v0.2.example.yaml').read_text())
    data['data_dir']=str(tmp_path/'data'); data['database_url']='sqlite:///'+str(tmp_path/'data'/'radar.db').replace('\\','/')
    if extra:
        for k,v in extra.items(): data[k]=v
    p=tmp_path/'config.yaml'; p.write_text(yaml.safe_dump(data)); return p

def test_config_uses_corrected_email_but_live_send_stays_disabled(tmp_path):
    c=load_config(cfg_file(tmp_path))
    assert c.email.recipient_email == 'recipient@example.com'
    assert c.email.reply_to_email == 'reply@example.com'
    assert c.email.invalid_addresses() == []
    with pytest.raises(ValueError, match='disabled|preview'):
        c.email.assert_live_send_allowed()

def test_config_blocks_invalid_email_before_smtp(tmp_path):
    p = cfg_file(tmp_path)
    data = yaml.safe_load(Path(p).read_text())
    data['email']['recipient_email'] = 'bad#example.com'
    Path(p).write_text(yaml.safe_dump(data))
    c = load_config(p)
    assert 'recipient_email=bad#example.com' in c.email.invalid_addresses()
    with pytest.raises(ValueError, match='Invalid email'):
        c.email.assert_live_send_allowed()

def test_url_normalization_and_scope():
    assert canonicalize_url('https://www.taxjar.com/blog/x?utm_source=chatgpt.com&ok=1')=='https://www.taxjar.com/blog/x?ok=1'
    with pytest.raises(ValueError): validate_public_http_url('http://evil.com/blog/x',['www.taxjar.com'],['/blog/'])
    assert validate_public_http_url('https://www.taxjar.com/blog/x',['www.taxjar.com'],['/blog/'])

def test_extract_sanitizes_and_hashes():
    a=extract_article('<html><title>T</title><script>bad()</script><article>Hello <b>world</b></article></html>','https://x/a')
    assert a.title=='T' and 'bad' not in a.sanitized_text and len(a.content_hash)==64

def test_repository_baseline_and_update(tmp_path):
    c=load_config(cfg_file(tmp_path)); Session,_=make_session_factory(c.database_url)
    art=extract_article('<article>one</article>','https://www.taxjar.com/blog/a')
    with Session.begin() as s:
        r=RadarRepository(s,c.workspace_id); a,st=r.upsert_article('taxjar-blog', art, baseline=True); assert st=='baseline'; assert not r.pending_articles()
        art2=extract_article('<article>two</article>','https://www.taxjar.com/blog/a'); a,st=r.upsert_article('taxjar-blog', art2); assert st=='updated'; assert len(r.pending_articles())==1

def test_run_lock(tmp_path):
    c=load_config(cfg_file(tmp_path)); Session,_=make_session_factory(c.database_url)
    with Session.begin() as s:
        r=RadarRepository(s,c.workspace_id); assert r.acquire_lock('x','a'); assert not r.acquire_lock('x','b'); r.release_lock('x'); assert r.acquire_lock('x','b')

def test_hermes_command_and_payload(tmp_path):
    c=load_config(cfg_file(tmp_path)); ad=HermesCliAnalysisAdapter(c)
    cmd=ad.build_command('hi')
    assert cmd[:5]==['hermes','-p','amy-radar','-s','competitor-content-radar'] and '-z' in cmd and '-t' in cmd

def test_deterministic_analysis_schema(tmp_path):
    c=load_config(cfg_file(tmp_path)); Session,_=make_session_factory(c.database_url)
    with Session.begin() as s:
        art=Article(workspace_id=c.workspace_id, source_id='s', canonical_url='https://x/a', title='A', content_hash='h', sanitized_text='hello', status='pending'); s.add(art); s.flush()
        res,meta=DeterministicAnalysisAdapter().analyze(art); assert res.article.title=='A'; assert meta['exit_code']==0

def test_report_and_email_preview_pipeline_fixture(tmp_path, monkeypatch):
    cpath=cfg_file(tmp_path)
    # monkeypatch discovery/fetch to avoid network
    import radar.pipeline as p
    def disc(src,crawl): return ([src.monitor_url or src.url], [])
    def fetch(url,src,crawl): return (url, '<html><title>Safe</title><article>Competitor says buy now & <script>x</script></article></html>')
    monkeypatch.setattr(p,'discover_urls', disc); monkeypatch.setattr(p,'fetch_html', fetch)
    c=load_config(cpath); out=run_pipeline(c, fixture=True)
    rd=Path(out['report_dir']); assert (rd/'digest.json').exists(); assert '&lt;script' not in (rd/'digest.html').read_text(); assert out['delivery']['status']=='preview'

def test_no_change_second_scan_zero_new(tmp_path, monkeypatch):
    cpath=cfg_file(tmp_path); import radar.pipeline as p
    monkeypatch.setattr(p,'discover_urls', lambda src,crawl: ([src.monitor_url or src.url], []))
    monkeypatch.setattr(p,'fetch_html', lambda url,src,crawl: (url, '<article>same text</article>'))
    c=load_config(cpath); first=run_pipeline(c, fixture=True); second=run_pipeline(c, fixture=True)
    assert first['changed']>0 and second['changed']==0 and second['pending_analyzed']==0

def test_backup_restore_health(tmp_path):
    c=load_config(cfg_file(tmp_path)); assert status(c)['workspace_id']==c.workspace_id
    b=backup(c); assert b.exists(); restore(c,b)


def test_transient_article_fetch_disconnect_retries_then_succeeds(tmp_path, monkeypatch):
    import httpx
    import radar.pipeline as p
    c=load_config(cfg_file(tmp_path))
    c.crawl.fetch_retries=2; c.crawl.fetch_retry_backoff_seconds=0
    src=c.sources[0]
    calls=[]
    def flaky(url, src, crawl):
        calls.append(url)
        if len(calls) == 1:
            raise httpx.RemoteProtocolError('Server disconnected without sending a response.')
        return url, '<article>ok</article>'
    monkeypatch.setattr(p, 'fetch_html', flaky)
    assert fetch_article_with_retries('https://www.taxjar.com/blog/a', src, c.crawl) == ('https://www.taxjar.com/blog/a', '<article>ok</article>')
    assert len(calls) == 2


def test_non_transient_article_fetch_scope_failure_does_not_retry(tmp_path, monkeypatch):
    import radar.pipeline as p
    c=load_config(cfg_file(tmp_path))
    c.crawl.fetch_retries=2; c.crawl.fetch_retry_backoff_seconds=0
    src=c.sources[0]
    calls=[]
    def invalid(url, src, crawl):
        calls.append(url)
        raise ValueError('URL outside configured scope')
    monkeypatch.setattr(p, 'fetch_html', invalid)
    with pytest.raises(ValueError):
        fetch_article_with_retries('https://evil.example/blog/a', src, c.crawl)
    assert len(calls) == 1


def test_retry_exhaustion_records_one_clear_source_error(tmp_path, monkeypatch):
    import httpx
    import radar.pipeline as p
    cpath=cfg_file(tmp_path)
    c=load_config(cpath)
    c.crawl.fetch_retries=2; c.crawl.fetch_retry_backoff_seconds=0
    monkeypatch.setattr(p,'discover_urls', lambda src,crawl: ([src.monitor_url or src.url], []))
    def always_disconnect(url,src,crawl):
        raise httpx.RemoteProtocolError('Server disconnected without sending a response.')
    monkeypatch.setattr(p,'fetch_html', always_disconnect)
    out=run_pipeline(c, fixture=False, use_hermes=False)
    errs=out['source_errors'][c.sources[0].id]
    assert len(errs) == 1
    assert 'Server disconnected without sending a response' in errs[0]


def _write_report_artifacts(cfg, run_id='r1'):
    report_dir=cfg.data_dir/'reports'/run_id
    report_dir.mkdir(parents=True, exist_ok=True)
    digest={'schema_version':'test','article_count':1,'source_error_count':0,'articles':[{'url':'https://example.com/a','title':'A','summary':'S','content_hash':'h'}]}
    (report_dir/'digest.json').write_text(json.dumps(digest), encoding='utf-8')
    (report_dir/'digest.html').write_text('<html>A</html>', encoding='utf-8')
    (report_dir/'digest.txt').write_text('A', encoding='utf-8')
    (report_dir/'digest_email.html').write_text('<html>Email A</html>', encoding='utf-8')
    (report_dir/'digest_email.txt').write_text('Email A', encoding='utf-8')
    (report_dir/'digest.md').write_text('# A', encoding='utf-8')
    (report_dir/'run-summary.json').write_text(json.dumps({'run_id':run_id}), encoding='utf-8')
    return report_dir


class FakeProvider:
    def __init__(self): self.sent=[]
    def send(self, msg):
        self.sent.append(msg)
        return 'fake-sent'


def test_deliver_existing_report_preview_delivery(tmp_path):
    c=load_config(cfg_file(tmp_path))
    _write_report_artifacts(c)
    Session,_=make_session_factory(c.database_url)
    with Session.begin() as s:
        result=deliver_existing_report(RadarRepository(s,c.workspace_id), c, 'r1')
    assert result['delivery']['status']=='preview'
    with Session() as s:
        rows=s.execute(__import__('sqlalchemy').select(Outbox)).scalars().all()
        assert len(rows)==1 and rows[0].status=='preview'
        assert 'digest_email.html' in rows[0].provider_response


def test_deliver_report_refuses_live_config_without_send(tmp_path):
    p=cfg_file(tmp_path)
    data=yaml.safe_load(Path(p).read_text())
    data['dry_run']=False; data['email']['enabled']=True; data['email']['preview_only']=False
    Path(p).write_text(yaml.safe_dump(data), encoding='utf-8')
    c=load_config(p); _write_report_artifacts(c)
    result=CliRunner().invoke(app, ['deliver-report','--config',str(p),'--run-id','r1'])
    assert result.exit_code==2
    assert 'Refusing live-send-capable config without --send' in result.output


def test_deliver_existing_report_idempotency_skips_duplicate_sent(tmp_path):
    p=cfg_file(tmp_path)
    data=yaml.safe_load(Path(p).read_text())
    data['dry_run']=False; data['email']['enabled']=True; data['email']['preview_only']=False
    Path(p).write_text(yaml.safe_dump(data), encoding='utf-8')
    c=load_config(p); _write_report_artifacts(c)
    provider=FakeProvider()
    Session,_=make_session_factory(c.database_url)
    with Session.begin() as s:
        first=deliver_existing_report(RadarRepository(s,c.workspace_id), c, 'r1', send=True, provider=provider)
    with Session.begin() as s:
        second=deliver_existing_report(RadarRepository(s,c.workspace_id), c, 'r1', send=True, provider=provider)
    assert first['delivery']['status']=='sent'
    assert first['delivery']['html_artifact']=='digest_email.html'
    assert second['delivery']['status']=='duplicate_skipped'
    assert len(provider.sent)==1


def test_deliver_existing_report_uses_email_specific_body_when_present(tmp_path):
    c=_live_email_cfg(tmp_path)
    provider=FakeProvider()
    Session,_=make_session_factory(c.database_url)
    with Session.begin() as s:
        result=deliver_existing_report(RadarRepository(s,c.workspace_id), c, 'r1', send=True, provider=provider)

    assert result['delivery']['html_artifact']=='digest_email.html'
    assert result['delivery']['text_artifact']=='digest_email.txt'
    sent=provider.sent[0]
    assert sent.get_body(preferencelist=('plain',)).get_content().strip()=='Email A'
    assert 'Email A' in sent.get_body(preferencelist=('html',)).get_content()
    assert '<html>A</html>' not in sent.get_body(preferencelist=('html',)).get_content()


def test_deliver_report_command_does_not_invoke_discovery_fetch_or_hermes(tmp_path, monkeypatch):
    p=cfg_file(tmp_path)
    c=load_config(p); _write_report_artifacts(c)
    import radar.pipeline as pipeline
    import radar.analysis as analysis
    monkeypatch.setattr(pipeline, 'discover_urls', lambda *a, **k: (_ for _ in ()).throw(AssertionError('discovery called')))
    monkeypatch.setattr(pipeline, 'fetch_html', lambda *a, **k: (_ for _ in ()).throw(AssertionError('fetch called')))
    monkeypatch.setattr(analysis.HermesCliAnalysisAdapter, 'analyze', lambda *a, **k: (_ for _ in ()).throw(AssertionError('hermes called')))
    result=CliRunner().invoke(app, ['deliver-report','--config',str(p),'--run-id','r1'])
    assert result.exit_code==0, result.output
    assert 'preview' in result.output


def test_export_report_site_writes_static_route_without_send_or_deploy(tmp_path):
    p=cfg_file(tmp_path)
    c=load_config(p); _write_report_artifacts(c)
    export_root=tmp_path/'site-export'

    result=CliRunner().invoke(app, ['export-report-site','--config',str(p),'--run-id','r1','--output-dir',str(export_root),'--base-url','https://reports.example.com'])

    assert result.exit_code==0, result.output
    payload=json.loads(result.output)
    destination=export_root/'reports'/'r1'
    assert payload['route']=='/reports/r1/'
    assert payload['hosted_url']=='https://reports.example.com/reports/r1/'
    assert payload['sends_email'] is False
    assert payload['deploys'] is False
    assert (destination/'index.html').read_text(encoding='utf-8')=='<html>A</html>'
    assert (destination/'digest_email.html').read_text(encoding='utf-8')=='<html>Email A</html>'


def test_export_report_site_can_replace_a_stable_route_without_changing_run_metadata(tmp_path):
    p=cfg_file(tmp_path)
    c=load_config(p); _write_report_artifacts(c)
    export_root=tmp_path/'site-export'

    result=CliRunner().invoke(app, ['export-report-site','--config',str(p),'--run-id','r1','--output-dir',str(export_root),'--route-name','1099fire-radar','--base-url','https://reports.example.com','--overwrite'])

    assert result.exit_code==0, result.output
    payload=json.loads(result.output)
    destination=export_root/'reports'/'1099fire-radar'
    assert payload['run_id']=='r1'
    assert payload['route_name']=='1099fire-radar'
    assert payload['route']=='/reports/1099fire-radar/'
    assert payload['hosted_url']=='https://reports.example.com/reports/1099fire-radar/'
    assert payload['exported_at'].endswith('+00:00')
    assert payload['source_report_dir']=='reports/r1'
    assert payload['destination']=='/reports/1099fire-radar/'
    assert json.loads((destination/'report-site.json').read_text(encoding='utf-8'))['run_id']=='r1'


def test_export_report_site_refuses_unsafe_route_name(tmp_path):
    p=cfg_file(tmp_path)
    c=load_config(p); _write_report_artifacts(c)

    result=CliRunner().invoke(app, ['export-report-site','--config',str(p),'--run-id','r1','--output-dir',str(tmp_path/'site-export'),'--route-name','../latest'])

    assert result.exit_code==2
    assert 'single safe URL segment' in result.output


def test_publish_preflight_requires_preview_only_email_disabled_config(tmp_path):
    p=cfg_file(tmp_path)
    safe=CliRunner().invoke(app, ['publish-preflight','--config',str(p)])
    data=yaml.safe_load(Path(p).read_text())
    data['dry_run']=False
    Path(p).write_text(yaml.safe_dump(data), encoding='utf-8')
    unsafe=CliRunner().invoke(app, ['publish-preflight','--config',str(p)])

    assert safe.exit_code==0, safe.output
    assert json.loads(safe.output)['ok'] is True
    assert unsafe.exit_code==2
    assert json.loads(unsafe.output)['ok'] is False


def test_export_report_site_refuses_existing_export_without_overwrite(tmp_path):
    p=cfg_file(tmp_path)
    c=load_config(p); _write_report_artifacts(c)
    export_root=tmp_path/'site-export'
    first=CliRunner().invoke(app, ['export-report-site','--config',str(p),'--run-id','r1','--output-dir',str(export_root)])
    second=CliRunner().invoke(app, ['export-report-site','--config',str(p),'--run-id','r1','--output-dir',str(export_root)])

    assert first.exit_code==0, first.output
    assert second.exit_code==2
    assert 'refused_existing_export' in second.output


class FailingThenSuccessProvider:
    def __init__(self):
        self.calls=0
    def send(self, msg):
        self.calls += 1
        if self.calls == 1:
            raise RuntimeError('smtp connection refused on localhost test port')
        return 'fake-sent-after-retry'


def _live_email_cfg(tmp_path):
    p=cfg_file(tmp_path)
    data=yaml.safe_load(Path(p).read_text())
    data['dry_run']=False; data['email']['enabled']=True; data['email']['preview_only']=False
    Path(p).write_text(yaml.safe_dump(data), encoding='utf-8')
    c=load_config(p); _write_report_artifacts(c)
    return c


def test_smtp_provider_exception_records_failed_outbox_without_sent_at(tmp_path):
    c=_live_email_cfg(tmp_path)
    provider=FailingThenSuccessProvider()
    Session,_=make_session_factory(c.database_url)
    with Session.begin() as s:
        result=deliver_existing_report(RadarRepository(s,c.workspace_id), c, 'r1', send=True, provider=provider)
    assert result['delivery']['status']=='failed'
    with Session() as s:
        row=s.execute(__import__('sqlalchemy').select(Outbox)).scalar_one()
        assert row.status=='failed'
        assert row.attempt_count==1
        assert row.sent_at is None
        assert 'RuntimeError' in row.provider_response
        assert 'smtp connection refused' in row.provider_response


def test_email_subject_uses_ascii_hyphen_without_mojibake(tmp_path):
    c=load_config(cfg_file(tmp_path))
    subject=email_subject(c.email, 9, '42915827efff')
    assert subject == '[Competitor Radar] 9 article(s) - 42915827efff'
    assert '—' not in subject
    assert 'â€”' not in subject


def test_retry_after_failed_send_can_send_once_then_duplicate_skip(tmp_path):
    c=_live_email_cfg(tmp_path)
    provider=FailingThenSuccessProvider()
    Session,_=make_session_factory(c.database_url)
    with Session.begin() as s:
        first=deliver_existing_report(RadarRepository(s,c.workspace_id), c, 'r1', send=True, provider=provider)
    with Session.begin() as s:
        second=deliver_existing_report(RadarRepository(s,c.workspace_id), c, 'r1', send=True, provider=provider)
    with Session.begin() as s:
        third=deliver_existing_report(RadarRepository(s,c.workspace_id), c, 'r1', send=True, provider=provider)
    assert first['delivery']['status']=='failed'
    assert second['delivery']['status']=='sent'
    assert third['delivery']['status']=='duplicate_skipped'
    assert provider.calls==2
    with Session() as s:
        row=s.execute(__import__('sqlalchemy').select(Outbox)).scalar_one()
        assert row.status=='sent'
        assert row.sent_at is not None
        assert row.attempt_count==2
        assert row.subject == '[Competitor Radar] 1 article(s) - r1'
