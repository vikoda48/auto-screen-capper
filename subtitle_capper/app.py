"""
字幕自动截屏工具 —— GUI 入口

使用方法：
    python -m subtitle_capper.app
    或
    python subtitle_capper/app.py

界面包含：
- 保存路径选择
- 「选择字幕区域」按钮（会弹出半透明全屏蒙层，拖拽框选字幕位置）
- 实时预览字幕区域
- 检测灵敏度（差异阈值）与防抖时长调节
- 开始 / 停止 检测按钮
- 截屏数量、最后一次保存路径、运行日志
"""

import os
import sys
import tkinter as tk
from tkinter import filedialog, messagebox, ttk
from typing import Optional, Tuple

from PIL import Image, ImageTk

from .capturer import (
    DEFAULT_COOLDOWN_SECONDS,
    DEFAULT_DIFF_THRESHOLD,
    SubtitleCapturer,
)


# ---------- 温和配色 ----------
BG = "#FAF6F1"          # 奶油米白背景
PANEL = "#FFFFFF"       # 卡片面板
ACCENT = "#E8A87C"      # 柔和暖橘（主按钮）
ACCENT_DARK = "#D48E60"
ACCENT_SOFT = "#FBE8D9"
TEXT = "#4A4540"        # 暖棕文字
TEXT_LIGHT = "#8A837C"
BORDER = "#EDE4D8"
GOOD = "#8FB996"
WARN = "#D9A566"

DEFAULT_SAVE_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "subtitle_shots",
)


# ============================================================
# 全屏区域选择器
# ============================================================
class RegionSelector(tk.Toplevel):
    """
    半透明全屏蒙层，用户拖鼠标框选字幕矩形。
    选完后 result 属性会被置为 (x1,y1,x2,y2) 屏幕坐标；
    按 ESC 或右键取消 -> result = None
    """

    def __init__(self, master: tk.Misc) -> None:
        super().__init__(master)
        self.result: Optional[Tuple[int, int, int, int]] = None

        self.title("框选字幕区域")
        self.attributes("-fullscreen", True)
        self.attributes("-alpha", 0.3)
        self.configure(bg="black")
        self.config(cursor="crosshair")

        # 覆盖所有屏幕的画布
        self.canvas = tk.Canvas(self, bg="black", highlightthickness=0)
        self.canvas.pack(fill="both", expand=True)

        self._start: Optional[Tuple[int, int]] = None
        self._rect_id: Optional[int] = None

        # 顶部提示文字（使用半透明文字）
        self.canvas.create_text(
            0, 0, anchor="nw",
            text="   按住鼠标左键拖拽，框选字幕显示的区域（通常在屏幕底部）；按 ESC 或右键取消。",
            fill="white", font=("Microsoft YaHei", 16, "bold"),
        )

        self.bind("<ButtonPress-1>", self._on_press)
        self.bind("<B1-Motion>", self._on_drag)
        self.bind("<ButtonRelease-1>", self._on_release)
        self.bind("<Button-3>", lambda e: self._cancel())
        self.bind("<Escape>", lambda e: self._cancel())

    def _on_press(self, event: tk.Event) -> None:
        self._start = (event.x_root, event.y_root)
        if self._rect_id is not None:
            self.canvas.delete(self._rect_id)
        self._rect_id = self.canvas.create_rectangle(
            event.x, event.y, event.x, event.y,
            outline=ACCENT, width=3, dash=(4, 2),
        )

    def _on_drag(self, event: tk.Event) -> None:
        if self._start is None or self._rect_id is None:
            return
        # 注意：canvas 里的坐标是相对窗口的，而我们的 result 要用屏幕坐标
        sx = event.x_root - self.winfo_rootx()
        sy = event.y_root - self.winfo_rooty()
        sx0 = self._start[0] - self.winfo_rootx()
        sy0 = self._start[1] - self.winfo_rooty()
        self.canvas.coords(self._rect_id, sx0, sy0, sx, sy)

    def _on_release(self, event: tk.Event) -> None:
        if self._start is None:
            return
        x0, y0 = self._start
        x1, y1 = event.x_root, event.y_root
        if abs(x1 - x0) < 10 or abs(y1 - y0) < 5:
            # 太小，视为误触，允许重选
            self._start = None
            if self._rect_id is not None:
                self.canvas.delete(self._rect_id)
                self._rect_id = None
            return
        self.result = (x0, y0, x1, y1)
        self.attributes("-alpha", 0.0)  # 立即淡出，提升观感
        self.after(80, self.destroy)

    def _cancel(self) -> None:
        self.result = None
        self.destroy()


