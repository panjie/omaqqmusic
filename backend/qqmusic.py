"""QQ Music protocol adapter. Standard library only; never evaluates server code."""
import base64
import email.utils
import http.cookies
import json
import os
from pathlib import Path
import re
import secrets
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid

MAX_BODY = 2 * 1024 * 1024
LOGIN_SIGNATURE_HOSTS = {'ssl.ptlogin2.qq.com', 'ptlogin2.qq.com', 'ssl.ptlogin2.graph.qq.com'}
HOSTS = {'ssl.ptlogin2.graph.qq.com', 'ssl.ptlogin2.qq.com', 'ptlogin2.qq.com', 'graph.qq.com',
         'u.y.qq.com', 'c.y.qq.com', 'c6.y.qq.com', 'y.qq.com'}
MUSIC_COOKIES = {'uin', 'qqmusic_uin', 'qqmusic_key', 'qm_keyst', 'qm_sid',
                 'musicid', 'musickey', 'login_type', 'wxuin', 'wxopenid', 'wxrefresh_token'}


class UserError(Exception):
    """A stable, translated UI error key. Never include response bodies or URLs."""


def bounded(value, limit=512):
    return str(value or '')[:limit]


def identifier(value):
    value = str(value)
    if not re.fullmatch(r'[A-Za-z0-9]{1,64}', value):
        raise UserError('invalid_request')
    return value


def hash33(value, seed=0):
    for char in value:
        seed = (seed * 33 + ord(char)) & 0x7fffffff
    return seed


def validate_url(url, hosts=HOSTS):
    parsed = urllib.parse.urlsplit(url)
    if (parsed.scheme != 'https' or parsed.hostname not in hosts
            or parsed.username or parsed.password or parsed.port not in (None, 443)):
        raise UserError('unsafe_response')
    return url


def media_url(url):
    p = urllib.parse.urlsplit(url)
    # Only the official QQ Music delivery domains; no files, playlists or local URLs.
    if (p.scheme not in ('http', 'https') or not p.hostname
            or not (p.hostname.endswith('.qq.com') or p.hostname.endswith('.qqmusic.qq.com'))
            or p.username or p.password or p.port not in (None, 80, 443)
            or not re.search(r'\.(mp3|m4a|flac|aac|ogg)$', p.path, re.I)):
        raise UserError('unsafe_response')
    return urllib.parse.urlunsplit(('https', p.netloc, p.path, p.query, ''))


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


class CookieStore:
    """Domain-scoped cookie jar for the login exchange.

    QQ's login servers delete a cookie by re-issuing the same name with an
    empty value and a past expiry for a *different* domain: a valid ``p_skey``
    for ``graph.qq.com`` is immediately followed by ``p_skey=`` deletions
    scoped to ``qq.com``. A flat name-keyed map would let those deletions
    erase credentials that are still valid, so entries are keyed by
    (domain, name), deletions only remove their own domain and cookies are
    sent only to domain-matching hosts, like a browser (RFC 6265).
    """

    def __init__(self):
        self.entries = {}

    def update(self, headers, host):
        """Apply Set-Cookie headers that arrived from *host*."""
        host = str(host or '').lower()
        for header in headers.get_all('Set-Cookie', []):
            parsed = http.cookies.SimpleCookie()
            try:
                parsed.load(header)
            except http.cookies.CookieError:
                continue
            for key, item in parsed.items():
                if not re.fullmatch(r'[\w-]{1,64}', key) or len(item.value) > 8192:
                    continue
                domain = (item['domain'] or host).lower().lstrip('.')
                if not item.value or self.expired(item):
                    self.entries.pop((domain, key), None)
                else:
                    self.entries[(domain, key)] = item.value

    def set(self, name, value, domain):
        self.entries[(str(domain).lower().lstrip('.'), name)] = value

    def get(self, name):
        for (_, key), value in self.entries.items():
            if key == name:
                return value
        return ''

    def named(self):
        """All stored (name, value) pairs across domains, in arrival order."""
        return [(key, value) for (_, key), value in self.entries.items()]

    def header(self, host):
        """Cookie header value for *host*, domain-matched like a browser."""
        host = str(host or '').lower()
        return '; '.join(f'{key}={value}' for (domain, key), value in self.entries.items()
                         if domain and (host == domain or host.endswith('.' + domain)))

    @staticmethod
    def expired(item):
        max_age = str(item['max-age'] or '').strip()
        if max_age:
            try:
                if int(max_age) <= 0:
                    return True
            except ValueError:
                pass
        raw = str(item['expires'] or '').strip()
        if not raw:
            return False
        try:
            when = email.utils.parsedate_to_datetime(raw)
            return when is not None and when.timestamp() <= time.time()
        except (TypeError, ValueError, OverflowError, OSError):
            return False


