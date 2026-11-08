"""
client.py - Otaku HTTP Client Layer
====================================
Full-featured HTTP client with keep-alive pooling, session management,
Cloudflare/DDoS-Guard bypass, and a requests-compatible Response API.

Architecture
------------
Session Mgmt     - Cookie/opener caching per domain with auto cleanup
User Agents      - Cached random desktop/mobile UA strings
Response         - Requests-like Response object (text, json, status_code)
HTTP Verbs       - get / post / put / patch / delete / head / session_request
Legacy Request   - Full-featured urllib request() with CF/DDG bypass
Challenge Bypass - cfcookie / ddgcookie via FlareSolverr
Helpers          - store / retrieve / byteify / strip_cookie_url
"""

# -*- coding: utf-8 -*-

import gzip
import http.client
import io
import json
import os
import random
import re
import socket
import ssl
import sys
import threading
import time
import urllib.request
import urllib.parse
import urllib.error
import urllib.response
import http.cookiejar
import xbmcvfs

from resources.lib.ui import control


# ═══════════════════════════════════════════════════════════════════════════
#  Constants & Session State
# ═══════════════════════════════════════════════════════════════════════════

TRANSLATEPATH = xbmcvfs.translatePath
CERT_FILE = TRANSLATEPATH('special://xbmc/system/certs/cacert.pem')
_COOKIE_HEADER = "Cookie"
_HEADER_RE = re.compile(r"^([\w\d-]+?)=(.*?)$")

# Enforce a global default socket timeout so hung DNS/sockets never freeze worker threads indefinitely
try:
    if socket.getdefaulttimeout() is None or socket.getdefaulttimeout() > 15.0:
        socket.setdefaulttimeout(15.0)
except Exception:
    pass

class _SessionOpenerDict(dict):
    """Dict keyed by (domain, bool(verify)) with backward-compatible domain string lookup."""

    def get(self, key, default=None):
        if key in self:
            return super().get(key, default)
        if isinstance(key, str):
            return super().get((key, True), super().get((key, False), default))
        return default


_session_lock = threading.Lock()
_session_cookies = {}
_session_openers = _SessionOpenerDict()
_session_timestamps = {}
_SESSION_TIMEOUT = 600  # 10 minutes

_cached_useragent = None
_cached_useragent_time = 0
_cached_mobile_useragent = None
_cached_mobile_useragent_time = 0
_USERAGENT_CACHE_TTL = 3600  # 1 hour

# Amortize session cleanup on a fixed interval instead of per-request random checks.
_request_count = 0
_CLEANUP_EVERY_N_REQUESTS = 128

_VERIFIED_SSL_CONTEXT = None
_UNVERIFIED_SSL_CONTEXT = None


def _validate_url_scheme(url: str) -> str:
    """Validate that the URL has an allowed HTTP/HTTPS scheme to prevent SSRF and LFI."""
    if not url or not isinstance(url, str):
        raise ValueError("URL must be a non-empty string")
    url = url.strip()
    if url.startswith('//'):
        url = 'https:' + url
    parsed = urllib.parse.urlparse(url)
    scheme = parsed.scheme.lower()
    if scheme not in ('http', 'https'):
        raise ValueError(f"Unauthorized scheme '{scheme}'; only http and https are allowed")
    return url


def _get_ssl_context(verify=True):
    """Return a cached SSLContext for verified or unverified requests without mutating global ssl defaults."""
    global _VERIFIED_SSL_CONTEXT, _UNVERIFIED_SSL_CONTEXT
    if not verify:
        if _UNVERIFIED_SSL_CONTEXT is None:
            ctx = ssl._create_unverified_context()
            try:
                ctx.set_alpn_protocols(['http/1.1'])
            except (ssl.SSLError, NotImplementedError, AttributeError):
                pass
            _UNVERIFIED_SSL_CONTEXT = ctx
        return _UNVERIFIED_SSL_CONTEXT
    if _VERIFIED_SSL_CONTEXT is None:
        try:
            ctx = ssl.create_default_context(cafile=CERT_FILE)
        except (ssl.SSLError, OSError):
            ctx = ssl.create_default_context()
        try:
            ctx.set_alpn_protocols(['http/1.1'])
        except (ssl.SSLError, NotImplementedError, AttributeError):
            pass
        _VERIFIED_SSL_CONTEXT = ctx
    return _VERIFIED_SSL_CONTEXT


def _cleanup_old_sessions():
    """Clean up sessions older than timeout to prevent memory leaks"""
    current_time = time.time()
    with _session_lock:
        expired_keys = [k for k, v in list(_session_timestamps.items()) if current_time - v > _SESSION_TIMEOUT]
        for key in expired_keys:
            domain_key = key[0] if isinstance(key, tuple) else key
            _session_cookies.pop(domain_key, None)
            _session_openers.pop(key, None)
            _session_timestamps.pop(key, None)


def _get_cached_useragent(mobile=False):
    """Get cached user agent from memory to avoid database lookups"""
    import time
    global _cached_useragent, _cached_useragent_time, _cached_mobile_useragent, _cached_mobile_useragent_time

    current_time = time.time()

    # Check in-memory cache
    if mobile:
        if _cached_mobile_useragent and (current_time - _cached_mobile_useragent_time < _USERAGENT_CACHE_TTL):
            return _cached_mobile_useragent
    else:
        if _cached_useragent and (current_time - _cached_useragent_time < _USERAGENT_CACHE_TTL):
            return _cached_useragent

    # Generate new user agent and cache in memory
    agent = randommobileagent() if mobile else randomagent()

    if mobile:
        _cached_mobile_useragent = agent
        _cached_mobile_useragent_time = current_time
    else:
        _cached_useragent = agent
        _cached_useragent_time = current_time

    return agent


# ═══════════════════════════════════════════════════════════════════════════
#  Response - Requests-Compatible Response Object
# ═══════════════════════════════════════════════════════════════════════════

_JSON_RAISE = object()


