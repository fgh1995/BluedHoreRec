import os
import requests
from autobahn.asyncio.websocket import WebSocketClientProtocol, WebSocketClientFactory
import asyncio
import threading
import json
import tkinter as tk
from tkinter import ttk, scrolledtext, messagebox
from txaio import make_logger
from threading import Timer
from apscheduler.schedulers.background import BackgroundScheduler
import datetime
import concurrent.futures
import queue
import time
from functools import partial

import models

# 定义礼物对应的豆数
GIFT_VALUES = {
    "神秘人": 38,
    "插画师": 198,
    "医生": 688,
    "拳击手": 2688,
    "机长": 5688,
    "超级影帝": 15888
}


class MyClientProtocol(WebSocketClientProtocol):
    def __init__(self):
        WebSocketClientProtocol.__init__(self)
        self.lucky_gift_timer = None
        self.log = make_logger()
        self.app = None  # 将在工厂中设置

    def onConnect(self, response):
        if self.app:
            self.app.safe_ui_update(self.app.update_status, f"正在连接: {response.peer}")

    def onOpen(self):
        if self.app:
            self.app.protocol = self  # 保存协议引用
            self.app.safe_ui_update(self.app.connection_success)

    def onMessage(self, payload, isBinary):
        if not self.app:
            return

        if isBinary:
            message = f"二进制消息 ({len(payload)} bytes)"
        else:
            # 将消息处理交给线程池
            self.app.thread_pool.submit(self.app.process_message, payload)

    def onClose(self, wasClean, code, reason):
        if self.app:
            self.app.safe_ui_update(self.app.update_status, f"连接关闭: {reason} (code: {code})")
            self.app.safe_ui_update(self.app.reset_connection)


def setup_treeview_sorting(tree):
    """为Treeview添加点击列头排序功能"""

    def treeview_sort_column(tv, col, reverse):
        # 获取列中的所有数据
        l = [(tv.set(k, col), k) for k in tv.get_children('')]

        # 尝试转换为数字排序（如果是数字）
        try:
            l.sort(key=lambda t: int(t[0]), reverse=reverse)
        except ValueError:
            try:
                l.sort(key=lambda t: float(t[0]), reverse=reverse)
            except ValueError:
                l.sort(reverse=reverse)

        # 重新排列项目
        for index, (val, k) in enumerate(l):
            tv.move(k, '', index)

        # 反转下次排序的顺序
        tv.heading(col, command=lambda: treeview_sort_column(tv, col, not reverse))

    # 为每一列绑定排序函数
    for col in tree['columns']:
        tree.heading(col, command=lambda c=col: treeview_sort_column(tree, c, False))


