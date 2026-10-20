# 服装固有 PNG 贴图

自定义迭代器在外观细节中提供三个服装贴图槽位，每个可独立选择衣袍、左袖子或右袖子，也可以重复选择同一个部位；后面的槽位覆盖前面的槽位

- 每个槽位只有显示开关、PNG、所属部位、X/Y 偏移，不提供缩放、几何图形、镜像或图层设置
- PNG 最大 128×128 像素、1 MB，保留原色和透明度；导入后使用托管副本
- 在正面直立、自然垂手的参考姿态下，1 个 PNG 像素对应 1 个逻辑像素，不拉伸铺满衣物
- 衣袍以衣料顶端中央为零点，袖子以参考轮廓包围盒上边中央为零点；PNG 顶边中央与零点加偏移重合，X 向右、Y 向下
- 左右指正视参考姿态的画面左右，身体旋转时不交换；两个袖子的贴图不自动镜像
- 运动时沿原有衣料网格分段变形；贴图溢出部位、领口及袖口圆角的部分裁掉，不扩张人偶范围或命中区域
- 图层固定在对应衣物底色上方、领边及相关附加外观下方，沿用袖子、斗篷和项链的现有遮挡关系

三个槽位属于角色外观，切换女仆套装等附加外观不清空它们；Bell 不使用这些槽位。自动保存、角色切换、右键恢复参数及外观/角色导入导出复用现有流程，关闭的槽位也保存引用图片。缺失字段使用各自默认值，不继承上一个角色的配置

实现入口：`oracle/clothing_config.py`、`oracle/graphics/clothing_decals.py`、`oracle/ui/clothing_editor.py`；字段归属在 `presets/fields.py` 显式登记

验证：`python -m unittest tests.oracle.test_clothing_decals tests.oracle.test_clothing_settings`；离屏预览：`python tools/oracle/review_clothing_decals.py`，输出至 `artifacts/clothing-decals`，不使用本机角色库
