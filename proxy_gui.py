import tkinter as tk
from tkinter import ttk, scrolledtext, filedialog, messagebox
import threading
import proxy
import argparse
import time
import queue
import asyncio
import random

class ProxyGUI:
    def __init__(self, master):
        self.master = master
        master.title("代理服务器 GUI")
        master.geometry("600x500")

        self.frame = tk.Frame(master)
        self.frame.pack(padx=10, pady=10, fill=tk.BOTH, expand=True)

        # 代理类型选择
        self.type_frame = tk.Frame(self.frame)
        self.type_frame.pack(fill=tk.X)
        tk.Label(self.type_frame, text="代理类型:").pack(side=tk.LEFT)
        self.type_var = tk.StringVar(value="http")
        ttk.Combobox(self.type_frame, textvariable=self.type_var, values=["http", "socks5"]).pack(side=tk.LEFT)

        # 端口输入
        self.port_frame = tk.Frame(self.frame)
        self.port_frame.pack(fill=tk.X)
        tk.Label(self.port_frame, text="端口:").pack(side=tk.LEFT)
        self.port_var = tk.StringVar(value="8080")
        tk.Entry(self.port_frame, textvariable=self.port_var).pack(side=tk.LEFT)

        # 上游代理设置
        self.upstream_frame = tk.Frame(self.frame)
        self.upstream_frame.pack(fill=tk.X)
        tk.Label(self.upstream_frame, text="上游代理:").pack(side=tk.LEFT)
        self.upstream_var = tk.StringVar()
        tk.Entry(self.upstream_frame, textvariable=self.upstream_var).pack(side=tk.LEFT, expand=True, fill=tk.X)

        # 上游代理文件
        self.upstream_file_frame = tk.Frame(self.frame)
        self.upstream_file_frame.pack(fill=tk.X)
        tk.Label(self.upstream_file_frame, text="上游代理文件:").pack(side=tk.LEFT)
        self.upstream_file_var = tk.StringVar()
        tk.Entry(self.upstream_file_frame, textvariable=self.upstream_file_var).pack(side=tk.LEFT, expand=True, fill=tk.X)
        tk.Button(self.upstream_file_frame, text="浏览", command=self.browse_file).pack(side=tk.LEFT)

        # 上游代理 URL
        self.upstream_url_frame = tk.Frame(self.frame)
        self.upstream_url_frame.pack(fill=tk.X)
        tk.Label(self.upstream_url_frame, text="上游代理 URL:").pack(side=tk.LEFT)
        self.upstream_url_var = tk.StringVar(value='http://142.171.43.137:5000/fetch_random')
        tk.Entry(self.upstream_url_frame, textvariable=self.upstream_url_var).pack(side=tk.LEFT, expand=True, fill=tk.X)

        # 刷新间隔
        self.refresh_frame = tk.Frame(self.frame)
        self.refresh_frame.pack(fill=tk.X)
        tk.Label(self.refresh_frame, text="刷新间隔 (秒):").pack(side=tk.LEFT)
        self.refresh_var = tk.StringVar(value="0")
        tk.Entry(self.refresh_frame, textvariable=self.refresh_var).pack(side=tk.LEFT)
        tk.Label(self.refresh_frame, text="(0 表示不自动刷新)").pack(side=tk.LEFT)

        # 修改启动按钮和添加停止按钮
        self.button_frame = tk.Frame(self.frame)
        self.button_frame.pack(fill=tk.X, pady=5)
        self.start_button = tk.Button(self.button_frame, text="启动代理服务器", command=self.start_proxy)
        self.start_button.pack(side=tk.LEFT, padx=(0, 5))
        self.stop_button = tk.Button(self.button_frame, text="停止代理服务器", command=self.stop_proxy, state=tk.DISABLED)
        self.stop_button.pack(side=tk.LEFT)

        # 日志区域
        self.log_label = tk.Label(self.frame, text="日志:")
        self.log_label.pack()
        self.log_text = scrolledtext.ScrolledText(self.frame, height=10)
        self.log_text.pack(fill=tk.BOTH, expand=True)

        self.proxy_server = None
        self.proxy_thread = None
        self.is_running = False
        self.last_proxy_update = None
        self.stop_event = threading.Event()
        self.log_queue = queue.Queue()
        self.after_id = None

        # 添加窗口关闭事件处理
        self.master.protocol("WM_DELETE_WINDOW", self.on_closing)

        # 添加更改代理按钮和输入框
        self.change_proxy_frame = tk.Frame(self.frame)
        self.change_proxy_frame.pack(fill=tk.X, pady=5)
        self.new_proxy_var = tk.StringVar()
        tk.Entry(self.change_proxy_frame, textvariable=self.new_proxy_var).pack(side=tk.LEFT, expand=True, fill=tk.X)
        tk.Button(self.change_proxy_frame, text="手动更改代理", command=self.change_proxy_manually).pack(side=tk.LEFT)
        tk.Button(self.change_proxy_frame, text="重新获取代理", command=self.refresh_proxy).pack(side=tk.LEFT)

        # 添加显示当前代理数量的标签
        self.proxy_count_label = tk.Label(self.frame, text="当前代理数量: 0")
        self.proxy_count_label.pack()

        # 添加刷新代理池按钮
        self.refresh_pool_button = tk.Button(self.frame, text="刷新代理池", command=self.refresh_proxy_pool)
        self.refresh_pool_button.pack()

        # 添加显示当前使用代理的框
        self.current_proxy_frame = tk.Frame(self.frame)
        self.current_proxy_frame.pack(fill=tk.X, pady=5)
        tk.Label(self.current_proxy_frame, text="当前使用的代理:").pack(side=tk.LEFT)
        self.current_proxy_var = tk.StringVar(value="无")
        tk.Entry(self.current_proxy_frame, textvariable=self.current_proxy_var, state='readonly', width=50).pack(side=tk.LEFT, expand=True, fill=tk.X)

    def browse_file(self):
        filename = filedialog.askopenfilename(filetypes=[("Text files", "*.txt")])
        if filename:
            self.upstream_file_var.set(filename)

    def start_proxy(self):
        if self.is_running:
            return

        args = argparse.Namespace(
            type=self.type_var.get(),
            port=int(self.port_var.get()),
            upstream=self.upstream_var.get(),
            upstream_file=self.upstream_file_var.get(),
            upstream_url=self.upstream_url_var.get(),
            upstream_refresh=int(self.refresh_var.get())
        )

        self.queue_log_message("正在启动代理服务器...")
        self.queue_log_message(f"使用的参数: {args}")
        self.start_button.config(state=tk.DISABLED)
        self.stop_button.config(state=tk.NORMAL)

        def run_proxy():
            try:
                proxy.log.callback = self.queue_log_message
                asyncio.run(proxy.proxy_pool.load_from_file())  # 加载代理文件
                self.master.after(0, self.update_proxy_count)  # 更新代理数量显示
                self.proxy_server = proxy.create_server(args)
                
                # 获取并显示初始代理
                initial_proxy = self.proxy_server.upstream_proxy
                if initial_proxy:
                    self.master.after(0, lambda: self.update_proxy(initial_proxy))
                
                self.is_running = True
                self.master.after(0, self.update_buttons)
                self.queue_log_message(f"代理服务器已启动在 0.0.0.0:{args.port}")

                if args.type == 'http':
                    while not self.stop_event.is_set():
                        self.proxy_server.handle_request()
                else:
                    self.proxy_server.start()  # 启动SOCKS5代理
                    while self.proxy_server.is_alive() and not self.stop_event.is_set():
                        time.sleep(1)

                # 定期更新当前使用的代理信息
                self.update_proxy_thread = threading.Thread(target=self.periodic_proxy_update, args=(args,), daemon=True)
                self.update_proxy_thread.start()

            except Exception as e:
                self.queue_log_message(f"错误: {str(e)}")
            finally:
                self.is_running = False
                self.stop_event.clear()
                self.master.after(0, self.update_buttons)

        self.stop_event.clear()
        self.proxy_thread = threading.Thread(target=run_proxy, daemon=True)
        self.proxy_thread.start()
        self.start_log_polling()

    def periodic_proxy_update(self, args):
        while not self.stop_event.is_set():
            if args.upstream_refresh > 0:
                time.sleep(args.upstream_refresh)
                self.update_current_proxy(args)
            else:
                # 如果刷新间隔为 0，则不进行自动刷新
                self.queue_log_message("自动刷新已禁用（刷新间隔为 0）")
                break

    def stop_proxy(self):
        if not self.is_running:
            return

        self.queue_log_message("正在停止代理服务器...")
        
        def stop_proxy_thread():
            self.stop_event.set()
            
            if self.proxy_server:
                self.queue_log_message("正在关闭代理服务器...")
                try:
                    if isinstance(self.proxy_server, proxy.ThreadingHTTPServer):
                        self.proxy_server.shutdown()
                        self.proxy_server.server_close()
                    elif isinstance(self.proxy_server, proxy.SocksProxy):
                        self.proxy_server.stop()
                except Exception as e:
                    self.queue_log_message(f"关闭代理服务器时出错: {e}")
                self.proxy_server = None
                self.queue_log_message("代理服务器已关闭")
            
            if self.proxy_thread:
                self.queue_log_message("等待代理线程结束...")
                self.proxy_thread.join(timeout=10)  # 增加超时时间到10秒
                if self.proxy_thread.is_alive():
                    self.queue_log_message("警告：代理线程未能在10秒内结束，强制终止")
                else:
                    self.queue_log_message("代理线程已结束")
            
            if hasattr(self, 'update_proxy_thread'):
                self.queue_log_message("等待代理更新线程结束...")
                self.update_proxy_thread.join(timeout=5)
                if self.update_proxy_thread.is_alive():
                    self.queue_log_message("警告：代理更新线程未能在5秒内结束，强制终止")
                else:
                    self.queue_log_message("代理更新线程已结束")
            
            self.is_running = False
            self.queue_log_message("代理服务器已完全停止")
            self.master.after(0, self.update_buttons)

        threading.Thread(target=stop_proxy_thread, daemon=True).start()
        self.master.after(15000, self.force_stop)  # 15秒后强制停止

    def force_stop(self):
        if self.is_running:
            self.queue_log_message("强制停止代理服务器")
            self.is_running = False
            self.update_buttons()

    def queue_log_message(self, message):
        self.log_queue.put(message)

    def start_log_polling(self):
        self.poll_log_queue()

    def poll_log_queue(self):
        while not self.log_queue.empty():
            message = self.log_queue.get()
            self.log_text.insert(tk.END, message + "\n")
            self.log_text.see(tk.END)
        self.after_id = self.master.after(100, self.poll_log_queue)

    def update_buttons(self):
        if self.is_running:
            self.start_button.config(state=tk.DISABLED)
            self.stop_button.config(state=tk.NORMAL)
        else:
            self.start_button.config(state=tk.NORMAL)
            self.stop_button.config(state=tk.DISABLED)

    def update_current_proxy(self, args):
        new_proxy = asyncio.run(proxy.proxy_pool.get_proxy())
        if new_proxy:
            if self.proxy_server:
                if isinstance(self.proxy_server, proxy.ThreadingHTTPServer):
                    self.proxy_server.upstream_proxy = new_proxy
                    proxy.ProxyHandler.upstream_proxy = new_proxy
                elif isinstance(self.proxy_server, proxy.SocksProxy):
                    self.proxy_server.upstream_proxy = new_proxy
            self.queue_log_message(f"更新上游代理: {new_proxy}")
        else:
            self.queue_log_message("未找到有效的上游代理，将以直接模式运行")

    def log_callback(self, message):
        self.log_text.insert(tk.END, message + "\n")
        self.log_text.see(tk.END)

    def on_closing(self):
        if self.is_running:
            if messagebox.askokcancel("退出", "代理服务器正在运行。是否确定要退出？"):
                self.stop_proxy()
                self.master.after(1000, self.master.destroy)  # 给停止过程一些时间
            else:
                return
        else:
            self.master.destroy()

    def change_proxy_manually(self):
        if not self.is_running:
            self.queue_log_message("代理服务器未运行，无法更改代理")
            return

        new_proxy = self.new_proxy_var.get().strip()
        if not new_proxy:
            self.queue_log_message("请输入新的代理地址")
            return

        parsed_proxy = proxy.parse_proxy_string(new_proxy)
        if parsed_proxy:
            self.update_proxy(parsed_proxy)
            self.queue_log_message(f"手动更改代理为: {new_proxy}")
        else:
            self.queue_log_message("无效的代理地址格式")

    def refresh_proxy(self):
        if not self.is_running:
            self.queue_log_message("代理服务器未运行，无法刷新代理")
            return

        self.queue_log_message("正在从网站获取新代理...")
        threading.Thread(target=self._refresh_proxy_thread, daemon=True).start()

    def _refresh_proxy_thread(self):
        try:
            args = argparse.Namespace(upstream_url=self.upstream_url_var.get())
            new_proxies = asyncio.run(proxy.get_proxies_from_url(args.upstream_url))
            if new_proxies:
                valid_proxy = asyncio.run(proxy.proxy_pool.get_proxy())
                if valid_proxy:
                    asyncio.run(proxy.proxy_pool.add_proxies([valid_proxy]))
                    new_proxy = proxy.parse_proxy_string(valid_proxy)
                    self.update_proxy(new_proxy)
                    self.queue_log_message(f"成功获取新的有效代理: {valid_proxy}")
                    self.master.after(0, self.update_proxy_count)
                else:
                    self.queue_log_message("无法获取有效的新代理")
            else:
                self.queue_log_message("无法从网站获取新的代理")
        except Exception as e:
            self.queue_log_message(f"获取新代理时发生错误: {str(e)}")

    def update_proxy(self, new_proxy):
        if self.proxy_server:
            if isinstance(self.proxy_server, proxy.ThreadingHTTPServer):
                self.proxy_server.upstream_proxy = new_proxy
                proxy.ProxyHandler.upstream_proxy = new_proxy
            elif isinstance(self.proxy_server, proxy.SocksProxy):
                self.proxy_server.upstream_proxy = new_proxy
        
        # 更新当前使用的代理显示
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
        
        self.queue_log_message(f"更新上游代理: {new_proxy}")

    def update_proxy_count(self):
        count = len(proxy.proxy_pool.proxies)
        self.proxy_count_label.config(text=f"当前代理数量: {count}")

    def refresh_proxy_pool(self):
        if not self.is_running:
            self.queue_log_message("代理服务器未运行，无法刷新代理池")
            return

        self.queue_log_message("正在刷新代理池...")
        threading.Thread(target=self._refresh_proxy_pool_thread, daemon=True).start()

    def _refresh_proxy_pool_thread(self):
        try:
            asyncio.run(proxy.proxy_pool.refresh_proxies())
            self.master.after(0, self.update_proxy_count)
            
            # 从刷新后的代理池中随机选择一个新代理
            new_proxy_str = asyncio.run(proxy.proxy_pool.get_proxy())
            if new_proxy_str:
                new_proxy = proxy.parse_proxy_string(new_proxy_str)
                self.update_proxy(new_proxy)
                self.queue_log_message(f"代理池刷新完成，选择新代理: {new_proxy_str}")
            else:
                self.queue_log_message("代理池刷新完成，但没有可用的代理")
        except Exception as e:
            self.queue_log_message(f"刷新代理池时发生错误: {str(e)}")

def main():
    root = tk.Tk()
    app = ProxyGUI(root)
    root.mainloop()

if __name__ == "__main__":
    main()