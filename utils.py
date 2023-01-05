import functools
import json
import os
import sys
from ctypes import windll
from json import JSONDecodeError

# from win32 import win32gui, win32print
import win32api
import win32gui
import win32print
from win32.lib import win32con
# from win32.api import GetSystemMetrics
from win32api import GetSystemMetrics

TimeBeginPeriod = windll.winmm.timeBeginPeriod
HPSleep = windll.kernel32.Sleep
TimeEndPeriod = windll.winmm.timeEndPeriod


def del_dir_tree(path):
    """ 递归删除目录及其子目录,　子文件"""
    if os.path.isfile(path):
        try:
            os.remove(path)
        except Exception as e:
            print(e)
    elif os.path.isdir(path):
        for item in os.listdir(path):
            item_path = os.path.join(path, item)
            del_dir_tree(item_path)
        try:
            os.rmdir(path)  # 删除空目录
        except Exception as e:
            print(e)


def get_resource_path(relative_path):
    if hasattr(sys, '_MEIPASS'):
        return True, os.path.join(sys._MEIPASS, relative_path)
    return False, os.path.join(os.path.abspath("."), relative_path)


def exit_(*args, **kwargs):
    sys.exit(*args, **kwargs)


def milli_sleep(num):
    """比起python自带sleep稍微精准的睡眠"""
    TimeBeginPeriod(1)
    try:
        HPSleep(int(num))  # 减少报错
    except KeyboardInterrupt:
        exit_("已结束")
    TimeEndPeriod(1)


def write(k, v, n, f=None):
    """配置写入"""
    if k:
        if n != 1:
            k_str = f"'{str(k)}': "
        else:
            k_str = str(k) + " = "
    else:
        k_str = ""

    if isinstance(v, dict):
        f.write("%s%s{\n" % ("\t" * n, k_str))
        for local_k, local_v in v.items():
            write(local_k, local_v, n + 1, f)

        f.write("%s}" % ("\t" * n))

    elif isinstance(v, list) or isinstance(v, tuple) or isinstance(v, set):
        start = str(v)[0]
        end = str(v)[-1]
        f.write("%s%s%s\n" % ("\t" * n, k_str, start))
        for local_v in v:
            write(None, local_v, n + 1, f)
        f.write("%s%s" % ("\t" * n, end))
    else:
        if isinstance(v, str):
            v = f"'{v}'"
            f.write("%s%s%s" % ("\t" * n, k_str, v))
        else:
            f.write("%s%s%s" % ("\t" * n, k_str, v))

    if n != 1:
        f.write(",\n")
    else:
        f.write("\n")


def json2py(filename: str):
    """解析 hazedumper 中的 json 为 py"""
    out_file = filename.rsplit(".", 1)[0] + ".py"

    try:
        data = json.load(open(filename, "r"))
    except JSONDecodeError:
        # data = None
        exit_("配置文件解析失败")
    n = 1
    with open(out_file, "w") as f:
        f.write("%sclass Info:\n\n" % ("\t" * (n - 1)))
        for k, v in data.items():
            write(k, v, n, f)


def singleton(cls):
    """单例"""
    __instance = {}

    @functools.wraps(cls)
    def wrapper(x):
        if cls in __instance:
            return __instance[cls]
        else:
            __instance[cls] = cls(x)
            return __instance[cls]

    return wrapper


def get_real_resolution():
    """获取真实的分辨率"""
    hDC = win32gui.GetDC(0)
    # 横向分辨率
    w = win32print.GetDeviceCaps(hDC, win32con.DESKTOPHORZRES)
    # 纵向分辨率
    h = win32print.GetDeviceCaps(hDC, win32con.DESKTOPVERTRES)
    return w, h


def get_screen_size():
    """获取缩放后的分辨率"""
    w = GetSystemMetrics(0)
    h = GetSystemMetrics(1)
    return w, h