class Response:
    """
    Requests-like Response object to match requests module API

    Attributes:
        text: Response content as string
        content: Response content as bytes
        status_code: HTTP status code
        headers: Response headers dict
        url: Final URL after redirects
        cookies: Response cookies dict
        ok: True if status_code < 400
    """
    def __init__(self, content, status_code=200, headers=None, url='', cookies=None, is_binary=False):
        self._raw_content = content
        self._is_binary = is_binary
        self.status_code = status_code
        self.headers = headers or {}
        self.url = url
        self.cookies = cookies or {}
        self.ok = 200 <= status_code < 400

    @property
    def text(self):
        """Response content as string"""
        if isinstance(self._raw_content, bytes):
            try:
                return self._raw_content.decode('utf-8', errors='ignore')
            except UnicodeDecodeError:
                return self._raw_content.decode('latin-1', errors='ignore')
        return self._raw_content or ''

    @property
    def content(self):
        """Response content as bytes"""
        if isinstance(self._raw_content, str):
            return self._raw_content.encode('utf-8', errors='ignore')
        return self._raw_content or b''

    def json(self, default=_JSON_RAISE):
        """Parse response content as JSON with optional default fallback."""
        if not self.text:
            return {} if default is _JSON_RAISE else default
        sentinel = object()
        parsed = control.loads_json(self.text, default=sentinel)
        if parsed is sentinel:
            if default is not _JSON_RAISE:
                return default
            raise ValueError("Invalid JSON response")
        return parsed

    def __bool__(self):
        """Allow truthiness check like: if response:"""
        return self._raw_content is not None and self.ok

    def __repr__(self):
        return f"<Response [{self.status_code}]>"


# ═══════════════════════════════════════════════════════════════════════════
#  Legacy Request - Full-Featured urllib with CF/DDG Bypass
# ═══════════════════════════════════════════════════════════════════════════