class Transport:
    def __init__(self):
        self.opener = urllib.request.build_opener(NoRedirect)

    def request(self, url, *, params=None, data=None, cookies=None, content_type=None, referer=None, origin=None):
        validate_url(url)
        host = urllib.parse.urlsplit(url).hostname or ''
        if params:
            url += '?' + urllib.parse.urlencode(params)
        headers = {'User-Agent': 'Mozilla/5.0', 'Referer': 'https://y.qq.com/',
                   'Accept': '*/*', 'Accept-Encoding': 'identity'}
        if referer:
            headers['Referer'] = referer
        if origin:
            headers['Origin'] = origin
        cookie_header = cookies.header(host) if isinstance(cookies, CookieStore) else (
            '; '.join(f'{k}={v}' for k, v in cookies.items()) if cookies else '')
        if cookie_header:
            headers['Cookie'] = cookie_header
        if content_type:
            headers['Content-Type'] = content_type
        request = urllib.request.Request(url, data=data, headers=headers)
        try:
            try:
                response = self.opener.open(request, timeout=10)
            except urllib.error.HTTPError as exc:
                if exc.code not in (301, 302, 303, 307, 308):
                    raise UserError('network_error') from None
                response = exc
            with response:
                chunks, size, deadline = [], 0, time.monotonic() + 15
                while True:
                    chunk = response.read(65536)
                    size += len(chunk)
                    if size > MAX_BODY or time.monotonic() > deadline:
                        raise UserError('response_limit')
                    if not chunk:
                        break
                    chunks.append(chunk)
                return b''.join(chunks), response.headers, response.status
        except (OSError, urllib.error.URLError, TimeoutError):
            raise UserError('network_error') from None


def decode(body):
    try:
        result = json.loads(body)
        if not isinstance(result, dict):
            raise ValueError()
        return result
    except (ValueError, UnicodeError):
        raise UserError('upstream_changed') from None


def song_list(items):
    if not isinstance(items, list):
        raise UserError('upstream_changed')
    result = []
    for raw in items[:200]:
        if not isinstance(raw, dict):
            continue
        raw = raw.get('songInfo', raw)
        try:
            mid = identifier(raw.get('mid') or raw.get('songmid') or '')
            media = identifier((raw.get('file') or {}).get('media_mid') or mid)
        except UserError:
            continue
        singers = raw.get('singer') or []
        result.append({'mid': mid, 'media': media,
                       'title': bounded(raw.get('title') or raw.get('name') or raw.get('songname')),
                       'artist': bounded(' / '.join(bounded(s.get('name'), 100) for s in singers[:10] if isinstance(s, dict))),
                       'album': bounded((raw.get('album') or {}).get('name') or raw.get('albumname'))})
    return result


