# -*- coding: utf-8 -*-
"""录屏 → 自动挖角色 → **按角色名**出核对表（而不是按时间轴）。

用户 2026-10-03 的要求：
    "我往里面丢录屏，然后你自行分别，然后给我看是不是而不是哪些是，
     按照角色名字分而不是时间轴"

用法
----
    python tools/axis/harvest_characters.py --video "records/xxx.mp4" --team 我的队

流程（每一步都有已实测依据）
--------------------------
  1. **抽帧**：按 --fps 抽（默认 5fps = 0.2s —— 角色行动只有 1~2 秒，1fps 会大面积漏采）
     ⚠️ 两种实现，`--mode` 选：
       * `fast`（默认）：**单次解码**整片，用 crop 只切"标记+卡"那一小块。
         实测本类录屏（21 Mbps 2880x1800）逐帧 `-ss` seek 要 **1.19 秒/帧**
         （每次都得从关键帧解起）→ 12 分钟录屏 74 分钟；改成单次解码后
         **30 秒素材 4.3 秒**（约 20 倍）。注意这个精简版 ffmpeg **没有 fps/select 滤镜**，
         降采样必须用**输出选项 `-r`**（实测可用），用滤镜会报 'No option name near'。
       * `seek`：逐帧 `-ss`（老路径，慢但语义最直白），用于和 fast 做等价性对照。
  2. **判战斗帧**：左标记必须是 `ally_*`（青点/青星/菱形）
     —— 用户确认过的样本上 100% 正确；战斗外的换队板/暂停界面一律跳过
  3. **质量闸**：卡面梯度 ≥ GRAD_MIN 且彩色占比 ≥ COL_MIN（排除空槽/纯色 UI）
  4. **分组**：同类特征加权 NCC 贪心聚类（把"同一个人"归到一起）
  5. **认名**：每组与**共享模板库**比对；足够像就写该角色名，否则标「新角色」
  6. **出表**：`samples/<队名>_角色核对.png` —— **按角色名分栏**，每栏给
     代表图、张数、若干样本、以及"我认为这是谁 / 是新角色"

用户只需看图回答「是/不是」，不用对时间轴、不用编号。
"""

import ffmpeg_path as _ffmpeg_path
_FF_CANDIDATES_TUPLE = _ffmpeg_path._FALLBACKS
import argparse
import glob
import json
import os
import subprocess
import sys
import time

import cv2
import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

import axis_actor as T      # noqa: E402
from mvp.resource import resource as _res   # noqa: E402

# ── 默认几何（以参考分辨率 2876×1798 为基准；本录屏 2880×1800 实测一致）──
#   行动卡：用户确认过的框 (82,78)-(281,178)
#   标记区：卡左侧那一带，含标记中心 (86,127)
CARD_BOX = (82, 78, 281, 178)
MARK_BOX = (40, 66, 300, 196)
#   ⚠️ 卡框的**左上角在基准坐标系里的位置**。取头像区时必须减掉它 ——
#   否则会拿"整张卡（含边框/标记/周围 UI）"去做特征，与库内模板口径不一致，
#   实测会把正确角色从 1.90 打到 0.70（**踩过：导致全部认错**）。
CROP_ORIGIN = (82, 78)

# ── 质量闸（阈值来历见 docs/任意队伍适配.md §12 与 §13.12）──
# ⚠️ 12.0 → 6.5：12 卡在"我方卡梯度最小值"之上，会把**平滑的召唤物**当空槽丢掉。
#    实测（复杂情况全片抽样）：空槽/非战斗帧梯度中位 **0.2**、90 分位 7.8；
#    我方卡中位 17.4、最小 10.0。而**龙灵（丹恒•腾荒的召唤物）只有 6.9~10.6**
#    —— 金龙是一大片平滑金色，梯度天然低，被 12.0 误杀（标记闸是过的）。
#    放到 6.5 后龙灵能进；空槽那一侧本来就被**标记闸**挡着（empty/none 不会以 ally 开头）。
GRAD_MIN = 6.5         # 卡面梯度能量：低于此多为空槽/纯色界面
COL_MIN = 0.30         # 彩色像素占比：低于此多为 UI 板
# ── 认名闸 ──
#   这里**不是**识别器的两道闸（0.90/0.45）。本工具的目的是"分栏给用户核对"，
#   但**不能把猜出来的名字当结论**：
#     旧录屏（库覆盖该录屏）认对时是 **1.70~1.90**；
#     第三段录屏（164043）全库最高只有 **1.25**，而 0.85 的线会把 0.9~1.1 的
#     "最像谁"输出成名字 —— 实测 17 个名字**逐张看图全是错的**（见
#     samples/_诊断_同名对照.png）。所以线定在 1.45：分不清就弃权。
NAME_THR = 1.45        # 与库内某角色的分数下限（低于此一律进「新角色?」栏）
NAME_MARGIN = 0.05     # 与第二名的分差下限
LOW_CONF = 1.60        # 低于此分标「低置信，请重点核对」
# ── 分组阈值（贪心代表聚类；越大越细）──
#   口径是 `pair_score_shift`（位移容忍）：自比 1.900；实测"同一个人"跨战斗 1.4~1.55、
#   同一场战斗内 1.6~1.9；"不同的人" ≤1.0~1.1。所以 1.30 落在两带之间的空档里。
CLUSTER_THR = 1.30
# ── 未认出卡的二次分组阈值 ──
#   认不出名字的卡如果全塞进一栏，用户就没法回答"是/不是"（实测一段素材能攒出
#   上百张杂卡）。所以对它们**再聚一次**、各自成栏。与 CLUSTER_THR 同口径。
NEW_CLUSTER_THR = 1.30

