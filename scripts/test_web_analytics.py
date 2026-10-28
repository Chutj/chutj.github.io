"""Isolated synthetic fixtures: no real analytics calls, FIG writes or public counts."""
import copy
import datetime as dt
import io
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
import urllib.error
from unittest.mock import patch

import archive_web_analytics as analytics

REAL_FETCH_DAY = analytics.fetch_day


class ArchiveTest(unittest.TestCase):
    def setUp(self):
        parent = analytics.ROOT/'.analytics-local/tests';parent.mkdir(parents=True,exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(dir=parent);self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        for name in ('analytics','data'):(self.root/name).mkdir()
        for name in ('analytics/settings.json','analytics/history.json','data/site-analytics.json','hugo.toml'):
            shutil.copyfile(analytics.ROOT/name,self.root/name)
        self.config = analytics.settings(self.root)
        self.config['start_date'] = '2026-10-25'
        self.write('analytics/settings.json',self.config)
        self.now = dt.datetime(2026,10,28,8,43,tzinfo=analytics.TZ)
        self.binding = analytics.hashlib.sha256(('a'*32+':'+'b'*32).encode()).hexdigest()

    def write(self,name,value):
        (self.root/name).write_bytes(analytics.encoded(value))

    def response(self,count=5):
        item = dict(total=[dict(count=count,avg=dict(sampleInterval=1))],
                    home=[dict(count=2 if count else 0)],gallery=[dict(count=3 if count else 0)],gee_access=[],
                    countries=[dict(count=count,dimensions=dict(countryName='CN'))] if count else [])
        return dict(data=dict(viewer=dict(accounts=[item])),errors=None)

    def fetch(self,day='2026-10-25',response=None):
        with patch.object(analytics,'request',return_value=self.response() if response is None else response):
            return REAL_FETCH_DAY(self.config,'a'*32,'b'*32,'private-test-secret',day,self.now)

    def seed(self,days):
        value=analytics.history(self.root,self.config)
        value.update(start_date=self.config['start_date'],site_binding_sha256=self.binding,days=days)
        self.write('analytics/history.json',value)

    def run_collect(self,fetcher=None,now=None):
        with patch.object(analytics,'credentials',return_value=('a'*32,'b'*32,'private-test-secret','c'*32)), \
             patch.object(analytics,'verify_site'), \
             patch.object(analytics,'fetch_day',side_effect=fetcher or (lambda c,a,s,t,d,n:self.fetch(d))):
            return analytics.collect(self.root,dry_run=False,now=now or self.now)

    def test_unconfigured_is_null_and_never_calls_network_or_writes(self):
        self.config['start_date']=None;self.write('analytics/settings.json',self.config)
        before=(self.root/'analytics/history.json').read_bytes()
        with patch.object(analytics,'request') as network:
            result=analytics.collect(self.root,dry_run=True,now=self.now)
            public=analytics.snapshot(self.root,now=self.now)
        self.assertEqual(result['status'],'not_configured');self.assertFalse(result['writes'])
        self.assertIsNone(public['total_page_views']);network.assert_not_called()
        self.assertEqual(before,(self.root/'analytics/history.json').read_bytes())
        with patch.object(analytics,'request') as network:
            with self.assertRaisesRegex(analytics.AnalyticsError,'not configured'):
                analytics.collect(self.root,dry_run=False,now=self.now)
            with self.assertRaisesRegex(analytics.AnalyticsError,'not configured'):
                analytics.snapshot(self.root,write=True,now=self.now)
            network.assert_not_called()

    def test_dry_plan_includes_missing_days_without_credentials(self):
        with patch.object(analytics,'credentials') as credentials:
            result=analytics.collect(self.root,dry_run=True,now=self.now)
        self.assertEqual(result['dates'],['2026-10-25','2026-10-26','2026-10-27'])
        credentials.assert_not_called();self.assertFalse(result['network'])

    def test_china_calendar_boundaries_and_exact_host_site_page_filters(self):
        query=analytics.query(self.config,'a'*32,'b'*32,'2026-12-31')
        for text in ['2026-12-30T16:00:00Z','2026-12-31T16:00:00Z','datetime_geq','datetime_lt',
                     'siteTag: "'+('b'*32)+'"','requestHost: "chutj.github.io"','requestPath: "/gallery/"']:
            self.assertIn(text,query)
        self.assertNotIn('private-test-secret',query)

    def test_repeat_run_is_idempotent_and_source_correction_replaces_one_day(self):
        first=self.run_collect();path=self.root/'analytics/history.json';before=path.read_bytes()
        second=self.run_collect(now=self.now+dt.timedelta(minutes=10))
        self.assertTrue(first['writes']);self.assertFalse(second['writes']);self.assertEqual(before,path.read_bytes())
        def corrected(c,a,s,t,d,n):return self.fetch(d,self.response(7 if d=='2026-10-26' else 5))
        self.run_collect(corrected)
        days=analytics.load(path)['days'];self.assertEqual(len(days),3)
        self.assertEqual(sum(d['page_views'] for d in days),17)

    def test_mid_batch_failure_preserves_entire_existing_archive(self):
        self.seed([self.fetch()]);before=(self.root/'analytics/history.json').read_bytes()
        def broken(c,a,s,t,d,n):
            if d=='2026-10-26':raise analytics.AnalyticsError('Fixture network failure')
            return self.fetch(d)
        with self.assertRaises(analytics.AnalyticsError):self.run_collect(broken)
        self.assertEqual(before,(self.root/'analytics/history.json').read_bytes())

    def test_missing_or_partial_api_data_is_not_silently_stored_as_zero(self):
        malformed=[{},[],dict(errors=[dict(message='private-test-secret')]),dict(data=dict(viewer=dict(accounts=[])))]
        value=self.response();del value['data']['viewer']['accounts'][0]['total'];malformed.append(value)
        value=self.response();value['data']['viewer']['accounts'][0]['countries']=None;malformed.append(value)
        for payload in malformed:
            with self.subTest(payload_type=type(payload).__name__),self.assertRaises(analytics.AnalyticsError) as caught:
                self.fetch(response=payload)
            self.assertNotIn('private-test-secret',str(caught.exception))
        zero=self.fetch(response=self.response(0));self.assertEqual(zero['page_views'],0)

    def test_truncated_countries_and_negative_or_boolean_counts_fail_closed(self):
        value=self.response();value['data']['viewer']['accounts'][0]['countries']=[{}]*analytics.COUNTRY_LIMIT
        with self.assertRaisesRegex(analytics.AnalyticsError,'truncated'):self.fetch(response=value)
        for count in (-1,True,3.5):
            with self.assertRaises(analytics.AnalyticsError):self.fetch(response=self.response(count))

    def test_sample_interval_is_recorded_without_multiplying_estimated_counts(self):
        value=self.response();value['data']['viewer']['accounts'][0]['total'][0]['avg']['sampleInterval']=4
        row=self.fetch(response=value);self.assertEqual(row['page_views'],5);self.assertEqual(row['sample_interval'],4)

    def test_site_and_live_beacon_must_match_before_collecting_zero_days(self):
        site=dict(success=True,result=dict(site_tag='b'*32,site_token='c'*32,rules=[dict(host='chutj.github.io',inclusive=True)]))
        html='<script src="https://static.cloudflareinsights.com/beacon.min.js" data-cf-beacon=\'{"token":"'+('c'*32)+'"}\'></script>'
        with patch.object(analytics,'request',side_effect=[site,html]):
            analytics.verify_site(self.config,'a'*32,'b'*32,'private-test-secret','c'*32)
        for wrong in [dict(site_tag='d'*32),dict(site_token='d'*32),dict(rules=[])]:
            value=copy.deepcopy(site);value['result'].update(wrong)
            with patch.object(analytics,'request',return_value=value),self.assertRaises(analytics.AnalyticsError):
                analytics.verify_site(self.config,'a'*32,'b'*32,'private-test-secret','c'*32)
        for page in ['',html+html,html.replace('c'*32,'d'*32)]:
            with patch.object(analytics,'request',side_effect=[site,page]),self.assertRaises(analytics.AnalyticsError):
                analytics.verify_site(self.config,'a'*32,'b'*32,'private-test-secret','c'*32)

    def test_site_replacement_duplicate_days_and_changed_start_are_not_merged(self):
        self.seed([self.fetch()]);path=self.root/'analytics/history.json'
        value=analytics.load(path);value['site_binding_sha256']='0'*64;self.write('analytics/history.json',value)
        with self.assertRaisesRegex(analytics.AnalyticsError,'cannot be silently combined'):self.run_collect()
        value['site_binding_sha256']=self.binding;value['days']*=2;self.write('analytics/history.json',value)
        with self.assertRaisesRegex(analytics.AnalyticsError,'Duplicate'):analytics.history(self.root,self.config)
        value['days']=value['days'][:1];self.write('analytics/history.json',value)
        changed=dict(self.config,start_date='2026-10-24')
        with self.assertRaisesRegex(analytics.AnalyticsError,'migration'):analytics.history(self.root,changed)

    def test_snapshot_sums_days_once_and_refuses_gaps(self):
        self.seed([self.fetch(day=d) for d in ['2026-10-25','2026-10-26','2026-10-27']])
        result=analytics.snapshot(self.root,write=True,through='2026-10-27',now=self.now)
        self.assertEqual(result['total_page_views'],15);self.assertEqual(result['countries'],{'CN':15})
        self.assertNotIn('visitors',result);self.assertNotIn('followers',result)
        path=self.root/'data/site-analytics.json';before=path.read_bytes()
        self.seed([self.fetch(day=d) for d in ['2026-10-25','2026-10-27']])
        with self.assertRaisesRegex(analytics.AnalyticsError,'missing'):analytics.snapshot(self.root,write=True,through='2026-10-27',now=self.now)
        self.assertEqual(before,path.read_bytes())

    def test_monthly_snapshot_uses_previous_month_and_keeps_history_beyond_six_months(self):
        self.seed([self.fetch(day='2026-10-'+str(d)) for d in range(25,32)])
        result=analytics.snapshot(self.root,now=dt.datetime(2026,11,1,10,tzinfo=analytics.TZ))
        self.assertEqual(result['through'],'2026-10-31');self.assertEqual(result['total_page_views'],35)
        result=analytics.snapshot(self.root,through='2026-10-31',now=dt.datetime(2027,11,1,tzinfo=analytics.TZ))
        self.assertEqual(result['total_page_views'],35)

    def test_failed_http_request_does_not_echo_token_or_response_body(self):
        error=urllib.error.HTTPError(analytics.API+'/graphql',403,'forbidden',{},io.BytesIO(b'private-test-secret'))
        with patch('urllib.request.OpenerDirector.open',side_effect=error),self.assertRaises(analytics.AnalyticsError) as caught:
            analytics.request(analytics.API+'/graphql','private-test-secret',{})
        self.assertIn('403',str(caught.exception));self.assertNotIn('private-test-secret',str(caught.exception))
        with self.assertRaises(analytics.AnalyticsError):analytics.request('https://example.invalid/','private-test-secret')

    def test_stale_missing_history_needs_review_not_fabricated_zeros(self):
        with self.assertRaisesRegex(analytics.AnalyticsError,'expired'):
            analytics.plan(self.config,analytics.history(self.root,self.config),dt.date(2027,10,28))


@unittest.skipUnless(shutil.which('hugo'),'Hugo is required for real template rendering')
class BeaconTemplateTest(unittest.TestCase):
    def setUp(self):
        parent=analytics.ROOT/'.analytics-local/tests';parent.mkdir(parents=True,exist_ok=True)
        self.temp=tempfile.TemporaryDirectory(dir=parent);self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name)
        for folder in ('layouts/_partials','layouts/_default','content/gallery','content/gee-access'):
            (self.root/folder).mkdir(parents=True)
        for name in ('web-analytics.html','extend_footer.html'):
            shutil.copyfile(analytics.ROOT/'layouts/_partials'/name,self.root/'layouts/_partials'/name)
        (self.root/'layouts/_default/baseof.html').write_text('<!doctype html><html><body>{{ block "main" . }}{{ end }}{{ partial "extend_footer.html" . }}</body></html>',encoding='utf-8')
        for name in ('list','single'):
            (self.root/('layouts/_default/'+name+'.html')).write_text('{{ define "main" }}{{ .Title }}{{ end }}',encoding='utf-8')
        for name in ('_index.md','gallery/_index.md','gee-access/_index.md'):
            (self.root/'content'/name).write_text('---\ntitle: Fixture page\n---\n',encoding='utf-8')

    def build(self,enabled=True,token=None,base='https://chutj.github.io/',environment='production',extra=''):
        token='c'*32 if token is None else token
        (self.root/'hugo.toml').write_text('baseURL = '+json.dumps(base)+'\n[params]\n'+extra+'\n[params.webAnalytics]\nenabled = '+str(enabled).lower()+'\nbeaconToken = '+json.dumps(token)+'\n',encoding='utf-8')
        return subprocess.run([shutil.which('hugo'),'build','--environment',environment,'--destination','output','--noBuildLock'],cwd=self.root,capture_output=True,encoding='utf-8')

    def test_one_beacon_on_each_production_page(self):
        result=self.build();self.assertEqual(result.returncode,0,result.stderr)
        for path in ('index.html','gallery/index.html','gee-access/index.html'):
            parser=analytics.BeaconParser();parser.feed((self.root/'output'/path).read_text(encoding='utf-8'))
            self.assertEqual(parser.tokens,['c'*32])

    def test_disabled_development_localhost_and_private_previews_have_no_beacon(self):
        for kwargs in [dict(enabled=False),dict(environment='development'),dict(base='http://localhost:1330/'),
                       dict(extra='galleryLocalPreview = true'),dict(extra='galleryCandidatePreview = true')]:
            with self.subTest(kwargs=kwargs):
                result=self.build(**kwargs);self.assertEqual(result.returncode,0,result.stderr)
                for path in ('index.html','gallery/index.html','gee-access/index.html'):
                    self.assertNotIn('cloudflareinsights',(self.root/'output'/path).read_text(encoding='utf-8'))

    def test_bad_public_token_fails_build_without_exposing_its_value(self):
        result=self.build(token='invalid-private-value');self.assertNotEqual(result.returncode,0)
        self.assertNotIn('invalid-private-value',result.stdout+result.stderr)


if __name__=='__main__':
    unittest.main()
