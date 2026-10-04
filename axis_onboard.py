# -*- coding: utf-8 -*-
"""任意队伍/任意角色适配 —— onboarding 流水线（G1）。

目标：**用户给一段该队伍的战斗录屏 → 自动挖出场上角色的头像模板 → 用户只答一次
（给每张头像报个名字）→ 该角色进入共享模板库，此后实时即可识别。**

设计纪律（与 `docs/任意队伍适配.md` §6 一致）：
  * 顶端槽位**固定** `TOP_ART`，不做全图滑窗；
  * **不改识别算法**——特征/匹配/两道闸全部直接复用 `axis_actor`，模板口径逐位对齐；
  * 判不出来就"待复核"，不猜；
  * 不写死任何角色名：角色 → 名字的唯一来源是**用户这一次的回答**。

与既有两条线的区别（这就是"适配任意队伍"缺的那块）：
  | | 队伍1 (`axis_actor`) | 队伍2 (`axis_actor_team2`) | **本模块** |
  |---|---|---|---|
  | 角色名 | 写死在代码 | 写死在代码 | **数据文件（用户填）** |
  | 素材 | 整帧 `frames/glyphcache` | 裁块 `frames/axis2_L2` | **任意录屏当场抽** |
  | 建库 | 手工核对 71 帧 | 手工核对 381 帧 | **自动聚类 + 一次指认** |

子命令
------
    extract   录屏 → 裁出顶端卡小块（只存需要的区域，整帧不落盘）
    cluster   小块 → 特征 → 自动分组（"长得一样"的归一组）
    label     出「指认图」：每组一张代表图 + 组内成员 → 用户填一次名字
    build     用户答案 → 模板 → **并入共享模板库**（增量，不覆盖别的角色）
    eval      自检：留一帧准确率 + 全片覆盖率
    status    看当前注册了哪些角色

典型用法（一段新队伍的录屏）
------
    python axis_onboard.py extract --video "records/xxx.mp4" --team 我的队 --step 2
    python axis_onboard.py cluster --team 我的队
    python axis_onboard.py label   --team 我的队          # 看图，填 out/teams/我的队.labels.json
    python axis_onboard.py build   --team 我的队          # 之后实时即可识别

参考实现：`docs/录屏2欢愉队.md`（线2 那次成功的 onboarding 案例）。
"""

import ffmpeg_path as _ffmpeg_path
_FF_CANDIDATES_TUPLE = _ffmpeg_path._FALLBACKS
import argparse
import glob
import json
import os
import re
import subprocess
import sys
import time

import cv2
import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

import axis_actor as T                      # noqa: E402  复用识别器的特征/匹配/标记（不改它）
from mvp.resource import resource as _res   # noqa: E402

# ---------------------------------------------------------------- 常量与路径

# 本机 ffmpeg（Remotion 精简版：crop/fps 滤镜不可用，只能 -ss 定位 + 出整帧，裁剪用 cv2 做）
FF_CANDIDATES = (
    *_FF_CANDIDATES_TUPLE,   # 共享解析器的兜底位置（见 ffmpeg_path.py）
    "ffmpeg",
    "ffmpeg.exe",
)

# 顶端卡区域（含左标记），**以参考分辨率 2876×1798 为基准**：
#   (40,50)-(322,217) 覆盖参考系 (66,66)-(300,195) 的卡框 + 左标记中心 (86,127) + 26px 看图余量
# 来历：`axis_extract_team2.py` 的 REGIONS["top"]（录屏2 = 2870×1800，与参考只差 0.2%）
REGION_TOP = (40, 50, 322, 217)
# 队伍面板（开场/暂停时画面右侧的角色名 + 头像）——可选，给用户"照着念名字"用
REGION_PANEL_REF = (2100, 380, 2876, 1500)

TEAMS_DIR = _res("out/teams")
INDEX_PATH = os.path.join(TEAMS_DIR, "index.json")
OWNERS_PATH = os.path.join(TEAMS_DIR, "owners.json")
CROPS_DIR = os.path.join(HERE, "frames", "onboard")
SAMPLES_DIR = os.path.join(HERE, "samples")

# 阈值：与识别器完全一致（不另立标准）
THR = T.THR
MIN_MARGIN = T.MIN_MARGIN
# 卡面细节闸（线2 实测新增的第四道闸）：头像区梯度能量下限，拦"糊卡/白屏/极暗"。
# 数值 8.0 来自 `axis_actor_team2.GRAD_MIN`（84 张真值帧最低 10.2，中位 20.1；糊卡 t=15 会虚高到 1.51）。
GRAD_MIN = 8.0

# 我方标记（左标记分类结果的前缀）；聚类默认只看这些帧，避免把敌方/空槽/特效卡混进来
ALLY_MARKERS = ("ally_dot", "ally_star")
GOOD_MARKERS = ALLY_MARKERS + ("ally_diamond",)


# ---------------------------------------------------------------- ffmpeg / 抽帧


def find_ffmpeg(explicit=None):
    for c in ([explicit] if explicit else []) + list(FF_CANDIDATES):
        if not c:
            continue
        if os.path.sep in c or c.endswith(".exe"):
            if os.path.exists(c):
                return c
        else:
            from shutil import which
            p = which(c)
            if p:
                return p
    raise SystemExit(
        "找不到 ffmpeg。本机 ffmpeg 是 Remotion 精简版，路径见 axis_onboard.FF_CANDIDATES；"
        "用 --ffmpeg 显式指定，或把 ffmpeg 放进 PATH。")


