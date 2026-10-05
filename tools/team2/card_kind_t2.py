# -*- coding: utf-8 -*-
"""【T2】顶端卡"种类"判定 —— 把 `axis_actor_team2` 的 `elation` 拆成两类，并识别"敌方给我方的 buff"卡。

为什么需要（用户 2026-10-04 定案）：
  * `axis_actor_team2` 把**菱形标记（ally_diamond）**一律判成 `card_type=elation`（欢愉技）。
    实测这是**两种卡**：
      - **六边形【?】卡** → **【头号补给盲盒】**（银狼LV.999 的召唤物）→ **归银狼LV.999**；
      - **带头像的菱形卡**（如 t=205 银狼头像）→ **欢愉技** → 归头像那个成员。
  * **红兔卡**（t=137）= **敌方给我方的 buff** → 归敌方机制，**不计入我方伤害**。

判据：与 T2 模板库做 NCC（口径与 E 线一致），实测分离度很干净——
  盲盒 9 帧留一 **1.77~1.87**，非盲盒帧最高只有 **0.824**；红兔 t=137 自匹配 1.900，其余 <0.60。

用法：
  python -u tools/team2/card_kind_t2.py --build      # 建 out/t2_card_bank.npz
  python -u tools/team2/card_kind_t2.py --selftest   # 自检（9 盲盒 / t=205 欢愉技 / t=137 红兔 / 角色卡）
接口：
  from tools.team2.card_kind_t2 import read_actor_t2   # 在 E2 结果上叠加 T2 判定
"""
import os as _os
import sys as _sys
_t = _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__)))
if _os.path.isdir(_t) and _t not in _sys.path:
    _sys.path.insert(0, _t)
from tools_bootstrap import *  # noqa: E402,F401,F403

import json
import os
import sys

import numpy as np

HERE = _os.path.dirname(_os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))))
if not _os.path.isdir(_os.path.join(HERE, "out")):
    HERE = _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__)))
sys.path.insert(0, HERE)
import axis_actor as T        # noqa: E402  复用 E 线的特征/打分口径
import axis_actor_team2 as E2      # noqa: E402

BANK_PATH = _os.path.join(HERE, "out/t2_card_bank.npz")

# ── 真值帧（用户 2026-10-04 定案 + 全片模板扫描验证）──
BLINDBOX_FRAMES = [86, 87, 89, 150, 256, 257, 329, 330, 332]   # 六边形【?】= 【头号补给盲盒】
RABBIT_FRAMES = [137]                                          # 红兔 = 敌方给我方的 buff

# 判定阈值（实测留一 1.77~1.87 / 非盲盒最高 0.824 → 余量很大）
THR_BLINDBOX = 1.20
THR_RABBIT = 0.90

# 卡片种类 → 归属（None = 不计入我方伤害）
KIND_OWNER = {"blindbox": "银狼LV.999", "enemy_buff": None}
KIND_NOTE = {"blindbox": "【头号补给盲盒】= 银狼LV.999 的召唤物（顶轴有自己的卡）",
             "enemy_buff": "敌方给我方的 buff 卡 → 不计入我方伤害"}


def build_bank(out_path=None, verbose=True):
    out_path = BANK_PATH if out_path is None else out_path
    bank = {}
    for name, frames in (("blindbox", BLINDBOX_FRAMES), ("enemy_buff", RABBIT_FRAMES)):
        mats = []
        for t in frames:
            crop = E2.load_crop(float(t))
            mats.append(E2.feats_top(crop))
        bank[name] = np.stack(mats)
        bank[name + "_frames"] = np.array(frames, dtype=float)
    np.savez_compressed(out_path, **bank)
    if verbose:
        print("已写出 %s：blindbox %d 张、enemy_buff %d 张"
              % (out_path, len(BLINDBOX_FRAMES), len(RABBIT_FRAMES)))
    return bank


_CACHE = {}