class QQMusic:
    def __init__(self, state_dir=None, transport=None):
        self.directory = Path(state_dir or Path(os.environ.get('XDG_STATE_HOME', Path.home() / '.local/state')) / 'omarchy-qqmusic')
        self.directory.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.directory.chmod(0o700)
        self.session_path = self.directory / 'session.json'
        self.transport = transport or Transport()
        self.cookies = {}
        self.name = ''
        self.qr = None
        self.login_stage = ''
        self.login_diagnostic = {}
        self.load()

    @property
    def uin(self):
        value = self.cookies.get('musicid') or self.cookies.get('qqmusic_uin') or self.cookies.get('uin', '')
        value = value.lstrip('o').lstrip('0')
        return value if value.isdecimal() else ''

    def account(self):
        return {'loggedIn': bool(self.uin and (self.cookies.get('musickey') or self.cookies.get('qqmusic_key') or self.cookies.get('qm_keyst'))),
                'name': self.name, 'uin': self.uin}

    def load(self):
        try:
            if self.session_path.stat().st_size > 65536:
                return
            data = json.loads(self.session_path.read_text())
            self.cookies = {k: v for k, v in data['cookies'].items()
                            if k in MUSIC_COOKIES and isinstance(v, str) and len(v) <= 8192
                            and not re.search(r'[\r\n;]', v)}
            self.name = bounded(data.get('name'))
            self.session_path.chmod(0o600)
        except (FileNotFoundError, ValueError, KeyError, TypeError, AttributeError):
            self.cookies = {}

    def save(self):
        fd, path = tempfile.mkstemp(prefix='.session-', dir=self.directory)
        try:
            with os.fdopen(fd, 'w') as stream:
                json.dump({'cookies': self.cookies, 'name': self.name}, stream)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(path, self.session_path)
        finally:
            if os.path.exists(path):
                os.unlink(path)

    def logout(self):
        self.cookies, self.name, self.qr = {}, '', None
        self.session_path.unlink(missing_ok=True)
        return self.account()

    def start_login(self):
        self.login_stage = 'qr'
        self.login_diagnostic = {}
        cookies = CookieStore()
        body, headers, _ = self.transport.request('https://ssl.ptlogin2.qq.com/ptqrshow', params={
            'appid': '716027609', 'e': 2, 'l': 'M', 's': 3, 'd': 72, 'v': 4,
            't': secrets.randbelow(10**12) / 10**12, 'daid': '383', 'pt_3rd_aid': '100497308',
            'u1': 'https://graph.qq.com/oauth2.0/login_jump'})
        cookies.update(headers, 'ssl.ptlogin2.qq.com')
        if not cookies.get('qrsig') or not body.startswith(b'\x89PNG\r\n\x1a\n') or len(body) > 256000:
            raise UserError('upstream_changed')
        self.qr = {'cookies': cookies, 'expires': time.monotonic() + 120}
        return {'image': 'data:image/png;base64,' + base64.b64encode(body).decode(), 'status': 'waiting'}

    def poll_login(self):
        self.login_stage = 'poll'
        if not self.qr or time.monotonic() > self.qr['expires'] or not isinstance(self.qr.get('cookies'), CookieStore):
            self.qr = None
            return {'status': 'expired'}
        cookies = self.qr['cookies']
        body, headers, _ = self.transport.request('https://ssl.ptlogin2.qq.com/ptqrlogin', cookies=cookies, params={
            'u1': 'https://graph.qq.com/oauth2.0/login_jump', 'ptqrtoken': hash33(cookies.get('qrsig')),
            'ptredirect': 0, 'h': 1, 't': 1, 'g': 1, 'from_ui': 1, 'ptlang': 2052,
            'action': f'0-0-{int(time.time()*1000)}', 'js_ver': '23111510', 'js_type': 1,
            'pt_uistyle': 40, 'aid': '716027609', 'daid': 383, 'pt_3rd_aid': '100497308'})
        # Parse quoted arguments only; never eval the JavaScript callback.
        fields = re.findall(r"'((?:[^'\\]|\\.)*)'", body.decode('utf-8', errors='replace'))
        if len(fields) < 3 or not body.lstrip().startswith(b'ptuiCB('):
            raise UserError('upstream_changed')
        code = fields[0]
        if code in ('66', '67'):
            return {'status': 'scanned' if code == '67' else 'waiting'}
        if code == '65':
            self.qr = None
            return {'status': 'expired'}
        if code != '0':
            self.qr = None
            raise UserError('login_rejected')
        cookies.update(headers, 'ssl.ptlogin2.qq.com')
        self.login_stage = 'signature'
        check_url = validate_url(fields[2], LOGIN_SIGNATURE_HOSTS)
        _, headers, _ = self.transport.request(check_url, cookies=cookies)
        cookies.update(headers, urllib.parse.urlsplit(check_url).hostname)
        self.login_diagnostic['has_signature_cookie'] = bool(cookies.get('p_skey'))
        if not cookies.get('p_skey'):
            raise UserError('login_failed')
        gtk = hash33(cookies.get('p_skey'), 5381)
        form = {'response_type': 'code', 'client_id': '100497308',
                'redirect_uri': 'https://y.qq.com/portal/wx_redirect.html?login_type=1&surl=https://y.qq.com/',
                'scope': 'get_user_info,get_app_friends', 'state': 'state', 'switch': '',
                'from_ptlogin': 1, 'src': 1, 'update_auth': 1, 'openapi': '1010_1030',
                'g_tk': gtk, 'auth_time': time.ctime(), 'ui': str(uuid.uuid4()).upper()}
        self.login_stage = 'authorize'
        _, headers, status = self.transport.request('https://graph.qq.com/oauth2.0/authorize',
            data=urllib.parse.urlencode(form).encode(), cookies=cookies,
            content_type='application/x-www-form-urlencoded',
            referer='https://graph.qq.com/oauth2.0/login_jump', origin='https://graph.qq.com')
        self.login_diagnostic['authorize_http_status'] = status
        self.login_diagnostic['has_authorize_location'] = bool(headers.get('Location'))
        cookies.update(headers, 'graph.qq.com')
        location = headers.get('Location', '')
        if status not in (301, 302, 303):
            raise UserError('login_failed')
        validate_url(location, {'y.qq.com'})
        code = urllib.parse.parse_qs(urllib.parse.urlsplit(location).query).get('code', [''])[0]
        if not code:
            raise UserError('login_failed')
        payload = {'comm': {'g_tk': gtk, 'platform': 'yqq.json', 'ct': 24, 'cv': 4747474, 'tmeLoginType': 2},
                   'req': {'module': 'QQConnectLogin.LoginServer', 'method': 'QQLogin', 'param': {'code': code}}}
        self.login_stage = 'music'
        body, headers, _ = self.transport.request('https://u.y.qq.com/cgi-bin/musicu.fcg',
            data=json.dumps(payload).encode(), cookies=cookies, content_type='application/json')
        cookies.update(headers, 'u.y.qq.com')
        result = decode(body)
        module = result.get('req', {})
        self.login_diagnostic['response_code'] = result.get('code') if isinstance(result.get('code'), int) else None
        self.login_diagnostic['module_code'] = module.get('code') if isinstance(module.get('code'), int) else None
        if result.get('code', 0) != 0 or module.get('code', -1) != 0:
            raise UserError('login_failed')
        data = module.get('data') or {}
        # QQLogin can return credentials in JSON rather than Set-Cookie.
        # Only accept a complete pair from that response; do not mix accounts.
        music_id = next((str(data[k]) for k in ('musicid', 'str_musicid', 'musicId', 'uin')
                         if isinstance(data.get(k), (str, int)) and str(data[k]).isdigit()
                         and 0 < len(str(data[k])) <= 32 and int(data[k]) > 0), '')
        music_key = next((data[k] for k in ('musickey', 'musicKey', 'qqmusic_key', 'qm_keyst')
                          if isinstance(data.get(k), str) and 0 < len(data[k]) <= 8192
                          and not re.search(r'[\r\n;]', data[k])), '')
        self.login_diagnostic['body_has_music_id'] = bool(music_id)
        self.login_diagnostic['body_has_music_key'] = bool(music_key)
        saved = self.cookies
        self.cookies = {name: value for name, value in cookies.named() if name in MUSIC_COOKIES}
        if music_id and music_key:
            # Only apply the JSON pair on top of the jar cookies when complete.
            self.cookies.update(musicid=music_id, qqmusic_uin=music_id, uin=music_id,
                                musickey=music_key, qqmusic_key=music_key, qm_keyst=music_key)
        self.login_diagnostic['session_has_music_id'] = bool(self.uin)
        self.login_diagnostic['session_has_music_key'] = bool(self.cookies.get('musickey') or self.cookies.get('qqmusic_key') or self.cookies.get('qm_keyst'))
        if not self.account()['loggedIn']:
            self.cookies = saved
            raise UserError('login_failed')
        self.name = bounded(fields[5] if len(fields) > 5 else self.uin)
        self.login_stage = 'save'
        self.save()
        self.qr = None
        return {'status': 'success', 'account': self.account()}

    def record_login_failure(self, error):
        # Fixed keys, numeric codes and booleans only. No cookies, URLs or bodies.
        payload = {**self.login_diagnostic, 'stage': self.login_stage,
                   'error': error, 'time': int(time.time())}
        fd, path = tempfile.mkstemp(prefix='.login-diagnostic-', dir=self.directory)
        try:
            with os.fdopen(fd, 'w') as stream:
                json.dump(payload, stream)
            os.replace(path, self.directory / 'login-diagnostic.json')
        finally:
            if os.path.exists(path):
                os.unlink(path)

    def get_json(self, url, params):
        body, _, _ = self.transport.request(url, params={'format': 'json', 'outCharset': 'utf-8', **params}, cookies=self.cookies)
        payload = decode(body)
        if payload.get('code', 0) != 0:
            raise UserError('upstream_rejected')
        return payload

    def search(self, query, page=1):
        query = str(query).strip()
        if not query or len(query) > 100 or not 1 <= page <= 100:
            raise UserError('invalid_request')
        payload = self.get_json('https://c.y.qq.com/soso/fcgi-bin/client_search_cp', {
            'w': query, 'p': page, 'n': 30, 'ct': 24, 'qqmusic_ver': 1298, 'remoteplace': 'txt.yqq.song',
            't': 0, 'aggr': 1, 'cr': 1, 'lossless': 0, 'flag_qc': 0, 'platform': 'yqq.json'})
        song = payload.get('data', {}).get('song', {})
        return {'songs': song_list(song.get('list')), 'page': page,
                'more': int(song.get('totalnum', 0)) > page * 30}

    def profile(self):
        if not self.account()['loggedIn']:
            raise UserError('login_required')
        payload = self.get_json('https://c6.y.qq.com/rsc/fcgi-bin/fcg_get_profile_homepage.fcg', {
            'cv': 4747474, 'ct': 24, 'inCharset': 'utf-8', 'notice': 0, 'platform': 'yqq.json',
            'needNewCode': 0, 'uin': self.uin, 'g_tk_new_20200303': 0, 'g_tk': 0,
            'cid': 205360838, 'userid': self.uin, 'reqfrom': 1, 'reqtype': 0, 'hostUin': 0, 'loginUin': self.uin})
        data = payload.get('data', {})
        if not isinstance(data, dict):
            raise UserError('upstream_changed')
        return data

    @staticmethod
    def favorite(data):
        """The profile's favorites playlist entry as (id, title), or ('', '')."""
        # The profile tab row ("mymusic") leads with the favorites diss
        # ("我喜欢"); the created-playlist list never includes it.
        tabs = data.get('mymusic')
        for item in tabs if isinstance(tabs, list) else ():
            if not isinstance(item, dict):
                continue
            key = str(item.get('id') or '')
            if key.isdecimal() and int(key) > 0:
                return key, bounded(item.get('title') or item.get('name')) or '我喜欢'
        return '', ''

    def playlists(self):
        data = self.profile()
        created = (data.get('mydiss') or {}).get('list')
        if not isinstance(data.get('mymusic'), list) and not isinstance(created, list):
            raise UserError('upstream_changed')
        key, title = self.favorite(data)
        result = [{'id': key, 'title': title}] if key else []
        for item in (created if isinstance(created, list) else [])[:100]:
            if not isinstance(item, dict):
                continue
            item_key = str(item.get('dissid') or item.get('tid') or '')
            if item_key.isdecimal() and int(item_key) > 0 and item_key != key:
                result.append({'id': item_key, 'title': bounded(item.get('title') or item.get('dissname'))})
        return result

    def favorites(self):
        key, _ = self.favorite(self.profile())
        if not key:
            raise UserError('upstream_changed')
        return self.playlist(key)

    def playlist(self, key):
        key = identifier(key)
        if not key.isdecimal():
            raise UserError('invalid_request')
        payload = self.get_json('https://c.y.qq.com/qzone/fcg-bin/fcg_ucc_getcdinfo_byids_cp.fcg', {
            'disstid': key, 'type': 1, 'json': 1, 'utf8': 1, 'onlysong': 0, 'new_format': 1})
        lists = payload.get('cdlist')
        if not isinstance(lists, list) or not lists:
            raise UserError('upstream_changed')
        return {'songs': song_list(lists[0].get('songlist')), 'page': 1, 'more': False}

    def play_url(self, song):
        mid, media = identifier(song['mid']), identifier(song.get('media') or song['mid'])
        guid = str(secrets.randbelow(10**10))
        param = {'filename': [f'M500{mid}{media}.mp3'], 'guid': guid, 'songmid': [mid],
                 'songtype': [0], 'uin': self.uin or '0', 'loginflag': 1, 'platform': '20'}
        auth = self.cookies.get('musickey') or self.cookies.get('qqmusic_key') or self.cookies.get('qm_keyst')
        if auth:
            param['authst'] = auth
        payload = {'req_0': {'module': 'vkey.GetVkeyServer', 'method': 'CgiGetVkey', 'param': param},
                   'loginUin': self.uin or '0', 'comm': {'uin': self.uin or '0', 'format': 'json', 'ct': 24, 'cv': 0}}
        result = self.get_json('https://u.y.qq.com/cgi-bin/musicu.fcg', {'data': json.dumps(payload)})
        data = result.get('req_0', {}).get('data', {})
        entries = data.get('midurlinfo') or []
        info = next((i for i in entries if i.get('songmid') == mid), {})
        path = info.get('purl')
        if not path:
            raise UserError('unavailable')
        for domain in data.get('sip', []):
            try:
                return media_url(urllib.parse.urljoin(domain, path))
            except (UserError, ValueError):
                pass
        raise UserError('unsafe_response')
