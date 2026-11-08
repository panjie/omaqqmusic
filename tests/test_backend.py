import io
import json
import os
from email.message import Message
from pathlib import Path
import stat
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'backend'))
from qqmusic import QQMusic, UserError, hash33, song_list, media_url, validate_url, Transport, CookieStore
from main import App


class FakeTransport:
    def __init__(self, replies):
        self.replies = iter(replies)
        self.calls = []

    def request(self, url, **kwargs):
        self.calls.append((url, kwargs))
        return next(self.replies)


def seeded_qr(**cookies):
    store = CookieStore()
    for name, value in cookies.items():
        store.set(name, value, 'ptlogin2.qq.com')
    return {'expires': time.monotonic() + 120, 'cookies': store}


def reply(body, cookies=(), location='', status=200):
    headers = Message()
    for cookie in cookies:
        headers.add_header('Set-Cookie', cookie)
    if location:
        headers['Location'] = location
    return body if isinstance(body, bytes) else json.dumps(body).encode(), headers, status


class ProtocolTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)

    def api(self, replies=()):
        return QQMusic(self.tmp.name, FakeTransport(replies))

    def test_qr_complete_exchange_and_private_persistence(self):
        api = self.api([
            reply(b'\x89PNG\r\n\x1a\nfixture', ['qrsig=qr_secret; Path=/']),
            reply(b"ptuiCB('0','0','https://ssl.ptlogin2.graph.qq.com/check_sig?a=1','0','ok','Alice');", ['uin=o012345; Path=/']),
            reply(b'', ['p_skey=oauth_secret; Path=/'], status=302),
            reply(b'', location='https://y.qq.com/portal/wx_redirect.html?code=auth_code', status=302),
            reply({'req': {'code': 0}}, ['qqmusic_key=music_secret; Path=/', 'qqmusic_uin=12345; Path=/']),
        ])
        qr = api.start_login()
        self.assertTrue(qr['image'].startswith('data:image/png;base64,'))
        result = api.poll_login()
        self.assertEqual(result['status'], 'success')
        self.assertTrue(result['account']['loggedIn'])
        self.assertEqual(result['account']['uin'], '12345')
        self.assertNotIn('secret', json.dumps(result))
        stored = api.session_path.read_text()
        self.assertIn('music_secret', stored)
        self.assertNotIn('oauth_secret', stored)
        self.assertEqual(stat.S_IMODE(api.session_path.stat().st_mode), 0o600)
        self.assertEqual(stat.S_IMODE(api.directory.stat().st_mode), 0o700)
        self.assertTrue(self.api().account()['loggedIn'])
        api.logout()
        self.assertFalse(api.session_path.exists())
        self.assertFalse(api.account()['loggedIn'])

    def test_login_accepts_body_only_music_credentials(self):
        api = self.api([
            reply(b"ptuiCB('0','0','https://ssl.ptlogin2.graph.qq.com/check_sig','0','ok','Alice');", ['uin=o999']),
            reply(b'', ['p_skey=oauth_secret'], status=302),
            reply(b'', location='https://y.qq.com/?code=auth_code', status=302),
            reply({'code': 0, 'req': {'code': 0, 'data': {'str_musicid': '12345', 'musickey': 'music_secret'}}}),
        ])
        api.qr = seeded_qr(qrsig='qr_secret')
        result = api.poll_login()
        self.assertTrue(result['account']['loggedIn'])
        self.assertEqual(result['account']['uin'], '12345')
        self.assertNotIn('secret', json.dumps(result))
        restored = self.api()
        self.assertTrue(restored.account()['loggedIn'])
        self.assertEqual(restored.cookies['qqmusic_key'], 'music_secret')
        request = json.loads(api.transport.calls[-1][1]['data'])
        self.assertEqual(request['comm']['tmeLoginType'], 2)

    def test_check_sig_deletion_for_other_domain_keeps_signature(self):
        # Captured live: check_sig returns a valid p_skey for graph.qq.com and
        # then same-name deletions scoped to qq.com. A flat name-keyed map let
        # those deletions erase the credential and login always failed here.
        api = self.api([
            reply(b"ptuiCB('0','0','https://ssl.ptlogin2.graph.qq.com/check_sig?a=1','0','ok','Alice');"),
            reply(b'', [
                'p_skey=graph_secret; Path=/; Domain=graph.qq.com; Secure;',
                'p_skey_forbid=; Expires=Thu, 01 Jan 1970 00:00:00 GMT; Path=/; Domain=graph.qq.com;',
                'p_skey=; Expires=Thu, 01 Jan 1970 00:00:00 GMT; Path=/; Domain=qq.com;',
                'pt4_token=; Expires=Thu, 01 Jan 1970 00:00:00 GMT; Path=/; Domain=qq.com;',
            ], status=302),
            reply(b'', location='https://y.qq.com/portal/wx_redirect.html?login_type=1&surl=https%3A%2F%2Fy.qq.com%2F&code=auth_code', status=302),
            reply({'code': 0, 'req': {'code': 0, 'data': {'str_musicid': '12345', 'musickey': 'music_secret'}}}),
        ])
        api.qr = seeded_qr(qrsig='qr_secret')
        result = api.poll_login()
        self.assertEqual(result['status'], 'success')
        self.assertTrue(result['account']['loggedIn'])
        authorize_jar = api.transport.calls[2][1]['cookies']
        self.assertIn('p_skey=graph_secret', authorize_jar.header('graph.qq.com'))
        self.assertNotIn('p_skey', authorize_jar.header('ssl.ptlogin2.qq.com'))
        self.assertNotIn('graph_secret', api.session_path.read_text())

    def test_musickey_cookie_session_and_safe_diagnostics(self):
        api = self.api()
        api.cookies = {'musicid': '12345', 'musickey': 'secret'}
        self.assertTrue(api.account()['loggedIn'])
        api.login_stage = 'music'
        api.login_diagnostic = {'module_code': 10006, 'body_has_music_key': False}
        api.record_login_failure('login_failed')
        path = api.directory / 'login-diagnostic.json'
        self.assertNotIn('secret', path.read_text())
        self.assertEqual(json.loads(path.read_text())['stage'], 'music')
        self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o600)

    def test_qr_poll_states_and_expiry(self):
        api = self.api([reply(b"ptuiCB('66','0','','0','','');"),
                        reply(b"ptuiCB('67','0','','0','','');"),
                        reply(b"ptuiCB('65','0','','0','','');")])
        api.qr = seeded_qr(qrsig='x')
        self.assertEqual(api.poll_login()['status'], 'waiting')
        self.assertEqual(api.poll_login()['status'], 'scanned')
        self.assertEqual(api.poll_login()['status'], 'expired')
        self.assertIsNone(api.qr)
        self.assertEqual(api.poll_login()['status'], 'expired')

    def test_qr_rejects_untrusted_redirect_before_sending_cookies(self):
        api = self.api([reply(b"ptuiCB('0','0','https://evil.test/','0','','');")])
        api.qr = seeded_qr(qrsig='secret')
        with self.assertRaisesRegex(UserError, 'unsafe_response'):
            api.poll_login()
        self.assertEqual(len(api.transport.calls), 1)

    def test_login_does_not_accept_success_without_music_credentials(self):
        api = self.api([
            reply(b"ptuiCB('0','0','https://ssl.ptlogin2.qq.com/check_sig','0','','');"),
            reply(b'', ['p_skey=x'], status=302),
            reply(b'', location='https://y.qq.com/?code=x', status=302),
            reply({'req': {'code': 0}}),
        ])
        api.qr = seeded_qr(qrsig='x')
        with self.assertRaisesRegex(UserError, 'login_failed'):
            api.poll_login()
        self.assertFalse(api.session_path.exists())

    def test_search_metadata_is_bounded_plain_data(self):
        title = '<img src="https://evil.test/pixel">'
        api = self.api([reply({'code': 0, 'data': {'song': {'totalnum': 80, 'list': [
            {'songmid': 'ABC123', 'songname': title, 'singer': [{'name': 'Artist'}]},
            {'songmid': ';rm -rf /'},
        ]}}})])
        result = api.search('测试', 2)
        self.assertEqual(result['songs'][0]['title'], title)
        self.assertEqual(len(result['songs']), 1)
        self.assertTrue(result['more'])
        self.assertEqual(api.transport.calls[0][1]['params']['p'], 2)
        self.assertEqual(len(song_list([{'mid': 'a', 'title': 'x'*1000}])[0]['title']), 512)

    def test_album_cover_supports_search_and_playlist_metadata(self):
        for metadata in ({'album': {'mid': 'Album123', 'name': 'Album'}},
                         {'albummid': 'Album123', 'albumname': 'Album'},
                         {'songInfo': {'mid': 'song', 'album': {'mid': 'Album123', 'name': 'Album'}}}):
            with self.subTest(metadata=metadata):
                song = song_list([{'mid': 'song', **metadata}])[0]
                self.assertEqual(song['album'], 'Album')
                self.assertEqual(song['cover'],
                                 'https://y.gtimg.cn/music/photo_new/T002R300x300M000Album123.jpg')

    def test_invalid_album_cover_keeps_song_without_remote_image(self):
        for mid in ('', '../private', 'https://evil.test/image', '<img>', 'a' * 65):
            with self.subTest(mid=mid):
                song = song_list([{'mid': 'song', 'album': {'mid': mid}}])[0]
                self.assertEqual(song['mid'], 'song')
                self.assertEqual(song['cover'], '')
        for album in (None, 'invalid', []):
            self.assertEqual(song_list([{'mid': 'song', 'album': album}])[0]['cover'], '')

    def test_play_url_respects_server_entitlement_and_uses_media_mid(self):
        api = self.api([reply({'code': 0, 'req_0': {'data': {'sip': ['http://dl.stream.qqmusic.qq.com/'],
                       'midurlinfo': [{'songmid': 'abc', 'purl': 'M500abcfile.mp3?vkey=x'}]}}})])
        url = api.play_url({'mid': 'abc', 'media': 'file'})
        self.assertTrue(url.startswith('https://dl.stream.qqmusic.qq.com/'))
        payload = json.loads(api.transport.calls[0][1]['params']['data'])
        self.assertEqual(payload['req_0']['param']['filename'], ['M500abcfile.mp3'])
        api = self.api([reply({'req_0': {'data': {'sip': [], 'midurlinfo': []}}})])
        with self.assertRaisesRegex(UserError, 'unavailable'):
            api.play_url({'mid': 'abc'})

    def test_urls_do_not_allow_local_files_or_spoofed_domains(self):
        for url in ('file:///etc/passwd', 'https://qq.com.evil.test/a.mp3', 'https://127.0.0.1/a.mp3',
                    'https://user:pass@c.y.qq.com/a.mp3', 'https://c.y.qq.com/a.m3u'):
            with self.subTest(url=url), self.assertRaises(UserError):
                media_url(url)
        with self.assertRaises(UserError):
            validate_url('https://graph.qq.com.evil.test/')
        self.assertEqual(validate_url('https://ssl.ptlogin2.graph.qq.com/check_sig'),
                         'https://ssl.ptlogin2.graph.qq.com/check_sig')
        with self.assertRaises(UserError):
            validate_url('https://ssl.ptlogin2.graph.qq.com.evil.test/check_sig')

    def test_hash33_known_vector(self):
        self.assertEqual(hash33('abc'), 108966)
        self.assertEqual(hash33('', 5381), 5381)

    def test_playlists_and_details(self):
        api = self.api([reply({'data': {'mydiss': {'list': [{'tid': 123, 'dissname': 'Favorites'}]}}}),
                        reply({'cdlist': [{'songlist': [{'mid': 'ABC', 'name': 'Track'}]}]})])
        api.cookies = {'uin': '12345', 'qqmusic_key': 'secret'}
        self.assertEqual(api.playlists(), [{'id': '123', 'title': 'Favorites'}])
        self.assertEqual(api.playlist('123')['songs'][0]['mid'], 'ABC')
        api = self.api([reply({'data': {}})])
        api.cookies = {'uin': '12345', 'qqmusic_key': 'secret'}
        with self.assertRaisesRegex(UserError, 'upstream_changed'):
            api.playlists()

    def test_playlists_lead_with_favorites_from_profile_tabs(self):
        # Captured live: data.mymusic leads with the favorites diss ("我喜欢")
        # and data.mydiss.list holds only created playlists; a duplicate of
        # the favorites id in the created list must not yield two entries.
        api = self.api([reply({'data': {
            'mymusic': [{'id': '3334232827', 'title': '我喜欢', 'num0': 430},
                         {'id': '0', 'title': '那年今日'}],
            'mydiss': {'list': [{'dissid': 8753787379, 'title': '2022年度歌单', 'dirid': 4},
                                {'dissid': 3334232827, 'title': 'duplicate'}]}}})])
        api.cookies = {'uin': '875814989', 'qqmusic_key': 'secret'}
        self.assertEqual(api.playlists(), [
            {'id': '3334232827', 'title': '我喜欢'},
            {'id': '8753787379', 'title': '2022年度歌单'}])
        api = self.api([reply({'data': {'mymusic': [{'id': 0, 'title': '那年今日'}],
                                        'mydiss': {'list': []}}})])
        api.cookies = {'uin': '875814989', 'qqmusic_key': 'secret'}
        self.assertEqual(api.playlists(), [])

    def test_favorites_resolves_profile_tab_then_playlist(self):
        api = self.api([reply({'data': {
            'mymusic': [{'id': '333', 'title': '我喜欢', 'num0': 9},
                         {'id': '0', 'title': '那年今日'}],
            'mydiss': {'list': [{'dissid': 7, 'title': '其他'}]}}}),
            reply({'cdlist': [{'songlist': [{'mid': 'ABC', 'title': 'Loved'}]}]})])
        api.cookies = {'uin': '12345', 'qqmusic_key': 'secret'}
        result = api.favorites()
        self.assertEqual(result['songs'][0]['mid'], 'ABC')
        self.assertTrue(api.transport.calls[0][0].endswith('fcg_get_profile_homepage.fcg'))
        self.assertEqual(api.transport.calls[1][1]['params']['disstid'], '333')

    def test_favorites_requires_login_and_profile_tab(self):
        api = self.api()
        with self.assertRaisesRegex(UserError, 'login_required'):
            api.favorites()
        api = self.api([reply({'data': {'mymusic': [{'id': 0, 'title': '那年今日'}],
                                        'mydiss': {'list': []}}})])
        api.cookies = {'uin': '12345', 'qqmusic_key': 'secret'}
        with self.assertRaisesRegex(UserError, 'upstream_changed'):
            api.favorites()

    def test_transport_has_size_limit_and_no_automatic_redirect(self):
        class Response(io.BytesIO):
            headers = Message()
            status = 200
        transport = Transport()
        with patch.object(transport.opener, 'open', return_value=Response(b'x' * (2*1024*1024+1))):
            with self.assertRaisesRegex(UserError, 'response_limit'):
                transport.request('https://y.qq.com/')
        with patch.object(transport.opener, 'open', side_effect=OSError('secret URL')):
            with self.assertRaisesRegex(UserError, '^network_error$'):
                transport.request('https://y.qq.com/')

    def test_cookie_store_scopes_deletions_and_matches_domains(self):
        store = CookieStore()
        headers = Message()
        headers.add_header('Set-Cookie', 'p_skey=graph_secret; Path=/; Domain=graph.qq.com; Secure;')
        headers.add_header('Set-Cookie', 'p_skey=; Expires=Thu, 01 Jan 1970 00:00:00 GMT; Path=/; Domain=qq.com;')
        headers.add_header('Set-Cookie', 'uin=o12345; Path=/; Domain=ptlogin2.qq.com; Secure;')
        store.update(headers, 'ssl.ptlogin2.graph.qq.com')
        self.assertEqual(store.get('p_skey'), 'graph_secret')
        self.assertIn('p_skey=graph_secret', store.header('graph.qq.com'))
        self.assertIn('uin=o12345', store.header('ssl.ptlogin2.qq.com'))
        self.assertNotIn('p_skey', store.header('ssl.ptlogin2.qq.com'))
        headers = Message()
        headers.add_header('Set-Cookie', 'uin=; Expires=Thu, 01 Jan 1970 00:00:00 GMT; Path=/; Domain=ptlogin2.qq.com;')
        store.update(headers, 'ssl.ptlogin2.qq.com')
        self.assertNotIn('uin=', store.header('ssl.ptlogin2.qq.com'))
        headers = Message()
        headers.add_header('Set-Cookie', 'rk=server1; Path=/;')
        store.update(headers, 'ssl.ptlogin2.qq.com')
        self.assertIn('rk=server1', store.header('ssl.ptlogin2.qq.com'))
        self.assertNotIn('rk', store.header('ptlogin2.qq.com'))
        headers = Message()
        headers.add_header('Set-Cookie', 'rk=; Max-Age=0; Path=/;')
        store.update(headers, 'ssl.ptlogin2.qq.com')
        self.assertNotIn('rk=', store.header('ssl.ptlogin2.qq.com'))

    def test_transport_sends_only_domain_matched_jar_cookies(self):
        transport = Transport()
        jar = CookieStore()
        jar.set('qrsig', 'qr_secret', 'ptlogin2.qq.com')
        jar.set('p_skey', 'oauth_secret', 'graph.qq.com')
        captured = {}

        class Response(io.BytesIO):
            headers = Message()
            status = 200

        def capture(request, timeout=None):
            captured['cookie'] = request.headers.get('Cookie')
            return Response(b'')

        with patch.object(transport.opener, 'open', side_effect=capture):
            transport.request('https://graph.qq.com/oauth2.0/authorize', cookies=jar)
        self.assertEqual(captured['cookie'], 'p_skey=oauth_secret')