# ============================================================
# 主应用窗口
# ============================================================
class SubtitleCapperApp:
    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        self.root.title("字幕自动截屏工具")
        self.root.geometry("760x620")
        self.root.minsize(720, 580)
        self.root.configure(bg=BG)

        # ---------- 数据 ----------
        self._save_dir = DEFAULT_SAVE_DIR
        self._region: Optional[Tuple[int, int, int, int]] = None
        self._capturer: Optional[SubtitleCapturer] = None
        self._preview_photo: Optional[ImageTk.PhotoImage] = None
        self._last_preview_ts = 0.0

        self._build_style()
        self._build_ui()
        self._schedule_preview_refresh()

        # 关闭时清理
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)

    # ---------- 样式 ----------
    def _build_style(self) -> None:
        style = ttk.Style(self.root)
        try:
            style.theme_use("clam")
        except tk.TclError:
            pass

        style.configure("TFrame", background=BG)
        style.configure("Panel.TFrame", background=PANEL, relief="flat")

        style.configure(
            "TLabel", background=BG, foreground=TEXT,
            font=("Microsoft YaHei", 10),
        )
        style.configure(
            "Title.TLabel", background=BG, foreground=TEXT,
            font=("Microsoft YaHei", 18, "bold"),
        )
        style.configure(
            "SubTitle.TLabel", background=BG, foreground=TEXT_LIGHT,
            font=("Microsoft YaHei", 9),
        )
        style.configure(
            "PanelLabel.TLabel", background=PANEL, foreground=TEXT,
            font=("Microsoft YaHei", 10),
        )
        style.configure(
            "PanelTitle.TLabel", background=PANEL, foreground=TEXT,
            font=("Microsoft YaHei", 11, "bold"),
        )
        style.configure(
            "Value.TLabel", background=PANEL, foreground=ACCENT_DARK,
            font=("Microsoft YaHei", 11, "bold"),
        )
        style.configure(
            "GoodValue.TLabel", background=PANEL, foreground=GOOD,
            font=("Microsoft YaHei", 11, "bold"),
        )

        style.configure(
            "TScale", background=BG, troughcolor=BORDER,
        )

        style.configure(
            "Accent.TButton",
            background=ACCENT, foreground="white", borderwidth=0,
            font=("Microsoft YaHei", 10, "bold"), padding=(18, 8),
        )
        style.map(
            "Accent.TButton",
            background=[("active", ACCENT_DARK), ("disabled", BORDER)],
            foreground=[("disabled", TEXT_LIGHT)],
        )

        style.configure(
            "Soft.TButton",
            background=ACCENT_SOFT, foreground=ACCENT_DARK, borderwidth=0,
            font=("Microsoft YaHei", 10), padding=(14, 7),
        )
        style.map(
            "Soft.TButton",
            background=[("active", "#F7DBC3")],
        )

    # ---------- UI 构建 ----------
    def _build_ui(self) -> None:
        root = self.root
        root.grid_columnconfigure(0, weight=1)
        root.grid_rowconfigure(1, weight=1)

        # ===== 顶部标题 =====
        header = ttk.Frame(root)
        header.grid(row=0, column=0, sticky="ew", padx=20, pady=(18, 6))
        ttk.Label(header, text="字幕自动截屏工具", style="Title.TLabel").pack(anchor="w")
        ttk.Label(
            header,
            text="看剧时自动检测对白变化并保存截图，解放双手，专注观影 ☕️",
            style="SubTitle.TLabel",
        ).pack(anchor="w", pady=(2, 0))

        # ===== 主体两列 =====
        body = ttk.Frame(root)
        body.grid(row=1, column=0, sticky="nsew", padx=20, pady=10)
        body.grid_columnconfigure(0, weight=3, uniform="col", pad=8)
        body.grid_columnconfigure(1, weight=2, uniform="col", pad=8)
        body.grid_rowconfigure(0, weight=1)

        self._build_left_panel(body)
        self._build_right_panel(body)

    # --- 左侧：配置 + 操作 ---
    def _build_left_panel(self, parent: ttk.Frame) -> None:
        wrap = tk.Frame(parent, bg=PANEL, highlightbackground=BORDER, highlightthickness=1)
        wrap.grid(row=0, column=0, sticky="nsew")
        # 圆角近似效果：内边距
        inner = tk.Frame(wrap, bg=PANEL)
        inner.pack(fill="both", expand=True, padx=18, pady=18)

        # --- 保存路径 ---
        ttk.Label(inner, text="保存目录", style="PanelTitle.TLabel").grid(
            row=0, column=0, sticky="w", columnspan=3,
        )

        self.dir_var = tk.StringVar(value=self._save_dir)
        dir_entry = tk.Entry(
            inner, textvariable=self.dir_var,
            bg=BG, fg=TEXT, borderwidth=0, highlightthickness=1,
            highlightbackground=BORDER, highlightcolor=ACCENT,
            font=("Microsoft YaHei", 10), relief="flat",
        )
        dir_entry.grid(row=1, column=0, columnspan=2, sticky="ew", pady=(6, 14), ipady=6, padx=(0, 8))
        ttk.Button(inner, text="选择…", style="Soft.TButton", command=self._choose_dir).grid(
            row=1, column=2, sticky="ew", pady=(6, 14),
        )

        # --- 字幕区域 ---
        ttk.Label(inner, text="字幕检测区域", style="PanelTitle.TLabel").grid(
            row=2, column=0, sticky="w", columnspan=3,
        )
        self.region_var = tk.StringVar(value="未设置，点击右侧按钮框选屏幕上的字幕区域")
        region_entry = tk.Entry(
            inner, textvariable=self.region_var,
            bg=BG, fg=TEXT_LIGHT, borderwidth=0, highlightthickness=1,
            highlightbackground=BORDER, highlightcolor=ACCENT,
            font=("Microsoft YaHei", 10), readonlybackground=BG, relief="flat", state="readonly",
        )
        region_entry.grid(row=3, column=0, columnspan=2, sticky="ew", pady=(6, 14), ipady=6, padx=(0, 8))
        ttk.Button(inner, text="框选区域", style="Soft.TButton", command=self._choose_region).grid(
            row=3, column=2, sticky="ew", pady=(6, 14),
        )

        # --- 灵敏度参数 ---
        ttk.Label(inner, text="检测灵敏度", style="PanelTitle.TLabel").grid(
            row=4, column=0, sticky="w", columnspan=3, pady=(0, 6),
        )

        ttk.Label(inner, text="差异阈值（越高越不敏感）", style="PanelLabel.TLabel").grid(
            row=5, column=0, sticky="w", columnspan=3,
        )
        self.threshold_var = tk.DoubleVar(value=DEFAULT_DIFF_THRESHOLD)
        self.threshold_label = ttk.Label(
            inner, text=f"{DEFAULT_DIFF_THRESHOLD:.1f}", style="Value.TLabel",
        )
        self.threshold_label.grid(row=5, column=2, sticky="e")
        thr_scale = ttk.Scale(
            inner, from_=1.0, to=25.0, orient="horizontal",
            variable=self.threshold_var,
            command=lambda v: self.threshold_label.configure(text=f"{float(v):.1f}"),
        )
        thr_scale.grid(row=6, column=0, columnspan=3, sticky="ew", pady=(4, 14))

        ttk.Label(inner, text="防抖（连拍冷却秒数）", style="PanelLabel.TLabel").grid(
            row=7, column=0, sticky="w", columnspan=3,
        )
        self.cooldown_var = tk.DoubleVar(value=DEFAULT_COOLDOWN_SECONDS)
        self.cooldown_label = ttk.Label(
            inner, text=f"{DEFAULT_COOLDOWN_SECONDS:.1f}s", style="Value.TLabel",
        )
        self.cooldown_label.grid(row=7, column=2, sticky="e")
        cd_scale = ttk.Scale(
            inner, from_=0.3, to=6.0, orient="horizontal",
            variable=self.cooldown_var,
            command=lambda v: self.cooldown_label.configure(text=f"{float(v):.1f}s"),
        )
        cd_scale.grid(row=8, column=0, columnspan=3, sticky="ew", pady=(4, 18))

        # --- 控制按钮 ---
        btn_row = tk.Frame(inner, bg=PANEL)
        btn_row.grid(row=9, column=0, columnspan=3, sticky="ew", pady=(0, 12))
        btn_row.grid_columnconfigure(0, weight=1)
        btn_row.grid_columnconfigure(1, weight=1)

        self.start_btn = ttk.Button(
            btn_row, text="▶ 开始检测", style="Accent.TButton", command=self._start_capture,
        )
        self.start_btn.grid(row=0, column=0, sticky="ew", padx=(0, 6), ipady=4)
        self.stop_btn = ttk.Button(
            btn_row, text="■ 停止", style="Soft.TButton", command=self._stop_capture, state="disabled",
        )
        self.stop_btn.grid(row=0, column=1, sticky="ew", padx=(6, 0), ipady=4)

        # --- 状态 ---
        status_wrap = tk.Frame(inner, bg=BG, highlightbackground=BORDER, highlightthickness=1)
        status_wrap.grid(row=10, column=0, columnspan=3, sticky="nsew", pady=(4, 0))
        inner.grid_rowconfigure(10, weight=1)
        inner.grid_columnconfigure(0, weight=1)
        inner.grid_columnconfigure(1, weight=1)
        inner.grid_columnconfigure(2, weight=0)

        status_inner = tk.Frame(status_wrap, bg=BG)
        status_inner.pack(fill="both", expand=True, padx=12, pady=10)
        status_inner.grid_columnconfigure(1, weight=1)

        ttk.Label(status_inner, text="状态：", background=BG, foreground=TEXT_LIGHT,
                  font=("Microsoft YaHei", 10)).grid(row=0, column=0, sticky="w", pady=2)
        self.status_var = tk.StringVar(value="待机中")
        self.status_label = tk.Label(
            status_inner, textvariable=self.status_var,
            bg=BG, fg=TEXT_LIGHT, font=("Microsoft YaHei", 10, "bold"), anchor="w",
        )
        self.status_label.grid(row=0, column=1, sticky="ew", pady=2)

        ttk.Label(status_inner, text="已保存：", background=BG, foreground=TEXT_LIGHT,
                  font=("Microsoft YaHei", 10)).grid(row=1, column=0, sticky="w", pady=2)
        self.count_var = tk.StringVar(value="0 张")
        tk.Label(status_inner, textvariable=self.count_var,
                 bg=BG, fg=ACCENT_DARK, font=("Microsoft YaHei", 10, "bold"), anchor="w",
                 ).grid(row=1, column=1, sticky="ew", pady=2)

        ttk.Label(status_inner, text="当前差异：", background=BG, foreground=TEXT_LIGHT,
                  font=("Microsoft YaHei", 10)).grid(row=2, column=0, sticky="w", pady=2)
        self.diff_var = tk.StringVar(value="—")
        tk.Label(status_inner, textvariable=self.diff_var,
                 bg=BG, fg=TEXT, font=("Microsoft YaHei", 10, "bold"), anchor="w",
                 ).grid(row=2, column=1, sticky="ew", pady=2)

        ttk.Label(status_inner, text="最后保存：", background=BG, foreground=TEXT_LIGHT,
                  font=("Microsoft YaHei", 10)).grid(row=3, column=0, sticky="nw", pady=2)
        self.last_file_var = tk.StringVar(value="—")
        tk.Label(status_inner, textvariable=self.last_file_var,
                 bg=BG, fg=GOOD, font=("Microsoft YaHei", 9), anchor="w", justify="left",
                 wraplength=280,
                 ).grid(row=3, column=1, sticky="ew", pady=2)

        # --- 日志 ---
        log_wrap = tk.Frame(inner, bg=PANEL)
        log_wrap.grid(row=11, column=0, columnspan=3, sticky="ew", pady=(10, 0))
        ttk.Label(log_wrap, text="运行日志", style="PanelTitle.TLabel").pack(anchor="w")
        self.log_text = tk.Text(
            log_wrap, height=6, bg=BG, fg=TEXT, borderwidth=0,
            highlightthickness=1, highlightbackground=BORDER,
            font=("Consolas", 9), relief="flat", wrap="word", state="disabled",
        )
        self.log_text.pack(fill="x", pady=(6, 0))

    # --- 右侧：预览 ---
    def _build_right_panel(self, parent: ttk.Frame) -> None:
        wrap = tk.Frame(parent, bg=PANEL, highlightbackground=BORDER, highlightthickness=1)
        wrap.grid(row=0, column=1, sticky="nsew")
        inner = tk.Frame(wrap, bg=PANEL)
        inner.pack(fill="both", expand=True, padx=18, pady=18)
        inner.grid_rowconfigure(1, weight=1)
        inner.grid_columnconfigure(0, weight=1)

        ttk.Label(inner, text="字幕区域实时预览", style="PanelTitle.TLabel").grid(
            row=0, column=0, sticky="w", pady=(0, 8),
        )

        self.preview_frame = tk.Frame(inner, bg=BG, highlightbackground=BORDER, highlightthickness=1)
        self.preview_frame.grid(row=1, column=0, sticky="nsew")
        self.preview_canvas = tk.Canvas(
            self.preview_frame, bg=BG, highlightthickness=0,
        )
        self.preview_canvas.pack(fill="both", expand=True, padx=6, pady=6)

        self._draw_preview_placeholder()

        tip = ttk.Label(
            inner,
            text="💡 使用小贴士\n"
                 "1. 把播放器窗口调到字幕稳定的位置，再框选字幕条。\n"
                 "2. 默认参数适合大多数视频；如果误触发多，把差异阈值调高。\n"
                 "3. 如果漏拍快切镜头，把防抖调到 0.5s 左右。",
            style="PanelLabel.TLabel", justify="left",
        )
        tip.grid(row=2, column=0, sticky="ew", pady=(14, 0))

    def _draw_preview_placeholder(self) -> None:
        self.preview_canvas.delete("all")
        cw = self.preview_canvas.winfo_width() or 360
        ch = self.preview_canvas.winfo_height() or 240
        self.preview_canvas.create_rectangle(0, 0, cw, ch, outline="", fill=BG)
        self.preview_canvas.create_text(
            cw / 2, ch / 2 - 10,
            text="未设置字幕区域",
            fill=TEXT_LIGHT, font=("Microsoft YaHei", 12),
        )
        self.preview_canvas.create_text(
            cw / 2, ch / 2 + 16,
            text="点击左侧「框选区域」开始",
            fill=BORDER, font=("Microsoft YaHei", 10),
        )

    # ---------- 交互逻辑 ----------
    def _choose_dir(self) -> None:
        path = filedialog.askdirectory(
            title="选择截图保存目录",
            initialdir=self._save_dir,
        )
        if path:
            self._save_dir = path
            self.dir_var.set(path)
            # 如果已经在运行，同步更新 capturer 的目录
            if self._capturer is not None:
                self._capturer.save_dir = path
                os.makedirs(path, exist_ok=True)

    def _choose_region(self) -> None:
        if self._capturer and self._capturer.is_running():
            messagebox.showinfo("检测中", "检测正在运行，停止后再重新框选区域哦～")
            return

        # 最小化主窗口，让用户看得清屏幕，再弹出选择器
        self.root.iconify()
        self.root.update()
        self.root.after(200, self._open_region_selector)

    def _open_region_selector(self) -> None:
        selector = RegionSelector(self.root)
        self.root.wait_window(selector)
        self.root.deiconify()
        if selector.result is None:
            return  # 用户取消
        self._region = selector.result
        x1, y1, x2, y2 = self._region
        w, h = abs(x2 - x1), abs(y2 - y1)
        self.region_var.set(f"屏幕坐标 ({x1},{y1}) — ({x2},{y2})  尺寸 {w}×{h}")

    def _start_capture(self) -> None:
        self._save_dir = self.dir_var.get().strip() or DEFAULT_SAVE_DIR
        if self._region is None:
            messagebox.showwarning("缺少区域", "请先点击「框选区域」选择字幕所在的屏幕位置～")
            return
        try:
            os.makedirs(self._save_dir, exist_ok=True)
        except OSError as e:
            messagebox.showerror("保存目录错误", f"无法创建保存目录：\n{e}")
            return

        self._capturer = SubtitleCapturer(
            save_dir=self._save_dir,
            region=self._region,
            diff_threshold=float(self.threshold_var.get()),
            cooldown_seconds=float(self.cooldown_var.get()),
        )
        self._capturer.on_capture = self._on_capture
        self._capturer.on_tick = self._on_tick
        self._capturer.on_error = self._on_error

        try:
            self._capturer.start()
        except ValueError as e:
            messagebox.showerror("启动失败", str(e))
            return

        self.start_btn.configure(state="disabled")
        self.stop_btn.configure(state="normal")
        self.status_var.set("运行中 · 正在监测字幕变化…")
        self.status_label.configure(fg=GOOD)
        self._append_log("▶ 开始检测，截图将保存到：" + self._save_dir)

    def _stop_capture(self) -> None:
        if self._capturer is not None:
            self._capturer.stop()
        self.start_btn.configure(state="normal")
        self.stop_btn.configure(state="disabled")
        self.status_var.set("已停止")
        self.status_label.configure(fg=WARN)
        self._append_log("■ 已停止检测，共保存 " + str(self._capturer.capture_count if self._capturer else 0) + " 张截图。")

    # ---------- capturer 回调（在后台线程触发，需切回主线程） ----------
    def _on_capture(self, filepath: str, count: int) -> None:
        self.root.after(0, lambda: self._update_on_capture(filepath, count))

    def _update_on_capture(self, filepath: str, count: int) -> None:
        self.count_var.set(f"{count} 张")
        self.last_file_var.set(filepath)
        self._append_log(f"📸 已保存: {os.path.basename(filepath)}")

    def _on_tick(self, diff: float, changed: bool) -> None:
        self.root.after(0, lambda: self._update_diff(diff, changed))

    def _update_diff(self, diff: float, changed: bool) -> None:
        self.diff_var.set(f"{diff:.2f}" + ("  ✨变化" if changed else ""))

    def _on_error(self, e: Exception) -> None:
        self.root.after(0, lambda: self._append_log(f"[错误] {type(e).__name__}: {e}"))

    # ---------- 其它 ----------
    def _append_log(self, line: str) -> None:
        self.log_text.configure(state="normal")
        self.log_text.insert("end", line + "\n")
        self.log_text.see("end")
        self.log_text.configure(state="disabled")

    def _schedule_preview_refresh(self) -> None:
        self._refresh_preview()
        self.root.after(300, self._schedule_preview_refresh)  # 每 300ms 刷一次预览

    def _refresh_preview(self) -> None:
        # 选择器没有设置区域或 capturer 没准备好，画占位
        region = self._region
        if region is None:
            self._draw_preview_placeholder()
            return

        try:
            x1, y1, x2, y2 = region
            from PIL import ImageGrab
            img = ImageGrab.grab(bbox=(x1, y1, x2, y2), all_screens=True)
        except Exception:
            self._draw_preview_placeholder()
            return

        cw = self.preview_canvas.winfo_width() or 360
        ch = self.preview_canvas.winfo_height() or 240
        if cw < 20 or ch < 20:
            return
        img.thumbnail((cw - 4, ch - 4), Image.Resampling.BILINEAR)

        self._preview_photo = ImageTk.PhotoImage(img)
        self.preview_canvas.delete("all")
        self.preview_canvas.create_rectangle(0, 0, cw, ch, outline="", fill=BG)
        self.preview_canvas.create_image(cw / 2, ch / 2, image=self._preview_photo)

    def _on_close(self) -> None:
        if self._capturer is not None and self._capturer.is_running():
            if not messagebox.askokcancel("退出", "检测还在跑呢，确认退出吗？"):
                return
            self._capturer.stop()
        self.root.destroy()


def main() -> None:
    import sys
    # PyInstaller 打包为窗口模式(console=False)时，sys.stdout/stderr 为 None，
    # 只有在存在控制台时才需要重配置编码。
    if getattr(sys.stdout, "reconfigure", None) is not None:
        try:
            sys.stdout.reconfigure(encoding="utf-8")
        except Exception:  # noqa: BLE001
            pass
    if getattr(sys.stderr, "reconfigure", None) is not None:
        try:
            sys.stderr.reconfigure(encoding="utf-8")
        except Exception:  # noqa: BLE001
            pass

    root = tk.Tk()
    try:
        # 高分屏适配，Windows 下才生效
        from ctypes import windll  # type: ignore
        windll.shcore.SetProcessDpiAwareness(1)
    except Exception:  # noqa: BLE001
        pass
    SubtitleCapperApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
