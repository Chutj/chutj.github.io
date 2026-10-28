"""Archive aggregate Cloudflare page views; never store visitor identities or secrets.

Standard library only. Default commands are read-only. Live API/schema verification
requires the owner's configured Cloudflare site and read-only API credential.
"""
import argparse
import datetime as dt
import hashlib
from html.parser import HTMLParser
import json
import math
import os
from pathlib import Path
import re
import tempfile
import time
import tomllib
import urllib.error
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
TZ = dt.timezone(dt.timedelta(hours=8), 'Asia/Shanghai')
API = 'https://api.cloudflare.com/client/v4'
HEX = re.compile(r'^[a-fA-F0-9]{32}$')
COUNTRY_LIMIT = 1000


class AnalyticsError(ValueError):
    pass


def encoded(value):
    return (json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True)+'\n').encode('utf-8')


def load(path):
    return json.loads(path.read_text(encoding='utf-8-sig'))


def save_if_changed(path, value):
    content = encoded(value)
    if path.exists() and load(path) == value:
        return False
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(prefix='.analytics-', dir=path.parent)
    try:
        with os.fdopen(fd, 'wb') as stream:
            stream.write(content)
        os.replace(name, path)
    finally:
        if os.path.exists(name):
            os.unlink(name)
    return True


def date(value):
    try:
        result = dt.date.fromisoformat(value)
    except (ValueError, TypeError):
        raise AnalyticsError('Expected an ISO calendar date (YYYY-MM-DD).') from None
    if result.isoformat() != value:
        raise AnalyticsError('Expected a canonical ISO calendar date.')
    return result


def settings(root=ROOT):
    value = load(root/'analytics/settings.json')
    if (value.get('schema_version') != 1 or value.get('hostname') != 'chutj.github.io'
            or value.get('timezone') != 'Asia/Shanghai'):
        raise AnalyticsError('Unsupported analytics settings or site/timezone change.')
    if type(value.get('refresh_days')) is not int or not 1 <= value['refresh_days'] <= 7:
        raise AnalyticsError('refresh_days must be between 1 and 7.')
    pages = value.get('pages')
    if not isinstance(pages, dict) or not pages or len(pages) > 10:
        raise AnalyticsError('Configure 1–10 named public page paths.')
    for key, path in pages.items():
        if key in ('total','countries') or not re.fullmatch(r'[a-z][a-z0-9_]{0,24}', key) or not re.fullmatch(r'/[a-z0-9/_-]*', path):
            raise AnalyticsError('Invalid named public page path.')
    if len(set(pages.values())) != len(pages):
        raise AnalyticsError('Duplicate page paths would double-count a breakdown.')
    if value.get('start_date') is not None:
        date(value['start_date'])
    return value


def integer(value):
    if type(value) is not int or value < 0:
        raise AnalyticsError('Missing or invalid nonnegative page-view count.')
    return value


def interval(value):
    if value is None:
        return None
    if type(value) not in (int, float) or not math.isfinite(value) or value < 1:
        raise AnalyticsError('Invalid sampling interval.')
    return value


def validate_day(row, config):
    if set(row) != {'date', 'page_views', 'pages', 'countries', 'sample_interval', 'retrieved_at'}:
        raise AnalyticsError('Unexpected daily fields; raw visitor data must not be archived.')
    day = date(row['date'])
    if config['start_date'] is None or day < date(config['start_date']):
        raise AnalyticsError('Archived date precedes the configured collection start.')
    integer(row['page_views']); interval(row['sample_interval'])
    if not isinstance(row['pages'], dict) or set(row['pages']) != set(config['pages']):
        raise AnalyticsError('Page definitions changed; review the archive before migration.')
    for count in row['pages'].values():
        integer(count)
    if not isinstance(row['countries'], dict) or len(row['countries']) >= COUNTRY_LIMIT:
        raise AnalyticsError('Invalid/truncated country breakdown.')
    for country, count in row['countries'].items():
        if not isinstance(country, str) or not country or len(country) > 80 or not all(c.isalpha() or c in " .'-()" for c in country):
            raise AnalyticsError('Unexpected country label; raw location data was rejected.')
        integer(count)
    try:
        if dt.datetime.fromisoformat(row['retrieved_at']).tzinfo is None:
            raise ValueError()
    except (ValueError, TypeError):
        raise AnalyticsError('Daily observation timestamp must have a timezone.') from None


