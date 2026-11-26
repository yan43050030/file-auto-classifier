# -*- coding: utf-8 -*-
"""后台线程 → 界面线程 的安全通道。

Qt 规定:所有控件只能在界面(主)线程里创建和修改。后台线程直接改日志框、
进度条或弹对话框,在 Windows 上会直接闪退(Segmentation fault)。
这里用"跨线程信号(QueuedConnection)"把要做的事投递回主线程执行。
"""

import threading

from PySide6.QtCore import QObject, Signal, Qt


def in_main_thread() -> bool:
    return threading.current_thread() is threading.main_thread()


class UiBridge(QObject):
    """在主线程创建;post / call_sync 可在任意线程调用。"""

    _call = Signal(object)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._call.connect(self._run, Qt.QueuedConnection)

    @staticmethod
    def _run(fn):
        fn()

    def post(self, fn):
        """异步:把 fn 交给主线程执行,立即返回。"""
        if in_main_thread():
            fn()
        else:
            self._call.emit(fn)

    def call_sync(self, fn):
        """同步:在主线程执行 fn 并等待其返回值(用于弹密码框/预览确认)。"""
        if in_main_thread():
            return fn()
        ev = threading.Event()
        box = [None, None]

        def wrapper():
            try:
                box[0] = fn()
            except BaseException as e:      # 把异常带回调用线程
                box[1] = e
            finally:
                ev.set()

        self._call.emit(wrapper)
        ev.wait()
        if box[1] is not None:
            raise box[1]
        return box[0]
