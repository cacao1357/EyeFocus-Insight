# 1. 激活环境

.venv\Scripts\activate

# 2. S1: FPS 基准测试（坐正，等 2 分钟或按 Q 退出）

python spike/fps_benchmark.py

# 3. S3: 头部姿态验证（跟着屏幕指令做 4 个动作）

python spike/head_pose_proto.py

# 4. S2: 基线校准 ×3（每次 7 秒正常坐姿）

python spike/baseline_proto.py

# 跑完后把 s2_result.json 重命名为 s2_result_1.json

# 再跑 2 次 → s2_result_2.json / s2_result_3.json
