"""
截屏与字幕变化检测核心模块

核心原理：
1. 定期截取用户框选的字幕区域图像（灰度化缩小后）
2. 计算当前帧与上一帧的像素差异度
3. 差异超过阈值 -> 判定字幕发生变化 -> 保存全屏截图
4. 防抖窗口（cooldown）内重复变化只保存一次，避免同一条对白被连拍
"""

import os
import time
import threading
from datetime import datetime
from typing import Callable, Optional, Tuple

from PIL import Image, ImageChops, ImageGrab


# 字幕区域检测的默认参数
DEFAULT_CHECK_INTERVAL = 0.25      # 字幕采样间隔：每 0.25 秒看一次，人眼感受流畅
DEFAULT_DIFF_THRESHOLD = 4.0       # 平均像素差异阈值（0~255），越高越不敏感
DEFAULT_COOLDOWN_SECONDS = 1.5     # 防抖：两次截屏之间至少间隔 1.5 秒
DEFAULT_PREVIEW_MAX_SIZE = 320     # 预览缩略图最大边长（像素）

# 内部比较时使用的统一尺寸，缩小可加快比较速度、过滤噪点
_COMPARE_W = 480
_COMPARE_H = 80


def _normalize_region(bbox: Tuple[int, int, int, int]) -> Optional[Tuple[int, int, int, int]]:
    """标准化字幕区域坐标，保证 x1<x2, y1<y2，且宽高都为正"""
    x1, y1, x2, y2 = bbox
    nx1, nx2 = sorted((x1, x2))
    ny1, ny2 = sorted((y1, y2))
    w, h = nx2 - nx1, ny2 - ny1
    if w < 10 or h < 5:
        return None
    return (nx1, ny1, nx2, ny2)


def _prepare_for_compare(img: Image.Image) -> Image.Image:
    """把字幕区域处理成统一小尺寸灰度图，用于快速比较"""
    gray = img.convert("L")
    return gray.resize((_COMPARE_W, _COMPARE_H), Image.Resampling.BILINEAR)


def _calc_avg_diff(a: Image.Image, b: Image.Image) -> float:
    """计算两帧之间的平均像素差异（0~255）"""
    diff = ImageChops.difference(a, b)
    # 用 histogram 快速统计总和，避免逐像素遍历
    hist = diff.histogram()
    total = sum(i * v for i, v in enumerate(hist))
    pixels = a.width * a.height
    return total / pixels if pixels > 0 else 0.0


class SubtitleCapturer:
    """字幕自动截屏器

    使用示例：
        cap = SubtitleCapturer(save_dir="./shots", region=(0, 900, 1920, 1080))
        cap.on_capture = lambda path, idx: print(f"已保存: {path}")
        cap.start()
        ...
        cap.stop()
    """

    def __init__(
        self,
        save_dir: str,
        region: Optional[Tuple[int, int, int, int]] = None,
        check_interval: float = DEFAULT_CHECK_INTERVAL,
        diff_threshold: float = DEFAULT_DIFF_THRESHOLD,
        cooldown_seconds: float = DEFAULT_COOLDOWN_SECONDS,
    ) -> None:
        self.save_dir = save_dir
        self.check_interval = check_interval
        self.diff_threshold = diff_threshold
        self.cooldown_seconds = cooldown_seconds

        self._region = _normalize_region(region) if region else None
        self._running = False
        self._thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()
        self._last_capture_time = 0.0
        self._last_frame: Optional[Image.Image] = None
        self._capture_count = 0

        # 回调钩子，方便 GUI 更新状态
        self.on_capture: Optional[Callable[[str, int], None]] = None
        self.on_tick: Optional[Callable[[float, bool], None]] = None
        self.on_error: Optional[Callable[[Exception], None]] = None

        os.makedirs(self.save_dir, exist_ok=True)

    # ---------- 配置 ----------

    @property
    def region(self) -> Optional[Tuple[int, int, int, int]]:
        return self._region

    @region.setter
    def region(self, value: Optional[Tuple[int, int, int, int]]) -> None:
        if value is None:
            self._region = None
        else:
            self._region = _normalize_region(value)
        # 区域切换后重置上一帧，避免旧残留触发误判
        self._last_frame = None

    @property
    def capture_count(self) -> int:
        return self._capture_count

    # ---------- 生命周期 ----------

    def is_running(self) -> bool:
        return self._running

    def start(self) -> bool:
        if self._running:
            return False
        if self._region is None:
            raise ValueError("未设置字幕检测区域，请先在屏幕上框选字幕位置")
        self._running = True
        self._stop_event.clear()
        self._last_capture_time = 0.0
        self._last_frame = None
        self._capture_count = 0
        self._thread = threading.Thread(target=self._run_loop, name="capture_loop", daemon=True)
        self._thread.start()
        return True

    def stop(self) -> None:
        if not self._running:
            return
        self._running = False
        self._stop_event.set()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=2.0)
        self._thread = None

    # ---------- 核心循环 ----------

    def _run_loop(self) -> None:
        while not self._stop_event.is_set():
            try:
                changed, diff = self._tick_once()
                if self.on_tick:
                    self.on_tick(diff, changed)
            except Exception as e:  # noqa: BLE001 - 捕获给 GUI 展示，避免后台线程崩
                if self.on_error:
                    self.on_error(e)
            # 使用 wait 代替 sleep，让 stop() 可以立即唤醒退出
            self._stop_event.wait(timeout=self.check_interval)

    def _tick_once(self) -> Tuple[bool, float]:
        """执行一次采样：返回 (是否触发了截屏, 本次差异值)"""
        assert self._region is not None
        x1, y1, x2, y2 = self._region

        # 1. 截取字幕区域（用于比较）
        region_img = ImageGrab.grab(bbox=(x1, y1, x2, y2), all_screens=True)
        current = _prepare_for_compare(region_img)

        if self._last_frame is None:
            # 初始化帧，第一次不触发截屏
            self._last_frame = current
            return False, 0.0

        diff = _calc_avg_diff(self._last_frame, current)
        changed = False

        now = time.time()
        if (
            diff >= self.diff_threshold
            and now - self._last_capture_time >= self.cooldown_seconds
        ):
            self._save_fullscreen()
            self._last_capture_time = now
            changed = True

        # 无论是否保存，都更新上一帧（这样同一句字幕的轻微抖动不会反复触发）
        self._last_frame = current
        return changed, diff

    # ---------- 保存 ----------

    def _save_fullscreen(self) -> None:
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")[:-3]
        filename = f"subtitle_{timestamp}.png"
        filepath = os.path.join(self.save_dir, filename)

        shot = ImageGrab.grab(all_screens=True)
        shot.save(filepath, format="PNG", optimize=True)

        self._capture_count += 1
        if self.on_capture:
            try:
                self.on_capture(filepath, self._capture_count)
            except Exception:  # noqa: BLE001 - 回调异常不影响主循环
                pass

    # ---------- 给 GUI 预览用 ----------

    def make_preview(self) -> Optional[Image.Image]:
        """抓一张当前字幕区域的缩略图，给 GUI 实时预览用"""
        if self._region is None:
            return None
        try:
            x1, y1, x2, y2 = self._region
            img = ImageGrab.grab(bbox=(x1, y1, x2, y2), all_screens=True)
            img.thumbnail((DEFAULT_PREVIEW_MAX_SIZE, DEFAULT_PREVIEW_MAX_SIZE), Image.Resampling.BILINEAR)
            return img
        except Exception:  # noqa: BLE001
            return None