def request(
        url,
        close=True,
        redirect=True,
        error=False,
        verify=True,
        proxy=None,
        post=None,
        headers=None,
        mobile=False,
        XHR=False,
        limit=None,
        referer='',
        cookie=None,
        compression=True,
        output='',
        timeout=10,
        jpost=False,
        params=None,
        method='',
        use_session=False,
        tls_version=None
):
    try:
        if not url:
            return

        try:
            url = _validate_url_scheme(url)
        except ValueError as e:
            control.log(f"client.request blocked URL: {e}", level='warning')
            return None

        global _request_count
        _request_count += 1
        if _request_count % _CLEANUP_EVERY_N_REQUESTS == 0:
            _cleanup_old_sessions()

        # Initialize response to None to avoid UnboundLocalError
        response = None

        _headers = {}
        if headers:
            _headers.update(headers)
        if _headers.get('verifypeer', '') == 'false':
            verify = False
            _headers.pop('verifypeer')

        # Global SSL verification toggle override
        if verify is True and not control.getBool('general.verify_ssl', default=True):
            verify = False

        # Parse domain for session management
        uri = urllib.parse.urlparse(url)
        domain = uri.scheme + '://' + uri.netloc
        # system_proxy = urllib.request.getproxies()

        handlers = []

        if proxy is not None:
            handlers += [urllib.request.ProxyHandler(
                {'http': '%s' % proxy}), urllib.request.HTTPHandler]

        if params is not None:
            if isinstance(params, dict):
                params = urllib.parse.urlencode(params, doseq=True)
            url = url + '?' + params

        if output == 'cookie' or output == 'extended' or not close:
            cookies = http.cookiejar.LWPCookieJar()
            handlers += [urllib.request.HTTPHandler(),
                         urllib.request.HTTPCookieProcessor(cookies)]

        start_time = (time.time() * 1000) if output == 'elapsed' else 0.0

        # Enhanced SSL/TLS handling with multiple protocol support (WNT2-style)
        ssl_context_created = False

        # TLS version override for Cloudflare bypass (like WNT2's TLS adapters)
        if tls_version:
            try:
                if tls_version == 'TLSv1_1':
                    ssl_context = ssl.SSLContext(ssl.PROTOCOL_TLSv1_1)
                elif tls_version == 'TLSv1_2':
                    ssl_context = ssl.SSLContext(ssl.PROTOCOL_TLSv1_2)
                else:
                    ssl_context = ssl.SSLContext(ssl.PROTOCOL_TLS)

                ssl_context.check_hostname = False if not verify else True
                ssl_context.verify_mode = ssl.CERT_NONE if not verify else ssl.CERT_REQUIRED
                ssl_context.set_alpn_protocols(['http/1.1'])
                handlers += [urllib.request.HTTPSHandler(context=ssl_context)]
                ssl_context_created = True
                control.log(f"Using TLS version: {tls_version}")
            except Exception as e:
                control.log(f"TLS override failed: {str(e)}")

        if not ssl_context_created:
            try:
                ssl_context = _get_ssl_context(verify=bool(verify))
                handlers += [urllib.request.HTTPSHandler(context=ssl_context)]
                ssl_context_created = True
            except (ssl.SSLError, OSError) as e:
                control.log(f"client HTTPSHandler init error: {e}", 'debug')

        if redirect is False:
            class NoRedirectHandler(urllib.request.HTTPRedirectHandler):
                def http_error_302(self, req, fp, code, msg, headers):
                    infourl = urllib.response.addinfourl(fp, headers, req.full_url)
                    if sys.version_info < (3, 9, 0):
                        infourl.status = code
                        infourl.code = code
                    return infourl
                http_error_300 = http_error_302
                http_error_301 = http_error_302
                http_error_303 = http_error_302
                http_error_307 = http_error_302

            handlers += [NoRedirectHandler()]

        # Reuse existing session opener for domain when eligible, otherwise build a new local opener
        can_use_session_opener = (use_session and redirect is not False and proxy is None and not tls_version)
        session_key = (domain, bool(verify))
        opener = None
        if can_use_session_opener:
            with _session_lock:
                opener = _session_openers.get(session_key)
                if opener is not None:
                    _session_timestamps[session_key] = time.time()
                    for h in getattr(opener, 'handlers', ()):
                        if isinstance(h, urllib.request.HTTPCookieProcessor):
                            cookies = h.cookiejar
                            break
        if opener is None:
            opener = urllib.request.build_opener(*handlers) if handlers else urllib.request.build_opener()
            if can_use_session_opener:
                with _session_lock:
                    _session_openers[session_key] = opener
                    _session_timestamps[session_key] = time.time()

        if url.startswith('//'):
            url = 'http:' + url

        if 'User-Agent' in _headers:
            pass
        elif mobile:
            _headers['User-Agent'] = _get_cached_useragent(mobile=True)
        else:
            _headers['User-Agent'] = _get_cached_useragent(mobile=False)

        if 'Referer' in _headers:
            pass
        elif referer:
            _headers['Referer'] = referer

        if 'Accept-Language' not in _headers:
            _headers['Accept-Language'] = 'en-US,en'

        if 'Accept' not in _headers:
            _headers['Accept'] = '*/*'

        if 'Connection' not in _headers:
            if can_use_session_opener or not close:
                _headers['Connection'] = 'keep-alive'

        if 'X-Requested-With' in _headers:
            pass
        elif XHR:
            _headers['X-Requested-With'] = 'XMLHttpRequest'

        if 'Cookie' in _headers:
            pass
        elif cookie:
            if isinstance(cookie, dict):
                cookie = '; '.join(['{0}={1}'.format(x, y) for x, y in cookie.items()])
            if cookie:
                _headers['Cookie'] = cookie
        else:
            # Check for session cookies first
            session_cookie = None
            if use_session:
                with _session_lock:
                    session_cookie = _session_cookies.get(domain)
            if session_cookie:
                _headers['Cookie'] = session_cookie
            else:
                cpath = os.path.basename(urllib.parse.urlparse(url).netloc)
                txt_path = os.path.join(control.dataPath, cpath + '.txt')
                json_path = os.path.join(control.dataPath, cpath + '.json')
                if control.pathExists(txt_path):
                    ccookie = retrieve(cpath + '.txt')
                    if ccookie:
                        _headers['Cookie'] = ccookie
                elif control.pathExists(json_path):
                    raw_json = retrieve(cpath + '.json')
                    if raw_json:
                        cfhdrs = control.loads_json(raw_json, default={})
                        if isinstance(cfhdrs, dict):
                            _headers.update(cfhdrs)

        if 'Accept-Encoding' in _headers:
            pass
        elif compression and limit is None:
            _headers['Accept-Encoding'] = 'gzip'

        url = byteify(url.replace(' ', '%20'))
        req = urllib.request.Request(url)

        if post is not None:
            if jpost:
                post = json.dumps(post)
                post = post.encode('utf8')
                req = urllib.request.Request(url, post)
                req.add_header('Content-Type', 'application/json')
            else:
                if isinstance(post, (dict, list, tuple)):
                    post = byteify(post)
                    post = urllib.parse.urlencode(post, doseq=True)
                if len(post) > 0:
                    post = post.encode('utf8')
                    req = urllib.request.Request(url, data=post)
                else:
                    req.get_method = lambda: 'POST'
                    req.has_header = lambda header_name: (
                        header_name == 'Content-type'
                        or urllib.request.Request.has_header(req, header_name)
                    )

        if limit == '0':
            req.get_method = lambda: 'HEAD'

        if method:
            req.get_method = lambda: method

        _add_request_header(req, _headers)

        try:
            # Use local/session opener so concurrent threads never clobber global urllib state
            req_timeout = float(timeout) if timeout is not None else 15.0
            response = opener.open(req, timeout=req_timeout)
        except urllib.error.HTTPError as e:
            if error is True:
                response = e
            server = e.info().get('Server')
            if server and 'cloudflare' in server.lower():
                if e.info().get('Content-Encoding', '').lower() == 'gzip':
                    buf = io.BytesIO(e.read())
                    f = gzip.GzipFile(fileobj=buf)
                    result = f.read()
                    f.close()
                else:
                    result = e.read()
                result = result.decode('utf-8', errors='ignore')
                error_code = e.code

                if _is_cf_hard_waf_block(result):
                    url_parsed = urllib.parse.urlparse(url)
                    netloc = '%s://%s/' % (url_parsed.scheme, url_parsed.netloc)
                    control.log('%s returned a hard Cloudflare WAF IP/ASN block; skipping FlareSolverr.' % netloc)
                    if output == 'extended':
                        try:
                            err_headers = dict([(item[0].title(), item[1]) for item in list(e.info().items())])
                        except Exception:
                            err_headers = {}
                        return (result, str(error_code), err_headers, _headers, '', getattr(e, 'url', url))
                    if error is True:
                        return result
                    return None

                # Enhanced Cloudflare 403 handling with single TLS 1.2 retry (guarded by `not tls_version` to prevent recursion)
                elif error_code == 403 and 'cf-alert-error' in result and not tls_version:
                    control.log(f"Cloudflare 403 detected for {url}, trying TLS 1.2 bypass")
                    for tls_ver in ('TLSv1_2',):
                        try:
                            control.log(f"Attempting {tls_ver} bypass")
                            retry_response = request(
                                url,
                                close=close,
                                redirect=redirect,
                                error=error,
                                verify=verify,
                                post=post,
                                headers=_headers,
                                timeout=timeout,
                                output=output,
                                tls_version=tls_ver,
                                use_session=use_session
                            )
                            if retry_response:
                                if output == 'extended' and isinstance(retry_response, tuple) and len(retry_response) >= 2:
                                    try:
                                        if int(retry_response[1]) >= 400:
                                            continue
                                    except (ValueError, TypeError):
                                        pass
                                control.log(f"{tls_ver} bypass successful")
                                return retry_response
                        except Exception as retry_error:
                            control.log(f"{tls_ver} bypass failed: {str(retry_error)}")
                            continue

                    control.log("All TLS bypass attempts failed")
                    if output == 'extended':
                        try:
                            err_headers = dict([(item[0].title(), item[1]) for item in list(e.info().items())])
                        except Exception:
                            err_headers = {}
                        return (result, str(error_code), err_headers, _headers, '', getattr(e, 'url', url))
                    if not error:
                        return None

                elif _is_cf_solvable_challenge(error_code, e.info(), result):
                    url_parsed = urllib.parse.urlparse(url)
                    netloc = '%s://%s/' % (url_parsed.scheme, url_parsed.netloc)
                    if control.getBool('fs_enable'):
                        cf_solver = cfcookie()
                        can_direct_solve = (post is None) or (not jpost)
                        solved = cf_solver.solve_request(url, timeout, post=post if can_direct_solve else None) if can_direct_solve else None
                        if solved and solved.get('status', 500) < 400 and solved.get('body') is not None:
                            if use_session and solved.get('cookie'):
                                with _session_lock:
                                    _session_cookies['%s://%s' % (url_parsed.scheme, url_parsed.netloc)] = solved['cookie']
                            return _format_solved_response(solved, _headers, output, start_time)

                        cf_cookie, cf_ua = (cf_solver.cookie, cf_solver.ua) if can_direct_solve else cf_solver.get(netloc, timeout)
                        if cf_cookie is None:
                            control.log('%s has an unsolvable Cloudflare challenge.' % (netloc))
                            if output == 'extended':
                                try:
                                    err_headers = dict([(item[0].title(), item[1]) for item in list(e.info().items())])
                                except Exception:
                                    err_headers = {}
                                return (result, str(error_code), err_headers, _headers, '', getattr(e, 'url', url))
                            if not error:
                                return None
                        if cf_cookie:
                            _headers['Cookie'] = cf_cookie
                        if cf_ua:
                            _headers['User-Agent'] = cf_ua
                        req = urllib.request.Request(url, data=post)
                        _add_request_header(req, _headers)
                        response = opener.open(req, timeout=float(timeout) if timeout is not None else 15.0)
                    else:
                        control.log('%s has a Cloudflare challenge.' % (netloc))
                        if output == 'extended':
                            try:
                                err_headers = dict([(item[0].title(), item[1]) for item in list(e.info().items())])
                            except Exception:
                                err_headers = {}
                            return (result, str(error_code), err_headers, _headers, '', getattr(e, 'url', url))
                        if not error:
                            return None
                else:
                    if output == 'extended':
                        try:
                            err_headers = dict([(item[0].title(), item[1]) for item in list(e.info().items())])
                        except Exception:
                            err_headers = {}
                        return (result, str(error_code), err_headers, _headers, '', getattr(e, 'url', url))
                    if error is True:
                        return result
                    else:
                        return None
            elif server and 'ddos-guard' in server.lower() and e.code in (403, 429, 503):
                url_parsed = urllib.parse.urlparse(url)
                netloc = '%s://%s/' % (url_parsed.scheme, url_parsed.netloc)
                if control.getBool('fs_enable'):
                    ddg_solver = ddgcookie()
                    can_direct_solve = (post is None) or (not jpost)
                    solved = ddg_solver.solve_request(url, timeout, post=post if can_direct_solve else None) if can_direct_solve else None
                    if solved and solved.get('status', 500) < 400 and solved.get('body') is not None:
                        if use_session and solved.get('cookie'):
                            with _session_lock:
                                _session_cookies['%s://%s' % (url_parsed.scheme, url_parsed.netloc)] = solved['cookie']
                        return _format_solved_response(solved, _headers, output, start_time)

                    ddg_cookie, ddg_ua = (ddg_solver.cookie, ddg_solver.ua) if can_direct_solve else ddg_solver.get(netloc, timeout)
                    if ddg_cookie is None:
                        control.log('%s has an unsolvable DDos-Guard challenge.' % (netloc))
                        if not error:
                            return None
                    if ddg_cookie:
                        _headers['Cookie'] = ddg_cookie
                    if ddg_ua:
                        _headers['User-Agent'] = ddg_ua
                    req = urllib.request.Request(url, data=post)
                    _add_request_header(req, _headers)
                    response = opener.open(req, timeout=float(timeout) if timeout is not None else 15.0)
                else:
                    control.log('%s has a DDoS-Guard challenge.' % (netloc))
                    if not error:
                        return None
            elif output == 'extended':
                response = e
            elif output == '':
                control.log('Request-HTTPError (%s): %s' % (e.code, url))
                if not error:
                    return None
        except urllib.error.URLError as e:
            if output == '':
                control.log('Request-Error (%s): %s' % (e.reason, url))
            if not error:
                return None
            else:
                # For error=True, return the error for extended output
                response = e

        # Safety check: if response is still None, return None
        if response is None:
            return None

        if output == 'cookie':
            try:
                result = '; '.join(['%s=%s' % (i.name, i.value)
                                    for i in cookies])
            except (AttributeError, TypeError, KeyError) as e:
                control.log(f"client cookie parse error: {e}", 'debug')
            if close:
                response.close()
            return result

        elif output == 'elapsed':
            result = (time.time() * 1000) - start_time
            if close:
                response.close()
            return int(result)

        elif output == 'geturl':
            result = response.url
            if close:
                response.close()
            return result

        elif output == 'headers':
            result = response.headers
            if close:
                response.close()
            return result

        elif output == 'status_code':
            result = response.code
            if close:
                response.close()
            return result

        elif output == 'chunk':
            try:
                content = int(response.headers['Content-Length'])
            except Exception:
                content = (2049 * 1024)
            if content < (2048 * 1024):
                return
            result = response.read(16 * 1024)
            if close:
                response.close()
            return result

        elif output == 'file_size':
            try:
                content = int(response.headers['Content-Length'])
            except Exception:
                content = '0'
            response.close()
            return content

        if limit == '0' or limit == 0:
            result = response.read(1 * 1024)
        elif limit is not None:
            result = response.read(int(limit) * 1024)
        else:
            try:
                result = response.read()
            except http.client.IncompleteRead as e:
                control.log(f'IncompleteRead: Got {len(e.partial)} bytes from {url}', 'warning')
                result = e.partial
                if not result:
                    return None

        encoding = None
        text_content = False

        if response.headers.get('content-encoding', '').lower() == 'gzip':
            result = gzip.GzipFile(fileobj=io.BytesIO(result)).read()

        content_type = response.headers.get('content-type', '').lower()

        text_content = any(x in content_type for x in ['text', 'json', 'xml', 'mpegurl'])

        if 'charset=' in content_type:
            encoding = content_type.split('charset=')[-1].split(';')[0].strip().strip('"\'')

        if 'text/vtt' in content_type or url.endswith('.srt') or url.endswith('.vtt'):
            encoding = 'utf8'

        if encoding is None:
            epatterns = [r'<meta\s+http-equiv="Content-Type"\s+content="(?:.+?);\s+charset=(.+?)"',
                         r'xml\s*version.+encoding="([^"]+)']
            for epattern in epatterns:
                epattern = epattern.encode('utf8')
                r = re.search(epattern, result, re.IGNORECASE)
                if r:
                    encoding = r.group(1).decode('utf8')
                    break

        if encoding is None:
            r = re.search(b'^#EXT', result, re.IGNORECASE)
            if r:
                encoding = 'utf8'
        if encoding is not None:
            result = result.decode(encoding, errors='ignore')
            text_content = True
        elif text_content and encoding is None:
            # Try UTF-8 first (for modern APIs: JSON/XML from MAL, AniList, etc.)
            # Fall back to latin-1 if UTF-8 fails (for legacy content)
            # This fixes mojibake for Unicode chars like ×, -, …, accented letters, etc.
            try:
                result = result.decode('utf-8')
            except UnicodeDecodeError:
                result = result.decode('latin-1', errors='ignore')
        else:
            control.log('Unknown Page Encoding')

        if isinstance(result, str) and _is_ddg_challenge(
            getattr(response, 'code', 200),
            response.headers.get('Server', ''),
            result,
        ):
            url_parsed = urllib.parse.urlparse(url)
            if control.getBool('fs_enable') and ((post is None) or (not jpost)):
                solved = ddgcookie().solve_request(url, timeout, post=post)
                if solved and solved.get('status', 500) < 400 and solved.get('body') is not None:
                    if close:
                        response.close()
                    if use_session and solved.get('cookie'):
                        with _session_lock:
                            _session_cookies['%s://%s' % (url_parsed.scheme, url_parsed.netloc)] = solved['cookie']
                    return _format_solved_response(solved, _headers, output, start_time)

        if output == 'extended':
            try:
                response_headers = dict(
                    [(item[0].title(), item[1]) for item in list(response.info().items())])
            except Exception:
                response_headers = response.headers
            response_url = response.url
            response_code = str(response.code)
            try:
                cookie = '; '.join(['%s=%s' % (i.name, i.value)
                                    for i in cookies])
            except (AttributeError, TypeError, KeyError) as e:
                control.log(f"client response cookie parse error: {e}", 'debug')

            if close:
                response.close()
            return (result, response_code, response_headers, _headers, cookie, response_url)
        else:
            if close:
                response.close()
            return result
    except Exception as e:
        control.log('Request-Error: (%s) => %s' % (str(e), url))
        return