def history(root, config):
    value = load(root/'analytics/history.json')
    if set(value) != {'schema_version', 'source', 'metric', 'hostname', 'timezone', 'start_date', 'site_binding_sha256', 'days'}:
        raise AnalyticsError('Unexpected history fields; existing archive kept.')
    if (value['schema_version'] != 1 or value['source'] != 'cloudflare-web-analytics'
            or value['metric'] != 'page_views' or value['hostname'] != config['hostname']
            or value['timezone'] != config['timezone'] or not isinstance(value['days'], list)):
        raise AnalyticsError('History context does not match this site.')
    if value['days'] and (value['start_date'] != config['start_date'] or not re.fullmatch(r'[a-f0-9]{64}', value['site_binding_sha256'] or '')):
        raise AnalyticsError('Collection start/site binding changed; explicit migration required.')
    seen = set()
    for row in value['days']:
        validate_day(row, config)
        if row['date'] in seen:
            raise AnalyticsError('Duplicate archived calendar day.')
        seen.add(row['date'])
    return value


def plan(config, archive, today):
    if config['start_date'] is None:
        return dict(status='not_configured',dates=[],writes=False,network=False,
                    next='Add the Cloudflare site, install its public beacon, then set start_date.')
    start = date(config['start_date'])
    if start > today:
        raise AnalyticsError('Collection start cannot be in the future.')
    existing = {r['date'] for r in archive['days']}
    if any(date(d) >= today for d in existing):
        raise AnalyticsError('Archive includes unfinished/future days.')
    recent = today-dt.timedelta(days=config['refresh_days'])
    pending = []
    cursor = start
    while cursor < today:
        if cursor.isoformat() not in existing or cursor >= recent:
            pending.append(cursor.isoformat())
        cursor += dt.timedelta(days=1)
    if pending and date(pending[0]) < today-dt.timedelta(days=179):
        raise AnalyticsError('An unarchived day may have expired at Cloudflare; do not replace missing history with zero.')
    if len(pending) > 31:
        raise AnalyticsError('More than 31 days need recovery; review/backfill explicitly before automatic collection.')
    return dict(status='ready' if pending else 'collecting',dates=pending,writes=False,network=False)


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def request(url, token='', payload=None):
    """Never echo API payloads, credentials or upstream error messages into logs."""
    if not (url.startswith(API+'/') or url == 'https://chutj.github.io/'):
        raise AnalyticsError('Unapproved analytics endpoint.')
    headers = {'User-Agent':'Academic-Website-Analytics','Accept':'application/json' if token else 'text/html'}
    if token:
        if not url.startswith(API+'/'):
            raise AnalyticsError('Credentials cannot be sent to a website endpoint.')
        headers['Authorization'] = 'Bearer '+token
    data = None if payload is None else encoded(payload)
    if data is not None:
        headers['Content-Type'] = 'application/json'
    for attempt in range(3):
        try:
            req = urllib.request.Request(url, headers=headers, data=data)
            with urllib.request.build_opener(NoRedirect).open(req,timeout=30) as response:
                body = response.read(20_000_001)
                if len(body) > 20_000_000:
                    raise AnalyticsError('Analytics response exceeded the size limit.')
                return json.loads(body) if token else body.decode('utf-8')
        except urllib.error.HTTPError as exc:
            if exc.code not in (429,500,502,503,504) or attempt == 2:
                raise AnalyticsError('Analytics HTTP '+str(exc.code)+'; check read-only permissions, IDs or service status. History kept.') from None
        except (urllib.error.URLError, TimeoutError, OSError):
            if attempt == 2:
                raise AnalyticsError('Analytics network request failed. History kept; retry later.') from None
        except (ValueError, UnicodeError):
            raise AnalyticsError('Malformed analytics response. History kept.') from None
        time.sleep(attempt+1)


class BeaconParser(HTMLParser):
    def __init__(self):
        super().__init__(); self.tokens=[]

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == 'script' and attrs.get('src') == 'https://static.cloudflareinsights.com/beacon.min.js':
            try:
                self.tokens.append(json.loads(attrs['data-cf-beacon'])['token'])
            except (KeyError, ValueError, TypeError):
                self.tokens.append(None)


def credentials(root, config):
    account = os.environ.get('CF_ANALYTICS_ACCOUNT_ID','')
    site = os.environ.get('CF_ANALYTICS_SITE_TAG','')
    token = os.environ.get('CF_ANALYTICS_API_TOKEN','')
    if not HEX.fullmatch(account) or not HEX.fullmatch(site) or not token.strip():
        raise AnalyticsError('Configure CF_ANALYTICS_ACCOUNT_ID, CF_ANALYTICS_SITE_TAG and the private CF_ANALYTICS_API_TOKEN.')
    public = tomllib.loads((root/'hugo.toml').read_text(encoding='utf-8'))['params'].get('webAnalytics',{})
    beacon = public.get('beaconToken','')
    if public.get('enabled') is not True or not HEX.fullmatch(beacon):
        raise AnalyticsError('Enable the public Cloudflare beacon in hugo.toml before archiving.')
    return account, site, token, beacon