def load_bank(path=None):
    """读模板库（`out/t2_card_bank.npz`）。

    ⚠️⚠️ 2026-10-05 修：**不再"文件不在就静默重建"**。
    原因（用户实机："盲盒还是没记进去"）：模板库当时**没打进 exe**，
    而这里的兜底会去 `build_bank()` → 它要读 `frames/axis2_L2/*_top.png`
    —— 那是**开发期的抽帧缓存，exe 里没有** → 抛 FileNotFoundError →
    这个异常被 `mvp/reader.read_actor` 的"别崩掉循环"兜底吞掉 →
    **盲盒整块功能静默失效**（没有任何报错，只是盲盒永远认不出、伤害不记录）。
    在**仓库里**却一直看不出来：抽帧缓存在，于是它每次都**悄悄重建**了这个库。

    ⇒ 现在：文件不在就**报错**（并给出可操作指令）。要重建请显式跑 `--build`。
    （`path=None` 而不是把 `BANK_PATH` 写成默认参数 —— 默认值是**定义时**绑定的，
    运行期改模块变量不生效，排查时会被这个假象骗到。）
    """
    path = BANK_PATH if path is None else path
    if path in _CACHE:
        return _CACHE[path]
    if not os.path.isfile(path):
        raise RuntimeError(
            "缺模板库 %s → 实时链路认不出「头号补给盲盒」，盲盒伤害不会被记录。\n"
            "  ① 重建（需要 frames/axis2_L2 抽帧缓存）："
            "python -u tools/team2/card_kind_t2.py --build\n"
            "  ② 确认它进了打包清单：hud_pack.spec 的 DATAS_REL + mvp/resource.py 的 RESOURCES"
            % path)
    z = np.load(path)
    bank = {k: z[k] for k in z.files}
    _CACHE[path] = bank
    return bank


def _score_against(mats, feat):
    return max(T.pair_score(m, feat) for m in mats)


def card_kind(crop_or_feat, bank=None, thr_blindbox=THR_BLINDBOX, thr_rabbit=THR_RABBIT,
              exclude_frame=None):
    """顶端卡小块（或已算好的特征）→ {'kind','owner','score','note'}。

    kind: `blindbox`（盲盒→银狼）/ `enemy_buff`（不计入）/ `None`（不是这两类，交回 E2）。
    `exclude_frame`：传帧号时，**不拿它自己那张当模板**（留一自检用）。
    """
    bank = bank or load_bank()
    if isinstance(crop_or_feat, np.ndarray) and crop_or_feat.ndim == 3 and crop_or_feat.shape[2] == 3:
        feat = E2.feats_top(crop_or_feat)     # 传进来的是 BGR 小块
    else:
        feat = crop_or_feat                   # 已经是特征 (4,48,72)

    def _mats(name):
        mats = bank[name]
        fr = bank.get(name + "_frames")
        if exclude_frame is None or fr is None:
            return mats
        keep = [i for i, t in enumerate(fr) if abs(float(t) - float(exclude_frame)) > 1e-6]
        return mats[keep] if keep else mats

    sb = _score_against(_mats("blindbox"), feat)
    sr = _score_against(_mats("enemy_buff"), feat)
    if sb >= thr_blindbox:
        return {"kind": "blindbox", "owner": KIND_OWNER["blindbox"], "score": float(sb),
                "note": KIND_NOTE["blindbox"]}
    if sr >= thr_rabbit:
        return {"kind": "enemy_buff", "owner": None, "score": float(sr),
                "note": KIND_NOTE["enemy_buff"]}
    return {"kind": None, "owner": None, "score": float(max(sb, sr)), "note": ""}


def read_actor_t2(src, bank_e2=None, bank_t2=None, **kw):
    """在 `axis_actor_team2.read_actor` 的结果上叠加 T2 判定。

    返回同形 dict，另加：
      `t2_kind`   blindbox / enemy_buff / None
      `t2_score`  与 T2 模板的最高分
      `card_type` 被细化为 blindbox / enemy_buff / elation / unit / …
      `owner`     盲盒 → 银狼LV.999；enemy_buff → None（不计入我方伤害）
    """
    crop = E2.load_crop(src)
    r = dict(E2.read_actor(src, bank=bank_e2, **kw))
    k = card_kind(crop, bank=bank_t2)
    r["t2_kind"], r["t2_score"] = k["kind"], k["score"]
    if k["kind"] == "blindbox":
        r["card_type"], r["owner"], r["unit"] = "blindbox", k["owner"], k["owner"]
    elif k["kind"] == "enemy_buff":
        r["card_type"], r["owner"], r["unit"] = "enemy_buff", None, None
    elif r.get("marker") == "ally_diamond" and r.get("unit"):
        # 带头像的菱形 = 欢愉技 → 归头像那个成员（用户 2026-10-04 定案）
        r["card_type"] = "elation"
    return r


