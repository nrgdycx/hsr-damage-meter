# -*- coding: utf-8 -*-
"""B 线：HUD 数字的**实时读取**——掩膜/列分割（numpy，无 torch）+ onnxruntime 推理。

为什么不直接调 `read_hud.py`：
  * `read_hud.read_frame(png)` 走的是"**PNG 路径 + PIL 打开整张全屏图**"，
    实时循环里每帧编码/解码 PNG 是纯浪费（抓到的本来就是内存里的 ndarray）。
  * 实时推理要的是 `out/digit_cnn.onnx`（onnxruntime CPU，单字形 0.09ms），
    而 `read_hud.py` 用 torch（A 线的离线评测继续用它）。

一致性保证（铁律：裁剪/掩膜参数必须与 `read_hud.py` 同步）：
  本文件的 `_MASK_*` / `W_MAX` / `H_MIN` / `BAR_ROWS` 与 `read_hud.py` **逐条对应**，
  算法逐行照抄，只把"从 PNG 里读全屏图再裁 `[CY0:CY1, CX0:CX1]`"改成
  "直接给已经裁好的区域 ndarray"。
  是否真的一致由 `verify_B.py` 在**全部 249 张缓存帧**上做逐字形 + 逐位比对（见验收）。
"""
from __future__ import annotations

import os
import sys

import numpy as np
from PIL import Image

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import hud_glyphs as HG  # noqa: E402
from mvp.resource import resource as _res  # noqa: E402  （打包专项：按 exe 位置解析资源）

# ── 掩膜/分割参数：**唯一实现在 hud_glyphs.py**，这里只做转发 ──
# 原来本文件整段抄了一份掩膜+分割代码，靠"改一处必须改两处"的纪律同步。
# A 线这轮改掩膜（辉光层掏空笔画 → 改用核心∪辉光）时就证明了这种纪律不可靠：
# 离线修好了，实时端会静默地继续用旧掩膜读错数。现在两边调同一个函数。
CY0, CY1 = HG.CY0, HG.CY1
CX0, CX1 = HG.CX0, HG.CX1
BAR_ROWS = HG.BAR_ROWS     # 数字左侧细横线所在行带（绝对 y）
W_MAX = HG.W_MAX
H_MIN = HG.H_MIN
GW, GH = 24, 34           # 与 train_digit_cnn.py 一致
CONF_MIN = 0.55           # 与 read_hud.read_frame 默认值一致
MODEL_ONNX = _res("out/digit_cnn.onnx")     # 打包后 = exe 同级或包内解包目录（见 mvp/resource.py）
# 探针：若干真实字形 + 它们在本 .pt 下的 logits。用于**不加载 torch** 就判断
# "实时用的这份 ONNX 跟 .pt 是不是同一个模型"。由 export_onnx_B.py 生成。
PROBE = _res("out/digit_cnn.probe.npz")


def extract_glyphs(rgb, top=CY0, left=CX0, bar_rows=BAR_ROWS):
    """
    从**已裁好的 HUD 区域** ndarray (H, W, 3) RGB 里切出字形。

    返回 [(v, w, h)]，v 是 (GH, GW) float32（0~1），与 read_hud.extract_glyphs 完全一致
    （那边是 torch 张量，这里给 numpy，便于喂 ONNX）。两边都调 hud_glyphs.extract_cropped，
    一致性是结构上保证的，不再靠人同步。`top/left` 是区域左上角在整帧里的绝对坐标。
    """
    return HG.extract_cropped(rgb, top=top, left=left)