def verify_site(config, account, site, token, beacon):
    response = request(API+'/accounts/'+account+'/rum/site_info/'+site,token)
    if not isinstance(response,dict):
        raise AnalyticsError('Malformed Cloudflare site identity response.')
    info = response.get('result')
    if response.get('success') is not True or not isinstance(info,dict):
        raise AnalyticsError('Cloudflare site identity could not be verified.')
    hosts = {rule.get('host') for rule in info.get('rules',[]) if rule.get('inclusive') is True and not rule.get('is_paused')}
    if info.get('host'):
        hosts.add(info['host'])
    if info.get('site_tag') != site or info.get('site_token') != beacon or config['hostname'] not in hosts:
        raise AnalyticsError('Account/site/hostname/beacon mismatch; refusing misleading zero counts.')
    parser = BeaconParser(); parser.feed(request('https://chutj.github.io/'))
    if parser.tokens != [beacon]:
        raise AnalyticsError('The matching beacon is not yet live on Home. Publish/verify the site before archiving.')


def query(config, account, site, day):
    start = dt.datetime.combine(date(day),dt.time(),TZ).astimezone(dt.timezone.utc)
    end = start+dt.timedelta(days=1)
    filters = ', '.join(k+': '+json.dumps(v) for k,v in dict(siteTag=site,requestHost=config['hostname'],datetime_geq=start.strftime('%Y-%m-%dT%H:%M:%SZ'),datetime_lt=end.strftime('%Y-%m-%dT%H:%M:%SZ')).items())
    nodes = ['total: rumPageloadEventsAdaptiveGroups(limit: 2, filter: {'+filters+'}) { count avg { sampleInterval } }']
    for name,path in config['pages'].items():
        nodes.append(name+': rumPageloadEventsAdaptiveGroups(limit: 2, filter: {'+filters+', requestPath: '+json.dumps(path)+'}) { count }')
    nodes.append('countries: rumPageloadEventsAdaptiveGroups(limit: '+str(COUNTRY_LIMIT)+', filter: {'+filters+'}) { count dimensions { countryName } }')
    return 'query WebsiteDailyViews { viewer { accounts(filter: { accountTag: '+json.dumps(account)+' }) { '+' '.join(nodes)+' } } }'


def fetch_day(config, account, site, token, day, now):
    payload = request(API+'/graphql',token,{'query':query(config,account,site,day)})
    if not isinstance(payload,dict):
        raise AnalyticsError('Malformed Cloudflare GraphQL response; archive kept.')
    if payload.get('errors'):
        raise AnalyticsError('Cloudflare GraphQL rejected the query. Check token permissions, account/site IDs and current RUM schema; history kept.')
    try:
        accounts = payload['data']['viewer']['accounts']
        if not isinstance(accounts,list) or len(accounts) != 1 or not isinstance(accounts[0],dict):
            raise KeyError()
        account_data = accounts[0]
        def count(name):
            rows = account_data[name]
            if not isinstance(rows,list) or len(rows)>1:
                raise KeyError()
            return integer(rows[0]['count']) if rows else 0
        total = count('total')
        sample = interval(account_data['total'][0]['avg']['sampleInterval']) if account_data['total'] else None
        pages = {key:count(key) for key in config['pages']}
        countries = {}; rows = account_data['countries']
        if not isinstance(rows,list) or len(rows) >= COUNTRY_LIMIT:
            raise AnalyticsError('Country results may be truncated; archive kept.')
        for row in rows:
            name = row['dimensions']['countryName'] or 'Unknown'
            if name in countries:
                raise AnalyticsError('Duplicate country grouping; archive kept.')
            countries[name] = integer(row['count'])
        if total == 0 and (any(pages.values()) or any(countries.values())):
            raise AnalyticsError('Inconsistent zero total; archive kept.')
        result = dict(date=day,page_views=total,pages=pages,countries=countries,sample_interval=sample,retrieved_at=now.isoformat())
        validate_day(result,config)
        return result
    except (KeyError,TypeError,IndexError):
        raise AnalyticsError('Incomplete Cloudflare GraphQL response; archive kept.') from None


