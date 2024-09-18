import tkinter as tk
from tkinter import ttk, scrolledtext, filedialog, messagebox
import threading
import proxy
import argparse
import asyncio
import os
import json
from functools import partial
import sys
import queue
import logging
import random

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

class ProxyGUI:
    def __init__(self, master):
        self.master = master
        master.title("代理服务器 GUI")
        master.geometry("700x600")

        self.frame = tk.Frame(master)
        self.frame.pack(padx=10, pady=10, fill=tk.BOTH, expand=True)

        self.proxy_server = None
        self.proxy_thread = None
        self.is_running = False
        self.stop_event = threading.Event()
        self.proxy_pool = proxy.ProxyPool()
        self.upstream_var = tk.StringVar()
        self.log_queue = queue.Queue()
        self.master.after(100, self.process_log_queue)

        self.create_widgets()

        self.master.protocol("WM_DELETE_WINDOW", self.on_closing)

    def create_widgets(self):
        self.create_settings()
        self.create_control_buttons()
        self.create_log_area()

    def create_settings(self):
        settings = [
            ("代理类型:", "type_var", "http", ["http", "socks5"]),
            ("端口:", "port_var", "8080", None),
            ("代理获取方法:", "proxy_method_var", "网页获取代理地址", ["网页获取代理地址", "文件获取代理地址", "手动输入代理地址"]),
            ("刷新间隔 (秒):", "refresh_var", "0", None),
        ]

        for text, var_name, default, values in settings:
            frame = ttk.Frame(self.frame)
            frame.pack(fill=tk.X, pady=2)
            ttk.Label(frame, text=text).pack(side=tk.LEFT)
            setattr(self, var_name, tk.StringVar(value=default))
            if values:
                widget = ttk.Combobox(frame, textvariable=getattr(self, var_name), values=values, state="readonly")
            else:
                widget = ttk.Entry(frame, textvariable=getattr(self, var_name))
            widget.pack(side=tk.LEFT, expand=True, fill=tk.X)

        # 创建动态显示的框架
        self.dynamic_frame = ttk.Frame(self.frame)
        self.dynamic_frame.pack(fill=tk.X, pady=2)

        # 初始显示URL输入框
        self.show_url_input()

        self.proxy_method_var.trace("w", self.on_proxy_method_change)

    def on_proxy_method_change(self, *args):
        # 清除当前显示的内容
        for widget in self.dynamic_frame.winfo_children():
            widget.destroy()

        method = self.proxy_method_var.get()
        if method == "网页获取代理地址":
            self.show_url_input()
        elif method == "文件获取代理地址":
            self.show_file_input()
        elif method == "手动输入代理地址":
            self.show_manual_input()

    def show_url_input(self):
        ttk.Label(self.dynamic_frame, text="上游代理 URL:").pack(side=tk.LEFT)
        self.upstream_url_var = tk.StringVar(value='http://142.171.43.137:5000/fetch_random')
        ttk.Entry(self.dynamic_frame, textvariable=self.upstream_url_var).pack(side=tk.LEFT, expand=True, fill=tk.X)

    def show_file_input(self):
        ttk.Label(self.dynamic_frame, text="上游代理文件:").pack(side=tk.LEFT)
        self.upstream_file_var = tk.StringVar()
        ttk.Entry(self.dynamic_frame, textvariable=self.upstream_file_var).pack(side=tk.LEFT, expand=True, fill=tk.X)
        ttk.Button(self.dynamic_frame, text="浏览", command=self.browse_file).pack(side=tk.LEFT)

    def show_manual_input(self):
        ttk.Label(self.dynamic_frame, text="上游代理:").pack(side=tk.LEFT)
        self.upstream_var = tk.StringVar()
        ttk.Entry(self.dynamic_frame, textvariable=self.upstream_var).pack(side=tk.LEFT, expand=True, fill=tk.X)
        ttk.Button(self.dynamic_frame, text="更改代理", command=self.change_proxy_manually).pack(side=tk.LEFT)

    def create_control_buttons(self):
        self.button_frame = ttk.Frame(self.frame)
        self.button_frame.pack(fill=tk.X, pady=5)
        self.start_button = ttk.Button(self.button_frame, text="启动代理服务器", command=self.start_proxy)
        self.start_button.pack(side=tk.LEFT, padx=(0, 5))
        self.stop_button = ttk.Button(self.button_frame, text="停止代理服务器", command=self.stop_proxy, state=tk.DISABLED)
        self.stop_button.pack(side=tk.LEFT)

        actions = [
            ("重新获取代理", self.refresh_proxy),
            ("刷新代理池", self.refresh_proxy_pool),
            ("清理代理池", self.clean_proxy_pool),
        ]

        for text, command in actions:
            ttk.Button(self.button_frame, text=text, command=command).pack(side=tk.LEFT)

        self.proxy_count_label = ttk.Label(self.frame, text="当前代理数量: 0")
        self.proxy_count_label.pack()

        self.current_proxy_frame = ttk.Frame(self.frame)
        self.current_proxy_frame.pack(fill=tk.X, pady=5)
        ttk.Label(self.current_proxy_frame, text="当前使用的代理:").pack(side=tk.LEFT)
        self.current_proxy_var = tk.StringVar(value="无")
        ttk.Entry(self.current_proxy_frame, textvariable=self.current_proxy_var, state='readonly').pack(side=tk.LEFT, expand=True, fill=tk.X)

    def create_log_area(self):
        self.log_text = scrolledtext.ScrolledText(self.frame, height=10)
        self.log_text.pack(fill=tk.BOTH, expand=True)

    def browse_file(self):
        filename = filedialog.askopenfilename()
        if filename:
            self.upstream_file_var.set(filename)

    def change_proxy_manually(self):
        if not self.is_running:
            self.log_message("代理服务器未运行，无法更改代理", level=logging.WARNING)
            return

        new_proxy = self.upstream_var.get().strip()
        if not new_proxy:
            self.log_message("请输入新的代理地址", level=logging.WARNING)
            return

        parsed_proxy = proxy.parse_proxy_string(new_proxy)
        if parsed_proxy:
            self.update_proxy(parsed_proxy)
            self.log_message(f"手动更改代理为: {new_proxy}")
        else:
            self.log_message("无效的代理地址格式", level=logging.ERROR)

    def refresh_proxy(self):
        if not self.is_running:
            self.log_message("代理服务器未运行，无法刷新代理", level=logging.WARNING)
            return

        self.log_message("正在刷新代理...")
        args = self._prepare_proxy_args()
        new_proxy = self.get_initial_proxy(args)
        if new_proxy:
            self.update_proxy(proxy.parse_proxy_string(new_proxy))
            self.log_message(f"成功刷新代理: {new_proxy}")
        else:
            self.log_message("无法获取新的代理", level=logging.WARNING)

    def update_proxy(self, new_proxy):
        if self.proxy_server:
            self.proxy_server.upstream_proxy = new_proxy
            if hasattr(self.proxy_server, 'RequestHandlerClass'):
                self.proxy_server.RequestHandlerClass.upstream_proxy = new_proxy
        
        # 将解析后的代理格式转换回原始字符串格式
        if isinstance(new_proxy, dict):
            if 'http' in new_proxy:
                proxy_str = new_proxy['http']
            elif 'proxy_type' in new_proxy:
                proxy_type = 'socks4' if new_proxy['proxy_type'] == socks.SOCKS4 else 'socks5'
                proxy_str = f"{proxy_type}://{new_proxy['addr']}:{new_proxy['port']}"
            else:
                proxy_str = str(new_proxy)
        else:
            proxy_str = str(new_proxy)
        
        self.current_proxy_var.set(proxy_str)
        self.log_message(f"更新上游代理为: {proxy_str}")

    def update_proxy_count(self):
        count = len(self.proxy_pool.proxies)
        self.proxy_count_label.config(text=f"当前代理数量: {count}")

    def refresh_proxy_pool(self):
        if not self.is_running:
            self.log_message("代理服务器未运行，无法刷新代理池", level=logging.WARNING)
            return

        self.log_message("正在刷新代理池...")
        asyncio.run(self._refresh_proxy_pool())

    async def _refresh_proxy_pool(self):
        try:
            await self.proxy_pool.refresh_proxies()
            self.master.after(0, self.update_proxy_count)
            
            new_proxy_str = await self.proxy_pool.get_proxy()
            if new_proxy_str:
                new_proxy = proxy.parse_proxy_string(new_proxy_str)
                self.update_proxy(new_proxy)
                self.log_message(f"代理池刷新完成，选择新代理: {new_proxy_str}")
            else:
                self.log_message("代理池刷新完成，但没有可用的代理", level=logging.WARNING)
        except Exception as e:
            self.log_message(f"刷新代理池时发生错误: {str(e)}", level=logging.ERROR)

    def clean_proxy_pool(self):
        if not self.is_running:
            self.log_message("代理服务器未运行，无法清理代理池", level=logging.WARNING)
            return

        self.log_message("正在清理代理池...")
        asyncio.run(self._clean_proxy_pool())

    async def _clean_proxy_pool(self):
        try:
            initial_count = len(self.proxy_pool.proxies)
            await self.proxy_pool.clean_proxies()
            final_count = len(self.proxy_pool.proxies)
            removed_count = initial_count - final_count

            self.log_message(f"代理池清理完成。移除了 {removed_count} 个无效代理。")
            self.master.after(0, self.update_proxy_count)
            
            if final_count == 0:
                self.log_message("代理池为空，尝试获取新代理...", level=logging.WARNING)
                await self._refresh_proxy()
            else:
                new_proxy_str = await self.proxy_pool.get_proxy()
                if new_proxy_str:
                    new_proxy = proxy.parse_proxy_string(new_proxy_str)
                    self.update_proxy(new_proxy)
                    self.log_message(f"使用现有代理: {new_proxy_str}")
        except Exception as e:
            self.log_message(f"清理代理池时发生错误: {str(e)}", level=logging.ERROR)

    def start_proxy(self):
        if self.is_running:
            self.log_message("代理服务器已经在运行中", level=logging.WARNING)
            return

        self.start_button.config(state=tk.DISABLED)
        self.stop_button.config(state=tk.NORMAL)
        
        threading.Thread(target=self._start_proxy_thread, daemon=True).start()

    def _start_proxy_thread(self):
        try:
            args = self._prepare_proxy_args()
            self.stop_event.clear()
            
            self.log_message("正在获取初始代理...")
            initial_proxy = self.get_initial_proxy(args)
            
            if initial_proxy:
                args.upstream = initial_proxy
                self.log_message(f"使用初始代理: {initial_proxy}")
                self.master.after(0, lambda: self.update_proxy(proxy.parse_proxy_string(initial_proxy)))
                self.master.after(0, self.update_proxy_count)
            else:
                self.log_message("无法获取初始代理，将使用默认设置", level=logging.WARNING)

            self.log_message("正在创建代理服务器...")
            self.proxy_server = proxy.create_server(args)
            self.is_running = True
            self.log_message("代理服务器已启动")

            if isinstance(self.proxy_server, proxy.ThreadingHTTPServer):
                self.proxy_server.serve_forever()
            elif isinstance(self.proxy_server, proxy.SocksProxy):
                self.proxy_server.run()
        except Exception as e:
            self.log_message(f"启动失败: {str(e)}", level=logging.ERROR)
            self.master.after(0, self._reset_buttons)
        finally:
            if self.is_running:
                self.log_message("代理服务器停止运行")
                self.master.after(0, self.stop_proxy)

    def _reset_buttons(self):
        self.start_button.config(state=tk.NORMAL)
        self.stop_button.config(state=tk.DISABLED)

    def _prepare_proxy_args(self):
        args = argparse.Namespace(
            port=int(self.port_var.get()),
            type=self.type_var.get(),
            proxy_method=self.proxy_method_var.get(),
            refresh=int(self.refresh_var.get()),
        )

        if args.proxy_method == '网页获取代理地址':
            args.upstream_url = self.upstream_url_var.get()
        elif args.proxy_method == '文件获取代理地址':
            args.upstream_file = self.upstream_file_var.get()
        elif args.proxy_method == '手动输入代理地址':
            args.upstream = self.upstream_var.get()

        return args

    def get_initial_proxy(self, args):
        if args.proxy_method == '网页获取代理地址':
            proxies = asyncio.run(proxy.get_proxies_from_url(args.upstream_url))
            return random.choice(proxies) if proxies else None
        elif args.proxy_method == '文件获取代理地址':
            proxies = asyncio.run(self.proxy_pool.load_from_file(args.upstream_file))
            return random.choice(proxies) if proxies else None
        elif args.proxy_method == '手动输入代理地址':
            return args.upstream
        return None

    def stop_proxy(self):
        if not self.is_running:
            self.log_message("代理服务器未在运行", level=logging.WARNING)
            return

        self.log_message("正在停止代理服务器...")
        self.stop_event.set()

        def shutdown_server():
            if self.proxy_server:
                if isinstance(self.proxy_server, proxy.ThreadingHTTPServer):
                    self.proxy_server.shutdown()
                    self.proxy_server.server_close()
                elif isinstance(self.proxy_server, proxy.SocksProxy):
                    self.proxy_server.stop()

            self.is_running = False
            self.master.after(0, self._reset_buttons)
            self.log_message("代理服务器已停止")

        threading.Thread(target=shutdown_server, daemon=True).start()

    def log_message(self, message, level=logging.INFO):
        logging.log(level, message)
        self.log_queue.put((level, message))

    def process_log_queue(self):
        try:
            while True:
                level, message = self.log_queue.get_nowait()
                self.log_text.insert(tk.END, f"{message}\n")
                self.log_text.see(tk.END)
        except queue.Empty:
            pass
        finally:
            self.master.after(100, self.process_log_queue)

    def on_closing(self):
        if self.is_running:
            if messagebox.askokcancel("退出", "代理服务器正在运行。确定要退出吗？"):
                self.stop_proxy()
                self.master.after(1000, self.master.destroy)
        else:
            self.master.destroy()

def main():
    root = tk.Tk()
    app = ProxyGUI(root)
    root.mainloop()

if __name__ == "__main__":
    main()