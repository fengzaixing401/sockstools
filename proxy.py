import socket
import select
import threading
import argparse
from http.server import HTTPServer, BaseHTTPRequestHandler
from socketserver import ThreadingMixIn
import socks
import requests
import json
import random
import time
import urllib3
import aiohttp
import asyncio
from typing import List
import aiofiles
import sys
import logging

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

class ThreadingHTTPServer(ThreadingMixIn, HTTPServer):
    def __init__(self, *args, **kwargs):
        self.upstream_proxy = None
        super().__init__(*args, **kwargs)

class ProxyHandler(BaseHTTPRequestHandler):
    upstream_proxy = None

    def do_CONNECT(self):
        address = self.path.split(':', 1)
        address[1] = int(address[1]) or 443
        try:
            s = socks.create_connection(address, **self.upstream_proxy) if self.upstream_proxy else socket.create_connection(address, timeout=self.timeout)
            self.send_response(200, 'Connection Established')
            self.end_headers()
            self._handle_connection(s)
        except Exception as e:
            self.send_error(502)
            log(f"Error connecting to upstream: {e}")

    def _handle_connection(self, s):
        conns = [self.connection, s]
        self.close_connection = 0
        while not self.close_connection:
            rlist, _, xlist = select.select(conns, [], conns, self.timeout)
            if xlist or not rlist:
                break
            for r in rlist:
                other = conns[1] if r is conns[0] else conns[0]
                data = r.recv(8192)
                if not data:
                    self.close_connection = 1
                    break
                other.sendall(data)

    def do_GET(self):
        self._handle_request()

    def _handle_request(self):
        try:
            url = self.path
            headers = {k: v for k, v in self.headers.items()}
            proxies = self.upstream_proxy if self.upstream_proxy else None
            with requests.get(url, headers=headers, proxies=proxies, stream=True) as response:
                self.send_response(response.status_code)
                for header, value in response.headers.items():
                    self.send_header(header, value)
                self.end_headers()
                for chunk in response.iter_content(8192):
                    self.wfile.write(chunk)
        except Exception as e:
            self.send_error(502)
            log(f"Error handling request: {e}")

    do_POST = do_PUT = do_DELETE = do_HEAD = _handle_request

class SocksProxy(threading.Thread):
    def __init__(self, host, port, upstream_proxy=None):
        super().__init__()
        self.host = host
        self.port = port
        self.upstream_proxy = upstream_proxy
        self.running = False
        self.server = None
        self.stop_event = threading.Event()

    def run(self):
        self.server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.server.bind((self.host, self.port))
        self.server.listen(5)
        self.server.settimeout(1)
        self.running = True
        while self.running and not self.stop_event.is_set():
            try:
                client, _ = self.server.accept()
                threading.Thread(target=self.handle_client, args=(client,)).start()
            except socket.timeout:
                continue
            except Exception as e:
                if self.running:
                    log(f"Error accepting connection: {e}")

    def stop(self):
        self.running = False
        self.stop_event.set()
        if self.server:
            self.server.close()

    def handle_client(self, client):
        with client:
            client.recv(2)
            client.sendall(b"\x05\x00")
            version, cmd, _, address_type = client.recv(4)
            if address_type == 1:
                address = socket.inet_ntoa(client.recv(4))
            elif address_type == 3:
                domain_length = ord(client.recv(1))
                address = client.recv(domain_length).decode()
            else:
                client.close()
                return
            port = int.from_bytes(client.recv(2), 'big')
            try:
                if cmd == 1:
                    remote = socks.create_connection((address, port), **self.upstream_proxy) if self.upstream_proxy else socket.create_connection((address, port))
                    bind_address = remote.getsockname()
                    log(f"Connected to {address}:{port}")
                else:
                    client.close()
                    return
            except Exception as e:
                log(e)
                client.close()
                return
            client.sendall(b"\x05\x00\x00\x01" + socket.inet_aton(bind_address[0]) + bind_address[1].to_bytes(2, 'big'))
            self.exchange_loop(client, remote)

    def exchange_loop(self, client, remote):
        while True:
            r, _, _ = select.select([client, remote], [], [])
            if client in r:
                data = client.recv(4096)
                if remote.send(data) <= 0:
                    break
            if remote in r:
                data = remote.recv(4096)
                if client.send(data) <= 0:
                    break

