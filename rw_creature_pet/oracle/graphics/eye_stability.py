"""眼形保真范围及固定步滞回；不修改真实视线、头部方向或睁闭眼状态"""

# 角度为距最近 90° 轴向的偏差，侧躺和倒立仍沿头部方向显示眼睛
ROLL_HOLD = 8.
ROLL_RELEASE = 24.
ROLL_HYSTERESIS = 2.
# gx 是头部局部横向视线，不是角度；接近侧脸时才恢复原有压缩
YAW_HOLD = .65
YAW_RELEASE = .95
YAW_HYSTERESIS = .025


def axis_delta(angle):
    return (angle+45.) % 90.-45.


def smooth_release(value, start, end):
    t = max(0., min(1., (value-start)/(end-start)))
    return t*t*(3.-2.*t)


def deformation_amount(angle, gx, pose=None):
    roll, yaw = abs(axis_delta(angle)), abs(gx)
    if pose is not None:
        # 快速旋转跨过轴向时，前后帧的偏差可能都很小，而插值中途很大
        # 滞回只能在当前姿态附近生效，不能让旧状态把大角度也锁成正视眼形
        roll = follow_band(pose[0], roll, ROLL_HYSTERESIS)
        yaw = follow_band(pose[1], yaw, YAW_HYSTERESIS)
    return max(smooth_release(roll, ROLL_HOLD, ROLL_RELEASE),
               smooth_release(yaw, YAW_HOLD, YAW_RELEASE))


def follow_band(previous, value, margin):
    """连续滞回：持续慢转仍会跟随，阈值附近的小幅往返不反复重采样"""
    return max(value-margin, min(value+margin, previous))


class EyeStability:
    """只在外观物理步更新；任意数量的绘制、预览和命中检查均只读"""
    def __init__(self, angle=0., gx=0.):
        self.current = self.previous = (abs(axis_delta(angle)), min(1., abs(gx)))

    def step(self, angle, gx):
        self.previous = self.current
        roll, yaw = abs(axis_delta(angle)), min(1., abs(gx))
        # 两端精确归位，正常正视和极端侧视不残留历史偏差
        self.current = (
            roll if roll < 1e-6 or roll > 45.-1e-6 else follow_band(self.current[0], roll, ROLL_HYSTERESIS),
            yaw if yaw < 1e-6 or yaw > 1.-1e-6 else follow_band(self.current[1], yaw, YAW_HYSTERESIS))

    def sample(self, alpha):
        return tuple(a+(b-a)*alpha for a, b in zip(self.previous, self.current))