FF_CANDIDATES = (
    *_FF_CANDIDATES_TUPLE,   # 共享解析器的兜底位置（见 ffmpeg_path.py）
    "ffmpeg",
)


def find_ffmpeg(explicit=None):
    from shutil import which
    for c in ([explicit] if explicit else []) + list(FF_CANDIDATES):
        if not c:
            continue
        if os.path.sep in c or c.endswith(".exe"):
            if os.path.exists(c):
                return c
        else:
            p = which(c)
            if p:
                return p
    raise SystemExit("找不到 ffmpeg；用 --ffmpeg 指定")


def imread_u(p):
    """读图（支持中文路径 —— cv2.imread 在 Windows 上打不开非 ASCII 路径）。"""
    try:
        return cv2.imdecode(np.fromfile(p, dtype=np.uint8), cv2.IMREAD_UNCHANGED)
    except OSError:
        return None


def imwrite_u(p, img):
    ok, buf = cv2.imencode(os.path.splitext(p)[1], img)
    if ok:
        buf.tofile(p)
        return True
    return False


def probe_video(ff, video):
    """→ (宽, 高, 时长秒)。精简版 ffmpeg 没有 ffprobe，只能读它自报的信息。"""
    import re
    r = subprocess.run([ff, "-i", video], stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    txt = (r.stdout or b"").decode("utf-8", "replace")
    w = h = dur = None
    m = re.search(r"Video:.*?,\s*(\d{2,5})x(\d{2,5})", txt)
    if m:
        w, h = int(m.group(1)), int(m.group(2))
    m = re.search(r"Duration:\s*(\d+):(\d+):(\d+(?:\.\d+)?)", txt)
    if m:
        dur = int(m.group(1)) * 3600 + int(m.group(2)) * 60 + float(m.group(3))
    return w, h, dur


def scaled_box(box, fw, base_w=2876.0):
    s = fw / float(base_w)
    return tuple(int(round(v * s)) for v in box)


class CardHarvester:
    def __init__(self, video, ff, base_w=2876.0, verbose=True):
        self.video = video
        self.ff = ff
        self.verbose = verbose
        w, h, dur = probe_video(ff, video)
        if not w:
            raise SystemExit("读不出录屏分辨率：%s" % video)
        self.base_w = base_w
        self.fw, self.fh, self.dur = w, h, dur
        self.s = w / float(base_w)
        self.card = scaled_box(CARD_BOX, w, base_w)
        self.mark = scaled_box(MARK_BOX, w, base_w)
        if self.verbose:
            print("录屏 %s  %dx%d%s" % (os.path.basename(video), w, h,
                                        "  时长 %.0fs" % dur if dur else ""))
            print("  卡框 %s   标记区 %s" % (self.card, self.mark))

    def probe_bar(self, n=5):
        """探测这段素材的黑边（上/左），取几帧的**中位数**——避免开场淡入那 1 秒
        （实测 t=5 时上边只有 16px，与正片的 90px 不同）把结果带偏。
        返回 (bar_left, bar_top)；无黑边返回 (0, 0)。"""
        tmp = os.path.join(os.path.dirname(self.video) or ".", "_probe_bar.png")
        tops, lefts = [], []
        for k in range(n):
            t = (self.dur or 60.0) * (0.15 + 0.15 * k)
            subprocess.run([self.ff, "-ss", "%.2f" % t, "-i", self.video,
                            "-frames:v", "1", "-y", tmp],
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            img = imread_u(tmp)
            if img is None:
                continue
            _c, bar = T.crop_letterbox(img)
            tops.append(bar[1])
            lefts.append(bar[0])
        try:
            os.remove(tmp)
        except OSError:
            pass
        if not tops:
            return 0, 0
        return int(np.median(lefts)), int(np.median(tops))

    def run_dense(self, outdir, fps=10.0, t0=0.0, t1=None, save_cards=True, q=3):
        """**逐帧探黑边 + 一次解码**（拼贴/演示视频的正确通道）。

        为什么需要它：
          * 快通道整段只探一次黑边 → 拼贴视频错位；
          * 分块（`harvest_montage.py`）在"块里混了转场"时会算错黑边
            （实测 `皮肤.mp4` 第1段的战斗帧就是这样被跳过的）；
          * 逐帧 seek 通道虽然对，但 1.19 秒/帧，密采（10fps）要十几分钟。
        做法：一次解码把整段按 fps 导成 JPEG（~0.3MB/张，I/O 可控），
        再在 Python 里**逐帧探黑边 + 裁卡**（每帧约 5ms）。
        """
        import glob
        os.makedirs(outdir, exist_ok=True)
        seq = os.path.join(outdir, "_seqd")
        if os.path.isdir(seq):
            for f in glob.glob(os.path.join(seq, "*")):
                try:
                    os.remove(f)
                except OSError:
                    pass
        os.makedirs(seq, exist_ok=True)
        cmd = [self.ff, "-v", "error"]
        if t0:
            cmd += ["-ss", "%.3f" % t0]
        cmd += ["-i", self.video]
        if t1 is not None:
            cmd += ["-t", "%.3f" % max(0.0, t1 - t0)]
        cmd += ["-r", ("%g" % fps), "-q:v", str(q), "-y", os.path.join(seq, "f%05d.jpg")]
        r = subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
        files = sorted(glob.glob(os.path.join(seq, "*.jpg")))
        if not files:
            err = (r.stderr or b"").decode("utf-8", "replace")[-400:]
            raise RuntimeError("单次解码没有产出帧\n%s" % err)

        cards, marks, skipped, bars = [], {}, 0, {}
        for k, f in enumerate(files):
            img = imread_u(f)
            if img is None:
                continue
            img, bar = T.crop_letterbox(img)
            bars[bar[1]] = bars.get(bar[1], 0) + 1
            mk = self._marker(img)
            marks[mk] = marks.get(mk, 0) + 1
            if not (mk or "").startswith("ally"):
                skipped += 1
                continue
            x0, y0, x1, y1 = self.card
            card = img[y0:y1, x0:x1]
            if card.size == 0:
                skipped += 1
                continue
            ok, col, grad = self._card_ok(card)
            if ok:
                cards.append(dict(t=t0 + k / fps, card=card, marker=mk, col=col, grad=grad))
            else:
                skipped += 1
        for f in files:
            try:
                os.remove(f)
            except OSError:
                pass
        try:
            os.rmdir(seq)
        except OSError:
            pass
        stats = dict(scanned=len(files), kept=len(cards), skipped=skipped, markers=marks,
                     bars=bars)
        if self.verbose:
            print("  [dense] 扫 %d 帧：采到 %d，跳过 %d；黑边分布 %s"
                  % (len(files), len(cards), skipped, bars))
        if save_cards:
            cd = os.path.join(outdir, "cards")
            os.makedirs(cd, exist_ok=True)
            for c in cards:
                imwrite_u(os.path.join(cd, "t%08.2f.png" % c["t"]), c["card"])
        return cards, stats

    def probe_bar_range(self, a, b, n=4):
        """在 [a,b) 区间内探黑边（拼贴视频**每段黑边不同**，只能逐段探）。"""
        tops, lefts = [], []
        for k in range(n):
            t = a + (b - a) * (k + 0.5) / n
            tmp = os.path.join(os.path.dirname(self.video) or ".", "_probe_r.png")
            subprocess.run([self.ff, "-ss", "%.2f" % t, "-i", self.video,
                            "-frames:v", "1", "-y", tmp],
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            img = imread_u(tmp)
            if img is None:
                continue
            _c, bar = T.crop_letterbox(img)
            tops.append(bar[1])
            lefts.append(bar[0])
            try:
                os.remove(tmp)
            except OSError:
                pass
        if not tops:
            return 0, 0
        return int(np.median(lefts)), int(np.median(tops))

    def _grab(self, t, tmp):
        cmd = [self.ff, "-ss", "%.2f" % t, "-i", self.video, "-frames:v", "1", "-y", tmp]
        subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        img = imread_u(tmp)
        if img is None:
            return None
        # **自动裁黑边**：用户 2026-10-03 的 `水砂视频.mp4` 上下各加黑边（上90/下88），
        # 真实内容是 16:9；不裁的话卡框整体偏 90px，采集全废。裁后旧卡框坐标正好对上
        # （已用刻度尺图核对）。没有黑边的素材原样返回 → 老素材零影响。
        img, bar = T.crop_letterbox(img)
        if bar[2] - bar[0] != self.fw and bar[2] > bar[0]:
            # 左右也被裁了 → 宽度变了，卡框/标记区要按新宽度重算
            self.fw = bar[2] - bar[0]
            self.s = self.fw / float(self.base_w)
            self.card = scaled_box(CARD_BOX, self.fw, self.base_w)
            self.mark = scaled_box(MARK_BOX, self.fw, self.base_w)
        return img

    def _marker(self, img):
        """左标记类型。

        ⚠️ 用识别器自带的 `marker_feat`（形状 + 颜色命名一体，已在 84 个真值卡面上
        实测 100% 判对）。**不要自己重写颜色判据**：试过一版"直接在裁块上取标记块"
        的快写法，速度从 330ms 降到 10ms，但颜色前缀判错（t=51 的 `ally_dot`
        变成 `gold_dot`、非战斗帧变成 `enemy_dot`）——判据正确性优先于速度。
        """
        x0, y0, x1, y1 = self.mark
        crop = img[y0:y1, x0:x1]
        full = np.zeros((max(y0 + crop.shape[0], 220),
                         max(int(2876 * self.s), x0 + crop.shape[1]), 3), np.uint8)
        full[y0:y0 + crop.shape[0], x0:x0 + crop.shape[1]] = crop
        return T.marker_feat(full, s=self.s)[0]

    @staticmethod
    def _card_ok(card):
        hsv = cv2.cvtColor(card, cv2.COLOR_BGR2HSV)
        col = float((hsv[:, :, 1] > 70).mean())
        g = cv2.cvtColor(card, cv2.COLOR_BGR2GRAY)
        grad = float(np.abs(np.diff(g.astype(np.float32), axis=1)).std())
        return (col >= COL_MIN) and (grad >= GRAD_MIN), col, grad

    def run(self, outdir, step=0.2, t0=0.0, t1=None, save_cards=True):
        """扫全片 → 返回 (cards, stats)。cards = [dict(t, card, marker)]"""
        os.makedirs(outdir, exist_ok=True)
        tmp = os.path.join(outdir, "_tmp_frame.png")
        t1 = self.dur if (t1 is None and self.dur) else (t1 or 0.0)
        cards, marks, skipped = [], {}, 0
        t = t0
        n = 0
        t_start = time.time()
        while t <= t1:
            img = self._grab(t, tmp)
            n += 1
            if img is not None:
                mk = self._marker(img)
                marks[mk] = marks.get(mk, 0) + 1
                if (mk or "").startswith("ally"):
                    x0, y0, x1, y1 = self.card
                    card = img[y0:y1, x0:x1]
                    ok, col, grad = self._card_ok(card)
                    if ok:
                        cards.append(dict(t=t, card=card, marker=mk, col=col, grad=grad))
                    else:
                        skipped += 1
                else:
                    skipped += 1
            t += step
            if self.verbose and n % 250 == 0:
                print("    %.0fs / %.0fs  已采 %d 张（%.0fs 用时）"
                      % (t, t1, len(cards), time.time() - t_start))
        try:
            os.remove(tmp)
        except OSError:
            pass
        stats = dict(scanned=n, kept=len(cards), skipped=skipped, markers=marks)
        if self.verbose:
            print("  扫 %d 帧：采到卡面 %d，跳过 %d" % (n, len(cards), skipped))
        if save_cards:
            cd = os.path.join(outdir, "cards")
            os.makedirs(cd, exist_ok=True)
            for c in cards:
                imwrite_u(os.path.join(cd, "t%08.2f.png" % c["t"]), c["card"])
        return cards, stats

    # ────────────────── 单次解码（快 ~20x；与 run 产出等价）──────────────────

    def run_fast(self, outdir, fps=5.0, t0=0.0, t1=None, save_cards=True, bar=None):
        """整片**一次**解码 + crop 小区域 → 与 `run` 等价的 cards，但快约 20 倍。

        为什么可行：`MARK_BOX` 完全包住 `CARD_BOX`（40<82、66<78、300>281、196>178），
        所以一次 crop 同时拿到"标记"和"头像区"，不需要两趟解码。

        ⚠️ 与 `run` 的一致性要求：画布构造必须与 `_marker` **逐字一致**
        （zeros(h, w) + 把裁块贴回原坐标），否则 `marker_feat` 会因缺少周围上下文而判错。
        """
        os.makedirs(outdir, exist_ok=True)
        seq = os.path.join(outdir, "_seq")
        if os.path.isdir(seq):
            for f in os.listdir(seq):
                try:
                    os.remove(os.path.join(seq, f))
                except OSError:
                    pass
        os.makedirs(seq, exist_ok=True)
        # ⚠️ **黑边必须先探明**：快通道用 ffmpeg 直接 crop 卡框（绕过 `_grab`），
        #    素材若上下加了黑边（用户 2026-10-03 的 `水砂视频.mp4`：上 90 / 下 88），
        #    裁剪坐标会整体偏 90px → 标记几乎全判错（实测 ?_dot 194 / gold_aha 174）。
        bar = bar if bar is not None else self.probe_bar()
        # 两套坐标必须分清：
        #   * ffmpeg 的 crop 用**全幅坐标**（= 参考坐标 + 黑边偏移）；
        #   * 画布/头像偏移仍用**参考坐标** —— `marker_feat(full, s=…)` 是按参考位置
        #     去找标记的，把裁块贴到 y+92 会让它去看空白画布（实测：贴错后 463 帧 0 采到）。
        mx0, my0, mx1, my1 = self.mark
        bx0, by0 = mx0 + bar[0], my0 + bar[1]
        rw, rh = mx1 - mx0, my1 - my0
        x0, y0 = mx0, my0                       # 后续画布/头像偏移统一用参考坐标
        cmd = [self.ff, "-v", "error"]
        if t0:
            cmd += ["-ss", "%.3f" % t0]
        cmd += ["-i", self.video]
        if t1 is not None:
            cmd += ["-t", "%.3f" % max(0.0, t1 - t0)]
        cmd += ["-vf", "crop=%d:%d:%d:%d" % (rw, rh, bx0, by0),
                "-r", ("%g" % fps), "-y", os.path.join(seq, "r%05d.png")]
        r = subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
        files = sorted(f for f in os.listdir(seq) if f.endswith(".png"))
        if not files:
            err = (r.stderr or b"").decode("utf-8", "replace")[-400:]
            raise RuntimeError("单次解码没有产出帧（该 ffmpeg 是否带 crop 滤镜？）\n%s" % err)

        ch = max(y0 + rh, 220)                       # 与 _marker 的画布尺寸一致
        cw = max(int(2876 * self.s), x0 + rw)
        cx0, cy0 = self.card[0] - x0, self.card[1] - y0
        cwd, chd = self.card[2] - self.card[0], self.card[3] - self.card[1]
        if bar[0] or bar[1]:
            print("  黑边：上 %d / 左 %d（已从裁剪坐标里扣除）" % (bar[1], bar[0]))

        cards, marks, skipped = [], {}, 0
        n = 0
        t_start = time.time()
        for k, f in enumerate(files):
            reg = imread_u(os.path.join(seq, f))
            n += 1
            if reg is None:
                continue
            full = np.zeros((ch, cw, 3), np.uint8)
            full[y0:y0 + reg.shape[0], x0:x0 + reg.shape[1]] = reg
            mk = T.marker_feat(full, s=self.s)[0]
            marks[mk] = marks.get(mk, 0) + 1
            if not (mk or "").startswith("ally"):
                skipped += 1
                continue
            card = reg[cy0:cy0 + chd, cx0:cx0 + cwd]
            if card.size == 0:
                skipped += 1
                continue
            ok, col, grad = self._card_ok(card)
            if ok:
                cards.append(dict(t=t0 + k / fps, card=card, marker=mk, col=col, grad=grad))
            else:
                skipped += 1
            if self.verbose and n % 500 == 0:
                print("    %d/%d 帧  已采 %d 张（%.0fs 用时）"
                      % (n, len(files), len(cards), time.time() - t_start))
        for f in files:
            try:
                os.remove(os.path.join(seq, f))
            except OSError:
                pass
        try:
            os.rmdir(seq)
        except OSError:
            pass
        stats = dict(scanned=n, kept=len(cards), skipped=skipped, markers=marks)
        if self.verbose:
            print("  扫 %d 帧：采到卡面 %d，跳过 %d" % (n, len(cards), skipped))
        if save_cards:
            cd = os.path.join(outdir, "cards")
            os.makedirs(cd, exist_ok=True)
            for c in cards:
                imwrite_u(os.path.join(cd, "t%08.2f.png" % c["t"]), c["card"])
        return cards, stats


# ────────────────────────── 分组与认名 ──────────────────────────

def cluster_cards(cards, thr=CLUSTER_THR, base_w=2876.0):
    """贪心代表聚类：把"同一个人"的卡归到一起。返回 [ [idx...], ... ]（按大小降序）。

    ⚠️ 用**头像区**特征（不是整张卡）：同一角色的卡会带不同标记（点/星/菱形），
    整张卡比对会因标记不同而被拆成多组（实测过）。
    """
    n = len(cards)
    if n == 0:
        return []
    # ⚠️ 用**位移容忍**打分（见 `SHIFT_R` 的注释）：卡的边框固定、框内头像会位移，
    #    用位置敏感的点积会把同一个人拆成多组（实测同人跨战斗只有 1.0~1.5，
    #    与"不同的人"0.9~1.0 重叠）。
    ff = [feat_fft(card_feat(c, base_w)) for c in cards]
    S = np.eye(n, dtype=np.float32)
    for i in range(n):
        for j in range(i + 1, n):
            v = pair_score_shift(ff[i], ff[j])
            S[i, j] = S[j, i] = v
    order = list(np.argsort(-S.mean(axis=1)))
    reps, assign = [], []
    for i in order:
        best, bi = -9.0, -1
        for ri, r in enumerate(reps):
            if S[i, r] > best:
                best, bi = S[i, r], ri
        if bi >= 0 and best >= thr:
            assign.append(bi)
        else:
            reps.append(i)
            assign.append(len(reps) - 1)
    groups = {}
    for i, g in enumerate(assign):
        groups.setdefault(g, []).append(i)
    out = []
    for g, idxs in groups.items():
        if len(idxs) > 1:
            sub = S[np.ix_(idxs, idxs)].copy()
            np.fill_diagonal(sub, np.nan)
            rep = idxs[int(np.nanargmax(np.nanmean(sub, axis=1)))]
        else:
            rep = idxs[0]
        out.append(dict(idxs=sorted(idxs, key=lambda i: cards[i]["t"]), rep=rep,
                        n=len(idxs)))
    out.sort(key=lambda d: -d["n"])
    for k, d in enumerate(out):
        d["gid"] = k + 1
    return out


def load_bank(path=None):
    path = path or T.BANK_PATH
    with np.load(path) as z:
        return {k: z[k] for k in z.files}


def art_of_card(card, base_w=2876.0):
    """行动卡裁块 → **头像区**（与库内模板的口径一致）。

    库内模板是「帧基准坐标下 `T.TOP_ART` 那一块」，而卡是 `CARD_BOX` 裁出来的，
    所以要把基准坐标减去裁块原点 `CROP_ORIGIN`。**这一步漏了就会全部认错。**
    """
    s = base_w / float(T.REF_W)
    x0 = int(round((T.TOP_ART[0] - CROP_ORIGIN[0]) * s))
    y0 = int(round((T.TOP_ART[1] - CROP_ORIGIN[1]) * s))
    x1 = int(round((T.TOP_ART[2] - CROP_ORIGIN[0]) * s))
    y1 = int(round((T.TOP_ART[3] - CROP_ORIGIN[1]) * s))
    x0, y0 = max(0, x0), max(0, y0)
    x1, y1 = min(card.shape[1], x1), min(card.shape[0], y1)
    return card[y0:y1, x0:x1]


def card_feat(card, base_w=2876.0):
    """卡头像区的特征（**缓存**在 card 字典里）。

    同一张卡在"分组"和"认名"里各要算一次特征；72x48x4 的归一化不算便宜，
    缓存掉实测省掉一半时间（本录屏 3730 帧规模下是分钟级差别）。

    兼容两种传法：卡字典（会缓存）或直接的 BGR 数组（不缓存）。
    """
    if not isinstance(card, dict):
        return T.feats(art_of_card(card, base_w))
    f = card.get("_feat")
    if f is None:
        f = T.feats(art_of_card(card["card"], base_w))
        card["_feat"] = f
    return f


# ── 位移容忍打分 ──
# 实测（第三段录屏）：**行动卡的边框不动，动的是框里那张头像**（用
# `axis_geometry(refine=True)` 逐帧量过：所有帧 left=88/top=80，而两张同角色的卡
# 用像素搜索得到的最优相对位移是 2~8 像素）。固定窗口取特征因此必然对不齐：
# 同一个角色跨战斗只有 1.0~1.5 分，而"不同的人"能到 0.9~1.0，两带重叠。
# 对策不是"对齐"（框是固定的，对齐无处可依），而是**让打分容忍位移**：
#     score = max_{|dx|,|dy| <= R} Σ_c w_c · mean(f_c · shift(m_c))
# 用 FFT 一次算出所有位移的互相关，只需一次逆变换，几乎不增加成本。
SHIFT_R = 5            # 位移容忍半径（特征图像素；特征图是原图的一半 → 约 10 原像素）
_W4 = np.array([T.W_GRAY, T.W_GRAD, T.W_COLOR / 2, T.W_COLOR / 2], np.float32)


def feat_fft(f):
    """预先算好 4 个通道的 rfft2（每张卡算一次，配对时复用）。

    返回 ((h, w), [4 个 rfft2])。⚠️ rfft2 的输出形状是 (h, w//2+1)，
    不能用它反推原尺寸 —— 必须把原尺寸一起带出来。
    """
    return (f.shape[1], f.shape[2]), tuple(np.fft.rfft2(f[c]) for c in range(4))


def pair_score_shift(a, b, r=SHIFT_R):
    """位移容忍的相似度（与 `T.pair_score` 同尺度；≈1.9 表示逐像素相同）。"""
    (h, w), F1 = a
    _, F2 = b
    S = None
    for c in range(4):
        v = _W4[c] * (F1[c] * np.conj(F2[c]))
        S = v if S is None else S + v
    C = np.fft.irfft2(S, s=(h, w)) / (h * w)
    sub = np.concatenate([C[:r + 1], C[h - r:]], axis=0)
    sub = np.concatenate([sub[:, :r + 1], sub[:, w - r:]], axis=1)
    return float(sub.max())


def score_against_bank(card, bank, base_w=2876.0):
    """与库内每个角色的最高分。返回 [(角色, 分)] 降序。

    ⚠️ 特征取自 `art_of_card`（头像区），不是整张卡 —— 见 `CROP_ORIGIN` 的注释。
    """
    f = card_feat(card, base_w)
    out = []
    for unit, mats in bank.items():
        vals = []
        for m in mats:
            ch = float((m[0] * f[0]).mean())
            gr = float((m[1] * f[1]).mean())
            co = (float((m[2] * f[2]).mean()) + float((m[3] * f[3]).mean())) / 2
            vals.append(T.W_GRAY * ch + T.W_GRAD * gr + T.W_COLOR * co)
        out.append((unit, max(vals)))
    out.sort(key=lambda kv: -kv[1])
    return out


def label_by_name(cards, clusters, bank, thr=NAME_THR, margin=NAME_MARGIN,
                  low=LOW_CONF, new_thr=NEW_CLUSTER_THR, base_w=2876.0):
    """**先逐张认名，再按名字归并** —— 这正是用户要的"按角色名分，不按时间轴/组号"。

    做法：
      1. 每张卡与库比对，取 top1（角色名 + 分数 + 与第二名的分差）；
      2. 逐张判定：
         * 分数 ≥ thr 且分差 ≥ margin → 归到该角色（分数 < low 时标「低置信」）
         * 否则 → 记下"最像谁"，进**未认出池**
      3. 已认出的合并同名 → 每个角色一栏；
      4. **未认出的再聚一次**，各自成栏（`tag` = 「新角色? #k」）——
         实测一段素材能攒出上百张杂卡，全塞一栏用户根本没法回答。
         这里比 CLUSTER_THR 严（NEW_CLUSTER_THR），因为"把两个人并成一栏"
         会让用户答错名字，比"把一个人拆成两栏"有害得多。

    返回 [ {name|None, tag, idxs, n, score, margin, low, vote} ]
    """
    named, unknown = {}, []
    for d in clusters:
        for i in d["idxs"]:
            sc = score_against_bank(cards[i], bank, base_w)
            top, val = sc[0]
            second = sc[1][1] if len(sc) > 1 else -1.0
            gap = val - second
            cards[i]["top"] = top
            cards[i]["val"] = val
            cards[i]["gap"] = gap
            if val >= thr and gap >= margin:
                b = named.setdefault(top, dict(name=top, idxs=[], vals=[], gaps=[]))
                b["idxs"].append(i)
                b["vals"].append(val)
                b["gaps"].append(gap)
            else:
                cards[i]["vote"] = top
                unknown.append(i)

    out = []
    for key, b in named.items():
        b["n"] = len(b["idxs"])
        b["score"] = round(float(np.mean(b["vals"])), 3)
        b["margin"] = round(float(np.mean(b["gaps"])), 3)
        b["low"] = b["score"] < low
        b["vote"] = key
        b["tag"] = key
        out.append(b)

    if unknown:
        sub = [cards[i] for i in unknown]
        for k, g in enumerate(cluster_cards(sub, thr=new_thr, base_w=base_w)):
            idxs = [unknown[j] for j in g["idxs"]]
            votes = {}
            for i in idxs:
                v = cards[i].get("vote", "?")
                votes[v] = votes.get(v, 0) + 1
            vote = max(votes, key=lambda x: votes[x]) if votes else "?"
            out.append(dict(name=None, tag="【新角色? #%d】" % (k + 1), idxs=idxs,
                            n=len(idxs),
                            score=round(float(np.mean([cards[i]["val"] for i in idxs])), 3),
                            margin=round(float(np.mean([cards[i]["gap"] for i in idxs])), 3),
                            low=True, vote=vote))
    out.sort(key=lambda d: (-d["n"] if d["name"] else -1, -d["n"]))
    return out


# ────────────────────────── 出核对表（按角色名） ──────────────────────────

def _font(sz):
    from PIL import ImageFont
    for p in (r"C:\Windows\Fonts\msyh.ttc", r"C:\Windows\Fonts\msyhbd.ttc",
              r"C:\Windows\Fonts\arial.ttf"):
        if os.path.exists(p):
            try:
                return ImageFont.truetype(p, sz)
            except OSError:
                pass
    return ImageFont.load_default()


def make_sheet(cards, buckets, out_path, team="", per_group=5, thumb=(300, 150)):
    """按**角色名**分栏出核对表。

    buckets 来自 `label_by_name`：每栏 = 一个角色（或一个"新角色？"桶），
    栏内按时间给若干样本卡。用户只需回答「是 / 不是」。
    """
    from PIL import Image, ImageDraw
    tiles = []
    for d in buckets:
        cw, ch = thumb
        idxs = sorted(d["idxs"], key=lambda i: cards[i]["t"])
        imgs = []
        for k, i in enumerate(idxs[:per_group]):
            c = cards[i]["card"]
            big = cv2.resize(c, (cw, ch), interpolation=cv2.INTER_LANCZOS4)
            imgs.append((Image.fromarray(cv2.cvtColor(big, cv2.COLOR_BGR2RGB)),
                         "t=%.0f" % cards[i]["t"], k == 0))
        col_w = cw + 10
        col_h = 96 + sum(im.height + 18 for im, _l, _r in imgs)
        canvas = Image.new("RGB", (col_w, col_h), (16, 16, 16))
        dr = ImageDraw.Draw(canvas)
        nm = d["name"]
        title = nm if nm else (d.get("tag") or "【新角色？】")
        dr.text((6, 6), title, font=_font(26),
                fill=(150, 245, 170) if nm else (255, 170, 120))
        if nm:
            sub1 = "%d 张   均分 %.2f  均间距 %.2f" % (d["n"], d["score"], d["margin"])
            sub2 = ("⚠ 低置信，请重点核对" if d.get("low") else "✓ 与库内模板一致")
        else:
            sub1 = "%d 张  库里没有匹配" % d["n"]
            sub2 = "最像「%s」%.2f（未达认名线）" % (d["vote"], d["score"])
        dr.text((6, 38), sub1, font=_font(15), fill=(200, 200, 200))
        dr.text((6, 58), sub2, font=_font(15),
                fill=(255, 200, 120) if (nm and d.get("low")) or not nm else (170, 230, 170))
        y = 82
        for im, lab, is_rep in imgs:
            canvas.paste(im, (5, y))
            dr.text((7, y + im.height + 1), lab, font=_font(13),
                    fill=(255, 255, 255) if is_rep else (180, 180, 180))
            y += im.height + 18
        tiles.append(canvas)

    cols = 5
    rows = []
    for s in range(0, len(tiles), cols):
        chunk = tiles[s:s + cols]
        w = sum(c.width + 8 for c in chunk) + 12
        h = max(c.height for c in chunk) + 12
        row = Image.new("RGB", (w, h), (8, 8, 8))
        x = 8
        for c in chunk:
            row.paste(c, (x, 6))
            x += c.width + 8
        rows.append(row)
    W = max(r.width for r in rows)
    H = sum(r.height for r in rows) + 78
    sheet = Image.new("RGB", (W, H), (8, 8, 8))
    d = ImageDraw.Draw(sheet)
    d.text((10, 8), "角色核对表%s —— 每栏一个「我认为是的人」；请回答 是 / 不是"
           % (("（%s）" % team) if team else ""), font=_font(24), fill=(255, 235, 120))
    d.text((10, 40), "标【新角色？】的表示库里没有、或我不敢确定；"
                     "每栏下的 t= 是该卡在录屏里的秒数", font=_font(15), fill=(200, 200, 200))
    y = 66
    for r in rows:
        sheet.paste(r, (0, y))
        y += r.height
    imwrite_u(out_path, np.array(sheet)[:, :, ::-1])
    return out_path, sheet.size


# ────────────────────────── CLI ──────────────────────────

def main(argv=None):
    # 控制台编码：Windows 默认 GBK，打印 '⚠' 会直接 UnicodeEncodeError 崩掉
    # （实测：扫完 300 帧、聚类做完，最后一步打印分栏时崩 —— 图一张没出）。
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, OSError):
        pass

    ap = argparse.ArgumentParser(description="录屏 → 自动挖角色 → 按角色名出核对表")
    ap.add_argument("--video", required=True)
    ap.add_argument("--team", default="", help="队伍名（只用于文件名/标注）")
    ap.add_argument("--outdir", default=None, help="中间产物目录（默认 frames/harvest_<队名>）")
    ap.add_argument("--ffmpeg", default=None)
    ap.add_argument("--base-width", type=float, default=2876.0,
                    help="几何基准宽度（卡框/标记区按它等比换算；默认 2876）")
    ap.add_argument("--mode", choices=("fast", "seek", "dense"), default="fast",
                    help="抽帧实现：fast=单次解码（默认，快 ~20x）；seek=逐帧 -ss")
    ap.add_argument("--fps", type=float, default=5.0, help="抽帧率（默认 5 = 0.2s/帧，别低于 2）")
    ap.add_argument("--step", type=float, default=0.2,
                    help="仅 --mode seek 用：抽帧间隔秒（默认 0.2）")
    ap.add_argument("--start", type=float, default=0.0)
    ap.add_argument("--end", type=float, default=None)
    ap.add_argument("--thr", type=float, default=CLUSTER_THR, help="分组阈值")
    ap.add_argument("--new-thr", type=float, default=NEW_CLUSTER_THR,
                    help="未认出卡的二次分组阈值（越大越细，默认 %g）" % NEW_CLUSTER_THR)
    ap.add_argument("--name-thr", type=float, default=NAME_THR, help="认名分数下限")
    ap.add_argument("--bank", default=None)
    ap.add_argument("--no-save-cards", action="store_true")
    args = ap.parse_args(argv)

    ff = find_ffmpeg(args.ffmpeg)
    team = args.team or os.path.splitext(os.path.basename(args.video))[0]
    outdir = args.outdir or os.path.join(ROOT, "frames", "harvest_%s" % team)
    os.makedirs(outdir, exist_ok=True)

    print("=== 1/4 抽帧 + 判战斗帧（左标记必须是 ally_*）===")
    hv = CardHarvester(args.video, ff, base_w=args.base_width)
    if args.mode == "dense":
        # 逐帧探黑边 + 一次解码：拼贴/演示视频（黑边逐段不同）的正确通道
        h = hv
        h.verbose = True
        cards, stats = h.run_dense(outdir, fps=args.fps, t0=0.0, t1=None,
                                   save_cards=True, q=3)
        print("\n录屏 %s  %dx%d  时长 %.0fs" % (os.path.basename(args.video), h.fw, h.fh,
                                              h.dur or 0))
        print("  [dense] 扫 %d 帧：采到卡面 %d，跳过 %d"
              % (stats["scanned"], stats["kept"], stats["skipped"]))
        print("  黑边分布（上边像素 → 帧数）：%s" % stats.get("bars"))
        print("  标记分布：%s" % {k: v for k, v in sorted(stats["markers"].items(),
                                                    key=lambda kv: -kv[1])})
        with open(os.path.join(outdir, "buckets.json"), "w", encoding="utf-8") as f:
            json.dump(dict(video=args.video, mode="dense-逐帧黑边", scanned=stats["scanned"],
                           kept=stats["kept"], skipped=stats["skipped"],
                           markers=stats["markers"], bars=stats.get("bars")), f,
                      ensure_ascii=False, indent=1)
        print("\n卡面已写出 %s" % os.path.join(outdir, "cards"))
        return 0

    if args.mode == "fast":
        cards, stats = hv.run_fast(outdir, fps=args.fps, t0=args.start, t1=args.end,
                                   save_cards=not args.no_save_cards)
    else:
        cards, stats = hv.run(outdir, step=args.step, t0=args.start, t1=args.end,
                              save_cards=not args.no_save_cards)
    if not cards:
        raise SystemExit("没有采到任何我方卡面 —— 检查 --base-width / 卡框是否与该录屏匹配")

    print("\n=== 2/4 按「同一个人」分组 ===")
    clusters = cluster_cards(cards, thr=args.thr)
    print("  采到 %d 张 → %d 组" % (len(cards), len(clusters)))

    print("\n=== 2/4 与共享模板库逐张比对、按角色名归并 ===")
    bank = load_bank(args.bank)
    print("  库内角色 %d 个" % len(bank))
    buckets = label_by_name(cards, clusters, bank, thr=args.name_thr, new_thr=args.new_thr)
    known = [d for d in buckets if d["name"]]
    unknown = [d for d in buckets if not d["name"]]
    print("  归并成 %d 个角色栏；另有 %d 个「新角色?」栏" % (len(known), len(unknown)))
    for d in buckets:
        print("    %-16s %4d 张   均分 %.2f%s"
              % (d["name"] or ("【新角色? 最像 %s】" % d["vote"]), d["n"], d["score"],
                 "  ⚠低置信" if (d["name"] and d.get("low")) else ""))

    print("\n=== 3/3 出核对表（按角色名分栏）===")
    p = os.path.join(ROOT, "samples", "%s_角色核对.png" % team)
    p, size = make_sheet(cards, buckets, p, team=team)
    print("  已写出 %s  %s" % (p, size))

    meta = dict(video=os.path.abspath(args.video), team=team,
                scanned=stats["scanned"], kept=stats["kept"], skipped=stats["skipped"],
                buckets=[dict(name=d["name"], tag=d.get("tag"), vote=d["vote"], n=d["n"],
                              score=d["score"], margin=d["margin"], low=d.get("low"),
                              times=[cards[i]["t"] for i in sorted(d["idxs"])])
                         for d in buckets],
                markers=stats["markers"])
    jp = os.path.join(outdir, "buckets.json")
    with open(jp, "w", encoding="utf-8") as f:
        json.dump(meta, f, ensure_ascii=False, indent=1)
    print("  分栏明细 %s" % jp)
    print("\n请打开核对表回答「是 / 不是」；把不是的告诉我，我改标注后重跑即可。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
