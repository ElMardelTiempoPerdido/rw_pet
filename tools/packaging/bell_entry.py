"""Windows 单文件入口；freeze_support 必须早于 Qt / Numba 初始化。"""
import multiprocessing
import sys


if __name__ == '__main__':
    multiprocessing.freeze_support()
    if sys.argv[1:2] == ['--self-test']:
        from frozen_smoke import main
        raise SystemExit(main(sys.argv[2:]))
    if sys.argv[1:2] == ['--audio-probe']:
        from audio_probe import main
        raise SystemExit(main(sys.argv[2:]))
    from rw_creature_pet.app import bell_main
    raise SystemExit(bell_main())