# ═══════════════════════════════════════════════════════════════════════════
#  HTTP Verbs - Requests-Compatible API
# ═══════════════════════════════════════════════════════════════════════════

def _build_response(result, url):
    """Convert a raw request() result tuple into a Response object."""
    if result and isinstance(result, tuple) and len(result) >= 5:
        content, status_code, response_headers, _req_headers, cookie, response_url = result
        content_type = response_headers.get('Content-Type', '').lower()
        is_binary = not any(x in content_type for x in ['text', 'json', 'xml', 'html', 'javascript'])
        cookie_dict = {}
        if cookie:
            for item in cookie.split('; '):
                if '=' in item:
                    key, val = item.split('=', 1)
                    cookie_dict[key] = val
        return Response(
            content=content,
            status_code=int(status_code) if status_code else 200,
            headers=response_headers,
            url=response_url or url,
            cookies=cookie_dict,
            is_binary=is_binary
        )
    if result:
        return Response(content=result, status_code=200, url=url)
    return Response(content=None, status_code=0, url=url)


def get(url, headers=None, timeout=10, verify=True, cookies=None, params=None, redirect=True):
    """Requests-like GET.  Returns a Response object."""
    result = request(url, headers=headers or {}, timeout=timeout, verify=verify,
                     cookie=cookies, params=params, redirect=redirect,
                     output='extended', use_session=True)
    return _build_response(result, url)


