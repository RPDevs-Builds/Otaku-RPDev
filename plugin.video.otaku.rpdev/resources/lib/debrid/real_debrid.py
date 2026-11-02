import threading
import time

from resources.lib.ui import client, control, source_utils, database


class RealDebrid:
    _refresh_lock = threading.Lock()

    def __init__(self):
        self.ClientID = control.getSetting('realdebrid.client_id')
        if self.ClientID == '':
            api_info = database.get_info('Real-Debrid') or {}
            self.ClientID = api_info.get('client_id', '')
        self.ClientSecret = control.getSetting('realdebrid.secret')
        self.token = control.getSetting('realdebrid.token')
        self.refresh = control.getSetting('realdebrid.refresh')
        self.autodelete = control.getBool('realdebrid.autodelete')
        self.DeviceCode = ''
        self.OauthTimeout = 0
        self.OauthTimeStep = 0
        self.OauthTotalTimeout = 0
        self.OauthUrl = 'https://api.real-debrid.com/oauth/v2'
        self.BaseUrl = "https://api.real-debrid.com/rest/1.0"
        self.dialog = None

    def headers(self):
        return {'Authorization': f"Bearer {self.token}"}

    def auth_loop(self):
        if self.dialog and self.dialog.iscanceled():
            self.OauthTimeout = 0
            return False
        params = {
            'client_id': self.ClientID,
            'code': self.DeviceCode
        }
        r = client.get(f'{self.OauthUrl}/device/credentials', params=params)
        if r and r.ok:
            try:
                response = r.json()
                control.setSetting('realdebrid.client_id', response['client_id'])
                control.setSetting('realdebrid.secret', response['client_secret'])
                self.ClientSecret = response['client_secret']
                self.ClientID = response['client_id']
                return True
            except (ValueError, KeyError) as e:
                control.log(f"Real-Debrid auth_loop error: {str(e)}", 'error')
                return False
        return False

    def auth(self):
        import os
        from resources.lib.windows.progress_dialog import Progress_dialog

        api_info = database.get_info('Real-Debrid') or {}
        self.ClientID = api_info.get('client_id') or database._BUILTIN_API_INFO.get('Real-Debrid', {}).get('client_id', 'X245A4XAIBGVM')
        self.ClientSecret = ''
        params = {
            'client_id': self.ClientID,
            'new_credentials': 'yes'
        }
        response = client.get(f'{self.OauthUrl}/device/code', params=params)
        if not response or not response.ok:
            control.ok_dialog(control.ADDON_NAME, 'Failed to connect to Real-Debrid')
            return

        try:
            resp = response.json()
        except ValueError as e:
            control.ok_dialog(control.ADDON_NAME, f'Real-Debrid API error: {str(e)}')
            return

        copied = control.copy2clip(resp['user_code'])
        display_dialog = (f"{control.lang(30081).format(control.colorstr('https://real-debrid.com/device'))}[CR]"
                          f"{control.lang(30082).format(control.colorstr(resp['user_code']))}")
        if copied:
            display_dialog = f"{display_dialog}[CR]{control.lang(30083)}"

        qr_path = os.path.join(control.dataPath, 'qr_code.png')
        try:
            import pyqrcode
            os.makedirs(control.dataPath, exist_ok=True)
            qr = pyqrcode.create('https://real-debrid.com/device')
            qr.png(qr_path, scale=20)
        except Exception as e:
            control.log(f'Real-Debrid QR generation failed: {e}', level='warning')
            qr_path = ''

        config = {
            'heading': f'{control.ADDON_NAME}: Real-Debrid Auth',
            'text': display_dialog,
            'qr_code': qr_path,
            'percent': 100
        }
        self.dialog = Progress_dialog('progress_dialog.xml', control.ADDON_PATH, config=config)
        self.dialog.show()

        auth_done = False
        try:
            self.OauthTotalTimeout = self.OauthTimeout = int(resp.get('expires_in', 900))
            self.OauthTimeStep = max(1, int(resp.get('interval', 5)))
            self.DeviceCode = resp['device_code']
            while not auth_done and self.OauthTimeout > 0:
                for _ in range(self.OauthTimeStep):
                    if control.abort_requested() or (self.dialog and self.dialog.iscanceled()):
                        break
                    control.sleep(1000)
                if control.abort_requested() or (self.dialog and self.dialog.iscanceled()):
                    break
                self.OauthTimeout -= self.OauthTimeStep
                auth_done = self.auth_loop()
                if self.dialog:
                    self.dialog.update(int(self.OauthTimeout / self.OauthTotalTimeout * 100))
        finally:
            if self.dialog:
                self.dialog.close()
                del self.dialog
                self.dialog = None

        if auth_done:
            self.token_request()
            self.status()
            control.setBool('realdebrid.enabled', True)

    def token_request(self):
        if self.ClientSecret == '':
            return

        postData = {
            'client_id': self.ClientID,
            'client_secret': self.ClientSecret,
            'code': self.DeviceCode,
            'grant_type': 'http://oauth.net/grant_type/device/1.0'
        }

        response = client.post(f'{self.OauthUrl}/token', data=postData)
        if not response or not response.ok:
            control.ok_dialog(control.ADDON_NAME, 'Failed to get Real-Debrid token')
            return

        try:
            response = response.json()
            control.setSetting('realdebrid.token', response['access_token'])
            control.setSetting('realdebrid.refresh', response['refresh_token'])
            control.setInt('realdebrid.expiry', int(time.time()) + int(response['expires_in']))
            self.token = response['access_token']
            self.refresh = response['refresh_token']
        except (ValueError, KeyError) as e:
            control.ok_dialog(control.ADDON_NAME, f'Real-Debrid token error: {str(e)}')

    def status(self):
        response = client.get(f'{self.BaseUrl}/user', headers=self.headers())
        if not response or not response.ok:
            control.ok_dialog(control.ADDON_NAME, 'Failed to get Real-Debrid user info')
            return

        try:
            user_info = response.json()
            control.setSetting('realdebrid.username', user_info['username'])
            control.setSetting('realdebrid.auth.status', user_info['type'].capitalize())
            control.ok_dialog(control.ADDON_NAME, f'Real-Debrid {control.lang(30084)}')
            if user_info['type'] != 'premium':
                control.ok_dialog(f'{control.ADDON_NAME}: Real-Debrid', control.lang(30085))
        except (ValueError, KeyError) as e:
            control.ok_dialog(control.ADDON_NAME, f'Real-Debrid user info error: {str(e)}')

    def refreshToken(self):
        with self._refresh_lock:
            postData = {
                'grant_type': 'http://oauth.net/grant_type/device/1.0',
                'code': self.refresh,
                'client_secret': self.ClientSecret,
                'client_id': self.ClientID
            }
            response = client.post(f"{self.OauthUrl}/token", data=postData)
            if response and response.ok:
                try:
                    response = response.json()
                    self.token = response['access_token']
                    self.refresh = response['refresh_token']
                    control.setSetting('realdebrid.token', self.token)
                    control.setSetting('realdebrid.refresh', self.refresh)
                    control.setInt('realdebrid.expiry', int(time.time()) + int(response['expires_in']))

                    user_info_response = client.get(f'{self.BaseUrl}/user', headers=self.headers())
                    if user_info_response and user_info_response.ok:
                        user_info = user_info_response.json()
                        control.setSetting('realdebrid.username', user_info['username'])
                        control.setSetting('realdebrid.auth.status', user_info['type'])
                    control.log('refreshed realdebrid.token')
                except (ValueError, KeyError) as e:
                    control.log(f"realdebrid.refresh error: {str(e)}", 'warning')
            else:
                control.log(f"realdebrid.refresh failed: status {response.status_code if response else 'no response'}", 'warning')

    def _request_with_backoff(self, method, url, **kwargs):
        """Execute HTTP request with 1x exponential backoff if HTTP 429 is received."""
        r = getattr(client, method.lower())(url, **kwargs)
        if r and r.status_code == 429:
            try:
                wait_seconds = int(r.headers.get('Retry-After', 1))
            except (ValueError, TypeError):
                wait_seconds = 1
            wait_seconds = min(max(wait_seconds, 1), 3)
            control.log(f"Real-Debrid API rate limited (429) for {url}, backing off {wait_seconds}s", 'warning')
            time.sleep(wait_seconds)
            r = getattr(client, method.lower())(url, **kwargs)
        return r

    def addMagnet(self, magnet):
        postData = {'magnet': magnet}
        response = self._request_with_backoff('post', f'{self.BaseUrl}/torrents/addMagnet', headers=self.headers(), data=postData)
        if response and response.ok:
            return response.json()
        return None

    def list_torrents(self):
        response = self._request_with_backoff('get', f'{self.BaseUrl}/torrents', headers=self.headers())
        if response and response.ok:
            return response.json()
        return []

    def torrentInfo(self, torrent_id):
        response = self._request_with_backoff('get', f'{self.BaseUrl}/torrents/info/{torrent_id}', headers=self.headers())
        if response and response.ok:
            return response.json()
        return None

    def torrentSelect(self, torrentid, fileid='all'):
        postData = {'files': fileid}
        response = self._request_with_backoff('post', f'{self.BaseUrl}/torrents/selectFiles/{torrentid}', headers=self.headers(), data=postData)
        return bool(response and getattr(response, 'ok', True))

    def resolve_hoster(self, link):
        postData = {'link': link}
        response = self._request_with_backoff('post', f'{self.BaseUrl}/unrestrict/link', headers=self.headers(), data=postData)
        if response and response.ok:
            response = response.json()
            return response.get('download')
        return None

    def deleteTorrent(self, torrent_id):
        response = self._request_with_backoff('delete', f'{self.BaseUrl}/torrents/delete/{torrent_id}', headers=self.headers(), timeout=10)
        return bool(response and getattr(response, 'ok', True))

    @staticmethod
    def resolve_cloud(source, pack_select):
        if source['torrent_files']:
            best_match = source_utils.get_best_match('path', source['torrent_files'], source['episode'], pack_select)
            if not best_match or not best_match['path']:
                return
            for f_index, torrent_file in enumerate(source['torrent_files']):
                if torrent_file['path'] == best_match['path']:
                    return source['torrent_info']['links'][f_index]

    def resolve_single_magnet(self, hash_, magnet, episode='', pack_select=False, filename=None):
        # DMM handles cache checking - just add the magnet directly
        stream_link = None
        torrent = self.addMagnet(magnet)
        if not torrent:
            return None

        torrent_id = torrent.get('id')
        if not torrent_id:
            return None

        try:
            self.torrentSelect(torrent_id)
            files = self.torrentInfo(torrent_id)
            if not files or not files.get('links'):
                return None

            selected_files = [(idx, i) for idx, i in enumerate([i for i in files.get('files', []) if i.get('selected') == 1])]
            if not selected_files:
                return None

            if pack_select:
                best_match = source_utils.get_best_match('path', [i[1] for i in selected_files], episode, pack_select, filename)
                if best_match:
                    try:
                        file_index = [i[0] for i in selected_files if i[1].get('path') == best_match.get('path')][0]
                        link = files['links'][file_index]
                        stream_link = self.resolve_hoster(link)
                    except (IndexError, KeyError) as e:
                        control.log(f"RD pack match link error: {e}", 'debug')
            elif len(selected_files) == 1:
                try:
                    stream_link = self.resolve_hoster(files['links'][0])
                except (IndexError, KeyError) as e:
                    control.log(f"RD single file link error: {e}", 'debug')
            elif len(selected_files) > 1:
                best_match = source_utils.get_best_match('path', [i[1] for i in selected_files], episode, pack_select=False, filename=filename)
                if best_match:
                    try:
                        file_index = [i[0] for i in selected_files if i[1].get('path') == best_match.get('path')][0]
                        link = files['links'][file_index]
                        stream_link = self.resolve_hoster(link)
                    except (IndexError, KeyError) as e:
                        control.log(f"RD multi file match error: {e}", 'debug')
        finally:
            if not stream_link or self.autodelete:
                self.deleteTorrent(torrent_id)

        return stream_link

    def get_torrent_status(self, magnet):
        """
        Given a magnet link, get torrent data needed for further resolution.
        Returns a tuple: (torrent_id, status, torrent_info)
        If the torrent cannot be selected, returns (None, None, None).
        """
        magnet_data = self.addMagnet(magnet)
        if not magnet_data or 'id' not in magnet_data:
            control.ok_dialog(control.ADDON_NAME, "BAD LINK")
            return None, None, None
        if not self.torrentSelect(magnet_data['id']):
            self.deleteTorrent(magnet_data['id'])
            control.ok_dialog(control.ADDON_NAME, "BAD LINK")
            return None, None, None
        torrent_id = magnet_data['id']
        torrent_info = self.torrentInfo(torrent_id)
        if not torrent_info:
            self.deleteTorrent(torrent_id)
            return None, None, None
        status = torrent_info.get('status', 'error')
        return torrent_id, status, torrent_info

    def resolve_uncached_source(self, source, runinbackground, runinforground, pack_select):
        heading = f'{control.ADDON_NAME}: Cache Resolver'
        if runinforground:
            control.progressDialog.create(heading, "Caching Progress")
        stream_link = None
        magnet = source['magnet']
        magnet_data = self.addMagnet(magnet)
        if not magnet_data or 'id' not in magnet_data:
            control.ok_dialog(control.ADDON_NAME, "BAD LINK")
            if runinforground:
                control.progressDialog.close()
            return None

        if not self.torrentSelect(magnet_data['id']):
            self.deleteTorrent(magnet_data['id'])
            control.ok_dialog(control.ADDON_NAME, "BAD LINK")
            if runinbackground:
                return

        torrent_id = magnet_data['id']
        torrent_info = self.torrentInfo(torrent_id)
        if not torrent_info:
            self.deleteTorrent(torrent_id)
            if runinforground:
                control.progressDialog.close()
            return None
        status = torrent_info['status']

        if runinbackground:
            control.notify(heading, "The source is downloading to your cloud")
            return

        progress = 0
        while status not in ['downloaded', 'error']:
            if runinforground and (control.progressDialog.iscanceled() or control.wait_for_abort(5)):
                break
            torrent_info = self.torrentInfo(torrent_id)
            if not torrent_info:
                status = 'error'
                break
            status = torrent_info.get('status', 'error')
            progress = torrent_info.get('progress', 0)
            seeders = torrent_info.get('seeders', 0)
            speed = torrent_info.get('speed', 0)
            if runinforground:
                f_body = (f"Status: {status}[CR]"
                          f"Progress: {round(progress, 2)} %[CR]"
                          f"Seeders: {seeders}[CR]"
                          f"Speed: {source_utils.get_size(speed)}")
                control.progressDialog.update(int(progress), f_body)

        if status == 'downloaded':
            if progress == 100:
                control.ok_dialog(heading, "This file has been added to your Cloud")
            torrent_files = [selected for selected in torrent_info['files'] if selected['selected'] == 1]

            if len(torrent_info['files']) == 1:
                best_match = torrent_files[0]
            else:
                best_match = source_utils.get_best_match('path', torrent_files, source['episode_re'], pack_select)

            if not best_match or not best_match['path']:
                self.deleteTorrent(torrent_id)
                return

            for f_index, torrent_file in enumerate(torrent_files):
                if torrent_file['path'] == best_match['path']:
                    hash_ = torrent_info['links'][f_index]
                    stream_link = self.resolve_hoster(hash_)
            if self.autodelete:
                self.deleteTorrent(torrent_id)
        else:
            self.deleteTorrent(torrent_id)
        if runinforground:
            control.progressDialog.close()
        return stream_link