def get_window_info():
    """确认窗口句柄与类名"""
    supported_games = 'Valve001 CrossFire LaunchUnrealUWindowsClient LaunchCombatUWindowsClient UnrealWindow UnityWndClass'
    emulator_window = 'BS2CHINAUI Qt5154QWindowOwnDCIcon LSPlayerMainFrame TXGuiFoundation Qt5QWindowIcon LDPlayerMainFrame'
    class_name, hwnd_var, outer_hwnd = None, None, None
    while not hwnd_var:  # 等待游戏窗口出现
        milli_sleep(3000)
        try:
            hwnd_active = win32gui.GetForegroundWindow()
            class_name = win32gui.GetClassName(hwnd_active)
            if class_name not in (supported_games + emulator_window):
                print('请使支持的游戏/程序窗口成为活动窗口...')
                continue
            else:
                outer_hwnd = hwnd_var = win32gui.FindWindow(class_name, None)
                if class_name in emulator_window:
                    hwnd_var = win32gui.FindWindowEx(hwnd_var, None, None, None)
                print('已找到窗口')
        except KeyboardInterrupt:
            exit_("歡迎使用")
        except Exception as e:
            print(e, '您可能正使用沙盒,目前不支持沙盒使用')
            exit_(0)

    return class_name, hwnd_var, outer_hwnd


def get_windows_location():
    """获取对应句柄的窗口位置"""
    # _, _, hwnd, _ = get_window_info()
    rect = win32gui.GetWindowRect(hwnd)
    x = rect[0]
    y = rect[1]
    w = rect[2] - x
    h = rect[3] - y
    return x, y, w, h


def get_hdc(_hwnd=0):
    hwndDC = win32gui.GetWindowDC(_hwnd)  # 根据窗口句柄获取窗口的设备上下文DC（Divice Context）
    return hwndDC


def draw_rect(location, color=(255, 0, 255), line_width=1):
    """绘制方框"""
    x, y, w, h = map(int, location)
    hwndDC = get_hdc(hwnd)
    # # 绘制辅助框 暂时未解决透明问题
    hPen = win32gui.CreatePen(win32con.PS_SOLID, line_width, win32api.RGB(*color))  # 定义框颜色
    win32gui.SelectObject(hwndDC, hPen)
    hbrush = win32gui.GetStockObject(win32con.NULL_BRUSH)  # 定义透明画刷，这个很重要！！
    pre_brush = win32gui.SelectObject(hwndDC, hbrush)
    win32gui.Rectangle(hwndDC, x - 1, y - 1, x + w + 2, y + h + 2)  # 左上到右下的坐标
    win32gui.SelectObject(hwndDC, pre_brush)
    # # 回收资源

    win32gui.DeleteObject(hPen)
    win32gui.DeleteObject(hbrush)
    win32gui.DeleteObject(pre_brush)
    win32gui.ReleaseDC(hwnd, hwndDC)


def draw_line(start, end, color=(255, 255, 0), line_width=1):
    """
    绘制线段
    @param: start 起点坐标
    @param: end 终点坐标
    @param: color 画笔颜色，默认绿色
    """
    start = map(int, start)
    end = map(int, end)

    hwndDC = get_hdc(hwnd)
    # # 绘制辅助框 暂时未解决透明问题
    hPen = win32gui.CreatePen(win32con.PS_SOLID, line_width, win32api.RGB(*color))  # 定义框颜色
    win32gui.SelectObject(hwndDC, hPen)
    win32gui.MoveToEx(hwndDC, *start)
    win32gui.LineTo(hwndDC, *end)
    # # 回收资源
    win32gui.DeleteObject(hPen)
    win32gui.ReleaseDC(hwnd, hwndDC)


def draw_ellipse(left_top, right_bottom, color=(0, 255, 255), line_width=1):
    left_top = map(int, left_top)
    right_bottom = map(int, right_bottom)

    hwndDC = get_hdc(hwnd)
    # # 绘制辅助框 暂时未解决透明问题
    hPen = win32gui.CreatePen(win32con.PS_SOLID, line_width, win32api.RGB(*color))  # 定义框颜色
    win32gui.SelectObject(hwndDC, hPen)

    hbrush = win32gui.GetStockObject(win32con.NULL_BRUSH)  # 定义透明画刷，这个很重要！！
    pre_brush = win32gui.SelectObject(hwndDC, hbrush)
    win32gui.Ellipse(hwndDC, *left_top, *right_bottom)
    win32gui.SelectObject(hwndDC, pre_brush)

    # # 回收资源
    win32gui.DeleteObject(hPen)
    win32gui.DeleteObject(hbrush)
    win32gui.ReleaseDC(hwnd, hwndDC)


def __get_mid_location(loc1, loc2):
    """获取两个坐标的中间坐标"""
    return [
        (loc1[0] + loc2[0]) / 2,
        (loc1[1] + loc2[1]) / 2,
        (loc1[2] + loc2[2]) / 2,
    ]


_, _, hwnd, = get_window_info()