def post(url, data=None, json_data=None, headers=None, timeout=10, verify=True, cookies=None):
    """Requests-like POST.  Returns a Response object."""
    if json_data:
        result = request(url, post=json_data, jpost=True, headers=headers or {},
                         timeout=timeout, verify=verify, cookie=cookies,
                         output='extended', use_session=True)
    else:
        result = request(url, post=data, headers=headers or {}, timeout=timeout,
                         verify=verify, cookie=cookies, output='extended', use_session=True)
    return _build_response(result, url)


def put(url, data=None, json_data=None, headers=None, timeout=10, verify=True, cookies=None):
    """Requests-like PUT.  Returns a Response object."""
    if json_data:
        result = request(url, post=json_data, jpost=True, method='PUT', headers=headers or {},
                         timeout=timeout, verify=verify, cookie=cookies,
                         output='extended', use_session=True)
    else:
        result = request(url, post=data, method='PUT', headers=headers or {},
                         timeout=timeout, verify=verify, cookie=cookies,
                         output='extended', use_session=True)
    return _build_response(result, url)


def patch(url, data=None, json_data=None, headers=None, timeout=10, verify=True, cookies=None):
    """Requests-like PATCH.  Returns a Response object."""
    if json_data:
        result = request(url, post=json_data, jpost=True, method='PATCH', headers=headers or {},
                         timeout=timeout, verify=verify, cookie=cookies,
                         output='extended', use_session=True)
    else:
        result = request(url, post=data, method='PATCH', headers=headers or {},
                         timeout=timeout, verify=verify, cookie=cookies,
                         output='extended', use_session=True)
    return _build_response(result, url)


def delete(url, data=None, json_data=None, headers=None, timeout=10, verify=True, cookies=None):
    """Requests-like DELETE.  Returns a Response object."""
    if json_data:
        result = request(url, post=json_data, jpost=True, method='DELETE', headers=headers or {},
                         timeout=timeout, verify=verify, cookie=cookies,
                         output='extended', use_session=True)
    elif data:
        result = request(url, post=data, method='DELETE', headers=headers or {},
                         timeout=timeout, verify=verify, cookie=cookies,
                         output='extended', use_session=True)
    else:
        result = request(url, method='DELETE', headers=headers or {}, timeout=timeout,
                         verify=verify, cookie=cookies, output='extended', use_session=True)
    return _build_response(result, url)


def head(url, headers=None, timeout=10, verify=True, cookies=None, params=None):
    """Requests-like HEAD (headers only, no body).  Returns a Response object."""
    result = request(url, headers=headers or {}, timeout=timeout, verify=verify,
                     cookie=cookies, params=params, limit='0',
                     output='extended', use_session=True)
    resp = _build_response(result, url)
    resp._raw_content = ''  # HEAD has no body
    return resp


def session_request(url, method='GET', data=None, headers=None, timeout=10, verify=True):
    """
    Session-based request that maintains cookies across calls (like requests.Session)

    Usage:
        # Cookies will be automatically stored and reused for the same domain
        response1 = client.session_request('https://example.com/login', method='POST', data={'user': 'test'})
        response2 = client.session_request('https://example.com/protected')  # Uses cookies from first request
    """
    uri = urllib.parse.urlparse(url)
    domain = uri.scheme + '://' + uri.netloc

    # Make request with session support
    if method.upper() == 'POST':
        result = request(url, post=data, headers=headers or {}, timeout=timeout, verify=verify, use_session=True, output='extended')
    else:
        result = request(url, headers=headers or {}, timeout=timeout, verify=verify, use_session=True, output='extended')

    if result and isinstance(result, tuple) and len(result) >= 5:
        content, response_code, response_headers, request_headers, cookie, response_url = result
        # Store cookies for this domain
        if cookie:
            with _session_lock:
                _session_cookies[domain] = cookie
        return content
    elif result:
        return result

    return None


def clear_session():
    """Clear all session cookies and openers"""
    with _session_lock:
        _session_cookies.clear()
        _session_openers.clear()
        _session_timestamps.clear()
    clear_fs_fail_cache()
    control.log("Session cache cleared")


# ═══════════════════════════════════════════════════════════════════════════
#  Session Class - Persistent Cookie Management
# ═══════════════════════════════════════════════════════════════════════════

