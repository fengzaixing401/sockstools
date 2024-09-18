import tkinter as tk
from tkinter import ttk, scrolledtext, filedialog, messagebox
import threading
import proxy
import argparse
import time
import queue
import asyncio
import random
import os
import json
import aiohttp
import atexit

from proxy import ThreadingHTTPServer, SocksProxy, ProxyPool, get_proxies_from_url, parse_proxy_string

class ProxyGUI:
    def __init__(self, master):
        self.master = master
        master.title("代理服务器 GUI")
        master.geometry("700x600")

        self.frame = tk.Frame(master)
        self.frame.pack(padx=10, pady=10, fill=tk.BOTH, expand=True)

        self.create_settings(self.frame)
        self.create_control_buttons(self.frame)
        self.create_log_level_selector(self.frame)
        self.create_log_area(self.frame)

        self.proxy_server = None
        self.proxy_thread = None
        self.is_running = False
        self.last_proxy_update = None
        self.stop_event = threading.Event()
        self.log_queue = queue.Queue()
        self.after_id = None
        self.proxy_pool = ProxyPool()
        self.load_proxies_from_file()

        self.master.protocol("WM_DELETE_WINDOW", self.on_closing)
        atexit.register(self.cleanup)

    def create_settings(self, parent):
        # 代理类型选择
        self.type_frame = ttk.Frame(parent)
        self.type_frame.pack(fill=tk.X, pady=2)
        ttk.Label(self.type_frame, text="代理类型:").pack(side=tk.LEFT)
        self.type_var = tk.StringVar(value="http")
        ttk.Combobox(self.type_frame, textvariable=self.type_var, values=["http", "socks5"]).pack(side=tk.LEFT, expand=True, fill=tk.X)

        # 端口输入
        self.port_frame = ttk.Frame(parent)
        self.port_frame.pack(fill=tk.X, pady=2)
        ttk.Label(self.port_frame, text="端口:").pack(side=tk.LEFT)
        self.port_var = tk.StringVar(value="8080")
        ttk.Entry(self.port_frame, textvariable=self.port_var).pack(side=tk.LEFT, expand=True, fill=tk.X)

        # 上游代理 URL
        self.upstream_url_frame = ttk.Frame(parent)
        self.upstream_url_frame.pack(fill=tk.X, pady=2)
        ttk.Label(self.upstream_url_frame, text="上游代理 URL:").pack(side=tk.LEFT)
        self.upstream_url_var = tk.StringVar(value='http://142.171.43.137:5000/fetch_random')
        self.upstream_url_combo = ttk.Combobox(self.upstream_url_frame, textvariable=self.upstream_url_var, 
                                               values=['http://142.171.43.137:5000/fetch_random', 
                                                       'http://142.171.43.137:5000/fetch_all'])
        self.upstream_url_combo.pack(side=tk.LEFT, expand=True, fill=tk.X)
        self.upstream_url_combo.bind('<KeyRelease>', self.on_url_edit)

        # 上游代理设置
        self.upstream_frame = ttk.Frame(parent)
        self.upstream_frame.pack(fill=tk.X, pady=2)
        ttk.Label(self.upstream_frame, text="上游代理:").pack(side=tk.LEFT)
        self.upstream_var = tk.StringVar()
        ttk.Entry(self.upstream_frame, textvariable=self.upstream_var).pack(side=tk.LEFT, expand=True, fill=tk.X)

        # 上游代理文件
        self.upstream_file_frame = ttk.Frame(parent)
        self.upstream_file_frame.pack(fill=tk.X, pady=2)
        ttk.Label(self.upstream_file_frame, text="上游代理文件:").pack(side=tk.LEFT)
        self.upstream_file_var = tk.StringVar()
        ttk.Entry(self.upstream_file_frame, textvariable=self.upstream_file_var).pack(side=tk.LEFT, expand=True, fill=tk.X)
        ttk.Button(self.upstream_file_frame, text="浏览", command=self.browse_file).pack(side=tk.LEFT)

        # 刷新间隔
        self.refresh_frame = ttk.Frame(parent)
        self.refresh_frame.pack(fill=tk.X, pady=2)
        ttk.Label(self.refresh_frame, text="刷新间隔 (秒):").pack(side=tk.LEFT)
        self.refresh_var = tk.StringVar(value="0")
        ttk.Entry(self.refresh_frame, textvariable=self.refresh_var).pack(side=tk.LEFT)
        ttk.Label(self.refresh_frame, text="(0 表示不自动刷新)").pack(side=tk.LEFT)

    def create_control_buttons(self, parent):
        self.button_frame = ttk.Frame(parent)
        self.button_frame.pack(fill=tk.X, pady=5)
        self.start_button = ttk.Button(self.button_frame, text="启动代理服务器", command=self.start_proxy)
        self.start_button.pack(side=tk.LEFT, padx=(0, 5))
        self.stop_button = ttk.Button(self.button_frame, text="停止代理服务器", command=self.stop_proxy, state=tk.DISABLED)
        self.stop_button.pack(side=tk.LEFT)

        self.change_proxy_frame = ttk.Frame(parent)
        self.change_proxy_frame.pack(fill=tk.X, pady=5)
        self.new_proxy_var = tk.StringVar()
        ttk.Entry(self.change_proxy_frame, textvariable=self.new_proxy_var).pack(side=tk.LEFT, expand=True, fill=tk.X)
        ttk.Button(self.change_proxy_frame, text="手动更改代理", command=self.change_proxy_manually).pack(side=tk.LEFT)
        ttk.Button(self.change_proxy_frame, text="重新获取代理", command=self.refresh_proxy).pack(side=tk.LEFT)
        ttk.Button(self.change_proxy_frame, text="刷新代理池", command=self.refresh_proxy_pool).pack(side=tk.LEFT)
        ttk.Button(self.change_proxy_frame, text="清理代理池", command=self.clean_proxy_pool).pack(side=tk.LEFT)

        self.proxy_count_label = ttk.Label(parent, text="当前代理数量: 0")
        self.proxy_count_label.pack()

        self.current_proxy_frame = ttk.Frame(parent)
        self.current_proxy_frame.pack(fill=tk.X, pady=5)
        ttk.Label(self.current_proxy_frame, text="当前使用的代理:").pack(side=tk.LEFT)
        self.current_proxy_var = tk.StringVar(value="无")
        ttk.Entry(self.current_proxy_frame, textvariable=self.current_proxy_var, state='readonly').pack(side=tk.LEFT, expand=True, fill=tk.X)

    def create_log_level_selector(self, parent):
        self.log_level_frame = ttk.Frame(parent)
        self.log_level_frame.pack(fill=tk.X, pady=2)
        ttk.Label(self.log_level_frame, text="日志级别:").pack(side=tk.LEFT)
        self.log_level = tk.StringVar(value="INFO")
        log_levels = ["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]
        self.log_level_combo = ttk.Combobox(self.log_level_frame, textvariable=self.log_level, values=log_levels)
        self.log_level_combo.pack(side=tk.LEFT, expand=True, fill=tk.X)
        self.log_level_combo.bind("<<ComboboxSelected>>", self.on_log_level_change)

    def create_log_area(self, parent):
        self.log_label = ttk.Label(parent, text="日志:")
        self.log_label.pack()
        self.log_text = scrolledtext.ScrolledText(parent, height=10)
        self.log_text.pack(fill=tk.BOTH, expand=True)

    def browse_file(self):
        filename = filedialog.askopenfilename(filetypes=[("所有文件", "*.*"), ("文本文件", "*.txt"), ("JSON文件", "*.json")])
        if filename:
            self.upstream_file_var.set(filename)

    def change_proxy_manually(self):
        if not self.is_running:
            self.queue_log_message("代理服务器未运行，无法更改代理", "WARNING")
            return

        new_proxy = self.new_proxy_var.get().strip()
        if not new_proxy:
            self.queue_log_message("请输入新的代理地址", "WARNING")
            return

        parsed_proxy = parse_proxy_string(new_proxy)
        if parsed_proxy:
            self.update_proxy(parsed_proxy)
            self.queue_log_message(f"手动更改代理为: {new_proxy}", "INFO")
        else:
            self.queue_log_message("无效的代理地址格式", "ERROR")

    def refresh_proxy(self):
        if not self.is_running:
            self.queue_log_message("代理服务器未运行，无法刷新代理", "WARNING")
            return

        self.queue_log_message("正在从网站获取新代理...", "INFO")
        threading.Thread(target=self._refresh_proxy_thread, daemon=True).start()

    def _refresh_proxy_thread(self):
        try:
            args = argparse.Namespace(upstream_url=self.upstream_url_var.get())
            new_proxies = asyncio.run(get_proxies_from_url(args.upstream_url))
            if new_proxies:
                asyncio.run(self.proxy_pool.add_proxies(new_proxies))
                self.queue_log_message(f"成功获取并添加 {len(new_proxies)} 个新代理到代理池", "INFO")
                self.save_proxies_to_file()
                valid_proxy = asyncio.run(self.proxy_pool.get_proxy())
                if valid_proxy:
                    new_proxy = parse_proxy_string(valid_proxy)
                    self.update_proxy(new_proxy)
                    self.queue_log_message("成功获取新的有效代理", "INFO")
                    self.master.after(0, self.update_proxy_count)
                else:
                    self.queue_log_message("无法获取有效的新代理", "WARNING")
            else:
                self.queue_log_message("无法从网站获取新的代理", "WARNING")
        except Exception as e:
            self.queue_log_message(f"获取新代理时发生错误: {str(e)}", "ERROR")

    def update_proxy(self, new_proxy):
        if self.proxy_server:
            if isinstance(self.proxy_server, ThreadingHTTPServer):
                self.proxy_server.upstream_proxy = new_proxy
                proxy.ProxyHandler.upstream_proxy = new_proxy
            elif isinstance(self.proxy_server, SocksProxy):
                self.proxy_server.upstream_proxy = new_proxy
        
        if isinstance(new_proxy, dict):
            if 'http' in new_proxy:
                self.current_proxy_var.set(new_proxy['http'])
            elif 'proxy_type' in new_proxy:
                proxy_type = 'socks4' if new_proxy['proxy_type'] == proxy.socks.SOCKS4 else 'socks5'
                self.current_proxy_var.set(f"{proxy_type}://{new_proxy['addr']}:{new_proxy['port']}")
        elif isinstance(new_proxy, str):
            self.current_proxy_var.set(new_proxy)
        else:
            self.current_proxy_var.set(str(new_proxy))
        
        self.queue_log_message(f"更新上游代理", "INFO")

    def update_proxy_count(self):
        count = len(self.proxy_pool.proxies)
        self.proxy_count_label.config(text=f"当前代理数量: {count}")

    def refresh_proxy_pool(self):
        if not self.is_running:
            self.queue_log_message("代理服务器未运行，无法刷新代理池", "WARNING")
            return

        self.queue_log_message("正在刷新代理池...", "INFO")
        threading.Thread(target=self._refresh_proxy_pool_thread, daemon=True).start()

    def _refresh_proxy_pool_thread(self):
        try:
            asyncio.run(self.proxy_pool.refresh_proxies())
            self.master.after(0, self.update_proxy_count)
            
            new_proxy_str = asyncio.run(self.proxy_pool.get_proxy())
            if new_proxy_str:
                new_proxy = parse_proxy_string(new_proxy_str)
                self.update_proxy(new_proxy)
                self.queue_log_message(f"代理池刷新完成，选择新代理: {new_proxy_str}", "INFO")
            else:
                self.queue_log_message("代理池刷新完成，但没有可用的代理", "WARNING")
        except Exception as e:
            self.queue_log_message(f"刷新代理池时发生错误: {str(e)}", "ERROR")

    def on_url_edit(self, event):
        current_value = self.upstream_url_var.get()
        if current_value not in self.upstream_url_combo['values']:
            new_values = list(self.upstream_url_combo['values']) + [current_value]
            self.upstream_url_combo['values'] = new_values

    def on_log_level_change(self, event):
        self.queue_log_message(f"日志级别已更改为: {self.log_level.get()}", "INFO")

    @property
    def log_levels(self):
        return ["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]

    def save_proxies_to_file(self):
        proxy_file = 'proxies.json'
        try:
            with open(proxy_file, 'w') as f:
                json.dump({"proxies": self.proxy_pool.proxies}, f, indent=2)
            self.queue_log_message(f"成功保存 {len(self.proxy_pool.proxies)} 个代理到文件", "INFO")
        except Exception as e:
            self.queue_log_message(f"保存代理到文件时发生错误: {str(e)}", "ERROR")

    def clean_proxy_pool(self):
        if not self.is_running:
            self.queue_log_message("代理服务器未运行，无法清理代理池", "WARNING")
            return

        self.queue_log_message("正在清理代理池...", "INFO")
        threading.Thread(target=self._clean_proxy_pool_thread, daemon=True).start()

    def _clean_proxy_pool_thread(self):
        try:
            initial_count = len(self.proxy_pool.proxies)
            asyncio.run(self._clean_proxies())
            final_count = len(self.proxy_pool.proxies)
            removed_count = initial_count - final_count

            self.queue_log_message(f"代理池清理完成。移除了 {removed_count} 个无效代理。", "INFO")
            self.master.after(0, self.update_proxy_count)
            
            if final_count == 0:
                self.queue_log_message("代理池为空，尝试获取新代理...", "INFO")
                new_proxies = asyncio.run(get_proxies_from_url(self.upstream_url_var.get()))
                if new_proxies:
                    asyncio.run(self.proxy_pool.add_proxies(new_proxies))
                    self.queue_log_message(f"成功获取并添加 {len(new_proxies)} 个新代理到代理池", "INFO")
                    self.save_proxies_to_file()
                    new_proxy_str = asyncio.run(self.proxy_pool.get_proxy())
                    if new_proxy_str:
                        new_proxy = parse_proxy_string(new_proxy_str)
                        self.update_proxy(new_proxy)
                        self.queue_log_message(f"成功获取新的有效代理: {new_proxy_str}", "INFO")
                else:
                    self.queue_log_message("无法从网站获取新的代理", "WARNING")
            else:
                self.save_proxies_to_file()
                new_proxy_str = asyncio.run(self.proxy_pool.get_proxy())
                if new_proxy_str:
                    new_proxy = parse_proxy_string(new_proxy_str)
                    self.update_proxy(new_proxy)
                    self.queue_log_message(f"使用现有代理: {new_proxy_str}", "INFO")

            self.master.after(0, self.update_proxy_count)
        except Exception as e:
            self.queue_log_message(f"清理代理池时发生错误: {str(e)}", "ERROR")

    async def _clean_proxies(self):
        valid_proxies = []
        for proxy_str in self.proxy_pool.proxies:
            if await self._is_proxy_valid(proxy_str):
                valid_proxies.append(proxy_str)
            else:
                self.queue_log_message(f"移除无效代理: {proxy_str}", "INFO")
        self.proxy_pool.proxies = valid_proxies

    async def _is_proxy_valid(self, proxy_str):
        try:
            parsed_proxy = parse_proxy_string(proxy_str)
            async with aiohttp.ClientSession() as session:
                async with session.get('http://www.example.com', proxy=parsed_proxy, timeout=5) as response:
                    return response.status == 200
        except Exception:
            return False

    def start_proxy(self):
        if self.is_running:
            self.queue_log_message("代理服务器已经在运行中", "WARNING")
            return

        try:
            port = int(self.port_var.get())
            proxy_type = self.type_var.get()
            upstream_proxy = self.upstream_var.get()
            upstream_file = self.upstream_file_var.get()
            refresh_interval = int(self.refresh_var.get())

            args = argparse.Namespace(
                port=port,
                type=proxy_type,
                upstream=upstream_proxy,
                upstream_file=upstream_file,
                refresh=refresh_interval,
                upstream_url=self.upstream_url_var.get()
            )

            self.stop_event.clear()
            
            self.queue_log_message("正在获取初始代理...", "INFO")
            initial_proxy = self.get_initial_proxy(args.upstream_url)
            if initial_proxy:
                args.upstream = initial_proxy
                self.queue_log_message(f"使用初始代理: {initial_proxy}", "INFO")
                self.update_proxy(initial_proxy)
                self.update_proxy_count()
            else:
                self.queue_log_message("无法获取初始代理，将使用默认设置", "WARNING")

            self.proxy_thread = threading.Thread(target=self._run_proxy, args=(args,), daemon=True)
            self.proxy_thread.start()

            self.is_running = True
            self.start_button.config(state=tk.DISABLED)
            self.stop_button.config(state=tk.NORMAL)
            self.queue_log_message("代理服务器已启动", "INFO")
        except ValueError as e:
            self.queue_log_message(f"启动失败: {str(e)}", "ERROR")

    def get_initial_proxy(self, upstream_url):
        if self.proxy_pool.proxies:
            return random.choice(self.proxy_pool.proxies)
        
        try:
            new_proxies = asyncio.run(get_proxies_from_url(upstream_url))
            if new_proxies:
                asyncio.run(self.proxy_pool.add_proxies(new_proxies))
                self.save_proxies_to_file()
                return asyncio.run(self.proxy_pool.get_proxy())
        except Exception as e:
            self.queue_log_message(f"获取初始代理时发生错误: {str(e)}", "ERROR")
        return None

    def stop_proxy(self):
        if not self.is_running:
            self.queue_log_message("代理服务器未在运行", "WARNING")
            return

        self.queue_log_message("正在停止代理服务器...", "INFO")
        self.stop_event.set()

        def shutdown_server():
            try:
                if self.proxy_server:
                    if isinstance(self.proxy_server, ThreadingHTTPServer):
                        self.proxy_server.shutdown()
                        self.proxy_server.server_close()
                    elif isinstance(self.proxy_server, SocksProxy):
                        self.proxy_server.stop()
                self.queue_log_message("代理服务器已成功停止", "INFO")
            except Exception as e:
                self.queue_log_message(f"停止代理服务器时发生错误: {str(e)}", "ERROR")

        shutdown_thread = threading.Thread(target=shutdown_server)
        shutdown_thread.start()

        # 等待关闭线程最多 10 秒
        shutdown_thread.join(timeout=10)

        if shutdown_thread.is_alive():
            self.queue_log_message("停止代理服务器超时，强制关闭", "WARNING")
        
        self.is_running = False
        self.start_button.config(state=tk.NORMAL)
        self.stop_button.config(state=tk.DISABLED)

        # 重置代理服务器和线程
        self.proxy_server = None
        if self.proxy_thread and self.proxy_thread.is_alive():
            self.proxy_thread.join(timeout=2)
        self.proxy_thread = None

        # 确保所有相关的异步任务都被取消
        self.cancel_all_tasks()

    def cancel_all_tasks(self):
        try:
            loop = asyncio.get_event_loop()
            tasks = [t for t in asyncio.all_tasks(loop) if t is not asyncio.current_task()]
            [task.cancel() for task in tasks]
            loop.run_until_complete(asyncio.gather(*tasks, return_exceptions=True))
        except Exception as e:
            self.queue_log_message(f"取消异步任务时发生错误: {str(e)}", "ERROR")

    def _run_proxy(self, args):
        try:
            self.proxy_server = proxy.create_server(args)
            if isinstance(self.proxy_server, ThreadingHTTPServer):
                self.proxy_server.timeout = 1  # 设置超时时间为1秒
                while not self.stop_event.is_set():
                    self.proxy_server.handle_request()
            elif isinstance(self.proxy_server, SocksProxy):
                self.proxy_server.run()
        except Exception as e:
            self.queue_log_message(f"代理服务器运行错误: {str(e)}", "ERROR")
        finally:
            self.master.after(0, self.stop_proxy)

    def queue_log_message(self, message, level):
        self.log_queue.put((message, level))
        if self.after_id is None:
            self.after_id = self.master.after(100, self.process_log_queue)

    def process_log_queue(self):
        while not self.log_queue.empty():
            message, level = self.log_queue.get()
            self.log_text.insert(tk.END, f"[{level}] {message}\n")
            self.log_text.see(tk.END)
        self.after_id = None

    def on_closing(self):
        if self.is_running:
            if messagebox.askokcancel("退出", "代理服务器正在运行。确定要退出吗？"):
                self.stop_proxy()
                self.master.after(1000, self.force_exit)  # 给一些时间让停止过程完成
        else:
            self.force_exit()

    def force_exit(self):
        self.cleanup()
        self.master.destroy()
        os._exit(0)  # 强制终止所有线程

    def cleanup(self):
        if self.is_running:
            self.stop_proxy()
        
        # 确保所有线程都已停止
        if self.proxy_thread and self.proxy_thread.is_alive():
            self.proxy_thread.join(timeout=2)
        
        # 关闭所有可能的网络连接
        try:
            loop = asyncio.get_event_loop()
        except RuntimeError:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
        
        tasks = asyncio.all_tasks(loop)
        for task in tasks:
            task.cancel()
        
        if tasks:
            loop.run_until_complete(asyncio.gather(*tasks, return_exceptions=True))
        
        loop.close()
        
        # 确保日志队列被处理
        self.process_log_queue()

    def load_proxies_from_file(self):
        proxy_file = 'proxies.json'
        try:
            with open(proxy_file, 'r') as f:
                data = json.load(f)
            if isinstance(data, dict) and 'proxies' in data:
                self.proxy_pool.proxies = data['proxies']
            else:
                self.proxy_pool.proxies = data  # 兼容旧格式
            self.queue_log_message(f"从文件加载了 {len(self.proxy_pool.proxies)} 个代理", "INFO")
            self.update_proxy_count()
        except Exception as e:
            self.queue_log_message(f"加载代理文件时发生错误: {str(e)}", "ERROR")

def main():
    root = tk.Tk()
    app = ProxyGUI(root)
    root.mainloop()

if __name__ == "__main__":
    main()