class HudOnnxReader:
    """onnxruntime CPU 版 HUD 读数器。单线程、懒加载。"""

    def __init__(self, path=MODEL_ONNX, conf_min=CONF_MIN, threads=1, check_fresh=True,
                 profile=None):
        """`profile=` 指定**字体档案**名（`hud_profiles` 里的键）。

        ⭐ 2026-10-05 加：**一套字体 = 一个分类器**。实时链路要按行动者切档案
        （狼尊强普是像素字体 `yinlang999`），所以这里必须能按档案取对应 ONNX。
        `path` 显式给了就用 `path`；只给 `profile` 就用该档案登记的 ONNX。
        """
        import onnxruntime as ort

        if profile and path == MODEL_ONNX:
            try:
                import hud_profiles as _HP
                cand = _HP.model_path(profile)
                if cand.endswith((".pt", ".onnx")):
                    cand = cand.rsplit(".", 1)[0] + ".onnx"
                if os.path.exists(cand):
                    path = cand
            except Exception:
                pass
        self.path = path
        so = ort.SessionOptions()
        so.intra_op_num_threads = threads
        so.inter_op_num_threads = threads
        so.graph_optimization_level = ort.GraphOptimizationLevel.ORT_ENABLE_ALL
        self.sess = ort.InferenceSession(path, so, providers=["CPUExecutionProvider"])
        self.input = self.sess.get_inputs()[0].name
        self.conf_min = conf_min
        if check_fresh:
            ok, msg = check_model_freshness(path, sess=self.sess)
            if not ok:
                sys.stderr.write("[hud_digits] 警告：%s\n" % msg)

    def classify(self, glyphs):
        """glyphs: extract_glyphs 的输出。返回 [(digit, prob)]。"""
        if not glyphs:
            return []
        x = np.stack([g[0] for g in glyphs])[:, None, :, :].astype(np.float32)
        logits = self.sess.run(None, {self.input: x})[0]
        e = np.exp(logits - logits.max(1, keepdims=True))
        p = e / e.sum(1, keepdims=True)
        idx = p.argmax(1)
        return [(int(i), float(c)) for i, c in zip(idx, p.max(1))]

    def read_region(self, rgb, top=CY0):
        """读一块**已裁好**的 HUD 区域。返回 (数值串, 最低置信度, 明细)。低置信位标 '?'。"""
        glyphs = extract_glyphs(rgb, top=top, left=CX0, bar_rows=BAR_ROWS)
        chars, mins = [], 1.0
        res = self.classify(glyphs)
        for d, c in res:
            chars.append(str(d) if c >= self.conf_min else "?")
            mins = min(mins, c)
        return "".join(chars), (mins if res else 0.0), res

    def read_png(self, png):
        """读全屏帧 PNG（离线对照用，等价于 read_hud.read_frame）。"""
        a = np.asarray(Image.open(png).convert("RGB"))
        return self.read_region(a[CY0:CY1, CX0:CX1], top=CY0)

    def read_screen(self, grabber):
        """实时：直接从抓屏器读（HUD 区域）。"""
        rgb = grabber.grab_rgb(REGION_HUD) if grabber else None
        return self.read_region(rgb, top=CY0)


def vote_readings(readings, ):
    """
    多帧逐位投票（逻辑与 read_hud.vote_frames 完全一致）：
    先按"位数众数"锁定位数，再在同位数内逐位投票。
    readings: [数值串, ...]（空的会被忽略）
    """
    from collections import Counter

    readings = [s for s in readings if s]
    if not readings:
        return None, [], 0
    cnt = Counter(len(s) for s in readings)
    L = cnt.most_common(1)[0][0]
    picked = [s for s in readings if len(s) == L]
    votes = [Counter() for _ in range(L)]
    for s in picked:
        for i, ch in enumerate(s):
            votes[i][ch] += 1
    final = "".join(v.most_common(1)[0][0] if v else "?" for v in votes)
    return final, [dict(v) for v in votes], len(picked)