class Session:
    """
    Requests-like Session class for persistent cookies and settings

    Usage:
        session = client.Session()
        response = session.get('https://example.com')
        response = session.post('https://example.com/login', data={'user': 'test'})
        session.close()
    """
    def __init__(self):
        self.cookies = {}
        self.headers = {}
        self._domain_cookies = {}

    def _request(self, url, method='GET', data=None, json_data=None, headers=None, timeout=10, verify=True):
        """Internal: execute a request, store cookies, return Response."""
        merged_headers = self.headers.copy()
        if headers:
            merged_headers.update(headers)

        domain = urllib.parse.urlparse(url).netloc
        cookie_str = None
        if domain in self._domain_cookies:
            cookie_str = '; '.join([f'{k}={v}' for k, v in self._domain_cookies[domain].items()])

        kwargs = dict(headers=merged_headers, timeout=timeout, verify=verify,
                      cookie=cookie_str, use_session=False, output='extended')
        if method == 'POST':
            if json_data:
                kwargs.update(post=json_data, jpost=True)
            else:
                kwargs.update(post=data)

        result = request(url, **kwargs)

        # Store cookies from the response before building the Response object
        if result and isinstance(result, tuple) and len(result) >= 5:
            cookie = result[4]
            if cookie:
                if domain not in self._domain_cookies:
                    self._domain_cookies[domain] = {}
                for item in cookie.split('; '):
                    if '=' in item:
                        key, val = item.split('=', 1)
                        self._domain_cookies[domain][key] = val
                        self.cookies[key] = val

        resp = _build_response(result, url)
        resp.cookies = self._domain_cookies.get(domain, {})
        return resp

    def get(self, url, headers=None, timeout=10, verify=True):
        """GET request with session cookies"""
        return self._request(url, 'GET', headers=headers, timeout=timeout, verify=verify)

    def post(self, url, data=None, json_data=None, headers=None, timeout=10, verify=True):
        """POST request with session cookies"""
        return self._request(url, 'POST', data=data, json_data=json_data,
                             headers=headers, timeout=timeout, verify=verify)

    def close(self):
        """Close the session and clear cookies"""
        self.cookies.clear()
        self._domain_cookies.clear()


# ═══════════════════════════════════════════════════════════════════════════
#  Low-Level Helpers
# ═══════════════════════════════════════════════════════════════════════════

def _basic_request(url, headers=None, post=None, timeout=60, jpost=False, limit=None):
    try:
        url = _validate_url_scheme(url)
        request = urllib.request.Request(url)
        if post is not None:
            if jpost:
                post = json.dumps(post)
                post = post.encode('utf8')
                request = urllib.request.Request(url, post)
                request.add_header('Content-Type', 'application/json')
            else:
                if isinstance(post, (dict, list, tuple)):
                    post = byteify(post)
                    post = urllib.parse.urlencode(post, doseq=True)
                if len(post) > 0:
                    post = post.encode('utf8')
                    request = urllib.request.Request(url, data=post)
                else:
                    request.get_method = lambda: 'POST'
                    request.has_header = lambda header_name: (
                        header_name == 'Content-type'
                        or urllib.request.Request.has_header(request, header_name)
                    )
        if headers is not None:
            _add_request_header(request, headers)
        req_timeout = float(timeout if timeout is not None else 60.0)
        response = urllib.request.urlopen(request, timeout=req_timeout)
        return _get_result(response, limit)
    except Exception:
        return


def _add_request_header(_request, headers):
    try:
        scheme = urllib.parse.urlparse(_request.get_full_url()).scheme
        host = _request.host

        referer = headers.get('Referer', '') or '%s://%s/' % (scheme, host)

        _request.add_unredirected_header('Host', host)
        _request.add_unredirected_header('Referer', referer)
        for key in headers:
            _request.add_header(key, headers[key])
    except Exception:
        return


def _get_result(response, limit=None):
    if limit == '0':
        result = response.read(224 * 1024)
    elif limit:
        result = response.read(int(limit) * 1024)
    else:
        result = response.read(5242880)

    try:
        encoding = response.headers.get('Content-Encoding')
    except Exception:
        encoding = None
    if encoding == 'gzip':
        result = gzip.GzipFile(fileobj=io.BytesIO(result)).read()

    return result


def randomagent():
    _agents = [
        'Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:109.0) Gecko/20100101 Firefox/117.0',
        'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/117.0.8464.47 Safari/537.36 OPR/117.0.8464.47',
        'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/116.0.0.0 Safari/537.36 Edg/116.0.1938.62',
        'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/118.0.0.0 Safari/537.36',
        'Mozilla/5.0 (Macintosh; Intel Mac OS X 17.1.2) AppleWebKit/800.6.25 (KHTML, like Gecko) Version/17.2 Safari/605.1.15',
        'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/116.0.0.0 Safari/537.36',
        'Mozilla/5.0 (Macintosh; Intel Mac OS X 10.15; rv:109.0) Gecko/20100101 Firefox/117.0',
        'Mozilla/5.0 (Macintosh; Intel Mac OS X 13_5_2) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/117.0.0.0 Safari/537.36 Vivaldi/6.2.3105.48',
        'Mozilla/5.0 (MacBook Air; M1 Mac OS X 11_4) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/14.1.1 Safari/604.1',
        'Mozilla/5.0 (X11; Ubuntu; Linux x86_64; rv:109.0) Gecko/20100101 Firefox/117.0',
        'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/113.0.0.0 Safari/537.36',
        'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.21 (KHTML, like Gecko) konqueror/4.14.26 Safari/537.21'
    ]
    return random.choice(_agents)


# — User Agents —

def randommobileagent():
    _mobagents = [
        'Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1',
        'Mozilla/5.0 (iPad; CPU OS 16_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/15.4 Mobile/15E148 Safari/604.1',
        'Mozilla/5.0 (iPhone; CPU iPhone OS 16_6 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) CriOS/116.0.5845.177 Mobile/15E148 Safari/604.1',
        'Mozilla/5.0 (Linux; Android 12; motorola edge (2022)) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/99.0.4844.88 Mobile Safari/537.36',
        'Mozilla/5.0 (Linux; Android 13; SAMSUNG SM-A546B) AppleWebKit/537.36 (KHTML, like Gecko) SamsungBrowser/22.0 Chrome/111.0.5563.116 Mobile Safari/537.3',
        'Mozilla/5.0 (Linux; Android 13; V2302A; wv) AppleWebKit/537.36 (KHTML, like Gecko) Version/4.0 Chrome/87.0.4280.141 Mobile Safari/537.36 VivoBrowser/14.5.10.2'
    ]
    return random.choice(_mobagents)


def agent():
    return 'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/113.0.0.0 Safari/537.36'


# — File storage —

def store(ftext, fname):
    safe_name = os.path.basename(fname)
    fpath = os.path.join(control.dataPath, safe_name)
    control.atomic_write_text(fpath, ftext)


def retrieve(fname):
    safe_name = os.path.basename(fname)
    fpath = os.path.join(control.dataPath, safe_name)
    if control.pathExists(fpath):
        try:
            with open(fpath, 'r', encoding='utf-8') as f:
                return f.read()
        except Exception as e:
            control.log(f"retrieve error for {safe_name}: {e}", 'warning')
            return None
    else:
        return None