class WebSocketClientApp:
    def __init__(self, root):
        self.result = None
        self.final_text = None
        self.rec_final_text = None
        self.root = root
        self.root.title("WebSocket 客户端")
        self.root.geometry("1280x720")
        self.root.minsize(100, 100)

        self.protocol = None
        self.loop = None
        self.thread = None
        self.connected = False
        self.factory = None
        self.records_data = {}  # 存储所有记录数据
        self.current_records = {}  # 当前显示的记录
        self.auto_analyze = True  # 自动分析标志

        # 创建线程池 (4个工作线程)
        self.thread_pool = concurrent.futures.ThreadPoolExecutor(max_workers=4)

        # 创建消息队列用于线程间通信
        self.message_queue = queue.Queue()

        # 定期检查消息队列
        self.root.after(100, self.process_pending_messages)

        # 创建顶部控制面板
        self.create_control_panel()

        # 创建主内容区域
        self.main_notebook = ttk.Notebook(self.root)
        self.main_notebook.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)

        # 创建消息标签页
        self.create_message_tab()

        # 创建数据分析标签页
        self.create_analysis_tab()

    def process_pending_messages(self):
        """处理来自后台线程的UI更新请求"""
        try:
            while True:
                # 非阻塞获取消息
                callback, args = self.message_queue.get_nowait()
                callback(*args)
        except queue.Empty:
            pass
        finally:
            # 继续定期检查
            self.root.after(100, self.process_pending_messages)

    def safe_ui_update(self, callback, *args):
        """安全地在UI线程中执行回调"""
        self.message_queue.put((callback, args))

    def process_message(self, payload):
        """在后台线程中处理消息"""
        try:
            message = payload.decode('utf8')
            data = json.loads(message)
            msg_type = data.get("msgType")
            msg_extra = data.get("msgExtra", {})

            # 根据消息类型处理
            if msg_type == 28:
                self.handle_exit_message(msg_extra)
            elif msg_type == 1995:
                self.safe_ui_update(self.display_message, "接收", "收到同步数据")
                if msg_extra.get("msgType") == "lotteryRecords":
                    records = msg_extra.get("msgExtra", {})
                    self.safe_ui_update(self.process_records, records)
            elif msg_type == 233:
                parsed_msg = models.LiveMessageParser.convert_special_message(msg_extra)
                self.safe_ui_update(self.display_message, "接收", parsed_msg)
            else:
                self.safe_ui_update(self.display_message, "接收", msg_extra)
        except Exception as e:
            print(f"消息处理出错: {e}")

    def handle_exit_message(self, msg_extra):
        """处理退出消息"""
        try:
            # 发送到vMix的操作放到线程池
            def update_vmix_text(text):
                params = {
                    "Function": "SetText",
                    "Input": "退出直播间消息",
                    "SelectedName": "Text-Title.Text",
                    "Value": text
                }
                try:
                    response = requests.get("http://localhost:8088/api/", params=params, timeout=3)
                    if response.status_code == 200:
                        print(f'vMix更新成功: 退出直播间消息-{response.text}')
                except Exception as e:
                    print(f'vMix API调用失败: 退出直播间消息-{e}')

            # 立即更新
            self.thread_pool.submit(update_vmix_text, msg_extra)

            # 延迟恢复
            def delayed_reset():
                time.sleep(7.0)
                self.thread_pool.submit(update_vmix_text, "欢迎来到夏天的直播间")

            self.thread_pool.submit(delayed_reset)

        except Exception as e:
            print(f"处理退出消息出错: {e}")

    def create_control_panel(self):
        """创建顶部控制面板"""
        control_frame = tk.Frame(self.root, padx=10, pady=5, bd=1, relief=tk.RIDGE)
        control_frame.pack(fill=tk.X, padx=5, pady=5)

        # 第一行：服务器地址和连接控制
        row1 = tk.Frame(control_frame)
        row1.pack(fill=tk.X, pady=2)

        tk.Label(row1, text="服务器地址:").pack(side=tk.LEFT)
        self.server_url = tk.StringVar(value="ws://192.168.2.104:1995")
        tk.Entry(row1, textvariable=self.server_url, width=40).pack(side=tk.LEFT, padx=5)

        self.connect_btn = tk.Button(row1, text="连接", command=self.connect)
        self.connect_btn.pack(side=tk.LEFT, padx=5)

        self.disconnect_btn = tk.Button(row1, text="断开", command=self.disconnect, state=tk.DISABLED)
        self.disconnect_btn.pack(side=tk.LEFT, padx=5)

        tk.Button(row1, text="清空消息", command=self.clear_messages).pack(side=tk.LEFT, padx=5)

        # 第二行：状态显示
        row2 = tk.Frame(control_frame)
        row2.pack(fill=tk.X, pady=2)

        self.status_var = tk.StringVar(value="未连接")
        tk.Label(row2, textvariable=self.status_var, anchor=tk.W).pack(fill=tk.X)

    def create_message_tab(self):
        """创建消息标签页"""
        message_frame = tk.Frame(self.main_notebook)
        self.main_notebook.add(message_frame, text="消息")

        # 消息显示区域
        self.message_area = scrolledtext.ScrolledText(
            message_frame,
            wrap=tk.WORD,
            font=('Microsoft YaHei', 10),
            state='disabled'
        )
        self.message_area.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)

        # 消息发送区域
        send_frame = tk.Frame(message_frame)
        send_frame.pack(fill=tk.X, pady=5)

        tk.Label(send_frame, text="发送消息:").pack(side=tk.LEFT)
        self.message_entry = tk.Entry(send_frame)
        self.message_entry.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=5)
        self.message_entry.bind("<Return>", lambda e: self.send_message())

        tk.Button(send_frame, text="发送", command=self.send_message).pack(side=tk.LEFT)

    def create_analysis_tab(self):
        """创建数据分析标签页"""
        self.rec_final_text = ''
        analysis_frame = tk.Frame(self.main_notebook)
        self.main_notebook.add(analysis_frame, text="数据分析")

        # 控制面板
        control_frame = tk.Frame(analysis_frame, bd=1, relief=tk.RIDGE, padx=5, pady=5)
        control_frame.pack(fill=tk.X, padx=5, pady=5)

        # 自动分析复选框
        auto_frame = tk.Frame(control_frame)
        auto_frame.pack(fill=tk.X, pady=2)
        self.auto_analyze_var = tk.BooleanVar(value=True)
        tk.Checkbutton(auto_frame, text="自动分析", variable=self.auto_analyze_var,
                       command=self.toggle_auto_analyze).pack(side=tk.LEFT)

        # 日期选择
        date_frame = tk.Frame(control_frame)
        date_frame.pack(fill=tk.X, pady=2)
        tk.Label(date_frame, text="选择日期:").pack(side=tk.LEFT)
        self.date_var = tk.StringVar()
        self.date_combobox = ttk.Combobox(date_frame, textvariable=self.date_var, state="readonly")
        self.date_combobox.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=5)
        self.date_combobox.bind("<<ComboboxSelected>>", self.on_date_selected)

        # 文件选择
        file_frame = tk.Frame(control_frame)
        file_frame.pack(fill=tk.X, pady=2)
        tk.Label(file_frame, text="选择文件类型:").pack(side=tk.LEFT)
        self.file_var = tk.StringVar()
        self.file_combobox = ttk.Combobox(file_frame, textvariable=self.file_var, state="readonly")
        self.file_combobox.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=5)
        self.file_combobox.bind("<<ComboboxSelected>>", self.on_file_selected)

        # 分析按钮
        analyze_btn = tk.Button(control_frame, text="分析数据", command=self.analyze_data)
        analyze_btn.pack(pady=5)
        self.filter_var = tk.StringVar()
        self.filter_var.trace("w", self.filter_treeview)  # 当文本变化时自动过滤
        self.filter_entry = tk.Entry(control_frame, textvariable=self.filter_var)
        self.filter_entry.pack(pady=5)
        # 统计信息
        self.summary_var = tk.StringVar()
        summary_label = tk.Label(control_frame, textvariable=self.summary_var,
                                 font=('Microsoft YaHei', 10, 'bold'), anchor=tk.W)
        summary_label.pack(fill=tk.X, pady=5)

        # 结果显示区域
        result_frame = tk.Frame(analysis_frame)
        result_frame.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)

        # 使用Treeview显示结果
        self.result_tree = ttk.Treeview(
            result_frame,
            columns=('time', 'giftType', 'user', 'gift', 'beans', 'count', 'total', 'toAnchor'),
            show='headings'
        )
        # 在创建 Treeview 后添加样式配置
        style = ttk.Style()
        style.configure("Treeview",
                        font=('Microsoft YaHei', 10),
                        rowheight=25,
                        background="#F5F5F5",  # 背景色
                        fieldbackground="#F5F5F5")  # 字段背景色
        style.configure("Treeview.Heading",
                        font=('Microsoft YaHei', 10, 'bold'),
                        background="#4CAF50",  # 表头背景色
                        foreground="black")  # 改为白色文字
        self.result_tree.tag_configure('oddrow', background='#EEDFCC')  # 奇数行颜色
        self.result_tree.tag_configure('evenrow', background='#FFFFFF')  # 偶数行颜色
        style.map("Treeview",
                  background=[('selected', '#4CAF50')],  # 选中行背景色
                  foreground=[('selected', 'white')])  # 选中行文字颜色
        setup_treeview_sorting(self.result_tree)
        self.result_tree.heading('time', text='时间')
        self.result_tree.heading('giftType', text='礼物分类')
        self.result_tree.heading('user', text='用户')
        self.result_tree.heading('gift', text='礼物')
        self.result_tree.heading('beans', text='豆数')
        self.result_tree.heading('count', text='数量/倍数')
        self.result_tree.heading('total', text='总计')
        self.result_tree.heading('toAnchor', text='赠送目标')
        # 修改列配置部分
        self.result_tree.column('time', width=150, anchor=tk.W, minwidth=1)
        self.result_tree.column('giftType', width=150, anchor=tk.W, minwidth=1)
        self.result_tree.column('user', width=150, anchor=tk.W, minwidth=1)
        self.result_tree.column('gift', width=150, anchor=tk.W, minwidth=1)
        self.result_tree.column('beans', width=100, anchor=tk.E, minwidth=1)
        self.result_tree.column('count', width=80, anchor=tk.E, minwidth=1)
        self.result_tree.column('total', width=120, anchor=tk.E, minwidth=1)
        self.result_tree.column('toAnchor', width=150, anchor=tk.W, minwidth=1)
        # 滚动条
        vsb = ttk.Scrollbar(result_frame, orient="vertical", command=self.result_tree.yview)
        hsb = ttk.Scrollbar(result_frame, orient="horizontal", command=self.result_tree.xview)
        self.result_tree.configure(yscrollcommand=vsb.set, xscrollcommand=hsb.set)

        # 布局
        self.result_tree.grid(row=0, column=0, sticky='nsew')
        vsb.grid(row=0, column=1, sticky='ns')
        hsb.grid(row=1, column=0, sticky='ew')

        result_frame.grid_rowconfigure(0, weight=1)
        result_frame.grid_columnconfigure(0, weight=1)

    def filter_treeview(self, *args):
        """优化后的过滤方法"""
        filter_text = self.filter_var.get().lower()
        filter_items = [item.strip() for item in filter_text.split('|')]

        # 在后台线程中执行过滤和准备数据
        def do_filter():
            try:
                # 准备数据
                all_matched_items = []
                output_lines = []

                # 获取当前所有项
                all_items = [(self.result_tree.item(item, "values"),
                              self.result_tree.item(item, "tags"))
                             for item in self.result_tree.get_children()]

                # 过滤数据
                filtered_data = []
                for values, tags in all_items:
                    if any(any(f_item in str(val).lower() for val in values)
                           for f_item in filter_items):
                        filtered_data.append((values, tags))
                # 提取第6个项（倍数）并转换为整数
                multiples = [int(item[0][5]) for item in filtered_data]
                # 找到最大的倍数
                max_multiple = max(multiples)
                # 找到对应的记录
                max_records = [item for item in filtered_data if int(item[0][5]) == max_multiple]
                print("最大的倍数是:", max_multiple)
                print("对应的记录是:")
                for record in max_records:
                    # 提取关键字段
                    time = record[0][0].split()[1]  # 提取时间部分 "21:10:11"
                    anchor_name = record[0][2]  # "90岁风韵犹存你太奶"
                    gift_name = record[0][3]  # "幸运魔镜"
                    multiple = record[0][5]  # "1000"
                    beans = record[0][4]  # "36000"
                    # 拼接成目标文本
                    self.result = f"近期最大出奖 {time} {anchor_name} 抽出 {gift_name} {multiple} 倍 共 {beans} 豆。   "
                # 准备输出文本
                items_to_output = filtered_data[-3:] if len(filtered_data) > 3 else filtered_data
                items_to_output.reverse()
                final_text = self.result
                for values, _ in items_to_output:
                    time_str = values[0]
                    username = values[2]
                    gift = values[3]
                    beans = values[4]
                    multiplier = values[5]
                    formatted_time = time_str.split(" ")[1]

                    line = (f"{formatted_time} [{filter_text}] {username} "
                            f"抽中 {multiplier} 倍 {gift}，获得 {beans} 豆。   ")
                    final_text += line

                # 更新UI
                def update_ui():
                    # 清空并重新插入过滤后的项
                    self.result_tree.delete(*self.result_tree.get_children())
                    for i, (values, tags) in enumerate(filtered_data):
                        self.result_tree.insert("", "end", values=values, tags=tags)

                    # 更新vMix
                    if hasattr(self, 'rec_final_text') and self.rec_final_text != final_text:
                        self.rec_final_text = final_text
                        self.thread_pool.submit(self.update_vmix_text, final_text)

                self.safe_ui_update(update_ui)

            except Exception as e:
                print(f"过滤出错: {e}")

        self.thread_pool.submit(do_filter)

    def update_vmix_text(self, text):
        """更新vMix文本的专用方法"""
        params = {
            "Function": "SetText",
            "Input": "动态滚动1",
            "SelectedName": "Ticker.Text",
            "Value": text
        }
        try:
            response = requests.get("http://localhost:8088/api/", params=params, timeout=3)
            if response.status_code == 200:
                print(f'vMix更新成功: {response.text}')
        except Exception as e:
            print(f'vMix API调用失败: {e}')

    def toggle_auto_analyze(self):
        """切换自动分析状态"""
        self.auto_analyze = self.auto_analyze_var.get()

    def process_records(self, records):
        """处理接收到的记录数据时保持当前选中状态"""
        # 1. 先保存当前选中的日期和文件类型
        current_date = self.date_var.get()
        current_file = self.file_var.get()

        # 2. 更新数据源
        self.records_data = records
        dates = list(records.keys())

        # 3. 更新日期下拉框（保持原有选中项如果仍然存在）
        self.date_combobox['values'] = dates
        if dates:
            # 如果之前选的日期在新数据中仍然存在，就保持选中
            if current_date in dates:
                self.date_var.set(current_date)
            else:  # 否则默认选第一个
                self.date_var.set(dates[0])
            self.on_date_selected()  # 触发日期变更事件

            # 4. 尝试恢复之前选中的文件类型（如果存在）
            if (current_file and
                    current_date in self.records_data and
                    current_file in self.records_data[current_date]):
                self.file_var.set(current_file)
                self.on_file_selected()

            # 5. 如果启用了自动分析，则自动分析数据
            if self.auto_analyze:
                self.analyze_data()

    def on_date_selected(self, event=None):
        """日期选择事件处理"""
        selected_date = self.date_var.get()
        if selected_date in self.records_data:
            self.current_records = self.records_data[selected_date]
            file_types = list(self.current_records.keys())
            self.file_combobox['values'] = file_types
            if file_types:
                self.file_var.set(file_types[0])
                self.on_file_selected()

                # 如果启用了自动分析，则自动分析数据
                if self.auto_analyze:
                    self.analyze_data()

    def on_file_selected(self, event=None):
        """文件类型选择事件处理"""
        selected_file = self.file_var.get()
        if selected_file and self.current_records and selected_file in self.current_records:
            records = self.current_records[selected_file]
            self.display_records(selected_file, records)

            # 如果启用了自动分析，则自动分析数据
            if self.auto_analyze:
                self.analyze_data()

    def display_records(self, file_type, records):
        """显示原始记录"""
        self.display_message("数据分析", f"显示 {file_type} 记录")

    def analyze_data(self):
        """优化后的数据分析方法"""
        selected_date = self.date_var.get()
        selected_file = self.file_var.get()

        if not selected_date or not selected_file or not self.current_records or selected_file not in self.current_records:
            return

        records = self.current_records[selected_file]

        def do_analysis():
            try:
                # 在后台线程中解析数据
                parsed_data = []
                for line in records:
                    if not line.strip():
                        continue
                    messageType = models.LiveMessageParser.determine_message_type(line)
                    if messageType == models.LiveMessageParser.MessageType.ARTIFICE:
                        giftRecord = models.DataAnalyzer.parse_gift_records(line)
                        if giftRecord:
                            parsed_data.append((
                                'gift',
                                (giftRecord.time, giftRecord.gift_type, giftRecord.user,
                                 giftRecord.gift, giftRecord.beans, giftRecord.count,
                                 f"{giftRecord.total:,}", "")
                            ))
                    elif messageType == models.LiveMessageParser.MessageType.MULTIPLIER_REWARD:
                        lotteryRecord = models.DataAnalyzer.parse_lottery_record(line)
                        if lotteryRecord:
                            parsed_data.append((
                                'lottery',
                                (lotteryRecord.time, lotteryRecord.gift_type, lotteryRecord.user,
                                 lotteryRecord.gift, lotteryRecord.beans, lotteryRecord.multiple,
                                 f"{lotteryRecord.beans:,}", "")
                            ))
                    elif messageType == models.LiveMessageParser.MessageType.CHAMELEON_LIFE:
                        eggRecord = models.DataAnalyzer.parse_egg_record(line)
                        if eggRecord:
                            parsed_data.append((
                                'egg',
                                (eggRecord.time, eggRecord.gift_type, eggRecord.user,
                                 eggRecord.gift, eggRecord.beans, eggRecord.count,
                                 f"{eggRecord.beans:,}", f"赠送给 {eggRecord.receiver}")
                            ))

                # 更新UI
                def update_ui():
                    self.result_tree.delete(*self.result_tree.get_children())
                    for i, (item_type, values) in enumerate(parsed_data):
                        tags = ('evenrow',) if i % 2 == 0 else ('oddrow',)
                        self.result_tree.insert("", "end", values=values, tags=tags)
                    self.result_tree.yview_moveto(1.0)
                    self.filter_treeview()

                self.safe_ui_update(update_ui)

            except Exception as e:
                print(f"数据分析出错: {e}")

        self.thread_pool.submit(do_analysis)

    def show_gift_result(self, giftRecord):
        """显示礼物结果"""
        if giftRecord is not None:
            tags = ('evenrow',) if len(self.result_tree.get_children()) % 2 == 0 else ('oddrow',)
            self.result_tree.insert('', 'end', values=(
                giftRecord.time,
                giftRecord.gift_type,
                giftRecord.user,
                giftRecord.gift,
                giftRecord.beans,
                giftRecord.count,
                f"{giftRecord.total:,}",
                ""
            ), tags=tags)

    def show_lottery_result(self, lotteryRecord):
        if lotteryRecord is not None:
            tags = ('evenrow',) if len(self.result_tree.get_children()) % 2 == 0 else ('oddrow',)
            self.result_tree.insert('', 'end', values=(
                lotteryRecord.time,
                lotteryRecord.gift_type,
                lotteryRecord.user,
                lotteryRecord.gift,
                lotteryRecord.beans,
                lotteryRecord.multiple,
                f"{lotteryRecord.beans:,}",
                ""
            ), tags=tags)

    def show_egg_results(self, eggRecord):
        tags = ('evenrow',) if len(self.result_tree.get_children()) % 2 == 0 else ('oddrow',)
        self.result_tree.insert('', 'end', values=(
            eggRecord.time,
            eggRecord.gift_type,
            eggRecord.user,
            eggRecord.gift,
            eggRecord.beans,
            eggRecord.count,
            f"{eggRecord.beans:,}",
            f"赠送给 {eggRecord.receiver}"
        ), tags=tags)

    def connect(self):
        if self.connected:
            return

        url = self.server_url.get().strip()
        if not url:
            messagebox.showerror("错误", "请输入服务器地址")
            return

        self.status_var.set("正在连接...")
        self.connect_btn.config(state=tk.DISABLED)

        # 启动事件循环线程
        self.thread = threading.Thread(target=self.run_client, args=(url,), daemon=True)
        self.thread.start()

    def run_client(self, url):
        self.loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self.loop)

        # 创建工厂并设置应用引用
        self.factory = WebSocketClientFactory(url)
        self.factory.protocol = MyClientProtocol
        self.factory.app = self  # 将应用实例传递给工厂

        try:
            coro = self.loop.create_connection(self.factory, self.factory.host, self.factory.port)
            transport, protocol = self.loop.run_until_complete(coro)

            # 设置协议的应用引用
            protocol.app = self

            self.loop.run_forever()
        except Exception as e:
            self.safe_ui_update(self.update_status, f"连接错误: {str(e)}")
            self.safe_ui_update(self.reset_connection)
        finally:
            if self.loop:
                self.loop.close()

    def connection_success(self):
        self.connected = True
        self.status_var.set("已连接")
        self.connect_btn.config(state=tk.DISABLED)
        self.disconnect_btn.config(state=tk.NORMAL)
        self.display_message("系统", "成功连接到服务器")

        def job():
            message = '同步数据'
            if self.protocol is not None:
                self.protocol.sendMessage(message.encode('utf-8'))

        # 创建后台调度器
        scheduler = BackgroundScheduler()
        scheduler.add_job(job, 'interval', seconds=10)  # 每10秒执行一次
        scheduler.start()

    def disconnect(self):
        if self.connected and self.protocol:
            self.connected = False
            self.status_var.set("正在断开...")
            self.protocol.sendClose()

    def send_message(self):
        if not self.connected or not self.protocol:
            messagebox.showerror("错误", "未连接到服务器")
            return

        message = self.message_entry.get().strip()
        if not message:
            return

        self.message_entry.delete(0, tk.END)
        self.display_message("发送", message)
        self.protocol.sendMessage(message.encode('utf8'))

    def display_message(self, source, message):
        self.message_area.config(state='normal')
        self.message_area.insert(tk.END, f"[{source}] {message}\n")
        self.message_area.config(state='disabled')
        self.message_area.see(tk.END)

    def clear_messages(self):
        self.message_area.config(state='normal')
        self.message_area.delete(1.0, tk.END)
        self.message_area.config(state='disabled')

    def update_status(self, message):
        self.status_var.set(message)

    def reset_connection(self):
        self.connected = False
        self.protocol = None
        self.status_var.set("未连接")
        self.connect_btn.config(state=tk.NORMAL)
        self.disconnect_btn.config(state=tk.DISABLED)
        if self.loop and self.loop.is_running():
            self.loop.call_soon_threadsafe(self.loop.stop())

    def on_closing(self):
        """应用关闭时的清理工作"""
        self.thread_pool.shutdown(wait=False)
        if self.loop and self.loop.is_running():
            self.loop.call_soon_threadsafe(self.loop.stop())
        self.root.destroy()


if __name__ == "__main__":
    root = tk.Tk()
    app = WebSocketClientApp(root)
    root.protocol("WM_DELETE_WINDOW", app.on_closing)
    root.mainloop()
