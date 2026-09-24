import unittest

from rw_creature_pet.lizard.config import DebugConfig
from rw_creature_pet.lizard.gait import FootPhase
from rw_creature_pet.shared.geometry import Vec2
from rw_creature_pet.lizard.render import LizardRenderer
from rw_creature_pet.lizard.scene import DebugScene
from tests.lizard.test_wall_observation import placed


class IndependentFeetTests(unittest.TestCase):
    def test_wall_selects_single_leg_from_its_own_grip_geometry(self):
        for index in range(4):
            s = placed()
            for _ in range(100): s.step()
            # 初始抓点由空间分布决定；此测试显式构造轻微落后与接近极限的两种几何。
            foot = s.feet[index]
            foot.position = s.body.chunks[foot.chunk_index].position+Vec2(-10, foot.side*14)
            s.background.set_direction(Vec2(1,0))
            s.step()
            self.assertFalse(any(f.phase == FootPhase.SWING for f in s.feet), '轻微落后不应提前迈小步')
            foot = s.feet[index]
            foot.position = s.body.chunks[foot.chunk_index].position + Vec2(-19, foot.side*14)
            s.step()
            self.assertEqual([i for i,f in enumerate(s.feet) if f.phase == FootPhase.SWING], [index])
            self.assertEqual(s.background.grip_count,3)

    def test_dynamic_leg_frames_apply_to_wall_and_floor(self):
        for flip in (-1,-.5,-.1,.1,.5,1):
            for hind in (False,True):
                self.assertEqual(LizardRenderer.limb_frame(16,1,hind,True,flip),
                                 LizardRenderer.limb_frame(16,1,hind,False,flip))

    def test_low_crawl_and_independent_release_preserve_support(self):
        for direction in (-1,1):
            s = DebugScene(DebugConfig(world_width=1200,world_height=500,floor_y=450))
            s.gait.enabled=True
            s.gait.set_speed(direction*.65)
            for _ in range(180): s.step()
            clearances=[]
            released=set()
            for _ in range(240):
                old=[(f.phase,f.position) for f in s.feet]
                s.step()
                starts=[i for i,(f,(phase,_)) in enumerate(zip(s.feet,old))
                        if f.phase == FootPhase.SWING and phase == FootPhase.STANCE]
                self.assertLessEqual(len(starts),1)
                released.update(starts)
                self.assertGreaterEqual(s.gait.grip_count,2)
                for f,(phase,point) in zip(s.feet,old):
                    if f.phase == phase == FootPhase.STANCE:
                        self.assertEqual(f.position,point)
                middle=s.body.chunks[1]
                clearances.append(s.world.floor_y-middle.position.y-middle.radius)
            self.assertEqual(released,{0,1,2,3})
            self.assertGreaterEqual(min(clearances),-1e-6)
            self.assertLess(max(clearances),1.5)
            s.gait.set_speed(0)
            s.gait.posture='raised'
            for _ in range(600): s.step()
            self.assertGreater(s.body.chunks[2].position.y-s.body.chunks[0].position.y,7)