# ═══════════════════════════════════════════════════════════════════════════
#  Challenge Bypass - Cloudflare & DDoS-Guard via FlareSolverr
# ═══════════════════════════════════════════════════════════════════════════

_FS_FAIL_CACHE = {}
_FS_FAIL_LOCK = threading.Lock()
_FS_FAIL_TTL = 600.0  # 10-minute per-host negative cache for unsolvable challenges


def clear_fs_fail_cache():
    """Clear cached FlareSolverr negative host cooldowns."""
    with _FS_FAIL_LOCK:
        _FS_FAIL_CACHE.clear()


def _is_fs_host_in_cooldown(url):
    host = urllib.parse.urlparse(url or '').netloc.lower()
    if not host:
        return False
    with _FS_FAIL_LOCK:
        ts = _FS_FAIL_CACHE.get(host)
        if ts is not None and (time.time() - ts) < _FS_FAIL_TTL:
            return True
        if ts is not None:
            _FS_FAIL_CACHE.pop(host, None)
    return False


def _record_fs_host_failure(url):
    host = urllib.parse.urlparse(url or '').netloc.lower()
    if host:
        with _FS_FAIL_LOCK:
            _FS_FAIL_CACHE[host] = time.time()


def _clear_fs_host_failure(url):
    host = urllib.parse.urlparse(url or '').netloc.lower()
    if host:
        with _FS_FAIL_LOCK:
            _FS_FAIL_CACHE.pop(host, None)


def _is_cf_hard_waf_block(body):
    """Detect unsolvable Cloudflare IP/ASN WAF blocks where FlareSolverr cannot help."""
    if not body or not isinstance(body, str):
        return False
    if 'Attention Required! | Cloudflare' in body:
        return True
    if 'Sorry, you have been blocked' in body and 'cf-error-details' in body:
        return True
    return False


def _is_cf_solvable_challenge(error_code, headers, body):
    """Detect solvable Cloudflare JS/Turnstile challenges including modern cf-mitigated headers."""
    if error_code not in (403, 429, 503):
        return False
    if _is_cf_hard_waf_block(body):
        return False
    try:
        cf_mitigated = (headers.get('cf-mitigated') or headers.get('Cf-Mitigated') or '') if headers else ''
    except Exception:
        cf_mitigated = ''
    if 'challenge' in cf_mitigated.lower():
        return True
    text = body if isinstance(body, str) else ''
    return any(
        marker in text
        for marker in (
            '__cf_chl_f_tk',
            '__cf_chl_jschl_tk__=',
            '/cdn-cgi/challenge-platform/',
            '<title>Just a moment...</title>',
            'Enable JavaScript and cookies to continue',
        )
    )


def _is_ddg_challenge(status_code, server, body):
    """Detect DDoS-Guard 403/503 blocks as well as HTTP 200 JS challenge interstitials."""
    text = body if isinstance(body, str) else ''
    srv = (server or '').lower()
    if 'ddos-guard' in srv and int(status_code or 0) in (403, 429, 503):
        return True
    if any(marker in text for marker in ('check.ddos-guard.net', '<title>DDoS-Guard</title>', '__ddg_mark_')):
        return True
    return False


def _format_solved_response(solved, req_headers, output, start_time):
    """Format a direct FlareSolverr solution dict into client.request()'s requested output shape."""
    body = solved.get('body', '')
    status = int(solved.get('status') or 200)
    raw_headers = solved.get('headers') if isinstance(solved.get('headers'), dict) else {}
    norm_headers = {str(k).title(): str(v) for k, v in raw_headers.items()}
    if 'Content-Type' not in norm_headers:
        norm_headers['Content-Type'] = 'text/html; charset=utf-8'
    cookie_str = solved.get('cookie', '')
    final_url = solved.get('url', '')

    if output == 'cookie':
        return cookie_str
    if output == 'elapsed':
        return int((time.time() * 1000) - start_time)
    if output == 'geturl':
        return final_url
    if output == 'headers':
        return norm_headers
    if output == 'status_code':
        return status
    if output == 'extended':
        return (body, str(status), norm_headers, req_headers, cookie_str, final_url)
    return body


def _execute_flaresolverr(target_url, timeout=None, post=None, return_only_cookies=False):
    """Execute a FlareSolverr v3 request with bounded timeout and per-host negative caching."""
    fs_url = (control.getSetting('fs_url') or '').strip()
    if not fs_url.startswith('http'):
        control.log('Sorry, malformed flaresolverr url')
        return None
    if _is_fs_host_in_cooldown(target_url):
        control.log('Skipping FlareSolverr for %s (host in failure cooldown).' % target_url)
        return None

    fs_setting_timeout = control.getInt('fs_timeout')
    effective_sec = fs_setting_timeout if fs_setting_timeout and fs_setting_timeout > 0 else 25
    effective_sec = min(max(int(effective_sec), 10), 30)

    if post is not None:
        post_str = post.decode('utf-8', errors='ignore') if isinstance(post, (bytes, bytearray)) else str(post)
        payload = {
            'cmd': 'request.post',
            'url': target_url,
            'postData': post_str,
            'returnOnlyCookies': bool(return_only_cookies),
            'maxTimeout': effective_sec * 1000,
        }
    else:
        payload = {
            'cmd': 'request.get',
            'url': target_url,
            'returnOnlyCookies': bool(return_only_cookies),
            'maxTimeout': effective_sec * 1000,
        }

    resp = _basic_request(fs_url, post=payload, timeout=float(effective_sec + 5.0), jpost=True)
    if not resp:
        _record_fs_host_failure(target_url)
        control.log('%s returned %s.' % (target_url, repr(resp)))
        return None

    parsed = control.loads_json(resp, default={})
    soln = parsed.get('solution') if isinstance(parsed, dict) and parsed.get('status') in ('ok', None) else None
    if not isinstance(soln, dict):
        _record_fs_host_failure(target_url)
        control.log('%s returned invalid response. Could not collect tokens.' % target_url)
        return None

    _clear_fs_host_failure(target_url)
    return soln