class ProxyPool:
    def __init__(self, file_path: str = 'proxies.json'):
        self.file_path = file_path
        self.proxies: List[str] = []
        self.last_refresh = 0
        self.refresh_interval = 300

    async def add_proxies(self, new_proxies: List[str]):
        self.proxies.extend([proxy for proxy in new_proxies if proxy not in self.proxies])
        await self.save_to_file()
        log(f"Added {len(new_proxies)} new proxies. Total proxies: {len(self.proxies)}")
        return new_proxies[-1] if new_proxies else None  # 返回最新添加的代理

    async def get_proxy(self) -> str:
        if not self.proxies:
            await self.load_from_file()
        return random.choice(self.proxies) if self.proxies else None

    async def refresh_proxies(self):
        await self.load_from_file()
        log(f"刷新代理完成。当前代理数量: {len(self.proxies)}")

    async def save_to_file(self):
        async with aiofiles.open(self.file_path, 'w') as f:
            await f.write(json.dumps(self.proxies, indent=2))
        log(f"Saved {len(self.proxies)} proxies to {self.file_path}")

    async def load_from_file(self, file_path=None):
        try:
            path = file_path or self.file_path
            async with aiofiles.open(path, 'r') as f:
                content = await f.read()
                self.proxies = json.loads(content) if content.strip() else []
            log(f"Loaded {len(self.proxies)} proxies from {path}")
            return self.proxies
        except (FileNotFoundError, json.JSONDecodeError):
            self.proxies = []
            log(f"Error loading proxies from {path}. Starting with empty proxy list.")
            return []

    async def get_latest_proxy(self) -> str:
        if not self.proxies:
            await self.load_from_file()
        return self.proxies[-1] if self.proxies else None

    async def clean_proxies(self):
        valid_proxies = []
        for proxy in self.proxies:
            if await self.is_proxy_valid(proxy):
                valid_proxies.append(proxy)
            else:
                log(f"移除无效代理: {proxy}")
        self.proxies = valid_proxies
        await self.save_to_file()
        log(f"清理完成。当前有效代理数: {len(self.proxies)}")

    @staticmethod
    async def is_proxy_valid(proxy: str) -> bool:
        try:
            parsed_proxy = parse_proxy_string(proxy)
            async with aiohttp.ClientSession() as session:
                async with session.get('http://www.example.com', proxy=parsed_proxy, timeout=5) as response:
                    return response.status == 200
        except Exception:
            return False

proxy_pool = ProxyPool()

async def get_proxies_from_url(url):
    log(f"开始从 URL 获取代理: {url}")
    headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'}
    async with aiohttp.ClientSession() as session:
        for attempt in range(3):
            try:
                log(f"发送 GET 请求... (尝试 {attempt + 1}/3)")
                async with session.get(url, headers=headers, timeout=10) as response:
                    if response.status == 200:
                        content = await response.text()
                        proxy_list = content.strip().split(',')
                        valid_proxies = [proxy.strip() for proxy in proxy_list if proxy.strip()]
                        if valid_proxies:
                            log(f"获取到 {len(valid_proxies)} 个有效代理地址")
                            return valid_proxies
                        log("响应中没有有效的代理地址")
                    else:
                        log(f"请求失败，状态码: {response.status}")
            except asyncio.TimeoutError:
                log(f"请求超时 (尝试 {attempt + 1}/3)")
            except Exception as e:
                log(f"发生错误: {str(e)} (尝试 {attempt + 1}/3)")
            if attempt < 2:
                await asyncio.sleep(2)
        log("未能获取到有效的代理地址")
        return []

def parse_proxy_string(proxy_string):
    if '://' not in proxy_string:
        proxy_string = 'http://' + proxy_string
    parts = proxy_string.split('://')
    proxy_type = parts[0].lower()
    if proxy_type in ['http', 'https']:
        return proxy_string
    elif proxy_type in ['socks4', 'socks5', 'socks']:
        return proxy_string if proxy_type != 'socks' else 'socks5://' + parts[1]
    return None

def get_upstream_proxy(args):
    if args.proxy_method == 'url':
        proxies = asyncio.run(get_proxies_from_url(args.upstream_url))
        return random.choice(proxies) if proxies else None
    elif args.proxy_method == 'file':
        proxies = asyncio.run(proxy_pool.load_from_file(args.upstream_file))
        return random.choice(proxies) if proxies else None
    elif args.proxy_method == 'manual':
        return args.upstream
    log("No valid upstream proxy found. Running in direct mode.")
    return None

def log(message, level=logging.INFO):
    logging.log(level, message)

def create_server(args):
    try:
        upstream_proxy = get_upstream_proxy(args)

        if args.type == 'http':
            server = ThreadingHTTPServer(('0.0.0.0', args.port), ProxyHandler)
            server.upstream_proxy = upstream_proxy
            ProxyHandler.upstream_proxy = upstream_proxy
            log(f"Starting HTTP proxy on 0.0.0.0:{args.port}")
        else:  # socks5
            server = SocksProxy('0.0.0.0', args.port, upstream_proxy)
            log(f"Starting SOCKS5 proxy on 0.0.0.0:{args.port}")

        if upstream_proxy:
            log(f"Using upstream proxy: {upstream_proxy}")
        else:
            log("No valid upstream proxy found. Running in direct mode.")

        return server
    except Exception as e:
        log(f"Error creating server: {str(e)}")
        raise

def main(args=None):
    if args is None:
        parser = argparse.ArgumentParser(description="Simple HTTP and SOCKS5 Proxy with Upstream Support")
        parser.add_argument('--type', choices=['http', 'socks5'], default='http', help='Proxy type (default: http)')
        parser.add_argument('--port', type=int, default=8080, help='Bind port (default: 8080)')
        parser.add_argument('--upstream', help='Upstream proxy address (e.g., http://1.2.3.4:8080 or socks5://1.2.3.4:1080)')
        parser.add_argument('--upstream-file', help='File containing upstream proxy addresses')
        parser.add_argument('--upstream-url', help='URL to fetch random proxy addresses')
        parser.add_argument('--upstream-refresh', type=int, default=0, help='Refresh upstream proxy every N seconds (0 to disable)')
        args = parser.parse_args()

    server = create_server(args)

    try:
        if args.type == 'http':
            server.serve_forever()
        else:
            server.run()
    except KeyboardInterrupt:
        log("Proxy server stopped.")

if __name__ == "__main__":
    main()