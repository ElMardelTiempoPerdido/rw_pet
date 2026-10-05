"""前台身份、物理坐标、全屏识别和独立观察时序；无需操控真实窗口。"""
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from rw_creature_pet.interaction.windows import DesktopWindow, ForegroundWindowTracker, WindowsWindowReader
from rw_creature_pet.interaction.window_attention import WindowAttention
from rw_creature_pet.shared.geometry import Bounds, Vec2


def window(handle=10, box=Bounds(100, 100, 900, 700), screen=Bounds(0, 0, 1920, 1080)):
    return DesktopWindow(handle, 99999, box, screen)


class WindowTrackingTests(unittest.TestCase):
    def test_baseline_identity_move_resize_close_and_reactivation(self):
        source = SimpleNamespace(read=Mock(return_value=window()))
        tracker = ForegroundWindowTracker(source)
        self.assertFalse(tracker.poll().changed, '启动时不把现有窗口当作切换')
        source.read.return_value = window(box=Bounds(500, 50, 1100, 600))
        update = tracker.poll()
        self.assertFalse(update.changed)
        self.assertEqual(update.window.center, Vec2(800, 325))
        source.read.return_value = window(11)
        self.assertTrue(tracker.poll().changed)
        source.read.return_value = None
        self.assertTrue(tracker.poll().changed)
        self.assertFalse(tracker.poll().changed)
        source.read.return_value = window(11)
        self.assertTrue(tracker.poll().changed)
        tracker.reset()
        self.assertFalse(tracker.poll().changed)

    def test_fullscreen_uses_full_monitor_center_not_work_area_or_oversized_frame(self):
        screen = Bounds(-1920, -200, 0, 880)
        full = window(box=Bounds(-1928, -208, 1, 881), screen=screen)
        self.assertTrue(full.fullscreen)
        self.assertEqual(full.center, Vec2(-960, 340))
        maximized = window(box=Bounds(-1920, -200, 0, 840), screen=screen)
        self.assertFalse(maximized.fullscreen)
        self.assertEqual(maximized.center, Vec2(-960, 320))

    def test_attention_draws_on_switch_only_tracks_motion_and_has_no_cooldown(self):
        event = WindowAttention(1., 1., (2., 5.))
        self.assertFalse(event.notice((10, 1), Vec2(), changed=False))
        self.assertTrue(event.notice((10, 1), Vec2(10, 20), changed=True))
        first, state = event.remaining, event.random.getstate()
        self.assertTrue(event.opened)
        self.assertTrue(2 <= first <= 5)
        event.step(.5)
        event.notice((10, 1), Vec2(50, 60), changed=False)
        self.assertEqual(event.target, Vec2(50, 60))
        self.assertEqual(event.remaining, first-.5)
        self.assertEqual(event.random.getstate(), state)
        self.assertTrue(event.notice((11, 1), Vec2(), changed=True), '事件中再次切换也可触发')
        event.step(10.)
        self.assertFalse(event.active)
        self.assertTrue(event.notice((12, 1), Vec2(), changed=True), '结束后没有冷却')
        event.probability = 0.
        self.assertFalse(event.notice((13, 1), Vec2(), changed=True))
        self.assertFalse(event.active)
        event.probability = 1.
        event.notice((14, 1), Vec2(), changed=True, enabled=False)
        self.assertFalse(event.active)
        event.notice((14, 1), Vec2(), changed=False)
        self.assertFalse(event.active, '禁用期间的切换不补播')


class NativeWindowReaderTests(unittest.TestCase):
    def reader(self, *, own=False, hidden=False, iconic=False, cloaked=False, fallback=False):
        reader = WindowsWindowReader.__new__(WindowsWindowReader)
        def pid(handle, output):
            import os
            output._obj.value = os.getpid() if own else 99999
            return 1
        def name(handle, output, count):
            output.value = 'ApplicationWindow'
            return len(output.value)
        def monitor(handle, output):
            item = output._obj
            item.screen.left, item.screen.top, item.screen.right, item.screen.bottom = (-1920, 0, 0, 1080)
            item.work.left, item.work.top, item.work.right, item.work.bottom = (-1920, 40, 0, 1080)
            return True
        def rectangle(handle, output):
            item = output._obj
            item.left, item.top, item.right, item.bottom = (-1500, 100, -500, 900)
            return True
        def attribute(handle, attr, output, size):
            if attr == 14:
                output._obj.value = int(cloaked)
            elif attr == 9:
                if fallback:
                    return -1
                rectangle(handle, output)
            return 0
        reader.user = SimpleNamespace(
            SetThreadDpiAwarenessContext=Mock(return_value=123),
            GetForegroundWindow=Mock(return_value=10), GetAncestor=Mock(return_value=10),
            IsWindowVisible=Mock(return_value=not hidden), IsIconic=Mock(return_value=iconic),
            GetWindowThreadProcessId=pid, GetClassNameW=name,
            MonitorFromWindow=Mock(return_value=2), GetMonitorInfoW=monitor, GetWindowRect=Mock(side_effect=rectangle))
        reader.dwm = SimpleNamespace(DwmGetWindowAttribute=attribute)
        return reader

    def test_native_filters_fallback_workarea_and_restores_thread_context(self):
        for options in ({'own': True}, {'hidden': True}, {'iconic': True}, {'cloaked': True}):
            reader = self.reader(**options)
            self.assertIsNone(reader.read())
            self.assertEqual(reader.user.SetThreadDpiAwarenessContext.call_args.args, (123,))
        reader = self.reader(fallback=True)
        self.assertEqual(reader.read().center, Vec2(-1000, 500))
        reader.user.GetWindowRect.assert_called_once()
        self.assertEqual(reader.work_area(77), Bounds(-1920, 40, 0, 1080))
        self.assertEqual(reader.user.SetThreadDpiAwarenessContext.call_args.args, (123,))
        with patch.object(reader.user, 'GetMonitorInfoW', side_effect=RuntimeError('test')):
            with self.assertRaises(RuntimeError):
                reader.read()
        self.assertEqual(reader.user.SetThreadDpiAwarenessContext.call_args.args, (123,))


if __name__ == '__main__':
    unittest.main()