class cfcookie:
    def __init__(self):
        self.cookie = None
        self.ua = None
        self.last_solution = None

    def get(self, netloc, timeout):
        try:
            self.netloc = netloc
            self.timeout = timeout
            self._get_cookie(netloc, timeout)
            if self.cookie is not None:
                cfdata = json.dumps({'Cookie': self.cookie, 'User-Agent': self.ua})
                store(cfdata, urllib.parse.urlparse(netloc).netloc + '.json')
            return (self.cookie, self.ua)
        except Exception as e:
            control.log('%s returned an error. Could not collect tokens - Error: %s.' % (netloc, str(e)))
            return (self.cookie, self.ua)

    def solve_request(self, url, timeout=None, post=None):
        """Fetch target URL directly via FlareSolverr Chromium to avoid JA3/JA4 TLS fingerprint rejection."""
        try:
            soln = _execute_flaresolverr(url, timeout=timeout, post=post, return_only_cookies=False)
            if not soln:
                return None
            status = int(soln.get('status') or 500)
            cookies_raw = soln.get('cookies') if isinstance(soln.get('cookies'), list) else []
            cookie_str = '; '.join([
                '%s=%s' % (i.get('name'), i.get('value'))
                for i in cookies_raw
                if isinstance(i, dict) and i.get('name')
            ])
            ua_str = soln.get('userAgent')
            if status < 400 and cookie_str:
                self.cookie = cookie_str
                self.ua = ua_str
                host = urllib.parse.urlparse(url).netloc
                if host:
                    store(json.dumps({'Cookie': cookie_str, 'User-Agent': ua_str}), host + '.json')
            self.last_solution = {
                'body': soln.get('response'),
                'status': status,
                'headers': soln.get('headers') if isinstance(soln.get('headers'), dict) else {},
                'cookie': cookie_str,
                'ua': ua_str,
                'url': soln.get('url') or url,
            }
            return self.last_solution
        except Exception as e:
            control.log('FlareSolverr solve_request failed for %s: %s' % (url, str(e)))
            return None

    def _get_cookie(self, netloc, timeout):
        soln = _execute_flaresolverr(netloc, timeout=timeout, return_only_cookies=True)
        if not soln:
            return
        if int(soln.get('status') or 500) < 300:
            cookies_raw = soln.get('cookies') if isinstance(soln.get('cookies'), list) else []
            cookie = '; '.join([
                '%s=%s' % (i.get('name'), i.get('value'))
                for i in cookies_raw
                if isinstance(i, dict) and i.get('name')
            ])
            if 'cf_clearance' in cookie or '__cf_bm' in cookie:
                self.cookie = cookie
                self.ua = soln.get('userAgent')
            else:
                control.log('%s returned cookies without cf_clearance. Could not collect tokens.' % netloc)


class ddgcookie:
    def __init__(self):
        self.cookie = None
        self.ua = None
        self.last_solution = None

    def get(self, netloc, timeout):
        try:
            self.netloc = netloc
            self.timeout = timeout
            self._get_cookie(netloc, timeout)
            if self.cookie is not None:
                cfdata = json.dumps({'Cookie': self.cookie, 'User-Agent': self.ua})
                store(cfdata, urllib.parse.urlparse(netloc).netloc + '.json')
            return (self.cookie, self.ua)
        except Exception as e:
            control.log('%s returned an error. Could not collect tokens - Error: %s.' % (netloc, str(e)))
            return (self.cookie, self.ua)

    def solve_request(self, url, timeout=None, post=None):
        """Fetch DDoS-Guard target URL directly via FlareSolverr and persist modern __ddg* cookies."""
        try:
            soln = _execute_flaresolverr(url, timeout=timeout, post=post, return_only_cookies=False)
            if not soln:
                return None
            status = int(soln.get('status') or 500)
            cookies_raw = soln.get('cookies') if isinstance(soln.get('cookies'), list) else []
            ddg_pairs = [
                '%s=%s' % (i.get('name'), i.get('value'))
                for i in cookies_raw
                if isinstance(i, dict) and i.get('name') and 'ddg' in str(i.get('name')).lower()
            ]
            cookie_str = '; '.join(ddg_pairs) or '; '.join([
                '%s=%s' % (i.get('name'), i.get('value'))
                for i in cookies_raw
                if isinstance(i, dict) and i.get('name')
            ])
            ua_str = soln.get('userAgent')
            if status < 400 and cookie_str:
                self.cookie = cookie_str
                self.ua = ua_str
                host = urllib.parse.urlparse(url).netloc
                if host:
                    store(json.dumps({'Cookie': cookie_str, 'User-Agent': ua_str}), host + '.json')
            self.last_solution = {
                'body': soln.get('response'),
                'status': status,
                'headers': soln.get('headers') if isinstance(soln.get('headers'), dict) else {},
                'cookie': cookie_str,
                'ua': ua_str,
                'url': soln.get('url') or url,
            }
            return self.last_solution
        except Exception as e:
            control.log('FlareSolverr DDG solve_request failed for %s: %s' % (url, str(e)))
            return None

    def _get_cookie(self, netloc, timeout):
        soln = _execute_flaresolverr(netloc, timeout=timeout, return_only_cookies=True)
        if not soln:
            return
        if int(soln.get('status') or 500) < 300:
            cookies_raw = soln.get('cookies') if isinstance(soln.get('cookies'), list) else []
            cookie = '; '.join([
                '%s=%s' % (i.get('name'), i.get('value'))
                for i in cookies_raw
                if isinstance(i, dict) and i.get('name') and 'ddg' in str(i.get('name')).lower()
            ])
            if any(k in cookie for k in ('__ddg1_', '__ddg2_', '__ddg8_', '__ddg9_', '__ddg10_')) or '__ddg' in cookie:
                self.cookie = cookie
                self.ua = soln.get('userAgent')
            else:
                control.log('%s returned cookies without __ddg* tokens. Could not collect tokens.' % netloc)


# ═══════════════════════════════════════════════════════════════════════════
#  URL & Cookie Helpers
# ═══════════════════════════════════════════════════════════════════════════

def byteify(data, ignore_dicts=False):
    if isinstance(data, list):
        return [byteify(item, ignore_dicts=True) for item in data]
    if isinstance(data, dict) and not ignore_dicts:
        return dict([(byteify(key, ignore_dicts=True), byteify(
            value, ignore_dicts=True)) for key, value in data.items()])
    return data


def strip_cookie_url(url):
    url, headers = _strip_url(url)
    if _COOKIE_HEADER in headers.keys():
        del headers[_COOKIE_HEADER]

    return _url_with_headers(url, headers)


def _url_with_headers(url, headers):
    if not len(headers.keys()):
        return url

    headers_arr = [
        "%s=%s" % (key, urllib.parse.quote_plus(value))
        for key, value in headers.items()
    ]

    return "|".join([url] + headers_arr)


def _strip_url(url):
    if url.find('|') == -1:
        return (url, {})

    headers = url.split('|')
    target_url = headers.pop(0)
    out_headers = {}
    for h in headers:
        m = _HEADER_RE.findall(h)
        if not len(m):
            continue
        out_headers[m[0][0]] = urllib.parse.unquote_plus(m[0][1])

    return (target_url, out_headers)
