import random
import time
import urllib.parse
from resources.lib.ui import client, control, source_utils


class AllDebrid:
    def __init__(self):
        self.token = control.getSetting('alldebrid.token')
        self.autodelete = control.getBool('alldebrid.autodelete')
        self.agent_identifier = 'Otaku'
        self.base_url = 'https://api.alldebrid.com/v4.1'
        self.cache_check_results = []
        self.OauthTimeStep = 1
        self.OauthTimeout = 0
        self.OauthTotalTimeout = 0
        self.dialog = None

    def auth(self):
        import os
        from resources.lib.windows.progress_dialog import Progress_dialog

        params = {'agent': self.agent_identifier}
        r = client.get(f'{self.base_url}/pin/get', params=params)
        resp = r.json().get('data', {}) if (r and r.ok) else {}
        if not resp or 'pin' not in resp:
            control.ok_dialog(control.ADDON_NAME, 'Failed to connect to AllDebrid')
            return

        self.OauthTotalTimeout = self.OauthTimeout = int(resp.get('expires_in', 600))
        self.OauthTimeStep = max(1, int(resp.get('check_step', 2)))
        copied = control.copy2clip(resp['pin'])
        display_dialog = (f"{control.lang(30081).format(control.colorstr(resp.get('base_url', 'https://alldebrid.com/pin')))}[CR]"
                          f"{control.lang(30082).format(control.colorstr(resp['pin']))}")
        if copied:
            display_dialog = f"{display_dialog}[CR]{control.lang(30083)}"

        qr_path = os.path.join(control.dataPath, 'qr_code.png')
        try:
            import pyqrcode
            os.makedirs(control.dataPath, exist_ok=True)
            qr = pyqrcode.create(resp.get('user_url', resp.get('base_url', 'https://alldebrid.com/pin')))
            qr.png(qr_path, scale=20)
        except Exception as e:
            control.log(f"AllDebrid pyqrcode generation error: {e}", 'warning')
            qr_path = ''

        config = {
            'heading': f'{control.ADDON_NAME}: AllDebrid Auth',
            'text': display_dialog,
            'qr_code': qr_path,
            'percent': 100
        }
        self.dialog = Progress_dialog('progress_dialog.xml', control.ADDON_PATH, config=config)
        self.dialog.show()

        auth_done = False
        try:
            # Responsive initial wait before polling pin
            for _ in range(5):
                if control.abort_requested() or (self.dialog and self.dialog.iscanceled()):
                    return
                control.sleep(1000)

            while not auth_done and self.OauthTimeout > 0:
                for _ in range(self.OauthTimeStep):
                    if control.abort_requested() or (self.dialog and self.dialog.iscanceled()):
                        break
                    control.sleep(1000)
                if control.abort_requested() or (self.dialog and self.dialog.iscanceled()):
                    break
                self.OauthTimeout -= self.OauthTimeStep
                auth_done = self.auth_loop(check=resp.get('check'), pin=resp.get('pin'))
                if self.dialog:
                    self.dialog.update(int(self.OauthTimeout / self.OauthTotalTimeout * 100))
        finally:
            if self.dialog:
                self.dialog.close()
                del self.dialog
                self.dialog = None

        if auth_done:
            self.status()
            control.setBool('alldebrid.enabled', True)

    def status(self):
        params = {
            'agent': self.agent_identifier,
            'apikey': self.token
        }
        r = client.get(f'{self.base_url}/user', params=params)
        res = r.json().get('data', {}) if (r and r.ok) else {}
        user_information = res.get('user', {})
        if not user_information:
            control.ok_dialog(control.ADDON_NAME, 'Failed to get AllDebrid user info')
            return
        premium = user_information.get('isPremium', False)
        control.setSetting('alldebrid.username', user_information.get('username', ''))
        control.ok_dialog(control.ADDON_NAME, f'Alldebrid {control.lang(30084)}')
        if not premium:
            control.setSetting('alldebrid.auth.status', 'Expired')
            control.ok_dialog(f'{control.ADDON_NAME}: AllDebrid', control.lang(30085))
        else:
            control.setSetting('alldebrid.auth.status', 'Premium')

    def auth_loop(self, **params):
        if self.dialog and self.dialog.iscanceled():
            self.OauthTimeout = 0
            return False
        params['agent'] = self.agent_identifier
        r = client.get(f'{self.base_url}/pin/check', params=params)
        resp = r.json().get('data', {}) if (r and r.ok) else {}
        if resp.get('activated'):
            self.token = resp.get('apikey', '')
            control.setSetting('alldebrid.token', self.token)
            return True
        return False

    def _request_with_backoff(self, method, url, **kwargs):
        """Execute HTTP request with 1x exponential backoff if HTTP 429 is received."""
        r = getattr(client, method.lower())(url, **kwargs)
        if r and r.status_code == 429:
            try:
                wait_seconds = float(r.headers.get('Retry-After', 1))
            except (ValueError, TypeError):
                wait_seconds = 1.0
            wait_seconds = min(max(wait_seconds, 1.0), 3.0) + random.uniform(0.1, 0.4)
            control.log(f"AllDebrid API rate limited (429) for {url}, backing off {wait_seconds:.2f}s", 'warning')
            if control.monitor.waitForAbort(wait_seconds):
                return None
            r = getattr(client, method.lower())(url, **kwargs)
        return r

    def addMagnet(self, magnet_hash):
        params = {
            'agent': self.agent_identifier,
            'apikey': self.token,
            'magnets': magnet_hash
        }
        r = self._request_with_backoff('get', f'{self.base_url}/magnet/upload', params=params)
        return (r.json() or {}).get('data') if r else None

    def resolve_hoster(self, url):
        params = {
            'agent': self.agent_identifier,
            'apikey': self.token,
            'link': url
        }
        r = self._request_with_backoff('get', f'{self.base_url}/link/unlock', params=params)
        resolve = ((r.json() or {}).get('data') or {}) if r else {}
        return resolve.get('link')

    def magnet_status(self, magnet_id):
        params = {
            'agent': self.agent_identifier,
            'apikey': self.token,
            'id': magnet_id
        }
        r = self._request_with_backoff('get', f'{self.base_url}/magnet/status', params=params)
        return (r.json() or {}).get('data') if r else None

    def list_saved_links(self):
        params = {
            'agent': self.agent_identifier,
            'apikey': self.token
        }
        r = self._request_with_backoff('get', f'{self.base_url}/user/links', params=params)
        return (r.json() or {}).get('data') if r else None

    def list_torrents(self):
        params = {
            'agent': self.agent_identifier,
            'apikey': self.token,
            'status': 'ready'
        }
        r = self._request_with_backoff('get', f'{self.base_url}/magnet/status', params=params)
        data = (r.json() or {}).get('data') if r else None
        if not data:
            return []
        magnets = data.get('magnets', [])
        if isinstance(magnets, dict):
            magnets = list(magnets.values())
        return magnets

    def list_history(self):
        params = {
            'agent': self.agent_identifier,
            'apikey': self.token
        }
        r = self._request_with_backoff('get', f'{self.base_url}/user/history', params=params)
        return (r.json() or {}).get('data') if r else None

    def link_info(self, link):
        params = {
            'agent': self.agent_identifier,
            'apikey': self.token,
            'link[]': link
        }
        encoded_params = urllib.parse.urlencode(params, doseq=True)
        url = f'{self.base_url}/link/infos?{encoded_params}'
        r = self._request_with_backoff('get', url)
        return (r.json() or {}).get('data') if r else None

    def resolve_single_magnet(self, hash_, magnet, episode, pack_select, filename=None):
        magnet_data = self.addMagnet(magnet)
        if not magnet_data or 'magnets' not in magnet_data or not magnet_data['magnets']:
            return None
        magnet_id = magnet_data['magnets'][0]['id']
        resolved_link = None
        try:
            status_data = self.magnet_status(magnet_id)
            if not status_data or 'magnets' not in status_data:
                return None
            magnets = status_data.get('magnets')
            if isinstance(magnets, list):
                magnets = magnets[0] if magnets else {}
            if not magnets or 'files' not in magnets:
                return None
            details = magnets['files']
            folder_details = []
            for x in details:
                self.collect_files(x, folder_details)

            if not folder_details:
                return None

            if episode:
                selected_file = source_utils.get_best_match('path', folder_details, str(episode), pack_select, filename)
                if selected_file and selected_file.get('link'):
                    resolved_link = self.resolve_hoster(selected_file['link'])
                    return resolved_link

            if not resolved_link and folder_details:
                first_link = folder_details[0].get('link')
                if first_link:
                    resolved_link = self.resolve_hoster(first_link)
            return resolved_link
        finally:
            if not resolved_link or self.autodelete:
                self.delete_magnet(magnet_id)

    def resolve_cloud(self, source, pack_select):
        pass

    def delete_magnet(self, magnet_id):
        params = {
            'agent': self.agent_identifier,
            'apikey': self.token,
            'id': magnet_id
        }
        r = self._request_with_backoff('get', f'{self.base_url}/magnet/delete', params=params)
        return r and r.ok

    def get_torrent_status(self, magnet):
        """
        Given a magnet link, get magnet status data needed for further resolution.
        Returns a tuple: (magnet_id, status, status_data)
        If the magnet cannot be processed correctly, returns (None, None, None).
        """
        magnet_data = self.addMagnet(magnet)
        if not magnet_data or 'magnets' not in magnet_data or not magnet_data['magnets']:
            control.ok_dialog(control.ADDON_NAME, "BAD LINK")
            return None, None, None

        magnet_id = magnet_data['magnets'][0]['id']
        status_data = self.magnet_status(magnet_id)
        if not status_data or 'magnets' not in status_data:
            self.delete_magnet(magnet_id)
            control.ok_dialog(control.ADDON_NAME, "BAD LINK")
            return None, None, None

        magnets = status_data.get('magnets')
        if isinstance(magnets, list):
            magnets = magnets[0] if magnets else {}
        status = magnets.get('status')
        return magnet_id, status, status_data

    def collect_files(self, y, files):
        if y.get('e'):
            for z in y.get('e'):
                self.collect_files(z, files)
        else:
            files.append({'link': y['l'], 'path': y['n'], 'size': y.get('s', 0)})
        return files

    def resolve_uncached_source(self, source, runinbackground, runinforground, pack_select):
        heading = f'{control.ADDON_NAME}: Cache Resolver'
        if runinforground:
            control.progressDialog.create(heading, "Caching Progress")
        stream_link = None
        magnet = source['magnet']
        magnet_data = self.addMagnet(magnet)
        if not magnet_data or 'magnets' not in magnet_data or not magnet_data['magnets']:
            if runinforground:
                control.progressDialog.close()
            return None
        magnet_id = magnet_data['magnets'][0]['id']
        magnet_status = self.magnet_status(magnet_id)
        if not magnet_status or 'magnets' not in magnet_status:
            self.delete_magnet(magnet_id)
            if runinforground:
                control.progressDialog.close()
            return None
        magnets = magnet_status.get('magnets')
        if isinstance(magnets, list):
            magnets = magnets[0] if magnets else {}
        status = magnets.get('status')

        if runinbackground:
            control.notify(heading, "The source is downloading to your cloud")
            return

        total_size = 0
        progress = 0
        while status not in ['Ready', 'Error']:
            if runinforground and (control.progressDialog.iscanceled() or control.wait_for_abort(5)):
                break
            magnet_status = self.magnet_status(magnet_id)
            if not magnet_status or 'magnets' not in magnet_status:
                status = 'Error'
                break
            magnets = magnet_status.get('magnets')
            if isinstance(magnets, list):
                magnets = magnets[0] if magnets else {}
            status = magnets.get('status', 'Error')
            total_size = magnets.get('size', 0)  # Update total_size in the loop
            try:
                downloaded = magnets.get('downloaded', 0)
                seeders = magnets.get('seeders', 0)
                speed = magnets.get('downloadSpeed', 0)
                if total_size > 0:
                    progress = (downloaded / total_size) * 100
                else:
                    progress = 0
            except TypeError:
                control.log(magnet_status)
            if runinforground:
                f_body = (f"Status: {status}[CR]"
                          f"Progress: {round(progress, 2)} %[CR]"
                          f"Seeders: {seeders}[CR]"
                          f"Speed: {source_utils.get_size(speed)}")
                control.progressDialog.update(int(progress), f_body)

        if status == 'Ready':
            if total_size > 0:
                control.ok_dialog(heading, "This file has been added to your Cloud")
            # Check if there's only one file in the torrent
            details = magnets.get('files', [])
            folder_details = []
            for x in details:
                self.collect_files(x, folder_details)
            if len(folder_details) == 1:
                # If there's just one file, use it directly
                stream_link = self.resolve_hoster(folder_details[0]['link'])
            else:
                # If there are multiple files, use best match algorithm
                selected_file = source_utils.get_best_match('path', folder_details, source['episode_re'], pack_select)

                if not selected_file or not selected_file['path']:
                    self.delete_magnet(magnet_id)
                    return

                stream_link = self.resolve_hoster(selected_file['link'])
            if self.autodelete:
                self.delete_magnet(magnet_id)
        else:
            self.delete_magnet(magnet_id)
        if runinforground:
            control.progressDialog.close()
        return stream_link
