import random
import time
import urllib.parse

from resources.lib.ui import source_utils, client, control, database


class Premiumize:
    def __init__(self):
        api_info = database.get_info('Premiumize') or {}
        self.client_id = api_info.get('client_id', '')
        self.token = control.getSetting('premiumize.token')
        self.addtocloud = control.getBool('premiumize.addToCloud')
        self.autodelete = control.getBool('premiumize.autodelete')
        self.threshold = control.getInt('premiumize.threshold')
        self.base_url = 'https://www.premiumize.me/api'
        self.OauthTimeStep = 0
        self.OauthTimeout = 0
        self.OauthTotalTimeout = 0
        self.dialog = None

    def headers(self):
        return {'Authorization': f"Bearer {self.token}"}

    def _request_with_backoff(self, method, url, **kwargs):
        """Execute HTTP request with 1x exponential backoff if HTTP 429 is received."""
        r = getattr(client, method.lower())(url, **kwargs)
        if r and r.status_code == 429:
            try:
                wait_seconds = float(r.headers.get('Retry-After', 1))
            except (ValueError, TypeError):
                wait_seconds = 1.0
            wait_seconds = min(max(wait_seconds, 1.0), 3.0) + random.uniform(0.1, 0.4)
            control.log(f"Premiumize API rate limited (429) for {url}, backing off {wait_seconds:.2f}s", 'warning')
            if control.monitor.waitForAbort(wait_seconds):
                return None
            r = getattr(client, method.lower())(url, **kwargs)
        return r

    def auth(self):
        import os
        from resources.lib.windows.progress_dialog import Progress_dialog

        client_id = self.client_id or '807831898'
        data = {'client_id': client_id, 'response_type': 'device_code'}
        response = client.post('https://www.premiumize.me/token', json_data=data)
        if not response or not response.ok:
            control.ok_dialog(control.ADDON_NAME, 'Failed to connect to Premiumize')
            return

        try:
            resp = response.json()
        except (ValueError, TypeError) as e:
            control.ok_dialog(control.ADDON_NAME, f'Premiumize API error: {str(e)}')
            return

        if not resp or 'device_code' not in resp:
            control.ok_dialog(control.ADDON_NAME, 'Failed to retrieve device code from Premiumize')
            return

        self.OauthTotalTimeout = self.OauthTimeout = int(resp.get('expires_in', 600))
        self.OauthTimeStep = int(resp.get('interval', 5))
        user_code = resp['user_code']
        verification_uri = resp.get('verification_uri', 'https://www.premiumize.me/device')

        copied = control.copy2clip(user_code)
        display_dialog = (f"{control.lang(30081).format(control.colorstr(verification_uri))}[CR]"
                          f"{control.lang(30082).format(control.colorstr(user_code))}")
        if copied:
            display_dialog = f"{display_dialog}[CR]{control.lang(30083)}"

        # Generate QR code pointing directly to enrollment URL with user_code embedded
        qr_path = ''
        try:
            import pyqrcode
            os.makedirs(control.dataPath, exist_ok=True)
            qr_target = f"{verification_uri}?user_code={user_code}"
            qr_file = os.path.join(control.dataPath, 'qr_code.png')
            qr = pyqrcode.create(qr_target)
            qr.png(qr_file, scale=20)
            qr_path = qr_file
        except Exception as e:
            control.log(f"Premiumize pyqrcode generation error: {e}", 'warning')

        config = {
            'heading': f'{control.ADDON_NAME}: Premiumize Auth',
            'text': display_dialog,
            'qr_code': qr_path,
            'percent': 100
        }
        self.dialog = Progress_dialog('progress_dialog.xml', control.ADDON_PATH, config=config)
        self.dialog.show()

        auth_done = False
        try:
            while not auth_done and self.OauthTimeout > 0:
                for _ in range(max(1, self.OauthTimeStep)):
                    if control.abort_requested() or (self.dialog and self.dialog.iscanceled()):
                        break
                    control.sleep(1000)
                if control.abort_requested() or (self.dialog and self.dialog.iscanceled()):
                    break
                self.OauthTimeout -= self.OauthTimeStep
                auth_done = self.auth_loop(resp['device_code'])
                if self.dialog:
                    self.dialog.update(int(self.OauthTimeout / self.OauthTotalTimeout * 100))
        finally:
            if self.dialog:
                self.dialog.close()
                del self.dialog
                self.dialog = None

        if auth_done:
            self.status()
            control.setBool('premiumize.enabled', True)

    def status(self):
        r = client.get(f'{self.base_url}/account/info', headers=self.headers())
        user_information = r.json(default={}) if (r and r.ok) else {}
        premium_until = user_information.get('premium_until') or 0
        premium = int(premium_until) > 0 if str(premium_until).isdigit() else False
        customer_id = str(user_information.get('customer_id', ''))
        control.setSetting('premiumize.username', customer_id)
        control.ok_dialog(control.ADDON_NAME, f'Premiumize {control.lang(30084)}')
        if not premium:
            control.setSetting('premiumize.auth.status', 'Expired')
            control.ok_dialog(f'{control.ADDON_NAME}: Premiumize', control.lang(30085))
        else:
            control.setSetting('premiumize.auth.status', 'Premium')

    def auth_loop(self, device_code):
        if not self.dialog or self.dialog.iscanceled():
            self.OauthTimeout = 0
            return False
        client_id = self.client_id or '807831898'
        data = {'client_id': client_id, 'code': device_code, 'grant_type': 'device_code'}
        r = client.post('https://www.premiumize.me/token', json_data=data)
        try:
            token = r.json() if r is not None else {}
        except Exception:
            token = {}

        if r and r.ok and 'access_token' in token:
            self.token = token['access_token']
            control.setSetting('premiumize.token', self.token)
            return True
        else:
            error = token.get('error')
            if error in ('access_denied', 'invalid_grant'):
                self.OauthTimeout = 0
            elif error == 'slow_down':
                self.OauthTimeStep += 5
                control.monitor.waitForAbort(5)
        return False

    def search_folder(self, query):
        params = {'q': query}
        r = self._request_with_backoff('get', f'{self.base_url}/folder/search', headers=self.headers(), params=params)
        return (r.json() or {}).get('content', []) if r else None

    def list_folder(self, folderid=None):
        params = {'id': folderid} if (folderid and folderid != 'root') else None
        r = self._request_with_backoff('get', f"{self.base_url}/folder/list", headers=self.headers(), params=params)
        data = r.json() if r else {}
        return data.get('content', []) if isinstance(data, dict) else []

    def get_root_folder_id(self):
        r = self._request_with_backoff('get', f"{self.base_url}/folder/list", headers=self.headers())
        data = r.json() if r else {}
        return data.get('folder_id') if isinstance(data, dict) else None

    def item_details(self, item_id):
        r = self._request_with_backoff('get', f"{self.base_url}/item/details", headers=self.headers(), params={'id': item_id})
        return r.json() if r else None

    def create_folder(self, name, parent_id=None):
        data = {'name': name}
        if parent_id and parent_id != 'root':
            data['parent_id'] = parent_id
        r = self._request_with_backoff('post', f"{self.base_url}/folder/create", headers=self.headers(), data=data)
        return r.json() if r else None

    def rename_folder(self, folder_id, name):
        data = {'id': folder_id, 'name': name}
        r = self._request_with_backoff('post', f"{self.base_url}/folder/rename", headers=self.headers(), data=data)
        return r.json() if r else None

    def rename_item(self, item_id, name):
        data = {'id': item_id, 'name': name}
        r = self._request_with_backoff('post', f"{self.base_url}/item/rename", headers=self.headers(), data=data)
        return r.json() if r else None

    def delete_folder(self, folder_id):
        data = {'id': folder_id}
        r = self._request_with_backoff('post', f"{self.base_url}/folder/delete", headers=self.headers(), data=data)
        return r.json() if r else None

    def delete_item(self, item_id):
        data = {'id': item_id}
        r = self._request_with_backoff('post', f"{self.base_url}/item/delete", headers=self.headers(), data=data)
        return r.json() if r else None

    def move_items(self, target_folder_id, file_ids=None, folder_ids=None):
        if not target_folder_id or target_folder_id == 'root':
            target_folder_id = self.get_root_folder_id()
        if not target_folder_id:
            return None
        data = [('id', target_folder_id)]
        for fid in (file_ids or []):
            data.append(('files[]', fid))
        for flid in (folder_ids or []):
            data.append(('folders[]', flid))
        r = self._request_with_backoff('post', f"{self.base_url}/folder/paste", headers=self.headers(), data=data)
        return r.json() if r else None

    def hash_check(self, hashlist):
        if not hashlist:
            return None
        all_responses = []
        chunk_size = 100
        for i in range(0, len(hashlist), chunk_size):
            chunk = hashlist[i:i + chunk_size]
            data = [('items[]', h) for h in chunk]
            r = self._request_with_backoff('post', f'{self.base_url}/cache/check', headers=self.headers(), data=data)
            res = r.json() if r else None
            if not res or 'response' not in res:
                return None
            all_responses.extend(res['response'])
        return {'status': 'success', 'response': all_responses}

    def direct_download(self, src):
        postData = {'src': src}
        r = self._request_with_backoff('post', f'{self.base_url}/transfer/directdl', headers=self.headers(), data=postData)
        return r.json() if r else None

    def addMagnet(self, src):
        postData = {'src': src}
        r = self._request_with_backoff('post', f'{self.base_url}/transfer/create', headers=self.headers(), data=postData)
        return r.json() if r else None

    def transfer_list(self):
        r = self._request_with_backoff('get', f'{self.base_url}/transfer/list', headers=self.headers())
        return (r.json() or {}).get('transfers', []) if r else None

    def delete_torrent(self, torrent_id):
        params = {'id': torrent_id}
        r = self._request_with_backoff('post', f'{self.base_url}/transfer/delete', headers=self.headers(), data=params)
        return r.json() if r else None

    def manage_storage_space(self):
        storage_info = self.get_storage_info()
        if not storage_info or 'space_used' not in storage_info:
            return
        used_space_gb = storage_info['space_used'] / (1024 ** 3)
        if used_space_gb > self.threshold:
            oldest_items = self.get_oldest_items()
            for item in oldest_items:
                self.delete_torrent(item['id'])
                used_space_gb -= item['size'] / (1024 ** 3)
                if used_space_gb <= self.threshold:
                    break

    def get_storage_info(self):
        r = self._request_with_backoff('get', f'{self.base_url}/account/info', headers=self.headers())
        return r.json() if r else None

    def get_oldest_items(self):
        r = client.get(f'{self.base_url}/transfer/list', headers=self.headers())
        transfers = (r.json() or {}).get('transfers', []) if r else []
        # Filter out items missing 'created_at' to avoid KeyError
        transfers_with_created = [x for x in transfers if 'created_at' in x]
        return sorted(transfers_with_created, key=lambda x: x['created_at'])

    def add_to_cloud(self, link):
        postData = {'src': link}
        r = client.post(f'{self.base_url}/transfer/create', headers=self.headers(), data=postData)
        response = r.json() if r else {}
        if response.get('status') == 'success':
            control.log(f"Successfully added to cloud: {link}")
        else:
            control.log(f"Failed to add to cloud: {link}", level='error')
        return response

    def resolve_hoster(self, source):
        self.manage_storage_space()
        directLink = self.direct_download(source)
        if not directLink or directLink.get('status') != 'success':
            return None
        if self.addtocloud:
            self.add_to_cloud(directLink.get('location', ''))
        return directLink.get('location')

    def resolve_single_magnet(self, hash_, magnet, episode, pack_select, filename=None):
        self.manage_storage_space()
        dd_result = self.direct_download(magnet)
        if not dd_result or 'content' not in dd_result:
            return None
        folder_details = dd_result['content']
        folder_details = sorted(folder_details, key=lambda i: int(i['size']), reverse=True)
        folder_details = [i for i in folder_details if source_utils.is_file_ext_valid(i.get('path') or i.get('link', ''))]
        filter_list = [i for i in folder_details]

        if pack_select:
            identified_file = source_utils.get_best_match('path', folder_details, episode, pack_select, filename)
            stream_link = identified_file.get('link') if identified_file else None
        elif len(filter_list) == 1:
            stream_link = filter_list[0]['link']
        elif len(filter_list) > 1:
            identified_file = source_utils.get_best_match('path', folder_details, episode, filename=filename)
            stream_link = identified_file.get('link') if identified_file else None
            if not stream_link:
                if identified_file and identified_file.get('path') == '' and 'link' not in identified_file:
                    return None
                samples_filtered = [tfile for tfile in folder_details if 'sample' not in tfile.get('path', '').lower()]
                if samples_filtered:
                    stream_link = samples_filtered[0]['link']
        else:
            samples_filtered = [tfile for tfile in folder_details if 'sample' not in tfile.get('path', '').lower()]
            if samples_filtered:
                stream_link = samples_filtered[0]['link']

        if stream_link and self.addtocloud:
            self.add_to_cloud(magnet)
        return stream_link

    def resolve_cloud(self, source, pack_select):
        def get_all_files(folder_id):
            items = self.list_folder(folder_id)
            files = []
            for item in items:
                if item['type'] == 'folder':
                    files.extend(get_all_files(item['id']))
                else:
                    files.append(item)
            return files

        link = None
        if source['torrent_type'] == 'file':
            link = source['hash']
        elif source['torrent_type'] == 'folder':
            all_files = get_all_files(source['id'])
            best_match = source_utils.get_best_match('name', all_files, source['episode'], pack_select)
            if best_match and best_match.get('link'):
                link = best_match['link']
        return link

    def resolve_uncached_source(self, source, runinbackground, runinforground, pack_select):
        heading = f'{control.ADDON_NAME}: Cache Resolver'
        if runinforground:
            control.progressDialog.create(heading, "Caching Progress")
        stream_link = None
        magnet = source['magnet']
        magnet_data = self.addMagnet(magnet)
        if not magnet_data or 'id' not in magnet_data:
            control.log('Premiumize addMagnet failed - no valid response', 'warning')
            if runinforground:
                control.progressDialog.close()
            return None
        transfer_id = magnet_data['id']
        transfer_status = self.transfer_list()
        if not transfer_status:
            if runinforground:
                control.progressDialog.close()
            return None
        status_item = next((item for item in transfer_status if item['id'] == transfer_id), None)
        if not status_item:
            if runinforground:
                control.progressDialog.close()
            return None
        status = status_item['status']

        if runinbackground:
            control.notify(heading, "The source is downloading to your cloud")
            return

        progress = 0
        while status not in ['finished', 'error']:
            if runinforground and (control.progressDialog.iscanceled() or control.wait_for_abort(5)):
                break
            transfer_status = self.transfer_list()
            if not transfer_status:
                status = 'error'
                break
            status_item = next((item for item in transfer_status if item['id'] == transfer_id), None)
            if not status_item:
                status = 'error'
                break
            status = status_item.get('status', 'error')
            progress = status_item.get('progress', 0)
            if progress is not None:
                progress *= 100
            else:
                progress = 100 if status == 'finished' else 0
            if runinforground:
                f_body = (f"Status: {status}[CR]"
                          f"Progress: {round(progress, 2)} %")
                control.progressDialog.update(int(progress), f_body)

        if status == 'finished':
            self.manage_storage_space()
            control.ok_dialog(heading, "This file has been added to your Cloud")
            dd_result = self.direct_download(magnet)
            if not dd_result or 'content' not in dd_result:
                self.delete_torrent(transfer_id)
                if runinforground:
                    control.progressDialog.close()
                return None
            folder_details = dd_result['content']
            folder_details = sorted(folder_details, key=lambda i: int(i['size']), reverse=True)
            folder_details = [i for i in folder_details if source_utils.is_file_ext_valid(i.get('path') or i.get('link', ''))]
            filter_list = [i for i in folder_details]

            if pack_select:
                identified_file = source_utils.get_best_match('path', folder_details, source['episode_re'], pack_select)
                stream_link = identified_file.get('link') if identified_file else None
            elif len(filter_list) == 1:
                stream_link = filter_list[0]['link']
            elif len(filter_list) > 1:
                identified_file = source_utils.get_best_match('path', folder_details, source['episode_re'])
                stream_link = identified_file.get('link') if identified_file else None
                if not stream_link:
                    if identified_file and identified_file.get('path') == '' and 'link' not in identified_file:
                        if runinforground:
                            control.progressDialog.close()
                        return None
                    samples_filtered = [tfile for tfile in folder_details if 'sample' not in tfile.get('path', '').lower()]
                    if samples_filtered:
                        stream_link = samples_filtered[0]['link']
            else:
                samples_filtered = [tfile for tfile in folder_details if 'sample' not in tfile.get('path', '').lower()]
                if samples_filtered:
                    stream_link = samples_filtered[0]['link']

            if stream_link and self.addtocloud:
                self.add_to_cloud(stream_link)
        else:
            self.delete_torrent(transfer_id)
        if runinforground:
            control.progressDialog.close()
        return stream_link