def check_model_freshness(onnx_path=MODEL_ONNX, sess=None):
    """
    检查实时用的 ONNX 是不是**当前 .pt 的等价产物**。

    为什么必须有这个检查（本会话实测两次踩到）：
      1) 一开始 out/digit_cnn.onnx 比 out/digit_cnn.pt 旧 21 分钟（**旧权重**）：
         同一批字形喂两个模型，argmax 有 4/74 不一致，t=105 直接一个读 4 一个读 6
         （torch 端本来就是 0.59/0.40 的近似平票，任何数值差异都会翻盘）。
      2) 权重同源**也不保险**：A 线 16:47 用 `train_digit_cnn.py` 自己导出的 ONNX
         虽然时间更新，但与同一份 .pt 的 argmax 有 **9/627 不一致**、最大概率差 0.81
         —— 换一个导出路径（opset / dynamo / 外部权重文件）就可能产生不等价的模型。

    判据（按顺序）：
      1. `.pt` 比 `.onnx` 新 => 过期；
      2. 有**探针** `out/digit_cnn.probe.npz`（若干真实字形 + 它们在本 .pt 下的 logits）
         且传入了 onnx session => 直接比对 logits，argmax 必须全一致、最大 logit 差 < 0.1；
      3. 都没有时只看时间，并提示跑 `python export_onnx_B.py --check`。

    返回 (是否新鲜, 说明)。
    """
    import hashlib
    import json

    pt = _res("out/digit_cnn.pt")
    meta_path = onnx_path + ".meta.json"
    if not os.path.exists(pt) or not os.path.exists(onnx_path):
        return True, "缺少 %s 或 %s，跳过新鲜度检查" % (os.path.basename(pt), os.path.basename(onnx_path))
    pt_m, onnx_m = os.path.getmtime(pt), os.path.getmtime(onnx_path)
    if pt_m > onnx_m + 2:      # 2s 容差，避免同一次训练里保存顺序造成的误报
        return False, ("%s 比 %s 新 %.0f 秒：实时端在用旧模型！"
                       "跑 `python export_onnx_B.py` 重新导出。"
                       % (os.path.basename(pt), os.path.basename(onnx_path), pt_m - onnx_m))

    # ── 探针比对：最能说明问题的一步 ──
    if sess is not None and os.path.exists(PROBE):
        try:
            d = np.load(PROBE)
            x, y = d["X"].astype(np.float32), d["Y"]
            got = sess.run(None, {sess.get_inputs()[0].name: x})[0]
            diff = float(np.abs(got - y).max())
            if not np.array_equal(got.argmax(1), y.argmax(1)):
                bad = int((got.argmax(1) != y.argmax(1)).sum())
                return False, ("ONNX 与 .pt **不等价**：%d/%d 个探针字形 argmax 不一致（可能是换了导出方式或权重）；"
                               "跑 `python export_onnx_B.py` 重新导出。" % (bad, len(y)))
            if diff > 0.1:
                return False, ("ONNX 与 .pt 数值偏差过大（最大 logit 差 %.3f）：别用这份 ONNX 做实时推理；"
                               "跑 `python export_onnx_B.py` 重新导出。" % diff)
            return True, ("ONNX 与 .pt 等价（%d 个探针字形 argmax 全一致，最大 logit 差 %.4f）"
                          % (len(y), diff))
        except Exception as e:
            return True, "探针检查出错（按时间看不过期）：%r" % (e,)

    try:
        if os.path.exists(meta_path):
            with open(meta_path, encoding="utf-8") as f:
                meta = json.load(f)
            h = hashlib.sha256()
            with open(pt, "rb") as f:
                for b in iter(lambda: f.read(1 << 20), b""):
                    h.update(b)
            if meta.get("pt_sha256") == h.hexdigest():
                return True, "ONNX 与 .pt 同源（权重哈希已记录；没有探针，未做数值比对）"
            return True, ("ONNX 比 .pt 新，但不是 export_onnx_B.py 导出的；"
                          "要严格确认请跑 `python export_onnx_B.py --check`")
        return True, "ONNX 比 .pt 新（没有哈希记录）；要严格确认请跑 `python export_onnx_B.py --check`"
    except Exception as e:
        return True, "新鲜度检查出错（按时间看不过期）：%r" % (e,)


# 抓屏区域在这里再声明一次，避免 hud_digits 依赖 capture（离线测试时不需要 mss）
REGION_HUD = {"left": CX0, "top": CY0, "width": CX1 - CX0, "height": CY1 - CY0}


if __name__ == "__main__":
    import time

    r = HudOnnxReader()
    KNOWN = {106: "2809", 109: "48076", 134: "47794", 135: "191176", 152: "324751",
             167: "113891", 195: "319195", 100: "121418", 102: "304505"}
    ok = tot = 0
    for t, val in sorted(KNOWN.items()):
        p = os.path.join(HERE, "frames", "glyphcache", "f%08.2f.png" % t)
        if not os.path.exists(p):
            continue
        t0 = time.perf_counter()
        s, c, _ = r.read_png(p)
        dt = (time.perf_counter() - t0) * 1000
        ok += s == val
        tot += 1
        print("   t=%-5s 期望%-9s 读出%-9s %s (最低置信 %.2f, 含读 PNG 共 %.1fms)"
              % (t, val, s, "✓" if s == val else "✗", c, dt))
    print("\nONNX 路径单帧正确率 %d/%d" % (ok, tot))
