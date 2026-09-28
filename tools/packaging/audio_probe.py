"""隔离检查冷缓存、拖动语音以及松手后的真实等待和加速自主活动。"""
import argparse
from dataclasses import replace
from hashlib import sha256
import json
import os
from pathlib import Path
import sys
from time import monotonic
import traceback
import wave


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('output', type=Path)
    parser.add_argument('--seconds', type=float, default=120.)
    parser.add_argument('--simulation-seconds', type=float, default=1800.)
    args = parser.parse_args(argv)
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    os.environ['QT_QPA_PLATFORM'] = 'offscreen'
    report = {'ok': False, 'frozen': bool(getattr(sys, 'frozen', False)),
              'events': [], 'errors': [], 'scope': 'offscreen desktop; programmatic drag; muted real audio'}
    began = monotonic()
    window = None

    def record(kind, **data):
        event = dict(seconds=round(monotonic()-began, 3), kind=kind, **data)
        report['events'].append(event)
        with (output/'events.jsonl').open('a', encoding='utf-8') as stream:
            stream.write(json.dumps(event, ensure_ascii=False)+'\n')

    try:
        from PySide6.QtCore import QEventLoop, QTimer
        from PySide6.QtWidgets import QApplication, QSystemTrayIcon
        from rw_creature_pet.settings_store import SettingsStore
        from rw_creature_pet.oracle.assets import prepare_oracle_assets
        from rw_creature_pet.oracle.desktop import OracleDesktopWindow
        from rw_creature_pet.oracle.voice import BELL_VOICE_CLIPS
        from rw_creature_pet.interaction.audio import QtSoundBackend

        config, _, _ = SettingsStore().startup()
        os.environ['LOCALAPPDATA'] = str(output/'profile')
        config = replace(config, interaction=replace(config.interaction, drag_enabled=True),
                         audio=replace(config.audio, enabled=True, volume=.7),
                         oracle=replace(config.oracle, voice_directory='auto',
                             drag_reactions=replace(config.oracle.drag_reactions, voice_probability=1.)))
        app = QApplication.instance() or QApplication([])
        app.setQuitOnLastWindowClosed(False)
        assets = prepare_oracle_assets(config)
        assert not assets.voice_error, assets.voice_error
        report['clips'] = {}
        for clip in BELL_VOICE_CLIPS:
            path = assets.voice_paths[clip.clip_id]
            with wave.open(str(path), 'rb') as sound:
                duration = sound.getnframes()/sound.getframerate()
                assert abs(duration-clip.duration) < 1/sound.getframerate()
            report['clips'][clip.clip_id] = dict(duration=duration, sha256=sha256(path.read_bytes()).hexdigest())
        record('assets_ready', clips=len(report['clips']))

        QSystemTrayIcon.isSystemTrayAvailable = staticmethod(lambda: True)
        window = OracleDesktopWindow(config, config.desktop.scale, assets=assets)
        window.hide()
        window.tray.hide()
        window.drag_input.hide()
        window.sync_drag_input = lambda: None  # 不采集真实鼠标，使用同一个拖动适配器模拟抓取。
        scene = window.motion.scene
        player = window.voice_player
        scene.set_autonomous(True)

        class TracedSound(QtSoundBackend):
            def __init__(self, parent):
                super().__init__(parent)
                self.effect.setMuted(True)  # 仍进行真实设备加载/播放，只让测试保持安静。
                self.effect.playingChanged.connect(self.changed)
                self.effect.statusChanged.connect(self.status_changed)

            def changed(self):
                record('device_playing', playing=self.effect.isPlaying(),
                       file=self.effect.source().toLocalFile(), drag=scene.drag.active,
                       reacting=scene.drag_reactions.active)

            def status_changed(self):
                record('device_status', status=self.effect.status().name)

            def play(self, path):
                record('play_request', file=path.name, drag=scene.drag.active,
                       reacting=scene.drag_reactions.active, cue=player.current.clip_id)
                super().play(path)

        player._factory = TracedSound

        def wait(seconds):
            loop = QEventLoop()
            QTimer.singleShot(round(seconds*1000), loop.quit)
            loop.exec()
            if player.error:
                raise RuntimeError(player.error)

        record('no_interaction_begin')
        wait(10.)
        assert player._backend is None and scene.drag_reactions.voice.request_count == 0
        assert scene.drag.press(scene.head.position, lambda _: True)
        record('drag_begin')
        wait(8.)
        assert player.play_count > 0, '真实 Qt 播放路径未成功执行'
        scene.drag.release()
        record('drag_release', count=player.play_count)
        expected_requests = scene.drag_reactions.voice.request_count
        expected_plays = len([e for e in report['events'] if e['kind'] == 'play_request'])
        wait(args.seconds)
        assert not scene.drag.active and not scene.drag_reactions.active
        assert scene.drag_reactions.voice.request_count == expected_requests
        assert player.current is None and player._backend.state == 'idle'
        assert len([e for e in report['events'] if e['kind'] == 'play_request']) == expected_plays
        record('wall_clock_idle_complete', waited_seconds=args.seconds)

        window.timer.stop()
        activities = {}
        frames = round(args.simulation_seconds*40)
        for tick in range(frames):
            scene.step()
            player.sync(scene.drag_reactions.voice)
            state = scene.behavior.state.value
            activities[state] = activities.get(state, 0)+1
            assert not scene.drag.active and not scene.drag_reactions.active
            assert scene.drag_reactions.voice.request_count == expected_requests
            if tick % 1200 == 0:
                app.processEvents()
        assert len([e for e in report['events'] if e['kind'] == 'play_request']) == expected_plays
        report.update(ok=True, idle_seconds=args.seconds, simulation_seconds=args.simulation_seconds,
                      simulation_frames=frames, activity_frames=activities,
                      total_voice_requests=expected_requests, total_play_requests=expected_plays,
                      unexpected_play_requests=0)
        record('complete')
    except BaseException:
        report['errors'].append(traceback.format_exc())
    finally:
        if window is not None:
            window.cleanup()
        report['elapsed_seconds'] = round(monotonic()-began, 3)
        (output/'report.json').write_text(json.dumps(report, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')
    return 0 if report['ok'] else 1


if __name__ == '__main__':
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
    raise SystemExit(main())