class FakePlayer:
    def __init__(self): self.calls = []
    def play(self, url): self.calls.append(('play', url))
    def command(self, value): self.calls.append(('command', value))
    def close(self): self.calls.append(('close',))


class PlaybackTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.api = QQMusic(self.tmp.name)
        self.api.play_url = lambda song: 'https://dl.stream.qqmusic.qq.com/' + song['mid'] + '.mp3'
        self.out = []
        self.player = FakePlayer()
        self.app = App(self.api, self.player, self.out.append)
        self.app.results = [{'mid': 'one'}, {'mid': 'two'}]

    def test_queue_survives_new_search_and_advances_only_at_eof(self):
        self.app.dispatch('play', {'index': 0})
        self.app.results = [{'mid': 'different'}]
        self.app.on_player({'event': 'end-file', 'reason': 'stop'})
        self.assertEqual(self.app.index, 0)
        self.app.on_player({'event': 'end-file', 'reason': 'eof'})
        self.assertEqual(self.app.index, 1)
        self.assertIn('two.mp3', self.player.calls[-1][1])
        self.app.on_player({'event': 'file-loaded'})
        self.assertTrue(self.app.status()['playing'])
        self.app.on_player({'event': 'end-file', 'reason': 'eof'})
        self.assertFalse(self.app.status()['playing'])
        self.assertFalse(self.app.status()['canNext'])

    def test_failed_resolution_keeps_current_track(self):
        self.app.dispatch('play', {'index': 0})
        self.api.play_url = lambda _: (_ for _ in ()).throw(UserError('unavailable'))
        self.app.handle({'id': 7, 'command': 'next'})
        self.assertEqual(self.app.index, 0)
        self.assertEqual(self.out[-1], {'id': 7, 'ok': False, 'error': 'unavailable'})

    def test_shuffle_visits_each_song_once_and_previous_retraces_order(self):
        self.app.results = [{'mid': str(i)} for i in range(5)]
        self.app.dispatch('play', {'index': 2})
        calls = list(self.player.calls)
        with patch('main.random.shuffle', side_effect=lambda values: values.reverse()):
            self.app.dispatch('playback_mode', {'mode': 'shuffle'})
        self.assertEqual(self.player.calls, calls)  # Switching does not restart playback.
        self.assertEqual(self.app.status()['playbackMode'], 'shuffle')
        self.assertFalse(self.app.status()['canPrevious'])
        self.app.dispatch('next', {})
        self.assertEqual(self.app.index, 4)
        self.app.dispatch('previous', {})
        self.assertEqual(self.app.index, 2)
        self.app.results = [{'mid': 'new-search'}]
        visited = [self.app.index]
        while self.app.status()['canNext']:
            self.app.on_player({'event': 'end-file', 'reason': 'eof'})
            visited.append(self.app.index)
        self.assertEqual(visited, [2, 4, 3, 1, 0])
        count = len(self.player.calls)
        self.app.on_player({'event': 'end-file', 'reason': 'eof'})
        self.assertEqual(len(self.player.calls), count)
        self.assertFalse(self.app.status()['playing'])

    def test_switch_to_sequential_restores_list_order(self):
        self.app.results = [{'mid': str(i)} for i in range(4)]
        self.app.dispatch('playback_mode', {'mode': 'shuffle'})
        self.app.dispatch('play', {'index': 1})
        self.app.dispatch('playback_mode', {'mode': 'sequential'})
        self.assertEqual(self.app.index, 1)
        self.assertTrue(self.app.status()['canPrevious'])
        self.app.dispatch('next', {})
        self.assertEqual(self.app.index, 2)
        self.app.dispatch('previous', {})
        self.assertEqual(self.app.index, 1)

    def test_shuffle_failure_keeps_next_song_and_new_queue_resets_order(self):
        self.app.dispatch('playback_mode', {'mode': 'shuffle'})
        self.app.dispatch('play', {'index': 0})
        order = list(self.app.order)
        with patch.object(self.api, 'play_url', side_effect=UserError('unavailable')):
            with self.assertRaises(UserError):
                self.app.dispatch('next', {})
        self.assertEqual(self.app.index, 0)
        self.assertEqual(self.app.order, order)
        self.app.dispatch('next', {})
        self.assertEqual(self.app.index, 1)
        self.app.results = [{'mid': 'single'}]
        self.app.dispatch('play', {'index': 0})
        self.assertFalse(self.app.status()['canNext'])
        self.assertFalse(self.app.status()['canPrevious'])
        with self.assertRaises(UserError):
            self.app.dispatch('playback_mode', {'mode': 'invalid'})
        self.assertEqual(self.app.status()['playbackMode'], 'shuffle')
        self.app.dispatch('logout', {})
        self.assertEqual(self.app.order, [])
        self.assertFalse(self.app.status()['canNext'])

    def test_favorites_dispatch_populates_results(self):
        self.api.favorites = lambda: {'songs': [{'mid': 'fav'}], 'page': 1, 'more': False}
        self.app.dispatch('favorites', {})
        self.assertEqual(self.app.results, [{'mid': 'fav'}])

    def test_seek_volume_and_logout(self):
        self.app.dispatch('play', {'index': 0})
        self.app.on_player({'event': 'file-loaded'})
        self.app.duration = 100
        self.app.dispatch('seek', {'seconds': 999})
        self.assertEqual(self.player.calls[-1][1], ['seek', 100, 'absolute'])
        self.app.dispatch('volume', {'value': -3})
        self.assertEqual(self.player.calls[-1][1], ['set_property', 'volume', 0])
        with self.assertRaises(UserError): self.app.dispatch('seek', {'seconds': float('nan')})
        self.app.dispatch('logout', {})
        self.assertIsNone(self.app.status()['track'])
        self.assertEqual(self.app.results, [])

    def test_unexpected_error_never_exposes_secret(self):
        self.api.search = lambda *_: (_ for _ in ()).throw(RuntimeError('qqmusic_key=SECRET'))
        self.app.handle({'id': 3, 'command': 'search', 'args': {'query': 'test'}})
        self.assertNotIn('SECRET', json.dumps(self.out))
        self.assertEqual(self.out[-1]['error'], 'backend_error')

    def test_stdio_ready_status_and_clean_eof(self):
        root = Path(__file__).resolve().parents[1]
        result = subprocess.run([sys.executable, '-B', str(root/'backend/main.py')],
                                input='{"id":1,"command":"status"}\n', text=True, capture_output=True,
                                env={**os.environ, 'XDG_STATE_HOME': self.tmp.name}, timeout=5)
        self.assertEqual(result.returncode, 0, result.stderr)
        messages = [json.loads(line) for line in result.stdout.splitlines()]
        self.assertEqual(messages[0]['event'], 'ready')
        self.assertTrue(messages[1]['ok'])
        self.assertFalse(messages[1]['data']['account']['loggedIn'])


if __name__ == '__main__':
    unittest.main()