def collect(root=ROOT, dry_run=True, now=None):
    now = now or dt.datetime.now(TZ)
    config = settings(root); old = history(root,config)
    report = plan(config,old,now.astimezone(TZ).date())
    if not dry_run and report['status'] == 'not_configured':
        raise AnalyticsError('Analytics is not configured; no history written. Set the actual start_date after enabling the site.')
    if dry_run or not report['dates']:
        return report
    account,site,token,beacon = credentials(root,config)
    binding = hashlib.sha256((account+':'+site).encode()).hexdigest()
    if old['days'] and old['site_binding_sha256'] != binding:
        raise AnalyticsError('Analytics account/site changed. Existing cumulative history cannot be silently combined.')
    verify_site(config,account,site,token,beacon)
    rows = {row['date']:row for row in old['days']}
    for day in report['dates']:
        fresh = fetch_day(config,account,site,token,day,now)
        prior = rows.get(day)
        if prior and all(prior[k] == fresh[k] for k in fresh if k != 'retrieved_at'):
            fresh = prior
        rows[day] = fresh
    updated = dict(old,start_date=config['start_date'],site_binding_sha256=binding,days=[rows[key] for key in sorted(rows)])
    # All requests/validation complete before replacing the one persistent file.
    changed = save_if_changed(root/'analytics/history.json',updated)
    return dict(status='archived',days_checked=len(report['dates']),days_stored=len(rows),writes=changed,network=True)


def snapshot(root=ROOT, write=False, through=None, now=None):
    now = now or dt.datetime.now(TZ)
    config = settings(root); archive = history(root,config)
    if write and config['start_date'] is None:
        raise AnalyticsError('Analytics is not configured; no public snapshot written.')
    result = dict(schema_version=1,status='not_configured',metric='page_views',hostname=config['hostname'],timezone=config['timezone'],since=config['start_date'],through=None,total_page_views=None,pages={},countries={},updated_at=None)
    if config['start_date']:
        end = date(through) if through else now.astimezone(TZ).date().replace(day=1)-dt.timedelta(days=1)
        if end >= now.astimezone(TZ).date():
            raise AnalyticsError('Do not publish an unfinished day.')
        start = date(config['start_date'])
        if end < start:
            result['status'] = 'collecting'
        else:
            rows = {row['date']:row for row in archive['days']}; days = []; missing = []
            cursor = start
            while cursor <= end:
                (days if cursor.isoformat() in rows else missing).append(cursor.isoformat())
                cursor += dt.timedelta(days=1)
            if missing:
                raise AnalyticsError(str(len(missing))+' archived days are missing before the snapshot cutoff. Previous public snapshot kept.')
            result.update(status='available',through=end.isoformat(),total_page_views=sum(rows[d]['page_views'] for d in days),pages={key:sum(rows[d]['pages'][key] for d in days) for key in config['pages']},countries={},sampled_days=sum((rows[d]['sample_interval'] or 1)>1 for d in days),updated_at=now.isoformat())
            for day in days:
                for country,count in rows[day]['countries'].items():
                    result['countries'][country] = result['countries'].get(country,0)+count
    path = root/'data/site-analytics.json'
    old = load(path) if path.exists() else None
    if old and old.get('status') == 'available' and result['status'] != 'available':
        raise AnalyticsError('Refusing to erase a valid public cumulative snapshot.')
    if old and {k:v for k,v in old.items() if k!='updated_at'} == {k:v for k,v in result.items() if k!='updated_at'}:
        result = old
    if write:
        save_if_changed(path,result)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest='mode',required=True)
    p = commands.add_parser('archive'); p.add_argument('--write',action='store_true',help='Fetch verified live data and persist daily aggregates; otherwise show an offline plan.')
    p = commands.add_parser('snapshot'); p.add_argument('--write',action='store_true'); p.add_argument('--through',help='Explicit completed-day cutoff; default is the last day of the previous month.')
    args = parser.parse_args()
    try:
        result = collect(dry_run=not args.write) if args.mode=='archive' else snapshot(write=args.write,through=args.through)
        print(json.dumps(result,ensure_ascii=False,indent=2)); return 0
    except (AnalyticsError,OSError,ValueError,TypeError,KeyError):
        # Known diagnostics contain no upstream response bodies or credentials.
        import sys
        exc = sys.exception()
        message = str(exc) if isinstance(exc,AnalyticsError) else 'Invalid local analytics configuration/data. Existing files kept.'
        print('STOP: '+message,file=sys.stderr);return 1


if __name__ == '__main__':
    raise SystemExit(main())