def _probe_info(ff, video):
    """用 ffmpeg 自报的流信息取 (宽, 高, 时长秒)。精简版没有 ffprobe，只能这样读。"""
    r = subprocess.run([ff, "-i", video], stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    txt = (r.stdout or b"").decode("utf-8", "replace")
    size = None
    m = re.search(r"Video:.*?,\s*(\d{2,5})x(\d{2,5})", txt)
    if m:
        size = (int(m.group(1)), int(m.group(2)))
    else:
        m = re.search(r"(\d{3,5})x(\d{3,5})", txt)
        if m:
            size = (int(m.group(1)), int(m.group(2)))
    dur = None
    m = re.search(r"Duration:\s*(\d+):(\d+):(\d+(?:\.\d+)?)", txt)
    if m:
        dur = int(m.group(1)) * 3600 + int(m.group(2)) * 60 + float(m.group(3))
    return (size[0] if size else None, size[1] if size else None, dur)


def region_for_frame(frame_w, base_w=None):
    """把基准区域换算到实际帧尺寸。返回 (x0,y0,x1,y1, base_w)。

    base_w 的三种情况（顺序很重要，历史教训：同一台机器换分辨率后固定像素坐标会**静默**失效）：
      1. 传了 base_w      → 用户/注册表已知的基准宽度，直接用；
      2. 没传             → 假定参考系 2876；
      3. 结果明显不合理（帧宽 <50% 或 >200% 的基准）→ 回退成"帧宽即基准"（即像素坐标直接用）。
    """
    if not base_w:
        base_w = T.REF_W
    s = frame_w / float(base_w)
    if s < 0.5 or s > 2.0:
        # 画面尺度与基准差太多：按"该录屏自己的基准"理解（原样使用参考像素坐标）
        base_w, s = frame_w, 1.0
    x0, y0, x1, y1 = REGION_TOP
    return int(round(x0 * s)), int(round(y0 * s)), int(round(x1 * s)), int(round(y1 * s)), base_w


def stem_t(t):
    return "t%08.2f" % float(t)


def crop_path(team, t, outdir=None):
    return os.path.join(outdir or crops_dir(team), "%s_top.png" % stem_t(t))


def panel_path(team, t, outdir=None):
    return os.path.join(outdir or crops_dir(team), "%s_panel.png" % stem_t(t))


def crops_dir(team):
    """队伍 → 裁块目录（优先新建的 frames/onboard/<队伍>，回退到已存在的队伍专属目录）。

    回退是为了**直接复用已经抽好的素材**（队伍2 的 893 帧裁块在 frames/axis2_L2），
    否则每换一支队伍都要把旧素材重抽一遍。
    """
    cand = [os.path.join(CROPS_DIR, _safe_name(team))]
    for alt in _LEGACY_CROPS.get(team, ()):
        cand.append(os.path.join(HERE, alt))
    for c in cand:
        if os.path.isdir(c) and glob.glob(os.path.join(c, "*_top.png")):
            return c
    return cand[0]


# 既有素材目录（只读复用；新队伍一律落在 frames/onboard/<队伍>）
_LEGACY_CROPS = {
    "team2": ("frames/axis2_L2",),
    "录屏2": ("frames/axis2_L2",),
    "欢愉队": ("frames/axis2_L2",),
}


def _safe_name(s):
    return re.sub(r'[<>:"/\\|?*\s]+', "_", str(s)).strip("_") or "team"


def _grab_raw(ff, video, t, out_path):
    if os.path.exists(out_path) and os.path.getsize(out_path) > 0:
        return True
    cmd = [ff, "-ss", "%.3f" % t, "-i", video, "-frames:v", "1", "-y", out_path]
    r = subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    return r.returncode == 0 and os.path.exists(out_path) and os.path.getsize(out_path) > 0


def cmd_extract(args):
    """录屏 → 裁出顶端卡小块，并保存**队伍面板全帧**（画面上带角色名，用户照着一遍读完）。

    整帧只在 --panel-time 那一帧落盘一次（约 7 MB，人工指认时必需）；其余帧只留裁块。
    """
    ff = find_ffmpeg(args.ffmpeg)
    video = args.video
    if not os.path.exists(video):
        raise SystemExit("找不到录屏：%s" % video)
    outdir = crops_dir(args.team)
    os.makedirs(outdir, exist_ok=True)
    fw, fh, dur = _probe_info(ff, video)
    if not fw:
        raise SystemExit("读不出录屏分辨率：%s" % video)
    x0, y0, x1, y1, base_w = region_for_frame(fw, args.base_width)
    print("录屏 %s  分辨率 %dx%d%s  顶端卡区域 (%d,%d)-(%d,%d)  base_w=%s"
          % (os.path.basename(video), fw, fh,
             "  时长 %.0fs" % dur if dur else "", x0, y0, x1, y1, base_w))
    if x1 > fw:
        raise SystemExit("裁块区域 (%d,%d)-(%d,%d) 超出帧宽 %d —— 这份录屏的"
                         "分辨率/游戏画面缩放与本工具假设不同，请用 --base-width 指定基准"
                         % (x0, y0, x1, y1, fw))

    # 时长未知时 --end 的默认值（380）可能远超实际片长 → **静默抽不到帧**是最坏的失败方式，
    # 所以一旦读出时长就自动钳制，并明确告诉用户改了什么。
    if not args.times and dur:
        if args.end > dur:
            print("  注意：--end %.0fs 超出片长 %.0fs → 自动收到 %.0fs（短录屏请用 --start/--end "
                  "只取战斗段，面板仍从 --panel-time 取整帧）" % (args.end, dur, dur))
            args.end = dur
        if args.start >= args.end:
            raise SystemExit("--start %.1f 不小于 --end %.1f，没有帧可抽"
                             % (args.start, args.end))
    times = _times_of(args)

    # ── 队伍面板：画面上写着角色名，是 onboarding 唯一"照着念"的依据 ──
    # 策略：在 --panel-time（默认 0 = 战斗开场）抽一帧整帧存下来，永久保留。
    # 开场那一刻队伍列表一定在（线2 就是这么定案的，见 docs/录屏2欢愉队_*.md §1）。
    fullp = os.path.join(outdir, "_panel_full.png")
    if not os.path.exists(fullp):
        if _grab_raw(ff, video, args.panel_time, fullp):
            print("队伍面板全帧已保存 %s（t=%.2f；用户照它读角色名）" % (fullp, args.panel_time))
        else:
            print("！t=%.2f 取不到整帧（面板图缺失，用户指认时只能靠头像认脸）" % args.panel_time)

    tmp = os.path.join(outdir, "_tmp_frame.png")
    ok, fail = 0, []
    t0 = time.time()
    for i, t in enumerate(times):
        tp = crop_path(args.team, t)
        pp = panel_path(args.team, t)
        want_panel = args.panel and not os.path.exists(pp)
        if os.path.exists(tp) and not want_panel:
            ok += 1
            continue
        if not _grab_raw(ff, video, t, tmp):
            fail.append(t)
            continue
        img = cv2.imread(tmp, cv2.IMREAD_COLOR)
        if img is None:
            fail.append(t)
            continue
        cv2.imwrite(tp, img[y0:y1, x0:x1])
        if want_panel:
            pan = _panel_rect(img.shape[1], img.shape[0], base_w)
            px0, py0, px1, py1 = pan
            if px1 - px0 > 8 and py1 - py0 > 8:
                cv2.imwrite(pp, img[py0:py1, px0:px1])
        ok += 1
        if (i + 1) % 25 == 0:
            print("  %d/%d …（%.1fs）" % (i + 1, len(times), time.time() - t0))
    try:
        os.remove(tmp)
    except OSError:
        pass
    print("抽帧完成：%d/%d -> %s" % (ok, len(times), outdir))
    if fail:
        print("  失败时刻：%s%s" % (fail[:12], " …" if len(fail) > 12 else ""))
    _touch_index_team(args.team, dict(
        video=os.path.abspath(video), video_size=[fw, fh], base_width=base_w,
        region_top=[x0, y0, x1, y1], frames=ok, extract_at=time.strftime("%Y-%m-%d %H:%M:%S")))
    return 0


def _times_of(args):
    if args.times:
        return [float(x) for x in args.times.split(",") if x.strip()]
    return [args.start + i * args.step for i in range(int((args.end - args.start) / args.step) + 1)]


def _panel_rect(fw, fh, base_w):
    """队伍面板裁剪矩形（按帧实际尺寸换算 + 夹到帧内）。

    面板在画面右侧（角色名 + 头像竖排）。`REGION_PANEL_REF` 只是够宽的取景框，
    真正的信息在框里；给宽一点无害，给窄了会把名字切掉。
    """
    s = fw / float(base_w) if base_w else 1.0
    x0, y0, x1, y1 = (int(round(v * s)) for v in REGION_PANEL_REF)
    return (max(0, x0), max(0, y0), min(fw, x1), min(fh, y1))


def panel_full_path(team):
    """队伍面板全帧（画面上带角色名）——人工指认的依据。"""
    return os.path.join(crops_dir(team), "_panel_full.png")


# ---------------------------------------------------------------- 特征与聚类


def art_of_crop(crop, base_w):
    """裁块 → 顶端卡头像区（**与识别器模板口径逐位一致**）。

    ⚠️ 坐标系（踩过一次，特征 max|diff|=9 才发现）：`T.TOP_ART` 是**帧/画布基准系**坐标，
    而裁块的原点是 `REGION_TOP` 的左上角。所以裁块内取头像区必须**减掉裁块原点**：
        crop 内 x = TOP_ART_x * s - REGION_TOP_x * s
    （裁块原点在基准系里的位置换算成裁块自己的基准宽度后，就是 REGION_TOP 原值 ——
     两者同为"基准宽度"下的坐标，所以直接相减即可。）
    """
    s = base_w / float(T.REF_W) if base_w else 1.0
    x0 = int(round((T.TOP_ART[0] - REGION_TOP[0]) * s))
    y0 = int(round((T.TOP_ART[1] - REGION_TOP[1]) * s))
    x1 = int(round((T.TOP_ART[2] - REGION_TOP[0]) * s))
    y1 = int(round((T.TOP_ART[3] - REGION_TOP[1]) * s))
    if y1 > crop.shape[0] or x1 > crop.shape[1] or y0 < 0 or x0 < 0:
        raise ValueError("裁块 %s 放不下头像区 %s（裁块原点 %s）—— 抽帧区域与实际画面不符"
                         % (crop.shape, T.TOP_ART, REGION_TOP))
    return crop[y0:y1, x0:x1]


def feats_of_art(art, s_zoom=1.0):
    """头像区 → 4×48×72 特征（缩放态口径复制自 `T.feats_art`，保证与模板库同源）。"""
    if s_zoom != 1.0:
        h, w = art.shape[:2]
        z = cv2.resize(art, (max(2, int(round(w * s_zoom))), max(2, int(round(h * s_zoom)))),
                       interpolation=cv2.INTER_AREA if s_zoom < 1 else cv2.INTER_LINEAR)
        if z.shape[0] >= h and z.shape[1] >= w:
            yy, xx = (z.shape[0] - h) // 2, (z.shape[1] - w) // 2
            z = z[yy:yy + h, xx:xx + w]
        else:
            z = cv2.copyMakeBorder(z, 0, max(0, h - z.shape[0]), 0, max(0, w - z.shape[1]),
                                   cv2.BORDER_REPLICATE)
        art = z
    return T.feats(art)


def _load_crop(team, t, base_w=None):
    p = crop_path(team, t)
    img = cv2.imread(p, cv2.IMREAD_COLOR)
    if img is None:
        return None
    return img


def scan_team(team, base_w=None, verbose=True):
    """扫一支队伍的裁块 → [{t, crop, feats(每缩放态一个), marker, grad}]。"""
    files = sorted(glob.glob(os.path.join(crops_dir(team), "*_top.png")))
    if not files:
        raise SystemExit("没有裁块：%s\n  先跑 `python axis_onboard.py extract --video <录屏> --team %s`"
                         % (crops_dir(team), team))
    items = []
    for p in files:
        try:
            t = float(os.path.basename(p)[1:9])
        except ValueError:
            continue
        crop = cv2.imread(p, cv2.IMREAD_COLOR)
        if crop is None:
            continue
        if base_w is None:
            base_w = _base_width_of(team) or T.REF_W
        art = art_of_crop(crop, base_w)
        fs = [feats_of_art(art, z) for z in T.ZOOMS]
        try:
            mk = T.marker_feat(_canvas_of(crop, base_w), s=base_w / float(T.REF_W))[0]
        except Exception:                                  # noqa: BLE001
            mk = "?"
        g = art.mean(axis=2)
        items.append(dict(t=t, crop=crop, art=art, feats=fs, marker=mk,
                          grad=float(np.abs(np.diff(g, axis=1)).std())))
    if verbose:
        print("扫到 %d 帧（%s，base_w=%s）" % (len(items), crops_dir(team), base_w))
    return items


def _canvas_of(crop, base_w):
    """裁块 → 一张够大的画布，让 `T.marker_feat` 能在正确位置取到左标记。

    裁块原点即 REGION_TOP 的 (40,50)（基准系），画布高度留到 220（左标记在 y≈127）。

    ⚠️ 画布尺寸必须「原点 + 裁块尺寸」再留余量：用 `round(REF_W*s)` 会少 1px，
    把裁块最后一列/行截掉 —— 那会让头像区**静默变形**（实测特征 max|diff|=9），
    模板库一旦混进这种帧，分数会莫名偏低。
    """
    s = base_w / float(T.REF_W)
    x_off = int(round(REGION_TOP[0] * s))
    y_off = int(round(REGION_TOP[1] * s))
    h, w = crop.shape[:2]
    canvas = np.zeros((max(y_off + h, int(round(220 * s)), 4),
                       max(x_off + w, int(round(T.REF_W * s)), 4), 3), np.uint8)
    canvas[y_off:y_off + h, x_off:x_off + w] = crop
    return canvas


def sim_matrix(items, idx=None):
    """两帧相似度 = 各缩放态组合的最大 pair_score（与线2 同一口径）。"""
    idx = idx if idx is not None else range(len(items))
    idx = list(idx)
    n = len(idx)
    S = np.eye(n, dtype=np.float32)
    for a in range(n):
        ia = items[idx[a]]["feats"]
        for b in range(a + 1, n):
            ib = items[idx[b]]["feats"]
            best = max(T.pair_score(x, y) for x in ia for y in ib)
            S[a, b] = S[b, a] = best
    return S


def greedy_cluster(S, thr):
    """贪心代表聚类（顺序无关）。

    为什么不用完全连接层次聚类（线2 的 `cluster_complete`，O(n³)）：381 帧时要几分钟，
    而 onboarding 要对**任意长度**的录屏跑。贪心代表法是 O(n²) 矩阵上的一遍扫描，
    且天然给出"每组的代表帧"——正是出指认图需要的。

    规则：按"与现有所有代表的最大相似度"降序取，≥thr 就归入该代表，否则**自成一组的代表**。
    因此同一角色若因光照/形态差异分成多组，会**分别**出现在指认图上（让用户各报一次名，
    或都报同一个名字 —— 后者正好把两个形态都收进同一个角色的模板库）。
    """
    n = len(S)
    order = list(range(n))
    # 先挑"最典型"的当种子：与全体平均相似度最高者优先
    if n > 1:
        S0 = S.copy()
        np.fill_diagonal(S0, np.nan)
        avg = np.nanmean(S0, axis=1)
        order.sort(key=lambda i: -float(avg[i]))
    reps, assign = [], [-1] * n
    for i in order:
        best, bi = -9.0, -1
        for ri, r in enumerate(reps):
            v = float(S[i, r])
            if v > best:
                best, bi = v, ri
        if bi >= 0 and best >= thr:
            assign[i] = bi
        else:
            reps.append(i)
            assign[i] = len(reps) - 1
    groups = [[] for _ in reps]
    for i, g in enumerate(assign):
        groups[g].append(i)
    return groups, reps


def cmd_cluster(args):
    base_w = args.base_width or _base_width_of(args.team) or T.REF_W
    items = scan_team(args.team, base_w)

    # ── 选哪些帧参与聚类 ──
    # 默认 ally：左标记（青色点/星）是"我方单位卡"的客观证据 —— 实测 84 个真值帧 100% 被判成
    # ally_*；而阿哈面具框 / 敌方卡 / 空槽会被排除，用户就不用为这些组一个个填"null"。
    # ⚠️ 但左标记的覆盖率**取决于玩法**：录屏2（欢愉玩法）62% 时长是阿哈时刻
    #    （gold_aha 606/893 帧），我方卡只剩 90 帧。这不是流程缺陷，是素材特性 →
    #    覆盖偏低时**明确告警并回退全集**，让用户自己判断要不要补录长一点的战斗段。
    pool, note = items, ""
    if args.only in ("ally", "good"):
        want = ALLY_MARKERS if args.only == "ally" else GOOD_MARKERS
        sub = [it for it in items if it["marker"] in want]
        if not items:
            raise SystemExit("没有可聚类的帧")
        frac = len(sub) / float(len(items))
        if frac >= args.min_ally_frac and len(sub) >= 8:
            pool = sub
            note = "（左标记=我方单位卡，%d/%d = %.0f%%）" % (len(sub), len(items), 100 * frac)
        else:
            note = ("！我方标记帧只有 %d/%d = %.0f%%（低于 %.0f%%）→ **回退成全部帧**聚类。\n"
                    "     原因通常是这段录屏里我方单位卡占比低（阿哈时刻/特效/敌方回合占了大头）。\n"
                    "     建议：录一段**更长的普通战斗**，或看下面的分组里哪些明显是敌方/特效卡（填 null 跳过）。"
                    % (len(sub), len(items), 100 * frac, 100 * args.min_ally_frac))
            pool = items
    print("参与聚类 %d/%d 帧（only=%s）%s" % (len(pool), len(items), args.only, note))

    S = sim_matrix(pool)
    groups, reps = greedy_cluster(S, args.thr)

    rows = []
    for gi, g in enumerate(groups):
        ts = sorted(pool[k]["t"] for k in g)
        mks = {}
        for k in g:
            mk = pool[k]["marker"]
            mks[mk] = mks.get(mk, 0) + 1
        rep_k = reps[gi]
        # 组内"最不像成员"：暴露"这组其实混了两个角色"
        if len(g) > 1:
            sub = S[np.ix_(g, g)].copy()
            np.fill_diagonal(sub, np.nan)
            with np.errstate(invalid="ignore"):
                avg = np.nanmean(sub, axis=1)
            worst_k = g[int(np.nanargmin(avg))]
            worst_sim = float(np.nanmin(avg))
        else:
            worst_k, worst_sim = rep_k, -1.0
        rows.append(dict(gid=gi + 1, n=len(g), times=ts,
                         rep=pool[rep_k]["t"], worst=pool[worst_k]["t"],
                         worst_sim=round(worst_sim, 3), markers=mks,
                         is_unit=all(k.startswith("ally") for k in mks)))
    rows.sort(key=lambda r: (-r["n"], r["rep"]))
    for i, r in enumerate(rows):
        r["gid"] = i + 1

    out = os.path.join(TEAMS_DIR, "%s.clusters.json" % _safe_name(args.team))
    _ensure_teams_dir()
    with open(out, "w", encoding="utf-8") as f:
        json.dump(dict(team=args.team, thr=args.thr, only=args.only, n_frames=len(items),
                       n_pool=len(pool), clusters=rows), f, ensure_ascii=False, indent=1)
    print("聚类：阈值 %.2f，共 %d 组（%d 帧）" % (args.thr, len(rows), len(pool)))
    for r in rows[:args.show]:
        print("  组%-2d n=%-4d 例 t=%-7s 标记=%-26s 最不像成员 t=%-7s（相似度 %.2f）"
              % (r["gid"], r["n"], T.fmt_t(r["rep"]), str(r["markers"]),
                 T.fmt_t(r["worst"]), r["worst_sim"]))
    print("已写出 %s" % out)
    _touch_index_team(args.team, dict(clusters=out, cluster_thr=args.thr, cluster_only=args.only))
    return 0


# ---------------------------------------------------------------- 指认图（label）


def _font(sz):
    from PIL import ImageFont
    for p in ("C:/Windows/Fonts/msyh.ttc", "C:/Windows/Fonts/msyhbd.ttc",
              "C:/Windows/Fonts/arial.ttf"):
        if os.path.exists(p):
            try:
                return ImageFont.truetype(p, sz)
            except OSError:
                pass
    return ImageFont.load_default()


def _cell(crop, caption, scale=2.0):
    """一张裁块 → 带标题的展示格（只画文字标签，不用颜色编码传递信息）。"""
    from PIL import Image, ImageDraw
    pil = Image.fromarray(cv2.cvtColor(crop, cv2.COLOR_BGR2RGB))
    pil = pil.resize((int(pil.width * scale), int(pil.height * scale)), Image.LANCZOS)
    pad = 30
    canvas = Image.new("RGB", (pil.width, pil.height + pad), (22, 22, 22))
    canvas.paste(pil, (0, 0))
    ImageDraw.Draw(canvas).text((4, pil.height + 5), caption, font=_font(16),
                                fill=(255, 255, 255))
    return canvas


def _sheet(cells, path, title, cols=3):
    from PIL import Image, ImageDraw
    if not cells:
        return None
    cw = max(c.width for c in cells) + 8
    ch = max(c.height for c in cells) + 8
    rows = (len(cells) + cols - 1) // cols
    head = 38
    W = min(cols * cw, 1900)
    cols = max(1, W // cw)
    rows = (len(cells) + cols - 1) // cols
    canvas = Image.new("RGB", (cols * cw, head + rows * ch), (8, 8, 8))
    d = ImageDraw.Draw(canvas)
    d.text((8, 8), title, font=_font(20), fill=(255, 235, 120))
    for i, c in enumerate(cells):
        r, col = divmod(i, cols)
        canvas.paste(c, (col * cw + 4, head + r * ch + 4))
    canvas.save(path)
    return path


def _group_cells(team, r, base_w, per, scale):
    """一个组 → 若干展示格：代表帧 + 最不像成员（暴露"这组其实混了两个人"）。

    给多个成员而不是一张：同一角色会因**光照/特效/卡面缩放**看起来不同，
    只给一张代表图，用户可能把"同一个人的两种光照"当成两个人（线2 踩过，见 §1.1）。
    """
    ts = [r["rep"]]
    for t in [r["worst"]] + list(r["times"]):
        if len(ts) >= max(1, per):
            break
        if t not in ts:
            ts.append(t)
    cells = []
    for i, t in enumerate(ts):
        crop = _load_crop(team, t, base_w)
        if crop is None:
            continue
        cap = ("组%d  %s  n=%d  例t=%s" % (r["gid"], _mk_short(r["markers"]), r["n"], T.fmt_t(t))
               if i == 0 else "t=%s" % T.fmt_t(t))
        cells.append(_cell(crop, cap, scale))
    return cells


def cmd_label(args):
    cl_path = os.path.join(TEAMS_DIR, "%s.clusters.json" % _safe_name(args.team))
    if not os.path.exists(cl_path):
        raise SystemExit("还没有聚类结果：先跑 `python axis_onboard.py cluster --team %s`" % args.team)
    with open(cl_path, encoding="utf-8") as f:
        cl = json.load(f)
    rows = cl["clusters"]
    base_w = args.base_width or _base_width_of(args.team) or T.REF_W
    os.makedirs(SAMPLES_DIR, exist_ok=True)
    ans_path = _labels_path(args.team)

    # 我方单位卡组 vs 其它（敌方/特效/过渡）：后者单独放一页，别让用户为噪声分心
    unit_rows = [r for r in rows if r.get("is_unit", True)]
    other_rows = [r for r in rows if not r.get("is_unit", True)]

    # 队伍面板放**最上面**：画面上直接写着角色名，用户照着一遍读完即是答案
    # （线2 的成功关键就是这个，见 docs/录屏2欢愉队.md §1）
    cells = []
    pf = panel_full_path(args.team)
    if os.path.exists(pf):
        img = cv2.imread(pf, cv2.IMREAD_COLOR)
        if img is not None:
            h, w = img.shape[:2]
            sc = min(args.panel_scale, 1400.0 / max(1, w))
            cells.append(_cell(img, "队伍面板（画面上带角色名 ← 答案照这里念）",
                               sc))
    for r in unit_rows:
        cells += _group_cells(args.team, r, base_w, args.per_group, args.scale)
    p1 = _sheet(cells, os.path.join(SAMPLES_DIR, "%s_请指认.png" % _safe_name(args.team)),
                "请给每组填角色名：把「组N = 角色名」填进 %s（同一个人被分成多组就填同一个名字）"
                % os.path.relpath(ans_path, HERE), args.cols)
    print("指认图已写出 %s（%d 组待指认%s）"
          % (p1, len(unit_rows), "，含队伍面板" if os.path.exists(pf) else ""))

    if other_rows and not args.no_other:
        cells2 = []
        for r in other_rows[:args.max_other]:
            cells2 += _group_cells(args.team, r, base_w, 1, min(args.scale, 1.5))
        p2 = _sheet(cells2, os.path.join(SAMPLES_DIR, "%s_其余分组.png" % _safe_name(args.team)),
                    "这些组不是我方单位卡（敌方/阿哈/特效/过渡）——默认全部跳过，"
                    "只有发现里面混了你的角色时才需要填", 4)
        print("其余分组图已写出 %s（%d 组，默认跳过）" % (p2, len(other_rows)))

    # 答案模板：只列候选组，用户填名字；已存在的答案不覆盖
    lp = _labels_path(args.team)
    old = {}
    if os.path.exists(lp):
        with open(lp, encoding="utf-8") as f:
            old = json.load(f)
    if old.get("_answers"):
        print("已有答案文件 %s（保留原答案，只补新组）" % lp)
    ans = old.get("_answers") or {}
    tpl = {
        "_note": "把每组填成角色名（直接照队伍面板念）。同一个角色若被分成多组（不同形态/光照），"
                 "各填同一个名字即可 —— 两个形态都会进同一个角色的模板库。"
                 "不是角色的组留空即可（默认跳过，不会进模板库）。",
        "_team": args.team,
        "_step": cl.get("cluster_thr", cl.get("thr")),
        "_answers": {str(r["gid"]): ans.get(str(r["gid"]), "") for r in rows},
        "_clusters": {str(r["gid"]): dict(n=r["n"], rep=r["rep"], worst=r["worst"],
                                          worst_sim=r["worst_sim"], markers=r["markers"],
                                          is_unit=r.get("is_unit", True))
                      for r in rows},
    }
    with open(lp, "w", encoding="utf-8") as f:
        json.dump(tpl, f, ensure_ascii=False, indent=1)
    print("\n答案文件（只填带「我方」的那几组）：\n  %s" % lp)
    for r in unit_rows:
        print("    组%-2d（%d 帧，%s）→ ?" % (r["gid"], r["n"], _mk_short(r["markers"])))
    if other_rows:
        print("    （另有 %d 组非我方卡：%s —— 默认跳过）"
              % (len(other_rows), "、".join("组%d" % r["gid"] for r in other_rows[:12])))
    return 0


def _mk_short(mks):
    """{标记: 次数} → 简短文字（如 '我方点×12/空×3'）。"""
    name = {"ally_dot": "我方点", "ally_star": "我方星", "ally_diamond": "欢愉技卡",
            "gold_aha": "阿哈框", "empty": "空槽", "?": "未知"}
    parts = []
    for k, v in sorted(mks.items(), key=lambda kv: -kv[1]):
        parts.append("%s×%d" % (name.get(k, k), v))
    return "/".join(parts)


def _labels_path(team):
    return os.path.join(TEAMS_DIR, "%s.labels.json" % _safe_name(team))


# ---------------------------------------------------------------- 建库（并入共享库）


def cmd_build(args):
    lp = _labels_path(args.team)
    if not os.path.exists(lp):
        raise SystemExit("还没有答案文件：先跑 `python axis_onboard.py label --team %s` 并填写 %s"
                         % (args.team, lp))
    with open(lp, encoding="utf-8") as f:
        lab = json.load(f)
    answers = lab.get("_answers") or {}
    cl_path = os.path.join(TEAMS_DIR, "%s.clusters.json" % _safe_name(args.team))
    with open(cl_path, encoding="utf-8") as f:
        cl = json.load(f)
    by_gid = {str(r["gid"]): r for r in cl["clusters"]}

    base_w = args.base_width or _base_width_of(args.team) or T.REF_W
    # 组号 → 角色名（同一角色可对应多组；null/空 = 不是角色，跳过）
    char_frames, skipped, gid_of = {}, [], {}
    for gid, name in answers.items():
        name = (name or "").strip()
        r = by_gid.get(str(gid))
        if r is None:
            skipped.append("组%s（聚类文件里没有这个组号）" % gid)
            continue
        if not name or name.lower() in ("null", "none", "无", "-", "?"):
            skipped.append("组%s（%d 帧，用户标为不是角色）" % (gid, r["n"]))
            continue
        ts = list(r["times"])
        # 每组的样本上限：太多了对匹配没增益，只拖慢实时（模板越多 match 越慢）
        if len(ts) > args.max_per_char:
            step = len(ts) / float(args.max_per_char)
            ts = [ts[int(i * step)] for i in range(args.max_per_char)]
        for t in ts:
            gid_of[float(t)] = int(r["gid"])
        char_frames.setdefault(name, []).extend(ts)
    if not char_frames:
        raise SystemExit("答案里没有任何角色名 —— 请在 %s 的 _answers 里填「组号: 角色名」" % lp)

    # 逐帧做特征（缺帧就报出来，不静默丢）。
    # `order` 记录**每个模板来自哪一组哪一帧** —— 留一帧评估要靠它做到诚实：
    # 同一个"形态组"里的帧彼此高度相似，留一帧会把同组的近邻留在库里 → 分数虚高。
    # 所以评估时按**组**留（见 cmd_eval），并把这一组之外的形态留给它泛化（这才是真实场景）。
    new_banks, missing, per_char, order = {}, [], {}, {}
    for name, ts in char_frames.items():
        mats, used, ents = [], [], []
        for t in sorted(set(ts)):
            crop = _load_crop(args.team, t, base_w)
            if crop is None:
                missing.append((name, t))
                continue
            art = art_of_crop(crop, base_w)
            for z in T.ZOOMS:
                mats.append(feats_of_art(art, z))
            used.append(t)
            ents.append([name, gid_of[float(t)], float(t)])
        if mats:
            new_banks[name] = np.stack(mats)
            per_char[name] = used
            order[name] = ents
    if missing:
        print("！%d 帧缺失（已跳过，不会静默污染模板库）：%s%s"
              % (len(missing), missing[:6], " …" if len(missing) > 6 else ""))
    if not new_banks:
        raise SystemExit("没有可用样本")

    # 并入共享模板库（增量：别的队伍/角色的模板原样保留）
    #
    # ⚠️ 幂等：**本队这次登记过的角色，先剪掉"上次本队追加的那一段"再追加**。
    # 否则同一份素材跑两次 build 会把模板翻倍（分数不变但实时变慢，且污染评估）。
    # 别的队伍的另外两支队/别的角色（没有本队记录的）一律不动。
    bank_path = args.bank or T.BANK_PATH
    old_lens = bank_lengths(bank_path)
    info = load_index().get("teams", {}).get(args.team, {})
    base_lens = info.get("bank_base_lengths") or {}
    merged_all, report = merge_banks(bank_path, new_banks, trim_to=base_lens)
    np.savez_compressed(bank_path, **merged_all)
    T._BANK_CACHE.pop(bank_path, None)          # 让同进程后续调用读到新库
    merged = merged_all
    print("\n模板库已更新 %s" % bank_path)
    for name in sorted(new_banks):
        n_new = new_banks[name].shape[0] // len(T.ZOOMS)
        n_old = report["old"].get(name, 0)
        print("  %-8s 新增 %3d 帧模板%s（共 %d）"
              % (name, n_new, "，原有 %d 帧" % n_old if n_old else "（新角色）",
                 merged[name].shape[0] // len(T.ZOOMS)))
    if report.get("trimmed"):
        print("  幂等：先剪掉上次本队追加的模板 %s" % report["trimmed"])
    print("  库内角色 %d 个 / 模板 %d 帧"
          % (len(merged), sum(m.shape[0] for m in merged.values()) // len(T.ZOOMS)))

    # 登记：把"哪些角色"落成数据（这是本任务相对旧方案的核心变化——不再写死在代码里）
    _ensure_teams_dir()
    owners = load_owners()
    for name, ts in per_char.items():
        if name in lab.get("_owners", {}):
            owners[name] = lab["_owners"][name]
    if lab.get("_owners"):
        save_owners(owners)
    info = load_index().get("teams", {}).get(args.team, {})
    # `banks_base`：**本次之前**各角色的模板数 —— 下次 build 靠它剪掉本队这一段（幂等）
    new_base = dict(base_lens)
    for name in new_banks:
        new_base[name] = base_lens.get(name, 0)
    # `characters` = **本队登记的角色**（评估只认这些）；
    # 别看合并库的全部键 —— 那是全项目所有队伍的角色并集，混进评估会把口径搞乱。
    mine = sorted(set(info.get("characters") or []) | set(new_banks))
    _touch_index_team(args.team, dict(
        built_at=time.strftime("%Y-%m-%d %H:%M:%S"),
        bank=os.path.relpath(bank_path, HERE),
        labels=os.path.relpath(lp, HERE),
        characters=mine,
        bank_characters=sorted(merged),
        this_run_characters=sorted(new_banks),
        sample_frames=per_char, template_order=order,
        bank_base_lengths=new_base,
        bank_lengths=old_lens,
        skipped=skipped))
    _write_owners_if_missing()
    print("\n下一步：python axis_onboard.py eval --team %s" % args.team)
    return 0


def bank_lengths(path):
    """各角色当前的模板帧数（不含缩放态）—— 记录"本次新增从第几个模板开始"。"""
    if not os.path.exists(path):
        return {}
    with open_bank(path) as z:
        return {k: int(z[k].shape[0]) // len(T.ZOOMS) for k in z.files}


def merge_banks(bank_path, new_banks, trim_to=None):
    """把新角色的模板并入已有模板库。返回 (合并结果, 报告)。

    冲突处理：
      * 形状不一致 → 直接报错（不同特征口径的模板混在一起会静默污染，宁可停下）；
      * 同名已有模板 → **保留旧的、追加新的**（同名多模板本就是设计内的：银狼有两个形态）。

    `trim_to` = {角色: 保留帧数}：先把这些角色的模板剪到指定长度**再**追加。
    用途是让"同一份素材重跑 build"幂等 —— 剪掉上次本队追加的那一段，
    而不是把模板翻倍（翻倍不改分数但拖慢实时，还会让评估口径漂移）。
    """
    old = {}
    if os.path.exists(bank_path):
        with open_bank(bank_path) as z:
            old = {k: z[k] for k in z.files}
    nz = len(T.ZOOMS)
    report = dict(old={k: v.shape[0] // nz for k, v in old.items()},
                  conflict=[], appended=[], trimmed={})
    merged = dict(old)
    if trim_to:
        for name, keep in trim_to.items():
            if name in merged and keep is not None and keep >= 0:
                have = merged[name].shape[0] // nz
                if have > keep:
                    merged[name] = merged[name][:keep * nz]
                    report["trimmed"][name] = [have, keep]
    for name, mats in new_banks.items():
        if name in merged and merged[name].shape[0] > 0:
            if merged[name].shape[1:] != mats.shape[1:]:
                report["conflict"].append("%s：旧 %s vs 新 %s" % (name, merged[name].shape, mats.shape))
                continue
            merged[name] = np.concatenate([merged[name], mats], axis=0)
            report["appended"].append(name)
        else:
            merged[name] = mats
    if report["conflict"]:
        raise SystemExit("模板规格冲突，已放弃写库：\n  " + "\n  ".join(report["conflict"]))
    return merged, report


def open_bank(path):
    return np.load(path)


# ---------------------------------------------------------------- 自检与覆盖率


def cmd_eval(args):
    bank = load_merged_bank(args.bank or T.BANK_PATH)
    base_w = args.base_width or _base_width_of(args.team) or T.REF_W
    items = scan_team(args.team, base_w)
    if not items:
        raise SystemExit("没有可评估的帧")
    info = load_index().get("teams", {}).get(args.team, {})
    mine = list(info.get("characters") or [])
    print("模板库角色（%d）：%s" % (len(bank), "、".join(sorted(bank))))
    if mine:
        print("本次 onboarding 登记的角色：%s" % "、".join(mine))

    # ---- 覆盖率：全片有多少帧给出身份（与线2 的 22.3% 同口径对比）
    conf, tally, rej = 0, {}, {}
    for it in items:
        r = read_crop(it, bank)
        if r["unit"]:
            conf += 1
            tally[r["unit"]] = tally.get(r["unit"], 0) + 1
        else:
            rej[r["reject"]] = rej.get(r["reject"], 0) + 1
    n = len(items)
    print("\n覆盖率：%d/%d = %.1f%% 帧给出身份" % (conf, n, 100.0 * conf / n))
    for k, v in sorted(tally.items(), key=lambda kv: -kv[1]):
        print("    %-10s %4d 帧  %s" % (k, v, "（本次登记）" if k in mine else "（库里其它队伍的角色）"))
    print("  待复核原因：%s" % (rej or "无"))

    # ---- 留一帧：**两个口径都报**，因为"留一帧"在本项目里其实是两件不同的事。
    #
    #   口径① 逐帧留出（留着同组的其它帧）= 当年 98.8% 用的口径 → 用来**横向对比**，
    #          证明本流水线建出的模板库与人工流水线同级。
    #   口径② 逐组留出（该形态整组拿掉，只靠库里别的形态认它）= **泛化能力**，
    #          这才是"换个形态/换段光照还认不认得出"的真实答案。
    #
    # ⚠️ 别把①当成"识别能力"汇报：同组帧彼此相似度常 >0.99，近邻还在库里 → 分数虚高。
    # 只评本次登记的角色（合并库里还有别的队伍的角色，混进来会把口径搞乱）。
    n_zoom = len(T.ZOOMS)
    order = (info.get("template_order") or {})
    by_t = {it["t"]: it for it in items}
    if not mine:
        print("\n！注册表里没有本队角色（先跑 build）→ 按全库角色评估，结果仅供参考")
    scope = {u: m for u, m in bank.items() if u in mine} or bank

    def _holdout_frame(name, t):
        """把"这一帧自己"从库里拿掉（同组近邻仍在）→ 口径①。"""
        ents = order.get(name) or []
        k = next((i for i, e in enumerate(ents) if abs(e[2] - t) < 1e-6), None)
        if k is None:
            return None
        mats = scope[name]
        if (k + 1) * n_zoom > mats.shape[0]:
            return None
        return {u: (np.delete(m, [k * n_zoom + j for j in range(n_zoom)], axis=0)
                    if u == name else m) for u, m in scope.items()}

    per_frame, per_group, bad_g = {}, {}, []
    for name in mine:
        mats = scope.get(name)
        ents = order.get(name) or []
        if mats is None or not ents:
            continue
        n_tpl = min(mats.shape[0] // n_zoom, len(ents))
        groups = {}
        for k in range(n_tpl):
            groups.setdefault(ents[k][1], []).append((k, ents[k][2]))
        for gid, members in sorted(groups.items()):
            drop = []
            for k, _t in members:
                drop += [k * n_zoom + j for j in range(n_zoom)]
            sub = dict(scope)
            sub[name] = np.delete(mats, drop, axis=0)
            sub = {u: m for u, m in sub.items() if m.shape[0] >= n_zoom}
            for _k, t in members:
                it = by_t.get(t)
                if it is None:
                    continue
                # 口径①
                hb = _holdout_frame(name, t)
                if hb:
                    r = read_crop(it, hb)
                    per_frame.setdefault(name, [0, 0])
                    per_frame[name][1] += 1
                    per_frame[name][0] += 1 if r["unit"] == name else 0
                # 口径②
                r2 = read_crop(it, sub)
                per_group.setdefault(name, [0, 0])
                per_group[name][1] += 1
                if r2["unit"] == name:
                    per_group[name][0] += 1
                else:
                    bad_g.append("t=%s 组%s 期望=%s 实得=%s（%.2f/%.2f %s）"
                                 % (T.fmt_t(t), gid, name, r2["unit"] or "待复核",
                                    r2["score"], r2["margin"], r2["reject"] or ""))

    def _print_block(title, per, note=""):
        if not per:
            return None
        s = sum(v[0] for v in per.values())
        n = sum(v[1] for v in per.values())
        print("\n%s" % title)
        for k in sorted(per):
            print("    %-10s %2d/%-2d  %.1f%%" % (k, per[k][0], per[k][1],
                                                  100.0 * per[k][0] / per[k][1]))
        print("    合计 %d/%d = %.1f%%%s" % (s, n, 100.0 * s / n, note))
        return s / float(n)

    acc1 = _print_block("留一帧 · 口径①逐帧留出（本次登记帧，同口径横向对比）", per_frame)
    acc2 = _print_block("留一帧 · 口径②逐组留出（该形态整组拿掉，只靠别的形态认它 = 真实泛化）",
                        per_group, "  ← 这一项低是正常的：跨形态本来靠 NCC 泛化不动")
    if acc1 is not None and args.min_acc and acc1 < args.min_acc:
        print("    ！口径①低于验收线 %.0f%%（任务书要求新队伍 ≥95%%）" % (100 * args.min_acc))
    if acc2 is not None and acc2 < 0.6:
        print("    提示：口径②偏低说明该角色的**形态差异大**。若希望换形态也认得出，"
              "把该形态也在指认图里报同一个名字（多形态各给模板）即可。")

    # ---- 对外部真值标签的整体核对（最接近"当年 98.8%"的对照）
    # 用本队既有的真值文件（若有）逐帧核对：直接拿全库认，不做任何留出。
    ext = _external_truth(args.team)
    if ext:
        ok, per_ext, tot_ext = 0, {}, 0
        for t, want in sorted((k, v) for k, v in ext.items() if isinstance(k, float)):
            it = by_t.get(t)
            if it is None:
                continue
            tot_ext += 1
            r = read_crop(it, scope)
            per_ext.setdefault(want, [0, 0])
            per_ext[want][1] += 1
            if r["unit"] == want:
                ok += 1
                per_ext[want][0] += 1
        print("\n外部真值核对（%s 的 %d 帧，全库直接认、不留出）："
              % (os.path.basename(ext["__path__"]), len(ext) - 1))
        for k in sorted(per_ext):
            print("    %-10s %2d/%-2d  %.1f%%" % (k, per_ext[k][0], per_ext[k][1],
                                                  100.0 * per_ext[k][0] / per_ext[k][1]))
        if tot_ext:
            print("    合计 %d/%d = %.1f%%" % (ok, tot_ext, 100.0 * ok / tot_ext))
    bad = bad_g
    for b in bad[:args.show]:
        print("    ! %s" % b)
    if len(bad) > args.show:
        print("    …其余 %d 条省略" % (len(bad) - args.show))

    # ---- 逐帧明细（可选）
    if args.csv:
        with open(args.csv, "w", encoding="utf-8") as f:
            f.write("t,unit,owner,score,margin,marker,card_type,reject\n")
            for it in items:
                r = read_crop(it, bank)
                f.write("%s,%s,%s,%.3f,%.3f,%s,%s,%s\n"
                        % (T.fmt_t(it["t"]), r["unit"] or "", r["owner"] or "", r["score"],
                           r["margin"], r["marker"], r["card_type"], r["reject"] or ""))
        print("逐帧明细已写出 %s" % args.csv)
    return 0


def _frame_of_template(team, name, k):
    """第 k 个模板对应的原始帧号（从注册表/答案文件反查）。"""
    info = load_index().get("teams", {}).get(team, {})
    ts = (info.get("sample_frames") or {}).get(name) or []
    return ts[k] if k < len(ts) else None


# 队伍 → 该队**既有的人工真值文件**（当年手工核对出来的那份，用于横向对照）
_EXTERNAL_TRUTH = {
    "team2": "out/axis_top_labels_E2.json",
    "录屏2": "out/axis_top_labels_E2.json",
    "欢愉队": "out/axis_top_labels_E2.json",
}


def _external_truth(team):
    """读该队既有的人工真值标签 → {帧号: 角色名}（没有就返回 {}）。"""
    rel = _EXTERNAL_TRUTH.get(team)
    if not rel:
        return {}
    p = _res(rel)
    if not p or not os.path.exists(p):
        return {}
    try:
        with open(p, encoding="utf-8") as f:
            d = json.load(f)
    except (OSError, ValueError):
        return {}
    out = {}
    for k, ts in d.items():
        if str(k).startswith("_"):
            continue
        for t in ts:
            out[float(t)] = k
    out["__path__"] = p
    return out


def read_crop(item, bank, thr=THR, min_margin=MIN_MARGIN):
    """裁块 → 走与识别器**同一套**匹配/两道闸（含卡面缩放态与放大态折扣）。"""
    pen = np.array([T.ZOOM_PEN[i % len(T.ZOOMS)]
                    for i in range(max((m.shape[0] for m in bank.values()), default=0))],
                   dtype=np.float32)
    sc = {}
    for unit, mats in bank.items():
        vals = []
        for f in item["feats"]:
            ch = (mats[:, 0] * f[0]).mean(axis=(1, 2))
            gr = (mats[:, 1] * f[1]).mean(axis=(1, 2))
            co = ((mats[:, 2] * f[2]).mean(axis=(1, 2)) + (mats[:, 3] * f[3]).mean(axis=(1, 2))) / 2
            vals.append(T.W_GRAY * ch + T.W_GRAD * gr + T.W_COLOR * co - pen[:mats.shape[0]])
        v = np.max(np.stack(vals), axis=0)
        sc[unit] = (float(v.max()), float(np.sort(v)[-2]) if len(v) > 1 else -1.0)
    rank = sorted(sc.items(), key=lambda kv: -kv[1][0])
    unit, (best, _) = rank[0]
    second = rank[1][1][0] if len(rank) > 1 else -1.0
    margin = best - second
    mk = item["marker"]
    card_type = card_type_of(mk)
    # 与 `axis_actor_team2` 同口径的第四道闸：卡面糊/白屏/极暗 → 不认。
    # 来历：这三路特征都做了逐通道归一化，"低频糊"能和偏灰的模板高度相关 → 分数虚高
    # （线2 实测 t=15 一张糊卡拿到「爻光 1.51 / 间距 0.59」，会被采纳成错答案）。
    grad = float(item.get("grad") or 0.0)
    ok, reject = True, None
    if best < thr:
        ok, reject = False, "low_score"
    elif margin < min_margin:
        ok, reject = False, "low_margin"
    elif card_type not in ("unit", "elation"):
        # 阿哈面具框（头像不在这个区域）/ 敌方 / 空槽 → 不给单位名。
        # 菱形（elation）例外：带成员头像的欢愉技卡**可以**给身份（伤害算释放者本人）。
        ok, reject = False, "not_unit"
    elif grad < GRAD_MIN:
        ok, reject = False, "low_detail"
    owners = load_owners()
    return dict(unit=unit if ok else None, raw=unit,
                owner=(owners.get(unit, unit) if ok else None),
                score=round(best, 3), margin=round(margin, 3), marker=mk,
                card_type=card_type, grad=round(grad, 1),
                reject=reject,
                scores={k: round(v[0], 3) for k, v in rank})


def card_type_of(mk):
    """左标记 → 卡类型（与 `axis_actor.read_actor` / `axis_actor_team2.read_actor` 同一套判据）。"""
    if mk == "gold_aha":
        return "aha"
    if mk == "ally_diamond":
        return "elation"
    if mk.startswith("enemy"):
        return "enemy"
    if mk == "empty":
        return "empty"
    return "unit"


def load_merged_bank(path=None):
    """读共享模板库（npz）→ {角色: (N,4,48,72)}。"""
    path = path or T.BANK_PATH
    with open_bank(path) as z:
        return {k: z[k] for k in z.files}


# ---------------------------------------------------------------- 注册表


def _ensure_teams_dir():
    os.makedirs(TEAMS_DIR, exist_ok=True)


def load_index():
    if not os.path.exists(INDEX_PATH):
        return {"_note": "onboarding 注册表：队伍 → 素材/答案/角色清单", "teams": {}}
    with open(INDEX_PATH, encoding="utf-8") as f:
        return json.load(f)


def _touch_index_team(team, patch):
    _ensure_teams_dir()
    idx = load_index()
    t = idx.setdefault("teams", {}).setdefault(team, {})
    t.update({k: v for k, v in patch.items() if v is not None})
    with open(INDEX_PATH, "w", encoding="utf-8") as f:
        json.dump(idx, f, ensure_ascii=False, indent=1)


def _base_width_of(team):
    info = load_index().get("teams", {}).get(team, {})
    return info.get("base_width")


def load_owners():
    """忆灵 → 召唤者（按用户口径：就按现在这样写）。数据文件为首选，缺省用识别器内置的。"""
    if os.path.exists(OWNERS_PATH):
        try:
            with open(OWNERS_PATH, encoding="utf-8") as f:
                return json.load(f)
        except (OSError, ValueError):
            pass
    return dict(T.OWNER)


def save_owners(d):
    _ensure_teams_dir()
    with open(OWNERS_PATH, "w", encoding="utf-8") as f:
        json.dump(d, f, ensure_ascii=False, indent=1)


def _write_owners_if_missing():
    if not os.path.exists(OWNERS_PATH):
        save_owners(dict(T.OWNER))


def cmd_drop(args):
    """把一个队伍的登记项从注册表里删掉（打错队名、或重新 onboarding 时用）。

    ⚠️ **不动共享模板库**：角色一旦入库就可能被别的队伍/别的队名共用，
    悄悄删掉会让别的队失效。要连模板一起删，请显式加 --purge-templates。
    """
    idx = load_index()
    teams = idx.get("teams") or {}
    if args.team not in teams:
        raise SystemExit("注册表里没有队伍 %r；现有：%s" % (args.team, "、".join(teams) or "（空）"))
    info = teams.pop(args.team)
    with open(INDEX_PATH, "w", encoding="utf-8") as f:
        json.dump(idx, f, ensure_ascii=False, indent=1)
    print("已从注册表删除队伍 %s（角色：%s）" % (args.team, "、".join(info.get("characters") or []) or "-"))
    if not args.purge_templates:
        print("  共享模板库未改动（模板可能被别的队伍共用）。要一起删角色模板请加 --purge-templates")
        return 0
    bank_path = args.bank or T.BANK_PATH
    with open_bank(bank_path) as z:
        bank = {k: z[k] for k in z.files}
    removed = []
    for c in info.get("characters") or []:
        if c in bank:
            bank.pop(c)
            removed.append(c)
    np.savez_compressed(bank_path, **bank)
    T._BANK_CACHE.pop(bank_path, None)
    print("  已从模板库删除角色：%s（库内剩 %d 个）" % ("、".join(removed) or "-", len(bank)))
    return 0


def cmd_status(args):
    idx = load_index()
    teams = idx.get("teams") or {}
    print("注册表 %s" % INDEX_PATH)
    if not teams:
        print("  （还没有 onboarding 过的队伍）")
    bank_path = args.bank or T.BANK_PATH
    chars = []
    if os.path.exists(bank_path):
        with open_bank(bank_path) as z:
            chars = [(k, z[k].shape[0] // len(T.ZOOMS)) for k in z.files]
    print("\n共享模板库 %s：%d 个角色" % (bank_path, len(chars)))
    for k, n in sorted(chars, key=lambda kv: -kv[1]):
        print("    %-10s %3d 帧模板" % (k, n))
    if teams:
        print("\n队伍：")
        for name, info in teams.items():
            nf = info.get("frames")
            if nf is None:
                # 复用既有素材的队伍（如 team2 用 frames/axis2_L2）没走过 extract → 没有 frames 字段，
                # 就从裁块目录现数一个，别显示成 "?"。
                try:
                    nf = len(glob.glob(os.path.join(crops_dir(name), "*_top.png")))
                except OSError:
                    nf = None
            print("  · %-12s 帧=%-5s 角色=%-28s 建库=%s"
                  % (name, nf if nf is not None else "?", 
                     "、".join(info.get("characters") or []) or "-",
                     info.get("built_at", "-")))
    owners = load_owners()
    if owners:
        print("\n忆灵归属（owners.json）：%s" % "、".join("%s→%s" % kv for kv in owners.items()))
    return 0


# ---------------------------------------------------------------- CLI


def main(argv=None):
    ap = argparse.ArgumentParser(description="任意队伍/任意角色适配 —— onboarding 流水线")
    sub = ap.add_subparsers(dest="cmd", required=True)

    def add_common(p, team_required=True):
        p.add_argument("--team", required=team_required, help="队伍名（同时是文件名/目录名）")
        p.add_argument("--base-width", type=float, default=None,
                       help="该录屏的基准宽度（缺省按参考系 2876 或注册表里抽帧时记下的值）")
        p.add_argument("--bank", default=None, help="模板库路径（缺省 out/axis_top_bank_E.npz）")

    p = sub.add_parser("extract", help="录屏 → 裁出顶端卡小块")
    add_common(p)
    p.add_argument("--video", required=True)
    p.add_argument("--ffmpeg", default=None)
    p.add_argument("--times", default="")
    p.add_argument("--step", type=float, default=1.0)
    p.add_argument("--start", type=float, default=0.0)
    p.add_argument("--end", type=float, default=380.0)
    p.add_argument("--panel", action="store_true", help="额外按 --start..--end 逐帧存队伍面板小块")
    p.add_argument("--panel-time", type=float, default=0.0,
                   help="存整帧队伍面板的时刻（默认 0 = 战斗开场，那时队伍列表一定在）")
    p.set_defaults(func=cmd_extract)

    p = sub.add_parser("cluster", help="小块 → 自动分组")
    add_common(p)
    p.add_argument("--thr", type=float, default=0.80, help="归组相似度下限（线2 用 0.80）")
    p.add_argument("--only", default="ally", choices=["all", "ally", "good"],
                   help="只用某一类左标记的帧聚类（默认 ally=我方单位卡，避免敌方/阿哈卡混入）")
    p.add_argument("--min-ally-frac", type=float, default=0.05,
                   help="我方帧占比低于此值就回退成全部帧聚类（默认 0.05）")
    p.add_argument("--show", type=int, default=14)
    p.set_defaults(func=cmd_cluster)

    p = sub.add_parser("label", help="出指认图 + 答案模板")
    add_common(p)
    p.add_argument("--per-group", type=int, default=3, help="每组展示几张（默认 3）")
    p.add_argument("--cols", type=int, default=3)
    p.add_argument("--scale", type=float, default=2.0)
    p.add_argument("--panel-scale", type=float, default=0.85, help="队伍面板图的缩放（默认 0.85）")
    p.add_argument("--max-other", type=int, default=12, help="「其余分组」图最多展示几组")
    p.add_argument("--no-other", action="store_true", help="不出「其余分组」图")
    p.set_defaults(func=cmd_label)

    p = sub.add_parser("build", help="用户答案 → 模板 → 并入共享模板库")
    add_common(p)
    p.add_argument("--max-per-char", type=int, default=24,
                   help="每个角色最多取多少帧做模板（默认 24；越多越慢，收益很小）")
    p.set_defaults(func=cmd_build)

    p = sub.add_parser("eval", help="自检：覆盖率 + 留一帧准确率")
    add_common(p)
    p.add_argument("--csv", default="", help="把逐帧明细写到 CSV")
    p.add_argument("--show", type=int, default=20)
    p.add_argument("--min-acc", type=float, default=0.95,
                   help="留一帧准确率的验收线（默认 0.95，任务书 §5 要求 ≥95%%）")
    p.set_defaults(func=cmd_eval)

    p = sub.add_parser("status", help="看已注册的队伍/角色")
    add_common(p, team_required=False)
    p.set_defaults(func=cmd_status)

    p = sub.add_parser("drop", help="从注册表删掉一个队伍（打错队名/重新 onboarding）")
    add_common(p)
    p.add_argument("--purge-templates", action="store_true",
                   help="连同该队角色的模板一起从共享库删掉（默认不删，怕影响别的队伍）")
    p.set_defaults(func=cmd_drop)

    args = ap.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