def feat_top_live(bgr, offset=(0, 0), geom=None):
    """**实时**用的顶端卡特征（与模板库同口径）。

    * 整帧（回放/离线）：按建库时同一算法 —— 静态框 `TOP_ART × scale_of(宽度)`；
    * 实时抓的是**轴区域**（x60~340 那条）：用线7 的**局部几何** `geom`（已减过原点），
      没有几何时就按 `offset` 自己减。
    """
    import axis_actor as T
    if geom is not None:
        art = T.top_art(bgr, geom=geom)
    else:
        s = T.scale_of(bgr.shape) if bgr.shape[1] >= 1000 else 1.0
        x0, y0, x1, y1 = [int(round(v * s)) for v in T.TOP_ART]
        x0, x1 = max(0, x0 - offset[0]), max(0, x1 - offset[0])
        y0, y1 = max(0, y0 - offset[1]), max(0, y1 - offset[1])
        art = bgr[y0:y1, x0:x1]
    if art.size == 0:
        raise ValueError("顶端卡框落在画面外：图 %s offset %s" % (bgr.shape, offset))
    return T.feats(art)


def card_kind_live(bgr, bank=None, offset=(0, 0), geom=None):
    """实时入口：图（整帧或轴区域）→ `card_kind()` 的同形结果。"""
    try:
        feat = feat_top_live(bgr, offset=offset, geom=geom)
    except Exception as e:                       # noqa: BLE001
        return {"kind": None, "owner": None, "score": 0.0, "note": "feat-failed:%s" % e}
    return card_kind(feat, bank=bank)


def selftest():
    bank = load_bank()
    ok = True
    print("== 离线口径（小块，留一）==")
    for t in BLINDBOX_FRAMES:
        feat = E2.feats_top(E2.load_crop(float(t)))
        k = card_kind(feat, bank=bank, exclude_frame=t)
        good = k["kind"] == "blindbox"
        ok &= good
        print("  t=%-5d %-10s %.3f  %s" % (t, k["kind"], k["score"], "OK" if good else "✗"))
    print("== 实时口径（整帧 / 真·轴区域切片 + 局部几何）==")
    import axis_actor as T
    for t in BLINDBOX_FRAMES:
        full = E2.as_full(E2.load_crop(float(t)))
        k = card_kind_live(full, bank=bank)                      # ① 整帧路径
        # ② 真·轴区域：像实时那样只切 x60~340 那条，再用**局部几何**（原点减 60）
        reg = np.ascontiguousarray(full[0:1250, 60:340])
        local = {"top_art": tuple([T.TOP_ART[0] - 60, T.TOP_ART[1] + 0,
                                   T.TOP_ART[2] - 60, T.TOP_ART[3] + 0])}
        k2 = card_kind_live(reg, bank=bank, geom=local)
        good = k["kind"] == "blindbox" and k2["kind"] == "blindbox"
        ok &= good
        print("  t=%-5d 整帧:%-10s %.3f ｜ 轴区域:%-10s %.3f  %s"
              % (t, k["kind"], k["score"], k2["kind"], k2["score"], "OK" if good else "✗"))
    print("== 红兔帧（整帧路径）==")
    for t in RABBIT_FRAMES:
        full = E2.as_full(E2.load_crop(float(t)))
        k = card_kind_live(full, bank=bank)
        good = k["kind"] == "enemy_buff"
        ok &= good
        print("  t=%-5d %-10s %.3f  %s" % (t, k["kind"], k["score"], "OK" if good else "✗"))
    print("== 不该误判的帧（整帧路径）==")
    for t, why in [(205, "银狼头像+菱形=欢愉技"), (85, "火花"), (148, "爻光"), (15, "糊卡")]:
        full = E2.as_full(E2.load_crop(float(t)))
        k = card_kind_live(full, bank=bank)
        bad = k["kind"] == "blindbox"
        ok &= not bad
        print("  t=%-5d %-22s kind=%-10s %.3f %s" % (t, why, k["kind"], k["score"],
                                                     "✗ 误判" if bad else "OK"))
    print("\n自检：%s" % ("全部通过 ✓" if ok else "**有失败** ✗"))
    return 0 if ok else 1


def _cli():
    if "--build" in sys.argv:
        build_bank()
        return 0
    if "--selftest" in sys.argv:
        return selftest()
    print(__doc__)
    return 0


if __name__ == "__main__":
    sys.exit(_cli())
